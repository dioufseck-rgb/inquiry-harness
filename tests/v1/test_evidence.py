from copy import deepcopy
import json

import pytest

from inquiry.v1.evidence import EvidenceEnvironment, EvidenceError
from inquiry.v1.packets import content_hash, load_packet


@pytest.fixture
def public_case():
    return load_packet().public("question_001")


def test_supplied_mode_records_exact_worker_exposure(public_case):
    env = EvidenceEnvironment(public_case)
    actual = env.initial_input("proposer")
    assert actual == public_case
    quote = "80 programme credits of wages"
    verification = env.verify_quote("proposer", "doc_003", "1.0", quote, "field_group_2")
    assert verification.valid and verification.is_current
    assert verification.exposure_ids == ("exposure_000001",)
    assert not env.verify_quote("critic", "doc_003", "1.0", quote, "field_group_2").valid
    env.expose("critic", content={"task": actual, "draft": "review this"})
    assert env.verify_quote("critic", "doc_003", "1.0", quote, "field_group_2").valid


@pytest.mark.parametrize("mode", ["documents", "search"])
def test_initial_discovery_views_do_not_expose_source_text(public_case, mode):
    env = EvidenceEnvironment(public_case, mode)
    actual = env.initial_input()
    assert "corpus" not in actual
    assert ("source_manifest" in actual) is (mode == "documents")
    assert env.exposures[0]["segments"] == []
    assert not env.verify_quote("proposer", "doc_003", "1.0", "80 programme credits").valid


def test_prepared_input_is_not_exposed_until_admitted_call(public_case):
    env = EvidenceEnvironment(public_case, "supplied")
    prepared = env.initial_input(record_exposure=False)
    assert prepared == public_case
    assert env.exposures == []
    assert not env.verify_quote("proposer", "doc_003", "1.0", "80 programme credits").valid
    env.expose("proposer", content=prepared)
    assert env.verify_quote("proposer", "doc_003", "1.0", "80 programme credits").valid


def test_zero_call_run_records_no_worker_source_exposure(public_case):
    from inquiry.v1.demo import DemoWorker
    from inquiry.v1.runtime import Budget, run_inquiry

    result = run_inquiry(public_case, DemoWorker(), budget=Budget(max_model_calls=0))
    assert result["usage"]["model_calls"] == 0
    assert result["exposures"] == []


def test_returned_open_is_not_read_until_in_worker_input(public_case):
    env = EvidenceEnvironment(public_case, "documents")
    response = env.open("doc_003", "1.0", "field_group_2")
    assert env.tool_events[0]["phase"] == "tool_returned"
    assert not env.verify_quote("proposer", "doc_003", "1.0", "80 programme credits").valid
    env.expose("proposer", content={"tool_results": [response]})
    assert env.verify_quote("proposer", "doc_003", "1.0", "80 programme credits").valid
    assert not env.verify_quote("proposer", "doc_003", "1.0", "Household income statement").valid


def test_draft_echo_cannot_self_certify_guessed_source_quote(public_case):
    env = EvidenceEnvironment(public_case, "search")
    env.initial_input()
    guessed = {"source_id": "doc_003", "version": "1.0", "locator": "field_group_2", "text": "80 programme credits", "quote": "80 programme credits"}
    env.expose("proposer", content={"previous_draft": guessed})
    assert env.exposures[-1]["segments"] == []
    assert not env.verify_quote("proposer", "doc_003", "1.0", "80 programme credits").valid
    fetched = env.open("doc_003", "1.0", "field_group_2")
    env.expose("critic", content={"previous_draft": guessed})
    assert not env.verify_quote("critic", "doc_003", "1.0", "80 programme credits").valid
    env.expose("critic", content={"actual_tool_evidence": fetched})
    assert env.verify_quote("critic", "doc_003", "1.0", "80 programme credits").valid


def test_truncation_cannot_earn_unseen_quote_credit(public_case):
    env = EvidenceEnvironment(public_case, "documents")
    response = env.open("doc_003", "1.0", "field_group_2", limit=45)
    assert response["truncated"]
    assert response["coverage"]["characters_returned"] == 45
    assert not response["coverage"]["complete_document"]
    env.expose("proposer", response)
    assert env.verify_quote("proposer", "doc_003", "1.0", "My workplace closed").valid
    assert not env.verify_quote("proposer", "doc_003", "1.0", "80 programme credits").valid
    assert not env.verify_quote("proposer", "doc_003", "1.0", "My  workplace closed").valid


