"""Create a draft for a stored dispute with the same runner the eval uses.

If a run yields no usable draft (an empty reply after a reasoning overrun, a missing required field),
retry up to TRIES times in total, each retry with a fresh cache key so nothing is replayed."""
import inspect
import json
from core.pipeline import run_case
from core.submitter import save_draft

MODEL = "deepseek-ai/DeepSeek-V4.1-Flash-1017"
TRIES = 3


def _accepts_salt(run):
    ps = inspect.signature(run).parameters
    return "cache_salt" in ps or any(p.kind == p.VAR_KEYWORD for p in ps.values())


class DisputeNotFound(Exception):
    pass


class NotDraftable(Exception):
    pass


def draft_dispute(conn, dispute_id, gw=None, model=MODEL, run=run_case):
    row = conn.execute("SELECT status, raw_json FROM disputes WHERE paypal_dispute_id=?", (dispute_id,)).fetchone()
    if not row:
        raise DisputeNotFound(dispute_id)
    if row["status"] != "WAITING_FOR_SELLER_RESPONSE":
        raise NotDraftable(f"dispute status is {row['status']}")
    if gw is None:
        from core.gateway import Gateway
        gw = Gateway(conn)
    dispute = json.loads(row["raw_json"])
    r = None
    for i in range(TRIES):
        kw = {"cache_salt": f"retry-{i}"} if i and _accepts_salt(run) else {}
        r = run(conn, gw, dispute, model, **kw)
        if r["draft_result"]["ok"] and r["verification"] is not None:
            break
    else:
        return {"ok": False, "reason": "The model did not return a usable draft. Nothing was saved."}
    v = dict(r["verification"])
    d = r["draft_result"].get("draft")
    if d is not None:
        v["drafter_decision"], v["rationale"] = d.decision, d.rationale
    return {"ok": True, "draft_id": save_draft(conn, r["bundle"], v), "decision": v["decision"]}
