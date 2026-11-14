import copy
import json

import pytest

from inquiry.v1.models import Attack, InquiryGraph, Profile
from inquiry.v1.packets import load_packet
from inquiry.v1.adapters.hardship import to_inquiry_request
from inquiry.v1.persistence import load_run, save_run
from inquiry.v1.runtime import (Budget, Operation, ResponseDraft, _answers_form, _snapshot_revision,
                                build_critic_prompt, build_prompt, replay_run, run_inquiry, starter_graph)
from inquiry.v1.kernel import evaluate
from inquiry.v1.workers import RecordedWorker


def public_case(question_id, mutation_id=None):
    return to_inquiry_request(load_packet().public(question_id, mutation_id))


def example():
    case = public_case("question_001")
    document = next(d for d in case["corpus"]["documents"] if d["id"] == "doc_003")
    quote = next(b["text"] for b in document["reading_blocks"] if b["locator"] == "field_group_2")
    scope = case["question"]["scope"]
    graph = {
        "claims": {"c1": {"id": "c1", "text": "The applicant reports the financial disruption described in the signed account.",
                              "kind": "attribution", "form": "source_reports", "scope": scope,
                              "target_question_id": case["question"]["id"]}},
        "evidence": {"e1": {"id": "e1", "source_id": "doc_003", "source_version": "1.0",
                                "locator": "field_group_2", "quote": quote}},
        "conditions": {"cq1": {"id": "cq1", "text": "The account is faithfully attributed.", "status": "met", "evidence_ids": ["e1"], "performer": "fixture", "performer_kind": "model"},
                       "cq2": {"id": "cq2", "text": "The attribution concerns this applicant and statement.", "status": "met", "evidence_ids": ["e1"], "performer": "fixture", "performer_kind": "model"}},
        "arguments": {"a1": {"id": "a1", "claim_id": "c1", "pattern": "attribution", "premise_ids": ["e1"],
                                "conditions": {"attribution": "cq1", "applicability": "cq2"}, "scope": scope}},
    }
    response = {"target_claim_id": "c1", "inquiry_completed": True,
                "assessment": "The account is attributed to its author; no independent verification is inferred."}
    return case, graph, response


def test_end_to_end_record_standing_and_model_free_replay(tmp_path):
    case, graph, response = example()
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]))
    assert result["status"] == "complete"
    assert result["response"]["findings"][0]["status"] == "reported"
    assert result["response"]["findings"][0]["citations"][0]["locator"] == "field_group_2"
    save_run(result, tmp_path)
    replay = replay_run(load_run(tmp_path))
    assert replay["ledger_valid"] and replay["evaluation_reproduced"]


def test_incomplete_draft_does_not_abort_a_useful_assessment():
    case, graph, response = example()
    graph["arguments"]["a1"]["conditions"].pop("applicability")
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]))
    assert result["status"] != "failed"
    assert result["response"]["findings"][0]["status"] == "not_established"
    assert "Not established" in result["response"]["text"]


def test_malformed_output_is_repairable_and_counted():
    case, graph, response = example()
    worker = RecordedWorker(["not json", {"operation": "finish", "graph": graph, "response": response}])
    result = run_inquiry(case, worker)
    assert result["status"] == "complete"
    assert result["usage"]["model_calls"] == 2
    assert result["usage"]["failed_calls"] == 1
    assert result["errors"]


@pytest.mark.parametrize("budget", [Budget(max_model_calls=0), Budget(max_total_tokens=1)])
def test_resource_stop_preserves_an_explicit_partial_result(budget):
    case, _, _ = example()
    worker = RecordedWorker([])
    result = run_inquiry(case, worker, budget=budget)
    assert result["status"] == "partial"
    assert not result["response"]["inquiry_completed"]
    assert result["stop_reason"] == "resource_limit"
    assert not worker.calls
    assert not result["exposures"]


def test_unread_quotes_are_not_admitted_in_document_mode():
    case, graph, response = example()
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]), mode="documents")
    assert result["response"]["findings"][0]["status"] == "not_established"
    assert result["response"]["findings"][0]["citations"] == []


def test_model_cannot_claim_code_or_human_condition_checks():
    case, graph, response = example()
    graph["conditions"]["cq1"].update(performer="independent_human", performer_kind="human")
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]))
    condition = result["graph"]["conditions"]["cq1"]
    assert condition["performer_kind"] == "model"
    assert condition["performer"].startswith("proposer:")


