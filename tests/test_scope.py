import json
from pathlib import Path

from inquiry.argument.graph import ArgumentGraph, Claim, Issue, Scope, sub_scope
from inquiry.argument.scope import answers_scope
from inquiry.specificity import claim_specificity_errors


def test_scope_equality_narrowing_and_direction():
    wide = Scope(population="adults 60+", outcome="net harm", comparison="aspirin vs placebo", period="follow-up")
    narrow = wide.model_copy(update={"population": "adults 70+", "relation": "increases"})
    assert sub_scope(narrow, wide) and not sub_scope(wide, narrow)
    assert answers_scope(wide, wide) and not answers_scope(narrow, wide)
    assert not sub_scope(narrow.model_copy(update={"outcome": "bleeding"}), wide)
    assert not sub_scope(narrow, wide.model_copy(update={"relation": "reduces"}))
    assert not sub_scope(narrow.model_copy(update={"population": "other country adults 70+"}),
                         wide.model_copy(update={"population": "UK adults 60+"}))


def test_explicit_narrowing_is_bound_to_parent():
    wide = Scope(population="trial participants", period="source follow-up", outcome="harm")
    narrow = Scope(population="trial participants at high risk", period="4.7 years", outcome="harm",
                   narrower_than=["period"], parent_scope={"period": "source follow-up"})
    assert sub_scope(narrow, wide)
    assert not sub_scope(narrow, wide.model_copy(update={"period": "10 years"}))


def test_answerhood_recomputed_and_inherited():
    g = ArgumentGraph()
    q = g.add_issue("Q", scope=Scope(population="adults 60+", outcome="harm", period="5 years"))
    c = g.add_claim("Finding", issue_id=q.id)
    assert c.answers_issue and c.scope == q.scope
    c.scope.population = "adults 70+"
    c.answers_issue = True
    loaded = ArgumentGraph.model_validate(g.model_dump())
    assert not loaded.claim(c.id).answers_issue


def test_field_granularity_and_unrequested_dose():
    issue = Scope(population="adults 70+", outcome="harm", period="5 years")
    scope = issue.model_copy(update={"population": "adults 60+"})
    errors = claim_specificity_errors("100 mg daily reduces harm", "direction", scope=scope, issue_scope=issue)
    assert any("population" in e for e in errors) and any("dose" in e for e in errors)


def test_saved_scope_migration_keeps_energy_components():
    from inquiry.state import Inquiry
    raw = json.loads(Path("experiments/E6-generalisation/energy/inquiry.json").read_text(encoding="utf-8"))
    inq = Inquiry.model_validate(raw)
    assert all(not c.answers_issue for c in inq.main_claims())
