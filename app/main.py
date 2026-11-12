import datetime
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from core.db import connect
from core import trail
from core.paypal_client import PayPalClient, SANDBOX_BASE
from dotenv import load_dotenv
from app import ingest_api
from app.ingest_api import router as ingest_router
from app.draft_api import router as draft_router
from core.submitter import EXTRA_SCHEMA, NotApproved, NotSubmittable, approve, submit, phash


templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app = FastAPI(title="ProofTrail", lifespan=ingest_api.lifespan)
app.include_router(ingest_router)
app.include_router(draft_router)
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
EVAL_RESULTS_DIR = Path(__file__).resolve().parent.parent / "eval" / "results"
TRAIL_DEMO_KEY = "prooftrail-ui-sample-key"
TRAIL_DEMO_REF = "DEMO-TRAIL-001"



def evidence_type_label(value):
    known = {"PROOF_OF_REFUND": "Proof of refund", "PROOF_OF_FULFILLMENT": "Proof of fulfillment",
             "OTHER": "Other"}
    return known.get(str(value), str(value).replace("_", " ").capitalize())


def pluralize(count, singular, plural=None):
    return singular if count == 1 else (plural or f"{singular}s")


templates.env.globals["pluralize"] = pluralize


def source_bundle_partial(records, verification):
    if not records:
        return True
    if not any(record.get("kind") == "order" for record in records.values()):
        return True
    if not any(record.get("kind") == "shipment" for record in records.values()):
        return True
    return any(
        ref.get("record_id") not in records
        for item in (verification or {}).get("claims", [])
        for ref in item.get("claim", {}).get("source_refs", [])
    )

def reason_label(code):
    return REASONS.get(code) or str(code).replace("_", " ").capitalize()


def open_db():
    conn = connect(os.environ.get("PT_DB") or None)
    conn.executescript(EXTRA_SCHEMA)
    return conn


def configured_submit_mode():
    mode = os.environ.get("PT_MODE", "live-sandbox")
    requested = os.environ.get("PT_SUBMIT_MODE", "dry-run").strip().lower()
    if mode == "live-sandbox" and requested == "sandbox-submit":
        return "sandbox-submit"
    return "dry-run"


