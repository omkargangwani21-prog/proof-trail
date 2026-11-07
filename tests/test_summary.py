import json
from eval.summary import summarize


def sysrow(ok, uns=False):
    return {"decision": "CONTEST" if ok else "NOT_CONTEST", "decision_ok": ok, "any_unsupported": uns, "marker_hit": False,
            "complete": True if ok else None, "flags": [{"text": "x", "why": ["w"]}] if uns else []}


def test_summary_has_the_contract_shape(tmp_path):
    rows = []
    for cid, cat, ok_b in [("a", "clean", True), ("b", "clean", True), ("c", "conflicting", False), ("d", "conflicting", False)]:
        for rep in range(2):
            rows.append({"case_id": cid, "category": cat, "variant": "", "rep": rep, "model": "m", "errors": [],
                         "baseline": sysrow(ok_b, uns=(cid == "a" and rep == 0)), "cited": sysrow(ok_b), "verified": sysrow(True),
                         "verdicts": ["VERIFIED"], "cost_usd": {"baseline": 0.001, "agent": 0.002, "judge": 0.001}})
    (tmp_path / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (tmp_path / "config.json").write_text(json.dumps({"split": "test", "model": "m", "repeats": 2, "commit": "abc", "started": "t"}))
    s = summarize(str(tmp_path))
    json.dumps(s)
    assert set(s) >= {"run", "metrics", "categories", "consistency", "cost_per_run_usd", "failures", "limits"}
    assert s["run"]["cases"] == 4 and s["run"]["repeats"] == 2
    acc = s["metrics"]["decision_accuracy"]
    assert acc["verified"]["mean"] == 1.0 and acc["baseline"]["mean"] == 0.5
    assert acc["paired_baseline_minus_verified"]["mean"] == -0.5
    assert [c["name"] for c in s["categories"]] == ["clean", "conflicting"]
    assert s["failures"] == [] and len(s["flagged_runs"]) == 1 and s["flagged_runs"][0]["system"] == "baseline"
    assert s["cost_per_run_usd"]["agent"] == 0.002
