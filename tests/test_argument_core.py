import json

import pytest

from inquiry.argument import (
    ArgumentGraph, Credentials, evaluate, load_bearing, what_would_settle,
    summary, toulmin, wigmore, SCHEMES,
)


def strong():
    return Credentials(relevance="strong", credibility="strong", force="strong")


def moderate():
    return Credentials(relevance="moderate", credibility="moderate", force="moderate")


def discharge(g, aid):
    """Answer every assumption-type CQ of an argument."""
    a = g.arg(aid)
    for q in SCHEMES[a.scheme].assumptions():
        g.answer_cq(aid, q.id, "ok")


def base_graph(question_type="empirical"):
    g = ArgumentGraph()
    q = g.add_issue("Did X happen?", question_type=question_type)
    c = g.add_claim("X happened", issue_id=q.id)
    n = g.add_claim("X did not happen", issue_id=q.id, kind="null")
    g.set_contraries(c.id, n.id)
    s = g.add_source(url="https://example.org/a", title="Record A", kind="primary")
    return g, q, c, n, s


# -- applicability ------------------------------------------------------------

def test_open_assumption_makes_argument_inapplicable():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("record says X", source_id=s.id, credentials=strong())
    a = g.add_argument("document_record", [e.id], c.id)
    ev = evaluate(g)
    assert ev.applicable[a.id] is False
    assert ev.status(c.id) == "undecided"
    assert any(f.code == "inapplicable_argument" and f.node_id == a.id for f in ev.flags)


def test_discharged_assumptions_accept_claim():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("record says X", source_id=s.id, credentials=strong())
    a = g.add_argument("document_record", [e.id], c.id)
    discharge(g, a.id)
    ev = evaluate(g)
    assert ev.labels[a.id] == "in"
    assert ev.status(c.id) == "in"
    assert ev.status(n.id) == "out"
    assert ev.issues[q.id] == [c.id]


def test_defaulted_assumption_weakens_one_level():
    g, q, c, n, s = base_graph(question_type="causal")  # clear_and_convincing
    e = g.add_evidence("record says X", source_id=s.id, credentials=strong())
    a = g.add_argument("document_record", [e.id], c.id)
    for cq in SCHEMES["document_record"].assumptions():
        g.answer_cq(a.id, cq.id, "assumed", defaulted=True)
    ev = evaluate(g)
    assert ev.argument_strength[a.id] == "moderate"
    assert ev.status(c.id) == "undecided"  # strong required


def test_premise_claim_must_be_accepted():
    g, q, c, n, s = base_graph()
    mid = g.add_claim("intermediate fact", issue_id=q.id)
    a = g.add_argument("sign", [mid.id], c.id)
    discharge(g, a.id)
    ev = evaluate(g)
    assert ev.applicable[a.id] is False
    e = g.add_evidence("record establishes intermediate fact", source_id=s.id, credentials=strong())
    b = g.add_argument("document_record", [e.id], mid.id)
    discharge(g, b.id)
    ev = evaluate(g)
    assert ev.status(mid.id) == "in"
    assert ev.applicable[a.id] is True
    assert ev.status(c.id) == "in"
    assert ev.converged


# -- attacks ------------------------------------------------------------------

def test_undercut_without_grounds_is_inapplicable():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("record says X", source_id=s.id, credentials=strong())
    a = g.add_argument("document_record", [e.id], c.id)
    discharge(g, a.id)
    x = g.add_attack(a.id, "undercut", origin="critic")
    ev = evaluate(g)
    assert ev.applicable[x.id] is False
    assert ev.status(c.id) == "in"


def test_undercut_with_grounds_defeats_and_reinstatement_works():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("record says X", source_id=s.id, credentials=strong())
    a = g.add_argument("document_record", [e.id], c.id)
    discharge(g, a.id)
    e2 = g.add_evidence("definitions differ between periods", source_id=s.id, credentials=moderate())
    x = g.add_attack(a.id, "undercut", premise_ids=[e2.id], origin="critic")
    ev = evaluate(g)
    assert ev.labels[x.id] == "in" and ev.labels[a.id] == "out"
    assert ev.status(c.id) == "undecided"
    # answer the attack: undercut the attacker
    e3 = g.add_evidence("errata reconciles the definitions", source_id=s.id, credentials=strong())
    y = g.add_attack(x.id, "undercut", premise_ids=[e3.id])
    ev = evaluate(g)
    assert ev.labels[y.id] == "in" and ev.labels[x.id] == "out" and ev.labels[a.id] == "in"
    assert ev.status(c.id) == "in"


