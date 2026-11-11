import json

from inquiry import moves
from inquiry.closure import whole_question_answer
from inquiry.live import Harness
from inquiry.llm import FakeLLM
from inquiry.metrics import metrics
from inquiry.state import Inquiry
from inquiry.store import InquiryStore
from inquiry.tools import FakeFetcher, FakeSearch
from test_composition import component_graph


def proposal(main, components):
    scope = main.scope.model_copy(update={"population": "adults 70+", "relation": "increases"})
    return {"composed_claims": [{"text": "Net harm increased in adults 70+", "scope": scope.model_dump(),
        "relation": "increases", "premise_claim_ids": [c.id for c in components], "cq": {
            qid: {"answer": "The accepted findings supply this bridge", "evidence_ids": [c.id for c in components]}
            for qid in ("commensurable", "direction")}}]}


def test_compose_minimal_view_and_review_gate():
    g, main, components = component_graph()
    inq = Inquiry(id="compose", question=main.text, graph=g, round=1)
    moves.evaluate_move(inq)
    view = json.loads(moves.compose_view(inq))
    assert set(view) == {"main_issue", "accepted_components", "live_main_claims"}
    assert len(view["accepted_components"]) == 3 and "pro_strength" in view["accepted_components"][0]
    result = moves.apply_compose(inq, moves.ComposeOutput.model_validate(proposal(main, components)))
    ev = moves.evaluate_move(inq)
    claim = g.claim(result["composed_claims"][0])
    assert ev.status(claim.id) == "in" and whole_question_answer(g, ev) is None
    assert moves.stop(inq, ev, 1, 0).decision == "continue"
    moves.critique(inq, FakeLLM({"critique": {}}), claim_ids={claim.id})
    assert whole_question_answer(g, ev).id == claim.id
    assert moves.stop(inq, ev, 1, 0).decision == "stop"
    moves.apply_conclude(inq, moves.ConcludeOutput(answer="A qualified finding."))
    assert "60–69" in inq.conclusion.answer and "untested" in inq.conclusion.answer
    assert metrics(inq, ev)["whole_question_answered"]
    assert metrics(inq, ev)["composition_accepted"] == 1


def test_last_round_composition_gets_only_one_capped_review(tmp_path):
    g, main, components = component_graph()
    inq = Inquiry(id="cap", question=main.text, graph=g, phase="inquiring")
    proposer = FakeLLM({"plan": {"tests": []}, "argue": {}, "revise": {},
                        "compose": proposal(main, components), "conclude": {"answer": "Qualified finding."}})
    critic = FakeLLM({"critique": {}})
    store = InquiryStore(tmp_path, "cap")
    h = Harness(inq, store, proposer, critic, FakeSearch(), FakeFetcher({}), log=lambda _: None)
    h.run(rounds=1)
    names = [e["move"] for e in store.events()]
    assert names.count("compose") == names.count("critique_composed") == names.count("respond_composed") == 1
    assert names.index("evaluate") < names.index("compose") < names.index("critique_composed")
    assert len(critic.calls) == 2 and "Allowed attack targets only" in critic.calls[-1][1]
    assert inq.round == 1 and whole_question_answer(g, inq.evaluation) is not None


def test_capped_review_drops_other_targets():
    g, main, components = component_graph()
    inq = Inquiry(id="targets", question=main.text, graph=g, round=1)
    moves.evaluate_move(inq)
    result = moves.apply_compose(inq, moves.ComposeOutput.model_validate(proposal(main, components)))
    moves.evaluate_move(inq)
    critic = FakeLLM({"critique": {"attacks": [{"target_id": components[0].id,
        "type": "rebut", "premise_ids": [components[1].id]}]}})
    result = moves.critique(inq, critic, claim_ids=set(result["composed_claims"]))
    assert not result["attacks"] and "out-of-scope" in result["dropped"][0]
