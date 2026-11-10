"""
Persistence for an inquiry.

    runs/<inquiry_id>/
        inquiry.json      the full state, rewritten after every move
        ledger.jsonl      append-only, hash-chained record of every move
        sources/<id>.txt  extracted text of every fetched source

The ledger is what makes an inquiry auditable afterwards: which move ran,
in what order, what it changed, and what the state hash was at each step.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .state import Inquiry, now_iso


class InquiryStore:
    def __init__(self, root: Path | str, inquiry_id: str):
        self.dir = Path(root) / inquiry_id
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "sources").mkdir(exist_ok=True)
        self.state_path = self.dir / "inquiry.json"
        self.ledger_path = self.dir / "ledger.jsonl"

    # -- state ---------------------------------------------------------------

    def save(self, inquiry: Inquiry) -> None:
        self.state_path.write_text(inquiry.model_dump_json(indent=2), encoding="utf-8")

    def load(self) -> Inquiry:
        return Inquiry.model_validate_json(self.state_path.read_text(encoding="utf-8"))

    @staticmethod
    def exists(root: Path | str, inquiry_id: str) -> bool:
        return (Path(root) / inquiry_id / "inquiry.json").exists()

    # -- source text -----------------------------------------------------------

    def write_source_text(self, source_id: str, text: str) -> str:
        path = self.dir / "sources" / f"{source_id}.txt"
        path.write_text(text, encoding="utf-8")
        return str(path.relative_to(self.dir))

    def read_source_text(self, source_id: str) -> str:
        path = self.dir / "sources" / f"{source_id}.txt"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    # -- ledger ------------------------------------------------------------------

    def _last_hash(self) -> str:
        if not self.ledger_path.exists():
            return "0" * 64
        last = ""
        with self.ledger_path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = line
        return json.loads(last)["hash"] if last else "0" * 64

    def append_event(self, move: str, inquiry: Inquiry, summary: dict[str, Any],
                     usage: list[dict[str, Any]] | None = None) -> dict:
        state_hash = hashlib.sha256(inquiry.model_dump_json().encode("utf-8")).hexdigest()
        event = {
            "ts": now_iso(),
            "move": move,
            "round": inquiry.round,
            "summary": summary,
            "state_hash": state_hash,
            "prev_hash": self._last_hash(),
        }
        if usage is not None:
            event["usage"] = usage
        payload = json.dumps(event, sort_keys=True, ensure_ascii=False)
        event["hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self.ledger_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def verify_ledger(self) -> bool:
        """Recompute the chain; return True if no event was altered or removed."""
        prev = "0" * 64
        if not self.ledger_path.exists():
            return True
        with self.ledger_path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                event = json.loads(line)
                claimed = event.pop("hash")
                if event["prev_hash"] != prev:
                    return False
                payload = json.dumps(event, sort_keys=True, ensure_ascii=False)
                if hashlib.sha256(payload.encode("utf-8")).hexdigest() != claimed:
                    return False
                prev = claimed
        return True

    def events(self) -> list[dict]:
        if not self.ledger_path.exists():
            return []
        return [json.loads(l) for l in self.ledger_path.read_text(encoding="utf-8").splitlines() if l.strip()]
