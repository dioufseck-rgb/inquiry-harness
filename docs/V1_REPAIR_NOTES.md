# V1 operational corrections before the second live batch

14 November 2026 · `1.0.0a2`

The first eight-case live batch is preserved at commit `7712518`, including its original scores. These changes address failures observed in that batch. They do not supply new inference patterns for the whole epistemic repertoire or establish an accuracy advantage.

## Corrections

| Observed problem | Correction | Acceptance boundary |
|---|---|---|
| The first JSON object was accepted and later operations discarded | Consume exactly one complete bare JSON object; reject trailing objects, duplicate keys and malformed data | Full parser plus role-specific Pydantic validation |
| Provider text parts and completion reasons were flattened or omitted | Preserve ordinary answer-block boundaries, response status and completion details; reject multiple answer blocks and incomplete generation | Provider adapter; private reasoning content is not recorded |
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
python experiments/v1/rerun_known_failures.py --out runs/v1/repair_20261114_live
```
