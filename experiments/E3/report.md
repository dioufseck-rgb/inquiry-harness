# E3: Critique across proposers and critics

Applicable-attack gate: **FAIL / incomplete** (at least five in each sample).

All efforts are medium. Values are means [min, max]. The 12 samples include both within-provider and cross-provider critics, as requested by the 2 × 2 matrix.

| Proposer graph | Critic | n | Attacks | Applicable | With CQ | Obtainable needs | Unobtainable needs | Cost estimate |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| openai:gpt-6.1-sol | openai:gpt-6.1-sol | 3 | 2.00 [2.00, 2.00] | 2.00 [2.00, 2.00] | 1.00 [0.00, 2.00] | 3.00 [3.00, 3.00] | 1.00 [1.00, 1.00] | $0.1722 |
| openai:gpt-6.1-sol | anthropic:claude-sonnet-5-5 | 3 | 4.33 [3.00, 6.00] | 4.33 [3.00, 6.00] | 3.67 [3.00, 5.00] | 3.33 [3.00, 4.00] | 1.00 [1.00, 1.00] | $0.5442 |
| anthropic:claude-sonnet-5-5 | openai:gpt-6.1-sol | 3 | 3.33 [3.00, 4.00] | 3.33 [3.00, 4.00] | 3.33 [3.00, 4.00] | 3.67 [3.00, 4.00] | 0.00 [0.00, 0.00] | $0.1783 |
| anthropic:claude-sonnet-5-5 | anthropic:claude-sonnet-5-5 | 3 | 3.33 [3.00, 4.00] | 3.33 [3.00, 4.00] | 3.00 [3.00, 3.00] | 4.00 [3.00, 5.00] | 1.00 [1.00, 1.00] | $0.5436 |

Critique code and skill are unchanged. Groundless attacks and unverified absence attacks remain rejected by code. All needs were manually reviewed in needs-review.json: public document/search routes are obtainable, custom participant-level endpoints or author access are unobtainable. A public route is not a claim that the exact requested estimate exists. Independence notes that request no new evidence are excluded from need counts. Native heuristic tags and reviewed tags are both retained in analysis.json.

The count gate failed; it would be inappropriate to manufacture extra attacks just to reach five. E4 uses the six-attack sample under the predeclared most-attacks rule.
