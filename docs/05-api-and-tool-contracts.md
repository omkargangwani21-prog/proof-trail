# 05 — API and Retrieval Contracts


## 1. PayPal calls
Base: `https://api-m.sandbox.paypal.com` (code refuses any other host). Auth: `POST /v1/oauth2/token` with client credentials; cache token until near expiry. Idempotency header `PayPal-Request-Id` on writes **[VERIFY]**.

| Purpose | Call | Notes |
|---|---|---|
| List disputes | `GET /v1/customer/disputes` | params: `start_time`, `disputed_transaction_id`, `page`, `page_size`, `next_page_token`, `dispute_state`, `create_time_*`, `update_time_*` |
| Dispute details | `GET /v1/customer/disputes/{id}` | fields depend on scope; HATEOAS links show allowed actions (e.g. `provide-evidence`) |
| Provide evidence | `POST /v1/customer/disputes/{id}/provide-evidence` | multipart/form-data; only when status `WAITING_FOR_SELLER_RESPONSE`; example `evidences[{evidence_type, evidence_info{tracking_info[{carrier_name,tracking_number}]}, notes}]` |
| Accept claim | `POST /v1/customer/disputes/{id}/accept-claim` | `accept_claim_type` in `REFUND`, `REFUND_WITH_RETURN`, `PARTIAL_REFUND`, `REFUND_WITH_RETURN_SHIPMENT_LABEL`; choose only from `allowed_response_options` |
| Sandbox: require evidence | `POST .../require-evidence` | moves `UNDER_REVIEW` → `WAITING_FOR_SELLER_RESPONSE` (action `SELLER_EVIDENCE`). **Sandbox only** |
| Sandbox: adjudicate | `POST .../adjudicate` | `BUYER_FAVOR`/`SELLER_FAVOR`; needs `UNDER_REVIEW`. **Sandbox only** |
| Create order | Orders v2 `POST /v2/checkout/orders` | **[VERIFY]** payload and approval flow |
| Capture | Orders v2 `POST /v2/checkout/orders/{id}/capture` | **[VERIFY]** |
| Verify webhook | `POST /v1/notifications/verify-webhook-signature` | needs `webhook_id` from dashboard; header names **[VERIFY]** |

**Not available to us by default (limited-release per the schema note):** create, cancel, compute-metrics, change-reason, validate-eligibility dispute methods. API creation needs `DISPUTE_CREATE` scope enabled by a PayPal account manager, buyer consent and a `PayPal-Auth-Assertion` header. Our primary path is a buyer-opened sandbox case; see Gate 1 (doc 09).

Webhook events: `CUSTOMER.DISPUTE.CREATED`, `.UPDATED`, `.RESOLVED`. Same event may arrive more than once → dedupe on event id. Webhook Simulator fails signature verification, so test with real sandbox transactions.

Lifecycle reference: INQUIRY → claim; billing and unauthorized disputes go directly to claims; seller response window about 10 days; escalate only from `INQUIRY`.

## 2. Our HTTP routes
| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Disputes queue |
| GET | `/disputes/{id}` | Workspace |
| POST | `/disputes/{id}/draft` | Run agent + verifier |
| POST | `/disputes/{id}/approve` | Record approval (CSRF token required) |
| POST | `/disputes/{id}/submit` | Submit (needs approval; `?dry_run=1` default) |
| POST | `/disputes/{id}/accept` | Accept-claim path |
| POST | `/webhooks/paypal` | Receiver |
| GET | `/trail/{order_id}` | Trail viewer |
| GET/POST | `/agent` | Demo agent simulator |
| GET | `/eval` | Results |
| GET | `/settings` | Mode, budget, keys status (never values) |
| GET | `/healthz` | Health |

Errors use `{ "error": {"code": "...", "message": "..."} }`. Codes: `NOT_APPROVED`, `BUDGET_EXCEEDED`, `NON_SANDBOX_URL`, `BAD_SIGNATURE`, `INVALID_DRAFT`, `PAYPAL_ERROR`.

## 3. Retrieval functions and the fixed-plan runner
These are **application functions, not model-callable tools**. Code calls them; the model never sees their names and never triggers them. All return JSON containing `record_id`s. None writes to PayPal.

| Function (called by code) | Args | Returns |
|---|---|---|
| `get_dispute` | none | dispute record |
| `get_order` | `order_id` | order + items |
| `get_trail` | `order_id` | trail events + verification flag |
| `get_shipment` | `order_id` | shipment records |
| `get_policy` | none | active policy text |
| `list_buyer_messages` | none | messages wrapped `<untrusted>…</untrusted>` |
| `search_prior_orders` | `buyer_ref` | prior orders summary |
| `store_draft` | `draft` | called by code after JSON validation; stores the draft locally only; **no PayPal call** |

**Runner decision (one runner everywhere):** fixed-plan JSON runner. Steps: (1) code calls the retrieval functions in a fixed order; (2) code packs the outputs into the prompt, untrusted text delimited; (3) one model call returns a `Draft` JSON; (4) code validates it against the schema (invalid → retry once, then `INVALID_DRAFT`); (5) code runs the verifier; (6) code calls `store_draft`. No native tool calling is used, so every model is tested under identical conditions and eval numbers describe the same flow the app runs.

## 4. Draft output schema (Pydantic)
```python
class SourceRef(BaseModel):
    record_id: str
    field: str
    quoted_value: str

class Claim(BaseModel):
    claim_id: str
    text: str
    type: Literal["fulfillment","authorization","policy","history","other"]
    source_refs: list[SourceRef]   # may be empty only if the model abstains on that point
    confidence: float              # 0..1, advisory only

class Draft(BaseModel):
    decision: Literal["CONTEST","ACCEPT","ABSTAIN"]
    rationale: str
    claims: list[Claim]
    missing_evidence: list[str]
```

## 5. LLM gateway contract
`chat(role, model, messages, max_tokens, temperature, cache=True) -> {text, usage, cost_usd, cached}`. Behavior: look up cache by hash, check budget, call, log to `llm_calls`, raise `BUDGET_EXCEEDED` at hard cap. Base URL `https://api.tokenfactory.nebius.com/v1` **[VERIFY in console]**.

## 6. Contract tests
- Fixture-based test per PayPal call shape (recorded JSON).
- Schema fuzz: malformed LLM output always yields `INVALID_DRAFT`, never an exception to the user.
- Route test: `/submit` without approval → 403.
