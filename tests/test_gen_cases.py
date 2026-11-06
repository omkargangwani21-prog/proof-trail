import json, collections
from core.schemas import Draft
from core.verifier import verify
from eval.gen_cases import generate, dump, PLAN


def cases():
    return generate("dev") + generate("test")


def test_counts():
    for split, want in {"dev": 20, "test": 40}.items():
        assert len(generate(split)) == want
    c = collections.Counter(x["category"] for x in generate("test"))
    assert c == {"clean": 10, "missing": 8, "conflicting": 6, "injection": 8, "trail": 8}


def test_deterministic_and_disjoint():
    assert dump(generate("test")) == dump(generate("test"))
    ids = [c["id"] for c in cases()]
    assert len(ids) == len(set(ids))
    disputes = [c["bundle"]["dispute"]["content"]["paypal_dispute_id"] for c in cases()]
    assert len(disputes) == len(set(disputes))


def test_injection_markers_not_in_trusted_records():
    for c in cases():
        trusted = " ".join(json.dumps(r["content"]) for r in c["bundle"]["records"] if not r["untrusted"]).lower()
        for m in c["truth"]["markers"]:
            assert m.lower() not in trusted, (c["id"], m)


def test_only_buyer_text_untrusted():
    for c in cases():
        assert [r["record_id"] for r in c["bundle"]["records"] if r["untrusted"]] == ["msg:1"]


def oracle(case):
    shp = next((r for r in case["bundle"]["records"] if r["kind"] == "shipment"), None)
    if shp is None:
        return Draft(decision="ABSTAIN", rationale="no shipment record", claims=[], missing_evidence=["PROOF_OF_FULFILLMENT"])
    c = shp["content"]
    ref = lambda f: {"record_id": "shp:1", "field": f, "quoted_value": str(c[f])}
    claims = [{"claim_id": "c1", "type": "fulfillment", "confidence": 0.9,
               "text": f"{c['carrier']} shipment status is {c['delivery_status']}.",
               "source_refs": [ref("carrier"), ref("delivery_status")]}]
    if c.get("tracking_number") and c.get("delivered_at"):
        claims.append({"claim_id": "c2", "type": "fulfillment", "confidence": 0.9,
                       "text": f"Tracking number {c['tracking_number']} delivered at {c['delivered_at']}.",
                       "source_refs": [ref("tracking_number"), ref("delivered_at")]})
    return Draft(decision="CONTEST", rationale="r", claims=claims, missing_evidence=[])


def test_oracle_agrees_with_ground_truth_on_every_case():
    for c in cases():
        got = verify(c["bundle"], oracle(c), lambda t, r: True)["decision"]
        assert got == c["truth"]["expected_decision"], (c["id"], c["variant"], got)


def test_truth_dates_are_extracted_from_timestamps():
    for c in cases():
        if any(r["kind"] == "shipment" for r in c["bundle"]["records"]):
            assert c["truth"]["true_entities"]["dates"], c["id"]
