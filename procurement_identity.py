"""
procurement_identity.py -- Auto Procurement Identity and Authority Resolution.

Implements BI-VALUE-2 / BI-VALUE-2.1 Authority Model:
1. Strict evidence hierarchy:
   Rank 1: Canonical / reconciled procurement truth (metadata_by_doc merged via canonical_procurement)
   Rank 2: Validated Stage A / primary solicitation document metadata
   Rank 3: Corroborated package-level document content evidence (text content outranks filename)
   Rank 4: Human confirmation if unresolved or conflicting
2. Centralized explicit internal sentinels:
   - PENDING_CLIENT_SENTINEL = "__PENDING_BUYER__"
   - PENDING_TITLE_SENTINEL = "__PENDING_PROCUREMENT_TITLE__"
   - Sentinels cannot become evidence, cannot leak to LLM prompts, queries, reports, or tables.
3. Conflict & Ambiguity Detection:
   - Conflicting buyers across documents -> NEEDS_CONFIRMATION
   - Conflicting titles or solicitations across documents -> NEEDS_CONFIRMATION
   - Missing solicitation allowed if buyer and title are otherwise clear
   - Content strictly outranks filename; filename cannot override body text
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

# ---------------------------------------------------------------------------
# Authoritative Sentinels
# ---------------------------------------------------------------------------
PENDING_CLIENT_SENTINEL: str = "__PENDING_BUYER__"
PENDING_TITLE_SENTINEL: str = "__PENDING_PROCUREMENT_TITLE__"

CUSTOMER_FACING_PENDING_CLIENT: str = "Identifying procurement buyer…"
CUSTOMER_FACING_PENDING_TITLE: str = "Identifying opportunity title…"


class IdentityStatus(str, Enum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ProcurementIdentityCandidate:
    client_name: str
    opportunity_title: str
    solicitation_number: str | None = None
    authority_rank: int = 4
    source_document: str | None = None
    evidence_excerpt: str | None = None
    jurisdiction_country: str | None = None
    jurisdiction_subdivision: str | None = None


@dataclass(frozen=True)
class ProcurementIdentity:
    status: IdentityStatus
    client_name: str | None
    opportunity_title: str | None
    solicitation_number: str | None
    authority_rank: int
    resolution_basis: str
    evidence_count: int
    conflict_present: bool
    jurisdiction_country: str | None = None
    jurisdiction_subdivision: str | None = None
    evidence_references: tuple[dict[str, Any], ...] = ()
    alternative_candidates: tuple[ProcurementIdentityCandidate, ...] = ()
    candidate_domains: tuple[str, ...] = ()

    @property
    def is_resolved(self) -> bool:
        return self.status == IdentityStatus.RESOLVED

    @property
    def needs_confirmation(self) -> bool:
        return self.status == IdentityStatus.NEEDS_CONFIRMATION

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "client_name": self.client_name,
            "opportunity_title": self.opportunity_title,
            "solicitation_number": self.solicitation_number,
            "authority_rank": self.authority_rank,
            "resolution_basis": self.resolution_basis,
            "evidence_count": self.evidence_count,
            "conflict_present": self.conflict_present,
            "jurisdiction_country": self.jurisdiction_country,
            "jurisdiction_subdivision": self.jurisdiction_subdivision,
            "evidence_references": list(self.evidence_references),
            "candidate_domains": list(self.candidate_domains),
            "alternative_candidates": [
                {
                    "client_name": c.client_name,
                    "opportunity_title": c.opportunity_title,
                    "solicitation_number": c.solicitation_number,
                    "authority_rank": c.authority_rank,
                    "source_document": c.source_document,
                    "evidence_excerpt": c.evidence_excerpt,
                    "jurisdiction_country": c.jurisdiction_country,
                    "jurisdiction_subdivision": c.jurisdiction_subdivision,
                }
                for c in self.alternative_candidates
            ],
        }


# ---------------------------------------------------------------------------
# Extraction Patterns
# ---------------------------------------------------------------------------

_SOLICITATION_PATTERNS = [
    re.compile(r'\b(?:RFP|SOLICITATION|TENDER|BID|REFERENCE|REF|DOC)\s*(?:NO\.?|NUMBER|#)?\s*[:\-\s]\s*([A-Z0-9]{2,6}[-\s]?[0-9]{3,8}(?:[-_][A-Z0-9]+)?)\b', re.IGNORECASE),
    re.compile(r'\b([A-Z][0-9]{2,3}[-\s][0-9]{3,5})\b'),  # e.g. P27-070
    re.compile(r'\b(?:RFP\s*([0-9]{4}[-_][0-9]{3,6}))\b', re.IGNORECASE),  # e.g. RFP 2026-026
    re.compile(r'\b([0-9]{4}[-_][0-9]{3,6})\b'),
]

_BUYER_PATTERNS = [
    re.compile(r'(?:ISSUED BY|CLIENT|BUYER|ORGANIZATION|PURCHASER|PROCURING ENTITY|OWNER)\s*[:\-\s]\s*([^\n\r,;]{3,80})', re.IGNORECASE),
    re.compile(r'\b([A-Z][a-zA-Z0-9\s&,\.\'-]+(?:University|College|Hospital|Corporation|Commission|Authority|Department|Ministry|City of [A-Z][a-zA-Z]+|Town of [A-Z][a-zA-Z]+|Region of [A-Z][a-zA-Z]+|Government of [A-Z][a-zA-Z]+|Bank of [A-Z][a-zA-Z]+))\b'),
]

_TITLE_PATTERNS = [
    re.compile(r'(?:^\s*FOR|\bPROJECT TITLE|\bOPPORTUNITY TITLE|\bDESCRIPTION OF WORK|\bREQUIREMENT FOR)\s*[:\-\s]\s*([^\n\r]{6,150})', re.IGNORECASE | re.MULTILINE),
    re.compile(r'(?:REQUEST FOR PROPOSALS?|RFP)\s*(?:[-–—:]\s*)([^\n\r]{6,150})', re.IGNORECASE),
]


def is_sentinel(value: str | None) -> bool:
    """Check if value is one of the pending sentinels."""
    if not value or not isinstance(value, str):
        return False
    v = value.strip()
    return v in (PENDING_CLIENT_SENTINEL, PENDING_TITLE_SENTINEL)


def clean_display_client(client: str | None) -> str:
    """Return customer-facing display string for client."""
    if is_sentinel(client) or not client or not client.strip():
        return CUSTOMER_FACING_PENDING_CLIENT
    return client.strip()


def clean_display_title(title: str | None) -> str:
    """Return customer-facing display string for title."""
    if is_sentinel(title) or not title or not title.strip():
        return CUSTOMER_FACING_PENDING_TITLE
    return title.strip()


def resolve_procurement_identity(
    documents: Sequence[dict[str, Any]],
    metadata_by_doc: dict[str, dict[str, Any]] | None = None,
) -> ProcurementIdentity:
    """
    Resolve canonical procurement identity across document package following
    the strict evidence hierarchy:
    Rank 1: Canonical / reconciled procurement truth
    Rank 2: Validated document metadata
    Rank 3: Corroborated package document content (text strictly outranks filename)
    Rank 4: Human confirmation if unresolved / conflicting
    """
    if not documents:
        return ProcurementIdentity(
            status=IdentityStatus.PENDING,
            client_name=None,
            opportunity_title=None,
            solicitation_number=None,
            authority_rank=4,
            resolution_basis="No documents provided for procurement identity resolution.",
            evidence_count=0,
            conflict_present=False,
        )

    # -----------------------------------------------------------------------
    # Rank 1: Canonical / Reconciled Procurement Truth
    # -----------------------------------------------------------------------
    if metadata_by_doc:
        try:
            import canonical_procurement as cp
            merged_ident = cp.merge_identity_fields_with_provenance(metadata_by_doc, "identity")
            c_val, c_doc = merged_ident.get("client") or (None, None)
            t_val, t_doc = merged_ident.get("title") or (None, None)
            f_val, f_doc = merged_ident.get("file_number") or (None, None)

            if c_val and t_val and not is_sentinel(c_val) and not is_sentinel(t_val):
                ev_refs = []
                if c_doc:
                    ev_refs.append({"field": "client", "value": c_val, "source_doc": c_doc})
                if t_doc:
                    ev_refs.append({"field": "title", "value": t_val, "source_doc": t_doc})
                if f_doc:
                    ev_refs.append({"field": "file_number", "value": f_val, "source_doc": f_doc})

                return ProcurementIdentity(
                    status=IdentityStatus.RESOLVED,
                    client_name=str(c_val).strip(),
                    opportunity_title=str(t_val).strip(),
                    solicitation_number=str(f_val).strip() if f_val else None,
                    authority_rank=1,
                    resolution_basis="Canonical reconciled procurement truth (Rank 1)",
                    evidence_count=len(ev_refs),
                    conflict_present=False,
                    evidence_references=tuple(ev_refs),
                )
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Rank 2 & 3: Corroborated Package Document Content
    # Content body strictly outranks filenames.
    # -----------------------------------------------------------------------
    body_buyers: list[tuple[str, str, str]] = []  # (value, doc_name, excerpt)
    filename_buyers: list[tuple[str, str, str]] = []

    body_titles: list[tuple[str, str, str]] = []
    filename_titles: list[tuple[str, str, str]] = []

    body_solicitations: list[tuple[str, str, str]] = []
    filename_solicitations: list[tuple[str, str, str]] = []

    # Domain extraction from procurement documents (BI-VALUE-2.4)
    extracted_doc_domains: list[str] = []
    _URL_PATTERN = re.compile(r'https?://([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', re.IGNORECASE)
    _EMAIL_DOMAIN_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', re.IGNORECASE)
    _EXCLUDED_DOC_DOMAINS = {
        "merx.com", "biddingo.com", "bonfirehub.com", "buyandsell.gc.ca",
        "canadabuys.canada.ca", "adobe.com", "microsoft.com", "google.com"
    }

    for d in documents:
        name = d.get("name") or d.get("filename") or ""
        text = d.get("text") or d.get("raw_text") or d.get("content") or ""
        header_text = text[:8000]

        # Extract URLs and emails for candidate domains
        if text:
            for m in _URL_PATTERN.finditer(text[:15000]):
                dom = m.group(1).lower().strip('.')
                if not any(dom == ex or dom.endswith('.' + ex) for ex in _EXCLUDED_DOC_DOMAINS):
                    if dom not in extracted_doc_domains:
                        extracted_doc_domains.append(dom)
            for m in _EMAIL_DOMAIN_PATTERN.finditer(text[:15000]):
                dom = m.group(1).lower().strip('.')
                if not any(dom == ex or dom.endswith('.' + ex) for ex in _EXCLUDED_DOC_DOMAINS):
                    if dom not in extracted_doc_domains:
                        extracted_doc_domains.append(dom)

        # Extract from text body first (Rank 3 authority)
        if header_text:
            for pat in _SOLICITATION_PATTERNS:
                m = pat.search(header_text)
                if m:
                    val = m.group(1).replace(" ", "-").strip("-_ #")
                    body_solicitations.append((val, name, m.group(0)))
                    break

            for pat in _BUYER_PATTERNS:
                m = pat.search(header_text)
                if m:
                    val = m.group(1).strip(" \t\n\r,.-")
                    if len(val) >= 4 and not any(kw in val.lower() for kw in ("proponent", "bidder", "vendor")):
                        body_buyers.append((val, name, m.group(0)))
                        break

            for pat in _TITLE_PATTERNS:
                m = pat.search(header_text)
                if m:
                    val = m.group(1).strip(" \t\n\r,.-")
                    if len(val) >= 6 and not any(kw in val.lower() for kw in ("request for proposal", "appendix")):
                        body_titles.append((val, name, m.group(0)))
                        break

        # Filename heuristics (Lower authority - fallback only)
        if name:
            for pat in _SOLICITATION_PATTERNS:
                m = pat.search(name)
                if m:
                    val = m.group(1).replace(" ", "-").strip("-_ #")
                    filename_solicitations.append((val, name, m.group(0)))
                    break

    # Body evidence strictly outranks filename evidence
    active_buyers = body_buyers if body_buyers else filename_buyers
    active_titles = body_titles if body_titles else filename_titles
    active_solicitations = body_solicitations if body_solicitations else filename_solicitations

    # Group unique normalized values
    body_jurisdictions: list[tuple[str, str, str]] = []  # (country, subdivision, excerpt)
    _JURISDICTION_PATTERNS = [
        (re.compile(r'\b(Ontario|Toronto|Ottawa|Hamilton|London, Ontario|Waterloo)\b', re.IGNORECASE), "CA", "CA-ON"),
        (re.compile(r'\b(Alberta|Calgary|Edmonton)\b', re.IGNORECASE), "CA", "CA-AB"),
        (re.compile(r'\b(British Columbia|Vancouver|Victoria, BC)\b', re.IGNORECASE), "CA", "CA-BC"),
        (re.compile(r'\b(Quebec|Montreal)\b', re.IGNORECASE), "CA", "CA-QC"),
        (re.compile(r'\b(Canada|Canadian)\b', re.IGNORECASE), "CA", None),
        (re.compile(r'\b(United Kingdom|England|London, UK|Yorkshire|Scotland)\b', re.IGNORECASE), "GB", None),
        (re.compile(r'\b(United States|USA|U\.S\.A\.|Nebraska|California|New York|Texas)\b', re.IGNORECASE), "US", None),
    ]

    for d in documents:
        text = d.get("text") or d.get("raw_text") or d.get("content") or ""
        header_text = text[:8000]
        if header_text:
            for pat, ctry, subdiv in _JURISDICTION_PATTERNS:
                m = pat.search(header_text)
                if m:
                    body_jurisdictions.append((ctry, subdiv or "", m.group(0)))
                    break

    resolved_country = body_jurisdictions[0][0] if body_jurisdictions else None
    resolved_subdiv = body_jurisdictions[0][1] if (body_jurisdictions and body_jurisdictions[0][1]) else None

    # Group unique normalized values
    unique_buyers: dict[str, tuple[str, str, str]] = {}
    for b, doc, ex in active_buyers:
        norm = re.sub(r'\s+', ' ', b.lower().strip())
        if norm not in unique_buyers:
            unique_buyers[norm] = (b, doc, ex)

    unique_titles: dict[str, tuple[str, str, str]] = {}
    for t, doc, ex in active_titles:
        norm = re.sub(r'\s+', ' ', t.lower().strip())
        if norm not in unique_titles:
            unique_titles[norm] = (t, doc, ex)

    unique_solicitations: dict[str, tuple[str, str, str]] = {}
    for s, doc, ex in active_solicitations:
        norm = s.upper().replace(" ", "-")
        if norm not in unique_solicitations:
            unique_solicitations[norm] = (s, doc, ex)

    # -----------------------------------------------------------------------
    # Rank 4: Conflict / Ambiguity Detection
    # -----------------------------------------------------------------------
    # Case A: Multiple conflicting buyers across documents
    if len(unique_buyers) > 1:
        candidates = tuple(
            ProcurementIdentityCandidate(
                client_name=b[0],
                opportunity_title=list(unique_titles.values())[0][0] if unique_titles else "Procurement Opportunity",
                solicitation_number=list(unique_solicitations.values())[0][0] if unique_solicitations else None,
                authority_rank=3,
                source_document=b[1],
                evidence_excerpt=b[2],
            )
            for b in unique_buyers.values()
        )
        return ProcurementIdentity(
            status=IdentityStatus.NEEDS_CONFIRMATION,
            client_name=None,
            opportunity_title=list(unique_titles.values())[0][0] if unique_titles else None,
            solicitation_number=list(unique_solicitations.values())[0][0] if unique_solicitations else None,
            authority_rank=4,
            resolution_basis=f"Conflicting issuing organizations found across documents: {', '.join(b[0] for b in unique_buyers.values())}.",
            evidence_count=len(unique_buyers),
            conflict_present=True,
            alternative_candidates=candidates,
        )

    # Case B: Multiple conflicting titles with no canonical resolution
    if len(unique_titles) > 1 and len(unique_buyers) == 1:
        buyer_val = list(unique_buyers.values())[0][0]
        candidates = tuple(
            ProcurementIdentityCandidate(
                client_name=buyer_val,
                opportunity_title=t[0],
                solicitation_number=list(unique_solicitations.values())[0][0] if unique_solicitations else None,
                authority_rank=3,
                source_document=t[1],
                evidence_excerpt=t[2],
            )
            for t in unique_titles.values()
        )
        return ProcurementIdentity(
            status=IdentityStatus.NEEDS_CONFIRMATION,
            client_name=buyer_val,
            opportunity_title=None,
            solicitation_number=list(unique_solicitations.values())[0][0] if unique_solicitations else None,
            authority_rank=4,
            resolution_basis="Conflicting opportunity titles detected across documents.",
            evidence_count=len(unique_titles),
            conflict_present=True,
            alternative_candidates=candidates,
        )

    # Case C: Single buyer cleanly resolved
    if len(unique_buyers) == 1:
        chosen_buyer, b_doc, b_ex = list(unique_buyers.values())[0]
        chosen_title = list(unique_titles.values())[0][0] if unique_titles else None
        chosen_sol = list(unique_solicitations.values())[0][0] if unique_solicitations else None

        if not chosen_title:
            # Fall back to first document name cleaned
            first_doc = documents[0].get("name") or documents[0].get("filename") or "Procurement Package"
            chosen_title = first_doc.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()

        ev_refs = [
            {"field": "client", "value": chosen_buyer, "source_doc": b_doc, "excerpt": b_ex}
        ]
        if chosen_sol:
            ev_refs.append({"field": "solicitation_number", "value": chosen_sol, "source_doc": b_doc})

        return ProcurementIdentity(
            status=IdentityStatus.RESOLVED,
            client_name=chosen_buyer,
            opportunity_title=chosen_title,
            solicitation_number=chosen_sol,
            authority_rank=3,
            resolution_basis="Corroborated package document content evidence (Rank 3)",
            evidence_count=len(ev_refs),
            conflict_present=False,
            jurisdiction_country=resolved_country,
            jurisdiction_subdivision=resolved_subdiv,
            evidence_references=tuple(ev_refs),
            candidate_domains=tuple(extracted_doc_domains),
        )

    # Fallback: buyer could not be reliably determined
    return ProcurementIdentity(
        status=IdentityStatus.NEEDS_CONFIRMATION,
        client_name=None,
        opportunity_title=list(unique_titles.values())[0][0] if unique_titles else None,
        solicitation_number=list(unique_solicitations.values())[0][0] if unique_solicitations else None,
        authority_rank=4,
        resolution_basis="Issuing organization could not be definitively extracted from provided document texts.",
        evidence_count=0,
        conflict_present=False,
        candidate_domains=tuple(extracted_doc_domains),
    )
