"""Backend routes for getting disputes in. Wire into the app with app.include_router(router)."""
import os, re
from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from core.db import connect
from core.paypal_client import PayPalClient, PayPalError
from core import ingest

router = APIRouter()
ID = re.compile(r"^[A-Za-z0-9-]{5,40}$")


def make_client():
    return PayPalClient()


def _conn():
    return connect(os.environ.get("PT_DB") or None)


def _fetch(dispute_id):
    conn = _conn()
    try:
        return ingest.ingest_dispute(conn, make_client(), dispute_id)
    finally:
        conn.close()


def _refresh():
    conn = _conn()
    try:
        return ingest.poll_once(conn, make_client())
    finally:
        conn.close()


def _webhook(headers, raw, webhook_id):
    conn = _conn()
    try:
        return ingest.handle_webhook(conn, make_client(), headers, raw, webhook_id)
    except PayPalError as e:
        return 502, {"error": "could not fetch the dispute from PayPal", "detail": str(e)[:200]}
    finally:
        conn.close()


@router.post("/ingest/fetch")
async def fetch(dispute_id: str = Form(...)):
    pid = dispute_id.strip()
    if not ID.match(pid):
        return RedirectResponse("/disputes?fetch=invalid", status_code=303)
    try:
        res = await run_in_threadpool(_fetch, pid)
    except PayPalError as e:
        return RedirectResponse("/disputes?fetch=" + ("notfound" if e.status == 404 else "error"), status_code=303)
    return RedirectResponse(f"/disputes/{res['dispute_id']}?fetch=ok", status_code=303)


@router.post("/ingest/refresh")
async def refresh():
    try:
        res = await run_in_threadpool(_refresh)
    except PayPalError:
        return RedirectResponse("/disputes?refresh=error", status_code=303)
    return RedirectResponse("/disputes?refresh=" + ("partial" if res["errors"] else "done"), status_code=303)


@router.post("/webhooks/paypal")
async def paypal_webhook(request: Request):
    webhook_id = os.environ.get("PAYPAL_WEBHOOK_ID", "")
    if not webhook_id:
        return JSONResponse({"error": "PAYPAL_WEBHOOK_ID is not set"}, status_code=503)
    code, body = await run_in_threadpool(_webhook, dict(request.headers), await request.body(), webhook_id)
    return JSONResponse(body, status_code=code)
