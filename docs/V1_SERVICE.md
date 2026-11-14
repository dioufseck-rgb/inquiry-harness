# Epistemic inquiry service

Version 1.0.0a5 — 14 November 2026

## Architectural boundary

The inquiry service examines propositions and returns their standing and warrant.
It does not own a caller's objectives, choose an operational response, or authorize
action. A finding is relative to an explicit scope, evidence set and acceptance
profile. It is not an instruction to the caller.

General methods, critical questions, provenance, evaluation semantics, acquisition
control, challenge, revision and stopping belong in the service. Domain facts,
policies, definitions and valuation criteria arrive as caller context or located
evidence. No institutional rule or workflow is built into the shared controller.
The model's background knowledge does not substitute for a recorded premise.

The harness owns evidence search and acquisition. Caller-supplied sources are
optional starting material. Within enabled sources and the inquiry budget, the
harness selects queries, discovers and fetches sources, reads the relevant
material and appraises what it finds. Domain-neutrality concerns the methods
and contracts; domain knowledge can be acquired during the inquiry. The host
supplies source access and credentials, while the caller can constrain scope,
sources and cost. The current v1 integration limit is described below.

The service may return an unresolved information need: the condition, the question
left open, and what evidence could resolve it. It returns this when the available
acquisition path cannot settle the gap within its limits, or when information
requires the caller's access or clarification. The caller decides how to handle
the remaining need. A business letter, intake transition, approval or payment
is a separate application product.

## What is implemented

The package now provides a domain-neutral request validator and evidence
environment, an epistemic controller, the finite argument kernel, a Python service
API, and an optional MCP stdio transport. Each invocation gets its own evidence,
graph, ledger and fresh workers supplied by host factories. No benchmark oracle
or application adapter is imported by the service.

The kernel currently supports attribution, document records, rule application,
single-event process tracing, explicit conjunction/composition, and bounded
absence. This is part of E1, E2, E3 and E5. A universal target can be represented
and examined without being forced into an unsupported positive proof pattern.
General estimation, forecasting, instrument building and quantitative composition
remain future work. The `capabilities` tool states the implemented patterns and
distinguishes representable forms from forms with a positive proof pattern.

The original harness already has external acquisition:
[`SerperSearch` and `EuropePMCSearch`](../inquiry/tools/search.py),
[`HttpFetcher`](../inquiry/tools/fetch.py), and the search, fetch and appraisal
loop in [`Harness`](../inquiry/live.py).

The rebuilt v1 service currently uses deterministic retrieval over a fixed source
collection so experiments can control what information is available. Its worker
chooses `search`, `open` and `read_table` operations, but external discovery and
dynamic source ingestion have not yet been connected to the new service. The
acquisition increment ports the existing providers into v1's provenance,
exposure, budget and replay contracts. It does not delegate all research to the
caller or require a new search implementation from scratch.

The request currently contains one caller-framed question and explicit target
kind/form; automatic framing of compound questions is not implemented by this
interface.

## Request contract

`InquiryRequest` has exactly three top-level fields:

| Field | Contents |
|---|---|
| `shared_context` | Required `as_of` date plus caller-supplied JSON context. |
| `corpus` | Initial `documents` and explicit `current_versions` keyed by source ID; the collection may be empty. |
| `question` | `id`, `question`, `intended_use`, `scope`, `target`, and `profile`. |

The a5 envelope still requires the `corpus` field. An empty initial collection is
`{"documents": [], "current_versions": {}}`. In the current fixed-source backend
it remains empty; external acquisition must be connected before the service can
populate it. The intended provider settings include fixed, live and mixed
acquisition; the experimental `supplied`, `documents` and `search` modes instead
control evidence exposure within a fixed collection.

`target` declares a claim `kind` and `form`; it does not supply the answer.
`profile` contains an ID, version, authority, substantive requirements and supported
kernel settings. The caller's requirements and thresholds are not editable by a
worker. An authority string records provenance; it does not authenticate the
caller's right to select an institutional profile. The embedding host owns that
authorization.

