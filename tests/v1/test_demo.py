"""Integration-plumbing checks, explicitly not competence measurements."""

from copy import deepcopy
import json

import pytest

from inquiry.v1.adapters.hardship_demo import DemoWorker
from inquiry.v1.adapters.hardship import to_inquiry_request
from inquiry.v1.evidence import EvidenceEnvironment
from inquiry.v1.models import InquiryGraph
from inquiry.v1.packets import load_packet


def scripted_draft(case, mode="supplied"):
    environment = EvidenceEnvironment(to_inquiry_request(case), mode)
    initial = environment.initial_input()
    observations = []
    worker = DemoWorker()
    for _ in range(12):
        operation = json.loads(worker.complete("", json.dumps({"initial": initial, "observations": observations, "draft_response": None})))
        if operation["operation"] == "submit":
            return operation, environment, worker
        result = getattr(environment, operation["operation"])(**operation["arguments"])
        observations.append(result)
        environment.expose("proposer", result)
    raise AssertionError("Scripted worker failed to submit within its finite acquisition sequence")


@pytest.mark.parametrize("mode", ["supplied", "documents", "search"])
def test_demo_all_seed_variants_have_valid_records_and_exposed_quotes(mode):
    packet = load_packet()
    for mutation in (None, *packet.mutation_ids):
        for question in packet.question_ids:
            operation, environment, worker = scripted_draft(packet.public(question, mutation), mode)
            graph = InquiryGraph.model_validate(operation["graph"])
            assert operation["response"]["inquiry_completed"]
            assert graph.claims["C_target"].scope.root == packet.public(question, mutation)["question"]["scope"]
            for item in graph.evidence.values():
                assert environment.verify_quote(item.worker_id, item.source_id, item.source_version, item.quote, item.locator).valid
                assert environment.current_versions[item.source_id] == item.source_version
            assert worker.is_test_instrument
            assert worker.provider == worker.model == "demo"
            assert all(u["input_tokens"] == u["output_tokens"] == u["cost_usd"] == 0 for u in worker.usage)


def test_demo_does_not_route_on_question_identifiers():
    case = load_packet().public("question_004", "mutation_002")
    renamed = deepcopy(case)
    renamed["question"]["id"] = "question_987"
    renamed["question"]["profile"]["id"] = "profile_765"
    original, _, _ = scripted_draft(case)
    alternate, _, _ = scripted_draft(renamed)
    assert original["graph"]["claims"]["C_target"].pop("target_question_id") == "question_004"
    assert alternate["graph"]["claims"]["C_target"].pop("target_question_id") == "question_987"
    assert original["response"]["findings"][0].pop("target_question_id") == "question_004"
    assert alternate["response"]["findings"][0].pop("target_question_id") == "question_987"
    assert original["graph"] == alternate["graph"]
    assert original["response"] == alternate["response"]


def test_demo_reports_actual_record_amount_and_alias():
    case = load_packet().public("question_001", "mutation_006")
    account = next(d for d in case["corpus"]["documents"] if d["id"] == "doc_003")
    for block in account["reading_blocks"]:
        block["text"] = block["text"].replace("80 programme credits", "125 programme credits")
    operation, _, _ = scripted_draft(case)
    text = operation["response"]["text"]
    assert "Rin Sela" in text and "125 programme credits" in text
    assert "Mira Noll" not in text and "80 programme credits" not in text


def test_missing_intake_information_does_not_make_the_next_response_conditional():
    operation, _, _ = scripted_draft(load_packet().public("question_004", "mutation_002"))
    graph, response = operation["graph"], operation["response"]
    assert graph["claims"]["C_target"]["conditions"] == []
    assert response["findings"][0]["status"] == "established"
    assert {item["condition_id"] for item in response["information_needs"]} == {"impact_description", "event_date"}
    assert all(graph["conditions"][cid]["status"] == "met" for cid in graph["arguments"]["A_target"]["conditions"].values())


def test_new_policy_requests_only_new_intake_declaration():
    operation, _, _ = scripted_draft(load_packet().public("question_004", "mutation_005"))
    assert [item["condition_id"] for item in operation["response"]["information_needs"]] == ["prior_payment_declaration"]
    assert "register clearance" not in operation["response"]["assessment"]
    policy_evidence = [e for e in operation["graph"]["evidence"].values() if e["source_id"] == "doc_001"]
    assert policy_evidence and all(e["source_version"] == "2.0" for e in policy_evidence)


def test_causal_trace_is_target_specific():
    packet = load_packet()
    baseline, _, _ = scripted_draft(packet.public("question_003"))
    added, _, _ = scripted_draft(packet.public("question_003", "mutation_003"))
    assert baseline["response"]["findings"][0]["status"] == "not_established"
    assert added["response"]["findings"][0]["status"] == "established"
    other_person = packet.public("question_003", "mutation_003")
    trace = next(d for d in other_person["corpus"]["documents"] if d["id"] == "doc_005")
    for block in trace["reading_blocks"]:
        block["text"] = block["text"].replace("person_001", "a different worker")
    mismatched, _, _ = scripted_draft(other_person)
    assert mismatched["response"]["findings"][0]["status"] == "not_established"


def test_demo_critic_does_not_claim_independent_review():
    worker = DemoWorker()
    reply = json.loads(worker.complete("Review the record for material flaws", "{}"))
    assert reply["attacks"] == {}
    assert "no substantive independent critique" in reply["observations"][0]


def test_demo_finish_preserves_supplied_record():
    operation, _, worker = scripted_draft(load_packet().public("question_001"))
    reply = json.loads(worker.complete("", json.dumps({"draft_response": operation["response"], "graph": operation["graph"]})))
    assert reply["operation"] == "finish"
    assert reply["graph"] == operation["graph"]
    assert reply["response"] == operation["response"]
