import os, requests
from dotenv import load_dotenv
load_dotenv()
r = requests.post(
    os.environ["PAYPAL_BASE"] + "/v1/oauth2/token",
    auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]),
    data={"grant_type": "client_credentials"},
    timeout=30,
)
print(r.status_code)
print({k: ("<hidden>" if k == "access_token" else v) for k, v in r.json().items()})
