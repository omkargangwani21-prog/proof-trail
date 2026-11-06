import json, os
from core.agent import extract

JUDGE_SYSTEM = open(os.path.join(os.path.dirname(__file__), "prompts", "judge_v1.md")).read()
DEFAULT_JUDGE = "openai/gpt-oss-120b"
JUDGE_FOR = {"openai/gpt-oss-120b": "nvidia/nemotron-3-super-120b-a12b"}


def judge_model_for(agent_model):
    return JUDGE_FOR.get(agent_model, DEFAULT_JUDGE)


def make_judge(gw, model, run_id=None):
    def judge(claim_text, cited):
        msgs = [{"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": "CLAIM: " + claim_text + "\nCITED_RECORDS: " + json.dumps(cited)}]
        res = gw.chat("judge", model, msgs, temperature=0.0, run_id=run_id)
        s = json.loads(extract(res["text"])).get("supported")
        if s is True or s is False:
            return s
        if s == "unclear":
            return "unclear"
        raise ValueError("bad judge output")
    return judge
