"""Application translation is explicit and leaves service records epistemic."""

from copy import deepcopy
import json

import pytest

from inquiry.v1.adapters.hardship import TARGET_FORMS, to_inquiry_request
from inquiry.v1.adapters.hardship_application import prepare_intake_draft
from inquiry.v1.adapters.hardship_demo import DemoWorker
from inquiry.v1.adapters.legacy import EpistemicWorkerAdapter, to_epistemic_response
from inquiry.v1.contracts import validate_inquiry_request
from inquiry.v1.packets import load_packet
from inquiry.v1.runtime import Budget, ResponseDraft, run_inquiry
from inquiry.v1.scoring import score_run


def test_every_packet_projection_has_an_explicit_lossless_source_adapter():
    packet = load_packet()
    for mutation in (None, *packet.mutation_ids):
        for identifier in packet.question_ids:
            original = packet.public(identifier, mutation)
            before = deepcopy(original)
            request = to_inquiry_request(original)
            assert validate_inquiry_request(request) == request
            assert original == before
            assert request["corpus"]["documents"] == original["corpus"]["documents"]
            assert set(request["corpus"]) == {"documents", "current_versions"}
            assert request["question"]["target"] == TARGET_FORMS[original["question"]["profile"]["required_form"]]
            assert "required_form" not in request["question"]["profile"]
            assert "policy_binding" not in request["question"]["profile"]
            request["corpus"]["documents"][0]["title"] = "caller edit"
            assert original == before


def test_private_annotations_are_rejected_by_the_explicit_adapter():
    public = load_packet().public("question_001")
    public["evaluator_only"] = {"answer": "PRIVATE_SENTINEL"}
    with pytest.raises(ValueError):
        to_inquiry_request(public)


def test_caller_profile_overrides_survive_application_translation():
    public = load_packet().public("question_004")
    profile = public["question"]["profile"]
    profile["authority"] = "The caller's explicit review authority."
    profile["kernel"] = {"min_origins": 2, "allow_conditional": True}
    profile["requirements"].append("Preserve this caller-specific additional warrant requirement.")
    translated = to_inquiry_request(public)["question"]["profile"]
    assert translated["authority"] == profile["authority"]
    assert translated["kernel"] == profile["kernel"]
    assert translated["requirements"][-1] == profile["requirements"][-1]


def test_intake_application_product_is_translated_to_an_epistemic_question():
    original = load_packet().public("question_004")
    request = to_inquiry_request(original)
    assert "prepare the next permitted response" in original["question"]["question"]
    assert "what does the supplied application establish" in request["question"]["question"]
    assert request["question"]["target"] == {"kind": "policy", "form": "rule_consequence"}
    assert request["shared_context"]["authority"] == "Epistemic analysis of the supplied fictional records only."


@pytest.mark.parametrize("mutation,action", [(None, "advance_intake"), ("mutation_002", "request_information")])
def test_application_letter_is_created_only_after_service_returns(mutation, action):
    public = load_packet().public("question_004", mutation)
    request = to_inquiry_request(public)
    result = run_inquiry(request, DemoWorker(), budget=Budget(max_model_calls=3))
    before = deepcopy(result)
    assert result["response"]["inquiry_completed"] is True
    assert score_run(result, request)["structural"]["status"] == "pass"
    assert not {"next_action", "deliverable", "task_completed"}.intersection(result["response"])
    application = prepare_intake_draft(public, result)
    assert application["suggested_action"] == action
    assert application["draft"].startswith("Thank you")
    assert application["human_review_required"] is True
    assert result == before
    assert application["draft"] not in json.dumps(result)


def test_incomplete_inquiry_is_not_application_authorization():
    public = load_packet().public("question_004")
    result = run_inquiry(to_inquiry_request(public), DemoWorker(), budget=Budget(max_model_calls=0))
    with pytest.raises(ValueError, match="completed, scoped intake assessment"):
        prepare_intake_draft(public, result)


def test_legacy_reply_adapter_strips_business_products_without_mutating_the_original():
    legacy = {"text": "The record does not resolve K1.", "task_completed": True,
              "deliverable": "Dear applicant, APPLICATION_LETTER_SENTINEL",
              "next_action": {"kind": "advance_intake", "condition_ids": ["K1"]}}
    before = deepcopy(legacy)
    graph = {"conditions": {"K1": {"text": "An authenticated measurement would resolve K1."}}}
    adapted = to_epistemic_response(legacy, graph)
    assert ResponseDraft.model_validate(adapted).inquiry_completed
    assert adapted["assessment"] == legacy["text"]
    assert adapted["information_needs"][0]["condition_id"] == "K1"
    assert "APPLICATION_LETTER_SENTINEL" not in json.dumps(adapted)
    assert legacy == before


def test_legacy_worker_wrapper_is_explicit_and_preserves_usage_identity():
    class Scripted:
        provider = "test"
        usage = [{"input_tokens": 1}]

        def complete(self, system, user, max_tokens=4096):
            return json.dumps({"operation": "submit", "response": {"text": "A scoped answer.",
                "next_action": {"kind": "answer", "condition_ids": []}, "task_completed": True}})

    raw_worker = Scripted()
    raw_reply = json.loads(raw_worker.complete("", "{}"))
    with pytest.raises(ValueError):
        ResponseDraft.model_validate(raw_reply["response"])
    wrapper = EpistemicWorkerAdapter(raw_worker)
    response = json.loads(wrapper.complete("", "{}"))["response"]
    assert ResponseDraft.model_validate(response).inquiry_completed
    assert wrapper.provider == "test" and wrapper.usage is raw_worker.usage
