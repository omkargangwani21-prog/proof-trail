import os, sys, json, uuid, requests
from dotenv import load_dotenv
load_dotenv()

BASE = os.environ["PAYPAL_BASE"]
assert BASE == "https://api-m.sandbox.paypal.com", "Refusing non-sandbox URL"

def token():
    r = requests.post(BASE + "/v1/oauth2/token",
        auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]),
        data={"grant_type": "client_credentials"}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

def hdr(t):
    return {"Authorization": "Bearer " + t, "Content-Type": "application/json",
            "PayPal-Request-Id": str(uuid.uuid4())}

cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "create":
    body = {"intent": "CAPTURE",
            "purchase_units": [{"reference_id": "order-001", "description": "Desk lamp",
                                "amount": {"currency_code": "USD", "value": "49.00"}}],
            "payment_source": {"paypal": {"experience_context": {
                "return_url": "https://example.com/return",
                "cancel_url": "https://example.com/cancel",
                "user_action": "PAY_NOW"}}}}
    r = requests.post(BASE + "/v2/checkout/orders", json=body, headers=hdr(token()), timeout=30)
    print(r.status_code)
    d = r.json()
    if r.status_code >= 300:
        print(json.dumps(d, indent=2)[:1500]); sys.exit(1)
    link = next((l["href"] for l in d["links"] if l["rel"] in ("payer-action", "approve")), None)
    json.dump({"order_id": d["id"]}, open("sandbox_state.json", "w"))
    print("order id:", d["id"], "| status:", d["status"])
    print("OPEN THIS LINK AS THE BUYER:", link)
elif cmd == "capture":
    oid = json.load(open("sandbox_state.json"))["order_id"]
    r = requests.post(BASE + "/v2/checkout/orders/%s/capture" % oid,
                      headers=hdr(token()), json={}, timeout=30)
    print(r.status_code)
    d = r.json()
    if r.status_code >= 300:
        print(json.dumps(d, indent=2)[:1500]); sys.exit(1)
    cap = d["purchase_units"][0]["payments"]["captures"][0]
    st = json.load(open("sandbox_state.json")); st["capture_id"] = cap["id"]
    json.dump(st, open("sandbox_state.json", "w"))
    print("status:", d["status"], "| capture id:", cap["id"], "| amount:", cap["amount"])
else:
    print("usage: python orders.py create | capture")
