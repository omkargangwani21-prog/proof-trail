import re, json

BLAME = re.compile(r"\b(liar|lying|lies|lied|fraud|fraudster|fraudulent|scam|scammer|dishonest|cheat|cheating|thief|stole)\b", re.I)
REQUIRED_MAP = {"PROOF_OF_FULFILLMENT": ("fulfillment", "shipment")}  # evidence type -> (claim type, record kind)
FACTUAL = {"fulfillment", "authorization", "policy", "history"}
CARRIERS = ("ups", "fedex", "usps", "dhl")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
AMOUNT = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|\b\d+\.\d{2}\b")
TRACK = re.compile(r"\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{10,}\b", re.I)


def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def nums(text):
    out = set()
    for x in re.findall(r"\d[\d,]*\.?\d*", text):
        try:
            out.add(float(x.replace(",", "")))
        except ValueError:
            pass
    return out


def entities(text):
    ents = [("date", d) for d in DATE.findall(text)]
    ents += [("amount", a) for a in AMOUNT.findall(text)]
    ents += [("track", t) for t in TRACK.findall(text)]
    ents += [("carrier", c) for c in CARRIERS if re.search(rf"\b{c}\b", text, re.I)]
    return ents


def present(kind, value, haystack):
    if kind == "amount":
        return float(value.replace("$", "").replace(",", "").strip()) in nums(haystack)
    return norm(value) in norm(haystack)


def check_claim(claim, recs, trusted_text):
    """Deterministic layers. Returns (verdict, reasons) where verdict in REMOVED / NEEDS_REVIEW / PASS."""
    if not claim.source_refs:
        return "REMOVED", ["L1: claim has no source"]
    cited_vals, rec_txt = [], ""
    for ref in claim.source_refs:
        rec = recs.get(ref.record_id)
        if rec is None:
            return "REMOVED", [f"L2: record {ref.record_id} is not in this case"]
        if ref.field not in rec["content"]:
            return "REMOVED", [f"L2: field {ref.field} not in {ref.record_id}"]
        val = rec["content"][ref.field]
        val_s = val if isinstance(val, str) else json.dumps(val)
        if norm(ref.quoted_value) not in norm(val_s):
            return "REMOVED", [f"L2: quoted value not found in {ref.record_id}.{ref.field}"]
        cited_vals.append(ref.quoted_value)
        rec_txt += " " + json.dumps(rec["content"])
    if BLAME.search(claim.text):
        return "REMOVED", ["L4: accusatory or character language"]
    cited_txt = " ".join(cited_vals)
    review = []
    for kind, val in entities(claim.text):
        if present(kind, val, cited_txt):
            continue
        if present(kind, val, rec_txt):
            review.append(f"L2: {kind} '{val}' is in the cited record but not in the cited field")
        elif present(kind, val, trusted_text):
            review.append(f"L2: {kind} '{val}' is only in a different record")
        else:
            return "REMOVED", [f"L2: {kind} '{val}' appears in no trusted record"]
    if claim.type in FACTUAL and all(recs[r.record_id]["untrusted"] for r in claim.source_refs):
        review.append("L4: factual claim sourced only from buyer-written text")
    return ("NEEDS_REVIEW", review) if review else ("PASS", [])


def verify(bundle, draft, judge=None):
    """judge(claim_text, cited_records) -> True | False | 'unclear'. None = not run (fail closed)."""
    recs = {r["record_id"]: r for r in bundle["records"]}
    trusted_text = " ".join(json.dumps(r["content"]) for r in bundle["records"] if not r["untrusted"])
    out, seen = [], set()
    for c in draft.claims:
        if c.claim_id in seen:
            out.append({"claim": c, "verdict": "REMOVED", "reasons": ["L1: duplicate claim_id"]})
            continue
        seen.add(c.claim_id)
        v, why = check_claim(c, recs, trusted_text)
        if v == "PASS":
            if judge is None:
                v, why = "NEEDS_REVIEW", ["L3: judge not run (fail closed)"]
            else:
                try:
                    cited = {r.record_id: recs[r.record_id]["content"] for r in c.source_refs}
                    j = judge(c.text, cited)
                except Exception as e:
                    j = "error"
                    why = [f"L3: judge error {type(e).__name__} (fail closed)"]
                if j is True:
                    v, why = "VERIFIED", []
                elif j is False:
                    v, why = "REMOVED", ["L3: judge says the cited text does not support the claim"]
                elif j == "unclear":
                    v, why = "NEEDS_REVIEW", ["L3: judge unclear"]
                else:
                    v = "NEEDS_REVIEW"
        out.append({"claim": c, "verdict": v, "reasons": why})

    verified = [x["claim"] for x in out if x["verdict"] == "VERIFIED"]
    missing = []
    for ev in bundle["required_evidence"]:
        need = REQUIRED_MAP.get(ev)
        ok = bool(need) and any(c.type == need[0] and any(recs[r.record_id]["kind"] == need[1] for r in c.source_refs)
                                for c in verified)
        if not ok:
            missing.append(ev)
    if draft.decision == "ACCEPT":
        decision = "ACCEPT"
    elif draft.decision == "ABSTAIN" or missing:
        decision = "ABSTAIN"
    else:
        decision = "CONTEST"
    return {"decision": decision,
            "recommendation": "Accept the claim" if decision in ("ABSTAIN", "ACCEPT") else "Contest with the verified claims",
            "claims": out, "missing_evidence": missing, "l3_ran": judge is not None}
