from core.schemas import Draft
from core.verifier import verify

SHIP = {"carrier": "UPS", "tracking_number": "1Z999AA10123456784", "shipped_at": "2026-11-05T15:00:00Z",
        "delivered_at": "2026-11-06T03:15:00Z", "delivery_status": "DELIVERED"}
YES = lambda t, r: True


def rec(rid, kind, content, untrusted=False):
    return {"record_id": rid, "kind": kind, "untrusted": untrusted, "content": content}


def bundle(ship=SHIP, order_created="2026-11-05T12:00:00Z", dispute_amt="49.00 USD", extra=None):
    recs = [rec("dsp:1", "dispute", {"amount": dispute_amt}),
            rec("ord:1", "order", {"amount": "49.00 USD", "created_at": order_created})]
    if ship is not None:
        recs.append(rec("shp:1", "shipment", ship))
    recs += extra or []
    return {"case_id": "c_1", "dispute": recs[0], "records": recs, "required_evidence": ["PROOF_OF_FULFILLMENT"]}


def ref(rid, field, val):
    return {"record_id": rid, "field": field, "quoted_value": val}


def run(b, text, refs, type="fulfillment"):
    d = Draft(decision="CONTEST", rationale="r", missing_evidence=[],
              claims=[{"claim_id": "c1", "text": text, "type": type, "source_refs": refs, "confidence": 0.9}])
    return verify(b, d, YES)


GOOD = [ref("shp:1", "carrier", "UPS"), ref("shp:1", "delivery_status", "DELIVERED")]


def test_sufficient_shipment_contests():
    r = run(bundle(), "UPS delivery status is DELIVERED.", GOOD)
    assert r["decision"] == "CONTEST" and r["consistency_issues"] == []


def test_label_created_is_not_proof_of_fulfillment():
    ship = {"carrier": "UPS", "tracking_number": "", "shipped_at": None, "delivered_at": None,
            "delivery_status": "LABEL_CREATED"}
    r = run(bundle(ship), "UPS status is LABEL_CREATED.",
            [ref("shp:1", "carrier", "UPS"), ref("shp:1", "delivery_status", "LABEL_CREATED")])
    assert r["claims"][0]["verdict"] == "VERIFIED"
    assert r["decision"] == "ABSTAIN" and r["missing_evidence"] == ["PROOF_OF_FULFILLMENT"]


def test_delivered_before_shipped_abstains():
    r = run(bundle({**SHIP, "delivered_at": "2026-11-05T10:00:00Z"}), "UPS status is DELIVERED.", GOOD)
    assert r["decision"] == "ABSTAIN" and "delivered before it shipped" in r["consistency_issues"][0]


def test_shipped_before_order_abstains():
    r = run(bundle(order_created="2026-11-06T00:00:00Z"), "UPS status is DELIVERED.", GOOD)
    assert r["decision"] == "ABSTAIN" and "shipped before the order" in r["consistency_issues"][0]


def test_dispute_amount_above_order_abstains():
    r = run(bundle(dispute_amt="80.00 USD"), "UPS status is DELIVERED.", GOOD)
    assert r["decision"] == "ABSTAIN" and "exceeds" in r["consistency_issues"][0]


def test_broken_trail_claim_needs_review_verified_trail_passes():
    def trail(status):
        return rec("trl:1", "trail_event", {"event": "intent", "summary": "Buyer agent asked to buy a desk lamp under 50 USD",
                                            "chain_status": status})
    txt, refs = "The purchase intent was to buy a desk lamp.", [ref("trl:1", "summary", "buy a desk lamp")]
    assert run(bundle(extra=[trail("BROKEN")]), txt, refs, "authorization")["claims"][0]["verdict"] == "NEEDS_REVIEW"
    assert run(bundle(extra=[trail("VERIFIED")]), txt, refs, "authorization")["claims"][0]["verdict"] == "VERIFIED"


def test_wrong_date_inside_a_timestamp_is_caught():
    r = run(bundle(), "UPS delivered at 2026-11-09T03:15:00Z.",
            [ref("shp:1", "carrier", "UPS"), ref("shp:1", "delivered_at", "2026-11-06T03:15:00Z")])
    assert r["claims"][0]["verdict"] == "REMOVED"


def test_right_date_inside_a_timestamp_passes():
    r = run(bundle(), "UPS delivered at 2026-11-06T03:15:00Z.",
            [ref("shp:1", "carrier", "UPS"), ref("shp:1", "delivered_at", "2026-11-06T03:15:00Z")])
    assert r["claims"][0]["verdict"] == "VERIFIED"
