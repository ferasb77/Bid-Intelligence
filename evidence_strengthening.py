"""
evidence_strengthening.py -- OM-3: Requirement Evidence Strengthening.

The FIRST product-value integration between Organizational Memory
(migrations/016_organizational_memory.sql, OM-1/OM-2, live-commissioned) and
Bid Intelligence's existing requirement/evidence model. This module answers
exactly one question: "can a requirement whose CURRENT-BID evidence is weak,
partial, missing, or conflicted retrieve a small, ranked set of relevant
Organizational Memory evidence, with provenance/trust/lineage preserved,
without ever letting Organizational Memory override the current RFP or
bid-specific evidence?"

It is advisory enrichment, never a second requirement/evidence model:

  - "current evidence state" reuses proposal_intelligence.py's EXISTING,
    already-persisted vocabulary verbatim -- ASSESSMENT_STATUSES
    ("Fully Addressed"/"Partially Addressed"/"Not Addressed"/"Cannot
    Assess") and EVIDENCE_STRENGTH_VALUES ("STRONG"/"MODERATE"/"WEAK"),
    plus the existing CONTRADICTION/INTERNAL_INCONSISTENCY finding types
    for "conflicted" -- never a second invented status vocabulary.
  - Organizational Memory candidates and their provenance/trust/lineage
    reuse organizational_memory.py's retrieval contract (`retrieve()`,
    `OrganizationalMemoryItem`, `RetrievalResult`, `SourceProvenance`)
    verbatim -- this module does not re-rank, re-filter, or re-fetch
    Organizational Memory itself, only calls the existing contract with a
    query it derives deterministically from the requirement.

Evidence hierarchy (enforced in behavior, not merely documented):
  1. current RFP / amendments / appendices        (source_refs on the
                                                     requirement itself)
  2. bid-specific verified evidence                (the requirement's own
                                                     latest Proposal
                                                     Intelligence
                                                     assessment_status /
                                                     evidence_strength --
                                                     `RequirementEvidenceState`)
  3. APPROVED_FIRM_KNOWLEDGE                        (Organizational Memory)
  4. SOURCE_MEMORY                                  (Organizational Memory)
  5. model inference                                (the adjudication call
                                                     below classifies, it
                                                     never asserts a new
                                                     fact)

Tiers 3-4 (Organizational Memory) can only ADD candidate evidence for a
human to review -- `strengthen_requirement_evidence()` NEVER overwrites
`assessment_status`/`evidence_strength` (tier 2) with anything Organizational
Memory says; a CONTRADICTION-classified candidate is surfaced for review,
never silently treated as support, and never allowed to change tier 2's own
verdict.

This module performs no I/O and no persistence of its own -- exactly like
proposal_intelligence.py, tenancy.py owns fetching the requirement/
assessment/candidate rows, wiring this module's pure functions together
(see tenancy.strengthen_requirement_evidence_for_organization), and
persisting the result (migrations/017_requirement_evidence_enrichment.sql,
OM-3B). The one external call this module DOES make -- the adjudication
classification -- reuses this codebase's existing structured-output
model-call infrastructure (config.get_anthropic_client/
execute_messages_create, the same pattern as
analyst._call_package_reasoning) and is fully injectable via `adjudicate_fn`
for deterministic, mocked testing.

OM-3B (durable persistence, migration 017): `compute_input_fingerprint()`
below is this module's own contribution to that reuse layer -- a pure,
deterministic sha256 fingerprint (same canonicalization convention as
proposal_intelligence.compute_package_digest) over exactly what
`strengthen_requirement_evidence()`'s output actually depends on, so a
caller can persist a result keyed by this fingerprint and skip recomputing
(including the adjudication model call) whenever the fingerprint is
unchanged. This module still performs no persistence itself -- the
fingerprint is a pure function callers use however they choose.

Explicitly NOT built here (OM-3 scope, see docs/current/SYSTEM_STATE.md):
proposal-text generation, UI, auto-approval/auto-promotion of any
Organizational Memory item, and a generic free-form
`searchOrganizationalMemory(query)` capability.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable, Optional

import organizational_memory as om

EVIDENCE_STRENGTHENING_CONTRACT_VERSION = "om-3.0.0"

DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 0.0


class MemoryRelationship(str, Enum):
    """The bounded relationship vocabulary a retrieved Organizational
    Memory candidate may be classified into, relative to ONE requirement.
    Never expanded ad hoc -- an adjudicator returning anything outside
    this set is rejected (fail-closed), not coerced into the nearest
    value."""

    DIRECT_SUPPORT = "DIRECT_SUPPORT"
    PARTIAL_SUPPORT = "PARTIAL_SUPPORT"
    CONTEXT = "CONTEXT"
    CONTRADICTION = "CONTRADICTION"


_VALID_RELATIONSHIPS = {r.value for r in MemoryRelationship}

# Only these relationships ever count as "organizational support" toward
# evidence_state_after -- CONTRADICTION is structurally excluded so
# retrieval itself can never turn a conflicting memory item into an
# asserted claim of support (instruction 4).
_SUPPORTIVE_RELATIONSHIPS = {MemoryRelationship.DIRECT_SUPPORT.value, MemoryRelationship.PARTIAL_SUPPORT.value}


class EvidenceGapKind(str, Enum):
    """Closed classification of a requirement's CURRENT-BID evidence gap,
    derived ONLY from proposal_intelligence.py's existing
    assessment_status/evidence_strength vocabulary (tier 2 of the
    hierarchy) plus whether an existing CONTRADICTION/
    INTERNAL_INCONSISTENCY finding is already tied to this requirement --
    never from Organizational Memory, which cannot influence this
    classification at all."""

    MISSING = "MISSING"
    PARTIAL = "PARTIAL"
    WEAK = "WEAK"
    CONFLICTED = "CONFLICTED"
    SUFFICIENT = "SUFFICIENT"


_GAP_DESCRIPTIONS = {
    EvidenceGapKind.MISSING: "no current-bid evidence addresses this requirement",
    EvidenceGapKind.PARTIAL: "current-bid evidence only partially addresses this requirement",
    EvidenceGapKind.WEAK: "current-bid evidence is weak or unsubstantiated for this requirement",
    EvidenceGapKind.CONFLICTED: "current-bid evidence for this requirement has a known contradiction",
    EvidenceGapKind.SUFFICIENT: "",
}


@dataclass(frozen=True)
class RequirementEvidenceState:
    """The requirement's CURRENT-BID evidence-gap state (hierarchy tier 2)
    -- built by the caller from the requirement's own latest
    proposal_requirement_assessments row and any
    CONTRADICTION/INTERNAL_INCONSISTENCY finding already tied to it.
    Organizational Memory is never consulted to construct this -- it is
    the input strengthening reasons FROM, never the thing being
    strengthened."""

    assessment_status: Optional[str] = None   # one of proposal_intelligence.ASSESSMENT_STATUSES, or None (no PI run yet)
    evidence_strength: Optional[str] = None   # one of proposal_intelligence.EVIDENCE_STRENGTH_VALUES, or None
    has_contradiction_finding: bool = False

    @property
    def gap_kind(self) -> EvidenceGapKind:
        if self.has_contradiction_finding:
            return EvidenceGapKind.CONFLICTED
        if self.assessment_status in (None, "Not Addressed", "Cannot Assess"):
            return EvidenceGapKind.MISSING
        if self.assessment_status == "Partially Addressed":
            return EvidenceGapKind.PARTIAL
        if self.evidence_strength in (None, "WEAK"):
            return EvidenceGapKind.WEAK
        # Fully Addressed + STRONG/MODERATE evidence, no known contradiction.
        return EvidenceGapKind.SUFFICIENT

    @property
    def needs_strengthening(self) -> bool:
        """False only for a genuinely strong requirement -- Organizational
        Memory retrieval must never run merely because it CAN; see
        instruction 9's "a strong requirement does not trigger wasteful
        retrieval if strengthening would add no value"."""
        return self.gap_kind is not EvidenceGapKind.SUFFICIENT

    def to_dict(self) -> dict:
        return {
            "assessment_status": self.assessment_status,
            "evidence_strength": self.evidence_strength,
            "has_contradiction_finding": self.has_contradiction_finding,
            "gap_kind": self.gap_kind.value,
        }


