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

## E3.1: audit answered assumptions (N2)

Six calls: one critique per saved Sol H1 graph for each critic (three graph samples per critic), all medium effort. The critics see each actual claim and the answered/defaulted assumption text and evidence IDs. No retrieval or new Argue move is run.

N1's separate **agent-provisional** review protects ten specific Sol CQ answers at their narrower stated scope. It provides zero against-Sol same-claim references. The requested ≥70% overlap is therefore **not estimable**; this is not labelled a pass. Applicable-attack means also fail to rise above the prior E3 means. No protected CQ was reopened.

| Critic | n | Prior E3 applicable attacks | E3.1 applicable attacks | Reopened CQs | Sol support applicable before → after |
|---|---:|---:|---:|---:|---:|
| openai | 3 | 2.00 | 1.00 | 1.00 | 17.67 → 16.67 |
| anthropic | 3 | 4.33 | 3.00 | 0.67 | 17.67 → 17.00 |

Both critics identify a population/treatment-contrast concern in the remaining unscoped C5 argument about adding extracranial bleeding. The mechanism works, but the result does not support the prediction that most of Sol's applicable scoped findings should fall to Sonnet's count. N3 makes the original/scoped split explicit before E6 is read.

A challenge snapshots the CQ revision: its old answer cannot discharge itself. Only a newer satisfied, evidence-backed Respond answer discharges answer_inadequate. Grounded labels determine active reopenings before target applicability, with reopenings included in the bounded fixed point. Counterattacks can restore the target without changing the original CQ answer. Exact quoted proposer contradictions can ground an internal attack without fabricating a source item.

E3.1 is recorded with its unmet count/overlap criterion. N4 requires N2 committed with E3.1 recorded, rather than requiring a fabricated overlap denominator. The user's autonomous-continuation instruction supplies provisional review authority; the human-review blanks remain untouched.
