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

5. BI-VALUE-2.4 / source-authority-policy/3 — positive ownership proof:
   - Domain DISCOVERY is separate from organizational OWNERSHIP proof.
   - OFFICIAL_BUYER requires one of: procurement-package URL/email domain (buyer-reflecting),
     verified registrable-ROOT page self-identity, copyright notice, or @domain contact email.
   - Weak signals (token in hostname + buyer name mentioned + correct country) never suffice.
   - VerifiedOfficialDomain carries observed_domain / registrable_domain / canonical_buyer_domain;
     research is constrained to site:<canonical_buyer_domain>.
   - Foreign .gov is not a GOVERNMENT_AUTHORITY for Canadian buyers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit

from buyer_evidence import EvidenceAuthority


SOURCE_AUTHORITY_POLICY_VERSION = "source-authority-policy/3"


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


class DomainVerificationMethod(str, Enum):
    PROCUREMENT_DOCUMENT_URL = "PROCUREMENT_DOCUMENT_URL"
    PROCUREMENT_CONTACT_EMAIL_DOMAIN = "PROCUREMENT_CONTACT_EMAIL_DOMAIN"
    OFFICIAL_ROOT_PAGE_IDENTITY = "OFFICIAL_ROOT_PAGE_IDENTITY"
    OFFICIAL_PARENT_AUTHORITY = "OFFICIAL_PARENT_AUTHORITY"
    GOVERNMENT_TLD_AND_REGISTRY = "GOVERNMENT_TLD_AND_REGISTRY"
    MANUAL_VERIFIED = "MANUAL_VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class VerifiedOfficialDomain:
    domain: str
    buyer_name: str
    authority_class: SourceAuthorityClass
    status: SourceAuthorityStatus
    verification_method: str
    verification_evidence: str
    observed_domain: str = ""
    registrable_domain: str = ""
    canonical_buyer_domain: str = ""
    jurisdiction_country: str | None = None
    jurisdiction_subdivision: str | None = None

    def __post_init__(self) -> None:
        norm_d = normalize_domain(self.domain)
        reg_d = self.registrable_domain or get_registrable_domain(norm_d)
        obs_d = self.observed_domain or norm_d
        canon_d = self.canonical_buyer_domain or reg_d
        # Update field defaults cleanly
        object.__setattr__(self, "domain", norm_d)
        object.__setattr__(self, "observed_domain", obs_d)
        object.__setattr__(self, "registrable_domain", reg_d)
        object.__setattr__(self, "canonical_buyer_domain", canon_d)

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


# Generic aggregator / social / search / job / commercial domains / third-party tender portals
DISALLOWED_DOMAINS = {
    "wikipedia.org", "wikimedia.org", "linkedin.com", "twitter.com", "x.com",
    "facebook.com", "instagram.com", "youtube.com", "tiktok.com", "reddit.com",
    "quora.com", "medium.com", "substack.com", "glassdoor.com", "indeed.com",
    "crunchbase.com", "zoominfo.com", "yelp.com", "merx.com", "biddingo.com",
    "bonfirehub.com", "buyandsell.gc.ca", "canadabuys.canada.ca", "news.google.com",
    "cbc.ca", "theglobeandmail.com", "thestar.com", "bloomberg.com", "forbes.com"
}


def normalize_domain(url_or_domain: str) -> str:
    """Extract and normalize host domain."""
    if not url_or_domain or not isinstance(url_or_domain, str):
        return ""
    val = url_or_domain.strip().lower()
    if "://" in val:
        val = urlsplit(val).netloc
    for sep in ("/", "?", "#"):
        if sep in val:
            val = val.split(sep, 1)[0]
    if "@" in val:
        val = val.rsplit("@", 1)[1]
    if ":" in val:
        val = val.split(":")[0]
    return val.strip(".")


