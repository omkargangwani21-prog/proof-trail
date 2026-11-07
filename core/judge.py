import json, os, re
from core.agent import extract

JUDGE_SYSTEM = open(os.path.join(os.path.dirname(__file__), "prompts", "judge_v1.md")).read()
DEFAULT_JUDGE = "openai/gpt-oss-120b"
JUDGE_FOR = {"openai/gpt-oss-120b": "nvidia/nemotron-3-super-120b-a12b"}
VERDICT = re.compile(r'"supported"\s*:\s*(true|false|"unclear")', re.I)


def judge_model_for(agent_model):
    return JUDGE_FOR.get(agent_model, DEFAULT_JUDGE)


def parse_verdict(text):
    """Strict JSON first. If the JSON is malformed, accept the verdict only when exactly one distinct
    "supported" value appears. Anything else raises, and the verifier then fails closed."""
    try:
        s = json.loads(extract(text)).get("supported")
    except (ValueError, AttributeError, TypeError):
        found = {m.lower() for m in VERDICT.findall(text or "")}
        if len(found) != 1:
            raise ValueError("bad judge output")
        v = found.pop()
        s = {"true": True, "false": False}.get(v, "unclear")
    if s is True or s is False:
        return s
    if s == "unclear":
        return "unclear"
    raise ValueError("bad judge output")


def make_judge(gw, model, run_id=None):
    def judge(claim_text, cited):
        msgs = [{"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": "CLAIM: " + claim_text + "\nCITED_RECORDS: " + json.dumps(cited)}]
        res = gw.chat("judge", model, msgs, temperature=0.0, run_id=run_id)
        try:
            return parse_verdict(res["text"])
        except ValueError:
            res = gw.chat("judge", model, msgs, temperature=0.0, cache=False, run_id=run_id)
            return parse_verdict(res["text"])
    return judge
