"""Create a draft for a stored dispute with the same runner the eval uses. One model call per click."""
import json
from core.pipeline import run_case
from core.submitter import save_draft

MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"


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
    r = run(conn, gw, json.loads(row["raw_json"]), model)
    if not r["draft_result"]["ok"] or r["verification"] is None:
        return {"ok": False, "reason": "The model did not return a usable draft. Nothing was saved."}
    v = r["verification"]
    return {"ok": True, "draft_id": save_draft(conn, r["bundle"], v), "decision": v["decision"]}
