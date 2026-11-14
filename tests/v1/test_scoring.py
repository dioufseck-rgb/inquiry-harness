from copy import deepcopy

import pytest

from inquiry.v1.scoring import (
    HUMAN_DIMENSIONS, SCORER_VERSION, SMOKE_METRIC_VERSION, SMOKE_ORACLE_VERSION,
    categorical_smoke_assertions, hardship_smoke_expectation,
    hardship_smoke_matrix, human_rubric_review, result_fingerprint, score_run, structural_audit,
)


def public_case():
    return {
        "shared_context": {"as_of": "2026-04-12"},
        "corpus": {"documents": [{"id": "doc_1", "version": "1.0",
            "reading_blocks": [{"locator": "p1", "text": "The applicant reports losing 80 credits."}]}]},
        "question": {"id": "question_001", "question": "What does the applicant report?",
                     "scope": {"subject": "applicant"}, "profile": {"id": "profile_1"}},
    }


def valid_run():
    quote = "The applicant reports losing 80 credits."
    finding = {"claim_id": "c1", "text": "The applicant reports losing 80 credits.",
               "status": "reported", "scope": {"subject": "applicant"}, "conditions": [],
               "citations": [{"source_id": "doc_1", "version": "1.0", "locator": "p1", "quote": quote}]}
    return {
        "run_id": "run1", "arm": "ordinary", "mode": "supplied", "status": "complete",
        "question_id": "question_001", "response": {"text": finding["text"], "findings": [finding],
            "target_claim_id": "c1", "target_scope_answered": True, "task_completed": True,
            "next_action": {"kind": "answer", "description": "Summarize the account.", "condition_ids": []}},
        "graph": None, "evaluation": None,
        "exposures": [{"phase": "worker_input", "worker_id": "proposer", "segments": [
            {"source_id": "doc_1", "version": "1.0", "locator": "p1", "text": quote}]}],
    }


def graph_run():
    run = valid_run()
    run["arm"] = "harness"
    run["graph"] = {
        "claims": {"c1": {"id": "c1", "text": run["response"]["findings"][0]["text"]}},
        "evidence": {"e1": {"id": "e1", "source_id": "doc_1", "source_version": "1.0",
                                  "locator": "p1", "quote": "The applicant reports losing 80 credits."}},
    }
    run["evaluation"] = {"findings": {"c1": {"claim_id": "c1", "status": "reported",
        "scope": {"subject": "applicant"}, "condition_texts": [], "evidence_ids": ["e1"]}}}
    return run


def test_structural_pass_never_becomes_substantive_success():
    result = score_run(valid_run(), public_case(), answer_spec={"required": ["Attribution"]},
                       smoke_expectation=hardship_smoke_expectation("question_001"))
    assert result["structural"]["status"] == "pass"
    assert result["smoke"]["status"] == "pass"
    assert result["smoke"]["human_outcome_score"] is None
    assert result["human"]["status"] == "pending"
    assert all(value is None for value in result["human"]["ratings"].values())


def test_keyword_or_quote_match_does_not_judge_prose_entailment():
    run = valid_run()
    run["response"]["text"] = "Every resident certainly lost wages; the quotation proves it."
    result = score_run(run, public_case())
    assert result["structural"]["status"] == "pass"
    assert result["structural"]["substantive_validity_established"] is False
    assert result["human"]["status"] == "pending"


@pytest.mark.parametrize("field,value", [("version", "2.0"), ("locator", "p9"), ("quote", "Invented statement")])
def test_citation_transcription_and_locator_are_exact_checks(field, value):
    run = valid_run()
    run["response"]["findings"][0]["citations"][0][field] = value
    assert structural_audit(run, public_case())["status"] == "fail"


def test_retrieval_is_not_worker_exposure_and_partial_read_is_not_full_read():
    run = valid_run()
    run["exposures"][0]["phase"] = "tool_returned"
    audit = structural_audit(run, public_case())
    assert "finding:c1:citation:0:worker_input_exposure" in audit["failed_checks"]
    run["exposures"][0]["phase"] = "worker_input"
    run["exposures"][0]["segments"][0]["text"] = "The applicant reports"
    assert structural_audit(run, public_case())["status"] == "fail"


