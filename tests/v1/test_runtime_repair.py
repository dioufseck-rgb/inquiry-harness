"""Local record repair, useful delivery, and revision integrity at the controller."""

import copy
import json

import pytest

from inquiry.v1.evidence import EvidenceEnvironment
from inquiry.v1.kernel import evaluate
from inquiry.v1.models import Attack, Condition, InquiryGraph
from inquiry.v1.packets import load_packet
from inquiry.v1.runtime import Budget, _snapshot_revision, bind_profile, run_inquiry
from inquiry.v1.workers import RecordedWorker


def attributed_record():
    case = load_packet().public("question_001")
    document = next(d for d in case["corpus"]["documents"] if d["id"] == "doc_003")
    block = next(b for b in document["reading_blocks"] if b["locator"] == "field_group_2")
    scope = case["question"]["scope"]
    graph = {
        "claims": {"c": {"id": "c", "text": "The signed account reports a financial disruption.",
                          "kind": "attribution", "form": "source_reports", "scope": scope,
                          "target_question_id": case["question"]["id"]}},
        "evidence": {"e": {"id": "e", "source_id": document["id"],
                           "source_version": document["version"],
                           "locator": block["locator"], "quote": block["text"]}},
        "conditions": {
            "attribution": {"id": "attribution", "text": "Does the account state this report?",
                            "answer": "The quoted signed account contains the reported disruption.",
                            "status": "met", "evidence_ids": ["e"]},
            "applicability": {"id": "applicability", "text": "Does the report concern this case and period?",
                              "answer": "The account identifies the case and event date.",
                              "status": "met", "evidence_ids": ["e"]},
        },
        "arguments": {"a": {"id": "a", "claim_id": "c", "pattern": "attribution",
                            "premise_ids": ["e"], "scope": scope,
                            "conditions": {"attribution": "attribution", "applicability": "applicability"}}},
    }
    response = {"target_claim_id": "c", "task_completed": True,
                "next_action": {"kind": "answer", "description": "Return the attributed account."}}
    return case, graph, response


def policy_record(question_id):
    case = load_packet().public(question_id)
    document = next(d for d in case["corpus"]["documents"] if d["id"] == "doc_001")
    locator = "section_2" if question_id == "question_004" else "section_3"
    block = next(b for b in document["reading_blocks"] if b["locator"] == locator)
    scope = case["question"]["scope"]
    conditions = {}
    links = {}
    for key in ("authority", "antecedents", "inference_validity", "applicability"):
        cid = "check_" + key
        conditions[cid] = {
            "id": cid, "text": f"Is {key} satisfied for the bounded policy response?",
            "answer": "The supplied current policy expressly specifies this response and its limits.",
            "status": "met", "evidence_ids": ["policy"],
        }
        links[key] = cid
    graph = {
        "claims": {"c": {"id": "c", "text": "A bounded response can be drafted under the supplied policy.",
                          "kind": "policy", "form": "rule_consequence", "scope": scope,
                          "target_question_id": case["question"]["id"]}},
        "evidence": {"policy": {"id": "policy", "source_id": document["id"],
                                "source_version": document["version"],
                                "locator": locator, "quote": block["text"]}},
        "conditions": conditions,
        "arguments": {"a": {"id": "a", "claim_id": "c", "pattern": "rule_application",
                            "premise_ids": ["policy"], "scope": scope, "conditions": links}},
    }
    response = {
        "target_claim_id": "c", "task_completed": True,
        "text": "A complete response can be drafted from the supplied record.",
        "next_action": {"kind": "prepare_assessment",
                        "description": "The requested response can now be drafted."},
    }
    deliverable = (
        "We acknowledge your signed account and will proceed to review the separate final eligibility "
        "requirements. This intake step is not final approval."
        if question_id == "question_004" else
        "Final eligibility remains undetermined. The residence-register extract, income statement, and "
        "programme payment-register check remain outstanding. Their absence is not a finding of ineligibility."
    )
    return case, graph, response, deliverable


