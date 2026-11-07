# 06 — Verifier Design


## 1. Goal
No claim reaches the merchant as "Verified" unless a deterministic check confirms the cited record exists and contains the quoted value, and an independent model agrees it supports the claim.

## 2. Layers
```mermaid
flowchart LR
  D[Draft] --> L1[L1 Structure]
  L1 --> L2[L2 Deterministic grounding]
  L2 --> L3[L3 LLM judge + consistency]
  L3 --> L4[L4 Policy and safety]
  L4 --> R[Verdicts + decision rule]
```

| Layer | Checks | Method |
|---|---|---|
| L1 | JSON matches schema; each claim has ≥1 source ref; ids unique | Pydantic |
| L2 | `record_id` exists in this case; `quoted_value` is a substring of `content[field]` after normalization; entities in claim text (amounts, dates, tracking numbers, order ids, carrier names) appear in the cited fields | code, regex + normalizers |
| L3 | Does the cited text **entail** the claim? Cross-claim consistency (dates in order: order < ship < delivery < dispute; amounts match) | LLM judge, different family (gpt-oss-120b; nvidia/nemotron-3-super-120b-a12b when gpt-oss is the agent), temperature 0, JSON verdict; consistency by code |
| L4 | No claims about buyer's character or intent; no accusations of fraud; no legal conclusions; no content copied from untrusted messages as fact | rules + judge |

## 3. Verdicts
- **VERIFIED**: passes L1–L4.
- **NEEDS_REVIEW**: L3 uncertain or judge unavailable (fail closed). Visible, not submittable without explicit merchant override note.
- **REMOVED**: fails L1, L2, L4, or L3 says unsupported. Shown struck-through with reason; not included in payload.

## 4. Decision rule
1. `required_evidence` is read from the dispute's own `evidences` entries marked `REQUESTED_FROM_SELLER` (checked against real sandbox disputes), not derived from the reason code.
2. If `PROOF_OF_FULFILLMENT` is requested and no VERIFIED `fulfillment` claim cites a shipment record that satisfies the shipped predicate (tracking number, `shipped_at`, status IN_TRANSIT / OUT_FOR_DELIVERY / DELIVERED) → decision `ABSTAIN` with recommendation "Accept claim" and a list of what is missing. Any consistency issue (date order, amounts), or an `ABSTAIN` from the drafter, also forces `ABSTAIN`.
   Other requested types (for example `PROOF_OF_REFUND`, `OTHER`) do not gate a contest; unmet ones are reported as `requested_not_provided`. If PayPal lists no gating type at all, every requested type must be satisfied. This gating rule was changed after the frozen test run (see DECISIONS.md, 2026-11-07); for the synthetic cases, which request only `PROOF_OF_FULFILLMENT`, behaviour is identical.
3. Else `CONTEST` with VERIFIED claims only.
4. A human can override NEEDS_REVIEW claims, with a note. Overrides are logged and counted in eval.

Abstention is a feature: a wrong confident submission costs more than a declined contest.

## 5. Judge prompt contract (summary)
Input: claim text, cited `quoted_value` and its record excerpt. Output JSON `{"supported": true|false|"unclear", "reason": "<=30 words"}`. Judge never sees the agent's reasoning, only claim + cited text. Prompt text lives in `core/prompts/judge.md` and is versioned and frozen before the test run. The judge call is retried once, uncached, if its output cannot be parsed; the parser accepts strict JSON, or salvages a verdict only when exactly one distinct verdict is present. If it still fails, the claim is NEEDS_REVIEW (fail closed).

## 6. Prompt-injection stance
- Untrusted records are wrapped in delimiters and labeled in the agent prompt and in the UI.
- Verifier L2 requires citations to point to **trusted** records for factual claims about fulfillment/authorization. A claim whose only source is a buyer message is capped at NEEDS_REVIEW.
- The model has no tools or write access, so a successful injection can at worst corrupt a draft, which the verifier and human still gate.

## 7. Known limits (published in README)
1. L2 proves the quote exists, not that it is relevant. L3 covers relevance and can err.
2. Judge and agent can share blind spots; different family reduces but does not remove this.
3. Normalization can miss paraphrased dates or amounts. Measured via judge-accuracy sample.
4. A drafter can omit a helpful fact. The verifier checks precision, not recall. Recall appears as the evidence-completeness metric.
5. Strictness has a measured cost. On the frozen test split the Verified system lost a contest it should have made in 2 of 260 runs on DeepSeek-V4-Flash and 5 of 260 on gpt-oss-120b (a valid claim was REMOVED by the judge or L2); 0 on Qwen3-30B. Per-run lists are in each run's `report.txt`.
6. The judge differs by agent model (Nemotron when gpt-oss is the agent), so that panel row also changes the judge.
7. The 60-pair judge audit passed 60/60 on both judges, but the pairs were hand-built by the system's author and are obvious cases. Real false removals (item 5) show the audit understates judge error.
8. The agent-purchase trail is tamper-evident, not tamper-proof: deleting the newest events is undetectable without an externally stored head hash, and the key holder can forge. The shopper's intent text is recorded as given; the chain shows it was not edited afterwards, not that it is true.

## 8. Tests
- Unit: fabricated tracking number → REMOVED; mismatched amount → REMOVED; date order violation → flagged.
- Property: removing a cited record always demotes its claims.
- Judge accuracy: 60 hand-labeled (claim, evidence) pairs; report accuracy and confusion matrix.
- Fail-closed: simulated judge outage → all claims NEEDS_REVIEW.
