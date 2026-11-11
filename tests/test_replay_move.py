import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from inquiry.experiment_budget import BudgetExceeded, ExperimentBudget, estimate_cost, token_counts
from inquiry.llm import FakeLLM
from inquiry.replay_move import (apply_evidence_map, claim_fingerprint, load_run, mapping_template,
                                  reconstruct_pre_move, run_samples)
from inquiry.state import Inquiry


def tiny():
    i = Inquiry(id="tiny", question="Did X happen?")
    g = i.graph
    q = g.add_issue(i.question)
    c = g.add_claim("X happened", issue_id=q.id)
    s1 = g.add_source(url="https://a.example", title="A")
    s2 = g.add_source(url="https://b.example", title="B")
    g.add_evidence("Grade D", source_id=s1.id, quote="Grade D", bears_on={c.id: "for"})
    g.add_evidence("Second item", source_id=s2.id, bears_on={c.id: "against"})
    a = g.add_argument("document_record", ["E1"], c.id)
    x = g.add_attack(a.id, "undercut", ["E2"], origin="critic", note="reason (conceded by proposer: need more)")
    g.add_argument("document_record", ["E2"], c.id)
    return i


def test_argue_replay_ulez_zero_pre_arguments_and_fixed_output(tmp_path):
    final, _ = load_run(Path("bench/run-artifacts/ulez-live-4"))
    pre, preparation = reconstruct_pre_move(final, "argue")
    assert pre.graph.arguments == []
    assert final.graph.arguments  # the saved input was not modified
    cid = pre.main_claims()[0].id
    eid = pre.graph.evidence[0].id
    proposal = {"claim_reasons": [{"claim_id": c.id, "reason": "The fixed test proposal leaves this claim without an argument."} for c in pre.graph.claims if c.id != cid],
                "arguments": [{"scheme": "document_record", "claim_id": cid, "premise_ids": [eid],
                               "cq_answers": {qid: {"answer": "record", "evidence_ids": [eid]}
                                              for qid in ("authentic", "accuracy", "reading")}}]}
    result = run_samples(pre, "argue", lambda: FakeLLM({"argue": proposal}), tmp_path / "probe", preparation=preparation)
    assert len(result["samples"]) == 3
    assert all(s["metrics"]["supporting_args"] == 1 and not s["error"] for s in result["samples"])
    assert result["aggregate"]["supporting_args"] == {"mean": 1, "min": 1, "max": 1, "n": 3}
    assert not json.loads((tmp_path / "probe/pre-move.json").read_text())["graph"]["arguments"]
    assert all(s["provider"] == "fake" and s["cost_usd"] == 0 for s in result["samples"])


def test_hypothesize_projection_is_deterministic_and_empty():
    final = tiny()
    a, _ = reconstruct_pre_move(final, "hypothesize")
    b, _ = reconstruct_pre_move(final, "hypothesize")
    assert a.model_dump() == b.model_dump()
    assert a.graph.issues and not a.graph.claims and not a.graph.evidence
    assert not a.graph.sources and not a.graph.arguments and not a.tests


def test_critique_compacts_arguments_and_respond_clears_dispositions():
    final = tiny()
    pre, _ = reconstruct_pre_move(final, "critique")
    assert [a.id for a in pre.graph.arguments] == ["A1", "A2"]
    assert not any(a.is_attack for a in pre.graph.arguments)
    assert not pre.graph.validate_refs()
    pre, metadata = reconstruct_pre_move(final, "respond")
    assert "conceded by proposer" not in pre.graph.arg("A2").note
    assert metadata["dispositions_reset"] and len(pre.graph.arguments) == 3


def test_appraise_removal_keeps_other_source_and_avoids_id_collisions():
    pre, _ = reconstruct_pre_move(tiny(), "appraise", source_id="S1")
    assert len(pre.graph.evidence) == 1 and pre.graph.evidence[0].source_id == "S2"
    assert pre.graph.evidence[0].id == "E1"
    assert not pre.graph.validate_refs()
    new = pre.graph.add_evidence("New extraction", source_id="S1")
    assert new.id == "E2" and not pre.graph.validate_refs()


def test_replaced_claims_match_issue_text_and_need_reviewed_stances():
    final = tiny()
    target_issue = final.graph.add_issue("Outcome?")
    other = Inquiry(id="other", question=final.question)
    other.graph.add_issue(final.question)
    other.graph.add_issue("Different sub-issue")
    same = other.graph.add_issue("Outcome?")
    other.graph.add_claim("X did not happen", issue_id=same.id)
    pre, info = reconstruct_pre_move(final, "argue", claims_from=other)
    assert pre.graph.claims[0].issue_id == target_issue.id
    assert info["requires_evidence_map"]
    assert pre.graph.evidence[0].bears_on == {}  # no old C1 -> new C1 alias
    data = mapping_template(pre)
    with pytest.raises(ValueError, match="reviewed"):
        apply_evidence_map(pre, data)
    data.update(reviewed=True, reviewed_by="test reviewer")
    data["directions"]["E1"] = {"C1": "against"}
    apply_evidence_map(pre, data)
    assert pre.graph.ev("E1").bears_on == {"C1": "against"}
    data["claims_sha256"] = "wrong graph"
    with pytest.raises(ValueError, match="different claim set"):
        apply_evidence_map(pre, data)


def test_cache_aware_costing_is_consistent_across_api_usage_shapes():
    rate = {"input": 2, "cached_input": .1, "cache_write": 2.5, "output": 10}
    anthropic = {"input_tokens": 100, "cache_read_input_tokens": 300, "cache_creation_input_tokens": 200, "output_tokens": 50}
    openai = {"input_tokens": 600, "cached_input_tokens": 300, "cache_write_input_tokens": 200, "output_tokens": 50}
    assert token_counts(anthropic, False) == token_counts(openai, True)
    assert estimate_cost(anthropic, rate) == pytest.approx(.00123)
    assert estimate_cost(openai, {**rate, "input_includes_cache": True}) == pytest.approx(.00123)


def test_budget_protects_opus_reserve_and_retains_unknown_charge(tmp_path):
    b = ExperimentBudget(tmp_path / "budget.json", {"anthropic": 1}, {"anthropic": .4})
    first = b.reserve("anthropic", .5)
    with pytest.raises(BudgetExceeded):
        b.reserve("anthropic", .2)
    b.finish(first, .1, {})
    second = b.reserve("anthropic", .5)
    b.finish(second, None, {})
    with pytest.raises(BudgetExceeded):
        b.reserve("anthropic", .01)
    last = b.reserve("anthropic", .4, use_reserved=True)
    b.finish(last, .2, {})
    assert b.status()["spent"]["anthropic"] == pytest.approx(.8)


def test_llm_usage_keeps_cache_tokens_for_experiment_accounting():
    llm = FakeLLM({})
    llm._usage(SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=2,
                                                   cache_creation_input_tokens=100, cache_read_input_tokens=50)))
    assert llm.usage[0]["cache_creation_input_tokens"] == 100
    assert llm.usage[0]["cache_read_input_tokens"] == 50
