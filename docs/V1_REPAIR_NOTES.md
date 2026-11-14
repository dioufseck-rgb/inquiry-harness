# V1 operational corrections and controlled reruns

14 November 2026 · `1.0.0a4`

Historical account of the a4 contract. Version a5 moves application products
outside the core and replaces business-task completion with epistemic inquiry
completion. See [the current service contract](V1_SERVICE.md); the corrections
and experiments described below retain their original interpretation.

The first eight-case live batch is preserved at commit `7712518`, including its original scores. These changes address failures observed in that batch. They do not supply new inference patterns for the whole epistemic repertoire or establish an accuracy advantage.

## Corrections

| Observed problem | Correction | Acceptance boundary |
|---|---|---|
| The first JSON object was accepted and later operations discarded | Consume exactly one complete bare JSON object; reject trailing objects, duplicate keys and malformed data | Full parser plus role-specific Pydantic validation |
| Provider text parts and completion reasons were flattened or omitted | Preserve ordinary answer-block boundaries, response status and completion details; use the declared final-answer channel; retain non-operative commentary, normalize only exact duplicate finals, reject conflicting finals and incomplete generation | Provider adapter; private reasoning content is not recorded |
| Critic inherited proposer tool instructions and lacked a validated envelope | Separate critic prompt/schema; bounded repair of invalid critiques; controller executes evidence requests and presents their results before a final review | A malformed or provisional critique never counts as completed review |
| Structural record errors became stale argumentative objections | Repair record references and condition links before critique | Code validates structure; the critic examines substantive warrant |
| Editing an argument failed to resolve its challenge, or metadata could make a reply appear new | Stable question text plus revisable `Condition.answer`; explicit located reply; controller stamps semantic revisions, ignoring extra metadata and ID-list order | Edits alone do not discharge attacks; old challenges remain in the ledger |
| Text block locators were treated as table IDs | Typed manifests, exact argument schemas and side-effect-free preflight with corrective errors | No guessed or automatic tool substitution |
| Sensible withholding failed solely because universal propositions were unrepresentable | Admit universal claim records with explicit open coverage conditions | No current pattern can establish a universal; a document citation cannot grant population coverage |
| A drafting task ended with “the response can be drafted” | Require `response.deliverable` for requested policy messages and eligibility assessments | Presence is structural; adequacy and fidelity remain review questions |
| A no-graph failure received a vacuous structural pass | Report applicable checks and unassessed checks separately | No completed target means `unassessed`, not a pass |
| A legitimate established negative metaclaim failed direct status comparison | Explicit target relation and question anchor; normalization requires matching scope/form and graph/evaluation declarations | No inference from prose or automatic inversion; semantic alignment still needs review |
| An interrupted process lost its unsaved usage | Append and fsync each event to a live journal; inspection distinguishes incomplete journals and pending calls | An incomplete journal never becomes a fabricated completed run |

The OpenAI adapter requests a role schema with `strict:false` because graph records contain dynamic dictionaries. Generation is schema guided; **local acceptance is strict**. OpenAI's [schema documentation](https://developers.openai.com/api/docs/guides/prompt-generation#defining-a-constrained-meta-schema) distinguishes this from constrained strict-mode generation. Unsupported provider configurations fail explicitly without hidden fallback or extra SDK retries.

## Preserved distinctions

An existing open condition is an evidential gap. A link to a nonexistent condition is a record defect. A complete clarification can answer a task even while the underlying factual proposition remains unresolved. The kernel's disposition, the requested artifact, critical review and task completion are separate recorded results.

Actor identity, source exposure and source versions remain controller owned. An unchanged assessment cannot become a fresh reply by adding metadata, rearranging evidence IDs or claiming a new revision number. Substantive judgments remain defeasible and model supplied; structural consistency does not prove them true.

## Planned rerun

`experiments/v1/rerun_known_failures.py` repeats the same eight settings, public packet, model snapshots, effort and total resource caps as the first batch. It refuses a dirty checkout and writes its protocol before provider calls. No completed setting is rerun within that batch. Original and revised scorers are both retained for comparison; old results are rescored separately without modifying them or inferring missing orientation tags.

The inputs are wholly synthetic. Credentials are read from the environment or a hidden prompt and never persisted. All provider calls and evidence requests remain inside the shared limits. Human adjudication and the three-arm comparison remain future work.

Run from an installed checkout:

```sh
python experiments/v1/rerun_known_failures.py --out runs/v1/repair_20261114_live_v3
```

## Provider-format interruption before the completed rerun

The first repair batch, frozen at `f871bc5`, stopped after two failed cases and one interrupted case. The provider returned separate completed messages with byte-identical JSON in three replies. Rejecting every multi-block response prevented these unambiguous operations from running. Another reply contained distinct commentary plus repeated final JSON and remains correctly rejected.

Version `1.0.0a3` normalized only exact repeated complete answer messages into one operation. All original message boundaries and text remain in the usage record, with normalization metadata. Distinct messages, JSON fragments, duplicate JSON keys, incomplete output and appended operations remain invalid. This compatibility change does not authorize executing multiple operations per call.

The stopped batch is preserved separately, including the pending request whose eventual usage and outcome were not observed. The next batch uses a new directory and frozen commit. This is an explicit restart after a provider-format repair, not an unreported retry within the earlier protocol.

## Phase handling and terminal review correction

The complete intermediate batch at `24dbf24` retained the strict all-message rule. Its preserved traces exposed two integration errors addressed in `1.0.0a4`.

First, OpenAI's [deployment checklist](https://developers.openai.com/api/docs/guides/deployment-checklist) and [GPT-5.4 guide](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.4) define `commentary` as intermediate progress and `final_answer` as the completed response. The adapter now treats this as an explicit channel contract: commentary is preserved with its indexes and exclusion reason but never executed as an operation or admitted as evidence. Only the final channel supplies a candidate operation. Multiple distinct final answers remain invalid; exact repeated complete finals can normalize once. A legacy single unphased message remains supported without guessing a phase. No first-object parsing or last-message preference is used.

Second, a valid `finish` followed by a completed critique with no attacks should terminate when all existing task, record, scope, delivery and review gates hold. The controller previously continued despite that finish request, consuming calls on redundant confirmations and sometimes turning a complete artifact into an operational failure. The correction preserves the finish request through that review. An objection, invalid or provisional review, or incomplete record still requires further work.

The intermediate results remain separate. The final comparison reports every attempted batch and does not treat repeated development cases as independent held-out evidence. Raw traces are retained privately; they were not published to the public repository.
