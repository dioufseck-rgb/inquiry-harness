"""
Page fetching and text extraction.

    HttpFetcher   httpx + trafilatura for HTML; pypdf for PDF when installed
    FakeFetcher   scripted pages, for tests and dry runs

A fetch never raises: failures come back as a Fetched with empty text and
an error string, so one dead link does not abort a gather.
"""

from __future__ import annotations

import html
import io
import re

from pydantic import BaseModel, Field


class Fetched(BaseModel):
    url: str
    final_url: str = ""
    title: str = ""
    text: str = ""
    content_type: str = ""
    status: int = 0
    error: str = ""
    truncated: bool = Field(default=False, description="True when text was cut at the fetcher's cap.")
    total_chars: int = Field(default=0, description="Length of the extracted text before any cap.")
    links: list[str] = Field(default_factory=list, description="Supplementary-material links found in the page.")


_SUPP_HREF = re.compile(r"""href=["']([^"']+)["']""", re.I)
_SUPP_WORDS = re.compile(r"suppl|MOESM|/esm/|additional[-_ ]?file|appendix", re.I)


def extract_supplementary_links(markup: str, base_url: str, limit: int = 4) -> list[str]:
    """Absolute URLs of supplementary material linked from an article page, in page order."""
    from urllib.parse import urljoin

    out: list[str] = []
    for href in _SUPP_HREF.findall(markup):
        if not _SUPP_WORDS.search(href) or href.startswith(("#", "mailto:", "javascript:")):
            continue
        url = urljoin(base_url, html.unescape(href))
        if url not in out and url != base_url:
            out.append(url)
        if len(out) >= limit:
            break
    return out


class Fetcher:
    name: str = "base"

    def fetch(self, url: str, title: str = "") -> Fetched:  # pragma: no cover
        """`title` is what the search engine reported for the page; a hint for fallbacks, never trusted as content."""
        raise NotImplementedError


_PMC = re.compile(r"https?://(?:www\.)?(?:pmc\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pmc)/articles/(PMC\d+)", re.I)
_PUBMED = re.compile(r"https?://(?:www\.)?pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", re.I)
_DOI_IN_URL = re.compile(r"10\.\d{4,9}/[^\s\"'<>?#]+", re.I)
EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def europepmc_query_for(url: str, title: str = "") -> str | None:
    """
    A Europe PMC query for a PubMed record, a DOI-bearing article URL, or,
    failing both, the article's title as a search engine reported it.
    """
    m = _PUBMED.search(url)
    if m:
        return f"EXT_ID:{m.group(1)} AND SRC:MED"
    m = _DOI_IN_URL.search(url)
    if m:
        return f'DOI:"{m.group(0).rstrip(".,;)")}"'
    words = re.sub(r"[^\w\s-]", " ", title.replace("...", " ")).split()
    if len(words) >= 5:
        return 'TITLE:"' + " ".join(words[:10]) + '"'
    return None


_SCHOLARLY_HOST = re.compile(
    r"nejm\.org|jamanetwork\.com|thelancet\.com|bmj\.com|acpjournals\.org|sciencedirect\.com|springer\.com|"
    r"wiley\.com|nature\.com|cell\.com|ahajournals\.org|oup\.com|tandfonline\.com|sagepub\.com|cambridge\.org|"
    r"pubmed|ncbi\.nlm\.nih\.gov|doi\.org|/doi/", re.I)


def _looks_scholarly(url: str, title: str) -> bool:
    """Only article pages are worth a bibliographic lookup; a blocked news page is not in Europe PMC."""
    return bool(_SCHOLARLY_HOST.search(url) or _DOI_IN_URL.search(url))


def title_matches(hint: str, found: str) -> bool:
    """
    Is the record Europe PMC returned the paper the search engine named? The
    hint's words (truncation marks removed) must nearly all appear in the found
    title, in order; phrase search alone returns near neighbours.
    """
    if not hint.strip():
        return True
    norm = lambda s: re.sub(r"[^a-z0-9\s]", " ", s.lower().replace("...", " ")).split()  # noqa: E731
    h, f = norm(hint), norm(found)
    if not h:
        return True
    i = 0
    for w in f:
        if i < len(h) and w == h[i]:
            i += 1
    return i >= max(4, int(0.9 * len(h)))


