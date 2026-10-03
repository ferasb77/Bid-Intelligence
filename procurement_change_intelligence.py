"""
procurement_change_intelligence.py -- PCI-A.1: Procurement Revision Foundation &
Deterministic Change Model (Durable & Invariant-Closed).

PHASE 1 ONLY:
- Revision Foundation (Revision 0 baseline + additive buyer revisions)
- System Revision (monotonic applied counter) vs Buyer Chronology (buyer sequence)
- Deterministic Change Model (bounded change taxonomy, field-level precedence)
- Replay & Authoritative Current State derivation
- Out-of-order and duplicate upload resilience (idempotency across restarts)
- Stable semantic fingerprinting (excludes timestamps, DB row IDs, revision numbers)
- Durable persistence adapter over existing migration 010 schema (bids, procurement_update_reviews,
  procurement_update_review_documents, procurement_changes, procurement_conflicts)
- Real content hash required (fail closed on missing content_hash)
- Tenancy verification against persisted ownership
- Optimistic database-level concurrency (expected_base_revision)

Pure, deterministic, fail-closed. No model calls.
Does NOT modify prompts, UI, brief generation, or CHECK.
Reuses existing database schema (migration 010 governance precedent) without DDL changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import copy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
import threading
from types import MappingProxyType
from typing import Any, Sequence

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# 1. Closed Vocabularies
# ═══════════════════════════════════════════════════════════════════════════

# Document-level change types (Section 7)
DOC_CHANGE_ORIGINAL_RFP = "ORIGINAL_RFP"
DOC_CHANGE_ADDENDUM = "ADDENDUM"
DOC_CHANGE_AMENDMENT = "AMENDMENT"
DOC_CHANGE_Q_AND_A = "Q_AND_A"
DOC_CHANGE_CLARIFICATION = "CLARIFICATION"
DOC_CHANGE_REVISED_FORM = "REVISED_FORM"
DOC_CHANGE_REPLACEMENT_DOCUMENT = "REPLACEMENT_DOCUMENT"
DOC_CHANGE_BUYER_NOTICE = "BUYER_NOTICE"

DOCUMENT_CHANGE_TYPES = (
    DOC_CHANGE_ORIGINAL_RFP,
    DOC_CHANGE_ADDENDUM,
    DOC_CHANGE_AMENDMENT,
    DOC_CHANGE_Q_AND_A,
    DOC_CHANGE_CLARIFICATION,
    DOC_CHANGE_REVISED_FORM,
    DOC_CHANGE_REPLACEMENT_DOCUMENT,
    DOC_CHANGE_BUYER_NOTICE,
)

# Fact-level change semantics taxonomy (Section 8)
CHANGE_ADDS = "ADDS"
CHANGE_REMOVES = "REMOVES"
CHANGE_SUPERSEDES = "SUPERSEDES"
CHANGE_REPLACES = "REPLACES"
CHANGE_CORRECTS = "CORRECTS"
CHANGE_CLARIFIES = "CLARIFIES"
CHANGE_NARROWS = "NARROWS"
CHANGE_EXPANDS = "EXPANDS"
CHANGE_CONFLICTS_WITH = "CONFLICTS_WITH"
CHANGE_UNCHANGED = "UNCHANGED"

FACT_CHANGE_TYPES = (
    CHANGE_ADDS,
    CHANGE_REMOVES,
    CHANGE_SUPERSEDES,
    CHANGE_REPLACES,
    CHANGE_CORRECTS,
    CHANGE_CLARIFIES,
    CHANGE_NARROWS,
    CHANGE_EXPANDS,
    CHANGE_CONFLICTS_WITH,
    CHANGE_UNCHANGED,
)

# Authority status
AUTHORITY_CURRENT = "CURRENT"
AUTHORITY_SUPERSEDED = "SUPERSEDED"
AUTHORITY_AMBIGUOUS = "AMBIGUOUS"
AUTHORITY_REMOVED = "REMOVED"
AUTHORITY_UNCHANGED = "UNCHANGED"

AUTHORITY_STATUSES = (
    AUTHORITY_CURRENT,
    AUTHORITY_SUPERSEDED,
    AUTHORITY_AMBIGUOUS,
    AUTHORITY_REMOVED,
    AUTHORITY_UNCHANGED,
)

# Review status (Section 10)
REVIEW_STATUS_APPROVED = "APPROVED"
REVIEW_STATUS_PENDING = "PENDING"
REVIEW_STATUS_REJECTED = "REJECTED"
REVIEW_STATUS_HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"

REVIEW_STATUSES = (
    REVIEW_STATUS_APPROVED,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_REJECTED,
    REVIEW_STATUS_HUMAN_REVIEW_REQUIRED,
)

# Outcome constants
OUTCOME_REVISION_CREATED = "REVISION_CREATED"
OUTCOME_NO_NEW_REVISION = "NO_NEW_REVISION"
OUTCOME_NEW_REVISION_NO_SEMANTIC_CHANGE = "NEW_REVISION_NO_SEMANTIC_CHANGE"
OUTCOME_ORDERING_REVIEW_REQUIRED = "ORDERING_REVIEW_REQUIRED"

# Specialist domain vocabulary (Reused from full_analysis.py)
SPECIALIST_PROCUREMENT_STRUCTURE = "PROCUREMENT_STRUCTURE"
SPECIALIST_REQUIREMENTS_COMPLIANCE = "REQUIREMENTS_COMPLIANCE"
SPECIALIST_EVALUATION_INTELLIGENCE = "EVALUATION_INTELLIGENCE"
SPECIALIST_SCOPE_DELIVERABLES = "SCOPE_DELIVERABLES"
SPECIALIST_COMMERCIAL_CONTRACTUAL = "COMMERCIAL_CONTRACTUAL"
SPECIALIST_SCHEDULE_SUBMISSION = "SCHEDULE_SUBMISSION"

SPECIALIST_DOMAINS = (
    SPECIALIST_PROCUREMENT_STRUCTURE,
    SPECIALIST_REQUIREMENTS_COMPLIANCE,
    SPECIALIST_EVALUATION_INTELLIGENCE,
    SPECIALIST_SCOPE_DELIVERABLES,
    SPECIALIST_COMMERCIAL_CONTRACTUAL,
    SPECIALIST_SCHEDULE_SUBMISSION,
)

# Finding PCI Statuses (Section 10)
FINDING_STATUS_RETAINED = "RETAINED"
FINDING_STATUS_STALE = "STALE"
FINDING_STATUS_UNRESOLVED = "UNRESOLVED"

FINDING_PCI_STATUSES = (
    FINDING_STATUS_RETAINED,
    FINDING_STATUS_STALE,
    FINDING_STATUS_UNRESOLVED,
)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Exceptions
# ═══════════════════════════════════════════════════════════════════════════

class PCIEngineError(Exception):
    """Base error for Procurement Change Intelligence."""


class StaleRevisionError(PCIEngineError):
    """Raised when expected base revision does not match current state."""


class TenancyViolationError(PCIEngineError):
    """Raised when a cross-organization or cross-bid boundary is breached."""


class ChronologyConflictError(PCIEngineError):
    """Raised when revision chronology cannot be resolved safely without human review."""


class ImmutableRevisionError(PCIEngineError):
    """Raised when an illegal attempt is made to mutate historical revision records."""


class PCIContextNotEligibleError(PCIEngineError):
    """Raised when a revision or specialist domain is not eligible for revision-aware specialist context."""


class PCIContextBindingError(PCIEngineError):
    """Raised when a procurement change cannot be safely or deterministically bound to canonical objects."""


class RevisionNotCurrentError(PCIEngineError):
    """Raised when an incremental Full Analysis is requested for a revision
    that is not the latest applied revision (Requirement 1: REVISION_NOT_CURRENT)."""


# ═══════════════════════════════════════════════════════════════════════════
# 3. Document Classification & Chronology Extraction (Sections 5 & 7)
# ═══════════════════════════════════════════════════════════════════════════

_ADDENDUM_NUM_RE = re.compile(r'(?:addend(?:um|a)|bulletin)[_\s]*#?[_\s]*0*(\d+)\b', re.IGNORECASE)
_AMENDMENT_NUM_RE = re.compile(r'(?:amendment|amend)[_\s]*#?[_\s]*0*(\d+)\b', re.IGNORECASE)
_QA_NUM_RE = re.compile(r'(?:clarifications?|q\s*&?\s*a|round)[_\s]*#?[_\s]*0*(\d+)\b', re.IGNORECASE)
_VERSION_NUM_RE = re.compile(r'[_\-\s](?:v|rev|version)[_\s]*0*(\d+)\b', re.IGNORECASE)
_QA_RE = re.compile(r'\b(?:q\s*&?\s*a|questions?\s+(?:and|&)\s+answers?)\b', re.IGNORECASE)
_CLARIFICATION_RE = re.compile(r'\bclarifications?\b', re.IGNORECASE)
_REPLACEMENT_RE = re.compile(r'\b(?:replacement|replaces?|supersed(?:es?|ing))\b', re.IGNORECASE)
_REVISED_FORM_RE = re.compile(r'\b(?:revised|amended)\s+(?:form|appendix|schedule|annex|pricing|submission)\b', re.IGNORECASE)
_DATE_ISO_RE = re.compile(r'\b(\d{4}-\d{2}-\d{2})\b')
_DATE_MONTH_RE = re.compile(
    r'\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|'
    r'Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2}),?\s+(\d{4})\b',
    re.IGNORECASE
)

_MONTH_MAP = {
    "jan": "01", "january": "01",
    "feb": "02", "february": "02",
    "mar": "03", "march": "03",
    "apr": "04", "april": "04",
    "may": "05",
    "jun": "06", "june": "06",
    "jul": "07", "july": "07",
    "aug": "08", "august": "08",
    "sep": "09", "september": "09",
    "oct": "10", "october": "10",
    "nov": "11", "november": "11",
    "dec": "12", "december": "12",
}


def classify_document_change_type(
    filename: str,
    doc_type: str | None = None,
    content_sample: str | None = None,
) -> str:
    """Classifies a document into the bounded document-level change taxonomy.
    Never relies solely on filename extensions."""
    name = (filename or "").strip()
    sample = (content_sample or "").strip()
    combined = f"{name} {sample}".lower()

    if _REPLACEMENT_RE.search(combined):
        return DOC_CHANGE_REPLACEMENT_DOCUMENT
    if _REVISED_FORM_RE.search(combined):
        return DOC_CHANGE_REVISED_FORM
    if _AMENDMENT_NUM_RE.search(name):
        return DOC_CHANGE_AMENDMENT
    if _ADDENDUM_NUM_RE.search(name):
        return DOC_CHANGE_ADDENDUM
    if _QA_RE.search(combined):
        return DOC_CHANGE_Q_AND_A
    if _CLARIFICATION_RE.search(combined):
        return DOC_CHANGE_CLARIFICATION
    if "notice" in combined or "bulletin" in combined:
        return DOC_CHANGE_BUYER_NOTICE
    if doc_type and "rfp" in doc_type.lower():
        return DOC_CHANGE_ORIGINAL_RFP
    if "rfp" in name.lower() or "solicitation" in name.lower():
        return DOC_CHANGE_ORIGINAL_RFP
    return DOC_CHANGE_BUYER_NOTICE


def extract_chronology_metadata(
    filename: str,
    buyer_issued_date: str | None = None,
    content_sample: str | None = None,
) -> dict[str, Any]:
    """Extracts sequence numbers and explicit dates to order revisions
    by buyer authority/chronology rather than upload time (Section 5)."""
    seq: int | None = None
    name = filename or ""
    combined = f"{name} {content_sample or ''}"

    add_match = _ADDENDUM_NUM_RE.search(name)
    if add_match:
        seq = int(add_match.group(1))
    else:
        amend_match = _AMENDMENT_NUM_RE.search(name)
        if amend_match:
            seq = int(amend_match.group(1))
        else:
            qa_match = _QA_NUM_RE.search(name)
            if qa_match:
                seq = int(qa_match.group(1))
            else:
                ver_match = _VERSION_NUM_RE.search(name)
                if ver_match:
                    seq = int(ver_match.group(1))

    # Parse date: priority to explicit buyer_issued_date, then content/filename
    parsed_date = buyer_issued_date
    if not parsed_date:
        iso_m = _DATE_ISO_RE.search(combined)
        if iso_m:
            parsed_date = iso_m.group(1)
        else:
            month_m = _DATE_MONTH_RE.search(combined)
            if month_m:
                mon = _MONTH_MAP.get(month_m.group(1).lower(), "01")
                day = f"{int(month_m.group(2)):02d}"
                yr = month_m.group(3)
                parsed_date = f"{yr}-{mon}-{day}"

    confidence = "high" if (seq is not None or parsed_date is not None) else "low"
    doc_change_type = classify_document_change_type(filename, content_sample=content_sample)

    return {
        "sequence_number": seq,
        "issued_date": parsed_date,
        "document_change_type": doc_change_type,
        "confidence": confidence,
    }


def compute_chronology_sort_key(meta: dict[str, Any], filename: str) -> tuple:
    """Deterministic tuple for sorting documents by buyer authority."""
    date_key = meta.get("issued_date") or "9999-99-99"
    seq_key = meta.get("sequence_number") if meta.get("sequence_number") is not None else 999999
    # If it's an original RFP, it sorts first
    is_rfp = 0 if meta.get("document_change_type") == DOC_CHANGE_ORIGINAL_RFP else 1
    return (is_rfp, date_key, seq_key, filename.lower())


# ═══════════════════════════════════════════════════════════════════════════
# 4. Fingerprinting (Section 12 & 15)
# ═══════════════════════════════════════════════════════════════════════════

def _canonical_json_hash(payload: Any) -> str:
    """SHA-256 over deterministic JSON without timestamps or volatile keys."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_fact_fingerprint(fact: FactChange) -> str:
    payload = {
        "entity_id": fact.entity_id,
        "fact_type": fact.fact_type,
        "change_type": fact.change_type,
        "before_value": fact.before_value,
        "after_value": fact.after_value,
        "source_hash": fact.source_hash,
        "authority_status": fact.authority_status,
    }
    return _canonical_json_hash(payload)


def compute_changeset_fingerprint(
    revision: int,
    prev_revision: int | None,
    changes: Sequence[FactChange],
    source_hashes: Sequence[str],
) -> str:
    payload = {
        "revision": revision,
        "prev_revision": prev_revision,
        "source_hashes": sorted(source_hashes),
        "changes": [
            {
                "entity_id": c.entity_id,
                "fact_type": c.fact_type,
                "change_type": c.change_type,
                "before": c.before_value,
                "after": c.after_value,
                "source_hash": c.source_hash,
                "authority_status": c.authority_status,
                "review_status": c.review_status,
            }
            for c in sorted(changes, key=lambda x: (x.entity_id, x.fact_type, x.change_type))
        ],
    }
    return _canonical_json_hash(payload)


def compute_revision_fingerprint(
    revision: int,
    parent_fp: str | None,
    source_hashes: Sequence[str],
    changeset_fp: str,
) -> str:
    """REVISION FINGERPRINT: Represents the exact node in the revision graph.
    Includes revision counter, parent fingerprint, source hashes, and changeset fingerprint."""
    payload = {
        "revision": revision,
        "parent_fp": parent_fp or "",
        "source_hashes": sorted(source_hashes),
        "changeset_fp": changeset_fp,
    }
    return _canonical_json_hash(payload)


def compute_state_fingerprint(
    bid_id: int,
    authoritative_facts: dict[str, FactChange],
    active_artifacts: dict[str, ArtifactRecord],
    current_revision: int | None = None,  # accepted for backwards-compatibility, excluded from payload
) -> str:
    """AUTHORITATIVE STATE FINGERPRINT (Section 12): Represents semantic current truth only.
    Strictly excludes revision numbers, artifact revision numbers, row IDs, and timestamps.
    Changes ONLY when semantic authoritative facts or active artifact identities change."""
    facts_payload = [
        {
            "entity_id": k,
            "fact_type": v.fact_type,
            "value": v.after_value,
            "authority_status": v.authority_status,
        }
        for k, v in sorted(authoritative_facts.items())
        if v.authority_status != AUTHORITY_REMOVED
    ]
    artifacts_payload = [
        {
            "artifact_id": k,
            "name": a.name,
            "content_hash": a.content_hash,
            "status": a.status,
        }
        for k, a in sorted(active_artifacts.items())
        if a.status == AUTHORITY_CURRENT
    ]
    payload = {
        "bid_id": bid_id,
        "facts": facts_payload,
        "artifacts": artifacts_payload,
    }
    return _canonical_json_hash(payload)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Core Data Structures (Sections 4, 8, 11, 13, 14)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class FactChange:
    """A bounded fact-level or artifact-level change."""
    change_type: str
    fact_type: str
    entity_id: str
    before_value: Any
    after_value: Any
    source_document: str
    source_hash: str
    source_document_id: int | None = None
    authority_status: str = AUTHORITY_CURRENT
    review_status: str = REVIEW_STATUS_APPROVED
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_type": self.change_type,
            "fact_type": self.fact_type,
            "entity_id": self.entity_id,
            "before_value": self.before_value,
            "after_value": self.after_value,
            "source_document": self.source_document,
            "source_hash": self.source_hash,
            "source_document_id": self.source_document_id,
            "authority_status": self.authority_status,
            "review_status": self.review_status,
            "metadata": copy.deepcopy(self.metadata),
        }
    as_dict = to_dict

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FactChange:
        return cls(
            change_type=data["change_type"],
            fact_type=data["fact_type"],
            entity_id=data["entity_id"],
            before_value=data.get("before_value"),
            after_value=data.get("after_value"),
            source_document=data.get("source_document", ""),
            source_hash=data.get("source_hash", ""),
            source_document_id=data.get("source_document_id"),
            authority_status=data.get("authority_status", AUTHORITY_CURRENT),
            review_status=data.get("review_status", REVIEW_STATUS_APPROVED),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class ArtifactRecord:
    """A buyer-issued file artifact (e.g. Appendix D Pricing Form)."""
    artifact_id: str
    name: str
    content_hash: str
    revision: int
    status: str = AUTHORITY_CURRENT
    replaces_artifact_id: str | None = None
    replaced_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "name": self.name,
            "content_hash": self.content_hash,
            "revision": self.revision,
            "status": self.status,
            "replaces_artifact_id": self.replaces_artifact_id,
            "replaced_by": self.replaced_by,
        }


@dataclass
class ProcurementChangeSet:
    """Deterministic ChangeSet for a single procurement revision."""
    revision: int
    previous_revision: int | None
    source_documents: list[dict[str, Any]]
    changes: list[FactChange]
    buyer_issued_date: str | None = None
    fingerprint: str = ""

    def __post_init__(self):
        if not self.fingerprint:
            src_hashes = [d.get("content_hash", "") for d in self.source_documents if d.get("content_hash")]
            self.fingerprint = compute_changeset_fingerprint(
                self.revision, self.previous_revision, self.changes, src_hashes
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "previous_revision": self.previous_revision,
            "source_documents": copy.deepcopy(self.source_documents),
            "changes": [c.to_dict() for c in self.changes],
            "buyer_issued_date": self.buyer_issued_date,
            "fingerprint": self.fingerprint,
        }


@dataclass
class ProcurementRevision:
    """Immutable record of one procurement revision in the chronological chain.
    Separates System Procurement Revision (monotonic applied counter) from
    Buyer Chronology (buyer sequence / addendum number)."""
    revision_number: int  # SYSTEM PROCUREMENT REVISION
    revision_id: str
    parent_revision_id: str | None
    buyer_chronology_index: int  # BUYER CHRONOLOGY
    buyer_issued_date: str | None
    trigger_documents: list[dict[str, Any]]
    change_set: ProcurementChangeSet
    fingerprint: str
    review_status: str = "applied"
    is_current: bool = False
    chronology_unresolved: bool = False
    no_canonical_change: bool = False

    @property
    def is_applied(self) -> bool:
        return self.review_status == "applied"

    @property
    def revision_fingerprint(self) -> str:
        return self.fingerprint

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_number": self.revision_number,
            "revision_id": self.revision_id,
            "parent_revision_id": self.parent_revision_id,
            "buyer_chronology_index": self.buyer_chronology_index,
            "buyer_issued_date": self.buyer_issued_date,
            "trigger_documents": copy.deepcopy(self.trigger_documents),
            "change_set": self.change_set.to_dict(),
            "fingerprint": self.fingerprint,
            "review_status": self.review_status,
            "is_applied": self.is_applied,
            "is_current": self.is_current,
            "chronology_unresolved": self.chronology_unresolved,
            "no_canonical_change": self.no_canonical_change,
        }


@dataclass
class AuthoritativeProcurementState:
    """Current Authoritative Procurement State (Section 13).
    Derived deterministically from immutable revision history."""
    bid_id: int
    organization_id: str
    current_revision: int
    current_revision_fingerprint: str
    authoritative_facts: dict[str, FactChange]
    active_artifacts: dict[str, ArtifactRecord]
    superseded_facts: list[FactChange]
    pending_conflicts: list[FactChange]
    history_chain: list[int]
    state_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "bid_id": self.bid_id,
            "organization_id": self.organization_id,
            "current_revision": self.current_revision,
            "current_revision_fingerprint": self.current_revision_fingerprint,
            "authoritative_facts": {k: v.to_dict() for k, v in self.authoritative_facts.items()},
            "active_artifacts": {k: v.to_dict() for k, v in self.active_artifacts.items()},
            "superseded_facts": [f.to_dict() for f in self.superseded_facts],
            "pending_conflicts": [f.to_dict() for f in self.pending_conflicts],
            "history_chain": list(self.history_chain),
            "state_fingerprint": self.state_fingerprint,
        }


