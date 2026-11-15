"""Premise check: the propositions an action rests on, triaged and examined.

A calling agent declares the premises a contemplated action rests on. Each
premise is triaged; those routed to inquiry, or marked ``examine: always``,
are examined as ordinary inquiries with their own evidence environment,
workers, ledger and record. The result is per-premise: no single go or
no-go value is returned. The caller combines the per-premise results; the
host decides which actions require a premise check at all.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any, Callable, Mapping

from .contracts import InquiryValidationError, _snapshot, canonical_json, validate_inquiry_request
from .runtime import Budget

PREMISE_SET_SCHEMA_VERSION = "premise-set-request/v1"
EXAMINE_MODES = ("auto", "always")
NOT_EXAMINED_REASONS = ("routed", "budget")
LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2}
SET_USAGE_FIELDS = ("model_calls", "input_tokens", "output_tokens", "tool_calls", "failed_calls", "elapsed_seconds")


def validate_premise_set(value: Any, *, max_premises: int) -> dict[str, Any]:
    """Validate the whole set before any worker exists: context, corpus, premises and action context.

    Each premise is a question object that must carry stakes, may carry
    examine ("auto" or "always"), and must have an id unique in the set. Each
    is also validated as a complete single-question request against the same
    corpus, so a bad premise rejects the whole set.
    """
    request = _snapshot(value, "request")
    if not isinstance(request, dict):
        raise InquiryValidationError("request: expected an object")
    required, optional = {"shared_context", "corpus", "premises"}, {"action_context"}
    missing, extra = required - request.keys(), request.keys() - required - optional
    if missing or extra:
        raise InquiryValidationError(f"request: missing={sorted(missing)}, unknown fields={sorted(extra)}")
    action_context = request.get("action_context")
    if action_context is not None and (not isinstance(action_context, str) or not action_context.strip()):
        raise InquiryValidationError("request.action_context: expected a nonempty string when present")
    premises = request["premises"]
    if not isinstance(premises, list) or not premises:
        raise InquiryValidationError("request.premises: expected a nonempty array of question objects")
    if len(premises) > max_premises:
        raise InquiryValidationError(f"request.premises: at most {max_premises} premises per check; got {len(premises)}")
    seen: set[str] = set()
    questions: list[dict[str, Any]] = []
    examine: list[str] = []
    for index, premise in enumerate(premises):
        at = f"request.premises[{index}]"
        if not isinstance(premise, dict):
            raise InquiryValidationError(f"{at}: expected a question object")
        mode = premise.get("examine", "auto")
        if mode not in EXAMINE_MODES:
            raise InquiryValidationError(f"{at}.examine: expected one of {list(EXAMINE_MODES)}")
        question = {key: item for key, item in premise.items() if key != "examine"}
        if "stakes" not in question:
            raise InquiryValidationError(f"{at}: every premise must declare stakes")
        single = validate_inquiry_request({"shared_context": request["shared_context"], "corpus": request["corpus"],
                                           "question": question})
        premise_id = single["question"]["id"]
        if premise_id in seen:
            raise InquiryValidationError(f"{at}: duplicate premise id {premise_id!r}")
        seen.add(premise_id)
        questions.append(single)
        examine.append(mode)
    canonical_json(request).encode("utf-8")
    return {"shared_context": request["shared_context"], "corpus": request["corpus"],
            "action_context": action_context, "questions": questions, "examine": examine}


def premise_set_json_schema() -> dict[str, Any]:
    """Structural description of the premise-set request; relational checks are in the validator."""
    from .contracts import request_json_schema
    single = request_json_schema()
    question = deepcopy(single["properties"]["question"])
    question["properties"]["examine"] = {"type": "string", "enum": list(EXAMINE_MODES)}
    question["required"] = sorted(set(question["required"]) | {"stakes"})
    return {
        "$schema": single["$schema"], "title": "PremiseSetRequest", "description": PREMISE_SET_SCHEMA_VERSION,
        "type": "object", "additionalProperties": False,
        "required": ["shared_context", "corpus", "premises"],
        "properties": {
            "shared_context": single["properties"]["shared_context"],
            "corpus": single["properties"]["corpus"],
            "premises": {"type": "array", "minItems": 1, "items": question},
            "action_context": {"type": "string", "minLength": 1},
        },
        "$defs": single["$defs"],
    }


def examination_order(questions: list[dict[str, Any]], selected: list[int]) -> list[int]:
    """Examined premises by stakes level, high first, then request order."""
    return sorted(selected, key=lambda index: (LEVEL_ORDER[questions[index]["question"]["stakes"]["level"]], index))


def remaining_budget(total: Budget, spent: Mapping[str, Any]) -> dict[str, Any]:
    """What a set budget still allows after recorded usage; unknown cost counts as its known part."""
    cost_spent = spent.get("cost_usd")
    if cost_spent is None:
        cost_spent = spent.get("known_cost_usd", 0.0) or 0.0
    return {
        "max_model_calls": max(0, total.max_model_calls - int(spent.get("model_calls", 0))),
        "max_tool_calls": max(0, total.max_tool_calls - int(spent.get("tool_calls", 0))),
        "max_total_tokens": max(0, total.max_total_tokens - int(spent.get("input_tokens", 0)) - int(spent.get("output_tokens", 0))),
        "max_output_tokens": total.max_output_tokens,
        "timeout_seconds": max(0.0, total.timeout_seconds - float(spent.get("elapsed_seconds", 0.0))),
        "max_consecutive_errors": total.max_consecutive_errors,
        "max_critique_calls": total.max_critique_calls,
        "max_cost_usd": None if total.max_cost_usd is None else max(0.0, total.max_cost_usd - float(cost_spent)),
    }


def can_fund(remaining: Mapping[str, Any], low: Budget) -> bool:
    """Can the remainder fund the low tier? Every field must still reach the low value."""
    low_values = asdict(low)
    for key, floor in low_values.items():
        value = remaining[key]
        if key == "max_cost_usd":
            if floor is not None and (value is None or value < floor):
                return False
            continue
        if value < floor:
            return False
    return True


def premise_budget(tier: Budget, remaining: Mapping[str, Any]) -> Budget:
    """The smaller of the premise's tier budget and what remains of the set budget, field by field."""
    values = {}
    for key, tier_value in asdict(tier).items():
        rest = remaining[key]
        if key == "max_cost_usd":
            values[key] = tier_value if rest is None else (rest if tier_value is None else min(tier_value, rest))
        elif key in ("max_output_tokens", "max_consecutive_errors", "max_critique_calls"):
            values[key] = tier_value
        else:
            values[key] = min(tier_value, rest)
    # a Budget needs at least one error allowance and one output token; the floors are enforced by Budget itself
    return Budget(**values)


