"""Domain-neutral inquiry requests and source-integrity validation.

Callers supply the question, target claim kind/form, acceptance profile, and
source material. This boundary does not choose business decisions, interpret
domain rules, or import an application fixture. Source lineage is a declared
provenance graph, not a certification of evidential independence.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
from math import isfinite
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, model_validator


REQUEST_SCHEMA_VERSION = "inquiry-request/v1"

# Evaluation annotations belong to the caller's private experiment records,
# never to the public input of an inquiry worker. Check every nested object.
FORBIDDEN_PUBLIC_KEYS = frozenset({
    "evaluator_only", "hidden_world", "admissible_answer_spec", "admissible_answer_specs",
    "controlled_mutations", "expected_relationships", "annotation_status", "export_requirement",
    "oracle", "oracle_version", "smoke_expectation", "mutation_id", "variant_id",
})

_KERNEL_BOOLEAN_FIELDS = frozenset({
    "allow_conditional", "allow_historical_sources", "require_independent_reply",
})
_KERNEL_INTEGER_FIELDS = frozenset({
    "min_origins", "max_derivations", "max_depth", "max_evaluation_steps",
})
_KERNEL_LIST_FIELDS = frozenset({
    "allowed_claim_kinds", "allowed_patterns", "required_scope_fields", "allowed_performer_kinds",
})
KERNEL_PROFILE_FIELDS = (
    _KERNEL_BOOLEAN_FIELDS | _KERNEL_INTEGER_FIELDS | _KERNEL_LIST_FIELDS | {"premise_min_origins"}
)


class InquiryValidationError(ValueError):
    """An inquiry request violates the public or source-integrity contract."""


def canonical_json(value: Any) -> str:
    """Serialize JSON deterministically, rejecting nonfinite numeric values."""
    if isinstance(value, InquiryRequest):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _snapshot(value: Any, at: str, active: set[int] | None = None) -> Any:
    """Take a JSON-only copy while preventing private annotations and cycles."""
    active = set() if active is None else active
    if isinstance(value, Mapping):
        if id(value) in active:
            raise InquiryValidationError(f"{at}: cyclic JSON object")
        if any(not isinstance(key, str) for key in value):
            raise InquiryValidationError(f"{at}: JSON object keys must be strings")
        forbidden = FORBIDDEN_PUBLIC_KEYS.intersection(value)
        if forbidden:
            raise InquiryValidationError(f"{at}: private evaluation keys are forbidden: {sorted(forbidden)}")
        active.add(id(value))
        try:
            return {key: _snapshot(item, f"{at}.{key}", active) for key, item in value.items()}
        finally:
            active.remove(id(value))
    if isinstance(value, list):
        if id(value) in active:
            raise InquiryValidationError(f"{at}: cyclic JSON array")
        active.add(id(value))
        try:
            return [_snapshot(item, f"{at}[{index}]", active) for index, item in enumerate(value)]
        finally:
            active.remove(id(value))
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and isfinite(value):
        return value
    raise InquiryValidationError(f"{at}: expected a finite JSON value")


def _fields(value: Any, required: set[str], optional: set[str] | frozenset[str], at: str) -> None:
    if not isinstance(value, dict):
        raise InquiryValidationError(f"{at}: expected an object")
    missing, extra = required - value.keys(), value.keys() - required - optional
    if missing or extra:
        raise InquiryValidationError(f"{at}: missing={sorted(missing)}, unknown fields={sorted(extra)}")


def _text(value: Any, at: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InquiryValidationError(f"{at}: expected a nonempty string")


def _list(value: Any, at: str) -> None:
    if not isinstance(value, list):
        raise InquiryValidationError(f"{at}: expected an array")


def _iso_date(value: Any, at: str) -> None:
    _text(value, at)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise InquiryValidationError(f"{at}: expected ISO date YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise InquiryValidationError(f"{at}: expected ISO date YYYY-MM-DD")


def _reference(ref: Any, at: str, *, locator: bool = False) -> None:
    _fields(ref, {"document_id", "version"}, {"locator"} if locator else set(), at)
    for field in ref:
        _text(ref[field], f"{at}.{field}")


def _table(table: Any, at: str) -> list[str]:
    _fields(table, {"id", "columns", "rows"}, {"title", "column_units", "footnotes"}, at)
    _text(table["id"], at + ".id")
    _list(table["columns"], at + ".columns")
    for column in table["columns"]:
        _text(column, at + ".columns")
    if not table["columns"] or len(set(table["columns"])) != len(table["columns"]):
        raise InquiryValidationError(f"{at}: columns must be nonempty and unique")
    if "title" in table:
        _text(table["title"], at + ".title")
    _list(table["rows"], at + ".rows")
    row_ids: set[str] = set()
    for index, row in enumerate(table["rows"]):
        row_at = f"{at}.rows[{index}]"
        _fields(row, {"id", "cells"}, set(), row_at)
        _text(row["id"], row_at + ".id")
        if row["id"] in row_ids:
            raise InquiryValidationError(f"{at}: duplicate table row identifier")
        row_ids.add(row["id"])
        if not isinstance(row["cells"], dict) or set(row["cells"]) != set(table["columns"]):
            raise InquiryValidationError(f"{row_at}: cells must match the declared columns")
        if any(not isinstance(value, (str, int, float, bool, type(None))) for value in row["cells"].values()):
            raise InquiryValidationError(f"{row_at}: table cells must be scalar JSON values")
    units = table.get("column_units", {})
    if not isinstance(units, dict) or set(units) - set(table["columns"]):
        raise InquiryValidationError(f"{at}: units reference unknown columns")
    for value in units.values():
        _text(value, at + ".column_units")
    _list(table.get("footnotes", []), at + ".footnotes")
    for value in table.get("footnotes", []):
        _text(value, at + ".footnotes")

    prefix = "table:" + table["id"]
    locators = [prefix + "/title"] if table.get("title") else []
    for column in table["columns"]:
        locators.append(prefix + "/header:" + column)
        if column in units:
            locators.append(prefix + "/unit:" + column)
    for row in table["rows"]:
        locators.extend(prefix + "/row:" + row["id"] + "/column:" + column for column in table["columns"])
    locators.extend(prefix + "/footnote:" + str(index) for index in range(1, len(table.get("footnotes", [])) + 1))
    return locators


def _source(document: Any, at: str) -> set[str]:
    _fields(document, {"id", "version", "title", "issuer_id", "origin_id", "issued_at", "language", "reading_blocks"},
            {"effective_from", "derived_from", "publication_origin_id", "supersedes", "tables"}, at)
    for field in ("id", "version", "title", "issuer_id", "origin_id", "language"):
        _text(document[field], f"{at}.{field}")
    if "publication_origin_id" in document:
        _text(document["publication_origin_id"], at + ".publication_origin_id")
    for field in ("issued_at", "effective_from"):
        if field in document:
            _iso_date(document[field], f"{at}.{field}")
    _list(document["reading_blocks"], at + ".reading_blocks")
    locators: list[str] = []
    for index, block in enumerate(document["reading_blocks"]):
        block_at = f"{at}.reading_blocks[{index}]"
        _fields(block, {"locator", "text"}, set(), block_at)
        for field in ("locator", "text"):
            _text(block[field], f"{block_at}.{field}")
        locators.append(block["locator"])
    _list(document.get("tables", []), at + ".tables")
    table_ids: set[str] = set()
    for index, table in enumerate(document.get("tables", [])):
        locators.extend(_table(table, f"{at}.tables[{index}]"))
        if table["id"] in table_ids:
            raise InquiryValidationError(f"{at}: duplicate table identifier")
        table_ids.add(table["id"])
    if not locators:
        raise InquiryValidationError(f"{at}: source has no reading blocks or tables")
    if len(set(locators)) != len(locators):
        raise InquiryValidationError(f"{at}: duplicate source locator")
    if "supersedes" in document:
        _reference(document["supersedes"], at + ".supersedes")
        if document["supersedes"]["document_id"] != document["id"]:
            raise InquiryValidationError(f"{at}: a source revision must preserve source identity")
    _list(document.get("derived_from", []), at + ".derived_from")
    for index, ref in enumerate(document.get("derived_from", [])):
        _reference(ref, f"{at}.derived_from[{index}]", locator=True)
    return set(locators)


def _acyclic(edges: dict[tuple[str, str], list[tuple[str, str]]]) -> None:
    # Iterative traversal also handles long, valid revision histories without
    # depending on Python's call-stack depth.
    done: set[tuple[str, str]] = set()
    active: set[tuple[str, str]] = set()
    for pair in edges:
        if pair in done:
            continue
        active.add(pair)
        stack = [(pair, iter(edges[pair]))]
        while stack:
            current, children = stack[-1]
            try:
                target = next(children)
            except StopIteration:
                stack.pop()
                active.remove(current)
                done.add(current)
                continue
            if target in active:
                raise InquiryValidationError("Cyclic source lineage or revision history")
            if target not in done:
                active.add(target)
                stack.append((target, iter(edges[target])))


def _validate_corpus(corpus: Any) -> dict[str, str]:
    _fields(corpus, {"documents", "current_versions"}, set(), "corpus")
    _list(corpus["documents"], "corpus.documents")
    if not isinstance(corpus["current_versions"], dict):
        raise InquiryValidationError("corpus.current_versions: expected an object")
    lookup: dict[tuple[str, str], dict] = {}
    locators: dict[tuple[str, str], set[str]] = {}
    by_id: dict[str, set[str]] = {}
    for index, document in enumerate(corpus["documents"]):
        source_locators = _source(document, f"corpus.documents[{index}]")
        pair = (document["id"], document["version"])
        if pair in lookup:
            raise InquiryValidationError(f"Duplicate source version {pair}")
        lookup[pair], locators[pair] = document, source_locators
        by_id.setdefault(pair[0], set()).add(pair[1])
    edges: dict[tuple[str, str], list[tuple[str, str]]] = {}
    superseded: set[tuple[str, str]] = set()
    for pair, document in lookup.items():
        refs = list(document.get("derived_from", []))
        if "supersedes" in document:
            refs.append(document["supersedes"])
            superseded.add((document["supersedes"]["document_id"], document["supersedes"]["version"]))
        edges[pair] = []
        for ref in refs:
            target = (ref["document_id"], ref["version"])
            if target not in lookup:
                raise InquiryValidationError(f"Unresolved source reference {target}")
            if "locator" in ref and ref["locator"] not in locators[target]:
                raise InquiryValidationError(f"Unresolved source locator {ref['locator']}")
            edges[pair].append(target)
    _acyclic(edges)

    declared = corpus["current_versions"]
    for source_id, version in declared.items():
        _text(source_id, "corpus.current_versions source ID")
        _text(version, f"corpus.current_versions.{source_id}")
        if (source_id, version) not in lookup:
            raise InquiryValidationError(f"Unresolved current source version {(source_id, version)}")
    if set(declared) != set(by_id):
        raise InquiryValidationError("corpus.current_versions must bind every source ID exactly once")
    for source_id, versions in by_id.items():
        leaves = [version for version in versions if (source_id, version) not in superseded]
        if len(leaves) != 1:
            raise InquiryValidationError(f"{source_id}: history has no unique current version")
        if declared[source_id] != leaves[0]:
            raise InquiryValidationError(f"{source_id}: current binding points at a superseded version")
    return dict(declared)


def current_versions(corpus: Mapping[str, Any]) -> dict[str, str]:
    """Validate and copy explicit current bindings; never infer application roles."""
    return _validate_corpus(_snapshot(corpus, "corpus"))


def _question(question: Any) -> None:
    _fields(question, {"id", "question", "intended_use", "scope", "target", "profile"}, set(), "question")
    for field in ("id", "question", "intended_use"):
        _text(question[field], "question." + field)
    if not isinstance(question["scope"], dict):
        raise InquiryValidationError("question.scope: expected an object")
    _fields(question["target"], {"kind", "form"}, set(), "question.target")
    for field in ("kind", "form"):
        _text(question["target"][field], "question.target." + field)
    profile = question["profile"]
    _fields(profile, {"id", "version", "authority", "requirements", "kernel"}, set(), "question.profile")
    for field in ("id", "version", "authority"):
        _text(profile[field], "question.profile." + field)
    _list(profile["requirements"], "question.profile.requirements")
    for item in profile["requirements"]:
        _text(item, "question.profile.requirements")
    _fields(profile["kernel"], set(), KERNEL_PROFILE_FIELDS, "question.profile.kernel")
    for field, value in profile["kernel"].items():
        at = "question.profile.kernel." + field
        if field in _KERNEL_BOOLEAN_FIELDS:
            if not isinstance(value, bool):
                raise InquiryValidationError(f"{at}: expected a boolean")
        elif field in _KERNEL_LIST_FIELDS:
            _list(value, at)
            for item in value:
                _text(item, at)
            if len(set(value)) != len(value):
                raise InquiryValidationError(f"{at}: entries must be unique")
        elif field == "premise_min_origins" and value is None:
            continue
        elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise InquiryValidationError(f"{at}: expected a nonnegative integer")


def validate_inquiry_request(value: Any) -> dict[str, Any]:
    """Return a validated, independent canonical request without domain conversion.

    Source metadata uses the existing document/reading-block/table interchange
    shape, but IDs and scope fields belong to the caller. Empty evidence is
    permitted with an empty current-version map. The public envelope is exact;
    arbitrary JSON context is allowed inside ``shared_context`` and ``scope``.
    """
    if isinstance(value, InquiryRequest):
        value = value.model_dump(mode="python")
    request = _snapshot(value, "request")
    _fields(request, {"shared_context", "corpus", "question"}, set(), "request")
    context = request["shared_context"]
    if not isinstance(context, dict) or "as_of" not in context:
        raise InquiryValidationError("shared_context: expected an object containing as_of")
    _iso_date(context["as_of"], "shared_context.as_of")
    _validate_corpus(request["corpus"])
    _question(request["question"])
    # Keep hashing and public JSON admission aligned, including Unicode and
    # numeric serialization failures, before any worker receives the request.
    try:
        canonical_json(request).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise InquiryValidationError("Request is not serializable as canonical UTF-8 JSON") from exc
    return request


def request_json_schema() -> dict[str, Any]:
    """Describe public structure for service callers; references are also checked.

    The validator additionally resolves source versions/locators, checks acyclic
    lineage and unique current revisions, and verifies matching table columns.
    Those relational checks cannot be expressed by this structural JSON schema.
    """
    text = {"type": "string", "minLength": 1, "pattern": r"\S"}
    iso_date = {"type": "string", "format": "date", "pattern": r"^\d{4}-\d{2}-\d{2}$"}
    forbidden_names = {"not": {"enum": sorted(FORBIDDEN_PUBLIC_KEYS)}}

    def record(properties: dict, required: list[str] | None = None, additional: Any = False) -> dict:
        result = {"type": "object", "properties": properties, "required": list(properties) if required is None else required,
                  "additionalProperties": additional, "propertyNames": deepcopy(forbidden_names)}
        return result

    reference = record({"document_id": text, "version": text})
    lineage_reference = record({"document_id": text, "version": text, "locator": text}, ["document_id", "version"])
    string_list = {"type": "array", "items": text}
    scalar = {"type": ["string", "number", "boolean", "null"]}
    kernel_fields = {name: {"type": "boolean"} for name in sorted(_KERNEL_BOOLEAN_FIELDS)}
    kernel_fields.update({name: {"type": "integer", "minimum": 0} for name in sorted(_KERNEL_INTEGER_FIELDS)})
    kernel_fields.update({name: {**string_list, "uniqueItems": True} for name in sorted(_KERNEL_LIST_FIELDS)})
    kernel_fields["premise_min_origins"] = {"type": ["integer", "null"], "minimum": 0}
    table = record({
        "id": text, "title": text,
        "columns": {**string_list, "minItems": 1, "uniqueItems": True},
        "rows": {"type": "array", "items": record({"id": text, "cells": record({}, [], scalar)})},
        "column_units": record({}, [], text), "footnotes": string_list,
    }, ["id", "columns", "rows"])
    source = record({
        "id": text, "version": text, "title": text, "issuer_id": text,
        "origin_id": text, "issued_at": iso_date, "language": text,
        "reading_blocks": {"type": "array", "items": record({"locator": text, "text": text})},
        "effective_from": iso_date, "publication_origin_id": text,
        "derived_from": {"type": "array", "items": {"$ref": "#/$defs/lineage_reference"}},
        "supersedes": {"$ref": "#/$defs/source_reference"},
        "tables": {"type": "array", "items": {"$ref": "#/$defs/table"}},
    }, ["id", "version", "title", "issuer_id", "origin_id", "issued_at", "language", "reading_blocks"])
    versions = record({}, [], text)
    versions["propertyNames"] = {"allOf": [text, forbidden_names]}
    schema = record({
        "shared_context": record({"as_of": iso_date}, ["as_of"], {"$ref": "#/$defs/public_value"}),
        "corpus": record({"documents": {"type": "array", "items": {"$ref": "#/$defs/source"}},
                          "current_versions": versions}),
        "question": record({
            "id": text, "question": text, "intended_use": text,
            "scope": {"$ref": "#/$defs/public_object"},
            "target": record({"kind": text, "form": text}),
            "profile": record({"id": text, "version": text, "authority": text,
                               "requirements": string_list, "kernel": record(kernel_fields, [])}),
        }),
    })
    schema.update({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "InquiryRequest", "description": REQUEST_SCHEMA_VERSION,
        "$defs": {
            "source_reference": reference, "lineage_reference": lineage_reference,
            "source": source, "table": table,
            "public_object": record({}, [], {"$ref": "#/$defs/public_value"}),
            "public_value": {"anyOf": [scalar, {"type": "array", "items": {"$ref": "#/$defs/public_value"}},
                                        {"$ref": "#/$defs/public_object"}]},
        },
    })
    return deepcopy(schema)


# A compatibility name for generic callers. Legacy application packets need an
# explicit adapter; this alias does not recognize or convert their domain roles.
validate_public_case = validate_inquiry_request


class InquiryRequest(BaseModel):
    """Validated public input with the canonical three-record JSON shape."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, revalidate_instances="always")

    shared_context: dict[str, Any]
    corpus: dict[str, Any]
    question: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def _validate_contract(cls, value: Any) -> dict[str, Any]:
        return validate_inquiry_request(value)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InquiryRequest":
        return cls.model_validate(value)

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.model_dump(mode="json"))


__all__ = [
    "REQUEST_SCHEMA_VERSION", "FORBIDDEN_PUBLIC_KEYS", "KERNEL_PROFILE_FIELDS",
    "InquiryRequest", "InquiryValidationError", "canonical_json", "content_hash",
    "current_versions", "request_json_schema", "validate_inquiry_request", "validate_public_case",
]
