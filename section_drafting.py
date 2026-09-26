"""
section_drafting.py -- Section Response Intelligence (formerly PI-3A
"Evidence-Aware Section Drafting").

PRODUCT BOUNDARY: Bid Intelligence no longer generates proposal narrative.
The proposal-generation path this module once hosted (`draft_section`, its
`_call_section_draft` model call and drafting prompt) was DECOMMISSIONED
and deleted. What remains is pure, non-generative response intelligence
and claim/evidence-validation logic, kept for BUILD's Response Brief and
as building blocks for future CHECK work:

    build_brief(...)                  : deterministic assembly of a bounded
                                         SectionResponseBrief (requirements,
                                         evaluation intent, evidence tiers,
                                         gaps, contradictions, human-
                                         confirmation needs, constraints)
                                         from ALREADY-FETCHED raw materials
    compute_draft_input_fingerprint() : freshness fingerprint (still used to
                                         mark historical persisted drafts as
                                         stale/current, read-only)
    evidence_id_registry / reconcile_material_claims /
    reconcile_structured_result       : fail-closed claim/evidence-support
                                         validation (no model call)
    assure_section_draft(...)         : deterministic structural assurance of
                                         an already-structured result

The file name and `SECTION_DRAFTING_CONTRACT_VERSION` are kept unchanged so
historical `section_drafts` rows (migrations 018/019) keep their lineage
and fingerprints. No function here calls a model or writes anything.

Evidence hierarchy (structural, not just behavioral -- the brief itself
keeps these tiers in separate, distinctly-named fields so nothing can
blur into another tier by construction):
  1. current RFP / amendments / appendices   -> `current_rfp_source_refs`
                                                 (the requirement's OWN
                                                 canonical `source_refs`)
  2. bid-specific verified evidence           -> `bid_specific_evidence`
                                                 (the requirement's latest
                                                 Proposal Intelligence
                                                 assessment: assessment_
                                                 status/evidence_strength/
                                                 confidence/explanation/
                                                 proposal_source_refs)
  3/4. Organizational Memory (APPROVED_FIRM_
       KNOWLEDGE / SOURCE_MEMORY)             -> `organizational_evidence`
                                                 (OM-3B's ALREADY-PERSISTED
                                                 enrichment, read-only --
                                                 see "No independent
                                                 retrieval" below)
  5. model inference                          -> never a factual source;
                                                 the drafting call is
                                                 instructed to classify,
                                                 never assert, and to mark
                                                 a gap explicitly rather
                                                 than invent

Tiers 3/4 (Organizational Memory) can only ADD candidate evidence for the
draft to cite; a CONTRADICTION-classified OM item already present in the
brief must be surfaced as a caveat, never silently used as support, and
current-bid evidence (tiers 1/2) is never overridden by it -- this module
does not re-derive that precedence (OM-3A/OM-3B already established it);
it only carries the ALREADY-adjudicated relationship through unchanged.

No independent retrieval (instruction 6): this module
NEVER calls organizational_memory.retrieve(), NEVER re-runs OM-3A/OM-3B,
NEVER re-runs Proposal Alignment, and NEVER fetches full RFP/proposal
text. `build_brief()` takes an ALREADY-PERSISTED OM-3B enrichment dict (or
None) as a plain argument -- it does not fetch or compute one. This
extends the "analyze once, persist, draft from persisted intelligence"
discipline to brief assembly itself, not merely the drafting call: a
caller that wants fresh Organizational Memory enrichment must invoke OM-3B
(tenancy.strengthen_requirement_evidence_for_organization) as its OWN,
separate, prior step -- this module is strictly a downstream consumer.

Claim discipline (instruction 5): every evidence item a structured result
cites must reference a stable, bounded evidence id that already exists in
the brief (see `_evidence_id_registry`) -- an id the model invents, or
that isn't in the brief, is dropped by fail-closed reconciliation, never
trusted. This mirrors analyst.py's PI-2B1 P#/C# short-id ledger pattern
(`_build_package_intelligence_ledger`/`_reconcile_package_findings`) --
the same "bounded, addressed-only-by-short-IDs, never resend raw content"
discipline, applied here to a single-requirement brief instead of a
whole-package ledger.

Explicitly NOT here: any proposal-prose generation (retired product
direction -- must not be reintroduced under another name), Word export,
new Organizational Memory infrastructure.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

SECTION_DRAFTING_CONTRACT_VERSION = "pi-3a.1.0.0"

# ---------------------------------------------------------------------------
# Closed claim-type vocabulary (instruction 5) -- an evidence item cited by
# the drafting model must be tagged as exactly one of these; anything else
# is dropped by reconciliation, never guessed into the nearest value.
# ---------------------------------------------------------------------------
CLAIM_TYPE_VERIFIED_FACT = "VERIFIED_FACT"
CLAIM_TYPE_ORGANIZATIONAL_KNOWLEDGE = "ORGANIZATIONAL_KNOWLEDGE"
CLAIM_TYPE_PROPOSED_APPROACH = "PROPOSED_APPROACH"
CLAIM_TYPE_UNSUPPORTED_GAP = "UNSUPPORTED_GAP"
CLAIM_TYPES = (
    CLAIM_TYPE_VERIFIED_FACT, CLAIM_TYPE_ORGANIZATIONAL_KNOWLEDGE,
    CLAIM_TYPE_PROPOSED_APPROACH, CLAIM_TYPE_UNSUPPORTED_GAP,
)

# Evidence-source-kind vocabulary -- which tier of the hierarchy an
# evidence id in the brief's registry belongs to. Never conflated: a
# PROCUREMENT_EVIDENCE id is tier 1, PROPOSAL_EVIDENCE is tier 2,
# ORGANIZATIONAL_MEMORY is tier 3/4.
SOURCE_KIND_PROCUREMENT = "PROCUREMENT_EVIDENCE"
SOURCE_KIND_PROPOSAL = "PROPOSAL_EVIDENCE"
SOURCE_KIND_ORGANIZATIONAL_MEMORY = "ORGANIZATIONAL_MEMORY"

# ---------------------------------------------------------------------------
# PI-3C: claim-level support status -- a closed vocabulary describing
# whether a MATERIAL FACTUAL CLAIM in draft_text is actually backed by
# evidence already present in the brief's registry (see
# `_evidence_id_registry` / `MaterialClaim` below). Never trusted verbatim
# from the model -- derived/overridden deterministically during
# reconciliation from the claim's (fail-closed-filtered) evidence_ids and
# claim_type, per the hierarchy rules in `_reconcile_material_claims`.
# ---------------------------------------------------------------------------
SUPPORT_STATUS_SUPPORTED = "SUPPORTED"
SUPPORT_STATUS_PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
SUPPORT_STATUS_UNSUPPORTED = "UNSUPPORTED"
# PROPOSED_APPROACH claims are forward-looking commitments, never a
# historical fact "supported" by evidence -- COMMITMENT is a distinct
# status so a reader can never mistake a future promise for verified
# support.
SUPPORT_STATUS_COMMITMENT = "COMMITMENT"
SUPPORT_STATUSES = (
    SUPPORT_STATUS_SUPPORTED, SUPPORT_STATUS_PARTIALLY_SUPPORTED,
    SUPPORT_STATUS_UNSUPPORTED, SUPPORT_STATUS_COMMITMENT,
)

# A material claim is a BOUNDED improvement, not an attempt at exhaustive
# sentence-level citation (instruction 7 explicitly forbids that) -- capped
# so the drafting model can never turn this into an unbounded list.
MAX_MATERIAL_CLAIMS = 12


@dataclass(frozen=True)
class RelatedRequirement:
    """Lightweight context for a sibling requirement -- identity/label
    only, never that requirement's own full assessment/enrichment (which
    would blur this brief's single-requirement scope)."""

    req_id: str
    category: Optional[str]
    description: str

    def to_dict(self) -> dict:
        return {"req_id": self.req_id, "category": self.category, "description": self.description}