def test_table_citation_is_checked_at_its_exact_cell_locator():
    public = public_case()
    public["corpus"]["documents"][0]["tables"] = [{"id": "t1", "columns": ["wages"],
        "column_units": {"wages": "credits"}, "rows": [{"id": "r1", "cells": {"wages": 80}}],
        "footnotes": ["Reported, not independently verified."]}]
    run = valid_run()
    cell = {"source_id": "doc_1", "version": "1.0", "locator": "table:t1/row:r1/column:wages", "quote": "80"}
    run["response"]["findings"][0]["citations"] = [cell]
    run["exposures"][0]["segments"] = [{**cell, "text": "80"}]
    assert structural_audit(run, public)["status"] == "pass"
    run["response"]["findings"][0]["citations"][0]["locator"] = "table:t1/row:r2/column:wages"
    assert structural_audit(run, public)["status"] == "fail"


def test_graph_report_consistency_is_checked_without_kernel_import():
    run = graph_run()
    assert structural_audit(run, public_case())["status"] == "pass"
    run["response"]["findings"][0]["status"] = "established"
    assert "finding:c1:evaluated_status" in structural_audit(run, public_case())["failed_checks"]


def test_evaluation_cannot_cite_an_unrecorded_basis():
    run = graph_run()
    run["evaluation"]["findings"]["c1"]["evidence_ids"] = []
    assert "finding:c1:citations_in_recorded_basis" in structural_audit(run, public_case())["failed_checks"]


def test_component_acceptance_does_not_pass_requested_scope_smoke():
    run = valid_run()
    run["response"]["findings"][0]["scope"] = {"subject": "another person"}
    run["response"]["target_scope_answered"] = False
    run["response"]["task_completed"] = False
    smoke = categorical_smoke_assertions(run, hardship_smoke_expectation("question_001"))
    assert smoke["status"] == "fail"
    run["response"]["target_scope_answered"] = True
    assert "declared_target_scope_matches_record" in structural_audit(run, public_case())["failed_checks"]


def test_explicit_target_form_rejection_blocks_smoke_and_completion_claim():
    run = valid_run()
    run["response"]["target_form_answered"] = False
    audit = structural_audit(run, public_case())
    assert "target_form_gate" in audit["failed_checks"]
    assert "target_form_completion_consistent" in audit["failed_checks"]
    assert categorical_smoke_assertions(run, hardship_smoke_expectation("question_001"))["status"] == "fail"


def test_baseline_without_form_gate_retains_pending_semantic_review():
    result = score_run(valid_run(), public_case())
    check = next(c for c in result["structural"]["checks"] if c["name"] == "target_form_gate")
    assert check["passed"] is None
    assert result["human"]["status"] == "pending"


@pytest.mark.parametrize("evaluation_status", ["failed", "incomplete"])
def test_failed_evaluation_cannot_be_masked_by_a_true_completion_flag(evaluation_status):
    run = graph_run()
    run["response"]["evaluation_completed"] = True
    run["evaluation"]["evaluation_status"] = evaluation_status
    result = score_run(run, public_case(), smoke_expectation=hardship_smoke_expectation("question_001"))
    assert "evaluation_completion_gate" in result["structural"]["failed_checks"]
    assert "declared_evaluation_matches_record" in result["structural"]["failed_checks"]
    assert result["smoke"]["status"] == "fail"
    assert result["human"]["status"] == "pending"


def test_explicit_incomplete_evaluation_never_passes_the_smoke_gate():
    run = valid_run()
    run["response"]["evaluation_completed"] = False
    result = score_run(run, public_case(), smoke_expectation=hardship_smoke_expectation("question_001"))
    assert "evaluation_task_completion_consistent" in result["structural"]["failed_checks"]
    assert result["smoke"]["status"] == "fail"


