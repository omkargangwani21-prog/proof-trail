# 02 — Scope and Non-Goals


## 1. In scope (build all)
| # | Module | Doc |
|---|---|---|
| 1 | PayPal client wrapper (OAuth, retries, sandbox guard) | 05 |
| 2 | Demo shopping agent + sandbox order/capture | 03, 05 |
| 3 | Trail recorder (hash chain + HMAC) and viewer | 03, 04, 06 |
| 4 | Dispute ingestion: webhook + polling + dedupe | 05, 08 |
| 5 | Case builder | 04 |
| 6 | Evidence drafter (fixed-plan JSON runner, no model tools) | 05 |
| 7 | Verifier L1–L4 | 06 |
| 8 | Approval + audit + submitter (dry-run default) | 05, 08 |
| 9 | LLM gateway (budget, cache, traces) | 03 |
| 10 | Eval harness + ablation + report | 07 |
| 11 | Web UI, six screens | 10, 11 |
| 12 | Replay mode | 03 |
| 13 | README, license, 3-minute video, Devpost text | 09 |

## 2. Non-goals (will not build, will not claim)
1. **Live PayPal.** Sandbox only. Never touch real merchant accounts.
2. **Win-rate improvement claims.** No evidence we can produce.
3. **Compliance claims.** Not "PCI", not "AP2 compliant", not "SOC2". The trail is "AP2-inspired".
4. **Legal advice.** Tool does not tell a merchant what the law requires.
5. **Autonomous submission.** Human gate is a product principle, not a missing feature.
6. **Fine-tuning or training models.**
7. **Multi-tenant SaaS, auth providers, billing.** Single-operator demo; basic local auth only.
8. **Card-network chargeback flows** (external disputes via issuer). Only PayPal internal disputes. [VERIFY which sandbox types we can generate]
9. **Mobile app.** Responsive web only.
10. **Using PayPal logos or marks** in the UI or video.
11. **Optional sponsor-tool prizes** (Render, Postman, Zapier…) unless a tool is naturally used. Not a goal.

## 3. Scope-change protocol
A change is allowed only if all are true:
1. It increases a judging criterion we can name.
2. We can name what it displaces on the schedule.
3. It is written into doc 00 first.
Anything else goes to the "After the hackathon" list.

## 4. Honest-limits statement (goes in README)
- Evidence is synthetic; real merchant data was not used.
- Sandbox behavior may differ from live PayPal.
- LLM judge can be wrong; its measured accuracy is reported.
- Results come from 40 cases × 5 repeats and carry wide intervals.

## 5. Parking lot (after hackathon)
Real merchant pilots, Shopify/Woo connectors, additional PSPs, fine-tuned verifier, human-labeled eval set.