Sources retain issuer, origin, dates, versions, located text, optional tables,
derivation and revision history. Identifiers and scope fields are arbitrary
caller identifiers. There is no required policy, applicant, event, fictional
scenario or business-stage field. Relational validation checks all references,
acyclic lineage, locator integrity and unique current versions. Private benchmark
annotations are rejected recursively before a worker sees the request.

The full structural JSON Schema is returned by `capabilities`. Three complete
requests demonstrate unrelated domains:

- [Equipment temperature record](../examples/v1/equipment_temperature.json)
- [Attribution of a research result](../examples/v1/research_attribution.json)
- [Household meter record](../examples/v1/household_meter.json)

They are synthetic integration examples, not independently adjudicated model
benchmarks.

## Result contract

The Python service and MCP tools return a service envelope with `inquiry_id`,
`execution_status`, `stop_reason`, `response`, `graph`, `evaluation`, `profile`,
`usage` and an optional persistent `record_ref`. `include_record=True` additionally
returns the full trace, input exposures and journaled result.

The epistemic response contains findings, target identity, scope/form checks,
caveats, an optional assessment, `information_needs` and `inquiry_completed`.
Assessment text is model-authored explanatory prose; its presence is not a
semantic validity check. Each information need identifies an unresolved condition,
a question and what would resolve it. The response also exposes separate record,
evaluation and configured-review completion gates.

There is no `next_action`, `deliverable`, business decision, or application
`task_completed` field. These fields are rejected by the worker output contract.
The kernel's evaluation completion concerns one graph snapshot; it does not
declare the inquiry or application task complete.

An inquiry can complete with a well-supported account of an unresolved proposition.
An accepted proposition can also survive in a resource-limited execution. These
states remain distinct. Completion requires the correct target question, exact
declared scope/form, a sound record, completed configured review and no standing
attack. It does not require repeated identical wording or a customer letter.

## Python use

```python
import json
from functools import partial
from inquiry.v1.service import InquiryService
from inquiry.v1.workers import LLMWorker

service = InquiryService(
    worker_factory=partial(LLMWorker.from_spec, "openai:YOUR_PROPOSER_MODEL", effort="low"),
    critic_factory=partial(LLMWorker.from_spec, "openai:YOUR_CRITIC_MODEL", effort="low"),
    record_root="runs/service",
)
request = json.load(open("examples/v1/equipment_temperature.json"))
result = service.inquire(request, mode="documents")
```

Factories create fresh worker instances per invocation. Workers do not share a
mutable evidence environment between requests. The same service instance can
process unrelated domains; scope, facts and profiles come from each request.

`check(request)` conducts a focused model-assisted inquiry under the same
acceptance profile. Its default ceiling is four model calls, four evidence-tool
calls, 32,000 total tokens, 4,096 output tokens per call and 60 seconds, bounded
further by the host ceiling. It does not reduce the proof requirements to fit the
budget. Both operations may return partial or unresolved findings.

Hosts set the maximum model/tool/token resources and kernel work limits. Callers
can request smaller budgets; requests above the host ceilings are rejected before
worker construction. The time limit is a scheduling deadline with provider
timeouts, not a hard process-kill sandbox.

## MCP interface

Install the optional transport and provider packages:

```bash
python -m pip install -e '.[llm,service]'
inquiry-service --model 'openai:YOUR_PROPOSER_MODEL' \
  --critic-model 'openai:YOUR_CRITIC_MODEL' --record-root runs/service
```

The host starts this command as a stdio MCP subprocess and supplies provider
credentials through the environment. The server exposes:

| Tool | Function |
|---|---|
| `capabilities` | Inspect the request schema, implemented methods, limits and review configuration. |
| `inquire` | Conduct one bounded inquiry and return scoped findings and warrant. |
| `check` | Conduct a focused inquiry with a smaller ceiling and unchanged acceptance requirements. |
| `replay` | Verify and recompute a stored inquiry without model calls. |

