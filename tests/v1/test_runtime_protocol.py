"""Controller regressions for the single-object, role-specific worker protocol.

These recorded workers make no provider requests. The examples exercise
admission, accounting, repair limits, and preservation of the available record;
they are not tests of a language model's substantive reasoning.
"""
import copy
import json

import pytest

from inquiry.v1.packets import load_packet
from inquiry.v1.runtime import Budget, CritiqueOutput, Operation, replay_run, run_inquiry
from inquiry.v1.workers import RecordedWorker


def attribution_case():
    case = load_packet().public("question_001")
    document = next(item for item in case["corpus"]["documents"] if item["id"] == "doc_003")
    block = next(item for item in document["reading_blocks"] if item["locator"] == "field_group_2")
    scope = case["question"]["scope"]
    graph = {
        "claims": {"c_report": {
            "id": "c_report", "text": "The signed account reports the applicant's financial disruption.",
            "kind": "attribution", "form": "source_reports", "scope": scope,
        }},
        "evidence": {"e_report": {
            "id": "e_report", "source_id": document["id"], "source_version": document["version"],
            "locator": block["locator"], "quote": block["text"],
        }},
        "conditions": {
            "cq_attribution": {
                "id": "cq_attribution", "text": "Is the account faithfully attributed?",
                "answer": "The finding attributes the located statement to its author.",
                "status": "met", "evidence_ids": ["e_report"],
                "performer": "fixture", "performer_kind": "model",
            },
            "cq_applicability": {
                "id": "cq_applicability", "text": "Does the statement concern this applicant?",
                "answer": "The scoped finding concerns the applicant identified in the statement.",
                "status": "met", "evidence_ids": ["e_report"],
                "performer": "fixture", "performer_kind": "model",
            },
        },
        "arguments": {"a_report": {
            "id": "a_report", "claim_id": "c_report", "pattern": "attribution",
            "premise_ids": ["e_report"], "scope": scope,
            "conditions": {"attribution": "cq_attribution", "applicability": "cq_applicability"},
        }},
    }
    finish = {
        "operation": "finish", "graph": graph,
        "response": {"target_claim_id": "c_report", "task_completed": True,
                     "next_action": {"kind": "answer", "description": "Retain the attributed account."}},
    }
    return case, finish


def events(result, kind, role=None):
    return [event for event in result["events"] if event["kind"] == kind
            and (role is None or event["data"].get("role") == role)]


class SchemaRecordingWorker(RecordedWorker):
    def __init__(self, replies):
        super().__init__(replies)
        self.schema_assignments = []

    def set_output_schema(self, name, schema, *, strict=False):
        self.schema_assignments.append({"name": name, "schema": copy.deepcopy(schema), "strict": strict})


def assert_critic_contract(call):
    payload = json.loads(call["user"])
    assert payload["available_tools"] == []
    assert set(payload["evidence_request_contracts"]) == {"search", "open", "read_table"}
    assert "tool_contracts" not in payload
    assert "starter_graph" not in payload
    assert "next_step" not in payload
    assert payload.get("required_response") != "one operation matching the schema"
    assert "CritiqueOutput schema:" in call["system"]
    assert "Return one JSON operation per call." not in call["system"]
    assert "You cannot directly call tools." in call["system"]


def test_concatenated_operations_execute_neither_tool_and_can_be_repaired():
    case, finish = attribution_case()
    raw = ('{"operation":"open","arguments":{"source_id":"doc_001","version":"1.0"}}'
           '{"operation":"open","arguments":{"source_id":"doc_003","version":"1.0"}}')
    worker = RecordedWorker([raw, finish])
    result = run_inquiry(case, worker)

    assert result["status"] == "complete"
    assert result["usage"]["model_calls"] == 2
    assert result["usage"]["failed_calls"] == 1
    assert result["usage"]["tool_calls"] == 0
    assert not events(result, "tool_result")
    assert [event["data"]["operation"] for event in events(result, "operation")] == ["finish"]
    assert events(result, "worker_output", "proposer")[0]["data"]["reply"] == raw
    assert events(result, "worker_error", "proposer")[0]["data"]["error_type"] == "OutputProtocolError"
    assert result["response"]["findings"][0]["status"] == "reported"