@dataclass(frozen=True)
class EvaluationContext:
    """Evaluation-criteria/response-guideline context for this requirement
    -- reuses Fast Analysis's own evaluation_criteria/response_guideline
    shapes verbatim (never re-derived or re-modeled); see
    section_analyzer._match_evaluation_criterion, the SAME matching
    function this module reuses rather than reimplementing."""

    criterion_label: Optional[str] = None
    weight: Optional[str] = None
    minimum_score: Optional[str] = None
    response_guideline: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "criterion_label": self.criterion_label, "weight": self.weight,
            "minimum_score": self.minimum_score, "response_guideline": self.response_guideline,
        }


@dataclass(frozen=True)
class ResponseConstraints:
    """Known response constraints, when available. None means genuinely
    not known -- never defaulted to a guessed value."""

    word_limit: Optional[int] = None
    section_title: Optional[str] = None
    section_guidance: Optional[str] = None

    def to_dict(self) -> dict:
        return {"word_limit": self.word_limit, "section_title": self.section_title,
                "section_guidance": self.section_guidance}


@dataclass(frozen=True)
class SectionResponseBrief:
    """Response-intelligence brief for ONE requirement (formerly named
    `SectionDraftingBrief`; that name remains as a transitional alias).
    Non-generative: requirements, evaluation intent, evidence tiers, gaps,
    contradictions, human-confirmation needs and response constraints --
    guidance for a HUMAN writer, never proposal prose. Bounded by
    construction -- every field here is either a small scalar or a small,
    already-filtered list; nothing here is the full RFP, the full
    Proposal Intelligence package, or the full Organizational Memory
    corpus."""

    organization_id: str
    bid_id: int
    requirement_id: Optional[int]
    req_id: str
    category: Optional[str]
    description: str
    is_mandatory: bool
    related_requirements: tuple = ()
    evaluation: EvaluationContext = field(default_factory=EvaluationContext)
    evidence_gap_kind: Optional[str] = None
    current_rfp_source_refs: tuple = ()
    bid_specific_evidence: dict = field(default_factory=dict)
    organizational_evidence: tuple = ()
    remaining_gaps: tuple = ()
    requires_human_confirmation_from_enrichment: bool = False
    # PI-3B: the SOURCE requirement_evidence_enrichments row's own
    # input_fingerprint (migration 017), when a persisted OM-3B enrichment
    # was actually available -- folded into the draft's own fingerprint
    # (compute_draft_input_fingerprint) as a compact, robust representation
    # of "exactly which OM-3B enrichment state this draft was built from"
    # -- belt-and-suspenders alongside the full organizational_evidence
    # content already in this brief (which the draft fingerprint also
    # hashes): if OM-3B's own contract version bumps (invalidating ITS
    # fingerprint) with the enrichment content coincidentally unchanged,
    # this field still changes, so the draft is still correctly
    # invalidated.
    source_enrichment_fingerprint: Optional[str] = None
    proposal_intelligence_findings: tuple = ()
    response_constraints: ResponseConstraints = field(default_factory=ResponseConstraints)
    contract_version: str = SECTION_DRAFTING_CONTRACT_VERSION

    def to_dict(self) -> dict:
        return {
            "organization_id": self.organization_id,
            "bid_id": self.bid_id,
            "requirement_id": self.requirement_id,
            "req_id": self.req_id,
            "category": self.category,
            "description": self.description,
            "is_mandatory": self.is_mandatory,
            "related_requirements": [r.to_dict() for r in self.related_requirements],
            "evaluation": self.evaluation.to_dict(),
            "evidence_gap_kind": self.evidence_gap_kind,
            "current_rfp_source_refs": list(self.current_rfp_source_refs),
            "bid_specific_evidence": self.bid_specific_evidence,
            "organizational_evidence": list(self.organizational_evidence),
            "remaining_gaps": list(self.remaining_gaps),
            "requires_human_confirmation_from_enrichment": self.requires_human_confirmation_from_enrichment,
            "source_enrichment_fingerprint": self.source_enrichment_fingerprint,
            "proposal_intelligence_findings": list(self.proposal_intelligence_findings),
            "response_constraints": self.response_constraints.to_dict(),
            "contract_version": self.contract_version,
        }