def test_malformed_submit_is_repaired_before_the_critic_sees_the_graph():
    case, graph, response = attributed_record()
    malformed = copy.deepcopy(graph)
    del malformed["arguments"]["a"]["conditions"]["applicability"]

    class StructuralCritic(RecordedWorker):
        def __init__(self):
            super().__init__([])
            self.observed_graphs = []

        def complete(self, system, user, max_tokens=4096):
            observed = json.loads(user)["graph"]
            self.observed_graphs.append(observed)
            attacks = {}
            if "applicability" not in observed["arguments"]["a"]["conditions"]:
                attacks["stale-structural-objection"] = {
                    "id": "stale-structural-objection", "target_id": "a",
                    "grounds": "The applicability condition link is missing.", "evidence_ids": ["e"],
                }
            self.replies.append({"observations": [], "attacks": attacks, "evidence_requests": []})
            return super().complete(system, user, max_tokens=max_tokens)

    critic = StructuralCritic()
    proposer = RecordedWorker([
        {"operation": "submit", "graph": malformed, "response": response},
        {"operation": "submit", "graph": graph, "response": response},
        {"operation": "finish", "response": response},
    ])
    result = run_inquiry(case, proposer, critic=critic, budget=Budget(max_model_calls=4))
    assert result["status"] == "complete", result["errors"]
    assert result["usage"]["failed_calls"] == 0
    assert len(critic.observed_graphs) == 1
    assert critic.observed_graphs[0]["arguments"]["a"]["conditions"] == graph["arguments"]["a"]["conditions"]
    assert result["graph"]["attacks"] == {}
    inputs = [event for event in result["events"] if event["kind"] == "worker_input"]
    assert [event["data"]["role"] for event in inputs] == ["proposer", "proposer", "critic", "proposer"]
    repair = next(event for event in result["events"] if event["kind"] == "record_repair_requested")
    assert repair["sequence"] < inputs[2]["sequence"]
    assert result["response"]["record_completed"]


@pytest.mark.parametrize("question_id", ["question_004", "question_005"])
def test_saying_a_policy_response_can_be_drafted_does_not_deliver_it(question_id):
    case, graph, response, _ = policy_record(question_id)
    response["deliverable"] = " \n "
    result = run_inquiry(
        case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]),
        budget=Budget(max_model_calls=1),
    )
    assert result["evaluation"]["findings"]["c"]["status"] == "established"
    assert result["response"]["record_completed"]
    assert not result["response"]["delivery_completed"]
    assert "requested_deliverable_missing" in result["response"]["delivery_defects"]
    assert not result["response"]["task_completed"]
    assert result["status"] == "partial"


@pytest.mark.parametrize("question_id", ["question_004", "question_005"])
def test_bounded_delivery_repair_can_supply_the_actual_requested_response(question_id):
    case, graph, response, deliverable = policy_record(question_id)
    completed_response = {**response, "deliverable": deliverable}
    proposer = RecordedWorker([
        {"operation": "finish", "graph": graph, "response": response},
        {"operation": "finish", "graph": graph, "response": completed_response},
    ])
    result = run_inquiry(case, proposer, budget=Budget(max_model_calls=2))
    assert result["status"] == "complete", result["errors"]
    assert result["usage"]["model_calls"] == 2
    assert result["response"]["delivery_completed"]
    assert result["response"]["task_completed"]
    assert result["response"]["deliverable"] == deliverable
    assert deliverable in result["response"]["text"]
    assert "deliverable" in json.loads(proposer.calls[1]["user"])["feedback"][-1].lower()


