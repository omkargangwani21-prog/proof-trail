from core.case_builder import build_case
from core.agent import draft
from core.judge import make_judge, judge_model_for
from core.verifier import verify


def run_case(conn, gw, dispute, agent_model, run_id=None, cache_salt="", cache=True,
             judge_model=None, mutate=None):
    bundle = build_case(conn, dispute)
    dr = draft(gw, bundle, agent_model, run_id, cache_salt, cache)
    if not dr["ok"]:
        return {"bundle": bundle, "draft_result": dr, "verification": None}
    d = mutate(dr["draft"]) if mutate else dr["draft"]
    judge = make_judge(gw, judge_model or judge_model_for(agent_model), run_id)
    return {"bundle": bundle, "draft_result": dr, "verification": verify(bundle, d, judge)}
