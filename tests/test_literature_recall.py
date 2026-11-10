from types import SimpleNamespace

from inquiry import moves
from inquiry.state import Inquiry
from inquiry.tools.search import EuropePMCSearch, FakeSearch, named_study_queries
from test_live_cycle import U1, make_harness


def test_europepmc_records_keep_doi_and_deduplicate_hosts(monkeypatch):
    import httpx

    calls = []
    records = [
        {"title": "Primary trial", "doi": "10.1000/TRIAL", "pmcid": "PMC123", "abstractText": "<p>Evidence &amp; outcomes</p>", "firstPublicationDate": "2018-09-16"},
        {"title": "Same paper", "doi": "10.1000/trial", "id": "456", "source": "MED"},
        {"title": "Another paper", "id": "789", "source": "MED"},
    ]
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"resultList": {"result": records}})
    monkeypatch.setattr(httpx, "get", get)
    hits = EuropePMCSearch().search("aspirin", k=5)
    assert len(hits) == 2 and hits[0].doi == "10.1000/trial"
    assert hits[0].url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/"
    assert "Evidence & outcomes" in hits[0].snippet
    assert calls[0][1]["params"] == {"query": "aspirin sort_cited:y", "format": "json", "resultType": "core", "pageSize": 5}


def test_recall_runs_four_queries_per_issue_once_and_merges_dois(tmp_path):
    h, _ = make_harness(tmp_path, [])
    moves.apply_frame(h.inq, moves.FrameOutput(restatement="q", search_topic="aspirin primary prevention",
                      sub_issues=[moves.SubIssue(text="Trial outcomes?", search_topic="aspirin trial outcomes")]))
    h.inq.round = 1
    h.literature_search = FakeSearch(default=[{"url": U1, "title": "Trial", "doi": "10.1/ABC"}])
    result = h.discover_literature()
    assert len(result["queries"]) == 8 and len(h.inq.candidates) == 1
    assert h.inq.candidates[0].issue_ids == ["Q1", "Q2"]
    assert h.inq.candidates[0].tags == ["recall"]
    assert all("FIRST_PDATE:[" in q for q in result["queries"])
    assert any("aspirin AND primary AND prevention" in q and "randomised OR randomized" in q for q in result["queries"])
    assert h.discover_literature()["queries"] == []
    named = h.discover_literature(["Read the ASPREE cardiovascular outcomes paper"])
    assert named["queries"] == ["ASPREE"]
    assert h.inq.candidates[0].tags == ["needed_evidence", "recall"]
    assert not h.discover_literature(["Read the ASPREE cardiovascular outcomes paper"])["queries"]


def test_plan_can_choose_a_recall_candidate_without_web_queries(tmp_path):
    def plan(user):
        assert "R1 [recall]" in user and "discovered, not yet evidence" in user
        return {"tests": [{"claim_ids": ["C1"], "observation": "Read the primary trial", "candidate_ids": ["R1"]}]}
    h, store = make_harness(tmp_path, [], overrides={"plan": plan})
    h.literature_search = FakeSearch(default=[{"url": U1, "title": "Primary trial", "doi": "10.1/trial"}])
    inq = h.run(rounds=1)
    assert not h.search.calls
    assert inq.graph.sources[0].url == U1 and inq.graph.evidence
    assert inq.candidates[0].status == "read"
    names = [e["move"] for e in store.events()]
    assert names.index("recall") < names.index("plan") < names.index("gather")
    assert store.verify_ledger()


def test_named_queries_prefer_a_title_or_study_acronym():
    assert named_study_queries('Read "Aspirin and cardiovascular outcomes"') == ["Aspirin and cardiovascular outcomes"]
    assert named_study_queries("Retrieve ARRIVE and ASCEND trial reports") == ["ARRIVE", "ASCEND"]
    assert named_study_queries("a population-specific event estimate") == ["a population-specific event estimate"]


def test_named_request_goes_to_literature_before_web_search(tmp_path):
    timeline = []
    class TracedSearch(FakeSearch):
        def __init__(self, label, **kw):
            super().__init__(**kw)
            self.label = label
        def search(self, query, k=5):
            timeline.append((self.label, query))
            return super().search(query, k)

    h, store = make_harness(tmp_path, [])
    h.search = TracedSearch("web", default=h.search.default)
    h.literature_search = TracedSearch("literature")
    h.critic.script["critique"]["needed_evidence"] = ["Read the ASPREE cardiovascular outcomes paper"]
    h.run(rounds=2)
    lit_index = timeline.index(("literature", "ASPREE"))
    web_index = timeline.index(("web", "ASPREE"))
    assert lit_index < web_index
    assert any("ASPREE" in t.queries for t in h.inq.tests)
    assert store.verify_ledger()