def challenged_snapshot(*, with_stale_reply=False):
    case, graph_data, _ = attributed_record()
    graph = _snapshot_revision(None, InquiryGraph.model_validate(graph_data), "proposer:initial")
    graph.revision = 5
    graph.attacks["objection"] = Attack(
        id="objection", target_id="a", condition_id="attribution", basis="answer_inadequate",
        grounds="The interpretation of the recorded account omits a material limitation.",
        evidence_ids=["e"], performer="critic:reviewer", performer_kind="model",
        raised_revision=4, challenged_revision=1,
    )
    if with_stale_reply:
        graph.conditions["reply"] = Condition(
            id="reply", text="Does this response address the interpretation objection?",
            answer="An earlier assessment of the source exists.", status="met", evidence_ids=["e"],
            performer="proposer:initial", performer_kind="model", revision=2,
        )
        graph.attacks["objection"].reply_condition_id = "reply"
        graph.attacks["objection"].reply_evidence_ids = ["e"]
        graph.attacks["objection"].reply_reason = "The existing assessment is offered for consideration."
        graph.attacks["objection"].reply_revision = 5
    env = EvidenceEnvironment(case)
    env.initial_input(worker_id="proposer")
    return graph, bind_profile(case), env


def test_condition_answer_changes_while_the_challenged_question_stays_stable():
    previous, _, _ = challenged_snapshot()
    proposed = previous.model_copy(deep=True)
    proposed.conditions["attribution"].answer = "The reassessment explicitly retains the source's stated limitation."
    proposed.conditions["attribution"].revision = 400
    revised = _snapshot_revision(previous, proposed, "proposer:reviser")
    assert revised.revision == 6
    assert revised.conditions["attribution"].text == previous.conditions["attribution"].text
    assert revised.conditions["attribution"].answer != previous.conditions["attribution"].answer
    assert revised.conditions["attribution"].revision == 6
    assert revised.conditions["attribution"].performer == "proposer:reviser"
    assert revised.attacks["objection"].reply_revision is None
    assert revised.attacks["objection"].grounds == previous.attacks["objection"].grounds


def test_metadata_only_recopies_cannot_refresh_an_old_reply_or_argument():
    previous, profile, env = challenged_snapshot(with_stale_reply=True)
    previous.evidence["e_copy"] = previous.evidence["e"].model_copy(update={"id": "e_copy"})
    previous.conditions["reply"].evidence_ids.append("e_copy")
    proposed = previous.model_copy(deep=True)
    proposed.conditions["reply"].revision = 400
    proposed.conditions["reply"].performer = "invented-independent-checker"
    proposed.conditions["reply"].performer_kind = "tool"
    proposed.conditions["reply"].model_extra["copied_at"] = "new ledger snapshot"
    proposed.conditions["reply"].evidence_ids.reverse()
    proposed.arguments["a"].revision = 400
    proposed.attacks["objection"].reply_revision = 400
    revised = _snapshot_revision(previous, proposed, "proposer:reviser")
    assert revised.revision == 6
    assert revised.conditions["reply"].revision == 2
    assert revised.conditions["reply"].performer == "proposer:initial"
    assert revised.conditions["reply"].performer_kind == "model"
    assert revised.conditions["reply"].model_extra["copied_at"] == "new ledger snapshot"
    assert revised.conditions["reply"].evidence_ids == ["e_copy", "e"]
    assert revised.arguments["a"].revision == previous.arguments["a"].revision
    assert revised.attacks["objection"].reply_revision == 5
    result = evaluate(revised, profile, evidence_context=env)
    assert result.attack_labels["objection"] == "IN"
    assert "reply_does_not_discharge" in {item["code"] for item in result.diagnostics}


def test_revising_a_referenced_reply_assessment_updates_both_controller_revisions():
    previous, profile, env = challenged_snapshot(with_stale_reply=True)
    proposed = previous.model_copy(deep=True)
    proposed.conditions["reply"].answer = "The revised reading addresses the exact objection and preserves the qualification."
    revised = _snapshot_revision(previous, proposed, "proposer:reviser")
    assert revised.conditions["reply"].revision == revised.attacks["objection"].reply_revision == 6
    assert revised.attacks["objection"].raised_revision == 4
    assert revised.conditions["reply"].text == previous.conditions["reply"].text
    result = evaluate(revised, profile, evidence_context=env)
    assert result.attack_labels["objection"] == "OUT"
    assert result.findings["c"].status == "reported"


