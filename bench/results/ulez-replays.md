# ULEZ on a fixed evidence packet: three OpenAI replays

Harness: `b23b6b8` (T1–T3 plus the live JSON-input compatibility fix).
All three processes loaded that version before optional T5–T7 work began in an
isolated copy. Evidence packet: the 12 surviving source texts in
`runs/ulez-live-4`, including the npj paper at two hosts. Retrieval returned that
same packet for every query; appraisal, claims, and arguments were sampled anew.

Model configuration, resolved from the supplied key's `client.models.list()`:
proposer `openai:gpt-6.1-sol`, effort `medium`; critic `openai:gpt-6-astra`, effort
`high`. These are different models on one provider, a separate configuration
from the earlier Anthropic runs. Token budget was unlimited (`0`). No key is
stored in these artifacts.

Each run used two rounds, `--max-sources 20 --queries 6 --hits 20
--read-parts 36 --evidence-from runs/ulez-live-4`, with IDs
`ulez-openai-replay-1`, `ulez-openai-replay-2`, and `ulez-openai-replay-3`.
The raised source ceiling allowed the whole packet to be considered. Sources
that supplied no relevant evidence were dropped by the existing gather policy.
Each ID had one initial attempt fail before Frame on the JSON-mode input
requirement, then one successful restart after the compatibility fix.

| run | harness | accepted on main issue | other accepted | what Revise did | verdict shape |
|---|---|---|---|---|---|
| replay 1 | b23b6b8 | none | C5: road-level inclusion in the expansion | narrowed C8 to C18, which remained OUT; requested geographic inclusion rules | undecided; no IN pro on main |
| replay 2 | b23b6b8 | none | C16: detected compliance series; C17: concurrent fleet-policy dates | narrowed C10/C11, withdrew A1/A2, retained the scoped administrative findings | undecided; no IN pro on main |
| replay 3 | b23b6b8 | none | C20: expansion date, coverage, charge and standards | narrowed C4, withdrew A2, retained C20 | undecided; no IN pro on main |

## Checks against the F1–F4 predictions

| check / metric | replay 1 | replay 2 | replay 3 |
|---|---:|---:|---:|
| sources | 8 | 8 | 6 |
| evidence | 187 | 148 | 166 |
| duplicate_sources | 1 | 1 | 0 |
| attacks | 1 | 2 | 0 |
| attacks_out | 0 | 0 | 0 |
| attacks_discharged | 0 | 0 | 0 |
| supporting_in (all issues) | 1 | 2 | 1 |
| single_origin_accepts | 0 | 1 | 0 |
| absence_assertions | 0 | 0 | 0 |
| false corroboration | 0 | 0 | 0 |
| IN pro arguments on Q1 | 0 | 0 | 0 |
| C1 or C2 undecided | yes | yes | yes |
| both report-finding claims IN | not proposed | not proposed | not proposed |
| npj duplicate host skipped | yes | yes | yes |
| ledger and graph references valid | yes | yes | yes |
| expected shape matched | yes | yes | yes |

False corroboration means an accepted claim marked corroborated without any
pair of IN pro arguments with nonempty, disjoint origin sets. None was found.
The two duplicate-source flags join DEFRA documents by a shared publisher
origin (`S6,S7` in replay 1; `S7,S8` in replay 2). In every run, the Nature host
of the npj paper was skipped as the same document as its earlier host. That
specific deduplication prediction held, while the overall zero-duplicate target
failed twice.

F2's discharge and surviving-main-support predictions did not hold. The model
proposed very few arguments and attacks: main claims required an exact annual
period and fixed monitoring population, while much of the packet described
endpoint estimates or different periods. No counter was rejected or created.
All three Frames were causal; the kept sub-issue counts were 3, 3, and 4.

F3 was not exercised: none of these hypothesis sets proposed the pair of
descriptive claims about what the official and independent evaluations report.
Their absence from acceptance cannot test whether the rivalry guard would let
both stand. Checks requiring proposed claims or attacks depend on sampling;
origin and reference checks are deterministic on the resulting graph.

The existing literal gold matcher reports sources 1/4 and facts 4/5 in each run.
The npj paper was read via its other host, whose title and URL omit the Nature
article suffix used by the gold matcher. These scores are preserved as measured;
the source score is not a complete account of the packet's contents.

## Metrics lines

`ulez-openai-replay-1`

```text
metrics provider_proposer=openai model_proposer=gpt-6.1-sol effort_proposer=medium provider_critic=openai model_critic=gpt-6-astra effort_critic=high tokens_in=1387414 tokens_out=95481 calls=179 sources=8 origins=6 duplicate_sources=1 evidence=187 orphans=0 supporting_args=2 supporting_in=1 attacks=1 attacks_out=0 attacks_discharged=0 counters_dropped=0 counters_dropped_reasons={} counters_inapplicable=0 counters_inapplicable_reasons={} accepted_claims=1 single_origin_accepts=0 absence_assertions=0 gold_sources=1/4 gold_facts=4/5 shape_match=True stop_reason='rounds exhausted' main=C1:undecided,C2:undecided,C3:undecided,C4:undecided
```

`ulez-openai-replay-2`

```text
metrics provider_proposer=openai model_proposer=gpt-6.1-sol effort_proposer=medium provider_critic=openai model_critic=gpt-6-astra effort_critic=high tokens_in=1139745 tokens_out=87569 calls=144 sources=8 origins=6 duplicate_sources=1 evidence=148 orphans=0 supporting_args=4 supporting_in=2 attacks=2 attacks_out=0 attacks_discharged=0 counters_dropped=0 counters_dropped_reasons={} counters_inapplicable=0 counters_inapplicable_reasons={} accepted_claims=2 single_origin_accepts=1 absence_assertions=0 gold_sources=1/4 gold_facts=4/5 shape_match=True stop_reason='rounds exhausted' main=C1:undecided,C2:undecided,C3:undecided,C4:undecided
```

`ulez-openai-replay-3`

```text
metrics provider_proposer=openai model_proposer=gpt-6.1-sol effort_proposer=medium provider_critic=openai model_critic=gpt-6-astra effort_critic=high tokens_in=1459845 tokens_out=92862 calls=205 sources=6 origins=5 duplicate_sources=0 evidence=166 orphans=0 supporting_args=3 supporting_in=1 attacks=0 attacks_out=0 attacks_discharged=0 counters_dropped=0 counters_dropped_reasons={} counters_inapplicable=0 counters_inapplicable_reasons={} accepted_claims=1 single_origin_accepts=0 absence_assertions=0 gold_sources=1/4 gold_facts=4/5 shape_match=True stop_reason='rounds exhausted' main=C1:undecided,C2:undecided,C3:undecided
```

