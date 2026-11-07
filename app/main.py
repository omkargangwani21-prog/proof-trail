import datetime
import json
import os
from pathlib import Path

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from core.db import connect
from core.gateway import Gateway
from core.paypal_client import PayPalClient
from core.submitter import EXTRA_SCHEMA, NotApproved, NotSubmittable, approve, submit


templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app = FastAPI(title="ProofTrail")
ACTION_STATUSES = {"WAITING_FOR_SELLER_RESPONSE", "OPEN"}
SUBMITTED_STATUSES = {"SUBMITTED", "SUBMITTED_DRY_RUN"}
PAGES = {}
MODES = {"live-sandbox": "Live sandbox", "replay": "Replay"}
REASONS = {
    "MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "Item not received",
    "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": "Item not as described",
    "UNAUTHORISED": "Unauthorized transaction",
    "UNAUTHORIZED": "Unauthorized transaction",
    "CREDIT_NOT_PROCESSED": "Credit not processed",
    "DUPLICATE_TRANSACTION": "Duplicate transaction",
    "INCORRECT_AMOUNT": "Incorrect amount",
}
FIXTURES_ENABLED = os.environ.get("PT_ENV") == "development" and os.environ.get("PT_UI_FIXTURES") == "1"


def reason_label(code):
    return REASONS.get(code) or str(code).replace("_", " ").capitalize()


def open_db():
    conn = connect(os.environ.get("PT_DB") or None)
    conn.executescript(EXTRA_SCHEMA)
    return conn


def common(conn, active, dev_fixture=False):
    spent, cap = 0.0, 20.0
    if conn is not None:
        try:
            gw = Gateway(conn)
            spent, cap = float(gw.spent()), float(gw.hard)
        except Exception:
            pass
    mode = os.environ.get("PT_MODE", "live-sandbox")
    return {
        "active": active, "spent": spent, "cap": cap,
        "pct": min(100, round(100 * spent / cap)) if cap else 0,
        "mode": mode, "mode_label": MODES.get(mode, mode), "pages": PAGES,
        "dev_fixture": dev_fixture,
    }


def parse_ts(s):
    if not s:
        return None
    try:
        value = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)


def display_ts(value):
    parsed = parse_ts(value)
    if parsed is None:
        return "Date not provided"
    return parsed.strftime("%b %-d, %Y · %H:%M UTC")