@pytest.mark.parametrize("wrong_envelope", [
    {"source_id": "doc_003", "version": "1.0"},
    {"operation": "open", "arguments": {"source_id": "doc_003", "version": "1.0"}},
    {"observations": []},
    {"observations": [], "attacks": {}, "operation": "finish"},
])
def test_wrong_critic_envelope_cannot_be_counted_as_successful_review(wrong_envelope):
    case, finish = attribution_case()
    proposer = RecordedWorker([finish, finish])
    critic = RecordedWorker([wrong_envelope])
    result = run_inquiry(case, proposer, critic=critic, budget=Budget(max_model_calls=2))

    assert len(critic.calls) == 1
    assert not events(result, "critique")
    assert len(events(result, "worker_error", "critic")) == 1
    assert result["usage"]["model_calls"] == 2
    assert result["usage"]["failed_calls"] == 1
    assert result["usage"]["critique_attempts"] == len(critic.calls)
    assert result["usage"]["critique_completed_calls"] == 0
    assert result["usage"]["tool_calls"] == 0
    assert result["response"]["review_completed"] is False
    assert result["response"]["task_completed"] is False
    assert result["status"] == "partial"
    assert result["stop_reason"] == "resource_limit"
    assert result["response"]["findings"][0]["status"] == "reported"


def test_malformed_critic_can_recover_without_consuming_the_successful_review_slot():
    case, finish = attribution_case()
    proposer = SchemaRecordingWorker([finish] * 4)
    critic = SchemaRecordingWorker(['{"observations":', {"observations": [], "attacks": {}}])
    budget = Budget(max_model_calls=8, max_consecutive_errors=2, max_critique_calls=1)
    result = run_inquiry(case, proposer, critic=critic, budget=budget)

    assert result["status"] == "complete"
    assert result["response"]["review_completed"] is True
    assert result["response"]["task_completed"] is True
    assert len(critic.calls) == 2
    assert len(events(result, "critique")) == 1
    assert len(events(result, "worker_error", "critic")) == 1
    assert result["usage"]["failed_calls"] == 1
    assert result["usage"]["critique_attempts"] == 2
    assert result["usage"]["critique_completed_calls"] == 1
    assert result["usage"]["model_calls"] == len(proposer.calls) + len(critic.calls)
    assert result["usage"]["model_calls"] <= budget.max_model_calls
    assert result["usage"]["tool_calls"] == 0
    for call in critic.calls:
        assert_critic_contract(call)
    assert len(proposer.schema_assignments) == len(proposer.calls)
    assert len(critic.schema_assignments) == len(critic.calls)
    assert {entry["name"] for entry in proposer.schema_assignments}.isdisjoint(
        {entry["name"] for entry in critic.schema_assignments})
    assert all(entry["schema"] == Operation.model_json_schema() and entry["strict"] is False
               for entry in proposer.schema_assignments)
    assert all(entry["schema"] == CritiqueOutput.model_json_schema() and entry["strict"] is False
               for entry in critic.schema_assignments)


def test_two_invalid_critic_attempts_stop_with_a_partial_record_not_false_completion():
    case, finish = attribution_case()
    proposer = RecordedWorker([finish] * 5)
    critic = RecordedWorker([{"source_id": "doc_003", "version": "1.0"}] * 5)
    budget = Budget(max_model_calls=10, max_consecutive_errors=2, max_critique_calls=1)
    result = run_inquiry(case, proposer, critic=critic, budget=budget)

    assert len(critic.calls) == 2
    assert len(events(result, "worker_error", "critic")) == 2
    assert not events(result, "critique")
    assert result["usage"]["failed_calls"] == 2
    assert result["usage"]["model_calls"] == len(proposer.calls) + len(critic.calls)
    assert result["usage"]["model_calls"] < budget.max_model_calls
    assert result["usage"]["tool_calls"] == 0
    assert result["response"]["review_completed"] is False
    assert result["response"]["task_completed"] is False
    assert result["status"] == "partial"
    assert result["stop_reason"] != "settled_for_purpose"
    assert result["graph"]["attacks"] == {}
    finding = result["response"]["findings"][0]
    assert finding["claim_id"] == "c_report"
    assert finding["status"] == "reported"
    assert finding["citations"][0]["source_id"] == "doc_003"
    replay = replay_run(result)
    assert replay["ledger_valid"] is True
    assert replay["evaluation_reproduced"] is True


