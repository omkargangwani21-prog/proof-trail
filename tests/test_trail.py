import pytest
from core.db import connect
from core import trail

KEY = "test-key-not-a-secret"
REF = "ord:1"


def seeded(conn, ref=REF):
    trail.record(conn, ref, "intent", "Buy a desk lamp under 60 USD", {"max_usd": 60}, key=KEY, at="2026-10-01T10:00:00Z")
    trail.record(conn, ref, "cart", "Desk lamp x1, 49.00 USD", {"total": "49.00"}, key=KEY, at="2026-10-01T10:02:00Z")
    trail.record(conn, ref, "payment", "Payment captured, 49.00 USD", {"capture_id": "CAP1"}, key=KEY, at="2026-10-01T10:05:00Z")


def test_intact_chain_verifies():
    c = connect(":memory:")
    seeded(c)
    r = trail.verify_chain(c, REF, key=KEY)
    assert r["status"] == "VERIFIED" and r["events"] == 3 and r["head"]


def test_changed_content_breaks_at_that_event():
    c = connect(":memory:")
    seeded(c)
    t = trail.tampered(trail.load_events(c, REF), 2, summary="Desk lamp x9, 441.00 USD")
    r = trail.verify_events(t, KEY)
    assert r["status"] == "BROKEN" and r["broken_at"] == 2


def test_forger_without_the_key_cannot_fix_the_hash():
    c = connect(":memory:")
    seeded(c)
    t = trail.tampered(trail.load_events(c, REF), 2, summary="forged")
    t[1]["hash"] = trail.event_hash(t[1])
    r = trail.verify_events(t, KEY)
    assert r["status"] == "BROKEN" and r["broken_at"] == 2 and "signature" in r["reason"]


def test_deleted_middle_event_is_detected():
    c = connect(":memory:")
    seeded(c)
    e = trail.load_events(c, REF)
    assert trail.verify_events([e[0], e[2]], KEY)["status"] == "BROKEN"


def test_wrong_key_breaks():
    c = connect(":memory:")
    seeded(c)
    r = trail.verify_chain(c, REF, key="another-key")
    assert r["status"] == "BROKEN" and r["broken_at"] == 1


def test_events_must_come_in_order():
    c = connect(":memory:")
    with pytest.raises(ValueError):
        trail.record(c, REF, "payment", "too early", key=KEY)


def test_records_for_the_case_bundle_and_db_tampering():
    c = connect(":memory:")
    seeded(c)
    recs = trail.trail_records(c, REF, key=KEY)
    assert [r["kind"] for r in recs] == ["trail_event"] * 3
    assert all(r["record_id"].startswith("trl:") and r["content"]["chain_status"] == "VERIFIED" for r in recs)
    c.execute("UPDATE trail_events SET summary='edited' WHERE seq=2")
    c.commit()
    assert all(r["content"]["chain_status"] == "BROKEN" for r in trail.trail_records(c, REF, key=KEY))


def test_missing_key_is_unverified_and_empty_needs_no_key(monkeypatch):
    monkeypatch.delenv("PT_HMAC_KEY", raising=False)
    monkeypatch.delenv("HMAC_KEY", raising=False)
    c = connect(":memory:")
    seeded(c)
    assert trail.trail_records(c, REF)[0]["content"]["chain_status"] == "UNVERIFIED"
    assert trail.trail_records(c, "ord:9") == []