def test_attack_cannot_cite_its_own_target():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("record says X", source_id=s.id, credentials=strong())
    with pytest.raises(ValueError):
        g.add_attack(e.id, "undermine", premise_ids=[e.id])


def test_undermine_cannot_use_the_same_passage_against_itself():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("table says 104", source_id=s.id, location="Table 4, p. 37")
    same = g.add_evidence("table says 104 on a different basis", source_id=s.id, location="table 4, P. 37")
    other = g.add_evidence("methodology note: definitions changed", source_id=s.id, location="p. 80")
    with pytest.raises(ValueError):
        g.add_attack(e.id, "undermine", premise_ids=[same.id])
    x = g.add_attack(e.id, "undermine", premise_ids=[other.id])
    assert x.attacks.type == "undermine"
    # the rule is specific to undermining evidence: an undercut may cite any passage
    a = g.add_argument("document_record", [e.id], c.id)
    y = g.add_attack(a.id, "undercut", premise_ids=[same.id])
    assert y.attacks.target_id == a.id


def test_unusable_evidence_is_not_flagged_orphan_and_load_bearing_names_claim():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("record says X", source_id=s.id, credentials=strong())
    e2 = g.add_evidence("press restatement", source_id=s.id, provenance={"unusable": "repeats E1"})
    a = g.add_argument("document_record", [e.id], c.id)
    discharge(g, a.id)
    ev = evaluate(g)
    orphan_ids = {f.node_id for f in ev.flags if f.code == "orphan_evidence"}
    assert e2.id not in orphan_ids
    lb = load_bearing(g, c.id)
    assert lb and all(x.claim_id == c.id for x in lb)
    assert f"for {c.id}" in summary(g, ev, lb)


def test_an_unsatisfied_answer_is_not_a_discharged_question():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("trial in adults 70+ found more bleeding", source_id=s.id, credentials=strong())
    a = g.add_argument("study_result", [e.id], c.id)
    for qid in ("design", "uncertainty", "reported"):
        g.answer_cq(a.id, qid, "ok", [e.id])
    # the directness check was performed and found the population does not match: inapplicable, with the reason
    g.answer_cq(a.id, "directness", "population is 70+, claim is 60+", [e.id], outcome="unsatisfied")
    ev = evaluate(g)
    assert ev.applicable[a.id] is False and "assumption unsatisfied: directness" in ev.inapplicable_reasons[a.id]
    g.answer_cq(a.id, "directness", "cannot tell from the abstract", [e.id], outcome="unresolved")
    ev = evaluate(g)
    assert ev.applicable[a.id] is False and "assumption unresolved: directness" in ev.inapplicable_reasons[a.id]
    g.answer_cq(a.id, "directness", "same population", [e.id], outcome="satisfied")
    assert evaluate(g).status(c.id) == "in"
    # the proponent's own check of an exception that finds it obtains defeats the argument
    g.answer_cq(a.id, "bias", "the authors concede contamination of the comparison", [e.id], outcome="unsatisfied")
    ev = evaluate(g)
    assert ev.applicable[a.id] is False and "exception obtains: bias" in ev.inapplicable_reasons[a.id]
    # an undercut raising a question is discharged only by a satisfied answer with evidence
    g.answer_cq(a.id, "bias", "no interest shown", [e.id], outcome="satisfied")
    x = g.add_attack(a.id, "undercut", premise_ids=[e.id], origin="critic")
    x.attacks.raises_cq = "consistency"
    g.answer_cq(a.id, "consistency", "other trials disagree", [e.id], outcome="unsatisfied")
    ev = evaluate(g)
    assert ev.applicable[a.id] is False  # the exception obtains by the proponent's own account
    g.answer_cq(a.id, "consistency", "pooled estimates agree", [e.id], outcome="satisfied")
    assert evaluate(g).labels[a.id] == "in"
    # a withdrawn support relation neither supports nor attacks, and keeps its evidence
    a.withdrawn = "outcome mismatch: supports a narrower claim"
    ev = evaluate(g)
    assert ev.applicable[a.id] is False and ev.status(c.id) == "undecided" and g.ev(e.id) is not None


