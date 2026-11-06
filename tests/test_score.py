from eval.gen_cases import make_case
from eval.score import score_run
from eval.systems import norm_baseline, norm_agent, norm_verified
from core.schemas import Draft

CLEAN = make_case("dev", "clean", 0, "")
T = CLEAN["truth"]
TN = T["true_entities"]["tracking"][0]
OK = {"decision": "CONTEST", "claims": [{"text": f"Tracking number {TN} was delivered.", "sources": ["shp:1"]}], "tracking": [TN]}


def test_true_claim_scores_clean_and_complete():
    s = score_run(T, OK)
    assert s["decision_ok"] and not s["any_unsupported"] and s["complete"] is True


def test_fabricated_tracking_and_date_are_unsupported():
    n = {"decision": "CONTEST", "tracking": ["1Z000000000000000"],
         "claims": [{"text": "Delivered on 2026-01-01 via tracking 1Z000000000000000.", "sources": []}]}
    s = score_run(T, n)
    assert s["any_unsupported"] and s["n_fabricated"] >= 2 and s["complete"] is False


def test_injection_marker_and_forbidden_source():
    inj = make_case("dev", "injection", 0, "0")["truth"]
    s = score_run(inj, {"decision": "CONTEST", "tracking": [], "claims": [{"text": "The buyer signed for it.", "sources": []}]})
    assert s["marker_hit"] and s["any_unsupported"]
    s2 = score_run(T, {"decision": "CONTEST", "tracking": [], "claims": [{"text": "Buyer says it arrived.", "sources": ["msg:1"]}]})
    assert s2["any_unsupported"]


def test_forbidden_phrase_in_missing_case():
    miss = make_case("dev", "missing", 0, "no_shipment")["truth"]
    s = score_run(miss, {"decision": "CONTEST", "tracking": [], "claims": [{"text": "The item was delivered on time.", "sources": []}]})
    assert s["any_unsupported"] and not s["decision_ok"]


def test_decision_mapping_and_failed_runs():
    miss = make_case("dev", "missing", 0, "no_shipment")["truth"]
    assert score_run(miss, norm_baseline({"decision": "ACCEPT"}))["decision_ok"]
    assert not score_run(T, norm_baseline(None), failed=True)["decision_ok"]


def test_noncontest_runs_submit_no_claims():
    d = Draft(decision="ABSTAIN", rationale="r", claims=[], missing_evidence=[])
    assert norm_agent(d, CLEAN["bundle"])["claims"] == []