def test_a_narrower_component_cannot_complete_the_target():
    case, graph, response = example()
    graph["claims"]["c1"]["scope"] = {"subject_id": "a_different_person"}
    graph["arguments"]["a1"]["scope"] = {"subject_id": "a_different_person"}
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]))
    assert not result["response"]["target_scope_answered"]
    assert not result["response"]["inquiry_completed"]
    assert result["status"] == "partial"


def test_an_attributed_account_cannot_complete_a_causal_examination():
    case, graph, response = example()
    case = public_case("question_003")
    graph["claims"]["c1"]["scope"] = case["question"]["scope"]
    graph["arguments"]["a1"]["scope"] = case["question"]["scope"]
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]))
    assert result["response"]["findings"][0]["status"] == "reported"
    assert result["response"]["target_scope_answered"]
    assert not result["response"]["target_form_answered"]
    assert not result["response"]["inquiry_completed"]
    assert result["stop_reason"] == "information_unavailable"


@pytest.mark.parametrize("bad_operation", [
    {"operation": "invented_tool"},
    {"operation": "open", "arguments": {"source_id": "missing", "version": "1.0"}},
])
def test_schema_and_tool_failures_are_counted_without_blocking_repair(bad_operation):
    case, graph, response = example()
    result = run_inquiry(case, RecordedWorker([bad_operation, {"operation": "finish", "graph": graph, "response": response}]))
    assert result["status"] == "complete"
    assert result["usage"]["failed_calls"] == 1
    assert result["usage"]["model_calls"] == 2


def test_unknown_provider_usage_is_reserved_and_never_reported_as_zero():
    case, graph, response = example()

    class UnknownUsageWorker(RecordedWorker):
        def complete(self, *args, **kwargs):
            text = super().complete(*args, **kwargs)
            self.usage[-1].update(input_tokens=None, output_tokens=None,
                                  usage_known=False, cost_usd=None, api_attempts=1)
            return text

    result = run_inquiry(case, UnknownUsageWorker([{"operation": "finish", "graph": graph, "response": response}]))
    assert result["status"] == "complete"
    assert result["usage"]["estimated_usage_calls"] == 1
    assert result["usage"]["input_tokens"] > 0
    assert result["usage"]["output_tokens"] == Budget().max_output_tokens
    assert result["usage"]["cost_usd"] is None
    assert not result["usage"]["cost_complete"]
    assert result["usage"]["api_attempts"] == 1


def test_proposer_cannot_delete_or_rewrite_challenge():
    _, graph, _ = example()
    graph["attacks"] = {"x1": {"id": "x1", "target_id": "a1", "grounds": "Material mismatch", "evidence_ids": ["e1"], "performer": "critic"}}
    previous = InquiryGraph.model_validate(graph)
    proposed = InquiryGraph.model_validate({**graph, "attacks": {}})
    changed = _snapshot_revision(previous, proposed, "proposer:test")
    assert changed.attacks["x1"].grounds == "Material mismatch"
    proposed = copy.deepcopy(previous)
    proposed.attacks["x1"].grounds = "Actually there was no mismatch"
    proposed.attacks["x1"].disposition = "withdrawn"
    changed = _snapshot_revision(previous, proposed, "proposer:test")
    assert changed.attacks["x1"].grounds == "Material mismatch"
    assert changed.attacks["x1"].disposition == "open"


def test_snapshot_preserves_challenge_ground_records_and_global_revision():
    _, graph, _ = example()
    previous = InquiryGraph.model_validate(graph)
    previous.revision = 4
    proposed = previous.model_copy(deep=True)
    proposed.evidence.clear()
    proposed.conditions.clear()
    retained = _snapshot_revision(previous, proposed, "proposer:test")
    assert retained.evidence["e1"] == previous.evidence["e1"]
    assert retained.conditions["cq1"] == previous.conditions["cq1"]
    proposed = previous.model_copy(deep=True)
    proposed.conditions["cq1"].status = "reopened"
    revised = _snapshot_revision(previous, proposed, "proposer:test")
    assert revised.conditions["cq1"].revision == 5
    proposed = previous.model_copy(deep=True)
    proposed.evidence["e1"].quote = "Replacement grounds"
    with pytest.raises(ValueError, match="immutable"):
        _snapshot_revision(previous, proposed, "proposer:test")


