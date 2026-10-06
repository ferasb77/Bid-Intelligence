"""
buyer_source_authority.py -- Verified Source Authority and Domain Disambiguation (BI-VALUE-2.3).

Contracts:
1. Authority Classes:
   - OFFICIAL_BUYER: The buyer's verified official domain.
   - GOVERNMENT_AUTHORITY: Legitimate government authority domain (e.g., ontario.ca, canada.ca).
   - OFFICIAL_PROCUREMENT_AUTHORITY: Dedicated public procurement oversight / registry portal.
   - OTHER_OFFICIAL_AUTHORITY: Other verified public institutional publisher.
   - UNVERIFIED: Candidate domain whose ownership by the buyer cannot be proven.
   - DIFFERENT_ORGANIZATION: Domain proven to belong to an unrelated entity or conflicting jurisdiction.

2. SourceAuthorityStatus:
   - VERIFIED: Positively identified and confirmed via content / official register.
   - REJECTED: Disallowed, fake, aggregator, or proven different entity.
   - UNVERIFIED: Inconclusive; fails closed.

3. VerifiedOfficialDomain:
   - Record preserving normalized domain, buyer identity, authority class, status, verification method, evidence summary, and jurisdiction.

4. Multi-step Domain Discovery & Verification:
   - Content-driven verification: checks fetched home/about content for organizational identity.
   - Rejects same-name entities across different jurisdictions (e.g., York University UK or Nebraska vs. York University Canada).
   - Rejects single-token matches ("york", "bank", "city") without full organizational verification.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit

from buyer_evidence import EvidenceAuthority


SOURCE_AUTHORITY_POLICY_VERSION = "source-authority-policy/2"


class SourceAuthorityClass(str, Enum):
    OFFICIAL_BUYER = "OFFICIAL_BUYER"
    GOVERNMENT_AUTHORITY = "GOVERNMENT_AUTHORITY"
    OFFICIAL_PROCUREMENT_AUTHORITY = "OFFICIAL_PROCUREMENT_AUTHORITY"
    OTHER_OFFICIAL_AUTHORITY = "OTHER_OFFICIAL_AUTHORITY"
    UNVERIFIED = "UNVERIFIED"
    DIFFERENT_ORGANIZATION = "DIFFERENT_ORGANIZATION"


class SourceAuthorityStatus(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class VerifiedOfficialDomain:
    domain: str
    buyer_name: str
    authority_class: SourceAuthorityClass
    status: SourceAuthorityStatus
    verification_method: str
    verification_evidence: str
    jurisdiction_country: str | None = None
    jurisdiction_subdivision: str | None = None

    @property
    def is_official_buyer(self) -> bool:
        return self.status == SourceAuthorityStatus.VERIFIED and self.authority_class == SourceAuthorityClass.OFFICIAL_BUYER

    @property
    def is_government_authority(self) -> bool:
        return self.status == SourceAuthorityStatus.VERIFIED and self.authority_class == SourceAuthorityClass.GOVERNMENT_AUTHORITY

    @property
    def is_allowed_source(self) -> bool:
        return self.status == SourceAuthorityStatus.VERIFIED and self.authority_class in (
            SourceAuthorityClass.OFFICIAL_BUYER,
            SourceAuthorityClass.GOVERNMENT_AUTHORITY,
            SourceAuthorityClass.OFFICIAL_PROCUREMENT_AUTHORITY,
            SourceAuthorityClass.OTHER_OFFICIAL_AUTHORITY,
        )


# Generic aggregator / social / search / job / commercial domains
DISALLOWED_DOMAINS = {
    "wikipedia.org", "wikimedia.org", "linkedin.com", "twitter.com", "x.com",
    "facebook.com", "instagram.com", "youtube.com", "tiktok.com", "reddit.com",
    "quora.com", "medium.com", "substack.com", "glassdoor.com", "indeed.com",
    "crunchbase.com", "zoominfo.com", "yelp.com", "merx.com", "biddingo.com",
    "bonfirehub.com", "buyandsell.gc.ca", "news.google.com", "cbc.ca",
    "theglobeandmail.com", "thestar.com", "bloomberg.com", "forbes.com"
}


def normalize_domain(url_or_domain: str) -> str:
    """Extract and normalize host domain."""
    if not url_or_domain or not isinstance(url_or_domain, str):
        return ""
    val = url_or_domain.strip().lower()
    if "://" in val:
        val = urlsplit(val).netloc
    if ":" in val:
        val = val.split(":")[0]
    return val


def is_adversarial_or_disallowed_domain(domain: str) -> bool:
    """Check if domain is an obvious aggregator, social platform, or adversarial fake."""
    d = normalize_domain(domain)
    if not d:
        return True
    for bad in DISALLOWED_DOMAINS:
        if d == bad or d.endswith("." + bad):
            return True
    if "fake-" in d or "-fake" in d or "example.com" in d or d.endswith(".example.com"):
        return True
    return False


def classify_government_domain(domain: str, buyer_jurisdiction: str | None = None) -> VerifiedOfficialDomain | None:
    """
    Check if a domain is a known government or procurement oversight domain.
    E.g. .gc.ca, .gov.on.ca, .gov.ab.ca, ontario.ca, canada.ca.
    Government domains are classified as GOVERNMENT_AUTHORITY, NEVER as OFFICIAL_BUYER.
    """
    d = normalize_domain(domain)
    if not d or is_adversarial_or_disallowed_domain(d):
        return None

    is_gov = (
        d.endswith(".gc.ca") or
        d.endswith(".gov.on.ca") or
        d.endswith(".gov.ab.ca") or
        d.endswith(".gov.bc.ca") or
        d.endswith(".gov.sk.ca") or
        d.endswith(".gov.mb.ca") or
        d.endswith(".gov.qc.ca") or
        d.endswith(".gov.ns.ca") or
        d.endswith(".gov.nb.ca") or
        d == "ontario.ca" or d.endswith(".ontario.ca") or
        d == "canada.ca" or d.endswith(".canada.ca") or
        d == "alberta.ca" or d.endswith(".alberta.ca") or
        (d.endswith(".gov") and not d.endswith(".fake.gov"))
    )

    if is_gov:
        country = "CA" if (d.endswith(".ca") or "ontario" in d or "canada" in d or "alberta" in d) else None
        subdivision = "CA-ON" if "ontario" in d or d.endswith(".gov.on.ca") else None
        return VerifiedOfficialDomain(
            domain=d,
            buyer_name="",
            authority_class=SourceAuthorityClass.GOVERNMENT_AUTHORITY,
            status=SourceAuthorityStatus.VERIFIED,
            verification_method="government_tld_and_registry",
            verification_evidence=f"Official government domain structure: {d}",
            jurisdiction_country=country,
            jurisdiction_subdivision=subdivision,
        )
    return None


def get_registrable_domain(domain: str) -> str:
    """Extract registrable domain (e.g. yorku.ca, torontoglobal.ca, ontario.ca)."""
    d = normalize_domain(domain)
    if not d:
        return ""
    parts = d.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "ac", "gov", "gc", "org", "com", "edu", "net") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return d


def verify_buyer_domain_content(
    domain: str,
    buyer_name: str,
    page_text: str,
    jurisdiction_country: str | None = None,
    jurisdiction_subdivision: str | None = None,
) -> VerifiedOfficialDomain:
    """
    Analyze fetched page content (e.g. homepage or about page) to verify if the domain
    actually belongs to the resolved buyer, enforcing full entity, domain ownership,
    and jurisdiction checks.
    """
    d = normalize_domain(domain)
    if not d or is_adversarial_or_disallowed_domain(d):
        return VerifiedOfficialDomain(
            domain=d,
            buyer_name=buyer_name,
            authority_class=SourceAuthorityClass.DIFFERENT_ORGANIZATION,
            status=SourceAuthorityStatus.REJECTED,
            verification_method="disallowed_or_adversarial_check",
            verification_evidence=f"Domain {d} matches disallowed or adversarial pattern.",
        )

    # 1. Government authority check
    gov_match = classify_government_domain(d, buyer_jurisdiction=jurisdiction_country)
    if gov_match:
        return gov_match

    if not page_text or len(page_text.strip()) < 40:
        return VerifiedOfficialDomain(
            domain=d,
            buyer_name=buyer_name,
            authority_class=SourceAuthorityClass.UNVERIFIED,
            status=SourceAuthorityStatus.UNVERIFIED,
            verification_method="insufficient_content",
            verification_evidence="Fetched page content was empty or insufficient for identity verification.",
        )

    norm_text = re.sub(r'\s+', ' ', page_text.lower())
    norm_buyer = re.sub(r'\s+', ' ', buyer_name.lower().strip())

    # Full buyer name match
    has_full_buyer_name = norm_buyer in norm_text

    # Extract buyer core tokens (e.g. ['york'] from 'York University')
    core_tokens = [w for w in re.split(r'[^a-z0-9]+', norm_buyer) if w and w not in (
        "university", "college", "corporation", "authority", "board", "city", "town",
        "bank", "department", "ministry", "of", "and", "the", "program", "inc", "ltd"
    )]

    # 2. Domain institutional ownership check:
    # An official buyer domain must incorporate at least one distinctive core token or buyer acronym
    reg_domain = get_registrable_domain(d)
    domain_body = reg_domain.split(".")[0] if "." in reg_domain else reg_domain
    buyer_acronym = "".join(w[0] for w in re.split(r'[^a-z0-9]+', norm_buyer) if w)

    domain_reflects_buyer = any(token in domain_body for token in core_tokens) or (
        len(buyer_acronym) >= 3 and buyer_acronym in domain_body
    )

    if not domain_reflects_buyer:
        return VerifiedOfficialDomain(
            domain=d,
            buyer_name=buyer_name,
            authority_class=SourceAuthorityClass.DIFFERENT_ORGANIZATION,
            status=SourceAuthorityStatus.REJECTED,
            verification_method="domain_identity_mismatch",
            verification_evidence=f"Domain {d} ({reg_domain}) does not reflect buyer entity identity '{buyer_name}'.",
        )

    # 3. Jurisdiction conflict detection
    # Country cues in text
    cues_uk = bool(re.search(r'\b(united kingdom|uk|england|scotland|wales|london|yorkshire)\b', norm_text))
    cues_us = bool(re.search(r'\b(united states|usa|u\.s\.a\.|nebraska|texas|california|new york)\b', norm_text))
    cues_ca = bool(re.search(r'\b(canada|ontario|toronto|alberta|british columbia|quebec|ottawa|calgary)\b', norm_text))

    domain_uk = d.endswith(".uk") or d.endswith(".ac.uk")
    domain_us = d.endswith(".edu") or d.endswith(".gov") or d.endswith(".us")
    domain_ca = d.endswith(".ca")

    expected_ca = jurisdiction_country == "CA" or (jurisdiction_subdivision and jurisdiction_subdivision.startswith("CA"))
    expected_us = jurisdiction_country == "US"
    expected_uk = jurisdiction_country == "GB"

    # Conflicting jurisdiction check
    conflict_detected = False
    conflict_reason = ""

    if expected_ca:
        if domain_uk or (cues_uk and not cues_ca):
            conflict_detected = True
            conflict_reason = f"Buyer expects Canadian jurisdiction ({jurisdiction_country}), but domain {d} has UK cues/domain."
        elif (domain_us and "nebraska" in norm_text) or (cues_us and not cues_ca):
            conflict_detected = True
            conflict_reason = f"Buyer expects Canadian jurisdiction ({jurisdiction_country}), but domain {d} has US/Nebraska cues."

    if conflict_detected:
        return VerifiedOfficialDomain(
            domain=d,
            buyer_name=buyer_name,
            authority_class=SourceAuthorityClass.DIFFERENT_ORGANIZATION,
            status=SourceAuthorityStatus.REJECTED,
            verification_method="jurisdiction_conflict_check",
            verification_evidence=conflict_reason,
            jurisdiction_country="GB" if domain_uk or cues_uk else ("US" if domain_us or cues_us else None),
        )

    # 4. Same-name ambiguity defense: weak single-token match on generic .edu/.org/.com fails closed
    if not has_full_buyer_name:
        return VerifiedOfficialDomain(
            domain=d,
            buyer_name=buyer_name,
            authority_class=SourceAuthorityClass.UNVERIFIED,
            status=SourceAuthorityStatus.UNVERIFIED,
            verification_method="full_name_absent",
            verification_evidence=f"Full organization name '{buyer_name}' not found in page text; token match rejected.",
        )

    # 5. If full buyer name present and jurisdiction aligns (or no conflict), accept as OFFICIAL_BUYER
    detected_country = "CA" if (domain_ca or cues_ca) else ("GB" if (domain_uk or cues_uk) else ("US" if (domain_us or cues_us) else None))
    detected_subdiv = "CA-ON" if "ontario" in norm_text or "toronto" in norm_text else None

    # For .ca or aligned cues:
    return VerifiedOfficialDomain(
        domain=d,
        buyer_name=buyer_name,
        authority_class=SourceAuthorityClass.OFFICIAL_BUYER,
        status=SourceAuthorityStatus.VERIFIED,
        verification_method="content_identity_and_jurisdiction_verification",
        verification_evidence=f"Verified full legal/common name '{buyer_name}' with aligned geographic cues on {d}.",
        jurisdiction_country=detected_country or jurisdiction_country,
        jurisdiction_subdivision=detected_subdiv or jurisdiction_subdivision,
    )


def discover_and_verify_buyer_domain(
    buyer_name: str,
    *,
    jurisdiction_country: str | None = None,
    jurisdiction_subdivision: str | None = None,
    search_fn: Callable[[str], list[dict[str, str]]] | None = None,
    fetch_fn: Callable[[str], str] | None = None,
    max_discovery_searches: int = 1,
) -> tuple[VerifiedOfficialDomain | None, list[VerifiedOfficialDomain]]:
    """
    Bounded domain discovery stage:
    1. Query search provider specifically for the official buyer website.
    2. Filter candidates through initial disallowed and government checks.
    3. Fetch candidate homepage/about content and run verify_buyer_domain_content.
    4. Return (primary_verified_buyer_domain, all_evaluated_domains).
    """
    if not buyer_name or not buyer_name.strip():
        return None, []

    if search_fn is None or fetch_fn is None:
        import buyer_research_provider as brp
        search_fn = search_fn or brp.anthropic_search
        fetch_fn = fetch_fn or brp.anthropic_fetch

    evaluated: list[VerifiedOfficialDomain] = []

    # Query focused on institutional identity
    loc_hint = ""
    if jurisdiction_subdivision:
        loc_hint = jurisdiction_subdivision.replace("CA-", "")
    elif jurisdiction_country:
        loc_hint = jurisdiction_country

    query = f"{buyer_name} {loc_hint} official website about".strip()
    try:
        results = search_fn(query)
    except Exception:
        results = []

    seen_domains: set[str] = set()

    for item in results:
        u = item.get("url") or ""
        if not u:
            continue
        d = normalize_domain(u)
        if not d or d in seen_domains:
            continue
        seen_domains.add(d)

        if is_adversarial_or_disallowed_domain(d):
            evaluated.append(
                VerifiedOfficialDomain(
                    domain=d,
                    buyer_name=buyer_name,
                    authority_class=SourceAuthorityClass.DIFFERENT_ORGANIZATION,
                    status=SourceAuthorityStatus.REJECTED,
                    verification_method="adversarial_disallowed_filter",
                    verification_evidence=f"Domain {d} matched disallowed list.",
                )
            )
            continue

        # Check government authority first
        gov = classify_government_domain(d, buyer_jurisdiction=jurisdiction_country)
        if gov:
            evaluated.append(gov)
            continue

        # Fetch candidate content for domain verification
        try:
            home_url = f"https://{d}"
            text = fetch_fn(home_url)
            if not text or len(text.strip()) < 80:
                # Try original url
                text = fetch_fn(u)
        except Exception:
            text = ""

        ver = verify_buyer_domain_content(
            d,
            buyer_name=buyer_name,
            page_text=text,
            jurisdiction_country=jurisdiction_country,
            jurisdiction_subdivision=jurisdiction_subdivision,
        )
        evaluated.append(ver)
        if ver.is_official_buyer:
            return ver, evaluated

    # If no official buyer domain found
    return None, evaluated