@dataclass(frozen=True)
class MemoryEvidenceCandidate:
    """One adjudicated Organizational Memory candidate for a requirement.
    Carries everything a human reviewer needs to decide whether/how to use
    it -- memory item identity, trust class, relationship, a concise
    rationale, full provenance, and approval lineage when present -- never
    bare text with no context. Nothing here mutates the underlying
    Organizational Memory item; this is a read-only projection of it."""

    item_id: str
    memory_class: str
    is_trusted_fact: bool
    title: str
    relationship: str
    rationale: str
    relevance_score: float
    relevance_signal: str
    provenance: dict
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    derived_from_item_id: Optional[str] = None
    source_document_id: Optional[str] = None
    caveat: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "memory_class": self.memory_class,
            "is_trusted_fact": self.is_trusted_fact,
            "title": self.title,
            "relationship": self.relationship,
            "rationale": self.rationale,
            "relevance_score": self.relevance_score,
            "relevance_signal": self.relevance_signal,
            "provenance": self.provenance,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "derived_from_item_id": self.derived_from_item_id,
            "source_document_id": self.source_document_id,
            "caveat": self.caveat,
        }


@dataclass(frozen=True)
class EvidenceEnrichmentResult:
    """The deterministic domain object this module returns. Never persisted
    by this module -- a pure compute-and-return result, exactly like
    proposal_intelligence.py's adapter functions return plain rows for a
    caller to persist (or not)."""

    requirement_id: Optional[int]
    req_id: str
    evidence_state_before: dict
    organizational_evidence: tuple
    evidence_state_after: dict
    remaining_gaps: tuple
    requires_human_confirmation: bool
    retrieval_skipped_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "requirement_id": self.requirement_id,
            "req_id": self.req_id,
            "evidence_state_before": self.evidence_state_before,
            "organizational_evidence": [c.to_dict() for c in self.organizational_evidence],
            "evidence_state_after": self.evidence_state_after,
            "remaining_gaps": list(self.remaining_gaps),
            "requires_human_confirmation": self.requires_human_confirmation,
            "retrieval_skipped_reason": self.retrieval_skipped_reason,
        }


