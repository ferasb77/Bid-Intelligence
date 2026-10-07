"""
buyer_research.py -- Governed Buyer Research Orchestrator (BI-VALUE-2 / BI-VALUE-2.1).

Enforces:
1. MAX_SEARCHES = 3 hard budget.
2. MAX_ACCEPTED_OFFICIAL_PAGES = 6 hard budget.
3. Official Source Gate:
   - Allowable authority using resolved buyer identity and attributable source ownership.
   - Primary: buyer's official domain matching tokens/slugs (.ca, .edu, .org, .com).
   - Secondary: official parent / government authority domains (.gc.ca, .gov, .gov.on.ca, .gov.ab.ca).
   - Adversarial / commercial / social / aggregators strictly rejected.
4. Verbatim Extract Verification:
   - Every extract checked via buyer_evidence_acquisition against actual fetched page full text.
5. Separation of Truth Classes:
   - Extracted facts tagged FactClass.AUTHORITATIVE_BUYER_FACT or PUBLIC_ORGANIZATIONAL_INFORMATION.
6. Durable Persistence & Exact Complete Reuse:
   - Checks database table buyer_research_runs (bid/organization scoped, UNIQUE complete fingerprint).
   - In-memory cache as secondary optimization.
   - Exact reuse yields status REUSED_COMPLETE with 0 searches, 0 fetches, 0 model calls.
   - Preserves complete provenance (URLs, publishers, titles, category, hashes, exact extracts).
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
    EvidenceAuthority, EvidenceSource, LocatorType, SourceCategory, normalize_evidence_url,
)
from buyer_intelligence import FactClass, FactKind

logger = logging.getLogger(__name__)

# Hard limits (BI-VALUE-2 / BI-VALUE-2.3)
MAX_SEARCHES: int = 3
MAX_ACCEPTED_OFFICIAL_PAGES: int = 6
RESEARCH_CONTRACT_VERSION: str = "buyer-research/2"

import buyer_source_authority as bsa
from buyer_source_authority import (
    SOURCE_AUTHORITY_POLICY_VERSION,
    SourceAuthorityClass, SourceAuthorityStatus, VerifiedOfficialDomain,
    classify_government_domain, is_adversarial_or_disallowed_domain,
    normalize_domain, verify_buyer_domain_content,
)

# Disallowed domains (aggregators, social media, blogs, forums, commercial registries)
DISALLOWED_DOMAINS = bsa.DISALLOWED_DOMAINS


class ResearchStatus(str, Enum):
    COMPLETE = "COMPLETE"
    REUSED_COMPLETE = "REUSED_COMPLETE"
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
    evidence_id: str | None = None
    content_hash: str | None = None
    authority_class: str = SourceAuthorityClass.OFFICIAL_BUYER.value


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
    run_id: int | None = None
    error: str | None = None
    verified_buyer_domain: str | None = None

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
            "run_id": self.run_id,
            "error": self.error,
            "verified_buyer_domain": self.verified_buyer_domain,
        }


def compute_research_fingerprint(
    buyer_name: str,
    solicitation_number: str | None = None,
    context_anchors: str = "",
    contract_version: str = RESEARCH_CONTRACT_VERSION,
    authority_policy_version: str = bsa.SOURCE_AUTHORITY_POLICY_VERSION,
) -> str:
    """Compute deterministic cache fingerprint for buyer research including authority policy version."""
    norm_buyer = re.sub(r'\s+', ' ', (buyer_name or "").strip().lower())
    norm_sol = re.sub(r'\s+', ' ', (solicitation_number or "").strip().lower())
    norm_anchors = re.sub(r'\s+', ' ', (context_anchors or "").strip().lower())
    payload = f"buyer_research:{contract_version}:{authority_policy_version}:{norm_buyer}:{norm_sol}:{norm_anchors}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_official_source_allowed(
    url: str,
    buyer_name: str,
    verified_buyer_domain: str | None = None,
    jurisdiction_country: str | None = None,
) -> bool:
    """
    Validate whether URL meets the strict verified source authority boundary (BI-VALUE-2.3).
    Rules:
    1. HTTP/HTTPS only.
    2. Hostname must NOT match any disallowed generic aggregator/social/news domain.
    3. Hostname cannot be an adversarial fake containing hyphens with arbitrary tlds (e.g. fake-yorku.ca).
    4. Allowable authority:
       a. Verified official buyer domain or subdomain of it (e.g. yorku.ca -> *.yorku.ca).
       b. Official government authority domains (.gc.ca, .gov.on.ca, .gov.ab.ca, ontario.ca, canada.ca).
    5. Token-based matching without domain verification is PROHIBITED.
       Arbitrary .edu/.org/.uk domains (e.g., york.ac.uk, york.edu) are REJECTED for Canadian York University.
    """
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    if not u.startswith("http://") and not u.startswith("https://"):
        return False

    domain = normalize_domain(u)
    if not domain or is_adversarial_or_disallowed_domain(domain):
        return False

    # Check government authority
    gov = classify_government_domain(domain, buyer_jurisdiction=jurisdiction_country)
    if gov and gov.is_government_authority:
        return True

    # If a verified official buyer domain exists, accept exact match or subdomain
    if verified_buyer_domain:
        norm_vbd = normalize_domain(verified_buyer_domain)
        if domain == norm_vbd or domain.endswith("." + norm_vbd):
            return True
        return False

    # Without a verified buyer domain, unverified candidate domains cannot be admitted
    return False


# ---------------------------------------------------------------------------
# In-Memory Cache (Secondary optimization)
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
# Durable DB Persistence Helpers
# ---------------------------------------------------------------------------

def _load_durable_research_run(
    organization_id: str,
    fingerprint: str,
) -> BuyerResearchResult | None:
    """Query durable complete research runs from public.buyer_research_runs."""
    if not organization_id:
        return None
    try:
        import database
        client = database.get_service_client()
        resp = (
            client.table("buyer_research_runs")
            .select("*")
            .eq("organization_id", organization_id)
            .eq("research_fingerprint", fingerprint)
            .eq("status", "COMPLETE")
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        if not resp.data:
            return None

        row = resp.data[0]
        payload = row.get("payload") or {}
        signals_data = payload.get("signals") or []
        signals = tuple(
            ResearchSignal(
                title=s.get("title", ""),
                detail=s.get("detail", ""),
                source_url=s.get("source_url", ""),
                source_title=s.get("source_title", ""),
                fact_class=s.get("fact_class", FactClass.AUTHORITATIVE_BUYER_FACT.value),
                fact_kind=s.get("fact_kind", FactKind.MANDATE.value),
                verbatim_quote=s.get("verbatim_quote", ""),
                evidence_id=s.get("evidence_id"),
                content_hash=s.get("content_hash"),
            )
            for s in signals_data
        )

        return BuyerResearchResult(
            status=ResearchStatus.REUSED_COMPLETE,
            resolved_buyer=row.get("resolved_buyer_name", ""),
            query_fingerprint=fingerprint,
            searches_executed=0,
            pages_accepted=row.get("accepted_page_count", len(signals)),
            signals=signals,
            evidence_ids=tuple(payload.get("evidence_ids") or []),
            official_website=payload.get("official_website"),
            buyer_id=payload.get("buyer_id", ""),
            cached_reuse=True,
            run_id=row.get("id"),
            verified_buyer_domain=payload.get("verified_buyer_domain"),
        )
    except Exception as exc:
        logger.debug("Durable buyer research lookup skipped or table absent: %s", exc)
        return None


def _persist_durable_research_run(
    bid_id: int | None,
    organization_id: str | None,
    result: BuyerResearchResult,
    provider: str = "anthropic_server_tools",
    error_reason: str | None = None,
) -> int | None:
    """Persist completed or failed research run into public.buyer_research_runs."""
    if not bid_id or not organization_id:
        return None
    try:
        import database
        client = database.get_service_client()
        status_str = result.status.value
        if status_str == "REUSED_COMPLETE":
            status_str = "COMPLETE"

        payload = {
            "signals": [asdict(s) for s in result.signals],
            "evidence_ids": list(result.evidence_ids),
            "official_website": result.official_website,
            "buyer_id": result.buyer_id,
            "verified_buyer_domain": result.verified_buyer_domain,
        }

        row_data = {
            "bid_id": bid_id,
            "organization_id": organization_id,
            "research_fingerprint": result.query_fingerprint,
            "contract_version": RESEARCH_CONTRACT_VERSION,
            "status": status_str,
            "resolved_buyer_name": result.resolved_buyer,
            "search_count": result.searches_executed,
            "accepted_page_count": result.pages_accepted,
            "provider": provider,
            "payload": payload,
            "error_reason": error_reason or result.error,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

        resp = client.table("buyer_research_runs").insert(row_data).execute()
        if resp.data:
            return resp.data[0].get("id")
    except Exception as exc:
        logger.debug("Could not persist durable research run: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Governed Research Execution Engine
# ---------------------------------------------------------------------------

def run_governed_buyer_research(
    resolved_buyer: str,
    *,
    bid_id: int | None = None,
    organization_id: str | None = None,
    solicitation_number: str | None = None,
    context_anchors: str = "",
    jurisdiction_country: str | None = None,
    jurisdiction_subdivision: str | None = None,
    verified_buyer_domain: str | None = None,
    procurement_document_domains: Sequence[str] = (),
    search_fn: Callable[[str], list[dict[str, str]]] | None = None,
    fetch_fn: Callable[[str], str] | None = None,
    max_searches: int = MAX_SEARCHES,
    max_pages: int = MAX_ACCEPTED_OFFICIAL_PAGES,
    provider: str = "anthropic_server_tools",
) -> BuyerResearchResult:
    """
    Executes bounded, governed buyer research with source-authority closure (BI-VALUE-2.4):
    1. Checks durable persistence first (survives process restart with 0 calls).
    2. Checks in-memory cache as secondary layer.
    3. Performs bounded domain discovery and identity verification if verified_buyer_domain not supplied.
    4. Constrains buyer-specific research queries to the canonical verified buyer root domain.
    5. Enforces Max 3 searches and Max 6 accepted official pages.
    6. Verifies every extract verbatim against fetched page text.
    7. Yields structured BuyerResearchResult.
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

    fingerprint = compute_research_fingerprint(
        resolved_buyer,
        solicitation_number=solicitation_number,
        context_anchors=context_anchors,
    )

    # 1. Check durable persistence from database (works across processes)
    if organization_id:
        durable_match = _load_durable_research_run(organization_id, fingerprint)
        if durable_match:
            logger.info("Durable exact reuse for buyer '%s' (0 searches, 0 fetches, 0 provider calls)", resolved_buyer)
            cache_research(durable_match)
            return durable_match

    # 2. Check in-memory cache
    cached = get_cached_research(fingerprint)
    if cached and cached.status in (ResearchStatus.COMPLETE, ResearchStatus.REUSED_COMPLETE):
        logger.info("In-memory exact reuse for buyer '%s' (0 searches, 0 fetches)", resolved_buyer)
        return BuyerResearchResult(
            status=ResearchStatus.REUSED_COMPLETE,
            resolved_buyer=cached.resolved_buyer,
            query_fingerprint=cached.query_fingerprint,
            searches_executed=0,
            pages_accepted=cached.pages_accepted,
            signals=cached.signals,
            evidence_ids=cached.evidence_ids,
            official_website=cached.official_website,
            buyer_id=cached.buyer_id,
            cached_reuse=True,
            run_id=cached.run_id,
            verified_buyer_domain=cached.verified_buyer_domain,
        )

    # 3. If no search/fetch functions supplied, default to Anthropic server-side tools
    if search_fn is None or fetch_fn is None:
        import buyer_research_provider as brp
        search_fn = search_fn or brp.anthropic_search
        fetch_fn = fetch_fn or brp.anthropic_fetch
        if provider == "live_direct_http":
            provider = "anthropic_server_tools"

    # 4. Search & Domain Verification Orchestration (Phase E & F)
    searches_executed = 0
    known_verified_domain = verified_buyer_domain
    if known_verified_domain:
        known_verified_domain = bsa.get_registrable_domain(known_verified_domain)

    pages_accepted = 0
    accepted_pages: list[bea.FetchedPage] = []
    signals: list[ResearchSignal] = []

    clean_anchor = re.sub(r'[^a-zA-Z0-9\s]', ' ', context_anchors)[:60].strip()

    candidate_urls: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    candidate_texts: dict[str, str] = {}

    # Check procurement document domains directly before searching
    if not known_verified_domain and procurement_document_domains:
        for p_dom in procurement_document_domains:
            norm_p = normalize_domain(p_dom)
            if not norm_p or is_adversarial_or_disallowed_domain(norm_p):
                continue
            try:
                p_text = fetch_fn(f"https://{norm_p}")
                candidate_texts[f"https://{norm_p}"] = p_text
            except Exception:
                p_text = ""
            ver = bsa.verify_buyer_domain_content(
                norm_p,
                resolved_buyer,
                p_text,
                jurisdiction_country=jurisdiction_country,
                jurisdiction_subdivision=jurisdiction_subdivision,
                procurement_document_domains=procurement_document_domains,
                fetch_root_fn=fetch_fn,
            )
            if ver.is_official_buyer:
                known_verified_domain = ver.canonical_buyer_domain or ver.registrable_domain or ver.domain
                logger.info("Verified official buyer domain from procurement document: %s", known_verified_domain)
                break

    # Query definitions
    if known_verified_domain:
        queries = [
            f"site:{known_verified_domain} {clean_anchor} strategic priorities mandate".strip(),
            f"site:{known_verified_domain} procurement policy guidelines".strip(),
            f"site:{known_verified_domain} continuing education training".strip(),
        ]
    else:
        # Initial queries search broadly, but first result triggers domain verification
        queries = [
            f"{resolved_buyer} {clean_anchor} strategic priorities mandate".strip(),
            f"{resolved_buyer} procurement policy guidelines",
            f"{resolved_buyer} continuing education training",
        ]

    for q in queries:
        if searches_executed >= max_searches:
            break
        try:
            results = search_fn(q)
            searches_executed += 1

            # If we don't have a verified domain yet, discover and verify from search candidates
            if not known_verified_domain:
                for cand in results:
                    u = cand.get("url") or ""
                    d = normalize_domain(u)
                    if not d or is_adversarial_or_disallowed_domain(d):
                        continue
                    # Attempt verification by fetching candidate page
                    try:
                        c_text = fetch_fn(u)
                        candidate_texts[u] = c_text
                    except Exception:
                        c_text = ""
                    ver = bsa.verify_buyer_domain_content(
                        d,
                        resolved_buyer,
                        c_text,
                        jurisdiction_country=jurisdiction_country,
                        jurisdiction_subdivision=jurisdiction_subdivision,
                        procurement_document_domains=procurement_document_domains,
                        fetch_root_fn=fetch_fn,
                    )
                    if ver.is_official_buyer:
                        known_verified_domain = ver.canonical_buyer_domain or ver.registrable_domain or ver.domain
                        logger.info("Verified official buyer domain from candidate: %s", known_verified_domain)
                        # Dynamically constrain remaining queries to site:<verified_domain>
                        remaining_queries = [
                            f"site:{known_verified_domain} {clean_anchor} strategic priorities mandate".strip(),
                            f"site:{known_verified_domain} procurement policy guidelines".strip(),
                            f"site:{known_verified_domain} continuing education training".strip(),
                        ]
                        queries = queries[:searches_executed] + remaining_queries[searches_executed:]
                        break

            for res in results:
                url = res.get("url") or ""
                title = res.get("title") or ""
                if url and url not in seen_urls and is_official_source_allowed(
                    url,
                    resolved_buyer,
                    verified_buyer_domain=known_verified_domain,
                    jurisdiction_country=jurisdiction_country,
                ):
                    seen_urls.add(url)
                    candidate_urls.append({"url": url, "title": title})
        except Exception as exc:
            logger.warning("Search query '%s' failed: %s", q, exc)

    buyer_slug = re.sub(r'[^a-z0-9]+', '-', resolved_buyer.lower()).strip('-')
    buyer_id = f"buyer:{buyer_slug}"
    official_website = None

    for cand in candidate_urls:
        if pages_accepted >= max_pages:
            break
        u = cand["url"]
        t = cand["title"] or f"{resolved_buyer} Official Page"
        try:
            full_text = candidate_texts.get(u)
            if full_text is None:
                full_text = fetch_fn(u)
            if not full_text or len(full_text.strip()) < 50:
                continue

            if not official_website:
                official_website = f"{urlsplit(u).scheme}://{urlsplit(u).netloc}"

            content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()

            # Extract key factual sentences
            sentences = [s.strip() for s in re.split(r'[\r\n]+|[.!?]\s+', full_text) if len(s.strip()) > 35]
            page_extracts: list[bea.FetchedExtract] = []

            for i, sent in enumerate(sentences[:3]):
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
                            evidence_id=ext_id,
                            content_hash=content_hash,
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

    # Build governed BuyerEvidenceSet
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
        verified_buyer_domain=known_verified_domain,
    )

    # Cache and persist
    if final_status == ResearchStatus.COMPLETE:
        cache_research(res)
        if bid_id and organization_id:
            run_id = _persist_durable_research_run(bid_id, organization_id, res, provider=provider)
            if not run_id:
                logger.error("Durable persistence failed for bid %s, org %s; downgrading status to PARTIAL", bid_id, organization_id)
                return BuyerResearchResult(
                    status=ResearchStatus.PARTIAL,
                    resolved_buyer=res.resolved_buyer,
                    query_fingerprint=res.query_fingerprint,
                    searches_executed=res.searches_executed,
                    pages_accepted=res.pages_accepted,
                    signals=res.signals,
                    evidence_ids=res.evidence_ids,
                    official_website=res.official_website,
                    buyer_id=res.buyer_id,
                    cached_reuse=False,
                    verified_buyer_domain=known_verified_domain,
                    error="Buyer research completed but durable persistence failed.",
                )
            res = BuyerResearchResult(
                status=res.status,
                resolved_buyer=res.resolved_buyer,
                query_fingerprint=res.query_fingerprint,
                searches_executed=res.searches_executed,
                pages_accepted=res.pages_accepted,
                signals=res.signals,
                evidence_ids=res.evidence_ids,
                official_website=res.official_website,
                buyer_id=res.buyer_id,
                cached_reuse=res.cached_reuse,
                run_id=run_id,
                verified_buyer_domain=known_verified_domain,
            )

    return res
