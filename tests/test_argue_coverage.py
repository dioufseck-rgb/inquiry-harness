import pytest

from inquiry import moves
from inquiry.llm import FakeLLM
from inquiry.state import Inquiry


def packet(n=10):
    inq = Inquiry(id="coverage", question="Did treatment reduce harm?")
    g = inq.graph
    q = g.add_issue(inq.question, answerhood="Direction and population")
    c = g.add_claim("Treatment reduced harm", issue_id=q.id)
    for i in range(n):
        g.add_evidence(f"Observation {i}", bears_on={c.id: "for"})
    return inq


def test_unusable_cap_is_enforced_even_when_model_ignores_it():
    inq = packet()
    out = moves.ArgueOutput(unusable=[moves.UnusableProposal(evidence_id=f"E{i}", reason="Cannot support this claim") for i in range(1, 11)])
    result = moves.apply_argue(inq, out)
    assert len(result["unusable"]) == 2 and len(result["ignored_unusable"]) == 8
    assert len([e for e in inq.graph.evidence if e.provenance.get("unusable")]) / 10 < .3


def test_coverage_retry_requires_argument_or_claim_reason_once():
    inq = packet()
    responses = iter([{}, {"claim_reasons": [{"claim_id": "C1", "reason": "No observation establishes the intervention comparison."}]}])
    llm = FakeLLM({"argue": lambda _: next(responses)})
    result = moves.argue(inq, llm)
    assert len(llm.calls) == 2 and "Required coverage correction" in llm.calls[1][1]
    assert result["coverage_retries"] == ["Q1"] and inq.claim_reasons["C1"]
    assert not inq.graph.arguments  # reasons must not be counted as arguments


def test_coverage_failure_is_not_silently_marked_complete():
    inq = packet()
    llm = FakeLLM({"argue": {}})
    with pytest.raises(ValueError, match="coverage unresolved after one retry"):
        moves.argue(inq, llm)
    assert len(llm.calls) == 2 and not inq.claim_reasons


def test_scoped_revision_has_argument_and_does_not_defeat_whole_issue_answers():
    inq = packet()
    g = inq.graph
    rival = g.add_claim("Treatment increased harm", issue_id="Q1")
    g.set_contraries("C1", rival.id)
    out = moves.ArgueOutput(scoped_claims=[moves.ScopedClaimProposal(
        text="The trial reported lower harm in its enrolled population", revision_of="C1", issue_id="Q1",
        answers_issue=False, premise_ids=["E1", "E2"], scheme="document_record")])
    result = moves.apply_argue(inq, out, allowed_claims={"C1", rival.id}, allowed_evidence={"E1", "E2"})
    new = g.claim(result["scoped_claims"][0])
    assert not g.claim("C1").live and new.revision_of == "C1" and not new.answers_issue
    assert g.arg(result["arguments"][0]).claim_id == new.id
    assert not new.contrary_ids and new.id not in rival.contrary_ids
    assert g.ev("E1").bears_on[new.id] == "for" and not g.validate_refs()


def test_invalid_scoped_argument_cannot_withdraw_a_claim():
    inq = packet()
    out = moves.ArgueOutput(scoped_claims=[moves.ScopedClaimProposal(
        text="Narrower result", revision_of="C1", issue_id="Q1", answers_issue=False,
        premise_ids=["E999"], scheme="study_result")])
    result = moves.apply_argue(inq, out)
    assert inq.graph.claim("C1").live and not result["scoped_claims"] and result["dropped"]
