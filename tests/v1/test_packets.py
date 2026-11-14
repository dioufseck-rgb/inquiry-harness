from copy import deepcopy
import json

import pytest

from inquiry.v1.packets import DEFAULT_PACKET_PATH, Packet, PacketValidationError, current_versions, load_packet, validate_public_case


@pytest.fixture
def packet():
    return load_packet()


def documents(case):
    return {(d["id"], d["version"]): d for d in case["corpus"]["documents"]}


def block(document, locator):
    return next(b["text"] for b in document["reading_blocks"] if b["locator"] == locator)


def test_public_projection_is_allowlisted_and_independent_of_oracle():
    data = json.loads(DEFAULT_PACKET_PATH.read_text())
    sentinel = "SCORER_ONLY_SENTINEL_do_not_export"
    data["evaluator_only"]["hidden_world"]["private_sentinel"] = sentinel
    data["evaluator_only"]["admissible_answer_specs"][0]["world_truth"] = sentinel
    p = Packet.from_dict(data)
    case = p.public("question_004", "mutation_001")
    assert set(case) == {"shared_context", "corpus", "question"}
    serialized = json.dumps(case)
    for forbidden in [sentinel, "evaluator_only", "annotation_status", "hidden_world", "expected_relationships", "mutation_001", "Relay addition", "question_001", "question_005"]:
        assert forbidden not in serialized
    assert p.oracle("question_001")["admissible_answer_spec"]["world_truth"] == sentinel


def test_export_and_oracle_are_deep_copies(packet):
    first = packet.public("question_004")
    first["corpus"]["documents"][0]["reading_blocks"][0]["text"] = "changed"
    first["question"]["profile"]["requirements"].clear()
    oracle = packet.oracle("question_004")
    oracle["hidden_world"].clear()
    assert packet.public("question_004")["question"]["profile"]["requirements"]
    assert packet.public("question_004")["corpus"]["documents"][0]["reading_blocks"][0]["text"] != "changed"
    assert packet.oracle("question_004")["hidden_world"]
    assert packet.packet_hash == load_packet().packet_hash


def test_relay_keeps_original_observation_origin(packet):
    case = packet.public("question_002", "mutation_001")
    docs = documents(case)
    relay = docs["doc_004", "1.0"]
    assert relay["origin_id"] == docs["doc_002", "1.0"]["origin_id"]
    assert relay["publication_origin_id"] != relay["origin_id"]
    assert relay["derived_from"] == [{"document_id": "doc_002", "version": "1.0", "locator": "paragraph_1"}]
    assert any(e["id"] == "entity_003" for e in case["shared_context"]["entities"])


def test_missing_detail_is_new_current_version_and_keeps_history(packet):
    base = documents(packet.public("question_001"))
    case = packet.public("question_001", "mutation_002")
    docs = documents(case)
    assert docs["doc_003", "1.0"] == base["doc_003", "1.0"]
    assert current_versions(case["corpus"])["doc_003"] == "1.1"
    assert docs["doc_003", "1.1"]["supersedes"] == {"document_id": "doc_003", "version": "1.0"}
    assert block(docs["doc_003", "1.1"], "field_group_2") == "Personal financial-disruption description: not provided. Event date for the claimed impact: not provided."
    assert block(docs["doc_003", "1.1"], "field_group_1") == block(base["doc_003", "1.0"], "field_group_1")


def test_independent_trace_adds_only_declared_records(packet):
    case = packet.public("question_003", "mutation_003")
    docs = documents(case)
    trace = docs["doc_005", "1.0"]
    assert trace["origin_id"] == "origin_005"
    assert [b["locator"] for b in trace["reading_blocks"]] == ["operations_log", "roster_row_17", "payroll_row_17"]
    assert "person_001" in block(trace, "roster_row_17")
    assert len(docs) == 4
    assert docs["doc_003", "1.0"] == documents(packet.public("question_003"))["doc_003", "1.0"]


@pytest.mark.parametrize("mutation,source,binding", [("mutation_004", "doc_002", "current_event_record"), ("mutation_005", "doc_001", "current_policy")])
def test_correction_and_policy_revision_keep_history(packet, mutation, source, binding):
    baseline = documents(packet.public("question_004"))
    case = packet.public("question_004", mutation)
    docs = documents(case)
    assert case["corpus"][binding] == {"document_id": source, "version": "2.0"}
    assert docs[source, "1.0"] == baseline[source, "1.0"]
    assert docs[source, "2.0"]["supersedes"] == {"document_id": source, "version": "1.0"}
    assert current_versions(case["corpus"])[source] == "2.0"
    for key in baseline:
        assert docs[key] == baseline[key]


