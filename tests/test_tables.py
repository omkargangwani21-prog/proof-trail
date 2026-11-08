import json
from eval.tables import build


def cell(m):
    return {"mean": m, "lo": m - 0.1, "hi": min(1.0, m + 0.1)}


def make(root, name, model, classified):
    d = root / name
    d.mkdir()
    metrics = {k: {s: cell(0.5) for s in ("baseline", "cited", "verified")} for k in
               ("decision_accuracy", "unsupported_run_rate", "injection_leak_rate", "completeness")}
    metrics["decision_accuracy"]["paired_baseline_minus_verified"] = cell(-0.2)
    (d / "summary.json").write_text(json.dumps({"run": {"model": model, "cases": 2, "repeats": 1, "commit": "abcdef123456"},
        "metrics": metrics, "consistency": {"baseline": 1.0, "cited": 0.5, "verified": None},
        "cost_per_run_usd": {"baseline": 0.001, "agent": 0.002, "judge": 0.0005}, "limits": ["Synthetic data."]}))
    row = lambda failed: {s: {"failed": failed} for s in ("baseline", "cited", "verified")}
    (d / "results.jsonl").write_text(json.dumps(row(False)) + "\n" + json.dumps(row(True)) + "\n")
    if classified:
        (d / "flag-classification.json").write_text(json.dumps({"counts": {"REBUTTAL": 3}, "classified_by": "the author"}))


def test_headline_and_panel_are_separate(tmp_path):
    make(tmp_path, "test-DeepSeek-V4-Flash-0731", "deepseek-main", True)
    make(tmp_path, "test-other-model", "other-model", False)
    t = build(str(tmp_path))
    assert t.index("## Headline") < t.index("## Cross-model panel") < t.index("## Limits")
    assert "### deepseek-main" in t and "### other-model" in t
    assert "0.50 [0.40, 0.60]" in t and "-0.20 [-0.30, -0.10]" in t
    assert "REBUTTAL 3" in t and "not classified yet" in t
    assert "Runs with no usable draft: baseline 1, cited 1, verified 1 of 2." in t
    assert "- Synthetic data." in t
    assert "Paired difference is baseline minus verified" in t and "-0.20 [-0.30, -0.10]" in t


def test_empty_results_dir_still_builds(tmp_path):
    t = build(str(tmp_path))
    assert "## Limits" in t and "## Headline" not in t
