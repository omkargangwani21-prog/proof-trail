import json
import pytest
from core.db import connect
from core import demo_agent
from core.case_builder import build_case
from core.schemas import Claim, Draft, SourceRef
from core.verifier import verify


class FakeClient:
    def create_order(self, value, description, reference_id):
        return {"id": "ORD1", "links": [{"rel": "payer-action", "href": "https://x"}]}

    def capture_order(self, order_id):
        return {"status": "COMPLETED", "purchase_units": [{"payments": {"captures": [
            {"id": "CAP1", "amount": {"currency_code": "USD", "value": "49.00"}}]}}]}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("TRAIL_HMAC_KEY", "test-key-not-a-secret")


def run(required):
    c = connect(":memory:")
    demo_agent.start_purchase(c, FakeClient(), "buy a desk lamp under 60 dollars")
    demo_agent.finish_purchase(c, FakeClient(), "ord:1")
    d = json.load(open("dispute_sample.json"))
    for t in d["disputed_transactions"]:
        t["seller_transaction_id"] = "CAP1"
    d["evidences"] = [{"evidence_type": e, "source": "REQUESTED_FROM_SELLER"} for e in required]
    b = build_case(c, d)
    shp = next(r for r in b["records"] if r["kind"] == "shipment")
    ct = shp["content"]
    claim = Claim(claim_id="c1", text=f"The item shipped via {ct['carrier']} with tracking number {ct['tracking_number']}.",
                  type="fulfillment", confidence=1.0,
                  source_refs=[SourceRef(record_id=shp["record_id"], field="carrier", quoted_value=ct["carrier"]),
                               SourceRef(record_id=shp["record_id"], field="tracking_number", quoted_value=ct["tracking_number"])])
    draft = Draft(decision="CONTEST", rationale="shipped", claims=[claim], missing_evidence=[])
    return verify(b, draft, judge=lambda text, cited: True)


def test_extra_requested_types_are_reported_not_gating():
    r = run(["PROOF_OF_FULFILLMENT", "PROOF_OF_REFUND", "OTHER"])
    assert r["missing_evidence"] == []
    assert r["requested_not_provided"] == ["PROOF_OF_REFUND", "OTHER"]


def test_only_fulfillment_requested_behaves_as_before():
    r = run(["PROOF_OF_FULFILLMENT"])
    assert r["missing_evidence"] == [] and r["requested_not_provided"] == []


def test_no_gating_type_listed_stays_strict():
    r = run(["PROOF_OF_REFUND"])
    assert r["missing_evidence"] == ["PROOF_OF_REFUND"] and r["requested_not_provided"] == []
    assert r["decision"] == "ABSTAIN"
