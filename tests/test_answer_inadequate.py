from inquiry import moves
from inquiry.argument.evaluate import evaluate, is_discharged, reopening_metrics
from inquiry.state import Inquiry


def packet():
    inq = Inquiry(id="audit", question="Does treatment help all adults?")
    g = inq.graph
    issue = g.add_issue(inq.question)
    claim = g.add_claim("Treatment helps all adults", issue_id=issue.id)
    evidence = g.add_evidence("The trial only enrolled older adults")
    argument = g.add_argument("study_result", [evidence.id], claim.id)
    from inquiry.argument.schemes import SCHEMES
    for question in SCHEMES[argument.scheme].assumptions():
        g.answer_cq(argument.id, question.id, "Population matches all adults", [evidence.id])
    return inq, argument


def reopen(inq, argument, **kwargs):
    proposal = moves.AttackProposal(target_id=argument.id, type="undercut", cq_id="directness",
        basis="answer_inadequate", premise_ids=["E1"], note="The enrolled population excludes younger adults", **kwargs)
    return moves.apply_critique(inq, moves.CritiqueOutput(attacks=[proposal]))


def test_satisfied_answer_can_be_reopened_and_respond_can_restore_it():
    inq, argument = packet()
    result = reopen(inq, argument)
    attack = inq.graph.arg(result["attacks"][0])
    ev = evaluate(inq.graph)
    assert ev.converged and ev.reopened_cqs == {argument.id: ["directness"]}
    assert not ev.applicable[argument.id] and ev.labels[attack.id] == "in"
    assert argument.cq["directness"].status == "answered" and not is_discharged(inq.graph, attack)
    assert attack.attacks.was_reopened
    # A later Argue answer cannot certify away the critic's challenge.
    inq.graph.answer_cq(argument.id, "directness", "A better answer", ["E1"])
    assert not is_discharged(inq.graph, attack)
    response = moves.ResponseProposal(attack_id=attack.id, action="discharge", cq_answers={
        "directness": moves.CQAnswerProposal(answer="Evidence-backed response to the precise mismatch", evidence_ids=["E1"])})
    assert moves.apply_respond(inq, moves.RespondOutput(responses=[response]))["discharged"] == [attack.id]
    ev = evaluate(inq.graph)
    assert ev.applicable[argument.id] and not ev.reopened_cqs and is_discharged(inq.graph, attack)
    assert reopening_metrics(inq.graph, ev)["reopened_then_discharged"] == 1


def test_counterattack_restores_target_order_independently():
    inq, argument = packet()
    attack = inq.graph.arg(reopen(inq, argument)["attacks"][0])
    inq.graph.add_attack(attack.id, "undercut", ["E1"], origin="proposer")
    first = evaluate(inq.graph)
    assert first.applicable[argument.id] and not first.reopened_cqs and first.converged
    reversed_graph = inq.graph.model_copy(deep=True)
    reversed_graph.arguments.reverse()
    second = evaluate(reversed_graph)
    assert first.applicable == second.applicable and first.labels == second.labels
    assert first.reopened_cqs == second.reopened_cqs and second.converged


def test_only_satisfied_or_defaulted_assumptions_can_be_reopened():
    inq, argument = packet()
    bad = moves.AttackProposal(target_id=argument.id, type="undercut", cq_id="bias", basis="answer_inadequate", premise_ids=["E1"])
    result = moves.apply_critique(inq, moves.CritiqueOutput(attacks=[bad]))
    assert not result["attacks"] and result["dropped"]
    argument.cq["directness"].status = "defaulted"
    assert reopen(inq, argument)["attacks"]


def test_quoted_self_contradiction_can_ground_reopening_without_external_premise():
    inq, argument = packet()
    quote = argument.cq["directness"].answer
    result = moves.apply_critique(inq, moves.CritiqueOutput(attacks=[moves.AttackProposal(
        target_id=argument.id, type="undercut", cq_id="directness", basis="answer_inadequate",
        answer_quote=quote, note=f'"{quote}" contradicts the stated restriction to an older-only trial population.')]))
    assert result["attacks"] and not inq.graph.validate_refs()
    assert evaluate(inq.graph).reopened_cqs == {argument.id: ["directness"]}
    second, other = packet()
    bad = moves.apply_critique(second, moves.CritiqueOutput(attacks=[moves.AttackProposal(
        target_id=other.id, type="undercut", cq_id="directness", basis="answer_inadequate", note="I disagree")]))
    assert not bad["attacks"]


def test_critique_audit_shows_actual_claim_and_answer_evidence():
    inq, argument = packet()
    moves.evaluate_move(inq)
    view = moves.critique_view(inq)
    assert "Audit answered assumptions" in view and "Population matches all adults" in view
    assert "evidence_ids: E1" in view and "answers_issue=True" in view
