"""
One full cycle with FakeLLM (scripted by skill name), FakeSearch and
FakeFetcher. No network, no model calls.
"""

from inquiry.live import Harness, slug_for
from inquiry.llm import FakeLLM
from inquiry.state import Inquiry
from inquiry.store import InquiryStore
from inquiry.tools import FakeFetcher, FakeSearch

QUESTION = "Did the 2024 schedule change reduce fleet turn time?"
U1 = "https://example.org/regulator-2024"
U2 = "https://example.org/regulator-2024-methodology"


def appraise_script(user: str) -> dict:
    """Return evidence keyed on which source is being appraised."""
    if f"\nS1:" in user:
        return {
            "kind": "primary", "publisher": "Regulator", "date": "2024", "competence": "collects returns",
            "incentives": "none apparent",
            "evidence": [{
                "text": "Table 4: mean turn 118 min in 2023 vs 104 min in 2024",
                "kind": "tangible", "quote": "mean turn time 118 / 104", "location": "p. 37",
                "relevance": "strong", "credibility": "strong", "force": "strong",
                "bears_on": {"C1": "for", "C2": "against"},
            }],
        }
    return {
        "kind": "primary", "publisher": "Regulator", "date": "2024",
        "evidence": [{
            "text": "2023 defines turn as arrival-to-departure; 2024 as arrival-to-ready",
            "kind": "tangible", "quote": "arrival-to-ready", "location": "p. 80",
            "relevance": "strong", "credibility": "strong", "force": "strong",
            "bears_on": {"C1": "against"},
        }],
    }


def make_scripts(plan_calls: list[str], overrides: dict | None = None):
    def plan_script(user: str) -> dict:
        plan_calls.append(user)
        return {"tests": [{
            "claim_ids": ["C1", "C2"],
            "observation": "regulator turn-time tables for 2023 and 2024 on one definition",
            "expected_if": {"C1": "a fall of roughly 12%", "C2": "no material change"},
            "diagnosticity": "high",
            "queries": ["regulator annual report 2024 turn time", "turn time methodology 2024"],
        }]}

    proposer = FakeLLM({
        "frame": {
            "restatement": "Did the schedule change cause turn time to fall?",
            "question_type": "causal",
            "scope_in": ["the fleet in question"], "scope_out": ["other operators"],
            "presuppositions": ["a schedule change happened in 2024"],
            "answerhood": "direction and magnitude, measure held constant",
            "standard_override": None,
            "sub_issues": [{"text": "Was turn time measured the same way in both years?",
                            "question_type": "empirical", "answerhood": "a definition for each year"}],
        },
        "hypothesize": {"claims": [
            {"issue_id": "Q1", "text": "Turn time fell by about 12% after the change", "kind": "substantive"},
            {"issue_id": "Q1", "text": "Turn time did not change materially", "kind": "null"},
            {"issue_id": "Q2", "text": "The measure was held constant", "kind": "substantive"},
            {"issue_id": "Q9", "text": "dangling", "kind": "substantive"},
        ]},
        "plan": plan_script,
        "appraise": appraise_script,
        "argue": {"arguments": [{
            "scheme": "document_record", "claim_id": "C1", "premise_ids": ["E1"],
            "cq_answers": {
                "authentic": {"answer": "regulator's own report", "evidence_ids": ["E1"]},
                "accuracy": {"answer": "full operational returns", "evidence_ids": ["E1"]},
                "reading": {"answer": "table states the means directly", "evidence_ids": ["E1"]},
                "definitions": {"answer": "should be ignored: exception"},
            },
        }, {
            "scheme": "no_such_scheme", "claim_id": "C1", "premise_ids": ["E1"],
        }, {
            "scheme": "document_record", "claim_id": "C3", "premise_ids": ["E1"],  # not this issue's claim
        }],
            "unusable": [{"evidence_id": "E2", "reason": "grounds an objection, not a claim"}]},
        "respond": {"responses": [{"attack_id": "A2", "action": "concede", "note": "need the errata"}]},
        "compute": {"computations": []},
        "conclude": {
            "answer": "Not settled: the only support for a fall is undercut by a definition change.",
            "judgements": [
                {"text": "Turn time fell 12%", "confidence": "high", "rests_on": "E1", "claim_ids": ["C1"]},
            ],
            "what_would_change_this": ["a 2023 figure restated on the 2024 definition"],
            "unresolved": ["Q1"],
        },
        **(overrides or {}),
    })
    critic = FakeLLM({
        "critique": {
            "attacks": [
                {"target_id": "A1", "type": "undercut", "premise_ids": ["E2"], "cq_id": "definitions",
                 "note": "the 2023 figure uses a different turn definition"},
                {"target_id": "A1", "type": "undercut", "premise_ids": [], "note": "bare denial"},
                {"target_id": "C1", "type": "undercut", "premise_ids": ["E2"], "note": "wrong type for a claim"},
            ],
            "needed_evidence": ["errata restating the 2023 turn figure on the 2024 definition"],
        },
    })
    return proposer, critic


