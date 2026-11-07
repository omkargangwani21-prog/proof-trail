import json
from dotenv import load_dotenv
load_dotenv(".env")
from core.db import connect
from core.gateway import Gateway
from core.pipeline import run_case

c = connect()
d = json.loads(c.execute("SELECT raw_json FROM disputes WHERE paypal_dispute_id='PP-R-WVY-10197010'").fetchone()["raw_json"])
r = run_case(c, Gateway(c), d, "deepseek-ai/DeepSeek-V4-Flash-0731")
print("trail:", [x["content"]["chain_status"] for x in r["bundle"]["records"] if x["kind"] == "trail_event"])
dr = r["draft_result"]
print("draft ok:", dr["ok"])
if not dr["ok"]:
    print(json.dumps(dr, indent=1, default=str)[:2000])
else:
    print("--- DRAFT")
    print(json.dumps(dr["draft"], indent=1, default=str)[:4500])
    print("--- VERIFICATION")
    print(json.dumps(r["verification"], indent=1, default=str)[:4500])
print("spent total: $%.4f" % Gateway(c).spent())