def test_unattacked_condition_assessment_can_be_revised_with_history():
    _, graph, _ = example()
    previous = InquiryGraph.model_validate(graph)
    proposed = previous.model_copy(deep=True)
    proposed.conditions["cq1"].text = "The attribution has now been examined against the located statement."
    revised = _snapshot_revision(previous, proposed, "proposer:test")
    assert revised.conditions["cq1"].revision == 2
    assert previous.conditions["cq1"].text != revised.conditions["cq1"].text
    previous.attacks["x1"] = Attack(
        id="x1", target_id="a1", condition_id="cq1", grounds="The attributed account is challenged.", evidence_ids=["e1"])
    with pytest.raises(ValueError, match="changed meaning"):
        _snapshot_revision(previous, proposed.model_copy(deep=True), "proposer:test")


def test_authoring_packet_never_enters_runtime():
    public, _, _ = example()
    public["evaluator_only"] = {"answer": "spoiler"}
    with pytest.raises(ValueError, match="private evaluation"):
        run_inquiry(public, RecordedWorker([]))


def test_ledger_tampering_is_detected(tmp_path):
    case, graph, response = example()
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]))
    save_run(result, tmp_path)
    path = tmp_path / "result.json"
    value = json.loads(path.read_text())
    value["response"]["text"] = "An unrecorded conclusion"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="payload differs"):
        load_run(tmp_path)


def test_provider_error_cannot_copy_credentials_into_run_record(monkeypatch):
    case, _, _ = example()
    fake_key = "sk-proj-example-credential-never-real"
    monkeypatch.setenv("OPENAI_API_KEY", fake_key)
    result = run_inquiry(case, RecordedWorker([RuntimeError("Invalid credential " + fake_key)]),
                         budget=Budget(max_model_calls=1))
    assert fake_key not in json.dumps(result)
    assert "[redacted credential]" in json.dumps(result)


def test_evaluator_exhaustion_cannot_complete_an_evidence_assessment():
    case, graph, response = example()
    case["question"]["profile"]["kernel"] = {"max_derivations": 0}
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]))
    assert not result["response"]["evaluation_completed"]
    assert not result["response"]["inquiry_completed"]
    assert result["status"] == "partial"
    assert "evaluation could not complete" in result["response"]["text"]


def test_starter_structure_supplies_no_warrant_or_hidden_answer():
    packet = load_packet()
    for question in packet.question_ids:
        case = to_inquiry_request(packet.public(question))
        scaffold = starter_graph(case)
        assert not scaffold["evidence"]
        assert all(condition["status"] == "open" for condition in scaffold["conditions"].values())
        result = evaluate(InquiryGraph.model_validate(scaffold), Profile(id="test"), evidence_context=None)
        assert all(finding.status == "not_established" for finding in result.findings.values())


def test_finish_with_misplaced_condition_ids_gets_a_bounded_record_repair():
    case, graph, response = example()
    malformed = copy.deepcopy(graph)
    malformed["arguments"]["a1"]["premise_ids"] = ["cq1", "cq2"]
    worker = RecordedWorker([
        {"operation": "finish", "graph": malformed, "response": response},
        {"operation": "finish", "graph": graph, "response": response},
    ])
    result = run_inquiry(case, worker)
    assert result["status"] == "complete"
    assert result["usage"]["model_calls"] == 2
    assert result["response"]["record_completed"]
    assert any(event["kind"] == "record_repair_requested" for event in result["events"])


def test_runtime_response_and_prompts_have_only_epistemic_output_fields():
    properties = ResponseDraft.model_json_schema()["properties"]
    assert set(properties) == {
        "text", "target_claim_id", "findings", "caveats", "target_scope_answered",
        "assessment", "inquiry_completed", "information_needs",
    }
    for application_field in ("next_action", "deliverable", "task_completed"):
        with pytest.raises(ValueError):
            Operation.model_validate({"operation": "finish", "response": {application_field: True}})
        assert application_field not in build_prompt("harness")
        assert application_field not in build_critic_prompt()
    for product in ("advance_intake", "final_eligibility", "policy_grounded_next_response"):
        assert product not in build_prompt("harness")


