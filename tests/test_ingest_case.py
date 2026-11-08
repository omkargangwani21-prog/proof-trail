from core.db import connect
from core import ingest


class FakeClient:
    def __init__(self, d):
        self.d = d

    def get_dispute(self, pid):
        return self.d


def dispute():
    return {"dispute_id": "PP-R-TST-1", "reason": "UNAUTHORISED", "status": "WAITING_FOR_SELLER_RESPONSE",
            "dispute_life_cycle_stage": "CHARGEBACK", "dispute_amount": {"value": "15.99", "currency_code": "USD"},
            "seller_response_due_date": "2026-11-19T04:59:59.000Z", "create_time": "2026-11-08T17:59:00Z",
            "update_time": "2026-11-08T17:59:00Z", "disputed_transactions": [{"seller_transaction_id": "CAP-1"}],
            "evidences": [{"evidence_type": "PROOF_OF_FULFILLMENT", "source": "REQUESTED_FROM_SELLER"}], "messages": []}


def seed(conn):
    oid = conn.execute("INSERT INTO orders(paypal_order_id,capture_id,buyer_ref,amount_minor,currency,status,created_at,origin)"
                       " VALUES('O1','CAP-1','b',1599,'USD','COMPLETED','2026-11-08T17:00:00Z','human')").lastrowid
    conn.execute("INSERT INTO shipments(order_id,carrier,tracking_number,shipped_at,delivered_at,delivery_status,data_origin)"
                 " VALUES(?,?,?,?,?,?,?)", (oid, "UPS", "1ZX", "2026-11-08T17:10:00Z", "2026-11-08T17:20:00Z", "DELIVERED", "synthetic_demo"))
    conn.commit()


def test_ingest_builds_the_case_with_order_and_shipment(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    seed(conn)
    ingest.ingest_dispute(conn, FakeClient(dispute()), "PP-R-TST-1")
    kinds = {r["kind"] for r in conn.execute("SELECT kind FROM source_records")}
    assert {"dispute", "order", "shipment"} <= kinds


def test_second_ingest_keeps_the_same_case(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    seed(conn)
    c = FakeClient(dispute())
    ingest.ingest_dispute(conn, c, "PP-R-TST-1")
    first = conn.execute("SELECT id FROM cases").fetchone()["id"]
    ingest.ingest_dispute(conn, c, "PP-R-TST-1")
    assert [r["id"] for r in conn.execute("SELECT id FROM cases")] == [first]
