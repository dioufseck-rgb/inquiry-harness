"""B2: the source_adjudication pattern in the kernel, case by case and check by check."""
from __future__ import annotations

import pytest

from inquiry.v1.kernel import PATTERN_ASSUMABLE, PATTERN_FORMS, PATTERN_REQUIREMENTS, evaluate
from inquiry.v1.models import Argument, Attack, Claim, Condition, Evidence, InquiryGraph, Profile, Scope
from inquiry.v1.runtime import REPERTOIRE, starter_graph

from test_kernel import EvidenceBoundary

SCOPE = {"unit": "pump-A4", "event": "post-overhaul inspection", "before": "2026-04-13"}
ADJ = PATTERN_REQUIREMENTS["source_adjudication"]


def setting(min_origins=2, allowed=("attribution", "source_adjudication")):
    env = EvidenceBoundary()
    env.add("contractor-report", "Inspection of pump A4 completed on 10 April 2026.", origins=("contractor",))
    env.add("inspector-log", "Attended pump A4 inspection on 10 April 2026; all steps completed.", origins=("inspector",))
    env.add("sensor-record", "Pump A4 pressure test sequence recorded 10 April 2026 09:40.", origins=("rig-logger",))
    env.add("memo", "Memo: per the contractor report, pump A4 inspection completed.", origins=("contractor",))
    env.add("clerk-note", "The contractor told me the A4 inspection was done.", origins=("clerk",))
    env.add("inspector-log-opposed", "Pump A4 inspection not completed; pressure test outstanding.", origins=("inspector",))
    env.add("inspector-log-other-unit", "Entry concerns compressor K2, not pump A4; the A4 inspection was completed.", origins=("inspector",))
    graph = InquiryGraph(id="case", revision=1)
    for key in env.source_lookup:
        sid, version = key
        text = env.source_lookup[key]["reading_blocks"]["p1"]
        graph.evidence["e-" + sid] = Evidence(id="e-" + sid, source_id=sid, source_version=version, locator="p1", quote=text)
    # The finding standard is min_origins; a single report is usable as a premise (premise_min_origins 1)
    # while establishing nothing on its own.
    profile = Profile(id="adjudication", authority="test-authority", min_origins=min_origins, premise_min_origins=1,
                      allowed_patterns=list(allowed))
    return graph, profile, env


def report(graph, source_id, *, cid=None, aid=None):
    """An attribution claim for one source, supported by its own attribution argument."""
    cid = cid or "r-" + source_id
    aid = aid or "a-" + source_id
    eid = "e-" + source_id
    graph.claims[cid] = Claim(id=cid, text=f"{source_id} reports on the A4 inspection.", kind="attribution",
                              form="source_reports", scope=Scope(dict(SCOPE)))
    for key in PATTERN_REQUIREMENTS["attribution"]:
        graph.conditions[f"{aid}-{key}"] = Condition(id=f"{aid}-{key}", text=f"Assess {key}", status="met",
                                                     evidence_ids=[eid], performer="analyst", performer_kind="model")
    graph.arguments[aid] = Argument(id=aid, claim_id=cid, pattern="attribution", premise_ids=[eid],
                                    conditions={key: f"{aid}-{key}" for key in PATTERN_REQUIREMENTS["attribution"]},
                                    scope=Scope(dict(SCOPE)))
    return cid, aid


def adjudicate(graph, premises, *, open=(), assumed=(), omit=(), evidence=("e-inspector-log",), cid="C", aid="A"):
    graph.claims[cid] = Claim(id=cid, text="The required inspection of pump A4 was completed before it returned to service.",
                              kind="substantive", form="assertion", scope=Scope(dict(SCOPE)))
    conditions = {}
    for key in ADJ:
        if key in omit:
            continue
        status = "open" if key in open else "assumed" if key in assumed else "met"
        graph.conditions[f"{aid}-{key}"] = Condition(id=f"{aid}-{key}", text=f"Assess {key}", status=status,
                                                     evidence_ids=list(evidence) if status == "met" else [],
                                                     performer="analyst", performer_kind="model")
        conditions[key] = f"{aid}-{key}"
    graph.arguments[aid] = Argument(id=aid, claim_id=cid, pattern="source_adjudication", premise_ids=list(premises),
                                    conditions=conditions, scope=Scope(dict(SCOPE)))
    return cid, aid


