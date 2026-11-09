from core.schemas import Claim, SourceRef
from core.verifier import check_claim

RECS = {
    "msg:1": {"record_id": "msg:1", "kind": "buyer_message", "untrusted": True,
              "content": {"author": "BUYER", "text": "I did not get it"}},
    "shp:1": {"record_id": "shp:1", "kind": "shipment", "untrusted": False,
              "content": {"delivery_status": "DELIVERED"}},
}
TRUSTED = '{"delivery_status": "DELIVERED"}'


def claim(ctype, *refs):
    return Claim(claim_id="c1", text="The buyer states the parcel was not received.", type=ctype, confidence=0.9,
                 source_refs=[SourceRef(record_id=r, field=f, quoted_value=q) for r, f, q in refs])


MSG = ("msg:1", "text", "did not get it")
SHP = ("shp:1", "delivery_status", "DELIVERED")


def test_cap_off_leaves_other_type_buyer_quote_alone():
    assert check_claim(claim("other", MSG), RECS, TRUSTED, cap=False)[0] == "PASS"


def test_cap_on_sends_buyer_only_other_claim_to_review():
    v, why = check_claim(claim("other", MSG), RECS, TRUSTED, cap=True)
    assert v == "NEEDS_REVIEW" and "buyer-written" in why[0]


def test_cap_on_sends_mixed_citation_to_review():
    assert check_claim(claim("fulfillment", SHP, MSG), RECS, TRUSTED, cap=True)[0] == "NEEDS_REVIEW"
    assert check_claim(claim("fulfillment", SHP, MSG), RECS, TRUSTED, cap=False)[0] == "PASS"


def test_trusted_only_claim_is_unaffected():
    assert check_claim(claim("fulfillment", SHP), RECS, TRUSTED, cap=True)[0] == "PASS"