def is_adversarial_or_disallowed_domain(domain: str) -> bool:
    """Check if domain is an obvious aggregator, social platform, third-party portal, or adversarial fake."""
    d = normalize_domain(domain)
    if not d:
        return True
    for bad in DISALLOWED_DOMAINS:
        if d == bad or d.endswith("." + bad):
            return True
    if "fake-" in d or "-fake" in d or "example.com" in d or d.endswith(".example.com"):
        return True
    return False


CANADIAN_PROVINCIAL_SLDS = {
    "ab.ca", "bc.ca", "mb.ca", "nb.ca", "nl.ca", "ns.ca", "nt.ca",
    "nu.ca", "on.ca", "pe.ca", "qc.ca", "sk.ca", "yt.ca"
}


def get_registrable_domain(domain: str) -> str:
    """
    Extract registrable root domain (e.g. execed.schulich.yorku.ca -> yorku.ca,
    edmonton.ab.ca -> edmonton.ab.ca, torontoglobal.ca -> torontoglobal.ca).
    """
    d = normalize_domain(domain)
    if not d:
        return ""
    parts = d.split(".")
    if len(parts) >= 3:
        last_two = f"{parts[-2]}.{parts[-1]}"
        if last_two in CANADIAN_PROVINCIAL_SLDS:
            return ".".join(parts[-3:])
        if parts[-2] in ("co", "ac", "gov", "gc", "org", "com", "edu", "net") and len(parts[-1]) == 2:
            return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return d


def classify_government_domain(domain: str, buyer_jurisdiction: str | None = None) -> VerifiedOfficialDomain | None:
    """
    Check if a domain is a known legitimate government or public procurement oversight domain.
    E.g. .gc.ca, .gov.on.ca, .gov.ab.ca, ontario.ca, canada.ca, alberta.ca.
    Government domains are classified as GOVERNMENT_AUTHORITY, NEVER as OFFICIAL_BUYER.

    Enforces jurisdiction closure: non-Canadian .gov domains (e.g., US state .gov) are REJECTED
    when the buyer is in Canadian jurisdiction.
    """
    d = normalize_domain(domain)
    if not d or is_adversarial_or_disallowed_domain(d):
        return None

    is_ca_gov = (
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
        d == "alberta.ca" or d.endswith(".alberta.ca")
    )

    is_generic_gov = d.endswith(".gov") and not d.endswith(".fake.gov")

    buyer_is_ca = (buyer_jurisdiction == "CA" or (buyer_jurisdiction and buyer_jurisdiction.startswith("CA")))

    if is_ca_gov:
        subdivision = "CA-ON" if "ontario" in d or d.endswith(".gov.on.ca") else None
        return VerifiedOfficialDomain(
            domain=d,
            buyer_name="",
            authority_class=SourceAuthorityClass.GOVERNMENT_AUTHORITY,
            status=SourceAuthorityStatus.VERIFIED,
            verification_method=DomainVerificationMethod.GOVERNMENT_TLD_AND_REGISTRY.value,
            verification_evidence=f"Official Canadian government domain structure: {d}",
            observed_domain=d,
            registrable_domain=get_registrable_domain(d),
            canonical_buyer_domain=get_registrable_domain(d),
            jurisdiction_country="CA",
            jurisdiction_subdivision=subdivision,
        )

    if is_generic_gov:
        if buyer_is_ca:
            # Foreign government authority cannot serve as official authority for Canadian buyer
            return None
        return VerifiedOfficialDomain(
            domain=d,
            buyer_name="",
            authority_class=SourceAuthorityClass.GOVERNMENT_AUTHORITY,
            status=SourceAuthorityStatus.VERIFIED,
            verification_method=DomainVerificationMethod.GOVERNMENT_TLD_AND_REGISTRY.value,
            verification_evidence=f"Official government domain structure: {d}",
            observed_domain=d,
            registrable_domain=get_registrable_domain(d),
            canonical_buyer_domain=get_registrable_domain(d),
            jurisdiction_country="US",
        )

    return None


