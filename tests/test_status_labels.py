import pytest
from inquiry.argument import ArgumentGraph, Credentials
from inquiry.argument.evaluate import evaluate
from inquiry.argument.render import summary, wigmore
from inquiry.argument.schemes import SCHEMES
from inquiry.metrics import shape_match
from inquiry.state import Inquiry
from inquiry.bench import score_shape
from inquiry.llm import FakeLLM


def setup_case(kind):
    g = ArgumentGraph()
    q = g.add_issue("Did it change?", question_type="causal" if kind == "weak" else "empirical")
    c = g.add_claim("It increased", issue_id=q.id)
    n = g.add_claim("It did not increase", issue_id=q.id, kind="null")
    g.set_contraries(c.id, n.id)
    if kind == "untested":
        return g, c
    strength = "moderate" if kind in ("contested", "weak") else "strong"
    e = g.add_evidence("A relevant observation", bears_on={c.id: "for"},
                       credentials=Credentials(relevance=strength, credibility=strength, force=strength))
    if kind == "unsupported":
        return g, c
    def add(claim):
        a = g.add_argument("document_record", [e.id], claim.id)
        for cq in SCHEMES[a.scheme].assumptions():
            g.answer_cq(a.id, cq.id, "Checked", [e.id])
        return a
    if kind == "refuted":
        add(n)
        return g, c
    a = add(c)
    if kind == "contested":
        add(n)
    elif kind == "defeated":
        attack = g.add_attack(a.id, "undercut", [e.id], origin="critic")
        attack.attacks.raises_cq = "definitions"
    return g, c


@pytest.mark.parametrize("kind", ["accepted", "refuted", "defeated", "contested", "unsupported", "untested", "weak"])
def test_each_status_label_is_derived_without_changing_proof_statuses(kind):
    g, c = setup_case(kind)
    ev = evaluate(g)
    label = "insufficient" if kind == "weak" else kind
    assert ev.claims[c.id].label == label
    assert ev.status(c.id) in ("in", "out", "undecided")
    report = summary(g, ev)
    assert f"- {label} {c.id}:" in report
    assert all(mark not in report + wigmore(g, ev) for mark in ("✓", "✗"))


def test_expected_undecided_requires_a_real_contest_not_weak_unopposed_support():
    g, c = setup_case("weak")
    ev = evaluate(g)
    inq = Inquiry(id="weak", question="q", graph=g)
    assert ev.status(c.id) == "undecided" and ev.claims[c.id].pro_ids
    assert ev.claims[c.id].label == "insufficient" and "below the proof standard" in ev.claims[c.id].label_reason
    assert not shape_match(inq, ev, "undecided")
    g2, _ = setup_case("contested")
    inq2 = Inquiry(id="contested", question="q", graph=g2)
    assert shape_match(inq2, evaluate(g2), "undecided")


def test_shape_judge_cannot_override_the_contested_requirement():
    g, _ = setup_case("accepted")
    inq = Inquiry(id="accepted", question="q", graph=g)
    judge = FakeLLM({"shape_judge": {"match": True, "why": "not permitted"}})
    result = score_shape(inq, evaluate(g), {"shape": "undecided"}, judge)
    assert not result["shape_match"] and not judge.calls