def test_absent_baseline_evaluation_remains_unassessed():
    result = score_run(valid_run(), public_case())
    check = next(c for c in result["structural"]["checks"] if c["name"] == "evaluation_completion_gate")
    assert check["passed"] is None
    assert result["human"]["status"] == "pending"


def test_failed_run_without_a_target_or_graph_is_unassessed_not_a_vacuous_pass():
    run = valid_run()
    run["status"] = "failed"
    run["response"].update(target_claim_id=None, findings=[], task_completed=False)
    result = score_run(run, public_case(), smoke_expectation=hardship_smoke_expectation("question_001"))
    audit = result["structural"]
    assert audit["status"] == "unassessed"
    assert audit["failed_checks"] == []
    assert set(audit["unassessed_checks"]) >= {
        "target_references_finding", "evaluation_completion_gate", "graph_report_alignment"
    }
    assert audit["assessment_coverage"]["target_finding_present"] is False
    assert audit["assessment_coverage"]["graph_returned"] is False
    assert audit["assessment_coverage"]["evaluation_returned"] is False
    assert result["smoke"]["status"] == "not_checkable"
    assert result["human"]["status"] == "pending"


def test_structural_coverage_distinguishes_audited_baseline_records_from_missing_graph():
    audit = structural_audit(valid_run(), public_case())
    assert audit["status"] == "pass"
    assert audit["assessment_coverage"]["target_finding_present"] is True
    assert audit["assessment_coverage"]["graph_returned"] is False
    assert "graph_report_alignment" in audit["unassessed_checks"]
    assert audit["assessment_coverage"]["unassessed_checks"] == len(audit["unassessed_checks"])
    assert audit["substantive_validity_established"] is False


def declared_non_establishment_run():
    public = public_case()
    public["question"].update(id="question_005", question="Does the record establish final eligibility?",
                              profile={"id": "profile_005", "required_form": "final_eligibility_assessment"},
                              scope={"case_id": "case_001", "stage": "final_eligibility"})
    run = valid_run()
    run["question_id"] = "question_005"
    finding = run["response"]["findings"][0]
    finding.update(text="The supplied record does not establish final eligibility.",
                   kind="policy", form="rule_consequence", status="established",
                   target_relation="record_non_establishment", target_question_id="question_005",
                   scope=deepcopy(public["question"]["scope"]))
    run["response"].update(text=finding["text"], target_form_answered=True,
                            next_action={"kind": "prepare_assessment", "condition_ids": []})
    return public, run


def test_explicit_anchored_non_establishment_has_distinct_claim_and_target_statuses():
    public, run = declared_non_establishment_run()
    result = score_run(run, public, smoke_expectation=hardship_smoke_expectation("question_005"))
    assert result["smoke"]["status"] == "pass"
    comparison = result["smoke"]["target_status_comparison"]
    assert comparison["claim_status"] == "established"
    assert comparison["compared_target_status"] == "not_established"
    assert comparison["method"] == "declared_record_non_establishment"
    assert comparison["semantic_alignment"] == "pending_human_review"
    assert result["human"]["status"] == "pending"
    assert result["structural"]["substantive_validity_established"] is False


@pytest.mark.parametrize("deliverable", ["", "   ", None])
def test_delivery_completion_cannot_replace_the_required_artifact(deliverable):
    public, run = declared_non_establishment_run()
    run["response"].update(delivery_completed=True, delivery_defects=[], deliverable=deliverable)
    result = score_run(run, public, smoke_expectation=hardship_smoke_expectation("question_005"))
    assert "declared_delivery_has_required_artifact" in result["structural"]["failed_checks"]
    assert result["smoke"]["status"] == "fail"
    run["response"]["deliverable"] = "Final eligibility remains undetermined pending the required register records."
    assert score_run(run, public, smoke_expectation=hardship_smoke_expectation("question_005"))["smoke"]["status"] == "pass"


