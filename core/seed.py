import json
from core.db import connect


def seed(conn, capture_id, paypal_order_id):
    """Insert our sandbox order plus SYNTHETIC shipment and policy records (demo data)."""
    row = conn.execute("SELECT id FROM orders WHERE capture_id=?", (capture_id,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO orders(paypal_order_id,capture_id,buyer_ref,amount_minor,currency,status,created_at,origin)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (paypal_order_id, capture_id, "buyer-1", 4900, "USD", "COMPLETED", "2026-11-05T12:00:00Z", "human"))
    oid = cur.lastrowid
    conn.execute("INSERT INTO order_items(order_id,sku,name,qty,unit_minor) VALUES(?,?,?,?,?)",
                 (oid, "LAMP-01", "Desk lamp", 1, 4900))
    conn.execute(
        "INSERT INTO shipments(order_id,carrier,tracking_number,shipped_at,delivered_at,delivery_status,data_origin)"
        " VALUES(?,?,?,?,?,?,?)",
        (oid, "UPS", "1Z999AA10123456784", "2026-11-05T15:00:00Z", "2026-11-06T03:15:00Z",
         "DELIVERED", "synthetic_demo"))
    if not conn.execute("SELECT 1 FROM policies").fetchone():
        conn.execute("INSERT INTO policies(version,text,effective_from) VALUES(?,?,?)",
                     ("v1", "Orders ship within 1 business day with tracking. Refunds are issued for items not delivered.",
                      "2026-01-01"))
    conn.commit()
    return oid


if __name__ == "__main__":
    st = json.load(open("sandbox_state.json"))
    c = connect()
    oid = seed(c, st["capture_id"], st["order_id"])
    print("seeded order row", oid)
