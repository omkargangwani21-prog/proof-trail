import json
from core.db import connect
from core import submitter


def test_saved_draft_keeps_requested_not_provided(tmp_path, monkeypatch):
    monkeypatch.setattr(submitter, "build_payload", lambda b, v: [])
    conn = connect(str(tmp_path / "t.db"))
    bundle = {"case_id": "c_1", "dispute": {"content": {"paypal_dispute_id": "PP-1"}}}
    v = {"decision": "CONTEST", "recommendation": "x", "missing_evidence": [], "l3_ran": True,
         "requested_not_provided": ["PROOF_OF_REFUND", "OTHER"], "consistency_issues": [], "claims": []}
    did = submitter.save_draft(conn, bundle, v)
    ver = json.loads(conn.execute("select verification_json from draft_evidence where id=?", (did,)).fetchone()[0])
    assert ver["requested_not_provided"] == ["PROOF_OF_REFUND", "OTHER"]
