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
