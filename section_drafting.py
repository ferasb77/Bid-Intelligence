"""
section_drafting.py -- PI-3A: Evidence-Aware Section Drafting.

The first bounded proposal-generation capability in Bid Intelligence. Answers
exactly one question: "can BI generate a strong proposal-section draft for
ONE requirement from its EXISTING structured intelligence -- canonical
requirement text, its Proposal Intelligence assessment, its persisted
OM-3B Organizational Memory enrichment, and Fast Analysis's evaluation-
criteria/response-guideline extraction -- without independently re-reading
the RFP, re-running analysis, or inventing unsupported claims?"

This is section-LEVEL drafting for ONE requirement, not whole-proposal
generation.

Architecture (mirrors evidence_strengthening.py/proposal_intelligence.py's
split exactly -- this module is pure, no I/O of its own; tenancy.py owns
fetching every raw material and wiring this module's functions together,
see tenancy.draft_section_for_organization):

    build_brief(...)          : deterministic assembly of a bounded
                                 SectionDraftingBrief from ALREADY-FETCHED
                                 raw materials (never fetches anything
                                 itself)
    draft_section(...)        : the ONE new bounded model call, reusing
                                 this codebase's existing structured-output
                                 infrastructure (config.get_anthropic_client
                                 /execute_messages_create, the same pattern
                                 as analyst._call_package_reasoning and
                                 evidence_strengthening._call_memory_
                                 adjudication)
    assure_section_draft(...) : bounded, ENTIRELY DETERMINISTIC post-draft
                                 assurance (no second model call -- see its
                                 docstring)

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

No independent retrieval during drafting (instruction 6): this module
NEVER calls organizational_memory.retrieve(), NEVER re-runs OM-3A/OM-3B,
NEVER re-runs Proposal Alignment, and NEVER fetches full RFP/proposal
text. `build_brief()` takes an ALREADY-PERSISTED OM-3B enrichment dict (or
None) as a plain argument -- it does not fetch or compute one. This
extends the "analyze once, persist, draft from persisted intelligence"
discipline to brief assembly itself, not merely the drafting call: a
caller that wants fresh Organizational Memory enrichment must invoke OM-3B
(tenancy.strengthen_requirement_evidence_for_organization) as its OWN,
separate, prior step -- this module is strictly a downstream consumer.

Claim discipline (instruction 5): every evidence item the drafting model
cites must reference a stable, bounded evidence id that already exists in
the brief (see `_evidence_id_registry`) -- an id the model invents, or
that isn't in the brief, is dropped by fail-closed reconciliation, never
trusted. This mirrors analyst.py's PI-2B1 P#/C# short-id ledger pattern
(`_build_package_intelligence_ledger`/`_reconcile_package_findings`) --
the same "bounded, addressed-only-by-short-IDs, never resend raw content"
discipline, applied here to a single-requirement brief instead of a
whole-package ledger.

Explicitly NOT built here (PI-3A scope, see docs/current/SYSTEM_STATE.md):
whole-proposal generation, persistence of a draft, a UI, Word export,
Ask CapOS integration, Red Team, and any new Organizational Memory
infrastructure.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

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
class SectionDraftingBrief:
    """The ONLY substantive input the drafting call receives. Bounded by
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
) -> SectionDraftingBrief:
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

    return SectionDraftingBrief(
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
    `draft_section()`'s output depends on. The brief itself is already
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
    `_reconcile_draft_response`); this dataclass can never be constructed
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
        }


