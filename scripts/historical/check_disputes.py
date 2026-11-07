import os, requests
from dotenv import load_dotenv
load_dotenv()
base = os.environ["PAYPAL_BASE"]
t = requests.post(base + "/v1/oauth2/token",
    auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]),
    data={"grant_type": "client_credentials"}, timeout=30).json()["access_token"]
r = requests.get(base + "/v1/customer/disputes", params={"page_size": 5},
    headers={"Authorization": "Bearer " + t}, timeout=30)
print(r.status_code)
print(r.text[:600])