def europepmc_record_text(result: dict) -> tuple[str, str]:
    """Title and readable text (title, journal, year, abstract) from one Europe PMC search result."""
    title = html.unescape(re.sub(r"<[^>]+>", "", result.get("title", "") or "")).strip().rstrip(".")
    abstract = html.unescape(re.sub(r"<[^>]+>", " ", result.get("abstractText", "") or ""))
    abstract = re.sub(r"\s+", " ", abstract).strip()
    meta = ", ".join(x for x in [result.get("journalTitle") or (result.get("journalInfo") or {}).get("journal", {}).get("title"),
                                 str(result.get("pubYear") or ""), result.get("authorString", "")] if x)
    text = f"{title}\n{meta}\n\nAbstract\n{abstract}" if abstract else f"{title}\n{meta}"
    return title, text
_ARXIV = re.compile(r"https?://(?:www\.)?arxiv\.org/abs/(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?/?$", re.I)


def rewrite_url(url: str) -> str:
    """
    Route article pages that sit behind bot checks to their open machine-readable forms:
    PubMed Central -> Europe PMC full-text XML; arXiv abstract -> arXiv PDF.
    """
    m = _PMC.search(url)
    if m:
        return f"https://www.ebi.ac.uk/europepmc/webservices/rest/{m.group(1)}/fullTextXML"
    m = _ARXIV.search(url)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}"
    return url


def _strip_tags(markup: str) -> tuple[str, str]:
    """Last-resort extraction when trafilatura is unavailable, and the path for XML."""
    m = re.search(r"<title[^>]*>(.*?)</title>", markup, re.S | re.I) or \
        re.search(r"<article-title[^>]*>(.*?)</article-title>", markup, re.S | re.I)
    title = html.unescape(re.sub(r"<[^>]+>", "", " ".join(m.group(1).split()))) if m else ""
    markup = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", markup, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", markup)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip(), title


_CHALLENGE_MARKERS = (
    "checking your browser", "just a moment", "verify you are human", "enable javascript and cookies",
    "access denied", "attention required", "cloudflare",
)


def looks_like_challenge(title: str, text: str) -> bool:
    """A bot-protection interstitial, not the page. Treated as a non-fetch."""
    head = (title + " " + text[:600]).lower()
    return len(text) < 1500 and any(m in head for m in _CHALLENGE_MARKERS)


