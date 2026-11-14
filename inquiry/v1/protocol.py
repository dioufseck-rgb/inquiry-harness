"""The v1 worker wire protocol: one complete, unambiguous JSON object.

This parser deliberately does not search prose for JSON, remove Markdown fences,
repair truncated JSON, or choose one of several values. The controller records
the reply and decides whether another budgeted invocation is warranted.
"""
from __future__ import annotations

import json
from math import isfinite
from typing import Any


class OutputProtocolError(ValueError):
    """A worker reply failed the provider-independent JSON wire contract."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OutputProtocolError("duplicate_key", "Duplicate JSON object keys are not allowed")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise OutputProtocolError("nonfinite_number", "Nonfinite numbers are not valid worker JSON")


def _finite_float(value: str) -> float:
    result = float(value)
    if not isfinite(result):
        raise OutputProtocolError("nonfinite_number", "JSON numbers must be representable as finite values")
    return result


def parse_single_json_object(reply: str) -> dict[str, Any]:
    """Parse all of a reply, rejecting ambiguity instead of discarding data.

    Whitespace permitted by JSON is accepted around the object. Duplicate keys
    at any depth, JavaScript nonfinite constants, floating-point overflow, and
    every non-object top-level value are rejected. Errors contain positions or
    categories, never a potentially sensitive excerpt of the provider response.
    """
    if not isinstance(reply, str):
        raise OutputProtocolError("nontext_reply", "Worker reply must be text containing one JSON object")
    if not reply.strip(" \t\r\n"):
        raise OutputProtocolError("empty_reply", "Worker reply must contain exactly one JSON object")
    try:
        value = json.loads(reply, object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant, parse_float=_finite_float)
    except OutputProtocolError:
        raise
    except json.JSONDecodeError as exc:
        if exc.msg == "Extra data":
            raise OutputProtocolError(
                "trailing_data",
                f"Expected exactly one JSON object; extra data starts at character {exc.pos}",
            ) from exc
        raise OutputProtocolError(
            "invalid_json", f"Malformed or truncated JSON at character {exc.pos}: {exc.msg}",
        ) from exc
    except RecursionError as exc:
        raise OutputProtocolError("json_too_deep", "Worker JSON exceeds the parser nesting limit") from exc
    except ValueError as exc:
        raise OutputProtocolError("invalid_json", "Worker JSON contains an unsupported numeric value") from exc
    if not isinstance(value, dict):
        raise OutputProtocolError("nonobject_reply", "Worker reply must contain exactly one JSON object")
    return value
