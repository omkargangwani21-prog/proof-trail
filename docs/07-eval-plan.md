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

**Cross-model panel** (separate table, never mixed into the ablation). As run: each panel model runs all three systems on the full test split (52 cases × 5 repeats) through the same runner, so panel rows have the same shape as the ablation. This replaces the earlier plan of Verified-only, 40 cases × 2 repeats. Judge is `openai/gpt-oss-120b`; when gpt-oss-120b is the agent the judge is `nvidia/nemotron-3-super-120b-a12b` (never self-judging), so that row also changes the judge. `Qwen/Qwen3-30B-A3B-Instruct-2507` was the dev-iteration model: prompts and rules were tuned while looking at its output, so its test row is not independent of that tuning. Models actually run are the ones with a folder in `eval/results/` (planned: gpt-oss-120b, Qwen3-235B, GLM-5.3-Flash, DeepSeek-V4.1-Flash, and a V4-Pro subset); a model with no folder was not run. Gemma was dropped.

## 3. Dataset
Generated from templates with **ground truth by construction** (we know which facts are true because we wrote the records).

| Split | Cases | Use |
|---|---|---|
| Dev | 26 | tune prompts. May be inspected freely |
| Test | 52 | **frozen** (hashes in `eval/cases/MANIFEST.json`) before any test run. Never tuned on |

Test mix: 10 clean, 8 missing-evidence, 6 conflicting-evidence, 8 injection, 8 agent-trail, 12 partial-evidence (52). Partial cases are split shipments, in-transit shipments, and records missing a carrier or an authorization trail. For split and in-transit shipments both CONTEST and ABSTAIN are acceptable (`acceptable_decisions` in each case's truth). The `partial` category was added, and the dev and test sizes changed from 20 / 40, before any test run (DECISIONS.md). Seeds stored. Generator in `eval/gen_cases.py`.

Risk of synthetic bias is stated in README. A small hand-written appendix of 10 cases written without the generator is added to check template overfitting. The hand-written appendix of 10 cases is not built as of this edit, so template overfitting is an unchecked threat.

## 4. Repeats
5 runs per case per system → 52 × 5 = 260 runs per system per model. Sampling settings are in `eval/run.py`.

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

The scorer matches forbidden phrases as whole words and counts any mention of attacker text or a forbidden phrase in the payload, including a mention made only to reject it. Flagged runs are therefore hand-classified (ADOPTED, REBUTTAL, FABRICATION, CITATION_VIOLATION, FALSE_POSITIVE) and the classification is published beside the raw scorer numbers (`flag-classification.json` in each results folder). The classification was done by the system's author with an AI assistant, so it is not independent. Post-hoc scorer and rule changes are logged in DECISIONS.md.

## 6. Statistics
**Unit of analysis is the case (n = 52), not the run.** The 5 repeats of a case are repeated measurements of the same case, not independent examples.
1. Per-case metric = mean over that case's repeats.
2. System comparisons are **paired on case IDs**: compute the per-case difference (baseline − ours), then **cluster bootstrap** over cases (resample cases with replacement, keeping each case's repeats together, 10,000 resamples), and report the mean difference with a 95% percentile interval.
3. Absolute rates per system use the same case-level bootstrap. Do not use Wilson intervals on the 260 pooled runs.
4. Report n = 52 cases × 5 repeats. Do not hide wide intervals. No significance claims beyond what intervals support.

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

Actuals so far (test split, 52 cases × 5 repeats, all three systems): DeepSeek-V4-Flash about $0.20 (runner estimate $0.66), Qwen3-30B about $0.18 (estimate $0.66), gpt-oss-120b about $0.35 (estimate $1.18). The runner's estimate is conservative by roughly 3x.

## 8. Protocol
1. Freeze prompts and test set (commit hash).
2. Dry run: `python -m eval.run --split test --model <id> --repeats 5` (no `--go`) prints the cost estimate and spends nothing.
3. `python -m eval.run --split test --model <id> --repeats 5 --go` writes `eval/out/<split>-<model>-<timestamp>/` (config.json, results.jsonl). `python -m eval.report <run>` and `python -m eval.summary <run>` produce the report and summary.json. Published copies live in `eval/results/<split>-<model>/`.
4. Publish **failures**: every Verified-system failure is printed in each `report.txt` and listed in `summary.json`.
5. Any rerun after seeing test results is disclosed as such.

## 9. Outputs
Headline chart (unsupported-claim rate, baseline vs ours, with CI), model table, cost table, failure browser, reproducibility block (commit, seed, model IDs, date).

## 10. Threats to validity
Synthetic data; same-author prompts and checks; small n; model nondeterminism and provider drift; judge error. All listed in README under "Limits".


## 11. As run: deviations and gaps
- Sizes, panel shape and commands differ from the plan above and are stated in place. Post-hoc changes (scorer fixes, label policy, the verifier's evidence gating) are in DECISIONS.md with reasons.
- Reading of the results so far, without numbers (see each results folder): the decision-accuracy gain comes almost entirely from the conflicting-evidence category, where code rules force ABSTAIN; other differences are small or inside the intervals. The verifier has a measurable cost on some models (lost contests from removed claims, lower consistency). The fabrication effect is large on weaker baselines and negligible on DeepSeek-V4-Flash. No claim here generalizes beyond synthetic data written by the system's author.
- Not done as of this edit: the hand-written 10-case appendix, abstention calibration, claim-set Jaccard, and a p50/p95 latency table (latency is recorded per run but not reported). An ablation without the L3 judge, to isolate its contribution, has not been run.
