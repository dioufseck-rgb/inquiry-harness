"""A reusable epistemic service around the inquiry controller.

The host supplies fresh worker factories and a per-inquiry resource ceiling.
Callers supply questions, evidence and declared acceptance profiles. No business
workflow, application adapter, benchmark oracle or execution tool is imported.
The optional record directory belongs to the host, never to a tool argument.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import re
from typing import Any, Callable, Mapping
from uuid import uuid4

from . import __version__
from .contracts import canonical_json, validate_inquiry_request
from .kernel import PATTERN_FORMS, PATTERN_REQUIREMENTS, SUPPORTED_FORMS
from .models import Profile
from .persistence import load_run, save_run
from .runtime import Budget, replay_run, run_inquiry


SERVICE_VERSION = "epistemic-inquiry/v1"
_BUSINESS_RESPONSE_FIELDS = frozenset({"next_action", "deliverable", "task_completed",
                                     "decision", "authorization", "approved_action"})
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
                 max_request_bytes: int = 4 * 1024 * 1024):
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

    def capabilities(self) -> dict[str, Any]:
        """Describe implemented operations without promising unbuilt competences."""
        from .contracts import request_json_schema
        return {
            "service_version": SERVICE_VERSION,
            "implementation_version": __version__,
            "purpose": "Examine propositions and return scoped standing and warrant.",
            "epistemic_only": True,
            "operations": ["inquire", "check", "replay"],
            "evidence_modes": ["supplied", "documents", "search"],
            "evidence_access": "Caller-supplied source collection; search is local corpus search.",
            "patterns": {name: {"forms": list(PATTERN_FORMS[name]), "conditions": list(conditions)}
                         for name, conditions in PATTERN_REQUIREMENTS.items()},
            "representable_target_forms": sorted(SUPPORTED_FORMS),
            "forms_without_proof_pattern": sorted(set(SUPPORTED_FORMS) -
                                                    {form for forms in PATTERN_FORMS.values() for form in forms}),
            "per_inquiry_ceiling": asdict(self._ceiling),
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
            ],
        }

    def _limits(self, requested: Mapping[str, Any] | Budget | None, *, focused: bool) -> Budget:
        ceiling = asdict(self._ceiling)
        if focused:
            ceiling = {key: min(value, _FOCUSED_LIMITS[key]) for key, value in ceiling.items()}
        if requested is None:
            return Budget(**ceiling)
        values = asdict(requested) if isinstance(requested, Budget) else dict(requested)
        unknown = set(values) - ceiling.keys()
        if unknown:
            raise ValueError(f"Unknown budget fields: {sorted(unknown)}")
        budget = Budget(**{**ceiling, **values})
        exceeded = [key for key, value in asdict(budget).items() if value > ceiling[key]]
        if exceeded:
            raise ValueError(f"Requested budget exceeds the host ceiling: {sorted(exceeded)}")
        return budget

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
        limits = self._limits(budget, focused=focused)
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
                             event_path=pending / "events.live.jsonl" if pending else None)
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