# Transitional alias -- the brief never drove generation after the
# proposal-generation decommission; new code should use SectionResponseBrief.
SectionDraftingBrief = SectionResponseBrief


def build_brief(
    *,
    organization_id: str,
    bid_id: int,
    requirement: dict,
    related_requirements: list[dict] = (),
    evaluation_criterion: Optional[dict] = None,
    response_guideline: Optional[dict] = None,
    evidence_state: Optional[dict] = None,
    assessment: Optional[dict] = None,
    persisted_enrichment: Optional[dict] = None,
    proposal_intelligence_findings: list[dict] = (),
    response_constraints: Optional[ResponseConstraints] = None,
    max_related_requirements: int = 5,
    max_findings: int = 5,
) -> SectionResponseBrief:
    """Pure, deterministic assembly -- takes only ALREADY-FETCHED raw
    materials (never fetches, never calls a model, never touches
    Organizational Memory). `persisted_enrichment` must be an
    ALREADY-PERSISTED requirement_evidence_enrichments row/dict (or None)
    -- this function never triggers OM-3A/OM-3B itself (instruction 6).

    `evidence_state` is a RequirementEvidenceState.to_dict()-shaped dict
    (assessment_status/evidence_strength/has_contradiction_finding/
    gap_kind), reused verbatim from evidence_strengthening.py's OM-3A
    vocabulary -- never re-derived here; only its `gap_kind` is carried
    onto the brief (`evidence_gap_kind`) as drafting-model-facing context.
    `assessment` (a proposal_requirement_assessments-shaped dict) is the
    separate source for `bid_specific_evidence`'s own
    assessment_status/evidence_strength/confidence/explanation/
    proposal_source_refs -- the two are typically consistent but kept as
    distinct parameters since a caller may have one without the other.
    """
    req_id = requirement.get("req_id") or ""

    related = tuple(
        RelatedRequirement(
            req_id=r.get("req_id") or "", category=r.get("category"),
            description=r.get("description") or "",
        )
        for r in list(related_requirements)[:max_related_requirements]
        if r.get("req_id") != req_id
    )

    evaluation = EvaluationContext(
        criterion_label=(evaluation_criterion or {}).get("criterion_label") or (evaluation_criterion or {}).get("stage"),
        weight=(evaluation_criterion or {}).get("weight"),
        minimum_score=(evaluation_criterion or {}).get("threshold") or (evaluation_criterion or {}).get("minimum_score"),
        response_guideline=response_guideline,
    )

    current_rfp_refs = tuple(requirement.get("source_refs") or [])

    bid_specific = {}
    if assessment:
        bid_specific = {
            "assessment_status": assessment.get("assessment_status"),
            "evidence_strength": assessment.get("evidence_strength"),
            "confidence": assessment.get("confidence"),
            "explanation": assessment.get("explanation"),
            "proposal_source_refs": assessment.get("proposal_source_refs") or [],
        }

    organizational_evidence = tuple((persisted_enrichment or {}).get("organizational_evidence") or [])
    remaining_gaps = tuple((persisted_enrichment or {}).get("remaining_gaps") or [])
    requires_confirmation_from_enrichment = bool(
        (persisted_enrichment or {}).get("requires_human_confirmation"))
    source_enrichment_fingerprint = (persisted_enrichment or {}).get("input_fingerprint")

    findings = tuple(
        {"finding_type": f.get("finding_type"), "severity": f.get("severity"),
         "title": f.get("title"), "message": f.get("message")}
        for f in list(proposal_intelligence_findings)[:max_findings]
    )

    return SectionResponseBrief(
        organization_id=organization_id, bid_id=bid_id,
        requirement_id=requirement.get("id"), req_id=req_id,
        category=requirement.get("category"), description=requirement.get("description") or "",
        is_mandatory=(requirement.get("category") or "").strip().lower() == "mandatory",
        related_requirements=related, evaluation=evaluation,
        evidence_gap_kind=(evidence_state or {}).get("gap_kind"),
        current_rfp_source_refs=current_rfp_refs, bid_specific_evidence=bid_specific,
        organizational_evidence=organizational_evidence, remaining_gaps=remaining_gaps,
        requires_human_confirmation_from_enrichment=requires_confirmation_from_enrichment,
        source_enrichment_fingerprint=source_enrichment_fingerprint,
        proposal_intelligence_findings=findings,
        response_constraints=response_constraints or ResponseConstraints(),
    )


