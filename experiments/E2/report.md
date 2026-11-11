# E2: claim granularity versus Argue coverage

Combination gate: **PASS**. Complete 36-sample matrix: True.

Means [min, max], three independent move samples per cell. Every effort is medium. API calls include every issue and every correction/JSON repair.

| Version | Claims | Provider:model | n | Supporting | Applicable | Supported, unargued | Unusable share | Scope proposals | Cost estimate |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| after | claude-claims | openai:gpt-6.1-sol | 3 | 21.00 [19.00, 22.00] | 18.33 [18.00, 19.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 20.00 [18.00, 24.00] | $1.2790 |
| after | claude-claims | anthropic:claude-sonnet-5-5 | 3 | 15.67 [15.00, 16.00] | 2.67 [2.00, 3.00] | 0.00 [0.00, 0.00] | 0.05 [0.01, 0.08] | 0.67 [0.00, 1.00] | $1.6095 |
| after | h1-claims | openai:gpt-6.1-sol | 3 | 18.00 [16.00, 21.00] | 17.67 [16.00, 21.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 17.33 [15.00, 20.00] | $0.8840 |
| after | h1-claims | anthropic:claude-sonnet-5-5 | 3 | 10.00 [9.00, 11.00] | 2.00 [2.00, 2.00] | 0.00 [0.00, 0.00] | 0.02 [0.01, 0.02] | 0.67 [0.00, 1.00] | $0.9053 |
| after | own-claims | openai:gpt-6.1-sol | 3 | 15.00 [12.00, 17.00] | 12.67 [11.00, 15.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.01] | 16.00 [14.00, 17.00] | $0.8112 |
| after | own-claims | anthropic:claude-sonnet-5-5 | 3 | 12.00 [11.00, 13.00] | 2.33 [1.00, 3.00] | 0.00 [0.00, 0.00] | 0.05 [0.03, 0.07] | 1.00 [0.00, 2.00] | $0.8726 |
| before | claude-claims | openai:gpt-6.1-sol | 3 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 8.00 [8.00, 8.00] | 0.99 [0.99, 0.99] | 0.00 [0.00, 0.00] | $1.0493 |
| before | claude-claims | anthropic:claude-sonnet-5-5 | 3 | 20.67 [19.00, 24.00] | 4.33 [2.00, 7.00] | 1.67 [1.00, 3.00] | 0.52 [0.50, 0.53] | 0.00 [0.00, 0.00] | $1.7882 |
| before | h1-claims | openai:gpt-6.1-sol | 3 | 12.33 [6.00, 18.00] | 12.33 [6.00, 18.00] | 4.67 [4.00, 5.00] | 0.78 [0.77, 0.80] | 0.00 [0.00, 0.00] | $0.7733 |
| before | h1-claims | anthropic:claude-sonnet-5-5 | 3 | 15.67 [14.00, 17.00] | 7.00 [4.00, 10.00] | 1.00 [1.00, 1.00] | 0.58 [0.41, 0.68] | 0.00 [0.00, 0.00] | $1.0244 |
| before | own-claims | openai:gpt-6.1-sol | 3 | 3.67 [2.00, 5.00] | 3.67 [2.00, 5.00] | 5.00 [5.00, 5.00] | 0.92 [0.92, 0.92] | 0.00 [0.00, 0.00] | $0.5945 |
| before | own-claims | anthropic:claude-sonnet-5-5 | 3 | 16.33 [14.00, 18.00] | 3.67 [2.00, 5.00] | 0.33 [0.00, 1.00] | 0.61 [0.59, 0.63] | 0.00 [0.00, 0.00] | $1.1606 |

The Claude claim swap ran first. Sol still built exactly one supporting argument in each sample; changing claims alone did not recover coverage. H2 is evaluated on the identical evidence directions and issue contexts within each before/after pair. Across claim sets, the reviewed directions and associated issue contexts also change, so this does not isolate wording alone.

H1's raw E1 gate remains failed. Its E2 claim set is the median-length final-candidate Sol aspirin sample, fixed before its Argue results. A zero coverage gap cannot be supplied by a claim-level reason: reasons satisfy the structural response contract but still count as unargued in the strict experiment metric. Scoped revisions carry actual arguments, and the manifests record original eligible claim IDs as well as final eligibility.

The unusable denominator is the fixed input set of offered evidence; H2 records ignored excess entries separately. A lower unusable share partly reflects the enforced cap, not necessarily better model judgment. Applicable arguments are reported separately from mere argument count.

All before/after graph-and-framing fingerprints match: True. Empty bookkeeping fields added to the schema are excluded from this comparison.
