# T7: aspirin literature recall validation

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

Run: `runs/bench/health-aspirin-tonight-openai-t7`. Full metrics are in
`tonight-openai-health-aspirin.json`; the report, sources, inquiry state and
ledger remain in the run directory.

The recall pass ran 16 issue queries before the first
Plan and created 32 DOI-deduplicated candidates.
Across both rounds there were 21
literature queries and 46 distinct candidate records.
Plan selected candidates by ID; they were read before its web queries.
Named requests were sent to literature first and their queries were persisted
for subsequent web search. Candidate metadata alone was not added as evidence.

| metric | result |
|---|---:|
| sources | 16 |
| evidence | 160 |
| gold_sources_found | 4/5 |
| gold_facts_found | 2/3 |
| attacks_out | 0 |
| attacks_discharged | 0 |
| absence_assertions | 0 |
| shape_match_regex | False |
| shape_match_judge | None |
| recommendation placements by rule | 0 |

The requested source-coverage threshold of 4/5 was
**met**. The unchanged literal
gold matcher reports these labels missing: JAMA.
The first-round literal score was only 1/5 even though the ASPREE
cardiovascular paper was already read as “Effect of Aspirin on
Cardiovascular Events and Bleeding in the Healthy Elderly” through PMC; neither
that title nor its PMC URL contains the gold label “ASPREE”. The final pass
also read a separately titled ASPREE record that matches the literal label.
The score has not been widened after the run. The complete source list below
makes the retrieval and matching behavior reviewable.

The initial broad-query API smoke test surfaced the ASPREE cardiovascular
paper, ASCEND, ARRIVE, the JAMA meta-analysis and the USPSTF statement across
three citation-ranked query categories. The end-to-end run used Frame's own
issue topics and Plan's reading choices, so that smoke test does not establish
full-run coverage. Over-specific topics and ambiguous study acronyms remain
recall risks: the named ASCEND query also returned an unrelated pirfenidone
trial among its candidates. Candidate selection and appraisal remain necessary.

No recommendation was moved by the T6 rule in this run. Its conditional
population/outcome placement test passes; the live hypothesis set did not
supply a qualifying recommendation proposal. The automatic run therefore does
not demonstrate that the recommendation placement problem is resolved for all
Frames. `--review-frame` is available for human correction of that seam.

## Retrieved sources

- S1: [Effect of Aspirin on Cardiovascular Events and Bleeding in the Healthy Elderly.](https://pmc.ncbi.nlm.nih.gov/articles/PMC6289056/)
- S2: [Aspirin for primary prevention of cardiovascular disease: a meta-analysis with a particular focus on subgroups.](https://pmc.ncbi.nlm.nih.gov/articles/PMC6827248/)
- S3: [Aspirin for primary prevention of stroke in individuals without cardiovascular disease-A meta-analysis.](https://pmc.ncbi.nlm.nih.gov/articles/PMC7003154/)
- S4: [Aspirin, cardiovascular events, and major bleeding in older ...](https://pmc.ncbi.nlm.nih.gov/articles/PMC12596486/)
- S5: [Effects of Aspirin for Primary Prevention in Persons with ...](https://www.nejm.org/doi/full/10.1056/NEJMoa1804988)
- S6: [Aspirin Not Needed for Primary Prevention in Diabetes](https://www.natap.org/2018/HIV/091918_02.htm)
- S7: [ASCEND: A Study of Cardiovascular Events iN Diabetes](https://pmc.ncbi.nlm.nih.gov/articles/PMC5971211/)
- S8: [A Study of Cardiovascular Events in Diabetes](https://www.acc.org/latest-in-cardiology/clinical-trials/2018/08/25/02/16/ascend-aspirin)
- S9: [Low-Dose Aspirin and the Risk of Stroke and Intracerebral Bleeding in Healthy Older People: Secondary Analysis of a Randomized Clinical Trial.](https://pmc.ncbi.nlm.nih.gov/articles/PMC10372701/)
- S10: [Aspirin in Reducing Events in the Elderly - ASPREE](https://www.acc.org/latest-in-cardiology/clinical-trials/2018/09/16/21/55/aspree)
- S11: [Low-Dose Aspirin Increases Risk of Bleeding but Does Not ...](https://www.patientcareonline.com/view/low-dose-aspirin-increases-risk-of-bleeding-but-doe-not-reduce-risk-of-a-first-stroke-in-older-adults)
- S12: [Risk of Brain Bleeds with Aspirin May Outweigh Stroke ...](https://www.hcplive.com/view/risk-of-brain-bleeds-with-aspirin-may-outweigh-stroke-reduction-benefit-for-older-adults)
- S13: [Low-Dose Aspirin for the Primary Prevention of Cardiovascular Disease in Diabetic Individuals: A Meta-Analysis of Randomized Control Trials and Trial Sequential Analysis.](https://pmc.ncbi.nlm.nih.gov/articles/PMC6572181/)
- S14: [Use of aspirin to reduce risk of initial vascular events in ...](https://pubmed.ncbi.nlm.nih.gov/30158069/)
- S15: [Aspirin to Reduce Risk of Initial Vascular Events - ARRIVE](https://www.acc.org/latest-in-cardiology/clinical-trials/2018/08/25/01/46/arrive)
- S16: [Aspirin Use to Prevent Cardiovascular Disease ...](https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/aspirin-to-prevent-cardiovascular-disease-preventive-medication)

## Metrics line

```text
metrics provider_proposer=openai model_proposer=gpt-6.1-sol effort_proposer=medium provider_critic=openai model_critic=gpt-6-astra effort_critic=high tokens_in=630797 tokens_out=70453 calls=60 sources=16 origins=10 duplicate_sources=2 evidence=160 orphans=0 supporting_args=2 supporting_in=2 attacks=0 attacks_out=0 attacks_discharged=0 counters_dropped=0 counters_dropped_reasons={} counters_inapplicable=0 counters_inapplicable_reasons={} accepted_claims=1 single_origin_accepts=0 absence_assertions=0 gold_sources=4/5 gold_facts=2/3 shape_match=False stop_reason='rounds exhausted' main=C1:undecided,C2:undecided,C3:undecided
```