# ---------------------------------------------------------------------------
# PI-3B: draft input fingerprint -- reuses the SAME canonicalization
# convention as proposal_intelligence.compute_package_digest and
# evidence_strengthening.compute_input_fingerprint (sorted-key JSON, sha256
# hex over UTF-8 bytes).
# ---------------------------------------------------------------------------

def compute_draft_input_fingerprint(brief: SectionDraftingBrief) -> str:
    """A deterministic sha256 fingerprint over exactly what
    a historical draft's output depended on (and what
    the current Response Brief contains). The brief itself is already
    PI-3A's own bounded, exhaustive statement of everything the draft can
    see -- requirement identity/text, mandatory flag, related-requirement
    context, evaluation criterion/response guideline, response
    constraints, current-bid evidence state, the requirement's own
    current-RFP source refs, the FULL persisted OM-3B enrichment content
    actually included in the brief (plus that enrichment's own
    fingerprint, belt-and-suspenders), and bounded related Proposal
    Intelligence findings -- so hashing the brief whole (minus pure
    routing/identity keys that determine the cache KEY, not the drafting
    CONTENT: organization_id/bid_id/requirement_id) is both correct and
    the simplest sufficient mechanism. `contract_version` is already a
    field on the brief and is therefore already included -- bumping
    SECTION_DRAFTING_CONTRACT_VERSION (a prompt/logic change) invalidates
    every previously computed fingerprint even when every other input is
    identical, exactly like EVIDENCE_STRENGTHENING_CONTRACT_VERSION
    already does for OM-3B."""
    payload = brief.to_dict()
    for routing_key in ("organization_id", "bid_id", "requirement_id"):
        payload.pop(routing_key, None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Evidence id registry -- the ledger this brief exposes to the drafting
# model, mirroring analyst.py's PI-2B1 P#/C# short-id ledger discipline
# (bounded, addressed only by short ids, never resend raw content).
# Deterministic: the SAME brief always produces the SAME registry, in the
# SAME order, so prompt-building and reconciliation never disagree.
# ---------------------------------------------------------------------------

def _evidence_id_registry(brief: SectionDraftingBrief) -> dict:
    """id -> {"source_kind", "label", "detail"} for every evidence item
    this brief actually makes available. An id NOT in this registry can
    never be legitimately cited -- reconciliation drops anything else."""
    registry = {}
    for i, ref in enumerate(brief.current_rfp_source_refs, start=1):
        registry[f"CE{i}"] = {
            "source_kind": SOURCE_KIND_PROCUREMENT,
            "label": ref.get("section") or ref.get("filename") or "RFP reference",
            "detail": ref,
        }
    for i, ref in enumerate(brief.bid_specific_evidence.get("proposal_source_refs") or [], start=1):
        registry[f"PE{i}"] = {
            "source_kind": SOURCE_KIND_PROPOSAL,
            "label": ref.get("section") or ref.get("filename") or "Proposal reference",
            "detail": ref,
        }
    for i, item in enumerate(brief.organizational_evidence, start=1):
        registry[f"OM{i}"] = {
            "source_kind": SOURCE_KIND_ORGANIZATIONAL_MEMORY,
            "label": item.get("title") or item.get("item_id"),
            "detail": item,
        }
    return registry


@dataclass(frozen=True)
class EvidenceItemUsed:
    """One evidence item the draft actually cites -- `evidence_id` MUST
    already exist in the brief's registry (fail-closed enforced by
    `reconcile_structured_result`); this dataclass can never be constructed
    for an invented id by this module's own public entry point."""

    evidence_id: str
    source_kind: str
    claim_type: str
    label: Optional[str] = None
    trust_class: Optional[str] = None
    note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id, "source_kind": self.source_kind,
            "claim_type": self.claim_type, "label": self.label,
            "trust_class": self.trust_class, "note": self.note,
        }


