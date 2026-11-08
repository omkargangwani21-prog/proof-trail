import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.db import connect
from core import demo_agent, drafting, ingest
from core.case_builder import build_case
from core.gateway import BudgetExceeded
from core.schemas import Claim, Draft, SourceRef
from core.submitter import EXTRA_SCHEMA
from core.verifier import verify
from app import draft_api

PID = "PP-R-TEST-00001"


class FakeClient:
    def create_order(self, value, description, reference_id):
        return {"id": "ORD1", "links": [{"rel": "payer-action", "href": "https://x"}]}

    def capture_order(self, order_id):
        return {"status": "COMPLETED", "purchase_units": [{"payments": {"captures": [
            {"id": "CAP1", "amount": {"currency_code": "USD", "value": "49.00"}}]}}]}

    def get_dispute(self, dispute_id):
        d = json.load(open("dispute_sample.json"))
        d["dispute_id"], d["status"] = dispute_id, "WAITING_FOR_SELLER_RESPONSE"
        for t in d["disputed_transactions"]:
            t["seller_transaction_id"] = "CAP1"
        d["evidences"] = [{"evidence_type": "PROOF_OF_FULFILLMENT", "source": "REQUESTED_FROM_SELLER"}]
        return d


def fake_run(conn, gw, dispute, model):
    b = build_case(conn, dispute)
    shp = next(r for r in b["records"] if r["kind"] == "shipment")
    ct = shp["content"]
    claim = Claim(claim_id="c1", text=f"The item shipped via {ct['carrier']} with tracking number {ct['tracking_number']}.",
                  type="fulfillment", confidence=1.0,
                  source_refs=[SourceRef(record_id=shp["record_id"], field="carrier", quoted_value=ct["carrier"]),
                               SourceRef(record_id=shp["record_id"], field="tracking_number", quoted_value=ct["tracking_number"])])
    draft = Draft(decision="CONTEST", rationale="shipped", claims=[claim], missing_evidence=[])
    return {"bundle": b, "draft_result": {"ok": True, "draft": draft}, "verification": verify(b, draft, judge=lambda t, c: True)}


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setenv("TRAIL_HMAC_KEY", "test-key-not-a-secret")
    c = connect(":memory:")
    c.executescript(EXTRA_SCHEMA)
    demo_agent.start_purchase(c, FakeClient(), "buy a desk lamp under 60 dollars")
    demo_agent.finish_purchase(c, FakeClient(), "ord:1")
    ingest.ingest_dispute(c, FakeClient(), PID)
    return c


def n_drafts(c):
    return c.execute("SELECT COUNT(*) FROM draft_evidence").fetchone()[0]


def test_draft_is_saved_and_audited(conn):
    r = drafting.draft_dispute(conn, PID, gw=object(), run=fake_run)
    assert r["ok"] and r["decision"] == "CONTEST" and n_drafts(conn) == 1
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='draft_saved'").fetchone()[0] == 1


def test_unknown_dispute_is_refused(conn):
    with pytest.raises(drafting.DisputeNotFound):
        drafting.draft_dispute(conn, "PP-R-NOPE-00000", gw=object(), run=fake_run)
    assert n_drafts(conn) == 0


def test_not_waiting_for_seller_is_refused(conn):
    conn.execute("UPDATE disputes SET status='UNDER_REVIEW' WHERE paypal_dispute_id=?", (PID,))
    conn.commit()
    with pytest.raises(drafting.NotDraftable):
        drafting.draft_dispute(conn, PID, gw=object(), run=fake_run)
    assert n_drafts(conn) == 0


def test_unusable_model_output_saves_nothing(conn):
    bad = lambda c, g, d, m: {"bundle": None, "draft_result": {"ok": False}, "verification": None}
    r = drafting.draft_dispute(conn, PID, gw=object(), run=bad)
    assert r["ok"] is False and n_drafts(conn) == 0


@pytest.mark.parametrize("outcome,location", [
    ({"ok": True, "draft_id": 1, "decision": "CONTEST"}, f"/disputes/{PID}?draft=ok"),
    ({"ok": False, "reason": "x"}, f"/disputes/{PID}?draft=failed"),
    (drafting.NotDraftable("x"), f"/disputes/{PID}?draft=notready"),
    (BudgetExceeded("x"), f"/disputes/{PID}?draft=budget"),
    (drafting.DisputeNotFound("x"), "/disputes?draft=notfound"),
    (RuntimeError("boom"), f"/disputes/{PID}?draft=error"),
])
def test_route_redirects(monkeypatch, outcome, location):
    def fake(pid):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    monkeypatch.setattr(draft_api, "_draft", fake)
    app = FastAPI(); app.include_router(draft_api.router)
    r = TestClient(app).post(f"/disputes/{PID}/draft", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == location


def test_route_rejects_malformed_id():
    app = FastAPI(); app.include_router(draft_api.router)
    r = TestClient(app).post("/disputes/x/draft", follow_redirects=False)
    assert r.headers["location"] == "/disputes?draft=invalid"
