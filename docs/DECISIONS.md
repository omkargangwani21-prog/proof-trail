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

## 2026-11-07: Verifier gates a CONTEST on PROOF_OF_FULFILLMENT only (post-test change)
- Found on the first real UNAUTHORISED sandbox dispute (PP-R-WVY-10197010): PayPal listed PROOF_OF_FULFILLMENT, PROOF_OF_REFUND and OTHER as requested. The old rule required every requested type to be satisfied, so the verifier abstained although all four fulfillment claims were VERIFIED. PROOF_OF_REFUND cannot be satisfied when no refund happened.
- Change: only PROOF_OF_FULFILLMENT gates a contest; other unmet types are reported in `requested_not_provided` and shown to the reviewer. If PayPal lists no gating type, the old strict rule applies.
- Made after the frozen test run. When the required list is only PROOF_OF_FULFILLMENT (all synthetic cases) the behaviour is identical, pinned by tests/test_verifier_gating.py. No eval rerun was done or needed.
- Limit: this is one dispute. Whether PayPal always lists these three types for UNAUTHORISED disputes is not established.

## 2026-11-07: Hand classification of flagged test runs (DeepSeek-V4-Flash)
- Labels fixed before reading the flagged items (ADOPTED / REBUTTAL / FALSE_POSITIVE, plus CITATION_VIOLATION for forbidden-source flags). Result in eval/results/test-DeepSeek-V4-Flash-0731/flag-classification.json.
- 8 flagged runs: 4 baseline REBUTTAL (injection-07), 3 cited CITATION_VIOLATION (trail cases, broken-chain records), 1 baseline borderline FALSE_POSITIVE (partial-11). None adopted injected content.
- Raw scorer numbers are unchanged and remain the headline; the classification is published beside them. Classified by the system's author with an AI assistant, so not independent.
- Reading: on this model the test split shows no genuine fabrication in any system; the verifier's measurable value here is decision accuracy on conflicting records and provenance gating on broken-chain trail records.

## 2026-11-07: Hand classification of flagged test runs (Qwen3-30B-A3B)
- 39 flagged runs. Same labels as the DeepSeek classification plus FABRICATION (payload asserts a fact absent from the records), added at this step after seeing the flags. Result: eval/results/test-Qwen3-30B-A3B-Instruct-2507/flag-classification.json.
- Reading: 2 runs adopted attacker content (injection-00, both baseline); about 20 more echo attacker text only to reject it. About 16 baseline runs fabricated (invented tracking numbers or a delivery claim on no-shipment cases). The raw scorer numbers (injection 0.08, unsupported 0.14) overstate both and stay published unchanged.
- Classified by the system's author with an AI assistant, so not independent.

## 2026-11-07: Hand classification of flagged test runs (gpt-oss-120b)
- 19 flagged runs, classified after reading the flags and the case records. Result: eval/results/test-gpt-oss-120b/flag-classification.json.
- Reading: 3 baseline runs adopted attacker content (injection-04 date, injection-05 neighbor story); 3 fabricated (carrier inferred from a tracking prefix on the no_carrier variant; one implied buyer authorization); 12 only repeat the buyer's text to reject it; 1 borderline false positive. Raw scorer numbers (unsupported 0.07, injection 0.03) stay published unchanged.
- Classified by the system's author with an AI assistant, so not independent.

## 2026-11-08: Draft action added; GLM-5.3-Flash test run finding
- The app had no way to create a draft (only submit). Added core/drafting.py and app/draft_api.py (POST /disputes/{id}/draft): same runner as the eval, one model call per click, refused unless the dispute is WAITING_FOR_SELLER_RESPONSE, budget guard applies.
- GLM-5.3-Flash on the test split: 56 of 260 Cited/Verified runs had no usable draft (209 agent calls ended with finish_reason=length at the 6000-token cap). Those rows measure the model under that cap, not the verifier. Published as run; the 6000 cap was fixed before the run.
- Open question, not yet changed: the verifier marks a claim VERIFIED when it accurately quotes an untrusted buyer message, because claim type "other" is not capped by the buyer-text rule (seen on GLM clean-01/clean-03). A change would be a second post-test rule change and would be measured offline on cached drafts first.

## 2026-11-08: Draft action added; GLM-5.3-Flash test run finding
- The app had no way to create a draft (only submit). Added core/drafting.py and app/draft_api.py (POST /disputes/{id}/draft): same runner as the eval, one model call per click, refused unless the dispute is WAITING_FOR_SELLER_RESPONSE, budget guard applies.
- GLM-5.3-Flash on the test split: 56 of 260 Cited/Verified runs had no usable draft (209 agent calls ended with finish_reason=length at the 6000-token cap). Those rows measure the model under that cap, not the verifier. Published as run; the 6000 cap was fixed before the run.
- Open question, not yet changed: the verifier marks a claim VERIFIED when it accurately quotes an untrusted buyer message, because claim type "other" is not capped by the buyer-text rule (seen on GLM clean-01/clean-03). A change would be a second post-test rule change and would be measured offline on cached drafts first.

