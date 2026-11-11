import json
from pathlib import Path

import pytest

from experiments.analyze_cq_agreement import analyze, match_arguments, write_adjudication
from inquiry.argument.graph import CQAnswer
from inquiry.argument.schemes import SCHEMES
from inquiry.replay_move import argue_diagnostics, cq_outcome_bucket, fingerprint
from inquiry.state import Inquiry


def test_diagnostics_preserve_raw_unresolved_checks_and_count_failure_reasons():
    inq = Inquiry(id="cq", question="q")
    g = inq.graph
    q = g.add_issue("q")
    c = g.add_claim("The effect occurred", issue_id=q.id)
    unaccepted = g.add_claim("A required premise", issue_id=q.id)
    e = g.add_evidence("A measurement")
    a = g.add_argument("document_record", [e.id, unaccepted.id], c.id)
    g.answer_cq(a.id, "authentic", "Reasonable source default", [], defaulted=True)
    g.answer_cq(a.id, "accuracy", "The recording method is inadequate", [e.id], outcome="unsatisfied")
    g.answer_cq(a.id, "reading", "The wording is inconclusive", [e.id], outcome="unresolved")
    g.add_attack(a.id, "undercut", [e.id], origin="critic")
    withdrawn = g.add_argument("document_record", [e.id], c.id)
    withdrawn.withdrawn = "Replaced support"
    before = inq.model_dump()
    diagnostics = argue_diagnostics(inq)
    assert inq.model_dump() == before
    assert diagnostics["cq_outcomes"] == {"satisfied": 0, "unsatisfied": 1, "defaulted": 1, "open": 3}
    assert diagnostics["cq_outcomes_by_kind"]["assumption"]["open"] == 1
    assert diagnostics["cq_outcomes_by_kind"]["exception"]["open"] == 2
    assert diagnostics["cq_outcome_details"] == {"answered_unresolved": 1}
    assert diagnostics["inapplicable_reasons"] == {
        "open:reading": 1, "premise_claim_not_accepted": 1, "unsatisfied:accuracy": 1}
    assert cq_outcome_bucket(CQAnswer(status="answered", outcome="")) == "satisfied"


def record(aid, premises, text="The original proposition"):
    return {"argument_id": aid, "claim_id": "C1", "scheme": "study_result", "premise_ids": premises,
            "claim_text": text, "issue_id": "Q1", "answers_issue": True}


def test_matching_prefers_exact_premises_then_loose_one_to_one_matches():
    sol = [record("A1", ["E1", "E2"]), record("A2", ["E1"])]
    sonnet = [record("A1", ["E2", "E1"]), record("A2", ["E3"])]
    matches, collisions = match_arguments(sol, sonnet)
    assert not collisions
    assert [m["kind"] for m in matches] == ["exact", "loose_premises"]
    assert len({m["sol"]["argument_id"] for m in matches}) == 2


def test_identical_claim_ordinals_with_different_meanings_are_not_matches():
    matches, collisions = match_arguments([record("A1", ["E1"], "A scoped finding")],
                                          [record("A1", ["E1"], "A different scoped finding")])
    assert not matches and len(collisions) == 1


def write_cell(root: Path, provider: str):
    name = "sol" if provider == "openai" else "sonnet"
    out = root / "after/h1-claims" / name
    out.mkdir(parents=True)
    samples = []
    for n in range(1, 4):
        inq = Inquiry(id=f"{name}-{n}", question="Does treatment help all adults?")
        g = inq.graph
        q = g.add_issue(inq.question, question_type="causal")
        c = g.add_claim("Treatment helps all adults", issue_id=q.id)
        e = g.add_evidence("A result in the enrolled cohort")
        if provider == "openai":
            c = g.supersede_claim(c.id, ["Treatment helped the enrolled cohort"], answers_issue=False)[0]
        a = g.add_argument("study_result", [e.id], c.id)
        for question in SCHEMES[a.scheme].assumptions():
            outcome = "unsatisfied" if provider == "anthropic" and question.id == "directness" else "satisfied"
            g.answer_cq(a.id, question.id, "Check against the stated conclusion", [e.id], outcome=outcome)
        folder = out / f"sample-{n:03d}"
        folder.mkdir()
        (folder / "inquiry.json").write_text(inq.model_dump_json(indent=2), encoding="utf-8")
        samples.append({"provider": provider, "model": f"{name}-test", "effort": "medium", "sample": n,
                        "error": "", "graph": f"sample-{n:03d}/inquiry.json", "graph_sha256": fingerprint(inq.model_dump())})
    (out / "moves.json").write_text(json.dumps({"samples": samples}), encoding="utf-8")


def test_zero_matches_are_not_false_agreement_and_human_answers_survive_rerun(tmp_path):
    write_cell(tmp_path, "openai")
    write_cell(tmp_path, "anthropic")
    result, review = analyze(tmp_path, update_metrics=False)
    assert result["model_calls"] == 0 and not result["matched_cq_pairs"]
    assert len(result["sample_pairing"]) == 9 and len(result["diagnostic_lineage_contrasts"]) == 3
    assert all(r["rate"] is None for rs in result["per_cq_rates"].values() for r in rs)
    assert all(not c["comparable_as_same_claim"] for c in review["cases"])
    path = tmp_path / "cq_adjudication.json"
    review["cases"][0].update(adjudication="both_scope_appropriate", note="The conclusions differ in population.")
    path.write_text(json.dumps(review), encoding="utf-8")
    analyze(tmp_path, update_metrics=False)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["cases"][0]["adjudication"] == "both_scope_appropriate"
    assert saved["cases"][0]["note"] == "The conclusions differ in population."


def test_changed_cases_cannot_discard_human_adjudications(tmp_path):
    path = tmp_path / "review.json"
    path.write_text(json.dumps({"cases": [{"case_id": "old", "adjudication": "sol_inadequate", "note": "reason"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to discard"):
        write_adjudication(path, {"cases": [{"case_id": "new", "adjudication": "", "note": ""}]})
