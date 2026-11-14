"""Authored hardship benchmark expectations, outside generic inquiry scoring."""

from __future__ import annotations

from typing import Any


SMOKE_ORACLE_VERSION = "hardship-epistemic-smoke-0.3"


def hardship_smoke_expectation(question_id: str, variant_id: str | None = None) -> dict[str, Any]:
    """Return epistemic regression categories, never human outcome gold.

    Application actions and letters are not scored by the inquiry service. The
    old action-based categories remain available only in ``adapters.history``.
    """
    variant = variant_id or "baseline"
    valid_variants = {"baseline", *(f"mutation_{i:03d}" for i in range(1, 7))}
    if question_id not in {f"question_{i:03d}" for i in range(1, 7)}:
        raise ValueError(f"Unknown hardship question: {question_id}")
    if variant not in valid_variants:
        raise ValueError(f"Unknown hardship variant: {variant}")
    statuses = {
        "question_001": ["reported"],
        "question_002": ["established"],
        "question_003": ["not_established", "conditional"],
        "question_004": ["established"],
        "question_005": ["not_established", "conditional"],
        "question_006": ["not_established", "conditional"],
    }
    conditions: list[str] = []
    if question_id == "question_002" and variant == "mutation_004":
        statuses[question_id] = ["not_established", "conditional"]
    if question_id == "question_003" and variant == "mutation_003":
        statuses[question_id] = ["established"]
    if question_id == "question_004" and variant in {"mutation_002", "mutation_005"}:
        conditions = (["impact_description", "event_date"] if variant == "mutation_002"
                      else ["prior_payment_declaration"])
    return {
        "oracle_version": SMOKE_ORACLE_VERSION,
        "author": "model_authored", "human_adjudicated": False,
        "kind": "categorical_regression_assertion",
        "question_id": question_id, "variant_id": variant,
        "allowed_target_statuses": statuses[question_id],
        "required_condition_ids": conditions, "inquiry_completed": True,
        "target_scope_answered": True,
        "limitation": "Passing these categories is not a substantive outcome score or warrant judgment.",
    }


def hardship_smoke_matrix() -> list[dict[str, Any]]:
    return [hardship_smoke_expectation(f"question_{q:03d}", variant)
            for q in range(1, 7)
            for variant in ["baseline", *(f"mutation_{i:03d}" for i in range(1, 7))]]