@pytest.mark.parametrize("flag", ["delivery_completed", "review_completed"])
def test_explicit_incomplete_delivery_or_review_cannot_claim_task_completion(flag):
    run = valid_run()
    run["response"][flag] = False
    result = score_run(run, public_case(), smoke_expectation=hardship_smoke_expectation("question_001"))
    assert f"{flag}:task_completion_consistent" in result["structural"]["failed_checks"]
    assert result["smoke"]["status"] == "fail"
    assert result["human"]["status"] == "pending"


def test_delivery_success_must_not_retain_recorded_delivery_defects():
    run = valid_run()
    run["response"].update(delivery_completed=True, delivery_defects=["requested_deliverable_missing"])
    assert "declared_delivery_has_no_recorded_defects" in structural_audit(run, public_case())["failed_checks"]


@pytest.mark.parametrize("text", [
    "The supplied record does not establish final eligibility.",
    "The applicant certainly satisfies every final eligibility requirement.",
    "An unrelated positive claim is established.",
])
def test_prose_alone_never_reclassifies_an_established_direct_target(text):
    public, run = declared_non_establishment_run()
    finding = run["response"]["findings"][0]
    finding.pop("target_relation")
    finding.pop("target_question_id")
    finding["text"] = text
    result = score_run(run, public, smoke_expectation=hardship_smoke_expectation("question_005"))
    assert result["smoke"]["status"] == "fail"
    assert result["smoke"]["target_status_comparison"]["compared_target_status"] == "established"
    assert next(c for c in result["smoke"]["checks"] if c["name"] == "target_status")["passed"] is False
    assert result["human"]["status"] == "pending"


@pytest.mark.parametrize("field,value", [
    ("target_question_id", None), ("target_question_id", "question_003"),
    ("scope", {"case_id": "another_case", "stage": "final_eligibility"}),
    ("kind", "substantive"), ("form", "assertion"),
])
def test_non_establishment_normalization_requires_explicit_question_scope_and_form(field, value):
    public, run = declared_non_establishment_run()
    run["response"]["findings"][0][field] = value
    smoke = categorical_smoke_assertions(run, hardship_smoke_expectation("question_005"), public_case=public)
    assert smoke["status"] == "fail"
    assert smoke["target_status_comparison"]["compared_target_status"] is None


def test_non_establishment_cannot_be_retagged_only_in_the_rendered_finding():
    public, run = declared_non_establishment_run()
    finding = deepcopy(run["response"]["findings"][0])
    run["graph"] = {"claims": {"c1": {**finding, "id": "c1", "target_relation": "direct"}}}
    run["evaluation"] = {"findings": {"c1": finding}}
    result = score_run(run, public, smoke_expectation=hardship_smoke_expectation("question_005"))
    assert result["smoke"]["status"] == "fail"
    assert "finding:c1:record_target_relation" in result["structural"]["failed_checks"]
    assert result["smoke"]["target_status_comparison"]["compared_target_status"] is None


@pytest.mark.parametrize("relation,status", [("negated", "established"),
                                            ("record_non_establishment", "not_established"),
                                            ("record_non_establishment", "conditional")])
def test_other_negative_status_combinations_are_not_inverted(relation, status):
    public, run = declared_non_establishment_run()
    run["response"]["findings"][0].update(target_relation=relation, status=status)
    result = score_run(run, public, smoke_expectation=hardship_smoke_expectation("question_005"))
    assert result["smoke"]["status"] == "not_checkable"
    assert result["smoke"]["target_status_comparison"]["compared_target_status"] is None
    assert result["human"]["status"] == "pending"