def test_open_coverage_distinguishes_block_from_complete_source(public_case):
    env = EvidenceEnvironment(public_case, "documents")
    block = env.open("doc_001", "1.0", "section_2")
    full = env.open("doc_001", "1.0")
    empty = env.open("doc_001", "1.0", limit=0)
    assert not block["coverage"]["complete_document"]
    assert full["coverage"]["complete_document"]
    assert len(full["segments"]) == 4
    assert empty["segments"] == [] and empty["truncated"]
    assert not env.verify_quote("proposer", "doc_001", "1.0", full["segments"][0]["text"]).valid


def test_search_supports_new_queries_with_stable_ranking(public_case):
    env1 = EvidenceEnvironment(public_case, "search")
    env2 = EvidenceEnvironment(deepcopy(public_case), "search")
    for query in ("wages scheduled shift", "register residence income", "flooding street morning", "unmatchablexyz"):
        assert env1.search(query) == env2.search(query)
    assert env1.search("scheduled wages")["hits"][0]["source_id"] == "doc_003"
    assert env1.search("unmatchablexyz")["total_matches"] == 0
    filtered = env1.search("flood", filters={"source_id": "doc_002"})
    assert {hit["source_id"] for hit in filtered["hits"]} <= {"doc_002"}


def test_search_returns_exact_snippets_with_separate_exposure(public_case):
    env = EvidenceEnvironment(public_case, "search")
    result = env.search("financial disruption", filters={"source_id": "doc_001"})
    hit = result["hits"][0]
    snippet = hit["segments"][0]
    assert hit["snippet"] == snippet["text"]
    assert len(snippet["text"]) <= 240
    assert not env.verify_quote("proposer", hit["source_id"], hit["version"], snippet["text"], hit["locator"]).valid
    env.expose("proposer", result)
    assert env.verify_quote("proposer", hit["source_id"], hit["version"], snippet["text"], hit["locator"]).valid


def test_current_version_search_and_historical_attribution_are_distinct():
    env = EvidenceEnvironment(load_packet().public("question_002", "mutation_004"), "search")
    hits = env.search("North Wharf")
    assert all(hit["source_id"] != "doc_002" or hit["version"] == "2.0" for hit in hits["hits"])
    history = env.search("North Wharf", {"source_id": "doc_002", "current_only": False})
    assert {hit["version"] for hit in history["hits"]} == {"1.0", "2.0"}
    old = env.open("doc_002", "1.0", "paragraph_1")
    env.expose("proposer", old)
    verification = env.verify_quote("proposer", "doc_002", "1.0", "street flooding in North Wharf block")
    assert verification.valid and not verification.is_current
    assert env.current_versions["doc_002"] == "2.0"


def test_relay_root_origin_is_not_publisher_count():
    env = EvidenceEnvironment(load_packet().public("question_002", "mutation_001"))
    sources = env.source_lookup
    assert sources["doc_004", "1.0"]["origin_ids"] == sources["doc_002", "1.0"]["origin_ids"] == ["origin_002"]
    assert sources["doc_004", "1.0"]["publication_origin_id"] == "origin_004"


def test_forged_exposure_hash_or_text_is_rejected(public_case):
    env = EvidenceEnvironment(public_case, "documents")
    result = env.open("doc_003", "1.0", "field_group_2")
    forged = deepcopy(result)
    forged["segments"][0]["text"] = "Invented loss of 800 credits"
    with pytest.raises(EvidenceError, match="does not match"):
        env.expose("proposer", forged)
    forged = deepcopy(result)
    forged["segments"][0]["source_content_hash"] = "0" * 64
    with pytest.raises(EvidenceError, match="source content hash"):
        env.expose("proposer", forged)
    forged = deepcopy(result)
    forged["segments"][0]["segment_id"] = "segment_fabricated"
    with pytest.raises(EvidenceError, match="segment identity"):
        env.expose("proposer", forged)
    assert env.exposures == []


def test_explicit_references_must_be_issued_and_in_actual_input(public_case):
    env = EvidenceEnvironment(public_case, "documents")
    ref = {"source_id": "doc_003", "version": "1.0", "locator": "field_group_2"}
    with pytest.raises(EvidenceError, match="never issued"):
        env.expose("proposer", references=[ref])
    result = env.open("doc_003", "1.0", "field_group_2")
    with pytest.raises(EvidenceError, match="absent from the actual"):
        env.expose("proposer", content="This prompt contains no source text.", references=[ref])
    env.expose("proposer", content=result["segments"][0]["text"], references=[ref])
    assert env.verify_quote("proposer", "doc_003", "1.0", "80 programme credits").valid


