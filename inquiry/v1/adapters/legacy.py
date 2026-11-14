"""Opt-in translation of historical scripted worker replies.

This is a compatibility aid for callers and tests, never a runtime fallback.
Original records and application artifacts must be retained by their owner.
"""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Mapping


def to_epistemic_response(response: Mapping[str, Any], graph: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Remove legacy business fields and retain only their epistemic content.

    A legacy deliverable may be a letter, so it is deliberately not copied into
    assessment. The original analytical text is retained. This mechanical
    translation supplies no additional warrant or substantive validation.
    """
    result = deepcopy(dict(response))
    legacy_action = result.pop("next_action", {})
    legacy_deliverable = result.pop("deliverable", None)
    completed = result.pop("task_completed", False)
    result.setdefault("inquiry_completed", completed)
    if "assessment" not in result and legacy_deliverable:
        result["assessment"] = result.get("text") or None
    if "information_needs" not in result:
        conditions = (graph or {}).get("conditions", {})
        conditions = conditions if isinstance(conditions, Mapping) else {}
        identifiers = legacy_action.get("condition_ids", []) if isinstance(legacy_action, Mapping) else []
        result["information_needs"] = []
        for identifier in identifiers if isinstance(identifiers, list) else []:
            record = conditions.get(identifier, {})
            text = record.get("text") if isinstance(record, Mapping) else None
            text = text if isinstance(text, str) and text.strip() else f"The evidence condition {identifier} remains unresolved."
            result["information_needs"].append({
                "condition_id": identifier,
                "question": f"What evidence resolves the condition {identifier}?",
                "what_would_resolve": text,
            })
    return result


class EpistemicWorkerAdapter:
    """Explicitly wrap a legacy scripted worker; never infer an adapter in core."""

    def __init__(self, worker: Any):
        self.worker = worker

    def __getattr__(self, name: str) -> Any:
        return getattr(self.worker, name)

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        raw = self.worker.complete(system, user, max_tokens=max_tokens)
        try:
            reply = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return raw
        if isinstance(reply, dict) and isinstance(reply.get("response"), Mapping):
            reply["response"] = to_epistemic_response(reply["response"], reply.get("graph"))
            return json.dumps(reply, ensure_ascii=False)
        return raw