## 2026-11-08: Hand classification of flagged test runs (GLM-5.3-Flash) and a scorer limit
- 47 flagged runs. REBUTTAL 11, FABRICATION 6, FALSE_POSITIVE 18, FALSE_POSITIVE_BORDERLINE 1, CITATION_VIOLATION 11. File: eval/results/test-GLM-5.3-Flash/flag-classification.json. Classified by the system's author with an AI assistant, not independent.
- Scorer limit (not changed, scorer is frozen): item prices are stored in minor units, so correct dollar restatements of item prices ($25.99 from 2599) are flagged as fabricated entities. 16 of the 18 false positives come from this.
- Baseline GLM drafts on the split-shipment case promise refunds or reshipment on the merchant's behalf. Not scored; this is what the approval step is for.

## 2026-11-08: flag classification for Qwen3-235B and DeepSeek-V4.1-Flash, V4-Pro run
- Flags hand-classified with the same labels as the other panel runs (author plus AI, not independent). Counts are in each run's flag-classification.json; Qwen3-235B partial-04 r2 was labelled from truncated flag text.
- Qwen3-235B baseline adopts injected claims in 19 runs; V4.1-Flash baseline flags are almost all rebuttals (36) and scorer false positives (15).
- DeepSeek-V4-Pro-0813 ran once on the test split with 52 cases x 1 repeat (a smaller design than the 5-repeat runs, chosen to keep cost low). Verified decision accuracy 1.00 vs baseline 0.88; the gain again comes from the conflicting-evidence category.

## 2026-11-08: a draft failed on the live app; fixes limited to caching and app-side retries
- Live dispute OFG: attempt 1 returned an empty reply after spending all 6,000 output tokens (finish_reason length); attempt 2 was valid JSON but left out the required `confidence` field on every claim, so validation rejected it. Both replies were cached, so clicking "Draft again" replayed the failure.
- The drafter schema was NOT changed (it is what the frozen eval used, and nothing downstream reads `confidence`; making it optional would change what counts as a usable draft, a post-test change). The eval's "no usable draft" counts include this kind of failure.
- Changed: the gateway no longer caches empty or length-truncated replies; the app's `draft_dispute` retries up to 3 times with a fresh cache key. The eval runner is unchanged.

## 2026-11-09: saved drafts were dropping requested_not_provided
- `save_draft` did not store the verifier's `requested_not_provided`, so the page showed "No required evidence is missing" even when PayPal also asked for Proof of refund and Other (seen on live disputes WVY and OFG). Fixed, with a test; unsubmitted drafts already saved were backfilled from each dispute's stored PayPal request using the verifier's gating rule. Submitted drafts were not edited.


## 2026-11-09: why does the verified system sometimes not contest when every claim is VERIFIED?
- Two test-split V4.1-Flash runs ended NOT_CONTEST with all claims VERIFIED; the eval logs did not record the reason (drafts were uncached and the full verification result was not logged).
- Replication on the DEV split (not frozen): 26 dev cases x 5 repeats, DeepSeek-V4.1-Flash, draft and verify only, through the same code as the eval (scripts/hunt_verifier_decisions.py, data in eval/results/dev-hunt-DeepSeek-V4.1-Flash/runs.json). 130 usable runs.
- Runs that ended without a contest, by mechanism: {'required evidence missing': 26, 'consistency issue forced abstain': 15, 'drafter abstained with nothing missing': 6}.
- Runs whose final decision was outside the case's acceptable decisions: 0 of 130 ({}), by mechanism {}.
- Reading: when it happens with nothing missing and no consistency issue, the drafter itself chose ABSTAIN and the verifier respects it; it is not a verifier rule. The reason for the two test-split runs is still not recorded, so this is a replication on a different split, not an explanation of those runs. Rates on test may differ.
- Product consequence: the UI label "Not enough evidence to contest" is wrong when the model hedged on complete evidence; the page should say why (missing evidence, consistency issue, or the model's own abstain with its rationale).
- Correction to the entry above: scored with each case's acceptable_decisions, 0 of the 130 dev runs ended outside the acceptable set (the dev cases where the drafter abstained with nothing missing accept ABSTAIN). The replication shows the mechanism, not the failure seen on the two test-split runs, which come from cases that accept only CONTEST.
- New: saved drafts now store the drafter's own decision, its rationale and the list of rules behind a non-CONTEST decision (decision_reasons), so the page can say why. Existing unsubmitted drafts were backfilled from stored fields only; where nothing was recorded the page says so.

## 2026-11-12: claims that cite buyer-written text now go to NEEDS_REVIEW (post-test rule change)
- Before: only factual claims whose every source was buyer text were capped; a claim of type "other", or one citing the buyer message plus a trusted record, could reach VERIFIED and into the payload notes. On the test split, GLM's verified system had flagged runs citing the buyer message.
- Measured on the DEV split (draft once, verify both ways with the same judge; scripts/measure_untrusted_cap.py): DeepSeek-V4-Flash, 78 runs: 0 VERIFIED claims cited buyer text under the old rule, so no change (48 contests both ways). GLM-5.3-Flash, 61 usable runs: 1 VERIFIED claim cited buyer text ("The buyer message on file states ..."); with the cap, VERIFIED claims 212 -> 211, contests 38 -> 38, 0 contests lost. Data: eval/results/dev-cap-GLM-5.3-Flash/runs.json.
- Decision: cap on by default. The published test-split results were produced with it off and are unchanged; untrusted_cap=False reproduces them. Small samples on the dev split, not the test split.