# ═══════════════════════════════════════════════════════════════════════════
# 6. Deterministic State Derivation / Replay Engine (Sections 8, 9, 10, 11, 12, 13)
# ═══════════════════════════════════════════════════════════════════════════

def derive_current_authoritative_state(
    bid_id: int,
    organization_id: str,
    revisions: Sequence[ProcurementRevision],
) -> AuthoritativeProcurementState:
    """Deterministically replay revision history from Revision 0 to the latest revision.
    Replays strictly in BUYER CHRONOLOGY order (buyer_chronology_index),
    never by upload timestamp or system arrival order (Section 5 & 8).
    Excludes superseded facts from authoritative_facts while retaining them in superseded_facts.
    Unrelated facts survive unchanged (Section 9).
    Ambiguous or conflicting facts are routed to pending_conflicts without auto-resolving (Section 10)."""

    # Sort revisions strictly by buyer chronology index, then revision number
    ordered_revs = sorted(revisions, key=lambda r: (r.buyer_chronology_index, r.revision_number))

    active_facts: dict[str, FactChange] = {}
    superseded_facts: list[FactChange] = []
    pending_conflicts: list[FactChange] = []
    active_artifacts: dict[str, ArtifactRecord] = {}
    history_chain: list[int] = []

    current_rev_num = 0
    current_rev_fp = ""

    for rev in ordered_revs:
        # All-or-nothing check: only genuinely applied revisions can mutate canonical truth.
        # Analyzing, ready_for_review, reviewed, failed, or chronology-unresolved reviews must never mutate canonical truth.
        rev_is_unapplied = (
            not rev.is_applied
            or rev.review_status != "applied"
            or rev.chronology_unresolved
            or any(
                c.change_type == CHANGE_CONFLICTS_WITH
                or c.review_status in (REVIEW_STATUS_HUMAN_REVIEW_REQUIRED, REVIEW_STATUS_PENDING, REVIEW_STATUS_REJECTED)
                for c in rev.change_set.changes
            )
        )

        if rev_is_unapplied:
            for change in rev.change_set.changes:
                meta = copy.deepcopy(change.metadata) if change.metadata else {}
                if rev.chronology_unresolved:
                    meta["chronology_unresolved"] = True
                if not rev.is_applied:
                    meta["unapplied_review_status"] = rev.review_status
                conflict_change = replace(
                    change,
                    review_status=REVIEW_STATUS_HUMAN_REVIEW_REQUIRED if change.review_status == REVIEW_STATUS_APPROVED else change.review_status,
                    metadata=meta,
                )
                pending_conflicts.append(conflict_change)
            continue

        current_rev_num = rev.revision_number
        current_rev_fp = rev.fingerprint
        history_chain.append(rev.revision_number)

        for change in rev.change_set.changes:
            if change.review_status == REVIEW_STATUS_REJECTED:
                continue

            # 2. Artifact Replacement (Section 11)
            if change.fact_type == "ARTIFACT" or change.change_type == CHANGE_REPLACES:
                art_id = change.entity_id
                old_art = active_artifacts.get(art_id)
                if old_art:
                    # Mark old artifact as superseded
                    superseded_art = ArtifactRecord(
                        artifact_id=old_art.artifact_id,
                        name=old_art.name,
                        content_hash=old_art.content_hash,
                        revision=old_art.revision,
                        status=AUTHORITY_SUPERSEDED,
                        replaced_by=change.after_value.get("name") if isinstance(change.after_value, dict) else str(change.after_value),
                    )
                    active_artifacts[art_id] = superseded_art

                new_name = change.after_value.get("name", art_id) if isinstance(change.after_value, dict) else str(change.after_value)
                new_hash = change.after_value.get("content_hash", change.source_hash) if isinstance(change.after_value, dict) else change.source_hash
                new_art = ArtifactRecord(
                    artifact_id=art_id,
                    name=new_name,
                    content_hash=new_hash,
                    revision=rev.revision_number,
                    status=AUTHORITY_CURRENT,
                    replaces_artifact_id=art_id if old_art else None,
                )
                active_artifacts[art_id] = new_art

                # Also record fact in active_facts
                if old_fact := active_facts.get(change.entity_id):
                    superseded_facts.append(
                        FactChange(
                            change_type=old_fact.change_type,
                            fact_type=old_fact.fact_type,
                            entity_id=old_fact.entity_id,
                            before_value=old_fact.before_value,
                            after_value=old_fact.after_value,
                            source_document=old_fact.source_document,
                            source_hash=old_fact.source_hash,
                            authority_status=AUTHORITY_SUPERSEDED,
                            review_status=old_fact.review_status,
                            metadata=old_fact.metadata,
                        )
                    )
                active_facts[change.entity_id] = change
                continue

            # 3. Additive, Superseding, Correcting, Modifying Facts (Sections 8, 9, 12)
            if change.change_type in (CHANGE_ADDS, CHANGE_SUPERSEDES, CHANGE_CORRECTS, CHANGE_EXPANDS):
                if existing := active_facts.get(change.entity_id):
                    # Move previous version to superseded_facts
                    superseded_facts.append(
                        FactChange(
                            change_type=existing.change_type,
                            fact_type=existing.fact_type,
                            entity_id=existing.entity_id,
                            before_value=existing.before_value,
                            after_value=existing.after_value,
                            source_document=existing.source_document,
                            source_hash=existing.source_hash,
                            authority_status=AUTHORITY_SUPERSEDED,
                            review_status=existing.review_status,
                            metadata=existing.metadata,
                        )
                    )
                active_facts[change.entity_id] = change

            elif change.change_type in (CHANGE_CLARIFIES, CHANGE_NARROWS):
                # Clarifications/Narrowing: preserves existing fact while attaching qualification
                existing = active_facts.get(change.entity_id)
                meta = copy.deepcopy(change.metadata)
                if existing:
                    meta["clarifies_prior_value"] = existing.after_value
                    meta["clarified_at_revision"] = rev.revision_number
                updated_change = FactChange(
                    change_type=change.change_type,
                    fact_type=change.fact_type,
                    entity_id=change.entity_id,
                    before_value=existing.after_value if existing else change.before_value,
                    after_value=change.after_value,
                    source_document=change.source_document,
                    source_hash=change.source_hash,
                    authority_status=AUTHORITY_CURRENT,
                    review_status=change.review_status,
                    metadata=meta,
                )
                active_facts[change.entity_id] = updated_change

            elif change.change_type == CHANGE_REMOVES:
                if existing := active_facts.pop(change.entity_id, None):
                    superseded_facts.append(
                        FactChange(
                            change_type=CHANGE_REMOVES,
                            fact_type=existing.fact_type,
                            entity_id=existing.entity_id,
                            before_value=existing.after_value,
                            after_value=None,
                            source_document=change.source_document,
                            source_hash=change.source_hash,
                            authority_status=AUTHORITY_REMOVED,
                            review_status=change.review_status,
                            metadata=change.metadata,
                        )
                    )

            elif change.change_type == CHANGE_UNCHANGED:
                # Confirms unchanged evidence
                if change.entity_id in active_facts:
                    pass  # stays active
                else:
                    active_facts[change.entity_id] = change

    # State fingerprint excludes revision number (Section 12)
    state_fp = compute_state_fingerprint(bid_id, active_facts, active_artifacts)

    return AuthoritativeProcurementState(
        bid_id=bid_id,
        organization_id=organization_id,
        current_revision=current_rev_num,
        current_revision_fingerprint=current_rev_fp,
        authoritative_facts=active_facts,
        active_artifacts=active_artifacts,
        superseded_facts=superseded_facts,
        pending_conflicts=pending_conflicts,
        history_chain=history_chain,
        state_fingerprint=state_fp,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 7. Persistence Storage Adapter Layer (Sections 1, 2, 3, 4, 5, 9, 10, 11)
# ═══════════════════════════════════════════════════════════════════════════

class PCIBaseStorage(ABC):
    """Abstract interface for durable procurement revision and change persistence."""

    @abstractmethod
    def verify_tenancy(self, bid_id: int, organization_id: str) -> None:
        """Verifies that the bid belongs to the organization against persisted ownership."""

    @abstractmethod
    def get_procurement_state(self, bid_id: int) -> dict[str, Any]:
        """Returns {'procurement_revision': int, 'procurement_truth_status': str}."""

    @abstractmethod
    def get_known_document_hashes(self, bid_id: int) -> set[str]:
        """Returns set of all document content_hashes recorded in applied revisions."""

    @abstractmethod
    def load_revisions(self, bid_id: int, organization_id: str) -> list[ProcurementRevision]:
        """Rehydrates the complete revision history from persistent storage."""

    @abstractmethod
    def persist_revision(
        self,
        bid_id: int,
        organization_id: str,
        revision: ProcurementRevision,
        expected_base_revision: int | None,
    ) -> None:
        """Persists a new revision with optimistic concurrency check against expected_base_revision."""


class InMemoryPCIStorage(PCIBaseStorage):
    """Durable-in-memory storage implementing the exact schema and constraints of
    Migration 010 (bids, procurement_update_reviews, procurement_update_review_documents,
    procurement_changes, procurement_conflicts).
    Allows rigorous unit testing of process-restart, concurrency, and tenancy without network calls."""

    def __init__(self, initial_bids: dict[int, dict[str, Any]] | None = None):
        self._lock = threading.Lock()
        self.bids: dict[int, dict[str, Any]] = initial_bids.copy() if initial_bids else {}
        self.reviews: dict[int, list[dict[str, Any]]] = {}  # bid_id -> list of review dicts
        self.review_documents: dict[int, list[dict[str, Any]]] = {}  # review_id -> list of doc dicts
        self.changes: dict[int, list[dict[str, Any]]] = {}  # review_id -> list of change dicts
        self._next_review_id = 1
        self._next_change_id = 1

    def verify_tenancy(self, bid_id: int, organization_id: str) -> None:
        with self._lock:
            bid = self.bids.get(bid_id)
            if not bid:
                # Register bid if empty and not known
                self.bids[bid_id] = {
                    "id": bid_id,
                    "organization_id": str(organization_id),
                    "procurement_revision": 0,
                    "procurement_truth_status": "ungoverned",
                }
                return
            if str(bid.get("organization_id")) != str(organization_id):
                raise TenancyViolationError(
                    f"Access denied: organization '{organization_id}' does not own bid {bid_id}."
                )

    def get_procurement_state(self, bid_id: int) -> dict[str, Any]:
        with self._lock:
            bid = self.bids.get(bid_id, {})
            return {
                "procurement_revision": bid.get("procurement_revision", 0),
                "procurement_truth_status": bid.get("procurement_truth_status", "ungoverned"),
            }

    def get_known_document_hashes(self, bid_id: int) -> set[str]:
        with self._lock:
            hashes = set()
            reviews = self.reviews.get(bid_id, [])
            for r in reviews:
                if r.get("status") == "applied":
                    rid = r["id"]
                    for doc in self.review_documents.get(rid, []):
                        if h := doc.get("document_hash"):
                            hashes.add(h)
            return hashes

    def load_revisions(self, bid_id: int, organization_id: str) -> list[ProcurementRevision]:
        self.verify_tenancy(bid_id, organization_id)
        with self._lock:
            reviews = [r for r in self.reviews.get(bid_id, []) if r.get("status") in ("applied", "ready_for_review", "reviewed")]

            revisions = []
            applied_rev_ids = set()
            for r in reviews:
                rid = r["id"]
                rev_num = r.get("resulting_procurement_revision") if r.get("resulting_procurement_revision") is not None else (r.get("base_procurement_revision", 0) + 1 if r.get("review_kind") != "baseline" else 0)
                base_rev = r.get("base_procurement_revision", 0)

                # Documents
                doc_rows = self.review_documents.get(rid, [])
                trigger_docs = [
                    {
                        "document_id": d.get("document_id"),
                        "name": d.get("name", "Document"),
                        "content_hash": d.get("document_hash"),
                        "doc_type": d.get("role", "Addendum"),
                        "document_change_type": r.get("buyer_update_type", DOC_CHANGE_ADDENDUM),
                        "role": d.get("role", "primary"),
                    }
                    for d in doc_rows
                ]

                # Reconstruct chronology from document metadata (Gap 5)
                review_kind = r.get("review_kind", "buyer_update")
                chronology_unresolved = False
                if review_kind == "baseline":
                    chrono_idx = 0
                else:
                    primary_doc = next((d for d in doc_rows if d.get("role") == "primary"), doc_rows[0] if doc_rows else {})
                    doc_name = primary_doc.get("name", "")
                    chrono = extract_chronology_metadata(doc_name, r.get("buyer_issued_date"))
                    if chrono.get("sequence_number") is not None:
                        chrono_idx = chrono["sequence_number"]
                    elif r.get("review_note") and "force_chronology_index" in r.get("review_note", ""):
                        try:
                            note_data = json.loads(r["review_note"])
                            chrono_idx = note_data.get("force_chronology_index", 999999)
                        except Exception:
                            chrono_idx = 999999
                            chronology_unresolved = True
                    else:
                        chrono_idx = 999999
                        chronology_unresolved = True

                # Changes
                change_rows = self.changes.get(rid, [])
                fact_changes = []
                for c in change_rows:
                    nv = c.get("new_value") or {}
                    fact_review_status = nv.get("review_status") or c.get("review_decision") or REVIEW_STATUS_APPROVED
                    if chronology_unresolved or c.get("review_decision") == "pending":
                        fact_review_status = REVIEW_STATUS_HUMAN_REVIEW_REQUIRED
                    elif c.get("review_decision") == "rejected":
                        fact_review_status = REVIEW_STATUS_REJECTED

                    fact_changes.append(
                        FactChange(
                            change_type=nv.get("pci_change_type") or c.get("change_type"),
                            fact_type=nv.get("fact_type") or c.get("entity_type", "OTHER"),
                            entity_id=c.get("entity_id", ""),
                            before_value=c.get("previous_value", {}).get("value") if isinstance(c.get("previous_value"), dict) else c.get("previous_value"),
                            after_value=nv.get("value") if isinstance(nv, dict) and "value" in nv else nv,
                            source_document=c.get("physical_source_ref", ""),
                            source_hash=c.get("source_document_hash", ""),
                            source_document_id=c.get("source_document_id"),
                            authority_status=nv.get("authority_status", AUTHORITY_CURRENT) if isinstance(nv, dict) else AUTHORITY_CURRENT,
                            review_status=fact_review_status,
                            metadata=nv.get("metadata", {}) if isinstance(nv, dict) else {},
                        )
                    )

                src_hashes = [d.get("document_hash") for d in doc_rows if d.get("document_hash")]
                changeset = ProcurementChangeSet(
                    revision=rev_num,
                    previous_revision=base_rev if rev_num > 0 else None,
                    source_documents=trigger_docs,
                    changes=fact_changes,
                    buyer_issued_date=r.get("buyer_issued_date"),
                    fingerprint=r.get("document_set_digest", ""),
                )

                parent_id = f"bid-{bid_id}-rev-{base_rev}" if rev_num > 0 else None
                rev_id = r.get("idempotency_key") or f"bid-{bid_id}-rev-{rid}"
                if r.get("status") == "applied":
                    applied_rev_ids.add(rev_id)

                revisions.append(
                    ProcurementRevision(
                        revision_number=rev_num,
                        revision_id=rev_id,
                        parent_revision_id=parent_id,
                        buyer_chronology_index=chrono_idx,
                        buyer_issued_date=r.get("buyer_issued_date"),
                        trigger_documents=trigger_docs,
                        change_set=changeset,
                        fingerprint=r.get("document_set_digest", ""),
                        review_status=r.get("status", "applied"),
                        is_current=False,
                        chronology_unresolved=chronology_unresolved,
                        no_canonical_change=bool(r.get("no_canonical_change", False)),
                    )
                )

            # Replay strictly in buyer chronology order, then revision number
            revisions.sort(key=lambda rev: (rev.buyer_chronology_index, rev.revision_number))
            applied_revs = [rev for rev in revisions if rev.revision_id in applied_rev_ids]
            if applied_revs:
                applied_revs[-1].is_current = True
            return revisions

    def persist_revision(
        self,
        bid_id: int,
        organization_id: str,
        revision: ProcurementRevision,
        expected_base_revision: int | None,
    ) -> None:
        self.verify_tenancy(bid_id, organization_id)
        with self._lock:
            bid = self.bids[bid_id]
            current_rev = bid.get("procurement_revision", 0)
            truth_status = bid.get("procurement_truth_status", "ungoverned")

            review_kind = "baseline" if revision.parent_revision_id is None else "buyer_update"
            if review_kind == "baseline" and truth_status == "governed":
                raise PCIEngineError(f"Baseline already governed on bid {bid_id}.")
            if review_kind == "buyer_update" and truth_status != "governed":
                raise PCIEngineError(f"Baseline not governed on bid {bid_id}.")

            # Concurrency check against persisted revision counter (Section 9)
            if expected_base_revision is not None and expected_base_revision != current_rev:
                raise StaleRevisionError(
                    f"Stale revision: persisted DB revision is {current_rev}, "
                    f"expected {expected_base_revision}."
                )

            # Validate real document identity (Section 7)
            doc_roles = []
            for idx, d in enumerate(revision.trigger_documents):
                did = d.get("document_id")
                if did is None or not isinstance(did, int):
                    raise ValueError(
                        f"Missing required integer document_id for document '{d.get('name', 'unnamed')}'. "
                        "Real document identity is required for procurement change tracking."
                    )
                chash = d.get("content_hash")
                if not chash or not str(chash).strip():
                    raise ValueError(
                        f"Missing required content_hash for document '{d.get('name', 'unnamed')}'. "
                        "Real content identity is required for procurement change tracking."
                    )
                role = d.get("role")
                if not role:
                    if d.get("document_change_type") == DOC_CHANGE_REPLACEMENT_DOCUMENT:
                        role = "replacement"
                    elif idx == 0:
                        role = "primary"
                    else:
                        role = "supporting"
                doc_roles.append(role)

            if doc_roles.count("primary") != 1:
                raise ValueError(
                    f"Review requires exactly one primary document, but found {doc_roles.count('primary')}."
                )

            # Stage Review
            rid = self._next_review_id
            self._next_review_id += 1

            note_val = None
            if revision.buyer_chronology_index is not None and revision.buyer_chronology_index != 999999:
                note_val = json.dumps({"force_chronology_index": revision.buyer_chronology_index})

            # Stage Review Documents
            doc_rows = []
            for d, role in zip(revision.trigger_documents, doc_roles):
                doc_rows.append({
                    "review_id": rid,
                    "document_id": d["document_id"],
                    "organization_id": organization_id,
                    "name": d.get("name", "Document"),
                    "document_hash": d.get("content_hash"),
                    "role": role,
                })
            self.review_documents[rid] = doc_rows

            # Stage Changes
            change_rows = []
            canonical_change_count = 0
            doc_map = {d["document_id"]: d.get("content_hash") for d in revision.trigger_documents}
            for c in revision.change_set.changes:
                if c.source_document_id is None or c.source_document_id not in doc_map:
                    raise ValueError(
                        f"Missing or invalid source_document_id '{c.source_document_id}' for fact '{c.entity_id}'."
                    )
                if doc_map.get(c.source_document_id) and c.source_hash != doc_map[c.source_document_id]:
                    raise ValueError(
                        f"Mismatched source_hash for fact '{c.entity_id}': fact has '{c.source_hash}', "
                        f"but source document {c.source_document_id} has content_hash '{doc_map[c.source_document_id]}'."
                    )

                cid = self._next_change_id
                self._next_change_id += 1

                db_change_type = c.change_type
                if c.change_type in (CHANGE_REPLACES, CHANGE_CORRECTS, CHANGE_NARROWS, CHANGE_EXPANDS, CHANGE_CONFLICTS_WITH):
                    db_change_type = "MODIFIED"
                elif c.change_type == CHANGE_ADDS:
                    db_change_type = "ADDED"
                elif c.change_type == CHANGE_REMOVES:
                    db_change_type = "REMOVED"
                elif c.change_type == CHANGE_SUPERSEDES:
                    db_change_type = "SUPERSEDED"
                elif c.change_type == CHANGE_CLARIFIES:
                    db_change_type = "CLARIFIED"
                elif c.change_type == CHANGE_UNCHANGED:
                    db_change_type = "UNCHANGED"

                canon_effect = "evidence_only" if db_change_type == "UNCHANGED" else "canonical_change"
                if canon_effect == "canonical_change":
                    canonical_change_count += 1

                # Decision mapping (Section 8 & 10)
                if revision.chronology_unresolved or c.change_type == CHANGE_CONFLICTS_WITH:
                    decision = "pending"
                elif c.review_status == REVIEW_STATUS_APPROVED:
                    decision = "approved"
                elif c.review_status == REVIEW_STATUS_REJECTED:
                    decision = "rejected"
                else:
                    decision = "pending"

                change_rows.append({
                    "id": cid,
                    "review_id": rid,
                    "bid_id": bid_id,
                    "organization_id": organization_id,
                    "review_decision": decision,
                    "applied_at": None,
                    "procurement_revision": None,
                    "source_document_id": c.source_document_id,
                    "source_document_hash": c.source_hash,
                    "physical_source_ref": c.source_document,
                    "entity_type": c.fact_type.lower() if c.fact_type.lower() in ("requirement", "bid_brief_field", "deliverable", "outline_section") else "other",
                    "entity_id": c.entity_id,
                    "change_type": db_change_type,
                    "canonical_effect": canon_effect,
                    "previous_value": {"value": c.before_value},
                    "new_value": {
                        "value": c.after_value,
                        "pci_change_type": c.change_type,
                        "fact_type": c.fact_type,
                        "authority_status": c.authority_status,
                        "review_status": c.review_status,
                        "metadata": c.metadata,
                    },
                })
            self.changes[rid] = change_rows

            # Governed Apply Gate (all-or-nothing): check if any unapproved/pending or chronology unresolved
            has_unapproved = any(
                ch["review_decision"] in ("pending", "rejected") for ch in change_rows
            ) or any(
                c.review_status != REVIEW_STATUS_APPROVED for c in revision.change_set.changes
            )
            if has_unapproved or revision.chronology_unresolved:
                review_row = {
                    "id": rid,
                    "bid_id": bid_id,
                    "organization_id": organization_id,
                    "review_kind": review_kind,
                    "buyer_update_type": revision.trigger_documents[0].get("document_change_type", "Addendum") if revision.trigger_documents else "Other",
                    "buyer_issued_date": revision.buyer_issued_date,
                    "status": "ready_for_review",
                    "base_procurement_revision": current_rev,
                    "resulting_procurement_revision": None,
                    "document_set_digest": revision.fingerprint,
                    "idempotency_key": revision.revision_id,
                    "no_canonical_change": False,
                    "review_note": note_val,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "applied_at": None,
                }
                self.reviews.setdefault(bid_id, []).append(review_row)
                return

            # Atomic Apply
            applied_time = datetime.now(timezone.utc).isoformat()
            approved_canonical_count = sum(
                1 for ch in change_rows
                if ch["review_decision"] == "approved" and ch["canonical_effect"] == "canonical_change"
            )
            if review_kind == "baseline":
                new_rev = revision.revision_number
                no_canonical = False
            elif approved_canonical_count > 0:
                new_rev = current_rev + 1
                no_canonical = False
            else:
                new_rev = current_rev
                no_canonical = True

            bid["procurement_revision"] = new_rev
            bid["procurement_truth_status"] = "governed"

            for ch in change_rows:
                if ch["review_decision"] == "approved":
                    ch["applied_at"] = applied_time
                    ch["procurement_revision"] = new_rev

            review_row = {
                "id": rid,
                "bid_id": bid_id,
                "organization_id": organization_id,
                "review_kind": review_kind,
                "buyer_update_type": revision.trigger_documents[0].get("document_change_type", "Addendum") if revision.trigger_documents else "Other",
                "buyer_issued_date": revision.buyer_issued_date,
                "status": "applied",
                "base_procurement_revision": current_rev,
                "resulting_procurement_revision": new_rev,
                "document_set_digest": revision.fingerprint,
                "idempotency_key": revision.revision_id,
                "no_canonical_change": no_canonical,
                "review_note": note_val,
                "created_at": applied_time,
                "applied_at": applied_time,
            }
            self.reviews.setdefault(bid_id, []).append(review_row)


class PCIDatabaseStorage(PCIBaseStorage):
    """Production database storage adapter interfacing with Supabase via database.py.
    Maps domain models 1:1 to public.procurement_update_reviews,
    procurement_update_review_documents, and procurement_changes."""

    def __init__(self, client=None):
        self._client = client

    def _get_client(self):
        if self._client:
            return self._client
        import database
        return database.get_client()

    def verify_tenancy(self, bid_id: int, organization_id: str) -> None:
        sb = self._get_client()
        res = sb.table("bids").select("organization_id").eq("id", bid_id).execute()
        bid = res.data[0] if (res and res.data) else None
        if not bid:
            import database
            bid = database.get_bid(bid_id)
        if not bid or str(bid.get("organization_id")) != str(organization_id):
            raise TenancyViolationError(
                f"Access denied: organization '{organization_id}' does not have access to bid {bid_id}."
            )

    def get_procurement_state(self, bid_id: int) -> dict[str, Any]:
        sb = self._get_client()
        res = sb.table("bids").select("procurement_revision,procurement_truth_status").eq("id", bid_id).execute()
        if res and res.data:
            return res.data[0]
        import database
        return database.get_bid_procurement_state(bid_id)

    def get_known_document_hashes(self, bid_id: int) -> set[str]:
        sb = self._get_client()
        reviews = (
            sb.table("procurement_update_reviews")
            .select("id")
            .eq("bid_id", bid_id)
            .eq("status", "applied")
            .execute()
        ).data or []
        review_ids = [r["id"] for r in reviews]
        if not review_ids:
            return set()
        docs = (
            sb.table("procurement_update_review_documents")
            .select("document_hash")
            .in_("review_id", review_ids)
            .execute()
        ).data or []
        return {d["document_hash"] for d in docs if d.get("document_hash")}

    def load_revisions(self, bid_id: int, organization_id: str) -> list[ProcurementRevision]:
        self.verify_tenancy(bid_id, organization_id)
        sb = self._get_client()
        res = sb.table("procurement_update_reviews").select("*").eq("bid_id", bid_id).execute()
        reviews = res.data or []
        if not reviews:
            import database
            reviews = database.get_procurement_update_reviews(bid_id)
        applied_reviews = [r for r in reviews if r.get("status") in ("applied", "ready_for_review", "reviewed")]

        revisions = []
        applied_rev_ids = set()
        for r in applied_reviews:
            rid = r["id"]
            rev_num = r.get("resulting_procurement_revision") if r.get("resulting_procurement_revision") is not None else (r.get("base_procurement_revision", 0) + 1 if r.get("review_kind") != "baseline" else 0)
            base_rev = r.get("base_procurement_revision", 0)

            # Load review docs
            doc_res = sb.table("procurement_update_review_documents").select("*").eq("review_id", rid).execute()
            doc_rows = doc_res.data or []
            if not doc_rows:
                import database
                doc_rows = database.get_procurement_update_review_documents(rid)

            doc_ids = [d["document_id"] for d in doc_rows if d.get("document_id")]
            docs_map = {}
            if doc_ids:
                try:
                    docs_res = sb.table("documents").select("id,name,content_hash").in_("id", doc_ids).execute()
                    docs_map = {doc["id"]: doc for doc in (docs_res.data or [])}
                except Exception:
                    docs_map = {}

            trigger_docs = []
            for d in doc_rows:
                did = d.get("document_id")
                doc_meta = docs_map.get(did, {})
                trigger_docs.append({
                    "document_id": did,
                    "name": doc_meta.get("name") or d.get("name", "Document"),
                    "content_hash": d.get("document_hash") or doc_meta.get("content_hash"),
                    "doc_type": d.get("role", "Addendum"),
                    "document_change_type": r.get("buyer_update_type", DOC_CHANGE_ADDENDUM),
                    "role": d.get("role", "primary"),
                })

            # Reconstruct buyer chronology from document metadata (Gap 5)
            review_kind = r.get("review_kind", "buyer_update")
            chronology_unresolved = False
            if review_kind == "baseline":
                chrono_idx = 0
            else:
                primary_doc = next((d for d in trigger_docs if d.get("role") == "primary"), trigger_docs[0] if trigger_docs else {})
                doc_name = primary_doc.get("name", "")
                chrono = extract_chronology_metadata(doc_name, r.get("buyer_issued_date"))
                if chrono.get("sequence_number") is not None:
                    chrono_idx = chrono["sequence_number"]
                elif r.get("review_note") and "force_chronology_index" in r.get("review_note", ""):
                    try:
                        note_data = json.loads(r["review_note"])
                        chrono_idx = note_data.get("force_chronology_index", 999999)
                    except Exception:
                        chrono_idx = 999999
                        chronology_unresolved = True
                else:
                    chrono_idx = 999999
                    chronology_unresolved = True

            # Load changes
            chg_res = sb.table("procurement_changes").select("*").eq("review_id", rid).execute()
            change_rows = chg_res.data or []
            if not change_rows:
                import database
                change_rows = database.get_procurement_changes(rid)
            fact_changes = []
            for c in change_rows:
                nv = c.get("new_value") or {}
                fact_review_status = nv.get("review_status") or c.get("review_decision") or REVIEW_STATUS_APPROVED
                if chronology_unresolved or c.get("review_decision") == "pending":
                    fact_review_status = REVIEW_STATUS_HUMAN_REVIEW_REQUIRED
                elif c.get("review_decision") == "rejected":
                    fact_review_status = REVIEW_STATUS_REJECTED

                fact_changes.append(
                    FactChange(
                        change_type=nv.get("pci_change_type") or c.get("change_type"),
                        fact_type=nv.get("fact_type") or c.get("entity_type", "OTHER"),
                        entity_id=c.get("entity_id", ""),
                        before_value=c.get("previous_value", {}).get("value") if isinstance(c.get("previous_value"), dict) else c.get("previous_value"),
                        after_value=nv.get("value") if isinstance(nv, dict) and "value" in nv else nv,
                        source_document=c.get("physical_source_ref", ""),
                        source_hash=c.get("source_document_hash", ""),
                        source_document_id=c.get("source_document_id"),
                        authority_status=nv.get("authority_status", AUTHORITY_CURRENT) if isinstance(nv, dict) else AUTHORITY_CURRENT,
                        review_status=fact_review_status,
                        metadata=nv.get("metadata", {}) if isinstance(nv, dict) else {},
                    )
                )

            changeset = ProcurementChangeSet(
                revision=rev_num,
                previous_revision=base_rev if rev_num > 0 else None,
                source_documents=trigger_docs,
                changes=fact_changes,
                buyer_issued_date=r.get("buyer_issued_date"),
                fingerprint=r.get("document_set_digest", ""),
            )

            parent_id = f"bid-{bid_id}-rev-{base_rev}" if rev_num > 0 else None
            rev_id = r.get("idempotency_key") or f"bid-{bid_id}-rev-{rid}"
            if r.get("status") == "applied":
                applied_rev_ids.add(rev_id)

            revisions.append(
                ProcurementRevision(
                    revision_number=rev_num,
                    revision_id=rev_id,
                    parent_revision_id=parent_id,
                    buyer_chronology_index=chrono_idx,
                    buyer_issued_date=r.get("buyer_issued_date"),
                    trigger_documents=trigger_docs,
                    change_set=changeset,
                    fingerprint=r.get("document_set_digest", ""),
                    review_status=r.get("status", "applied"),
                    is_current=False,
                    chronology_unresolved=chronology_unresolved,
                    no_canonical_change=bool(r.get("no_canonical_change", False)),
                )
            )

        # Sort revisions strictly by buyer chronology index, then revision number
        revisions.sort(key=lambda rev: (rev.buyer_chronology_index, rev.revision_number))
        applied_revs = [rev for rev in revisions if rev.revision_id in applied_rev_ids]
        if applied_revs:
            applied_revs[-1].is_current = True
        return revisions

    def persist_revision(
        self,
        bid_id: int,
        organization_id: str,
        revision: ProcurementRevision,
        expected_base_revision: int | None,
    ) -> None:
        self.verify_tenancy(bid_id, organization_id)
        sb = self._get_client()

        # 1. Real document identity validation (Section 7)
        doc_ids = []
        doc_roles = []
        for idx, d in enumerate(revision.trigger_documents):
            did = d.get("document_id")
            if did is None or not isinstance(did, int):
                raise ValueError(
                    f"Missing required integer document_id for document '{d.get('name', 'unnamed')}'. "
                    "Real document identity is required for procurement change tracking."
                )
            chash = d.get("content_hash")
            if not chash or not str(chash).strip():
                raise ValueError(
                    f"Missing required content_hash for document '{d.get('name', 'unnamed')}'. "
                    "Real content identity is required for procurement change tracking."
                )
            doc_ids.append(did)
            role = d.get("role")
            if not role:
                if d.get("document_change_type") == DOC_CHANGE_REPLACEMENT_DOCUMENT:
                    role = "replacement"
                elif idx == 0:
                    role = "primary"
                else:
                    role = "supporting"
            doc_roles.append(role)

        if doc_roles.count("primary") != 1:
            raise ValueError(
                f"Review requires exactly one primary document, but found {doc_roles.count('primary')}."
            )

        review_kind = "baseline" if revision.parent_revision_id is None else "buyer_update"

        doc_type_val = revision.trigger_documents[0].get("document_change_type")
        if review_kind == "baseline":
            buyer_update_type = "Original RFP"
        elif doc_type_val == DOC_CHANGE_AMENDMENT:
            buyer_update_type = "Amendment"
        elif doc_type_val == DOC_CHANGE_CLARIFICATION:
            buyer_update_type = "Clarification/Q&A"
        elif doc_type_val == DOC_CHANGE_REPLACEMENT_DOCUMENT:
            buyer_update_type = "Revised Pricing Form"
        elif doc_type_val == DOC_CHANGE_BUYER_NOTICE:
            buyer_update_type = "Bulletin"
        else:
            buyer_update_type = "Addendum"

        # 2. Governed Lifecycle Step 1: create_procurement_update_review RPC
        review_params = {
            "p_bid_id": bid_id,
            "p_organization_id": organization_id,
            "p_review_kind": review_kind,
            "p_buyer_update_type": buyer_update_type,
            "p_buyer_issued_date": revision.buyer_issued_date,
            "p_document_ids": doc_ids,
            "p_document_roles": doc_roles,
            "p_conflict_id": None,
            "p_idempotency_key": revision.revision_id,
        }
        res = sb.rpc("create_procurement_update_review", review_params).execute()
        rows = res.data or []
        if not rows:
            raise PCIEngineError(f"Failed to create procurement update review for bid {bid_id}.")
        review_id = rows[0]["review_id"]
        is_new = rows[0].get("is_new", True)
        if not is_new:
            rev_res = sb.table("procurement_update_reviews").select("status").eq("id", review_id).execute()
            if rev_res.data and rev_res.data[0].get("status") == "applied":
                logger.info("Review %s already applied (idempotent).", review_id)
                return

        # 3. Governed Lifecycle Step 2: stage proposed changes (pending, not applied)
        doc_map = {d["document_id"]: d.get("content_hash") for d in revision.trigger_documents}
        change_rows = []
        for c in revision.change_set.changes:
            if c.source_document_id is None or c.source_document_id not in doc_ids:
                raise ValueError(
                    f"Missing or invalid source_document_id '{c.source_document_id}' for fact '{c.entity_id}'."
                )
            if doc_map.get(c.source_document_id) and c.source_hash != doc_map[c.source_document_id]:
                raise ValueError(
                    f"Mismatched source_hash for fact '{c.entity_id}': fact has '{c.source_hash}', "
                    f"but source document {c.source_document_id} has content_hash '{doc_map[c.source_document_id]}'."
                )

            db_change_type = c.change_type
            if c.change_type in (CHANGE_REPLACES, CHANGE_CORRECTS, CHANGE_NARROWS, CHANGE_EXPANDS, CHANGE_CONFLICTS_WITH):
                db_change_type = "MODIFIED"
            elif c.change_type == CHANGE_ADDS:
                db_change_type = "ADDED"
            elif c.change_type == CHANGE_REMOVES:
                db_change_type = "REMOVED"
            elif c.change_type == CHANGE_SUPERSEDES:
                db_change_type = "SUPERSEDED"
            elif c.change_type == CHANGE_CLARIFIES:
                db_change_type = "CLARIFIED"
            elif c.change_type == CHANGE_UNCHANGED:
                db_change_type = "UNCHANGED"

            canon_effect = "evidence_only" if db_change_type == "UNCHANGED" else "canonical_change"
            entity_type = c.fact_type.lower() if c.fact_type.lower() in ("requirement", "bid_brief_field", "deliverable", "outline_section") else "other"

            doc_id_for_change = c.source_document_id

            change_rows.append({
                "review_id": review_id,
                "bid_id": bid_id,
                "organization_id": organization_id,
                "review_decision": "pending",
                "applied_at": None,
                "procurement_revision": None,
                "source_document_id": doc_id_for_change,
                "source_document_hash": c.source_hash,
                "physical_source_ref": c.source_document,
                "entity_type": entity_type,
                "entity_id": c.entity_id,
                "change_type": db_change_type,
                "canonical_effect": canon_effect,
                "previous_value": {"value": c.before_value},
                "new_value": {
                    "value": c.after_value,
                    "pci_change_type": c.change_type,
                    "fact_type": c.fact_type,
                    "authority_status": c.authority_status,
                    "review_status": c.review_status,
                    "metadata": c.metadata,
                },
            })

        if change_rows:
            sb.table("procurement_changes").insert(change_rows).execute()

        # 4. Governed Lifecycle Step 3: transition status to ready_for_review
        sb.table("procurement_update_reviews").update({
            "status": "ready_for_review",
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", review_id).execute()

        # 5. Governed Lifecycle Step 4: record change review decisions
        staged_changes = sb.table("procurement_changes").select("id,entity_id,change_type,new_value,review_decision").eq("review_id", review_id).execute().data or []
        for sc in staged_changes:
            if sc.get("review_decision") == "pending":
                nv = sc.get("new_value") or {}
                fact_rev_status = nv.get("review_status")
                pci_change_type = nv.get("pci_change_type")

                # If chronology is unresolved or fact conflicts, it cannot be auto-approved
                if revision.chronology_unresolved or pci_change_type == CHANGE_CONFLICTS_WITH:
                    continue

                if fact_rev_status == REVIEW_STATUS_APPROVED:
                    sb.rpc("record_change_review_decision", {
                        "p_change_id": sc["id"],
                        "p_decision": "approved",
                        "p_actor_user_id": None,
                        "p_review_note": None,
                    }).execute()
                elif fact_rev_status == REVIEW_STATUS_REJECTED:
                    sb.rpc("record_change_review_decision", {
                        "p_change_id": sc["id"],
                        "p_decision": "rejected",
                        "p_actor_user_id": None,
                        "p_review_note": None,
                    }).execute()

        # 6. Governed Lifecycle Step 5: check apply gate (all-or-nothing)
        cur_changes = sb.table("procurement_changes").select("review_decision").eq("review_id", review_id).execute().data or []
        has_unapproved = any(
            c.get("review_decision") in ("pending", "rejected") for c in cur_changes
        ) or any(
            c.review_status != REVIEW_STATUS_APPROVED for c in revision.change_set.changes
        )

        if has_unapproved or revision.chronology_unresolved:
            logger.info(
                "Review %s has pending/rejected changes or unresolved chronology. "
                "Review remains in 'ready_for_review' pending human adjudication.",
                review_id,
            )
            return

        # 7. Governed Lifecycle Step 6: atomic apply via apply_procurement_update_review RPC
        base_rev = expected_base_revision if expected_base_revision is not None else 0
        try:
            sb.rpc("apply_procurement_update_review", {
                "p_review_id": review_id,
                "p_expected_base_revision": base_rev,
                "p_actor_user_id": None,
            }).execute()
        except Exception as exc:
            err_msg = str(exc)
            if "stale_revision" in err_msg:
                raise StaleRevisionError(
                    f"Atomic database concurrency failure on bid {bid_id}: "
                    f"expected base revision {base_rev}, but persisted state was concurrently modified."
                ) from exc
            elif "baseline_already_governed" in err_msg:
                raise PCIEngineError(
                    f"Atomic database concurrency failure on bid {bid_id}: "
                    "Revision 0 (baseline) already exists or bid is already governed."
                ) from exc
            raise PCIEngineError(
                f"Governed apply failed for review {review_id} on bid {bid_id}: {err_msg}"
            ) from exc


# ═══════════════════════════════════════════════════════════════════════════
# 8. Procurement Revision Manager (Sections 4, 5, 6, 7, 8, 9, 10, 16)
# ═══════════════════════════════════════════════════════════════════════════

class ProcurementRevisionManager:
    """Manages the lifecycle, chronology, idempotency, and concurrency
    for a single procurement's revision history.
    Durable across process restarts via PCIBaseStorage."""

    _locks: dict[int, threading.Lock] = {}
    _locks_guard = threading.Lock()

    def __init__(
        self,
        bid_id: int,
        organization_id: str,
        storage: PCIBaseStorage | None = None,
    ):
        if not bid_id or not organization_id:
            raise TenancyViolationError("Both bid_id and organization_id are required.")
        self.bid_id = bid_id
        self.organization_id = str(organization_id)

        # Storage initialization & persisted tenancy verification (Section 10)
        # Production execution strictly uses PCIDatabaseStorage; no implicit fallback to in-memory.
        self.storage: PCIBaseStorage = storage if storage is not None else PCIDatabaseStorage()
        self.storage.verify_tenancy(self.bid_id, self.organization_id)

        # Rehydrate existing revisions from storage (Sections 4, 5, 15)
        self._all_revisions: list[ProcurementRevision] = []
        self._revisions: dict[int, ProcurementRevision] = {}
        for rev in self.storage.load_revisions(self.bid_id, self.organization_id):
            self._all_revisions.append(rev)
            self._revisions[rev.revision_number] = rev

    @classmethod
    def _get_bid_lock(cls, bid_id: int) -> threading.Lock:
        with cls._locks_guard:
            if bid_id not in cls._locks:
                cls._locks[bid_id] = threading.Lock()
            return cls._locks[bid_id]

    def _verify_tenancy(self, target_bid_id: int, target_org_id: str) -> None:
        if target_bid_id != self.bid_id or str(target_org_id) != self.organization_id:
            raise TenancyViolationError(
                f"Tenancy mismatch: request for ({target_bid_id}, {target_org_id}) "
                f"denied on manager for ({self.bid_id}, {self.organization_id})"
            )
        self.storage.verify_tenancy(target_bid_id, target_org_id)

    @property
    def current_revision_number(self) -> int:
        proc_state = self.storage.get_procurement_state(self.bid_id)
        return proc_state.get("procurement_revision", max(self._revisions.keys(), default=-1))

    def get_revision(self, revision_number: int) -> ProcurementRevision | None:
        self.get_all_revisions()
        return self._revisions.get(revision_number)

    def get_revision_by_id(self, revision_id: str) -> ProcurementRevision | None:
        for rev in self.get_all_revisions():
            if rev.revision_id == revision_id:
                return rev
        return None

    def get_all_revisions(self) -> list[ProcurementRevision]:
        reloaded = self.storage.load_revisions(self.bid_id, self.organization_id)
        if reloaded and len(reloaded) > len(self._all_revisions):
            self._all_revisions = list(reloaded)
            self._revisions = {r.revision_number: r for r in reloaded}
        return sorted(self._all_revisions, key=lambda r: (r.buyer_chronology_index, r.revision_number))

    def get_current_state(self) -> AuthoritativeProcurementState:
        return derive_current_authoritative_state(
            self.bid_id, self.organization_id, self.get_all_revisions()
        )

    def create_baseline_revision(
        self,
        documents: Sequence[dict[str, Any]],
        initial_facts: Sequence[FactChange],
        buyer_issued_date: str | None = None,
    ) -> ProcurementRevision:
        """Establishes Revision 0 (original authoritative procurement state).
        Fails closed if baseline already exists or if content_hash or document_id is missing."""
        lock = self._get_bid_lock(self.bid_id)
        with lock:
            if 0 in self._revisions or any(r.revision_number == 0 for r in self._all_revisions):
                raise PCIEngineError("Revision 0 (baseline) already exists for this procurement.")

            # Require real document_id and content_hash (Section 7)
            src_docs = []
            src_hashes = []
            for idx, d in enumerate(documents):
                did = d.get("document_id")
                if did is None or not isinstance(did, int):
                    raise ValueError(
                        f"Missing required integer document_id for document '{d.get('name', 'unnamed')}'. "
                        "Real document identity is required for procurement change tracking."
                    )
                chash = d.get("content_hash")
                if not chash or not str(chash).strip():
                    raise ValueError(
                        f"Missing required content_hash for document '{d.get('name', 'unnamed')}'. "
                        "Real content identity is required for procurement change tracking."
                    )
                role = d.get("role")
                if not role:
                    role = "primary" if idx == 0 else "supporting"
                src_docs.append({
                    "document_id": did,
                    "name": d.get("name", "RFP"),
                    "content_hash": chash,
                    "doc_type": d.get("doc_type", "RFP / Source"),
                    "document_change_type": DOC_CHANGE_ORIGINAL_RFP,
                    "role": role,
                })
                src_hashes.append(chash)

            if [d["role"] for d in src_docs].count("primary") != 1:
                raise ValueError("Baseline requires exactly one primary document.")

            # Build doc_map
            doc_map = {d["document_id"]: d["content_hash"] for d in src_docs}

            # Require real source_document_id and matching source_hash on all initial facts
            for c in initial_facts:
                if c.source_document_id is None or not isinstance(c.source_document_id, int):
                    raise ValueError(
                        f"Missing required integer source_document_id for fact '{c.entity_id}'. "
                        "Every fact change must cite an explicit source_document_id matching a trigger document."
                    )
                if c.source_document_id not in doc_map:
                    raise ValueError(
                        f"Unknown source_document_id {c.source_document_id} for fact '{c.entity_id}'. "
                        f"Must match one of the trigger documents: {list(doc_map.keys())}."
                    )
                if not c.source_hash or not str(c.source_hash).strip():
                    raise ValueError(
                        f"Missing required source_hash for fact '{c.entity_id}'. "
                        "Every fact change must cite a verified source document hash."
                    )
                if c.source_hash != doc_map[c.source_document_id]:
                    raise ValueError(
                        f"Mismatched source_hash for fact '{c.entity_id}': fact has '{c.source_hash}', "
                        f"but source document {c.source_document_id} has content_hash '{doc_map[c.source_document_id]}'."
                    )

            # Build ChangeSet for Revision 0
            changes = [
                FactChange(
                    change_type=c.change_type if c.change_type in FACT_CHANGE_TYPES else CHANGE_ADDS,
                    fact_type=c.fact_type,
                    entity_id=c.entity_id,
                    before_value=None,
                    after_value=c.after_value,
                    source_document=c.source_document,
                    source_hash=c.source_hash,
                    source_document_id=c.source_document_id,
                    authority_status=AUTHORITY_CURRENT,
                    review_status=REVIEW_STATUS_APPROVED,
                    metadata=c.metadata,
                )
                for c in initial_facts
            ]

            changeset_fp = compute_changeset_fingerprint(0, None, changes, src_hashes)
            changeset = ProcurementChangeSet(
                revision=0,
                previous_revision=None,
                source_documents=src_docs,
                changes=changes,
                buyer_issued_date=buyer_issued_date,
                fingerprint=changeset_fp,
            )

            rev_fp = compute_revision_fingerprint(0, None, src_hashes, changeset_fp)
            rev_0 = ProcurementRevision(
                revision_number=0,
                revision_id=f"bid-{self.bid_id}-rev-0",
                parent_revision_id=None,
                buyer_chronology_index=0,
                buyer_issued_date=buyer_issued_date,
                trigger_documents=src_docs,
                change_set=changeset,
                fingerprint=rev_fp,
                review_status="applied",
                is_current=True,
                chronology_unresolved=False,
                no_canonical_change=False,
            )

            # Persist to durable storage (Section 4)
            self.storage.persist_revision(
                self.bid_id, self.organization_id, rev_0, expected_base_revision=None
            )

            self._all_revisions.append(rev_0)
            self._revisions[0] = rev_0
            logger.info("Created durable Revision 0 for bid %s (fingerprint: %s...)", self.bid_id, rev_fp[:12])
            return rev_0

    def add_buyer_update_revision(
        self,
        documents: Sequence[dict[str, Any]],
        changes: Sequence[FactChange],
        buyer_issued_date: str | None = None,
        expected_base_revision: int | None = None,
        force_chronology_index: int | None = None,
    ) -> dict[str, Any]:
        """Adds an additive buyer revision (Rev 1, 2, ...).
        Enforces idempotency across process restarts (Section 6),
        optimistic database concurrency (Section 9),
        two distinct sequences: Buyer Update Event vs Canonical Procurement Revision (Section 8),
        and separate buyer chronology vs system revision (Section 5 & 8)."""
        lock = self._get_bid_lock(self.bid_id)
        with lock:
            current_rev = self.current_revision_number
            if current_rev < 0 and not self._all_revisions:
                raise PCIEngineError("Cannot add buyer update revision: Revision 0 does not exist.")

            # Concurrency check against persisted revision counter (Section 9)
            proc_state = self.storage.get_procurement_state(self.bid_id)
            persisted_rev = proc_state.get("procurement_revision", current_rev)
            if expected_base_revision is not None and expected_base_revision != persisted_rev:
                raise StaleRevisionError(
                    f"Stale revision: expected base revision {expected_base_revision}, "
                    f"but persisted current revision is {persisted_rev}."
                )

            # Require real document_id and content_hash (Section 7)
            incoming_hashes = []
            for d in documents:
                did = d.get("document_id")
                if did is None or not isinstance(did, int):
                    raise ValueError(
                        f"Missing required integer document_id for document '{d.get('name', 'unnamed')}'. "
                        "Real document identity is required for procurement change tracking."
                    )
                chash = d.get("content_hash")
                if not chash or not str(chash).strip():
                    raise ValueError(
                        f"Missing required content_hash for document '{d.get('name', 'unnamed')}'. "
                        "Real content identity is required for procurement change tracking."
                    )
                incoming_hashes.append(chash)

            # Require real source_hash on all fact changes
            for c in changes:
                if not c.source_hash or not str(c.source_hash).strip():
                    raise ValueError(
                        f"Missing required source_hash for fact '{c.entity_id}'. "
                        "Every fact change must cite a verified source document hash."
                    )

            # Durable Idempotency check against persisted known hashes (Section 6)
            known_hashes = self.storage.get_known_document_hashes(self.bid_id)
            if incoming_hashes and all(h in known_hashes for h in incoming_hashes):
                logger.info("All incoming document hashes already registered. Outcome: NO_NEW_REVISION")
                return {
                    "outcome": OUTCOME_NO_NEW_REVISION,
                    "reason": "IDENTICAL_DOCUMENTS_ALREADY_REGISTERED",
                    "current_revision": current_rev,
                }

            # Chronology & Out-of-order analysis (Section 5 & 8)
            doc0 = documents[0] if documents else {}
            fname = doc0.get("name", "")
            chrono = extract_chronology_metadata(fname, buyer_issued_date)
            doc_change_type = chrono.get("document_change_type") or DOC_CHANGE_ADDENDUM

            chronology_unresolved = False
            if force_chronology_index is not None:
                chronology_index = force_chronology_index
            elif chrono.get("sequence_number") is not None:
                chronology_index = chrono["sequence_number"]
            else:
                # Ambiguous or missing sequence number -- flag unresolved!
                # Never silently fall back to procurement_revision counter!
                chronology_index = 999999
                chronology_unresolved = True

            # Two distinct sequences (Gap 4):
            # Check if this revision has semantic fact changes or is informational/no-op
            has_semantic_changes = any(
                c.change_type != CHANGE_UNCHANGED for c in changes
            )
            outcome = (
                OUTCOME_REVISION_CREATED
                if has_semantic_changes
                else OUTCOME_NEW_REVISION_NO_SEMANTIC_CHANGE
            )

            # Canonical revision increments ONLY if there are approved canonical changes!
            if has_semantic_changes:
                next_rev_num = current_rev + 1
            else:
                next_rev_num = current_rev

            parent_rev = self._revisions.get(current_rev) or self._all_revisions[-1]

            # Build source document metadata
            src_docs = []
            for idx, (d, chash) in enumerate(zip(documents, incoming_hashes)):
                role = d.get("role")
                if not role:
                    if d.get("document_change_type") == DOC_CHANGE_REPLACEMENT_DOCUMENT:
                        role = "replacement"
                    elif idx == 0:
                        role = "primary"
                    else:
                        role = "supporting"
                src_docs.append({
                    "document_id": d["document_id"],
                    "name": d.get("name", "Buyer Update"),
                    "content_hash": chash,
                    "doc_type": d.get("doc_type", "Addendum"),
                    "document_change_type": d.get("document_change_type") or doc_change_type,
                    "role": role,
                    "sequence_number": chrono.get("sequence_number"),
                    "issued_date": chrono.get("issued_date"),
                })

            if [d["role"] for d in src_docs].count("primary") != 1:
                raise ValueError("Buyer update requires exactly one primary document.")

            doc_map = {d["document_id"]: d["content_hash"] for d in src_docs}

            # Require real source_document_id and matching source_hash on all fact changes
            for c in changes:
                if c.source_document_id is None or not isinstance(c.source_document_id, int):
                    raise ValueError(
                        f"Missing required integer source_document_id for fact '{c.entity_id}'. "
                        "Every fact change must cite an explicit source_document_id matching a trigger document."
                    )
                if c.source_document_id not in doc_map:
                    raise ValueError(
                        f"Unknown source_document_id {c.source_document_id} for fact '{c.entity_id}'. "
                        f"Must match one of the trigger documents: {list(doc_map.keys())}."
                    )
                if not c.source_hash or not str(c.source_hash).strip():
                    raise ValueError(
                        f"Missing required source_hash for fact '{c.entity_id}'. "
                        "Every fact change must cite a verified source document hash."
                    )
                if c.source_hash != doc_map[c.source_document_id]:
                    raise ValueError(
                        f"Mismatched source_hash for fact '{c.entity_id}': fact has '{c.source_hash}', "
                        f"but source document {c.source_document_id} has content_hash '{doc_map[c.source_document_id]}'."
                    )

            # If chronology is unresolved or change is CONFLICTS_WITH, mark changes with HUMAN_REVIEW_REQUIRED
            prepared_changes = []
            for c in changes:
                meta = copy.deepcopy(c.metadata) if c.metadata else {}
                rev_status = c.review_status
                if chronology_unresolved or c.change_type == CHANGE_CONFLICTS_WITH:
                    rev_status = REVIEW_STATUS_HUMAN_REVIEW_REQUIRED
                    if chronology_unresolved:
                        meta["chronology_unresolved"] = True
                c_prepared = replace(
                    c,
                    source_document_id=c.source_document_id,
                    review_status=rev_status,
                    metadata=meta,
                )
                prepared_changes.append(c_prepared)

            is_pending_review = bool(
                chronology_unresolved
                or any(
                    c.review_status != REVIEW_STATUS_APPROVED
                    or c.change_type == CHANGE_CONFLICTS_WITH
                    for c in prepared_changes
                )
            )

            # Build ChangeSet
            changeset_fp = compute_changeset_fingerprint(
                next_rev_num, current_rev, prepared_changes, incoming_hashes
            )
            changeset = ProcurementChangeSet(
                revision=next_rev_num,
                previous_revision=current_rev,
                source_documents=src_docs,
                changes=prepared_changes,
                buyer_issued_date=chrono.get("issued_date") or buyer_issued_date,
                fingerprint=changeset_fp,
            )

            # Build Revision
            rev_fp = compute_revision_fingerprint(
                next_rev_num, parent_rev.fingerprint, incoming_hashes, changeset_fp
            )

            new_revision = ProcurementRevision(
                revision_number=next_rev_num,
                revision_id=f"bid-{self.bid_id}-rev-{next_rev_num}-{len(self._all_revisions)}",
                parent_revision_id=parent_rev.revision_id,
                buyer_chronology_index=chronology_index,
                buyer_issued_date=chrono.get("issued_date") or buyer_issued_date,
                trigger_documents=src_docs,
                change_set=changeset,
                fingerprint=rev_fp,
                review_status="ready_for_review" if is_pending_review else "applied",
                is_current=(not is_pending_review),
                chronology_unresolved=chronology_unresolved,
                no_canonical_change=(not has_semantic_changes),
            )

            # Persist to durable storage (Section 5)
            self.storage.persist_revision(
                self.bid_id, self.organization_id, new_revision, expected_base_revision=persisted_rev
            )

            # Immutability: Prior revisions remain immutable; un-mark is_current ONLY if this revision was applied
            if not is_pending_review:
                for i, r in enumerate(self._all_revisions):
                    if r.is_current:
                        unmarked_rev = replace(r, is_current=False)
                        self._all_revisions[i] = unmarked_rev
                        self._revisions[r.revision_number] = unmarked_rev

            self._all_revisions.append(new_revision)
            self._revisions[next_rev_num] = new_revision
            logger.info("Created durable Revision %d for bid %s (fingerprint: %s...)",
                        next_rev_num, self.bid_id, rev_fp[:12])

            return {
                "outcome": outcome,
                "revision": new_revision,
                "current_revision": current_rev if is_pending_review else next_rev_num,
                "has_semantic_changes": has_semantic_changes,
                "chronology_unresolved": chronology_unresolved,
                "review_status": "ready_for_review" if is_pending_review else "applied",
            }

    def get_fact_history(self, entity_id: str) -> list[dict[str, Any]]:
        """Returns the full chronological evolution of a specific fact across all revisions."""
        history = []
        ordered_revs = sorted(self._all_revisions, key=lambda r: (r.buyer_chronology_index, r.revision_number))
        for rev in ordered_revs:
            for c in rev.change_set.changes:
                if c.entity_id == entity_id:
                    history.append({
                        "revision": rev.revision_number,
                        "buyer_chronology_index": rev.buyer_chronology_index,
                        "change_type": c.change_type,
                        "fact_type": c.fact_type,
                        "before_value": c.before_value,
                        "after_value": c.after_value,
                        "source_document": c.source_document,
                        "source_document_id": c.source_document_id,
                        "authority_status": c.authority_status,
                        "review_status": c.review_status,
                    })
        return history

    def get_revision_impact_plan_by_id(
        self,
        revision_id: str,
        existing_findings: Sequence[dict[str, Any]] | None = None,
    ) -> RevisionImpactPlan:
        """Computes deterministic RevisionImpactPlan by revision_id."""
        rev = self.get_revision_by_id(revision_id)
        if rev is None:
            raise PCIEngineError(f"Revision with id '{revision_id}' not found for bid {self.bid_id}.")
        state = self.get_current_state()
        return generate_revision_impact_plan(rev, state, existing_findings, bid_id=self.bid_id)

    def get_revision_impact_plan(
        self,
        target: int | str | ProcurementRevision,
        existing_findings: Sequence[dict[str, Any]] | None = None,
    ) -> RevisionImpactPlan:
        """Computes the deterministic RevisionImpactPlan for a revision against current state.
        Fails closed on ambiguous integer revision_number matching multiple revisions."""
        if isinstance(target, ProcurementRevision):
            rev = target
        elif isinstance(target, str):
            rev = self.get_revision_by_id(target)
            if rev is None:
                raise PCIEngineError(f"Revision with id '{target}' not found for bid {self.bid_id}.")
        elif isinstance(target, int):
            matching = [r for r in self._all_revisions if r.revision_number == target]
            if not matching:
                raise PCIEngineError(f"Revision {target} not found for bid {self.bid_id}.")
            if len(matching) > 1:
                ids = [r.revision_id for r in matching]
                raise PCIEngineError(
                    f"Ambiguous revision_number {target} matches multiple revisions ({ids}). "
                    f"Use revision_id or get_revision_impact_plan_by_id instead."
                )
            rev = matching[0]
        else:
            raise TypeError(f"Target must be int, str, or ProcurementRevision, got {type(target).__name__}")

        state = self.get_current_state()
        return generate_revision_impact_plan(rev, state, existing_findings, bid_id=self.bid_id)

    def get_current_canonical_view(
        self,
        canonical_package: Any,
        up_to_revision: int | str | ProcurementRevision | None = None,
    ) -> CurrentCanonicalView:
        """Derives the unified CurrentCanonicalView for the bid up to the specified revision."""
        all_revs = self.get_all_revisions()
        target_rev = None
        if up_to_revision is not None:
            if isinstance(up_to_revision, ProcurementRevision):
                target_rev = up_to_revision
            elif isinstance(up_to_revision, str):
                target_rev = self.get_revision_by_id(up_to_revision)
            elif isinstance(up_to_revision, int):
                matching = [r for r in all_revs if r.revision_number == up_to_revision]
                if matching:
                    target_rev = matching[0]
        up_to_num = target_rev.revision_number if target_rev else None
        up_to_chrono = target_rev.buyer_chronology_index if target_rev else None
        return derive_current_canonical_view(
            canonical_package,
            all_revs,
            up_to_revision_number=up_to_num,
            up_to_buyer_chronology_index=up_to_chrono,
        )

    def get_revision_specialist_context(
        self,
        target: int | str | ProcurementRevision,
        specialist_id: str,
        canonical_package: Any,
        prior_findings: Sequence[Any] | None = None,
        impact_plan: RevisionImpactPlan | None = None,
        current_canonical_view: CurrentCanonicalView | None = None,
    ) -> RevisionSpecialistContext:
        """Constructs authoritative RevisionSpecialistContext for an affected specialist domain.
        Fails closed with PCIContextNotEligibleError if unapplied, conflicted, or unaffected."""
        if isinstance(target, ProcurementRevision):
            rev = target
        elif isinstance(target, str):
            rev = self.get_revision_by_id(target)
            if rev is None:
                raise PCIEngineError(f"Revision with id '{target}' not found for bid {self.bid_id}.")
        elif isinstance(target, int):
            matching = [r for r in self._all_revisions if r.revision_number == target]
            if not matching:
                raise PCIEngineError(f"Revision {target} not found for bid {self.bid_id}.")
            if len(matching) > 1:
                ids = [r.revision_id for r in matching]
                raise PCIEngineError(
                    f"Ambiguous revision_number {target} matches multiple revisions ({ids}). "
                    f"Use revision_id instead."
                )
            rev = matching[0]
        else:
            raise TypeError(f"Target must be int, str, or ProcurementRevision, got {type(target).__name__}")

        state = self.get_current_state()
        if impact_plan is None:
            impact_plan = self.get_revision_impact_plan(rev, existing_findings=prior_findings)
        if current_canonical_view is None:
            current_canonical_view = self.get_current_canonical_view(canonical_package, up_to_revision=rev)

        return build_revision_specialist_context(
            specialist_id=specialist_id,
            revision=rev,
            procurement_state=state,
            canonical_package=canonical_package,
            impact_plan=impact_plan,
            prior_specialist_findings=prior_findings,
            bid_id=self.bid_id,
            current_canonical_view=current_canonical_view,
        )


# ═══════════════════════════════════════════════════════════════════════════
# 9. Top-Level Production Entrypoint & Rehydration API (Section 15)
# ═══════════════════════════════════════════════════════════════════════════

def get_pci_manager(
    bid_id: int,
    organization_id: str,
    storage: PCIBaseStorage | None = None,
) -> ProcurementRevisionManager:
    """Canonical production entrypoint for ProcurementRevisionManager.
    Defaults strictly to PCIDatabaseStorage, with no implicit fallback to InMemoryPCIStorage."""
    return ProcurementRevisionManager(
        bid_id=bid_id,
        organization_id=organization_id,
        storage=storage if storage is not None else PCIDatabaseStorage(),
    )


def load_revision_history(
    bid_id: int,
    organization_id: str,
    storage: PCIBaseStorage | None = None,
) -> list[ProcurementRevision]:
    """Rehydrates the complete, immutable procurement revision history directly from storage."""
    mgr = get_pci_manager(bid_id, organization_id, storage=storage)
    return mgr.get_all_revisions()


def load_current_authoritative_state(
    bid_id: int,
    organization_id: str,
    storage: PCIBaseStorage | None = None,
) -> AuthoritativeProcurementState:
    """Rehydrates and deterministically derives current authoritative procurement state from storage."""
    mgr = get_pci_manager(bid_id, organization_id, storage=storage)
    return mgr.get_current_state()


# ═══════════════════════════════════════════════════════════════════════════
# 10. PCI-B1: Deterministic Impact Routing & Intelligence Dependency Engine
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DomainRoutingReason:
    """A compact, deterministic reason explaining why a domain was affected."""
    domain: str
    rule: str

    def to_dict(self) -> dict[str, str]:
        return {"domain": self.domain, "rule": self.rule}


@dataclass(frozen=True)
class ChangeRoutingDecision:
    """Deterministic routing decision for a single applied FactChange."""
    change_id: str
    affected_domains: tuple[str, ...]
    reasons: tuple[DomainRoutingReason, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "affected_domains": list(self.affected_domains),
            "reasons": [r.to_dict() for r in self.reasons],
        }


def compute_impact_plan_fingerprint(
    change_set_fingerprint: str,
    state_fingerprint: str,
    affected_domains: Sequence[str],
    finding_impacts: dict[str, dict[str, Any]],
    revision_id: str = "",
) -> str:
    """Computes a stable, semantic SHA-256 fingerprint for a RevisionImpactPlan.
    Excludes execution time, timestamps, database row IDs, and ordering noise."""
    payload = {
        "revision_id": str(revision_id or ""),
        "change_set_fingerprint": str(change_set_fingerprint or ""),
        "state_fingerprint": str(state_fingerprint or ""),
        "affected_domains": sorted(set(affected_domains)),
        "finding_impacts": [
            {
                "finding_id": str(fid),
                "status": impact["status"],
                "reasons": sorted(impact.get("reasons", []), key=lambda r: json.dumps(r, sort_keys=True)),
            }
            for fid, impact in sorted(finding_impacts.items())
        ],
    }
    return _canonical_json_hash(payload)


@dataclass
class RevisionImpactPlan:
    """The deterministic contract consumed by PCI-B2.
    Determines affected domains, stale findings, retained findings, and unresolved items."""
    revision_number: int
    change_set_fingerprint: str
    state_fingerprint: str
    affected_domains: list[str]
    retained_finding_ids: list[str]
    stale_finding_ids: list[str]
    unresolved_finding_ids: list[str]
    finding_impacts: dict[str, dict[str, Any]]
    routing_reasons: list[dict[str, Any]]
    revision_id: str = ""
    fingerprint: str = ""

    def __post_init__(self):
        if not self.fingerprint:
            self.fingerprint = compute_impact_plan_fingerprint(
                change_set_fingerprint=self.change_set_fingerprint,
                state_fingerprint=self.state_fingerprint,
                affected_domains=self.affected_domains,
                finding_impacts=self.finding_impacts,
                revision_id=self.revision_id,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_number": self.revision_number,
            "revision_id": self.revision_id,
            "change_set_fingerprint": self.change_set_fingerprint,
            "state_fingerprint": self.state_fingerprint,
            "affected_domains": list(self.affected_domains),
            "retained_finding_ids": list(self.retained_finding_ids),
            "stale_finding_ids": list(self.stale_finding_ids),
            "unresolved_finding_ids": list(self.unresolved_finding_ids),
            "finding_impacts": copy.deepcopy(self.finding_impacts),
            "routing_reasons": copy.deepcopy(self.routing_reasons),
            "fingerprint": self.fingerprint,
        }


def _normalize_key(val: Any) -> str:
    """Normalize dependency / entity key for robust matching across formats."""
    s = str(val or "").strip().lower()
    return re.sub(r'[\s\.\:\-_/]+', '_', s)


def _expand_key_variants(val: Any) -> set[str]:
    """Expands key variants to bridge canonical prefixes, slugs, and entity formats."""
    raw = str(val or "").strip()
    if not raw:
        return set()
    norm = _normalize_key(raw)
    variants = {raw, raw.lower(), norm}

    # 1. Strip common domain/entity prefixes:
    for prefix in (
        "doc_", "rel_", "artifact_", "req_", "crit_", "obl_", "ms_", "sub_",
        "eval_", "deadline_", "insurance_", "comm_", "commercial_", "scope_",
        "price_", "pricing_",
    ):
        if norm.startswith(prefix):
            stripped = norm[len(prefix):]
            if stripped and not stripped.isdigit():
                variants.add(stripped)

    # 2. For each current variant, strip common trailing attribute suffixes or numeric indices:
    expanded_more = set()
    for v in list(variants):
        for suffix in (
            "_weight", "_threshold", "_limit", "_score", "_date", "_time",
            "_submission", "_terms", "_requirements", "_specifications",
        ):
            if v.endswith(suffix):
                s_stripped = v[:-len(suffix)]
                if s_stripped:
                    expanded_more.add(s_stripped)
        num_stripped = re.sub(r'_\d+$', '', v)
        if num_stripped != v and num_stripped:
            expanded_more.add(num_stripped)

    # 3. Strip prefixes again on any stripped variants
    for v in list(expanded_more):
        for prefix in (
            "doc_", "rel_", "artifact_", "req_", "crit_", "obl_", "ms_", "sub_",
            "eval_", "deadline_", "insurance_", "comm_", "commercial_", "scope_",
            "price_", "pricing_",
        ):
            if v.startswith(prefix):
                stripped = v[len(prefix):]
                if stripped and not stripped.isdigit():
                    expanded_more.add(stripped)

    variants.update(expanded_more)
    return variants


ZERO_IMPACT_FACT_TYPES = frozenset({
    "buyer_contact",
    "administrative_contact",
    "administrative_notice",
    "document_metadata",
    "typographical_correction",
    "unchanged_fact",
})


@dataclass(frozen=True)
class _DomainRule:
    rule_id: str
    domains: tuple[str, ...]
    fact_types: tuple[str, ...]
    entity_prefixes: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    custom_reasons: dict[str, str] | None = None  # domain -> custom rule name


DOMAIN_ROUTING_RULES: tuple[_DomainRule, ...] = (
    # 1. Schedule & Submission Deadlines
    _DomainRule(
        rule_id="SUBMISSION_DEADLINE_CHANGE",
        domains=(SPECIALIST_SCHEDULE_SUBMISSION,),
        fact_types=(
            "DEADLINE", "deadline", "submission_deadline", "closing_date", "closing_time",
            "rfp_closing", "bid_closing", "proposal_deadline", "closing_deadline",
            "question_deadline", "addendum_deadline",
        ),
        entity_prefixes=("sub:deadline", "sub.deadline", "deadline", "deadline.", "closing"),
    ),
    # 2. Schedule Milestones
    _DomainRule(
        rule_id="SCHEDULE_MILESTONE_CHANGE",
        domains=(SPECIALIST_SCHEDULE_SUBMISSION,),
        fact_types=(
            "MILESTONE", "milestone", "schedule", "timetable", "project_schedule",
            "target_date", "scoped_milestone",
        ),
        entity_prefixes=("ms-", "ms:", "ms.", "milestone:", "milestone."),
    ),
    # 3. Submission Mechanics (Submission + Procurement Structure)
    _DomainRule(
        rule_id="SUBMISSION_MECHANICS_CHANGE",
        domains=(SPECIALIST_SCHEDULE_SUBMISSION, SPECIALIST_PROCUREMENT_STRUCTURE),
        fact_types=(
            "submission_mechanics", "submission_portal", "submission_method",
            "submission_format", "page_limit", "font_size", "number_of_copies",
            "submission_instructions",
        ),
        entity_prefixes=("submission", "pkg", "sub:mechanics", "sub.mechanics", "sub:portal", "sub.portal", "sub:format", "sub.format"),
    ),
    # 4. Evaluation Criteria & Weights
    _DomainRule(
        rule_id="EVALUATION_WEIGHT_CHANGE",
        domains=(SPECIALIST_EVALUATION_INTELLIGENCE,),
        fact_types=(
            "WEIGHT", "weight", "evaluation_weight", "evaluation_criterion", "evaluation_criteria",
            "scoring_weight", "scoring_formula", "evaluation_grid", "rating_scale",
            "criterion_weight", "scoring_model",
        ),
        entity_prefixes=("crit-", "crit:", "crit.", "eval:weight", "eval:criterion", "eval.", "eval_"),
    ),
    # 5. Evaluation Thresholds (Cross-domain: Evaluation + Compliance)
    _DomainRule(
        rule_id="EVALUATION_THRESHOLD_CHANGE",
        domains=(SPECIALIST_EVALUATION_INTELLIGENCE, SPECIALIST_REQUIREMENTS_COMPLIANCE),
        fact_types=(
            "THRESHOLD", "threshold", "evaluation_threshold", "minimum_score", "passing_score",
            "evaluation_gate", "technical_threshold", "minimum_passing_grade",
        ),
        entity_prefixes=("eval:threshold", "eval.threshold", "eval_threshold"),
        custom_reasons={
            SPECIALIST_EVALUATION_INTELLIGENCE: "EVALUATION_THRESHOLD_CHANGE",
            SPECIALIST_REQUIREMENTS_COMPLIANCE: "EVALUATION_THRESHOLD_COMPLIANCE_CROSS_DOMAIN",
        },
    ),
    # 6. Requirements & Compliance
    _DomainRule(
        rule_id="REQUIREMENT_COMPLIANCE_CHANGE",
        domains=(SPECIALIST_REQUIREMENTS_COMPLIANCE,),
        fact_types=(
            "MANDATORY", "mandatory", "mandatory_qualification", "qualification_requirement", "requirement",
            "compliance", "mandatory_requirement", "compliance_requirement",
            "canonical_requirement", "eligibility",
        ),
        entity_prefixes=("req-", "req:", "req."),
    ),
    # 7. Mandatory Staffing / Credentials (Cross-domain: Compliance + Scope)
    _DomainRule(
        rule_id="MANDATORY_CREDENTIAL_CHANGE",
        domains=(SPECIALIST_REQUIREMENTS_COMPLIANCE, SPECIALIST_SCOPE_DELIVERABLES),
        fact_types=(
            "mandatory_credential", "personnel_credential", "key_personnel",
            "staffing_requirement", "team_credential", "security_clearance",
            "professional_certification",
        ),
        entity_prefixes=("credential:", "personnel:", "staffing:", "credential.", "personnel.", "staffing."),
        keywords=("credential", "personnel", "staffing", "clearance"),
        custom_reasons={
            SPECIALIST_REQUIREMENTS_COMPLIANCE: "MANDATORY_CREDENTIAL_CHANGE",
            SPECIALIST_SCOPE_DELIVERABLES: "STAFFING_CREDENTIAL_SCOPE_CROSS_DOMAIN",
        },
    ),
    # 8. Scope & Deliverables
    _DomainRule(
        rule_id="SCOPE_DELIVERABLE_CHANGE",
        domains=(SPECIALIST_SCOPE_DELIVERABLES,),
        fact_types=(
            "SCOPE", "scope", "scope_item", "deliverable", "service_scope", "scope_delivery",
            "statement_of_work", "service", "resource_expectation",
            "specifications", "technical_requirements",
        ),
        entity_prefixes=("scope-", "scope:", "scope.", "deliv:", "deliv."),
    ),
    # 9. Delivery Geography / Scope Restriction (Cross-domain: Scope + Commercial)
    _DomainRule(
        rule_id="DELIVERY_GEOGRAPHY_COMMERCIAL_CROSS_DOMAIN",
        domains=(SPECIALIST_SCOPE_DELIVERABLES, SPECIALIST_COMMERCIAL_CONTRACTUAL),
        fact_types=(
            "scope_restriction", "delivery_geography", "geography_restriction",
            "delivery_location", "service_location", "territorial_restriction",
        ),
        entity_prefixes=("scope:geography", "scope.geography", "geography:", "geography.", "location:", "location."),
        keywords=("geography", "restriction", "location"),
        custom_reasons={
            SPECIALIST_SCOPE_DELIVERABLES: "SCOPE_DELIVERY_RESTRICTION_CHANGE",
            SPECIALIST_COMMERCIAL_CONTRACTUAL: "CONTRACT_GEOGRAPHY_COMMERCIAL_CROSS_DOMAIN",
        },
    ),
    # 10. Commercial Obligations
    _DomainRule(
        rule_id="COMMERCIAL_OBLIGATION_CHANGE",
        domains=(SPECIALIST_COMMERCIAL_CONTRACTUAL,),
        fact_types=(
            "COMMERCIAL", "commercial", "insurance", "insurance_limit", "liability", "liability_cap",
            "indemnity", "payment_terms", "commercial_obligation",
            "contractual_obligation", "warranty", "ip_rights", "termination",
            "liquidated_damages", "bonding", "confidentiality",
        ),
        entity_prefixes=("obl-", "comm:", "comm.", "commercial:", "commercial.", "obl:", "obl.", "insurance.", "insurance:"),
    ),
    # 11. Pricing Structure (Cross-domain: Commercial + Compliance)
    _DomainRule(
        rule_id="PRICING_STRUCTURE_CHANGE",
        domains=(SPECIALIST_COMMERCIAL_CONTRACTUAL, SPECIALIST_REQUIREMENTS_COMPLIANCE),
        fact_types=(
            "PRICING", "pricing", "pricing_structure", "pricing_model", "pricing_schedule",
            "rate_table", "pricing_terms", "fee_structure", "rate_structure",
        ),
        entity_prefixes=("price:", "pricing:", "price.", "pricing."),
        custom_reasons={
            SPECIALIST_COMMERCIAL_CONTRACTUAL: "PRICING_STRUCTURE_CHANGE",
            SPECIALIST_REQUIREMENTS_COMPLIANCE: "PRICING_COMPLIANCE_REQUIREMENTS_CROSS_DOMAIN",
        },
    ),
    # 12. Pricing Artifact / Replacement Form (Cross-domain: Commercial + Compliance + Schedule)
    _DomainRule(
        rule_id="PRICING_ARTIFACT_REPLACEMENT",
        domains=(
            SPECIALIST_COMMERCIAL_CONTRACTUAL,
            SPECIALIST_REQUIREMENTS_COMPLIANCE,
            SPECIALIST_SCHEDULE_SUBMISSION,
        ),
        fact_types=(
            "ARTIFACT", "artifact", "pricing_form", "replacement_pricing_form", "pricing_form_replacement",
            "pricing_artifact", "artifact.pricing_form",
        ),
        entity_prefixes=("artifact:pricing", "doc:pricing", "artifact.pricing", "artifact.", "artifact:"),
        custom_reasons={
            SPECIALIST_COMMERCIAL_CONTRACTUAL: "PRICING_ARTIFACT_COMMERCIAL_CHANGE",
            SPECIALIST_REQUIREMENTS_COMPLIANCE: "PRICING_FORM_SUBMISSION_COMPLIANCE_CROSS_DOMAIN",
            SPECIALIST_SCHEDULE_SUBMISSION: "PRICING_FORM_SUBMISSION_MECHANICS_CROSS_DOMAIN",
        },
    ),
    # 13. Procurement Structure & Roles
    _DomainRule(
        rule_id="PROCUREMENT_STRUCTURE_CHANGE",
        domains=(SPECIALIST_PROCUREMENT_STRUCTURE,),
        fact_types=(
            "procurement_identity", "document_role", "document_relationship",
            "package_completeness", "service_category", "procurement_structure",
        ),
        entity_prefixes=("ident", "doc-", "rel-", "pkg", "cat-", "doc.", "rel."),
    ),
)


def route_change_to_domains(fact: FactChange) -> ChangeRoutingDecision:
    """Pure deterministic router mapping one applied FactChange to affected specialist domains."""
    change_id = fact.entity_id or fact.fact_type or "unknown_change"

    # Authority boundary: only approved, non-conflict changes can route
    if fact.review_status != REVIEW_STATUS_APPROVED or fact.change_type == CHANGE_CONFLICTS_WITH:
        return ChangeRoutingDecision(
            change_id=change_id,
            affected_domains=(),
            reasons=(),
        )

    # Zero-impact changes: unchanged facts and administrative metadata
    if fact.change_type == CHANGE_UNCHANGED or fact.fact_type in ZERO_IMPACT_FACT_TYPES:
        return ChangeRoutingDecision(
            change_id=change_id,
            affected_domains=(),
            reasons=(),
        )

    norm_ft = _normalize_key(fact.fact_type)
    norm_eid = _normalize_key(fact.entity_id)

    affected: set[str] = set()
    reasons: list[DomainRoutingReason] = []

    for rule in DOMAIN_ROUTING_RULES:
        matched = False
        norm_rule_fts = {_normalize_key(ft) for ft in rule.fact_types}
        if norm_ft in norm_rule_fts:
            matched = True
        elif any(norm_eid.startswith(_normalize_key(prefix)) for prefix in rule.entity_prefixes):
            matched = True
        elif rule.keywords and any(kw in norm_ft or kw in norm_eid for kw in rule.keywords):
            matched = True

        if matched:
            for domain in rule.domains:
                affected.add(domain)
                rule_name = (rule.custom_reasons or {}).get(domain, rule.rule_id)
                reasons.append(DomainRoutingReason(domain=domain, rule=rule_name))

    # Deduplicate reasons while preserving order
    seen_reasons = set()
    deduped_reasons = []
    for r in reasons:
        k = (r.domain, r.rule)
        if k not in seen_reasons:
            seen_reasons.add(k)
            deduped_reasons.append(r)

    return ChangeRoutingDecision(
        change_id=change_id,
        affected_domains=tuple(sorted(affected)),
        reasons=tuple(deduped_reasons),
    )


def generate_revision_impact_plan(
    change_set_or_revision: ProcurementRevision | ProcurementChangeSet,
    authoritative_state: AuthoritativeProcurementState | None = None,
    existing_findings: Sequence[dict[str, Any]] | None = None,
    *,
    applied: bool = False,
    bid_id: int | None = None,
) -> RevisionImpactPlan:
    """Generates the deterministic RevisionImpactPlan for an applied revision/changeset.
    Consumes ONLY authoritative applied changes.
    Does NOT run specialists or make model calls."""
    is_rev = isinstance(change_set_or_revision, ProcurementRevision)
    rev_num = change_set_or_revision.revision_number if is_rev else change_set_or_revision.revision
    rev_id = change_set_or_revision.revision_id if is_rev else f"changeset-rev-{rev_num}"
    change_set = change_set_or_revision.change_set if is_rev else change_set_or_revision
    cs_fp = change_set.fingerprint or ""

    state_fp = authoritative_state.state_fingerprint if authoritative_state is not None else ""

    is_applied = (
        change_set_or_revision.is_applied
        and change_set_or_revision.review_status == "applied"
        and not change_set_or_revision.chronology_unresolved
    ) if is_rev else applied

    # Authority boundary check: only applied revisions/changesets can mutate canonical intelligence
    if not is_applied:
        return RevisionImpactPlan(
            revision_number=rev_num,
            revision_id=rev_id,
            change_set_fingerprint=cs_fp,
            state_fingerprint=state_fp,
            affected_domains=[],
            retained_finding_ids=[
                str(f.get("finding_id")) for f in (existing_findings or [])
                if isinstance(f, dict) and f.get("finding_id")
            ],
            stale_finding_ids=[],
            unresolved_finding_ids=[],
            finding_impacts={
                str(f.get("finding_id")): {
                    "status": FINDING_STATUS_RETAINED,
                    "reasons": [{"rule": "UNAPPLIED_BUYER_UPDATE_CANONICAL_UNTOUCHED"}],
                }
                for f in (existing_findings or [])
                if isinstance(f, dict) and f.get("finding_id")
            },
            routing_reasons=[],
        )

    # Route changes to affected specialist domains
    affected_domains_set: set[str] = set()
    routing_reasons_list: list[dict[str, Any]] = []

    # Collect changed entity keys for finding dependency matching ONLY from changes with affected domains
    changed_keys: set[str] = set()
    normalized_changed_keys: set[str] = set()

    for c in change_set.changes:
        if c.review_status != REVIEW_STATUS_APPROVED or c.change_type == CHANGE_CONFLICTS_WITH:
            continue
        if c.change_type == CHANGE_UNCHANGED:
            continue

        decision = route_change_to_domains(c)
        if decision.affected_domains:
            affected_domains_set.update(decision.affected_domains)
            routing_reasons_list.append(decision.to_dict())

            # Collect keys ONLY if this change affected at least one domain
            for val in (c.entity_id, c.fact_type, c.metadata.get("canonical_id")):
                if val:
                    variants = _expand_key_variants(val)
                    changed_keys.update(variants)
                    normalized_changed_keys.update(_normalize_key(v) for v in variants)

            if isinstance(c.metadata.get("canonical_ids"), (list, tuple)):
                for cid in c.metadata["canonical_ids"]:
                    variants = _expand_key_variants(cid)
                    changed_keys.update(variants)
                    normalized_changed_keys.update(_normalize_key(v) for v in variants)

            if c.metadata.get("artifact_id"):
                variants = _expand_key_variants(c.metadata["artifact_id"])
                changed_keys.update(variants)
                normalized_changed_keys.update(_normalize_key(v) for v in variants)

            # Artifact replacement
            if (c.fact_type in ("artifact_replacement", "pricing_form", "revised_form") or c.change_type == CHANGE_REPLACES) and c.before_value:
                b_val = c.before_value.get("name") if isinstance(c.before_value, dict) else str(c.before_value)
                variants = _expand_key_variants(b_val)
                changed_keys.update(variants)
                normalized_changed_keys.update(_normalize_key(v) for v in variants)

    # Check superseded artifacts in state
    if authoritative_state is not None:
        for art_id, art_rec in authoritative_state.active_artifacts.items():
            if art_rec.status == AUTHORITY_SUPERSEDED:
                variants = _expand_key_variants(art_rec.artifact_id) | _expand_key_variants(art_rec.name)
                changed_keys.update(variants)
                normalized_changed_keys.update(_normalize_key(v) for v in variants)
            if art_rec.replaces_artifact_id:
                variants = _expand_key_variants(art_rec.replaces_artifact_id)
                changed_keys.update(variants)
                normalized_changed_keys.update(_normalize_key(v) for v in variants)

    # Evaluate existing findings
    retained_ids: list[str] = []
    stale_ids: list[str] = []
    unresolved_ids: list[str] = []
    finding_impacts: dict[str, dict[str, Any]] = {}

    for raw_f in (existing_findings or []):
        f = raw_f.as_dict() if hasattr(raw_f, "as_dict") else (raw_f.to_dict() if hasattr(raw_f, "to_dict") else raw_f)
        if not isinstance(f, dict):
            continue

        fid = str(f.get("finding_id") or "UNKNOWN_ID")
        canonical_ids = [str(x).strip() for x in (f.get("canonical_ids") or []) if str(x).strip()]
        dependencies = [str(x).strip() for x in (f.get("dependencies") or []) if str(x).strip()]
        artifact_ids = [str(x).strip() for x in (f.get("artifact_ids") or []) if str(x).strip()]
        source_refs = [str(x).strip() for x in (f.get("source_refs") or []) if str(x).strip()]

        has_deps = bool(canonical_ids or dependencies or artifact_ids or source_refs)

        # Insufficient dependency metadata check
        if not has_deps:
            status = FINDING_STATUS_UNRESOLVED
            reasons = [{"rule": "UNRESOLVED_FINDING_DEPENDENCY", "reason": "INSUFFICIENT_DEPENDENCY_METADATA"}]
            unresolved_ids.append(fid)
            finding_impacts[fid] = {"status": status, "reasons": reasons}
            continue

        # Check if finding depends on any changed key
        finding_keys: set[str] = set()
        for k in (canonical_ids + dependencies + artifact_ids + source_refs):
            finding_keys.update(_expand_key_variants(k))

        matched_deps = []
        for k in finding_keys:
            if k in changed_keys or _normalize_key(k) in normalized_changed_keys:
                matched_deps.append(k)

        if matched_deps:
            status = FINDING_STATUS_STALE
            reasons = [{
                "rule": "AUTHORITATIVE_DEPENDENCY_CHANGED",
                "matched_dependencies": sorted(set(matched_deps)),
            }]
            stale_ids.append(fid)
        else:
            status = FINDING_STATUS_RETAINED
            reasons = [{"rule": "DEPENDENCIES_UNAFFECTED"}]
            retained_ids.append(fid)

        finding_impacts[fid] = {"status": status, "reasons": reasons}

    return RevisionImpactPlan(
        revision_number=rev_num,
        revision_id=rev_id,
        change_set_fingerprint=cs_fp,
        state_fingerprint=state_fp,
        affected_domains=sorted(affected_domains_set),
        retained_finding_ids=sorted(retained_ids),
        stale_finding_ids=sorted(stale_ids),
        unresolved_finding_ids=sorted(unresolved_ids),
        finding_impacts=finding_impacts,
        routing_reasons=routing_reasons_list,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 11. Revision-Aware Specialist Context (PCI-B2A)
# ═══════════════════════════════════════════════════════════════════════════

BINDING_EXISTING_CANONICAL = "EXISTING_CANONICAL"
BINDING_REVISION_FACT = "REVISION_FACT"
BINDING_UNRESOLVED = "UNRESOLVED"

CHANGE_BINDING_TYPES = (
    BINDING_EXISTING_CANONICAL,
    BINDING_REVISION_FACT,
    BINDING_UNRESOLVED,
)


@dataclass(frozen=True)
class ChangeBinding:
    """Deterministic binding between a FactChange and a canonical object or revision fact."""
    change_id: str
    entity_id: str
    fact_type: str
    binding_type: str
    canonical_id: str | None
    object_type: str | None
    binding_rationale: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "entity_id": self.entity_id,
            "fact_type": self.fact_type,
            "binding_type": self.binding_type,
            "canonical_id": self.canonical_id,
            "object_type": self.object_type,
            "binding_rationale": self.binding_rationale,
        }

    to_dict = as_dict


@dataclass(frozen=True)
class RevisionFact:
    """Additive or newly introduced procurement fact created from an applied revision."""
    fact_id: str
    fact_type: str
    entity_id: str
    value: Any
    change_type: str
    source_document_id: int
    source_document: str
    source_hash: str
    revision_id: str
    revision_number: int
    effective_date: str | None
    authority_status: str
    review_status: str
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "canonical_id": self.fact_id,
            "fact_type": self.fact_type,
            "entity_id": self.entity_id,
            "value": self.value,
            "change_type": self.change_type,
            "source_document_id": self.source_document_id,
            "source_document": self.source_document,
            "source_hash": self.source_hash,
            "revision_id": self.revision_id,
            "revision_number": self.revision_number,
            "effective_date": self.effective_date,
            "authority_status": self.authority_status,
            "review_status": self.review_status,
            "description": self.description,
            "metadata": dict(self.metadata),
        }

    to_dict = as_dict


@dataclass(frozen=True)
class RevisionSpecialistContext:
    """Authoritative revision-aware specialist execution context.

    Carries overlayed current active canonical objects, revision facts,
    provenance, and filtered prior findings for ONE affected specialist domain.
    """
    specialist_id: str
    revision_number: int
    revision_id: str
    bid_id: int | None
    context_fingerprint: str
    impacted_domain: str
    impact_plan_fingerprint: str
    base_package_digest: str
    relevant_changes: tuple[dict[str, Any], ...]
    relevant_current_canonical_objects: tuple[dict[str, Any], ...]
    revision_facts: tuple[RevisionFact, ...]
    permitted_canonical_ids: tuple[str, ...]
    stale_prior_finding_ids: tuple[str, ...]
    stale_prior_findings: tuple[dict[str, Any], ...]
    retained_prior_findings: tuple[dict[str, Any], ...]
    change_bindings: tuple[ChangeBinding, ...]
    is_executable: bool
    blocking_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "specialist_id": self.specialist_id,
            "revision_number": self.revision_number,
            "revision_id": self.revision_id,
            "bid_id": self.bid_id,
            "context_fingerprint": self.context_fingerprint,
            "impacted_domain": self.impacted_domain,
            "impact_plan_fingerprint": self.impact_plan_fingerprint,
            "base_package_digest": self.base_package_digest,
            "relevant_changes": list(self.relevant_changes),
            "relevant_current_canonical_objects": list(self.relevant_current_canonical_objects),
            "revision_facts": [rf.as_dict() for rf in self.revision_facts],
            "permitted_canonical_ids": list(self.permitted_canonical_ids),
            "stale_prior_finding_ids": list(self.stale_prior_finding_ids),
            "stale_prior_findings": list(self.stale_prior_findings),
            "retained_prior_findings": list(self.retained_prior_findings),
            "change_bindings": [cb.as_dict() for cb in self.change_bindings],
            "is_executable": self.is_executable,
            "blocking_reason": self.blocking_reason,
        }

    to_dict = as_dict


@dataclass(frozen=True)
class CurrentCanonicalView:
    """Current Authoritative Canonical View (PCI-B2B.1).
    Derived deterministically by replaying all applied revisions against the base
    CanonicalPackage. Provides the unified, cumulative authoritative procurement truth
    for specialists and reconciliation."""
    bid_id: int
    analysis_run_id: int
    package_digest: str
    identity: MappingProxyType
    document_roles: tuple[dict[str, Any], ...]
    document_relationships: tuple[dict[str, Any], ...]
    package_completeness: MappingProxyType
    service_categories: tuple[dict[str, Any], ...]
    requirements: tuple[dict[str, Any], ...]
    scoped_criteria: tuple[dict[str, Any], ...]
    category_scope_items: tuple[dict[str, Any], ...]
    commercial_obligations: tuple[dict[str, Any], ...]
    milestones: tuple[dict[str, Any], ...]
    submission_mechanics: MappingProxyType
    canonical_ids: frozenset[str]
    active_revision_facts: tuple[RevisionFact, ...] = ()
    removed_canonical_ids: frozenset[str] = frozenset()
    base_package_digest: str = ""

    def objects_of_type(self, object_type: str) -> tuple[dict[str, Any], ...]:
        from full_analysis import (
            OBJ_PROCUREMENT_IDENTITY,
            OBJ_DOCUMENT_ROLE,
            OBJ_DOCUMENT_RELATIONSHIP,
            OBJ_PACKAGE_COMPLETENESS,
            OBJ_SERVICE_CATEGORY,
            OBJ_CANONICAL_REQUIREMENT,
            OBJ_SCOPED_EVALUATION_CRITERION,
            OBJ_CATEGORY_SCOPE_ITEM,
            OBJ_COMMERCIAL_OBLIGATION,
            OBJ_SCOPED_MILESTONE,
            OBJ_SUBMISSION_MECHANICS,
        )
        mapping = {
            OBJ_PROCUREMENT_IDENTITY: (dict(self.identity),),
            OBJ_DOCUMENT_ROLE: tuple(self.document_roles),
            OBJ_DOCUMENT_RELATIONSHIP: tuple(self.document_relationships),
            OBJ_PACKAGE_COMPLETENESS: (dict(self.package_completeness),),
            OBJ_SERVICE_CATEGORY: tuple(self.service_categories),
            OBJ_CANONICAL_REQUIREMENT: tuple(self.requirements),
            OBJ_SCOPED_EVALUATION_CRITERION: tuple(self.scoped_criteria),
            OBJ_CATEGORY_SCOPE_ITEM: tuple(self.category_scope_items),
            OBJ_COMMERCIAL_OBLIGATION: tuple(self.commercial_obligations),
            OBJ_SCOPED_MILESTONE: tuple(self.milestones),
            OBJ_SUBMISSION_MECHANICS: (dict(self.submission_mechanics),),
        }
        return mapping.get(object_type, ())

    def to_dict(self) -> dict[str, Any]:
        return {
            "bid_id": self.bid_id,
            "analysis_run_id": self.analysis_run_id,
            "package_digest": self.package_digest,
            "base_package_digest": self.base_package_digest,
            "identity": dict(self.identity),
            "document_roles": list(self.document_roles),
            "document_relationships": list(self.document_relationships),
            "package_completeness": dict(self.package_completeness),
            "service_categories": list(self.service_categories),
            "requirements": list(self.requirements),
            "scoped_criteria": list(self.scoped_criteria),
            "category_scope_items": list(self.category_scope_items),
            "commercial_obligations": list(self.commercial_obligations),
            "milestones": list(self.milestones),
            "submission_mechanics": dict(self.submission_mechanics),
            "canonical_ids": sorted(self.canonical_ids),
            "active_revision_facts": [rf.as_dict() for rf in self.active_revision_facts],
            "removed_canonical_ids": sorted(self.removed_canonical_ids),
        }

    as_dict = to_dict


def _slug(text: Any, limit: int = 40) -> str:
    cleaned = re.sub(r'[^a-z0-9]+', '-', str(text or "").strip().lower()).strip('-')
    return cleaned[:limit] or "x"


def _thaw(value: Any) -> Any:
    if isinstance(value, (MappingProxyType, dict)):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_thaw(v) for v in value]
    return value


