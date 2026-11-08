"""POST /disputes/{id}/draft: one model call per click. Wire into the app with app.include_router(router).
Redirect query values for the UI: ?draft=ok | failed | notready | budget | error on the dispute page,
?draft=invalid | notfound on the queue. Never put spend figures in any message."""
import logging, os, re
from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from core.db import connect
from core import drafting
from core.gateway import BudgetExceeded

router = APIRouter()
ID = re.compile(r"^[A-Za-z0-9-]{5,40}$")
log = logging.getLogger("prooftrail.draft")


def _conn():
    return connect(os.environ.get("PT_DB") or None)


def _draft(pid):
    conn = _conn()
    try:
        return drafting.draft_dispute(conn, pid)
    finally:
        conn.close()


@router.post("/disputes/{pid}/draft")
async def create_draft(pid: str):
    if not ID.match(pid):
        return RedirectResponse("/disputes?draft=invalid", status_code=303)
    back = f"/disputes/{pid}"
    try:
        res = await run_in_threadpool(_draft, pid)
    except drafting.DisputeNotFound:
        return RedirectResponse("/disputes?draft=notfound", status_code=303)
    except drafting.NotDraftable:
        return RedirectResponse(back + "?draft=notready", status_code=303)
    except BudgetExceeded:
        return RedirectResponse(back + "?draft=budget", status_code=303)
    except Exception:
        log.exception("draft failed for %s", pid)
        return RedirectResponse(back + "?draft=error", status_code=303)
    return RedirectResponse(back + ("?draft=ok" if res["ok"] else "?draft=failed"), status_code=303)
