import json, os, re
from core.schemas import Draft

PROMPT_VERSION = "drafter_v1"
_HERE = os.path.dirname(__file__)
SYSTEM = open(os.path.join(_HERE, "prompts", "drafter_v1.md")).read()


def _esc(s):
    return s.replace("<", "\u2039").replace(">", "\u203a")


def render_bundle(bundle):
    out = ["DISPUTE: " + json.dumps(bundle["dispute"]["content"]),
           "REQUIRED_EVIDENCE: " + json.dumps(bundle["required_evidence"]), "", "RECORDS:"]
    for r in bundle["records"]:
        body = json.dumps(r["content"])
        if r["untrusted"]:
            out.append(f"[{r['record_id']}] kind={r['kind']} TRUSTED=no\n<untrusted_text>\n{_esc(body)}\n</untrusted_text>")
        else:
            out.append(f"[{r['record_id']}] kind={r['kind']} TRUSTED=yes\n{body}")
    return "\n".join(out)


def extract(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    s, e = text.find("{"), text.rfind("}")
    return text[s:e + 1] if s != -1 and e != -1 else text


def draft(gw, bundle, model, run_id=None, cache_salt="", cache=True):
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": render_bundle(bundle)}]
    attempts, err = [], ""
    for _ in range(2):
        res = gw.chat("agent", model, messages, cache=cache, cache_salt=cache_salt, run_id=run_id)
        attempts.append(res)
        try:
            d = Draft.model_validate_json(extract(res["text"]))
            return {"ok": True, "draft": d, "error": "", "attempts": attempts,
                    "cost_usd": sum(a["cost_usd"] for a in attempts)}
        except ValueError as e:
            err = str(e)[:400]
            messages = messages + [{"role": "assistant", "content": res["text"][:3000]},
                                   {"role": "user", "content": "Your output was invalid. Error: " + err +
                                    " Return ONE corrected JSON object only."}]
    return {"ok": False, "draft": None, "error": err, "attempts": attempts,
            "cost_usd": sum(a["cost_usd"] for a in attempts)}