def add_usage(total: dict[str, Any], usage: Mapping[str, Any]) -> None:
    for key in SET_USAGE_FIELDS:
        total[key] = total.get(key, 0) + usage.get(key, 0)
    cost = usage.get("cost_usd")
    if cost is None:
        total["cost_complete"] = False
        total["known_cost_usd"] = total.get("known_cost_usd", 0.0) + float(usage.get("known_cost_usd", 0.0) or 0.0)
    else:
        total["cost_usd"] = total.get("cost_usd", 0.0) + float(cost)
        total["known_cost_usd"] = total.get("known_cost_usd", 0.0) + float(cost)


def premise_summary(premise_id: str, triage: Mapping[str, Any], examine: str, *,
                    examined: bool, not_examined_reason: str | None, inquiry: Mapping[str, Any] | None) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "premise_id": premise_id, "examine": examine, "triage": deepcopy(dict(triage)),
        "examined": examined, "not_examined_reason": not_examined_reason,
    }
    if inquiry is not None:
        response = inquiry.get("response", {})
        target = next((f for f in response.get("findings", []) if isinstance(f, dict)
                       and f.get("claim_id") == response.get("target_claim_id")), None)
        summary.update({
            "inquiry_id": inquiry["inquiry_id"],
            "execution_status": inquiry["execution_status"],
            "stop_reason": inquiry["stop_reason"],
            "finding_status": target.get("status") if target else None,
            "meets_declared_standing": response.get("meets_declared_standing"),
            "resolution_state": response.get("resolution_state"),
            "information_needs": deepcopy(response.get("information_needs", [])),
            "record_ref": inquiry.get("record_ref"),
        })
    return summary


__all__ = ["EXAMINE_MODES", "NOT_EXAMINED_REASONS", "PREMISE_SET_SCHEMA_VERSION", "add_usage", "can_fund",
           "examination_order", "premise_budget", "premise_set_json_schema", "premise_summary",
           "remaining_budget", "validate_premise_set"]