def run(graph, profile, env):
    return evaluate(graph, profile, evidence_context=env)


def codes(result):
    return {d["code"] for d in result.diagnostics}


def test_pattern_is_catalogued_with_no_assumable_condition():
    assert ADJ == ("positioning", "interest", "independence", "opposition", "inference_validity", "applicability")
    assert PATTERN_FORMS["source_adjudication"] == ("assertion",)
    assert PATTERN_ASSUMABLE["source_adjudication"] == ()
    assert "source adjudication" in REPERTOIRE


# -- the six case types ---------------------------------------------------------------------------

def test_corroborated_two_independent_reports_establish_the_assertion():
    graph, profile, env = setting()
    r1, _ = report(graph, "inspector-log")
    r2, _ = report(graph, "sensor-record")
    adjudicate(graph, [r1, r2])
    result = run(graph, profile, env)
    finding = result.findings["C"]
    assert finding.status == "established" and sorted(finding.support_origins) == ["inspector", "rig-logger"]
    # each report alone does not reach the two-origin standard; only the adjudication does
    assert result.findings[r1].status == "not_established"
    assert "minimum_support_origins_not_met" in result.findings[r1].reasons
    assert "unsupported_pattern" not in codes(result) and "premise_use_profile_not_met" not in codes(result)


def test_interested_only_a_report_and_its_derived_memo_are_one_origin():
    graph, profile, env = setting()
    r1, _ = report(graph, "contractor-report")
    r2, _ = report(graph, "memo")  # declared lineage: the memo's root origin is the contractor
    adjudicate(graph, [r1, r2], open=("independence",))
    result = run(graph, profile, env)
    finding = result.findings["C"]
    assert finding.status == "not_established" and "A-independence" in finding.open_conditions
    # even with independence asserted met, one origin cannot reach min_origins 2
    graph.conditions["A-independence"].status = "met"
    graph.conditions["A-independence"].evidence_ids = ["e-contractor-report"]
    result = run(graph, profile, env)
    assert result.findings["C"].status == "not_established"
    assert "minimum_support_origins_not_met" in result.findings["C"].reasons


def test_opposed_unanswered_report_defeats_the_adjudication():
    graph, profile, env = setting()
    r1, _ = report(graph, "contractor-report")
    r2, _ = report(graph, "sensor-record")
    adjudicate(graph, [r1, r2])
    _, opposed = report(graph, "inspector-log-opposed")
    graph.attacks["x"] = Attack(id="x", target_id="C", kind="rebut", support_argument_id=opposed, raised_revision=1,
                                grounds="The inspector's log reports the inspection as not completed.",
                                scope=Scope(dict(SCOPE)))
    result = run(graph, profile, env)
    assert result.attack_labels["x"] == "IN"
    assert result.findings["C"].status in {"not_established", "contested"}
    assert result.findings["C"].status != "established"


def test_opposed_answered_a_later_reply_quoting_the_other_unit_discharges_the_rebut():
    graph, profile, env = setting()
    graph.revision = 2
    r1, _ = report(graph, "contractor-report")
    r2, _ = report(graph, "sensor-record")
    adjudicate(graph, [r1, r2])
    _, opposed = report(graph, "inspector-log-opposed")
    graph.conditions["reply-other-unit"] = Condition(
        id="reply-other-unit", text="Does the opposed entry concern this unit?",
        answer="The located entry concerns compressor K2, not pump A4.", status="met",
        evidence_ids=["e-inspector-log-other-unit"], performer="analyst", performer_kind="model", revision=2)
    graph.attacks["x"] = Attack(id="x", target_id="C", kind="rebut", support_argument_id=opposed, raised_revision=1,
                                grounds="The inspector's log reports the inspection as not completed.",
                                scope=Scope(dict(SCOPE)), disposition="answered",
                                reply_condition_id="reply-other-unit", reply_evidence_ids=["e-inspector-log-other-unit"],
                                reply_revision=2, reply_reason="The entry is about another unit, shown by its located text.")
    result = run(graph, profile, env)
    assert result.attack_labels["x"] == "OUT"
    assert result.findings["C"].status == "established"