def make_harness(tmp_path, rounds_plan_calls, overrides=None, **kw):
    proposer, critic = make_scripts(rounds_plan_calls, overrides)
    search = FakeSearch(default=[{"url": U1, "title": "Regulator annual operational report 2024"},
                                 {"url": U2, "title": "Methodology note"},
                                 {"url": "https://example.org/dead", "title": "dead link"},
                                 {"url": "https://mirror.example.org/report.pdf",
                                  "title": "Regulator Annual Operational Report 2024 (PDF)"}])
    filler = " Operational returns were collected from every operator on the standard form." * 6
    fetcher = FakeFetcher({U1: "Table 4. mean turn time 118 / 104 ..." + filler,
                           U2: "Definitions. arrival-to-ready ..." + filler,
                           "https://example.org/dead": "too short",
                           "https://mirror.example.org/report.pdf": "Table 4 again." + filler})
    store = InquiryStore(tmp_path, "t1")
    inq = Inquiry(id="t1", question=QUESTION)
    return Harness(inq, store, proposer, critic, search, fetcher, log=lambda s: None, **kw), store


def test_one_round_builds_graph_and_ledger(tmp_path):
    plan_calls: list[str] = []
    h, store = make_harness(tmp_path, plan_calls)
    inq = h.run(rounds=1)
    g = inq.graph

    # frame and hypothesize
    assert g.main_issue_id == "Q1" and len(g.issues) == 2
    assert g.issue("Q2").parent_id == "Q1"
    assert inq.framing.question_type == "causal"
    main_claims = g.claims_for_issue("Q1")
    assert {c.kind for c in main_claims} == {"substantive", "null"}
    assert g.claim("C1").contrary_ids == ["C2"]
    assert any(c.kind == "null" for c in g.claims_for_issue("Q2"))  # harness added the missing null
    assert g.claim("C1").proof_standard is None and g.standard_for(g.claim("C1")) == "clear_and_convincing"

    # plan and gather
    assert len(inq.tests) == 1 and inq.tests[0].status == "run"
    assert [s.url for s in g.sources] == [U1, U2]  # dead link skipped, no duplicates
    assert all(s.kind == "primary" and s.text_path for s in g.sources)
    assert store.read_source_text("S1").startswith("Table 4")
    assert len(g.evidence) == 2
    assert g.ev("E1").bears_on == {"C1": "for", "C2": "against"}
    assert g.evidence_origin(g.ev("E1")) == g.origin_key(g.source("S1"))

    # argue: called once (only Q1 has evidence bearing on it); one valid argument,
    # bogus scheme and off-issue claim dropped, exception answer ignored, E2 marked unusable
    argue_calls = [u for s, u in h.proposer.calls if s.startswith("# SKILL: argue")]
    assert len(argue_calls) == 1 and "Issue under argument" in argue_calls[0] and "Q1" in argue_calls[0]
    assert "not yet in any argument" in argue_calls[0]
    support = [a for a in g.arguments if not a.is_attack]
    assert len(support) == 1 and support[0].scheme == "document_record"
    a1 = support[0]
    assert a1.cq["authentic"].status == "answered" and a1.cq["definitions"].status == "open"
    assert g.ev("E2").provenance["unusable"] == "grounds an objection, not a claim"
    assert not any(f.code == "orphan_evidence" and f.node_id == "E2" for f in inq.evaluation.flags)
    argue_events = [e for e in store.events() if e["move"] == "argue"]
    assert any("not a claim of the issue" in d for d in argue_events[0]["summary"]["dropped"])

    # critique: grounded undercut recorded, bare denial and wrong-typed attack dropped
    attacks = [a for a in g.arguments if a.is_attack]
    assert len(attacks) == 1
    assert attacks[0].attacks.type == "undercut" and attacks[0].premise_ids == ["E2"]
    assert attacks[0].origin == "critic" and attacks[0].note.startswith("[definitions]")

    # respond: the proposer conceded the standing undercut
    assert "(conceded by proposer: need the errata)" in attacks[0].note
    respond_calls = [u for s, u in h.proposer.calls if s.startswith("# SKILL: respond")]
    assert len(respond_calls) == 1 and "Standing attacks" in respond_calls[0] and "A2" in respond_calls[0]
    assert not any(s.startswith("# SKILL: compute") for s, _ in h.proposer.calls)  # only one numeric item

    # evaluate, reflect, stop
    ev = inq.evaluation
    assert ev is not None
    assert ev.labels[a1.id] == "out" and ev.status("C1") == "undecided"
    assert inq.reflections and "defeated_by" in inq.reflections[-1].directive
    assert inq.stop_assessments[-1].decision == "stop" and "rounds exhausted" in inq.stop_assessments[-1].reason
    assert any(n.startswith("critic needs:") for n in inq.notes)

    # conclude: confidence capped because C1 is not accepted
    assert inq.phase == "concluded" and inq.conclusion is not None
    assert inq.conclusion.judgements[0].confidence == "low"

    # persistence
    assert store.verify_ledger() is True
    moves_run = [e["move"] for e in store.events()]
    assert moves_run == ["frame", "hypothesize", "plan", "gather", "argue", "critique", "respond", "evaluate",
                         "reflect", "stop", "conclude"]
    reloaded = store.load()
    assert reloaded.model_dump() == inq.model_dump()
    assert (store.dir / "report.md").exists() and (store.dir / "chart.mmd").exists()
    report = (store.dir / "report.md").read_text(encoding="utf-8")
    assert "Not settled" in report and "## Argument graph" in report
    assert "A1 (document_record" in report and "attacked by A2 (undercut, in)" in report
    gather = [e for e in store.events() if e["move"] == "gather"][0]["summary"]
    assert any("chars of text" in s for s in gather["skipped"])  # the short page was not kept
    assert any("same document as S1 by title" in s for s in gather["skipped"])  # the mirror was not a second origin
    assert g.validate_refs() == []


