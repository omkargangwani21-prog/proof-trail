import os, json, time, uuid, requests
from dotenv import load_dotenv

SANDBOX_BASE = "https://api-m.sandbox.paypal.com"


class NonSandboxURL(Exception):
    pass


class PayPalError(Exception):
    def __init__(self, status, body):
        super().__init__(f"PayPal {status}: {str(body)[:300]}")
        self.status, self.body = status, body


class PayPalClient:
    def __init__(self, base=None, client_id=None, secret=None):
        load_dotenv()
        self.base = base or os.environ.get("PAYPAL_BASE", SANDBOX_BASE)
        if self.base != SANDBOX_BASE:
            raise NonSandboxURL(f"Refusing non-sandbox URL: {self.base}")
        self._id = client_id or os.environ.get("PAYPAL_CLIENT_ID", "")
        self._secret = secret or os.environ.get("PAYPAL_CLIENT_SECRET", "")
        self._tok, self._exp = None, 0.0

    def _token(self):
        if self._tok and time.time() < self._exp - 60:
            return self._tok
        r = requests.post(self.base + "/v1/oauth2/token", auth=(self._id, self._secret),
                          data={"grant_type": "client_credentials"}, timeout=30)
        if r.status_code != 200:
            raise PayPalError(r.status_code, r.text)
        d = r.json()
        self._tok, self._exp = d["access_token"], time.time() + d["expires_in"]
        return self._tok

    def _request(self, method, path, **kw):
        headers = {"Authorization": "Bearer " + self._token()}
        if method == "POST":
            headers["PayPal-Request-Id"] = str(uuid.uuid4())
        headers.update(kw.pop("headers", {}))
        for attempt in range(3):
            r = requests.request(method, self.base + path, headers=headers, timeout=30, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            break
        if r.status_code >= 300:
            raise PayPalError(r.status_code, r.text)
        return r.json() if r.text else {}

    def get_dispute(self, dispute_id):
        return self._request("GET", f"/v1/customer/disputes/{dispute_id}")

    def list_disputes(self, **params):
        return self._request("GET", "/v1/customer/disputes", params=params)

    def provide_evidence(self, dispute_id, evidences, dry_run=True):
        """evidences: list of {evidence_type, evidence_info, notes}. Dry-run by default."""
        payload = {"evidences": evidences}
        if dry_run:
            return {"dry_run": True, "dispute_id": dispute_id, "payload": payload}
        files = {"input": (None, json.dumps(payload), "application/json")}
        return self._request("POST", f"/v1/customer/disputes/{dispute_id}/provide-evidence", files=files)

    def verify_webhook_signature(self, headers, event, webhook_id):
        """True only if PayPal itself confirms the signature. headers: lower-cased PAYPAL-* delivery headers."""
        names = ("auth-algo", "cert-url", "transmission-id", "transmission-sig", "transmission-time")
        vals = {n: headers.get("paypal-" + n) for n in names}
        if not webhook_id or not all(vals.values()):
            return False
        body = {k.replace("-", "_"): v for k, v in vals.items()}
        body.update({"webhook_id": webhook_id, "webhook_event": event})
        res = self._request("POST", "/v1/notifications/verify-webhook-signature", json=body)
        return res.get("verification_status") == "SUCCESS"

    def create_order(self, value, description, reference_id):
        body = {"intent": "CAPTURE",
                "purchase_units": [{"reference_id": reference_id, "description": description,
                                    "amount": {"currency_code": "USD", "value": value}}],
                "payment_source": {"paypal": {"experience_context": {
                    "return_url": "https://example.com/return", "cancel_url": "https://example.com/cancel",
                    "user_action": "PAY_NOW"}}}}
        return self._request("POST", "/v2/checkout/orders", json=body)

    def capture_order(self, order_id):
        return self._request("POST", f"/v2/checkout/orders/{order_id}/capture", json={})
