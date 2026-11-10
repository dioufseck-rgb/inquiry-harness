# T8: held-in measurements after T5–T7

Proposer `openai:gpt-6.1-sol` at medium effort; critic
`openai:gpt-6-astra` at high effort. Both models were returned by the supplied
key's model list. Two rounds, eight new sources per round, six queries per
round, five hits per query, 36 appraisal windows per primary source, no token
budget. No human frame edits; one Frame sample. Sources were discovered live.

All three processes loaded the same frozen T5–T7 snapshot. Its inquiry source
tree SHA-256 is `ca76f9e818063bc9d7a26114809b7604b1741e0e51a9cfcf59bfb4f5e37068ac`.
The integrated workspace was verified byte-for-byte against that snapshot.
No tuning was performed on energy-pjm or it-genai-95. All saved ledgers and
graph references verify. The frozen snapshot passes 84 tests.

`energy-pjm` and `it-genai-95` each ran once for two rounds. Aspirin is included
as the third held-in line from T7. These measurements were not used to adjust
the implementation. The independent earlier ULEZ measurements used `b23b6b8`
and are recorded separately in `ulez-replays.md`.

| question | sources | evidence | attacks out / discharged | gold sources | gold facts | shape regex / judge / final | absence assertions |
|---|---:|---:|---|---|---|---|---:|
| health-aspirin | 16 | 160 | 0 / 0 | 4/5 | 2/3 | False / None / False | 0 |
| energy-pjm | 16 | 412 | 0 / 0 | 1/5 | 3/4 | True / None / True | 0 |
| it-genai-95 | 16 | 90 | 0 / 0 | 2/3 | 3/3 | False / True / True | 0 |

The GenAI run exercised T5's one-call semantic fallback. Its regex score was
False and the judge score True: an accepted, narrowed report-attribution claim
did not endorse the 95% estimate. The judge explicitly left retrieval of two
independent critiques unestablished. This is a verdict-shape score, not evidence
that every expected note or gold source was satisfied. The separate raw scores
and the judge's explanation are preserved in its JSON and ledger.

## health-aspirin

Run: `runs/bench/health-aspirin-tonight-openai-t7`. Raw result: `tonight-openai-health-aspirin.json`.

```text
metrics provider_proposer=openai model_proposer=gpt-6.1-sol effort_proposer=medium provider_critic=openai model_critic=gpt-6-astra effort_critic=high tokens_in=630797 tokens_out=70453 calls=60 sources=16 origins=10 duplicate_sources=2 evidence=160 orphans=0 supporting_args=2 supporting_in=2 attacks=0 attacks_out=0 attacks_discharged=0 counters_dropped=0 counters_dropped_reasons={} counters_inapplicable=0 counters_inapplicable_reasons={} accepted_claims=1 single_origin_accepts=0 absence_assertions=0 gold_sources=4/5 gold_facts=2/3 shape_match=False stop_reason='rounds exhausted' main=C1:undecided,C2:undecided,C3:undecided
```

## energy-pjm

Run: `runs/bench/energy-pjm-tonight-openai-t7`. Raw result: `tonight-openai-energy-pjm.json`.

```text
metrics provider_proposer=openai model_proposer=gpt-6.1-sol effort_proposer=medium provider_critic=openai model_critic=gpt-6-astra effort_critic=high tokens_in=1625818 tokens_out=150850 calls=163 sources=16 origins=14 duplicate_sources=1 evidence=412 orphans=0 supporting_args=2 supporting_in=0 attacks=2 attacks_out=0 attacks_discharged=0 counters_dropped=0 counters_dropped_reasons={} counters_inapplicable=0 counters_inapplicable_reasons={} accepted_claims=0 single_origin_accepts=0 absence_assertions=0 gold_sources=1/5 gold_facts=3/4 shape_match=True stop_reason='rounds exhausted' main=C1:undecided,C2:undecided,C3:undecided,C4:undecided,C5:undecided
```

## it-genai-95

Run: `runs/bench/it-genai-95-tonight-openai-t7`. Raw result: `tonight-openai-it-genai-95.json`.

```text
metrics provider_proposer=openai model_proposer=gpt-6.1-sol effort_proposer=medium provider_critic=openai model_critic=gpt-6-astra effort_critic=high tokens_in=390955 tokens_out=46970 calls=53 sources=16 origins=9 duplicate_sources=21 evidence=90 orphans=0 supporting_args=7 supporting_in=5 attacks=2 attacks_out=0 attacks_discharged=0 counters_dropped=0 counters_dropped_reasons={} counters_inapplicable=0 counters_inapplicable_reasons={} accepted_claims=4 single_origin_accepts=2 absence_assertions=0 gold_sources=2/3 gold_facts=3/3 shape_match=True stop_reason='rounds exhausted' main=C1:out,C2:out,C3:undecided,C20:in
```

