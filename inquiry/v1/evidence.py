"""Deterministic corpus tools and worker-specific evidence exposure accounting.

There is no network access here. This is an evidence interface for trusted local
orchestration, not an OS security sandbox. A tool return is not a reading event:
the caller must record the exact material included in a worker input via expose.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .packets import canonical_json, content_hash, current_versions, validate_public_case


class EvidenceError(ValueError):
    """Invalid tool request, reference, or claimed exposure."""


@dataclass(frozen=True)
class QuoteVerification:
    valid: bool
    reason: str
    exposure_ids: tuple[str, ...] = ()
    is_current: bool = False


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


def _scalar_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)


class EvidenceEnvironment:
    """A private corpus plus deterministic tools, with no oracle reference.

    ``limit`` on open/read_table is a character limit, not a token estimate.
    Source versions and locators are always explicit. Origin sets trace declared
    lineage; they do not certify statistical or evidential independence.
    """

    def __init__(self, public_case: Mapping[str, Any], mode: str = "supplied"):
        public_case = deepcopy(dict(public_case))
        validate_public_case(public_case)
        if mode not in {"supplied", "documents", "search"}:
            raise EvidenceError("mode must be supplied, documents, or search")
        self.mode = mode
        self._case = public_case
        self._current = current_versions(public_case["corpus"])
        self._sources = {(d["id"], d["version"]): deepcopy(d) for d in public_case["corpus"]["documents"]}
        self._source_hashes = {key: content_hash(document) for key, document in self._sources.items()}
        self._origins: dict[tuple[str, str], list[str]] = {}
        self._all_segments: dict[tuple[str, str], list[dict]] = {}
        self._log: list[dict] = []
        self._issued_segments: dict[str, dict] = {}
        self._issued_documents: set[tuple[str, str]] = set()
        self._call_count = 0
        self._exposure_count = 0
        for key in self._sources:
            self._resolve_origins(key)
            self._all_segments[key] = self._make_segments(key)
        self._log.append({"phase": "available", "mode": mode, "sources": self._manifest()})

    @property
    def current_versions(self) -> dict[str, str]:
        return dict(self._current)

    @property
    def source_lookup(self) -> dict[tuple[str, str], dict]:
        result = deepcopy(self._sources)
        for key, record in result.items():
            record.update(content_hash=self._source_hashes[key], source_content_hash=self._source_hashes[key], origin_ids=list(self._origins[key]), root_origin_ids=list(self._origins[key]), is_current=self._current[key[0]] == key[1])
        return result

    @property
    def exposure_log(self) -> list[dict]:
        return deepcopy(self._log)

    @property
    def exposures(self) -> list[dict]:
        return [deepcopy(entry) for entry in self._log if entry["phase"] == "worker_input"]

    @property
    def tool_events(self) -> list[dict]:
        return [deepcopy(entry) for entry in self._log if entry["phase"] == "tool_returned"]

    @property
    def events(self) -> list[dict]:
        return self.exposure_log

    def _resolve_origins(self, key: tuple[str, str]) -> list[str]:
        if key not in self._origins:
            source = self._sources[key]
            if source.get("derived_from"):
                roots = {origin for ref in source["derived_from"] for origin in self._resolve_origins((ref["document_id"], ref["version"]))}
            else:
                roots = {source["origin_id"]}
            self._origins[key] = sorted(roots)
        return self._origins[key]

    def _source(self, source_id: str, version: str) -> tuple[tuple[str, str], dict]:
        key = (source_id, version)
        if key not in self._sources:
            raise EvidenceError(f"Unknown source version: {source_id}@{version}")
        return key, self._sources[key]

    def _segment(self, key: tuple[str, str], locator: str, text: str, kind: str, **extra: Any) -> dict:
        return {"source_id": key[0], "version": key[1], "locator": locator, "text": text, "start": 0, "end": len(text), "kind": kind, "source_content_hash": self._source_hashes[key], "content_hash": _text_hash(text), "complete": True, **extra}

    def _make_segments(self, key: tuple[str, str]) -> list[dict]:
        source = self._sources[key]
        result = [self._segment(key, block["locator"], block["text"], "reading_block") for block in source["reading_blocks"]]
        for table in source.get("tables", []):
            prefix = "table:" + table["id"]
            if table.get("title"):
                result.append(self._segment(key, prefix + "/title", table["title"], "table_title", table_id=table["id"]))
            for column in table["columns"]:
                result.append(self._segment(key, prefix + "/header:" + column, column, "table_header", table_id=table["id"], column=column))
                if column in table.get("column_units", {}):
                    result.append(self._segment(key, prefix + "/unit:" + column, table["column_units"][column], "table_unit", table_id=table["id"], column=column))
            for row in table["rows"]:
                for column in table["columns"]:
                    result.append(self._segment(key, prefix + "/row:" + row["id"] + "/column:" + column, _scalar_text(row["cells"][column]), "table_cell", table_id=table["id"], row_id=row["id"], column=column))
            for index, note in enumerate(table.get("footnotes", []), start=1):
                result.append(self._segment(key, prefix + "/footnote:" + str(index), note, "table_footnote", table_id=table["id"]))
        return result

    def _manifest(self) -> list[dict]:
        return [{"source_id": key[0], "version": key[1], "title": source["title"], "issuer_id": source["issuer_id"], "origin_ids": self._origins[key], "issued_at": source["issued_at"], "is_current": self._current[key[0]] == key[1], "source_content_hash": self._source_hashes[key], "locators": [s["locator"] for s in self._all_segments.get(key, [])]} for key, source in self._sources.items()]

    @staticmethod
    def _limit(limit: int | None) -> None:
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
            raise EvidenceError("Character limit must be a nonnegative integer or None")

    def _slice(self, segment: dict, start: int, end: int) -> dict:
        text = segment["text"][start:end]
        return {**deepcopy(segment), "text": text, "start": start, "end": start + len(text), "complete": start == 0 and end >= len(segment["text"]), "content_hash": _text_hash(text)}

    def _bounded(self, segments: list[dict], limit: int | None) -> tuple[list[dict], dict]:
        self._limit(limit)
        remaining = sum(len(s["text"]) for s in segments) if limit is None else limit
        returned = []
        for segment in segments:
            if remaining <= 0:
                break
            used = min(len(segment["text"]), remaining)
            returned.append(self._slice(segment, 0, used))
            remaining -= used
        available = sum(len(s["text"]) for s in segments)
        count = sum(len(s["text"]) for s in returned)
        return returned, {"characters_returned": count, "characters_available": available, "available_locators": [s["locator"] for s in segments], "returned_locators": [s["locator"] for s in returned], "truncated": count < available}

    def _return(self, tool: str, request: dict, payload: dict) -> dict:
        self._call_count += 1
        self._issue_payload(payload)
        result = {"tool": tool, "tool_call_id": f"tool_{self._call_count:06d}", **payload}
        self._log.append({"phase": "tool_returned", "tool": tool, "tool_call_id": result["tool_call_id"], "request": deepcopy(request), "response": deepcopy(result), "response_hash": content_hash(result)})
        return deepcopy(result)

    @staticmethod
    def _segment_id(segment: Mapping[str, Any]) -> str:
        identity = {key: segment[key] for key in ("source_id", "version", "locator", "start", "end", "text", "source_content_hash", "content_hash")}
        return "segment_" + content_hash(identity)

    def _issue(self, segment: dict) -> dict:
        result = deepcopy(segment)
        result["segment_id"] = self._segment_id(result)
        self._issued_segments[result["segment_id"]] = deepcopy(result)
        return result

    def _issue_payload(self, content: Any) -> None:
        if isinstance(content, dict):
            if {"source_id", "version", "locator", "text", "start", "end", "source_content_hash", "content_hash"} <= content.keys():
                content.update(self._issue(content))
            else:
                for value in content.values():
                    self._issue_payload(value)
        elif isinstance(content, list):
            for value in content:
                self._issue_payload(value)

    def initial_input(self, worker_id: str = "proposer", record_exposure: bool = True) -> dict:
        """Build the initial input, optionally recording its actual inclusion.

        A controller reserving budgets first uses record_exposure=False, then
        calls expose only when the model call is admitted. Preparation is not
        evidence that the worker actually received the material.
        """
        result = {"shared_context": deepcopy(self._case["shared_context"]), "question": deepcopy(self._case["question"])}
        if self.mode == "supplied":
            result["corpus"] = deepcopy(self._case["corpus"])
            self._issued_documents.update(self._sources)
            refs = [self._issue(segment) for segments in self._all_segments.values() for segment in segments]
        else:
            refs = []
            if self.mode == "documents":
                result["source_manifest"] = deepcopy(self._manifest())
        if record_exposure:
            self.expose(worker_id, content=result, references=refs)
        return result

    def search(self, query: str, filters: Mapping[str, Any] | None = None, limit: int = 5) -> dict:
        if not isinstance(query, str) or not query.strip():
            raise EvidenceError("Search query must be a nonempty string")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise EvidenceError("Search limit must be between 1 and 100")
        filters = dict(filters or {})
        if set(filters) - {"source_id", "issuer_id", "origin_id", "version", "current_only"}:
            raise EvidenceError("Unsupported search filter")
        if not isinstance(filters.get("current_only", True), bool):
            raise EvidenceError("current_only must be boolean")
        terms = set(_tokens(query))
        hits = []
        for key, source in self._sources.items():
            if filters.get("current_only", True) and self._current[key[0]] != key[1]:
                continue
            if any(source.get("id" if field == "source_id" else field) != value for field, value in filters.items() if field != "current_only"):
                continue
            scored = []
            for segment in self._all_segments[key]:
                counts = Counter(_tokens(segment["text"]))
                scored.append((sum(counts[t] for t in terms), segment))
            title_score = sum(t in set(_tokens(source["title"])) for t in terms)
            score = sum(n for n, _ in scored) + 2 * title_score
            if not score:
                continue
            best_score, segment = max(scored, key=lambda item: (item[0], -self._all_segments[key].index(item[1])))
            positions = [match.start() for match in re.finditer(r"\w+", segment["text"], re.UNICODE) if match.group().casefold() in terms]
            start = max(0, min(positions) - 40) if positions else 0
            snippet = self._slice(segment, start, start + 240)
            hits.append({"source_id": key[0], "version": key[1], "title": source["title"], "issuer_id": source["issuer_id"], "origin_ids": list(self._origins[key]), "is_current": self._current[key[0]] == key[1], "source_content_hash": self._source_hashes[key], "score": score, "snippet": snippet["text"], "locator": snippet["locator"], "segments": [snippet]})
        hits.sort(key=lambda hit: (-hit["score"], hit["source_id"], hit["version"]))
        return self._return("search", {"query": query, "filters": filters, "limit": limit}, {"query": query, "hits": hits[:limit], "total_matches": len(hits), "truncated": len(hits) > limit, "current_only": filters.get("current_only", True), "ranking": "lexical_counts_title_weight_2_stable_source_id_version"})

    def open(self, source_id: str, version: str, locator: str | None = None, limit: int | None = None) -> dict:
        key, source = self._source(source_id, version)
        selected = self._all_segments[key]
        if locator is not None:
            selected = [s for s in selected if s["locator"] == locator]
            if not selected:
                raise EvidenceError(f"Unknown locator: {locator}")
        segments, coverage = self._bounded(selected, limit)
        coverage["complete_document"] = locator is None and not coverage["truncated"]
        return self._return("open", {"source_id": source_id, "version": version, "locator": locator, "limit": limit}, {"source_id": source_id, "version": version, "title": source["title"], "is_current": self._current[source_id] == version, "origin_ids": list(self._origins[key]), "source_content_hash": self._source_hashes[key], "segments": segments, "coverage": coverage, "truncated": coverage["truncated"]})

    def read_table(self, source_id: str, version: str, table_id: str, rows: Sequence[str] | None = None, columns: Sequence[str] | None = None, limit: int | None = None) -> dict:
        key, source = self._source(source_id, version)
        table = next((t for t in source.get("tables", []) if t["id"] == table_id), None)
        if table is None:
            raise EvidenceError(f"Unknown table: {table_id}")
        row_ids = [row["id"] for row in table["rows"]]
        requested_rows = row_ids if rows is None else list(rows)
        requested_columns = table["columns"] if columns is None else list(columns)
        if len(set(requested_rows)) != len(requested_rows) or not set(requested_rows) <= set(row_ids) or len(set(requested_columns)) != len(requested_columns) or not set(requested_columns) <= set(table["columns"]):
            raise EvidenceError("Unknown or duplicate table rows/columns")
        selected = [s for s in self._all_segments[key] if s.get("table_id") == table_id and (s.get("row_id") is None or s["row_id"] in requested_rows) and (s.get("column") is None or s["column"] in requested_columns)]
        segments, coverage = self._bounded(selected, limit)
        coverage["complete_table"] = rows is None and columns is None and not coverage["truncated"]
        coverage["complete_document"] = False
        return self._return("read_table", {"source_id": source_id, "version": version, "table_id": table_id, "rows": requested_rows, "columns": requested_columns, "limit": limit}, {"source_id": source_id, "version": version, "table_id": table_id, "is_current": self._current[source_id] == version, "source_content_hash": self._source_hashes[key], "segments": segments, "coverage": coverage, "truncated": coverage["truncated"]})

    def _validate_segment(self, reference: Mapping[str, Any], *, allow_restore: bool = False) -> dict:
        source_id = reference.get("source_id", reference.get("document_id"))
        key, _ = self._source(source_id, reference.get("version"))
        locator = reference.get("locator")
        original = next((s for s in self._all_segments[key] if s["locator"] == locator), None)
        if original is None:
            raise EvidenceError(f"Exposure refers to unknown locator: {locator}")
        text = reference.get("text", original["text"])
        if not isinstance(text, str):
            raise EvidenceError("Exposed source text must be a string")
        start = reference.get("start", original["text"].find(text))
        if not isinstance(start, int) or start < 0 or original["text"][start:start + len(text)] != text:
            raise EvidenceError("Exposed text does not match this exact source segment")
        if reference.get("source_content_hash", self._source_hashes[key]) != self._source_hashes[key]:
            raise EvidenceError("Exposure has the wrong source content hash")
        if reference.get("content_hash", _text_hash(text)) != _text_hash(text):
            raise EvidenceError("Exposure has the wrong segment content hash")
        if reference.get("end", start + len(text)) != start + len(text):
            raise EvidenceError("Exposure has an inconsistent span")
        result = self._slice(original, start, start + len(text))
        segment_id = self._segment_id(result)
        if reference.get("segment_id", segment_id) != segment_id:
            raise EvidenceError("Exposure has an invalid issued-segment identity")
        if not allow_restore and segment_id not in self._issued_segments:
            raise EvidenceError("Source span was never issued by this evidence environment")
        result["segment_id"] = segment_id
        return result

    def _collect_segments(self, content: Any) -> list[dict]:
        result = []
        if isinstance(content, dict):
            if {"segment_id", "source_id", "version", "locator", "text", "source_content_hash", "content_hash"} <= content.keys():
                return [self._validate_segment(content)]
            if {"id", "version", "reading_blocks"} <= content.keys():
                key = (content["id"], content["version"])
                if key in self._issued_documents and content_hash(content) == self._source_hashes[key]:
                    return [self._validate_segment(self._issue(segment)) for segment in self._all_segments[key]]
            for value in content.values():
                result.extend(self._collect_segments(value))
        elif isinstance(content, list):
            for value in content:
                result.extend(self._collect_segments(value))
        return result

    @staticmethod
    def _strings(content: Any) -> list[str]:
        if isinstance(content, str):
            return [content]
        if isinstance(content, dict):
            return [s for value in content.values() for s in EvidenceEnvironment._strings(value)]
        if isinstance(content, list):
            return [s for value in content for s in EvidenceEnvironment._strings(value)]
        return [_scalar_text(content)] if content is not None else []

    def expose(self, worker_id: str, content: Any = None, references: Sequence[Mapping[str, Any]] | None = None) -> dict:
        """Record material actually included by trusted orchestration in an input.

        Pass an exact tool-result object, or explicit source/span references. With
        content and references together, each referenced text must occur in the
        supplied input. References alone construct the material the caller must
        include. Arbitrary prose without source references earns no quote credit.
        """
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise EvidenceError("worker_id must be nonempty")
        segments = self._collect_segments(content)
        if references is not None:
            strings = self._strings(content) if content is not None else []
            for reference in references:
                segment = self._validate_segment(reference)
                if content is not None and not any(segment["text"] in value for value in strings):
                    raise EvidenceError("Referenced source span is absent from the actual worker input")
                segments.append(segment)
        unique = {}
        for segment in segments:
            unique[(segment["source_id"], segment["version"], segment["locator"], segment["start"], segment["end"])] = segment
        self._exposure_count += 1
        actual = content if content is not None else {"segments": list(unique.values())}
        entry = {"phase": "worker_input", "exposure_id": f"exposure_{self._exposure_count:06d}", "worker_id": worker_id, "content_hash": content_hash(actual), "segments": list(unique.values())}
        self._log.append(deepcopy(entry))
        return deepcopy(entry)

    def restore_exposures(self, entries: Sequence[Mapping[str, Any]]) -> None:
        """Restore a trusted saved worker-input log, checking exact source spans.

        No model is called and no tool-return event is promoted into an exposure.
        This cannot authenticate a fabricated log; integrity of the saved run is
        the caller's responsibility. This method is not a worker-facing tool.
        """
        seen = {entry["exposure_id"] for entry in self.exposures}
        validated = []
        for entry in entries:
            entry = deepcopy(dict(entry))
            if entry.get("phase") != "worker_input" or not isinstance(entry.get("worker_id"), str) or not entry["worker_id"]:
                raise EvidenceError("Only worker_input entries can be restored")
            identifier = entry.get("exposure_id", "")
            if not re.fullmatch(r"exposure_[0-9]+", identifier) or identifier in seen:
                raise EvidenceError("Invalid or duplicate exposure identity")
            if not re.fullmatch(r"[0-9a-f]{64}", entry.get("content_hash", "")):
                raise EvidenceError("Invalid saved input hash")
            if not isinstance(entry.get("segments"), list):
                raise EvidenceError("Missing saved source segments")
            entry["segments"] = [self._validate_segment(segment, allow_restore=True) for segment in entry["segments"]]
            seen.add(identifier)
            validated.append(entry)
        for entry in validated:
            for segment in entry["segments"]:
                self._issue(segment)
            self._log.append(entry)
            self._exposure_count = max(self._exposure_count, int(entry["exposure_id"].split("_")[1]))

    def verify_quote(self, worker_id: str, source_id: str, version: str, quote: str, locator: str | None = None) -> QuoteVerification:
        """Verify literal source-and-exposure correspondence, never entailment."""
        key = (source_id, version)
        is_current = self._current.get(source_id) == version
        if key not in self._sources:
            return QuoteVerification(False, "unknown_source_version")
        if not isinstance(quote, str) or not quote:
            return QuoteVerification(False, "empty_or_invalid_quote", is_current=is_current)
        candidates = [s for s in self._all_segments[key] if locator is None or s["locator"] == locator]
        if not candidates:
            return QuoteVerification(False, "unknown_locator", is_current=is_current)
        if not any(quote in s["text"] for s in candidates):
            return QuoteVerification(False, "quote_not_in_source", is_current=is_current)
        exposures = []
        for entry in self._log:
            if entry["phase"] != "worker_input" or entry["worker_id"] != worker_id:
                continue
            if any(s["source_id"] == source_id and s["version"] == version and (locator is None or s["locator"] == locator) and quote in s["text"] for s in entry["segments"]):
                exposures.append(entry["exposure_id"])
        if not exposures:
            return QuoteVerification(False, "quote_not_exposed_to_worker", is_current=is_current)
        return QuoteVerification(True, "exact_quote_in_exposed_source_segment", tuple(exposures), is_current)