@dataclass(frozen=True)
class MaterialClaim:
    """PI-3C: a bounded claim-level support mapping -- "which evidence
    item supports THIS specific material factual claim," closing the gap
    PI-3B identified (draft-wide `evidence_items_used` answers "which
    evidence was used somewhere," not "which evidence backs this
    sentence"). Deliberately NOT sentence-level/exhaustive citation
    (instruction 7) -- a small, bounded set of the draft's MATERIAL
    claims only, each with `evidence_ids` fail-closed filtered to ids that
    actually exist in the brief's registry (see
    `_reconcile_material_claims`) and a `support_status` derived
    deterministically, never trusted verbatim from the model."""

    claim_id: str
    claim_text: str
    claim_type: str
    evidence_ids: tuple = ()
    support_status: str = SUPPORT_STATUS_UNSUPPORTED

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id, "claim_text": self.claim_text,
            "claim_type": self.claim_type, "evidence_ids": list(self.evidence_ids),
            "support_status": self.support_status,
        }


@dataclass(frozen=True)
class SectionDraftResult:
    """The structured drafting result. `draft_text` is natural-language
    prose; everything else is structured, closed-vocabulary, and
    traceable back into the brief."""

    requirement_id: Optional[int]
    req_id: str
    draft_text: str
    requirements_addressed: tuple = ()
    requirements_missing: tuple = ()
    evaluation_criteria_addressed: tuple = ()
    evidence_items_used: tuple = ()
    unsupported_or_unresolved_points: tuple = ()
    contradictions_or_caveats: tuple = ()
    human_confirmation_required: bool = True
    drafting_notes: Optional[str] = None
    word_count: Optional[int] = None
    failure_reason: Optional[str] = None
    material_claims: tuple = ()

    def to_dict(self) -> dict:
        return {
            "requirement_id": self.requirement_id, "req_id": self.req_id,
            "draft_text": self.draft_text,
            "requirements_addressed": list(self.requirements_addressed),
            "requirements_missing": list(self.requirements_missing),
            "evaluation_criteria_addressed": list(self.evaluation_criteria_addressed),
            "evidence_items_used": [e.to_dict() for e in self.evidence_items_used],
            "unsupported_or_unresolved_points": list(self.unsupported_or_unresolved_points),
            "contradictions_or_caveats": list(self.contradictions_or_caveats),
            "human_confirmation_required": self.human_confirmation_required,
            "drafting_notes": self.drafting_notes,
            "word_count": self.word_count,
            "failure_reason": self.failure_reason,
            "material_claims": [c.to_dict() for c in self.material_claims],
        }


