# v1 development validation

14 November 2026 (UTC) · version `1.0.0a1`

Historical validation of a1, retained with its original metrics and terminology.
For the a5 epistemic boundary and service interface, see [the current service
contract](V1_SERVICE.md) and [software validation summary](../experiments/v1/epistemic_boundary_validation_20261114.json).

The runnable alpha and controlled experiment framework are implemented. This is a development release for examining failures and comparing workflows. It has not established an advantage in reasoning quality, and its outputs are not a basis for unattended case decisions.

The tested implementation is commit `ac4700d7bdf1ed9b06bb21b44ad23c29b3cbd312`, tree `c864a678671e45bf1e8a90ea034016bcb1dafd04`. The local test commit `9d1ceca` has exactly the same tree; the connector-created commit differs only in commit metadata. The later validation commit adds this account and the machine-readable [validation summary](../experiments/v1/validation_summary.json).

## Software and packaging

The complete suite passes: **342 tests**, comprising 168 legacy tests and 174 new v1 tests. The local runtime is Python 3.12. Tests cover packet/oracle separation, all declared mutations, exposure-aware quotations, source revisions, origin independence, unsupported support cycles, conditionality, challenge and reply, record preservation, budget admission, usage accounting, failure retention, scoring and CLI behavior.

The wheel builds with its evidence packet included. The installed-package path was checked outside the repository import path. A CI workflow is included for Python 3.11 and 3.12, running the tests, packet validation, a demo and replay, and the complete scripted matrix. Local success does not by itself establish the result of hosted CI.

## Scripted matrix

All **378 scripted runs** passed their exact structural audits and authored categorical smoke assertions, with no execution failures. The matrix is six questions, baseline plus six independent mutations, three arms, and three evidence modes. It exercises 1,710 scripted worker invocations and 954 evidence-tool calls. All 378 human outcome reviews remain pending.

These are 378 settings from **one synthetic development family**. The deterministic demo worker is deliberately adapted to that family and is labelled a test instrument in the record. The result establishes integration and regression behavior, not model competence or 378 independent successes.

## Live development and frozen pilot

An 18-run development sequence made 61 provider requests using `gpt-5.4-mini-2026-03-17`. Early runs used omitted reasoning effort; later runs used `low`. These were debugging probes across changing code and instructions. They are not a matched statistical comparison, and the earlier ordinary/repertoire successes do not establish a relative advantage.

The probes revealed missing tool-argument documentation, incomplete pattern/form contracts, repeated prose revisions without graph changes, and a revision rule that unnecessarily prevented refinement of an unchallenged assessment. Repairs included exact public contracts, an empty type-derived graph template, bounded record repair, and explicit separation of an unfinished record from an unresolved evidence question. No evidence or accepted condition is supplied by the template.

The final three-run pilot used the frozen code above, `low` effort, the same fictional intake question, and no critic. Every final run completed without execution exceptions; all three exact structural audits passed and all three kernel evaluations replayed exactly. **Only one of the three categorical smoke assertions passed.**

| Frozen pilot setting | Kernel result | Categorical result | What the record shows |
|---|---|---|---|
| Baseline, documents opened by the worker | Established | Pass | The worker opened the policy and application, supported advancing intake, and preserved the separate final-eligibility stage. |
| Baseline, all evidence supplied initially | Not established | Fail | The model built circular support. The kernel rejected it, but the worker did not repair the argument despite the packet being sufficient. The next-action category also missed the authored expectation. |
| Missing impact details, supplied evidence | Established recommendation to request details | Fail | The prose requested the missing event date and financial-disruption description. The structured action remained `answer`, and its condition IDs pointed to argument checks rather than the requested information. |

This last distinction matters. Correct-looking prose does not ensure a correct machine-readable handoff. Conversely, a categorical mismatch alone does not establish that every part of the substantive response is wrong. The scorer retains these separate judgments and leaves human warrant and response review pending.

The final three runs used 10 provider calls, 70,906 input tokens and 13,064 output tokens. Across all 18 development runs, the recorded totals were 360,053 input tokens, including 112,384 cached tokens, and 50,386 output tokens. Applying the published [GPT-5.4 mini token prices](https://developers.openai.com/api/docs/models/gpt-5.4-mini) gives approximately **US$0.42** for the development sequence. This is a calculation from recorded usage and posted rates, not a verified provider invoice. Raw run accounting leaves unpriced dollar costs unknown.

## Remaining work before reliance or research claims

The next engineering targets are the live failures above: reliable recovery from unsupported circular arguments, and an action/condition contract that expresses the information request consistently. These should be exercised across frozen variants without adapting the expected answers to the outputs. A live critic and a second model family remain untested in this build; their adapters and controller paths have mocked tests only.

The next evaluation stage needs independently authored families, human-adjudicated warrant and response criteria, repeated runs, matched resource envelopes, and held-out cases. The current fixture should remain development material. The argument kernel still relies on attributed model or human judgments about source interpretation, applicability and inferential warrant; exact quotations and formal standing do not independently validate those judgments.

The implementation covers the first factual, rule-application and explicitly supported argument patterns. General estimation and forecasting, validated model instruments, practical optimization, live-web acquisition, general scope entailment, durable pause/resume, monetary spend caps, and the full seven-competence catalogue remain outside this alpha.
