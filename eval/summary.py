"""Machine-readable summary of one eval run, for the Eval screen. Reporting only: no scoring logic here."""
import collections, json, sys
from eval.report import SYSTEMS, boot, load, per_case

KEYS = {"decision_accuracy": "decision_ok", "unsupported_run_rate": "any_unsupported",
        "injection_leak_rate": "marker_hit", "completeness": "complete"}
LIMITS = [
    "All cases are synthetic, generated from templates by the same author as the system. Results may not transfer to real disputes.",
    "Small sample (cases, not runs, are the unit of analysis). Intervals are wide; no claim goes beyond what the intervals show.",
    "The scorer is code-based. It counts any mention of attacker text or forbidden phrases in the payload, including rebuttals; flagged items are listed so they can be read.",
    "Cited and Verified share the same drafts, so their difference is attributable to the verifier alone. Baseline uses a different prompt.",
    "Judge audit: 60 hand-built pairs per judge model, same author, obvious cases only.",
    "Prompts, scorer and test cases were frozen before this single test run. Earlier dev-set results informed changes that are logged in docs/DECISIONS.md.",
]


def ci(vals, seed=0):
    m, lo, hi = boot(vals, seed)
    return {"mean": round(m, 4), "lo": round(lo, 4), "hi": round(hi, 4)}


def summarize(path):
    rows, by = load(path)
    cfg = json.load(open(path + "/config.json"))
    metrics = {}
    for name, key in KEYS.items():
        m = {s: ci(list(per_case(by, s, key).values())) for s in SYSTEMS}
        b, v = per_case(by, "baseline", key), per_case(by, "verified", key)
        d = [b[c] - v[c] for c in b if c in v]
        if d:
            m["paired_baseline_minus_verified"] = ci(d, 1)
        metrics[name] = m
    cats = []
    for c in sorted({r["category"] for r in rows}):
        sub = {cid: reps for cid, reps in by.items() if reps[0]["category"] == c}
        cell = {"name": c, "n": len(sub)}
        for s in SYSTEMS:
            a, u = per_case(sub, s, "decision_ok"), per_case(sub, s, "any_unsupported")
            cell[s] = {"decision_ok": round(sum(a.values()) / len(a), 4),
                       "any_unsupported": round(sum(u.values()) / len(u), 4)}
        cats.append(cell)
    consistency = {}
    for s in SYSTEMS:
        same = [len({r[s]["decision"] for r in reps}) == 1 for reps in by.values() if len(reps) > 1]
        consistency[s] = round(sum(same) / len(same), 4) if same else None
    tot = collections.Counter()
    for r in rows:
        for role, c in r["cost_usd"].items():
            tot[role] += c
    failures, flagged = [], []
    for r in rows:
        v = r["verified"]
        if v["any_unsupported"] or not v["decision_ok"] or v["marker_hit"]:
            failures.append({"case_id": r["case_id"], "rep": r["rep"], "system": "verified",
                             "decision": v["decision"], "verdicts": r.get("verdicts")})
        for s in SYSTEMS:
            for fl in r[s]["flags"]:
                flagged.append({"case_id": r["case_id"], "rep": r["rep"], "system": s, "why": fl["why"], "text": fl["text"]})
    return {"run": {"split": cfg["split"], "model": cfg["model"], "cases": len(by), "repeats": cfg["repeats"],
                    "commit": cfg["commit"], "started": cfg.get("started")},
            "metrics": metrics, "categories": cats, "consistency": consistency,
            "cost_per_run_usd": {k: round(tot[k] / len(rows), 6) for k in ("baseline", "agent", "judge")},
            "failures": failures, "flagged_runs": flagged, "limits": LIMITS}


if __name__ == "__main__":
    out = summarize(sys.argv[1])
    json.dump(out, open(sys.argv[1] + "/summary.json", "w"), indent=2)
    print("wrote", sys.argv[1] + "/summary.json")
