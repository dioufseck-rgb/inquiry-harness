import pytest

from inquiry.bench import score_shape
from inquiry.llm import FakeLLM
from inquiry.moves import evaluate_move
from test_metrics import small_inquiry


def test_semantic_fallback_gets_notes_and_only_accepted_main_claims():
    inq = small_inquiry()
    ev = evaluate_move(inq)
    judge = FakeLLM({"shape_judge": {"match": True, "why": "A 12% rise is an increase."}})
    score = score_shape(inq, ev, {"shape": "accepted:increased", "notes": "A rise in X."}, judge)
    assert score["shape_match_regex"] is False
    assert score["shape_match_judge"] is True and score["shape_match"] is True
    assert len(judge.calls) == 1
    prompt = judge.calls[0][1]
    assert "A rise in X." in prompt and "X happened by about 12%" in prompt
    assert "X did not happen" not in prompt


@pytest.mark.parametrize("shape,remove_arguments", [("accepted:12%", False), ("accepted:other", True)])
def test_no_judge_when_regex_matches_or_main_has_no_accepted_answer(shape, remove_arguments):
    inq = small_inquiry()
    if remove_arguments:
        inq.graph.arguments.clear()
    judge = FakeLLM({})
    score = score_shape(inq, evaluate_move(inq), {"shape": shape}, judge)
    assert score["shape_match_judge"] is None and not judge.calls


def test_semantic_rejection_preserves_failed_score():
    inq = small_inquiry()
    judge = FakeLLM({"shape_judge": {"match": False, "why": "Wrong direction."}})
    score = score_shape(inq, evaluate_move(inq), {"shape": "accepted:decreased"}, judge)
    assert score["shape_match"] is False and score["shape_match_judge"] is False


def test_empty_retrieval_cannot_score_as_expected_undecided():
    inq = small_inquiry()
    inq.graph.evidence.clear()
    inq.graph.arguments.clear()
    judge = FakeLLM({})
    score = score_shape(inq, evaluate_move(inq), {"shape": "undecided"}, judge)
    assert score["shape_match_regex"] is True and score["shape_match"] is False
    assert score["shape_match_judge"] is None and not judge.calls
