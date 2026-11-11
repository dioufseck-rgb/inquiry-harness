from pathlib import Path

from inquiry.bench import select, table
from inquiry.metrics import metrics, one_line, shape_match
from inquiry.moves import evaluate_move
from inquiry.state import Inquiry
from inquiry.argument import Credentials


def small_inquiry():
    inq = Inquiry(id="m", question="Did X happen?")
    g = inq.graph
    q = g.add_issue("Did X happen?", question_type="empirical")
    c = g.add_claim("X happened by about 12%", issue_id=q.id)
    n = g.add_claim("X did not happen", issue_id=q.id, kind="null")
    g.set_contraries(c.id, n.id)
    s1 = g.add_source(url="https://a.example/report.pdf", title="Regulator Annual Operational Report 2024", kind="primary")
    s2 = g.add_source(url="https://b.example/mirror.pdf", title="Regulator annual operational report 2024", kind="primary")
    e1 = g.add_evidence("Table 4: 118 vs 104 min", source_id=s1.id, quote="mean turn time 118 / 104", credentials=Credentials(force="strong", relevance="strong", credibility="strong"))
    e2 = g.add_evidence("same table", source_id=s2.id)
    g.add_evidence("unused item", source_id=s1.id)
    a = g.add_argument("document_record", [e1.id], c.id)
    for qid in ("authentic", "accuracy", "reading"):
        g.answer_cq(a.id, qid, "ok", [e1.id])
    x = g.add_attack(a.id, "undercut", premise_ids=[e2.id], origin="critic")
    x.attacks.raises_cq = "definitions"
    g.answer_cq(a.id, "definitions", "same units", [e1.id])  # discharges x
    return inq


def test_metrics_counts_and_gold_matching():
    inq = small_inquiry()
    ev = evaluate_move(inq)
    gold = {"sources": ["Annual Operational Report", "Methodology note"], "facts": ["118 / 104", "Table 4", "5-40 km"]}
    m = metrics(inq, ev, gold, {"shape": "accepted:12%"})
    assert m["sources"] == 2 and m["origins"] == 1 and m["duplicate_sources"] == 1
    assert m["evidence"] == 3 and m["orphans"] == 1
    assert m["supporting_args"] == 1 and m["supporting_in"] == 1
    assert m["attacks"] == 1 and m["attacks_out"] == 0 and m["attacks_discharged"] == 1
    assert m["accepted_claims"] == 1 and m["single_origin_accepts"] == 1
    assert m["main_status"] == {"C1": "in", "C2": "out"}
    assert m["gold_sources_found"] == 1 and m["gold_sources_total"] == 2 and m["gold_sources_missing"] == ["Methodology note"]
    assert m["gold_facts_found"] == 2 and m["gold_facts_missing"] == ["5-40 km"]
    assert m["shape_match"] is True
    line = one_line(m)
    assert line.startswith("metrics ") and "gold_sources=1/2" in line and "main=C1:in,C2:out" in line


def test_shape_match_variants():
    inq = small_inquiry()
    ev = evaluate_move(inq)
    assert shape_match(inq, ev, "undecided") is False
    assert shape_match(inq, ev, "accepted:did not") is False
    assert shape_match(inq, ev, "contested") is False
    assert shape_match(inq, ev, "nonsense") is None
    # remove the only argument: main undecided
    inq.graph.arguments.clear()
    ev = evaluate_move(inq)
    assert shape_match(inq, ev, "undecided") is True