def test_answering_the_raised_question_with_evidence_discharges_an_undercut():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("record says X", source_id=s.id, credentials=strong())
    a = g.add_argument("document_record", [e.id], c.id)
    discharge(g, a.id)
    e2 = g.add_evidence("units differ between periods", source_id=s.id, credentials=moderate())
    x = g.add_attack(a.id, "undercut", premise_ids=[e2.id], origin="critic")
    x.attacks.raises_cq = "definitions"
    ev = evaluate(g)
    assert ev.labels[a.id] == "out" and ev.status(c.id) == "undecided"
    # (b) an answer without evidence does not discharge
    g.answer_cq(a.id, "definitions", "same units, trust me")
    ev = evaluate(g)
    assert ev.labels[a.id] == "out"
    # (a) an answer with evidence does
    e3 = g.add_evidence("appendix states identical units both years", source_id=s.id, credentials=strong())
    g.answer_cq(a.id, "definitions", "appendix gives one definition", [e3.id])
    ev = evaluate(g)
    assert ev.labels[a.id] == "in" and ev.status(c.id) == "in"
    assert ev.labels[x.id] == "in"  # the attack node itself is untouched; it simply no longer defeats


def test_human_attack_needs_no_premises():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("record says X", source_id=s.id, credentials=strong())
    a = g.add_argument("document_record", [e.id], c.id)
    discharge(g, a.id)
    x = g.add_attack(a.id, "undercut", origin="human", note="the record covers a different fleet")
    ev = evaluate(g)
    assert ev.applicable[x.id] is True
    assert ev.status(c.id) == "undecided"


def test_undermine_evidence_defeats_every_argument_using_it():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("record says X", source_id=s.id, credentials=strong())
    a1 = g.add_argument("document_record", [e.id], c.id)
    a2 = g.add_argument("sign", [e.id], c.id)
    discharge(g, a1.id)
    discharge(g, a2.id)
    e2 = g.add_evidence("record was withdrawn by its publisher", source_id=s.id, credentials=strong())
    x = g.add_attack(e.id, "undermine", premise_ids=[e2.id], origin="critic")
    ev = evaluate(g)
    assert ev.labels[a1.id] == "out" and ev.labels[a2.id] == "out"
    assert ev.status(c.id) == "undecided"


def test_rebut_counts_as_con_argument():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("record says X", source_id=s.id, credentials=moderate())
    a = g.add_argument("document_record", [e.id], c.id)
    discharge(g, a.id)
    e2 = g.add_evidence("independent record says not-X", source_id=s.id, credentials=strong(),
                        independence_group="other")
    x = g.add_attack(c.id, "rebut", premise_ids=[e2.id], origin="critic", strength_override="strong")
    ev = evaluate(g)
    d = ev.claims[c.id]
    assert x.id in d.con_ids
    assert d.pro_strength == 2 and d.con_strength == 3
    assert ev.status(c.id) == "undecided"  # preponderance not met, but no contrary accepted


def test_mutual_undercut_leaves_both_undecided():
    g, q, c, n, s = base_graph()
    e1 = g.add_evidence("e1", source_id=s.id)
    e2 = g.add_evidence("e2", source_id=s.id)
    a = g.add_argument("document_record", [e1.id], c.id)
    discharge(g, a.id)
    x = g.add_attack(a.id, "undercut", premise_ids=[e2.id])
    y = g.add_attack(x.id, "undercut", premise_ids=[e1.id])
    z = g.add_attack(y.id, "undercut", premise_ids=[e2.id])
    y.attacks.target_id = z.id  # y and z now attack each other; x is unattacked
    ev = evaluate(g)
    assert ev.labels[y.id] == "undecided" and ev.labels[z.id] == "undecided"
    assert ev.labels[x.id] == "in" and ev.labels[a.id] == "out"
    assert ev.status(c.id) == "undecided"