def test_restored_exposures_verify_without_any_model_or_tool_call(public_case):
    original = EvidenceEnvironment(public_case, "documents")
    original.expose("proposer", original.open("doc_003", "1.0", "field_group_2"))
    saved = json.loads(json.dumps(original.exposures))
    replayed = EvidenceEnvironment(public_case, "documents")
    replayed.restore_exposures(saved)
    assert replayed.tool_events == []
    assert replayed.exposures == saved
    assert replayed.verify_quote("proposer", "doc_003", "1.0", "80 programme credits").valid
    assert not replayed.verify_quote("critic", "doc_003", "1.0", "80 programme credits").valid
    tampered = deepcopy(saved)
    tampered[0]["segments"][0]["text"] = "invented"
    with pytest.raises(EvidenceError):
        EvidenceEnvironment(public_case).restore_exposures(tampered)
    with pytest.raises(EvidenceError, match="Only worker_input"):
        EvidenceEnvironment(public_case).restore_exposures(original.tool_events)


def test_source_and_log_properties_cannot_mutate_environment(public_case):
    env = EvidenceEnvironment(public_case)
    env.initial_input()
    lookup = env.source_lookup
    lookup["doc_003", "1.0"]["reading_blocks"][1]["text"] = "tampered"
    versions = env.current_versions
    versions["doc_003"] = "99.0"
    log = env.exposures
    log[0]["segments"].clear()
    assert env.verify_quote("proposer", "doc_003", "1.0", "80 programme credits").valid
    assert env.current_versions["doc_003"] == "1.0"
    expected = next(d for d in public_case["corpus"]["documents"] if d["id"] == "doc_003")
    assert env.source_lookup["doc_003", "1.0"]["content_hash"] == content_hash(expected)


def table_case(public_case):
    case = deepcopy(public_case)
    case["corpus"]["documents"][2]["tables"] = [{"id": "payroll", "title": "Reported shift amounts", "columns": ["hours", "wages"], "column_units": {"hours": "hours", "wages": "programme credits"}, "rows": [{"id": "row_1", "cells": {"hours": 4, "wages": 80}}, {"id": "row_2", "cells": {"hours": 2, "wages": 40}}], "footnotes": ["Applicant-reported amounts; not independent payroll verification."]}]
    return case


def test_table_read_preserves_cells_units_footnotes_and_coverage(public_case):
    env = EvidenceEnvironment(table_case(public_case), "documents")
    result = env.read_table("doc_003", "1.0", "payroll", rows=["row_1"], columns=["wages"])
    assert not result["coverage"]["complete_table"]
    assert not result["coverage"]["complete_document"]
    assert [s["text"] for s in result["segments"] if s["kind"] == "table_cell"] == ["80"]
    assert any(s["kind"] == "table_unit" and s["text"] == "programme credits" for s in result["segments"])
    assert any(s["kind"] == "table_footnote" for s in result["segments"])
    env.expose("proposer", result)
    assert env.verify_quote("proposer", "doc_003", "1.0", "80", "table:payroll/row:row_1/column:wages").valid
    assert not env.verify_quote("proposer", "doc_003", "1.0", "40", "table:payroll/row:row_2/column:wages").valid
    full = env.read_table("doc_003", "1.0", "payroll")
    assert full["coverage"]["complete_table"]
    assert env.read_table("doc_003", "1.0", "payroll", limit=10)["truncated"]
    with pytest.raises(EvidenceError):
        env.read_table("doc_003", "1.0", "payroll", rows=["missing"])


@pytest.mark.parametrize("operation", [lambda e: e.open("doc_999", "1.0"), lambda e: e.open("doc_001", "99.0"), lambda e: e.open("doc_001", "1.0", "missing"), lambda e: e.open("doc_001", "1.0", limit=-1), lambda e: e.search("flood", {"oracle": True}), lambda e: e.search("flood", limit=0)])
def test_invalid_tool_requests_fail_explicitly(public_case, operation):
    with pytest.raises(EvidenceError):
        operation(EvidenceEnvironment(public_case))
