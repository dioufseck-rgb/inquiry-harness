from copy import deepcopy
import json

import pytest

from inquiry.v1.contracts import InquiryRequest, InquiryValidationError, validate_inquiry_request
from inquiry.v1.evidence import EvidenceEnvironment, EvidenceError


def incident_request():
    original = {
        "id": "telemetry/checkout", "version": "raw", "title": "Checkout timing sample",
        "issuer_id": "observability team", "origin_id": "trace:46de", "issued_at": "2026-11-12", "language": "en",
        "reading_blocks": [{"locator": "summary", "text": "The sampled checkout request completed in 240 milliseconds."}],
    }
    corrected = deepcopy(original)
    corrected.update(version="corrected", supersedes={"document_id": original["id"], "version": original["version"]})
    corrected["reading_blocks"][0]["text"] = "The corrected sample completed in 210 milliseconds; queue time was excluded."
    table = {
        "id": "measurement table", "title": "Trace measurements", "columns": ["duration", "included"],
        "column_units": {"duration": "milliseconds"},
        "rows": [{"id": "request A", "cells": {"duration": 210, "included": True}}],
        "footnotes": ["Queue time is excluded from duration."],
    }
    corrected["tables"] = [table]
    digest = {
        "id": "incident digest / 7", "version": "published", "title": "Checkout observation digest",
        "issuer_id": "release team", "origin_id": "digest:editor", "publication_origin_id": "digest:editor",
        "issued_at": "2026-11-13", "language": "en",
        "reading_blocks": [{"locator": "observation", "text": "The trace records a duration of 210 milliseconds."}],
        "derived_from": [{"document_id": corrected["id"], "version": corrected["version"],
                          "locator": "table:measurement table/row:request A/column:duration"}],
    }
    return {
        "shared_context": {"as_of": "2026-11-14", "service": "checkout", "analysis_window_minutes": 30},
        "corpus": {"documents": [original, corrected, digest],
                   "current_versions": {"telemetry/checkout": "corrected", "incident digest / 7": "published"}},
        "question": {"id": "latency finding", "question": "What does the corrected trace record?",
                     "intended_use": "Inform the caller's incident analysis",
                     "scope": {"service": "checkout", "request_ids": ["A"], "queue_included": False},
                     "target": {"kind": "attribution", "form": "source_reports"},
                     "profile": {"id": "incident evidence", "version": "v2", "authority": "Incident coordinator",
                                 "requirements": ["Preserve timing units and exclusions."], "kernel": {}}},
    }


@pytest.mark.parametrize("mode", ["supplied", "documents", "search"])
def test_generic_evidence_modes_preserve_the_same_public_question_and_provenance(mode):
    value = incident_request()
    env = EvidenceEnvironment(InquiryRequest.model_validate(value), mode)
    initial = env.initial_input("analyst")
    assert initial["question"] == value["question"]
    assert initial["shared_context"] == value["shared_context"]
    assert env.current_versions == value["corpus"]["current_versions"]
    assert env.source_lookup[("incident digest / 7", "published")]["root_origin_ids"] == ["trace:46de"]
    assert "digest:editor" not in env.source_lookup[("incident digest / 7", "published")]["origin_ids"]
    quote = "210 milliseconds; queue time was excluded."
    assert env.verify_quote("analyst", "telemetry/checkout", "corrected", quote).valid is (mode == "supplied")
    if mode != "supplied":
        assert "corpus" not in initial
        assert quote not in json.dumps(initial)
        assert env.exposures[0]["segments"] == []


def test_corrected_and_historical_sources_have_distinct_exposure_credit():
    env = EvidenceEnvironment(incident_request(), "search")
    current = env.search("milliseconds")
    assert {(hit["source_id"], hit["version"]) for hit in current["hits"]} == {
        ("telemetry/checkout", "corrected"), ("incident digest / 7", "published"),
    }
    all_versions = env.search("milliseconds", filters={"current_only": False})
    assert any(hit["version"] == "raw" for hit in all_versions["hits"])
    assert not env.verify_quote("analyst", "telemetry/checkout", "raw", "240 milliseconds").valid
    historical = env.open("telemetry/checkout", "raw", "summary")
    env.expose("analyst", content=historical)
    verification = env.verify_quote("analyst", "telemetry/checkout", "raw", "240 milliseconds", "summary")
    assert verification.valid and not verification.is_current
    assert not env.verify_quote("analyst", "telemetry/checkout", "corrected", "210 milliseconds").valid