def _coerce_str_list(value) -> tuple:
    if not isinstance(value, list):
        return ()
    return tuple(v.strip() for v in value if isinstance(v, str) and v.strip())


def reconcile_structured_result(parsed: dict, brief: SectionDraftingBrief) -> SectionDraftResult:
    """PURE, NO MODEL CALL. Retained (formerly `reconcile_structured_result`)
    as reusable claim/evidence-validation logic: given an already-structured
    payload (historical persisted draft data, or -- in future CHECK work --
    claims extracted from a HUMAN-written response), fail-closed validates
    every cited evidence id and material claim against this brief's
    registry. It never generates prose.

    Fail-closed reconciliation -- mirrors analyst._reconcile_package_
    findings/evidence_strengthening._adjudicate_candidates' discipline. An
    evidence_items_used entry citing an id outside the brief's registry, or
    an unrecognized claim_type, is DROPPED, never invented or coerced into
    the nearest value. requirements_addressed/evaluation_criteria_addressed
    are trusted as free-text labels (the model's own restatement) since
    they describe coverage, not evidence identity -- traceability is
    enforced on evidence_items_used, the field this brief's registry
    actually bounds."""
    registry = _evidence_id_registry(brief)

    evidence_items = []
    for entry in parsed.get("evidence_items_used") or []:
        if not isinstance(entry, dict):
            continue
        eid = entry.get("evidence_id")
        claim_type = entry.get("claim_type")
        if eid not in registry or claim_type not in CLAIM_TYPES:
            continue
        reg_entry = registry[eid]
        om_detail = reg_entry["detail"] if reg_entry["source_kind"] == SOURCE_KIND_ORGANIZATIONAL_MEMORY else {}
        note = entry.get("note")
        evidence_items.append(EvidenceItemUsed(
            evidence_id=eid, source_kind=reg_entry["source_kind"], claim_type=claim_type,
            label=reg_entry["label"],
            trust_class=om_detail.get("memory_class") if om_detail else None,
            note=note.strip()[:200] if isinstance(note, str) and note.strip() else None,
        ))

    word_count = parsed.get("word_count")
    word_count = word_count if isinstance(word_count, int) else None
    drafting_notes = parsed.get("drafting_notes")
    drafting_notes = drafting_notes.strip()[:200] if isinstance(drafting_notes, str) and drafting_notes.strip() else None

    material_claims = _reconcile_material_claims(parsed.get("material_claims"), registry)

    return SectionDraftResult(
        requirement_id=brief.requirement_id, req_id=brief.req_id,
        draft_text=parsed.get("draft_text") or "",
        requirements_addressed=_coerce_str_list(parsed.get("requirements_addressed")),
        requirements_missing=_coerce_str_list(parsed.get("requirements_missing")),
        evaluation_criteria_addressed=_coerce_str_list(parsed.get("evaluation_criteria_addressed")),
        evidence_items_used=tuple(evidence_items),
        unsupported_or_unresolved_points=_coerce_str_list(parsed.get("unsupported_or_unresolved_points")),
        contradictions_or_caveats=_coerce_str_list(parsed.get("contradictions_or_caveats")),
        human_confirmation_required=bool(parsed.get("human_confirmation_required")),
        drafting_notes=drafting_notes, word_count=word_count,
        material_claims=material_claims,
    )


