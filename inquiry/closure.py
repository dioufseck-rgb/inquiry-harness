"""Deterministic distinction between component acceptance and question closure."""
from __future__ import annotations

from .argument.graph import ArgumentGraph, Claim
from .argument.evaluate import Evaluation
from .argument.scope import answers_scope


def answer_scope(claim: Claim) -> str:
    scope = getattr(claim, "scope", None)
    if scope is not None:
        return scope.summary()
    return "; ".join(claim.target.get(k, "") for k in ("population", "outcome", "horizon")
                     if claim.target.get(k)) or "issue scope"


def whole_question_answer(g: ArgumentGraph, ev: Evaluation) -> Claim | None:
    issue = g.issue(g.main_issue_id) if g.main_issue_id else None
    for c in g.claims_for_issue(g.main_issue_id):
        if ev.status(c.id) != "in" or not c.answers_issue:
            continue
        if issue and not answers_scope(c.scope, issue.scope):
            continue
        # Legacy graphs have no scope fields. A record or definition does not
        # answer an empirical/causal question merely by sharing its issue id.
        if issue and issue.question_type != "conceptual" and (
                c.kind == "deflationary" or c.target.get("evidence_status") in ("recommended", "reported")):
            continue
        return c
    return None


def accepted_components(g: ArgumentGraph, ev: Evaluation) -> list[Claim]:
    answer = whole_question_answer(g, ev)
    return [c for c in g.live_claims() if ev.status(c.id) == "in" and c != answer]
