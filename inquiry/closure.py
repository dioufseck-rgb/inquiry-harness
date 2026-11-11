"""Deterministic distinction between component acceptance and question closure."""
from __future__ import annotations

from .argument.graph import ArgumentGraph, Claim
from .argument.evaluate import Evaluation
from .argument.scope import answers_scope, sub_scope


def answer_scope(claim: Claim) -> str:
    scope = getattr(claim, "scope", None)
    if scope is not None:
        return scope.summary()
    return "; ".join(claim.target.get(k, "") for k in ("population", "outcome", "horizon")
                     if claim.target.get(k)) or "issue scope"


def whole_question_answer(g: ArgumentGraph, ev: Evaluation) -> Claim | None:
    issue = g.issue(g.main_issue_id) if g.main_issue_id else None
    for c in g.claims_for_issue(g.main_issue_id):
        if ev.status(c.id) != "in":
            continue
        composition = any(a.scheme == "composition" and not a.withdrawn and ev.labels.get(a.id) == "in"
                          for a in g.arguments_for(c.id))
        if composition and c.critique_round <= 0:
            continue  # no unreviewed composition closes a question
        if issue and answers_scope(c.scope, issue.scope) and c.answers_issue:
            if issue.question_type != "conceptual" and (c.kind == "deflationary" or c.target.get("evidence_status") in ("recommended", "reported")):
                continue
            return c
    # A reviewed composition may close at its stated narrower scope, with a gap.
    for c in g.claims_for_issue(g.main_issue_id):
        if (issue and ev.status(c.id) == "in" and c.critique_round > 0 and sub_scope(c.scope, issue.scope)
                and any(a.scheme == "composition" and not a.withdrawn and ev.labels.get(a.id) == "in"
                        for a in g.arguments_for(c.id))):
            return c
    return None


def accepted_components(g: ArgumentGraph, ev: Evaluation) -> list[Claim]:
    answer = whole_question_answer(g, ev)
    return [c for c in g.live_claims() if ev.status(c.id) == "in" and c != answer]
