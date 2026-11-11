from pathlib import Path

from inquiry import moves
from inquiry.llm import FakeLLM
from inquiry.state import Inquiry


def test_sonnet_revision_coverage_and_reopened_assumption_reach_respond():
    inq = Inquiry.model_validate_json(Path("experiments/E6/sonnet/inquiry.json").read_text(encoding="utf-8"))
    g = inq.graph
    old = g.claim("C27")
    for e in g.evidence[:3]:
        e.bears_on[old.id] = "for"
    moves.apply_revise(inq, moves.ReviseOutput(operations=[moves.RevisionOp(
        op="narrow", claim_id=old.id, texts=["USPSTF records a recommendation for its eligible population"],
        answers_issue=False)]))
    new = g.claim(old.superseded_by)
    fake = FakeLLM({"argue": {"claim_reasons": [{"claim_id": new.id,
                       "reason": "These items do not establish the narrowed recommendation population."}]}})
    moves.coverage_check(inq, fake)
    assert len(fake.calls) == 1 and new.id in fake.calls[0][1]
    a = g.add_argument("document_record", [g.evidence[0].id], new.id)
    for qid in a.cq:
        g.answer_cq(a.id, qid, "The record supplies this", [g.evidence[0].id])
    attack = g.add_attack(a.id, "undercut", [g.evidence[1].id], origin="critic")
    attack.attacks.raises_cq = "reading"
    attack.attacks.basis = "answer_inadequate"
    attack.attacks.challenged_revision = a.cq["reading"].revision
    ev = moves.evaluate_move(inq)
    assert "reading" in ev.reopened_cqs[a.id]
    view = moves.respond_view(inq, [attack])
    assert new.text in view and "reading" in view


def test_revise_round_claim_limit():
    inq = Inquiry(id="limit", question="Q")
    q = inq.graph.add_issue("Q")
    c = inq.graph.add_claim("old", issue_id=q.id)
    out = moves.apply_revise(inq, moves.ReviseOutput(operations=[moves.RevisionOp(
        op="split", claim_id=c.id, texts=["part"] * 5)]))
    assert c.live and out["dropped"]