def test_second_round_gets_critic_queries_and_stops_on_no_new_evidence(tmp_path):
    plan_calls: list[str] = []
    h, store = make_harness(tmp_path, plan_calls)
    inq = h.run(rounds=3)
    assert len(plan_calls) == 2
    assert "Evidence the critic asked for" not in plan_calls[0]
    assert "errata restating" in plan_calls[1]
    assert "What stands between undecided claims" in plan_calls[1]
    assert len(inq.graph.sources) == 2  # same URLs again: deduplicated, nothing new
    assert inq.round == 2
    assert "no new evidence" in inq.stop_assessments[-1].reason
    assert store.verify_ledger() is True


def test_interactive_human_objection(tmp_path):
    plan_calls: list[str] = []
    answers = iter(["A2 undercut the methodology note covers a different fleet", "bogus", "Q1 rebut nope", ""])
    h, store = make_harness(tmp_path, plan_calls, interactive=True, ask=lambda _: next(answers))
    inq = h.run(rounds=1)
    human = [a for a in inq.graph.arguments if a.origin == "human"]
    assert len(human) == 1 and human[0].attacks.target_id == "A2"
    ev = inq.evaluation
    # the human undercut defeats the critic's undercut, which reinstates A1 and accepts C1
    assert ev.labels["A2"] == "out" and ev.labels["A1"] == "in" and ev.status("C1") == "in"
    assert "human_review" in [e["move"] for e in store.events()]


