"""
LLM access.

One interface: complete_json(system, user, schema). The skill text is the
system prompt, the rendered state view is the user message, and the reply
is parsed and validated against a pydantic schema. One repair attempt is
made if validation fails, feeding the error back to the model.

Two implementations:
    AnthropicLLM  - the real thing
    FakeLLM       - returns scripted outputs, for tests and dry runs

The harness keeps two LLM handles: `proposer` for the constructive moves
and `critic` for critique. They should be configured with different models
so the critique is not the same model reviewing its own work.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def extract_json(text: str) -> Any:
    """Pull the first JSON object out of a reply that may carry prose or fences."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in reply: {text[:120]!r}")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as e:
        raise ValueError(f"malformed or truncated JSON in reply ({e.msg} at char {e.pos}); "
                         f"reply ends: {text[-120:]!r}") from e
    return obj


class LLM:
    name: str = "base"

    def __init__(self) -> None:
        self.repairs: list[dict[str, str]] = []  # one entry per reply that failed its contract and was repaired

    def complete(self, system: str, user: str, max_tokens: int = 16000) -> str:  # pragma: no cover
        raise NotImplementedError

    def complete_json(self, system: str, user: str, schema: Type[T], max_tokens: int = 16000) -> T:
        reply = self.complete(system, user, max_tokens=max_tokens)
        try:
            return schema.model_validate(extract_json(reply))
        except (ValidationError, ValueError, json.JSONDecodeError) as first_error:
            skill = system.splitlines()[0] if system else ""
            if not hasattr(self, "repairs"):
                self.repairs = []
            self.repairs.append({"skill": skill, "error": str(first_error)[:300], "reply_head": reply[:300]})
            repair = (
                f"{user}\n\n---\nYour previous reply did not match the required output schema.\n"
                f"Error: {first_error}\n\nReturn only a corrected JSON object, complete, with every required field."
            )
            reply = self.complete(system, repair, max_tokens=max_tokens)
            return schema.model_validate(extract_json(reply))


class AnthropicLLM(LLM):
    """
    Claude 5 family models reject sampling parameters (temperature, top_p);
    depth is controlled by `effort` instead, and thinking is adaptive by
    default. The system prompt (skill text) is stable across calls, so it is
    marked for prompt caching.
    """

    def __init__(self, model: str, effort: str = "medium"):
        import anthropic  # imported here so tests can run without the SDK configured

        super().__init__()
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self.model = model
        self.effort = effort
        self.name = model

    def complete(self, system: str, user: str, max_tokens: int = 4000) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            output_config={"effort": self.effort},
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"{self.model} declined the request: {getattr(resp.stop_details, 'category', None)}")
        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
        if not text.strip() and resp.stop_reason == "max_tokens":
            raise RuntimeError(f"{self.model} hit max_tokens={max_tokens} before producing text; raise max_tokens")
        return text


class FakeLLM(LLM):
    """
    Scripted responder. `script` maps a key (found in the system prompt's
    first line, e.g. the skill name) to either a dict or a callable taking
    the user message and returning a dict.
    """

    name = "fake"

    def __init__(self, script: dict[str, Any]):
        super().__init__()
        self.script = script
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, max_tokens: int = 4000) -> str:
        self.calls.append((system, user))
        key = next((k for k in self.script if k in system.splitlines()[0]), None)
        if key is None:
            raise KeyError(f"FakeLLM has no script for system prompt starting: {system[:60]!r}")
        out = self.script[key]
        if callable(out):
            out = out(user)
        return json.dumps(out)


def llm_from_env(role: str) -> LLM:
    """
    Build the proposer or critic from environment variables.

        INQUIRY_PROPOSER_MODEL  default claude-sonnet-5-5
        INQUIRY_CRITIC_MODEL    default claude-opus-5-5
    """
    defaults = {"proposer": "claude-sonnet-5-5", "critic": "claude-opus-5-5"}
    model = os.environ.get(f"INQUIRY_{role.upper()}_MODEL", defaults[role])
    effort = os.environ.get(f"INQUIRY_{role.upper()}_EFFORT", "medium" if role == "proposer" else "high")
    return AnthropicLLM(model=model, effort=effort)