def due_label(due_at, now=None):
    value = parse_ts(due_at)
    if value is None:
        return "Due date not provided", "neutral"
    now = now or datetime.datetime.now(datetime.timezone.utc)
    secs = (value - now).total_seconds()
    if secs < 0:
        return "Overdue", "removed"
    days = int(secs // 86400)
    if days >= 1:
        return f"Due in {days}d", ("review" if days <= 3 else "neutral")
    return f"Due in {max(1, int(secs // 3600))}h", "review"


def draft_state(draft):
    if draft is None:
        return "No draft", "neutral", "Review"
    status = draft["status"]
    if status == "SUBMITTED":
        return "Submitted to sandbox", "info", "View"
    if status == "SUBMITTED_DRY_RUN":
        return "Dry run complete", "info", "View"
    if status == "VERIFIED":
        return "Draft ready", "verified", "Review"
    if status == "ABSTAIN":
        return "Recommend accepting", "review", "Review"
    return status.replace("_", " ").capitalize(), "neutral", "Review"


def latest_draft(conn, pid):
    return conn.execute(
        "SELECT id,case_id,status,decision,payload_json,verification_json,created_at "
        "FROM draft_evidence WHERE paypal_dispute_id=? ORDER BY id DESC LIMIT 1", (pid,)
    ).fetchone()


def fixture_module():
    from app import dev_fixtures
    return dev_fixtures


def get_fixture(name):
    if not FIXTURES_ENABLED:
        return None
    fixtures = fixture_module()
    if name == "queue":
        return fixtures.queue_data()
    if name in {"verified", "abstain", "partial", "submitted"}:
        return fixtures.case_data(name)
    return None


def queue_row(d, draft, now=None):
    due, due_tone = due_label(d["due_at"], now)
    state, state_tone, cta = draft_state(draft)
    status = draft["status"] if draft else None
    is_action = d["status"] in ACTION_STATUSES and status not in SUBMITTED_STATUSES
    return {
        "pid": d["paypal_dispute_id"], "why": reason_label(d["reason"]),
        "reason": d["reason"], "status": d["status"],
        "amount": f"{d['amount_minor'] / 100:.2f} {d['currency']}",
        "due": due, "due_tone": due_tone, "state": state, "state_tone": state_tone,
        "cta": cta, "due_sort": d["due_at"] or "9999", "is_action": is_action,
    }


def error_context(request, active, message, dev_fixture=False):
    return common(None, active, dev_fixture) | {"state": "error", "error_message": message}


@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse("/disputes")


@app.get("/disputes", response_class=HTMLResponse)
async def disputes(request: Request, fixture: str | None = None):
    use_fixture = FIXTURES_ENABLED and fixture == "queue"
    if FIXTURES_ENABLED and fixture == "loading":
        ctx = common(None, "disputes", True) | {"state": "loading", "action": [], "other": []}
        return templates.TemplateResponse(request, "queue.html", ctx)
    if FIXTURES_ENABLED and fixture == "error":
        return templates.TemplateResponse(request, "queue.html", error_context(
            request, "disputes", "Disputes could not be loaded. Check the local database, then refresh.", True
        ) | {"action": [], "other": []})
    if FIXTURES_ENABLED and fixture == "empty":
        return templates.TemplateResponse(request, "queue.html", common(None, "disputes", True) | {
            "state": "empty", "action": [], "other": []
        })

    conn = None
    try:
        conn = open_db()
        if use_fixture:
            data = get_fixture("queue")
            action, other = data["action"], data["other"]
        else:
            action, other = [], []
            for dispute in conn.execute("SELECT * FROM disputes ORDER BY id DESC"):
                row = queue_row(dispute, latest_draft(conn, dispute["paypal_dispute_id"]))
                (action if row["is_action"] else other).append(row)
            action.sort(key=lambda row: row["due_sort"])
        ctx = common(conn, "disputes", use_fixture) | {
            "state": "success" if action or other else "empty", "action": action, "other": other,
        }
    except Exception:
        ctx = error_context(request, "disputes",
                            "Disputes could not be loaded. Check the local database, then refresh.", use_fixture) | {
            "action": [], "other": []
        }
    finally:
        if conn is not None:
            conn.close()
    return templates.TemplateResponse(request, "queue.html", ctx)


def source_records(conn, case_id):
    rows = conn.execute(
        "SELECT record_id,kind,content_json,untrusted FROM source_records WHERE case_id=? ORDER BY record_id",
        (case_id,),
    ).fetchall()
    records = {}
    for row in rows:
        records[row["record_id"]] = {
            "record_id": row["record_id"], "kind": row["kind"],
            "content": json.loads(row["content_json"]), "untrusted": bool(row["untrusted"]),
        }
    return records


def workspace_context(request, conn, dispute, draft, fixture_data=None):
    if fixture_data:
        d = fixture_data["dispute"]
        records = fixture_data["records"]
        verification = fixture_data.get("verification")
        payload = fixture_data.get("payload", [])
        partial = fixture_data.get("partial", False)
        draft_status = fixture_data.get("draft_status", "VERIFIED")
        dev_fixture = True
    else:
        d = dict(dispute)
        records = source_records(conn, draft["case_id"] if draft else _case_id(conn, d["paypal_dispute_id"]))
        verification = json.loads(draft["verification_json"]) if draft and draft["verification_json"] else None
        payload = json.loads(draft["payload_json"]) if draft and draft["payload_json"] else []
        partial = (not records or not any(r["kind"] == "order" for r in records.values()) or not any(r["kind"] == "shipment" for r in records.values()) or any(not ref.get("record") for item in (verification or {}).get("claims", []) for ref in item.get("claim", {}).get("source_refs", [])))
        draft_status = draft["status"] if draft else None
        dev_fixture = False

    timeline = []
    for record in records.values():
        content = record["content"]
        kind = record["kind"]
        if kind == "order":
            timeline.append({"key": "order", "label": "Order placed", "at": display_ts(content.get("created_at")),
                             "detail": f"{content.get('amount', '')} · {content.get('status', 'Status unavailable').replace('_', ' ').lower()}"})
        elif kind == "shipment":
            timeline.append({"key": "shipment", "label": "Shipment sent", "at": display_ts(content.get("shipped_at")),
                             "detail": f"{content.get('carrier') or 'Carrier unavailable'} · {content.get('tracking_number') or 'Tracking unavailable'}"})
            if content.get("delivered_at") or content.get("delivery_status") == "DELIVERED":
                timeline.append({"key": "delivery", "label": "Delivery recorded", "at": display_ts(content.get("delivered_at")),
                                 "detail": content.get("delivery_status", "Delivery status unavailable").replace("_", " ").lower()})
        elif kind == "dispute":
            timeline.append({"key": "dispute", "label": "Dispute opened", "at": display_ts(content.get("created_at") or d.get("created_at")),
                             "detail": reason_label(content.get("reason", d.get("reason", "Dispute")))})
    timeline.sort(key=lambda event: {"order": 0, "shipment": 1, "delivery": 2, "dispute": 3}.get(event["key"], 4))
    if not any(event["key"] == "dispute" for event in timeline):
        timeline.append({"key": "dispute", "label": "Dispute opened", "at": display_ts(d.get("created_at")),
                         "detail": reason_label(d.get("reason", "Dispute"))})

    claims = verification.get("claims", []) if verification else []
    normalized_claims = []
    for item in claims:
        claim = item.get("claim", {})
        refs = claim.get("source_refs", [])
        normalized_claims.append({
            "id": claim.get("claim_id", "Claim"), "text": claim.get("text", ""),
            "verdict": item.get("verdict", "NEEDS_REVIEW"), "reasons": item.get("reasons", []),
            "refs": [{**ref, "record": records.get(ref.get("record_id"))} for ref in refs],
        })
    counts = {v: sum(1 for claim in normalized_claims if claim["verdict"] == v)
              for v in ("VERIFIED", "NEEDS_REVIEW", "REMOVED")}
    submitted = draft_status in SUBMITTED_STATUSES
    missing = (verification or {}).get("missing_evidence", [])
    consistency = (verification or {}).get("consistency_issues", [])
    reasons = (verification or {}).get("recommendation")
    conn_common = common(conn, "disputes", dev_fixture)
    return conn_common | {
        "state": "partial" if partial else "success", "d": d, "due_display": display_ts(d.get("due_at")) if d.get("due_at") else "Not provided",
        "why": reason_label(d.get("reason", "Dispute")), "timeline": timeline,
        "records": records, "record_json": json.dumps(records, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"),
        "messages": [r["content"].get("text", "") for r in records.values() if r["kind"] == "buyer_message"],
        "verification": verification, "claims": normalized_claims, "counts": counts,
        "missing": missing, "consistency": consistency, "recommendation": reasons,
        "payload": payload, "payload_text": json.dumps(payload, indent=2, ensure_ascii=False),
        "draft_id": draft["id"] if draft else fixture_data.get("draft_id") if fixture_data else None,
        "draft_status": draft_status, "submitted": submitted,
        "is_abstain": (verification or {}).get("decision") == "ABSTAIN",
        "partial_message": "One or more source records are unavailable. Refresh after the case has been rebuilt.",
        "success_message": ("Dry run complete. No request was sent to PayPal." if draft_status == "SUBMITTED_DRY_RUN"
                            else "Submitted to PayPal sandbox." if draft_status == "SUBMITTED" else None),
        "error_message": request.query_params.get("error"),
    }


def _case_id(conn, pid):
    row = conn.execute("SELECT c.id FROM cases c JOIN disputes d ON d.id=c.dispute_id "
                       "WHERE d.paypal_dispute_id=? ORDER BY c.id DESC LIMIT 1", (pid,)).fetchone()
    return row["id"] if row else -1


@app.get("/disputes/{pid}", response_class=HTMLResponse)
async def dispute_workspace(request: Request, pid: str, fixture: str | None = None):
    fixture_data = get_fixture(fixture) if FIXTURES_ENABLED and fixture in {"verified", "abstain", "partial", "submitted"} else None
    if fixture_data:
        ctx = workspace_context(request, None, fixture_data["dispute"], None, fixture_data)
        return templates.TemplateResponse(request, "workspace.html", ctx)
    if FIXTURES_ENABLED and fixture == "loading":
        return templates.TemplateResponse(request, "workspace.html", common(None, "disputes", True) | {
            "state": "loading", "d": {"paypal_dispute_id": pid, "amount_minor": 0, "currency": "USD"},
            "why": "Loading dispute", "timeline": [], "records": {}, "record_json": "{}", "messages": [],
            "claims": [], "counts": {"VERIFIED": 0, "NEEDS_REVIEW": 0, "REMOVED": 0},
            "missing": [], "consistency": [], "payload": [], "payload_text": "[]", "draft_id": None,
            "draft_status": None, "submitted": False, "is_abstain": False, "verification": None,
            "partial": False,
        })
    if FIXTURES_ENABLED and fixture == "error":
        return templates.TemplateResponse(request, "workspace.html", error_context(
            request, "disputes", "This case could not be loaded. Return to disputes and try again.", True
        ) | {"d": {"paypal_dispute_id": pid}, "why": "Dispute unavailable", "timeline": [], "records": {},
             "record_json": "{}", "messages": [], "claims": [], "counts": {"VERIFIED": 0, "NEEDS_REVIEW": 0, "REMOVED": 0},
             "missing": [], "consistency": [], "payload": [], "payload_text": "[]", "submitted": False})

    conn = None
    try:
        conn = open_db()
        dispute = conn.execute("SELECT * FROM disputes WHERE paypal_dispute_id=?", (pid,)).fetchone()
        if not dispute:
            return templates.TemplateResponse(request, "workspace.html", {
                **common(conn, "disputes"), "state": "empty", "d": {"paypal_dispute_id": pid},
                "why": "Dispute not found", "timeline": [], "records": {}, "record_json": "{}", "messages": [],
                "claims": [], "counts": {"VERIFIED": 0, "NEEDS_REVIEW": 0, "REMOVED": 0}, "missing": [],
                "consistency": [], "payload": [], "payload_text": "[]", "submitted": False,
                "empty_message": "This dispute is not in the local case file. Return to disputes and refresh the list.",
            }, status_code=404)
        draft = latest_draft(conn, pid)
        ctx = workspace_context(request, conn, dispute, draft)
    except Exception:
        ctx = error_context(request, "disputes", "This case could not be loaded. Return to disputes and try again.") | {
            "d": {"paypal_dispute_id": pid}, "why": "Dispute unavailable", "timeline": [], "records": {},
            "record_json": "{}", "messages": [], "claims": [], "counts": {"VERIFIED": 0, "NEEDS_REVIEW": 0, "REMOVED": 0},
            "missing": [], "consistency": [], "payload": [], "payload_text": "[]", "submitted": False,
        }
    finally:
        if conn is not None:
            conn.close()
    return templates.TemplateResponse(request, "workspace.html", ctx)


@app.post("/disputes/{pid}/submit")
async def submit_dry_run(request: Request, pid: str, draft_id: int = Form(...), approved: str | None = Form(None)):
    if approved != "yes":
        return RedirectResponse(f"/disputes/{pid}?error=Approval+is+required+before+a+dry+run.", status_code=303)
    conn = open_db()
    try:
        row = conn.execute("SELECT id,paypal_dispute_id,status FROM draft_evidence WHERE id=? AND paypal_dispute_id=?",
                           (draft_id, pid)).fetchone()
        if not row:
            return RedirectResponse(f"/disputes/{pid}?error=This+draft+is+no+longer+available.", status_code=303)
        if row["status"] in SUBMITTED_STATUSES:
            return RedirectResponse(f"/disputes/{pid}?error=This+draft+has+already+been+submitted.", status_code=303)
        approve(conn, draft_id, actor="merchant", note="Approved from ProofTrail sandbox dry-run dialog")
        submit(conn, PayPalClient(), draft_id, dry_run=True, actor="merchant")
    except (NotApproved, NotSubmittable, Exception):
        conn.rollback()
        return RedirectResponse(f"/disputes/{pid}?error=The dry run failed. Check the draft, then try again.", status_code=303)
    finally:
        conn.close()
    return RedirectResponse(f"/disputes/{pid}", status_code=303)



