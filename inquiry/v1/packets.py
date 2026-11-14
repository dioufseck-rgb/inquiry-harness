"""Controlled authoring packets and a deliberately narrow public projection.

This is a trusted local-process boundary, not an operating-system sandbox.  A
worker must receive ``Packet.public(...)``, never the authoring file or Packet.
The bundled fixture is provisional development material, not human gold.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


DEFAULT_PACKET_PATH = Path(__file__).with_name("data") / "hardship.json"


class PacketValidationError(ValueError):
    """An authoring packet or public projection violates its contract."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _fields(value: Any, required: set[str], optional: set[str], at: str) -> None:
    if not isinstance(value, dict):
        raise PacketValidationError(f"{at}: expected an object")
    missing, extra = required - value.keys(), value.keys() - required - optional
    if missing or extra:
        raise PacketValidationError(f"{at}: missing={sorted(missing)}, forbidden fields={sorted(extra)}")


def _text(value: Any, at: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PacketValidationError(f"{at}: expected a nonempty string")


def _list(value: Any, at: str) -> None:
    if not isinstance(value, list):
        raise PacketValidationError(f"{at}: expected a list")


def _id(value: Any, prefix: str | tuple[str, ...], at: str) -> None:
    prefixes = (prefix,) if isinstance(prefix, str) else prefix
    if not isinstance(value, str) or not any(re.fullmatch(p + r"_[0-9]+", value) for p in prefixes):
        raise PacketValidationError(f"{at}: expected a neutral {prefixes} identifier")


def _reference(ref: Any, at: str, locator: bool = False) -> None:
    _fields(ref, {"document_id", "version"}, {"locator"} if locator else set(), at)
    _id(ref["document_id"], "doc", at)
    _text(ref["version"], at + ".version")
    if "locator" in ref:
        _text(ref["locator"], at + ".locator")


def _table(table: Any, at: str) -> None:
    _fields(table, {"id", "columns", "rows"}, {"title", "column_units", "footnotes"}, at)
    _text(table["id"], at + ".id")
    _list(table["columns"], at + ".columns")
    for column in table["columns"]:
        _text(column, at + ".columns")
    if not table["columns"] or len(set(table["columns"])) != len(table["columns"]):
        raise PacketValidationError(f"{at}: columns must be nonempty and unique")
    _list(table["rows"], at + ".rows")
    row_ids = set()
    for row in table["rows"]:
        _fields(row, {"id", "cells"}, set(), at + ".row")
        _text(row["id"], at + ".row.id")
        if row["id"] in row_ids or not isinstance(row["cells"], dict) or set(row["cells"]) != set(table["columns"]):
            raise PacketValidationError(f"{at}: duplicate row or mismatched columns")
        row_ids.add(row["id"])
        if any(not isinstance(v, (str, int, float, bool, type(None))) for v in row["cells"].values()):
            raise PacketValidationError(f"{at}: table cells must be scalar JSON values")
    units = table.get("column_units", {})
    if not isinstance(units, dict) or set(units) - set(table["columns"]):
        raise PacketValidationError(f"{at}: units reference unknown columns")
    for value in units.values():
        _text(value, at + ".column_units")
    _list(table.get("footnotes", []), at + ".footnotes")
    for value in table.get("footnotes", []):
        _text(value, at + ".footnotes")


def _question(question: Any, entity_ids: set[str], at: str) -> None:
    _fields(question, {"id", "question", "intended_use", "profile", "scope"}, set(), at)
    _id(question["id"], "question", at + ".id")
    _text(question["question"], at + ".question")
    _text(question["intended_use"], at + ".intended_use")
    profile = question["profile"]
    _fields(profile, {"id", "version", "required_form", "requirements"}, {"policy_binding", "authority", "kernel"}, at + ".profile")
    _id(profile["id"], "profile", at + ".profile.id")
    for key in ("version", "required_form"):
        _text(profile[key], at + ".profile." + key)
    _list(profile["requirements"], at + ".profile.requirements")
    for requirement in profile["requirements"]:
        _text(requirement, at + ".profile.requirements")
    if profile.get("policy_binding", "current_policy") != "current_policy":
        raise PacketValidationError(f"{at}: unknown policy binding")
    if "authority" in profile:
        _text(profile["authority"], at + ".profile.authority")
    if "kernel" in profile:
        settings = profile["kernel"]
        permitted = {"min_origins", "allowed_claim_kinds", "allow_conditional", "allow_historical_sources", "required_scope_fields", "max_derivations", "max_depth"}
        _fields(settings, set(), permitted, at + ".profile.kernel")
        for key, value in settings.items():
            if key in {"allow_conditional", "allow_historical_sources"}:
                if not isinstance(value, bool):
                    raise PacketValidationError(f"{at}: {key} must be boolean")
            elif key in {"allowed_claim_kinds", "required_scope_fields"}:
                _list(value, at + ".profile.kernel." + key)
                for item in value:
                    _text(item, at + ".profile.kernel." + key)
            elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PacketValidationError(f"{at}: {key} must be a nonnegative integer")
    scope_fields = {"subject_id", "location_id", "location_name", "period", "outcome", "quantifier", "event_date", "workplace_id", "case_id", "stage", "as_of", "population", "comparison", "conditions", "unit"}
    _fields(question["scope"], set(), scope_fields, at + ".scope")
    for key, value in question["scope"].items():
        _text(value, at + ".scope." + key)
        if key in {"subject_id", "location_id", "workplace_id"} and value not in entity_ids:
            raise PacketValidationError(f"{at}: unknown scope entity {value}")


def current_versions(corpus: Mapping[str, Any]) -> dict[str, str]:
    """Use explicit bindings, and the unique unsuperseded version otherwise."""
    documents = corpus["documents"]
    by_id: dict[str, set[str]] = {}
    superseded: set[tuple[str, str]] = set()
    for document in documents:
        by_id.setdefault(document["id"], set()).add(document["version"])
        if document.get("supersedes"):
            ref = document["supersedes"]
            superseded.add((ref["document_id"], ref["version"]))
    result: dict[str, str] = {}
    for key in ("current_policy", "current_event_record", "case_account"):
        ref = corpus[key]
        old = result.setdefault(ref["document_id"], ref["version"])
        if old != ref["version"]:
            raise PacketValidationError("Conflicting current-version bindings")
    for source_id, versions in by_id.items():
        leaves = [v for v in versions if (source_id, v) not in superseded]
        if len(leaves) != 1:
            raise PacketValidationError(f"{source_id}: history has no unique current version")
        if source_id in result and result[source_id] != leaves[0]:
            raise PacketValidationError(f"{source_id}: current binding points at a superseded version")
        result[source_id] = leaves[0]
    return result


def validate_public_case(case: Any) -> None:
    """Validate the allowlisted view, including referential and history integrity."""
    _fields(case, {"shared_context", "corpus", "question"}, set(), "public")
    context, corpus = case["shared_context"], case["corpus"]
    _fields(context, {"fiction_notice", "as_of", "authority", "source_handling", "evidence_boundary", "case_id", "entities"}, set(), "shared_context")
    for key in set(context) - {"entities"}:
        _text(context[key], "shared_context." + key)
    try:
        date.fromisoformat(context["as_of"])
    except ValueError as exc:
        raise PacketValidationError("shared_context.as_of: expected ISO date") from exc
    _id(context["case_id"], "case", "case_id")
    _list(context["entities"], "entities")
    entity_ids = set()
    for entity in context["entities"]:
        _fields(entity, {"id", "name"}, set(), "entity")
        _id(entity["id"], ("entity", "person", "site", "area"), "entity.id")
        _text(entity["name"], "entity.name")
        if entity["id"] in entity_ids:
            raise PacketValidationError("Duplicate entity identifier")
        entity_ids.add(entity["id"])
    _fields(corpus, {"current_policy", "current_event_record", "case_account", "documents"}, set(), "corpus")
    _list(corpus["documents"], "documents")
    lookup: dict[tuple[str, str], dict] = {}
    for document in corpus["documents"]:
        _fields(document, {"id", "version", "title", "issuer_id", "origin_id", "issued_at", "language", "reading_blocks"}, {"effective_from", "derived_from", "publication_origin_id", "supersedes", "tables"}, "document")
        _id(document["id"], "doc", "document.id")
        _id(document["origin_id"], "origin", "document.origin_id")
        if "publication_origin_id" in document:
            _id(document["publication_origin_id"], "origin", "document.publication_origin_id")
        for key in ("version", "title", "issued_at", "language"):
            _text(document[key], "document." + key)
        for key in ("issued_at", "effective_from"):
            if key in document:
                try:
                    date.fromisoformat(document[key])
                except (ValueError, TypeError) as exc:
                    raise PacketValidationError(f"document.{key}: expected ISO date") from exc
        if document["issuer_id"] not in entity_ids:
            raise PacketValidationError("Document refers to an unknown issuer")
        pair = (document["id"], document["version"])
        if pair in lookup:
            raise PacketValidationError(f"Duplicate source version {pair}")
        lookup[pair] = document
        _list(document["reading_blocks"], "reading_blocks")
        locators = set()
        for block in document["reading_blocks"]:
            _fields(block, {"locator", "text"}, set(), "reading_block")
            for key in ("locator", "text"):
                _text(block[key], "reading_block." + key)
            if block["locator"] in locators:
                raise PacketValidationError("Duplicate source locator")
            locators.add(block["locator"])
        table_ids = set()
        _list(document.get("tables", []), "tables")
        for table in document.get("tables", []):
            _table(table, "table")
            if table["id"] in table_ids:
                raise PacketValidationError("Duplicate table identifier")
            table_ids.add(table["id"])
        if not locators and not table_ids:
            raise PacketValidationError("Source has no reading blocks or tables")
        if "supersedes" in document:
            _reference(document["supersedes"], "supersedes")
            if document["supersedes"]["document_id"] != document["id"]:
                raise PacketValidationError("A source revision must preserve source identity")
        _list(document.get("derived_from", []), "derived_from")
        for ref in document.get("derived_from", []):
            _reference(ref, "derived_from", locator=True)
    for key in ("current_policy", "current_event_record", "case_account"):
        _reference(corpus[key], key)
        if (corpus[key]["document_id"], corpus[key]["version"]) not in lookup:
            raise PacketValidationError(f"Unresolved binding {key}")
    edges: dict[tuple, list[tuple]] = {}
    for pair, document in lookup.items():
        refs = document.get("derived_from", []) + ([document["supersedes"]] if document.get("supersedes") else [])
        edges[pair] = []
        for ref in refs:
            target = (ref["document_id"], ref["version"])
            if target not in lookup:
                raise PacketValidationError(f"Unresolved source reference {target}")
            if "locator" in ref and ref["locator"] not in {b["locator"] for b in lookup[target]["reading_blocks"]}:
                raise PacketValidationError(f"Unresolved source locator {ref['locator']}")
            edges[pair].append(target)
    done, active = set(), set()

    def visit(pair: tuple) -> None:
        if pair in active:
            raise PacketValidationError("Cyclic source lineage or revision history")
        if pair in done:
            return
        active.add(pair)
        for target in edges[pair]:
            visit(target)
        active.remove(pair)
        done.add(pair)

    for pair in edges:
        visit(pair)
    current_versions(corpus)
    _question(case["question"], entity_ids, "question")
    if case["question"]["scope"].get("case_id", context["case_id"]) != context["case_id"]:
        raise PacketValidationError("Question refers to a different case")


def _apply_mutation(public_input: dict, mutation: dict) -> None:
    """Execute only the declared finite operation language, once on baseline."""
    corpus, entities = public_input["baseline_corpus"], public_input["shared_context"]["entities"]
    documents = corpus["documents"]
    for operation in mutation["public_operations"]:
        name = operation.get("operation")
        if name == "append_entity":
            _fields(operation, {"operation", "path", "value"}, set(), name)
            if operation["path"] != "shared_context.entities" or any(e["id"] == operation["value"]["id"] for e in entities):
                raise PacketValidationError("Invalid append_entity target or duplicate identity")
            entities.append(deepcopy(operation["value"]))
        elif name == "append_document":
            _fields(operation, {"operation", "path", "value"}, set(), name)
            value = operation["value"]
            if operation["path"] != "baseline_corpus.documents" or any((d["id"], d["version"]) == (value["id"], value["version"]) for d in documents):
                raise PacketValidationError("Invalid append_document target or duplicate version")
            documents.append(deepcopy(value))
        elif name == "replace_reading_block":
            _fields(operation, {"operation", "document_id", "version", "locator", "new_version", "text"}, set(), name)
            original = next((d for d in documents if (d["id"], d["version"]) == (operation["document_id"], operation["version"])), None)
            if original is None or any((d["id"], d["version"]) == (operation["document_id"], operation["new_version"]) for d in documents):
                raise PacketValidationError("Missing original or duplicate revision")
            revised = deepcopy(original)
            block = next((b for b in revised["reading_blocks"] if b["locator"] == operation["locator"]), None)
            if block is None:
                raise PacketValidationError("Revision names an unknown locator")
            block["text"] = operation["text"]
            revised["version"] = operation["new_version"]
            revised["supersedes"] = {"document_id": original["id"], "version": original["version"]}
            documents.append(revised)
        elif name == "set_reference_version":
            _fields(operation, {"operation", "path", "value"}, set(), name)
            key = operation["path"].removeprefix("baseline_corpus.")
            if operation["path"] != "baseline_corpus." + key or key not in {"current_policy", "current_event_record", "case_account"}:
                raise PacketValidationError("Invalid reference update path")
            corpus[key]["version"] = operation["value"]
        elif name == "permute_documents":
            _fields(operation, {"operation", "path", "order"}, set(), name)
            order = operation["order"]
            if operation["path"] != "baseline_corpus.documents" or len(order) != len(documents) or set(order) != {d["id"] for d in documents}:
                raise PacketValidationError("Permutation must preserve each baseline document exactly once")
            by_id = {d["id"]: d for d in documents}
            documents[:] = [by_id[identifier] for identifier in order]
        elif name == "reverse_reading_block_presentation_order":
            _fields(operation, {"operation", "document_ids", "preserve_locators"}, set(), name)
            ids = operation["document_ids"]
            if operation["preserve_locators"] is not True or len(set(ids)) != len(ids) or not set(ids) <= {d["id"] for d in documents}:
                raise PacketValidationError("Invalid reading-order transform")
            for document in documents:
                if document["id"] in ids:
                    document["reading_blocks"].reverse()
        elif name == "consistent_display_name_substitution":
            _fields(operation, {"operation", "entity_id", "from", "to", "locations"}, set(), name)
            entity = next((e for e in entities if e["id"] == operation["entity_id"]), None)
            if entity is None or entity["name"] != operation["from"]:
                raise PacketValidationError("Alias does not match the stable entity identity")
            _text(operation["to"], "alias")
            entity["name"] = operation["to"]
            for document in documents:
                document["title"] = document["title"].replace(operation["from"], operation["to"])
                for block in document["reading_blocks"]:
                    block["text"] = block["text"].replace(operation["from"], operation["to"])
                for table in document.get("tables", []):
                    for row in table["rows"]:
                        row["cells"] = {k: v.replace(operation["from"], operation["to"]) if isinstance(v, str) else v for k, v in row["cells"].items()}
        else:
            raise PacketValidationError(f"Unsupported mutation operation: {name}")


@dataclass(frozen=True)
class Packet:
    """An immutable authoring snapshot. Public exports never retain its oracle."""

    _serialized: str

    @property
    def packet_hash(self) -> str:
        return hashlib.sha256(self._serialized.encode("utf-8")).hexdigest()

    @property
    def fixture_id(self) -> str:
        return json.loads(self._serialized)["fixture_id"]

    @property
    def question_ids(self) -> tuple[str, ...]:
        return tuple(q["id"] for q in json.loads(self._serialized)["public_agent_input"]["question_settings"])

    @property
    def mutation_ids(self) -> tuple[str, ...]:
        return tuple(m["id"] for m in json.loads(self._serialized)["evaluator_only"]["controlled_mutations"])

    def public(self, question_id: str, mutation_id: str | None = None) -> dict:
        data = json.loads(self._serialized)
        public = data["public_agent_input"]
        if mutation_id is not None:
            mutation = next((m for m in data["evaluator_only"]["controlled_mutations"] if m["id"] == mutation_id), None)
            if mutation is None:
                raise PacketValidationError(f"Unknown mutation {mutation_id}")
            _apply_mutation(public, mutation)
        question = next((q for q in public["question_settings"] if q["id"] == question_id), None)
        if question is None:
            raise PacketValidationError(f"Unknown question {question_id}")
        result = {"shared_context": public["shared_context"], "corpus": public["baseline_corpus"], "question": question}
        validate_public_case(result)
        return deepcopy(result)

    def oracle(self, question_id: str, mutation_id: str | None = None) -> dict:
        """Scorer-only projection; it must never be included in worker inputs."""
        data = json.loads(self._serialized)
        evaluator = data["evaluator_only"]
        answer = next((a for a in evaluator["admissible_answer_specs"] if a["question_id"] == question_id), None)
        if answer is None:
            raise PacketValidationError(f"Unknown question {question_id}")
        mutation = None
        if mutation_id is not None:
            selected = next((m for m in evaluator["controlled_mutations"] if m["id"] == mutation_id), None)
            if selected is None:
                raise PacketValidationError(f"Unknown mutation {mutation_id}")
            mutation = {k: v for k, v in selected.items() if k != "public_operations"}
        return deepcopy({"annotation_status": data["annotation_status"], "hidden_world": evaluator["hidden_world"], "admissible_answer_spec": answer, "mutation": mutation, "record_warrant_checks": evaluator["record_warrant_checks"], "scoring_notes": evaluator["scoring_notes"], "operational_access": evaluator["operational_access"]})

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Packet":
        data = deepcopy(dict(data))
        _fields(data, {"fixture_id", "asset_type", "annotation_status", "export_requirement", "public_agent_input", "evaluator_only"}, set(), "authoring")
        _fields(data["public_agent_input"], {"shared_context", "baseline_corpus", "question_settings"}, set(), "public_agent_input")
        _fields(data["evaluator_only"], {"hidden_world", "admissible_answer_specs", "record_warrant_checks", "controlled_mutations", "scoring_notes", "operational_access"}, set(), "evaluator_only")
        questions = data["public_agent_input"]["question_settings"]
        mutations = data["evaluator_only"]["controlled_mutations"]
        _list(questions, "question_settings")
        _list(mutations, "controlled_mutations")
        if not questions:
            raise PacketValidationError("Packet has no questions")
        qids = [q.get("id") for q in questions]
        mids = [m.get("id") for m in mutations]
        if len(set(qids)) != len(qids) or len(set(mids)) != len(mids):
            raise PacketValidationError("Duplicate question or mutation identifier")
        for mutation in mutations:
            _fields(mutation, {"id", "name", "apply_to", "preconditions", "public_operations", "world_effect", "expected_relationships", "allowed_variation"}, set(), "mutation")
            _id(mutation["id"], "mutation", "mutation.id")
            _list(mutation["public_operations"], "public_operations")
        answers = data["evaluator_only"]["admissible_answer_specs"]
        _list(answers, "admissible_answer_specs")
        if len(answers) != len(qids) or {a.get("question_id") for a in answers} != set(qids):
            raise PacketValidationError("Oracle must identify exactly the declared questions")
        packet = cls(canonical_json(data))
        for question_id in qids:
            packet.public(question_id)
        for mutation_id in mids:
            packet.public(qids[0], mutation_id)
        return packet


def load_packet(path: str | Path = DEFAULT_PACKET_PATH) -> Packet:
    """Load and validate authoring data; no network or executable patch language."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PacketValidationError(f"Invalid packet JSON: {exc}") from exc
    return Packet.from_dict(data)
