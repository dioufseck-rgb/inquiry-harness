"""CLI safety and acceptance gates; all workers/experiments are mocked."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from inquiry.v1 import cli
from inquiry.v1.adapters.hardship import to_inquiry_request
from inquiry.v1.contracts import validate_inquiry_request
from inquiry.v1.packets import load_packet


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


def test_neutral_request_never_loads_a_packet_or_hardship_expectation(monkeypatch, tmp_path):
    request = to_inquiry_request(load_packet().public("question_001"))
    request["question"]["id"] = "arbitrary/external-question"
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request))
    calls = []

    def forbidden(*args, **kwargs):
        raise AssertionError("A neutral request must not select a benchmark packet or expectation")

    def run(public, worker, **settings):
        assert public == request
        return {"status": "complete", "stop_reason": "settled_for_purpose", "response": {"text": "Mocked epistemic result."}}

    def score(result, public, **settings):
        calls.append(settings)
        return {"smoke": {"status": "not_configured"}}

    monkeypatch.setattr(cli, "load_packet", forbidden)
    monkeypatch.setattr(cli, "hardship_smoke_expectation", forbidden)
    monkeypatch.setattr(cli.LLMWorker, "from_spec", staticmethod(lambda *args, **kwargs: SimpleNamespace(name="recorded")))
    monkeypatch.setattr(cli, "run_inquiry", run)
    monkeypatch.setattr(cli, "save_run", lambda result, out: Path(out))
    monkeypatch.setattr(cli, "score_run", score)
    assert cli.main(["run", "--request", str(source), "--model", "test:recorded", "--out", str(tmp_path)]) == 0
    assert calls == [{"answer_spec": None, "smoke_expectation": None}]


def test_export_emits_the_neutral_service_request(tmp_path):
    destination = tmp_path / "request.json"
    assert cli.main(["export", "--question", "question_004", "--out", str(destination)]) == 0
    request = json.loads(destination.read_text())
    assert validate_inquiry_request(request) == request
    assert "required_form" not in request["question"]["profile"]
    assert request["question"]["target"] == {"kind": "policy", "form": "rule_consequence"}


def test_legacy_request_is_rejected_before_worker_construction(monkeypatch, tmp_path):
    source = tmp_path / "legacy.json"
    source.write_text(json.dumps(load_packet().public("question_001")))

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid neutral input must be rejected before a worker is constructed")

    monkeypatch.setattr(cli.LLMWorker, "from_spec", staticmethod(forbidden))
    with pytest.raises(SystemExit) as raised:
        cli.main(["run", "--request", str(source), "--model", "test:never-call", "--out", str(tmp_path)])
    assert raised.value.code == 2


def test_custom_authoring_packet_requires_its_explicit_adapter(tmp_path):
    with pytest.raises(SystemExit) as raised:
        cli.main(["run", "--packet", str(tmp_path / "custom.json"), "--demo", "--out", str(tmp_path)])
    assert raised.value.code == 2


@pytest.mark.parametrize("legacy", [False, True])
def test_replay_adapter_is_opt_in(legacy, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(cli, "load_run", lambda directory: {"original": True})
    monkeypatch.setattr(cli, "replay_run", lambda result, **kwargs: seen.append(kwargs) or {"evaluation_reproduced": True})
    arguments = ["replay", str(tmp_path)] + (["--legacy-hardship"] if legacy else [])
    assert cli.main(arguments) == 0
    assert seen == ([{"request_adapter": to_inquiry_request}] if legacy else [{}])
