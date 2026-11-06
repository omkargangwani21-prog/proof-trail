import json, sys
from core.db import connect
from core.gateway import Gateway
from core.case_builder import build_case
from core.agent import draft

model = sys.argv[1] if len(sys.argv) > 1 else "deepseek-ai/DeepSeek-V4-Flash-0731"
conn = connect()
gw = Gateway(conn)
d = json.load(open("dispute_sample.json"))
bundle = build_case(conn, d)
print("case", bundle["case_id"], "| records:", [r["record_id"] for r in bundle["records"]],
      "| required:", bundle["required_evidence"])
r = draft(gw, bundle, model)
print("ok:", r["ok"], "| calls:", len(r["attempts"]), "| cost: $%.5f" % r["cost_usd"], "| spent total: $%.4f" % gw.spent())
if r["ok"]:
    dr = r["draft"]
    print("decision:", dr.decision, "\nrationale:", dr.rationale)
    for c in dr.claims:
        print("-", c.claim_id, c.type, c.confidence, "|", c.text)
        for s in c.source_refs:
            print("     cites", s.record_id, s.field, "=", repr(s.quoted_value))
    print("missing:", dr.missing_evidence)
else:
    print("error:", r["error"])
