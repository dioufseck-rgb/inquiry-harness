"""Web tools: search and fetch. Each has a real implementation and a fake for tests."""

from .fetch import Fetched, Fetcher, FakeFetcher, HttpFetcher  # noqa: F401
from .search import FakeSearch, Search, SearchHit, SerperSearch  # noqa: F401
