"""Judge accuracy on labeled (claim, evidence) pairs that pass L2, so only the judge decides.
Same-author, small-n audit. Labels are by construction."""
import json, sys
from core.db import connect
from core.gateway import Gateway
from core.judge import make_judge
from core.verifier import verify
from core.schemas import Draft

MODELS = ["openai/gpt-oss-120b", "nvidia/nemotron-3-super-120b-a12b"]


def pairs():
    cases = [json.loads(l) for l in open("eval/cases/dev.jsonl")]
    use = []
    for c in cases:
        shp = next((r for r in c["bundle"]["records"] if r["kind"] == "shipment"), None)
        if shp and shp["content"].get("delivery_status") == "DELIVERED" and shp["content"].get("carrier"):
            use.append((c, shp["content"]))
        if len(use) == 10:
            break
    out = []
    for c, s in use:
        ref = lambda f: {"record_id": "shp:1", "field": f, "quoted_value": str(s[f])}
        S = [("The shipment status is DELIVERED.", [ref("delivery_status")]),
             (f"The carrier for this shipment is {s['carrier']}.", [ref("carrier")]),
             (f"The tracking number is {s['tracking_number']}.", [ref("tracking_number")])]
        U = [("The package was left at the buyer's front door.", [ref("delivery_status")]),
             ("The buyer signed for the package.", [ref("delivery_status")]),
             ("The carrier delayed the shipment and apologized to the buyer.", [ref("carrier")])]
        out += [(c, t, r, True) for t, r in S] + [(c, t, r, False) for t, r in U]
    return out


def main():
    gw = Gateway(connect())
    P = pairs()
    result = {}
    for model in MODELS:
        tp = fn = fp = tn = 0
        errors = []
        for i, (c, text, refs, label) in enumerate(P):
            d = Draft(decision="CONTEST", rationale="audit", missing_evidence=[],
                      claims=[{"claim_id": "c1", "type": "fulfillment", "confidence": 0.9, "text": text, "source_refs": refs}])
            ver = verify(c["bundle"], d, make_judge(gw, model, f"AUDIT|{model}|{i}"))
            got = ver["claims"][0]["verdict"] == "VERIFIED"
            why = ver["claims"][0]["reasons"]
            if label and got: tp += 1
            elif label and not got: fn += 1; errors.append(("FALSE_REJECT", text, why))
            elif not label and got: fp += 1; errors.append(("FALSE_ACCEPT", text, why))
            else: tn += 1
        n = len(P)
        result[model] = {"n": n, "accuracy": round((tp + tn) / n, 3), "false_accept_rate": round(fp / max(1, fp + tn), 3),
                         "false_reject_rate": round(fn / max(1, fn + tp), 3), "confusion": {"tp": tp, "fn": fn, "fp": fp, "tn": tn},
                         "errors": errors[:12]}
        r = result[model]
        print(f"\n{model}  n={n}  accuracy={r['accuracy']}  false_accept={r['false_accept_rate']}  false_reject={r['false_reject_rate']}")
        print("   confusion  supported->VERIFIED:", tp, "| supported->not:", fn, "| unsupported->VERIFIED:", fp, "| unsupported->not:", tn)
        for e in errors[:8]:
            print("   ", e[0], "|", e[1][:70], "|", e[2])
    json.dump(result, open("eval/out/judge-audit.json", "w"), indent=1)
    print("\nsaved eval/out/judge-audit.json | spent total: $%.4f" % Gateway(connect()).spent())


if __name__ == "__main__":
    main()