def test_counter_attack_reinstates_argument_and_accepts_claim(tmp_path):
    plan_calls: list[str] = []
    counter = {"respond": {"responses": [
        {"attack_id": "A2", "action": "counter", "premise_ids": ["E1"],
         "cq_answers": {"definitions": {"answer": "exception, ignored"}},
         "note": "the table itself states both years on one form"},
        {"attack_id": "A1", "action": "counter", "premise_ids": ["E1"]},  # not an attack: dropped
    ]}}
    h, store = make_harness(tmp_path, plan_calls, overrides=counter)
    inq = h.run(rounds=1)
    g, ev = inq.graph, inq.evaluation
    counters = [a for a in g.arguments if a.is_attack and a.origin == "proposer"]
    assert len(counters) == 1 and counters[0].attacks.target_id == "A2" and counters[0].attacks.type == "undercut"
    assert ev.labels[counters[0].id] == "in" and ev.labels["A2"] == "out" and ev.labels["A1"] == "in"
    assert ev.status("C1") == "in"
    assert "answered" in inq.stop_assessments[-1].reason
    assert inq.conclusion.judgements[0].confidence == "high"  # cites an accepted claim: not capped
    respond_event = [e for e in store.events() if e["move"] == "respond"][0]["summary"]
    assert respond_event["countered"] and any("not an attack" in d for d in respond_event["dropped"])


def test_argue_view_prefers_the_origin_over_its_relay():
    from inquiry.moves import argue_view, issue_evidence
    inq = Inquiry(id="x", question="q")
    g = inq.graph
    q = g.add_issue("Q?")
    c = g.add_claim("C", issue_id=q.id)
    report = g.add_source(url="https://tfl.example/report.pdf", title="One Year Report", kind="primary")
    relay = g.add_source(url="https://news.example/story", title="Story", kind="derivative", derived_from=report.id)
    orig = g.add_evidence("report: 4.8% lower", source_id=report.id, bears_on={c.id: "for"})
    rel = g.add_evidence("BBC: 4.8% lower", source_id=relay.id, bears_on={c.id: "for"})
    other = g.add_evidence("BBC: minister quoted", source_id=relay.id, bears_on={c.id: "against"})  # not shadowed
    claim_ids, ids = issue_evidence(g, q.id)
    assert ids == [orig.id, other.id]
    assert rel.provenance["unusable"].startswith(f"relay of {report.id}")
    view = argue_view(inq, q.id)
    assert f"- {orig.id} " in view and f"- {rel.id} " not in view
    # an argument built on the relay anyway is flagged
    from inquiry.argument import evaluate
    a = g.add_argument("document_record", [rel.id], c.id)
    ev = evaluate(g)
    assert any(f.code == "derivative_premise" and f.node_id == a.id for f in ev.flags)


