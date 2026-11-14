"""Canonical event records and deterministic, model-free trace replay.

The hash chain detects accidental edits and inconsistent records.  It is not a
digital signature or a guarantee against an actor rewriting the entire chain.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class Ledger:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def append(self, kind: str, data: Any) -> None:
        event = {
            "sequence": len(self.events), "kind": kind,
            "data": copy.deepcopy(data),
            "previous_hash": self.events[-1]["hash"] if self.events else "0" * 64,
        }
        event["hash"] = digest(event)
        self.events.append(event)


def verify_events(events: list[dict[str, Any]]) -> None:
    previous = "0" * 64
    for index, event in enumerate(events):
        body = {key: value for key, value in event.items() if key != "hash"}
        if body.get("sequence") != index or body.get("previous_hash") != previous:
            raise ValueError(f"ledger linkage invalid at event {index}")
        if event.get("hash") != digest(body):
            raise ValueError(f"ledger content invalid at event {index}")
        previous = event["hash"]
    if not events or events[-1].get("kind") != "result":
        raise ValueError("ledger is incomplete: no final result event")


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
    report = ["# Controlled inquiry", "", response.get("text", "No response was produced."), "",
              "## Run", "", f"- Status: {result.get('status')}",
              f"- Stop: {result.get('stop_reason')}", f"- Arm: {result.get('arm')}",
              f"- Evidence mode: {result.get('mode')}",
              f"- Task completed: {response.get('task_completed', False)}", ""]
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
