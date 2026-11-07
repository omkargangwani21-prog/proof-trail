"""Demo shopping agent: turns a shopper's instruction into a sandbox purchase and writes the signed trail.
The sandbox buyer's approval on PayPal's page is a human step. Shipment and delivery records are SYNTHETIC demo data.
The intent text comes from the shopper's side: the trail proves it was not edited afterwards, not that it is true."""
import datetime, re, sys
from core import trail

CATALOG = [("LAMP-01", "Desk lamp", 4900, ("lamp",)), ("MOUSE-01", "Wireless mouse", 2599, ("mouse",)),
           ("MAT-01", "Yoga mat", 3499, ("yoga mat", "mat")), ("STAND-01", "Phone stand", 1599, ("phone stand", "stand")),
           ("BOTTLE-01", "Water bottle", 2199, ("bottle",)), ("NOTE-01", "Notebook set", 1299, ("notebook",)),
           ("SPEAK-01", "Bluetooth speaker", 5999, ("speaker",))]
POLICY = "Orders ship within 1 business day with tracking. Refunds are issued for items not delivered."


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def clean(text):
    return re.sub(r"\s+", " ", re.sub(r"[<>\x00-\x1f]+", " ", text or "")).strip()[:140]


def parse_budget(text):
    m = re.search(r"(?:under|below|less than|max|up to)\s*\$?\s*(\d+(?:\.\d{1,2})?)", text, re.I)
    return int(round(float(m.group(1)) * 100)) if m else None


def choose(text, budget):
    low = text.lower()
    named = [c for c in CATALOG if any(re.search(rf"\b{re.escape(k)}\b", low) for k in c[3])]
    ok = [c for c in (named or CATALOG) if budget is None or c[2] <= budget]
    if not ok:
        return None
    return ok[0] if named else max(ok, key=lambda c: c[2])


def start_purchase(conn, client, intent, key=None):
    trail._key(key)
    intent = clean(intent)
    budget = parse_budget(intent)
    item = choose(intent, budget)
    if item is None:
        return {"ok": False, "reason": "No catalog item matches this instruction within the budget, so the agent does not buy."}
    sku, name, price, _ = item
    if not conn.execute("SELECT 1 FROM policies").fetchone():
        conn.execute("INSERT INTO policies(version,text,effective_from) VALUES(?,?,?)", ("v1", POLICY, "2026-01-01"))
    cur = conn.execute(
        "INSERT INTO orders(paypal_order_id,capture_id,buyer_ref,amount_minor,currency,status,created_at,origin)"
        " VALUES(NULL,NULL,?,?,?,?,?,?)", ("sandbox-buyer", price, "USD", "PENDING_APPROVAL", _iso(_now()), "agent"))
    oid = cur.lastrowid
    ref = f"ord:{oid}"
    conn.execute("INSERT INTO order_items(order_id,sku,name,qty,unit_minor) VALUES(?,?,?,?,?)", (oid, sku, name, 1, price))
    conn.commit()
    amount = f"{price / 100:.2f}"
    trail.record(conn, ref, "intent", f"Shopper asked the agent: {intent}", {"intent": intent, "max_minor": budget}, key=key)
    trail.record(conn, ref, "cart", f"{name} x1, {amount} USD", {"sku": sku, "qty": 1, "total_minor": price, "currency": "USD"}, key=key)
    try:
        order = client.create_order(amount, name, f"order-{oid}")
    except Exception:
        conn.execute("UPDATE orders SET status='FAILED' WHERE id=?", (oid,))
        conn.commit()
        raise
    link = next((l["href"] for l in order.get("links", []) if l["rel"] in ("payer-action", "approve")), None)
    conn.execute("UPDATE orders SET paypal_order_id=? WHERE id=?", (order["id"], oid))
    conn.commit()
    return {"ok": True, "order_ref": ref, "paypal_order_id": order["id"], "approve_url": link, "item": name, "amount": amount}


def latest_pending(conn):
    r = conn.execute("SELECT id FROM orders WHERE origin='agent' AND status='PENDING_APPROVAL' ORDER BY id DESC LIMIT 1").fetchone()
    return f"ord:{r['id']}" if r else None


def finish_purchase(conn, client, order_ref, key=None):
    trail._key(key)
    row = conn.execute("SELECT * FROM orders WHERE id=?", (int(order_ref.split(":", 1)[1]),)).fetchone()
    if not row or row["origin"] != "agent":
        raise ValueError("unknown agent order")
    if row["status"] != "PENDING_APPROVAL":
        raise ValueError(f"order is {row['status']}, expected PENDING_APPROVAL")
    d = client.capture_order(row["paypal_order_id"])
    cap = d["purchase_units"][0]["payments"]["captures"][0]
    t = _now()
    conn.execute("UPDATE orders SET capture_id=?, status='COMPLETED' WHERE id=?", (cap["id"], row["id"]))
    conn.execute(
        "INSERT INTO shipments(order_id,carrier,tracking_number,shipped_at,delivered_at,delivery_status,data_origin)"
        " VALUES(?,?,?,?,?,?,?)",
        (row["id"], "UPS", "1Z999AA1%010d" % row["id"], _iso(t), _iso(t + datetime.timedelta(minutes=1)), "DELIVERED", "synthetic_demo"))
    conn.commit()
    amount = cap["amount"]
    trail.record(conn, order_ref, "payment", f"Payment captured, {amount['value']} {amount['currency_code']}",
                 {"capture_id": cap["id"], "paypal_order_id": row["paypal_order_id"]}, key=key)
    return {"order_ref": order_ref, "capture_id": cap["id"], "status": d.get("status")}


def main(argv):
    from dotenv import load_dotenv
    load_dotenv()
    from core.db import connect
    from core.paypal_client import PayPalClient, PayPalError
    conn, client = connect(), PayPalClient()
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "start":
            r = start_purchase(conn, client, " ".join(argv[2:]))
            if not r["ok"]:
                print(r["reason"])
                return
            print(f"Agent chose: {r['item']}, {r['amount']} USD | order {r['order_ref']} | PayPal order {r['paypal_order_id']}")
            print("Trail so far: intent, cart (signed). Sandbox buyer approval is required:")
            print("OPEN THIS LINK AS THE SANDBOX BUYER AND APPROVE:", r["approve_url"])
            print("Then run: python -m core.demo_agent finish")
        elif cmd == "finish":
            ref = argv[2] if len(argv) > 2 else latest_pending(conn)
            if not ref:
                print("No order is waiting for approval.")
                return
            r = finish_purchase(conn, client, ref)
            v = trail.verify_chain(conn, ref)
            print(f"Captured {r['capture_id']} for {r['order_ref']} | chain: {v['status']} ({v['events']} events)")
        else:
            print('usage: python -m core.demo_agent start "buy a desk lamp under 60 dollars" | finish [ord:N]')
    except PayPalError as e:
        print("PayPal said no:", e, "\nIf this is ORDER_NOT_APPROVED, open the approval link as the buyer first.")
    except trail.MissingKey as e:
        print(e)


if __name__ == "__main__":
    main(sys.argv)
