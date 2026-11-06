import json, hashlib, datetime

EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS draft_evidence(
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER, paypal_dispute_id TEXT, decision TEXT,
  payload_json TEXT, verification_json TEXT, status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS approvals(
  id INTEGER PRIMARY KEY AUTOINCREMENT, draft_id INTEGER, actor TEXT, decision TEXT, note TEXT,
  payload_hash TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS submissions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, draft_id INTEGER, mode TEXT, payload_hash TEXT,
  response_json TEXT, submitted_at TEXT);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT, action TEXT, entity TEXT, entity_id TEXT,
  detail_json TEXT, at TEXT);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""


class NotApproved(Exception):
    pass


class NotSubmittable(Exception):
    pass


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def phash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def audit(conn, actor, action, entity, entity_id, detail=None):
    conn.execute("INSERT INTO audit_log(actor,action,entity,entity_id,detail_json,at) VALUES(?,?,?,?,?,?)",
                 (actor, action, entity, str(entity_id), json.dumps(detail or {}), _now()))


def build_payload(bundle, verification):
    """PayPal evidences list built from VERIFIED claims only. None if we are not contesting."""
    if verification["decision"] != "CONTEST":
        return None
    recs = {r["record_id"]: r for r in bundle["records"]}
    verified = [x["claim"] for x in verification["claims"] if x["verdict"] == "VERIFIED"]
    tracking, seen = [], set()
    for c in verified:
        for r in c.source_refs:
            rec = recs[r.record_id]
            if rec["kind"] == "shipment":
                key = (rec["content"]["carrier"], rec["content"]["tracking_number"])
                if key not in seen:
                    seen.add(key)
                    tracking.append({"carrier_name": key[0], "tracking_number": key[1]})
    notes = " ".join(c.text for c in verified)[:2000]
    return [{"evidence_type": "PROOF_OF_FULFILLMENT", "evidence_info": {"tracking_info": tracking}, "notes": notes}]


def save_draft(conn, bundle, verification):
    conn.executescript(EXTRA_SCHEMA)
    payload = build_payload(bundle, verification)
    ver = {"decision": verification["decision"], "recommendation": verification["recommendation"],
           "missing_evidence": verification["missing_evidence"], "l3_ran": verification["l3_ran"],
           "consistency_issues": verification.get("consistency_issues", []),
           "claims": [{"claim": x["claim"].model_dump(), "verdict": x["verdict"], "reasons": x["reasons"]}
                      for x in verification["claims"]]}
    case_id = int(bundle["case_id"].split("_")[1])
    status = "VERIFIED" if payload else verification["decision"]
    cur = conn.execute(
        "INSERT INTO draft_evidence(case_id,paypal_dispute_id,decision,payload_json,verification_json,status,created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (case_id, bundle["dispute"]["content"]["paypal_dispute_id"], verification["decision"],
         json.dumps(payload), json.dumps(ver), status, _now()))
    audit(conn, "system", "draft_saved", "draft", cur.lastrowid, {"decision": verification["decision"]})
    conn.commit()
    return cur.lastrowid


def _draft(conn, draft_id):
    row = conn.execute("SELECT * FROM draft_evidence WHERE id=?", (draft_id,)).fetchone()
    if not row:
        raise NotSubmittable("draft not found")
    payload = json.loads(row["payload_json"])
    if not payload:
        raise NotSubmittable("nothing to submit (decision is %s)" % row["decision"])
    return row, payload


def approve(conn, draft_id, actor, note=""):
    row, payload = _draft(conn, draft_id)
    h = phash(payload)
    conn.execute("INSERT INTO approvals(draft_id,actor,decision,note,payload_hash,at) VALUES(?,?,?,?,?,?)",
                 (draft_id, actor, "APPROVED", note, h, _now()))
    audit(conn, actor, "approved", "draft", draft_id, {"payload_hash": h, "note": note})
    conn.commit()
    return h


def submit(conn, client, draft_id, dry_run=True, actor="system"):
    row, payload = _draft(conn, draft_id)
    h = phash(payload)
    appr = conn.execute("SELECT * FROM approvals WHERE draft_id=? AND decision='APPROVED' ORDER BY id DESC LIMIT 1",
                        (draft_id,)).fetchone()
    if not appr or appr["payload_hash"] != h:
        audit(conn, actor, "submit_blocked", "draft", draft_id, {"reason": "no valid approval"})
        conn.commit()
        raise NotApproved("no approval matching the current payload")
    res = client.provide_evidence(row["paypal_dispute_id"], payload, dry_run=dry_run)
    mode = "dry_run" if dry_run else "sandbox"
    conn.execute("INSERT INTO submissions(draft_id,mode,payload_hash,response_json,submitted_at) VALUES(?,?,?,?,?)",
                 (draft_id, mode, h, json.dumps(res), _now()))
    conn.execute("UPDATE draft_evidence SET status=? WHERE id=?",
                 ("SUBMITTED_DRY_RUN" if dry_run else "SUBMITTED", draft_id))
    audit(conn, actor, "submitted_" + mode, "draft", draft_id, {"payload_hash": h})
    conn.commit()
    return res