def test_argument_content_revision_is_stamped_and_cannot_delete_an_objection():
    previous, profile, env = challenged_snapshot()
    proposed = previous.model_copy(deep=True)
    proposed.arguments["a"].revision = 400
    proposed.conditions["supplementary-review"] = Condition(
        id="supplementary-review", text="Has an additional source check been recorded?",
        answer="A further reading confirms the same attribution.", status="met", evidence_ids=["e"],
    )
    proposed.arguments["a"].conditions["supplementary"] = "supplementary-review"
    proposed.attacks.clear()
    revised = _snapshot_revision(previous, proposed, "proposer:reviser")
    assert revised.arguments["a"].revision == revised.revision == 6
    assert revised.attacks["objection"] == previous.attacks["objection"]
    result = evaluate(revised, profile, evidence_context=env)
    assert result.attack_labels["objection"] == "IN"
    assert result.findings["c"].status == "not_established"


def test_unargued_universal_with_an_open_coverage_gap_can_complete_the_assessment():
    case = load_packet().public("question_006")
    graph = {
        "claims": {"universal": {
            "id": "universal", "text": "Every worker in the requested population lost wages because of the event.",
            "kind": "substantive", "form": "universal", "scope": case["question"]["scope"],
            "target_question_id": case["question"]["id"], "conditions": ["population-coverage"],
        }},
        "conditions": {"population-coverage": {
            "id": "population-coverage", "text": "Do the records cover every worker in the requested population?",
            "answer": "The supplied area event and individual account do not provide population-wide coverage.",
            "status": "open", "evidence_ids": [],
        }},
    }
    response = {
        "target_claim_id": "universal", "task_completed": True,
        "next_action": {"kind": "answer", "description": "Withhold the universal statement because population "
                        "coverage is missing. This does not establish that the statement is false or supply a counterexample."},
    }
    result = run_inquiry(
        case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]),
        budget=Budget(max_model_calls=1),
    )
    assert result["status"] == "complete", result["errors"]
    assert result["response"]["record_completed"]
    assert result["response"]["task_completed"]
    assert result["evaluation"]["findings"]["universal"]["status"] == "not_established"
    assert result["evaluation"]["findings"]["universal"]["open_conditions"] == ["population-coverage"]
    assert "unsupported_claim_form" not in {item["code"] for item in result["evaluation"]["diagnostics"]}
    assert result["graph"]["arguments"] == {}
    assert result["usage"]["model_calls"] == 1


def test_open_claim_condition_is_an_evidential_gap_not_a_record_repair():
    case, graph, response, deliverable = policy_record("question_005")
    graph["claims"]["c"]["text"] = "Final eligibility is established under the supplied policy."
    graph["claims"]["c"]["conditions"] = ["residence-record"]
    graph["conditions"]["residence-record"] = {
        "id": "residence-record", "text": "Has the required residence-register extract been supplied?",
        "answer": "The supplied record does not contain the required extract.",
        "status": "open", "evidence_ids": [],
    }
    response["deliverable"] = deliverable
    result = run_inquiry(
        case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]),
        budget=Budget(max_model_calls=1),
    )
    assert result["status"] == "complete", result["errors"]
    assert result["response"]["record_completed"]
    assert result["response"]["task_completed"]
    finding = result["evaluation"]["findings"]["c"]
    assert finding["status"] == "not_established"
    assert finding["open_conditions"] == ["residence-record"]
    assert "argument_claim_not_admitted" in {item["code"] for item in result["evaluation"]["diagnostics"]}
    assert not any(event["kind"] == "record_repair_requested" for event in result["events"])
    assert result["response"]["deliverable"] == deliverable


