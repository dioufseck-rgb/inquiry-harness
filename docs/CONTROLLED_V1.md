# Controlled inquiry v1

This implementation provides a small end-to-end inquiry loop and a controlled evidence environment. It is intended for building and testing the harness against known source material. It does not implement the complete reasoning repertoire in the conceptual design.

The main path is a public question and profile, evidence acquisition, a proposed argument record, deterministic evaluation, and a response carrying the resulting standing. The same controller and evidence tools also support two comparison arms without kernel-assigned standing. The legacy `inquiry` command remains separate; use `inquiry-v1` or `python -m inquiry.v1` for this implementation.

The harness worker receives exact tool contracts and an empty graph template derived from the requested product type. This template supplies no evidence, accepted conditions, or hidden answer. Explicit graph feedback and at most two record-repair requests distinguish malformed records from genuinely unresolved evidence. An unresolved evidence question may complete an assessment; an unfinished argument record is reported as an execution gap.

## Install and inspect

From the repository root, create an environment and install the package. The `llm` extra is needed for live provider calls; the deterministic demo requires no credentials.

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev,llm]'
.venv/bin/python -m inquiry.v1 --help
.venv/bin/python -m inquiry.v1 validate
```

`validate` loads the bundled authoring packet and validates every declared question and mutation. Pass `--packet PATH` to use another packet in the supported format. Validation checks record structure, allowed public fields, identifiers, references, source versions, lineage, and the finite mutation operations. It does not adjudicate the sources or establish that the expected answers are correct.

## The controlled hardship case

The bundled packet, `inquiry/v1/data/hardship.json`, describes a fictional assistance programme, applicant, flood bulletin, and policy. The authoring file contains public material alongside hidden-world facts and provisional assessment guidance. **Never send the complete authoring file to a worker.**

The loader exports exactly three public fields: `shared_context`, `corpus`, and one selected `question`. It strips oracle annotations, mutation names, other questions, and expected outcomes. The runtime receives this public projection; the scorer receives its separate oracle projection. This is a boundary within a trusted local process, not an operating-system security boundary.

The six questions ask for:

1. An attributed account of the applicant's reported financial impact.
2. A bounded event finding from the official bulletin.
3. Independent examination of the individual causal chain.
4. The next permitted intake response under the current policy.
5. A final-eligibility assessment under that policy.
6. Examination of a universal claim about workers in the area.

Each question can run against the baseline or one of six separate mutations: a derivative relay, missing impact details, an additional employer trace, a corrected event record, a policy revision, or changed display order and applicant alias. Mutations are applied independently to the baseline; combinations are outside this seed specification. Revised records retain history and update current-version bindings. Stable entity IDs survive the alias treatment.

This gives **42 question–evidence settings**. Crossing them with three arms and three evidence modes gives **378 attempts per repetition**. These are variants of one development family, not 378 independent cases. The packet and its categorical expectations are model-authored, provisional, and not human-adjudicated gold.

## Export and run one setting

```bash
.venv/bin/python -m inquiry.v1 export \
  --question question_004 --mutation mutation_002 \
  --out runs/v1/public-intake.json

.venv/bin/python -m inquiry.v1 run --demo \
  --question question_004 --mutation mutation_002 \
  --arm harness --mode documents \
  --out runs/v1/demo-intake