def test_hypothesize_exclusive_groups_decide_who_is_a_rival():
    from inquiry.moves import ClaimProposal, HypothesizeOutput, apply_hypothesize
    inq = Inquiry(id="x", question="q")
    g = inq.graph
    q1 = g.add_issue("What do the evaluations report?")
    q2 = g.add_issue("How big was the effect?")
    out = HypothesizeOutput(claims=[
        ClaimProposal(issue_id=q1.id, text="The official evaluation estimates a reduction"),
        ClaimProposal(issue_id=q1.id, text="The independent study finds no significant effect"),
        ClaimProposal(issue_id=q2.id, text="Large", kind="substantive"),
        ClaimProposal(issue_id=q2.id, text="Small", kind="substantive"),
        ClaimProposal(issue_id=q2.id, text="None", kind="null"),
        ClaimProposal(issue_id=q2.id, text="Unanswerable as posed", kind="deflationary"),
    ], exclusive_groups=[[2, 3], [0, 3]])  # the second group spans issues and is split per issue
    res = apply_hypothesize(inq, out)
    c1, c2, big, small, null, defl = g.claims[:6]
    # (a) descriptive claims in no group: not rivals of each other, both rivals of the harness-added null
    assert c2.id not in c1.contrary_ids and c1.id not in c2.contrary_ids
    harness_null = next(c for c in g.claims_for_issue(q1.id) if c.kind == "null")
    assert harness_null.id in c1.contrary_ids and harness_null.id in c2.contrary_ids
    # (b) a group: pairwise contraries; null and deflationary rivals of every substantive answer
    assert small.id in big.contrary_ids and big.id in small.contrary_ids
    assert {null.id, defl.id} <= set(big.contrary_ids) and {null.id, defl.id} <= set(small.contrary_ids)
    assert defl.id not in null.contrary_ids  # the two non-answers are not rivals of each other
    assert res["exclusive_groups"] == 1 and not any(n.startswith("hypothesize:") for n in inq.notes)
    # fallback when the model gives no groups: all claims of an issue are rivals, and a note records it
    inq2 = Inquiry(id="y", question="q")
    q = inq2.graph.add_issue("Q")
    apply_hypothesize(inq2, HypothesizeOutput(claims=[ClaimProposal(issue_id=q.id, text="A"), ClaimProposal(issue_id=q.id, text="B")]))
    a, b = inq2.graph.claims[:2]
    assert b.id in a.contrary_ids and any(n.startswith("hypothesize: no exclusive_groups") for n in inq2.notes)


def test_respond_discharge_writes_the_answer_and_creates_no_attack():
    from inquiry.moves import AttackProposal, CritiqueOutput, RespondOutput, ResponseProposal, CQAnswerProposal, \
        apply_critique, apply_respond, evaluate_move
    from inquiry.argument import Credentials
    inq = Inquiry(id="x", question="q")
    g = inq.graph
    q = g.add_issue("Did X happen?")
    c = g.add_claim("X happened", issue_id=q.id)
    s = g.add_source(url="https://example.org/report", kind="primary", read_fully=True)
    e1 = g.add_evidence("report says X", source_id=s.id, credentials=Credentials(force="strong"))
    e2 = g.add_evidence("units changed", source_id=s.id)
    e3 = g.add_evidence("appendix: same units both years", source_id=s.id)
    a = g.add_argument("document_record", [e1.id], c.id)
    for qid in ("authentic", "accuracy", "reading"):
        g.answer_cq(a.id, qid, "ok", [e1.id])
    out = apply_critique(inq, CritiqueOutput(attacks=[
        AttackProposal(target_id=a.id, type="undercut", premise_ids=[e2.id], cq_id="definitions")]))
    atk = g.arg(out["attacks"][0])
    assert atk.attacks.raises_cq == "definitions"
    assert evaluate_move(inq).labels[a.id] == "out"
    n_before = len(g.arguments)
    res = apply_respond(inq, RespondOutput(responses=[
        ResponseProposal(attack_id=atk.id, action="discharge",
                         cq_answers={"definitions": CQAnswerProposal(answer="appendix", evidence_ids=[e3.id]),
                                     "currency": CQAnswerProposal(answer="no evidence"),  # ignored: no evidence
                                     "bogus": CQAnswerProposal(answer="x", evidence_ids=[e3.id])}),  # ignored: not a cq
    ]))
    assert res["discharged"] == [atk.id] and len(g.arguments) == n_before
    assert a.cq["definitions"].status == "answered" and a.cq["definitions"].evidence_ids == [e3.id]
    assert "currency" not in a.cq or a.cq["currency"].status == "open"
    assert evaluate_move(inq).labels[a.id] == "in"
    res2 = apply_respond(inq, RespondOutput(responses=[
        ResponseProposal(attack_id=atk.id, action="discharge", cq_answers={"currency": CQAnswerProposal(answer="no evidence")})]))
    assert res2["discharged"] == [] and any("no critical question answered" in d for d in res2["dropped"])