def test_structural_record_defect_is_repaired_before_substantive_critique():
    case, finish = attribution_case()
    malformed = copy.deepcopy(finish)
    malformed["operation"] = "submit"
    malformed["graph"]["arguments"]["a_report"]["premise_ids"] = ["cq_attribution", "cq_applicability"]
    proposer = RecordedWorker([malformed, finish, finish])
    critic = RecordedWorker([{"observations": [], "attacks": {}}])
    result = run_inquiry(case, proposer, critic=critic)

    assert result["status"] == "complete"
    assert len(critic.calls) == 1
    critic_input = events(result, "worker_input", "critic")[0]
    payload = json.loads(critic_input["data"]["user"])
    assert payload["graph"]["arguments"]["a_report"]["premise_ids"] == ["e_report"]
    repair_events = events(result, "record_repair_requested")
    assert repair_events
    assert repair_events[0]["sequence"] < critic_input["sequence"]
    assert len([event for event in events(result, "worker_input", "proposer")
                if event["sequence"] < critic_input["sequence"]]) == 2
    assert result["response"]["record_completed"] is True
    assert result["response"]["review_completed"] is True


@pytest.mark.parametrize("max_model_calls", [3, 8])
def test_critic_evidence_requests_are_provisional_controller_acquisitions(max_model_calls):
    case, finish = attribution_case()
    proposer = RecordedWorker([
        {"operation": "open", "arguments": {"source_id": "doc_003", "version": "1.0"}},
        finish, finish,
    ])
    critic = RecordedWorker([
        {"observations": ["Examine the current policy before concluding this review."], "attacks": {},
         "evidence_requests": [{"operation": "open", "arguments": {"source_id": "doc_001", "version": "1.0"},
                                "reason": "Read the policy against which the proposed response is framed."}]},
        {"observations": [], "attacks": {}},
    ])
    budget = Budget(max_model_calls=max_model_calls, max_tool_calls=2, max_critique_calls=1)
    result = run_inquiry(case, proposer, critic=critic, mode="documents", budget=budget)

    tool_results = events(result, "tool_result")
    assert result["usage"]["tool_calls"] == len(tool_results) == 2
    assert [event["data"]["arguments"]["source_id"] for event in tool_results] == ["doc_003", "doc_001"]
    delegated = tool_results[1]
    assert delegated["data"]["requester"] == "critic_request"
    assert delegated["data"]["result"]["segments"]
    assert delegated["sequence"] > events(result, "worker_output", "critic")[0]["sequence"]
    assert [event["data"]["arguments"]["source_id"] for event in events(result, "operation")
            if event["data"]["operation"] == "open"] == ["doc_003"]
    assert result["usage"]["model_calls"] == len(proposer.calls) + len(critic.calls)
    assert result["usage"]["model_calls"] <= max_model_calls
    assert result["usage"]["critique_attempts"] == len(critic.calls)
    assert result["usage"]["failed_calls"] == 0
    for call in critic.calls:
        assert_critic_contract(call)
    initial_review = json.loads(critic.calls[0]["user"])
    assert [item["source_id"] for item in initial_review["observations"] if item.get("tool") == "open"] == ["doc_003"]

    if max_model_calls == 3:
        assert len(critic.calls) == 1
        assert not events(result, "critique")
        assert result["usage"]["critique_completed_calls"] == 0
        assert result["response"]["review_completed"] is False
        assert result["response"]["task_completed"] is False
        assert result["status"] == "partial"
        assert result["stop_reason"] == "resource_limit"
    else:
        assert len(critic.calls) == 2
        final_review = json.loads(critic.calls[1]["user"])
        assert [item["source_id"] for item in final_review["observations"] if item.get("tool") == "open"] == ["doc_003", "doc_001"]
        assert len(events(result, "critique")) == 1
        assert result["usage"]["critique_completed_calls"] == 1
        assert result["response"]["review_completed"] is True
        assert result["status"] == "complete"
