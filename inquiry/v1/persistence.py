"""Canonical event records and deterministic, model-free trace replay.

The hash chain detects accidental edits and inconsistent records.  It is not a
digital signature or a guarantee against an actor rewriting the entire chain.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class Ledger:
    def __init__(self, journal_path: str | Path | None = None) -> None:
        self.events: list[dict[str, Any]] = []
        self.journal_path = Path(journal_path) if journal_path is not None else None
        self._journal_failed = False
        if self.journal_path is not None:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            # A new attempt must never truncate or append to another attempt's
            # ledger. Inspection is read-only; this is deliberately not resume.
            with self.journal_path.open("x", encoding="utf-8"):
                pass

    def append(self, kind: str, data: Any) -> None:
        if self._journal_failed:
            raise RuntimeError("journal write previously failed; refusing to continue the event chain")
        event = {
            "sequence": len(self.events), "kind": kind,
            "data": copy.deepcopy(data),
            "previous_hash": self.events[-1]["hash"] if self.events else "0" * 64,
        }
        event["hash"] = digest(event)
        if self.journal_path is not None:
            try:
                with self.journal_path.open("a", encoding="utf-8") as journal:
                    journal.write(canonical(event) + "\n")
                    journal.flush()
                    os.fsync(journal.fileno())
            except OSError:
                # A partial write may already exist. Further appends would
                # silently corrupt the chain or duplicate its next sequence.
                self._journal_failed = True
                raise
        self.events.append(event)


def _verify_chain(events: list[dict[str, Any]]) -> None:
    previous = "0" * 64
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"ledger event invalid at event {index}")
        body = {key: value for key, value in event.items() if key != "hash"}
        if body.get("sequence") != index or body.get("previous_hash") != previous:
            raise ValueError(f"ledger linkage invalid at event {index}")
        if event.get("hash") != digest(body):
            raise ValueError(f"ledger content invalid at event {index}")
        previous = event["hash"]


def verify_events(events: list[dict[str, Any]]) -> None:
    _verify_chain(events)
    if not events or events[-1].get("kind") != "result":
        raise ValueError("ledger is incomplete: no final result event")


def inspect_journal(path: str | Path) -> dict[str, Any]:
    """Verify a journal and summarize its recorded calls without resuming it.

    ``complete`` means that the chain has a terminal result event, regardless
    of whether that result reports a complete, partial, or failed inquiry.
    An interrupted call without a usage event remains explicitly unaccounted
    for: known token/cost subtotals are never presented as complete totals.
    Malformed or edited events are rejected, including a torn JSON line.
    """
    events = []
    for index, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"journal JSON invalid at line {index + 1}") from exc
    _verify_chain(events)
    calls_started = sum(event.get("kind") == "worker_input" for event in events)
    usage_events = [event.get("data") for event in events if event.get("kind") == "worker_usage"]
    known_input = known_output = known_records = unknown_records = 0
    known_cost = 0.0
    tokens_complete = cost_complete = len(usage_events) == calls_started

    def token_count(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    for data in usage_events:
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, list) or not records:
            tokens_complete = cost_complete = False
            continue
        for record in records:
            if not isinstance(record, dict):
                unknown_records += 1
                tokens_complete = cost_complete = False
                continue
            input_tokens, output_tokens = record.get("input_tokens"), record.get("output_tokens")
            if (record.get("usage_known") is not False
                    and token_count(input_tokens) and token_count(output_tokens)):
                known_records += 1
                known_input += input_tokens
                known_output += output_tokens
            else:
                unknown_records += 1
                tokens_complete = False
            cost = record.get("cost_usd")
            if (isinstance(cost, (int, float)) and not isinstance(cost, bool)
                    and math.isfinite(cost) and cost >= 0):
                known_cost += cost
            else:
                cost_complete = False
    return {
        "complete": bool(events and events[-1].get("kind") == "result"),
        "event_count": len(events),
        "last_event_kind": events[-1].get("kind") if events else None,
        "calls_started": calls_started,
        "calls_with_usage": len(usage_events),
        "pending_calls": max(0, calls_started - len(usage_events)),
        "usage": {
            "known_usage_records": known_records, "unknown_usage_records": unknown_records,
            "usage_complete": tokens_complete,
            "input_tokens": known_input if tokens_complete else None,
            "output_tokens": known_output if tokens_complete else None,
            "known_input_tokens": known_input, "known_output_tokens": known_output,
            "cost_complete": cost_complete,
            "cost_usd": known_cost if cost_complete else None,
            "known_cost_usd": known_cost,
        },
    }


def _atomic_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def save_run(result: dict[str, Any], directory: str | Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    events = result.get("events", [])
    verify_events(events)
    expected = {key: value for key, value in result.items() if key != "events"}
    if events[-1]["data"] != expected:
        raise ValueError("result is not the result committed by its ledger")
    _atomic_text(directory / "ledger.jsonl", "".join(canonical(x) + "\n" for x in events))
    _atomic_text(directory / "result.json", json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    response = result.get("response", {})
    completion_label = "Inquiry completed" if "inquiry_completed" in response else "Legacy task completed"
    completion = response.get("inquiry_completed", response.get("task_completed", False))
    report = ["# Inquiry record", "", response.get("text", "No response was produced."), "",
              "## Run", "", f"- Status: {result.get('status')}",
              f"- Stop: {result.get('stop_reason')}", f"- Arm: {result.get('arm')}",
              f"- Evidence mode: {result.get('mode')}",
              f"- {completion_label}: {completion}", ""]
    for caveat in response.get("caveats", []):
        report.append(f"- {caveat}")
    _atomic_text(directory / "report.md", "\n".join(report) + "\n")
    return directory


def load_run(directory: str | Path) -> dict[str, Any]:
    directory = Path(directory)
    events = [json.loads(line) for line in (directory / "ledger.jsonl").read_text(encoding="utf-8").splitlines() if line]
    verify_events(events)
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    if result.get("events") != events:
        raise ValueError("result event list differs from ledger")
    if {key: value for key, value in result.items() if key != "events"} != events[-1]["data"]:
        raise ValueError("result payload differs from ledger")
    return result