def test_explicit_finish_survives_a_clean_review_without_an_extra_proposer_call():
    case, graph, response, deliverable = policy_record("question_004")
    response["deliverable"] = deliverable
    proposer = RecordedWorker([{"operation": "finish", "graph": graph, "response": response}])
    critic = RecordedWorker([{"observations": ["The bounded response follows the supplied policy."], "attacks": {}}])
    result = run_inquiry(case, proposer, critic=critic, budget=Budget(max_model_calls=2))
    assert result["status"] == "complete", result["errors"]
    assert result["stop_reason"] == "settled_for_purpose"
    assert result["response"]["record_completed"]
    assert result["response"]["delivery_completed"]
    assert result["response"]["review_completed"]
    assert result["response"]["deliverable"] == deliverable
    assert len(proposer.calls) == len(critic.calls) == 1
    assert result["usage"]["model_calls"] == 2
    assert any(event["kind"] == "finish_accepted_after_review" for event in result["events"])


def test_identical_submit_after_review_can_settle_despite_a_new_snapshot_revision():
    case, graph, response = attributed_record()
    submission = {"operation": "submit", "graph": graph, "response": response}
    proposer = RecordedWorker([submission, submission])
    critic = RecordedWorker([{"observations": [], "attacks": {}}])
    result = run_inquiry(case, proposer, critic=critic, budget=Budget(max_model_calls=3))
    assert result["status"] == "complete", result["errors"]
    assert len(proposer.calls) == 2  # The first arbitrary submit is not final.
    assert result["usage"]["model_calls"] == 3
    graphs = [event["data"] for event in result["events"] if event["kind"] == "graph"]
    assert graphs[0]["revision"] + 1 == graphs[1]["revision"]
    assert {key: value for key, value in graphs[0].items() if key != "revision"} == {
        key: value for key, value in graphs[1].items() if key != "revision"
    }
    assert not any(event["kind"] == "finish_accepted_after_review" for event in result["events"])


@pytest.mark.parametrize("change", ["graph", "response"])
def test_a_changed_submission_does_not_match_the_artifact_reviewed_earlier(change):
    case, graph, response = attributed_record()
    first = {"operation": "submit", "graph": graph, "response": response}
    revised = copy.deepcopy(first)
    if change == "graph":
        revised["graph"]["conditions"]["attribution"]["answer"] = "The report is quoted faithfully, with its source limitation retained."
    else:
        revised["response"]["next_action"]["description"] = "Return the attributed account with its limit on independent verification."
    proposer = RecordedWorker([first, revised])
    critic = RecordedWorker([{"observations": [], "attacks": {}}])
    result = run_inquiry(case, proposer, critic=critic, budget=Budget(max_model_calls=3))
    assert result["status"] == "partial"
    assert result["stop_reason"] == "resource_limit"
    assert len(proposer.calls) == 2
    assert result["response"]["review_completed"]
    assert not any(event["kind"] == "finish_accepted_after_review" for event in result["events"])


def test_a_new_substantive_attack_returns_control_to_the_proposer_after_finish():
    case, graph, response = attributed_record()
    unresolved = {**response, "task_completed": False}
    proposer = RecordedWorker([
        {"operation": "finish", "graph": graph, "response": response},
        {"operation": "finish", "response": unresolved},
    ])
    critic = RecordedWorker([{"observations": [], "attacks": {"objection": {
        "id": "objection", "target_id": "a", "condition_id": "attribution",
        "basis": "answer_inadequate", "grounds": "The interpretation omits a material source qualification.",
        "evidence_ids": ["e"],
    }}}])
    result = run_inquiry(case, proposer, critic=critic, budget=Budget(max_model_calls=3))
    assert len(proposer.calls) == 2
    assert result["usage"]["model_calls"] == 3
    assert result["evaluation"]["attack_labels"]["objection"] == "IN"
    assert result["stop_reason"] == "information_unavailable"
    assert not result["response"]["task_completed"]
    assert not any(event["kind"] == "finish_accepted_after_review" for event in result["events"])


