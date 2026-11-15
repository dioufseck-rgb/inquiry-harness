"""B4: the source-adjudication fixture family and its scripted test instrument. No live calls."""
import json

import pytest

from inquiry.v1 import cli
from inquiry.v1.adapters.adjudication import (CASES_PATH, CASE_TYPES, EXPECTATIONS_PATH, VARIANTS,
                                              adjudication_case, load_adjudication_cases)
from inquiry.v1.adapters.adjudication_demo import AdjudicationWorker
from inquiry.v1.experiments import FORBIDDEN_PUBLIC_KEYS, run_experiments
from inquiry.v1.runtime import Budget, run_inquiry

BUDGET = Budget(max_model_calls=8, max_tool_calls=40)


def target_of(result):
    response = result["response"]
    return next(f for f in response["findings"] if f["claim_id"] == response["target_claim_id"])


def run(case, *, arm="harness", mode="supplied"):
    return run_inquiry(dict(case.public_case), AdjudicationWorker(), arm=arm, mode=mode, budget=BUDGET)


# -- the family ---------------------------------------------------------------------------------

def test_twelve_cases_with_expectations_held_apart():
    cases = load_adjudication_cases()
    assert {c.case_id for c in cases} == {f"{t}:{v}" for t in CASE_TYPES for v in VARIANTS} and len(cases) == 12
    public_text = CASES_PATH.read_text(encoding="utf-8")
    private_keys = set(FORBIDDEN_PUBLIC_KEYS) | {"allowed_target_statuses", "expected_mechanism", "case_type", "inquiry_completed"}
    assert not any(key in public_text for key in private_keys)
    assert "bank" not in public_text.casefold() and "loan" not in public_text.casefold()
    expectations = json.loads(EXPECTATIONS_PATH.read_text(encoding="utf-8"))
    assert set(expectations["cases"]) == {c.case_id for c in cases}
    for case in cases:
        assert set(case.public_case) == {"shared_context", "corpus", "question"}
        kernel = case.public_case["question"]["profile"]["kernel"]
        assert kernel == {"min_origins": 2, "premise_min_origins": 1, "allowed_patterns": ["attribution", "source_adjudication"]}
        assert case.smoke_expectation["allowed_target_statuses"] and case.oracle["case_type"] in CASE_TYPES
    assert adjudication_case("hearsay:compressor").variant_id == "compressor"
    with pytest.raises(ValueError, match="Unknown"):
        load_adjudication_cases(["nope"])
    # the two surface variants differ in identifiers, dates and wording
    pump, compressor = adjudication_case("corroborated:pump"), adjudication_case("corroborated:compressor")
    assert pump.public_case["question"]["scope"] != compressor.public_case["question"]["scope"]
    assert {b["text"] for d in pump.public_case["corpus"]["documents"] for b in d["reading_blocks"]}.isdisjoint(
        {b["text"] for d in compressor.public_case["corpus"]["documents"] for b in d["reading_blocks"]})


# -- the scripted worker, case by case ------------------------------------------------------------

@pytest.mark.parametrize("mode", ["supplied", "documents", "search"])
def test_scripted_worker_reaches_the_expected_status_in_the_harness_arm(mode):
    for case in load_adjudication_cases():
        result = run(case, mode=mode)
        exp = case.smoke_expectation
        target = target_of(result)
        detail = (case.case_id, mode, result["evaluation"]["diagnostics"], result["response"]["record_defects"],
                  result["response"]["response_defects"], result["stop_reason"])
        assert target["status"] in exp["allowed_target_statuses"], detail
        assert result["response"]["inquiry_completed"] is exp["inquiry_completed"], detail
        assert set(exp["required_condition_ids"]) <= {n["condition_id"] for n in result["response"]["information_needs"]}, detail
        assert result["status"] == ("complete" if exp["inquiry_completed"] else "partial")
        assert result["usage"]["cost_usd"] == 0.0


def test_corroborated_rests_on_two_origins_and_the_adjudication_pattern():
    result = run(adjudication_case("corroborated:pump"))
    finding = result["evaluation"]["findings"]["C_target"]
    assert finding["status"] == "established" and len(finding["support_origins"]) == 2
    assert result["graph"]["arguments"]["A_target"]["pattern"] == "source_adjudication"
    assert "shift-note/pump-A4" not in {c["source_id"] for c in target_of(result)["citations"]}  # the relay is not relied on


