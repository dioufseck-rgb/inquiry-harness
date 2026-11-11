# E2(b): replace claims before changing Argue

Three independent move samples per provider, all at medium effort, using the
unchanged Argue code frozen at `026cb58`. These six samples ran before the other
E2 claim sets. Evidence and sources are the same 160-item OpenAI aspirin packet.
Each sample makes seven issue-level API requests; all are included in its cost.

| Provider:model | Supporting arguments | Applicable arguments | Supported but unargued | Unusable share | Cost estimate |
|---|---:|---:|---:|---:|---:|
| anthropic:claude-sonnet-5-5 | 20.67 [19, 24] | 4.33 [2, 7] | 1.67 [1, 3] | 51.88% [50.38%, 53.38%] | $1.7882 |
| openai:gpt-6.1-sol | 1.00 [1, 1] | 1.00 [1, 1] | 8.00 [8, 8] | 99.25% [99.25%, 99.25%] | $1.0493 |

The claim swap alone did not restore Sol's argument coverage. Sonnet built many
arguments but most remained inapplicable. This implicates Argue behavior as well
as the original claim granularity; the remaining E2 cells test the combination.

The replacement main issue matches by text. Six source sub-issues have different
text and are imported with their relationships, as recorded in preparation
metadata. Existing target sub-issues remain. This is a claim-and-associated-issue
intervention, so differences cannot be attributed to claim wording alone.

Every evidence direction was explicitly reviewed in `evidence-map.json` against
the new claim meanings. No claim ordinals were reused as semantic mappings.
Direction means partial directional relevance, not entailment: population,
follow-up, endpoint and uncertainty limitations remain for critical questions.
Methodological or transport information is neutral, and a nonsignificant result
is not automatically evidence for a true-zero null. The map contains all 160
evidence IDs, its claim fingerprint, and rationale for the reviewed bindings.
