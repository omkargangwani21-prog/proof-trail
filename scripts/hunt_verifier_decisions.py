import json, collections, concurrent.futures as cf
from dotenv import load_dotenv; load_dotenv(".env")
from core.db import connect
from core.gateway import Gateway, BudgetExceeded
from core.agent import draft
from core.judge import make_judge, judge_model_for
from core.verifier import verify

MODEL, REPS = "deepseek-ai/DeepSeek-V4.1-Flash", 5
cases = [json.loads(l) for l in open("eval/cases/dev.jsonl")]

def one(case, rep):
    conn = connect(); gw = Gateway(conn)
    rid = f"hunt|{case['id']}|{rep}"
    dr = draft(gw, case["bundle"], MODEL, rid + "|ag", cache=False)
    base = {"case": case["id"], "category": case["category"], "expected": case["truth"]["expected_decision"], "rep": rep}
    if not dr["ok"]:
        return {**base, "draft_ok": False}
    d = dr["draft"]
    ver = verify(case["bundle"], d, make_judge(gw, judge_model_for(MODEL), rid + "|jd"))
    return {**base, "draft_ok": True, "draft_decision": d.decision, "ver_decision": ver["decision"],
            "verdicts": [x["verdict"] for x in ver["claims"]], "consistency": ver.get("consistency_issues", []),
            "missing": ver.get("missing_evidence", [])}

rows = []
with cf.ThreadPoolExecutor(6) as ex:
    futs = [ex.submit(one, c, r) for c in cases for r in range(REPS)]
    for f in cf.as_completed(futs):
        try:
            rows.append(f.result())
        except BudgetExceeded as e:
            print("BUDGET STOP", e); break
        except Exception as e:
            print("error", type(e).__name__, str(e)[:100])
json.dump(rows, open("/tmp/hunt.json", "w"))
ok = [r for r in rows if r["draft_ok"]]
print(f"runs {len(rows)}, draft failures {len(rows) - len(ok)}")
print("(draft decision, verifier decision):", dict(collections.Counter((r["draft_decision"], r["ver_decision"]) for r in ok)))
pat = [r for r in ok if r["ver_decision"] != "CONTEST" and r["verdicts"] and all(v == "VERIFIED" for v in r["verdicts"])]
print(f"\nPATTERN: verifier did not CONTEST although every claim was VERIFIED: {len(pat)} runs")
for k, v in collections.Counter((r["draft_decision"], bool(r["consistency"]), tuple(r["missing"])) for r in pat).items():
    print("  (draft decision, has consistency issue, missing evidence) =", k, "x", v)
for r in pat[:6]:
    print("  ", r["case"], "rep", r["rep"], "| draft:", r["draft_decision"], "| consistency:", str(r["consistency"])[:220], "| missing:", r["missing"])
miss = [r for r in ok if r["expected"] == "CONTEST" and r["ver_decision"] != "CONTEST"]
print(f"\nexpected CONTEST but verifier did not contest: {len(miss)} of {len([r for r in ok if r['expected']=='CONTEST'])}")
print("spent total: $%.4f" % Gateway(connect()).spent())
