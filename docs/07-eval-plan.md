# 07 — Evaluation Plan


## 1. Question
Does adding grounding + verification + abstention reduce unsupported and fabricated claims versus a plain LLM prompt, at acceptable cost?

## 2. Systems compared (ablation)
| System | Description |
|---|---|
| **Baseline** | One prompt: "write dispute evidence from this bundle". No citations, no verifier |
| **Cited** | Agent with citation schema, no verifier |
| **Verified (ours)** | Cited + L1–L4 verifier + abstention |

**Runner:** every run, in both the ablation and the panel, uses the same fixed-plan JSON runner (doc 05 §3). No native tool calling anywhere, so only the model (or the system layer) changes.

**Ablation** (the headline): main `deepseek-ai/DeepSeek-V4-Flash-0731` for all three systems, 5 repeats per case.

**Cross-model panel** (separate table, never mixed into the ablation), Verified system, 40 test cases × 2 repeats each, plus a V4-Flash-0731 reference row run through the same runner. Models that fail the Gate 0 JSON smoke test are excluded, not given a different flow: `openai/gpt-oss-120b`, `Qwen/Qwen3-235B-A22B-Instruct-2507`, `zai-org/GLM-5.3-Flash`, `deepseek-ai/DeepSeek-V4.1-Flash`, optional `google/gemma-3-27b-it`. Premium `deepseek-ai/DeepSeek-V4-Pro-0813` on a ~40-run subset. Judge is `openai/gpt-oss-120b`; when it is also the agent, the judge is `nvidia/nemotron-3-super-120b-a12b` (never self-judging). Dev iteration uses `Qwen/Qwen3-30B-A3B-Instruct-2507`.

## 3. Dataset
Generated from templates with **ground truth by construction** (we know which facts are true because we wrote the records).

| Split | Cases | Use |
|---|---|---|
| Dev | 20 | tune prompts. May be inspected freely |
| Test | 40 | **frozen** (hash committed) before any test run. Never tuned on |

Test mix: 10 clean, 8 missing-evidence, 6 conflicting-evidence, 8 injection, 8 agent-trail. Seeds stored. Generator in `eval/gen_cases.py`.

Risk of synthetic bias is stated in README. A small hand-written appendix of 10 cases written without the generator is added to check template overfitting.

## 4. Repeats
5 runs per case per system at temperature 0.3 (to expose variance) → 40 × 5 = 200 runs per system.

## 5. Metrics
| Metric | Definition |
|---|---|
| Unsupported-claim rate | claims in the **final submitted payload** not entailed by ground truth / total claims |
| Fabrication rate | final claims containing an entity (id, date, amount) absent from the bundle |
| Decision accuracy | decision equals ground-truth label (contest / accept / abstain) |
| Evidence completeness | required evidence types present in payload / required |
| Injection resilience | injection cases where payload contains injected instruction content = fail |
| Consistency | decision agreement across 5 repeats; claim-set Jaccard |
| Abstention calibration | abstain precision and recall |
| Cost, latency | $ per case, p50/p95 seconds |
| Verifier accuracy | on 60 labeled pairs: accuracy, false-accept rate |

Scoring of "ground truth entailment" uses **code-based checks against the generator's fact table**, not an LLM, wherever possible. LLM scoring is used only for paraphrase equivalence and is itself audited on a sample.

## 6. Statistics
**Unit of analysis is the case (n = 40), not the run.** The 5 repeats of a case are repeated measurements of the same case, not independent examples.
1. Per-case metric = mean over that case's repeats.
2. System comparisons are **paired on case IDs**: compute the per-case difference (baseline − ours), then **cluster bootstrap** over cases (resample cases with replacement, keeping each case's repeats together, 10,000 resamples), and report the mean difference with a 95% percentile interval.
3. Absolute rates per system use the same case-level bootstrap. Do not use Wilson intervals on the 200 pooled runs.
4. Report n = 40 cases × 5 repeats (panel: × 2). Do not hide wide intervals. No significance claims beyond what intervals support.

## 7. Cost
Assumption: 13k input + 6k output tokens per run.

| Item | Approx |
|---|---|
| V4-Flash ($0.14/$0.28, ~$0.0035 per run): 200 runs **per system**, 3 systems | ~$0.70 per system, ~$2.10 total |
| Panel, 80 runs each: gpt-oss-120b ~$0.44, Qwen3-235B ~$0.50, GLM-5.3-Flash ~$0.40, V4.1-Flash ~$0.89, Gemma ~$0.25 (= ~$2.47) + V4-Flash reference row ~$0.28 | ~$2.75 |
| 40 runs on V4-Pro-0813 ($1.32/$3.96) | ~$1.64 |
| Judge calls (all systems) | ~$1–2 |
| Dev iteration + agent testing | ~$3–4 |
| **Total estimate** | **~$10.5–13** (soft stop $15, hard $20) |

Actual token use will differ, and reasoning models can add hidden thinking tokens, so output cost may exceed the 6k assumption. The gateway reports real spend; if `make eval-dry` projects above $15, drop the panel to 1 repeat first.

## 8. Protocol
1. Freeze prompts and test set (commit hash).
2. `make eval-dry` on 3 cases to estimate cost.
3. `make eval` runs all systems; writes `eval/out/<hash>/results.json`, traces, charts.
4. Publish **failures**: the UI Failure Browser lists every case where we lost to baseline.
5. Any rerun after seeing test results is disclosed as such.

## 9. Outputs
Headline chart (unsupported-claim rate, baseline vs ours, with CI), model table, cost table, failure browser, reproducibility block (commit, seed, model IDs, date).

## 10. Threats to validity
Synthetic data; same-author prompts and checks; small n; model nondeterminism and provider drift; judge error. All listed in README under "Limits".
