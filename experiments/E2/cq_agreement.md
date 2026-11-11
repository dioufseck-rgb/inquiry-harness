# N1: critical-question outcome agreement

**Human review deferred by the user's instruction to continue while asleep.** The separate cq_adjudication_provisional.json is agent-authored; the human review file stays blank. All six saved graphs are present and verified; no model calls or retrieval were needed.

There are **0 comparable argument pairs and 0 matched CQ pairs** under the requested exact/loose keys. Sol chiefly argues scoped revisions; Sonnet chiefly argues the original claims. Provider outcome distributions therefore do not measure agreement on the same inference. A zero denominator is reported as n/a, never as zero disagreement.

All nine cross-provider sample pairings are searched, so the result does not depend on pairing samples by index. The same six independent graphs are reused; these are not nine independent observations. Exact matches use claim ID, scheme and sorted premise set. Loose matches retain claim ID/scheme and maximize premise overlap one-to-one within each sample pairing. Claim meanings and answerhood roles must also match. Every supporting argument/CQ, including any withdrawn support, is exported in cq_records.jsonl; active support is used for metrics and tables.

| Sol sample | Sonnet sample | Sol arguments | Sonnet arguments | Exact pairs | Loose pairs | Rejected ordinal collisions |
|---|---|---:|---:|---:|---:|---:|
| 1 | 1 | 21 | 10 | 0 | 0 | 0 |
| 1 | 2 | 21 | 11 | 0 | 0 | 0 |
| 1 | 3 | 21 | 9 | 0 | 0 | 0 |
| 2 | 1 | 17 | 10 | 0 | 0 | 0 |
| 2 | 2 | 17 | 11 | 0 | 0 | 0 |
| 2 | 3 | 17 | 9 | 0 | 0 | 0 |
| 3 | 1 | 16 | 10 | 0 | 0 | 0 |
| 3 | 2 | 16 | 11 | 0 | 0 | 0 |
| 3 | 3 | 16 | 9 | 0 | 0 | 0 |

## Assumption outcomes

| Outcome | OpenAI gpt-6.1-sol (medium) | Anthropic claude-sonnet-5-5 (medium) |
|---|---:|---:|
| satisfied | 191 | 74 |
| unsatisfied | 2 | 13 |
| defaulted | 1 | 0 |
| open | 0 | 18 |

| Scheme | CQ ID | Matched pairs | Disagreements | Disagreement rate |
|---|---|---:|---:|---:|
| consequences | follows | 0 | 0 | n/a |
| consequences | valued | 0 | 0 | n/a |
| document_record | accuracy | 0 | 0 | n/a |
| document_record | authentic | 0 | 0 | n/a |
| document_record | reading | 0 | 0 | n/a |
| expert_opinion | assertion | 0 | 0 | n/a |
| expert_opinion | basis | 0 | 0 | n/a |
| expert_opinion | expertise | 0 | 0 | n/a |
| expert_opinion | field | 0 | 0 | n/a |
| position_to_know | access | 0 | 0 | n/a |
| position_to_know | report | 0 | 0 | n/a |
| statistical_generalization | measurement | 0 | 0 | n/a |
| statistical_generalization | representative | 0 | 0 | n/a |
| statistical_generalization | size | 0 | 0 | n/a |
| study_result | design | 0 | 0 | n/a |
| study_result | directness | 0 | 0 | n/a |
| study_result | reported | 0 | 0 | n/a |
| study_result | uncertainty | 0 | 0 | n/a |

## Exception outcomes

| Outcome | OpenAI gpt-6.1-sol (medium) | Anthropic claude-sonnet-5-5 (medium) |
|---|---:|---:|
| satisfied | 0 | 0 |
| unsatisfied | 0 | 0 |
| defaulted | 0 | 0 |
| open | 141 | 76 |

