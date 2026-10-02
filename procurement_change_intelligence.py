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
    is_current: bool = False
    chronology_unresolved: bool = False
    no_canonical_change: bool = False

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
        # All-or-nothing check: if this revision is unapplied (pending review or chronology unresolved),
        # none of its changes can mutate canonical truth.
        rev_has_pending = rev.chronology_unresolved or any(
            c.change_type == CHANGE_CONFLICTS_WITH
            or c.review_status in (REVIEW_STATUS_HUMAN_REVIEW_REQUIRED, REVIEW_STATUS_PENDING)
            for c in rev.change_set.changes
        )

        if rev_has_pending:
            for change in rev.change_set.changes:
                if (
                    change.change_type == CHANGE_CONFLICTS_WITH
                    or change.review_status in (REVIEW_STATUS_HUMAN_REVIEW_REQUIRED, REVIEW_STATUS_PENDING)
                    or rev.chronology_unresolved
                ):
                    meta = copy.deepcopy(change.metadata) if change.metadata else {}
                    if rev.chronology_unresolved:
                        meta["chronology_unresolved"] = True
                    conflict_change = replace(
                        change,
                        review_status=REVIEW_STATUS_HUMAN_REVIEW_REQUIRED,
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
        return self._revisions.get(revision_number)

    def get_all_revisions(self) -> list[ProcurementRevision]:
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
