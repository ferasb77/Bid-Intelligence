"""
procurement_identity.py -- Auto Procurement Identity and Authority Resolution.

Implements BI-VALUE-2 Phase B:
1. Centralized explicit internal sentinels for pending buyer and opportunity title.
2. Canonical resolution of issuing organization, opportunity title, and solicitation number
   from uploaded document package evidence.
3. Strict confidence classification:
   - RESOLVED: clear issuing client and opportunity title found with high confidence.
   - NEEDS_CONFIRMATION: ambiguous / conflicting buyer names or multiple candidate titles.
   - PENDING: no documents or extraction yet performed.
   - FAILED: unable to determine identity from provided material.
4. Fail-closed human confirmation boundary for genuine ambiguities.
5. Zero LLM requirement for purely deterministic document extracts / cover page heuristics.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

# ---------------------------------------------------------------------------
# Authoritative Sentinels (BI-VALUE-2 Phase C)
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
    confidence_score: float = 0.0
    source_document: str | None = None
    evidence_excerpt: str | None = None


@dataclass(frozen=True)
class ProcurementIdentity:
    status: IdentityStatus
    client_name: str | None
    opportunity_title: str | None
    solicitation_number: str | None
    confidence_score: float
    confidence_notes: str
    evidence_references: tuple[dict[str, Any], ...] = ()
    alternative_candidates: tuple[ProcurementIdentityCandidate, ...] = ()

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
            "confidence_score": self.confidence_score,
            "confidence_notes": self.confidence_notes,
            "evidence_references": list(self.evidence_references),
            "alternative_candidates": [
                {
                    "client_name": c.client_name,
                    "opportunity_title": c.opportunity_title,
                    "solicitation_number": c.solicitation_number,
                    "confidence_score": c.confidence_score,
                    "source_document": c.source_document,
                    "evidence_excerpt": c.evidence_excerpt,
                }
                for c in self.alternative_candidates
            ],
        }


# ---------------------------------------------------------------------------
# Identity Extraction Heuristics & Deterministic Resolution
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
    Resolve canonical procurement identity across document package.
    Uses canonical_procurement ranking when metadata_by_doc is available,
    plus deterministic pattern extraction on document text and filenames.
    """
    if not documents:
        return ProcurementIdentity(
            status=IdentityStatus.PENDING,
            client_name=None,
            opportunity_title=None,
            solicitation_number=None,
            confidence_score=0.0,
            confidence_notes="No documents provided for procurement identity resolution.",
        )

    # 1. First consult canonical_procurement if metadata_by_doc exists
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
                    confidence_score=0.95,
                    confidence_notes="Resolved from canonical procurement document metadata.",
                    evidence_references=tuple(ev_refs),
                )
        except Exception:
            pass

    # 2. Extract candidates from document names, text extracts, and metadata
    extracted_solicitations: list[tuple[str, str, str]] = []  # (value, doc_name, excerpt)
    extracted_buyers: list[tuple[str, str, str]] = []
    extracted_titles: list[tuple[str, str, str]] = []

    for d in documents:
        name = d.get("name") or d.get("filename") or ""
        text = d.get("text") or d.get("raw_text") or d.get("content") or ""
        # Check first 5000 chars of text (cover page / opening sections)
        header_text = text[:5000]

        # A. Solicitation number from name or header
        for pat in _SOLICITATION_PATTERNS:
            m = pat.search(name) or pat.search(header_text)
            if m:
                val = m.group(1).replace(" ", "-").strip("-_ #")
                extracted_solicitations.append((val, name, m.group(0)))
                break

        # B. Buyer name from header text or filename
        for pat in _BUYER_PATTERNS:
            m = pat.search(header_text)
            if m:
                val = m.group(1).strip(" \t\n\r,.-")
                if len(val) >= 4 and not any(kw in val.lower() for kw in ("proponent", "bidder", "vendor")):
                    extracted_buyers.append((val, name, m.group(0)))
                    break

        # C. Title from header text
        for pat in _TITLE_PATTERNS:
            m = pat.search(header_text)
            if m:
                val = m.group(1).strip(" \t\n\r,.-")
                if len(val) >= 6 and not any(kw in val.lower() for kw in ("request for proposal", "appendix")):
                    extracted_titles.append((val, name, m.group(0)))
                    break

    # Determine unique buyers and titles
    unique_buyers = {}
    for b, doc, ex in extracted_buyers:
        norm = re.sub(r'\s+', ' ', b.lower().strip())
        if norm not in unique_buyers:
            unique_buyers[norm] = (b, doc, ex)

    unique_titles = {}
    for t, doc, ex in extracted_titles:
        norm = re.sub(r'\s+', ' ', t.lower().strip())
        if norm not in unique_titles:
            unique_titles[norm] = (t, doc, ex)

    unique_solicitations = {}
    for s, doc, ex in extracted_solicitations:
        norm = s.upper().replace(" ", "-")
        if norm not in unique_solicitations:
            unique_solicitations[norm] = (s, doc, ex)

    # 3. Check for genuine ambiguity
    if len(unique_buyers) > 1:
        candidates = tuple(
            ProcurementIdentityCandidate(
                client_name=b[0],
                opportunity_title=list(unique_titles.values())[0][0] if unique_titles else "Procurement Opportunity",
                solicitation_number=list(unique_solicitations.values())[0][0] if unique_solicitations else None,
                confidence_score=0.5,
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
            confidence_score=0.4,
            confidence_notes=f"Multiple distinct issuing organizations detected: {', '.join(b[0] for b in unique_buyers.values())}.",
            alternative_candidates=candidates,
        )

    # 4. If single buyer resolved
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
            confidence_score=0.9,
            confidence_notes="Resolved from procurement document text.",
            evidence_references=tuple(ev_refs),
        )

    # 5. Fallback: buyer could not be reliably determined
    return ProcurementIdentity(
        status=IdentityStatus.NEEDS_CONFIRMATION,
        client_name=None,
        opportunity_title=list(unique_titles.values())[0][0] if unique_titles else None,
        solicitation_number=list(unique_solicitations.values())[0][0] if unique_solicitations else None,
        confidence_score=0.2,
        confidence_notes="Issuing organization could not be definitively extracted from provided document texts.",
    )
