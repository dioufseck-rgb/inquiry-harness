"""A1: declared stakes on the question and the two derived response fields.

These tests use recorded workers only. No field here authorizes an action; the
derived values compare a finding with the caller's declared threshold.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from inquiry.v1.contracts import InquiryValidationError, request_json_schema, validate_inquiry_request
from inquiry.v1.kernel import PATTERN_REQUIREMENTS
from inquiry.v1.runtime import Budget, run_inquiry
from inquiry.v1.scoring import score_run
from inquiry.v1.service import InquiryService
from inquiry.v1.workers import RecordedWorker


EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "v1"


def request(name="equipment_temperature"):
    return json.loads((EXAMPLES / (name + ".json")).read_text(encoding="utf-8"))


def stakes(level="high", required=("established",), basis="A wrong belief would change a maintenance release."):
    return {"level": level, "required_standing": list(required), "basis": basis}


def reply(public, *, open_condition=None, target_relation="direct"):
    """A prescribed trace; it supplies no evidence about a live model."""
    q = public["question"]
    source = public["corpus"]["documents"][0]
    block = source["reading_blocks"][0]
    pattern = "attribution" if q["target"]["form"] == "source_reports" else "document_record"
    conditions = {}
    for key in PATTERN_REQUIREMENTS[pattern]:
        status = "open" if key == open_condition else "met"
        conditions["K_" + key] = {"id": "K_" + key, "text": "Examine " + key,
                                  "answer": "" if status == "open" else "The located record supports this scoped test claim.",
                                  "status": status, "evidence_ids": [] if status == "open" else ["E"]}
    needs = ([{"condition_id": "K_" + open_condition, "question": "Examine " + open_condition,
               "what_would_resolve": "A located record covering this condition.",
               "resolver_kind": "source", "resolver_hint": "the issuing record's scope section"}] if open_condition else [])
    return {"operation": "finish", "graph": {
        "id": "inquiry", "revision": 1,
        "claims": {"C": {"id": "C", "text": block["text"], **q["target"], "scope": deepcopy(q["scope"]),
                         "target_question_id": q["id"], "target_relation": target_relation}},
        "evidence": {"E": {"id": "E", "source_id": source["id"], "source_version": source["version"],
                           "locator": block["locator"], "quote": block["text"], "worker_id": "proposer"}},
        "conditions": conditions,
        "arguments": {"A": {"id": "A", "claim_id": "C", "pattern": pattern, "premise_ids": ["E"],
                            "conditions": {key: "K_" + key for key in PATTERN_REQUIREMENTS[pattern]},
                            "scope": deepcopy(q["scope"])}}, "attacks": {},
    }, "response": {"target_claim_id": "C", "inquiry_completed": True,
                     "assessment": "Scripted A1 check.", "information_needs": needs, "caveats": []}}


# -- contract -------------------------------------------------------------------

def test_stakes_absent_leaves_the_request_unchanged_and_derived_fields_null():
    public = request()
    assert validate_inquiry_request(public) == public
    service = InquiryService(lambda: RecordedWorker([reply(public)]))
    out = service.inquire(public, mode="supplied")
    response = out["response"]
    assert response["meets_declared_standing"] is None
    assert response["resolution_state"] == "settled"
    assert not any("declared" in caveat for caveat in response["caveats"])


@pytest.mark.parametrize("name", ["equipment_temperature", "research_attribution", "household_meter"])
def test_a5_examples_still_validate_unchanged(name):
    public = request(name)
    assert validate_inquiry_request(public) == public
    assert "stakes" not in public["question"]


def test_stakes_are_optional_and_strict_in_the_schema():
    schema = request_json_schema()
    question = schema["properties"]["question"]
    assert "stakes" in question["properties"] and "stakes" not in question["required"]
    stakes_schema = question["properties"]["stakes"]
    assert set(stakes_schema["required"]) == {"level", "required_standing", "basis"}
    assert stakes_schema["additionalProperties"] is False
    assert stakes_schema["properties"]["level"]["enum"] == ["low", "medium", "high"]
    assert stakes_schema["properties"]["required_standing"]["minItems"] == 1


@pytest.mark.parametrize("change,match", [
    ({"level": "urgent"}, "level"),
    ({"required_standing": []}, "required_standing"),
    ({"required_standing": ["true"]}, "required_standing"),
    ({"required_standing": ["established", "established"]}, "unique"),
    ({"basis": ""}, "basis"),
    ({"basis": None}, "missing"),
    ({"priority": 1}, "unknown"),
])
def test_invalid_stakes_are_rejected_before_worker_construction(change, match):
    public = request()
    public["question"]["stakes"] = {**stakes(), **change}
    if change.get("basis", "x") is None:
        public["question"]["stakes"].pop("basis")
    called = []
    service = InquiryService(lambda: called.append(True))
    with pytest.raises(InquiryValidationError, match=match):
        service.inquire(public)
    assert called == []


def test_stakes_basis_is_recorded_never_interpreted():
    public = request()
    public["question"]["stakes"] = stakes(basis="Because the plant manager said so.")
    out = InquiryService(lambda: RecordedWorker([reply(public)])).inquire(public, mode="supplied", include_record=True)
    case = next(e["data"] for e in out["record"]["events"] if e["kind"] == "case")
    assert case["question"]["stakes"]["basis"] == "Because the plant manager said so."


# -- derived fields -----------------------------------------------------------------

def test_established_direct_target_in_required_standing_is_true():
    public = request()
    public["question"]["stakes"] = stakes(required=("established", "reported"))
    out = InquiryService(lambda: RecordedWorker([reply(public)])).inquire(public, mode="supplied")
    response = out["response"]
    assert response["findings"][0]["status"] == "established"
    assert response["meets_declared_standing"] is True
    assert response["resolution_state"] == "settled"
    assert any("does not authorize" in caveat for caveat in response["caveats"])


def test_required_standing_not_reached_is_false():
    public = request("research_attribution")  # the scripted trace yields "reported"
    public["question"]["stakes"] = stakes(required=("established",))
    out = InquiryService(lambda: RecordedWorker([reply(public)])).inquire(public, mode="supplied")
    assert out["response"]["findings"][0]["status"] == "reported"
    assert out["response"]["inquiry_completed"] is True
    assert out["response"]["meets_declared_standing"] is False


def test_polarity_an_established_record_non_establishment_is_false():
    public = request()
    public["question"]["stakes"] = stakes(required=("established",))
    out = InquiryService(lambda: RecordedWorker([reply(public, target_relation="record_non_establishment")])).inquire(public, mode="supplied")
    finding = out["response"]["findings"][0]
    assert finding["status"] == "established" and finding["target_relation"] == "record_non_establishment"
    assert out["response"]["inquiry_completed"] is True
    assert out["response"]["meets_declared_standing"] is False


def test_resolution_state_open_needs_when_a_need_or_open_condition_remains():
    public = request()
    public["question"]["stakes"] = stakes()
    out = InquiryService(lambda: RecordedWorker([reply(public, open_condition="applicability")])).inquire(public, mode="supplied")
    response = out["response"]
    assert response["information_needs"] and response["inquiry_completed"] is True
    assert response["resolution_state"] == "open_needs"
    assert response["meets_declared_standing"] is False


def test_resolution_state_budget_limited():
    public = request()
    public["question"]["stakes"] = stakes()
    out = InquiryService(lambda: RecordedWorker([]), max_budget=Budget()).inquire(public, budget={"max_model_calls": 0})
    assert out["stop_reason"] == "resource_limit"
    assert out["response"]["resolution_state"] == "budget_limited"
    assert out["response"]["meets_declared_standing"] is None  # not completed


def test_resolution_state_execution_failed():
    public = request()
    public["question"]["stakes"] = stakes()
    out = InquiryService(lambda: RecordedWorker(["not json", "still not json"])).inquire(public)
    assert out["stop_reason"] == "execution_failure"
    assert out["response"]["resolution_state"] == "execution_failed"
    assert out["response"]["meets_declared_standing"] is None


def test_derived_fields_are_computed_in_code_not_taken_from_the_worker():
    public = request()
    public["question"]["stakes"] = stakes()
    forged = reply(public)
    forged["response"]["meets_declared_standing"] = True  # ResponseDraft forbids extra fields
    worker = RecordedWorker([forged, reply(public)])
    result = run_inquiry(public, worker, mode="supplied")
    assert result["usage"]["failed_calls"] == 1 and result["response"]["meets_declared_standing"] is True


def test_derived_fields_are_in_the_audit_allowlist_and_records_replay(tmp_path):
    public = request()
    public["question"]["stakes"] = stakes()
    service = InquiryService(lambda: RecordedWorker([reply(public)]), record_root=tmp_path)
    out = service.inquire(public, mode="supplied", include_record=True)
    audit = score_run(out["record"], public)["structural"]
    assert audit["status"] == "pass" and "epistemic_response_fields" not in audit["failed_checks"]
    assert service.replay(out["inquiry_id"])["evaluation_reproduced"] is True