def _digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def derive_current_canonical_view(
    package: Any,
    revisions: Sequence[ProcurementRevision],
    up_to_revision_number: int | None = None,
    up_to_buyer_chronology_index: int | None = None,
) -> CurrentCanonicalView:
    """Deterministically replay all applied revisions against the base CanonicalPackage
    up to the target revision / buyer chronology index.
    Produces the authoritative, unified CurrentCanonicalView (PCI-B2B.1)."""
    from full_analysis import (
        OBJ_PROCUREMENT_IDENTITY,
        OBJ_DOCUMENT_ROLE,
        OBJ_DOCUMENT_RELATIONSHIP,
        OBJ_PACKAGE_COMPLETENESS,
        OBJ_SERVICE_CATEGORY,
        OBJ_CANONICAL_REQUIREMENT,
        OBJ_SCOPED_EVALUATION_CRITERION,
        OBJ_CATEGORY_SCOPE_ITEM,
        OBJ_COMMERCIAL_OBLIGATION,
        OBJ_SCOPED_MILESTONE,
        OBJ_SUBMISSION_MECHANICS,
    )

    base_digest = getattr(package, "package_digest", "") or ""
    bid_id = getattr(package, "bid_id", 0)
    analysis_run_id = getattr(package, "analysis_run_id", 0)

    # 1. Base mutable pools (deep-copied from base package)
    raw_ident = getattr(package, "identity", {})
    identity_dict = copy.deepcopy(dict(raw_ident) if isinstance(raw_ident, (dict, MappingProxyType)) else {})
    if "fields" not in identity_dict:
        identity_dict["fields"] = {}
    else:
        identity_dict["fields"] = copy.deepcopy(dict(identity_dict["fields"]))

    raw_comp = getattr(package, "package_completeness", {})
    completeness_dict = copy.deepcopy(dict(raw_comp) if isinstance(raw_comp, (dict, MappingProxyType)) else {})

    raw_sub = getattr(package, "submission_mechanics", {})
    submission_dict = copy.deepcopy(dict(raw_sub) if isinstance(raw_sub, (dict, MappingProxyType)) else {})
    if "page_limits" in submission_dict:
        submission_dict["page_limits"] = copy.deepcopy(dict(submission_dict["page_limits"]))

    roles_by_id = {
        d["canonical_id"]: copy.deepcopy(d)
        for d in (getattr(package, "document_roles", ()) or ())
        if isinstance(d, dict) and d.get("canonical_id")
    }
    rels_by_id = {
        r["canonical_id"]: copy.deepcopy(r)
        for r in (getattr(package, "document_relationships", ()) or ())
        if isinstance(r, dict) and r.get("canonical_id")
    }
    cats_by_label = {
        c["label"]: copy.deepcopy(c)
        for c in (getattr(package, "service_categories", ()) or ())
        if isinstance(c, dict) and c.get("label")
    }
    criteria_by_id = {
        c["canonical_id"]: copy.deepcopy(c)
        for c in (getattr(package, "scoped_criteria", ()) or ())
        if isinstance(c, dict) and c.get("canonical_id")
    }
    scope_by_id = {
        s["canonical_id"]: copy.deepcopy(s)
        for s in (getattr(package, "category_scope_items", ()) or ())
        if isinstance(s, dict) and s.get("canonical_id")
    }
    reqs_by_id = {
        r["canonical_id"]: copy.deepcopy(r)
        for r in (getattr(package, "requirements", ()) or ())
        if isinstance(r, dict) and r.get("canonical_id")
    }
    obls_by_id = {
        o["canonical_id"]: copy.deepcopy(o)
        for o in (getattr(package, "commercial_obligations", ()) or ())
        if isinstance(o, dict) and o.get("canonical_id")
    }
    ms_by_id = {
        m["canonical_id"]: copy.deepcopy(m)
        for m in (getattr(package, "milestones", ()) or ())
        if isinstance(m, dict) and m.get("canonical_id")
    }

    # 2. Filter applied revisions up to the requested target
    applied = [
        r for r in revisions
        if r.is_applied and r.review_status == "applied" and not r.chronology_unresolved
    ]
    ordered_revs = sorted(applied, key=lambda r: (r.buyer_chronology_index, r.revision_number))
    if up_to_buyer_chronology_index is not None:
        ordered_revs = [r for r in ordered_revs if r.buyer_chronology_index <= up_to_buyer_chronology_index]
    if up_to_revision_number is not None:
        ordered_revs = [r for r in ordered_revs if r.revision_number <= up_to_revision_number]

    active_revision_facts: dict[str, RevisionFact] = {}
    removed_canonical_ids: set[str] = set()

    for rev in ordered_revs:
        for c in rev.change_set.changes:
            if c.review_status != REVIEW_STATUS_APPROVED or c.change_type == CHANGE_CONFLICTS_WITH:
                continue
            if c.change_type == CHANGE_UNCHANGED:
                continue

            # Candidate pool of current active objects
            candidate_pool = (
                list(criteria_by_id.values())
                + list(scope_by_id.values())
                + list(reqs_by_id.values())
                + list(obls_by_id.values())
                + list(ms_by_id.values())
                + list(roles_by_id.values())
                + list(rels_by_id.values())
                + [submission_dict, identity_dict, completeness_dict]
            )

            matched_obj, _ = _match_canonical_object(c, candidate_pool)

            matched_rf = None
            if matched_obj is None:
                meta_cid = c.metadata.get("canonical_id")
                if meta_cid and meta_cid in active_revision_facts:
                    matched_rf = active_revision_facts[meta_cid]
                elif c.entity_id in active_revision_facts:
                    matched_rf = active_revision_facts[c.entity_id]
                else:
                    rf_matches = [rf for rf in active_revision_facts.values() if rf.entity_id == c.entity_id]
                    if len(rf_matches) == 1:
                        matched_rf = rf_matches[0]

            if matched_obj is not None:
                cid = matched_obj.get("canonical_id")
                if c.change_type == CHANGE_REMOVES:
                    if cid:
                        removed_canonical_ids.add(cid)
                        criteria_by_id.pop(cid, None)
                        scope_by_id.pop(cid, None)
                        reqs_by_id.pop(cid, None)
                        obls_by_id.pop(cid, None)
                        ms_by_id.pop(cid, None)
                        roles_by_id.pop(cid, None)
                        rels_by_id.pop(cid, None)
                else:
                    _apply_change_overlay(matched_obj, c, rev)
                    if matched_obj.get("object_type") == OBJ_SUBMISSION_MECHANICS or cid == "SUBMISSION":
                        submission_dict.update(matched_obj)
                        if "submission_deadline" in matched_obj:
                            identity_dict.setdefault("fields", {})["submission_deadline"] = {
                                "value": matched_obj["submission_deadline"],
                                "source_doc": c.source_document,
                            }
                        if "clarification_deadline" in matched_obj:
                            identity_dict.setdefault("fields", {})["clarification_deadline"] = {
                                "value": matched_obj["clarification_deadline"],
                                "source_doc": c.source_document,
                            }
                    elif matched_obj.get("object_type") == OBJ_PROCUREMENT_IDENTITY or cid == "IDENT":
                        identity_dict.update(matched_obj)

            elif matched_rf is not None:
                fid = matched_rf.fact_id
                if c.change_type == CHANGE_REMOVES:
                    removed_canonical_ids.add(fid)
                    active_revision_facts.pop(fid, None)
                else:
                    updated_desc = c.metadata.get("description")
                    if not updated_desc:
                        updated_desc = str(c.after_value) if not isinstance(c.after_value, dict) else c.after_value.get("description", matched_rf.description)
                    updated_rf = replace(
                        matched_rf,
                        value=c.after_value,
                        change_type=c.change_type,
                        authority_status=c.authority_status,
                        review_status=c.review_status,
                        description=updated_desc,
                        metadata=dict(c.metadata),
                    )
                    active_revision_facts[fid] = updated_rf

            else:
                if c.change_type == CHANGE_ADDS:
                    if c.source_document_id is not None and c.source_hash:
                        fact_id = f"REV-FACT-{_slug(c.entity_id)}"
                        eff_date = getattr(rev, "effective_date", None) or getattr(rev, "buyer_issued_date", None)
                        rf = RevisionFact(
                            fact_id=fact_id,
                            fact_type=c.fact_type,
                            entity_id=c.entity_id,
                            value=c.after_value,
                            change_type=c.change_type,
                            source_document_id=c.source_document_id,
                            source_document=c.source_document,
                            source_hash=c.source_hash,
                            revision_id=rev.revision_id,
                            revision_number=rev.revision_number,
                            effective_date=eff_date,
                            authority_status=c.authority_status,
                            review_status=c.review_status,
                            description=c.metadata.get("description") or (str(c.after_value) if not isinstance(c.after_value, dict) else c.after_value.get("description")),
                            metadata=dict(c.metadata),
                        )
                        active_revision_facts[fact_id] = rf
                elif c.change_type == CHANGE_REMOVES:
                    rem_id = c.metadata.get("canonical_id") or c.entity_id
                    if rem_id:
                        removed_canonical_ids.add(rem_id)
                        criteria_by_id.pop(rem_id, None)
                        scope_by_id.pop(rem_id, None)
                        reqs_by_id.pop(rem_id, None)
                        obls_by_id.pop(rem_id, None)
                        ms_by_id.pop(rem_id, None)
                        active_revision_facts.pop(rem_id, None)

    active_criteria = tuple(
        c for cid, c in criteria_by_id.items() if cid not in removed_canonical_ids
    )
    active_scope = tuple(
        s for sid, s in scope_by_id.items() if sid not in removed_canonical_ids
    )

    # Recalculate derived service categories deterministically
    all_cat_labels = sorted(
        {c.get("category_scope") for c in active_criteria if c.get("category_scope")}
        | {s.get("category_scope") for s in active_scope if s.get("category_scope")}
        | set(cats_by_label.keys())
    )
    derived_categories = []
    for label in all_cat_labels:
        crit_count = sum(1 for c in active_criteria if c.get("category_scope") == label)
        scope_count = sum(1 for s in active_scope if s.get("category_scope") == label)
        cid = f"CAT-{_slug(label)}"
        derived_categories.append({
            "canonical_id": cid,
            "object_type": OBJ_SERVICE_CATEGORY,
            "label": label,
            "criterion_count": crit_count,
            "scope_item_count": scope_count,
        })
    service_categories = tuple(derived_categories)

    # Active requirements = native non-removed + active REV-FACT requirements
    reqs_list = [r for cid, r in reqs_by_id.items() if cid not in removed_canonical_ids]
    for fid, rf in sorted(active_revision_facts.items()):
        ft = _normalize_key(rf.fact_type)
        if "req" in ft or "compliance" in ft or "mandatory" in ft or "requirement" in ft:
            req_obj = {
                "canonical_id": rf.fact_id,
                "object_type": OBJ_CANONICAL_REQUIREMENT,
                "description": rf.description or str(rf.value),
                "requirement_type": "MANDATORY" if "mandatory" in ft else "STANDARD",
                "semantic_type": "MANDATORY_REQUIREMENT" if "mandatory" in ft else "GENERAL_REQUIREMENT",
                "applicability": "ALL",
                "applicable_category_ids": [],
                "source_docs": [rf.source_document] if rf.source_document else [],
                "source_refs": [f"doc:{rf.source_document_id}"] if rf.source_document_id else [],
                "source_document_id": rf.source_document_id,
                "revision_number": rf.revision_number,
                "last_modified_revision": rf.revision_number,
            }
            reqs_list.append(req_obj)
    requirements = tuple(reqs_list)

    commercial_obligations = tuple(
        o for oid, o in obls_by_id.items() if oid not in removed_canonical_ids
    )
    milestones = tuple(
        m for mid, m in ms_by_id.items() if mid not in removed_canonical_ids
    )
    document_roles = tuple(
        d for did, d in roles_by_id.items() if did not in removed_canonical_ids
    )
    document_relationships = tuple(
        r for rid, r in rels_by_id.items() if rid not in removed_canonical_ids
    )

    all_cids = {"IDENT", "SUBMISSION", "PKG"}
    for group in (document_roles, document_relationships, service_categories, requirements,
                  active_criteria, active_scope, commercial_obligations, milestones):
        all_cids |= {o["canonical_id"] for o in group if o.get("canonical_id")}
    for fid in active_revision_facts.keys():
        all_cids.add(fid)
    all_cids -= removed_canonical_ids

    view_digest_payload = {
        "identity": identity_dict,
        "document_roles": list(document_roles),
        "requirements": list(requirements),
        "scoped_criteria": list(active_criteria),
        "category_scope_items": list(active_scope),
        "commercial_obligations": list(commercial_obligations),
        "milestones": list(milestones),
        "submission": submission_dict,
    }
    current_view_digest = _digest(view_digest_payload)

    return CurrentCanonicalView(
        bid_id=bid_id,
        analysis_run_id=analysis_run_id,
        package_digest=current_view_digest,
        base_package_digest=base_digest,
        identity=MappingProxyType(identity_dict),
        document_roles=document_roles,
        document_relationships=document_relationships,
        package_completeness=MappingProxyType(completeness_dict),
        service_categories=service_categories,
        requirements=requirements,
        scoped_criteria=active_criteria,
        category_scope_items=active_scope,
        commercial_obligations=commercial_obligations,
        milestones=milestones,
        submission_mechanics=MappingProxyType(submission_dict),
        canonical_ids=frozenset(all_cids),
        active_revision_facts=tuple(active_revision_facts.values()),
        removed_canonical_ids=frozenset(removed_canonical_ids),
    )


