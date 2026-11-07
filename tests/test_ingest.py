import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.db import connect
from core import ingest
from core.paypal_client import PayPalError

SAMPLE = json.load(open("dispute_sample.json"))
PID = SAMPLE["dispute_id"]


def variant(status="WAITING_FOR_SELLER_RESPONSE", pid=None):
    d = json.loads(json.dumps(SAMPLE))
    d["status"] = status
    if pid:
        d["dispute_id"] = pid
    return d


class FakeClient:
    def __init__(self, disputes=(), listed=(), verify=True, verify_error=False):
        self.disputes = {d["dispute_id"]: d for d in disputes}
        self.listed, self.verify, self.verify_error, self.calls = list(listed), verify, verify_error, []

    def get_dispute(self, pid):
        self.calls.append(pid)
        if pid not in self.disputes:
            raise PayPalError(404, "not found")
        return self.disputes[pid]

    def list_disputes(self, **kw):
        return {"items": [{"dispute_id": p} for p in self.listed]}

    def verify_webhook_signature(self, headers, event, webhook_id):
        if self.verify_error:
            raise PayPalError(401, "missing scope")
        return self.verify


def row(conn, pid=PID):
    return conn.execute("SELECT * FROM disputes WHERE paypal_dispute_id=?", (pid,)).fetchone()


def test_ingest_stores_dispute():
    c = connect(":memory:")
    r = ingest.ingest_dispute(c, FakeClient([variant()]), PID)
    assert r["dispute_id"] == PID and row(c)["status"] == "WAITING_FOR_SELLER_RESPONSE"


def test_refresh_updates_a_stale_status():
    c = connect(":memory:")
    ingest.ingest_dispute(c, FakeClient([variant()]), PID)
    done, errors = ingest.refresh_known(c, FakeClient([variant("UNDER_REVIEW")]))
    assert not errors and row(c)["status"] == "UNDER_REVIEW"


def test_poll_finds_new_disputes_and_survives_errors():
    c = connect(":memory:")
    fc = FakeClient([variant(pid="PP-R-NEW-0001")], listed=["PP-R-NEW-0001", "PP-R-MISSING-1"])
    res = ingest.poll_once(c, fc)
    assert res["new"] == ["PP-R-NEW-0001"] and len(res["errors"]) == 1 and res["listed"] == 2
    assert row(c, "PP-R-NEW-0001") is not None


EVENT = {"id": "WH-1", "event_type": "CUSTOMER.DISPUTE.CREATED", "resource": {"dispute_id": PID}}
RAW = json.dumps(EVENT).encode()


def test_webhook_rejects_bad_signature_and_stores_nothing():
    c = connect(":memory:")
    code, _ = ingest.handle_webhook(c, FakeClient([variant()], verify=False), {}, RAW, "WID")
    assert code == 401 and row(c) is None


def test_webhook_ingests_and_ignores_duplicates():
    c = connect(":memory:")
    fc = FakeClient([variant()])
    assert ingest.handle_webhook(c, fc, {}, RAW, "WID") == (200, {"status": "ingested", "dispute_id": PID})
    assert ingest.handle_webhook(c, fc, {}, RAW, "WID") == (200, {"status": "duplicate"})
    assert fc.calls == [PID]


def test_webhook_fetch_failure_is_retryable():
    c = connect(":memory:")
    with pytest.raises(PayPalError):
        ingest.handle_webhook(c, FakeClient(), {}, RAW, "WID")
    assert ingest.handle_webhook(c, FakeClient([variant()]), {}, RAW, "WID")[0] == 200


def test_webhook_other_events_bad_bodies_and_verify_outage():
    c = connect(":memory:")
    other = json.dumps({"id": "WH-2", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {}}).encode()
    assert ingest.handle_webhook(c, FakeClient(), {}, other, "WID")[1]["status"] == "ignored"
    assert ingest.handle_webhook(c, FakeClient(), {}, b"not json", "WID")[0] == 400
    assert ingest.handle_webhook(c, FakeClient(verify_error=True), {}, RAW, "WID")[0] == 503


def make_app(monkeypatch, tmp_path, client):
    monkeypatch.setenv("PT_DB", str(tmp_path / "t.db"))
    import app.ingest_api as api
    monkeypatch.setattr(api, "make_client", lambda: client)
    a = FastAPI()
    a.include_router(api.router)
    return TestClient(a)


def test_fetch_route_redirects_and_stores(monkeypatch, tmp_path):
    c = make_app(monkeypatch, tmp_path, FakeClient([variant()]))
    r = c.post("/ingest/fetch", data={"dispute_id": PID}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/disputes/{PID}?fetch=ok"
    assert row(connect(str(tmp_path / "t.db"))) is not None
    assert c.post("/ingest/fetch", data={"dispute_id": "no way!"}, follow_redirects=False).headers["location"] == "/disputes?fetch=invalid"
    assert c.post("/ingest/fetch", data={"dispute_id": "PP-R-NONE-1"}, follow_redirects=False).headers["location"] == "/disputes?fetch=notfound"


def test_webhook_route(monkeypatch, tmp_path):
    monkeypatch.delenv("PAYPAL_WEBHOOK_ID", raising=False)
    c = make_app(monkeypatch, tmp_path, FakeClient([variant()]))
    assert c.post("/webhooks/paypal", content=RAW).status_code == 503
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WID")
    assert c.post("/webhooks/paypal", content=RAW).json()["status"] == "ingested"
    c2 = make_app(monkeypatch, tmp_path, FakeClient([variant()], verify=False))
    assert c2.post("/webhooks/paypal", content=RAW).status_code == 401