| Scheme | CQ ID | Matched pairs | Disagreements | Disagreement rate |
|---|---|---:|---:|---:|
| consequences | alternatives | 0 | 0 | n/a |
| consequences | other_consequences | 0 | 0 | n/a |
| document_record | currency | 0 | 0 | n/a |
| document_record | definitions | 0 | 0 | n/a |
| expert_opinion | bias | 0 | 0 | n/a |
| expert_opinion | consensus | 0 | 0 | n/a |
| position_to_know | objectivity | 0 | 0 | n/a |
| position_to_know | veracity | 0 | 0 | n/a |
| statistical_generalization | reference_class | 0 | 0 | n/a |
| statistical_generalization | stability | 0 | 0 | n/a |
| study_result | bias | 0 | 0 | n/a |
| study_result | consistency | 0 | 0 | n/a |
| study_result | precision | 0 | 0 | n/a |

The four requested buckets classify answered-but-unresolved as open: Sol 0, Sonnet 18. Their raw answered/unresolved values remain in the records and cq_outcome_details. Exceptions left open are not failed assumptions and are tabulated separately. Rates are broken down by scheme as well as CQ ID to avoid conflating identically named questions.

## Matched disagreements and human review

No matched disagreements are available. The complete paired outcome contingency matrices contain no observations and are saved in cq_agreement.json. The ten cases in cq_adjudication.json are explicitly labelled lineage-linked diagnostic contrasts, not matched disagreements. They share an original claim ancestor and at least one premise, use the same scheme/CQ, and record different outcomes for different conclusions. Both conclusions, answer texts, checked evidence and source quotations are included.

There are no main-issue study_result lineage pairs: Sonnet's main-issue arguments use document_record. The catalogue's directness question combines population and outcome checks. The selection therefore includes available main-issue record-reading contrasts and component study_result/directness contrasts.

| Case | Sample | Sol argument/claim | Sonnet argument/claim | Original ancestor | Scheme / CQ | Sol → Sonnet |
|---|---:|---|---|---|---|---|
| 1 (956070130515c711) | 2 | A1 / C18 | A1 / C4 | C4 | document_record / reading | satisfied → open |
| 2 (5765d1e64a883c40) | 2 | A2 / C19 | A1 / C4 | C4 | document_record / reading | satisfied → open |
| 3 (9874abd13352cdb2) | 1 | A13 / C29 | A6 / C9 | C9 | study_result / directness | satisfied → unsatisfied |
| 4 (6f8a2b0660c2e280) | 1 | A14 / C30 | A6 / C9 | C9 | study_result / directness | satisfied → unsatisfied |
| 5 (35c565499cc41b04) | 2 | A11 / C27 | A5 / C9 | C9 | study_result / directness | satisfied → unsatisfied |
| 6 (5ecee7589224f580) | 2 | A12 / C28 | A5 / C9 | C9 | study_result / directness | satisfied → unsatisfied |
| 7 (73d5a26759fed851) | 3 | A11 / C27 | A6 / C10 | C10 | study_result / directness | satisfied → unsatisfied |
| 8 (ef41a47325dcc1f1) | 1 | A17 / C33 | A9 / C13 | C13 | study_result / directness | satisfied → unsatisfied |
| 9 (e657e746a031dbcc) | 1 | A18 / C34 | A10 / C14 | C14 | study_result / directness | satisfied → unsatisfied |
| 10 (4c09e1cbfa13ce3b) | 1 | A19 / C35 | A10 / C14 | C14 | study_result / directness | satisfied → unsatisfied |

Fill each case's blank adjudication and note. In particular, a satisfied answer for a source-scoped result and an unsatisfied answer for the original all-adults claim can both be appropriate. These distributions alone cannot establish Sol self-certification or Sonnet over-strictness. Human review must evaluate Sol's actual narrower conclusion, not silently substitute the original claim.

## Move metrics

Argue now emits inapplicable_reasons (open:<cq_id>, unsatisfied:<cq_id>, premise_claim_not_accepted) and cq_outcomes per provider/sample, with assumption/exception splits and answered-unresolved details. Histograms count reason occurrences, so one inapplicable argument can contribute more than one reason. Saved E2 metrics are extended from local graphs; existing totals, costs, prompts and graph files remain unchanged. Inference and applicability rules are unchanged.

N1 spend: **$0**, with the Opus reserve untouched. At the N1 checkpoint, N2–N6 have not started. The original brief says: “Stop and ask him to fill it before N2.” The subsequent instruction, “i will be asleep. i need tou to move forward,” authorizes provisional agent adjudication and continuation; it is not recorded as Mamadou's hand adjudication.
