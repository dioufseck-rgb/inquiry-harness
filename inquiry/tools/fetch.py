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

    def fetch(self, url: str) -> Fetched:  # pragma: no cover
        raise NotImplementedError


_PMC = re.compile(r"https?://(?:www\.)?(?:pmc\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pmc)/articles/(PMC\d+)", re.I)
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

    def fetch(self, url: str) -> Fetched:
        target = rewrite_url(url)
        got = self._get(url, target)
        if target != url and got.error:
            # the open-form route failed (not open access, not yet indexed); try the page itself
            direct = self._get(url, url)
            if not direct.error:
                return direct
            got.error = f"{got.error}; direct: {direct.error}"
        return got

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

    def fetch(self, url: str) -> Fetched:
        self.calls.append(url)
        page = self.pages.get(url)
        if page is None:
            return Fetched(url=url, status=404, error="not in fake fetcher")
        if isinstance(page, Fetched):
            return page
        return Fetched(url=url, final_url=url, title=url.rsplit("/", 1)[-1], text=page, status=200,
                       total_chars=len(page))
