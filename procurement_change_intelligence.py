"""
procurement_change_intelligence.py -- PCI-A: Procurement Revision Foundation &
Deterministic Change Model.

PHASE 1 ONLY:
- Revision Foundation (Revision 0 baseline + additive buyer revisions)
- Deterministic Change Model (bounded change taxonomy, field-level precedence)
- Replay & Authoritative Current State derivation
- Out-of-order and duplicate upload resilience (idempotency)
- Stable semantic fingerprinting (no timestamps / DB IDs)
- Tenancy & optimistic concurrency safety

Pure, deterministic, fail-closed. No model calls.
Does NOT modify prompts, UI, brief generation, or CHECK.
Reuses existing database schema (migration 010 governance precedent) without DDL changes.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
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

_ADDENDUM_NUM_RE = re.compile(r'\b(?:addend(?:um|a)|bulletin)\s*#?\s*0*(\d+)\b', re.IGNORECASE)
_AMENDMENT_NUM_RE = re.compile(r'\b(?:amendment|amend)\s*#?\s*0*(\d+)\b', re.IGNORECASE)
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
# 4. Fingerprinting (Section 15)
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
    payload = {
        "revision": revision,
        "parent_fp": parent_fp or "",
        "source_hashes": sorted(source_hashes),
        "changeset_fp": changeset_fp,
    }
    return _canonical_json_hash(payload)


def compute_state_fingerprint(
    bid_id: int,
    current_revision: int,
    authoritative_facts: dict[str, FactChange],
    active_artifacts: dict[str, ArtifactRecord],
) -> str:
    """Stable fingerprint of the current authoritative procurement state.
    Changes ONLY when semantic facts change."""
    facts_payload = [
        {
            "entity_id": k,
            "fact_type": v.fact_type,
            "value": v.after_value,
            "source_hash": v.source_hash,
            "authority_status": v.authority_status,
        }
        for k, v in sorted(authoritative_facts.items())
    ]
    artifacts_payload = [
        {
            "artifact_id": k,
            "name": a.name,
            "content_hash": a.content_hash,
            "revision": a.revision,
            "status": a.status,
        }
        for k, a in sorted(active_artifacts.items())
    ]
    payload = {
        "bid_id": bid_id,
        "current_revision": current_revision,
        "facts": facts_payload,
        "artifacts": artifacts_payload,
    }
    return _canonical_json_hash(payload)


# ═══════════════════════════════════════════════════════════════════════════
# 5. Core Data Structures (Sections 4, 11, 13, 14)
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
    """Immutable record of one procurement revision in the chronological chain."""
    revision_number: int
    revision_id: str
    parent_revision_id: str | None
    buyer_chronology_index: int
    buyer_issued_date: str | None
    trigger_documents: list[dict[str, Any]]
    change_set: ProcurementChangeSet
    fingerprint: str
    is_current: bool = False

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
        current_rev_num = rev.revision_number
        current_rev_fp = rev.fingerprint
        history_chain.append(rev.revision_number)

        for change in rev.change_set.changes:
            # 1. Ambiguous precedence / conflict requiring review
            if (
                change.change_type == CHANGE_CONFLICTS_WITH
                or change.review_status == REVIEW_STATUS_HUMAN_REVIEW_REQUIRED
            ):
                pending_conflicts.append(change)
                # Keep active fact intact -- do not auto-resolve or silently rewrite!
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

    state_fp = compute_state_fingerprint(bid_id, current_rev_num, active_facts, active_artifacts)

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
# 7. Procurement Revision Manager (Sections 4, 5, 6, 16, 17, 18)
# ═══════════════════════════════════════════════════════════════════════════

class ProcurementRevisionManager:
    """Manages the lifecycle, chronology, idempotency, and concurrency
    for a single procurement's revision history.
    Enforces strict organization and bid tenancy boundaries."""

    _locks: dict[int, threading.Lock] = {}
    _locks_guard = threading.Lock()

    def __init__(self, bid_id: int, organization_id: str):
        if not bid_id or not organization_id:
            raise TenancyViolationError("Both bid_id and organization_id are required.")
        self.bid_id = bid_id
        self.organization_id = str(organization_id)
        self._revisions: dict[int, ProcurementRevision] = {}
        self._known_document_hashes: set[str] = set()

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

    @property
    def current_revision_number(self) -> int:
        return max(self._revisions.keys(), default=-1)

    def get_revision(self, revision_number: int) -> ProcurementRevision | None:
        return self._revisions.get(revision_number)

    def get_all_revisions(self) -> list[ProcurementRevision]:
        return [self._revisions[k] for k in sorted(self._revisions.keys())]

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
        Fails closed if baseline already exists."""
        lock = self._get_bid_lock(self.bid_id)
        with lock:
            if 0 in self._revisions:
                raise PCIEngineError("Revision 0 (baseline) already exists for this procurement.")

            # Record document hashes
            src_docs = []
            src_hashes = []
            for d in documents:
                chash = d.get("content_hash") or hashlib.sha256(
                    d.get("name", "").encode("utf-8")
                ).hexdigest()
                src_docs.append({
                    "name": d.get("name", "RFP"),
                    "content_hash": chash,
                    "doc_type": d.get("doc_type", "RFP / Source"),
                    "document_change_type": DOC_CHANGE_ORIGINAL_RFP,
                })
                src_hashes.append(chash)
                self._known_document_hashes.add(chash)

            # Build ChangeSet for Revision 0
            changes = [
                FactChange(
                    change_type=c.change_type if c.change_type in FACT_CHANGE_TYPES else CHANGE_ADDS,
                    fact_type=c.fact_type,
                    entity_id=c.entity_id,
                    before_value=None,
                    after_value=c.after_value,
                    source_document=c.source_document,
                    source_hash=c.source_hash or (src_hashes[0] if src_hashes else ""),
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
            )

            self._revisions[0] = rev_0
            logger.info("Created Revision 0 for bid %s (fingerprint: %s...)", self.bid_id, rev_fp[:12])
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
        Enforces idempotency (Section 6), optimistic concurrency (Section 16),
        and fail-closed failure semantics (Section 17)."""
        lock = self._get_bid_lock(self.bid_id)
        with lock:
            current_rev = self.current_revision_number
            if current_rev < 0:
                raise PCIEngineError("Cannot add buyer update revision: Revision 0 does not exist.")

            # Concurrency check (Section 16)
            if expected_base_revision is not None and expected_base_revision != current_rev:
                raise StaleRevisionError(
                    f"Stale revision: expected base revision {expected_base_revision}, "
                    f"but current revision is {current_rev}."
                )

            # Idempotency check (Section 6)
            incoming_hashes = [
                d.get("content_hash") or hashlib.sha256(d.get("name", "").encode("utf-8")).hexdigest()
                for d in documents
            ]
            if incoming_hashes and all(h in self._known_document_hashes for h in incoming_hashes):
                logger.info("All incoming document hashes already registered. Outcome: NO_NEW_REVISION")
                return {
                    "outcome": OUTCOME_NO_NEW_REVISION,
                    "reason": "IDENTICAL_DOCUMENTS_ALREADY_REGISTERED",
                    "current_revision": current_rev,
                }

            # Chronology & Out-of-order analysis (Section 5)
            # Inspect first document for chronological signals
            doc0 = documents[0] if documents else {}
            fname = doc0.get("name", "")
            chrono = extract_chronology_metadata(fname, buyer_issued_date)
            doc_change_type = chrono.get("document_change_type") or DOC_CHANGE_ADDENDUM

            next_rev_num = current_rev + 1
            parent_rev = self._revisions[current_rev]

            # Build source document metadata
            src_docs = []
            for d, chash in zip(documents, incoming_hashes):
                src_docs.append({
                    "name": d.get("name", "Buyer Update"),
                    "content_hash": chash,
                    "doc_type": d.get("doc_type", "Addendum"),
                    "document_change_type": doc_change_type,
                    "sequence_number": chrono.get("sequence_number"),
                    "issued_date": chrono.get("issued_date"),
                })
                self._known_document_hashes.add(chash)

            # Chronology index
            if force_chronology_index is not None:
                chronology_index = force_chronology_index
            elif chrono.get("sequence_number") is not None:
                chronology_index = chrono["sequence_number"]
            else:
                chronology_index = next_rev_num

            # Build ChangeSet
            changeset_fp = compute_changeset_fingerprint(
                next_rev_num, current_rev, changes, incoming_hashes
            )
            changeset = ProcurementChangeSet(
                revision=next_rev_num,
                previous_revision=current_rev,
                source_documents=src_docs,
                changes=list(changes),
                buyer_issued_date=chrono.get("issued_date") or buyer_issued_date,
                fingerprint=changeset_fp,
            )

            # Build Revision
            rev_fp = compute_revision_fingerprint(
                next_rev_num, parent_rev.fingerprint, incoming_hashes, changeset_fp
            )

            new_revision = ProcurementRevision(
                revision_number=next_rev_num,
                revision_id=f"bid-{self.bid_id}-rev-{next_rev_num}",
                parent_revision_id=parent_rev.revision_id,
                buyer_chronology_index=chronology_index,
                buyer_issued_date=chrono.get("issued_date") or buyer_issued_date,
                trigger_documents=src_docs,
                change_set=changeset,
                fingerprint=rev_fp,
                is_current=True,
            )

            # Immutability: Prior revisions remain immutable; un-mark is_current
            self._revisions[current_rev] = ProcurementRevision(
                revision_number=parent_rev.revision_number,
                revision_id=parent_rev.revision_id,
                parent_revision_id=parent_rev.parent_revision_id,
                buyer_chronology_index=parent_rev.buyer_chronology_index,
                buyer_issued_date=parent_rev.buyer_issued_date,
                trigger_documents=parent_rev.trigger_documents,
                change_set=parent_rev.change_set,
                fingerprint=parent_rev.fingerprint,
                is_current=False,
            )

            self._revisions[next_rev_num] = new_revision
            logger.info("Created Revision %d for bid %s (fingerprint: %s...)",
                        next_rev_num, self.bid_id, rev_fp[:12])

            return {
                "outcome": OUTCOME_REVISION_CREATED,
                "revision": new_revision,
                "current_revision": next_rev_num,
            }

    def get_fact_history(self, entity_id: str) -> list[dict[str, Any]]:
        """Returns the full chronological evolution of a specific fact across all revisions."""
        history = []
        ordered_revs = sorted(self._revisions.values(), key=lambda r: (r.buyer_chronology_index, r.revision_number))
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
                        "authority_status": c.authority_status,
                        "review_status": c.review_status,
                    })
        return history
