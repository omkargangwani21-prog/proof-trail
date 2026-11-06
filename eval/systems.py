import json, os, re
from core.agent import extract
from core.submitter import build_payload

BASELINE_SYSTEM = open(os.path.join(os.path.dirname(__file__), "prompts", "baseline_v1.md")).read()


def render_plain(bundle):
    out = ["DISPUTE: " + json.dumps(bundle["dispute"]["content"]),
           "REQUIRED_EVIDENCE: " + json.dumps(bundle["required_evidence"]), "", "RECORDS:"]
    out += [f"[{r['record_id']}] {r['kind']}\n{json.dumps(r['content'])}" for r in bundle["records"]]
    return "\n".join(out)


def call_baseline(gw, bundle, model, run_id):
    messages = [{"role": "system", "content": BASELINE_SYSTEM}, {"role": "user", "content": render_plain(bundle)}]
    for _ in range(2):
        res = gw.chat("baseline", model, messages, cache=False, run_id=run_id)
        try:
            d = json.loads(extract(res["text"]))
            if not isinstance(d, dict) or "decision" not in d:
                raise ValueError("no decision")
            return {"ok": True, "parsed": d}
        except ValueError as e:
            messages = messages + [{"role": "assistant", "content": res["text"][:3000]},
                                   {"role": "user", "content": "Invalid output (" + str(e)[:200] + "). Return ONE corrected JSON object only."}]
    return {"ok": False, "parsed": None}


NONE = {"decision": None, "claims": [], "tracking": []}
NOT = {"decision": "NOT_CONTEST", "claims": [], "tracking": []}


def norm_baseline(p):
    if not p:
        return NONE
    if str(p.get("decision", "")).upper() != "CONTEST":
        return NOT
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", str(p.get("evidence_notes", ""))) if s.strip()]
    tr = [str(t["tracking_number"]) for t in (p.get("tracking_info") or []) if isinstance(t, dict) and t.get("tracking_number")]
    return {"decision": "CONTEST", "claims": [{"text": s, "sources": []} for s in sents], "tracking": tr}


def norm_agent(draft, bundle):
    if draft.decision != "CONTEST":
        return NOT
    recs = {r["record_id"]: r for r in bundle["records"]}
    tr = []
    for c in draft.claims:
        for r in c.source_refs:
            rec = recs.get(r.record_id)
            tn = rec["content"].get("tracking_number") if rec and rec["kind"] == "shipment" else None
            if tn and tn not in tr:
                tr.append(tn)
    return {"decision": "CONTEST", "tracking": tr,
            "claims": [{"text": c.text, "sources": [r.record_id for r in c.source_refs]} for c in draft.claims]}


def norm_verified(bundle, ver):
    payload = build_payload(bundle, ver)
    if payload is None:
        return NOT
    ok = [x["claim"] for x in ver["claims"] if x["verdict"] == "VERIFIED"]
    tr = [t["tracking_number"] for t in payload[0]["evidence_info"]["tracking_info"]]
    return {"decision": "CONTEST", "tracking": tr,
            "claims": [{"text": c.text, "sources": [r.record_id for r in c.source_refs]} for c in ok]}
