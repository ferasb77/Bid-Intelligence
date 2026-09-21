"""Organizational Memory — OM-1 foundation.

Organization-scoped, retrieval-first durable memory, structurally distinct
from BOTH `content_library` (bid-scoped semantic reuse, migration 001) and
canonical procurement truth (`requirements`). This module owns:

  1. The three-memory-class data shape (`MemoryClass`, `OrganizationalMemoryItem`).
  2. A pure, deterministic retrieval contract (`retrieve`) that ranks/filters
     memory items for a query, exposing memory class, trust/approval state,
     provenance, and a relevance signal on every result -- never bare text.

This module makes ZERO live model/embedding calls. `retrieve()` accepts an
optional `embed_fn` (matching `embeddings.embed_query`'s signature -- see
`embeddings.py`) so a caller MAY wire the existing Voyage-backed embedding
interface through it; when `embed_fn` is None, returns None, or raises, this
module falls back to deterministic keyword/metadata filtering, exactly as
`embeddings.semantic_search` already degrades gracefully for the Content
Library. Every code path in this module is exercised in this phase only
against mocks/synthetic data -- see tests/test_organizational_memory.py.

── The three memory classes (never conflatable) ────────────────────────────
SOURCE_MEMORY            -- raw attributable organizational source material
                             (case study, capability statement, resume).
                             May SUPPORT a claim. NOT itself canonical firm
                             truth.
APPROVED_FIRM_KNOWLEDGE  -- human-approved reusable organizational fact,
                             derived from an identified source or synthesis
                             of one. Only this class may be treated as
                             trustworthy reusable firm knowledge, and only
                             once `approved_by`/`approved_at` are both set
                             by an explicit human action -- never inferred,
                             defaulted, or auto-promoted by this module or
                             any other code path in this phase.
PROPOSAL_MEMORY           -- reusable prior-proposal language/patterns. A
                             proposal is marketing/persuasive content, not
                             verified fact: PROPOSAL_MEMORY may suggest
                             language but can NEVER be used to PROVE a
                             fact, and this module structurally forbids it
                             from ever exposing/deriving APPROVED_FIRM_
                             KNOWLEDGE-equivalent trust (see
                             `TrustSignal.is_provable_fact`).

── Provenance ────────────────────────────────────────────────────────────
`SourceProvenance` mirrors the `ProposalSourceRef` discipline already
established in `analyst._build_proposal_source_ref` / migration 015, and
the exact-identity discipline `evidence.py`'s `EvidenceArtifact`/
`EvidenceExtract` enforce via `content_sha256`: every field is populated
only from values genuinely known (file identity, content hash, locator);
absent fields are omitted/None, never guessed or fabricated.

── Retrieval-first ──────────────────────────────────────────────────────
`retrieve()` never returns "everything" -- it requires an explicit
`organization_id`, applies memory-class/trust filters BEFORE ranking, and
always bounds output with `top_k`. There is no function in this module
that loads a firm's whole archive into a return value.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Callable, Iterable, Optional


ORGANIZATIONAL_MEMORY_CONTRACT_VERSION = "om-1.0.0"


class MemoryClass(str, Enum):
    SOURCE_MEMORY = "SOURCE_MEMORY"
    APPROVED_FIRM_KNOWLEDGE = "APPROVED_FIRM_KNOWLEDGE"
    PROPOSAL_MEMORY = "PROPOSAL_MEMORY"


_VALID_MEMORY_CLASSES = {m.value for m in MemoryClass}


class OrganizationalMemoryError(ValueError):
    """Raised for a structurally invalid memory item -- e.g. an
    APPROVED_FIRM_KNOWLEDGE item missing its human approval, or a
    PROPOSAL_MEMORY item carrying one it must never have."""


def content_hash(content: str) -> str:
    """The same exact-identity discipline evidence.py uses for
    content_sha256 -- sha256 over the normalized text. Never fabricated;
    always recomputed from the actual content, never trusted from caller
    input without verification by `OrganizationalMemoryItem.__post_init__`."""
    normalized = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    return sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceProvenance:
    """Physical/source identity for a memory item. Every field is
    populated ONLY from values the application already deterministically
    knows (file identity, content hash, locator) -- never invented. A
    field left None means the underlying source genuinely does not carry
    that coordinate, not that it was skipped."""

    file_id: Optional[str] = None
    content_hash: Optional[str] = None
    filename: Optional[str] = None
    package_path: Optional[str] = None
    locator: Optional[str] = None
    source_bid_id: Optional[int] = None
    # Commissioning-review fix #4: an internal Storage reference for the
    # ORIGINAL uploaded artifact (organizational_source_documents.
    # storage_path), never a public/signed URL -- matches this same
    # trust-boundary exposure pattern as content_hash/filename above (a
    # trusted-app-layer identifier, not an unauthenticated-caller-usable
    # credential). None when the item did not originate from a stored
    # upload at all.
    storage_path: Optional[str] = None

    def has_exact_identity(self) -> bool:
        """True iff this provenance references a real, specific source --
        at minimum a file identity or a content hash. Used to reject
        vague/fabricated provenance (never fuzzy-matched)."""
        return bool(self.file_id or self.content_hash)

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id,
            "content_hash": self.content_hash,
            "filename": self.filename,
            "package_path": self.package_path,
            "locator": self.locator,
            "source_bid_id": self.source_bid_id,
            "storage_path": self.storage_path,
        }


@dataclass(frozen=True)
class OrganizationalMemoryItem:
    """One Organizational Memory item. Organization-scoped -- never tied
    to a single bid for retrieval purposes (source_bid_id in `provenance`
    is provenance only, never a scoping key)."""

    id: str
    organization_id: str
    memory_class: MemoryClass
    title: str
    content: str
    provenance: SourceProvenance
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    derived_from_item_id: Optional[str] = None
    # Commissioning-review fix #4: durable link to the
    # organizational_source_documents parent row this item was chunked
    # from (None when the item did not originate from a chunked upload).
    # Carried through to RetrievalResult so a retrieved result can be
    # traced all the way to its physical source document.
    source_document_id: Optional[str] = None
    embedding: Optional[list[float]] = None
    metadata: dict = field(default_factory=dict)
    item_content_hash: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.organization_id:
            raise OrganizationalMemoryError("organization_id is required")
        if self.memory_class.value not in _VALID_MEMORY_CLASSES:
            raise OrganizationalMemoryError(f"unrecognized memory_class: {self.memory_class}")
        if not self.content or not self.content.strip():
            raise OrganizationalMemoryError("content must be non-empty")

        # Approval-coupling, enforced identically to migration 016's DB
        # CHECK constraint -- structural, not a docstring promise.
        is_approved_class = self.memory_class is MemoryClass.APPROVED_FIRM_KNOWLEDGE
        has_approval = self.approved_by is not None and self.approved_at is not None
        has_partial_approval = (self.approved_by is not None) != (self.approved_at is not None)
        if has_partial_approval:
            raise OrganizationalMemoryError(
                "approved_by and approved_at must be supplied together")
        if is_approved_class and not has_approval:
            raise OrganizationalMemoryError(
                "APPROVED_FIRM_KNOWLEDGE requires an explicit approved_by and approved_at "
                "-- it is never auto-promoted")
        if not is_approved_class and has_approval:
            raise OrganizationalMemoryError(
                f"{self.memory_class.value} must never carry approval fields -- "
                "only APPROVED_FIRM_KNOWLEDGE may be marked approved")

        # Lineage-coupling, enforced identically to migration 016's DB CHECK
        # constraint organizational_memory_items_approved_requires_lineage --
        # structural, not a docstring promise. It must be impossible to even
        # construct an in-memory APPROVED_FIRM_KNOWLEDGE item with no
        # identified SOURCE_MEMORY lineage.
        if is_approved_class and self.derived_from_item_id is None:
            raise OrganizationalMemoryError(
                "APPROVED_FIRM_KNOWLEDGE requires derived_from_item_id -- it must "
                "trace back to the SOURCE_MEMORY item it was derived from")

        # Exact source linkage: SOURCE_MEMORY and PROPOSAL_MEMORY must
        # reference a real, specific source, never a vague/fabricated one
        # (reuses PI-2A's exact-identity discipline -- content_hash/file_id,
        # never fuzzy-matched).
        if self.memory_class in (MemoryClass.SOURCE_MEMORY, MemoryClass.PROPOSAL_MEMORY):
            if not self.provenance.has_exact_identity():
                raise OrganizationalMemoryError(
                    f"{self.memory_class.value} requires exact source identity "
                    "(file_id or content_hash) -- provenance cannot be vague or fabricated")

    @property
    def is_trusted_fact(self) -> bool:
        """Only APPROVED_FIRM_KNOWLEDGE may ever be treated as verified,
        reusable organizational truth. SOURCE_MEMORY may only SUPPORT a
        claim; PROPOSAL_MEMORY can never PROVE one."""
        return self.memory_class is MemoryClass.APPROVED_FIRM_KNOWLEDGE

    @property
    def can_prove_facts(self) -> bool:
        """Structural gate matching the PI/evidence discipline: only
        explicit human-approved firm knowledge can ever be cited as proof.
        PROPOSAL_MEMORY is marketing language, never usable as proof of a
        fact by any code path."""
        return self.is_trusted_fact


# ── Retrieval contract ──────────────────────────────────────────────────

@dataclass(frozen=True)
class RetrievalResult:
    """One ranked/filtered result. Every result exposes memory class,
    trust/approval state, provenance, and a relevance signal -- never bare
    text with no context about what kind of thing it is or how much to
    trust it."""

    item_id: str
    memory_class: MemoryClass
    title: str
    content: str
    is_trusted_fact: bool
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    provenance: SourceProvenance
    relevance_score: float
    relevance_signal: str   # "SEMANTIC" | "KEYWORD" -- how the score was computed
    # Commissioning-review fix #4: durable lineage --
    # APPROVED_FIRM_KNOWLEDGE -> derived_from_item_id (its SOURCE_MEMORY
    # parent) -> source_document_id (that parent's organizational_source_
    # documents row) -> the physical source (content_hash/filename/
    # storage_path, already exposed via `provenance`). Both fields are None
    # when not applicable/known -- never fabricated. No signed-URL or
    # storage-credential field is ever exposed here or on `provenance`.
    source_document_id: Optional[str] = None
    derived_from_item_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "memory_class": self.memory_class.value,
            "title": self.title,
            "content": self.content,
            "is_trusted_fact": self.is_trusted_fact,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "provenance": self.provenance.to_dict(),
            "relevance_score": self.relevance_score,
            "relevance_signal": self.relevance_signal,
            "source_document_id": self.source_document_id,
            "derived_from_item_id": self.derived_from_item_id,
        }


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


_WORD = re.compile(r"[a-z0-9]+")


def _keywords(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def _keyword_score(query: str, item: OrganizationalMemoryItem) -> float:
    """Deterministic keyword-overlap fallback: Jaccard similarity between
    the query's and the item's (title + content) keyword sets. Always
    computable, never dependent on any external service."""
    query_words = _keywords(query)
    if not query_words:
        return 0.0
    item_words = _keywords(f"{item.title} {item.content}")
    if not item_words:
        return 0.0
    overlap = len(query_words & item_words)
    union = len(query_words | item_words)
    return round(overlap / union, 6) if union else 0.0


def retrieve(
    *,
    organization_id: str,
    query: str,
    items: Iterable[OrganizationalMemoryItem],
    memory_classes: Optional[Iterable[MemoryClass]] = None,
    trusted_only: bool = False,
    top_k: int = 10,
    min_score: float = 0.0,
    embed_fn: Optional[Callable[[str], Optional[list[float]]]] = None,
    item_embed_fn: Optional[Callable[[OrganizationalMemoryItem], Optional[list[float]]]] = None,
) -> list[RetrievalResult]:
    """The OM-1 retrieval contract: "what verified organizational evidence
    do we already have for this requirement or PI weakness?"

    Deterministic given the same inputs. Never returns items outside
    `organization_id` (no cross-organization retrieval is possible through
    this function -- every item not matching is dropped before scoring).
    Never loads more than `top_k` items into the result.

    Parameters
    ----------
    organization_id : the caller's own organization -- required. Only
        items whose `organization_id` matches exactly are eligible.
    query : free text (a requirement description, a PI weakness/gap
        description, or similar).
    items : the candidate pool (already fetched by the caller's own
        organization-scoped read path, e.g. tenancy.py's
        `*_authenticated`/`*_for_organization` pattern -- this function
        does not fetch anything itself).
    memory_classes : optional filter restricting which memory classes are
        eligible (e.g. only APPROVED_FIRM_KNOWLEDGE when a caller needs
        provable fact, not suggestion). None means all three classes are
        eligible.
    trusted_only : when True, restricts to `is_trusted_fact` items only
        (APPROVED_FIRM_KNOWLEDGE) regardless of `memory_classes`.
    top_k : hard cap on returned results -- retrieval is always selective,
        never a full-archive dump.
    min_score : results below this relevance score are dropped.
    embed_fn : optional query-embedding function, e.g. `embeddings.embed_query`.
        Called with `query`; expected to return a vector or None/raise on
        failure. When it returns a usable vector AND at least one
        candidate item exposes a usable embedding (via `item_embed_fn` or
        `item.embedding`), retrieval uses cosine similarity
        (`relevance_signal="SEMANTIC"`). Any failure (None returned,
        exception raised, or no items have vectors) degrades gracefully to
        the deterministic keyword filter (`relevance_signal="KEYWORD"`) --
        this fallback path is a required, explicitly tested scenario, not
        an afterthought.
    item_embed_fn : optional override for reading an item's embedding
        (defaults to `item.embedding`) -- lets a caller resolve stored
        embeddings lazily/differently without changing this contract.
    """
    if not organization_id:
        raise OrganizationalMemoryError("retrieve() requires organization_id")
    if top_k <= 0:
        return []

    allowed_classes = (
        {MemoryClass.APPROVED_FIRM_KNOWLEDGE} if trusted_only
        else (set(memory_classes) if memory_classes is not None else set(MemoryClass))
    )

    # Organization isolation + class filter, applied BEFORE any scoring --
    # an item from another organization is never even scored, let alone
    # returned. This is the retrieval-path enforcement of the same
    # isolation direct data access already provides.
    candidates = [
        item for item in items
        if item.organization_id == organization_id and item.memory_class in allowed_classes
    ]
    if not candidates:
        return []

    query_vector: Optional[list[float]] = None
    if embed_fn is not None:
        try:
            query_vector = embed_fn(query)
        except Exception:
            query_vector = None

    def _item_vector(item: OrganizationalMemoryItem) -> Optional[list[float]]:
        if item_embed_fn is not None:
            try:
                return item_embed_fn(item)
            except Exception:
                return None
        return item.embedding

    scoreable_semantic = query_vector is not None and any(
        _item_vector(item) for item in candidates
    )

    scored: list[RetrievalResult] = []
    for item in candidates:
        if scoreable_semantic:
            vec = _item_vector(item)
            if vec:
                score = round(_cosine_similarity(query_vector, vec), 6)
                signal = "SEMANTIC"
            else:
                # An item with no embedding still participates, via the
                # deterministic fallback score, rather than being silently
                # dropped from an otherwise-semantic result set.
                score = _keyword_score(query, item)
                signal = "KEYWORD"
        else:
            score = _keyword_score(query, item)
            signal = "KEYWORD"

        scored.append(RetrievalResult(
            item_id=item.id,
            memory_class=item.memory_class,
            title=item.title,
            content=item.content,
            is_trusted_fact=item.is_trusted_fact,
            approved_by=item.approved_by,
            approved_at=item.approved_at,
            provenance=item.provenance,
            relevance_score=score,
            relevance_signal=signal,
            source_document_id=item.source_document_id,
            derived_from_item_id=item.derived_from_item_id,
        ))

    scored = [r for r in scored if r.relevance_score >= min_score]
    # Deterministic ordering: score desc, then item_id asc as a stable
    # tie-break so identical inputs always produce identical output order.
    scored.sort(key=lambda r: (-r.relevance_score, r.item_id))
    return scored[:top_k]


# ── OM-2: deterministic source chunking ──────────────────────────────────
# Mirrors the bin-packing/window-fallback principles analyst.py already
# established for Proposal Alignment (_split_proposal_into_sections /
# _merge_and_size_bound_sections) -- greedy paragraph-bin-packing toward a
# target chunk size, with a fixed-window fallback for text that has no
# usable paragraph breaks (e.g. one giant unbroken blob). Deterministic:
# the same text always produces the same chunk boundaries, no randomness,
# no model calls. This is intentionally a smaller, self-contained version
# scoped to Organizational Memory source ingestion -- it does not import
# analyst.py (which is Proposal-Intelligence-specific and carries heading
# detection tuned for proposal documents) and it never fabricates a
# char_start/char_end coordinate beyond what the split itself produces.

SOURCE_CHUNK_TARGET_CHARS = 4000
SOURCE_CHUNK_MIN_CHARS = 200

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


def _fixed_window_chunks(text: str, target: int) -> list[tuple[int, int]]:
    """Deterministic non-overlapping fixed windows -- the fallback when a
    paragraph (or single oversized paragraph) has no usable break."""
    n = len(text)
    if n == 0:
        return []
    bounds = []
    start = 0
    while start < n:
        end = min(start + target, n)
        bounds.append((start, end))
        start = end
    return bounds


def split_source_into_chunks(
    text: str, target_chunk_chars: int = SOURCE_CHUNK_TARGET_CHARS,
) -> list[dict]:
    """Splits `text` into deterministic, bounded, non-overlapping chunks
    with exact char_start/char_end coordinates into the ORIGINAL text --
    never re-derived/approximate. Every character of `text` is accounted
    for in exactly one chunk; nothing is dropped, nothing is duplicated.

    Strategy: split on blank-line paragraph boundaries, then greedily
    bin-pack adjacent paragraphs together while the combined size still
    fits under `target_chunk_chars` (same bin-packing principle as
    analyst._merge_and_size_bound_sections). A single paragraph that alone
    exceeds the target is further split with a deterministic fixed-window
    fallback rather than kept as one oversized chunk.

    Returns a list of {"chunk_index", "char_start", "char_end", "text"}
    dicts, in original-document order.
    """
    if not text:
        return []

    n = len(text)
    # Raw paragraph spans, contiguous and covering 100% of `text`: each
    # span runs up to (and includes) the blank-line separator that follows
    # it, so no character -- including whitespace between paragraphs -- is
    # ever dropped or unaccounted for.
    bounds = [0] + [m.end() for m in _PARAGRAPH_SPLIT.finditer(text)] + [n]
    bounds = sorted(set(bounds))
    raw_spans = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1) if bounds[i + 1] > bounds[i]]
    if not raw_spans:
        raw_spans = [(0, n)]

    # Greedy bin-pack adjacent paragraph spans toward target_chunk_chars.
    merged: list[tuple[int, int]] = []
    cur_start, cur_end = raw_spans[0]
    for s, e in raw_spans[1:]:
        if (e - cur_start) <= target_chunk_chars:
            cur_end = e
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = s, e
    merged.append((cur_start, cur_end))

    # Split any still-oversized merged span (e.g. one huge paragraph) with
    # the deterministic fixed-window fallback.
    bounded: list[tuple[int, int]] = []
    for s, e in merged:
        if (e - s) <= target_chunk_chars:
            bounded.append((s, e))
        else:
            for ws, we in _fixed_window_chunks(text[s:e], target_chunk_chars):
                bounded.append((s + ws, s + we))

    chunks = []
    for idx, (s, e) in enumerate(bounded):
        chunks.append({
            "chunk_index": idx,
            "char_start": s,
            "char_end": e,
            "text": text[s:e],
        })
    return chunks


__all__ = [
    "ORGANIZATIONAL_MEMORY_CONTRACT_VERSION",
    "MemoryClass",
    "OrganizationalMemoryError",
    "OrganizationalMemoryItem",
    "RetrievalResult",
    "SourceProvenance",
    "content_hash",
    "retrieve",
    "SOURCE_CHUNK_TARGET_CHARS",
    "SOURCE_CHUNK_MIN_CHARS",
    "split_source_into_chunks",
]