_GENERIC_BUYER_WORDS = (
    "university", "college", "corporation", "authority", "board", "city", "town",
    "bank", "department", "ministry", "of", "and", "the", "program", "inc", "ltd",
)


def _domain_reflects_buyer(reg_domain: str, buyer_name: str) -> bool:
    """Naming signal only: registrable domain body contains a distinctive buyer token or acronym.

    This is NEVER sufficient ownership proof on its own (BI-VALUE-2.4).
    """
    if not reg_domain or not buyer_name:
        return False
    norm_buyer = re.sub(r'\s+', ' ', buyer_name.lower().strip())
    words = [w for w in re.split(r'[^a-z0-9]+', norm_buyer) if w]
    core_tokens = [w for w in words if w not in _GENERIC_BUYER_WORDS]
    acronym = "".join(w[0] for w in words)
    body = reg_domain.split(".")[0]
    return any(t in body for t in core_tokens) or (len(acronym) >= 3 and acronym in body)


def is_positive_root_self_identity(
    page_text: str, buyer_name: str, domain: str, *, is_root_page: bool = False,
) -> tuple[bool, str]:
    """
    Check if the fetched page affirmatively self-identifies *as* the buyer organisation,
    and verify it is not merely a third-party article, news post, directory, or partner page
    mentioning the buyer.

    Returns (is_self_identity, reason).
    """
    if not page_text or len(page_text.strip()) < 50:
        return False, "Insufficient content to verify self-identity"

    norm_text = re.sub(r'\s+', ' ', page_text.lower())
    norm_buyer = re.sub(r'\s+', ' ', buyer_name.lower().strip())

    if norm_buyer not in norm_text:
        return False, f"Full buyer name '{buyer_name}' not present in page text"

    # 1. Check for negative third-party article indicators
    article_patterns = [
        re.compile(r'\b(announced today|reported today|according to|in an article|in a statement released|spokesperson for|interviewed by)\b'),
        re.compile(r'\b(published on|byline|staff reporter|news editor|breaking news|local news)\b'),
        re.compile(r'\b(said in a statement|told reporters|told the star|told the globe)\b'),
    ]
    # If text is predominantly an article about the buyer by an outside observer
    for ap in article_patterns:
        if ap.search(norm_text):
            # Check if domain has self-identity markers that override article mention
            # (e.g. an official news release on buyer's own domain like news.yorku.ca)
            # Only allow if strong copyright/ownership exists on the domain
            has_strong_footer = bool(re.search(r'(©|copyright|all rights reserved).*?' + re.escape(norm_buyer), norm_text))
            if not has_strong_footer:
                return False, f"Third-party article phrasing detected on {domain} without official institutional ownership notice"

    # 2. Check for positive institutional ownership indicators:
    # A. Copyright or ownership notice: © / Copyright ... <Buyer Name>
    copyright_pattern = re.compile(r'(?:©|copyright|\(c\))\s*(?:\d{4}\s*[-–]\s*)?(?:\d{4})?\s*[^.\n]{0,40}' + re.escape(norm_buyer), re.IGNORECASE)
    if copyright_pattern.search(norm_text):
        return True, f"Official copyright/ownership notice for '{buyer_name}' on {domain}"

    # B. Explicit self-identification phrasing — ONLY admissible on the
    # registrable root page itself. On arbitrary pages (news, directories,
    # partner sites) such phrasing is merely a mention of the buyer.
    if is_root_page:
        self_id_patterns = [
            re.compile(r'\bwelcome to (?:the )?' + re.escape(norm_buyer) + r'\b'),
            re.compile(r'\bofficial (?:website|site|portal) of (?:the )?' + re.escape(norm_buyer) + r'\b'),
            re.compile(r'\b' + re.escape(norm_buyer) + r' is (?:a|an|the|canada\'s|ontario\'s|one of)\b'),
            re.compile(r'\bat ' + re.escape(norm_buyer) + r', (?:we|our)\b'),
            re.compile(r'\b' + re.escape(norm_buyer) + r' acknowledges (?:the|its|that)\b'),  # Canadian land acknowledgment
        ]
        for sip in self_id_patterns:
            if sip.search(norm_text):
                return True, f"Root page self-identity phrasing for '{buyer_name}' on {domain}"

    # C. Contact email with domain: e.g., @yorku.ca on the page for York University
    reg_d = get_registrable_domain(domain)
    email_pattern = re.compile(r'[a-zA-Z0-9._%+-]+@(?:[a-z0-9-]+\.)*' + re.escape(reg_d) + r'\b')
    if email_pattern.search(norm_text):
        return True, f"Official institutional contact email @{reg_d} on {domain} alongside '{buyer_name}'"

    return False, f"No affirmative institutional ownership notice or self-identity for '{buyer_name}' on {domain}"


