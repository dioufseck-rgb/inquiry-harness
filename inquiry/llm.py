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
        raise ValueError("no JSON object in reply")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("unbalanced JSON object in reply")


class LLM:
    name: str = "base"

    def complete(self, system: str, user: str, max_tokens: int = 4000) -> str:  # pragma: no cover
        raise NotImplementedError

    def complete_json(self, system: str, user: str, schema: Type[T], max_tokens: int = 4000) -> T:
        reply = self.complete(system, user, max_tokens=max_tokens)
        try:
            return schema.model_validate(extract_json(reply))
        except (ValidationError, ValueError, json.JSONDecodeError) as first_error:
            repair = (
                f"{user}\n\n---\nYour previous reply did not match the required output schema.\n"
                f"Error: {first_error}\n\nReturn only a corrected JSON object."
            )
            reply = self.complete(system, repair, max_tokens=max_tokens)
            return schema.model_validate(extract_json(reply))


class AnthropicLLM(LLM):
    def __init__(self, model: str, temperature: float = 0.2):
        import anthropic  # imported here so tests can run without the SDK configured

        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self.model = model
        self.temperature = temperature
        self.name = model

    def complete(self, system: str, user: str, max_tokens: int = 4000) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=self.temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")


class FakeLLM(LLM):
    """
    Scripted responder. `script` maps a key (found in the system prompt's
    first line, e.g. the skill name) to either a dict or a callable taking
    the user message and returning a dict.
    """

    name = "fake"

    def __init__(self, script: dict[str, Any]):
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
    temp = 0.2 if role == "proposer" else 0.4
    return AnthropicLLM(model=model, temperature=temp)