def test_interested_only_leaves_independence_open_and_counts_one_origin():
    result = run(adjudication_case("interested_only:compressor"))
    finding = result["evaluation"]["findings"]["C_target"]
    assert finding["status"] == "not_established" and "K_independence" in finding["open_conditions"]
    assert result["response"]["meets_declared_standing"] is False and result["response"]["resolution_state"] == "open_needs"


def test_opposed_unanswered_has_a_standing_founded_rebut():
    result = run(adjudication_case("opposed_unanswered:pump"))
    labels = result["evaluation"]["attack_labels"]
    assert labels == {"X_inspector_log_pump_A4": "IN"}
    assert result["response"]["standing_attack_ids"] == ["X_inspector_log_pump_A4"]
    assert result["response"]["inquiry_completed"] is False and result["stop_reason"] == "information_unavailable"


def test_opposed_answered_discharges_the_rebut_from_a_later_revision():
    result = run(adjudication_case("opposed_answered:compressor"))
    attack = result["graph"]["attacks"]["X_inspector_log_compressor_C7"]
    assert attack["raised_revision"] == 1 and attack["reply_revision"] == 2
    assert result["graph"]["conditions"][attack["reply_condition_id"]]["revision"] == 2
    assert result["evaluation"]["attack_labels"][attack["id"]] == "OUT"
    assert result["evaluation"]["findings"]["C_target"]["status"] == "established"
    assert result["graph"]["revision"] == 2 and result["response"]["inquiry_completed"] is True


def test_superseded_version_is_never_cited():
    result = run(adjudication_case("superseded:pump"))
    cited = {(c["source_id"], c["version"]) for c in target_of(result)["citations"]}
    assert ("inspector-log/pump-A4", "2") in cited and ("inspector-log/pump-A4", "1") not in cited
    assert result["evaluation"]["findings"]["C_target"]["status"] == "established"


def test_hearsay_leaves_positioning_open():
    result = run(adjudication_case("hearsay:pump"))
    finding = result["evaluation"]["findings"]["C_target"]
    assert finding["status"] == "not_established" and "K_positioning" in finding["open_conditions"]
    need = next(n for n in result["response"]["information_needs"] if n["condition_id"] == "K_positioning")
    assert need["resolver_kind"] == "source"


@pytest.mark.parametrize("arm", ["ordinary", "repertoire"])
def test_other_arms_complete_with_the_worker_declared_status(arm):
    for case in load_adjudication_cases():
        result = run(case, arm=arm)
        exp = case.smoke_expectation
        assert target_of(result)["status"] in exp["allowed_target_statuses"], case.case_id
        assert result["status"] in {"complete", "partial"} and result["usage"]["model_calls"] == 1


# -- the runner and the command line ------------------------------------------------------------

def test_family_runs_through_the_experiment_runner(tmp_path):
    def run_case(public, *, arm, mode):
        return run_inquiry(public, AdjudicationWorker(), arm=arm, mode=mode, budget=BUDGET)
    report = run_experiments(load_adjudication_cases(), run_case, arms=["harness"], modes=["supplied"], output_dir=tmp_path / "x")
    summary = report["summary"]
    assert summary["failed_runs"] == 0 and summary["smoke_status_counts"] == {"pass": 12}
    assert not {"fail", "error", "unassessed"} & set(summary["structural_status_counts"])


def test_bench_and_run_accept_the_adjudication_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_code_version", lambda: "test-code")
    monkeypatch.setattr(cli, "_code_dirty", lambda: False)
    assert cli.main(["bench", "--demo", "--adapter", "adjudication", "--arms", "harness", "--modes", "supplied",
                     "--questions", "corroborated:pump", "hearsay:compressor", "--out", str(tmp_path / "bench")]) == 0
    report = json.loads((tmp_path / "bench" / "experiment.json").read_text(encoding="utf-8"))
    assert {r["manifest"]["case_id"] for r in report["runs"]} == {"corroborated:pump", "hearsay:compressor"}
    assert report["configuration"]["adapter"] == "adjudication" and report["configuration"]["execution_kind"] == "scripted_smoke"
    assert cli.main(["run", "--demo", "--adapter", "adjudication", "--question", "opposed_answered:pump",
                     "--out", str(tmp_path / "single")]) == 0
    for bad in (["bench", "--demo", "--adapter", "adjudication", "--packet", "x.json", "--out", str(tmp_path / "b2")],
                ["run", "--demo", "--adapter", "adjudication", "--out", str(tmp_path / "s2")],
                ["bench", "--demo", "--adapter", "adjudication", "--questions", "nope", "--out", str(tmp_path / "b3")]):
        with pytest.raises(SystemExit) as raised:
            cli.main(bad)
        assert raised.value.code == 2