def test_superseded_version_cannot_ground_an_opposed_report():
    graph, profile, env = setting()
    env.add("inspector-log-v", "Pump A4 inspection not completed.", version="1", origins=("inspector",))
    env.add("inspector-log-v", "Correction: pump A4 inspection completed on 10 April 2026.", version="2", origins=("inspector",))
    graph.evidence["e-old"] = Evidence(id="e-old", source_id="inspector-log-v", source_version="1", locator="p1",
                                       quote="Pump A4 inspection not completed.")
    graph.evidence["e-inspector-log-v"] = Evidence(id="e-inspector-log-v", source_id="inspector-log-v", source_version="2",
                                                   locator="p1", quote="Correction: pump A4 inspection completed on 10 April 2026.")
    r1, _ = report(graph, "inspector-log-v")
    r2, _ = report(graph, "sensor-record")
    adjudicate(graph, [r1, r2])
    # an attribution of the superseded entry, and a rebut founded on it
    graph.claims["r-old"] = Claim(id="r-old", text="The old log entry reports non-completion.", kind="attribution",
                                  form="source_reports", scope=Scope(dict(SCOPE)))
    for key in PATTERN_REQUIREMENTS["attribution"]:
        graph.conditions[f"a-old-{key}"] = Condition(id=f"a-old-{key}", text=key, status="met", evidence_ids=["e-old"],
                                                     performer="analyst", performer_kind="model")
    graph.arguments["a-old"] = Argument(id="a-old", claim_id="r-old", pattern="attribution", premise_ids=["e-old"],
                                        conditions={key: f"a-old-{key}" for key in PATTERN_REQUIREMENTS["attribution"]},
                                        scope=Scope(dict(SCOPE)))
    graph.attacks["x"] = Attack(id="x", target_id="C", kind="rebut", support_argument_id="a-old", raised_revision=1,
                                grounds="An earlier log entry reports non-completion.", scope=Scope(dict(SCOPE)))
    result = run(graph, profile, env)
    assert "superseded_source" in codes(result)
    assert result.attack_labels["x"] != "IN"
    assert result.findings["C"].status == "established"


def test_hearsay_fails_positioning():
    graph, profile, env = setting()
    r1, _ = report(graph, "contractor-report")
    r2, _ = report(graph, "clerk-note")
    adjudicate(graph, [r1, r2], open=("positioning",))
    result = run(graph, profile, env)
    finding = result.findings["C"]
    assert finding.status == "not_established" and "A-positioning" in finding.open_conditions


# -- each code check on its own -------------------------------------------------------------------

def test_one_premise_is_not_an_adjudication():
    graph, profile, env = setting()
    r1, _ = report(graph, "inspector-log")
    adjudicate(graph, [r1])
    result = run(graph, profile, env)
    assert "adjudication_requires_attributed_reports" in codes(result)
    assert result.findings["C"].status == "not_established"


def test_premises_must_be_attributed_reports_not_record_assertions():
    graph, profile, env = setting(min_origins=1, allowed=("attribution", "source_adjudication", "document_record"))
    r1, _ = report(graph, "inspector-log")
    graph.claims["d"] = Claim(id="d", text="The sensor record states a completed test.", kind="substantive",
                              form="assertion", scope=Scope(dict(SCOPE)))
    for key in PATTERN_REQUIREMENTS["document_record"]:
        graph.conditions[f"ad-{key}"] = Condition(id=f"ad-{key}", text=key, status="met", evidence_ids=["e-sensor-record"],
                                                  performer="analyst", performer_kind="model")
    graph.arguments["ad"] = Argument(id="ad", claim_id="d", pattern="document_record", premise_ids=["e-sensor-record"],
                                     conditions={key: f"ad-{key}" for key in PATTERN_REQUIREMENTS["document_record"]},
                                     scope=Scope(dict(SCOPE)))
    adjudicate(graph, [r1, "d"])
    result = run(graph, profile, env)
    assert result.findings["d"].status == "established"
    assert "adjudication_requires_attributed_reports" in codes(result)
    assert result.findings["C"].status == "not_established"


