# 01 — Product Requirements (PRD)


## 1. Problem
- Merchants who lose a PayPal dispute lose the money and the item. Preparing evidence is manual and slow.
- AI tools that draft evidence exist (vendor claims, self-reported: Chargeflow, Justt, Stripe Smart Disputes, others). Merchant complaints reported by an aggregator summarizing reviews include fabricated details and submission without review (low confidence).
- No clear liability rule exists for purchases made by AI agents on a customer's behalf. A merchant has no proof of who authorized what.
- Evidence: a Reddit merchant reports losing most disputes even with legitimate evidence. **We therefore make no win-rate claim.**

## 2. Product statement
ProofTrail makes AI-drafted dispute evidence **checkable**: each claim points to a source record, a verifier rechecks it, and a human approves before submission.

## 3. Users
| Persona | Needs |
|---|---|
| **Maya, small-merchant dispute operator** (primary) | See what is due, see what the AI claims and why, remove weak claims, submit with confidence |
| **Judge / reviewer** (secondary) | Understand the idea in 30 seconds, see it work, see numbers |
| **Developer** (tertiary) | Clone, run replay mode, read the eval |

## 4. Jobs to be done
1. Know which disputes need action and by when.
2. Get a draft response without reading every record myself.
3. Trust that nothing in the draft is invented.
4. Decide to contest or accept with a reason.
5. Prove an AI-agent purchase was authorized.

## 5. Functional requirements
IDs are referenced by tests and docs.

| ID | Requirement | Acceptance test |
|---|---|---|
| FR-01 | Ingest disputes via webhook (`CUSTOMER.DISPUTE.CREATED/UPDATED/RESOLVED`) and polling fallback; dedupe by event id | Replaying the same event twice creates one dispute |
| FR-02 | Verify webhook signature before processing | Tampered body is rejected with 400 and logged |
| FR-03 | Show disputes queue with status, stage, amount, deadline [VERIFY field] | Queue renders from fixtures and sandbox |
| FR-04 | Build a case bundle: dispute, order, shipment, trail, policy, buyer messages (untrusted) | Each bundle item has a `record_id` |
| FR-05 | Agent drafts claims with `{text, type, source_refs[], confidence}` | Schema validation passes on 100% of outputs or the run is marked failed |
| FR-06 | Verifier runs L1–L4 and labels each claim Verified / Needs review / Removed | Seeded fabricated claim is removed in unit test |
| FR-07 | If required evidence is missing, system **abstains** and recommends accept | Missing-evidence case yields ABSTAIN |
| FR-08 | Human must approve before any submit. No auto-submit | Submit endpoint returns 403 without approval record |
| FR-09 | Submit via `provide-evidence`; dry-run is default; payload preview shown | Dry-run writes no PayPal call; real mode only in sandbox |
| FR-10 | Accept-claim path via `accept-claim` with allowed type from `allowed_response_options` | Only allowed values selectable |
| FR-11 | Demo agent places a sandbox order, human approves buyer step, capture recorded | Order and capture ids stored |
| FR-12 | Trail recorder writes hash-chained, HMAC-signed intent → cart → payment events | Altering a stored event makes verification fail |
| FR-13 | Trail viewer shows chain and verification result | Tampered row shows red Broken state |
| FR-14 | Eval harness runs baseline vs verified agent on frozen cases and emits JSON + charts | `make eval` reproduces numbers within noise |
| FR-15 | Replay mode runs end-to-end without any keys, labeled "REPLAY" | Fresh clone runs with no `.env` |
| FR-16 | Budget guard logs every LLM call and stops at hard cap | Simulated spend at $20 blocks next call |
| FR-17 | Audit log of every approval and submission | Rows exist with actor, time, payload hash |
| FR-18 | Refuse non-sandbox PayPal base URL | Startup fails if URL is not the sandbox host |

## 6. Non-functional requirements
| ID | Requirement |
|---|---|
| NFR-01 | Cold start to usable demo in replay mode under 5 minutes on a fresh machine (README steps) |
| NFR-02 | Draft generation p95 under 60 s on main model |
| NFR-03 | WCAG 2.2 AA for core flows (doc 10) |
| NFR-04 | No secret in repo history (secret scan in CI) |
| NFR-05 | All claims about the world in README cite sources |
| NFR-06 | Every metric reproducible from a command and a seed |

## 7. Success metrics (on frozen synthetic test set, 40 cases × 5 repeats)
These are **targets to measure, not promises**. Report whatever is true.

| Metric | Direction | Target (informal) |
|---|---|---|
| Unsupported-claim rate | lower | Verified agent clearly below baseline |
| Fabrication rate | lower | Verified agent ≈ 0 after verifier |
| Decision accuracy (contest/accept/abstain) | higher | Report with CI |
| Injection resilience | higher | Report with CI |
| Run-to-run consistency | higher | Report |
| Cost per case | lower | Report in $ |

## 8. Out of scope
See doc 02.

## 9. Open questions
- [VERIFY] Can sandbox disputes be created by API? (Gate 1)
- [VERIFY] Full `evidence_type` and `reason` enums.
- [VERIFY] Whether `seller_response_due_date` is returned.
- [VERIFY] Tunnel option for webhooks (otherwise poll).