def verify_buyer_domain_content(
    domain: str,
    buyer_name: str,
    page_text: str,
    jurisdiction_country: str | None = None,
    jurisdiction_subdivision: str | None = None,
    procurement_document_domains: Sequence[str] = (),
    fetch_root_fn: Callable[[str], str] | None = None,
) -> VerifiedOfficialDomain:
    """
    Analyze domain and page content to verify if the domain belongs to the resolved buyer.

    Requirements (BI-VALUE-2.4):
    1. Positive ownership proof is MANDATORY for OFFICIAL_BUYER:
       - Attributable procurement-package URL or email domain match, OR
       - Verified institutional root page affirmative self-identity, OR
       - Verified official parent/government authority.
       Weak signals (token in hostname, buyer name mentioned, correct country) together
       must NOT establish OFFICIAL_BUYER.
    2. Registrable root domain canonicalization:
       If candidate is execed.schulich.yorku.ca, verifies yorku.ca, establishing:
       observed_domain='execed.schulich.yorku.ca', registrable_domain='yorku.ca',
       canonical_buyer_domain='yorku.ca'.
    3. Rejects third-party platforms (MERX, Bonfire, etc.) as buyer domains.
    4. Rejects conflicting foreign jurisdictions.
    """
    d = normalize_domain(domain)
    if not d or is_adversarial_or_disallowed_domain(d):
        return VerifiedOfficialDomain(
            domain=d,
            buyer_name=buyer_name,
            authority_class=SourceAuthorityClass.DIFFERENT_ORGANIZATION,
            status=SourceAuthorityStatus.REJECTED,
            verification_method=DomainVerificationMethod.REJECTED.value,
            verification_evidence=f"Domain {d} matches disallowed or adversarial pattern.",
            observed_domain=d,
            registrable_domain=get_registrable_domain(d),
            canonical_buyer_domain=get_registrable_domain(d),
        )

    # 1. Government authority check
    gov_match = classify_government_domain(d, buyer_jurisdiction=jurisdiction_country)
    if gov_match:
        return gov_match

    reg_domain = get_registrable_domain(d)

    # 2. Check procurement document evidence first (Rank 1 positive proof).
    # Package evidence is only admissible when the registrable domain also
    # reflects the buyer identity (vendor / consultant / software URLs cited
    # inside an RFP must not become OFFICIAL_BUYER).
    if _domain_reflects_buyer(reg_domain, buyer_name):
        for p_dom in procurement_document_domains:
            norm_p = normalize_domain(p_dom)
            reg_p = get_registrable_domain(norm_p)
            if reg_domain and reg_domain == reg_p:
                return VerifiedOfficialDomain(
                    domain=d,
                    buyer_name=buyer_name,
                    authority_class=SourceAuthorityClass.OFFICIAL_BUYER,
                    status=SourceAuthorityStatus.VERIFIED,
                    verification_method=DomainVerificationMethod.PROCUREMENT_DOCUMENT_URL.value,
                    verification_evidence=f"Registrable domain {reg_domain} matches procurement package evidence domain {norm_p}.",
                    observed_domain=d,
                    registrable_domain=reg_domain,
                    canonical_buyer_domain=reg_domain,
                    jurisdiction_country=jurisdiction_country,
                    jurisdiction_subdivision=jurisdiction_subdivision,
                )

    # 3. Content check
    if not page_text or len(page_text.strip()) < 40:
        return VerifiedOfficialDomain(
            domain=d,
            buyer_name=buyer_name,
            authority_class=SourceAuthorityClass.UNVERIFIED,
            status=SourceAuthorityStatus.UNVERIFIED,
            verification_method=DomainVerificationMethod.UNVERIFIED.value,
            verification_evidence="Fetched page content was empty or insufficient for identity verification.",
            observed_domain=d,
            registrable_domain=reg_domain,
            canonical_buyer_domain=reg_domain,
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

    # Domain institutional naming check:
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
            verification_method=DomainVerificationMethod.REJECTED.value,
            verification_evidence=f"Domain {d} ({reg_domain}) does not reflect buyer entity identity '{buyer_name}'.",
            observed_domain=d,
            registrable_domain=reg_domain,
            canonical_buyer_domain=reg_domain,
        )

    # 4. Jurisdiction conflict detection
    cues_uk = bool(re.search(r'\b(united kingdom|uk|england|scotland|wales|london|yorkshire)\b', norm_text))
    cues_us = bool(re.search(r'\b(united states|usa|u\.s\.a\.|nebraska|texas|california|new york)\b', norm_text))
    cues_ca = bool(re.search(r'\b(canada|ontario|toronto|alberta|british columbia|quebec|ottawa|calgary)\b', norm_text))

    domain_uk = d.endswith(".uk") or d.endswith(".ac.uk")
    domain_us = d.endswith(".edu") or d.endswith(".gov") or d.endswith(".us")
    domain_ca = d.endswith(".ca")

    expected_ca = jurisdiction_country == "CA" or (jurisdiction_subdivision and jurisdiction_subdivision.startswith("CA"))

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
            verification_method=DomainVerificationMethod.REJECTED.value,
            verification_evidence=conflict_reason,
            observed_domain=d,
            registrable_domain=reg_domain,
            canonical_buyer_domain=reg_domain,
            jurisdiction_country="GB" if domain_uk or cues_uk else ("US" if domain_us or cues_us else None),
        )

    # 5. Full name requirement
    if not has_full_buyer_name:
        return VerifiedOfficialDomain(
            domain=d,
            buyer_name=buyer_name,
            authority_class=SourceAuthorityClass.UNVERIFIED,
            status=SourceAuthorityStatus.UNVERIFIED,
            verification_method=DomainVerificationMethod.UNVERIFIED.value,
            verification_evidence=f"Full organization name '{buyer_name}' not found in page text; token match rejected.",
            observed_domain=d,
            registrable_domain=reg_domain,
            canonical_buyer_domain=reg_domain,
        )

    # 6. Structural Positive Ownership Proof (BI-VALUE-2.4):
    # Weak signals (token in hostname + buyer name mentioned + correct country) alone MUST NOT establish OFFICIAL_BUYER.
    # We require positive proof of institutional ownership / self-identity.
    is_self_id, self_id_reason = is_positive_root_self_identity(page_text, buyer_name, d, is_root_page=False)

    # Verify the registrable ROOT page itself (e.g. execed.schulich.yorku.ca -> https://yorku.ca)
    if not is_self_id and fetch_root_fn:
        try:
            root_text = fetch_root_fn(f"https://{reg_domain}")
            is_self_id, self_id_reason = is_positive_root_self_identity(
                root_text, buyer_name, reg_domain, is_root_page=True,
            )
        except Exception as exc:
            self_id_reason = f"Root page fetch failed for {reg_domain}: {exc}"

    if not is_self_id:
        return VerifiedOfficialDomain(
            domain=d,
            buyer_name=buyer_name,
            authority_class=SourceAuthorityClass.UNVERIFIED,
            status=SourceAuthorityStatus.UNVERIFIED,
            verification_method=DomainVerificationMethod.UNVERIFIED.value,
            verification_evidence=f"Positive organizational ownership not established: {self_id_reason}",
            observed_domain=d,
            registrable_domain=reg_domain,
            canonical_buyer_domain=reg_domain,
            jurisdiction_country="CA" if (domain_ca or cues_ca) else None,
        )

    # 7. Positive verification confirmed
    detected_country = "CA" if (domain_ca or cues_ca) else ("GB" if (domain_uk or cues_uk) else ("US" if (domain_us or cues_us) else None))
    detected_subdiv = "CA-ON" if "ontario" in norm_text or "toronto" in norm_text else None

    return VerifiedOfficialDomain(
        domain=d,
        buyer_name=buyer_name,
        authority_class=SourceAuthorityClass.OFFICIAL_BUYER,
        status=SourceAuthorityStatus.VERIFIED,
        verification_method=DomainVerificationMethod.OFFICIAL_ROOT_PAGE_IDENTITY.value,
        verification_evidence=f"Verified institutional ownership: {self_id_reason}",
        observed_domain=d,
        registrable_domain=reg_domain,
        canonical_buyer_domain=reg_domain,
        jurisdiction_country=detected_country or jurisdiction_country,
        jurisdiction_subdivision=detected_subdiv or jurisdiction_subdivision,
    )


