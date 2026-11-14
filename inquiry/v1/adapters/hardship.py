"""The fictional hardship benchmark's explicit service boundary.

The authoring packet is intentionally left unchanged. Only its already-public
projection may cross this adapter, and the resulting request contains no oracle
or application-output contract. A policy question is still a legitimate inquiry;
preparing a letter or making an intake decision remains the caller's work.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from ..packets import current_versions, validate_public_case


TARGET_FORMS = {
    "source_reports(P)": {"kind": "attribution", "form": "source_reports"},
    "scoped_event_finding": {"kind": "substantive", "form": "assertion"},
    "examined_case_specific_causal_finding": {"kind": "causal", "form": "causal"},
    "policy_grounded_next_response": {"kind": "policy", "form": "rule_consequence"},
    "final_eligibility_assessment": {"kind": "policy", "form": "rule_consequence"},
    "universal_population_claim": {"kind": "substantive", "form": "universal"},
}


def to_inquiry_request(public_case: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a ``Packet.public`` copy into an explicit epistemic request.

    This function never loads a packet, selects a hidden mutation, or reads an
    oracle. Validation rejects an authoring packet or private annotations before
    translation. The original public projection is not mutated.
    """
    public = deepcopy(dict(public_case))
    validate_public_case(public)
    question = public["question"]
    legacy_profile = question["profile"]
    product = legacy_profile["required_form"]
    if product not in TARGET_FORMS:
        raise ValueError(f"Unsupported hardship benchmark product: {product}")
    question["target"] = deepcopy(TARGET_FORMS[product])
    question["profile"] = {
        "id": legacy_profile["id"],
        "version": legacy_profile["version"],
        "authority": legacy_profile.get("authority", "Caller-supplied fictional hardship benchmark profile."),
        "requirements": deepcopy(legacy_profile["requirements"]),
        "kernel": deepcopy(legacy_profile.get("kernel", {})),
    }
    if product == "policy_grounded_next_response":
        question["question"] = (
            "Under the currently bound policy, what does the supplied application "
            "establish about the intake requirements, and which required information is missing?"
        )
        question["intended_use"] = (
            "Provide an epistemic assessment of the policy's intake requirements "
            "and their evidential satisfaction for a separate application workflow."
        )
        requirement_translation = {
            "Identify any genuinely missing intake information and distinguish it from later eligibility records.":
                "Identify genuinely missing intake information and distinguish it from later eligibility records.",
            "Complete the response task without inventing independent personal-impact proof requirements.":
                "Assess the record without adding independent personal-impact proof requirements.",
        }
        question["profile"]["requirements"] = [
            requirement_translation.get(requirement, requirement)
            for requirement in legacy_profile["requirements"]
        ]
    elif product == "final_eligibility_assessment":
        question["intended_use"] = "Assess what the supplied record establishes about final-stage eligibility conditions."
    public["corpus"] = {
        "documents": public["corpus"]["documents"],
        "current_versions": current_versions(public["corpus"]),
    }
    # This field is the application's original execution authorization, not a
    # warrant profile. Narrow it at the service boundary to the actual request.
    public["shared_context"]["authority"] = "Epistemic analysis of the supplied fictional records only."
    return public


def fixture_form(question: Mapping[str, Any]) -> str:
    """Route the explicit scripted fixture by target shape and policy stage."""
    target = question.get("target", {})
    if target == {"kind": "policy", "form": "rule_consequence"}:
        stage = question.get("scope", {}).get("stage")
        if stage == "intake":
            return "policy_grounded_next_response"
        if stage == "final_eligibility":
            return "final_eligibility_assessment"
    for product, shape in TARGET_FORMS.items():
        if shape == target and shape["kind"] != "policy":
            return product
    raise ValueError("The hardship demo supports only its declared benchmark target shapes and stages.")
