import os, sys, json, requests
from dotenv import load_dotenv
load_dotenv()
base = os.environ["PAYPAL_BASE"]
assert base == "https://api-m.sandbox.paypal.com"
t = requests.post(base + "/v1/oauth2/token",
    auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]),
    data={"grant_type": "client_credentials"}, timeout=30).json()["access_token"]
did = sys.argv[1]
r = requests.get(base + "/v1/customer/disputes/" + did,
                 headers={"Authorization": "Bearer " + t}, timeout=30)
print(r.status_code)
d = r.json()
if r.status_code != 200:
    print(json.dumps(d, indent=2)[:1200]); sys.exit(1)
for k in ["dispute_id", "reason", "status", "dispute_state", "dispute_life_cycle_stage",
          "dispute_channel", "dispute_amount", "create_time", "seller_response_due_date"]:
    print(k, "=", d.get(k))
print("allowed_response_options =", json.dumps(d.get("allowed_response_options")))
print("link rels =", [l["rel"] for l in d.get("links", [])])
print("top-level keys =", sorted(d.keys()))
json.dump(d, open("dispute_sample.json", "w"), indent=2)
