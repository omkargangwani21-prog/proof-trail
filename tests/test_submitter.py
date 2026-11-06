import json, sqlite3, pytest
from core.db import connect
from core.seed import seed
from core.case_builder import build_case
from core.schemas import Draft
from core.verifier import verify
from core.submitter import save_draft, approve, submit, NotApproved, NotSubmittable, audit

D = json.load(open("dispute_sample.json"))


class FakeClient:
    def __init__(self):
        self.calls = []

    def provide_evidence(self, dispute_id, evidences, dry_run=True):
        self.calls.append((dispute_id, dry_run))
        return {"dry_run": dry_run, "dispute_id": dispute_id, "payload": {"evidences": evidences}}


def make(good=True):
    conn = connect(":memory:")
    seed(conn, D["disputed_transactions"][0]["seller_transaction_id"], "O")
    b = build_case(conn, D)
    claims = []
    if good:
        claims = [{"claim_id": "c1", "type": "fulfillment", "confidence": 0.9,
                   "text": "UPS delivered the order on 2026-11-06, status DELIVERED.",
                   "source_refs": [{"record_id": "shp:1", "field": "carrier", "quoted_value": "UPS"},
                                   {"record_id": "shp:1", "field": "delivered_at", "quoted_value": "2026-11-06T03:15:00Z"},
                                   {"record_id": "shp:1", "field": "delivery_status", "quoted_value": "DELIVERED"}]}]
    v = verify(b, Draft(decision="CONTEST", rationale="r", claims=claims, missing_evidence=[]), lambda t, r: True)
    return conn, save_draft(conn, b, v)


def test_submit_blocked_without_approval():
    conn, did = make()
    with pytest.raises(NotApproved):
        submit(conn, FakeClient(), did)


def test_approved_dry_run_passes_payload_with_tracking():
    conn, did = make()
    approve(conn, did, "op")
    c = FakeClient()
    out = submit(conn, c, did, dry_run=True)
    ev = out["payload"]["evidences"][0]
    assert c.calls == [("PP-R-GEH-10196749", True)]
    assert ev["evidence_type"] == "PROOF_OF_FULFILLMENT"
    assert ev["evidence_info"]["tracking_info"] == [{"carrier_name": "UPS", "tracking_number": "1Z999AA10123456784"}]


def test_changing_payload_after_approval_invalidates_it():
    conn, did = make()
    approve(conn, did, "op")
    conn.execute("UPDATE draft_evidence SET payload_json=? WHERE id=?", (json.dumps([{"evidence_type": "X"}]), did))
    with pytest.raises(NotApproved):
        submit(conn, FakeClient(), did)


def test_abstain_draft_cannot_be_submitted():
    conn, did = make(good=False)
    with pytest.raises(NotSubmittable):
        approve(conn, did, "op")


def test_audit_log_is_append_only():
    conn, did = make()
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE audit_log SET actor='x'")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM audit_log")
