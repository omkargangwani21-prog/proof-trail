# 00 — Project Context (source of truth)

> Last updated: 2026-11-05. Status tags: **[LOCKED]** decided, **[ASSUMED]** proposed and not objected to, **[VERIFY]** unverified fact, must be checked before use.

## 1. One-liner
**ProofTrail** is an open-source dispute-defense agent for PayPal merchants. It drafts dispute evidence where every claim cites a source record (or abstains), a verifier checks every claim, a human approves, and only then is anything submitted through the PayPal Disputes API.

## 2. Problem (must stay this short)
AI-drafted dispute evidence can contain fabricated details, and merchants have no proof of authorization when an AI agent buys on a customer's behalf. ProofTrail records an intent → cart → payment trail and drafts evidence where every claim is grounded or removed.

## 3. Hard constraints
| Item | Value |
|---|---|
| Hackathon | PayPal AI Hackathon (Devpost) |
| Deadline | **Nov 12, 2026, 12:00 PM PT = Nov 13, 01:30 AM IST**. Internal submit target: **Nov 12, 18:00 IST** |
| Must have | PayPal APIs central + AI; working demo (hosted URL or full run steps); public repo with visible license; YouTube video < 3 min; English |
| Video rules | Shows the project working. No third-party trademarks, no copyrighted music |
| Judging | Stage 1 pass/fail; Stage 2 five equal criteria: Technological Implementation, Design, Potential Impact, Innovation, Presentation. Ties broken by Technological Implementation |
| Budget | LLM spend **hard cap $20** (soft stop $15). Promo credits about $29.50 |
| Environment | Windows + WSL2 Ubuntu, project in `~/proof-trail`. Ryzen 7, RTX 4050 6 GB |
| Secrets | Only in local `.env`. `.env` and `.venv/` in `.gitignore`. Never in chat, code or logs |
| Sandbox only | PayPal base URL `https://api-m.sandbox.paypal.com`. Live URL refused in code |

## 4. Locked decisions
| Decision | Value | Status |
|---|---|---|
| Name | ProofTrail (no PayPal marks) | [ASSUMED] |
| Language / framework | Python 3.12, FastAPI, Pydantic, SQLite | [ASSUMED] |
| UI | Jinja + HTMX + Tailwind CDN, no Node build | [ASSUMED] |
| LLM provider | Nebius Token Factory (OpenAI-compatible SDK) | [LOCKED] |
| Main agent model | `deepseek-ai/DeepSeek-V4-Flash-0731` ($0.14/$0.28) | [LOCKED] |
| Judge | `openai/gpt-oss-120b` ($0.15/$0.60), different family from main agent | [LOCKED] |
| Premium reference | `deepseek-ai/DeepSeek-V4-Pro-0813` ($1.32/$3.96), ~40-run subset only | [LOCKED] |
| Cheap dev | `Qwen/Qwen3-30B-A3B-Instruct-2507` ($0.10/$0.30) | [LOCKED] |
| Cross-model panel (eval, 2 repeats, same fixed-plan JSON runner for every model, separate from the 3-system ablation) | `Qwen/Qwen3-235B-A22B-Instruct-2507` ($0.20/$0.60), `zai-org/GLM-5.3-Flash` ($0.15/$0.50), `deepseek-ai/DeepSeek-V4.1-Flash` ($0.30/$1.20), optional `google/gemma-3-27b-it` ($0.10/$0.30) | [LOCKED] |
| Judge when judge model is also the agent | `nvidia/nemotron-3-super-120b-a12b` ($0.30/$0.90) | [LOCKED] |
| Excluded | Kimi K3 / K3.1 Pro, GLM 5.1-5.3, Hermes 405B, Nemotron Ultra, Muse Spark, Qwen3.5 397B (too pricey for a $20 cap), VL/embedding models (wrong job) | [LOCKED] |
| License | MIT | [ASSUMED] |
| Scope | Full scope, no cuts (user decision) | [LOCKED] |
| Win-rate claims | **Forbidden** | [LOCKED] |

Model IDs and prices come from the user's console list (2026-11-05). Gate 0 still requires a smoke test (schema-valid JSON on 5 of 5 tries through the fixed-plan runner) per model. Reasoning models may emit hidden thinking tokens; real cost is read from the gateway, not assumed.

## 5. Scope in one paragraph
Demo shopping agent places a sandbox order and writes a signed trail. A dispute arrives (webhook or poll). The case builder assembles a bundle of source records. Code fetches the records in a fixed order and one model call drafts claims with citations (fixed-plan JSON runner, no model tools). The verifier drops unsupported claims or abstains. The merchant reviews and approves. The submitter calls `provide-evidence` (dry-run by default). An eval harness proves the effect with an ablation on 40 frozen synthetic cases. A replay mode lets anyone run the demo without keys.

## 6. Document map
00 context · 01 PRD · 02 scope · 03 architecture · 04 data model · 05 API and tool contracts · 06 verifier · 07 eval · 08 security · 09 build plan · 10 UI/UX · 11 design system.

## 7. Known risks (top 5)
1. Dispute creation. Primary path: sandbox buyer account opens an INR/SNAD case manually, app fetches it via API. API creation needs account-manager-enabled scopes, so it is a 1-hour side attempt. Fallback: fixtures/replay (doc 09).
2. Agent-purchase trail is a speculative bet. Kept thin, built last.
3. Synthetic eval can be accused of being rigged. Mitigation: frozen test set, labeled synthetic, judge accuracy reported, failures published.
4. Cost runaway. Client-side budget guard.
5. Solo schedule: 7 days left. Gates in doc 09.

## 7b. Rule for editing
Change a decision here first, then update the affected docs, then code. Never the other way round.
