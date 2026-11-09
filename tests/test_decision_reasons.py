import json
from types import SimpleNamespace as NS
from core.db import connect
from core import submitter, drafting
from core.submitter import decision_reasons


def test_reasons_for_each_rule():
    assert decision_reasons({"decision": "CONTEST"}) == []
    assert decision_reasons({"decision": "ABSTAIN", "consistency_issues": ["x"], "drafter_decision": "CONTEST"}) == ["consistency"]
    assert decision_reasons({"decision": "ABSTAIN", "missing_evidence": ["PROOF_OF_FULFILLMENT"],
                             "drafter_decision": "ABSTAIN"}) == ["missing_evidence", "model_abstained"]
    assert decision_reasons({"decision": "ABSTAIN", "drafter_decision": "ABSTAIN"}) == ["model_abstained"]
    assert decision_reasons({"decision": "ABSTAIN", "drafter_decision": "ACCEPT"}) == ["model_recommended_accept"]
    assert decision_reasons({"decision": "ABSTAIN"}) == []


def test_saved_draft_carries_reasons_and_rationale(tmp_path, monkeypatch):
    monkeypatch.setattr(submitter, "build_payload", lambda b, v: None)
    conn = connect(str(tmp_path / "t.db"))
    bundle = {"case_id": "c_1", "dispute": {"content": {"paypal_dispute_id": "PP-1"}}}
    v = {"decision": "ABSTAIN", "recommendation": "x", "missing_evidence": [], "l3_ran": True, "claims": [],
         "consistency_issues": [], "requested_not_provided": [], "drafter_decision": "ABSTAIN", "rationale": "hedged"}
    did = submitter.save_draft(conn, bundle, v)
    ver = json.loads(conn.execute("select verification_json from draft_evidence where id=?", (did,)).fetchone()[0])
    assert ver["decision_reasons"] == ["model_abstained"] and ver["rationale"] == "hedged" and ver["drafter_decision"] == "ABSTAIN"


def test_draft_dispute_passes_the_drafters_decision_and_rationale(tmp_path, monkeypatch):
    saved = {}
    monkeypatch.setattr(drafting, "save_draft", lambda conn, b, v: saved.update(v) or 3)
    conn = connect(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO disputes(paypal_dispute_id,reason,status,stage,amount_minor,currency,raw_json,origin)"
                 " VALUES('PP-1','X','WAITING_FOR_SELLER_RESPONSE','CHARGEBACK',100,'USD',?,'sandbox')", (json.dumps({"dispute_id": "PP-1"}),))
    conn.commit()

    def run(conn, gw, d, model, cache_salt=""):
        return {"draft_result": {"ok": True, "draft": NS(decision="ABSTAIN", rationale="not sure")},
                "verification": {"decision": "ABSTAIN"}, "bundle": {}}

    assert drafting.draft_dispute(conn, "PP-1", gw=object(), run=run)["draft_id"] == 3
    assert saved["drafter_decision"] == "ABSTAIN" and saved["rationale"] == "not sure"
