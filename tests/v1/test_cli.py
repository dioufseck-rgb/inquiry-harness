"""CLI safety and acceptance gates; all workers/experiments are mocked."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from inquiry.v1 import cli


@pytest.mark.parametrize("command", ["run", "bench"])
def test_demo_rejects_live_critic_before_constructing_any_sdk_worker(command, monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("No live worker may be constructed for a demo run")
    monkeypatch.setattr(cli.LLMWorker, "from_spec", staticmethod(forbidden))
    with pytest.raises(SystemExit) as raised:
        cli.main([command, "--demo", "--critic-model", "openai:must-not-run", "--out", str(tmp_path)])
    assert raised.value.code == 2


@pytest.mark.parametrize("effort,expected", [("none", None), ("high", "high")])
def test_effort_reaches_both_workers_without_a_network_call(effort, expected, monkeypatch, tmp_path):
    constructed = []
    invoked = []

    def construct(spec, *, effort):
        constructed.append((spec, effort))
        return SimpleNamespace(name=spec)

    def run(public_case, worker, **settings):
        invoked.append((worker.name, settings["critic"].name))
        return {"status": "complete", "stop_reason": "settled_for_purpose",
                "response": {"text": "A mocked response."}}

    monkeypatch.setattr(cli.LLMWorker, "from_spec", staticmethod(construct))
    monkeypatch.setattr(cli, "run_inquiry", run)
    monkeypatch.setattr(cli, "save_run", lambda result, out: Path(out))
    monkeypatch.setattr(cli, "score_run", lambda *args, **kwargs: {"human": {"status": "pending"}})
    exit_code = cli.main(["run", "--model", "openai:proposer", "--critic-model", "anthropic:critic",
                          "--effort", effort, "--out", str(tmp_path)])
    assert exit_code == 0
    assert set(constructed) == {("openai:proposer", expected), ("anthropic:critic", expected)}
    assert invoked == [("openai:proposer", "anthropic:critic")]


SUCCESS_SUMMARY = {
    "attempts": 1, "failed_runs": 0,
    "structural_status_counts": {"pass": 1}, "smoke_status_counts": {"pass": 1},
    "human_review_status_counts": {"pending": 1},
}


def mock_bench(monkeypatch, summary):
    monkeypatch.setattr(cli, "_code_version", lambda: "test-code")
    monkeypatch.setattr(cli, "_code_dirty", lambda: False)
    monkeypatch.setattr(cli, "_module_hash", lambda name: "test-hash:" + name)
    monkeypatch.setattr(cli, "run_experiments", lambda *args, **kwargs: {"summary": deepcopy(summary)})


@pytest.mark.parametrize("changes", [
    {"failed_runs": 1},
    {"structural_status_counts": {"fail": 1}},
    {"structural_status_counts": {"error": 1}},
    {"structural_status_counts": {"unassessed": 1}},
    {"smoke_status_counts": {"fail": 1}},
    {"smoke_status_counts": {"not_checkable": 1}},
])
def test_bench_failure_cannot_return_a_success_exit_code(changes, monkeypatch, tmp_path):
    summary = {**SUCCESS_SUMMARY, **changes}
    mock_bench(monkeypatch, summary)
    result = cli.main(["bench", "--demo", "--baseline-only", "--questions", "question_001",
                       "--arms", "ordinary", "--modes", "supplied", "--out", str(tmp_path)])
    assert result != 0


def test_pending_human_review_alone_does_not_fail_a_development_bench(monkeypatch, tmp_path):
    mock_bench(monkeypatch, SUCCESS_SUMMARY)
    assert cli.main(["bench", "--demo", "--baseline-only", "--questions", "question_001",
                     "--arms", "ordinary", "--modes", "supplied", "--out", str(tmp_path)]) == 0
