import json, hashlib, datetime


def _minor(v):
    return int(round(float(v) * 100))


def _money(m):
    return f"{m['value']} {m['currency_code']}"


def upsert_dispute(conn, d, origin="sandbox"):
    a = d["dispute_amount"]
    conn.execute(
        "INSERT INTO disputes(paypal_dispute_id,reason,status,stage,amount_minor,currency,due_at,raw_json,"
        "created_at,updated_at,origin) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(paypal_dispute_id) DO UPDATE SET reason=excluded.reason,status=excluded.status,"
        "stage=excluded.stage,due_at=excluded.due_at,raw_json=excluded.raw_json,updated_at=excluded.updated_at",
        (d["dispute_id"], d["reason"], d["status"], d["dispute_life_cycle_stage"], _minor(a["value"]),
         a["currency_code"], d.get("seller_response_due_date"), json.dumps(d), d.get("create_time"),
         d.get("update_time"), origin))
    did = conn.execute("SELECT id FROM disputes WHERE paypal_dispute_id=?", (d["dispute_id"],)).fetchone()["id"]
    for m in d.get("messages", []):
        conn.execute("INSERT OR IGNORE INTO dispute_messages(dispute_id,author_role,text,posted_at,untrusted)"
                     " VALUES(?,?,?,?,1)",
                     (did, m.get("posted_by"), m.get("content"), m.get("time_posted")))
    return did


def build_case(conn, d, origin="sandbox"):
    did = upsert_dispute(conn, d, origin)
    records = [{"record_id": f"dsp:{did}", "kind": "dispute", "untrusted": False, "content": {
        "paypal_dispute_id": d["dispute_id"], "reason": d["reason"], "status": d["status"],
        "stage": d["dispute_life_cycle_stage"], "amount": _money(d["dispute_amount"]),
        "due_at": d.get("seller_response_due_date")}}]

    order = None
    for t in d.get("disputed_transactions", []):
        order = conn.execute("SELECT * FROM orders WHERE capture_id=?", (t.get("seller_transaction_id"),)).fetchone()
        if order:
            break
    if order:
        items = [dict(r) for r in conn.execute(
            "SELECT sku,name,qty,unit_minor FROM order_items WHERE order_id=?", (order["id"],))]
        records.append({"record_id": f"ord:{order['id']}", "kind": "order", "untrusted": False, "content": {
            "paypal_order_id": order["paypal_order_id"], "capture_id": order["capture_id"],
            "amount": f"{order['amount_minor'] / 100:.2f} {order['currency']}", "status": order["status"],
            "created_at": order["created_at"], "items": items}})
        for s in conn.execute("SELECT * FROM shipments WHERE order_id=?", (order["id"],)):
            records.append({"record_id": f"shp:{s['id']}", "kind": "shipment", "untrusted": False, "content": {
                "carrier": s["carrier"], "tracking_number": s["tracking_number"], "shipped_at": s["shipped_at"],
                "delivered_at": s["delivered_at"], "delivery_status": s["delivery_status"],
                "data_origin": s["data_origin"]}})
    if order:
        from core.trail import trail_records
        records += trail_records(conn, f"ord:{order['id']}")
    pol = conn.execute("SELECT * FROM policies ORDER BY effective_from DESC, id DESC LIMIT 1").fetchone()
    if pol:
        records.append({"record_id": f"pol:{pol['id']}", "kind": "policy", "untrusted": False,
                        "content": {"version": pol["version"], "text": pol["text"]}})
    for m in conn.execute("SELECT * FROM dispute_messages WHERE dispute_id=? ORDER BY id", (did,)):
        records.append({"record_id": f"msg:{m['id']}", "kind": "buyer_message", "untrusted": True,
                        "content": {"author": m["author_role"], "text": m["text"]}})

    required = [e["evidence_type"] for e in d.get("evidences", []) if e.get("source") == "REQUESTED_FROM_SELLER"]
    h = hashlib.sha256(json.dumps({"records": records, "required": required}, sort_keys=True).encode()).hexdigest()

    old = conn.execute("SELECT id FROM cases WHERE dispute_id=?", (did,)).fetchone()
    if old:
        conn.execute("DELETE FROM source_records WHERE case_id=?", (old["id"],))
        conn.execute("DELETE FROM cases WHERE id=?", (old["id"],))
    cid = conn.execute("INSERT INTO cases(dispute_id,built_at,bundle_hash) VALUES(?,?,?)",
                       (did, datetime.datetime.now(datetime.timezone.utc).isoformat(), h)).lastrowid
    for r in records:
        conn.execute("INSERT INTO source_records(record_id,case_id,kind,content_json,untrusted) VALUES(?,?,?,?,?)",
                     (r["record_id"], cid, r["kind"], json.dumps(r["content"]), int(r["untrusted"])))
    conn.commit()
    return {"case_id": f"c_{cid}", "bundle_hash": h, "dispute": records[0], "records": records,
            "required_evidence": required}