def test_repeated_submissions_do_not_automatically_settle_an_unanswered_attack():
    case, graph, response = attributed_record()
    submission = {"operation": "submit", "graph": graph, "response": response}
    proposer = RecordedWorker([submission, submission, submission])
    critic = RecordedWorker([{"observations": [], "attacks": {"objection": {
        "id": "objection", "target_id": "a", "condition_id": "attribution",
        "basis": "answer_inadequate", "grounds": "The interpretation omits a material source qualification.",
        "evidence_ids": ["e"],
    }}}])
    result = run_inquiry(case, proposer, critic=critic, budget=Budget(max_model_calls=4))
    assert len(proposer.calls) == 3
    assert result["evaluation"]["attack_labels"]["objection"] == "IN"
    assert result["status"] == "partial"
    assert result["stop_reason"] == "resource_limit"
    assert not any(event["kind"] == "finish_accepted_after_review" for event in result["events"])


@pytest.mark.parametrize("review", [
    {"observations": []},
    {"observations": [], "attacks": {}, "evidence_requests": [
        {"operation": "open", "arguments": {"source_id": "doc_001", "version": "1.0"},
         "reason": "Read the relevant policy before completing the review."},
    ]},
])
def test_invalid_or_provisional_review_cannot_complete_a_pending_finish(review):
    case, graph, response = attributed_record()
    proposer = RecordedWorker([{"operation": "finish", "graph": graph, "response": response}])
    critic = RecordedWorker([review])
    result = run_inquiry(case, proposer, critic=critic, budget=Budget(max_model_calls=2))
    assert result["status"] == "partial"
    assert not result["response"]["review_completed"]
    assert not result["response"]["task_completed"]
    assert not any(event["kind"] == "finish_accepted_after_review" for event in result["events"])


@pytest.mark.parametrize("gap", ["scope", "completion", "existing_attack"])
def test_a_clean_review_does_not_override_outstanding_completion_gates(gap):
    case, graph, response = attributed_record()
    if gap == "scope":
        graph["claims"]["c"]["scope"] = graph["arguments"]["a"]["scope"] = {"subject_id": "other-case"}
    elif gap == "completion":
        response["task_completed"] = False
    else:
        graph["attacks"] = {"existing": {"id": "existing", "target_id": "a",
                            "grounds": "The inference still faces an unanswered source limitation.", "evidence_ids": ["e"]}}
    proposer = RecordedWorker([{"operation": "finish", "graph": graph, "response": response}])
    critic = RecordedWorker([{"observations": [], "attacks": {}}])
    result = run_inquiry(case, proposer, critic=critic, budget=Budget(max_model_calls=2))
    assert result["response"]["review_completed"]
    assert result["status"] == "partial"
    assert result["stop_reason"] == "resource_limit"
    assert not any(event["kind"] == "finish_accepted_after_review" for event in result["events"])


@pytest.mark.parametrize("condition_status", ["missing", "met", "open", "reopened", "assumed"])
def test_harness_information_requests_reference_existing_unresolved_conditions(condition_status):
    case, graph, response, _ = policy_record("question_004")
    case = load_packet().public("question_004", "mutation_002")
    requested_id = "check_antecedents" if condition_status == "met" else "needed_statement_details"
    if condition_status not in {"missing", "met"}:
        graph["conditions"][requested_id] = {
            "id": requested_id, "text": "Have the missing statement details been supplied?",
            "answer": "The applicant still needs to provide the missing details.",
            "status": condition_status, "evidence_ids": [],
        }
    response["deliverable"] = "We received your application. Please provide the missing statement details before intake can advance. No award decision has been made."
    response["next_action"] = {"kind": "request_information", "description": "Request the missing statement details.",
                               "condition_ids": [requested_id]}
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "graph": graph, "response": response}]),
                         budget=Budget(max_model_calls=1))
    if condition_status in {"missing", "met"}:
        code = "requested_condition_missing:" if condition_status == "missing" else "requested_condition_already_met:"
        assert code + requested_id in result["response"]["delivery_defects"]
        assert not result["response"]["delivery_completed"]
        assert not result["response"]["task_completed"]
    else:
        assert result["status"] == "complete", result["errors"]
        assert result["response"]["delivery_completed"]
        assert result["evaluation"]["findings"]["c"]["status"] == "established"
        assert result["graph"]["claims"]["c"]["conditions"] == []
    assert result["graph"]["conditions"]["check_antecedents"]["status"] == "met"


