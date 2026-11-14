from copy import deepcopy
import json

import pytest

from inquiry.v1.experiments import ExperimentCase, RunExecutionError, run_experiments, stable_hash
from inquiry.v1.scoring import hardship_smoke_expectation


def case(case_id="case_a", family_id="family_one", split="development"):
    public = {"shared_context": {"as_of": "2026-04-12"}, "corpus": {"documents": []},
              "question": {"id": "question_001", "question": "What is reported?",
                           "scope": {"subject": "applicant"}, "profile": {"id": "attribution", "version": "1"}}}
    return ExperimentCase(case_id, family_id, public,
                          {"hidden_world": {"secret": "never_send_this_to_a_worker"},
                           "admissible_answer_spec": {"required": ["Attribution"]}},
                          "question_001", split=split,
                          smoke_expectation=hardship_smoke_expectation("question_001"))


def configuration():
    return {"model_pool": [{"provider": "recorded", "model": "fixture", "version": "1"}],
            "prompt_hashes": {arm: stable_hash(arm) for arm in ("ordinary", "repertoire", "harness")},
            "tool_hash": "tools-1", "kernel_hash": "kernel-1", "code_version": "commit-fixture",
            "oracle_version": "authoring-0.1", "resource_envelope": {"max_calls": 4},
            "execution_kind": "recorded"}


def recorded_run(public, *, arm, mode):
    return {
        "arm": arm, "mode": mode, "status": "complete", "question_id": public["question"]["id"],
        "response": {"text": "A reported account.", "target_claim_id": "c1", "target_scope_answered": True,
                     "findings": [{"claim_id": "c1", "text": "A reported account.", "status": "reported",
                                   "scope": public["question"]["scope"], "conditions": [], "citations": []}],
                     "next_action": {"kind": "answer", "condition_ids": []}, "task_completed": True},
        "graph": None, "evaluation": None, "exposures": [], "errors": [],
        "usage": {"model_calls": 2, "input_tokens": 10, "output_tokens": 5,
                  "tool_calls": 1, "failed_calls": 1, "cost_usd": 0.2, "elapsed_seconds": 0.1},
    }


def test_all_arms_modes_and_repetitions_receive_only_fresh_public_inputs():
    c = case()
    calls = []

    def worker_callback(public, *, arm, mode):
        assert set(public) == {"shared_context", "corpus", "question"}
        assert "never_send_this_to_a_worker" not in json.dumps(public)
        assert "changed" not in public["shared_context"]
        calls.append((arm, mode))
        public["shared_context"]["changed"] = True
        return recorded_run(public, arm=arm, mode=mode)

    report = run_experiments([c], worker_callback, repetitions=2, manifest=configuration())
    assert len(calls) == 18
    assert "changed" not in c.public_case["shared_context"]
    assert report["summary"]["attempts"] == 18
    assert report["summary"]["usage_known_totals"]["failed_calls"] == 18
    assert report["summary"]["usage_known_totals"]["cost_usd"] == pytest.approx(3.6)
    assert report["summary"]["human_review_status_counts"] == {"pending": 18}
    assert report["summary"]["automatic_substantive_accuracy"] is None
    assert report["summary"]["smoke_status_counts"] == {"pass": 18}
    assert len(report["family_summaries"]) == 9
    assert len({r["manifest"]["public_input_hash"] for r in report["runs"]}) == 1
    assert all(r["manifest"]["missing_configuration"] == [] for r in report["runs"])


def test_arm_name_changes_no_scoring_or_outcome_by_itself():
    report = run_experiments([case()], recorded_run, modes=["supplied"], manifest=configuration())
    scores = [r["score"] for r in report["runs"]]
    assert scores[0]["structural"] == scores[1]["structural"] == scores[2]["structural"]
    assert scores[0]["smoke"] == scores[1]["smoke"] == scores[2]["smoke"]
    assert all(score["human"]["status"] == "pending" for score in scores)


def test_explicit_form_rejection_is_not_counted_as_task_completion():
    def wrong_form(public, *, arm, mode):
        result = recorded_run(public, arm=arm, mode=mode)
        result["response"]["target_form_answered"] = False
        return result
    report = run_experiments([case()], wrong_form, arms=["harness"], modes=["supplied"])
    assert report["summary"]["task_completed_count"] == 0
    assert report["summary"]["smoke_status_counts"] == {"fail": 1}


def test_incomplete_evaluation_is_not_counted_as_task_completion():
    def incomplete(public, *, arm, mode):
        result = recorded_run(public, arm=arm, mode=mode)
        result["response"]["evaluation_completed"] = False
        return result
    report = run_experiments([case()], incomplete, arms=["harness"], modes=["supplied"])
    assert report["summary"]["task_completed_count"] == 0
    assert report["summary"]["evaluation_completion_status_counts"] == {"not_completed": 1}
    assert report["summary"]["smoke_status_counts"] == {"fail": 1}
    baseline = run_experiments([case()], recorded_run, arms=["ordinary"], modes=["supplied"])
    assert baseline["summary"]["evaluation_completion_status_counts"] == {"pending": 1}


def test_family_cannot_leak_across_development_and_held_out():
    with pytest.raises(ValueError, match="same split"):
        run_experiments([case(), case("case_b", split="held_out")], recorded_run)