# Evidence-source-kinds a VERIFIED_FACT claim may legitimately cite --
# current RFP/procurement evidence, current bid-specific proposal
# evidence, or APPROVED_FIRM_KNOWLEDGE (tier 3, human-approved reusable
# firm fact). SOURCE_MEMORY (lower trust, tier 4) can never by itself
# back a claim tagged VERIFIED_FACT -- exactly PI-3A's own hierarchy,
# now enforced at the individual-claim level too.
def _permits_verified_fact(entry: dict) -> bool:
    if entry["source_kind"] in (SOURCE_KIND_PROCUREMENT, SOURCE_KIND_PROPOSAL):
        return True
    if entry["source_kind"] == SOURCE_KIND_ORGANIZATIONAL_MEMORY:
        return entry["detail"].get("memory_class") == "APPROVED_FIRM_KNOWLEDGE"
    return False


def _reconcile_material_claims(raw_claims, registry: dict) -> tuple:
    """Fail-closed reconciliation for PI-3C's claim-level support mapping
    -- mirrors `reconcile_structured_result`'s evidence_items_used discipline
    exactly, plus the additional per-claim-type hierarchy rules instruction
    7 requires:

      - an unknown claim_id, non-string claim_text, or claim_type outside
        CLAIM_TYPES drops that claim entirely (never guessed);
      - `evidence_ids` is ALWAYS filtered to ids that actually exist in
        the registry first -- an invented id can never survive, exactly
        like evidence_items_used;
      - UNSUPPORTED_GAP is forced to empty evidence_ids and UNSUPPORTED
        status regardless of what the model returned -- it can never
        masquerade as supported;
      - PROPOSED_APPROACH is forced to COMMITMENT status -- a future
        commitment is never presented as verified historical support;
      - VERIFIED_FACT is further filtered to ONLY evidence ids
        `_permits_verified_fact` allows (current-RFP/proposal evidence or
        APPROVED_FIRM_KNOWLEDGE) -- a SOURCE_MEMORY-only citation is
        stripped; if that leaves zero evidence ids, the ENTIRE claim is
        downgraded to UNSUPPORTED_GAP rather than left as an
        unsupported-but-still-labeled-VERIFIED_FACT claim;
      - ORGANIZATIONAL_KNOWLEDGE keeps any registry-valid evidence id
        (SOURCE_MEMORY included -- organizational knowledge legitimately
        may rest on lower-trust material, but its trust_class is always
        readable via the evidence id's own registry entry); if filtering
        leaves zero evidence ids, it is likewise downgraded to
        UNSUPPORTED_GAP -- a claim can never keep an "evidence-backed"
        claim_type with no actual evidence.

    Bounded to MAX_MATERIAL_CLAIMS; duplicate claim_ids keep only the
    first occurrence."""
    if not isinstance(raw_claims, list):
        return ()

    claims = []
    seen_ids = set()
    for entry in raw_claims:
        if len(claims) >= MAX_MATERIAL_CLAIMS:
            break
        if not isinstance(entry, dict):
            continue
        claim_id = entry.get("claim_id")
        claim_text = entry.get("claim_text")
        claim_type = entry.get("claim_type")
        if (not isinstance(claim_id, str) or not claim_id.strip()
                or claim_id in seen_ids
                or not isinstance(claim_text, str) or not claim_text.strip()
                or claim_type not in CLAIM_TYPES):
            continue

        raw_evidence_ids = entry.get("evidence_ids")
        evidence_ids = [e for e in (raw_evidence_ids or []) if isinstance(e, str) and e in registry]

        raw_status = entry.get("support_status")

        if claim_type == CLAIM_TYPE_UNSUPPORTED_GAP:
            evidence_ids = []
            support_status = SUPPORT_STATUS_UNSUPPORTED
        elif claim_type == CLAIM_TYPE_PROPOSED_APPROACH:
            support_status = SUPPORT_STATUS_COMMITMENT
        elif claim_type == CLAIM_TYPE_VERIFIED_FACT:
            evidence_ids = [e for e in evidence_ids if _permits_verified_fact(registry[e])]
            if not evidence_ids:
                claim_type = CLAIM_TYPE_UNSUPPORTED_GAP
                support_status = SUPPORT_STATUS_UNSUPPORTED
            else:
                support_status = raw_status if raw_status in SUPPORT_STATUSES else SUPPORT_STATUS_SUPPORTED
        else:  # CLAIM_TYPE_ORGANIZATIONAL_KNOWLEDGE
            if not evidence_ids:
                claim_type = CLAIM_TYPE_UNSUPPORTED_GAP
                support_status = SUPPORT_STATUS_UNSUPPORTED
            else:
                support_status = raw_status if raw_status in SUPPORT_STATUSES else SUPPORT_STATUS_SUPPORTED

        seen_ids.add(claim_id)
        claims.append(MaterialClaim(
            claim_id=claim_id, claim_text=claim_text.strip()[:300], claim_type=claim_type,
            evidence_ids=tuple(evidence_ids), support_status=support_status,
        ))
    return tuple(claims)


