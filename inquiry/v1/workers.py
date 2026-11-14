"""Provider-neutral worker protocol and explicit SDK/recorded adapters.

RecordedWorker and the demonstration worker are test instruments. They are never
reported as live language-model experiments.
"""
from __future__ import annotations

import copy
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version as package_version
import json
from math import isfinite
import re
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Mapping, Protocol

from .protocol import OutputProtocolError, parse_single_json_object


class ProviderOutputError(RuntimeError):
    """A completed SDK request did not produce one admissible answer value."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


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
    owns retries and any repair invocations. SDK usage, including cached input, is normalized
    here; absent usage and unpriced billing remain explicitly unknown.

    ``set_output_schema`` is an optional adapter capability. Schemas are passed
    unchanged to the selected provider; local role validation remains the
    controller's responsibility. Non-strict OpenAI schemas preserve dynamic
    graph maps instead of rewriting them as closed objects. An unsupported
    provider schema is one visible failed request, never a negotiated fallback.
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
        self.output_schema: dict[str, Any] | None = None

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

    def set_output_schema(self, name: str, schema: dict[str, Any], *, strict: bool = False) -> None:
        """Select the role's JSON Schema without changing its data representation.

        Strict mode is an OpenAI setting. Anthropic's schema output has no
        equivalent strict flag; its SDK receives the same schema and either
        accepts it or surfaces an error. This method does no capability probing.
        """
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) is None:
            raise ValueError("output schema name must contain 1-64 letters, digits, underscores, or dashes")
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ValueError("output schema must describe a JSON object")
        if not isinstance(strict, bool):
            raise ValueError("output schema strict must be a boolean")
        # JSON round-trip both checks the schema and detaches it from mutable
        # caller-owned records. Dynamic additionalProperties remain intact.
        try:
            schema_copy = json.loads(json.dumps(schema, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise ValueError("output schema must be finite JSON data") from exc
        self.output_schema = {"name": name, "schema": schema_copy, "strict": strict}

    @staticmethod
    def _field(value: Any, field: str, default: Any = None) -> Any:
        return value.get(field, default) if isinstance(value, Mapping) else getattr(value, field, default)

    @staticmethod
    def _tokens(value: Any, *, optional: bool = False) -> int | None:
        if value is None and optional:
            return 0
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    @classmethod
    def _text_field(cls, value: Any, field: str) -> str | None:
        result = cls._field(value, field)
        return result if isinstance(result, str) else None

    def _normalize_duplicate_messages(self, entry: dict[str, Any], items: list[dict[str, Any]],
                                      texts: list[Any]) -> bool:
        """Recognize repeated complete final answers, never select among answers.

        The declared admission channel has already separated and recorded
        non-operative commentary. Every candidate must be a completed assistant
        final-answer message with exactly one ordinary text block. All text must
        match exactly, and that common text must be one complete JSON object.
        No trimming, semantic JSON equivalence, or fragment assembly is permitted.
        The original items remain untouched.
        """
        if self.provider != "openai" or entry["provider_status"] != "completed":
            return False
        messages = []
        for item in items:
            if item["type"] == "reasoning":
                continue
            if (item["type"] != "message" or not item.get("id")
                    or item.get("status") != "completed" or item.get("role") != "assistant"
                    or item.get("phase") != "final_answer"):
                return False
            blocks = item.get("content", [])
            if len(blocks) != 1 or blocks[0]["type"] != "output_text":
                return False
            messages.append(item)
        if len(messages) != len(texts) or len(messages) < 2:
            return False
        common_text = texts[0]
        if not isinstance(common_text, str) or any(text != common_text for text in texts[1:]):
            return False
        try:
            parse_single_json_object(common_text)
        except OutputProtocolError:
            return False
        indexes = [{"item_index": item["index"], "content_index": item["content"][0]["index"]}
                   for item in messages]
        entry["provider_output_normalization"] = {
            "kind": "exact_duplicate_final_answer_messages",
            "retained": indexes[0], "duplicates": indexes[1:],
            "duplicate_count": len(indexes) - 1,
        }
        return True

    @staticmethod
    def _record_openai_admission(entry: dict[str, Any], items: list[dict[str, Any]]) -> None:
        """Declare channel candidates independently of their JSON contents."""
        messages = [item for item in items if item["type"] == "message"]
        finals = [item["index"] for item in messages if item["phase"] == "final_answer"]
        legacy = (len(messages) == 1 and messages[0]["phase"] is None
                  and "invalid_phase_type" not in messages[0])
        entry["provider_output_admission"] = {
            "policy": "openai_final_answer_v1",
            "channel": "legacy_single_unphased" if legacy else "final_answer",
            "candidate_final_item_indexes": finals,
            "candidate_item_indexes": [messages[0]["index"]] if legacy else finals,
            "excluded_commentary": [
                {"item_index": item["index"],
                 "content_indexes": [block["index"] for block in item["content"]],
                 "reason": "phase_commentary_nonoperative"}
                for item in messages if item["phase"] == "commentary"
            ],
            "selected": None,
        }

    @staticmethod
    def _openai_answer_candidates(entry: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Use documented message phases, with one explicit legacy exception.

        Commentary is retained in the raw record and never parsed as an
        operation or evidence. Missing/unknown phases in a multi-message reply
        are ambiguous; message position and apparent JSON validity cannot
        resolve them. A sole unphased assistant message is the legacy channel.
        """
        admission = entry["provider_output_admission"]
        legacy = admission["channel"] == "legacy_single_unphased"
        if not legacy and entry["provider_status"] != "completed":
            raise ProviderOutputError("provider_incomplete", "Provider response completion is not established")
        for item in items:
            if item["type"] == "reasoning":
                continue
            if item["type"] != "message":
                raise ProviderOutputError("unexpected_output_items", "Provider returned an unexpected non-message output item")
            if not item["id"] or item["role"] != "assistant" or item["status"] != "completed":
                raise ProviderOutputError("invalid_output_message", "Provider answer messages require identity, assistant role, and completed status")
            if "invalid_phase_type" in item or (not legacy and item["phase"] not in {"commentary", "final_answer"}):
                raise ProviderOutputError("invalid_output_phase", "Provider returned an unphased or unknown-phase message outside the single-message legacy contract")
            if any(block["type"] != "output_text" or not isinstance(block.get("text"), str)
                   for block in item["content"]):
                raise ProviderOutputError("invalid_output_content", "Provider returned unsupported or invalid message content")
        candidates = [item for item in items if item["index"] in admission["candidate_item_indexes"]]
        if not candidates:
            raise ProviderOutputError("missing_final_answer", "Provider returned no final-answer message; commentary is non-operative")
        if any(len(item["content"]) != 1 for item in candidates):
            raise ProviderOutputError("multiple_text_blocks", "Each final-answer message must contain exactly one text block")
        return candidates

    def _response_text(self, entry: dict[str, Any], response: Any) -> str:
        """Capture safe output boundaries before checking provider completion.

        Never serialize SDK objects wholesale: reasoning, thinking, encrypted
        content, tool arguments, and unknown payloads must not enter the ledger.
        Ordinary final-answer and commentary text is retained with its original
        item indexes. Only the declared answer channel may return an operation.
        The SDK's flattened output_text convenience property is never used.
        """
        entry["provider_status"] = self._text_field(response, "status")
        entry["provider_stop_reason"] = self._text_field(response, "stop_reason")
        entry["provider_stop_sequence"] = self._text_field(response, "stop_sequence")
        incomplete = self._field(response, "incomplete_details")
        entry["provider_incomplete_details"] = (
            {"reason": self._text_field(incomplete, "reason")} if incomplete is not None else None)
        error = self._field(response, "error")
        entry["provider_error_code"] = self._text_field(error, "code")
        items: list[dict[str, Any]] = []
        texts: list[Any] = []
        refused = False
        incomplete_items = False
        raw_items = self._field(response, "output" if self.provider == "openai" else "content")
        boundaries_known = isinstance(raw_items, (list, tuple))
        for index, item in enumerate(raw_items if boundaries_known else []):
            kind = self._text_field(item, "type")
            saved: dict[str, Any] = {"index": index, "type": kind}
            if self.provider == "openai":
                for field in ("id", "status", "role", "phase"):
                    saved[field] = self._text_field(item, field)
                raw_phase = self._field(item, "phase")
                if raw_phase is not None and saved["phase"] is None:
                    saved["invalid_phase_type"] = type(raw_phase).__name__
                incomplete_items |= saved["status"] not in {None, "completed"}
                if kind == "message":
                    saved["content"] = []
                    blocks = self._field(item, "content", [])
                    if not isinstance(blocks, (list, tuple)):
                        boundaries_known = False
                        blocks = []
                    for content_index, block in enumerate(blocks):
                        block_type = self._text_field(block, "type")
                        saved_block: dict[str, Any] = {"index": content_index, "type": block_type}
                        if block_type == "output_text":
                            text = self._field(block, "text")
                            saved_block["text"] = text if isinstance(text, str) else None
                            texts.append(text)
                        else:
                            saved_block["payload_omitted"] = True
                        refused |= block_type == "refusal"
                        saved["content"].append(saved_block)
                else:
                    saved["payload_omitted"] = True
            elif kind == "text":
                text = self._field(item, "text")
                saved["text"] = text if isinstance(text, str) else None
                texts.append(text)
            else:
                saved["payload_omitted"] = True
            items.append(saved)
        entry["provider_output_items"] = items
        entry["provider_output_boundaries_known"] = boundaries_known
        entry["provider_output_text_count"] = len(texts)
        entry["provider_output_normalization"] = None
        entry["provider_refused"] = refused or entry["provider_stop_reason"] == "refusal"
        if self.provider == "openai":
            self._record_openai_admission(entry, items)

        if entry["provider_refused"]:
            raise ProviderOutputError("provider_refusal", "Provider declined this request")
        if self.provider == "openai":
            status = entry["provider_status"]
            if status == "failed" or error is not None:
                raise ProviderOutputError("provider_error", "Provider returned a generation error")
            if status not in {None, "completed"} or incomplete is not None or incomplete_items:
                raise ProviderOutputError(
                    "provider_incomplete", "Provider response or output item is incomplete")
        elif entry["provider_stop_reason"] not in {None, "end_turn"}:
            raise ProviderOutputError("provider_incomplete", "Provider stopped before completing the answer")
        if not boundaries_known:
            raise ProviderOutputError("missing_output_items", "Provider returned no inspectable output-item boundaries")
        candidates = self._openai_answer_candidates(entry, items) if self.provider == "openai" else items
        if self.provider == "openai":
            texts = [item["content"][0]["text"] for item in candidates]
        if len(texts) > 1 and not self._normalize_duplicate_messages(entry, candidates, texts):
            raise ProviderOutputError(
                "multiple_text_blocks", "Provider returned multiple answer text blocks that are not exact duplicate completed final answers")
        if not texts or not isinstance(texts[0], str) or not texts[0].strip():
            raise ProviderOutputError("empty_output", "Provider returned no text within the supplied request limits")
        if self.provider == "openai":
            # Full-object parsing is still required after channel selection;
            # a malformed final must never fall back to a commentary object.
            parse_single_json_object(texts[0])
            entry["provider_output_admission"]["selected"] = {
                "item_index": candidates[0]["index"], "content_index": candidates[0]["content"][0]["index"]}
        return texts[0]

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
            "adapter_version": "v1-single-request-4",
            "api_attempts": 0, "failed_api_attempts": 0, "request_status": "not_attempted",
            "invocation_succeeded": False, "usage_known": False,
            "input_tokens": None, "output_tokens": None, "cost_usd": None,
            "timeout_seconds": self.timeout_seconds, "max_output_tokens": max_tokens,
            "max_retries": 0,
        }
        if self.output_schema is not None:
            encoded_schema = json.dumps(self.output_schema["schema"], sort_keys=True, separators=(",", ":"))
            entry["output_schema"] = {
                "name": self.output_schema["name"],
                "strict": self.output_schema["strict"] if self.provider == "openai" else None,
                "sha256": sha256(encoded_schema.encode()).hexdigest(),
            }
        try:
            client = self.llm.client.with_options(timeout=self.timeout_seconds, max_retries=0)
            if self.provider == "openai":
                params: dict[str, Any] = {
                    "model": self.model, "instructions": system,
                    "input": user,
                    "max_output_tokens": max_tokens, "text": {"format": {"type": "json_object"}},
                }
                if self.output_schema is not None:
                    params["text"]["format"] = {"type": "json_schema", **copy.deepcopy(self.output_schema)}
                else:
                    params["instructions"] += "\nReturn exactly one complete JSON object."
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
                if self.output_schema is not None:
                    params.setdefault("output_config", {})["format"] = {
                        "type": "json_schema", "schema": copy.deepcopy(self.output_schema["schema"])}
                entry["api_attempts"] = 1
                response = client.messages.create(**params)
            entry.update(request_status="completed", provider_request_id=self._field(response, "_request_id"),
                         provider_response_id=self._field(response, "id"),
                         resolved_model=self._field(response, "model"))
            self._record_usage(entry, response)
            text = self._response_text(entry, response)
            entry["invocation_succeeded"] = True
            return text
        except Exception as error:
            if entry["request_status"] != "completed" and entry["api_attempts"]:
                entry.update(request_status="failed", failed_api_attempts=1)
            entry.update(error_type=type(error).__name__, http_status=getattr(error, "status_code", None))
            if isinstance(error, (ProviderOutputError, OutputProtocolError)):
                entry["output_error_code"] = error.code
            raise
        finally:
            entry["elapsed_seconds"] = perf_counter() - started
            self.usage.append(entry)