def test_full_authoring_packet_and_nested_oracle_are_rejected_before_callback():
    c = case()
    invalid = deepcopy(dict(c.public_case))
    invalid["evaluator_only"] = {"secret": True}
    with pytest.raises(ValueError, match="exactly"):
        ExperimentCase("bad", "family", invalid, {}, "question_001")
    invalid = deepcopy(dict(c.public_case))
    invalid["shared_context"]["hidden_world"] = {"secret": True}
    with pytest.raises(ValueError, match="Private"):
        ExperimentCase("bad", "family", invalid, {}, "question_001")


def test_exception_costs_and_failed_calls_are_retained():
    def fail(public, *, arm, mode):
        raise RunExecutionError("Provider failed after usage", usage={
            "model_calls": 1, "input_tokens": 20, "output_tokens": 0,
            "tool_calls": 0, "failed_calls": 1, "cost_usd": 0.13})
    report = run_experiments([case()], fail, arms=["ordinary"], modes=["supplied"], repetitions=2)
    s = report["summary"]
    assert s["attempts"] == s["failed_runs"] == 2
    assert s["usage_known_totals"]["cost_usd"] == pytest.approx(0.26)
    assert s["usage_known_totals"]["failed_calls"] == 2
    assert s["monetary_cost_complete"] is True
    assert s["smoke_status_counts"] == {"not_checkable": 2}


def test_unknown_exception_cost_is_not_reported_as_a_free_run():
    def fail(public, **kwargs):
        raise RuntimeError("No provider accounting returned")
    report = run_experiments([case()], fail, arms=["ordinary"], modes=["search"])
    s = report["summary"]
    assert s["failed_runs"] == 1
    assert s["monetary_cost_complete"] is False
    assert s["usage_unknown_run_counts"]["cost_usd"] == 1
    assert s["usage_unknown_run_counts"]["failed_calls"] == 1


def test_partial_known_spend_survives_incomplete_overall_cost():
    def partial_cost(public, *, arm, mode):
        result = recorded_run(public, arm=arm, mode=mode)
        result["usage"].update(cost_usd=None, known_cost_usd=0.07, cost_complete=False)
        return result
    report = run_experiments([case()], partial_cost, arms=["ordinary"], modes=["supplied"])
    assert report["summary"]["usage_known_totals"]["cost_usd"] == 0.07
    assert report["summary"]["monetary_cost_complete"] is False


def test_invalid_json_result_preserves_available_usage():
    def invalid_json(public, *, arm, mode):
        result = recorded_run(public, arm=arm, mode=mode)
        result["invalid_extra"] = float("nan")
        return result
    report = run_experiments([case()], invalid_json, arms=["ordinary"], modes=["supplied"])
    assert report["summary"]["failed_runs"] == 1
    assert report["summary"]["usage_known_totals"]["cost_usd"] == 0.2


def test_malformed_or_misbound_result_remains_failed_with_its_known_cost():
    def wrong_arm(public, *, arm, mode):
        result = recorded_run(public, arm=arm, mode=mode)
        result["arm"] = "another_arm"
        return result
    report = run_experiments([case()], wrong_arm, arms=["ordinary"], modes=["supplied"])
    assert report["summary"]["failed_runs"] == 1
    assert report["summary"]["usage_known_totals"]["cost_usd"] == 0.2
    assert report["summary"]["task_completed_count"] == 0


def test_recorded_job_order_is_reproducible_but_repetitions_stay_in_family():
    args = dict(modes=["supplied"], repetitions=2, order_seed=42)
    first = run_experiments([case(), case("case_b")], recorded_run, **args)
    second = run_experiments([case(), case("case_b")], recorded_run, **args)
    ordering = lambda r: [(x["manifest"]["case_id"], x["manifest"]["arm"], x["manifest"]["repetition"]) for x in r["runs"]]
    assert ordering(first) == ordering(second)
    assert len(first["family_splits"]) == 1
    assert len(first["family_summaries"]) == 3


def test_output_retains_all_attempts_and_does_not_overwrite(tmp_path):
    report = run_experiments([case()], recorded_run, arms=["ordinary"], modes=["documents"], output_dir=tmp_path)
    assert len((tmp_path / "runs.jsonl").read_text().splitlines()) == 1
    assert json.loads((tmp_path / "experiment.json").read_text())["summary"]["attempts"] == 1
    assert report["runs"][0]["manifest"]["oracle_hash"]
    with pytest.raises(FileExistsError):
        run_experiments([case()], recorded_run, output_dir=tmp_path)


def test_pending_review_keeps_mutation_overlay_and_hidden_truth_outside_worker():
    original = case()
    oracle = deepcopy(dict(original.oracle))
    oracle["mutation"] = {"id": "mutation_003", "expected_relationships": ["Independent trace now available"]}
    changed = ExperimentCase(original.case_id, original.family_id, original.public_case, oracle,
                             original.question_id, variant_id="mutation_003")
    report = run_experiments([changed], recorded_run, arms=["ordinary"], modes=["supplied"])
    rubric = report["runs"][0]["score"]["human"]["answer_spec"]
    assert rubric["mutation"]["id"] == "mutation_003"
    assert rubric["hidden_world"]["secret"] == "never_send_this_to_a_worker"
    assert report["runs"][0]["score"]["human"]["status"] == "pending"
