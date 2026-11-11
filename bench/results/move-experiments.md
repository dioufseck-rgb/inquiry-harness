# Move experiments: two providers, fixed graphs

This page records the initial campaign through `0cb1476`. The subsequent [TONIGHT-2 work](tonight-2.md) adds the CQ audit, original/scoped split, six labels and the [full E6 aspirin runs](E6.md). E6's skip below describes the original stopping point; the follow-up runs completed and both failed their declared gate. Costs below cover only the initial campaign.

E2, E4 and E5 pass their stated gates. E1's raw specificity gate and E3's attack-count gate fail. E6 was therefore skipped, including Opus. No held-out question or live full-harness run was made during this campaign.

Both providers use medium effort: `openai:gpt-6.1-sol` and `anthropic:claude-sonnet-5-5`. Every sample records provider, model, effort, usage, cost estimate, graph hash and errors. All costs below are usage estimates, not invoice totals.

| Experiment | Result | Evidence |
|---|---|---|
| [E1](../../experiments/E1/report.md) | Fail | All final retained claims pass the code guard and retain nulls per issue. One of three final-candidate Sonnet aspirin raw proposals still invented an endpoint recipe. The other 11 final-candidate samples pass. |
| [E2](../../experiments/E2/report.md) | Pass | All 36 samples complete; H1 + H2 has zero supported-but-unargued claims and unusable share below 30% on both providers. |
| [E3](../../experiments/E3/report.md) | Fail | Applicable attacks average 2.00–4.33 across the four critic/proposer cells. Only one sample reaches six; the five-attack condition is not met on both. Needs were manually tagged. |
| [E4](../../experiments/E4/report.md) | Pass | Final candidate answers every standing attack; all concessions have validated CQ/check/reason records; mean defenses exceed concessions on both providers. |
| [E5](../../experiments/E5/report.md) | Pass | Grade D is extracted in all six guarded samples and 100% of retained quotes verify on both providers. Direction agreement is reported separately. |
| [E6 follow-up](E6.md) | Initially skipped | The initial campaign required E1 and E2 to pass. TONIGHT-2 later authorized the retained-claim guard rule and recorded the full runs separately. The $20 Anthropic Opus reserve remains unused. |

## What changed

The infrastructure replays one move from a deterministic saved-state projection, with no retrieval. H1 rejects claims above 250 characters, above eight digits, or with detected unrequested protocol details; it allows one correction, then drops failures. Frame and the Hypothesize view use source-based answerhood. Five H1 candidates were tested on both providers and both frames; failures were retained rather than hidden by post-guard metrics.

H2 caps per-evidence unusable dispositions, requests one coverage correction, requires an argument or claim-level reason for covered claims, and installs narrower revisions only with an argument. Component findings cannot defeat whole-issue answers through inherited rivalry. Evidence directions were explicitly reviewed against the 22 Claude claims and the 17 selected H1 claims; old claim ordinals were never treated as meanings.

E2(b) ran first: replacing the original claims with Claude's claims left Sol at one supporting argument per sample. H1's simpler claims alone partially recover coverage; H2 further improves it. Within each before/after pair, graph and framing fingerprints match. Across claim sets, the reviewed directions and associated issues also change, so wording alone is not isolated.

| H1 claim set | Provider | Supporting, mean | Applicable, mean | Unargued, mean | Unusable share, mean |
|---|---|---:|---:|---:|---:|
| after H2 | openai:gpt-6.1-sol | 18.00 | 17.67 | 0.00 | 0.0% |
| after H2 | anthropic:claude-sonnet-5-5 | 10.00 | 2.00 | 0.00 | 1.8% |
| before H2 | openai:gpt-6.1-sol | 12.33 | 12.33 | 4.67 | 78.2% |
| before H2 | anthropic:claude-sonnet-5-5 | 15.67 | 7.00 | 1.00 | 58.4% |

Sonnet's applicable argument count falls despite its improved coverage. Passing E2 therefore does not establish better overall inference. Critique was tested unchanged; extra attacks were not manufactured to meet its count threshold.

Respond now validates concession CQ routing, cited checks and reasons, records the attempt before conceding, and counts only actual new discharges. Already discharged attacks are excluded from its view. For an attack with no valid named CQ, the attack's own grounds question is required; unrelated target CQs cannot substitute. Failed intermediate candidates remain in E4's report.

Appraise now verifies contiguous quotations, allows one correction and drops remaining failures. Its general skill preserves explicit decision grades and separates propositions that require different passages. The ten gold labels were fixed before model outputs; separately recorded manual adjudications credit equivalent abbreviations and facts split across items without changing the labels.

| Guarded E5 | Direction agreement on explicit matched pairs | Explicit pairs / gold pairs |
|---|---:|---:|
| openai:gpt-6.1-sol | 79.7% | 64/78 |
| anthropic:claude-sonnet-5-5 | 59.5% | 74/78 |

Direction agreement remains lower on Sonnet; missing hints, fact aggregation and differences in label coverage make these conditional rates incomplete measures of extraction quality. In particular, merging age-specific items for the combined lifetime-model gold fact can expose conflicting directions that a combined item would mark neutral. Quote membership and structured concession checks do not prove semantic entailment. These limitations remain visible in the artifacts.

## Cost and validation

| Experiment, including failed candidates | Move samples | API calls | Anthropic estimate | OpenAI estimate |
|---|---:|---:|---:|---:|
| E1 | 72 | 91 | $0.9204 | $0.8286 |
| E2 | 36 | 187 | $7.3606 | $5.3914 |
| E3 | 12 | 12 | $1.0878 | $0.3505 |
| E4 | 24 | 30 | $2.3489 | $0.9353 |
| E5 | 12 | 12 | $0.4302 | $0.2426 |
| Total | 156 | 332 | $12.1479 | $7.7483 |

Total estimate: **$19.8962**. All manifest costs and API-call counts reconcile with the shared ledger; no requests remain pending. Limits were $50 Anthropic, including a protected $20 Opus reserve, and $16 OpenAI. The dated rates and official source links are in [pricing.json](../../experiments/pricing.json).

**125 local tests pass.** Every saved sample graph hash and graph reference was checked, including the one structurally failed Respond sample. Full replies and per-sample graphs are saved locally in ignored directories; metrics manifests, reviewed maps, gold labels and selected input graphs are committed. The pre-existing `bench/results/20261110-0233.json` is untouched.

Fixes were committed separately after their experiments. The E6 metrics distinguish an empty undecided main issue from one with surviving support for a claim that actually answers it. Accepted component findings are counted separately and cannot satisfy either deterministic or model-judged main-answer shape checks.

Machine-readable campaign totals and the artifact audit are in [campaign.json](../../experiments/campaign.json). Analysis scripts under `experiments/` reproduce the reports locally without model calls.