def test_pointer_repair_separates_requested_information_from_met_policy_antecedents():
    case, graph, response, _ = policy_record("question_004")
    case = load_packet().public("question_004", "mutation_002")
    response["deliverable"] = "Please provide your personal financial-disruption description and the event date. Intake cannot advance until those details are supplied; no award decision has been made."
    response["next_action"] = {"kind": "request_information", "description": "Request the two missing statement details.",
                               "condition_ids": ["check_antecedents"]}
    repaired_graph = copy.deepcopy(graph)
    for cid, question in (("needed_description", "Has the personal financial-disruption description been supplied?"),
                          ("needed_event_when", "Has the event date been supplied?")):
        repaired_graph["conditions"][cid] = {"id": cid, "text": question, "status": "open", "evidence_ids": []}
    repaired_response = copy.deepcopy(response)
    repaired_response["next_action"]["condition_ids"] = ["needed_description", "needed_event_when"]
    proposer = RecordedWorker([
        {"operation": "finish", "graph": graph, "response": response},
        {"operation": "finish", "graph": repaired_graph, "response": repaired_response},
    ])
    result = run_inquiry(case, proposer, budget=Budget(max_model_calls=2))
    assert result["status"] == "complete", result["errors"]
    assert result["evaluation"]["findings"]["c"]["status"] == "established"
    assert result["graph"]["conditions"]["check_antecedents"]["status"] == "met"
    assert result["graph"]["conditions"]["check_antecedents"]["revision"] == 1
    assert result["graph"]["claims"]["c"]["conditions"] == []
    assert all(result["graph"]["conditions"][cid]["status"] == "open"
               for cid in repaired_response["next_action"]["condition_ids"])
    feedback = json.loads(proposer.calls[1]["user"])["feedback"][-1]
    assert "do not reopen" in feedback
    assert "prerequisites of the clarification recommendation" in feedback


@pytest.mark.parametrize("arm", ["ordinary", "repertoire"])
def test_non_graph_information_requests_keep_descriptive_ids(arm):
    case, _, response, deliverable = policy_record("question_004")
    response["deliverable"] = deliverable
    response["next_action"] = {"kind": "request_information", "description": "Request missing details.",
                               "condition_ids": ["descriptive_missing_detail"]}
    result = run_inquiry(case, RecordedWorker([{"operation": "finish", "response": response}]),
                         arm=arm, budget=Budget(max_model_calls=1))
    assert result["status"] == "complete"
    assert result["response"]["task_completed"]
    assert result["graph"] is None


def test_direct_self_support_requires_record_repair_before_it_can_settle():
    case, graph, response, deliverable = policy_record("question_005")
    response["deliverable"] = deliverable
    circular = copy.deepcopy(graph)
    circular["arguments"]["a"]["premise_ids"] = ["c"]
    proposer = RecordedWorker([
        {"operation": "finish", "graph": circular, "response": response},
        {"operation": "finish", "graph": graph, "response": response},
    ])
    result = run_inquiry(case, proposer, budget=Budget(max_model_calls=2))
    repairs = [event for event in result["events"] if event["kind"] == "record_repair_requested"]
    assert len(repairs) == 1
    assert "unsupported_support_cycle:c" in repairs[0]["data"]["defects"]
    assert len(proposer.calls) == 2
    assert result["status"] == "complete", result["errors"]
    assert result["evaluation"]["findings"]["c"]["status"] == "established"