def test_absence_attack_needs_a_fully_read_source():
    from inquiry.moves import AttackProposal, CritiqueOutput, apply_critique
    from inquiry.argument import Credentials
    inq = Inquiry(id="x", question="q")
    g = inq.graph
    q = g.add_issue("Did X happen?")
    c = g.add_claim("X happened", issue_id=q.id)
    s = g.add_source(url="https://example.org/report", kind="primary", read_fully=False)
    e1 = g.add_evidence("report says X", source_id=s.id, credentials=Credentials(force="strong"))
    e2 = g.add_evidence("report gives no interval", source_id=s.id)
    a = g.add_argument("document_record", [e1.id], c.id)
    n_before = len(g.arguments)
    out = apply_critique(inq, CritiqueOutput(attacks=[
        AttackProposal(target_id=a.id, type="undercut", premise_ids=[e2.id], basis="absence", note="no interval")]))
    # not an argument: a request to read the source
    assert out["attacks"] == [] and len(g.arguments) == n_before
    assert out["absence_unverified"] == [f"undercut on {a.id}"]
    assert any(n.startswith(f"read {s.id} fully: no interval") for n in out["needed_evidence"])
    s.read_fully = True
    e3 = g.add_evidence("report has no method section", source_id=s.id)
    out2 = apply_critique(inq, CritiqueOutput(attacks=[
        AttackProposal(target_id=a.id, type="undercut", premise_ids=[e3.id], basis="absence")]))
    assert out2["absence_unverified"] == [] and g.arg(out2["attacks"][0]).cq["grounds"].status == "answered"


def test_primary_sources_are_read_to_the_end_and_others_sampled():
    from inquiry.moves import appraise_full
    calls = []

    def script(user):
        calls.append(user)
        if "PRIMARY" in user:
            kind = "primary"
        elif "FRONTMATTER" in user:
            kind = "unknown" if "part 3 of 3" not in user else "primary"  # settled only by the last part
        else:
            kind = "derivative"
        return {"kind": kind, "evidence": [{"text": f"fact {len(calls)} with 10 min", "bears_on": {"C1": "for"}}]}

    llm = FakeLLM({"appraise": script})
    inq = Inquiry(id="x", question="q")
    g = inq.graph
    q = g.add_issue("Q?")
    g.add_claim("C", issue_id=q.id)
    s1 = g.add_source(url="https://example.org/a")
    res = appraise_full(inq, llm, s1, "PRIMARY " + "x" * 30_000, window=12_000, overlap=500)
    assert res["parts"] == 3 and res["of"] == 3 and s1.read_fully is True and s1.kind == "primary"
    assert len(res["evidence"]) == 3 and "part 2 of 3" in calls[1]
    calls.clear()
    s2 = g.add_source(url="https://example.org/b")
    res2 = appraise_full(inq, llm, s2, "x" * 30_000, window=12_000, overlap=500)
    assert res2["parts"] == 1 and s2.read_fully is False and s2.kind == "derivative" and len(calls) == 1
    # a source still unknown after its front matter is read on, and a later part may settle its kind
    calls.clear()
    s4 = g.add_source(url="https://example.org/d")
    res4 = appraise_full(inq, llm, s4, "FRONTMATTER " * 2_500, window=12_000, overlap=500)
    assert res4["parts"] == 3 and s4.read_fully is True and s4.kind == "primary" and res4["kind"] == "primary"
    # text the fetcher cut is never "read fully", even when every part was appraised
    s3 = g.add_source(url="https://example.org/c")
    res3 = appraise_full(inq, llm, s3, "PRIMARY " + "x" * 20_000, window=12_000, overlap=500, text_complete=False)
    assert res3["parts"] == res3["of"] == 2 and s3.read_fully is False
    # the respond move does not re-present a conceded attack
    from inquiry.moves import CONCEDED_MARK, respond, standing_attacks
    from inquiry.moves import evaluate_move
    c1 = g.claims[0]
    e = g.add_evidence("x", source_id=s1.id)
    a = g.add_argument("document_record", [e.id], c1.id)
    for q in ("authentic", "accuracy", "reading"):
        g.answer_cq(a.id, q, "ok")
    atk = g.add_attack(a.id, "undercut", premise_ids=[g.evidence[0].id], origin="critic")
    ev = evaluate_move(inq)
    assert [x.id for x in standing_attacks(inq, ev)] == [atk.id]
    llm2 = FakeLLM({"respond": {"responses": [{"attack_id": atk.id, "action": "concede", "note": "fair"}]}})
    first = respond(inq, llm2)
    assert first["conceded"] == [atk.id] and atk.note.count(CONCEDED_MARK) == 1
    second = respond(inq, llm2)
    assert second["new"] == 0 and second["conceded"] == [] and len(llm2.calls) == 1
    assert atk.note.count(CONCEDED_MARK) == 1


