import json, sys
from core.db import connect
from core.gateway import Gateway
from core.pipeline import run_case
from core.schemas import Claim, SourceRef

FAB = "--fabricate" in sys.argv


def add_fake(d):
    d.claims.append(Claim(claim_id="c_fake", text="The parcel was signed for by J. Smith at the front desk.",
                          type="fulfillment", confidence=0.9,
                          source_refs=[SourceRef(record_id="shp:1", field="delivery_status",
                                                 quoted_value="SIGNED BY J. SMITH")]))
    return d


conn = connect()
gw = Gateway(conn)
d = json.load(open("dispute_sample.json"))
r = run_case(conn, gw, d, "deepseek-ai/DeepSeek-V4-Flash-0731", mutate=add_fake if FAB else None)
if not r["draft_result"]["ok"]:
    print("DRAFT FAILED:", r["draft_result"]["error"]); sys.exit(1)
v = r["verification"]
print("agent decision:", r["draft_result"]["draft"].decision, "| FINAL decision:", v["decision"],
      "|", v["recommendation"], "| judge ran:", v["l3_ran"], "| missing:", v["missing_evidence"])
for x in v["claims"]:
    c = x["claim"]
    tag = "  [seeded fake claim added by test harness]" if c.claim_id == "c_fake" else ""
    print(f"- {c.claim_id}: {x['verdict']}{tag}\n    {c.text}")
    for why in x["reasons"]:
        print("    reason:", why)
print("spent total: $%.4f" % gw.spent())
