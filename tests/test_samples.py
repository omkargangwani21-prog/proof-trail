import json
import datetime
import pytest
from core.db import connect
from core import samples

NOW = datetime.datetime(2026, 11, 8, 12, 0, tzinfo=datetime.timezone.utc)


def case(cat, n, variant="v", ship=True):
    cid = f"dev-{cat}-{n:02d}"
    recs = [
        {"kind": "dispute", "content": {"paypal_dispute_id": f"SYN-{cid}", "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
         "status": "WAITING_FOR_SELLER_RESPONSE", "stage": "INQUIRY", "amount": "25.99 USD", "due_at": "2026-10-25T17:00:00Z"}},
        {"kind": "order", "content": {"paypal_order_id": f"SYN-ORD-{cid}", "capture_id": f"SYN-CAP-{cid}", "amount": "25.99 USD",
         "status": "COMPLETED", "created_at": "2026-10-01T12:00:00Z",
         "items": [{"name": "Mouse", "qty": 1, "sku": "SKU-M", "unit_minor": 2599}]}},
        {"kind": "policy", "content": {"version": "v1", "text": "Orders ship within 1 business day."}},
        {"kind": "buyer_message", "content": {"author": "BUYER", "text": "It never arrived."}},
    ]
    if ship:
        recs.append({"kind": "shipment", "content": {"carrier": "UPS", "tracking_number": "1ZABC", "shipped_at": "2026-10-02T09:00:00Z",
                     "delivered_at": None, "delivery_status": "IN_TRANSIT", "data_origin": "synthetic_eval"}})
    return {"id": cid, "category": cat, "variant": variant, "split": "dev", "bundle": {"case_id": cid, "records": recs}}


@pytest.fixture
def conn(tmp_path):
    return connect(str(tmp_path / "t.db"))


def test_sample_goes_through_the_normal_case_path(conn):
    pid = samples.load_sample(conn, case("clean", 0), 0, NOW)
    assert pid == "SYN-dev-clean-00"
    d = conn.execute("SELECT * FROM disputes WHERE paypal_dispute_id=?", (pid,)).fetchone()
    assert d["origin"] == "synthetic_sample" and d["amount_minor"] == 2599
    assert d["due_at"] > "2026-11-08T12:00:00Z"
    kinds = {r["kind"] for r in conn.execute("SELECT kind FROM source_records")}
    assert {"dispute", "order", "shipment", "policy", "buyer_message"} <= kinds
    assert conn.execute("SELECT untrusted FROM source_records WHERE kind='buyer_message'").fetchone()["untrusted"] == 1


def test_no_shipment_case_has_no_shipment_record(conn):
    samples.load_sample(conn, case("missing", 0, ship=False), 0, NOW)
    assert conn.execute("SELECT COUNT(*) c FROM shipments").fetchone()["c"] == 0


def test_loading_twice_adds_nothing(conn):
    c = case("clean", 0)
    assert samples.load_sample(conn, c, 0, NOW)
    assert samples.load_sample(conn, c, 0, NOW) is None
    assert conn.execute("SELECT COUNT(*) c FROM disputes").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"] == 1


def test_pick_follows_the_plan_and_spreads_variants():
    cases = [case(cat, i, variant=str(i)) for cat, _ in samples.PLAN for i in range(4)]
    got = samples.pick(cases)
    assert len(got) == 8
    assert len({c["variant"] for c in got if c["category"] == "injection"}) == 2


def test_test_split_is_refused(tmp_path):
    bad = case("clean", 0)
    bad["split"] = "test"
    p = tmp_path / "c.jsonl"
    p.write_text(json.dumps(bad) + "\n")
    with pytest.raises(ValueError):
        samples.read_cases(str(p))
