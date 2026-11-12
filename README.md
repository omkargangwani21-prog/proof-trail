# ProofTrail

An open-source assistant for PayPal merchants who respond to disputes. A model drafts the evidence; code checks every claim against the merchant's own records; a person approves; only then does code submit through the PayPal Disputes API. Sandbox only.

## How it works

1. **Disputes arrive.** A poller (`python -m core.poll`), a verified webhook receiver, or a fetch-by-ID form puts disputes into a local queue.
2. **Draft on request.** One click asks the model to draft evidence from the order's records. Every claim must cite a record and a quoted value, or the draft abstains.
3. **Verify.** Each claim gets a label: VERIFIED, NEEDS_REVIEW or REMOVED. Layers: structure (L1), grounding checked by code (L2), an independent judge model from a different family (L3), policy rules such as no blame language and no buyer-text-only claims (L4). The decision is CONTEST only when the evidence PayPal requested (fulfillment) is backed by a verified claim and the records are consistent; otherwise ABSTAIN.
4. **Approve and submit.** A person reviews the claims. The approval is bound to the SHA-256 of the exact payload. Submission is a dry run by default. The audit log is append-only (enforced by SQLite triggers). The code refuses any PayPal base URL that is not the sandbox.
5. **Agent purchases.** A demo shopping agent records a hash-chained, HMAC-signed trail (intent, cart, payment) for each order it places. The trail is shown beside disputes about those orders.

Details: `docs/` (design, verifier, evaluation plan, decisions log).

## Results

Full tables with 95% intervals: [`docs/results.md`](docs/results.md), generated from `eval/results/`. Test split: 52 synthetic cases x 5 repeats, frozen before any test run, each model run once.

- Main model (DeepSeek-V4-Flash-0731): decision accuracy 0.90 for the plain-prompt baseline and 0.99 with the verifier (paired difference -0.09, 95% interval -0.18 to -0.02).
- That gain comes from the 6 conflicting-evidence cases, where a code rule forces ABSTAIN. Differences on unsupported claims, injected text and completeness are small or inside the intervals.
- The verifier has a cost: on DeepSeek it lost a contest it should have made in 2 of 260 runs, on gpt-oss-120b in 5 of 260 (completeness 0.97).
- On weaker baselines the fabrication effect is larger (for example invented tracking numbers on cases with no shipment record).
- Other models are reported in a separate panel, never merged with the headline.

## Limits

- All cases are synthetic and were written by the same author as the system. Results may not transfer to real disputes. 52 cases is a small sample; intervals are wide.
- The accuracy gain is concentrated in one category (6 cases). It comes from a deterministic rule, not from the judge model; the judge's own contribution has not been isolated.
- The verifier is strict. It sometimes removes a valid claim and loses a contest it should have made (counts above). On gpt-oss-120b the verified decision was less consistent across repeats (0.90 vs 0.98 for the baseline). For that agent the judge is a different model (Nemotron), so that row also changes the judge.
- The judge audit scored 60/60 on both judge models, but its pairs were built by hand by the author and are obvious cases. It understates real judge error.
- The scorer counts any mention of attacker text or a forbidden phrase, including a mention made only to reject it, and does not recognise correct dollar restatements of prices stored in minor units. Flagged runs were classified by hand by the system's author with an AI assistant, which is not independent. Raw and classified counts are published side by side.
- GLM-5.3-Flash: 56 of 260 draft runs produced no usable output because generation hit the 6000-token cap. Those rows measure the model under that cap, not the verifier.
- Qwen3-30B was the development model, so its test row is not independent of tuning.
- Rules changed after the frozen test run are logged in `docs/DECISIONS.md` with reasons (for example, only fulfillment evidence now gates a contest). A post-test rule now sends any claim citing buyer-written text to NEEDS_REVIEW. It was measured on small development samples only (78 DeepSeek runs and 61 usable GLM runs); there was no frozen-test rerun, so its impact on test-set results is unknown.
- The agent trail is tamper-evident, not tamper-proof: deleting the newest events is undetectable without an externally stored head hash, and the key holder can forge. The shopper's instruction is recorded as given; the chain shows it was not edited afterwards, not that it is true.
- Shipment and delivery records created by the demo agent are synthetic (`data_origin: synthetic_demo`).
- For unauthorized-payment disputes the current payload shows fulfillment. It does not show that the buyer authorized the purchase, and the trail is not yet sent to PayPal.
- On one sandbox dispute the buyer's case page showed a different ID than the seller API returned. The seller API answers 403 for the buyer-page ID. The cause is unknown.
- The accept-claim path is not built. The webhook receiver is written and unit-tested but has not been run against a live PayPal delivery (it needs a public URL); the poller is the working path.
- Model spend is tracked by a client-side guard. It is a local cap, not a provider-side limit.

## Setup

Python 3.14. Nothing here touches live PayPal.

```bash
git clone <this repository> && cd proof-trail
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt        # requirements.txt for runtime only
cp .env.example .env                       # then fill in your own sandbox keys
python -m pytest -q
```

`.env` variables: `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_BASE` (must be `https://api-m.sandbox.paypal.com`), `NEBIUS_API_KEY`, `NEBIUS_BASE_URL`, `TRAIL_HMAC_KEY` (any long random string), optional `PAYPAL_WEBHOOK_ID`. Never commit `.env`.

## Run

```bash
python -m uvicorn app.main:app --port 8000   # the web app
python -m core.poll --once                   # pull disputes from the PayPal sandbox
python -m core.demo_agent start "buy a desk lamp under 60 dollars"   # then approve as the sandbox buyer
python -m core.demo_agent finish
```

### Offline replay demo

To browse the synthetic queue, a reviewed draft, the trail, and the sample evaluation without configuring API keys:

```bash
bash scripts/replay-demo.sh
```

Replay mode loads synthetic dev cases and a fixed, precomputed draft into a temporary SQLite file outside the repository. The dispute queue, workspace, citations, payload download, approval, and dry run use the app’s database path; Trail and Eval use labeled display fixtures. The app blocks model drafting, PayPal fetch, poll refresh, and webhook requests. Submitting a synthetic sample can only record a local dry run. Sample figures and cases are for demonstration only.

Environment switches for the app: `PT_DB` (database path), `PT_SUBMIT_MODE` (`dry-run` is the default; `sandbox-submit` sends evidence to the PayPal sandbox).

Evaluation (a run without `--go` is a dry run that prints the estimated cost and spends nothing):

```bash
python -m eval.run --split test --model deepseek-ai/DeepSeek-V4-Flash-0731 --repeats 5
python -m eval.run --split test --model deepseek-ai/DeepSeek-V4-Flash-0731 --repeats 5 --go
python -m eval.report <run folder> ; python -m eval.summary <run folder> ; python -m eval.tables
```

## Layout

`core/` drafting, verifier, judge, trail, ingestion, PayPal client. `app/` web app. `eval/` cases, scorer, runner, reports, published results. `docs/` design and decisions. `tests/`. `scripts/historical/` throwaway development scripts, not part of the product.

## License

See `LICENSE`.
