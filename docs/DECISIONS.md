# Decisions log

## 2026-11-06: Gate 1 passed (dispute path)
- A buyer-opened sandbox case (Item not received) is retrievable via `GET /v1/customer/disputes/{id}`.
- Observed: `reason` = `MERCHANDISE_OR_SERVICE_NOT_RECEIVED` (docs previously said `ITEM_NOT_RECEIVED`), `status` = `WAITING_FOR_SELLER_RESPONSE`, `dispute_life_cycle_stage` = `INQUIRY`, `dispute_channel` = `INTERNAL`.
- `seller_response_due_date` is returned.
- `allowed_response_options`: `accept_claim` = [PARTIAL_REFUND, REFUND]; `make_offer` = [REFUND].
- Links returned: self, accept_claim, provide_evidence, send_message, escalate, make_offer.
- `GET /v1/customer/disputes` (list) returned an empty list for this dispute while fetch-by-ID worked. Ingestion must not depend on the list alone. [VERIFY] whether the list catches up later.
- API-based dispute creation is not needed; the buyer-opened path is the primary path.
