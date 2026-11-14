from copy import deepcopy
import json
from math import inf, nan

import pytest

from inquiry.v1.contracts import (
    FORBIDDEN_PUBLIC_KEYS,
    InquiryRequest,
    InquiryValidationError,
    canonical_json,
    content_hash,
    current_versions,
    request_json_schema,
    validate_inquiry_request,
)


def source(source_id="sensor/river A", version="revision alpha"):
    return {
        "id": source_id, "version": version, "title": "Field measurement report",
        "issuer_id": "team:hydrology", "origin_id": "measurement/run 42",
        "issued_at": "2026-10-30", "language": "en",
        "reading_blocks": [{"locator": "measurement/summary", "text": "The instrument reported 2.7 metres."}],
    }


def request(document=None):
    document = source() if document is None else document
    return {
        "shared_context": {"as_of": "2026-11-14", "caller": {"purpose": "Evidence assessment"}},
        "corpus": {"documents": [document], "current_versions": {document["id"]: document["version"]}},
        "question": {
            "id": "measurement question / A", "question": "What reading does the report record?",
            "intended_use": "Assess support for a source attribution",
            "scope": {"instrument": "A", "coordinates": [51.5, -0.1], "calibration": {"verified": False}},
            "target": {"kind": "attribution", "form": "source_reports"},
            "profile": {"id": "requester:attribution", "version": "2026.11", "authority": "Research caller",
                        "requirements": ["Attribute measurements to the originating report."], "kernel": {}},
        },
    }


@pytest.mark.parametrize("document_id,issuer_id,scope,target", [
    ("urn:lab:assay-17", "laboratory Δ", {"sample": "A-17", "analytes": ["iron", "copper"], "limit": 0.03},
     {"kind": "substantive", "form": "assertion"}),
    ("service/checkout:trace", "SRE team", {"region": "eu-west", "window": {"start": 10, "end": 20}, "complete": True},
     {"kind": "attribution", "form": "source_reports"}),
    ("archive MS 42 / folio 7", "city archivist", {"textual_witness": "codex B", "date_range": [1400, 1420], "author": None},
     {"kind": "textual_observation", "form": "caller_defined_form"}),
])
def test_unrelated_domains_use_arbitrary_ids_context_and_scope(document_id, issuer_id, scope, target):
    document = source(document_id)
    document["issuer_id"] = issuer_id
    value = request(document)
    value["question"].update(scope=scope, target=target)
    validated = validate_inquiry_request(value)
    assert validated == value
    assert set(validated["corpus"]) == {"documents", "current_versions"}
    assert "entities" not in validated["shared_context"]
    assert "fiction_notice" not in validated["shared_context"]
    assert "case_id" not in validated["question"]["scope"]


def test_typed_request_roundtrips_and_does_not_alias_caller_data():
    value = request()
    model = InquiryRequest.from_dict(value)
    exported = model.to_dict()
    assert model.model_dump(mode="json") == value
    assert InquiryRequest.model_validate_json(model.model_dump_json()).to_dict() == value
    assert canonical_json(model) == canonical_json(value)
    assert content_hash(model) == content_hash(value)
    exported["question"]["scope"]["instrument"] = "changed export"
    value["corpus"]["documents"][0]["reading_blocks"][0]["text"] = "changed input"
    assert model.question["scope"]["instrument"] == "A"
    assert model.corpus["documents"][0]["reading_blocks"][0]["text"] == "The instrument reported 2.7 metres."


def test_no_evidence_is_an_explicit_empty_collection():
    value = request()
    value["corpus"] = {"documents": [], "current_versions": {}}
    assert InquiryRequest.model_validate(value).to_dict() == value
    assert current_versions(value["corpus"]) == {}


def test_legacy_application_shape_requires_an_explicit_adapter():
    value = request()
    value["corpus"].pop("current_versions")
    value["corpus"]["current_policy"] = {"document_id": "sensor/river A", "version": "revision alpha"}
    with pytest.raises(InquiryValidationError, match="current_versions.*current_policy"):
        validate_inquiry_request(value)


@pytest.mark.parametrize("field", ["target", "profile"])
def test_caller_must_supply_the_target_and_profile(field):
    value = request()
    del value["question"][field]
    with pytest.raises(InquiryValidationError, match=field):
        validate_inquiry_request(value)


@pytest.mark.parametrize("key", sorted(FORBIDDEN_PUBLIC_KEYS))
def test_private_evaluation_annotations_are_rejected_at_arbitrary_depth(key):
    value = request()
    value["shared_context"]["arbitrary_caller_data"] = [{"another": {key: "private"}}]
    with pytest.raises(InquiryValidationError, match="private evaluation keys"):
        validate_inquiry_request(value)


@pytest.mark.parametrize("invalid", [inf, -inf, nan, ("tuple",), {"set"}, {1: "nonstring key"}])
def test_public_request_is_strict_finite_json(invalid):
    value = request()
    value["question"]["scope"]["value"] = invalid
    with pytest.raises(InquiryValidationError):
        validate_inquiry_request(value)


