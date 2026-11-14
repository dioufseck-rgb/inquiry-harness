"""An example application consumer of an epistemic inquiry result.

This synthetic development adapter prepares a reviewable intake letter. It is
not imported by the service, does not contact anyone, and does not grant award
authority. Its workflow suggestion and draft remain separate application data.
"""

from __future__ import annotations

from typing import Any, Mapping


def prepare_intake_draft(public_case: Mapping[str, Any], inquiry_result: Mapping[str, Any]) -> dict[str, Any]:
    """Consume a completed scoped assessment without changing its record."""
    question = public_case.get("question", {})
    response = inquiry_result.get("response", {})
    target_id = response.get("target_claim_id")
    targets = [item for item in response.get("findings", []) if item.get("claim_id") == target_id]
    if (question.get("scope", {}).get("stage") != "intake"
            or inquiry_result.get("question_id") != question.get("id")
            or response.get("inquiry_completed") is not True
            or response.get("target_scope_answered") is not True
            or response.get("target_form_answered") is not True
            or len(targets) != 1 or targets[0].get("status") != "established"):
        raise ValueError("A completed, scoped intake assessment is required before preparing this application draft.")
    needs = response.get("information_needs", [])
    if needs:
        draft = ("Thank you for your application. The intake assessment identifies the following "
                 "missing information: " + " ".join(item["what_would_resolve"] for item in needs)
                 + " Your own signed statement is accepted for the policy's stated intake purpose. "
                 "Final eligibility requires a separate review.")
    else:
        draft = ("Thank you for your complete signed statement. It satisfies the policy's intake "
                 "impact-evidence requirement. Your application can proceed to the separate "
                 "final-eligibility review; no award decision has been made.")
    return {
        "application": "fictional_hardship_intake",
        "inquiry_run_id": inquiry_result.get("run_id"),
        "suggested_action": "request_information" if needs else "advance_intake",
        "draft": draft,
        "human_review_required": True,
        "limitation": "Scripted development consumer; the service's epistemic completion is not application approval.",
    }