class HttpFetcher(Fetcher):
    name = "http"

    # Many publishers return 403 to an unfamiliar agent string; a browser-like one gets the public page.
    DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36 inquiry-harness/0.1")

    def __init__(self, timeout: float = 25.0, max_chars: int = 400_000, user_agent: str | None = None):
        self.timeout = timeout
        self.max_chars = max_chars
        self.user_agent = user_agent or self.DEFAULT_UA

    def fetch(self, url: str, title: str = "") -> Fetched:
        if _PUBMED.search(url):
            # PubMed pages block automated clients; Europe PMC holds the same record
            via = self._europepmc(url)
            if via is not None:
                return via
        target = rewrite_url(url)
        got = self._get(url, target)
        if target != url and got.error:
            # the open-form route failed (not open access, not yet indexed); try the page itself
            direct = self._get(url, url)
            if not direct.error:
                return direct
            got.error = f"{got.error}; direct: {direct.error}"
        if got.error and _looks_scholarly(url, title) and europepmc_query_for(url, title):
            # a paywalled or blocked article page: at least its abstract, and full text when open access
            via = self._europepmc(url, title)
            if via is not None:
                via.error = ""
                return via
        return got

    def _europepmc(self, url: str, title: str = "") -> Fetched | None:
        import httpx

        query = europepmc_query_for(url, title)
        if not query:
            return None
        try:
            r = httpx.get(EUROPEPMC_SEARCH, params={"query": query, "resultType": "core", "format": "json", "pageSize": 1},
                          timeout=self.timeout, headers={"User-Agent": self.user_agent})
            if r.status_code != 200:
                return None
            results = (r.json().get("resultList") or {}).get("result") or []
        except Exception:  # noqa: BLE001 — a lookup failure just means no fallback
            return None
        if not results:
            return None
        rec = results[0]
        found_title, text = europepmc_record_text(rec)
        if query.startswith("TITLE:") and not title_matches(title, found_title):
            return None  # a near neighbour, not the paper the search engine named
        pmcid = rec.get("pmcid")
        if pmcid and (rec.get("isOpenAccess") == "Y" or rec.get("inPMC") == "Y"):
            full = self._get(url, f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")
            if not full.error and len(full.text) > len(text):
                full.title = full.title or found_title
                return full
        return Fetched(url=url, final_url=f"{EUROPEPMC_SEARCH}?query={query}", title=found_title, text=text,
                       content_type="application/json; europepmc", status=200, total_chars=len(text))

    def _get(self, url: str, target: str, retries: int = 3) -> Fetched:
        import time

        import httpx  # imported here so tests can run without the web extra

        for attempt in range(retries + 1):
            try:
                r = httpx.get(target, follow_redirects=True, timeout=self.timeout,
                              headers={"User-Agent": self.user_agent})
            except Exception as e:  # noqa: BLE001 — any transport failure is a non-fetch
                if attempt < retries:
                    time.sleep(1.0 + attempt)
                    continue
                return Fetched(url=url, error=f"{type(e).__name__}: {e}")
            if r.status_code >= 500 and attempt < retries:
                time.sleep(1.0 + attempt)  # some open-data endpoints (Europe PMC) return intermittent 5xx
                continue
            break
        ct = r.headers.get("content-type", "")
        links: list[str] = []
        if r.status_code >= 400:
            return Fetched(url=url, final_url=str(r.url), content_type=ct, status=r.status_code,
                           error=f"HTTP {r.status_code}")
        if "pdf" in ct.lower() or str(r.url).lower().endswith(".pdf"):
            text, title = self._pdf_text(r.content), str(r.url).rsplit("/", 1)[-1]
        elif "xml" in ct.lower() and "html" not in ct.lower():
            text, title = _strip_tags(r.text)
        else:
            text, title = self._html_text(r.text)
            if looks_like_challenge(title, text):
                return Fetched(url=url, final_url=str(r.url), title=title, content_type=ct,
                               status=r.status_code, error="bot-protection interstitial, not the page")
            links = extract_supplementary_links(r.text, str(r.url))
        return Fetched(url=url, final_url=str(r.url), title=title, text=text[: self.max_chars],
                       content_type=ct, status=r.status_code, truncated=len(text) > self.max_chars,
                       total_chars=len(text), links=links)

    @staticmethod
    def _html_text(markup: str) -> tuple[str, str]:
        try:
            import trafilatura
        except ImportError:
            return _strip_tags(markup)
        text = trafilatura.extract(markup, include_comments=False, include_tables=True) or ""
        title = ""
        try:
            meta = trafilatura.extract_metadata(markup)
            title = (meta.title or "") if meta else ""
        except Exception:  # noqa: BLE001 — metadata is a nicety
            pass
        if not text:
            text, fallback_title = _strip_tags(markup)
            title = title or fallback_title
        return text, title

    @staticmethod
    def _pdf_text(data: bytes) -> str:
        try:
            from pypdf import PdfReader
        except ImportError:
            return ""
        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:  # noqa: BLE001 — a corrupt PDF is a non-fetch
            return ""


class FakeFetcher(Fetcher):
    """`pages` maps a URL to its text, or to a Fetched for full control."""

    name = "fake"

    def __init__(self, pages: dict[str, str | Fetched] | None = None):
        self.pages = pages or {}
        self.calls: list[str] = []

    def fetch(self, url: str, title: str = "") -> Fetched:
        self.calls.append(url)
        page = self.pages.get(url)
        if page is None:
            return Fetched(url=url, status=404, error="not in fake fetcher")
        if isinstance(page, Fetched):
            return page
        return Fetched(url=url, final_url=url, title=url.rsplit("/", 1)[-1], text=page, status=200,
                       total_chars=len(page))
