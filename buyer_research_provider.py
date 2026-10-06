"""
buyer_research_provider.py -- Live and Mock Search & Web Fetch Providers for Governed Buyer Research.

Implements Phase E & F:
1. Anthropic server-side tools adapter (WebSearchTool20250305Param / WebFetchTool20250910Param).
2. Direct HTTP search/fetch adapter with strict governance safeguards:
   - Enforce timeouts (default 10s).
   - Maximum response size (2 MB) to prevent denial of service.
   - Redirects bounded (max 5) and re-validated at each hop.
   - HTTP/HTTPS only; reject arbitrary schemes (file://, ftp://, gopher://, etc.).
   - Reject localhost, loopback, private, reserved, link-local IP addresses (SSRF prevention).
   - Reject credentials embedded in URLs (e.g. http://user:pass@host).
   - Explicit user-agent header.
   - Structured error classification.
   - Discovery-only search results; verbatim extracts verified only against actual fetched page content.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urljoin
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

USER_AGENT = "Bid-Intelligence-BuyerResearch/1.0 (+https://bid-intelligence.ca; verification-bot)"
MAX_FETCH_BYTES = 2 * 1024 * 1024  # 2 Megabytes
MAX_REDIRECTS = 5
DEFAULT_TIMEOUT = 10


class ProviderSecurityError(ValueError):
    """Raised when a URL violates network security or SSRF constraints."""


class ProviderNetworkError(IOError):
    """Raised when an external request encounters a network error."""


def validate_network_url(url: str) -> str:
    """
    Validate URL safety:
    1. HTTP/HTTPS only.
    2. No credentials (user:pass).
    3. Resolves and rejects private, loopback, link-local, and reserved IP ranges (SSRF defense).
    """
    if not url or not isinstance(url, str):
        raise ProviderSecurityError("URL must be a non-empty string.")

    cleaned = url.strip()
    parsed = urlsplit(cleaned)

    if parsed.scheme.lower() not in ("http", "https"):
        raise ProviderSecurityError(f"Disallowed scheme '{parsed.scheme}': only HTTP/HTTPS permitted.")

    if parsed.username or parsed.password:
        raise ProviderSecurityError("URLs with embedded credentials are prohibited.")

    hostname = parsed.hostname
    if not hostname:
        raise ProviderSecurityError("URL has no valid hostname.")

    # Reject obvious localhost strings immediately
    if hostname.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise ProviderSecurityError(f"Prohibited host '{hostname}' (loopback/localhost).")

    # Resolve IP address to check for private / reserved ranges
    try:
        addr_info = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme.lower() == "https" else 80))
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise ProviderSecurityError(f"Resolved IP {ip_str} for host '{hostname}' is in a private/reserved address block.")
    except socket.gaierror as exc:
        raise ProviderNetworkError(f"DNS resolution failed for host '{hostname}': {exc}") from exc

    return cleaned


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


# ---------------------------------------------------------------------------
# Direct HTTP Retrieval Providers with Security Safeguards
# ---------------------------------------------------------------------------

def live_search(query: str, timeout: int = DEFAULT_TIMEOUT) -> list[dict[str, str]]:
    """Execute search query using DuckDuckGo Lite without external API dependencies."""
    search_endpoint = "https://lite.duckduckgo.com/lite/"
    validate_network_url(search_endpoint)

    data = urllib.parse.urlencode({"q": query}).encode("utf-8")
    req = urllib.request.Request(
        search_endpoint,
        data=data,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    )
    results: list[dict[str, str]] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read(MAX_FETCH_BYTES)
            body = raw_bytes.decode("utf-8", errors="ignore")
            # Extract links and titles
            links = re.findall(r'href=[\x22\x27](https?://[^\x22\x27]+)[\x22\x27][^>]*>(.*?)</a>', body, re.IGNORECASE)
            for href, raw_title in links:
                clean_title = re.sub(r'<[^>]+>', '', raw_title).strip()
                if "duckduckgo.com" not in href:
                    results.append({"url": href, "title": clean_title})
    except Exception as exc:
        logger.warning("Direct live_search failed for query '%s': %s", query, exc)

    return results


def live_fetch(url: str, timeout: int = DEFAULT_TIMEOUT, max_redirects: int = MAX_REDIRECTS) -> str:
    """Fetch URL safely with SSRF protection, size cap, and bounded redirects."""
    current_url = url
    redirect_count = 0

    while redirect_count <= max_redirects:
        validated_url = validate_network_url(current_url)
        req = urllib.request.Request(
            validated_url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"},
        )

        class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                # Intercept redirect so we can validate next destination before following
                return None

        opener = urllib.request.build_opener(_NoRedirectHandler)

        try:
            with opener.open(req, timeout=timeout) as resp:
                raw_bytes = resp.read(MAX_FETCH_BYTES)
                html_text = raw_bytes.decode("utf-8", errors="ignore")
                parser = _CleanHTMLParser()
                parser.feed(html_text)
                return "\n".join(parser.texts)
        except HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                location = e.headers.get("Location")
                if not location:
                    raise ProviderNetworkError(f"HTTP {e.code} redirect missing Location header.")
                current_url = urljoin(current_url, location)
                redirect_count += 1
                if redirect_count > max_redirects:
                    raise ProviderNetworkError(f"Exceeded max redirects ({max_redirects}) for URL {url}")
                continue
            else:
                logger.warning("live_fetch HTTP error for %s: %s", current_url, e)
                return ""
        except Exception as exc:
            logger.warning("live_fetch failed for URL '%s': %s", current_url, exc)
            return ""

    return ""


# ---------------------------------------------------------------------------
# Anthropic Server-Side Retrieval Provider Adapter
# ---------------------------------------------------------------------------

def anthropic_search(query: str, client: Any = None, timeout: int = DEFAULT_TIMEOUT) -> list[dict[str, str]]:
    """Execute search query using Anthropic's server-side web_search tool."""
    try:
        import config
        cl = client or config.get_anthropic_client()
        if not cl:
            return []

        response = config.execute_messages_create(
            cl,
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": f"Search using web_search: {query}"}],
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
        )

        results: list[dict[str, str]] = []
        for block in response.content:
            if getattr(block, "type", None) == "web_search_tool_result":
                content = getattr(block, "content", [])
                for item in content:
                    u = getattr(item, "url", None)
                    t = getattr(item, "title", None) or ""
                    if u:
                        results.append({"url": u, "title": t})
        return results
    except Exception as exc:
        logger.warning("Anthropic server-side web_search failed: %s", exc)
        return []


def anthropic_fetch(url: str, client: Any = None, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Fetch page content using Anthropic's server-side web_fetch tool."""
    try:
        validate_network_url(url)
        import config
        cl = client or config.get_anthropic_client()
        if not cl:
            return ""

        response = config.execute_messages_create(
            cl,
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": f"Fetch {url}"}],
            tools=[{"type": "web_fetch_20250910", "name": "web_fetch"}],
        )

        for block in response.content:
            if getattr(block, "type", None) == "web_fetch_tool_result":
                fetch_block = getattr(block, "content", None)
                if fetch_block:
                    doc_block = getattr(fetch_block, "content", None)
                    if doc_block and hasattr(doc_block, "source"):
                        return getattr(doc_block.source, "data", "")
        return ""
    except Exception as exc:
        logger.warning("Anthropic server-side web_fetch failed: %s", exc)
        return ""
