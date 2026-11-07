# Decisions log

## 2026-11-06: Gate 1 passed (dispute path)
- A buyer-opened sandbox case (Item not received) is retrievable via `GET /v1/customer/disputes/{id}`.
- Observed: `reason` = `MERCHANDISE_OR_SERVICE_NOT_RECEIVED` (docs previously said `ITEM_NOT_RECEIVED`), `status` = `WAITING_FOR_SELLER_RESPONSE`, `dispute_life_cycle_stage` = `INQUIRY`, `dispute_channel` = `INTERNAL`.
- `seller_response_due_date` is returned.
- `allowed_response_options`: `accept_claim` = [PARTIAL_REFUND, REFUND]; `make_offer` = [REFUND].
- Links returned: self, accept_claim, provide_evidence, send_message, escalate, make_offer.
- `GET /v1/customer/disputes` (list) returned an empty list for this dispute while fetch-by-ID worked. Ingestion must not depend on the list alone. [VERIFY] whether the list catches up later.
- API-based dispute creation is not needed; the buyer-opened path is the primary path.

## 2026-11-06: More observed facts
- `evidences` on the dispute included `{"evidence_type": "PROOF_OF_FULFILLMENT", "source": "REQUESTED_FROM_SELLER"}`. This is the evidence type PayPal requests for an Item-not-received inquiry.
- `disputed_transactions[0].seller_transaction_id` equals the capture id of our sandbox order; this is the join key to our `orders` table.
- A fund hold appears in `fund_movements` (`HOLD_PLACED`).
- Buyer text appears in `messages[].content` and in `evidences[]` entries with `source` = `SUBMITTED_BY_BUYER`. Both are untrusted.

## 2026-11-06: Drafter prompt v1 -> v2 (dev-set finding)
- First real run (DeepSeek-V4-Flash, 1 dev case): the claim mentioned the carrier but cited only status, timestamp and tracking number. L2 flagged `carrier` as "in the cited record but not in the cited field" -> NEEDS_REVIEW -> final ABSTAIN (a false abstain).
- Fix: prompt v2 requires a citation for every date, amount, carrier, tracking number or status mentioned in a claim.
- Verifier behavior unchanged. Seeded fabricated claim was REMOVED at L2 in the same run.
- Prompt changes are allowed only on the dev set. The test set must be frozen before the final eval and prompts are then fixed.

## 2026-11-06: First real sandbox evidence submission succeeded
- `POST /v1/customer/disputes/{id}/provide-evidence` as multipart with one `input` part (application/json) containing `{"evidences":[{evidence_type, evidence_info:{tracking_info:[{carrier_name, tracking_number}]}, notes}]}` was accepted. Response contained only a `detail` link.
- Dispute moved WAITING_FOR_SELLER_RESPONSE -> UNDER_REVIEW (dispute_state UNDER_PAYPAL_REVIEW); evidence listed as PROOF_OF_FULFILLMENT, source SUBMITTED_BY_SELLER. After submission `allowed_response_options` is null.
- Tracking data was synthetic demo data in the sandbox; must stay labeled synthetic in UI, README and video.

## 2026-11-06: Date-pattern bug found by the first dev eval run
- The date pattern used `\b` after the day, so it never matched inside ISO timestamps (`2026-10-08T13:00:00Z`).
- Effect 1 (scorer): ground-truth `dates` was empty, so every correct date was flagged as invented.
- Effect 2 (verifier): dates written inside timestamps in claim text were not entity-checked. Fixed with `(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)`; tests added both ways.
- Eval cases regenerated and the manifest updated. The test split had not been run, so no test result was affected. Dev results from before the fix are discarded.

## 2026-11-06: Benchmark gap and "partial evidence" category (written BEFORE any run on it)
- First full dev run (DeepSeek-V4-Flash, 20 cases x 3): all systems scored 0 unsupported claims and 0 injection leaks. Cases were either complete or empty, so the model was never tempted to overstate. The only difference (conflicting records) is by construction.
- Added category `partial` (dev 6, test 12): in_transit, delivered_no_date, no_carrier, exception, no_trail_auth, split_shipment. Each encodes a trap and its false assertions. Dev is now 26 cases, test 52. Rationale: real disputes are mostly partial evidence.
- Added generic invented-delivery-detail phrases to every case's forbidden list.
- Commitment: we publish all results, including any where the plain baseline matches or beats the verified system. The test split is not tuned on. Categories and traps are fixed by this entry.

