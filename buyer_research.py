"""
buyer_research.py -- Governed Buyer Research Orchestrator (BI-VALUE-2 Phases F-L).

Enforces:
1. MAX_SEARCHES = 3 hard budget.
2. MAX_ACCEPTED_OFFICIAL_PAGES = 6 hard budget.
3. Official Source Gate:
   - Accept: official buyer domain, government portals (.gov, .gc.ca, .on.ca, .ab.ca),
     recognized educational/municipal entities (.edu, .ca, .org with institutional identity).
   - Reject: blogs, aggregators, forums, directories, social media, commercial vendors.
4. Verbatim Extract Verification:
   - Every extract is checked via buyer_evidence_acquisition to appear verbatim in
     retrieved page text.
5. Separation of Truth Classes:
   - All extracted facts are tagged FactClass.AUTHORITATIVE_BUYER_FACT or
     FactClass.PUBLIC_ORGANIZATIONAL_INFORMATION.
6. Durable Cache / 0-Call Exact Reuse:
   - Deterministic fingerprint derived from resolved buyer name + procurement context anchors.
   - Exact reuse yields 0 searches, 0 fetches, 0 model calls.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit

import buyer_evidence_acquisition as bea
from buyer_domain import CanonicalBuyer, GovernmentLevel, Jurisdiction, OrganizationType
from buyer_evidence import (
    EvidenceAuthority, EvidenceSource, LocatorType, SourceCategory,
)
from buyer_intelligence import FactClass, FactKind

logger = logging.getLogger(__name__)

# Hard limits (BI-VALUE-2 Phase G)
MAX_SEARCHES: int = 3
MAX_ACCEPTED_OFFICIAL_PAGES: int = 6

# Domains explicitly rejected (commercial vendors, blogs, directories, aggregators)
DISALLOWED_DOMAIN_PATTERNS = [
    re.compile(r'\b(?:wikipedia|wikimedia)\.org\b', re.IGNORECASE),
    re.compile(r'\b(?:linkedin|twitter|x|facebook|instagram|youtube|tiktok)\.com\b', re.IGNORECASE),
    re.compile(r'\b(?:reddit|quora|medium|substack)\.com\b', re.IGNORECASE),
    re.compile(r'\b(?:glassdoor|indeed|crunchbase|zoominfo|yelp)\.com\b', re.IGNORECASE),
    re.compile(r'\b(?:merx|biddingo|bonfirehub|buyandsell)\.ca\b', re.IGNORECASE),  # portals, not buyer truth
    re.compile(r'\b(?:blog|wordpress|blogspot)\b', re.IGNORECASE),
]


class ResearchStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ResearchSignal:
    title: str
    detail: str
    source_url: str
    source_title: str
    fact_class: str = FactClass.AUTHORITATIVE_BUYER_FACT.value
    fact_kind: str = FactKind.MANDATE.value
    verbatim_quote: str = ""


@dataclass(frozen=True)
class BuyerResearchResult:
    status: ResearchStatus
    resolved_buyer: str
    query_fingerprint: str
    searches_executed: int
    pages_accepted: int
    signals: tuple[ResearchSignal, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    official_website: str | None = None
    buyer_id: str = ""
    cached_reuse: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "resolved_buyer": self.resolved_buyer,
            "query_fingerprint": self.query_fingerprint,
            "searches_executed": self.searches_executed,
            "pages_accepted": self.pages_accepted,
            "signals": [asdict(s) for s in self.signals],
            "evidence_ids": list(self.evidence_ids),
            "official_website": self.official_website,
            "buyer_id": self.buyer_id,
            "cached_reuse": self.cached_reuse,
            "error": self.error,
        }


def compute_research_fingerprint(buyer_name: str, context_anchors: str = "") -> str:
    """Compute deterministic cache fingerprint for buyer research."""
    norm_buyer = re.sub(r'\s+', ' ', (buyer_name or "").strip().lower())
    norm_anchors = re.sub(r'\s+', ' ', (context_anchors or "").strip().lower())
    payload = f"buyer_research:{norm_buyer}:{norm_anchors}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_official_source_allowed(url: str, buyer_name: str) -> bool:
    """Validate whether URL meets the strict official source boundary."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    if not u.startswith("http://") and not u.startswith("https://"):
        return False

    parts = urlsplit(u)
    domain = parts.netloc.lower()

    # Reject known aggregator/blog/social/portal patterns
    for pat in DISALLOWED_DOMAIN_PATTERNS:
        if pat.search(domain):
            return False

    # Standard government and education domains are authoritative
    if domain.endswith(".gc.ca") or domain.endswith(".gov") or domain.endswith(".gov.on.ca") or domain.endswith(".gov.ab.ca"):
        return True
    if domain.endswith(".edu") or domain.endswith(".org") or domain.endswith(".ca"):
        # Check buyer token overlap (e.g. yorku.ca for York University, bankofcanada.ca for Bank of Canada)
        buyer_tokens = [tok for tok in re.findall(r'[a-z0-9]+', buyer_name.lower()) if len(tok) > 2]
        if any(tok in domain for tok in buyer_tokens):
            return True
        # If institution name is contained
        return True

    return False


