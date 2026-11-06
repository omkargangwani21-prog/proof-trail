# 09 — Build Plan and Gates


## 1. Order of work (risk first)
1. Prove credentials and APIs.
2. Prove a dispute can exist in the sandbox.
3. Build the core (case → agent → verifier → approval).
4. Measure.
5. UI polish, then video.
6. Trail/agent-purchase last and thin.

## 2. Day plan
| Day | Date | Work | Exit gate |
|---|---|---|---|
| D0 | Thu Nov 5 (eve) | Repo, WSL2, `.env`, token test, Nebius key test, model smoke tests | **Gate 0** |
| D1 | Fri Nov 6 | PayPal client, order/capture, find dispute-creation path, webhook or poller | **Gate 1** |
| D2 | Sat Nov 7 | DB, case builder, fixtures, LLM gateway, agent v1 | agent drafts on fixture |
| D3 | Sun Nov 8 | Verifier L1–L4, approval, submitter, dry-run, minimal UI | **Gate 2: e2e on fixture** |
| D4 | Mon Nov 9 | Eval generator, baseline, dev-set iteration, trail recorder | dev results |
| D5 | Tue Nov 10 | Freeze, **Gate 3: test run**, UI screens complete | results.json |
| D6 | Wed Nov 11 | UI polish, README, replay mode check, record video | **Gate 4: video + README done** |
| D7 | Thu Nov 12 | Fresh-clone test, license check, Devpost text, submit by 18:00 IST | submitted |

## 3. Gates
### Gate 0 — Foundations (Nov 5)
Pass when ALL true:
- `test_token.py` returns 200 and `scope` list is shown (no secret printed).
- `proof-trail` app is attached to the US Business sandbox account; Disputes enabled in app features.
- Nebius key works; **model IDs copied exactly from the console**; each planned model confirmed as per-token "Public".
- Smoke test per model through the **fixed-plan JSON runner** (doc 05 §3): the call must return valid schema JSON on 5 of 5 tries on one dev case. Models that fail are excluded from the panel. Native tool calling is not required.
- Repo public with MIT LICENSE, `.gitignore` correct.
Fail → fix before anything else. Model fails the JSON smoke test → drop it from the panel.

### Gate 1 — Dispute path (Nov 6, by evening)
Try in order, spend at most ~3 hours total:
- **Plan A (primary)**: make a sandbox test transaction, then log in as the sandbox **buyer (personal) account** and open an INR or SNAD case manually (PayPal's dispute test guide describes this). The merchant app then retrieves it via `GET /v1/customer/disputes`. Use `require-evidence` to reach `WAITING_FOR_SELLER_RESPONSE` if needed. Exact UI click path is **[VERIFY]**.
- **Plan B (time-box 1 h, do not depend on it)**: create the dispute by API. PayPal's docs say this needs the `DISPUTE_CREATE` scope added to the REST app **by a PayPal account manager**, buyer consent via Log in with PayPal, and a `PayPal-Auth-Assertion` JWT header. Likely blocked for us.
- **Plan C**: fixtures for disputes; keep real sandbox for orders/capture and for `GET`/`provide-evidence` on any dispute obtainable. Label clearly "fixture dispute".
Pass: Plan A (or B) yields a real sandbox dispute fetched via API, **or** C is declared and the README says so honestly. We never imply a real dispute if it is a fixture.

### Gate 2 — Core works (Nov 8)
Fixture dispute → case bundle → draft → verifier → approval → dry-run payload. A seeded fabricated claim is removed. Unit tests green.

### Gate 3 — Measured (Nov 10)
Test set hash committed, `make eval` done, spend under $15 total. If a result is unflattering, keep it.

### Gate 4 — Shippable (Nov 11)
Video under 3:00 recorded, README has run steps and Limits, replay mode works on a fresh clone, no secrets, license visible.

## 4. Fallback table
| Risk | Trigger | Response |
|---|---|---|
| Buyer-created sandbox dispute fails | Gate 1 | API route (1 h box), then fixtures (Plan C) |
| Webhooks unreachable | no tunnel | poller + say so |
| Model fails JSON smoke test | Gate 0 | exclude from panel |
| Budget at $15 | gateway | stop experiments; use cache; remove premium subset |
| Behind schedule at D5 | test run not done | drop optional Gemma/premium panels first, never drop test run or video |
| Trail unfinished at D6 | not working | ship with simplified recorder, state limits |

Cut order if forced (user said no cuts; this is a pre-agreed emergency order, decided by the user): optional models → UI extras → trail viewer polish. Never cut: verifier, eval, README, video.

## 5. Definition of done
Doc 01 FR list passes; doc 08 checklist ticked; fresh clone runs replay in under 5 minutes.

## 6. Daily routine
Morning: check `llm_calls` spend and the Nebius balance. Evening: commit, update this table. Keep a `DECISIONS.md` for any change to doc 00.

## 7. Submission pack
Repo URL, Devpost description (problem, how PayPal APIs are used, how AI is used, limits), YouTube link, run instructions, license. Describe the project only; no personal roles or team references.

## 8. Video storyboard (≤ 2:50)
| Time | Shot |
|---|---|
| 0:00–0:15 | Problem: AI evidence can invent facts |
| 0:15–0:40 | Demo agent buys, trail appears |
| 0:40–1:00 | Dispute arrives in queue |
| 1:00–1:40 | Draft: citation pills, one claim Removed, one ABSTAIN example |
| 1:40–2:05 | Approve, payload preview, dry-run/sandbox submit |
| 2:05–2:35 | Eval ablation chart, cost, failure browser |
| 2:35–2:50 | Limits and open-source repo |
No logos, no music, no secrets on screen.
