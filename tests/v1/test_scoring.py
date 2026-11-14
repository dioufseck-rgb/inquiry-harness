from copy import deepcopy

import pytest

from inquiry.v1.scoring import (
    HUMAN_DIMENSIONS, categorical_smoke_assertions, hardship_smoke_expectation,
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
