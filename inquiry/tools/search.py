"""
Web search.

    SerperSearch  Google results through the Serper API (SERPER_API_KEY)
    FakeSearch    scripted results, for tests and dry runs
"""

from __future__ import annotations

import os
import re
import html
from typing import Any

from pydantic import BaseModel, Field


class SearchHit(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""
    date: str = ""
    query: str = ""
    doi: str = ""
    tags: list[str] = Field(default_factory=list)


class Search:
    name: str = "base"

    def search(self, query: str, k: int = 5) -> list[SearchHit]:  # pragma: no cover
        raise NotImplementedError


class EuropePMCSearch(Search):
    """Bibliographic discovery; the normal fetcher reads the selected records."""

    name = "europepmc"
    endpoint = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout

    def search(self, query: str, k: int = 5) -> list[SearchHit]:
        import httpx

        # Explicit ranking is important for recall: a five-hit date-ranked
        # result page hides the established trials behind recent follow-ups.
        api_query = query if re.search(r"sort_(?:cited|date):", query) else query + " sort_cited:y"
        response = httpx.get(self.endpoint, params={"query": api_query, "format": "json", "resultType": "core", "pageSize": k},
                             timeout=self.timeout)
        response.raise_for_status()
        hits = []
        seen = set()
        for record in response.json().get("resultList", {}).get("result", []):
            doi = record.get("doi", "").strip().lower()
            pmcid, record_id = record.get("pmcid", ""), record.get("id", "")
            if pmcid:
                url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
            elif doi:
                url = f"https://doi.org/{doi}"
            elif record.get("source") == "MED" and record_id:
                url = f"https://pubmed.ncbi.nlm.nih.gov/{record_id}/"
            else:
                continue
            key = doi or url
            if key in seen:
                continue
            seen.add(key)
            abstract = html.unescape(re.sub(r"<[^>]*>", " ", record.get("abstractText", "")))
            hits.append(SearchHit(url=url, title=html.unescape(record.get("title", "")), snippet=abstract[:1600],
                                  date=record.get("firstPublicationDate", record.get("pubYear", "")), query=query,
                                  doi=doi))
            if len(hits) >= k:
                break
        return hits


def recall_query(topic: str, kind: str, floor: str, today: str) -> str:
    terms = " AND ".join(dict.fromkeys(re.findall(r"[a-z0-9]+", topic.lower())))
    methods = {
        "randomised trial": "((randomised OR randomized) AND trial)",
        "meta-analysis": '"meta-analysis"',
        "systematic review": "(systematic AND review)",
        "guideline recommendation": "(guideline AND recommendation)",
    }
    return f"TITLE_ABS:({terms}) AND {methods[kind]} AND FIRST_PDATE:[{floor} TO {today}] sort_cited:y"


def named_study_queries(request: str) -> list[str]:
    """Try explicit titles and study acronyms before the full evidence request."""
    titles = re.findall(r'["“]([^"”]{5,})["”]', request)
    names = re.findall(r"\b[A-Z][A-Z0-9-]{3,}\b", request)
    return list(dict.fromkeys(titles + names)) or [request]


class SerperSearch(Search):
    name = "serper"
    endpoint = "https://google.serper.dev/search"

    def __init__(self, api_key: str | None = None, timeout: float = 20.0):
        self.api_key = api_key or os.environ.get("SERPER_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("SERPER_API_KEY is not set")
        self.timeout = timeout

    def search(self, query: str, k: int = 5) -> list[SearchHit]:
        import httpx  # imported here so tests can run without the web extra

        r = httpx.post(
            self.endpoint,
            headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
            json={"q": query, "num": k},
            timeout=self.timeout,
        )
        r.raise_for_status()
        hits: list[SearchHit] = []
        for o in r.json().get("organic", []):
            if not o.get("link"):
                continue
            hits.append(SearchHit(url=o["link"], title=o.get("title", ""), snippet=o.get("snippet", ""),
                                  date=o.get("date", ""), query=query))
            if len(hits) >= k:
                break
        return hits


class FakeSearch(Search):
    """
    `results` maps a query to its hits; `default` is returned for any other
    query. Hits may be SearchHit objects or dicts.
    """

    name = "fake"

    def __init__(self, results: dict[str, list[Any]] | None = None, default: list[Any] | None = None):
        self.results = results or {}
        self.default = default or []
        self.calls: list[str] = []

    def search(self, query: str, k: int = 5) -> list[SearchHit]:
        self.calls.append(query)
        raw = self.results.get(query, self.default)
        hits = [h if isinstance(h, SearchHit) else SearchHit(**h) for h in raw]
        for h in hits:
            h.query = h.query or query
        return hits[:k]
