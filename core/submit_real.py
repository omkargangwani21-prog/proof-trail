import sys
from core.db import connect
from core.gateway import Gateway
from core.pipeline import run_case
from core.paypal_client import PayPalClient, PayPalError
from core.submitter import save_draft, approve, submit
import json

DID = sys.argv[1] if len(sys.argv) > 1 else "PP-R-GEH-10196749"
conn = connect()
gw = Gateway(conn)
client = PayPalClient()
d = client.get_dispute(DID)
print("BEFORE:", d["status"], "|", d["dispute_life_cycle_stage"])
if d["status"] != "WAITING_FOR_SELLER_RESPONSE":
    print("Dispute is not waiting for the seller. Stopping.")
    sys.exit(1)
r = run_case(conn, gw, d, "deepseek-ai/DeepSeek-V4-Flash-0731")
v = r["verification"]
print("decision:", v["decision"], "|", [(x["claim"].claim_id, x["verdict"]) for x in v["claims"]])
if v["decision"] != "CONTEST":
    print("Nothing to submit."); sys.exit(1)
did = save_draft(conn, r["bundle"], v)
preview = submit.__globals__["_draft"](conn, did)[1]
print("PAYLOAD THAT WILL BE SENT TO THE PAYPAL SANDBOX (tracking data is synthetic demo data):")
print(json.dumps({"evidences": preview}, indent=2))
if input("Type SUBMIT to send it: ").strip() != "SUBMIT":
    print("Cancelled. Nothing was sent."); sys.exit(0)
approve(conn, did, "demo operator", "approved in terminal after payload review")
try:
    res = submit(conn, client, did, dry_run=False, actor="demo operator")
    print("PayPal accepted the request. Response:", json.dumps(res)[:600])
except PayPalError as e:
    print("PAYPAL ERROR:", e); sys.exit(1)
a = client.get_dispute(DID)
print("AFTER:", a["status"], "|", a["dispute_life_cycle_stage"], "| state:", a["dispute_state"])
for e in a.get("evidences", []):
    print("  evidence:", e.get("evidence_type"), "|", e.get("source"))
print("allowed_response_options:", json.dumps(a.get("allowed_response_options")))
