from inquiry import moves
from inquiry.llm import FakeLLM
from inquiry.state import Inquiry
from test_live_cycle import make_harness


def test_frame_samples_choose_modal_type_and_median_tree():
    frames = [
        {"restatement": "q", "question_type": "causal", "sub_issues": [{"text": "one"}]},
        {"restatement": "q", "question_type": "causal", "sub_issues": [{"text": "one"}, {"text": "two"}, {"text": "three"}]},
        {"restatement": "q", "question_type": "empirical", "sub_issues": []},
    ]
    scope = {"population": "population X", "comparison": "X vs alternative", "outcome": "Y", "period": "follow-up", "relation": "unknown"}
    for frame in frames:
        frame["scope"] = dict(scope)
        for sub in frame.get("sub_issues", []):
            sub["scope"] = dict(scope)
    outputs = iter(frames)
    llm = FakeLLM({"frame": lambda _: next(outputs)})
    inq = Inquiry(id="f", question="Did X reduce Y?")
    result = moves.frame(inq, llm, samples=3)
    assert inq.framing.question_type == "causal"
    assert result["selected_sample"] in (0, 1)
    assert [s["question_type"] for s in result["samples"]] == ["causal", "causal", "empirical"]
    assert [s["sub_issue_count"] for s in result["samples"]] == [1, 3, 0]
    assert len(llm.calls) == 3


def test_frame_type_uses_the_question_not_the_topic():
    inq = Inquiry(id="f", question="What does body B recommend about reducing net harm?")
    result = moves.apply_frame(inq, moves.FrameOutput(restatement="q", question_type="causal"))
    assert inq.framing.question_type == "empirical" and result["type_by_rule"]
    inq = Inquiry(id="g", question="Does initiating X reduce net harm?")
    moves.apply_frame(inq, moves.FrameOutput(restatement="q", question_type="empirical"))
    assert inq.framing.question_type == "causal"


def test_recommendation_matching_population_and_outcome_moves_to_main():
    inq = Inquiry(id="f", question="Does initiating aspirin reduce net cardiovascular harm in adults 60+?")
    moves.apply_frame(inq, moves.FrameOutput(
        restatement="q", question_type="causal",
        answerhood="The verdict about net cardiovascular harm in adults aged 60 and over",
        sub_issues=[moves.SubIssue(text="What does the guideline recommend?")]))
    result = moves.apply_hypothesize(inq, moves.HypothesizeOutput(claims=[
        moves.ClaimProposal(issue_id="Q2", text="USPSTF recommends against initiation because of net cardiovascular harm in adults 60+",
                            recommendation_body="USPSTF", target={"population": "adults aged 60 and over", "outcome": "net cardiovascular harm"}),
        moves.ClaimProposal(issue_id="Q2", text="USPSTF recommends against initiation because of net cardiovascular harm in adults 70+",
                            recommendation_body="USPSTF", target={"population": "adults 70+", "outcome": "net cardiovascular harm"}),
    ]))
    assert inq.graph.claim("C1").issue_id == "Q1"
    assert inq.graph.claim("C2").issue_id == "Q2"
    assert inq.graph.standard_for(inq.graph.claim("C1")) == "preponderance"
    assert result["placed_by_rule"] == [{"claim_id": "C1", "from_issue": "Q2", "to_issue": "Q1",
                                         "body": "USPSTF", "population": "adults aged 60 and over", "outcome": "net cardiovascular harm"}]


def test_human_frame_edits_are_saved_and_keep_graph_references(tmp_path):
    answers = iter(["type Q1 empirical", "move C3 Q1", "drop Q2", 'add Q1 "A human alternative"', ""])
    h, store = make_harness(tmp_path, [], review_frame=True, ask=lambda _: next(answers))
    inq = h.run(rounds=1)
    event = next(e for e in store.events() if e["move"] == "human_frame")
    assert [e["command"] for e in event["summary"]["edits"]] == ["type", "move", "drop", "add"]
    assert inq.graph.issue("Q1").question_type == "empirical"
    assert inq.graph.claim("C3").issue_id == "Q1"
    assert inq.graph.issue("Q2").status == "dropped" and inq.graph.claims_for_issue("Q2") == []
    assert any(c.text == "A human alternative" and c.origin == "human" for c in inq.main_claims())
    assert not inq.graph.validate_refs() and store.verify_ledger()