# -- contraries, corroboration, standards -------------------------------------

def test_contraries_stronger_wins_under_preponderance():
    g, q, c, n, s = base_graph()
    e1 = g.add_evidence("for X", source_id=s.id, credentials=strong())
    e2 = g.add_evidence("against X", source_id=s.id, credentials=moderate())
    a = g.add_argument("document_record", [e1.id], c.id)
    b = g.add_argument("document_record", [e2.id], n.id)
    discharge(g, a.id)
    discharge(g, b.id)
    ev = evaluate(g)
    assert ev.status(c.id) == "in" and ev.status(n.id) == "out"


def test_contraries_equal_strength_both_undecided():
    g, q, c, n, s = base_graph()
    e1 = g.add_evidence("for X", source_id=s.id, credentials=moderate())
    e2 = g.add_evidence("against X", source_id=s.id, credentials=moderate())
    a = g.add_argument("document_record", [e1.id], c.id)
    b = g.add_argument("document_record", [e2.id], n.id)
    discharge(g, a.id)
    discharge(g, b.id)
    ev = evaluate(g)
    assert ev.status(c.id) == "undecided" and ev.status(n.id) == "undecided"
    assert any(f.code == "main_issue_unresolved" for f in ev.flags)


def test_corroboration_raises_pro_strength_and_single_origin_flag():
    g, q, c, n, s = base_graph(question_type="causal")
    e1 = g.add_evidence("source A", source_id=s.id, credentials=moderate(), independence_group="A")
    e2 = g.add_evidence("source A again", source_id=s.id, credentials=moderate(), independence_group="A")
    a1 = g.add_argument("document_record", [e1.id], c.id)
    a2 = g.add_argument("document_record", [e2.id], c.id)
    discharge(g, a1.id)
    discharge(g, a2.id)
    ev = evaluate(g)
    assert ev.claims[c.id].corroborated is False
    assert ev.status(c.id) == "undecided"  # moderate cannot clear clear_and_convincing
    e2.independence_group = "B"
    ev = evaluate(g)
    assert ev.claims[c.id].corroborated is True
    assert ev.claims[c.id].pro_strength == 3
    assert ev.status(c.id) == "in"
    assert not any(f.code == "single_origin" for f in ev.flags)


def test_derivative_source_without_origin_cannot_corroborate():
    g, q, c, n, s = base_graph(question_type="causal")
    s2 = g.add_source(url="https://example.org/news", kind="derivative")  # no derived_from
    e1 = g.add_evidence("report: X", source_id=s.id, credentials=moderate())
    e2 = g.add_evidence("news says X", source_id=s2.id, credentials=moderate())
    a1 = g.add_argument("document_record", [e1.id], c.id)
    a2 = g.add_argument("document_record", [e2.id], c.id)
    discharge(g, a1.id)
    discharge(g, a2.id)
    ev = evaluate(g)
    assert ev.claims[c.id].corroborated is False and ev.status(c.id) == "undecided"
    s2.kind = "secondary"
    ev = evaluate(g)
    assert ev.claims[c.id].corroborated is True and ev.status(c.id) == "in"


def test_origin_key_prefers_doi_then_derivation_then_title_then_publisher():
    g = ArgumentGraph()
    paper = g.add_source(url="https://www.nature.com/articles/s44407-025-00030-9", title="Further improvement", publisher="Nature")
    mirror = g.add_source(url="https://pmc.ncbi.nlm.nih.gov/articles/PMC1/", title="Further improvement in London's air quality demands more")
    assert g.origin_key(paper).startswith("title:") or g.origin_key(paper).startswith("publisher:")
    doi = g.add_source(url="https://doi.org/10.1038/s44407-025-00030-9", title="x")
    assert g.origin_key(doi) == "doi:10.1038/s44407-025-00030-9"
    relay = g.add_source(url="https://news.example/x", title="Short", kind="derivative", derived_from=doi.id)
    assert g.origin_key(relay) == g.origin_key(doi)
    report = g.add_source(url="https://a.example/r.pdf", title="London-wide ULEZ One Year Report", publisher="TfL")
    report2 = g.add_source(url="https://b.example/r.pdf", title="London-wide ULEZ one year report")
    assert g.origin_key(report) == g.origin_key(report2) == "title:londonwideulezoneyearreport"
    brief = g.add_source(url="https://c.example/", title="Brief", publisher="TfL")
    assert g.origin_key(brief) == "publisher:tfl"
    bare = g.add_source(url="https://d.example/")
    assert g.origin_key(bare) == f"source:{bare.id}"
    assert g.origin_key(mirror).startswith("title:")


