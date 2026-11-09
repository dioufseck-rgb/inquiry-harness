"""
Web search.

    SerperSearch  Google results through the Serper API (SERPER_API_KEY)
    FakeSearch    scripted results, for tests and dry runs
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel


class SearchHit(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""
    date: str = ""
    query: str = ""


class Search:
    name: str = "base"

    def search(self, query: str, k: int = 5) -> list[SearchHit]:  # pragma: no cover
        raise NotImplementedError


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