def test_compute_instrument_writes_model_output_evidence():
    from inquiry.moves import compute, numeric_evidence
    from inquiry.argument import Credentials
    inq = Inquiry(id="x", question="q")
    g = inq.graph
    q = g.add_issue("Did turn time fall?")
    c = g.add_claim("fell by about 12%", issue_id=q.id)
    s = g.add_source(url="https://example.org/r", kind="primary")
    e1 = g.add_evidence("mean turn 118 min in 2023", source_id=s.id, independence_group="reg",
                        credentials=Credentials(credibility="strong", force="moderate"))
    e2 = g.add_evidence("mean turn 104 min in 2024", source_id=s.id, independence_group="reg",
                        credentials=Credentials(credibility="moderate", force="strong"))
    g.add_evidence("the change took effect in 2024", source_id=s.id)  # a year is not a number to compute with
    assert [e.id for e in numeric_evidence(g)] == [e1.id, e2.id]
    llm = FakeLLM({"compute": {"computations": [
        {"name": "relative fall", "expression": "(a - b) / a * 100",
         "variables": {"a": {"value": 118, "evidence_id": "E1", "what": "2023 mean"},
                       "b": {"value": 104, "evidence_id": "E2", "what": "2024 mean"}},
         "text": "The raw fall in mean turn time between 2023 and 2024 is", "unit": "%", "bears_on": {"C1": "for"}},
        {"name": "bad", "expression": "__import__('os').system('x')", "variables": {"a": {"value": 1, "evidence_id": "E1"}}, "text": "t"},
        {"name": "unknown", "expression": "a", "variables": {"a": {"value": 1, "evidence_id": "E99"}}, "text": "t"},
    ]}})
    res = compute(inq, llm)
    assert res["computed"] == ["E4"] and len(res["dropped"]) == 2
    e4 = g.ev("E4")
    assert e4.kind == "model_output" and e4.origin == "instrument" and e4.text.endswith("11.86 %")
    assert e4.provenance["expression"] == "(a - b) / a * 100" and "E1" in e4.provenance["inputs"]
    assert g.evidence_origin(e4) == "reg" and e4.credentials.credibility == "moderate" and e4.credentials.force == "moderate"
    assert e4.bears_on == {"C1": "for"}
    a = g.add_argument("model_output", [e4.id], c.id)
    assert a.scheme == "model_output"


def test_article_urls_are_routed_to_open_forms():
    from inquiry.tools.fetch import rewrite_url
    assert rewrite_url("https://pmc.ncbi.nlm.nih.gov/articles/PMC12545172/") == \
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12545172/fullTextXML"
    assert rewrite_url("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123/") .endswith("PMC123/fullTextXML")
    assert rewrite_url("https://arxiv.org/abs/2401.01234v2") == "https://arxiv.org/pdf/2401.01234"
    assert rewrite_url("https://example.org/page") == "https://example.org/page"


def test_bot_challenge_pages_are_not_pages():
    from inquiry.tools.fetch import looks_like_challenge
    assert looks_like_challenge("", "Checking your browser before accessing pmc.ncbi.nlm.nih.gov ... Click here")
    assert looks_like_challenge("Just a moment...", "Enable JavaScript and cookies to continue")
    assert not looks_like_challenge("ULEZ one year report", "Cloudflare is mentioned once in " + "real content " * 300)
    assert not looks_like_challenge("Air quality trends", "Roadside NO2 fell by 4.8% in outer London " * 10)


def test_slug_is_stable_and_filesystem_safe():
    s = slug_for(QUESTION)
    assert s == slug_for(QUESTION)
    assert s.startswith("did-the-2024-schedule-change") and "/" not in s and " " not in s
