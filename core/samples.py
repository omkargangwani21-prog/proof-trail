"""Labelled synthetic sample disputes, so the demo list is not empty.

Cases come from the DEV split only (never test). They are stored with origin='synthetic_sample' through the
same build_case path real disputes use. Only the response deadline is re-dated (so it is in the future).
Usage: python -m core.samples [--draft]
"""
import datetime
import json
import sqlite3
import sys

from core.case_builder import build_case
from core.db import connect

ORIGIN = "synthetic_sample"
CASES = "eval/cases/dev.jsonl"
PLAN = (("clean", 2), ("missing", 1), ("conflicting", 2), ("injection", 2), ("partial", 1))
DUE_DAYS = (4, 6, 9, 11, 13, 14, 16, 18)
REQUESTED = [{"evidence_type": "PROOF_OF_FULFILLMENT", "source": "REQUESTED_FROM_SELLER"}]


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _minor(amount):
    return int(round(float(amount.split()[0]) * 100))


def read_cases(path=CASES):
    out = []
    for line in open(path):
        if line.strip():
            c = json.loads(line)
            if c.get("split") != "dev":
                raise ValueError(f"{c.get('id')}: only dev-split cases may be used as samples")
            out.append(c)
    return out


def pick(cases, plan=PLAN):
    chosen = []
    for cat, n in plan:
        pool = [c for c in cases if c["category"] == cat]
        out, seen = [], set()
        for c in pool:
            if c["variant"] not in seen and len(out) < n:
                seen.add(c["variant"])
                out.append(c)
        for c in pool:
            if len(out) >= n:
                break
            if c not in out:
                out.append(c)
        chosen += out
    return chosen


def load_sample(conn, case, idx, now=None):
    """Insert one sample. Returns its PayPal-style dispute id, or None if it is already there."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    recs = {}
    for r in case["bundle"]["records"]:
        recs.setdefault(r["kind"], []).append(r["content"])
    dsp, order = recs["dispute"][0], recs["order"][0]
    if conn.execute("SELECT 1 FROM disputes WHERE paypal_dispute_id=?", (dsp["paypal_dispute_id"],)).fetchone():
        return None
    if not conn.execute("SELECT 1 FROM policies").fetchone() and recs.get("policy"):
        p = recs["policy"][0]
        conn.execute("INSERT INTO policies(version,text,effective_from) VALUES(?,?,?)",
                     (p["version"], p["text"], "2026-01-01"))
    cur = conn.execute(
        "INSERT OR IGNORE INTO orders(paypal_order_id,capture_id,buyer_ref,amount_minor,currency,status,created_at,origin)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (order["paypal_order_id"], order["capture_id"], "sample-buyer", _minor(order["amount"]),
         order["amount"].split()[1], order["status"], order["created_at"], ORIGIN))
    oid = conn.execute("SELECT id FROM orders WHERE capture_id=?", (order["capture_id"],)).fetchone()["id"]
    if cur.rowcount == 1:
        for it in order.get("items", []):
            conn.execute("INSERT INTO order_items(order_id,sku,name,qty,unit_minor) VALUES(?,?,?,?,?)",
                         (oid, it["sku"], it["name"], it["qty"], it["unit_minor"]))
        for s in recs.get("shipment", []):
            conn.execute(
                "INSERT INTO shipments(order_id,carrier,tracking_number,shipped_at,delivered_at,delivery_status,data_origin)"
                " VALUES(?,?,?,?,?,?,?)",
                (oid, s["carrier"], s["tracking_number"], s["shipped_at"], s["delivered_at"],
                 s["delivery_status"], s["data_origin"]))
    value, currency = dsp["amount"].split()
    created = now - datetime.timedelta(days=idx + 1, hours=3 * idx % 11)
    d = {
        "dispute_id": dsp["paypal_dispute_id"], "reason": dsp["reason"], "status": dsp["status"],
        "dispute_life_cycle_stage": dsp["stage"], "dispute_amount": {"value": value, "currency_code": currency},
        "seller_response_due_date": _iso(now + datetime.timedelta(days=DUE_DAYS[idx % len(DUE_DAYS)])),
        "create_time": _iso(created), "update_time": _iso(created),
        "disputed_transactions": [{"seller_transaction_id": order["capture_id"]}],
        "evidences": REQUESTED,
        "messages": [{"posted_by": m["author"], "content": m["text"], "time_posted": _iso(created)}
                     for m in recs.get("buyer_message", [])],
    }
    build_case(conn, d, origin=ORIGIN)
    return d["dispute_id"]


def load_all(conn, cases=None, now=None):
    cases = pick(read_cases()) if cases is None else cases
    new = [x for x in (load_sample(conn, c, i, now) for i, c in enumerate(cases)) if x]
    conn.commit()
    return new


def sample_ids(conn):
    return [r[0] for r in conn.execute("SELECT paypal_dispute_id FROM disputes WHERE origin=? ORDER BY id", (ORIGIN,))]


def has_draft(conn, pid):
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(draft_evidence)")]
        return any(conn.execute(f'SELECT 1 FROM draft_evidence WHERE "{c}"=? LIMIT 1', (pid,)).fetchone() for c in cols)
    except sqlite3.OperationalError:
        return False


def draft_all(conn):
    from core.drafting import draft_dispute
    from core.gateway import BudgetExceeded
    for pid in sample_ids(conn):
        if has_draft(conn, pid):
            print(pid, "already has a draft")
            continue
        try:
            print(pid, draft_dispute(conn, pid))
        except BudgetExceeded:
            print("budget guard stopped drafting")
            break
        except Exception as e:
            print(pid, "failed:", type(e).__name__, str(e)[:120])


def main(argv):
    from dotenv import load_dotenv
    load_dotenv(".env")
    conn = connect()
    new = load_all(conn)
    print(f"loaded {len(new)} new samples; {len(sample_ids(conn))} samples in the database")
    if "--draft" in argv:
        draft_all(conn)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