def test_recursive_python_containers_fail_cleanly_before_worker_admission():
    value = request()
    value["shared_context"]["self"] = value
    with pytest.raises(InquiryValidationError, match="cyclic JSON"):
        validate_inquiry_request(value)


def test_profile_accepts_neutral_kernel_controls_without_authenticating_actors():
    value = request()
    value["question"]["profile"]["kernel"] = {
        "min_origins": 2, "premise_min_origins": None, "allowed_claim_kinds": ["attribution"],
        "allowed_patterns": ["attribution"], "allow_conditional": False,
        "allow_historical_sources": True, "required_scope_fields": ["instrument"],
        "allowed_performer_kinds": ["model", "human"], "require_independent_reply": True,
        "max_derivations": 50, "max_depth": 8, "max_evaluation_steps": 300,
    }
    assert validate_inquiry_request(value) == value
    value["question"]["profile"]["kernel"]["trusted_performers"] = {"model": "human"}
    with pytest.raises(InquiryValidationError, match="trusted_performers"):
        validate_inquiry_request(value)


@pytest.mark.parametrize("kernel", [
    {"min_origins": True}, {"max_depth": -1}, {"premise_min_origins": 1.5},
    {"allow_conditional": "true"}, {"allowed_claim_kinds": ["attribution", "attribution"]},
    {"allowed_patterns": [1]}, {"ignore_quotes": True},
])
def test_kernel_controls_do_not_silently_coerce_or_accept_unknown_settings(kernel):
    value = request()
    value["question"]["profile"]["kernel"] = kernel
    with pytest.raises(InquiryValidationError):
        validate_inquiry_request(value)


def versioned_request():
    original = source()
    revised = deepcopy(original)
    revised.update(version="corrected", supersedes={"document_id": original["id"], "version": original["version"]})
    revised["reading_blocks"][0]["text"] = "The corrected instrument reading was 2.5 metres."
    value = request(original)
    value["corpus"]["documents"].append(revised)
    value["corpus"]["current_versions"][original["id"]] = revised["version"]
    return value


def test_versions_are_explicit_and_history_preserves_arbitrary_version_names():
    value = versioned_request()
    assert validate_inquiry_request(value) == value
    versions = current_versions(value["corpus"])
    assert versions == {"sensor/river A": "corrected"}
    versions["sensor/river A"] = "tampered"
    assert value["corpus"]["current_versions"]["sensor/river A"] == "corrected"


@pytest.mark.parametrize("defect,match", [
    ("duplicate_source", "Duplicate source version"),
    ("missing_current", "every source ID"),
    ("unknown_current", "Unresolved current source version"),
    ("superseded_current", "superseded version"),
    ("ambiguous_history", "unique current version"),
    ("unknown_reference", "Unresolved source reference"),
    ("unknown_locator", "Unresolved source locator"),
    ("revision_identity", "preserve source identity"),
    ("lineage_cycle", "Cyclic source lineage"),
    ("revision_cycle", "Cyclic source lineage"),
])
def test_invalid_versions_references_and_cycles_are_rejected(defect, match):
    value = versioned_request()
    documents = value["corpus"]["documents"]
    original, revised = documents
    original_ref = {"document_id": original["id"], "version": original["version"]}
    revised_ref = {"document_id": revised["id"], "version": revised["version"]}
    if defect == "duplicate_source":
        documents.append(deepcopy(original))
    elif defect == "missing_current":
        value["corpus"]["current_versions"].clear()
    elif defect == "unknown_current":
        value["corpus"]["current_versions"][original["id"]] = "unknown revision"
    elif defect == "superseded_current":
        value["corpus"]["current_versions"][original["id"]] = original["version"]
    elif defect == "ambiguous_history":
        del revised["supersedes"]
    elif defect == "unknown_reference":
        revised["derived_from"] = [{"document_id": "missing source", "version": "1"}]
    elif defect == "unknown_locator":
        revised["derived_from"] = [{**original_ref, "locator": "unpublished section"}]
    elif defect == "revision_identity":
        revised["supersedes"]["document_id"] = "another source"
    elif defect == "lineage_cycle":
        original["derived_from"] = [revised_ref]
        revised["derived_from"] = [original_ref]
    else:
        original["supersedes"] = revised_ref
    with pytest.raises(InquiryValidationError, match=match):
        validate_inquiry_request(value)


def test_capability_schema_describes_the_canonical_public_shape():
    schema = request_json_schema()
    assert set(schema["required"]) == {"shared_context", "corpus", "question"}
    corpus = schema["properties"]["corpus"]
    assert set(corpus["required"]) == {"documents", "current_versions"}
    question = schema["properties"]["question"]
    assert question["properties"]["target"]["required"] == ["kind", "form"]
    assert set(question["properties"]["profile"]["required"]) == {"id", "version", "authority", "requirements", "kernel"}
    assert "current_policy" not in json.dumps(schema)
    schema["$defs"]["source"]["required"].clear()
    assert request_json_schema()["$defs"]["source"]["required"]