def test_scoring_changes_are_versioned_without_rewriting_supplied_expectations():
    expectation = hardship_smoke_expectation("question_001")
    assert expectation["oracle_version"] == SMOKE_ORACLE_VERSION == "hardship-categorical-smoke-0.2"
    old_expectation = deepcopy(expectation)
    old_expectation["oracle_version"] = "hardship-categorical-smoke-0.1"
    original = deepcopy(old_expectation)
    result = score_run(valid_run(), public_case(), smoke_expectation=old_expectation)
    assert old_expectation == original
    assert result["scorer_version"] == SCORER_VERSION
    assert result["smoke"]["metric_version"] == SMOKE_METRIC_VERSION
    assert result["smoke"]["oracle_version"] == "hardship-categorical-smoke-0.1"
    assert result["smoke"]["status"] == "pass"


def test_correct_component_does_not_mask_overclaimed_target():
    run = valid_run()
    run["response"]["findings"].append({"claim_id": "c2", "status": "not_established"})
    run["response"]["findings"][0]["status"] = "established"
    smoke = categorical_smoke_assertions(run, hardship_smoke_expectation("question_003"))
    assert smoke["status"] == "fail"


def test_smoke_matrix_covers_all42_cells_and_material_mutations():
    matrix = hardship_smoke_matrix()
    assert len(matrix) == 42
    assert len({(x["question_id"], x["variant_id"]) for x in matrix}) == 42
    assert all(not x["human_adjudicated"] for x in matrix)
    assert hardship_smoke_expectation("question_002", "mutation_004")["allowed_target_statuses"] == ["not_established", "conditional"]
    assert hardship_smoke_expectation("question_003", "mutation_003")["allowed_target_statuses"] == ["established"]
    impact = hardship_smoke_expectation("question_004", "mutation_002")
    declaration = hardship_smoke_expectation("question_004", "mutation_005")
    assert impact["allowed_next_actions"] == declaration["allowed_next_actions"] == ["request_information"]
    assert impact["required_condition_ids"] == ["impact_description", "event_date"]
    assert declaration["required_condition_ids"] == ["prior_payment_declaration"]
    for q in range(1, 7):
        baseline = hardship_smoke_expectation(f"question_{q:03d}")
        for variant in ("mutation_001", "mutation_006"):
            invariant = hardship_smoke_expectation(f"question_{q:03d}", variant)
            for key in ("allowed_target_statuses", "allowed_next_actions", "required_condition_ids"):
                assert invariant[key] == baseline[key]


def test_failing_and_malformed_drafts_are_not_smoke_passes():
    run = valid_run()
    run["status"] = "failed"
    assert categorical_smoke_assertions(run, hardship_smoke_expectation("question_001"))["status"] == "not_checkable"
    run["status"] = "partial"
    run["response"]["findings"] = None
    assert categorical_smoke_assertions(run, hardship_smoke_expectation("question_001"))["status"] == "not_checkable"


def test_only_explicit_separate_human_review_populates_outcome_ratings():
    review = {"status": "adjudicated", "author_type": "human", "reviewer_ids": ["reviewer_a", "reviewer_b"],
              "rubric_version": "review-1", "ratings": {d: "pass" for d in HUMAN_DIMENSIONS}}
    assert human_rubric_review(adjudication=review)["status"] == "adjudicated"
    model_review = deepcopy(review)
    model_review["author_type"] = "model"
    assert human_rubric_review(adjudication=model_review)["status"] == "invalid_adjudication"
    assert human_rubric_review(adjudication={"status": "adjudicated"})["ratings"]["world_truth"] is None


def test_human_outcome_review_cannot_be_copied_to_another_run_or_changed_graph():
    run = valid_run()
    review = {"status": "adjudicated", "author_type": "human", "reviewer_ids": ["reviewer_a"],
              "rubric_version": "review-1", "ratings": {d: "pass" for d in HUMAN_DIMENSIONS},
              "run_id": run["run_id"], "result_hash": result_fingerprint(run)}
    assert score_run(run, public_case(), human_adjudication=review)["human"]["status"] == "adjudicated"
    run["response"]["text"] = "A different output."
    scored = score_run(run, public_case(), human_adjudication=review)
    assert scored["human"]["status"] == "invalid_adjudication"
    assert all(value is None for value in scored["human"]["ratings"].values())
