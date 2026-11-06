import json, glob, sys, random, collections

SYSTEMS = ("baseline", "cited", "verified")
METRICS = [("decision_ok", "decision accuracy (higher better)"),
           ("any_unsupported", "runs with >=1 unsupported claim (lower better)"),
           ("marker_hit", "injection leaked into payload (lower better)"),
           ("complete", "evidence completeness on contest cases (higher better)")]
B = 10000


def load(path):
    rows = [json.loads(l) for l in open(path + "/results.jsonl")]
    by = collections.defaultdict(list)
    for r in rows:
        by[r["case_id"]].append(r)
    return rows, by


def per_case(by, system, key):
    out = {}
    for cid, reps in by.items():
        vals = [float(r[system][key]) for r in reps if r[system][key] is not None]
        if vals:
            out[cid] = sum(vals) / len(vals)
    return out


def boot(vals, seed=0):
    rng, n = random.Random(seed), len(vals)
    means = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return sum(vals) / n, means[int(0.025 * B)], means[int(0.975 * B)]


def main(path):
    rows, by = load(path)
    cfg = json.load(open(path + "/config.json"))
    print(f"RUN {path}\nmodel {cfg['model']} | {len(by)} cases | {len(rows)} runs | repeats {cfg['repeats']} | commit {cfg['commit'][:8]}")
    print("SYNTHETIC DATA. Case-level cluster bootstrap, 95% interval, 10,000 resamples.\n")
    report = {"model": cfg["model"], "cases": len(by), "runs": len(rows), "metrics": {}}
    for key, label in METRICS:
        print(f"{label}")
        for s in SYSTEMS:
            m, lo, hi = boot(list(per_case(by, s, key).values()))
            report["metrics"].setdefault(key, {})[s] = [m, lo, hi]
            print(f"   {s:9s} {m:5.2f}  [{lo:.2f}, {hi:.2f}]")
        b, v = per_case(by, "baseline", key), per_case(by, "verified", key)
        d = [b[c] - v[c] for c in b if c in v]
        if d:
            m, lo, hi = boot(d, 1)
            report["metrics"][key]["paired_baseline_minus_verified"] = [m, lo, hi]
            print(f"   paired difference (baseline - verified): {m:+.2f}  [{lo:+.2f}, {hi:+.2f}]  over {len(d)} cases")
        print()
    print("BY CATEGORY (case means): decision_ok / any_unsupported")
    cats = sorted({r["category"] for r in rows})
    for c in cats:
        sub = {cid: reps for cid, reps in by.items() if reps[0]["category"] == c}
        cell = []
        for s in SYSTEMS:
            a = per_case(sub, s, "decision_ok")
            u = per_case(sub, s, "any_unsupported")
            cell.append(f"{s[:4]} {sum(a.values()) / len(a):.2f}/{sum(u.values()) / len(u):.2f}")
        print(f"   {c:12s} n={len(sub):2d}  " + "   ".join(cell))
    print("\nCONSISTENCY across repeats (same decision on every repeat):")
    for s in SYSTEMS:
        same = [len({r[s]["decision"] for r in reps}) == 1 for reps in by.values() if len(reps) > 1]
        if same:
            print(f"   {s:9s} {sum(same) / len(same):.2f} of {len(same)} cases")
    print("\nCOST per run (USD):")
    tot = collections.Counter()
    for r in rows:
        for role, c in r["cost_usd"].items():
            tot[role] += c
    for role in ("baseline", "agent", "judge"):
        print(f"   {role:9s} ${tot[role] / len(rows):.4f}")
    print("\nVERIFIED-SYSTEM FAILURES (we publish these):")
    n = 0
    for r in rows:
        v = r["verified"]
        if v["any_unsupported"] or not v["decision_ok"] or v["marker_hit"]:
            n += 1
            print(f"   {r['case_id']} rep{r['rep']} decision={v['decision']} ok={v['decision_ok']} verdicts={r.get('verdicts')}")
            for fl in v["flags"]:
                print(f"       flagged: {fl['text'][:140]}  why={fl['why']}")
    if not n:
        print("   none")
    json.dump(report, open(path + "/report.json", "w"), indent=2)


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob("eval/out/dev-*"))[-1]
    main(d)
