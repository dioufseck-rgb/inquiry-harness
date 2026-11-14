"""Provider-neutral worker protocol and explicit SDK/recorded adapters.

RecordedWorker and the demonstration worker are test instruments. They are never
reported as live language-model experiments.
"""
from __future__ import annotations

import copy
from importlib.metadata import PackageNotFoundError, version as package_version
import json
from math import isfinite
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Mapping, Protocol


class Worker(Protocol):
    name: str
    model: str
    provider: str
    usage: list[dict[str, Any]]

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str: ...


class RecordedWorker:
    """Repeat fixed responses; useful for isolated, reproducible worker tests."""
    provider = "recorded"
    model = name = "recorded-test-worker"
    is_test_instrument = True

    def __init__(self, replies: list[Any]):
        self.replies = copy.deepcopy(replies)
        self.calls: list[dict[str, Any]] = []
        self.usage: list[dict[str, Any]] = []

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        if not self.replies:
            raise RuntimeError("recorded worker exhausted")
        result = self.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        self.usage.append({"provider": self.provider, "model": self.model,
                           "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        return result if isinstance(result, str) else json.dumps(result)


class LLMWorker:
    """One SDK request per invocation, without retries or capability negotiation.

    The supplied handle provides ``provider``, ``model``, ``client`` and optional
    effort fields. Its legacy ``complete`` method is never called. The runtime
    owns retries and JSON repair. SDK usage, including cached input, is normalized
    here; absent usage and unpriced billing remain explicitly unknown.
    """
    is_test_instrument = False

    def __init__(self, llm: Any):
        self.llm = llm
        self.name = getattr(llm, "name", "custom")
        self.provider = getattr(llm, "provider", "custom")
        self.model = getattr(llm, "model", self.name)
        if self.provider not in {"openai", "anthropic"}:
            raise ValueError("LLMWorker requires an explicit openai or anthropic SDK handle")
        try:
            self.sdk_version: str | None = package_version(self.provider)
        except PackageNotFoundError:
            self.sdk_version = None
        if not callable(getattr(getattr(llm, "client", None), "with_options", None)):
            raise ValueError("SDK client must support with_options for explicit timeout and retry control")
        self.effort = getattr(llm, "reasoning_effort", getattr(llm, "effort", None))
        if self.effort not in {None, "low", "medium", "high"}:
            raise ValueError("effort must be low, medium, high, or None")
        existing_usage = getattr(llm, "usage", None)
        self.usage: list[dict[str, Any]] = existing_usage if isinstance(existing_usage, list) else []
        self.timeout_seconds = 60.0

    @classmethod
    def from_spec(cls, spec: str, effort: str | None = "medium") -> "LLMWorker":
        if not isinstance(spec, str) or ":" not in spec:
            raise ValueError("model must be explicit provider:model")
        provider, model = spec.split(":", 1)
        provider, model = provider.strip().lower(), model.strip()
        if not model:
            raise ValueError("model name is empty")
        if effort not in {None, "low", "medium", "high"}:
            raise ValueError("effort must be low, medium, high, or None")
        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(max_retries=0, timeout=60.0)
        elif provider == "anthropic":
            from anthropic import Anthropic
            client = Anthropic(max_retries=0, timeout=60.0)
        else:
            raise ValueError(f"unsupported provider {provider!r}")
        return cls(SimpleNamespace(provider=provider, model=model, name=model,
                                   client=client, effort=effort, usage=[]))

    def set_timeout(self, seconds: float) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not isfinite(seconds) or seconds <= 0:
            raise ValueError("timeout must be finite and positive")
        self.timeout_seconds = float(seconds)

    @staticmethod
    def _field(value: Any, field: str, default: Any = None) -> Any:
        return value.get(field, default) if isinstance(value, Mapping) else getattr(value, field, default)

    @staticmethod
    def _tokens(value: Any, *, optional: bool = False) -> int | None:
        if value is None and optional:
            return 0
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    def _record_usage(self, entry: dict[str, Any], response: Any) -> None:
        usage = self._field(response, "usage")
        if usage is None:
            return
        raw_input = self._tokens(self._field(usage, "input_tokens"))
        output = self._tokens(self._field(usage, "output_tokens"))
        entry["raw_input_tokens"] = raw_input
        entry["output_tokens"] = output
        if self.provider == "anthropic":
            # Anthropic reports these as disjoint input partitions. OpenAI's
            # cached_input_tokens is already included in input_tokens instead.
            created = self._tokens(self._field(usage, "cache_creation_input_tokens"), optional=True)
            read = self._tokens(self._field(usage, "cache_read_input_tokens"), optional=True)
            entry.update(cache_creation_input_tokens=created, cache_read_input_tokens=read)
            entry["input_tokens"] = (raw_input + created + read
                                     if all(v is not None for v in (raw_input, created, read)) else None)
            breakdown = self._field(usage, "cache_creation")
            if breakdown is not None:
                entry["cache_creation"] = {
                    key: self._tokens(self._field(breakdown, key), optional=True)
                    for key in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
                }
        else:
            entry["input_tokens"] = raw_input
            details = self._field(usage, "input_tokens_details")
            entry["cached_input_tokens"] = self._tokens(self._field(details, "cached_tokens"), optional=True)
            output_details = self._field(usage, "output_tokens_details")
            entry["reasoning_output_tokens"] = self._tokens(self._field(output_details, "reasoning_tokens"), optional=True)
        entry["usage_known"] = entry["input_tokens"] is not None and output is not None

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
            raise ValueError("max_tokens must be a positive integer")
        if not isinstance(system, str) or not isinstance(user, str):
            raise ValueError("system and user must be text")
        started = perf_counter()
        entry: dict[str, Any] = {
            "provider": self.provider, "model": self.model, "effort": self.effort,
            "requested_model": self.model, "resolved_model": None,
            "sdk_package": self.provider, "sdk_version": self.sdk_version,
            "adapter_version": "v1-single-request-1",
            "api_attempts": 0, "failed_api_attempts": 0, "request_status": "not_attempted",
            "invocation_succeeded": False, "usage_known": False,
            "input_tokens": None, "output_tokens": None, "cost_usd": None,
            "timeout_seconds": self.timeout_seconds, "max_output_tokens": max_tokens,
            "max_retries": 0,
        }
        try:
            client = self.llm.client.with_options(timeout=self.timeout_seconds, max_retries=0)
            if self.provider == "openai":
                params: dict[str, Any] = {
                    "model": self.model, "instructions": system + "\nReturn a JSON object.",
                    "input": user + "\n\nReturn a JSON object.",
                    "max_output_tokens": max_tokens, "text": {"format": {"type": "json_object"}},
                }
                if self.effort is not None:
                    params["reasoning"] = {"effort": self.effort}
                entry["api_attempts"] = 1
                response = client.responses.create(**params)
            else:
                params = {
                    "model": self.model, "max_tokens": max_tokens,
                    "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                    "messages": [{"role": "user", "content": user}],
                }
                if self.effort is not None:
                    params["output_config"] = {"effort": self.effort}
                entry["api_attempts"] = 1
                response = client.messages.create(**params)
            entry.update(request_status="completed", provider_request_id=self._field(response, "_request_id"),
                         provider_response_id=self._field(response, "id"),
                         resolved_model=self._field(response, "model"))
            self._record_usage(entry, response)
            if self.provider == "openai":
                text = self._field(response, "output_text", "")
            else:
                if self._field(response, "stop_reason") == "refusal":
                    raise RuntimeError("Provider declined this request")
                text = "".join(self._field(block, "text", "") for block in self._field(response, "content", [])
                               if self._field(block, "type") == "text")
            if not isinstance(text, str) or not text.strip():
                raise RuntimeError("Provider returned no text within the supplied request limits")
            entry["invocation_succeeded"] = True
            return text
        except Exception as error:
            if entry["request_status"] != "completed" and entry["api_attempts"]:
                entry.update(request_status="failed", failed_api_attempts=1)
            entry.update(error_type=type(error).__name__, http_status=getattr(error, "status_code", None))
            raise
        finally:
            entry["elapsed_seconds"] = perf_counter() - started
            self.usage.append(entry)