```

`export` writes the public corpus and selected question. The run's evidence mode subsequently determines how much of that corpus reaches each worker input. Giving a search-mode worker the entire export directly would defeat the intended access restriction.

`--demo` selects a deterministic, narrowly scripted development instrument. It reads actual public inputs and tool observations, exercises retrieval and graph submission, and records zero simulated token cost. It does not call a language model or provide independent criticism. Its results test integration and record handling; they are not estimates of model competence or architectural advantage. `RecordedWorker` is another test instrument for replaying prescribed worker replies.

## Arms and evidence modes

| Arm | Worker instructions and output |
|---|---|
| `ordinary` | Common evidence tools and response contract; no argument graph is required and the worker supplies its findings. |
| `repertoire` | Adds instructions to choose among the seven reasoning competences; standing remains worker-supplied. |
| `harness` | Requires a typed graph. The kernel computes standing and the renderer checks the declared target scope and product form. |

| Mode | Initial access |
|---|---|
| `supplied` | The public corpus, including version history and current bindings, is included in the worker input. |
| `documents` | A source/version manifest is supplied; the worker must open documents. |
| `search` | The worker receives the context and question, then discovers material through the corpus search tool. |

Search is deterministic lexical retrieval over the packet. It accepts new queries and uses stable source/version tie breaks; it is not web search. `open` requires a source ID and version, with an optional locator and character limit. `read_table` returns selected rows and columns with located cells, units, headers, and footnotes. Search defaults to current versions, while explicitly requested history remains available.

Tool results record exact text, source hashes, locators, and truncation. Returning text from a tool does not itself establish that a worker saw it. The controller separately records environment-issued source segments included in admitted worker inputs. Quote verification requires an exact match within that worker's exposure and the specified source version. Merely echoing a guessed citation or quotation in a draft does not create an exposure. Exposure demonstrates input inclusion, not comprehension or correct interpretation.

## Live workers and budgets

Live calls require an explicit `provider:model` specification. The adapters support `openai` and `anthropic`; supply a model available to your account. Set the corresponding API key in the process environment. Keep credentials out of packets, prompts, commands containing literal secrets, and saved run records.

```bash
.venv/bin/python -m inquiry.v1 run \
  --model 'openai:YOUR_MODEL_ID' --effort none \
  --question question_004 --arm harness --mode supplied \
  --calls 8 --tool-calls 12 --tokens 120000 \
  --output-tokens 4096 --timeout 180 \
  --out runs/v1/live-intake
```

The CLI defaults to `--effort none`, which omits provider reasoning-effort parameters. Use `low`, `medium`, or `high` only with a compatible model. There is no automatic model selection or fallback. Each adapter invocation makes at most one provider request, with SDK retries disabled; any subsequent worker attempt belongs to the controller's budget.

The CLI defaults are 10 model calls, 30 tool calls, 200,000 total tokens, 4,096 maximum output tokens per call, and a 180-second scheduling deadline. The controller checks limits before admission, reserves for serialized input and requested output, and records known usage separately from estimates. Failed attempts consume limits. Provider timeouts receive the remaining time; this is not a process-kill sandbox.

Add `--critic-model 'provider:MODEL_ID'` to request a critic in the repertoire or harness arm. Its calls consume the same run budget; the default permits one completed final critique. Invalid envelopes are repaired within the error and total-call limits. Evidence requests are provisional: the controller acquires the material and presents it to the critic before final review. The critic needs grounded objections, and replies remain examinable. Budget exhaustion does not make either party correct. A live critic cannot be combined with `--demo` through the CLI.

Version `1.0.0a4` separates proposer and critic output schemas, rejects ambiguous or incomplete replies, repairs structural graph defects before critique, and requires the actual requested draft or assessment in `response.deliverable`. See [the repair notes](V1_REPAIR_NOTES.md) for the changes motivated by the first live batch and their limits. Dynamic graph dictionaries use schema-guided generation with strict local acceptance; the system does not claim provider-enforced strict-schema generation.

There is no monetary budget flag or complete price table. Unpriced or unavailable cost remains unknown rather than becoming zero. For initial live work, use a small call/output limit and inspect usage before expanding the experiment.

## Controlled comparisons

Start with a limited selection:

```bash
.venv/bin/python -m inquiry.v1 bench --demo \
  --questions question_001 question_004 --baseline-only \
  --arms ordinary repertoire harness --modes supplied documents search \
  --repetitions 1 --order-seed 17 \
  --out runs/v1/development-small