def common(conn, active, dev_fixture=False, force_dry_run=False):
    mode = os.environ.get("PT_MODE", "live-sandbox")
    submit_mode = "dry-run" if force_dry_run else configured_submit_mode()
    return {
        "active": active,
        "mode": mode, "mode_label": MODES.get(mode, mode), "pages": PAGES,
        "submit_mode": submit_mode,
        "submit_mode_label": "Sandbox submission" if submit_mode == "sandbox-submit" else "Dry run",
        "action_label": "Review and submit to PayPal sandbox" if submit_mode == "sandbox-submit" else "Review and submit (dry run)",
        "confirmation_title": "Review sandbox submission" if submit_mode == "sandbox-submit" else "Review before dry run",
        "confirmation_note": "PayPal sandbox will receive the approved evidence." if submit_mode == "sandbox-submit" else "No request will be sent.",
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
    parsed = parsed.astimezone(datetime.timezone.utc)
    return parsed.strftime("%b %d, %H:%M UTC").replace(" 0", " ")


PAYPAL_STATUSES = {
    "WAITING_FOR_SELLER_RESPONSE": "Waiting for your response",
    "WAITING_FOR_BUYER_RESPONSE": "Waiting for the buyer's response",
    "UNDER_REVIEW": "Under PayPal review",
    "OPEN": "Open",
    "RESOLVED": "Resolved",
    "OTHER": "Other",
    "EXPIRED": "Expired",
}


def paypal_status_label(code):
    if not code:
        return "Status unavailable"
    return PAYPAL_STATUSES.get(str(code), "Other PayPal status")


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
        return "Not contesting", "review", "Review"
    return status.replace("_", " ").capitalize(), "neutral", "Review"


DECISION_REASON_TAGS = {
    "consistency": "records conflict",
    "missing_evidence": "evidence missing",
    "model_abstained": "model abstained",
    "model_recommended_accept": "model recommended accept",
}


def decision_reason_tag(draft):
    if not draft or draft["status"] != "ABSTAIN" or not draft["verification_json"]:
        return None
    try:
        reasons = json.loads(draft["verification_json"]).get("decision_reasons", [])
    except (TypeError, ValueError, AttributeError):
        return None
    return next((DECISION_REASON_TAGS[reason] for reason in reasons if reason in DECISION_REASON_TAGS), None)


def decision_reason_lines(verification, missing_labels):
    lines = []
    for reason in (verification or {}).get("decision_reasons", []):
        if reason == "consistency":
            lines.append({"text": "The records contradict each other, so ProofTrail did not contest.",
                          "issues": (verification or {}).get("consistency_issues", [])})
        elif reason == "missing_evidence":
            missing = ", ".join(missing_labels) if missing_labels else "not specified"
            lines.append({"text": f"Required evidence is missing: {missing}.", "issues": []})
        elif reason == "model_abstained":
            lines.append({"text": "The model chose not to contest.", "issues": []})
        elif reason == "model_recommended_accept":
            lines.append({"text": "The model recommended accepting the claim.", "issues": []})
    return lines


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
    if name == "unauthorised":
        return fixtures.unauthorised_case_data()
    if name in {"verified", "abstain", "partial", "submitted", "before"}:
        return fixtures.case_data(name)
    return None


def queue_row(d, draft, now=None):
    due, due_tone = due_label(d["due_at"], now)
    state, state_tone, cta = draft_state(draft)
    status = draft["status"] if draft else None
    is_action = d["status"] in ACTION_STATUSES and status not in SUBMITTED_STATUSES
    return {
        "pid": d["paypal_dispute_id"], "why": reason_label(d["reason"]),
        "reason": d["reason"], "status": paypal_status_label(d["status"]),
        "amount": f"{d['amount_minor'] / 100:.2f} {d['currency']}",
        "due": due, "due_tone": due_tone, "state": state, "state_tone": state_tone,
        "cta": cta, "due_sort": d["due_at"] or "9999", "is_action": is_action,
        "origin": d["origin"] or "sandbox", "is_sample": d["origin"] == "synthetic_sample",
        "is_abstain": status == "ABSTAIN", "reason_tag": decision_reason_tag(draft),
    }


def error_context(request, active, message, dev_fixture=False):
    return common(None, active, dev_fixture) | {"state": "error", "error_message": message}


DRAFT_FEEDBACK = {
    "ok": ("Draft ready. Review each claim before approving.", "success"),
    "failed": ("The model did not return a usable draft. Nothing was saved. Try again.", "error"),
    "notready": ("This dispute is not waiting for your response.", "error"),
    "budget": ("Drafting is paused: the model usage limit has been reached.", "error"),
    "error": ("Something went wrong while drafting. Nothing was saved.", "error"),
    "busy": ("Drafting is already in progress for this dispute. Wait for it to finish.", "partial"),
    "replay": ("Replay mode is offline. Drafting is disabled in this demonstration.", "partial"),
}
QUEUE_DRAFT_FEEDBACK = {
    "invalid": "That dispute ID is not valid.",
    "notfound": "The dispute was not found.",
}
QUEUE_REFRESH_FEEDBACK = {
    "error": ("The dispute refresh failed. Check the PayPal connection, then try again.", "error"),
    "partial": ("Some disputes could not be refreshed. Review the list and try again.", "partial"),
    "done": ("Disputes refreshed.", "success"),
    "replay": ("PayPal refresh is disabled in offline replay mode.", "partial"),
}


def draft_feedback(request, queue=False):
    value = request.query_params.get("draft", "")
    if queue:
        message = QUEUE_DRAFT_FEEDBACK.get(value)
        return {"draft_feedback": message, "draft_feedback_tone": "error"} if message else {}
    result = DRAFT_FEEDBACK.get(value)
    return {"draft_feedback": result[0], "draft_feedback_tone": result[1]} if result else {}


@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse("/disputes?fixture=queue" if os.environ.get("PT_MODE") == "replay" else "/disputes")


@app.get("/disputes", response_class=HTMLResponse)
async def disputes(request: Request, fixture: str | None = None, filter: str = "all"):
    if filter not in {"all", "sandbox", "samples"}:
        filter = "all"
    use_fixture = FIXTURES_ENABLED and (fixture == "queue" or os.environ.get("PT_MODE") == "replay")
    if FIXTURES_ENABLED and fixture == "loading":
        ctx = common(None, "disputes", True) | {"state": "loading", "action": [], "other": [], "queue_filter": filter}
        return templates.TemplateResponse(request, "queue.html", ctx)
    if FIXTURES_ENABLED and fixture == "error":
        return templates.TemplateResponse(request, "queue.html", error_context(
            request, "disputes", "Disputes could not be loaded. Check the local database, then refresh.", True
        ) | {"action": [], "other": []})
    if FIXTURES_ENABLED and fixture == "empty":
        return templates.TemplateResponse(request, "queue.html", common(None, "disputes", True) | {
            "state": "empty", "action": [], "other": [], "queue_filter": filter
        })

    conn = None
    try:
        conn = open_db()
        if use_fixture:
            data = get_fixture("queue")
            action, other = data["action"], data["other"]
            for row in action + other:
                row["origin"] = "synthetic_sample" if row["pid"] == "PP-DEV-1002" else "sandbox"
                row["is_sample"] = row["origin"] == "synthetic_sample"
            if filter == "sandbox":
                action, other = ([r for r in action if not r["is_sample"]],
                                 [r for r in other if not r["is_sample"]])
            elif filter == "samples":
                action, other = ([r for r in action if r["is_sample"]],
                                 [r for r in other if r["is_sample"]])
        else:
            action, other = [], []
            for dispute in conn.execute("SELECT * FROM disputes ORDER BY id DESC"):
                if filter == "sandbox" and dispute["origin"] != "sandbox":
                    continue
                if filter == "samples" and dispute["origin"] != "synthetic_sample":
                    continue
                row = queue_row(dispute, latest_draft(conn, dispute["paypal_dispute_id"]))
                (action if row["is_action"] else other).append(row)
            action.sort(key=lambda row: row["due_sort"])
        ctx = common(conn, "disputes", use_fixture) | {
            "state": "success" if action or other else "empty", "action": action, "other": other,
            "queue_filter": filter if filter in {"all", "sandbox", "samples"} else "all",
        } | draft_feedback(request, queue=True)
        refresh_feedback = QUEUE_REFRESH_FEEDBACK.get(request.query_params.get("refresh", ""))
        if refresh_feedback:
            ctx.update({"refresh_feedback": refresh_feedback[0], "refresh_feedback_tone": refresh_feedback[1]})
    except Exception:
        ctx = error_context(request, "disputes",
                            "Disputes could not be loaded. Check the local database, then refresh.", use_fixture) | {
                            "action": [], "other": [], "queue_filter": filter,
                            "refresh_feedback": QUEUE_REFRESH_FEEDBACK.get(request.query_params.get("refresh", ""), (None,))[0]
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
        partial = source_bundle_partial(records, verification)
        draft_status = draft["status"] if draft else None
        dev_fixture = False

    timeline = []
    for record in records.values():
        content = record["content"]
        kind = record["kind"]
        if kind == "order":
            timeline.append({"key": "order", "label": "Order placed", "at": display_ts(content.get("created_at")),
                             "detail": f"{content.get('amount', '')} · {content.get('status', 'Status unavailable').replace('_', ' ').capitalize()}"})
        elif kind == "shipment":
            timeline.append({"key": "shipment", "label": "Shipment sent", "at": display_ts(content.get("shipped_at")),
                             "detail": f"{content.get('carrier') or 'Carrier unavailable'} · {content.get('tracking_number') or 'Tracking unavailable'}"})
            if content.get("delivered_at") or content.get("delivery_status") == "DELIVERED":
                timeline.append({"key": "delivery", "label": "Delivery recorded", "at": display_ts(content.get("delivered_at")),
                                 "detail": content.get("delivery_status", "Delivery status unavailable").replace("_", " ").capitalize()})
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
    trail_order = {"intent": 0, "cart": 1, "payment": 2}
    trail_records = sorted((r for r in records.values() if r.get("kind") == "trail_event"),
                           key=lambda r: trail_order.get(r.get("content", {}).get("event"), 9))
    trail_events = [{"event": r["content"].get("event"),
                     "label": {"intent": "Intent recorded by agent", "cart": "Cart recorded", "payment": "Payment recorded"}.get(r["content"].get("event"), "Trail event recorded"),
                     "summary": r["content"].get("summary", "Summary unavailable"),
                     "at": display_ts(r["content"].get("event_at")),
                     "shopper_text": r["content"].get("event") == "intent"}
                    for r in trail_records]
    trail_states = {r.get("content", {}).get("chain_status") for r in trail_records}
    if trail_records and trail_states == {"VERIFIED"}:
        trail_chain_label = f"Chain intact, {len(trail_records)} {pluralize(len(trail_records), 'event')}"
    elif "BROKEN" in trail_states:
        trail_chain_label = "Trail chain check failed"
    elif trail_records:
        trail_chain_label = "Trail chain check unavailable"
    else:
        trail_chain_label = None
    submitted = draft_status in SUBMITTED_STATUSES
    has_draft = draft is not None or bool(fixture_data and fixture_data.get("draft_id")) or verification is not None
    replay_mode = os.environ.get("PT_MODE") == "replay"
    can_draft = not replay_mode and d.get("status") == "WAITING_FOR_SELLER_RESPONSE" and not has_draft
    can_redraft = not replay_mode and d.get("status") == "WAITING_FOR_SELLER_RESPONSE" and has_draft and not submitted
    missing = (verification or {}).get("missing_evidence", [])
    missing_labels = [evidence_type_label(item) for item in missing]
    requested_not_provided = [evidence_type_label(item) for item in (verification or {}).get("requested_not_provided", [])]
    consistency = (verification or {}).get("consistency_issues", [])
    reasons = (verification or {}).get("recommendation")
    decision_reasons = decision_reason_lines(verification, missing_labels) if verification and verification.get("decision") != "CONTEST" else []
    rationale = (verification or {}).get("rationale")
    rationale_limit = 240
    is_sample = d.get("origin") == "synthetic_sample"
    conn_common = common(conn, "disputes", dev_fixture, force_dry_run=is_sample)
    return conn_common | {
        "state": "partial" if partial else "success", "d": d, "is_sample": is_sample, "due_display": display_ts(d.get("due_at")) if d.get("due_at") else "Not provided",
        "why": reason_label(d.get("reason", "Dispute")), "status_label": paypal_status_label(d.get("status")), "timeline": timeline,
        "records": records, "record_json": json.dumps(records, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"),
        "messages": [r["content"].get("text", "") for r in records.values() if r["kind"] == "buyer_message"],
        "verification": verification, "claims": normalized_claims, "counts": counts,
        "missing": missing, "requested_not_provided": requested_not_provided,
        "missing_labels": missing_labels, "can_draft": can_draft, "can_redraft": can_redraft,
        "decision_reasons": decision_reasons,
        "decision_reason_not_recorded": bool(verification and verification.get("decision") != "CONTEST"
                                               and not verification.get("decision_reasons")),
        "rationale": rationale, "rationale_preview": rationale[:rationale_limit] if rationale else None,
        "rationale_truncated": bool(rationale and len(rationale) > rationale_limit),
        "consistency": consistency, "recommendation": reasons,
        "trail_events": trail_events, "trail_chain_label": trail_chain_label,
        "stage_label": str(d.get("stage") or "Not provided").replace("_", " ").title(),
        "payload": payload, "payload_text": json.dumps(payload, indent=2, ensure_ascii=False),
        "draft_id": draft["id"] if draft else fixture_data.get("draft_id") if fixture_data else None,
        "draft_status": draft_status, "submitted": submitted,
        "is_abstain": (verification or {}).get("decision") == "ABSTAIN",
        "partial_message": "One or more source records are unavailable. Refresh after the case has been rebuilt.",
        "success_message": ("Dry run complete. No request was sent to PayPal." if draft_status == "SUBMITTED_DRY_RUN"
                            else "Submitted to PayPal sandbox." if draft_status == "SUBMITTED" else None),
        "error_message": request.query_params.get("error"),
    } | draft_feedback(request)


def _case_id(conn, pid):
    row = conn.execute("SELECT c.id FROM cases c JOIN disputes d ON d.id=c.dispute_id "
                       "WHERE d.paypal_dispute_id=? ORDER BY c.id DESC LIMIT 1", (pid,)).fetchone()
    return row["id"] if row else -1


@app.get("/disputes/{pid}", response_class=HTMLResponse)
async def dispute_workspace(request: Request, pid: str, fixture: str | None = None):
    if FIXTURES_ENABLED and os.environ.get("PT_MODE") == "replay" and fixture is None:
        fixture = {"PP-DEV-1001": "verified", "PP-DEV-1002": "abstain"}.get(pid)
    fixture_data = get_fixture(fixture) if FIXTURES_ENABLED and fixture in {"verified", "abstain", "partial", "submitted", "unauthorised", "before"} else None
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
        } | draft_feedback(request))
    if FIXTURES_ENABLED and fixture == "error":
        return templates.TemplateResponse(request, "workspace.html", error_context(
            request, "disputes", "This case could not be loaded. Return to disputes and try again.", True
        ) | {"d": {"paypal_dispute_id": pid}, "why": "Dispute unavailable", "timeline": [], "records": {},
             "record_json": "{}", "messages": [], "claims": [], "counts": {"VERIFIED": 0, "NEEDS_REVIEW": 0, "REMOVED": 0},
             "missing": [], "consistency": [], "payload": [], "payload_text": "[]", "submitted": False} | draft_feedback(request))

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
                **draft_feedback(request),
            }, status_code=404)
        draft = latest_draft(conn, pid)
        ctx = workspace_context(request, conn, dispute, draft)
    except Exception:
        ctx = error_context(request, "disputes", "This case could not be loaded. Return to disputes and try again.") | {
            "d": {"paypal_dispute_id": pid}, "why": "Dispute unavailable", "timeline": [], "records": {},
            "record_json": "{}", "messages": [], "claims": [], "counts": {"VERIFIED": 0, "NEEDS_REVIEW": 0, "REMOVED": 0},
            "missing": [], "consistency": [], "payload": [], "payload_text": "[]", "submitted": False,
        } | draft_feedback(request)
    finally:
        if conn is not None:
            conn.close()
    return templates.TemplateResponse(request, "workspace.html", ctx)


