import json, sys
from core.db import connect
from core.gateway import Gateway
from core.agent import draft
from core.judge import make_judge, judge_model_for
from core.verifier import verify

M = sys.argv[1]
ids = sys.argv[2].split(",")
reps = int(sys.argv[3])
cases = {json.loads(l)["id"]: json.loads(l) for l in open("eval/cases/dev.jsonl")}
gw = Gateway(connect())
ok = bad = 0
for cid in ids:
    b = cases[cid]["bundle"]
    for rep in range(reps):
        rid = f"{M}|DBG2-{cid}|{rep}"
        dr = draft(gw, b, M, rid + "|ag", cache=False)
        if not dr["ok"]:
            print(cid, rep, "DRAFT FAILED"); continue
        d = dr["draft"]
        ver = verify(b, d, make_judge(gw, judge_model_for(M), rid + "|jd"))
        if ver["decision"] == "CONTEST":
            ok += 1; continue
        bad += 1
        print("=" * 76)
        print(cid, "rep", rep, "| drafter:", d.decision, "| verifier:", ver["decision"], "| missing:", ver["missing_evidence"])
        for x in ver["claims"]:
            print("  ", x["verdict"], x["reasons"])
            print("      claim:", x["claim"].text[:140])
            for s in x["claim"].source_refs:
                print("        ref", s.record_id, s.field, repr(s.quoted_value)[:70])
print(f"\nCONTEST runs: {ok} | not-CONTEST runs: {bad} | judge model: {judge_model_for(M)}")