```

Omit `--questions` and `--baseline-only` to include all settings. By default, `bench` uses all three arms but only `supplied` mode. Use a fresh output directory: an existing experiment's `runs.jsonl` is not overwritten.

The runner interleaves jobs using the recorded order seed, gives each attempt a fresh public copy, and retains failures in the denominators. Its manifest records the selected models, effort, prompts, profile, evidence, implementation hashes, resource envelope, and oracle version. The callback responsible for each run enforces the budget; a manifest declaration alone does not enforce it.

`bench` exits nonzero for failed runs, failed or errored structural audits, and failed or uncheckable categorical smoke assertions. Pending human review alone does not fail the command. These mechanical gates are distinct from an adjudicated claim about answer quality.

Assessment separates exact structural audits, provisional categorical smoke expectations, and human semantic review. A valid quotation does not establish entailment. A correct label does not establish a justified answer. Hidden-world truth, packet warrant, and the suitability of the proposed response remain distinct judgments. Missing human adjudication remains pending rather than being inferred from a smoke pass.

## Records and replay

A single `run` saves `result.json`, `ledger.jsonl`, `report.md`, and `assessment.json`. It also appends each event to `events.live.jsonl` during execution, so completed calls survive a process interruption. Use a new output directory; a live journal is never overwritten. `inspect_journal()` verifies and reports partial journals without presenting them as completed results. Results include the final graph and evaluation, worker exposures, usage, errors, stopping reason, and configuration. Bench output uses `runs.jsonl` and `experiment.json` to retain individual attempts and grouped summaries, with per-attempt journals under `journals/`. These scorer-facing experiment records can include oracle material; do not use them as worker inputs.

```bash
.venv/bin/python -m inquiry.v1 replay runs/v1/demo-intake
```

Replay verifies the saved ledger and result agreement, restores recorded exposures, and recomputes the final kernel evaluation without model or network calls. A non-graph arm has no kernel evaluation to reproduce. Replay is different from resampling a worker or rerunning an adaptive inquiry against the same corpus.

Hashes detect changed content and inconsistent chains. They are not signatures: someone able to replace the entire record can recompute them. The active ledger is held in memory and saved after the run; crash recovery and durable interactive pause/resume are not implemented by this CLI.

## Supported semantics and practical limits

The kernel implements a finite fragment: attribution and document-record arguments, rule application, a case-specific process-trace pattern, explicit conjunction/composition, and bounded absence. These cover parts of E1, E2, E3, and E5. The composition fragment does not provide general quantitative aggregation. Advanced E4 estimation, E6 instrument construction and validation, and E7 optimization or decision analysis are not implemented merely because their names appear in repertoire instructions.

Arguments require located evidence and named condition assessments. The kernel checks forms, references, exact scope equality, permitted assumptions, provenance, source currency, founded dependencies, and grounded attack labels. It preserves challenges across exact structural aliases. It does not independently establish whether a natural-language interpretation, causal explanation, source warrant, or applicability judgment is correct.

Scope comparison is exact field equality, not general entailment, quantified logic, or population transfer. The final product-form check is likewise a declared-type check. Unsupported forms and exhausted evaluation remain explicit gaps; a universal question is not silently answered by a particular finding.

Findings can be established, reported, conditional, contested, or not established. An accepted attribution does not establish its content. Missing evidence does not establish the opposite proposition. A clarification task can complete while eligibility remains unresolved. Caller-bound profile requirements cannot be weakened by a proposed graph, and no finding authorizes sending a response, awarding assistance, making a payment, or otherwise executing an action.

For code changes, run `.venv/bin/python -m pytest tests/v1 -q`. Add isolated kernel counterexamples for structural rules, frozen-input worker tests for semantic products, and end-to-end cases for acquisition and response behavior. Keep the provisional fixture separate from future independently authored and human-reviewed evaluation families.