The resource `inquiry://records/{inquiry_id}` returns a stored record. Record IDs
come from the controller; caller-supplied filesystem paths are not accepted.
The transport uses the official MCP Python SDK v1 API, tested with 1.29.0 and pinned
to `<2`. SDK documentation: <https://github.com/modelcontextprotocol/python-sdk/tree/v1.29.0>.

This is a runnable local transport, not a deployed public endpoint. Run one
instance per host trust boundary. Authenticated multi-tenant hosting, per-caller
record ACLs, cancellation, and service-wide concurrency quotas are separate work.
The service does not pretend that per-request isolation supplies tenant access
control. No schedule or `watch` tool is advertised until its lifecycle exists.

## Application and benchmark adapters

The original hardship authoring packet remains unchanged. Its explicit adapter
converts `Packet.public(...)` into a generic request and removes application
product contracts. Q4 now asks which intake requirements are evidentially satisfied
and which information is missing. The policy remains evidence supplied by the
caller; the controller has no intake rule.

The scripted hardship worker and expectations live in `inquiry.v1.adapters`.
`hardship_application.prepare_intake_draft(...)` demonstrates an external consumer
that creates a proposed letter and workflow step from a completed inquiry. It
returns those separately and does not mutate the epistemic result.

CLI `run --request request.json` accepts the generic contract without loading a
benchmark oracle or selecting hardship expectations. Custom authoring packets
require an explicit adapter. A requested business product is evaluated by its
application test, not by generic inquiry completion.

## Historical records

Version a5 changes request and response schemas. Old records and registered
protocols are retained. `replay --legacy-hardship` verifies the unchanged ledger
and explicitly adapts a copy of the old request; it reports whether the current
evaluation exactly equals the original. An old result with a changed schema is
not falsely reported as reproduced. Use its frozen implementation for exact
historical replay. `experiments/v1/rerun_known_failures.py` now points to its frozen
a4 implementation instead of running the old protocol against a different API.

## Completing the harness

This refactor establishes the boundary and the first callable service. The next
implementation increments should complete the inquiry process in this order:

| Increment | Product | Completion test |
|---|---|---|
| Frame and plan | Atomic issues, presuppositions, dependencies, explicit gaps and recorded competence selection. | The same evidence under different question/use settings produces the correct target and adequate depth. |
| Acquire and appraise | Port the existing external search/fetch providers, register acquired source snapshots, and preserve full relevant reading, located observations and appraisal. | Known hidden sections are found; unavailable evidence remains distinguishable from unread evidence; frozen provider responses and replay retain exposure, lineage and budgets. |
| Extend methods | Condition contracts for remaining patterns, E4 estimation, E6 validated instruments, and explicit comparative claims. | Paired cases discriminate warranted acceptance, withholding and invalid bridges; unsupported methods remain explicit. |
| Re-entry and change | Issue budgets, resumable inquiries, source updates, dependency recomputation and scoped reuse. | Correcting a premise changes only affected findings and retains the original history. |
| Watch and hosting | Evidence-change triggers and a deployment boundary for independent callers. | Staleness triggers re-examination; tenant records and budgets remain isolated; watching performs no business action. |

Framing, acquisition/appraisal and challenge remain standing functions. Competences
are selected to answer epistemic gaps; they do not own the caller's workflow.
The intended comparative competence examines a proposition under supplied goals,
constraints and values. Choosing those values or acting on the comparison remains
outside this service.

Evaluation accompanies each increment: fixed-evidence paired cases first, then
live acquisition; bare prompt, repertoire-only and harness arms with matched
resources; a held-out set; repeated runs and independent human adjudication.
Software integration success is not evidence of improved judgment. Broader live
experiments should use the frozen generic contract rather than the old business
delivery metric.
