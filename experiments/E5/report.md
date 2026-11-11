# E5: local USPSTF appraisal

Gate: **PASS**. Gold was hand-labelled before outputs, with H1's fixed 17 claims.

| Version | Provider:model (medium) | Sample | Evidence | Verified quotes | Grade D with recommendation | Gold facts / 10 | Direction agreement (observed pairs) | Explicit pairs / total | Cost estimate |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|
| guarded | openai:gpt-6.1-sol | 1 | 19 | 100.0% | True | 10 | 81.8% | 22/26 | $0.0689 |
| guarded | openai:gpt-6.1-sol | 2 | 20 | 100.0% | True | 10 | 76.2% | 21/26 | $0.0411 |
| guarded | openai:gpt-6.1-sol | 3 | 20 | 100.0% | True | 10 | 81.0% | 21/26 | $0.0417 |
| guarded | anthropic:claude-sonnet-5-5 | 1 | 13 | 100.0% | True | 10 | 58.3% | 24/26 | $0.0816 |
| guarded | anthropic:claude-sonnet-5-5 | 2 | 14 | 100.0% | True | 10 | 60.0% | 25/26 | $0.0815 |
| guarded | anthropic:claude-sonnet-5-5 | 3 | 12 | 100.0% | True | 10 | 60.0% | 25/26 | $0.0750 |
| original | openai:gpt-6.1-sol | 1 | 7 | 100.0% | False | 9 | 72.7% | 22/26 | $0.0517 |
| original | openai:gpt-6.1-sol | 2 | 6 | 100.0% | False | 9 | 72.7% | 22/26 | $0.0199 |
| original | openai:gpt-6.1-sol | 3 | 6 | 100.0% | False | 9 | 69.6% | 23/26 | $0.0193 |
| original | anthropic:claude-sonnet-5-5 | 1 | 6 | 66.7% | True | 10 | 62.5% | 24/26 | $0.0650 |
| original | anthropic:claude-sonnet-5-5 | 2 | 6 | 50.0% | True | 10 | 64.0% | 25/26 | $0.0625 |
| original | anthropic:claude-sonnet-5-5 | 3 | 6 | 66.7% | True | 9 | 54.5% | 22/26 | $0.0646 |

Only S16 is read, from local text; no retrieval, gold injection into prompts, or held-out question is involved. Gold labels were frozen before outputs. Separate manual adjudications credit equivalent abbreviations/pronouns and a fact split across items; missing Grade D or numeric bounds are not inferred. The detailed matches and missing direction pairs are saved for review. Agreement is conditional on explicitly labelled matched pairs; pair coverage is shown alongside it.

Quote verification uses literal source membership after whitespace/case folding, including any clipping in the stored quote. It does not assume that plausible paraphrases are verified quotations.

For a gold fact split across extracted items, direction comparison uses the union of their explicit hints. The combined lifetime-model gold fact spans two age bands; age-specific hints may differ and therefore disagree with its combined neutral label. This aggregation limitation is visible in the detailed directions, rather than resolved by changing the frozen labels.
