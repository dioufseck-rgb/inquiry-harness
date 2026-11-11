# Move-level experiments

`python -m inquiry.replay_move` runs a single move without search, fetching, or
the rest of the harness. The default is three independent samples. Each starts
from a deep copy of the same deterministic pre-move projection. Final claim
revisions remain where the requested projection keeps claims; these are
projections of a final graph, not recovered historical snapshots.

```powershell
python -m inquiry.replay_move --run bench/run-artifacts/ulez-live-4 --move argue --provider openai:gpt-6.1-sol --effort medium --out experiments/example
```

Each output has provider, model, effort, input/output tokens, estimated USD cost,
the move result, the evaluated graph and its hash, and any error. `moves.json`
records every sample and numeric means and ranges. Full prompts, replies, and
graphs are local under `sample-*/`; repeated input snapshots are also ignored
by Git. The small metrics manifests and reviewed mapping files can be committed.

For claim replacement, issues match by normalized text, not ID ordinal. Missing
issues are imported with their relationships and listed in preparation metadata.
Only exactly matching claim texts inherit old stance hints. Changed claims need
a reviewed evidence mapping before any API request is allowed:

```powershell
python -m inquiry.replay_move --run bench/run-artifacts/health-aspirin-tonight-openai-t7 --move argue --claims-from bench/run-artifacts/health-aspirin-20261110-0209 --prepare-only --out experiments/E2/claude-claims/input
```

The template names every retained evidence item and new claim. Fill its
`directions`, mark it reviewed, identify the reviewer, and supply it through
`--evidence-map`. Its claim fingerprint must match and every evidence ID must
be explicitly accounted for. Clearing an item to `{}` means reviewed but not
assigned. A mapping must not reuse old claim ordinals as if their meanings were
unchanged. Appraise may instead replace claims and re-extract that source's
directions from its local text.

Appraise requires `--source S16` (or the appropriate source ID). Text is read
locally beside the input or from the workspace's original run; `--source-root`
can select another local source directory. It never fetches the URL. The whole
selected source is passed to one appraise call, rather than replaying gather's
window loop. JSON repair can add an API call; all such calls are counted.

Costs use the verified, dated rate card in [pricing.json](pricing.json), including
cache reads/writes. These are estimates from API usage, not invoice totals. The
shared budget is $50 Anthropic, with $20 protected for the reserved Opus run,
and $16 OpenAI. A conservative request maximum is reserved before each call.
Unknown charges retain that reservation. SDK automatic retries are disabled;
JSON repair remains visible and budgeted. `--use-reserved` releases the Opus
reserve only after the experiment gates permit that run. Budget totals persist
across invocations in the ignored `experiments/budget.json`.

Need-obtainability tags are explicit heuristic labels for review. Quote matching
folds whitespace and case. Claim coverage reports its eligible claim IDs and
evidence denominator, so a zero cannot hide an empty eligibility set.

The campaign must pass E1 and E2 on both providers before any full-harness run.
Held-out questions are not part of this campaign.