## 2026-11-06: Post-hoc dev changes after reading the first `partial` results (test split NOT yet run)
- Finding 1 (scorer bug): forbidden phrase "authorized" matched inside "unauthorized", so two baseline sentences ("the buyer's claim of unauthorized purchase ...") were wrongly flagged. The baseline's reported 0.03 unsupported rate on dev was entirely this bug. Fix: forbidden phrases match whole words.
- Finding 2 (label policy): on `in_transit` and `split_shipment` the drafter abstained 3/3 times with a defensible reason (no proof of delivery; no mapping of items to shipments). Our pre-registered label "CONTEST" there was a business-judgment call, not a fact. Change: both decisions are accepted for these two variants; the hard requirements (no delivery claim for in-transit, no "entire order delivered") are unchanged. Completeness is only measured where CONTEST is the sole acceptable decision.
- Made after seeing drafter output on the dev set. Test split has not been run. Clear-cut labels unchanged.
- Observed: one real verifier catch on dev (cited a payment record from a broken trail chain), but that case is planted by construction. On DeepSeek-V4-Flash the plain baseline did not fabricate on our cases.

## 2026-11-06: Judge output parsing bug (dev-time fix, test split not yet run)
- With gpt-oss-120b as the agent, the judge is Nemotron. About 1 in 3 clean-case runs ended in ABSTAIN because Nemotron sometimes returns almost-valid JSON (missing quote before the "reason" text). json.loads failed, the verifier failed closed. Drafts were correct.
- Fix: if strict JSON fails, accept the verdict only when exactly one distinct "supported" value appears; otherwise retry once uncached; otherwise fail closed as before. Reported number before the fix (gpt-oss agent, dev): verified decision accuracy 0.88, clean 0.60, consistency 0.65, completeness 0.81. Kept here as the "before" result.
- After the fix (gpt-oss agent, dev, 3 repeats): verified decision accuracy 0.96, clean 0.87, completeness 0.94, consistency 0.88 (cited: 0.82 / 1.00 / 1.00 / 0.96). Remaining gap = judge false rejections (one run: dev-clean-00 rep2 REMOVED). Over-removal is reported as its own metric. Unsupported-claim rate was 0.00 for cited and verified, 0.06 for baseline (interval touches zero); some baseline flags are rebuttals of buyer text, not assertions (scorer cannot tell mention from assertion; to be split into asserted vs echoed).

## 2026-11-07: Judge audit (eval/judge_audit.py) and freeze
- 60 labeled pairs per judge (30 supported, 30 unsupported, all passing L2 so only the judge decides). gpt-oss-120b and Nemotron-3-Super: 60/60 correct, 0 false accepts, 0 false rejects. Same-author, blatant-overreach templates only: weak evidence, not a proof; subtle cases untested. Listed under Limits.
- Frozen from now on: drafter_v2, judge_v1, scorer, case generator. No tuning on dev after this point. Remaining eval work: run the test split once.
- Known cost of strictness: a claim naming an item but citing only the shipment record is correctly REMOVED (item name lives in the order record). Completeness drops on some runs. Reported under Limits.

## 2026-11-07: UI stack detail
- UI uses plain CSS custom properties (the doc 11 tokens) instead of the Tailwind CDN: no network dependency, offline-safe replay mode. Jinja + FastAPI unchanged. Handlers are async and open the SQLite connection inside the handler (connections cannot cross threads).

## 2026-11-07: UI visual direction replaced
- v1 (indigo palette, IBM Plex, pastel pill rows, a banner, four placeholder pages) was rejected as generic. v2: ink/paper with evidence-tag yellow, Archivo + Courier Prime, single table queue, nav shows only built screens. Doc 11 rewritten first, then code.

## 2026-11-07: How disputes arrive (ingestion)
- Three entry paths, all ending in GET /v1/customer/disputes/{id}: (1) "Fetch by ID", (2) poller (`python -m core.poll`), (3) webhook `POST /webhooks/paypal`. The poller always refreshes known disputes by id because the list endpoint lagged 15+ minutes in our sandbox.
- Webhook: signature verified through POST /v1/notifications/verify-webhook-signature (fields per PayPal docs), duplicates ignored by event id, a failed fetch returns 5xx so PayPal retries. Events handled: CUSTOMER.DISPUTE.CREATED / UPDATED / RESOLVED.
- [VERIFY] not confirmed from docs: the `resource` shape of dispute events (code reads resource.dispute_id, falls back to resource.id, then fetches by id) and whether our sandbox app has the webhooks scope needed to call the verify endpoint. If not, the poller is the delivery path and the README says so.

## 2026-11-07: Test split run, eval/summary.py, demo shopping agent
- Test split executed once (52 cases x 5 repeats, DeepSeek-V4-Flash, frozen scorer and prompts, commit 996feaef). Results in eval/results/. First attempt copied the wrong report (a dev run) into eval/results; corrected in a follow-up commit.
- eval/summary.py added (reporting only, same bootstrap as report.py) to feed the Eval screen. No scoring change.
- Demo agent: `python -m core.demo_agent start "..."` / `finish`. Refuses when no item fits the budget. The trail proves integrity of what the agent recorded, not truth of the shopper's instruction (README Limits). Shipment/delivery rows it creates are synthetic (data_origin synthetic_demo). Sandbox buyer approval is a human step.
