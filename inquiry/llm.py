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
        self.usage: list[dict[str, Any]] = []

    def _usage(self, response: Any) -> None:
        usage = response.usage
        self.usage.append({"provider": self.provider, "model": self.model,
                           "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens})

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
    provider = "anthropic"
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
        self._usage(resp)
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"{self.model} declined the request: {getattr(resp.stop_details, 'category', None)}")
        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
        if not text.strip() and resp.stop_reason == "max_tokens":
            raise RuntimeError(f"{self.model} hit max_tokens={max_tokens} before producing text; raise max_tokens")
        return text


class OpenAILLM(LLM):
    """Responses API JSON mode, with capability negotiation cached per handle.

    The models endpoint does not advertise parameter support. Try reasoning
    once and omit it if the API identifies it as unsupported; this avoids a
    model-name allowlist that becomes stale as new models are released.
    """

    provider = "openai"

    def __init__(self, model: str, reasoning_effort: str = "medium", temperature: float | None = None):
        import openai

        super().__init__()
        if reasoning_effort not in {"low", "medium", "high"}:
            raise ValueError("OpenAI effort must be low, medium or high")
        self.client = openai.OpenAI()
        self.model = self.name = model
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature
        self._reasoning_supported = True
        self._temperature_supported = True

    def complete(self, system: str, user: str, max_tokens: int = 16000) -> str:
        from openai import BadRequestError

        # A reasoning-capable model never receives sampling parameters.
        while True:
            params: dict[str, Any] = {
                "model": self.model, "instructions": system + "\nReturn a JSON object.",
                "input": user + "\n\nReturn a JSON object.", "max_output_tokens": max_tokens,
                "text": {"format": {"type": "json_object"}},
            }
            if self._reasoning_supported:
                params["reasoning"] = {"effort": self.reasoning_effort}
            elif self.temperature is not None and self._temperature_supported:
                params["temperature"] = self.temperature
            try:
                resp = self.client.responses.create(**params)
                break
            except BadRequestError as exc:
                body = exc.body if isinstance(exc.body, dict) else {}
                error = body.get("error", body)
                param = str(error.get("param", ""))
                message = str(error.get("message", "")).lower()
                unsupported = "unsupported" in message or "not supported" in message
                if (unsupported and self._reasoning_supported
                        and (param.startswith("reasoning") or "reasoning" in message)):
                    self._reasoning_supported = False
                    continue
                if unsupported and "temperature" in params and (param == "temperature" or "temperature" in message):
                    self._temperature_supported = False
                    continue
                raise
        self._usage(resp)
        if not resp.output_text.strip():
            raise RuntimeError(f"{self.model} returned no text (status={getattr(resp, 'status', 'unknown')}); "
                               f"max_output_tokens={max_tokens}")
        return resp.output_text


class FakeLLM(LLM):
    """
    Scripted responder. `script` maps a key (found in the system prompt's
    first line, e.g. the skill name) to either a dict or a callable taking
    the user message and returning a dict.
    """

    name = "fake"
    model = "fake"
    provider = "fake"

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
        self.usage.append({"provider": self.provider, "model": self.model,
                           "input_tokens": 0, "output_tokens": 0})
        return json.dumps(out)


def llm_from_env(role: str) -> LLM:
    """
    Build the proposer or critic from environment variables.

        INQUIRY_PROPOSER_MODEL  default claude-sonnet-5-5
        INQUIRY_CRITIC_MODEL    default claude-opus-5-5
    """
    defaults = {"proposer": "claude-sonnet-5-5", "critic": "claude-opus-5-5"}
    configured = os.environ.get(f"INQUIRY_{role.upper()}_MODEL", defaults[role])
    provider, model = configured.split(":", 1) if ":" in configured else ("anthropic", configured)
    provider, model = provider.strip().lower(), model.strip()
    if not model:
        raise ValueError(f"INQUIRY_{role.upper()}_MODEL needs a model name")
    effort = os.environ.get(f"INQUIRY_{role.upper()}_EFFORT", "medium")
    if provider == "openai":
        return OpenAILLM(model=model, reasoning_effort=effort)
    if provider == "anthropic":
        return AnthropicLLM(model=model, effort=effort)
    raise ValueError(f"unknown LLM provider: {provider}")
