from inquiry import moves
from inquiry.argument.evaluate import evaluate
from inquiry.metrics import argument_split_metrics
from inquiry.state import Inquiry


def test_argue_provenance_survives_later_round_and_other_revisions_are_not_scoped():
    inq = Inquiry(id="split", question="q")
    g = inq.graph
    q = g.add_issue("q")
    c = g.add_claim("Original", issue_id=q.id)
    other = g.add_claim("Another original", issue_id=q.id)
    e = g.add_evidence("An observation")
    g.add_argument("document_record", [e.id], other.id)
    out = moves.ArgueOutput(scoped_claims=[moves.ScopedClaimProposal(text="Source-scoped result", revision_of=c.id,
        issue_id=q.id, answers_issue=False, premise_ids=[e.id], scheme="document_record")])
    result = moves.apply_argue(inq, out)
    scoped = g.claim(result["scoped_claims"][0])
    assert scoped.created_by_move == "argue"
    descendant = g.supersede_claim(scoped.id, ["A later narrowing of the scoped result"],
                                  carry_arguments=result["arguments"], answers_issue=False)[0]
    assert descendant.created_by_move == "argue"
    revised = g.supersede_claim(other.id, ["Revision from a different move"])[0]
    g.add_argument("document_record", [e.id], revised.id)
    inq.round = 2
    restored = Inquiry.model_validate_json(inq.model_dump_json())
    split = argument_split_metrics(restored, evaluate(restored.graph))
    assert split["supporting_original"] == 1 and split["supporting_scoped"] == 1
    assert split["main_supporting_in_original"] == 0


def test_legacy_scoped_ids_are_explicit_not_inferred_from_every_revision():
    inq = Inquiry(id="legacy", question="q")
    g = inq.graph
    q = g.add_issue("q")
    old = g.add_claim("old", issue_id=q.id)
    new = g.supersede_claim(old.id, ["new"])[0]
    e = g.add_evidence("e")
    g.add_argument("document_record", [e.id], new.id)
    ev = evaluate(g)
    assert argument_split_metrics(inq, ev)["supporting_original"] == 1
    assert argument_split_metrics(inq, ev, {new.id})["supporting_scoped"] == 1