_DRAFTING_SYSTEM = (
    "You are a precise, evidence-disciplined proposal writer drafting ONE response to ONE "
    "procurement requirement. Use ONLY the structured brief given below -- never assume or "
    "invent proposal content, evidence, client names, project examples, metrics, "
    "certifications, methodologies, personnel credentials, outcomes, delivery history, "
    "commitments, references, or compliance claims beyond it. For every evidence item you "
    "cite, tag it as exactly one of VERIFIED_FACT (from current-bid/procurement evidence), "
    "ORGANIZATIONAL_KNOWLEDGE (from Organizational Memory -- APPROVED_FIRM_KNOWLEDGE is "
    "reusable firm fact, SOURCE_MEMORY is lower-trust supporting material and must never be "
    "written as if it were approved company fact), PROPOSED_APPROACH (a future commitment "
    "you are proposing, not a claim of past fact), or UNSUPPORTED_GAP (evidence the brief "
    "does not actually have). Where evidence is only partial, write conservatively. Where a "
    "fact is genuinely missing, insert an explicit placeholder such as "
    "'[SME confirmation required: <what is needed>]' instead of inventing content -- a "
    "placeholder is always better than a fabricated fact. Current-bid/RFP evidence always "
    "outranks Organizational Memory; if an Organizational Memory item conflicts with current-"
    "bid evidence or the requirement, surface it as a caveat, never as support."
)


def _drafting_prompt(brief: SectionDraftingBrief, registry: dict) -> str:
    req_block = (
        f"req_id: {brief.req_id}\ncategory: {brief.category or ''} "
        f"(mandatory={brief.is_mandatory})\ndescription: {brief.description}"
    )
    related_block = "\n".join(
        f"- [{r.req_id}] {r.description}" for r in brief.related_requirements
    ) or "(none)"
    eval_block = (
        f"criterion: {brief.evaluation.criterion_label or 'unknown'} | "
        f"weight: {brief.evaluation.weight or 'unknown'} | "
        f"minimum_score: {brief.evaluation.minimum_score or 'none stated'}\n"
        f"response_guideline: {brief.evaluation.response_guideline or '(none)'}"
    )
    bid_evidence_block = (
        f"assessment_status: {brief.bid_specific_evidence.get('assessment_status') or 'unknown'} | "
        f"evidence_strength: {brief.bid_specific_evidence.get('evidence_strength') or 'unknown'} | "
        f"confidence: {brief.bid_specific_evidence.get('confidence') or 'unknown'} | "
        f"gap_kind: {brief.evidence_gap_kind or 'unknown'}\n"
        f"explanation: {brief.bid_specific_evidence.get('explanation') or '(none)'}"
    )
    registry_lines = []
    for eid, entry in registry.items():
        registry_lines.append(f"[{eid}] ({entry['source_kind']}) {entry['label']}")
        if entry["source_kind"] == SOURCE_KIND_ORGANIZATIONAL_MEMORY:
            om = entry["detail"]
            registry_lines.append(
                f"    trust_class={om.get('memory_class')} relationship={om.get('relationship')} "
                f"rationale={om.get('rationale')} caveat={om.get('caveat')}")
    registry_block = "\n".join(registry_lines) or "(no evidence available)"
    gaps_block = "\n".join(f"- {g}" for g in brief.remaining_gaps) or "(none recorded)"
    findings_block = "\n".join(
        f"- [{f.get('finding_type')}] {f.get('title')}: {f.get('message') or ''}"
        for f in brief.proposal_intelligence_findings
    ) or "(none)"
    constraints_block = (
        f"word_limit: {brief.response_constraints.word_limit or 'not set'} | "
        f"section: {brief.response_constraints.section_title or 'not set'}\n"
        f"guidance: {brief.response_constraints.section_guidance or '(none)'}"
    )

    return f"""REQUIREMENT
{req_block}

RELATED REQUIREMENTS (context only -- draft for the requirement above, not these)
{related_block}

EVALUATION CONTEXT
{eval_block}

BID-SPECIFIC EVIDENCE (tier 2 -- current bid's own already-analyzed evidence)
{bid_evidence_block}

EVIDENCE REGISTRY (cite ONLY these ids in evidence_items_used -- id in brackets)
{registry_block}

KNOWN REMAINING GAPS (from persisted Organizational Memory enrichment)
{gaps_block}

RELATED PROPOSAL INTELLIGENCE FINDINGS
{findings_block}

RESPONSE CONSTRAINTS
{constraints_block}

TASK: draft this ONE requirement's proposal response now, following every rule above.

Return ONLY valid JSON:
{{
  "draft_text": "the drafted proposal prose",
  "requirements_addressed": ["{brief.req_id}"],
  "requirements_missing": [],
  "evaluation_criteria_addressed": ["<criterion label(s) actually reflected, or empty>"],
  "evidence_items_used": [{{"evidence_id": "<id from the registry above>", "claim_type": "VERIFIED_FACT|ORGANIZATIONAL_KNOWLEDGE|PROPOSED_APPROACH|UNSUPPORTED_GAP", "note": "<=200 chars"}}],
  "unsupported_or_unresolved_points": ["<explicit gaps still open>"],
  "contradictions_or_caveats": ["<any Organizational Memory contradiction or caveat surfaced>"],
  "human_confirmation_required": true|false,
  "drafting_notes": "<=200 chars or null",
  "word_count": <integer, actual word count of draft_text>
}}"""