def test_table_lineage_and_units_remain_evidence_with_exact_worker_exposure():
    env = EvidenceEnvironment(incident_request(), "documents")
    initial = env.initial_input("reader")
    manifest = next(item for item in initial["source_manifest"] if item["source_id"] == "telemetry/checkout" and item["version"] == "corrected")
    assert manifest["table_ids"] == ["measurement table"]
    result = env.read_table("telemetry/checkout", "corrected", "measurement table", rows=["request A"], columns=["duration"])
    by_locator = {segment["locator"]: segment["text"] for segment in result["segments"]}
    assert by_locator["table:measurement table/row:request A/column:duration"] == "210"
    assert by_locator["table:measurement table/unit:duration"] == "milliseconds"
    assert by_locator["table:measurement table/footnote:1"] == "Queue time is excluded from duration."
    assert not env.verify_quote("reader", "telemetry/checkout", "corrected", "210").valid
    env.expose("reader", content=result)
    assert env.verify_quote("reader", "telemetry/checkout", "corrected", "210",
                            "table:measurement table/row:request A/column:duration").valid
    assert not env.verify_quote("reviewer", "telemetry/checkout", "corrected", "210").valid


def test_arbitrary_source_locators_cannot_collide_with_generated_table_addresses():
    value = incident_request()
    value["corpus"]["documents"][1]["reading_blocks"].append({
        "locator": "table:measurement table/row:request A/column:duration", "text": "A different value",
    })
    with pytest.raises(InquiryValidationError, match="duplicate source locator"):
        EvidenceEnvironment(value)


def test_unissued_and_forged_generic_source_spans_never_earn_quote_credit():
    env = EvidenceEnvironment(incident_request(), "documents")
    with pytest.raises(EvidenceError, match="never issued"):
        env.expose("analyst", references=[{"source_id": "telemetry/checkout", "version": "corrected", "locator": "summary"}])
    opened = env.open("telemetry/checkout", "corrected", "summary")
    forged = deepcopy(opened)
    forged["segments"][0]["text"] = "No incident occurred."
    with pytest.raises(EvidenceError, match="does not match"):
        env.expose("analyst", content=forged)
    env.expose("analyst", content=opened)
    restored = EvidenceEnvironment(incident_request(), "documents")
    restored.restore_exposures(env.exposures)
    assert restored.verify_quote("analyst", "telemetry/checkout", "corrected", "queue time was excluded").valid
    assert restored.tool_events == []


@pytest.mark.parametrize("field", ["start", "end"])
def test_boolean_span_boundaries_are_not_accepted_as_integer_offsets(field):
    env = EvidenceEnvironment(incident_request(), "documents")
    opened = env.open("telemetry/checkout", "corrected", "summary", limit=1)
    opened["segments"][0][field] = False if field == "start" else True
    with pytest.raises(EvidenceError):
        env.expose("analyst", content=opened)
    assert env.exposures == []


def test_deep_lineage_is_validated_and_resolved_without_python_recursion():
    value = incident_request()
    document = value["corpus"]["documents"][0]
    documents = [document]
    for index in range(1100):
        relay = deepcopy(document)
        relay.update(id=f"relay/{index}", origin_id=f"publisher/{index}",
                     derived_from=[{"document_id": documents[-1]["id"], "version": document["version"]}])
        documents.append(relay)
    value["corpus"] = {"documents": list(reversed(documents)),
                       "current_versions": {item["id"]: item["version"] for item in documents}}
    validate_inquiry_request(value)
    env = EvidenceEnvironment(value, "search")
    assert env.source_lookup[("relay/1099", "raw")]["origin_ids"] == ["trace:46de"]


def test_core_does_not_convert_legacy_corpus_roles():
    value = incident_request()
    value["corpus"].pop("current_versions")
    value["corpus"]["case_account"] = {"document_id": "telemetry/checkout", "version": "corrected"}
    with pytest.raises(InquiryValidationError, match="case_account"):
        EvidenceEnvironment(value)
