"""Common controlled runner. Worker callbacks receive public cases, never oracles.

The caller supplies a synchronous ``run_case(public_case, *, arm, mode)`` which
closes over workers and enforced budgets. This module schedules repetitions,
logs declared configuration and failures, and reports exact audits separately
from human outcome review. It does not implement or favor any experimental arm.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import random
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from .scoring import evaluation_completion_state, score_run

ARMS = ("ordinary", "repertoire", "harness")
MODES = ("supplied", "documents", "search")
PROTOCOL_VERSION = "controlled-runner-0.1"
FORBIDDEN_PUBLIC_KEYS = frozenset({
    "evaluator_only", "hidden_world", "admissible_answer_spec", "admissible_answer_specs",
    "controlled_mutations", "expected_relationships", "annotation_status", "export_requirement",
    "oracle", "oracle_version", "smoke_expectation", "mutation_id", "variant_id",
})


def stable_hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")).hexdigest()


def validate_public_case(public_case: Mapping[str, Any]) -> None:
    if set(public_case) != {"shared_context", "corpus", "question"}:
        raise ValueError("Public case must contain exactly shared_context, corpus, and question.")
    if not all(isinstance(public_case[key], Mapping) for key in public_case):
        raise ValueError("Public context, corpus, and question must each be records.")

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            forbidden = FORBIDDEN_PUBLIC_KEYS.intersection(value)
            if forbidden:
                raise ValueError(f"Private evaluation keys in public case: {sorted(forbidden)}")
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(public_case)
    stable_hash(public_case)  # Reject non-JSON and non-finite values before any worker sees them.


@dataclass(frozen=True)
class ExperimentCase:
    case_id: str
    family_id: str
    public_case: Mapping[str, Any]
    oracle: Mapping[str, Any]
    question_id: str
    variant_id: str = "baseline"
    split: str = "development"
    smoke_expectation: Mapping[str, Any] | None = None
    human_adjudication: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        validate_public_case(self.public_case)
        if not self.case_id or not self.family_id:
            raise ValueError("Case and family IDs must be nonempty.")
        if self.public_case["question"].get("id") != self.question_id:
            raise ValueError("Private case bookkeeping does not match its public active question.")


class RunExecutionError(RuntimeError):
    """An adapter may preserve costs incurred before an exception with this type."""

    def __init__(self, message: str, *, usage: Mapping[str, Any] | None = None,
                 partial_result: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.usage = dict(usage) if usage is not None else None
        self.partial_result = dict(partial_result) if partial_result is not None else None


def _result_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, Mapping):
        raise TypeError("run_case must return a JSON mapping or Pydantic model.")
    result = deepcopy(dict(value))
    stable_hash(result)
    return result


def _failed_result(error: Exception, case: ExperimentCase, arm: str, mode: str,
                   elapsed: float) -> dict[str, Any]:
    partial = getattr(error, "partial_result", None)
    result = deepcopy(dict(partial)) if isinstance(partial, Mapping) else {}
    usage = getattr(error, "usage", None)
    if not isinstance(usage, Mapping):
        usage = result.get("usage")
    if not isinstance(usage, Mapping):
        usage = {key: None for key in ("model_calls", "input_tokens", "output_tokens", "tool_calls",
                                      "failed_calls", "cost_usd")}
    result.update(arm=arm, mode=mode, status="failed", question_id=case.question_id,
                  question=case.public_case["question"].get("question", ""),
                  usage={**dict(usage), "elapsed_seconds": elapsed}, stop_reason="runner_exception")
    result.setdefault("response", {"text": "", "target_claim_id": None, "findings": [],
                                   "target_scope_answered": False,
                                   "next_action": {"kind": "none", "description": "", "condition_ids": []},
                                   "task_completed": False, "caveats": []})
    result.setdefault("graph", None)
    result.setdefault("evaluation", None)
    result.setdefault("events", [])
    result.setdefault("exposures", [])
    result.setdefault("manifest", {})
    result["errors"] = [*result.get("errors", []), f"{type(error).__name__}: {error}"]
    return result


def _run_manifest(case: ExperimentCase, arm: str, mode: str, repeat: int,
                  configuration: Mapping[str, Any], order_seed: int) -> dict[str, Any]:
    public = case.public_case
    model_pool = configuration.get("model_pool")
    prompt_hashes = configuration.get("prompt_hashes", {})
    prompt_hash = prompt_hashes.get(arm) if isinstance(prompt_hashes, Mapping) else None
    fields = {
        "protocol_version": PROTOCOL_VERSION, "case_id": case.case_id,
        "family_id": case.family_id, "question_id": case.question_id,
        "variant_id": case.variant_id, "split": case.split,
        "arm": arm, "mode": mode, "repetition": repeat, "order_seed": order_seed,
        "packet_hash": stable_hash({"shared_context": public["shared_context"], "corpus": public["corpus"]}),
        "public_input_hash": stable_hash(public), "question_hash": stable_hash(public["question"]),
        "profile_hash": stable_hash(public["question"].get("profile", {})),
        "oracle_hash": stable_hash(case.oracle), "oracle_version": configuration.get("oracle_version"),
        "model_pool": deepcopy(model_pool), "model_hash": stable_hash(model_pool) if model_pool else None,
        "prompt_hash": prompt_hash, "tool_hash": configuration.get("tool_hash"),
        "kernel_hash": configuration.get("kernel_hash"), "code_version": configuration.get("code_version"),
        "resource_envelope": deepcopy(configuration.get("resource_envelope")),
        "execution_kind": configuration.get("execution_kind", "unspecified"),
        "smoke_oracle_version": case.smoke_expectation.get("oracle_version") if case.smoke_expectation else None,
        "budget_enforcement": "Caller-supplied run_case is responsible; declaration alone is not enforcement.",
    }
    required = ("oracle_version", "model_hash", "prompt_hash", "tool_hash", "kernel_hash",
                "code_version", "resource_envelope")
    fields["missing_configuration"] = [key for key in required if fields.get(key) is None]
    return fields


def _known_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0


def summarize_runs(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """All attempts remain in denominators; unavailable accounting remains unknown."""
    usage_keys = ("model_calls", "input_tokens", "output_tokens", "tool_calls", "failed_calls", "cost_usd")
    totals = {key: 0 for key in usage_keys}
    unknown = {key: 0 for key in usage_keys}
    statuses: Counter[str] = Counter()
    smoke: Counter[str] = Counter()
    human: Counter[str] = Counter()
    structural: Counter[str] = Counter()
    evaluation_states: Counter[str] = Counter()
    completed = 0
    elapsed = 0.0
    for record in records:
        run = record["result"]
        statuses[str(run.get("status", "failed"))] += 1
        response = run.get("response", {})
        evaluation_done = evaluation_completion_state(run)
        evaluation_states["pending" if evaluation_done is None else "complete" if evaluation_done else "not_completed"] += 1
        completed += int(isinstance(response, Mapping) and response.get("task_completed") is True
                         and response.get("target_scope_answered") is not False
                         and response.get("target_form_answered") is not False
                         and response.get("delivery_completed") is not False
                         and response.get("review_completed") is not False
                         and evaluation_done is not False
                         and run.get("status") != "failed")
        usage = run.get("usage", {})
        usage = usage if isinstance(usage, Mapping) else {}
        for key in usage_keys:
            value = usage.get(key)
            if _known_number(value):
                totals[key] += value
            else:
                unknown[key] += 1
                if key == "cost_usd" and _known_number(usage.get("known_cost_usd")):
                    totals[key] += usage["known_cost_usd"]
        elapsed += record.get("attempt_elapsed_seconds", 0.0)
        score = record["score"]
        smoke[score["smoke"]["status"]] += 1
        human[score["human"]["status"]] += 1
        structural[score["structural"]["status"]] += 1
    return {
        "attempts": len(records), "run_status_counts": dict(statuses),
        "task_completed_count": completed, "failed_runs": statuses["failed"],
        "completion_count_interpretation": "Declared task completion, excluding scope/form rejection or incomplete evaluation, delivery or configured review; not human-adjudicated adequacy.",
        "evaluation_completion_status_counts": dict(evaluation_states),
        "usage_known_totals": totals, "usage_unknown_run_counts": unknown,
        "monetary_cost_complete": unknown["cost_usd"] == 0,
        "runner_elapsed_seconds": elapsed, "structural_status_counts": dict(structural),
        "smoke_status_counts": dict(smoke), "human_review_status_counts": dict(human),
        "automatic_substantive_accuracy": None,
        "interpretation": "Structural and categorical smoke results are not substantive accuracy estimates.",
    }


def run_experiments(cases: Sequence[ExperimentCase], run_case: Callable[..., Any], *,
                    arms: Sequence[str] = ARMS, modes: Sequence[str] = MODES,
                    repetitions: int = 1, manifest: Mapping[str, Any] | None = None,
                    order_seed: int = 0, output_dir: str | Path | None = None) -> dict[str, Any]:
    """Execute an interleaved family-level development experiment without oracle access."""
    cases = deepcopy(list(cases))
    if not cases or len({c.case_id for c in cases}) != len(cases):
        raise ValueError("Provide nonempty cases with unique case IDs.")
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 1:
        raise ValueError("repetitions must be a positive integer.")
    if not arms or len(set(arms)) != len(arms) or not set(arms) <= set(ARMS):
        raise ValueError("Unknown or repeated arm.")
    if not modes or len(set(modes)) != len(modes) or not set(modes) <= set(MODES):
        raise ValueError("Unknown or repeated mode.")
    family_splits: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        validate_public_case(case.public_case)
        family_splits[case.family_id].add(case.split)
    if any(len(splits) != 1 for splits in family_splits.values()):
        raise ValueError("All variants of a family must remain in the same split.")
    configuration = deepcopy(dict(manifest or {}))
    jobs = [(case, arm, mode, repeat) for case in cases for repeat in range(repetitions)
            for mode in modes for arm in arms]
    random.Random(order_seed).shuffle(jobs)
    records: list[dict[str, Any]] = []
    destination = Path(output_dir) if output_dir is not None else None
    if destination:
        destination.mkdir(parents=True, exist_ok=True)
        if (destination / "runs.jsonl").exists():
            raise FileExistsError("Use a new experiment directory; existing runs will not be overwritten.")

    for index, (case, arm, mode, repeat) in enumerate(jobs):
        job_id = f"job_{index:06d}"
        run_manifest = _run_manifest(case, arm, mode, repeat, configuration, order_seed)
        started = perf_counter()
        try:
            # A fresh copy prevents one arm or repetition from changing another's evidence.
            raw_result = run_case(deepcopy(dict(case.public_case)), arm=arm, mode=mode)
            try:
                result = _result_dict(raw_result)
            except Exception as error:
                usage = raw_result.get("usage") if isinstance(raw_result, Mapping) else None
                raise RunExecutionError(str(error), usage=usage) from error
            if result.get("status") not in {"complete", "partial", "failed"}:
                raise RunExecutionError("Invalid or missing run status.", partial_result=result)
            if result.get("arm") != arm or result.get("mode") != mode:
                raise RunExecutionError("Returned arm/mode differs from scheduled condition.", partial_result=result)
            if result.get("question_id") != case.question_id:
                raise RunExecutionError("Returned question differs from active question.", partial_result=result)
        except Exception as error:
            result = _failed_result(error, case, arm, mode, perf_counter() - started)
        elapsed = perf_counter() - started
        result.setdefault("run_id", job_id)
        # Keep mutation overlays and hidden-world context with the baseline
        # specification for human review. None is sent to the worker callback.
        score = score_run(result, case.public_case, answer_spec=case.oracle,
                          smoke_expectation=case.smoke_expectation,
                          human_adjudication=case.human_adjudication)
        record = {"job_id": job_id, "manifest": run_manifest, "result": result,
                  "score": score, "attempt_elapsed_seconds": elapsed}
        records.append(record)
        if destination:
            with (destination / "runs.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        m = record["manifest"]
        grouped[m["family_id"], m["arm"], m["mode"]].append(record)
    family_summaries = [
        {"family_id": family, "arm": arm, "mode": mode, **summarize_runs(group)}
        for (family, arm, mode), group in sorted(grouped.items())
    ]
    report = {
        "protocol_version": PROTOCOL_VERSION, "configuration": configuration,
        "order_seed": order_seed, "arms": list(arms), "modes": list(modes),
        "repetitions": repetitions, "family_splits": {k: next(iter(v)) for k, v in family_splits.items()},
        "summary": summarize_runs(records), "family_summaries": family_summaries, "runs": records,
        "limitations": ["Repeated runs and question variants are not independent scenario families.",
                        "No substantive human outcome is inferred from a structural or smoke pass.",
                        "Missing model or cost metadata remains explicitly incomplete."],
    }
    if destination:
        (destination / "experiment.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report
