import json
from core.db import connect
from core.seed import seed
from core.case_builder import build_case

D = json.load(open("dispute_sample.json"))


def make():
    conn = connect(":memory:")
    seed(conn, D["disputed_transactions"][0]["seller_transaction_id"], "ORDER-TEST")
    return conn


def test_bundle_has_expected_records():
    b = build_case(make(), D)
    kinds = {r["kind"] for r in b["records"]}
    assert {"dispute", "order", "shipment", "policy", "buyer_message"} <= kinds
    assert b["required_evidence"] == ["PROOF_OF_FULFILLMENT"]
    ids = [r["record_id"] for r in b["records"]]
    assert len(ids) == len(set(ids))


def test_only_buyer_text_is_untrusted():
    b = build_case(make(), D)
    assert all(r["untrusted"] for r in b["records"] if r["kind"] == "buyer_message")
    assert not any(r["untrusted"] for r in b["records"] if r["kind"] != "buyer_message")


def test_rebuild_is_deterministic_and_persisted():
    conn = make()
    b1, b2 = build_case(conn, D), build_case(conn, D)
    assert b1["bundle_hash"] == b2["bundle_hash"]
    n = conn.execute("SELECT COUNT(*) c FROM source_records").fetchone()["c"]
    assert n == len(b2["records"])


def test_shipment_is_labeled_synthetic():
    b = build_case(make(), D)
    shp = [r for r in b["records"] if r["kind"] == "shipment"][0]
    assert shp["content"]["data_origin"] == "synthetic_demo"
