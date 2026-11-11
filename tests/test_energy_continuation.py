from experiments.resume_energy import finish_saved_round
from inquiry import moves
from inquiry.live import Harness
from inquiry.llm import FakeLLM
from inquiry.state import Inquiry
from inquiry.store import InquiryStore
from inquiry.tools import FakeFetcher, FakeSearch
from test_argue_coverage import packet
from test_compose_move import proposal
from test_composition import component_graph


def test_argue_continuation_only_calls_remaining_issue():
    inq = packet(3)
    q = inq.graph.add_issue("Remaining issue")
    c = inq.graph.add_claim("Remaining claim", issue_id=q.id)
    for e in inq.graph.evidence:
        e.bears_on[c.id] = "for"
    before = inq.graph.claim("C1").model_dump()
    llm = FakeLLM({"argue": {"claim_reasons": [{"claim_id": c.id,
        "reason": "The observations do not establish the remaining comparison."}]}})
    result = moves.argue(inq, llm, issue_ids={q.id})
    assert result["issues"] == [q.id] and len(llm.calls) == 1
    assert f"{q.id} [" in llm.calls[0][1]
    assert inq.graph.claim("C1").model_dump() == before


def test_finish_checkpoint_stays_in_round_two_and_skips_appraisal(tmp_path):
    g, main, components = component_graph()
    inq = Inquiry(id="continue", question=main.text, graph=g, phase="inquiring", round=2)
    store = InquiryStore(tmp_path, "continue")
    store.save(inq)
    original_arguments = [a.model_dump() for a in g.arguments]
    proposer = FakeLLM({"argue": {}, "revise": {"operations": []},
                        "compose": proposal(main, components), "conclude": {"answer": "Qualified finding."}})
    critic = FakeLLM({"critique": {}})
    h = Harness(inq, store, proposer, critic, FakeSearch(), FakeFetcher({}), log=lambda _: None)
    finish_saved_round(h, {components[-1].issue_id})
    assert inq.phase == "concluded" and inq.round == 2
    assert [a.model_dump() for a in g.arguments[:len(original_arguments)]] == original_arguments
    names = [e["move"] for e in store.events()]
    assert names[:6] == ["argue", "revise", "coverage_check", "critique", "respond", "evaluate"]
    assert not set(names) & {"frame", "hypothesize", "plan", "gather", "compute"}
    assert names.count("critique_composed") == 1 and names[-1] == "conclude"
    assert store.verify_ledger() and not h.search.calls and not h.fetcher.calls
