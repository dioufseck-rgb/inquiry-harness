from pathlib import Path

import pytest

from inquiry import moves
from inquiry.closure import whole_question_answer
from inquiry.metrics import metrics
from inquiry.state import Inquiry


@pytest.mark.parametrize("folder", ["E6/sonnet", "E6/sol", "E6-generalisation/energy", "E6-generalisation/genai"])
def test_saved_components_do_not_close_main_question(folder, monkeypatch):
    inq = Inquiry.model_validate_json((Path("experiments") / folder / "inquiry.json").read_text(encoding="utf-8"))
    ev = moves.evaluate_move(inq)
    assert whole_question_answer(inq.graph, ev) is None
    result = moves.stop(inq, ev, rounds_left=1, new_evidence_this_round=1)
    assert result.decision == "continue" and "no whole-question answer" in result.reason
    assert "main issue answered" not in result.reason
    monkeypatch.setattr(moves, "load_bearing", lambda *args: [])
    assert "components accepted; compose or extend scope" in moves.reflect(inq, ev).directive
    assert not metrics(inq, ev)["whole_question_answered"]
