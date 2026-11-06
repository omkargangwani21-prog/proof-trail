import json
from core.db import connect
from core.seed import seed
from core.case_builder import build_case
from core.schemas import Draft
from core.verifier import verify

D = json.load(open("dispute_sample.json"))
conn = connect(":memory:")
seed(conn, D["disputed_transactions"][0]["seller_transaction_id"], "O")
B = build_case(conn, D)
YES = lambda text, recs: True


def ref(rid, field, val):
    return {"record_id": rid, "field": field, "quoted_value": val}


def draft(*claims, decision="CONTEST"):
    cl = [{"claim_id": f"c{i+1}", "confidence": 0.9, **c} for i, c in enumerate(claims)]
    return Draft(decision=decision, rationale="r", claims=cl, missing_evidence=[])


def one(text, refs, type="fulfillment", judge=YES):
    r = verify(B, draft({"text": text, "type": type, "source_refs": refs}), judge)
    return r, r["claims"][0]["verdict"]


GOOD = [ref("shp:1", "delivery_status", "DELIVERED"), ref("shp:1", "delivered_at", "2026-11-06T03:15:00Z"),
        ref("shp:1", "carrier", "UPS")]


def test_good_claim_verified_with_judge_and_contest():
    r, v = one("UPS delivered the order on 2026-11-06.", GOOD)
    assert v == "VERIFIED" and r["decision"] == "CONTEST" and r["missing_evidence"] == []


def test_no_judge_fails_closed_to_abstain():
    r, v = one("UPS delivered the order on 2026-11-06.", GOOD, judge=None)
    assert v == "NEEDS_REVIEW" and r["decision"] == "ABSTAIN" and not r["l3_ran"]


def test_fabricated_quote_removed():
    _, v = one("Tracking is 1Z000000000000000.", [ref("shp:1", "tracking_number", "1Z000000000000000")])
    assert v == "REMOVED"


def test_entity_nowhere_removed():
    _, v = one("Delivered on 2026-11-09.", [ref("shp:1", "delivery_status", "DELIVERED")])
    assert v == "REMOVED"


def test_entity_in_record_not_cited_needs_review():
    _, v = one("UPS delivered it.", [ref("shp:1", "delivery_status", "DELIVERED")])
    assert v == "NEEDS_REVIEW"


def test_unknown_record_removed():
    _, v = one("Delivered.", [ref("shp:99", "delivery_status", "DELIVERED")])
    assert v == "REMOVED"


def test_buyer_text_only_source_needs_review_and_abstains():
    r, v = one("The buyer ordered a desk lamp.", [ref("msg:1", "text", "I ordered a desk lamp")], type="history")
    assert v == "NEEDS_REVIEW" and r["decision"] == "ABSTAIN"


def test_blame_language_removed():
    _, v = one("The buyer is lying about delivery.", [ref("shp:1", "delivery_status", "DELIVERED")])
    assert v == "REMOVED"


def test_judge_false_removed_error_needs_review():
    _, v = one("Delivered.", [ref("shp:1", "delivery_status", "DELIVERED")], judge=lambda t, r: False)
    assert v == "REMOVED"
    def boom(t, r):
        raise RuntimeError("down")
    _, v = one("Delivered.", [ref("shp:1", "delivery_status", "DELIVERED")], judge=boom)
    assert v == "NEEDS_REVIEW"


def test_duplicate_claim_id_removed():
    d = Draft(decision="CONTEST", rationale="r", missing_evidence=[], claims=[
        {"claim_id": "c1", "text": "Delivered.", "type": "fulfillment", "confidence": 0.9,
         "source_refs": [ref("shp:1", "delivery_status", "DELIVERED")]},
        {"claim_id": "c1", "text": "Delivered.", "type": "fulfillment", "confidence": 0.9,
         "source_refs": [ref("shp:1", "delivery_status", "DELIVERED")]}])
    r = verify(B, d, YES)
    assert [x["verdict"] for x in r["claims"]] == ["VERIFIED", "REMOVED"]


def test_missing_required_evidence_abstains_with_recommendation():
    r, _ = one("The refund policy exists.", [ref("pol:1", "version", "v1")], type="policy")
    assert r["decision"] == "ABSTAIN" and r["missing_evidence"] == ["PROOF_OF_FULFILLMENT"]
    assert r["recommendation"] == "Accept the claim"
