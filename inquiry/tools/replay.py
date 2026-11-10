"""
Fixed-evidence replay.

    ReplaySearch, ReplayFetcher = replay_tools("runs/health-aspirin-20261110")

Search returns the URLs of the sources an earlier run held, for any query, and
fetch serves their stored text. The cycle then runs on exactly the evidence
packet that run saw, so two versions of the harness, or the harness and a
plain baseline, can be compared with retrieval held fixed.
"""

from __future__ import annotations

from pathlib import Path

from ..store import InquiryStore
from .fetch import Fetched, Fetcher
from .search import Search, SearchHit


class ReplaySearch(Search):
    name = "replay"

    def __init__(self, hits: list[SearchHit]):
        self.hits = hits
        self.calls: list[str] = []

    def search(self, query: str, k: int = 5) -> list[SearchHit]:
        """Every query returns the whole packet; gather's URL de-duplication keeps each source once."""
        self.calls.append(query)
        return [SearchHit(url=h.url, title=h.title, snippet=h.snippet, date=h.date, query=query) for h in self.hits]


class ReplayFetcher(Fetcher):
    name = "replay"

    def __init__(self, pages: dict[str, tuple[str, str]]):
        self.pages = pages  # url -> (title, text)
        self.calls: list[str] = []

    def fetch(self, url: str, title: str = "") -> Fetched:
        self.calls.append(url)
        if url not in self.pages:
            return Fetched(url=url, status=404, error="not in the replay packet")
        t, text = self.pages[url]
        return Fetched(url=url, final_url=url, title=t or title, text=text, status=200, total_chars=len(text))


def replay_tools(run_dir: str | Path) -> tuple[ReplaySearch, ReplayFetcher]:
    run_dir = Path(run_dir)
    store = InquiryStore(run_dir.parent, run_dir.name)
    inq = store.load()
    hits: list[SearchHit] = []
    pages: dict[str, tuple[str, str]] = {}
    for s in inq.graph.sources:
        text = store.read_source_text(s.id)
        if not s.url or not text:
            continue
        hits.append(SearchHit(url=s.url, title=s.title, date=s.date))
        pages[s.url] = (s.title, text)
    return ReplaySearch(hits), ReplayFetcher(pages)