def _build_requirement_query(requirement: dict) -> str:
    """Deterministically derives the Organizational Memory retrieval query
    from the requirement's OWN fields -- never a free-form query supplied
    by a caller (instruction 2: no unrestricted free-form memory-search
    query, and instruction "do not introduce a generic agent-facing
    searchOrganizationalMemory(query) capability")."""
    parts = [requirement.get("description") or "", requirement.get("category") or ""]
    return " ".join(p for p in parts if p).strip()


def compute_input_fingerprint(
    requirement: dict,
    evidence_state: RequirementEvidenceState,
    candidate_items: Iterable["om.OrganizationalMemoryItem"],
) -> str:
    """OM-3B: a deterministic sha256 fingerprint over exactly what
    `strengthen_requirement_evidence()`'s output depends on -- nothing more,
    nothing less. Same canonicalization convention as
    proposal_intelligence.compute_package_digest (sorted-key JSON, sha256
    hex over UTF-8 bytes), so a byte-identical set of inputs always
    produces the identical fingerprint and a caller can key a persisted
    result by it (instruction 3: "a simpler deterministic input fingerprint"
    rather than a broader dependency graph).

    Covers, in order:
      - the requirement's own identity/text (req_id/description/category)
        -- hierarchy tier 1/2 input;
      - the CURRENT-BID evidence-gap state (assessment_status/
        evidence_strength/has_contradiction_finding/gap_kind) -- tier 2;
      - the FULL considered Organizational Memory candidate pool's identity
        (item_id + item_content_hash + memory_class for every candidate
        handed to `retrieve()`, sorted by item_id) -- tier 3/4. This is
        deliberately the whole pool evidence_strengthening was GIVEN, not
        only the top_k actually ranked/returned: a newly-added or newly-
        changed memory item that would change what top_k selects must
        still invalidate a prior result, even if that item itself never
        makes the final ranked set. Never includes item content/text --
        identity only, exactly like compute_package_digest never includes
        raw extracted text;
      - EVIDENCE_STRENGTHENING_CONTRACT_VERSION -- bumping this constant
        (an adjudication prompt/logic change) invalidates every previously
        computed fingerprint even when every other input is identical,
        exactly like PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION already does
        for Proposal Intelligence.

    Deliberately excludes internal database row ids (requirement_id) and
    anything not actually read by `strengthen_requirement_evidence()` --
    an unrelated column changing on the requirement row must never
    invalidate a still-accurate enrichment."""
    requirement_identity = {
        "req_id": requirement.get("req_id"),
        "description": requirement.get("description"),
        "category": requirement.get("category"),
    }
    candidate_identity = sorted(
        (
            {
                "item_id": item.id,
                "memory_class": item.memory_class.value,
                "item_content_hash": item.item_content_hash,
            }
            for item in candidate_items
        ),
        key=lambda row: row["item_id"] or "",
    )
    payload = {
        "contract_version": EVIDENCE_STRENGTHENING_CONTRACT_VERSION,
        "requirement": requirement_identity,
        "evidence_state": evidence_state.to_dict(),
        "candidates": candidate_identity,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_ADJUDICATION_SYSTEM = (
    "You are a precise, evidence-bound reviewer classifying organizational-memory "
    "material against ONE procurement requirement. You reason ONLY over the requirement "
    "and candidate excerpts given -- never assume or invent content outside them. You "
    "never draft proposal language and you never assert that a candidate is true; you "
    "only classify its relationship to the requirement."
)


def _adjudication_prompt(requirement: dict, evidence_state: RequirementEvidenceState, candidates: list) -> str:
    req_block = (
        f"req_id: {requirement.get('req_id')}\n"
        f"category: {requirement.get('category') or ''}\n"
        f"description: {requirement.get('description') or ''}\n"
        f"current bid-evidence status: {evidence_state.assessment_status or 'unknown'} "
        f"(evidence_strength={evidence_state.evidence_strength or 'unknown'})"
    )
    cand_lines = [
        f"[{c.item_id}] class={c.memory_class.value} title={c.title!r}\n{(c.content or '')[:800]}"
        for c in candidates
    ]
    candidates_block = "\n\n".join(cand_lines)
    return f"""REQUIREMENT
{req_block}

CANDIDATE ORGANIZATIONAL MEMORY ITEMS (id in brackets)
{candidates_block}

TASK: for EACH candidate that has a genuine relationship to the requirement, classify it as exactly one of:
  DIRECT_SUPPORT   -- concretely, specifically supports meeting this requirement
  PARTIAL_SUPPORT  -- relevant and useful but incomplete or generic support
  CONTEXT          -- relevant background, does not itself support compliance
  CONTRADICTION    -- conflicts with the requirement or with the current bid-evidence status above

Omit any candidate with no genuine relationship at all -- never force a classification onto irrelevant material merely because it was retrieved.

Return ONLY valid JSON:
{{"assessments": [{{"item_id": "<id>", "relationship": "DIRECT_SUPPORT|PARTIAL_SUPPORT|CONTEXT|CONTRADICTION", "rationale": "<=200 chars, concise", "caveat": "<=200 chars or null"}}]}}
If no candidate has a genuine relationship, return {{"assessments": []}}."""


def _call_memory_adjudication(prompt: str, *, bid_id: Optional[int], max_tokens: int = 1200) -> tuple:
    """The ONE bounded model call this module adds -- reuses this
    codebase's existing structured-output infrastructure
    (config.get_anthropic_client/execute_messages_create with a
    telemetry_context, exactly analyst._call_package_reasoning's pattern)
    rather than inventing a new call mechanism. Never raises past this
    function; a failure returns (None, reason) and the caller treats that
    as zero adjudicated candidates (fail closed, never guesses a
    relationship). workflow="organizational_memory",
    operation="evidence_adjudication" keeps this call in its own telemetry
    bucket, distinct from analyst.py's 11 existing workflows."""
    from config import get_anthropic_client, execute_messages_create

    try:
        client = get_anthropic_client()
        response = execute_messages_create(
            client,
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            system=_ADJUDICATION_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            telemetry_context={
                "workflow": "organizational_memory",
                "operation": "evidence_adjudication",
                "bid_id": bid_id,
            },
            retry_number=0,
        )
        raw = response.content[0].text.strip()
    except Exception:
        return None, "api_error"

    import analyst
    try:
        parsed = analyst._parse_json(raw)
    except Exception:
        return None, "parse_error"
    if not isinstance(parsed, dict) or not isinstance(parsed.get("assessments"), list):
        return None, "malformed_response"
    return parsed, None


def _adjudicate_candidates(
    *, requirement: dict, evidence_state: RequirementEvidenceState,
    candidates: list, bid_id: Optional[int],
) -> list:
    """Default adjudicator: ONE bounded model call over the already-small,
    already-ranked candidate set, then fail-closed reconciliation of the
    response -- an unknown item_id, an item_id outside the candidate set
    (never invented), a duplicate item_id, an unrecognized relationship
    value, or a missing rationale drops THAT candidate only, mirroring
    analyst._reconcile_package_findings' per-item fail-closed pattern. A
    total API/parse failure returns [] -- retrieval alone is NEVER treated
    as support (instruction 4)."""
    if not candidates:
        return []

    candidate_by_id = {c.item_id: c for c in candidates}
    prompt = _adjudication_prompt(requirement, evidence_state, candidates)
    parsed, _failure_reason = _call_memory_adjudication(prompt, bid_id=bid_id)
    if parsed is None:
        return []

    results = []
    seen_ids = set()
    for entry in parsed.get("assessments") or []:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("item_id")
        relationship = entry.get("relationship")
        rationale = entry.get("rationale")
        if item_id not in candidate_by_id or item_id in seen_ids:
            continue
        if relationship not in _VALID_RELATIONSHIPS:
            continue
        if not isinstance(rationale, str) or not rationale.strip():
            continue
        caveat = entry.get("caveat")
        caveat = caveat.strip()[:200] if isinstance(caveat, str) and caveat.strip() else None

        seen_ids.add(item_id)
        cand = candidate_by_id[item_id]
        results.append(MemoryEvidenceCandidate(
            item_id=cand.item_id,
            memory_class=cand.memory_class.value,
            is_trusted_fact=cand.is_trusted_fact,
            title=cand.title,
            relationship=relationship,
            rationale=rationale.strip()[:200],
            relevance_score=cand.relevance_score,
            relevance_signal=cand.relevance_signal,
            provenance=cand.provenance.to_dict(),
            approved_by=cand.approved_by,
            approved_at=cand.approved_at.isoformat() if cand.approved_at else None,
            derived_from_item_id=cand.derived_from_item_id,
            source_document_id=cand.source_document_id,
            caveat=caveat,
        ))
    return results


def strengthen_requirement_evidence(
    *,
    organization_id: str,
    bid_id: Optional[int],
    requirement: dict,
    evidence_state: RequirementEvidenceState,
    candidate_items: Iterable["om.OrganizationalMemoryItem"] = (),
    top_k: int = DEFAULT_TOP_K,
    min_score: float = DEFAULT_MIN_SCORE,
    embed_fn: Optional[Callable] = None,
    item_embed_fn: Optional[Callable] = None,
    adjudicate_fn: Optional[Callable] = None,
) -> EvidenceEnrichmentResult:
    """The requirement-aware Organizational Memory strengthening boundary
    (OM-3). Inputs derive entirely from the requirement and its EXISTING
    evidence state -- there is no free-form query parameter here at all.

    Organization isolation, provenance, approval lineage, and trust class
    are preserved end to end: candidate_items must already be scoped to
    `organization_id` by the caller (tenancy.py's existing
    `*_for_organization` read pattern); `organizational_memory.retrieve()`
    re-enforces that scoping itself and drops anything that doesn't match
    before it is ever scored.

    Never mutates an Organizational Memory item, never converts
    SOURCE_MEMORY into APPROVED_FIRM_KNOWLEDGE, never drafts proposal
    text, and never lets Organizational Memory override
    `evidence_state.assessment_status`/`evidence_strength` -- those fields
    are copied into `evidence_state_after` completely unchanged; only new,
    additive fields describing Organizational Memory's contribution are
    added alongside them.
    """
    req_id = requirement.get("req_id") or ""
    requirement_id = requirement.get("id")
    before = evidence_state.to_dict()

    if not evidence_state.needs_strengthening:
        # Instruction 9: a genuinely strong requirement must not trigger
        # retrieval at all -- not even a candidate-pool scan. Returns
        # immediately; `candidate_items`/`om.retrieve`/`adjudicate_fn` are
        # never touched below this point.
        return EvidenceEnrichmentResult(
            requirement_id=requirement_id, req_id=req_id,
            evidence_state_before=before,
            organizational_evidence=(),
            evidence_state_after=dict(
                before, has_organizational_support=False,
                organizational_support_count=0, has_organizational_contradiction=False,
            ),
            remaining_gaps=(),
            requires_human_confirmation=False,
            retrieval_skipped_reason=(
                "requirement evidence is already sufficient (Fully Addressed, "
                "STRONG/MODERATE evidence, no known contradiction) -- "
                "Organizational Memory retrieval skipped"
            ),
        )

    query = _build_requirement_query(requirement)
    ranked = om.retrieve(
        organization_id=organization_id,
        query=query,
        items=candidate_items,
        memory_classes=[om.MemoryClass.APPROVED_FIRM_KNOWLEDGE, om.MemoryClass.SOURCE_MEMORY],
        top_k=top_k,
        min_score=min_score,
        embed_fn=embed_fn,
        item_embed_fn=item_embed_fn,
    )

    adjudicated = []
    if ranked:
        adjudicate = adjudicate_fn or _adjudicate_candidates
        adjudicated = adjudicate(
            requirement=requirement, evidence_state=evidence_state,
            candidates=ranked, bid_id=bid_id,
        )

    evidence = tuple(adjudicated)
    supportive = [c for c in evidence if c.relationship in _SUPPORTIVE_RELATIONSHIPS]
    contradictions = [c for c in evidence if c.relationship == MemoryRelationship.CONTRADICTION.value]

    # Hierarchy enforcement: `before` is copied verbatim into `after` --
    # Organizational Memory only ever ADDS fields alongside it, never
    # overwrites assessment_status/evidence_strength/gap_kind, regardless
    # of what was retrieved or how it was classified (tier 2 always beats
    # tiers 3-4).
    after = dict(before)
    after["has_organizational_support"] = bool(supportive)
    after["organizational_support_count"] = len(supportive)
    after["has_organizational_contradiction"] = bool(contradictions)

    remaining = []
    if not supportive:
        remaining.append(_GAP_DESCRIPTIONS[evidence_state.gap_kind])
    if contradictions:
        remaining.append(
            "organizational memory surfaced a possible contradiction -- "
            "requires human review before any use"
        )

    return EvidenceEnrichmentResult(
        requirement_id=requirement_id, req_id=req_id,
        evidence_state_before=before,
        organizational_evidence=evidence,
        evidence_state_after=after,
        remaining_gaps=tuple(g for g in remaining if g),
        # A human must confirm before anything surfaced here is ever used --
        # this module never auto-approves, never auto-promotes, and never
        # drafts proposal language, so ANY non-empty result still requires
        # explicit human confirmation.
        requires_human_confirmation=bool(evidence),
        retrieval_skipped_reason=None,
    )


__all__ = [
    "EVIDENCE_STRENGTHENING_CONTRACT_VERSION",
    "DEFAULT_TOP_K",
    "DEFAULT_MIN_SCORE",
    "MemoryRelationship",
    "EvidenceGapKind",
    "RequirementEvidenceState",
    "MemoryEvidenceCandidate",
    "EvidenceEnrichmentResult",
    "strengthen_requirement_evidence",
    "compute_input_fingerprint",
]