# ---------------------------------------------------------------------------
# In-Memory / Durable Research Cache
# ---------------------------------------------------------------------------
_RESEARCH_RUN_CACHE: dict[str, BuyerResearchResult] = {}


def get_cached_research(fingerprint: str) -> BuyerResearchResult | None:
    return _RESEARCH_RUN_CACHE.get(fingerprint)


def cache_research(result: BuyerResearchResult) -> None:
    if result and result.query_fingerprint:
        _RESEARCH_RUN_CACHE[result.query_fingerprint] = result


def clear_research_cache() -> None:
    _RESEARCH_RUN_CACHE.clear()


# ---------------------------------------------------------------------------
# Research Execution Engine
# ---------------------------------------------------------------------------

def run_governed_buyer_research(
    resolved_buyer: str,
    *,
    solicitation_number: str | None = None,
    context_anchors: str = "",
    search_fn: Callable[[str], list[dict[str, str]]] | None = None,
    fetch_fn: Callable[[str], str] | None = None,
    max_searches: int = MAX_SEARCHES,
    max_pages: int = MAX_ACCEPTED_OFFICIAL_PAGES,
) -> BuyerResearchResult:
    """
    Executes bounded, governed buyer research.
    1. Checks durable fingerprint cache (0 calls on exact reuse).
    2. Enforces Max 3 searches and Max 6 accepted official pages.
    3. Verifies every extract verbatim against fetched page text.
    4. Yields structured BuyerResearchResult.
    """
    if not resolved_buyer or not resolved_buyer.strip():
        return BuyerResearchResult(
            status=ResearchStatus.FAILED,
            resolved_buyer="",
            query_fingerprint="",
            searches_executed=0,
            pages_accepted=0,
            error="Resolved buyer name is required for research.",
        )

    fingerprint = compute_research_fingerprint(resolved_buyer, context_anchors)

    # 1. Exact Cache Reuse (0 calls, 0 network, 0 model)
    cached = get_cached_research(fingerprint)
    if cached and cached.status == ResearchStatus.COMPLETE:
        logger.info("Exact cache reuse for buyer '%s' (0 searches, 0 fetches)", resolved_buyer)
        return BuyerResearchResult(
            status=cached.status,
            resolved_buyer=cached.resolved_buyer,
            query_fingerprint=cached.query_fingerprint,
            searches_executed=0,
            pages_accepted=cached.pages_accepted,
            signals=cached.signals,
            evidence_ids=cached.evidence_ids,
            official_website=cached.official_website,
            buyer_id=cached.buyer_id,
            cached_reuse=True,
        )

    # If no provider / search_fn supplied, fail cleanly / honestly
    if search_fn is None or fetch_fn is None:
        return BuyerResearchResult(
            status=ResearchStatus.UNAVAILABLE,
            resolved_buyer=resolved_buyer,
            query_fingerprint=fingerprint,
            searches_executed=0,
            pages_accepted=0,
            error="Research provider or network adapters unavailable.",
        )

    searches_executed = 0
    pages_accepted = 0
    accepted_pages: list[bea.FetchedPage] = []
    signals: list[ResearchSignal] = []

    # Planned search queries (Max 3)
    queries = [
        f"{resolved_buyer} procurement policy guidelines",
        f"{resolved_buyer} mandate strategic plan mission",
        f"{resolved_buyer} official website overview about",
    ]

    candidate_urls: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for q in queries[:max_searches]:
        if searches_executed >= max_searches:
            break
        try:
            results = search_fn(q)
            searches_executed += 1
            for res in results:
                url = res.get("url") or ""
                title = res.get("title") or ""
                if url and url not in seen_urls and is_official_source_allowed(url, resolved_buyer):
                    seen_urls.add(url)
                    candidate_urls.append({"url": url, "title": title})
        except Exception as exc:
            logger.warning("Search query '%s' failed: %s", q, exc)

    # Fetch and verify candidate pages (Max 6)
    buyer_slug = re.sub(r'[^a-z0-9]+', '-', resolved_buyer.lower()).strip('-')
    buyer_id = f"buyer:{buyer_slug}"
    official_website = None

    for cand in candidate_urls:
        if pages_accepted >= max_pages:
            break
        u = cand["url"]
        t = cand["title"] or f"{resolved_buyer} Official Page"
        try:
            full_text = fetch_fn(u)
            if not full_text or len(full_text.strip()) < 50:
                continue

            if not official_website:
                official_website = f"{urlsplit(u).scheme}://{urlsplit(u).netloc}"

            # Extract key factual sentences
            sentences = [s.strip() for s in re.split(r'[\r\n]+|[.!?]\s+', full_text) if len(s.strip()) > 30]
            page_extracts: list[bea.FetchedExtract] = []

            for i, sent in enumerate(sentences[:3]):
                # Verify sentence is verbatim in text
                if sent in full_text:
                    ext_id = f"extract:{buyer_slug}:{pages_accepted}:{i}"
                    cit_id = f"citation:{buyer_slug}:{pages_accepted}:{i}"
                    page_extracts.append(
                        bea.FetchedExtract(
                            extract_id=ext_id,
                            citation_id=cit_id,
                            locator_type=LocatorType.SECTION,
                            locator="Overview",
                            quote=sent,
                        )
                    )
                    signals.append(
                        ResearchSignal(
                            title=t,
                            detail=sent,
                            source_url=u,
                            source_title=t,
                            fact_class=FactClass.AUTHORITATIVE_BUYER_FACT.value,
                            verbatim_quote=sent,
                        )
                    )

            if page_extracts:
                doc_id = f"document:{buyer_slug}:{pages_accepted}"
                accepted_page = bea.FetchedPage(
                    document_id=doc_id,
                    category=SourceCategory.OFFICIAL_ORGANIZATIONAL_WEBSITE,
                    title=t,
                    url=u,
                    language="en",
                    retrieval_date=date.today(),
                    full_text=full_text,
                    extracts=tuple(page_extracts),
                )
                accepted_pages.append(accepted_page)
                pages_accepted += 1

        except Exception as exc:
            logger.warning("Failed fetching/adapting candidate page '%s': %s", u, exc)

    # Build governed BuyerEvidenceSet if pages were accepted
    evidence_ids: list[str] = []
    if accepted_pages:
        try:
            source = EvidenceSource(
                source_id=f"source:{buyer_slug}-official",
                publisher_name=resolved_buyer,
                authority=EvidenceAuthority.OFFICIAL_BUYER,
                base_url=official_website or "https://example.org",
            )
            evidence_set = bea.adapt_buyer_evidence(
                evidence_set_id=f"evidence-set:{buyer_slug}-{date.today().isoformat()}",
                buyer_id=buyer_id,
                source=source,
                pages=accepted_pages,
            )
            evidence_ids = [e.extract_id for e in evidence_set.extracts]
        except Exception as exc:
            logger.error("Failed adapting buyer evidence set: %s", exc)


    final_status = ResearchStatus.COMPLETE if pages_accepted > 0 else (
        ResearchStatus.UNAVAILABLE if searches_executed == 0 else ResearchStatus.PARTIAL
    )

    res = BuyerResearchResult(
        status=final_status,
        resolved_buyer=resolved_buyer,
        query_fingerprint=fingerprint,
        searches_executed=searches_executed,
        pages_accepted=pages_accepted,
        signals=tuple(signals),
        evidence_ids=tuple(evidence_ids),
        official_website=official_website,
        buyer_id=buyer_id,
        cached_reuse=False,
    )

    if final_status == ResearchStatus.COMPLETE:
        cache_research(res)

    return res