@pytest.mark.parametrize("question_id", [None, "another-question"])
def test_a_scoped_finding_must_be_anchored_to_the_active_question(question_id):
    case, graph, response = example()
    graph["claims"]["c1"]["target_question_id"] = question_id
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]))
    assert result["response"]["findings"][0]["status"] == "reported"
    assert result["response"]["target_scope_answered"]
    assert result["response"]["target_form_answered"]
    assert not result["response"]["target_question_answered"]
    assert not result["response"]["inquiry_completed"]
    assert result["status"] == "partial"


def test_target_contract_accepts_caller_kinds_without_a_product_lookup():
    case, graph, response = example()
    case["question"]["target"] = {"kind": "textual_observation", "form": "assertion"}
    graph["claims"]["c1"].update(kind="textual_observation", form="assertion")
    graph["arguments"]["a1"].update(pattern="document_record",
                                    conditions={"record_warrant": "cq1", "applicability": "cq2"})
    scaffold = starter_graph(case)
    assert scaffold["claims"]["c_target"]["kind"] == "textual_observation"
    assert scaffold["claims"]["c_target"]["form"] == "assertion"
    assert scaffold["arguments"]["a_target"]["pattern"] == "document_record"
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]))
    assert result["status"] == "complete", result["response"]
    assert result["response"]["findings"][0]["status"] == "established"


def test_an_unsupported_target_form_remains_an_explicit_implementation_gap():
    case, _, response = example()
    case["question"]["target"] = {"kind": "forecast", "form": "calibrated_interval"}
    graph = starter_graph(case)
    response["target_claim_id"] = "c_target"
    assert not graph["arguments"]
    assert graph["claims"]["c_target"]["form"] == "calibrated_interval"
    assert not _answers_form(graph["claims"]["c_target"], case["question"]["target"])
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]),
                         budget=Budget(max_model_calls=1))
    assert result["status"] == "partial"
    assert not result["response"]["target_form_answered"]
    assert not result["response"]["inquiry_completed"]
    assert "unsupported_claim_form:c_target" in result["response"]["record_defects"]


def test_unargued_target_without_an_explicit_gap_cannot_claim_a_completed_examination():
    case, graph, response = example()
    graph.update(arguments={}, evidence={}, conditions={})
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]),
                         budget=Budget(max_model_calls=1))
    assert result["response"]["findings"][0]["status"] == "not_established"
    assert "unresolved_target_condition_missing" in result["response"]["record_defects"]
    assert not result["response"]["inquiry_completed"]


def test_omitted_records_preserve_supported_findings_across_a_response_revision():
    case, graph, response = example()
    worker = RecordedWorker([
        {"operation": "submit", "graph": graph, "response": {**response, "inquiry_completed": False}},
        {"operation": "finish", "graph": {}, "response": response},
    ])
    result = run_inquiry(case, worker, budget=Budget(max_model_calls=2))
    assert result["status"] == "complete", result["errors"]
    assert not result["graph"]["arguments"]["a1"]["withdrawn"]
    assert result["graph"]["arguments"]["a1"]["revision"] == 1
    assert result["graph"]["revision"] == 2
    assert result["response"]["findings"][0]["status"] == "reported"
    assert result["response"]["findings"][0]["citations"]


def test_native_replay_does_not_mutate_the_committed_run():
    case, graph, response = example()
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]))
    before = copy.deepcopy(result)
    replay = replay_run(result)
    assert replay["replay_mode"] == "native"
    assert replay["evaluation_reproduced"]
    assert result == before


@pytest.mark.parametrize("field", ["max_model_calls", "max_tool_calls", "max_total_tokens",
                                   "max_critique_calls", "max_output_tokens", "max_consecutive_errors"])
@pytest.mark.parametrize("invalid", [True, False, 1.5, "2", None, -1])
def test_resource_counts_require_nonboolean_integers(field, invalid):
    with pytest.raises(ValueError, match=field):
        Budget(**{field: invalid})


@pytest.mark.parametrize("invalid", [True, False, 0, -1, float("nan"), float("inf"), -float("inf"), "5", None])
def test_timeout_requires_a_finite_positive_number(invalid):
    with pytest.raises(ValueError, match="timeout_seconds"):
        Budget(timeout_seconds=invalid)


@pytest.mark.parametrize("field", ["max_output_tokens", "max_consecutive_errors"])
def test_output_and_repair_limits_cannot_be_zero(field):
    with pytest.raises(ValueError, match=field):
        Budget(**{field: 0})