def _clean_obj_for_fingerprint(obj: Any) -> Any:
    if isinstance(obj, RevisionFact):
        obj = obj.as_dict()
    elif hasattr(obj, "as_dict"):
        obj = obj.as_dict()
    elif hasattr(obj, "to_dict"):
        obj = obj.to_dict()

    if isinstance(obj, dict):
        noise_keys = {
            "created_at", "updated_at", "timestamp", "db_id", "row_id",
            "latency_seconds", "execution_time", "duration_seconds",
        }
        cleaned = {}
        for k, v in obj.items():
            if k in noise_keys:
                continue
            cleaned[k] = _clean_obj_for_fingerprint(v)
        return cleaned
    if isinstance(obj, (list, tuple)):
        return [_clean_obj_for_fingerprint(x) for x in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(str(x) for x in obj)
    return obj


def compute_specialist_context_fingerprint(
    specialist_id: str,
    revision_number: int,
    revision_id: str,
    change_set_fingerprint: str = "",
    state_fingerprint: str = "",
    canonical_package_digest: str = "",
    permitted_canonical_ids: Sequence[str] = (),
    stale_prior_finding_ids: Sequence[str] = (),
    *,
    impact_plan_fingerprint: str = "",
    base_package_digest: str = "",
    relevant_canonical_objects: Sequence[dict[str, Any]] = (),
    revision_facts: Sequence[Any] = (),
    relevant_changes: Sequence[dict[str, Any]] = (),
    stale_prior_findings: Sequence[dict[str, Any]] = (),
    retained_prior_findings: Sequence[dict[str, Any]] = (),
) -> str:
    """Computes stable, deterministic SHA-256 fingerprint for RevisionSpecialistContext.
    Reflects the ACTUAL semantic context consumed by specialists:
    includes semantic content of canonical objects, revision facts, relevant changes,
    stale prior findings, and retained prior findings.
    Excludes noise: timestamps, DB row IDs, execution time, and dictionary/list ordering."""
    bp_digest = str(base_package_digest or canonical_package_digest or "")
    ip_fp = str(impact_plan_fingerprint or change_set_fingerprint or "")

    clean_stale_findings = sorted(
        [_clean_obj_for_fingerprint(f) for f in stale_prior_findings if isinstance(f, dict)],
        key=lambda x: str(x.get("finding_id", ""))
    )
    clean_retained_findings = sorted(
        [_clean_obj_for_fingerprint(f) for f in retained_prior_findings if isinstance(f, dict)],
        key=lambda x: str(x.get("finding_id", ""))
    )
    clean_canonical_objs = sorted(
        [_clean_obj_for_fingerprint(o) for o in relevant_canonical_objects if isinstance(o, dict)],
        key=lambda x: (str(x.get("canonical_id", "")), str(x.get("object_type", "")))
    )
    clean_revision_facts = sorted(
        [_clean_obj_for_fingerprint(rf) for rf in revision_facts],
        key=lambda x: str(x.get("fact_id", "") if isinstance(x, dict) else getattr(x, "fact_id", ""))
    )
    clean_changes = sorted(
        [_clean_obj_for_fingerprint(c) for c in relevant_changes if isinstance(c, dict)],
        key=lambda x: (str(x.get("entity_id", "")), str(x.get("fact_type", "")))
    )

    payload = {
        "specialist_id": str(specialist_id),
        "revision_number": int(revision_number),
        "revision_id": str(revision_id),
        "impact_plan_fingerprint": ip_fp,
        "base_package_digest": bp_digest,
        "permitted_canonical_ids": sorted(set(str(x) for x in permitted_canonical_ids)),
        "stale_prior_finding_ids": sorted(set(str(x) for x in stale_prior_finding_ids)),
        "stale_prior_findings": clean_stale_findings,
        "retained_prior_findings": clean_retained_findings,
        "relevant_canonical_objects": clean_canonical_objs,
        "revision_facts": clean_revision_facts,
        "relevant_changes": clean_changes,
    }
    return _digest(payload)


def _extract_package_objects(canonical_package: Any, specialist_id: str) -> list[dict[str, Any]]:
    """Extracts deep-copied, mutable dictionary representations of canonical objects
    permitted for specialist_id without mutating the underlying canonical package."""
    from full_analysis import CANONICAL_OBJECT_TYPES, SPECIALIST_INPUT_TYPES, CanonicalBoundaryError

    if specialist_id not in SPECIALIST_INPUT_TYPES:
        raise CanonicalBoundaryError(f"unknown specialist id: {specialist_id!r}")

    permitted_types = SPECIALIST_INPUT_TYPES[specialist_id]
    extracted: list[dict[str, Any]] = []

    for obj_type in CANONICAL_OBJECT_TYPES:
        if obj_type not in permitted_types:
            continue

        raw_objs: Sequence[Any] = []
        if hasattr(canonical_package, "objects_of_type"):
            try:
                raw_objs = canonical_package.objects_of_type(obj_type)
            except Exception:
                raw_objs = []
        elif isinstance(canonical_package, dict):
            raw_objs = canonical_package.get("objects", {}).get(obj_type, [])
            if not raw_objs and obj_type in canonical_package:
                raw_objs = canonical_package[obj_type]
        else:
            attr_name = obj_type.lower()
            if hasattr(canonical_package, attr_name):
                raw_objs = getattr(canonical_package, attr_name)

        if not raw_objs and hasattr(canonical_package, "objects") and isinstance(canonical_package.objects, dict):
            raw_objs = canonical_package.objects.get(obj_type, [])

        if isinstance(raw_objs, (dict, MappingProxyType)):
            raw_objs = [raw_objs]

        for item in raw_objs:
            thawed = _thaw(item)
            if isinstance(thawed, dict):
                obj_copy = copy.deepcopy(thawed)
                if "object_type" not in obj_copy:
                    obj_copy["object_type"] = obj_type
                extracted.append(obj_copy)

    return extracted


def _clean_semantic_key(key: str) -> str:
    s = str(key or "").strip().lower()
    s = re.sub(r'[\s\:\-_/]+', '.', s)
    for p in ("eval.", "crit.", "obl.", "comm.", "scope.", "req.", "ms.", "sub.", "doc.", "artifact."):
        if s.startswith(p):
            s = s[len(p):]
    for suf in (".weight", ".threshold", ".limit", ".score", ".date", ".time", ".deliverable", ".terms", ".requirements"):
        if s.endswith(suf):
            s = s[:-len(suf)]
    return s


def _match_canonical_object(
    change: FactChange,
    candidate_objects: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    """Finds the matching canonical object for a FactChange following strict fail-closed precedence:
    1. Explicit metadata canonical_id
    2. Explicit metadata canonical_ids
    3. Exact normalized canonical identity (entity_id matches canonical_id)
    4. Deterministic exact / unambiguous semantic key match
    5. Otherwise UNRESOLVED (fails closed with diagnostic reason, never weak token guessing)
    Returns (matched_obj, unresolve_reason).
    """
    from full_analysis import (
        OBJ_SCOPED_EVALUATION_CRITERION,
        OBJ_SUBMISSION_MECHANICS,
        OBJ_COMMERCIAL_OBLIGATION,
        OBJ_CATEGORY_SCOPE_ITEM,
        OBJ_CANONICAL_REQUIREMENT,
        OBJ_SCOPED_MILESTONE,
        OBJ_DOCUMENT_ROLE,
    )

    # 1. Explicit canonical_id from metadata
    meta_cid = change.metadata.get("canonical_id")
    if meta_cid:
        matched = [obj for obj in candidate_objects if obj.get("canonical_id") == meta_cid]
        if len(matched) == 1:
            return matched[0], None
        elif len(matched) > 1:
            cids = [str(o.get("canonical_id")) for o in matched]
            return None, f"AMBIGUOUS_CANONICAL_BINDING: multiple objects for explicit canonical_id '{meta_cid}': {sorted(cids)}"
        else:
            return None, f"EXPLICIT_CANONICAL_ID_NOT_FOUND: {meta_cid}"

    # 2. Explicit canonical_ids list in metadata
    meta_cids = change.metadata.get("canonical_ids")
    if isinstance(meta_cids, (list, tuple, set)):
        meta_cids_set = {str(c).strip() for c in meta_cids if str(c).strip()}
        matched = [obj for obj in candidate_objects if str(obj.get("canonical_id")).strip() in meta_cids_set]
        if len(matched) == 1:
            return matched[0], None
        elif len(matched) > 1:
            cids = [str(o.get("canonical_id")) for o in matched]
            return None, f"AMBIGUOUS_CANONICAL_BINDING: multiple objects for canonical_ids {sorted(meta_cids_set)}: {sorted(cids)}"
        elif meta_cids_set:
            return None, f"EXPLICIT_CANONICAL_IDS_NOT_FOUND: {sorted(meta_cids_set)}"

    # 3. Exact normalized canonical identity (change.entity_id matches obj["canonical_id"])
    change_eid = str(change.entity_id or "").strip()
    norm_eid = _normalize_key(change_eid)
    exact_cid_matches = [
        obj for obj in candidate_objects
        if obj.get("canonical_id") and (
            str(obj.get("canonical_id")).strip() == change_eid
            or _normalize_key(obj.get("canonical_id")) == norm_eid
        )
    ]
    if len(exact_cid_matches) == 1:
        return exact_cid_matches[0], None
    elif len(exact_cid_matches) > 1:
        cids = [str(o.get("canonical_id")) for o in exact_cid_matches]
        return None, f"AMBIGUOUS_CANONICAL_BINDING: multiple objects match canonical identity '{change_eid}': {sorted(cids)}"

    # 4. Deterministic exact / unambiguous semantic key match
    # 4a. Submission mechanics matching
    sub_fact_types = {
        "deadline", "submission_deadline", "closing_date", "closing_time",
        "rfp_closing", "bid_closing", "proposal_deadline", "closing_deadline",
        "question_deadline", "addendum_deadline", "submission_mechanics",
        "submission_portal", "submission_method", "submission_format",
        "page_limit", "font_size", "number_of_copies", "submission_instructions",
    }
    if _normalize_key(change.fact_type) in sub_fact_types or any(norm_eid.startswith(p) for p in ("sub:", "sub.", "deadline", "submission")):
        sub_objs = [
            obj for obj in candidate_objects
            if obj.get("canonical_id") == "SUBMISSION" or obj.get("object_type") == OBJ_SUBMISSION_MECHANICS
        ]
        if len(sub_objs) == 1:
            return sub_objs[0], None
        elif len(sub_objs) > 1:
            cids = [str(o.get("canonical_id")) for o in sub_objs]
            return None, f"AMBIGUOUS_CANONICAL_BINDING: multiple submission mechanics objects: {sorted(cids)}"

    def _match_in_pool(
        pool: list[dict[str, Any]],
        candidate_key_fn,
        entity_key: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not pool:
            return None, None

        clean_key = _clean_semantic_key(entity_key)
        slug_clean = _slug(clean_key)
        slug_raw = _slug(entity_key)

        # 1. Exact semantic key matches
        exact_matches = []
        for obj in pool:
            keys = candidate_key_fn(obj)
            slugs = [_slug(k) for k in keys if k]
            if any(s == slug_clean or s == slug_raw for s in slugs if s and s != "x"):
                exact_matches.append(obj)

        if len(exact_matches) == 1:
            return exact_matches[0], None
        elif len(exact_matches) > 1:
            cids = [str(o.get("canonical_id")) for o in exact_matches]
            return None, f"AMBIGUOUS_CANONICAL_BINDING: candidate canonical IDs: {sorted(cids)}"

        # 2. Before-value match if provided on change
        if change.before_value is not None:
            slug_bv = _slug(change.before_value)
            if slug_bv and slug_bv != "x" and len(slug_bv) >= 3:
                bv_matches = []
                for obj in pool:
                    keys = candidate_key_fn(obj)
                    slugs = [_slug(k) for k in keys if k]
                    if any(slug_bv == s or slug_bv in s or s in slug_bv for s in slugs if s and s != "x"):
                        bv_matches.append(obj)
                if len(bv_matches) == 1:
                    return bv_matches[0], None
                elif len(bv_matches) > 1:
                    cids = [str(o.get("canonical_id")) for o in bv_matches]
                    return None, f"AMBIGUOUS_CANONICAL_BINDING: candidate canonical IDs: {sorted(cids)}"

        # 3. Plausible / strong substring or token matches
        plausible_matches = []
        clean_tokens = [t for t in slug_clean.split("-") if len(t) > 2]
        raw_tokens = [t for t in slug_raw.split("-") if len(t) > 2]
        tokens_to_check = set(clean_tokens + raw_tokens)

        for obj in pool:
            keys = candidate_key_fn(obj)
            slugs = [_slug(k) for k in keys if k]
            matched = False
            for s in slugs:
                if not s or s == "x":
                    continue
                if (slug_clean and len(slug_clean) >= 3 and (slug_clean in s or s in slug_clean)) or \
                   (slug_raw and len(slug_raw) >= 3 and (slug_raw in s or s in slug_raw)):
                    matched = True
                    break
                if any(t in s for t in tokens_to_check if len(t) >= 4):
                    matched = True
                    break
            if matched:
                plausible_matches.append(obj)

        if len(plausible_matches) == 1:
            return plausible_matches[0], None
        elif len(plausible_matches) > 1:
            cids = [str(o.get("canonical_id")) for o in plausible_matches]
            return None, f"AMBIGUOUS_CANONICAL_BINDING: candidate canonical IDs: {sorted(cids)}"

        return None, None

    crit_pool = [o for o in candidate_objects if o.get("object_type") == OBJ_SCOPED_EVALUATION_CRITERION or str(o.get("canonical_id", "")).startswith("CRIT-")]
    comm_pool = [o for o in candidate_objects if o.get("object_type") == OBJ_COMMERCIAL_OBLIGATION or str(o.get("canonical_id", "")).startswith("OBL-")]
    scope_pool = [o for o in candidate_objects if o.get("object_type") == OBJ_CATEGORY_SCOPE_ITEM or str(o.get("canonical_id", "")).startswith("SCOPE-")]
    req_pool = [o for o in candidate_objects if o.get("object_type") == OBJ_CANONICAL_REQUIREMENT or str(o.get("canonical_id", "")).startswith("REQ-")]
    ms_pool = [o for o in candidate_objects if o.get("object_type") == OBJ_SCOPED_MILESTONE or str(o.get("canonical_id", "")).startswith("MS-")]
    doc_pool = [o for o in candidate_objects if o.get("object_type") == OBJ_DOCUMENT_ROLE or str(o.get("canonical_id", "")).startswith("DOC-")]

    ordered_pools = []
    norm_ft = _normalize_key(change.fact_type)
    if "crit" in norm_eid or "eval" in norm_eid or "weight" in norm_ft or "criterion" in norm_ft:
        ordered_pools.append((crit_pool, lambda o: [o.get("criterion"), o.get("criterion_name"), o.get("title"), o.get("label"), o.get("scoped_key")]))
    elif "obl" in norm_eid or "comm" in norm_eid or "insurance" in norm_eid or "commercial" in norm_ft or "liability" in norm_ft:
        ordered_pools.append((comm_pool, lambda o: [o.get("topic"), o.get("heading"), o.get("clause_text")[:60] if o.get("clause_text") else ""]))
    elif "scope" in norm_eid or "deliv" in norm_eid or "scope" in norm_ft:
        ordered_pools.append((scope_pool, lambda o: [o.get("heading"), o.get("scope_item"), o.get("text"), o.get("label")]))
    elif "req" in norm_eid or "compliance" in norm_ft or "requirement" in norm_ft:
        ordered_pools.append((req_pool, lambda o: [o.get("req_id"), o.get("requirement_id"), o.get("description")[:80] if o.get("description") else ""]))
    elif "ms" in norm_eid or "milestone" in norm_eid or "milestone" in norm_ft or "schedule" in norm_ft:
        ordered_pools.append((ms_pool, lambda o: [o.get("label")]))
    elif "doc" in norm_eid or "role" in norm_eid or "form" in norm_ft:
        ordered_pools.append((doc_pool, lambda o: [o.get("document"), o.get("name")]))

    all_pools = [
        (crit_pool, lambda o: [o.get("criterion"), o.get("criterion_name"), o.get("title"), o.get("label"), o.get("scoped_key")]),
        (comm_pool, lambda o: [o.get("topic"), o.get("heading"), o.get("clause_text")[:60] if o.get("clause_text") else ""]),
        (scope_pool, lambda o: [o.get("heading"), o.get("scope_item"), o.get("text"), o.get("label")]),
        (req_pool, lambda o: [o.get("req_id"), o.get("requirement_id"), o.get("description")[:80] if o.get("description") else ""]),
        (ms_pool, lambda o: [o.get("label")]),
        (doc_pool, lambda o: [o.get("document"), o.get("name")]),
    ]
    seen_pool_ids = {id(p[0]) for p in ordered_pools}
    for p, fn in all_pools:
        if id(p) not in seen_pool_ids:
            ordered_pools.append((p, fn))

    ambiguity_reasons = []
    for pool, key_fn in ordered_pools:
        matched, err = _match_in_pool(pool, key_fn, change_eid)
        if matched is not None:
            return matched, None
        if err and "AMBIGUOUS" in err:
            ambiguity_reasons.append(err)

    if ambiguity_reasons:
        return None, ambiguity_reasons[0]

    return None, f"Target canonical object for '{change.entity_id}' (change_type='{change.change_type}') could not be resolved"


def _apply_change_overlay(
    obj: dict[str, Any],
    change: FactChange,
    revision: ProcurementRevision,
) -> None:
    """Mutates deep-copied candidate object with values and provenance from an applied FactChange."""
    from full_analysis import (
        OBJ_SCOPED_EVALUATION_CRITERION,
        OBJ_SUBMISSION_MECHANICS,
        OBJ_COMMERCIAL_OBLIGATION,
        OBJ_CATEGORY_SCOPE_ITEM,
        OBJ_CANONICAL_REQUIREMENT,
        OBJ_SCOPED_MILESTONE,
        OBJ_DOCUMENT_ROLE,
    )

    obj["last_modified_revision"] = revision.revision_number
    obj["source_document_id"] = change.source_document_id
    obj["source_hash"] = change.source_hash
    obj["source_document"] = change.source_document

    val = change.after_value
    obj_type = obj.get("object_type")

    if change.before_value is not None:
        obj["prior_value"] = change.before_value

    if obj_type == OBJ_SCOPED_EVALUATION_CRITERION:
        if change.fact_type in ("weight", "WEIGHT", "evaluation_weight", "scoring_weight", "criterion_weight"):
            obj["weight"] = val
            if "points" in obj:
                obj["points"] = val
            if change.before_value is not None:
                obj["prior_weight"] = change.before_value
        elif isinstance(val, dict):
            obj.update(val)
        else:
            obj["criterion_value"] = val

    elif obj_type == OBJ_SUBMISSION_MECHANICS:
        norm_ft = _normalize_key(change.fact_type)
        norm_eid = _normalize_key(change.entity_id)
        if "clarification" in norm_eid or "clarification" in norm_ft:
            obj["clarification_deadline"] = val
        elif "deadline" in norm_eid or "deadline" in norm_ft:
            obj["submission_deadline"] = val
        elif "portal" in norm_eid or "method" in norm_eid or "submission_method" in norm_ft:
            obj["submission_method"] = val
        elif "page_limit" in norm_eid or "page_limit" in norm_ft:
            if isinstance(obj.get("page_limits"), dict) and isinstance(val, dict):
                obj["page_limits"].update(val)
            else:
                obj["page_limits"] = val
        elif isinstance(val, dict):
            obj.update(val)
        else:
            obj["value"] = val

    elif obj_type == OBJ_COMMERCIAL_OBLIGATION:
        if isinstance(val, dict):
            obj.update(val)
        else:
            obj["clause_text"] = str(val)
            obj["current_value"] = val
            obj["value"] = val
            obj["summary"] = str(val)

    elif obj_type == OBJ_CATEGORY_SCOPE_ITEM:
        if isinstance(val, dict):
            obj.update(val)
        else:
            obj["text"] = str(val)
            obj["scope_item"] = str(val)
            obj["description"] = str(val)

    elif obj_type == OBJ_CANONICAL_REQUIREMENT:
        if isinstance(val, dict):
            obj.update(val)
        else:
            obj["description"] = str(val)
            obj["requirement_text"] = str(val)

    elif obj_type == OBJ_SCOPED_MILESTONE:
        if isinstance(val, dict):
            obj.update(val)
        else:
            obj["normalized_date_end"] = str(val)
            obj["target_date"] = str(val)

    elif obj_type == OBJ_DOCUMENT_ROLE:
        if isinstance(val, dict):
            obj.update(val)
        else:
            obj["document"] = str(val)

    else:
        if isinstance(val, dict):
            obj.update(val)
        else:
            obj["value"] = val


_CANONICAL_SPECIALIST_DOMAINS: dict[str, str] = {
    "procurement_structure": "procurement_structure",
    "structure": "procurement_structure",
    "requirements_compliance": "requirements_compliance",
    "requirements": "requirements_compliance",
    "compliance": "requirements_compliance",
    "evaluation_intelligence": "evaluation_intelligence",
    "evaluation": "evaluation_intelligence",
    "eval": "evaluation_intelligence",
    "scope_deliverables": "scope_deliverables",
    "scope": "scope_deliverables",
    "deliverables": "scope_deliverables",
    "commercial_contractual": "commercial_contractual",
    "commercial": "commercial_contractual",
    "contractual": "commercial_contractual",
    "schedule_submission": "schedule_submission",
    "schedule": "schedule_submission",
    "submission": "schedule_submission",
}


def _canonical_domain(name: Any) -> str:
    cleaned = re.sub(r'[\s\.\:\-_/]+', '_', str(name or "").strip().lower())
    if cleaned.startswith("specialist_"):
        cleaned = cleaned[len("specialist_"):]
    return _CANONICAL_SPECIALIST_DOMAINS.get(cleaned, cleaned)


def _finding_belongs_to_specialist(finding: dict[str, Any], specialist_id: str) -> bool:
    target_domain = _canonical_domain(specialist_id)

    # 1. Check produced_by (list, tuple, set, or string)
    prod = finding.get("produced_by")
    if prod:
        if isinstance(prod, (list, tuple, set)):
            if any(_canonical_domain(p) == target_domain for p in prod):
                return True
            return False
        elif isinstance(prod, str):
            return _canonical_domain(prod) == target_domain

    # 2. Check specialist_id
    sid = finding.get("specialist_id")
    if sid:
        return _canonical_domain(sid) == target_domain

    # 3. Check domain
    dom = finding.get("domain")
    if dom:
        return _canonical_domain(dom) == target_domain

    # 4. Check finding_id prefix (e.g. "EVALUATION_INTELLIGENCE:0" or "evaluation_intelligence:0")
    fid = str(finding.get("finding_id") or "")
    if ":" in fid:
        prefix = fid.split(":", 1)[0]
        prefix_domain = _canonical_domain(prefix)
        if prefix_domain in _CANONICAL_SPECIALIST_DOMAINS.values():
            return prefix_domain == target_domain

    return False


def build_revision_specialist_context(
    specialist_id: str,
    revision: ProcurementRevision,
    procurement_state: ProcurementState | dict[str, Any] | None,
    canonical_package: Any,
    impact_plan: RevisionImpactPlan,
    prior_specialist_findings: Sequence[Any] | None = None,
    bid_id: int | None = None,
    *,
    current_canonical_view: CurrentCanonicalView | None = None,
) -> RevisionSpecialistContext:
    """Builds authoritative, revision-aware specialist execution context for ONE affected domain.

    Fails closed with PCIContextNotEligibleError if:
    - Revision is not APPLIED
    - Revision has unresolved chronology conflicts
    - Specialist domain is not among impact_plan.affected_domains

    Overlay rules (PCI-B2B.1):
    - Base CanonicalPackage remains strictly immutable.
    - Updated values in relevant_current_canonical_objects reflect cumulative active truth through current revision.
    - Removed facts are completely excluded from relevant_current_canonical_objects.
    - relevant_changes reflects TARGET REVISION DELTA only.
    - Additive facts are represented as grounded RevisionFact instances.
    - permitted_canonical_ids contains only active canonical IDs + active revision fact IDs.
    - Unresolved bindings mark is_executable = False and set blocking_reason.
    """
    # 1. Authoritative Eligibility Checks (fail-closed)
    if revision.review_status != "applied" or not revision.is_applied:
        raise PCIContextNotEligibleError(
            f"Revision {revision.revision_number} is not applied (status='{revision.review_status}'). "
            "Specialist context can only be built from APPLIED revisions."
        )

    if revision.chronology_unresolved:
        raise PCIContextNotEligibleError(
            f"Revision {revision.revision_number} has unresolved chronology conflicts. "
            "Specialist context cannot be built until chronology is resolved."
        )

    if specialist_id not in impact_plan.affected_domains:
        raise PCIContextNotEligibleError(
            f"Specialist '{specialist_id}' is not in affected domains ({impact_plan.affected_domains}) "
            f"for revision {revision.revision_number}."
        )

    # 2. Extract deep-copied canonical objects for this specialist slice
    source_package = current_canonical_view if current_canonical_view is not None else canonical_package
    extracted_objects = _extract_package_objects(source_package, specialist_id)

    # 3. Route and filter changes relevant to this specialist (TARGET REVISION DELTA)
    relevant_changes_list: list[dict[str, Any]] = []
    for change in revision.change_set.changes:
        if change.review_status != REVIEW_STATUS_APPROVED or change.change_type == CHANGE_CONFLICTS_WITH:
            continue
        if change.change_type == CHANGE_UNCHANGED:
            continue
        routing = route_change_to_domains(change)
        if specialist_id in routing.affected_domains:
            c_dict = change.to_dict()
            c_dict["revision_id"] = revision.revision_id
            c_dict["revision_number"] = revision.revision_number
            c_dict["effective_date"] = getattr(revision, "effective_date", None) or getattr(revision, "buyer_issued_date", None)
            relevant_changes_list.append(c_dict)

    # 4. Bind changes and apply overlays
    change_bindings: list[ChangeBinding] = []
    revision_facts: list[RevisionFact] = []
    removed_canonical_ids: set[str] = set()
    is_executable = True
    blocking_reasons: list[str] = []

    active_facts_map = {
        rf.fact_id: rf for rf in getattr(current_canonical_view, "active_revision_facts", ())
    } if current_canonical_view else {}

    for c_dict in relevant_changes_list:
        change = FactChange.from_dict(c_dict)
        matched_obj, unresolve_reason = _match_canonical_object(change, extracted_objects)

        matched_rf = None
        if matched_obj is None and active_facts_map:
            meta_cid = change.metadata.get("canonical_id")
            if meta_cid and meta_cid in active_facts_map:
                matched_rf = active_facts_map[meta_cid]
            elif change.entity_id in active_facts_map:
                matched_rf = active_facts_map[change.entity_id]
            else:
                rf_matches = [rf for rf in active_facts_map.values() if rf.entity_id == change.entity_id]
                if len(rf_matches) == 1:
                    matched_rf = rf_matches[0]

        if matched_obj is not None:
            cid = matched_obj.get("canonical_id")
            otype = matched_obj.get("object_type")
            if change.change_type == CHANGE_REMOVES:
                if cid:
                    removed_canonical_ids.add(cid)
                change_bindings.append(ChangeBinding(
                    change_id=change.entity_id or change.fact_type,
                    entity_id=change.entity_id,
                    fact_type=change.fact_type,
                    binding_type=BINDING_EXISTING_CANONICAL,
                    canonical_id=cid,
                    object_type=otype,
                    binding_rationale=f"Bound to existing canonical object {cid} for removal",
                ))
            else:
                if current_canonical_view is None:
                    _apply_change_overlay(matched_obj, change, revision)
                change_bindings.append(ChangeBinding(
                    change_id=change.entity_id or change.fact_type,
                    entity_id=change.entity_id,
                    fact_type=change.fact_type,
                    binding_type=BINDING_EXISTING_CANONICAL,
                    canonical_id=cid,
                    object_type=otype,
                    binding_rationale=f"Bound to existing canonical object {cid} and applied overlay",
                ))
        elif matched_rf is not None:
            fid = matched_rf.fact_id
            if change.change_type == CHANGE_REMOVES:
                removed_canonical_ids.add(fid)
                change_bindings.append(ChangeBinding(
                    change_id=change.entity_id or change.fact_type,
                    entity_id=change.entity_id,
                    fact_type=change.fact_type,
                    binding_type=BINDING_REVISION_FACT,
                    canonical_id=fid,
                    object_type="REVISION_FACT",
                    binding_rationale=f"Bound to active revision fact {fid} for removal",
                ))
            else:
                change_bindings.append(ChangeBinding(
                    change_id=change.entity_id or change.fact_type,
                    entity_id=change.entity_id,
                    fact_type=change.fact_type,
                    binding_type=BINDING_REVISION_FACT,
                    canonical_id=fid,
                    object_type="REVISION_FACT",
                    binding_rationale=f"Bound to active revision fact {fid} and applied update",
                ))
        else:
            if change.change_type == CHANGE_ADDS:
                if change.source_document_id is not None and change.source_hash:
                    fact_id = f"REV-FACT-{_slug(change.entity_id)}"
                    eff_date = getattr(revision, "effective_date", None) or getattr(revision, "buyer_issued_date", None)
                    rf = RevisionFact(
                        fact_id=fact_id,
                        fact_type=change.fact_type,
                        entity_id=change.entity_id,
                        value=change.after_value,
                        change_type=change.change_type,
                        source_document_id=change.source_document_id,
                        source_document=change.source_document,
                        source_hash=change.source_hash,
                        revision_id=revision.revision_id,
                        revision_number=revision.revision_number,
                        effective_date=eff_date,
                        authority_status=change.authority_status,
                        review_status=change.review_status,
                        description=change.metadata.get("description") or (str(change.after_value) if not isinstance(change.after_value, dict) else change.after_value.get("description")),
                        metadata=dict(change.metadata),
                    )
                    revision_facts.append(rf)
                    change_bindings.append(ChangeBinding(
                        change_id=change.entity_id or change.fact_type,
                        entity_id=change.entity_id,
                        fact_type=change.fact_type,
                        binding_type=BINDING_REVISION_FACT,
                        canonical_id=fact_id,
                        object_type="REVISION_FACT",
                        binding_rationale=f"Additive fact formulated as revision fact {fact_id}",
                    ))
                else:
                    is_executable = False
                    reason = f"Additive change '{change.entity_id}' missing valid source provenance"
                    blocking_reasons.append(reason)
                    change_bindings.append(ChangeBinding(
                        change_id=change.entity_id or change.fact_type,
                        entity_id=change.entity_id,
                        fact_type=change.fact_type,
                        binding_type=BINDING_UNRESOLVED,
                        canonical_id=None,
                        object_type=None,
                        binding_rationale=reason,
                    ))
            elif change.change_type == CHANGE_REMOVES:
                rem_id = change.metadata.get("canonical_id") or change.entity_id
                removed_canonical_ids.add(rem_id)
                change_bindings.append(ChangeBinding(
                    change_id=change.entity_id or change.fact_type,
                    entity_id=change.entity_id,
                    fact_type=change.fact_type,
                    binding_type=BINDING_EXISTING_CANONICAL if change.metadata.get("canonical_id") else BINDING_UNRESOLVED,
                    canonical_id=rem_id,
                    object_type=None,
                    binding_rationale=f"Removed canonical id {rem_id}",
                ))
            else:
                is_executable = False
                reason = unresolve_reason or f"Target canonical object for '{change.entity_id}' (change_type='{change.change_type}') could not be resolved"
                blocking_reasons.append(reason)
                change_bindings.append(ChangeBinding(
                    change_id=change.entity_id or change.fact_type,
                    entity_id=change.entity_id,
                    fact_type=change.fact_type,
                    binding_type=BINDING_UNRESOLVED,
                    canonical_id=None,
                    object_type=None,
                    binding_rationale=reason,
                ))

    # Incorporate cumulative active revision facts if current_canonical_view is provided
    if current_canonical_view is not None:
        target_domain = _canonical_domain(specialist_id)
        active_cum_facts = []
        for rf in current_canonical_view.active_revision_facts:
            if rf.fact_id in removed_canonical_ids:
                continue
            ft = _normalize_key(rf.fact_type)
            if target_domain == "requirements_compliance" and ("req" in ft or "compliance" in ft or "mandatory" in ft or "requirement" in ft):
                active_cum_facts.append(rf)
            else:
                dummy_change = FactChange(
                    change_type=rf.change_type,
                    fact_type=rf.fact_type,
                    entity_id=rf.entity_id,
                    before_value=None,
                    after_value=rf.value,
                    source_document=rf.source_document,
                    source_hash=rf.source_hash,
                    source_document_id=rf.source_document_id,
                    review_status=REVIEW_STATUS_APPROVED,
                )
                routing = route_change_to_domains(dummy_change)
                if specialist_id in routing.affected_domains:
                    active_cum_facts.append(rf)
        for rf in revision_facts:
            if not any(x.fact_id == rf.fact_id for x in active_cum_facts):
                active_cum_facts.append(rf)
        revision_facts = active_cum_facts

    # 5. Filter removed canonical objects
    current_canonical_objects = [
        obj for obj in extracted_objects
        if obj.get("canonical_id") not in removed_canonical_ids
    ]

    # 6. Assemble permitted canonical IDs
    active_canonical_ids = {
        obj["canonical_id"] for obj in current_canonical_objects
        if obj.get("canonical_id")
    }
    rev_fact_ids = {rf.fact_id for rf in revision_facts}
    permitted_canonical_ids = tuple(sorted(active_canonical_ids | rev_fact_ids))

    # 7. Filter prior findings for this specialist domain
    stale_ids_for_specialist: list[str] = []
    stale_findings_list: list[dict[str, Any]] = []
    retained_findings_list: list[dict[str, Any]] = []

    if prior_specialist_findings:
        for raw_f in prior_specialist_findings:
            f = raw_f.as_dict() if hasattr(raw_f, "as_dict") else (raw_f.to_dict() if hasattr(raw_f, "to_dict") else raw_f)
            if not isinstance(f, dict):
                continue
            fid = str(f.get("finding_id") or "")
            if not fid:
                continue

            # Must belong strictly to this specialist domain
            if not _finding_belongs_to_specialist(f, specialist_id):
                continue

            if fid in impact_plan.stale_finding_ids or fid in impact_plan.unresolved_finding_ids:
                stale_ids_for_specialist.append(fid)
                stale_findings_list.append(dict(f))
            elif fid in impact_plan.retained_finding_ids or impact_plan.finding_impacts.get(fid, {}).get("status") == FINDING_STATUS_RETAINED:
                retained_findings_list.append(dict(f))
            else:
                retained_findings_list.append(dict(f))
    else:
        # If no prior finding objects were supplied, filter stale IDs by domain prefix if available
        target_domain = _canonical_domain(specialist_id)
        for fid in impact_plan.stale_finding_ids:
            if ":" in fid:
                prefix_domain = _canonical_domain(fid.split(":", 1)[0])
                if prefix_domain in _CANONICAL_SPECIALIST_DOMAINS.values():
                    if prefix_domain == target_domain:
                        stale_ids_for_specialist.append(fid)
                    continue
            stale_ids_for_specialist.append(fid)

    # 8. Compute stable context fingerprint
    canonical_package_digest = getattr(canonical_package, "package_digest", "") or _digest(canonical_package)
    impact_plan_fingerprint = getattr(impact_plan, "fingerprint", "") or impact_plan.fingerprint
    context_fingerprint = compute_specialist_context_fingerprint(
        specialist_id=specialist_id,
        revision_number=revision.revision_number,
        revision_id=revision.revision_id,
        impact_plan_fingerprint=impact_plan_fingerprint,
        base_package_digest=canonical_package_digest,
        permitted_canonical_ids=permitted_canonical_ids,
        stale_prior_finding_ids=stale_ids_for_specialist,
        relevant_canonical_objects=current_canonical_objects,
        revision_facts=revision_facts,
        relevant_changes=relevant_changes_list,
        stale_prior_findings=stale_findings_list,
        retained_prior_findings=retained_findings_list,
    )

    return RevisionSpecialistContext(
        specialist_id=specialist_id,
        revision_number=revision.revision_number,
        revision_id=revision.revision_id,
        bid_id=bid_id or getattr(canonical_package, "bid_id", None),
        context_fingerprint=context_fingerprint,
        impacted_domain=specialist_id,
        impact_plan_fingerprint=impact_plan_fingerprint,
        base_package_digest=canonical_package_digest,
        relevant_changes=tuple(relevant_changes_list),
        relevant_current_canonical_objects=tuple(current_canonical_objects),
        revision_facts=tuple(revision_facts),
        permitted_canonical_ids=permitted_canonical_ids,
        stale_prior_finding_ids=tuple(sorted(set(stale_ids_for_specialist))),
        stale_prior_findings=tuple(stale_findings_list),
        retained_prior_findings=tuple(retained_findings_list),
        change_bindings=tuple(change_bindings),
        is_executable=is_executable,
        blocking_reason="; ".join(blocking_reasons) if blocking_reasons else None,
    )