def test_corroboration_needs_two_arguments_with_disjoint_origins():
    g, q, c, n, s = base_graph(question_type="causal")
    s.title, s.publisher = "Report A", "Regulator"
    s2 = g.add_source(url="https://example.org/b", title="Methodology note B", publisher="Regulator", kind="primary")
    e1 = g.add_evidence("table", source_id=s.id, credentials=moderate())
    e2 = g.add_evidence("method", source_id=s2.id, credentials=moderate())
    # (a) one argument spanning two documents of one publisher is not corroboration
    a = g.add_argument("document_record", [e1.id, e2.id], c.id)
    discharge(g, a.id)
    ev = evaluate(g)
    assert ev.claims[c.id].corroborated is False and ev.status(c.id) == "undecided"
    # (b) two arguments from two publishers are
    s3 = g.add_source(url="https://example.org/c", title="Independent study C", publisher="University", kind="primary")
    e3 = g.add_evidence("finding", source_id=s3.id, credentials=moderate())
    b = g.add_argument("study_result", [e3.id], c.id)
    discharge(g, b.id)
    ev = evaluate(g)
    assert ev.claims[c.id].corroborated is True and ev.status(c.id) == "in"
    assert not any(f.code == "single_origin" for f in ev.flags)


def test_same_document_at_two_hosts_is_flagged_and_does_not_corroborate():
    g, q, c, n, s = base_graph()
    s.title = "Further improvement in London's air quality demands more"
    s2 = g.add_source(url="https://pmc.example/PMC1/", title="Further improvement in London's air quality demands more", kind="primary")
    e1 = g.add_evidence("finding", source_id=s.id, credentials=moderate())
    e2 = g.add_evidence("same finding", source_id=s2.id, credentials=moderate())
    a = g.add_argument("document_record", [e1.id], c.id)
    b = g.add_argument("document_record", [e2.id], c.id)
    discharge(g, a.id)
    discharge(g, b.id)
    ev = evaluate(g)
    assert ev.claims[c.id].corroborated is False
    dup = [f for f in ev.flags if f.code == "duplicate_source"]
    assert len(dup) == 1 and dup[0].node_id == f"{s.id},{s2.id}"
    assert any(f.code == "single_origin" and f.node_id == c.id for f in ev.flags)
    # (d) marking one as derived from the other removes the duplicate flag and keeps one origin
    s2.kind, s2.derived_from = "derivative", s.id
    ev = evaluate(g)
    assert not any(f.code == "duplicate_source" for f in ev.flags)
    assert g.evidence_origin(e2) == g.evidence_origin(e1)
    assert ev.claims[c.id].corroborated is False


def test_study_result_scheme_asks_the_grade_questions():
    sch = SCHEMES["study_result"]
    assert {q.id for q in sch.assumptions()} == {"design", "directness", "uncertainty", "reported"}
    assert {q.id for q in sch.exceptions()} == {"bias", "consistency", "precision"}
    g, q, c, n, s = base_graph(question_type="causal")
    e = g.add_evidence("study found no detectable effect", source_id=s.id, credentials=strong())
    a = g.add_argument("study_result", [e.id], n.id)
    assert evaluate(g).applicable[a.id] is False  # design and directness are open
    discharge(g, a.id)
    assert evaluate(g).status(n.id) == "in"


def test_safe_eval_is_arithmetic_only():
    from inquiry.tools.compute import ComputeError, safe_eval
    assert safe_eval("(a - b) / a * 100", {"a": 118, "b": 104}) == pytest.approx(11.864, rel=1e-3)
    assert safe_eval("max(abs(-x), 2) ** 2", {"x": 3}) == 9
    for bad in ["__import__('os')", "a.real", "x if 1 else 2", "[1][0]", "open('f')", "a + c"]:
        with pytest.raises(ComputeError):
            safe_eval(bad, {"a": 1, "x": 2})
    with pytest.raises(ComputeError):
        safe_eval("a / 0", {"a": 1})


