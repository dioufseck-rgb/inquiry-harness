import pytest

from inquiry import moves
from inquiry.llm import FakeLLM
from inquiry.specificity import claim_specificity_errors, source_answerhood
from inquiry.state import Inquiry


@pytest.mark.parametrize("text,anchor,reason", [
    ("x" * 251, "", "length"),
    ("Years 2023, 2024 and 2025", "", "digit count"),
    ("Treatment at 100 mg reduces harm", "Direction and population", "dose"),
    ("The outcome is defined as a composite of MI and bleeding", "Source outcomes", "endpoint_definition"),
    ("Equal weighting reduces the measured effect", "Source findings", "weighting_rule"),
    ("NO2 fell relative to December 2022", "Direction and magnitude", "fixed_baseline"),
    ("Treatment reduces harm over five years", "Direction and population", "followup_window"),
])
def test_specificity_rejects_unrequested_detail(text, anchor, reason):
    assert any(reason in error for error in claim_specificity_errors(text, anchor))


def test_concentrations_ages_and_explicit_doses_are_not_false_positives():
    assert not claim_specificity_errors("NO2 fell by 1 µg/m³", "NO2 direction")
    assert not claim_specificity_errors("There is benefit in adults over 60 years", "Benefit in adults 60+")
    assert not claim_specificity_errors("100 mg reduced harm", "The effect of 100 milligrams")


def test_frame_removes_unrequested_protocol_but_keeps_source_reporting():
    text, reasons = source_answerhood("Does the treatment reduce harm?", "Use an equally weighted first-event composite over five years")
    assert reasons and "composite" not in text and "five" not in text
    same = "Reported direction, population and uncertainty"
    assert source_answerhood("Did the policy reduce NO2?", same) == (same, [])
    text, reasons = source_answerhood("Does treatment reduce net harm?", "Specify whether net effects use an unweighted composite or explicit severity weights")
    assert reasons and "composite" not in text


def test_hypothesize_corrects_specificity_once_then_drops_remaining_failure():
    inq = Inquiry(id="h", question="Did the policy reduce pollution?")
    moves.apply_frame(inq, moves.FrameOutput(restatement=inq.question, answerhood="Direction of pollution change"))
    scope = inq.graph.issue(inq.graph.main_issue_id).scope.model_dump()
    replies = iter([
        {"claims": [{"issue_id": "Q1", "text": "The policy reduced pollution", "scope": scope}, {"issue_id": "Q1", "text": "x" * 251, "scope": scope}]},
        {"claims": [{"issue_id": "Q1", "text": "x" * 252, "scope": scope}]},
    ])
    llm = FakeLLM({"hypothesize": lambda _: next(replies)})
    result = moves.hypothesize(inq, llm)
    assert len(llm.calls) == 2 and "Rejected specificity" in llm.calls[1][1]
    assert len(result["rejected_specificity"]) == 2
    assert all(len(c.text) <= 250 for c in inq.graph.claims)
    assert any(c.kind == "null" for c in inq.main_claims())
    assert any(c.kind == "substantive" for c in inq.main_claims())


def test_null_is_retained_for_each_active_issue():
    inq = Inquiry(id="n", question="q")
    moves.apply_frame(inq, moves.FrameOutput(restatement="q", sub_issues=[moves.SubIssue(text="sub")]))
    result = moves.apply_hypothesize(inq, moves.HypothesizeOutput(claims=[]))
    assert all(any(c.kind == "null" for c in inq.graph.claims_for_issue(issue.id)) for issue in inq.graph.issues)


def test_deflationary_claim_does_not_replace_required_null():
    inq = Inquiry(id="d", question="q")
    moves.apply_frame(inq, moves.FrameOutput(restatement="q"))
    moves.apply_hypothesize(inq, moves.HypothesizeOutput(claims=[
        moves.ClaimProposal(issue_id="Q1", text="The premise of the question is false", kind="deflationary")]))
    assert {c.kind for c in inq.main_claims()} == {"null", "deflationary"}


def test_replay_reports_protocol_violation_before_guard_correction(tmp_path):
    from inquiry.replay_move import run_samples
    inq = Inquiry(id="raw", question="Does treatment reduce harm?")
    moves.apply_frame(inq, moves.FrameOutput(restatement=inq.question, answerhood="Direction of harm"))
    replies = iter([{"claims": [{"issue_id": "Q1", "text": "100 mg reduces harm"}]},
                    {"claims": [{"issue_id": "Q1", "text": "Treatment reduces harm"}]}])
    result = run_samples(inq, "hypothesize", lambda: FakeLLM({"hypothesize": lambda _: next(replies)}), tmp_path / "raw", n=1)
    assert result["samples"][0]["raw_metrics"]["n_over_guard"] == 1
    assert result["samples"][0]["metrics"]["n_over_guard"] == 0


def test_hypothesize_view_normalizes_legacy_protocol_without_changing_snapshot():
    inq = Inquiry(id="legacy", question="Does treatment reduce harm?")
    inq.graph.add_issue(inq.question, answerhood="Use an equally weighted first-event composite over five years")
    before = inq.model_dump()
    view = moves.hypothesize_view(inq)
    assert "over five years" not in view and "source" in view.lower()
    assert inq.model_dump() == before