def test_bench_select_and_table(tmp_path):
    qs = [{"id": "ulez", "split": "regression"}, {"id": "a", "split": "held_in"}, {"id": "b", "split": "held_out"}]
    assert [q["id"] for q in select(qs, "held_in", None)] == ["ulez", "a"]
    assert [q["id"] for q in select(qs, "held_out", None)] == ["ulez", "b"]
    assert [q["id"] for q in select(qs, "all", None)] == ["ulez", "a", "b"]
    assert [q["id"] for q in select(qs, "held_in", ["b"])] == ["b"]
    rows = [{"id": "ulez", "sources": 3, "gold_sources_found": 1, "gold_sources_total": 4,
             "gold_facts_found": 2, "gold_facts_total": 5, "shape_match": True, "seconds": 12}]
    t = table(rows)
    assert "1/4" in t and "2/5" in t and t.splitlines()[0].startswith("id")


def test_questions_file_parses_and_has_the_regression_question():
    import yaml
    qs = yaml.safe_load(Path("bench/questions.yaml").read_text(encoding="utf-8"))
    ids = [q["id"] for q in qs]
    assert ids == ["ulez", "energy-pjm", "it-genai-95", "health-aspirin", "geo-redsea", "lead-psychsafety"]
    assert sum(q["split"] == "regression" for q in qs) == 1
    for q in qs:
        assert q["gold"]["sources"] and q["gold"]["facts"] and q["expected"]["shape"]


def test_undecided_empty_and_supported_distinguish_live_main_support():
    inq = Inquiry(id="support", question="Did treatment change the outcome?")
    g = inq.graph
    q = g.add_issue(inq.question, question_type="causal")
    c = g.add_claim("Treatment reduced the outcome", issue_id=q.id)
    for _ in range(3):
        g.add_evidence("A reported comparison", bears_on={c.id: "for"})
    m = metrics(inq, evaluate_move(inq))
    assert m["undecided_empty"] and not m["undecided_supported"] and m["claims_supported_unargued"] == 1
    a = g.add_argument("study_result", ["E1"], c.id)
    from inquiry.argument.schemes import SCHEMES
    for cq in SCHEMES[a.scheme].assumptions():
        g.answer_cq(a.id, cq.id, "Checked", ["E1"])
    ev = evaluate_move(inq)
    assert ev.status(c.id) == "undecided"  # moderate support does not clear the causal standard
    m = metrics(inq, ev)
    assert m["undecided_supported"] and not m["undecided_empty"] and m["main_supporting_in"] == 1
    assert m["claims_supported_unargued"] == 0 and "undecided_supported=True" in one_line(m)
    a.withdrawn = "No longer supports this claim"
    m = metrics(inq, evaluate_move(inq))
    assert m["undecided_empty"] and m["claims_supported_unargued"] == 1


def test_accepted_component_does_not_count_as_a_main_answer_or_trigger_shape_judge():
    from inquiry.bench import score_shape
    from inquiry.llm import FakeLLM
    inq = small_inquiry()
    inq.graph.claim("C1").answers_issue = False
    ev = evaluate_move(inq)
    assert ev.status("C1") == "in"
    m = metrics(inq, ev)
    assert m["undecided_empty"] and not m["undecided_supported"]
    assert m["main_component_supporting_in"] == 1 and not m["main_supporting_in"]
    judge = FakeLLM({})
    score = score_shape(inq, ev, {"shape": "accepted:12%"}, judge)
    assert score["shape_match"] is False and not judge.calls


def test_coverage_uses_offered_evidence_without_mutating_shadow_metadata():
    inq = Inquiry(id="coverage", question="q")
    g = inq.graph
    q = g.add_issue("q")
    c = g.add_claim("c", issue_id=q.id)
    original = g.add_source(url="https://original.example", kind="primary")
    relay = g.add_source(url="https://relay.example", kind="derivative", derived_from=original.id)
    g.add_evidence("Original", source_id=original.id, bears_on={c.id: "for"})
    g.add_evidence("Repeated", source_id=relay.id, bears_on={c.id: "for"})
    g.add_evidence("Context", role="context", bears_on={c.id: "for"})
    before = g.model_dump()
    m = metrics(inq, evaluate_move(inq))
    assert not m["coverage_eligible_claims"] and g.model_dump() == before
