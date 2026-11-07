import json, sys
from core.db import connect
from core.gateway import Gateway
from core.agent import draft
from core.judge import make_judge, judge_model_for
from core.verifier import verify

M = "deepseek-ai/DeepSeek-V4-Flash-0731"
cases = {json.loads(l)["id"]: json.loads(l) for l in open("eval/cases/dev.jsonl")}
gw = Gateway(connect())
for cid in ["dev-partial-00", "dev-partial-02", "dev-partial-05"]:
    c = cases[cid]; b = c["bundle"]
    print("#" * 78)
    print(cid, c["variant"], "| expected:", c["truth"]["expected_decision"])
    for r in b["records"]:
        if r["kind"] == "shipment":
            print("  ", r["record_id"], json.dumps(r["content"]))
    for rep in range(3):
        rid = f"{M}|DBG-{cid}|{rep}"
        dr = draft(gw, b, M, rid + "|ag", cache=False)
        print(f"--- rep {rep}  ok={dr['ok']}")
        if not dr["ok"]:
            print("   draft failed"); continue
        d = dr["draft"]
        print("   DRAFT decision:", d.decision, "| missing:", d.missing_evidence)
        print("   rationale:", d.rationale[:300])
        for cl in d.claims:
            print("   CLAIM", cl.claim_id, cl.type, "|", cl.text)
            for s in cl.source_refs:
                print("        ref", s.record_id, s.field, repr(s.quoted_value))
        ver = verify(b, d, make_judge(gw, judge_model_for(M), rid + "|jd"))
        print("   VERIFIER decision:", ver["decision"], "| missing:", ver["missing_evidence"],
              "| consistency:", ver["consistency_issues"])
        for x in ver["claims"]:
            print("     ", x["verdict"], x["reasons"], "|", x["claim"].text[:80])
