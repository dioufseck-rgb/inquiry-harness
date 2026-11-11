import pytest

from inquiry import moves
from inquiry.llm import FakeLLM
from inquiry.state import Inquiry


def attacked():
    inq = Inquiry(id="response", question="q")
    g = inq.graph
    q = g.add_issue("q")
    c = g.add_claim("The measured value fell", issue_id=q.id)
    e = g.add_evidence("The comparison uses different definitions")
    a = g.add_argument("document_record", [e.id], c.id)
    for qid in ("authentic", "accuracy", "reading"):
        g.answer_cq(a.id, qid, "ok", [e.id])
    attack = g.add_attack(a.id, "undercut", [e.id], origin="critic")
    attack.attacks.raises_cq = "definitions"
    moves.evaluate_move(inq)
    return inq, attack


def justified(attack_id):
    return {"attack_id": attack_id, "action": "concede", "cq_id": "definitions",
            "discharge_attempt": "Checked the source's definitions against the comparison measure.",
            "checked_evidence_ids": ["E1"],
            "no_answer_reason": "The source documents the mismatch but supplies no common-definition estimate.",
            "note": "Need a reconciled series"}


def test_bare_concession_is_rejected_then_one_valid_correction_is_recorded():
    inq, attack = attacked()
    replies = iter([{"responses": [{"attack_id": attack.id, "action": "concede", "note": "fair concern"}]},
                    {"responses": [justified(attack.id)]}])
    llm = FakeLLM({"respond": lambda _: next(replies)})
    result = moves.respond(inq, llm)
    assert len(llm.calls) == 2 and result["rejected_concessions"]
    assert result["conceded"] == result["concessions_justified"] == [attack.id]
    assert inq.discharge_attempts[0]["attack_id"] == attack.id
    assert inq.response_dispositions[attack.id] == "concede"


def test_wrong_cq_or_unknown_checked_evidence_cannot_justify_concession():
    inq, attack = attacked()
    proposal = justified(attack.id)
    proposal.update(cq_id="accuracy", checked_evidence_ids=["E999"])
    result = moves.apply_respond(inq, moves.RespondOutput(responses=[moves.ResponseProposal(**proposal)]))
    assert not result["conceded"] and result["rejected_concessions"]
    assert not inq.discharge_attempts and moves.CONCEDED_MARK not in attack.note


def test_writing_an_unrelated_cq_is_not_counted_as_discharge():
    inq, attack = attacked()
    result = moves.apply_respond(inq, moves.RespondOutput(responses=[moves.ResponseProposal(
        attack_id=attack.id, action="discharge", cq_answers={"currency": moves.CQAnswerProposal(answer="Current", evidence_ids=["E1"])})]))
    assert not result["discharged"] and result["discharge_attempts"]
    inq.graph.answer_cq("A1", "definitions", "Reconciled", ["E1"])
    assert not moves.standing_attacks(inq, moves.evaluate_move(inq))


def test_missing_responses_fail_after_one_correction_instead_of_vacuous_success():
    inq, attack = attacked()
    llm = FakeLLM({"respond": {"responses": []}})
    with pytest.raises(ValueError, match="Respond unresolved after one correction"):
        moves.respond(inq, llm)
    assert len(llm.calls) == 2


def test_unnamed_attack_requires_counter_or_concession_not_an_unrelated_cq_answer():
    inq, attack = attacked()
    attack.attacks.raises_cq = ""
    assert moves.response_cq_ids(inq.graph, attack) == {"grounds"}
    result = moves.apply_respond(inq, moves.RespondOutput(responses=[moves.ResponseProposal(
        attack_id=attack.id, action="discharge", cq_answers={"definitions": moves.CQAnswerProposal(answer="same", evidence_ids=["E1"])})]))
    assert not result["discharged"] and "no valid named CQ" in result["dropped"][0]
    assert "Writing a CQ answer cannot discharge it" in moves.respond_view(inq, [attack])
