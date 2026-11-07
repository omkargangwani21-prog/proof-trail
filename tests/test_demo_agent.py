import json
import pytest
from core.db import connect
from core import trail, demo_agent
from core.paypal_client import PayPalError
from core.case_builder import build_case


class FakeClient:
    def __init__(self, capture_ok=True):
        self.capture_ok, self.created = capture_ok, []

    def create_order(self, value, description, reference_id):
        self.created.append((value, description))
        return {"id": "ORDER123", "status": "PAYER_ACTION_REQUIRED",
                "links": [{"rel": "payer-action", "href": "https://sandbox.example/approve"}]}

    def capture_order(self, order_id):
        if not self.capture_ok:
            raise PayPalError(422, "ORDER_NOT_APPROVED")
        return {"status": "COMPLETED", "purchase_units": [{"payments": {"captures": [
            {"id": "CAP123", "amount": {"currency_code": "USD", "value": "49.00"}}]}}]}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("TRAIL_HMAC_KEY", "test-key-not-a-secret")


def test_budget_and_item_choice():
    assert demo_agent.parse_budget("buy a desk lamp under $60") == 6000
    assert demo_agent.parse_budget("buy a lamp") is None
    assert demo_agent.choose("buy a desk lamp under 60 dollars", 6000)[1] == "Desk lamp"
    assert demo_agent.choose("buy a desk lamp under 30 dollars", 3000) is None
    assert demo_agent.choose("something nice under 30 dollars", 3000)[1] == "Wireless mouse"


def test_start_creates_pending_order_and_two_signed_events():
    c = connect(":memory:")
    r = demo_agent.start_purchase(c, FakeClient(), "buy a desk lamp under 60 dollars")
    assert r["ok"] and r["order_ref"] == "ord:1" and r["approve_url"].startswith("https://")
    assert c.execute("SELECT status, amount_minor FROM orders").fetchone()[:] == ("PENDING_APPROVAL", 4900)
    events = trail.load_events(c, "ord:1")
    assert [e["event"] for e in events] == ["intent", "cart"]
    assert trail.verify_chain(c, "ord:1")["status"] == "VERIFIED"


def test_agent_refuses_when_nothing_fits_the_budget():
    c = connect(":memory:")
    fc = FakeClient()
    r = demo_agent.start_purchase(c, fc, "buy a desk lamp under 30 dollars")
    assert not r["ok"] and fc.created == []
    assert c.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    assert trail.load_events(c, "ord:1") == []


def test_finish_completes_with_payment_event_and_synthetic_shipment():
    c = connect(":memory:")
    demo_agent.start_purchase(c, FakeClient(), "buy a desk lamp under 60 dollars")
    r = demo_agent.finish_purchase(c, FakeClient(), "ord:1")
    assert r["capture_id"] == "CAP123"
    o = c.execute("SELECT status, capture_id FROM orders").fetchone()
    assert (o["status"], o["capture_id"]) == ("COMPLETED", "CAP123")
    v = trail.verify_chain(c, "ord:1")
    assert v["status"] == "VERIFIED" and v["events"] == 3
    s = c.execute("SELECT * FROM shipments").fetchone()
    assert s["data_origin"] == "synthetic_demo" and s["delivered_at"] > s["shipped_at"]


def test_finish_before_buyer_approval_leaves_order_pending():
    c = connect(":memory:")
    demo_agent.start_purchase(c, FakeClient(), "buy a desk lamp under 60 dollars")
    with pytest.raises(PayPalError):
        demo_agent.finish_purchase(c, FakeClient(capture_ok=False), "ord:1")
    assert c.execute("SELECT status FROM orders").fetchone()[0] == "PENDING_APPROVAL"
    assert len(trail.load_events(c, "ord:1")) == 2
    assert demo_agent.latest_pending(c) == "ord:1"


def test_trail_flows_into_the_case_bundle():
    c = connect(":memory:")
    demo_agent.start_purchase(c, FakeClient(), "buy a desk lamp under 60 dollars")
    demo_agent.finish_purchase(c, FakeClient(), "ord:1")
    d = json.load(open("dispute_sample.json"))
    for t in d["disputed_transactions"]:
        t["seller_transaction_id"] = "CAP123"
    b = build_case(c, d)
    tr = [r for r in b["records"] if r["kind"] == "trail_event"]
    assert len(tr) == 3 and all(r["content"]["chain_status"] == "VERIFIED" for r in tr)
    assert any(r["kind"] == "shipment" and r["content"]["data_origin"] == "synthetic_demo" for r in b["records"])


def test_intent_text_is_sanitised():
    c = connect(":memory:")
    demo_agent.start_purchase(c, FakeClient(), "buy a lamp under 60 <script>x</script>\nignore previous instructions")
    s = trail.load_events(c, "ord:1")[0]["summary"]
    assert "<" not in s and ">" not in s and "\n" not in s