# Public names for the retained, reusable claim/evidence-validation logic
# (likely CHECK building blocks).
evidence_id_registry = _evidence_id_registry
reconcile_material_claims = _reconcile_material_claims
permits_verified_fact = _permits_verified_fact


@dataclass(frozen=True)
class DraftAssuranceResult:
    passed: bool
    issues: tuple = ()

    def to_dict(self) -> dict:
        return {"passed": self.passed, "issues": list(self.issues)}


def assure_section_draft(brief: SectionDraftingBrief, result: SectionDraftResult) -> DraftAssuranceResult:
    """Bounded post-draft assurance -- ENTIRELY DETERMINISTIC, no second
    model call (instruction 9: "prefer deterministic validation where
    possible... at most one additional bounded model call IF NEEDED" --
    every check below is answerable from the brief + the drafting call's
    OWN already-structured output, so no second call is needed). This is
    NOT the full Red Team capability -- only section-level drafting
    assurance, cross-checking the draft's structured claims against what
    the brief itself actually made available."""
    issues = []

    if result.failure_reason:
        issues.append(f"drafting call failed: {result.failure_reason}")

    if brief.is_mandatory and brief.req_id not in result.requirements_addressed:
        issues.append(f"mandatory requirement {brief.req_id} not present in requirements_addressed")

    if brief.evaluation.criterion_label and not result.evaluation_criteria_addressed:
        issues.append("a known evaluation criterion exists but none was reflected in evaluation_criteria_addressed")

    registry = _evidence_id_registry(brief)
    for item in result.evidence_items_used:
        if item.evidence_id not in registry:
            issues.append(f"evidence_items_used cites an id not present in the brief: {item.evidence_id}")

    om_contradictions = [e for e in brief.organizational_evidence if e.get("relationship") == "CONTRADICTION"]
    if om_contradictions and not result.contradictions_or_caveats:
        issues.append("brief carries an Organizational Memory CONTRADICTION but the draft surfaced no caveat")

    if (brief.response_constraints.word_limit and result.word_count
            and result.word_count > int(brief.response_constraints.word_limit * 1.15)):
        issues.append(
            f"draft word_count {result.word_count} exceeds word_limit "
            f"{brief.response_constraints.word_limit} by more than 15%")

    needs_confirmation = bool(
        result.unsupported_or_unresolved_points or om_contradictions
        or brief.requires_human_confirmation_from_enrichment or result.failure_reason
        or brief.evidence_gap_kind in ("MISSING", "CONFLICTED"))
    if needs_confirmation and not result.human_confirmation_required:
        issues.append(
            "human_confirmation_required should be True given unresolved points, an OM "
            "contradiction, the persisted enrichment's own flag, or a drafting failure")

    return DraftAssuranceResult(passed=not issues, issues=tuple(issues))


__all__ = [
    "SECTION_DRAFTING_CONTRACT_VERSION",
    "CLAIM_TYPE_VERIFIED_FACT", "CLAIM_TYPE_ORGANIZATIONAL_KNOWLEDGE",
    "CLAIM_TYPE_PROPOSED_APPROACH", "CLAIM_TYPE_UNSUPPORTED_GAP", "CLAIM_TYPES",
    "SOURCE_KIND_PROCUREMENT", "SOURCE_KIND_PROPOSAL", "SOURCE_KIND_ORGANIZATIONAL_MEMORY",
    "SUPPORT_STATUS_SUPPORTED", "SUPPORT_STATUS_PARTIALLY_SUPPORTED",
    "SUPPORT_STATUS_UNSUPPORTED", "SUPPORT_STATUS_COMMITMENT", "SUPPORT_STATUSES",
    "MAX_MATERIAL_CLAIMS",
    "RelatedRequirement", "EvaluationContext", "ResponseConstraints",
    "SectionResponseBrief", "SectionDraftingBrief", "build_brief", "compute_draft_input_fingerprint",
    "evidence_id_registry", "reconcile_material_claims", "permits_verified_fact",
    "reconcile_structured_result",
    "EvidenceItemUsed", "MaterialClaim", "SectionDraftResult",
    "DraftAssuranceResult", "assure_section_draft",
]
