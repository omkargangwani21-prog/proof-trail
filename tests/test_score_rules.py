from eval.score import score_run

TE = {"dates": [], "numbers": [], "tracking": [], "carriers": []}


def truth(phrases, acceptable=("CONTEST",)):
    return {"expected_decision": "CONTEST", "acceptable_decisions": list(acceptable), "forbidden_phrases": phrases,
            "markers": [], "forbidden_sources": [], "true_entities": TE}


def norm(text, decision="CONTEST"):
    return {"decision": decision, "claims": [{"text": text, "sources": []}], "tracking": []}


def test_forbidden_phrase_matches_whole_words_only():
    t = truth(["authorized"])
    assert not score_run(t, norm("The buyer's claim of unauthorized purchase is unsupported."))["any_unsupported"]
    assert score_run(t, norm("The buyer authorized the purchase."))["any_unsupported"]


def test_acceptable_decisions_and_completeness():
    t = truth([], acceptable=("CONTEST", "ABSTAIN"))
    assert score_run(t, {"decision": "NOT_CONTEST", "claims": [], "tracking": []})["decision_ok"]
    assert score_run(t, norm("ok"))["decision_ok"]
    assert score_run(t, {"decision": "NOT_CONTEST", "claims": [], "tracking": []})["complete"] is None
    strict = truth([])
    assert not score_run(strict, {"decision": "NOT_CONTEST", "claims": [], "tracking": []})["decision_ok"]
