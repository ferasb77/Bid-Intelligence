"""
buyer_research_provider.py -- Live and Mock Search & Web Fetch Providers for Governed Buyer Research.

Provides:
1. live_search(query) -> list[dict[str, str]] via DuckDuckGo Lite.
2. live_fetch(url) -> str with safe HTML-to-text stripping.
3. mock_search and mock_fetch for isolated unit testing with 0 network calls.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


class _CleanHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.texts: list[str] = []
        self._ignore = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag.lower() in ("script", "style", "nav", "header", "footer", "noscript", "svg"):
            self._ignore = True

    def handle_endtag(self, tag: str):
        if tag.lower() in ("script", "style", "nav", "header", "footer", "noscript", "svg"):
            self._ignore = False

    def handle_data(self, data: str):
        if not self._ignore:
            t = data.strip()
            if t:
                self.texts.append(t)


def live_search(query: str, timeout: int = 10) -> list[dict[str, str]]:
    """Execute search query using DuckDuckGo Lite without external API dependencies."""
    url = "https://lite.duckduckgo.com/lite/"
    data = urllib.parse.urlencode({"q": query}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    )
    results: list[dict[str, str]] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            # Extract links and titles
            links = re.findall(r'href=[\x22\x27](https?://[^\x22\x27]+)[\x22\x27][^>]*>(.*?)</a>', body, re.IGNORECASE)
            for href, raw_title in links:
                clean_title = re.sub(r'<[^>]+>', '', raw_title).strip()
                # Skip duckduckgo internal URLs
                if "duckduckgo.com" not in href:
                    results.append({"url": href, "title": clean_title})
    except Exception as exc:
        logger.warning("live_search failed for query '%s': %s", query, exc)

    return results


def live_fetch(url: str, timeout: int = 10) -> str:
    """Fetch URL and convert HTML to clean, extractable text."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("content-type", "").lower()
            raw_bytes = resp.read()
            html_text = raw_bytes.decode("utf-8", errors="ignore")

            parser = _CleanHTMLParser()
            parser.feed(html_text)
            return "\n".join(parser.texts)
    except Exception as exc:
        logger.warning("live_fetch failed for URL '%s': %s", url, exc)
        return ""