@app.get("/disputes/{pid}/payload.json")
async def download_payload(pid: str, draft_id: int):
    conn = None
    try:
        conn = open_db()
        row = conn.execute(
            "SELECT payload_json FROM draft_evidence WHERE id=? AND paypal_dispute_id=?",
            (draft_id, pid),
        ).fetchone()
        if not row or not row["payload_json"]:
            return Response("Payload not found.", status_code=404, media_type="text/plain")
        payload = json.loads(row["payload_json"])
        if not payload:
            return Response("Payload not found.", status_code=404, media_type="text/plain")
        filename = re.sub(r"[^A-Za-z0-9_-]", "-", pid) + "-payload.json"
        return Response(
            json.dumps(payload, indent=2, ensure_ascii=False), media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except (OSError, json.JSONDecodeError, ValueError):
        return Response("Payload could not be read.", status_code=404, media_type="text/plain")
    finally:
        if conn is not None:
            conn.close()


@app.post("/disputes/{pid}/submit")
async def submit_dry_run(request: Request, pid: str, draft_id: int = Form(...), approved: str | None = Form(None)):
    dry_run = configured_submit_mode() == "dry-run"
    conn = open_db()
    try:
        dispute = conn.execute("SELECT origin FROM disputes WHERE paypal_dispute_id=?", (pid,)).fetchone()
        if not dispute:
            return RedirectResponse(f"/disputes/{pid}?error=Dispute+not+found.", status_code=303)
        # Generated samples must never reach PayPal, regardless of environment configuration.
        if dispute["origin"] != "sandbox":
            dry_run = True
        if approved != "yes":
            message = "Approval is required before a dry run." if dry_run else "Approval is required before sandbox submission."
            return RedirectResponse(f"/disputes/{pid}?error={message.replace(' ', '+')}", status_code=303)
        row = conn.execute("SELECT id,paypal_dispute_id,status FROM draft_evidence WHERE id=? AND paypal_dispute_id=?",
                           (draft_id, pid)).fetchone()
        if not row:
            return RedirectResponse(f"/disputes/{pid}?error=This+draft+is+no+longer+available.", status_code=303)
        if row["status"] in SUBMITTED_STATUSES:
            return RedirectResponse(f"/disputes/{pid}?error=This+draft+has+already+been+submitted.", status_code=303)
        approve(conn, draft_id, actor="merchant", note="Approved from ProofTrail dry-run dialog" if dry_run else "Approved from ProofTrail sandbox submission dialog")
        submit(conn, PayPalClient(), draft_id, dry_run=dry_run, actor="merchant")
    except (NotApproved, NotSubmittable, Exception):
        conn.rollback()
        message = "The dry run failed. Check the draft, then try again." if dry_run else "Sandbox submission failed. Check the draft, then try again."
        return RedirectResponse(f"/disputes/{pid}?error={message.replace(' ', '+')}", status_code=303)
    finally:
        conn.close()
    return RedirectResponse(f"/disputes/{pid}", status_code=303)





def trail_status_text(result):
    status = result.get("status")
    if status == "VERIFIED":
        count = result.get("events", 0)
        return f"Chain intact, {count} {pluralize(count, 'event')}"
    if status == "BROKEN":
        return f"Chain altered at event {result.get('broken_at')}: {result.get('reason', 'verification failed')}"
    if status == "EMPTY":
        return "No trail events to verify."
    return f"Chain check unavailable: {result.get('reason') or 'signing key unavailable'}"


def _demo_trail():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    events = (
        ("intent", "Shopper asked the agent: “Find an item connected to my request.”", "2026-11-06T09:02:00+00:00"),
        ("cart", "Cart contained one desk lamp for $84.50", "2026-11-06T09:02:04+00:00"),
        ("payment", "PayPal sandbox payment completed for $84.50", "2026-11-06T09:02:11+00:00"),
    )
    for event, summary, at in events:
        trail.record(conn, TRAIL_DEMO_REF, event, summary, {"sample": True}, key=TRAIL_DEMO_KEY, at=at)
    loaded = trail.load_events(conn, TRAIL_DEMO_REF)
    result = trail.verify_chain(conn, TRAIL_DEMO_REF, key=TRAIL_DEMO_KEY)
    conn.close()
    return loaded, result


def _trail_entries(events):
    return [{
        "seq": event["seq"],
        "event": event["event"],
        "label": {"intent": "Intent recorded by agent", "cart": "Cart recorded", "payment": "Payment recorded"}.get(event["event"], "Trail event recorded"),
        "summary": event["summary"],
        "shopper_text": event["event"] == "intent",
        "at": display_ts(event["event_at"]),
        "hash_prefix": str(event["hash"])[:12],
        "prev_hash_prefix": str(event["prev_hash"])[:12],
    } for event in events]


def _trail_page_context(request, order_ref=None, use_fixture=False, tamper_result=None, stored_result=None):
    if not use_fixture:
        load_dotenv()
    ctx = common(None, "trail", use_fixture)
    if use_fixture:
        events, result = _demo_trail()
        refs = [{"ref": TRAIL_DEMO_REF, "href": f"/trail?order_ref={quote(TRAIL_DEMO_REF)}&fixture=sample",
                 "count": len(events), "status": trail_status_text(result), "tone": result["status"]}]
        if order_ref and order_ref != TRAIL_DEMO_REF:
            events = []
    else:
        conn = open_db()
        try:
            trail.ensure(conn)
            if order_ref:
                events = trail.load_events(conn, order_ref)
                result = trail.verify_chain(conn, order_ref)
                refs = []
            else:
                rows = conn.execute("SELECT order_ref,COUNT(*) AS event_count FROM trail_events GROUP BY order_ref ORDER BY MAX(id) DESC").fetchall()
                refs = []
                for row in rows:
                    verification = trail.verify_chain(conn, row["order_ref"])
                    refs.append({"ref": row["order_ref"], "href": f"/trail?order_ref={quote(row['order_ref'])}",
                                 "count": row["event_count"], "status": trail_status_text(verification), "tone": verification["status"]})
                events, result = [], {"status": "EMPTY", "events": 0, "reason": "no events"}
        finally:
            conn.close()
    detail = bool(order_ref and events)
    if order_ref and not events:
        result = {"status": "EMPTY", "events": 0, "reason": "no events"}
    ctx |= {
        "state": "detail" if detail else ("empty" if not refs else "list"),
        "orders": refs,
        "order_ref": order_ref,
        "encoded_ref": quote(order_ref or "", safe=""),
        "events": _trail_entries(events),
        "chain_status": trail_status_text(result),
        "chain_tone": result.get("status", "EMPTY"),
        "tamper_result": tamper_result,
        "stored_result": trail_status_text(stored_result) if stored_result else None,
        "fixture_query": "?fixture=sample" if use_fixture else "",
        "empty_message": "No order trails yet. A completed demo-agent purchase will appear here.",
        "missing_message": f"No trail was found for order {order_ref}. Return to the trail list and choose an order.",
        "tamper_note": "Simulated on a copy. Stored data is unchanged.",
        "trail_footnote": "Tamper-evident, not tamper-proof.",
    }
    return ctx


def activity_rows(conn):
    rows = []
    audit_rows = conn.execute(
        "SELECT a.actor,a.action,a.at,a.entity_id,a.detail_json,d.paypal_dispute_id,d.payload_json "
        "FROM audit_log a LEFT JOIN draft_evidence d ON d.id=CAST(a.entity_id AS INTEGER) "
        "WHERE a.entity='draft' AND a.action IN ('draft_saved','approved')"
    ).fetchall()
    for row in audit_rows:
        detail = json.loads(row["detail_json"] or "{}")
        payload_hash = detail.get("payload_hash")
        if not payload_hash and row["payload_json"]:
            try:
                payload_hash = phash(json.loads(row["payload_json"]))
            except (TypeError, ValueError):
                payload_hash = None
        rows.append({"time": display_ts(row["at"]), "sort_time": row["at"], "actor": row["actor"],
                     "action": row["action"], "pid": row["paypal_dispute_id"],
                     "payload_hash": payload_hash[:8] if payload_hash else "—"})
    submission_rows = conn.execute(
        "SELECT s.mode,s.payload_hash,s.submitted_at,d.paypal_dispute_id,"
        "COALESCE(a.actor,'merchant') AS actor FROM submissions s "
        "LEFT JOIN draft_evidence d ON d.id=s.draft_id "
        "LEFT JOIN audit_log a ON a.entity='draft' AND a.entity_id=CAST(s.draft_id AS TEXT) "
        "AND a.action='submitted_' || s.mode ORDER BY s.id DESC"
    ).fetchall()
    for row in submission_rows:
        rows.append({"time": display_ts(row["submitted_at"]), "sort_time": row["submitted_at"],
                     "actor": row["actor"], "action": "submitted_" + row["mode"],
                     "pid": row["paypal_dispute_id"],
                     "payload_hash": (row["payload_hash"] or "—")[:8]})
    rows.sort(key=lambda row: parse_ts(row["sort_time"]) or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
              reverse=True)
    return rows


@app.get("/trail", response_class=HTMLResponse)
async def trail_view(request: Request, order_ref: str | None = None, fixture: str | None = None,
                     view: str = "trail"):
    if view == "activity":
        conn = None
        try:
            conn = open_db()
            ctx = common(conn, "trail") | {"state": "activity", "activity_rows": activity_rows(conn),
                                             "trail_footnote": "The audit log is append-only."}
        except Exception:
            ctx = error_context(request, "trail", "Activity could not be loaded. Check the local database, then refresh.")
        finally:
            if conn is not None:
                conn.close()
        return templates.TemplateResponse(request, "trail.html", ctx)
    use_fixture = FIXTURES_ENABLED and (fixture == "sample" or os.environ.get("PT_MODE") == "replay")
    return templates.TemplateResponse(request, "trail.html", _trail_page_context(request, order_ref, use_fixture))


@app.post("/trail/{order_ref}/tamper", response_class=HTMLResponse)
async def trail_tamper(request: Request, order_ref: str):
    use_fixture = FIXTURES_ENABLED and (request.query_params.get("fixture") == "sample" or os.environ.get("PT_MODE") == "replay")
    ctx = _trail_page_context(request, order_ref, use_fixture)
    if ctx["state"] != "detail" or len(ctx["events"]) < 2:
        ctx["tamper_result"] = "Tamper test unavailable: event 2 is not present."
        return templates.TemplateResponse(request, "trail.html", ctx)
    if use_fixture:
        events, _ = _demo_trail()
        key = TRAIL_DEMO_KEY
    else:
        load_dotenv()
        conn = open_db()
        try:
            events = trail.load_events(conn, order_ref)
        finally:
            conn.close()
        key = None
    changed = trail.tampered(events, 2, summary=events[1]["summary"] + " (simulated change)")
    try:
        simulated = trail.verify_events(changed, key=key)
        ctx["tamper_result"] = trail_status_text(simulated)
    except trail.MissingKey:
        simulated = {"status": "UNVERIFIED", "reason": "signing key unavailable"}
        ctx["tamper_result"] = trail_status_text(simulated)
    if not use_fixture:
        conn = open_db()
        try:
            stored = trail.verify_chain(conn, order_ref)
        finally:
            conn.close()
    else:
        _, stored = _demo_trail()
    ctx["stored_result"] = trail_status_text(stored)
    return templates.TemplateResponse(request, "trail.html", ctx)


EVAL_MAIN_RUN = "test-DeepSeek-V4-Flash-0731"
EVAL_METRICS = (
    ("decision_accuracy", "Decision accuracy"),
    ("unsupported_run_rate", "Unsupported-run rate"),
    ("injection_leak_rate", "Injection-leak rate"),
    ("completeness", "Completeness"),
)
EVAL_SYSTEMS = (("baseline", "Baseline"), ("cited", "Cited"), ("verified", "Verified"))


def eval_rate(value):
    if not isinstance(value, (int, float)):
        return "—"
    return f"{100 * value:.1f}%"


def eval_interval(stat):
    if not isinstance(stat, dict) or not isinstance(stat.get("mean"), (int, float)):
        return "—"
    return f"{eval_rate(stat['mean'])} (95% CI {eval_rate(stat.get('lo'))}–{eval_rate(stat.get('hi'))})"


def eval_consistency(value, repeats=None):
    if isinstance(value, (int, float)) and 0 <= value <= 1:
        return eval_rate(value)
    if value is None or str(value).strip().lower() in {"", "—", "n/a", "na", "none"}:
        return "n/a (single repeat per case)" if repeats == 1 else "Not reported"
    return str(value)


def eval_started(value):
    if not value:
        return "Date not provided"
    try:
        if len(value) == 15 and value[8] == "-":
            parsed = datetime.datetime.strptime(value, "%Y%m%d-%H%M%S").replace(tzinfo=datetime.timezone.utc)
            return display_ts(parsed.isoformat())
    except (TypeError, ValueError):
        pass
    return display_ts(value)


def _eval_view(summary):
    metrics = summary.get("metrics", {})
    chart_metric = metrics.get("unsupported_run_rate", {})
    chart = []
    for key, label, shape in (("baseline", "Baseline", "circle"), ("cited", "Cited", "square"), ("verified", "Verified", "triangle")):
        stat = chart_metric.get(key, {})
        mean = stat.get("mean", 0) if isinstance(stat, dict) else 0
        lo = stat.get("lo", mean) if isinstance(stat, dict) else mean
        hi = stat.get("hi", mean) if isinstance(stat, dict) else mean
        position = lambda x: round(220 + max(0, min(1, float(x or 0))) * 470)
        chart.append({"label": label, "shape": shape, "mean": eval_rate(mean), "interval": f"95% CI {eval_rate(lo)}–{eval_rate(hi)}",
                      "x": position(mean), "lo": position(lo), "hi": position(hi), "y": 31 + len(chart) * 42})
    rows = []
    for key, label in EVAL_METRICS:
        metric = metrics.get(key, {})
        rows.append({"label": label, **{system: eval_interval(metric.get(system)) for system, _ in EVAL_SYSTEMS},
                     "paired": eval_interval(metric.get("paired_baseline_minus_verified"))})
    categories = []
    for category in summary.get("categories", []):
        n = category.get("n")
        def category_rate(value):
            if not isinstance(value, (int, float)):
                return "—"
            rate = value / n if isinstance(n, (int, float)) and n and value > 1 else value
            return eval_rate(rate)
        categories.append({"name": category.get("name", "Unlabeled category"), "n": n or "—",
                           **{system: f"Decision correct {category_rate(category.get(system, {}).get('decision_ok'))} · Unsupported runs {category_rate(category.get(system, {}).get('any_unsupported'))}"
                              for system, _ in EVAL_SYSTEMS}})
    repeats = summary.get("run", {}).get("repeats")
    consistency = [{"system": label, "value": eval_consistency(summary.get("consistency", {}).get(key), repeats)}
                   for key, label in EVAL_SYSTEMS]
    return {"run": summary.get("run", {}), "started_display": eval_started(summary.get("run", {}).get("started")),
            "chart": chart, "metrics": rows, "categories": categories, "consistency": consistency,
            "failures": summary.get("failures", []), "limits": summary.get("limits", []),
            "chart_table": [{"system": item["label"], "mean": item["mean"], "interval": item["interval"]} for item in chart]}


def _flag_view(summary, classification, folder_name):
    raw = summary.get("flagged_runs", [])
    raw_count = len(raw) if isinstance(raw, list) else (raw if isinstance(raw, int) else 0)
    if not classification:
        return {"folder": folder_name, "model": summary.get("run", {}).get("model", folder_name),
                "raw_count": raw_count, "classified": False, "classified_by": "", "reading": "",
                "counts": [], "classified_count": 0}
    raw_counts = classification.get("counts") if isinstance(classification.get("counts"), dict) else {}
    counts = {str(label): int(value) for label, value in raw_counts.items() if isinstance(value, (int, float))}
    if not counts:
        items = classification.get("items") or classification.get("reclassified") or []
        for item in items:
            label = item.get("label")
            if not label:
                continue
            indices = item.get("idx")
            counts[label] = counts.get(label, 0) + (len(indices) if isinstance(indices, list) else 1)
    labels = classification.get("labels", {})
    if isinstance(labels, dict):
        for label in labels:
            counts.setdefault(str(label), 0)
    hand_counts = [{"label": label, "count": count,
                    "description": labels.get(label, "") if isinstance(labels, dict) else ""}
                   for label, count in counts.items()]
    return {"folder": folder_name, "model": summary.get("run", {}).get("model", folder_name),
            "raw_count": raw_count, "classified": True,
            "classified_by": classification.get("classified_by", "Not recorded"),
            "classification_note": "Classified by the author with an AI assistant, not independent.",
            "reading": classification.get("reading", ""), "counts": hand_counts,
            "classified_count": sum(item["count"] for item in hand_counts)}


def _panel_model(summary, folder_name):
    metrics = summary.get("metrics", {})
    repeats = summary.get("run", {}).get("repeats")
    consistency = summary.get("consistency", {})
    return {"folder": folder_name, "model": summary.get("run", {}).get("model", folder_name),
            **{key: {system: eval_interval(metrics.get(key, {}).get(system)) for system, _ in EVAL_SYSTEMS}
               for key, _ in EVAL_METRICS},
            "consistency": {system: eval_consistency(consistency.get(system), repeats) for system, _ in EVAL_SYSTEMS}}


def _read_eval_folder(folder):
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    if not isinstance(summary.get("run"), dict) or not isinstance(summary.get("metrics"), dict):
        raise ValueError("summary is missing required run or metrics data")
    classification_path = folder / "flag-classification.json"
    classification = json.loads(classification_path.read_text(encoding="utf-8")) if classification_path.exists() else None
    return summary, classification


@app.get("/eval", response_class=HTMLResponse)
async def eval_results(request: Request, fixture: str | None = None):
    use_fixture = FIXTURES_ENABLED and (fixture == "sample" or os.environ.get("PT_MODE") == "replay")
    if use_fixture:
        from app.dev_fixtures import eval_summary_data
        summary = eval_summary_data()
        ctx = common(None, "eval", True) | {"state": "success", "is_fixture": True,
            "main_run_name": "Development sample", "main_eval": _eval_view(summary), "panel_models": [],
            "flag_models": [_flag_view(summary, None, "Development sample")],
            "main_failures": [], "main_limits": summary.get("limits", []),
            "eval_metrics": EVAL_METRICS, "eval_systems": EVAL_SYSTEMS,
            "synthetic_banner": "Synthetic data. 95% intervals are case-level cluster bootstrap."}
        return templates.TemplateResponse(request, "eval.html", ctx)

    folders = sorted((path for path in EVAL_RESULTS_DIR.glob("test-*") if path.is_dir()), key=lambda path: path.name) if EVAL_RESULTS_DIR.exists() else []
    summaries, classifications, errors = {}, {}, []
    for folder in folders:
        try:
            summaries[folder.name], classifications[folder.name] = _read_eval_folder(folder)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{folder.name}: {exc}")
    main_summary = summaries.get(EVAL_MAIN_RUN)
    panel_models = [_panel_model(data, name) for name, data in summaries.items() if name != EVAL_MAIN_RUN]
    flag_models = [_flag_view(data, classifications.get(name), name) for name, data in summaries.items()]
    if not main_summary and not panel_models:
        ctx = common(None, "eval") | {"state": "empty", "generate_command": "python -m eval.summary"}
        return templates.TemplateResponse(request, "eval.html", ctx)
    ctx = common(None, "eval") | {"state": "success", "is_fixture": False,
        "main_run_name": EVAL_MAIN_RUN, "main_eval": _eval_view(main_summary) if main_summary else None,
        "panel_models": panel_models, "flag_models": flag_models,
        "main_failures": [failure for failure in (main_summary or {}).get("failures", [])
                           if failure.get("system", "").lower() == "verified"],
        "main_limits": (main_summary or {}).get("limits", []), "load_errors": errors,
        "eval_metrics": EVAL_METRICS, "eval_systems": EVAL_SYSTEMS,
        "synthetic_banner": "Synthetic data. 95% intervals are case-level cluster bootstrap."}
    return templates.TemplateResponse(request, "eval.html", ctx)


@app.get("/settings", response_class=HTMLResponse)
async def settings(request: Request):
    load_dotenv()
    mode = os.environ.get("PT_MODE", "live-sandbox")
    mode_label = {"live-sandbox": "Live sandbox", "replay": "Replay"}.get(mode, "Unrecognized mode")
    names = ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "NEBIUS_API_KEY", "TRAIL_HMAC_KEY", "PAYPAL_WEBHOOK_ID")
    keys = [{"name": name, "status": "set" if os.environ.get(name) else "not set"} for name in names]
    if not keys[3]["status"] == "set" and os.environ.get("PT_HMAC_KEY"):
        keys[3]["status"] = "set"
    configured_base = os.environ.get("PAYPAL_BASE", SANDBOX_BASE)
    base_matches = configured_base == SANDBOX_BASE
    ctx = common(None, "settings") | {"state": "success", "mode_value": mode_label, "keys": keys,
        "paypal_base": SANDBOX_BASE, "base_matches": base_matches,
        "base_message": "Sandbox URL confirmed." if base_matches else "Configured mode is not the required sandbox URL; the PayPal client will refuse it.",
        "webhook_path": "/webhooks/paypal", "poll_command": "python -m core.poll"}
    return templates.TemplateResponse(request, "settings.html", ctx)
