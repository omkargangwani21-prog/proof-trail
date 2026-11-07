"""Tamper-evident trail of an agent purchase: intent -> cart -> payment.
Each event stores the hash of the previous event and an HMAC signature. Tamper-evident, not tamper-proof:
whoever holds the key can forge a chain, and deleting the LAST event is only detectable if the head hash is kept elsewhere."""
import copy, datetime, hashlib, hmac, json, os

SCHEMA = """CREATE TABLE IF NOT EXISTS trail_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_ref TEXT NOT NULL, seq INTEGER NOT NULL, event TEXT NOT NULL,
  summary TEXT NOT NULL, payload_json TEXT NOT NULL, event_at TEXT NOT NULL, prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL, sig TEXT NOT NULL, UNIQUE(order_ref, seq))"""
ORDER = ["intent", "cart", "payment"]
GENESIS = "0" * 64
FIELDS = ("order_ref", "seq", "event", "summary", "payload", "event_at", "prev_hash")


class MissingKey(Exception):
    pass


def _key(key=None):
    k = key or os.environ.get("TRAIL_HMAC_KEY") or os.environ.get("PT_HMAC_KEY")
    if not k:
        raise MissingKey("set TRAIL_HMAC_KEY in .env (any long random string)")
    return k.encode() if isinstance(k, str) else k


def ensure(conn):
    conn.execute(SCHEMA)


def event_hash(e):
    body = {k: e[k] for k in FIELDS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sign(h, key):
    return hmac.new(key, h.encode(), hashlib.sha256).hexdigest()


def record(conn, order_ref, event, summary, payload=None, key=None, at=None):
    ensure(conn)
    k = _key(key)
    last = conn.execute("SELECT seq, hash FROM trail_events WHERE order_ref=? ORDER BY seq DESC LIMIT 1",
                        (order_ref,)).fetchone()
    seq = last["seq"] + 1 if last else 1
    expected = ORDER[seq - 1] if seq <= len(ORDER) else None
    if event != expected:
        raise ValueError(f"event {seq} must be {expected!r}, got {event!r}")
    e = {"order_ref": order_ref, "seq": seq, "event": event, "summary": summary, "payload": payload or {},
         "event_at": at or datetime.datetime.now(datetime.timezone.utc).isoformat(),
         "prev_hash": last["hash"] if last else GENESIS}
    e["hash"] = event_hash(e)
    e["sig"] = sign(e["hash"], k)
    cur = conn.execute(
        "INSERT INTO trail_events(order_ref,seq,event,summary,payload_json,event_at,prev_hash,hash,sig) VALUES(?,?,?,?,?,?,?,?,?)",
        (order_ref, seq, event, summary, json.dumps(e["payload"], sort_keys=True), e["event_at"], e["prev_hash"], e["hash"], e["sig"]))
    conn.commit()
    return {"id": cur.lastrowid, "seq": seq, "hash": e["hash"]}


def load_events(conn, order_ref):
    ensure(conn)
    out = []
    for r in conn.execute("SELECT * FROM trail_events WHERE order_ref=? ORDER BY seq", (order_ref,)):
        d = dict(r)
        d["payload"] = json.loads(d.pop("payload_json"))
        out.append(d)
    return out


def _broken(seq, reason):
    return {"status": "BROKEN", "events": None, "broken_at": seq, "reason": reason, "head": None}


def verify_events(events, key=None):
    if not events:
        return {"status": "EMPTY", "events": 0, "broken_at": None, "reason": "no events", "head": None}
    k = _key(key)
    prev = GENESIS
    for i, e in enumerate(events, start=1):
        if e["seq"] != i:
            return _broken(i, "an event is missing or out of order")
        if e["prev_hash"] != prev:
            return _broken(i, "link to the previous event does not match")
        h = event_hash(e)
        if h != e["hash"]:
            return _broken(i, "event content was changed")
        if not hmac.compare_digest(sign(h, k), e["sig"]):
            return _broken(i, "signature does not match")
        prev = e["hash"]
    return {"status": "VERIFIED", "events": len(events), "broken_at": None, "reason": "chain intact", "head": prev}


def verify_chain(conn, order_ref, key=None):
    try:
        return verify_events(load_events(conn, order_ref), key)
    except MissingKey as ex:
        return {"status": "UNVERIFIED", "events": None, "broken_at": None, "reason": str(ex), "head": None}


def tampered(events, seq, **changes):
    """A modified COPY, for the tamper demo. Never touches stored data."""
    out = copy.deepcopy(events)
    for e in out:
        if e["seq"] == seq:
            e.update(changes)
    return out


def trail_records(conn, order_ref, key=None):
    """Source records for the case bundle. chain_status is VERIFIED only if the whole chain verifies."""
    events = load_events(conn, order_ref)
    if not events:
        return []
    status = verify_chain(conn, order_ref, key)["status"]
    return [{"record_id": f"trl:{e['id']}", "kind": "trail_event", "untrusted": False,
             "content": {"order_ref": order_ref, "event": e["event"], "summary": e["summary"],
                         "event_at": e["event_at"], "chain_status": status}} for e in events]
