import json
from core.db import connect
from core.gateway import Gateway
from core.pipeline import run_case
from core.paypal_client import PayPalClient
from core.submitter import save_draft, approve, submit, NotApproved

conn = connect()
gw = Gateway(conn)
d = json.load(open("dispute_sample.json"))
r = run_case(conn, gw, d, "deepseek-ai/DeepSeek-V4-Flash-0731")
v = r["verification"]
print("decision:", v["decision"], "|", [(x["claim"].claim_id, x["verdict"]) for x in v["claims"]])
did = save_draft(conn, r["bundle"], v)
client = PayPalClient()
try:
    submit(conn, client, did, dry_run=True)
except NotApproved as e:
    print("BLOCKED before approval:", e)
approve(conn, did, "demo operator", "reviewed claims and payload")
out = submit(conn, client, did, dry_run=True)
print("DRY RUN, nothing was sent to PayPal. Payload preview:")
print(json.dumps(out, indent=2))
print("audit log rows:", [(a["action"]) for a in conn.execute("SELECT action FROM audit_log")])
print("spent total: $%.4f" % gw.spent())