def test_alias_and_order_are_deterministic_and_preserve_identity(packet):
    baseline = packet.public("question_004")
    case = packet.public("question_004", "mutation_006")
    assert case == packet.public("question_004", "mutation_006")
    assert [d["id"] for d in case["corpus"]["documents"]] == ["doc_003", "doc_001", "doc_002"]
    docs = documents(case)
    for key, original in documents(baseline).items():
        revised = docs[key]
        assert [b["locator"] for b in revised["reading_blocks"]] == list(reversed([b["locator"] for b in original["reading_blocks"]]))
        for b in original["reading_blocks"]:
            assert block(revised, b["locator"]) == b["text"].replace("Mira Noll", "Rin Sela")
    assert next(e for e in case["shared_context"]["entities"] if e["id"] == "person_001")["name"] == "Rin Sela"
    assert "Mira Noll" not in json.dumps(case)
    assert "person_001" in json.dumps(case)
    assert case["question"] == baseline["question"]


def test_all_questions_and_mutations_export_valid_isolated_cases(packet):
    assert len(packet.question_ids) == 6
    assert len(packet.mutation_ids) == 6
    for question in packet.question_ids:
        for mutation in (None, *packet.mutation_ids):
            case = packet.public(question, mutation)
            validate_public_case(case)
            assert case["question"]["id"] == question
            assert "mutation" not in json.dumps(case)
    assert packet.oracle("question_001")["annotation_status"]["development_only"] is True
    assert packet.oracle("question_001")["annotation_status"]["human_adjudicated"] is False


@pytest.mark.parametrize("path", [("oracle",), ("shared_context", "evaluator_only"), ("question", "expected_answer"), ("question", "profile", "scorer_hint")])
def test_public_extra_fields_are_rejected(packet, path):
    case = packet.public("question_001")
    target = case
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = "leak"
    with pytest.raises(PacketValidationError, match="forbidden"):
        validate_public_case(case)


@pytest.mark.parametrize("change", ["duplicate_source", "unknown_current", "unknown_issuer", "unknown_locator", "lineage_cycle", "ambiguous_version", "descriptive_identifier"])
def test_source_integrity_errors_are_rejected(packet, change):
    case = packet.public("question_001")
    docs = case["corpus"]["documents"]
    if change == "duplicate_source":
        docs.append(deepcopy(docs[0]))
    elif change == "unknown_current":
        case["corpus"]["current_policy"]["version"] = "99.0"
    elif change == "unknown_issuer":
        docs[0]["issuer_id"] = "entity_999"
    elif change == "unknown_locator":
        docs[1]["derived_from"] = [{"document_id": "doc_001", "version": "1.0", "locator": "absent"}]
    elif change == "lineage_cycle":
        docs[0]["derived_from"] = [{"document_id": "doc_002", "version": "1.0"}]
        docs[1]["derived_from"] = [{"document_id": "doc_001", "version": "1.0"}]
    elif change == "ambiguous_version":
        revised = deepcopy(docs[0]); revised["version"] = "2.0"; docs.append(revised)
    else:
        docs[0]["id"] = "doc_expected_answer"
    with pytest.raises(PacketValidationError):
        validate_public_case(case)


def test_loader_rejects_unsupported_mutation_operation():
    data = json.loads(DEFAULT_PACKET_PATH.read_text())
    data["evaluator_only"]["controlled_mutations"][0]["public_operations"][0]["operation"] = "execute_python"
    with pytest.raises(PacketValidationError, match="Unsupported mutation"):
        Packet.from_dict(data)


def test_unknown_selection_is_not_silently_replaced(packet):
    with pytest.raises(PacketValidationError, match="Unknown question"):
        packet.public("question_999")
    with pytest.raises(PacketValidationError, match="Unknown mutation"):
        packet.public("question_001", "mutation_999")


def test_caller_kernel_profile_settings_are_explicitly_allowlisted(packet):
    case = packet.public("question_001")
    case["question"]["profile"]["authority"] = "synthetic caller policy"
    case["question"]["profile"]["kernel"] = {"min_origins": 1, "allowed_claim_kinds": ["attribution"], "allow_conditional": False, "allow_historical_sources": True, "required_scope_fields": ["subject_id"], "max_derivations": 50, "max_depth": 8}
    validate_public_case(case)
    case["question"]["profile"]["kernel"]["ignore_quotes"] = True
    with pytest.raises(PacketValidationError, match="forbidden"):
        validate_public_case(case)