def discover_and_verify_buyer_domain(
    buyer_name: str,
    *,
    jurisdiction_country: str | None = None,
    jurisdiction_subdivision: str | None = None,
    procurement_document_domains: Sequence[str] = (),
    search_fn: Callable[[str], list[dict[str, str]]] | None = None,
    fetch_fn: Callable[[str], str] | None = None,
    max_discovery_searches: int = 1,
) -> tuple[VerifiedOfficialDomain | None, list[VerifiedOfficialDomain]]:
    """
    Bounded domain discovery stage:
    1. Check procurement package document domains first (Rank 1 positive proof).
    2. Query search provider specifically for the official buyer website.
    3. Filter candidates through initial disallowed and government checks.
    4. Fetch candidate homepage/about content and run verify_buyer_domain_content.
    5. Return (primary_verified_buyer_domain, all_evaluated_domains).
    """
    if not buyer_name or not buyer_name.strip():
        return None, []

    if search_fn is None or fetch_fn is None:
        import buyer_research_provider as brp
        search_fn = search_fn or brp.anthropic_search
        fetch_fn = fetch_fn or brp.anthropic_fetch

    evaluated: list[VerifiedOfficialDomain] = []

    # Check procurement document domains directly first
    for p_dom in procurement_document_domains:
        norm_p = normalize_domain(p_dom)
        if not norm_p or is_adversarial_or_disallowed_domain(norm_p):
            continue
        try:
            home_url = f"https://{norm_p}"
            p_text = fetch_fn(home_url)
        except Exception:
            p_text = ""
        ver = verify_buyer_domain_content(
            norm_p,
            buyer_name=buyer_name,
            page_text=p_text,
            jurisdiction_country=jurisdiction_country,
            jurisdiction_subdivision=jurisdiction_subdivision,
            procurement_document_domains=procurement_document_domains,
            fetch_root_fn=fetch_fn,
        )
        evaluated.append(ver)
        if ver.is_official_buyer:
            return ver, evaluated

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
                    observed_domain=d,
                    registrable_domain=get_registrable_domain(d),
                    canonical_buyer_domain=get_registrable_domain(d),
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
            procurement_document_domains=procurement_document_domains,
            fetch_root_fn=fetch_fn,
        )
        evaluated.append(ver)
        if ver.is_official_buyer:
            return ver, evaluated

    # If no official buyer domain found
    return None, evaluated