def _call_section_draft(prompt: str, *, bid_id: Optional[int], max_tokens: int = 2000) -> tuple:
    """The ONE new bounded model call PI-3A adds -- reuses this codebase's
    existing structured-output infrastructure exactly like
    evidence_strengthening._call_memory_adjudication /
    analyst._call_package_reasoning. workflow="section_drafting",
    operation="draft_section" -- its own telemetry bucket. Never raises
    past this function; a failure returns (None, reason)."""
    from config import get_anthropic_client, execute_messages_create

    try:
        client = get_anthropic_client()
        response = execute_messages_create(
            client, model="claude-haiku-4-5-20251001", max_tokens=max_tokens,
            system=_DRAFTING_SYSTEM, messages=[{"role": "user", "content": prompt}],
            telemetry_context={"workflow": "section_drafting", "operation": "draft_section", "bid_id": bid_id},
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
    if not isinstance(parsed, dict) or not isinstance(parsed.get("draft_text"), str) or not parsed.get("draft_text").strip():
        return None, "malformed_response"
    return parsed, None


def _coerce_str_list(value) -> tuple:
    if not isinstance(value, list):
        return ()
    return tuple(v.strip() for v in value if isinstance(v, str) and v.strip())


def _reconcile_draft_response(parsed: dict, brief: SectionDraftingBrief) -> SectionDraftResult:
    """Fail-closed reconciliation -- mirrors analyst._reconcile_package_
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
    )


def draft_section(
    *, brief: SectionDraftingBrief, draft_fn: Optional[Callable] = None,
) -> SectionDraftResult:
    """The public drafting entry point. `draft_fn` defaults to
    `_call_section_draft`; tests inject a fake returning
    `(parsed_dict_or_None, failure_reason_or_None)` -- the SAME injection
    pattern as evidence_strengthening's `adjudicate_fn`. Never calls
    Organizational Memory retrieval, never re-runs analysis -- consumes
    ONLY `brief` (instruction 6). A total API/parse failure returns a
    SectionDraftResult with empty draft_text, human_confirmation_required
    True, and `failure_reason` set -- never fabricated prose."""
    call = draft_fn or _call_section_draft
    registry = _evidence_id_registry(brief)
    prompt = _drafting_prompt(brief, registry)
    parsed, failure_reason = call(prompt, bid_id=brief.bid_id)
    # Validated uniformly here, not only inside the default _call_section_
    # draft -- an injected draft_fn (test double or future alternative
    # caller) that returns a non-None but malformed dict (no usable
    # draft_text) must still be treated as a failure, never silently
    # reconciled into an empty, unflagged "success".
    if not isinstance(parsed, dict) or not isinstance(parsed.get("draft_text"), str) or not parsed.get("draft_text").strip():
        return SectionDraftResult(
            requirement_id=brief.requirement_id, req_id=brief.req_id, draft_text="",
            human_confirmation_required=True, failure_reason=failure_reason or "malformed_response",
        )
    return _reconcile_draft_response(parsed, brief)


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
    "RelatedRequirement", "EvaluationContext", "ResponseConstraints",
    "SectionDraftingBrief", "build_brief", "compute_draft_input_fingerprint",
    "EvidenceItemUsed", "SectionDraftResult", "draft_section",
    "DraftAssuranceResult", "assure_section_draft",
]
