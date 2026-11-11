# TONIGHT-2: coverage, critic audit and full cycles

Sol's high applicable count mainly covers narrower claims it created during Argue. Those findings are often appropriate to the cited source, but do not establish coverage of the original question. Both full aspirin runs and Energy fail the declared E6 gate. GenAI passes that structural gate and discharges a reopened assumption, while failing its expected-undecided shape check.

| Item | Result | Evidence |
|---|---|---|
| N1: CQ agreement | No comparable same-claim argument pairs, even with the requested loose key; agreement rates are not estimable. | [CQ agreement](../../experiments/E2/cq_agreement.md), [provisional review](../../experiments/E2/cq_adjudication_provisional.json) |
| N2: answered-assumption audit | New `answer_inadequate` undercuts reopen satisfied/defaulted assumptions; a newer evidence-backed Respond answer is required for discharge. Six E3.1 critiques ran. Attack counts did not rise; against-Sol overlap has no valid denominator. No protected provisional-review CQ was reopened. | [E3.1](../../experiments/E3/report.md), [analysis](../../experiments/E3_1/analysis.json) |
| N3: original/scoped split | Sol's H1 after-H2 mean is 17.67 applicable arguments: 1.00 original and 16.67 Argue-scoped. Sonnet's is 2.00 original and 0.00 scoped. Original-main IN support is 0.00 for Sol and 0.67 for Sonnet. | [E2 split table](../../experiments/E2/report.md) |
| N4: aspirin full cycles | Both complete and fail. Sonnet has no accepted or surviving supported main answer and one flagged absence assertion. Sol accepts a qualified recommendation record, but Revise leaves one covered original claim unargued. Neither discharges a reopened assumption. | [E6](E6.md) |
| N5: six labels | Accepted, refuted, defeated, contested, unsupported and untested are derived without changing in/out/undecided. Expected undecided now requires a genuine pro/con contest. | [Label tests](../../tests/test_status_labels.py), per-run labelled summaries linked from E6 |
| N6: generalisation | One fixed-packet run each, Sol proposer/Sonnet critic. Energy has 25 scoped supports, zero original supports and no live whole-question answer. GenAI has zero unargued covered claims and one reopened CQ discharged; its accepted definitional answer triggers an early stop and the expected-undecided shape check is false. | [Generalisation report](E6-generalisation.md) |

## What the aspirin result establishes

N1 does not establish that one provider is too strict on the same inference: the proposed inferences differ. The ten review entries are scope contrasts, not fabricated matched disagreements. The user explicitly asked to continue while asleep; the separate adjudication is therefore **agent-provisional**, with the human file preserved blank and no claim of Mamadou review.

The critic mechanism works on saved graphs and in the Sonnet full cycle. It does not, by itself, produce the predicted broad collapse of Sol's scoped supports. E3.1 remains a failed/non-estimable experiment rather than being relabelled a pass to open E6. N4's stated requirement was to commit the mechanism and record E3.1, and its guard-based E1 rule retains the raw 1/12 specificity-failure rate.

The missing composed answer remains a separate issue. Sol's accepted aspirin main answer is explicitly the USPSTF recommendation/benefit-harm assessment, rather than a demonstrated uniform causal net harm across every adult aged 60 or older. Sonnet's broader claims remain blocked. No composition fix was introduced during these measurements.

The requested six-label vocabulary omits weak, unopposed support below the proof standard. That case uses `unsupported` with an explicit insufficient-support reason. It never earns a contested/undecided shape success.

## Execution constraints

All calls use `openai:gpt-6.1-sol` and `anthropic:claude-sonnet-5-5`, medium effort. Each full cycle has a two-round limit and one Frame sample, with no human frame edits. An early stop on acceptance is retained. Only held-in questions and saved source text are used; no live retrieval or Opus run is configured. The shared tonight-only ledger allows $16 Anthropic and $10 OpenAI while protecting the separate $20 Opus reserve. No generalisation result is used to tune tonight's code.

Implementation commits: N1 `3f719d9`, N2 `d03690c`, N3 `20a225a`, N4 `eefca14`, N5 `6cf25ab`. Test baselines/results: N1 125 → 130, N2 130 → 135, N3 135 → 137, N4 137 → 139, N5 139 → 147; N6 starts with 147 passing tests. Each item was committed separately with its predicted effect.

## Final validation and cost

**147 tests pass before and after N6.** Every full-cycle graph reproduces its saved proof statuses and argument labels under the final evaluator. All graph references, packet fingerprints, final state anchors and hash-chained ledgers verify. Native aspirin state and metrics were preserved; separate derived files add N5's labels. The ten human-adjudication fields remain blank. No model/API error, pending call or unknown charge remains. The pre-existing `bench/results/20261110-0233.json` is untouched.

| Tonight-only work | API calls | Anthropic estimate | OpenAI estimate |
|---|---:|---:|---:|
| E3.1 saved-graph critiques | 6 | $0.5826 | $0.4437 |
| Aspirin: Sonnet proposer | 36 | $1.2434 | $0.1252 |
| Aspirin: Sol proposer | 23 | $0.0950 | $0.8016 |
| Energy: Sol proposer | 155 | $0.1932 | $3.7933 |
| GenAI: Sol proposer | 42 | $0.1493 | $1.3760 |
| Total | 262 | $2.2634 | $6.5399 |

Total usage-based estimate: **$8.8033**, within the $16/$10 operational limits. The $20 Opus reserve is untouched. N6 alone costs $5.5118. These totals exclude the earlier campaign; they reconcile exactly before rounding with the tonight-only budget ledger. The machine-readable verification is [tonight-2-audit.json](../../experiments/tonight-2-audit.json), reproducible locally with `python -m experiments.audit_tonight_2` while the ignored raw runs remain available.

The remaining design decision concerns whole-question closure: Energy loses every live main-answer claim to component scope, while GenAI stops on a relevant definitional claim. Neither result justifies treating a high applicable count as completion of the requested inquiry. This is recorded for the next composition/stopping decision; no repair or extra sample was introduced from these results.
