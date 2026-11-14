"""Durable call checkpoints remain inspectable without certifying completion."""

import json
import subprocess
import sys

import pytest

from inquiry.v1.persistence import Ledger, inspect_journal, load_run, save_run, verify_events


def read_events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_interrupted_process_retains_prior_events_usage_and_pending_call(tmp_path):
    path = tmp_path / "attempt" / "events.jsonl"
    process = subprocess.run(
        [sys.executable, "-c", """
import os
import sys
from inquiry.v1.persistence import Ledger

ledger = Ledger(sys.argv[1])
ledger.append("case", {"id": "interrupted-example"})
ledger.append("worker_input", {"role": "proposer", "user": "First question"})
ledger.append("worker_output", {"role": "proposer", "reply": "First response"})
ledger.append("worker_usage", {"role": "proposer", "records": [
    {"input_tokens": 17, "output_tokens": 9, "usage_known": True, "cost_usd": 0.04}
]})
ledger.append("worker_input", {"role": "critic", "user": "Second question"})
os._exit(19)
""", str(path)],
        capture_output=True, text=True, check=False,
    )
    assert process.returncode == 19, process.stderr
    events = read_events(path)
    assert [event["kind"] for event in events] == [
        "case", "worker_input", "worker_output", "worker_usage", "worker_input",
    ]
    summary = inspect_journal(path)
    assert not summary["complete"]
    assert summary["event_count"] == 5
    assert summary["calls_started"] == 2
    assert summary["calls_with_usage"] == summary["pending_calls"] == 1
    assert summary["last_event_kind"] == "worker_input"
    assert summary["usage"]["known_input_tokens"] == 17
    assert summary["usage"]["known_output_tokens"] == 9
    assert summary["usage"]["known_cost_usd"] == 0.04
    assert summary["usage"]["input_tokens"] is None
    assert summary["usage"]["cost_usd"] is None
    assert not summary["usage"]["usage_complete"]
    assert not summary["usage"]["cost_complete"]
    with pytest.raises(ValueError, match="incomplete"):
        verify_events(events)
    with pytest.raises(ValueError, match="incomplete"):
        save_run({"events": events}, tmp_path / "cannot-complete")


def test_journal_is_exclusive_and_never_overwrites_an_earlier_attempt(tmp_path):
    path = tmp_path / "events.jsonl"
    ledger = Ledger(journal_path=path)
    ledger.append("worker_input", {"role": "proposer"})
    previous = path.read_bytes()
    with pytest.raises(FileExistsError):
        Ledger(journal_path=path)
    assert path.read_bytes() == previous


@pytest.mark.parametrize("tamper", ["content", "linkage", "torn_line"])
def test_journal_inspection_rejects_modified_or_truncated_events(tmp_path, tamper):
    path = tmp_path / "events.jsonl"
    ledger = Ledger(path)
    ledger.append("case", {"id": "original"})
    ledger.append("worker_input", {"role": "proposer"})
    events = read_events(path)
    if tamper == "content":
        events[0]["data"]["id"] = "edited"
    elif tamper == "linkage":
        events[1]["previous_hash"] = "0" * 64
    if tamper == "torn_line":
        path.write_text(path.read_text(encoding="utf-8")[:-15], encoding="utf-8")
    else:
        path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid"):
        inspect_journal(path)


@pytest.mark.parametrize("records", [[], [
    {"input_tokens": None, "output_tokens": None, "usage_known": False, "cost_usd": None},
]])
def test_returned_call_without_known_usage_never_becomes_zero_cost(tmp_path, records):
    path = tmp_path / "events.jsonl"
    ledger = Ledger(path)
    ledger.append("worker_input", {"role": "proposer"})
    ledger.append("worker_error", {"role": "proposer", "error_type": "TimeoutError"})
    ledger.append("worker_usage", {"role": "proposer", "records": records,
                                   "input_reservation": 400, "output_reservation": 100})
    summary = inspect_journal(path)
    assert summary["pending_calls"] == 0
    assert summary["calls_with_usage"] == 1
    assert summary["usage"]["input_tokens"] is None
    assert summary["usage"]["output_tokens"] is None
    assert summary["usage"]["cost_usd"] is None
    assert not summary["usage"]["usage_complete"]


def test_terminal_result_remains_compatible_with_final_save_and_load(tmp_path):
    path = tmp_path / "events.jsonl"
    ledger = Ledger(path)
    ledger.append("case", {"id": "completed-example"})
    ledger.append("worker_input", {"role": "proposer"})
    ledger.append("worker_usage", {"role": "proposer", "records": [
        {"input_tokens": 17, "output_tokens": 9, "cost_usd": 0.04},
    ]})
    result = {"status": "partial", "stop_reason": "resource_limit", "arm": "harness",
              "mode": "documents", "response": {"text": "A bounded partial result.",
                                                   "task_completed": False}}
    ledger.append("result", result)
    result["events"] = ledger.events
    verify_events(ledger.events)
    summary = inspect_journal(path)
    assert summary["complete"]  # Journal completion is not task completion.
    assert summary["usage"]["usage_complete"]
    assert summary["usage"]["input_tokens"] == 17
    assert summary["usage"]["output_tokens"] == 9
    assert summary["usage"]["cost_usd"] == 0.04
    directory = save_run(result, tmp_path / "saved")
    assert load_run(directory) == result
    assert (directory / "ledger.jsonl").read_bytes() == path.read_bytes()


def test_empty_new_journal_is_inspectable_but_not_complete(tmp_path):
    path = tmp_path / "events.jsonl"
    Ledger(path)
    summary = inspect_journal(path)
    assert not summary["complete"]
    assert summary["event_count"] == summary["calls_started"] == 0
    assert summary["last_event_kind"] is None


def test_memory_only_ledger_retains_its_existing_interface():
    ledger = Ledger()
    ledger.append("result", {"status": "complete"})
    verify_events(ledger.events)
    assert ledger.journal_path is None