def test_beyond_reasonable_doubt_requires_no_surviving_con():
    g, q, c, n, s = base_graph()
    c.proof_standard = "beyond_reasonable_doubt"
    e1 = g.add_evidence("for X", source_id=s.id, credentials=strong())
    a = g.add_argument("document_record", [e1.id], c.id)
    discharge(g, a.id)
    assert evaluate(g).status(c.id) == "in"
    e2 = g.add_evidence("minor contrary indication", source_id=s.id, credentials=Credentials(force="weak"))
    b = g.add_argument("sign", [e2.id], n.id)
    discharge(g, b.id)
    assert evaluate(g).status(c.id) == "undecided"


def test_credence_mismatch_flag():
    g, q, c, n, s = base_graph()
    c.credence = 0.9
    ev = evaluate(g)
    assert any(f.code == "credence_status_mismatch" and f.node_id == c.id for f in ev.flags)


# -- load-bearing, serialization, rendering -----------------------------------

def test_load_bearing_finds_evidence_and_answers():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("record says X", source_id=s.id, credentials=strong())
    a = g.add_argument("document_record", [e.id], c.id)
    discharge(g, a.id)
    lb = load_bearing(g, c.id)
    kinds = {(x.kind, x.node_id) for x in lb}
    assert ("evidence", e.id) in kinds
    assert ("argument", a.id) in kinds
    assert any(k == "cq_answer" for k, _ in kinds)
    assert all(x.effect == "undecided" for x in lb)


def test_what_would_settle_names_the_obstacle():
    g, q, c, n, s = base_graph(question_type="causal")
    assert {x.kind for x in what_would_settle(g, c.id)} == {"no_argument"}
    e = g.add_evidence("record says X", source_id=s.id, credentials=moderate())
    a = g.add_argument("document_record", [e.id], c.id)
    kinds = {x.kind for x in what_would_settle(g, c.id)}
    assert "open_assumption" in kinds and "no_argument" not in kinds
    discharge(g, a.id)
    kinds = {x.kind for x in what_would_settle(g, c.id)}
    assert kinds == {"strength_short", "corroboration"}  # moderate on one origin vs clear_and_convincing
    e2 = g.add_evidence("withdrawn", source_id=s.id, credentials=strong())
    x = g.add_attack(a.id, "undercut", premise_ids=[e2.id])
    settlers = what_would_settle(g, c.id)
    assert any(z.kind == "defeated_by" and z.node_id == x.id for z in settlers)
    c.proof_standard = "scintilla"
    g.arguments.remove(x)
    assert what_would_settle(g, c.id) == []


def test_graph_round_trips_through_json():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("record says X", source_id=s.id, credentials=strong())
    a = g.add_argument("document_record", [e.id], c.id)
    discharge(g, a.id)
    g2 = ArgumentGraph.model_validate_json(g.model_dump_json())
    assert g2.model_dump() == g.model_dump()
    assert evaluate(g2).status(c.id) == "in"
    assert g2.validate_refs() == []


def test_renderers_produce_text():
    g, q, c, n, s = base_graph()
    e = g.add_evidence("record says X", source_id=s.id, quote="X: yes", credentials=strong())
    a = g.add_argument("document_record", [e.id], c.id)
    discharge(g, a.id)
    ev = evaluate(g)
    t = toulmin(g, a.id, ev)
    assert "Warrant" in t and e.id in t and "X: yes" in t
    w = wigmore(g, ev)
    assert w.startswith("flowchart BT") and a.id in w and c.id in w
    s_md = summary(g, ev, load_bearing(g, c.id))
    assert "## Issues" in s_md and "Load-bearing" in s_md


def test_every_scheme_has_at_least_one_assumption_and_sep_grounding():
    for name, sch in SCHEMES.items():
        assert sch.assumptions(), name
        assert sch.sep, name
        for q in sch.critical_questions:
            assert q.sep or name == "attack", (name, q.id)
