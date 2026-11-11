# E4: Respond concession justification

Gate for after-v3: **PASS**.

Means [min, max], three samples per provider/version, all medium effort. Both versions start from the same six-attack graph. A true discharge is distinguished from writing a CQ answer that leaves the attack active.

| Version | Provider:model | Successful samples | Concede | Newly discharged | Counters | Applicable counters | Justified concessions | Unanswered standing | Mean defense balance |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| after | openai:gpt-6.1-sol | 2/3 | 1.00 [0.00, 2.00] | 2.50 [2.00, 3.00] | 0.50 [0.00, 1.00] | 0.50 [0.00, 1.00] | 0.50 [0.00, 1.00] | 0.00 [0.00, 0.00] | 2.00 |
| after | anthropic:claude-sonnet-5-5 | 3/3 | 1.33 [1.00, 2.00] | 2.67 [2.00, 3.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.33 [0.00, 1.00] | 0.00 [0.00, 0.00] | 1.33 |
| after-v2 | openai:gpt-6.1-sol | 3/3 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 2.00 [2.00, 2.00] | 2.00 [2.00, 2.00] | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00] | 2.00 |
| after-v2 | anthropic:claude-sonnet-5-5 | 3/3 | 0.67 [0.00, 1.00] | 3.00 [3.00, 3.00] | 0.33 [0.00, 1.00] | 0.33 [0.00, 1.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 2.67 |
| after-v3 | openai:gpt-6.1-sol | 3/3 | 0.67 [0.00, 1.00] | 1.00 [1.00, 1.00] | 2.33 [2.00, 3.00] | 2.33 [2.00, 3.00] | 0.67 [0.00, 1.00] | 0.00 [0.00, 0.00] | 2.67 |
| after-v3 | anthropic:claude-sonnet-5-5 | 3/3 | 1.33 [1.00, 2.00] | 2.33 [2.00, 3.00] | 0.33 [0.00, 1.00] | 0.33 [0.00, 1.00] | 1.33 [1.00, 2.00] | 0.00 [0.00, 0.00] | 1.33 |
| before | openai:gpt-6.1-sol | 3/3 | 3.00 [2.00, 4.00] | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.33 [0.00, 1.00] | -2.00 |
| before | anthropic:claude-sonnet-5-5 | 3/3 | 5.33 [5.00, 6.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | -5.33 |

The new code validates the named CQ, checks that cited evidence IDs exist and intersect the attack context, requires an attempted discharge and a reason the listed evidence does not answer it, records the attempt before the concession, and allows one correction. It also excludes already discharged attacks from the standing view. The common scorer applies actual-discharge semantics to both versions; native attempted-answer counts are preserved in analysis.json.

These checks enforce an auditable justification structure, not the semantic truth of a claim that no evidence answers a CQ. The saved concession texts are available for review. A failed defense-balance gate is not repaired by inventing a counter or unsupported discharge.

The first candidate is retained as `after`: Sol's third sample tried twice to discharge an attack that had no valid named CQ, leaving it unresolved. The general view and retry now explain this structural limit and require a counter or justified concession. The revised candidate was rerun on both providers. Means/ranges exclude failed samples; their errors remain in analysis.json.

A review of `after-v2` found that concessions to an unnamed attack could cite arbitrary CQs from the target argument. The final candidate requires the attack scheme's `grounds` question in that case; only an explicitly valid raised CQ may select a target's question. Both providers were retested after this code correction.
