"""Counterexamples for the small deterministic v1 argument fragment.

The fake evidence boundary isolates the kernel from acquisition. It implements
the same current-version and per-worker exact-exposure protocol as the real
environment; environment integration has separate tests.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from inquiry.v1.kernel import evaluate
from inquiry.v1.models import (
    Argument, Attack, Claim, Condition, Evidence, InquiryGraph, Profile, Scope,
)


class EvidenceBoundary:
    def __init__(self):
        self.current_versions = {}
        self.source_lookup = {}
        self.exposures = set()
        self.calls = []

    def add(self, source_id, text, *, version="1", origins=("origin-1",), expose=True):
        self.current_versions[source_id] = version
        self.source_lookup[(source_id, version)] = {
            "root_origin_ids": list(origins), "reading_blocks": {"p1": text}
        }
        if expose:
            self.exposures.add(("proposer", source_id, version, "p1", text))

    def verify_quote(self, worker_id, source_id, version, quote, locator=None):
        self.calls.append((worker_id, source_id, version, quote, locator))
        text = self.source_lookup.get((source_id, version), {}).get("reading_blocks", {}).get(locator, "")
        exposed = any(worker == worker_id and sid == source_id and ver == version and loc == locator and quote in segment
                      for worker, sid, ver, loc, segment in self.exposures)
        valid = bool(quote and quote in text and exposed)
        return SimpleNamespace(valid=valid, reason="verified" if valid else "not exposed or not in source",
                               is_current=self.current_versions.get(source_id) == version)


def example():
    env = EvidenceBoundary()
    env.add("source-1", "The workshop was closed on 4 April.")
    env.add("source-2", "The workshop remained open on 4 April.", origins=("origin-2",))
    graph = InquiryGraph(id="case", revision=3)
    graph.evidence["e1"] = Evidence(id="e1", source_id="source-1", source_version="1",
                                     locator="p1", quote="The workshop was closed on 4 April.")
    graph.evidence["e2"] = Evidence(id="e2", source_id="source-2", source_version="1",
                                     locator="p1", quote="The workshop remained open on 4 April.")
    profile = Profile(id="reviewed", authority="test-authority")
    return graph, profile, env


def claim(graph, cid, *, kind="substantive", form="assertion", scope=None, conditions=()):
    obj = Claim(id=cid, text=f"Proposition {cid}", kind=kind, form=form,
                scope=scope or Scope({"subject": "site-1", "date": "2026-04-04"}),
                conditions=list(conditions), issue_id="issue-1")
    graph.claims[cid] = obj
    return obj


def condition(graph, cid, *, evidence=("e1",), status="met", **kwargs):
    obj = Condition(id=cid, text=f"Assessment {cid}", evidence_ids=list(evidence),
                    status=status, performer="analyst", performer_kind="model", **kwargs)
    graph.conditions[cid] = obj
    return obj


def argument(graph, aid, cid, premises=("e1",), *, pattern="document_record", evidence=("e1",)):
    required = {
        "document_record": ["record_warrant", "applicability"],
        "attribution": ["attribution", "applicability"],
        "rule_application": ["authority", "antecedents", "inference_validity", "applicability"],
        "conjunction": ["joint_rule", "inference_validity", "applicability"],
        "bounded_absence": ["coverage", "detection", "absence_strength", "inference_validity", "applicability"],
        "process_trace": ["trace_links", "alternatives", "inference_validity", "applicability"],
    }[pattern]
    conditions = {}
    for key in required:
        condition(graph, f"{aid}-{key}", evidence=evidence)
        conditions[key] = f"{aid}-{key}"
    obj = Argument(id=aid, claim_id=cid, pattern=pattern, premise_ids=list(premises),
                   conditions=conditions, scope=graph.claims[cid].scope)
    graph.arguments[aid] = obj
    return obj


def run(graph, profile, env, **kwargs):
    return evaluate(graph, profile, evidence_context=env, **kwargs)


def codes(result):
    return {d["code"] for d in result.diagnostics}


def test_a_fetched_source_does_not_make_its_quote_exposed():
    graph, profile, env = example()
    claim(graph, "c")
    argument(graph, "a", "c")
    env.exposures.clear()
    result = run(graph, profile, env)
    assert result.evaluation_status == "complete"
    assert result.findings["c"].status == "not_established"
    assert "quote_not_verified" in codes(result)
    assert env.calls  # The kernel did not substitute lookup membership.


def test_exposure_of_a_different_worker_or_passage_is_insufficient():
    graph, profile, env = example()
    claim(graph, "c")
    argument(graph, "a", "c")
    graph.evidence["e1"].worker_id = "critic"
    assert run(graph, profile, env).findings["c"].status == "not_established"
    graph.evidence["e1"].worker_id = "proposer"
    graph.evidence["e1"].quote = "The workshop never closed."
    assert run(graph, profile, env).findings["c"].status == "not_established"


def test_attribution_cannot_be_promoted_by_reusing_the_same_pattern():
    graph, profile, env = example()
    claim(graph, "report", kind="attribution", form="source_reports")
    argument(graph, "a-report", "report", pattern="attribution")
    claim(graph, "world")
    argument(graph, "a-world", "world", ("report",), pattern="attribution")
    result = run(graph, profile, env)
    assert result.findings["report"].status == "reported"
    assert result.findings["world"].status == "not_established"
    assert "pattern_claim_form_mismatch" in codes(result)


def test_missing_or_reused_required_conditions_are_not_completed_assessments():
    graph, profile, env = example()
    claim(graph, "c")
    a = argument(graph, "a", "c")
    del a.conditions["applicability"]
    result = run(graph, profile, env)
    assert result.findings["c"].status == "not_established"
    assert "required_conditions_missing" in codes(result)
    a.conditions["applicability"] = a.conditions["record_warrant"]
    result = run(graph, profile, env)
    assert result.findings["c"].status == "not_established"
    assert "required_conditions_not_distinct" in codes(result)


def test_reference_failures_are_local_and_drafts_do_not_abort_the_run():
    graph, profile, env = example()
    claim(graph, "sound")
    argument(graph, "a-sound", "sound")
    claim(graph, "draft")
    graph.arguments["a-draft"] = Argument(id="a-draft", claim_id="draft", pattern="invented_rule",
                                          premise_ids=["missing"], scope=graph.claims["draft"].scope)
    result = run(graph, profile, env)
    assert result.evaluation_status == "complete"
    assert result.findings["sound"].status == "established"
    assert result.findings["draft"].status == "not_established"
    assert "unsupported_pattern" in codes(result)


def test_a_support_cycle_cannot_bootstrap_but_an_external_foundation_can_support_it():
    graph, profile, env = example()
    claim(graph, "a")
    claim(graph, "b")
    argument(graph, "a-from-b", "a", ("b",))
    argument(graph, "b-from-a", "b", ("a",))
    result = run(graph, profile, env)
    assert {f.status for f in result.findings.values()} == {"not_established"}
    assert "unsupported_support_cycle" in codes(result)
    argument(graph, "foundation", "a")
    result = run(graph, profile, env)
    assert result.findings["a"].status == result.findings["b"].status == "established"


def test_scope_and_units_are_never_silently_transferred():
    graph, profile, env = example()
    claim(graph, "narrow", scope=Scope({"population": "ward-a", "unit": "hours"}))
    argument(graph, "a-narrow", "narrow")
    claim(graph, "broad", scope=Scope({"population": "whole-region", "unit": "days"}))
    argument(graph, "a-broad", "broad", ("narrow",))
    result = run(graph, profile, env)
    assert result.findings["narrow"].status == "established"
    assert result.findings["broad"].status == "not_established"
    assert "premise_scope_transfer_unsupported" in codes(result)


def test_an_assumption_remains_conditional_through_a_chain():
    graph, profile, env = example()
    profile.allow_conditional = True
    condition(graph, "input", evidence=(), status="assumed",
              assumption_kind="scenario_input", context_id="scenario-1")
    claim(graph, "component", conditions=["input"])
    argument(graph, "a-component", "component")
    claim(graph, "conclusion")
    argument(graph, "a-conclusion", "conclusion", ("component",))
    result = run(graph, profile, env)
    assert result.findings["conclusion"].status == "conditional"
    assert result.findings["conclusion"].assumption_contexts == ["scenario-1"]
    assert "input" in result.findings["conclusion"].open_conditions
    profile.allow_conditional = False
    assert run(graph, profile, env).findings["conclusion"].status == "not_established"


def test_open_premise_conditions_propagate_as_gaps_without_becoming_assumptions():
    graph, profile, env = example()
    condition(graph, "missing-input", evidence=(), status="open")
    claim(graph, "component", conditions=["missing-input"])
    argument(graph, "a-component", "component")
    claim(graph, "conclusion")
    argument(graph, "a-conclusion", "conclusion", ("component",))
    profile.allow_conditional = True
    result = run(graph, profile, env)
    assert result.findings["conclusion"].status == "not_established"
    assert "missing-input" in result.findings["conclusion"].open_conditions


def test_conditional_permission_never_waives_the_joint_rule():
    graph, profile, env = example()
    profile.allow_conditional = True
    for cid in ("a", "b"):
        claim(graph, cid)
        argument(graph, f"arg-{cid}", cid)
    c = claim(graph, "joint", kind="conjunction", form="conjunction")
    c.components = ["a", "b"]
    a = argument(graph, "arg-joint", "joint", ("a", "b"), pattern="conjunction")
    guard = graph.conditions[a.conditions["joint_rule"]]
    guard.status = "assumed"
    guard.assumption_kind = "conditional_premise"
    guard.context_id = "scenario-1"
    result = run(graph, profile, env)
    assert result.findings["joint"].status == "not_established"
    assert "assumption_not_permitted" in codes(result)


def test_conjunction_preserves_member_forms_and_rejects_incompatible_scenarios():
    graph, profile, env = example()
    profile.allow_conditional = True
    for cid, ctx in (("a", "scenario-a"), ("b", "scenario-b")):
        condition(graph, f"input-{cid}", evidence=(), status="assumed",
                  assumption_kind="scenario_input", context_id=ctx)
        claim(graph, cid, kind="attribution", form="source_reports", conditions=[f"input-{cid}"])
        argument(graph, f"arg-{cid}", cid, pattern="attribution")
    c = claim(graph, "joint", kind="conjunction", form="conjunction")
    c.components = ["a", "b"]
    argument(graph, "arg-joint", "joint", ("a", "b"), pattern="conjunction")
    result = run(graph, profile, env)
    assert result.findings["joint"].status == "not_established"
    assert "assumption_contexts_not_aligned" in codes(result)
    graph.conditions["input-b"].context_id = "scenario-a"
    result = run(graph, profile, env)
    assert result.findings["joint"].status == "conditional"
    assert result.findings["joint"].components == ["a", "b"]
    assert all(result.findings[cid].form == "source_reports" for cid in ("a", "b"))


def test_source_relays_do_not_manufacture_independent_origins_through_claims():
    graph, profile, env = example()
    env.source_lookup[("source-2", "1")]["root_origin_ids"] = ["origin-1"]
    graph.evidence["e2"].origin_ids = ["invented-origin"]
    for cid, eid in (("a", "e1"), ("b", "e2")):
        claim(graph, cid)
        argument(graph, f"arg-{cid}", cid, (eid,), evidence=(eid,))
    c = claim(graph, "joint", kind="conjunction", form="conjunction")
    c.components = ["a", "b"]
    argument(graph, "arg-joint", "joint", ("a", "b"), pattern="conjunction")
    profile.min_origins = 2
    profile.premise_min_origins = 1  # Explicit, separate premise-use requirement.
    result = run(graph, profile, env)
    assert result.findings["joint"].status == "not_established"
    assert result.findings["joint"].support_origins == ["origin-1"]
    assert "proposed_origin_mismatch" in codes(result)
    env.source_lookup[("source-2", "1")]["root_origin_ids"] = ["origin-2"]
    result = run(graph, profile, env)
    assert result.findings["joint"].status == "established"
    assert result.findings["joint"].support_origins == ["origin-1", "origin-2"]


def test_a_premise_must_meet_its_declared_use_profile_without_global_label_iteration():
    graph, profile, env = example()
    claim(graph, "component")
    argument(graph, "a-component", "component")
    claim(graph, "parent")
    argument(graph, "a-parent", "parent", ("component", "e2"))
    profile.min_origins = 2
    result = run(graph, profile, env)
    assert result.findings["parent"].status == "not_established"
    assert "premise_use_profile_not_met" in codes(result)
    profile.premise_min_origins = 1
    assert run(graph, profile, env).findings["parent"].status == "established"


def test_defeating_one_derivation_preserves_an_independent_alternative_and_its_parent():
    graph, profile, env = example()
    claim(graph, "component")
    argument(graph, "route-one", "component")
    argument(graph, "route-two", "component", ("e2",), evidence=("e2",))
    claim(graph, "parent")
    argument(graph, "a-parent", "parent", ("component",))
    graph.attacks["x"] = Attack(id="x", target_id="route-one", grounds="The first inference omits a condition.", evidence_ids=["e2"])
    result = run(graph, profile, env)
    assert result.argument_labels["route-one"] == "OUT"
    assert result.argument_labels["route-two"] == "IN"
    assert result.findings["parent"].status == "established"
    assert "route-one" not in result.findings["parent"].argument_ids


def test_grounded_mutual_attacks_remain_contested_and_timeout_has_no_winner():
    graph, profile, env = example()
    for cid, eid in (("a", "e1"), ("b", "e2")):
        claim(graph, cid)
        argument(graph, f"arg-{cid}", cid, (eid,), evidence=(eid,))
    graph.attacks["x"] = Attack(id="x", target_id="arg-b", support_argument_id="arg-a", grounds="A challenges B.", disposition="timed_out")
    graph.attacks["y"] = Attack(id="y", target_id="arg-a", support_argument_id="arg-b", grounds="B challenges A.")
    result = run(graph, profile, env)
    assert result.evaluation_status == "complete"
    assert result.findings["a"].status == result.findings["b"].status == "contested"
    assert set(result.attack_labels.values()) == {"UNDECIDED"}


def test_unsupported_attacks_and_scope_mismatched_rebuttals_cannot_defeat_support():
    graph, profile, env = example()
    claim(graph, "c")
    argument(graph, "a", "c")
    graph.attacks["x"] = Attack(id="x", target_id="a", grounds="Might be wrong.")
    graph.attacks["y"] = Attack(id="y", target_id="c", kind="rebut", grounds="Another site differed.",
                                evidence_ids=["e2"], scope=Scope({"subject": "different-site"}))
    result = run(graph, profile, env)
    assert result.findings["c"].status == "established"
    assert "attack_without_grounds" in codes(result)
    assert "attack_scope_mismatch" in codes(result)


def test_the_challenged_answer_cannot_discharge_itself_and_a_later_supported_reply_can():
    graph, profile, env = example()
    claim(graph, "c")
    a = argument(graph, "a", "c")
    original = a.conditions["record_warrant"]
    graph.attacks["x"] = Attack(
        id="x", target_id="a", kind="answer_inadequate", grounds="The recorded answer does not address the source limitation.",
        evidence_ids=["e2"], condition_id=original, challenged_revision=1, raised_revision=1,
        disposition="answered", reply_condition_id=original, reply_evidence_ids=["e1"],
        reply_revision=2, reply_reason="The original answer is still present.",
    )
    result = run(graph, profile, env)
    assert result.findings["c"].status == "not_established"
    assert "reply_does_not_discharge" in codes(result)
    condition(graph, "new-answer", evidence=("e1",), revision=2)
    graph.attacks["x"].reply_condition_id = "new-answer"
    graph.attacks["x"].reply_reason = "A later assessed answer addresses the specified limitation with located support."
    result = run(graph, profile, env)
    assert result.findings["c"].status == "established"
    assert result.attack_labels["x"] == "OUT"


def test_a_bare_discharge_flag_and_evidence_id_do_not_answer_an_objection():
    graph, profile, env = example()
    claim(graph, "c")
    argument(graph, "a", "c")
    graph.attacks["x"] = Attack(id="x", target_id="a", grounds="The inference has an unresolved defect.",
                                evidence_ids=["e2"], disposition="answered", reply_evidence_ids=["e1"])
    result = run(graph, profile, env)
    assert result.findings["c"].status == "not_established"
    assert result.attack_labels["x"] == "IN"
    assert "reply_does_not_discharge" in codes(result)


def test_replacing_a_challenged_condition_does_not_erase_the_objection():
    graph, profile, env = example()
    claim(graph, "c")
    a = argument(graph, "a", "c")
    original = a.conditions["record_warrant"]
    graph.attacks["x"] = Attack(id="x", target_id="a", kind="answer_inadequate",
                                condition_id=original, challenged_revision=1,
                                grounds="The original assessment misses a limitation.", evidence_ids=["e2"])
    condition(graph, "renamed-condition", revision=2)
    a.conditions["record_warrant"] = "renamed-condition"
    result = run(graph, profile, env)
    assert result.findings["c"].status == "not_established"
    assert result.attack_labels["x"] == "IN"
    assert "challenged_condition_replaced_without_discharge" in codes(result)


def test_cloning_a_challenged_argument_and_its_records_cannot_evade_the_attack():
    graph, profile, env = example()
    claim(graph, "c")
    original = argument(graph, "original", "c")
    graph.attacks["x"] = Attack(id="x", target_id=original.id, grounds="The recorded inference has a grounded defect.",
                                evidence_ids=["e2"])
    before = run(graph, profile, env)
    assert before.findings["c"].status == "not_established"
    copied = original.model_copy(deep=True, update={"id": "renamed"})
    original.withdrawn = True
    graph.evidence["e1-cloned"] = graph.evidence["e1"].model_copy(update={"id": "e1-cloned"})
    copied.premise_ids = ["e1-cloned"]
    for key, cid in list(copied.conditions.items()):
        clone_id = f"{cid}-cloned"
        graph.conditions[clone_id] = graph.conditions[cid].model_copy(
            update={"id": clone_id, "evidence_ids": ["e1-cloned"], "revision": 2})
        copied.conditions[key] = clone_id
    graph.arguments[copied.id] = copied
    after = run(graph, profile, env)
    assert after.findings["c"].status == "not_established"
    assert after.argument_labels["renamed"] == "OUT"
    assert after.attack_labels["x"] == "IN"


def test_bounded_absence_needs_a_strength_and_detection_argument():
    graph, profile, env = example()
    claim(graph, "absence", kind="absence", form="bounded_absence")
    a = argument(graph, "a-absence", "absence", pattern="bounded_absence")
    del a.conditions["absence_strength"]
    result = run(graph, profile, env)
    assert result.findings["absence"].status == "not_established"
    assert "required_conditions_missing" in codes(result)


def test_a_source_correction_recomputes_dependents_without_erasing_historical_attribution():
    graph, profile, env = example()
    claim(graph, "fact")
    argument(graph, "a-fact", "fact")
    claim(graph, "dependent")
    argument(graph, "a-dependent", "dependent", ("fact",))
    claim(graph, "report", kind="attribution", form="source_reports")
    argument(graph, "a-report", "report", pattern="attribution")
    before = run(graph, profile, env)
    assert before.findings["dependent"].status == "established"
    env.add("source-1", "Correction: the earlier closure report is withdrawn.", version="2")
    after = run(graph, profile, env)
    assert after.findings["fact"].status == after.findings["dependent"].status == "not_established"
    historical = profile.model_copy(update={"allow_historical_sources": True, "allowed_claim_kinds": ["attribution"]})
    result = run(graph, historical, env)
    assert result.findings["report"].status == "reported"
    assert "historical source source-1@1" in result.findings["report"].qualifications


@pytest.mark.parametrize("limit", ["max_derivations", "max_depth", "max_evaluation_steps"])
def test_resource_exhaustion_withholds_current_findings_and_retains_prior_result_as_history(limit):
    graph, profile, env = example()
    claim(graph, "component")
    argument(graph, "a-component", "component")
    claim(graph, "parent")
    argument(graph, "a-parent", "parent", ("component",))
    previous = run(graph, profile, env)
    graph.revision = 4
    limited = profile.model_copy(update={limit: 1})
    result = run(graph, limited, env, previous_evaluation=previous)
    assert result.evaluation_status == "incomplete"
    assert {f.status for f in result.findings.values()} == {"not_established"}
    assert result.last_complete_evaluation["graph_revision"] == 3
    assert result.graph_revision == 4
    assert result.task_completed is False


def test_ill_posed_requires_a_supported_failed_presupposition_not_merely_a_mapping():
    graph, profile, env = example()
    env.add("source-1", "No baseline schedule was adopted for this project.")
    graph.evidence["e1"].quote = "No baseline schedule was adopted for this project."
    c = claim(graph, "no-baseline", kind="presupposition_failure", form="presupposition_failure")
    graph.issue_presupposition_failures["issue-1"] = c.id
    first = run(graph, profile, env)
    assert first.issue_statuses["issue-1"] == "unresolved"
    argument(graph, "a-baseline", c.id)
    second = run(graph, profile, env)
    assert second.issue_statuses["issue-1"] == "ill_posed"
    assert second.task_completed is False


def test_claim_supersession_requires_a_valid_later_revision():
    graph, profile, env = example()
    original = claim(graph, "old")
    argument(graph, "a-old", "old")
    revised = claim(graph, "new")
    revised.supersedes = original.id
    argument(graph, "a-new", "new")
    first = run(graph, profile, env)
    assert first.findings["old"].status == "established"
    assert first.findings["new"].status == "not_established"
    revised.revision = 2
    second = run(graph, profile, env)
    assert second.findings["old"].status == "not_established"
    assert second.findings["new"].status == "established"
    assert "superseded_claim" in second.findings["old"].reasons


def test_actor_registry_prevents_a_model_record_from_claiming_a_trusted_tool_role():
    graph, profile, env = example()
    claim(graph, "c")
    a = argument(graph, "a", "c")
    profile.trusted_performers = {"analyst": "model"}
    graph.conditions[a.conditions["record_warrant"]].performer_kind = "tool"
    result = run(graph, profile, env)
    assert result.findings["c"].status == "not_established"
    assert "condition_performer_not_authenticated" in codes(result)
