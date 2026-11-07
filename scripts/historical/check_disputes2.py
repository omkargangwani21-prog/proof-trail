import os, requests
from dotenv import load_dotenv
load_dotenv()
base = os.environ["PAYPAL_BASE"]
t = requests.post(base + "/v1/oauth2/token",
    auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]),
    data={"grant_type": "client_credentials"}, timeout=30).json()["access_token"]
h = {"Authorization": "Bearer " + t}
for params in [{"disputed_transaction_id": "4BB10307P19571719"},
               {"start_time": "2026-11-01T00:00:00.000Z", "page_size": 20}]:
    r = requests.get(base + "/v1/customer/disputes", params=params, headers=h, timeout=30)
    print(params, "->", r.status_code, r.text[:300])