def test_a_report_claim_without_its_attribution_argument_is_not_a_premise():
    graph, profile, env = setting()
    r1, _ = report(graph, "inspector-log")
    graph.claims["bare"] = Claim(id="bare", text="A bare report claim.", kind="attribution", form="source_reports",
                                 scope=Scope(dict(SCOPE)))
    adjudicate(graph, [r1, "bare"])
    result = run(graph, profile, env)
    assert "adjudication_requires_attributed_reports" in codes(result)
    assert result.findings["C"].status == "not_established"


@pytest.mark.parametrize("defect", ["omit", "assumed"])
def test_every_condition_is_required_and_none_may_be_assumed(defect):
    graph, profile, env = setting()
    r1, _ = report(graph, "inspector-log")
    r2, _ = report(graph, "sensor-record")
    adjudicate(graph, [r1, r2], **({"omit": ("interest",)} if defect == "omit" else {"assumed": ("interest",)}))
    result = run(graph, profile, env)
    assert result.findings["C"].status == "not_established"
    if defect == "omit":
        assert "required_conditions_missing" in codes(result)


def test_a_rebut_needs_a_founded_supporting_report():
    graph, profile, env = setting()
    r1, _ = report(graph, "inspector-log")
    r2, _ = report(graph, "sensor-record")
    adjudicate(graph, [r1, r2])
    graph.attacks["x"] = Attack(id="x", target_id="C", kind="rebut", support_argument_id="a-nonexistent", raised_revision=1,
                                grounds="Someone said otherwise.", scope=Scope(dict(SCOPE)))
    result = run(graph, profile, env)
    assert "attack_support_not_founded" in codes(result)
    assert result.findings["C"].status == "established"


def test_a_reply_from_the_same_revision_does_not_discharge():
    graph, profile, env = setting()
    r1, _ = report(graph, "contractor-report")
    r2, _ = report(graph, "sensor-record")
    adjudicate(graph, [r1, r2])
    _, opposed = report(graph, "inspector-log-opposed")
    graph.conditions["reply"] = Condition(id="reply", text="Other unit?", status="met", evidence_ids=["e-inspector-log-other-unit"],
                                          performer="analyst", performer_kind="model", revision=1)
    graph.attacks["x"] = Attack(id="x", target_id="C", kind="rebut", support_argument_id=opposed, raised_revision=1,
                                grounds="Not completed, per the log.", scope=Scope(dict(SCOPE)), disposition="answered",
                                reply_condition_id="reply", reply_evidence_ids=["e-inspector-log-other-unit"],
                                reply_revision=1, reply_reason="Other unit.")
    result = run(graph, profile, env)
    assert "reply_does_not_discharge" in codes(result)
    assert result.attack_labels["x"] == "IN" and result.findings["C"].status != "established"


def test_the_profile_must_permit_the_pattern():
    graph, profile, env = setting(allowed=("attribution", "document_record"))
    r1, _ = report(graph, "inspector-log")
    r2, _ = report(graph, "sensor-record")
    adjudicate(graph, [r1, r2])
    result = run(graph, profile, env)
    assert "unsupported_pattern" in codes(result) and result.findings["C"].status == "not_established"


# -- starter graph selection ------------------------------------------------------------------------

def case(allowed=None):
    public = {
        "shared_context": {"as_of": "2026-04-13"},
        "corpus": {"documents": [], "current_versions": {}},
        "question": {"id": "q", "question": "Was the inspection completed before the unit returned to service?",
                     "intended_use": "A scoped finding.", "scope": dict(SCOPE),
                     "target": {"kind": "substantive", "form": "assertion"},
                     "profile": {"id": "p", "version": "1", "authority": "test", "requirements": [],
                                 "kernel": {} if allowed is None else {"allowed_patterns": list(allowed), "min_origins": 2}}},
    }
    return public


def test_starter_graph_takes_the_first_fitting_pattern_the_profile_permits():
    default = starter_graph(case())
    assert default["arguments"]["a_target"]["pattern"] == "document_record"
    chosen = starter_graph(case(["attribution", "source_adjudication"]))
    assert chosen["arguments"]["a_target"]["pattern"] == "source_adjudication"
    assert set(chosen["conditions"]) == {"cq_" + key for key in ADJ}
    assert all(cond["status"] == "open" for cond in chosen["conditions"].values())
    unfit = starter_graph(case(["attribution"]))  # nothing permitted concludes an assertion: no scaffold argument
    assert unfit["arguments"] == {}
