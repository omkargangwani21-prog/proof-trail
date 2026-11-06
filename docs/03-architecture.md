# 03 — Architecture


## 1. Principles
1. **Agent proposes, verifier checks, human decides, only code submits.**
2. The model has **no tools and no write access**. Application code fetches records (read-only) and calls the model once to produce a `Draft` JSON. The model cannot call any endpoint.
3. Every external call and LLM call is logged and replayable.
4. Untrusted text (buyer messages, notes) is data, never instructions.
5. One command to run, one command to eval.

## 2. System context
```mermaid
flowchart LR
  M[Merchant operator] -->|browser| UI[ProofTrail Web UI]
  UI --> API[FastAPI app]
  API <--> DB[(SQLite)]
  API <-->|OAuth + REST| PP[PayPal Sandbox APIs]
  PP -->|webhooks| API
  API <-->|OpenAI-compatible| NB[Nebius Token Factory]
  B[Sandbox buyer] -->|approves order| PP
```

## 3. Components
```mermaid
flowchart TB
  subgraph App[FastAPI process]
    WH[Webhook receiver + signature check]
    POLL[Poller]
    CB[Case builder]
    AG[Evidence drafter - fixed-plan runner: code fetches records, model returns Draft JSON]
    VF[Verifier L1-L4]
    AP[Approval service + audit log]
    SUB[Submitter - dry-run default]
    DSA[Demo shopping agent]
    TR[Trail recorder - hash chain + HMAC]
    PPC[PayPal client - token cache, retry, sandbox guard]
    GW[LLM gateway - budget, cache, traces]
    UI[Jinja + HTMX UI]
  end
  WH --> CB
  POLL --> CB
  CB --> AG
  AG --> GW
  AG --> VF
  VF --> GW
  VF --> AP
  AP --> SUB
  SUB --> PPC
  DSA --> PPC
  DSA --> TR
  CB --> PPC
  UI --> AP
  UI --> CB
```

## 4. Core flow: dispute to submission
```mermaid
sequenceDiagram
  participant PP as PayPal
  participant WH as Webhook/Poller
  participant CB as Case builder
  participant AG as Evidence drafter
  participant VF as Verifier
  participant U as Merchant
  participant SUB as Submitter
  PP->>WH: CUSTOMER.DISPUTE.CREATED
  WH->>WH: verify signature, dedupe event id
  WH->>CB: dispute_id
  CB->>PP: GET /v1/customer/disputes/{id}
  CB->>CB: join order, shipment, trail, policy -> source_records
  CB->>AG: case bundle
  AG->>AG: code fetches records in fixed order, packs prompt
  AG->>AG: one model call returns Draft JSON, code validates schema
  AG->>VF: draft
  VF->>VF: L1 schema, L2 grounding, L3 judge, L4 policy
  VF->>U: verified draft or ABSTAIN
  U->>SUB: approve (audited)
  SUB->>PP: POST provide-evidence (dry-run default)
```

## 5. Trail flow (agent purchase)
```mermaid
sequenceDiagram
  participant B as Sandbox buyer
  participant DSA as Demo agent
  participant TR as Trail recorder
  participant PP as PayPal
  B->>DSA: intent (e.g. "buy X under $Y")
  DSA->>TR: event intent
  DSA->>TR: event cart
  DSA->>PP: create order
  B->>PP: approve order (human step)
  DSA->>PP: capture
  DSA->>TR: event payment (capture id)
```

## 6. Modes
| Mode | PayPal | LLM | Purpose |
|---|---|---|---|
| `live-sandbox` | sandbox APIs | Nebius | Real demo |
| `replay` | recorded fixtures | cached responses | Judges without keys. UI shows REPLAY badge |
| `eval` | fixtures | Nebius, budget-guarded | Measurement |

## 7. Directory layout
```
proof-trail/
  app/ (main.py, routes/, templates/, static/)
  core/ (paypal_client.py, trail.py, case_builder.py, agent.py, verifier.py, submitter.py, gateway.py)
  data/ (fixtures/, replay/)
  eval/ (cases/, run.py, metrics.py, report.py)
  docs/  tests/  .env.example  Makefile  LICENSE  README.md
```

## 8. Technology choices and why
| Choice | Reason | Rejected |
|---|---|---|
| FastAPI | typed, async, quick | Django (heavy) |
| SQLite | zero setup, file is the demo state | Postgres |
| HTMX + Jinja | no build step, one language | React (build + time) |
| OpenAI SDK → Nebius | provider swap is a base URL | custom client |
| Own eval harness | full control, JSONL traces | heavy frameworks |

## 9. Failure behavior
| Failure | Behavior |
|---|---|
| LLM timeout / invalid JSON | retry once, then mark run FAILED, show in UI |
| PayPal 429/5xx | exponential backoff, max 3 |
| Webhook down | poller catches up |
| Verifier judge unavailable | **fail closed**: claims become Needs review |
| Budget cap hit | block LLM calls, UI shows banner |

## 10. Observability
JSONL trace per run (prompt hash, model, tokens, cost, latency, record ids fetched, schema-validation result). UI shows the run trace link.
