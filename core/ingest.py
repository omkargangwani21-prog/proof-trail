"""How disputes get into ProofTrail: fetch by id, poll, or webhook. All paths end in ingest_dispute (GET by id)."""
import datetime, json
from core.case_builder import build_case, upsert_dispute
from core.paypal_client import PayPalError

SCHEMA = """CREATE TABLE IF NOT EXISTS webhook_events(
  event_id TEXT PRIMARY KEY, event_type TEXT, dispute_id TEXT, received_at TEXT, status TEXT)"""
HANDLED = {"CUSTOMER.DISPUTE.CREATED", "CUSTOMER.DISPUTE.UPDATED", "CUSTOMER.DISPUTE.RESOLVED"}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def ingest_dispute(conn, client, dispute_id, origin="sandbox"):
    d = client.get_dispute(dispute_id)
    did = upsert_dispute(conn, d, origin)
    if not conn.execute("SELECT 1 FROM cases WHERE dispute_id=?", (did,)).fetchone():
        build_case(conn, d, origin)  # records exist as soon as the dispute does; never rebuilt here, drafts point at the case
    conn.commit()
    return {"dispute_id": d["dispute_id"], "status": d["status"], "stage": d.get("dispute_life_cycle_stage")}


def refresh_known(conn, client, skip=()):
    done, errors = [], []
    ids = [r[0] for r in conn.execute("SELECT paypal_dispute_id FROM disputes WHERE origin='sandbox'")]
    for pid in ids:
        if pid in skip:
            continue
        try:
            done.append(ingest_dispute(conn, client, pid))
        except PayPalError as e:
            errors.append({"dispute_id": pid, "error": str(e)[:200]})
    return done, errors


def poll_once(conn, client):
    """The list endpoint can lag by many minutes (observed), so known disputes are always refreshed by id too."""
    items = (client.list_disputes() or {}).get("items") or []
    known = {r[0] for r in conn.execute("SELECT paypal_dispute_id FROM disputes")}
    new, errors = [], []
    for it in items:
        pid = it.get("dispute_id")
        if pid and pid not in known:
            try:
                new.append(ingest_dispute(conn, client, pid)["dispute_id"])
            except PayPalError as e:
                errors.append({"dispute_id": pid, "error": str(e)[:200]})
    refreshed, errs = refresh_known(conn, client, skip=set(new))
    return {"listed": len(items), "new": new, "refreshed": refreshed, "errors": errors + errs}


def _mark(conn, event, dispute_id, status):
    conn.execute("INSERT OR IGNORE INTO webhook_events(event_id,event_type,dispute_id,received_at,status) VALUES(?,?,?,?,?)",
                 (event["id"], event.get("event_type"), dispute_id, _now(), status))
    conn.commit()


def handle_webhook(conn, client, headers, raw_body, webhook_id, verify=True):
    """Returns (http_status, body). A fetch failure raises, so the caller answers 5xx and PayPal retries."""
    try:
        event = json.loads(raw_body)
    except ValueError:
        return 400, {"error": "body is not JSON"}
    if not isinstance(event, dict) or not event.get("id") or not event.get("event_type"):
        return 400, {"error": "not a PayPal event"}
    if verify:
        try:
            ok = client.verify_webhook_signature({k.lower(): v for k, v in headers.items()}, event, webhook_id)
        except PayPalError as e:
            return 503, {"error": "could not verify with PayPal", "detail": str(e)[:200]}
        if not ok:
            return 401, {"error": "signature check failed"}
    conn.execute(SCHEMA)
    if conn.execute("SELECT 1 FROM webhook_events WHERE event_id=?", (event["id"],)).fetchone():
        return 200, {"status": "duplicate"}
    et = event["event_type"]
    if et not in HANDLED:
        _mark(conn, event, None, "IGNORED")
        return 200, {"status": "ignored", "event_type": et}
    res = event.get("resource") or {}
    pid = res.get("dispute_id") or res.get("id")
    if not pid:
        _mark(conn, event, None, "NO_DISPUTE_ID")
        return 200, {"status": "no dispute id in event"}
    ingest_dispute(conn, client, pid)
    _mark(conn, event, pid, "DONE")
    return 200, {"status": "ingested", "dispute_id": pid}
