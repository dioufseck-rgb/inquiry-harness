"""A reusable epistemic service around the inquiry controller.

The host supplies fresh worker factories and a per-inquiry resource ceiling.
Callers supply questions, evidence and declared acceptance profiles. No business
workflow, application adapter, benchmark oracle or execution tool is imported.
The optional record directory belongs to the host, never to a tool argument.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping
from uuid import uuid4

from . import __version__
from .contracts import STAKES_LEVELS, canonical_json, validate_inquiry_request
from .kernel import PATTERN_FORMS, PATTERN_REQUIREMENTS, SUPPORTED_FORMS
from .models import Profile
from .persistence import load_run, save_run
from .premises import (add_usage, can_fund, examination_order, premise_budget, premise_set_json_schema,
                       premise_summary, remaining_budget, validate_premise_set)
from .runtime import Budget, ZERO_COST_PROVIDERS, replay_run, run_inquiry, validate_prices
from .triage import ROUTES, run_triage


SERVICE_VERSION = "epistemic-inquiry/v1"
_BUSINESS_RESPONSE_FIELDS = frozenset({"next_action", "deliverable", "task_completed",
                                     "decision", "authorization", "approved_action",
                                     "approved", "all_clear", "proceed", "go", "cleared"})
_FOCUSED_LIMITS = {"max_model_calls": 4, "max_tool_calls": 4,
                   "max_total_tokens": 32000, "max_output_tokens": 4096,
                   "timeout_seconds": 60.0, "max_consecutive_errors": 2,
                   "max_critique_calls": 1}
_KERNEL_RESOURCE_FIELDS = ("max_derivations", "max_depth", "max_evaluation_steps")
_KERNEL_DEFAULTS = {name: getattr(Profile(id="resource-defaults"), name)
                    for name in _KERNEL_RESOURCE_FIELDS}


class InquiryService:
    """Host-configured service; a fresh controller, workers and evidence per call.

    Factories must return a fresh worker for each invocation. Authentication of
    callers and authority to select a profile belong to the embedding host. An
    authority string is provenance metadata, not authenticated authorization.
    This class performs no business actions and uses the controlled source
    environment; live retrieval adapters and scheduled watching are not implied.
    """

    def __init__(self, worker_factory: Callable[[], Any], *,
                 critic_factory: Callable[[], Any] | None = None,
                 max_budget: Budget | None = None,
                 max_kernel_work: Mapping[str, int] | None = None,
                 record_root: str | Path | None = None,
                 max_request_bytes: int = 4 * 1024 * 1024,
                 tiers: Mapping[str, Budget | Mapping[str, Any]] | None = None,
                 prices: Mapping[str, Mapping[str, float]] | None = None,
                 worker_identities: list[str] | None = None,
                 unclassified_route: str = "inquire",
                 max_premises: int = 8,
                 max_set_budget: Budget | None = None):
        if not callable(worker_factory) or (critic_factory is not None and not callable(critic_factory)):
            raise TypeError("worker factories must be callable")
        if isinstance(max_request_bytes, bool) or not isinstance(max_request_bytes, int) or max_request_bytes < 1:
            raise ValueError("max_request_bytes must be a positive integer")
        self._worker_factory = worker_factory
        self._critic_factory = critic_factory
        self._ceiling = Budget(**asdict(max_budget or Budget()))
        extra = dict(max_kernel_work or {})
        if set(extra) - set(_KERNEL_RESOURCE_FIELDS):
            raise ValueError("Unknown kernel resource limit")
        self._kernel_ceiling = {**_KERNEL_DEFAULTS, **extra}
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in self._kernel_ceiling.values()):
            raise ValueError("Kernel resource limits must be nonnegative integers")
        self._record_root = Path(record_root).resolve() if record_root is not None else None
        self._max_request_bytes = max_request_bytes
        self._prices = validate_prices(dict(prices) if prices is not None else None)
        if worker_identities is not None and (not isinstance(worker_identities, list)
                                              or any(not isinstance(x, str) or ":" not in x for x in worker_identities)):
            raise ValueError("worker_identities must be a list of provider:model strings")
        self._worker_identities = list(worker_identities) if worker_identities is not None else None
        if unclassified_route not in ROUTES:
            raise ValueError(f"unclassified_route must be one of {list(ROUTES)}")
        self._unclassified_route = unclassified_route
        if isinstance(max_premises, bool) or not isinstance(max_premises, int) or max_premises < 1:
            raise ValueError("max_premises must be a positive integer")
        self._max_premises = max_premises
        self._set_ceiling = Budget(**asdict(max_set_budget)) if max_set_budget is not None else self._default_set_ceiling()
        self._tiers = self._default_tiers()
        for level, value in dict(tiers or {}).items():
            if level not in STAKES_LEVELS:
                raise ValueError(f"Unknown budget tier {level!r}; expected one of {list(STAKES_LEVELS)}")
            # _limits rejects any field above the host ceiling
            self._tiers[level] = self._limits(value, focused=False)

    def _default_set_ceiling(self) -> Budget:
        """A premise set may spend up to max_premises inquiries at the per-inquiry ceiling."""
        high = asdict(self._ceiling)
        scaled = {}
        for key, value in high.items():
            if key in ("max_output_tokens", "max_consecutive_errors", "max_critique_calls") or value is None:
                scaled[key] = value
            else:
                scaled[key] = value * self._max_premises
        return Budget(**scaled)

    def _set_limits(self, requested: Mapping[str, Any] | Budget | None) -> Budget:
        ceiling = asdict(self._set_ceiling)
        if requested is None:
            return Budget(**ceiling)
        values = asdict(requested) if isinstance(requested, Budget) else dict(requested)
        unknown = set(values) - ceiling.keys()
        if unknown:
            raise ValueError(f"Unknown budget fields: {sorted(unknown)}")
        budget = Budget(**{**ceiling, **values})
        exceeded = [key for key, value in asdict(budget).items()
                    if ceiling[key] is not None and (value is None or value > ceiling[key])]
        if exceeded:
            raise ValueError(f"Requested set budget exceeds the host set ceiling: {sorted(exceeded)}")
        return budget

    def _default_tiers(self) -> dict[str, Budget]:
        """low: the focused ceiling; high: the host ceiling; medium: half of high, never below low."""
        high = asdict(self._ceiling)
        low = {key: (min(value, _FOCUSED_LIMITS[key]) if key in _FOCUSED_LIMITS else value) for key, value in high.items()}
        medium = {}
        for key, value in high.items():
            if value is None:
                medium[key] = None
                continue
            half = value / 2 if key in ("timeout_seconds", "max_cost_usd") else value // 2
            medium[key] = max(low[key], half)
        return {"low": Budget(**low), "medium": Budget(**medium), "high": Budget(**high)}

    def capabilities(self) -> dict[str, Any]:
        """Describe implemented operations without promising unbuilt competences."""
        from .contracts import request_json_schema
        return {
            "service_version": SERVICE_VERSION,
            "implementation_version": __version__,
            "purpose": "Examine propositions and return scoped standing and warrant.",
            "epistemic_only": True,
            "operations": ["inquire", "check", "replay", "triage", "examine_premises"],
            "premise_check": {"max_premises": self._max_premises, "set_ceiling": asdict(self._set_ceiling),
                              "returns": "per-premise standing and routing; never a single go or no-go value",
                              "request_schema": premise_set_json_schema()},
            "triage": {"classes": ["state", "judgment", "tacit", "intent", "unclassified"],
                       "routes": list(ROUTES), "unclassified_route": self._unclassified_route,
                       "ceiling": {"max_model_calls": 2, "max_total_tokens": 4096, "max_output_tokens": 512},
                       "sees_source_text": False},
            "evidence_modes": ["supplied", "documents", "search"],
            "evidence_access": "Caller-supplied source collection; search is local corpus search.",
            "patterns": {name: {"forms": list(PATTERN_FORMS[name]), "conditions": list(conditions)}
                         for name, conditions in PATTERN_REQUIREMENTS.items()},
            "representable_target_forms": sorted(SUPPORTED_FORMS),
            "forms_without_proof_pattern": sorted(set(SUPPORTED_FORMS) -
                                                    {form for forms in PATTERN_FORMS.values() for form in forms}),
            "per_inquiry_ceiling": asdict(self._ceiling),
            "price_entries": sorted(self._prices),
            "worker_identities": list(self._worker_identities) if self._worker_identities is not None else None,
            "budget_tiers": {level: asdict(budget) for level, budget in self._tiers.items()},
            "kernel_work_ceiling": dict(self._kernel_ceiling),
            "focused_check_ceiling": self._limits(None, focused=True).__dict__,
            "max_request_bytes": self._max_request_bytes,
            "critical_review_configured": self._critic_factory is not None,
            "persistent_records": self._record_root is not None,
            "request_schema": request_json_schema(),
            "limitations": [
                "Declared scope and forms are checked structurally; semantic judgment remains examinable.",
                "A complete inquiry may return a proposition that is not established.",
                "Profiles do not grant permission to act.",
                "Timeouts are scheduling deadlines with provider timeouts, not process-kill guarantees.",
                "Live discovery, instrument execution and scheduled watch are not implemented by this service.",
                "Budget tiers scale resources by declared stakes; they never change the acceptance profile.",
            ],
        }

    def _limits(self, requested: Mapping[str, Any] | Budget | None, *, focused: bool) -> Budget:
        ceiling = asdict(self._ceiling)
        if focused:
            ceiling = {key: (min(value, _FOCUSED_LIMITS[key]) if key in _FOCUSED_LIMITS else value)
                       for key, value in ceiling.items()}
        if requested is None:
            return Budget(**ceiling)
        values = asdict(requested) if isinstance(requested, Budget) else dict(requested)
        unknown = set(values) - ceiling.keys()
        if unknown:
            raise ValueError(f"Unknown budget fields: {sorted(unknown)}")
        budget = Budget(**{**ceiling, **values})
        exceeded = [key for key, value in asdict(budget).items()
                    if ceiling[key] is not None and (value is None or value > ceiling[key])]
        if exceeded:
            raise ValueError(f"Requested budget exceeds the host ceiling: {sorted(exceeded)}")
        return budget

    def _check_prices_cover_workers(self) -> None:
        """A cost cap is accepted only when every configured worker can be priced; checked before construction."""
        if self._worker_identities is None:
            raise ValueError("max_cost_usd is set but the host supplied no worker_identities; the cap could not be enforced")
        for identity in self._worker_identities:
            if identity.split(":", 1)[0] in ZERO_COST_PROVIDERS:
                continue
            if identity not in self._prices:
                raise ValueError(f"max_cost_usd is set but there is no price entry for {identity}")

    def inquire(self, request: Mapping[str, Any], *,
                budget: Mapping[str, Any] | Budget | None = None,
                mode: str = "documents", include_record: bool = False) -> dict[str, Any]:
        """Conduct one bounded inquiry; domain context is request data."""
        return self._run(request, budget=budget, mode=mode, include_record=include_record, focused=False)

    def check(self, request: Mapping[str, Any], *,
              budget: Mapping[str, Any] | Budget | None = None,
              mode: str = "supplied", include_record: bool = False) -> dict[str, Any]:
        """A focused inquiry with a smaller resource ceiling and the same standard.

        This is a model-assisted examination, not merely JSON or citation
        validation. Reducing the budget never weakens the acceptance profile.
        """
        return self._run(request, budget=budget, mode=mode, include_record=include_record, focused=True)

    def _run(self, request: Mapping[str, Any], *, budget: Mapping[str, Any] | Budget | None,
             mode: str, include_record: bool, focused: bool) -> dict[str, Any]:
        if hasattr(request, "model_dump"):
            request = request.model_dump(mode="json")
        raw = deepcopy(dict(request))
        if len(canonical_json(raw).encode("utf-8")) > self._max_request_bytes:
            raise ValueError("Inquiry request exceeds the host byte limit")
        public = validate_inquiry_request(raw)
        if mode not in {"supplied", "documents", "search"}:
            raise ValueError("Unknown evidence mode")
        if not isinstance(include_record, bool):
            raise TypeError("include_record must be boolean")
        if budget is None and not focused and "stakes" in public["question"]:
            # the caller declared stakes and no explicit budget: the tier applies
            limits = self._tiers[public["question"]["stakes"]["level"]]
        else:
            limits = self._limits(budget, focused=focused)
        if limits.max_cost_usd is not None:
            self._check_prices_cover_workers()
        profile_work = {**_KERNEL_DEFAULTS, **{key: value for key, value in
                        public["question"]["profile"]["kernel"].items() if key in _KERNEL_RESOURCE_FIELDS}}
        exceeded = [key for key, value in profile_work.items() if value > self._kernel_ceiling[key]]
        if exceeded:
            raise ValueError(f"Requested kernel work exceeds the host ceiling: {sorted(exceeded)}")
        # Validation precedes worker creation and any provider request.
        worker = self._worker_factory()
        critic = self._critic_factory() if self._critic_factory else None
        if critic is worker:
            raise ValueError("Proposer and critic must have separate worker instances")
        pending = None
        if self._record_root is not None:
            self._record_root.mkdir(parents=True, exist_ok=True)
            pending = self._record_root / ("pending_" + uuid4().hex)
            pending.mkdir()
        result = run_inquiry(public, worker, critic=critic, arm="harness", mode=mode, budget=limits,
                             event_path=pending / "events.live.jsonl" if pending else None,
                             prices=self._prices)
        forbidden = _BUSINESS_RESPONSE_FIELDS.intersection(result.get("response", {}))
        if forbidden:
            raise RuntimeError(f"Core returned fields outside the epistemic boundary: {sorted(forbidden)}")
        record_ref = None
        if pending is not None:
            destination = self._record_root / result["run_id"]
            if destination.exists():
                raise FileExistsError("Inquiry record ID already exists")
            pending.rename(destination)
            save_run(result, destination)
            record_ref = "inquiry://records/" + result["run_id"]
        response = {
            "service_version": SERVICE_VERSION,
            "inquiry_id": result["run_id"],
            "operation": "check" if focused else "inquire",
            "execution_status": result["status"],
            "stop_reason": result["stop_reason"],
            "response": deepcopy(result["response"]),
            "graph": deepcopy(result.get("graph")),
            "evaluation": deepcopy(result.get("evaluation")),
            "profile": deepcopy(result.get("manifest", {}).get("profile")),
            "usage": deepcopy(result.get("usage", {})),
            "record_ref": record_ref,
        }
        if include_record:
            response["record"] = result
        return response

    def triage(self, request: Mapping[str, Any], *, action_context: str | None = None,
               include_record: bool = False) -> dict[str, Any]:
        """Classify one question and route it in code; one small model call, no source text exposed."""
        if hasattr(request, "model_dump"):
            request = request.model_dump(mode="json")
        raw = deepcopy(dict(request))
        if len(canonical_json(raw).encode("utf-8")) > self._max_request_bytes:
            raise ValueError("Inquiry request exceeds the host byte limit")
        public = validate_inquiry_request(raw)
        if action_context is not None and not isinstance(action_context, str):
            raise TypeError("action_context must be a string")
        if not isinstance(include_record, bool):
            raise TypeError("include_record must be boolean")
        if self._ceiling.max_cost_usd is not None:
            self._check_prices_cover_workers()
        worker = self._worker_factory()
        result = run_triage(public, worker, action_context=action_context,
                            unclassified_route=self._unclassified_route, prices=self._prices)
        response = {
            "service_version": SERVICE_VERSION,
            "operation": "triage",
            "question_id": result["question_id"],
            "triage": deepcopy(result["triage"]),
            "usage": deepcopy(result["usage"]),
            "exposures": deepcopy(result["exposures"]),
        }
        if include_record:
            response["record"] = result
        return response

    def examine_premises(self, request: Mapping[str, Any], *,
                         budget: Mapping[str, Any] | Budget | None = None,
                         mode: str = "documents", include_record: bool = False) -> dict[str, Any]:
        """Triage every premise, examine those routed to inquiry or marked always, report per premise.

        Examined premises run high stakes first, then request order, each with
        the smaller of its tier budget and what remains of the set budget, in
        its own evidence environment with fresh workers and its own record.
        When the remainder cannot fund the low tier the rest are not examined.
        No field combines the results into a decision; the caller does that.
        """
        if hasattr(request, "model_dump"):
            request = request.model_dump(mode="json")
        raw = deepcopy(dict(request))
        if len(canonical_json(raw).encode("utf-8")) > self._max_request_bytes:
            raise ValueError("Premise-set request exceeds the host byte limit")
        validated = validate_premise_set(raw, max_premises=self._max_premises)
        if mode not in {"supplied", "documents", "search"}:
            raise ValueError("Unknown evidence mode")
        if not isinstance(include_record, bool):
            raise TypeError("include_record must be boolean")
        set_budget = self._set_limits(budget)
        if set_budget.max_cost_usd is not None or self._ceiling.max_cost_usd is not None:
            self._check_prices_cover_workers()
        questions, examine = validated["questions"], validated["examine"]
        set_id = uuid4().hex
        usage_total: dict[str, Any] = {"cost_complete": True, "cost_usd": 0.0, "known_cost_usd": 0.0}
        triages = []
        for question in questions:
            record = run_triage(question, self._worker_factory(), action_context=validated["action_context"],
                                unclassified_route=self._unclassified_route, prices=self._prices)
            triages.append(record)
            add_usage(usage_total, record["usage"])
        selected = [index for index, record in enumerate(triages)
                    if record["triage"]["route"] == "inquire" or examine[index] == "always"]
        reasons: dict[int, str | None] = {index: (None if index in selected else "routed") for index in range(len(questions))}
        results: dict[int, dict[str, Any]] = {}
        funded = True
        for index in examination_order(questions, selected):
            remaining = remaining_budget(set_budget, usage_total)
            if not funded or not can_fund(remaining, self._tiers["low"]):
                funded = False
                reasons[index] = "budget"
                continue
            tier = self._tiers[questions[index]["question"]["stakes"]["level"]]
            out = self._run(questions[index], budget=premise_budget(tier, remaining), mode=mode,
                            include_record=include_record, focused=False)
            results[index] = out
            add_usage(usage_total, out["usage"])
        premises = []
        for index, question in enumerate(questions):
            summary = premise_summary(question["question"]["id"], triages[index]["triage"], examine[index],
                                      examined=index in results, not_examined_reason=reasons[index],
                                      inquiry=results.get(index))
            if include_record:
                summary["triage_record"] = triages[index]
                if index in results:
                    summary["record"] = results[index]["record"]
            premises.append(summary)
        if usage_total["cost_complete"] is False:
            usage_total["cost_usd"] = None
        response: dict[str, Any] = {
            "service_version": SERVICE_VERSION,
            "operation": "examine_premises",
            "premise_set_id": set_id,
            "action_context": validated["action_context"],
            "premises": premises,
            "unmet_premise_ids": [p["premise_id"] for p in premises if p["examined"] and p["meets_declared_standing"] is not True],
            "unexamined_premise_ids": [p["premise_id"] for p in premises if not p["examined"]],
            "usage": usage_total,
            "record_ref": None,
        }
        forbidden = _BUSINESS_RESPONSE_FIELDS.intersection(response)
        for premise in premises:
            forbidden |= _BUSINESS_RESPONSE_FIELDS.intersection(premise)
        if forbidden:
            raise RuntimeError(f"Premise check returned fields outside the epistemic boundary: {sorted(forbidden)}")
        if self._record_root is not None:
            directory = self._record_root / ("set_" + set_id)
            directory.mkdir(parents=True, exist_ok=False)
            stored = {key: value for key, value in response.items() if key != "record_ref"}
            stored["premises"] = [{key: value for key, value in p.items() if key != "record"} for p in premises]
            stored["inquiry_record_refs"] = [p["record_ref"] for p in premises if p.get("record_ref")]
            (directory / "set.json").write_text(json.dumps(stored, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                                                encoding="utf-8")
            response["record_ref"] = "inquiry://premise-sets/" + set_id
        return response

    def read_premise_set(self, set_id: str) -> dict[str, Any]:
        """Read a stored premise-set record; it links the per-premise inquiry records."""
        if not isinstance(set_id, str) or not re.fullmatch(r"[0-9a-f]{32}", set_id):
            raise ValueError("Invalid premise set ID")
        if self._record_root is None:
            raise ValueError("Persistent records are not configured")
        directory = self._record_root / ("set_" + set_id)
        if directory.is_symlink() or directory.resolve().parent != self._record_root:
            raise ValueError("Record is outside the configured store")
        return json.loads((directory / "set.json").read_text(encoding="utf-8"))

    def read_record(self, inquiry_id: str) -> dict[str, Any]:
        """Read a host-owned stored record; callers cannot select filesystem paths."""
        if not isinstance(inquiry_id, str) or not re.fullmatch(r"[0-9a-f]{32}", inquiry_id):
            raise ValueError("Invalid inquiry ID")
        if self._record_root is None:
            raise ValueError("Persistent records are not configured")
        directory = self._record_root / inquiry_id
        if directory.is_symlink() or directory.resolve().parent != self._record_root:
            raise ValueError("Record is outside the configured store")
        return load_run(directory)

    def replay(self, inquiry_id: str) -> dict[str, Any]:
        """Recompute a stored record's evaluation without a model call.

        Replay checks record consistency, not the truth of the sources or the
        correctness of their interpretation. Hash chains are not signatures.
        """
        return replay_run(self.read_record(inquiry_id))
