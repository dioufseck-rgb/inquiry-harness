from inquiry.argument.graph import ArgumentGraph, Credentials, Scope
from inquiry.argument.evaluate import evaluate
from inquiry.argument.schemes import SCHEMES


def component_graph():
    g = ArgumentGraph()
    main = g.add_issue("Net harm in adults 60+?", question_type="causal",
                       scope=Scope(population="adults 60+", outcome="net harm", period="5 years"))
    components = []
    for outcome in ("bleeding", "mortality", "nonfatal events"):
        scope = Scope(population="adults 70+", outcome=outcome, period="5 years")
        sub = g.add_issue(outcome, parent_id=main.id, scope=scope)
        c = g.add_claim(outcome + " changed", issue_id=sub.id)
        e = g.add_evidence(outcome, credentials=Credentials(relevance="strong", credibility="strong", force="strong"))
        a = g.add_argument("document_record", [e.id], c.id)
        for cq in SCHEMES[a.scheme].assumptions():
            g.answer_cq(a.id, cq.id, "Checked", [e.id])
        components.append(c)
    return g, main, components


def composed(g, main, components, population="adults 70+"):
    c = g.add_claim("Net harm increased", issue_id=main.id, created_by_move="compose",
                    scope=Scope(population=population, outcome="net harm", period="5 years", relation="increases"))
    a = g.add_argument("composition", [c.id for c in components], c.id)
    for qid in ("commensurable", "direction", "same_scope"):
        g.answer_cq(a.id, qid, "Model says satisfied", [components[0].id])
    return c, a


def test_same_scope_composition_is_accepted_at_weakest_premise_strength():
    g, main, components = component_graph()
    c, a = composed(g, main, components)
    ev = evaluate(g)
    assert a.cq["same_scope"].outcome == "satisfied" and a.cq["same_scope"].answer_move == "evaluate"
    assert ev.applicable[a.id] and ev.status(c.id) == "in" and ev.argument_strength[a.id] == "strong"
    assert not c.answers_issue
    g.ev("E2").credentials.force = "moderate"
    ev = evaluate(g)
    assert ev.argument_strength[a.id] == "moderate" and ev.status(c.id) != "in"


def test_same_components_cannot_extend_to_60_plus_even_if_model_answers_cq():
    g, main, components = component_graph()
    c, a = composed(g, main, components, "adults 60+")
    ev = evaluate(g)
    assert a.cq["same_scope"].outcome == "unsatisfied"
    assert not ev.applicable[a.id] and ev.status(c.id) != "in"


def test_composition_requires_accepted_premises_and_inherits_origins():
    from inquiry.argument.evaluate import argument_origins
    g, main, components = component_graph()
    c, a = composed(g, main, components)
    assert len(argument_origins(g, a)) == 3
    g.arguments_for(components[0].id)[0].withdrawn = "failed review"
    ev = evaluate(g)
    assert not ev.applicable[a.id] and ev.status(c.id) != "in"
