import argparse, json, os, sys, time, datetime, subprocess, threading, concurrent.futures as cf
from core.db import connect
from core.gateway import Gateway, BudgetExceeded, PRICES
from core.agent import draft, SYSTEM
from core.judge import make_judge, judge_model_for
from core.verifier import verify
from eval.systems import call_baseline, norm_baseline, norm_agent, norm_verified, render_plain
from eval.score import score_run
from core.agent import render_bundle

FAILED = {"decision": None, "claims": [], "tracking": []}


def load(split):
    return [json.loads(l) for l in open(f"eval/cases/{split}.jsonl")]


def run_one(case, rep, model):
    conn = connect()
    gw = Gateway(conn)
    rid = f"{model}|{case['id']}|{rep}"
    b, truth = case["bundle"], case["truth"]
    rec = {"case_id": case["id"], "category": case["category"], "variant": case["variant"], "rep": rep,
           "model": model, "errors": []}
    t0 = time.time()
    try:
        bl = call_baseline(gw, b, model, rid + "|bl")
        rec["baseline"] = score_run(truth, norm_baseline(bl["parsed"]), failed=not bl["ok"])
    except BudgetExceeded:
        raise
    except Exception as e:
        rec["errors"].append("baseline:" + type(e).__name__ + ":" + str(e)[:120])
        rec["baseline"] = score_run(truth, FAILED, failed=True)
    try:
        dr = draft(gw, b, model, rid + "|ag", cache=False)
        if dr["ok"]:
            rec["cited"] = score_run(truth, norm_agent(dr["draft"], b))
            ver = verify(b, dr["draft"], make_judge(gw, judge_model_for(model), rid + "|jd"))
            rec["verified"] = score_run(truth, norm_verified(b, ver))
            rec["verdicts"] = [x["verdict"] for x in ver["claims"]]
        else:
            rec["cited"] = rec["verified"] = score_run(truth, FAILED, failed=True)
    except BudgetExceeded:
        raise
    except Exception as e:
        rec["errors"].append("agent:" + type(e).__name__ + ":" + str(e)[:120])
        rec["cited"] = rec["verified"] = score_run(truth, FAILED, failed=True)
    rec["latency_s"] = round(time.time() - t0, 1)
    rec["cost_usd"] = {r["role"]: round(r["c"], 6) for r in conn.execute(
        "SELECT role, SUM(cost_usd) c FROM llm_calls WHERE run_id LIKE ? GROUP BY role", (rid + "|%",))}
    return rec


def estimate(cases, repeats, model):
    pin, pout = PRICES[model]
    jin, jout = PRICES[judge_model_for(model)]
    total = 0.0
    for c in cases:
        tin = (len(SYSTEM) + len(render_bundle(c["bundle"]))) / 3.5
        base = tin * pin + 1500 * pout
        agent = tin * pin + 2500 * pout
        judge = 2 * (700 * jin + 800 * jout)
        total += (base + agent + judge) / 1e6
    return total * repeats


def summarize(rows):
    print(f"{'system':10s} {'runs':>5s} {'decision_ok':>12s} {'any_unsupported':>16s} {'marker_hit':>11s} {'complete':>9s} {'failed':>7s}")
    for s in ("baseline", "cited", "verified"):
        r = [x[s] for x in rows]
        comp = [x["complete"] for x in r if x["complete"] is not None]
        m = lambda k: sum(1 for x in r if x[k]) / len(r)
        print(f"{s:10s} {len(r):5d} {m('decision_ok'):12.2f} {m('any_unsupported'):16.2f} {m('marker_hit'):11.2f} "
              f"{(sum(comp) / len(comp) if comp else float('nan')):9.2f} {m('failed'):7.2f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test"])
    ap.add_argument("--model", default="deepseek-ai/DeepSeek-V4-Flash-0731")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--go", action="store_true", help="actually call the models and spend credits")
    a = ap.parse_args()
    cases = load(a.split)
    if a.limit:
        cases = cases[::max(1, len(cases) // a.limit)][:a.limit]
    conn = connect()
    gw = Gateway(conn)
    est = estimate(cases, a.repeats, a.model)
    print(f"{len(cases)} cases x {a.repeats} repeats | model {a.model} | estimated cost ~${est:.3f} "
          f"| spent so far ${gw.spent():.3f} of ${gw.hard:.0f} cap")
    if not a.go:
        print("DRY RUN. Add --go to spend credits.")
        sys.exit(0)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = f"eval/out/{a.split}-{a.model.split('/')[-1]}-{stamp}"
    os.makedirs(out, exist_ok=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    json.dump({"split": a.split, "model": a.model, "repeats": a.repeats, "commit": commit,
               "manifest": json.load(open("eval/cases/MANIFEST.json"))["sha256"], "max_tokens": 6000,
               "started": stamp}, open(out + "/config.json", "w"), indent=2)
    rows, lock = [], threading.Lock()
    tasks = [(c, r) for c in cases for r in range(a.repeats)]
    stop = False
    with cf.ThreadPoolExecutor(a.workers) as ex, open(out + "/results.jsonl", "a") as f:
        futs = [ex.submit(run_one, c, r, a.model) for c, r in tasks]
        for fu in cf.as_completed(futs):
            try:
                rec = fu.result()
            except BudgetExceeded as e:
                print("BUDGET STOP:", e)
                for x in futs:
                    x.cancel()
                break
            with lock:
                rows.append(rec)
                f.write(json.dumps(rec) + "\n")
                f.flush()
            print(f"  done {len(rows)}/{len(tasks)}  {rec['case_id']} rep{rec['rep']}  ${sum(rec['cost_usd'].values()):.4f}")
    if rows:
        summarize(rows)
    print("results:", out, "| spent total: $%.4f" % Gateway(connect()).spent())
