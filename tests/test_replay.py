from inquiry.state import Inquiry
from inquiry.store import InquiryStore
from inquiry.tools.replay import replay_tools


def test_replay_tools_serve_an_earlier_runs_sources(tmp_path):
    store = InquiryStore(tmp_path, "earlier")
    inq = Inquiry(id="earlier", question="q")
    g = inq.graph
    s1 = g.add_source(url="https://a.example/report.pdf", title="Report A", date="2024")
    s1.text_path = store.write_source_text(s1.id, "Table 4. mean turn time 118 / 104")
    s2 = g.add_source(url="https://b.example/note", title="Note B")
    s2.text_path = store.write_source_text(s2.id, "Definitions changed in 2024")
    g.add_source(url="", title="no url, skipped")
    store.save(inq)

    search, fetcher = replay_tools(tmp_path / "earlier")
    hits = search.search("anything at all", k=5)
    assert [h.url for h in hits] == ["https://a.example/report.pdf", "https://b.example/note"]
    assert hits[0].title == "Report A" and hits[0].date == "2024" and hits[0].query == "anything at all"
    got = fetcher.fetch("https://a.example/report.pdf")
    assert got.text.startswith("Table 4") and got.title == "Report A" and got.status == 200
    missing = fetcher.fetch("https://c.example/other")
    assert missing.error and not missing.text
