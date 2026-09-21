"""
proposal_outline.py -- PI-3D/PI-3D1: proposal-outline derivation and
BUILD-section intelligence rollups.

Given a bid's already-analyzed requirements (canonical `requirements`
table rows) and already-persisted structured intelligence, proposes a
BUILD-stage outline for the user to review, edit, and explicitly approve
before anything is persisted. Persistence and the approval UI live in
pages/stage_build.py, reusing the EXISTING outline_sections/
outline_section_requirements CRUD (tenancy.upsert_section_authenticated/
set_section_requirement_mapping_authenticated) -- no new table, no new
migration.

PI-3D1 replaces PI-3D's original "group by requirement category" outline
(Mandatory/Rated/Supporting/Financial -- requirement CLASSIFICATIONS, not
proposal sections) with a three-tier derivation hierarchy, in order of
authority:

  Tier 1 -- EXPLICIT_RFP_STRUCTURE: the RFP's OWN response architecture,
  read from already-persisted structured intelligence (`analysis_results.
  structured_intelligence`, built by fast_analysis_app_adapter.
  build_opportunity_intelligence -- never re-derived here). Specifically
  `evaluation.weights_by_category` (each buyer-stated response category
  heading, e.g. "Category 1 — Learning & Development (Form D1)", already
  groups its own evaluation criteria with real weights) and `response_
  requirements.checklist`/`pricing_and_commercial` for standalone forms/
  pricing components. A buyer-mandated structure is never overridden by
  a model-generated alternative.

  Tier 2 -- DETERMINISTIC_DERIVATION: when Tier 1 yields no coherent
  multi-section structure, cluster requirements by whichever evaluation
  criterion/heading they deterministically match (section_analyzer.
  _match_evaluation_criterion, reused not reimplemented) -- SOW/workstream
  and evaluation-criterion signals, never the requirement's own bare
  Mandatory/Rated/Supporting/Financial classification as the primary
  axis. Only when NO evaluation signal exists at all does this fall back
  to `derive_outline_sections`' original category-grouping (kept, not
  removed -- the correct behavior for a bid with no Fast Analysis
  evaluation intelligence yet).

  Tier 3 -- MODEL_REFINEMENT: ONE bounded model call (`_call_outline_
  refinement`, same injectable-call_fn/telemetry pattern as section_
  drafting._call_section_draft), used ONLY when Tiers 1+2 together fail
  to produce a coherent, adequately-covered structure (see
  `needs_model_refinement`). Receives ONLY bounded context (candidate
  sections, requirement/criteria SUMMARIES, submission constraints) --
  never the full raw RFP, Organizational Memory, or proposal drafts.

Every ACTIVE requirement is either mapped to a section or explicitly
classified via `classify_unresolved_requirement` (submission/form item,
commercial/pricing item, appendix/supporting item, non-response
informational item, or genuinely unresolved) -- no requirement silently
disappears (instruction 4).

Also holds `summarize_section_intelligence` -- the pure rollup the BUILD
section list/detail views use to show "N requirements / M evaluation
criteria / Evidence: Strong / K unresolved / Draft: ..." (instruction 5).
It never computes evidence/criteria matching itself -- tenancy.py builds
the per-requirement maps ONCE per bid from already-canonical reads
(section_analyzer's own deterministic evaluation-criterion matching,
proposal_intelligence's own assessment vocabulary) and this module only
rolls them up. No parallel evidence model, no parallel matching system.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

DEFAULT_WORD_LIMIT = 500
MAX_PROPOSED_SECTIONS = 20

EVIDENCE_READINESS_VALUES = ("Strong", "Moderate", "Weak", "None")
_READINESS_ORDER = {"None": 0, "Weak": 1, "Moderate": 2, "Strong": 3}

DRAFT_STATUS_VALUES = ("NOT_APPLICABLE", "NOT_GENERATED", "PARTIAL", "GENERATED")


@dataclass
class ProposedSection:
    title: str
    section_num: str
    requirement_ids: list = field(default_factory=list)
    word_limit: int = DEFAULT_WORD_LIMIT

    def to_dict(self) -> dict:
        return {
            "title": self.title, "section_num": self.section_num,
            "requirement_ids": list(self.requirement_ids), "word_limit": self.word_limit,
        }


def derive_outline_sections(requirements: list[dict]) -> list[dict]:
    """Groups ACTIVE requirements by their own `category` field into one
    proposed section per category. Categories are ordered by requirement
    count (descending -- the most substantial section first), ties broken
    alphabetically for a stable, reproducible order (the SAME requirement
    set always proposes the SAME structure). A requirement with no/blank
    category is grouped under "General" rather than silently dropped. A
    requirement with no `id` is skipped (it cannot be mapped via
    outline_section_requirements). Returns plain, JSON/session-state-safe
    dicts; never mutates `requirements`.

    Bounded to MAX_PROPOSED_SECTIONS -- a genuinely fragmented category set
    would produce an unreadable proposal regardless of what grouped it; a
    user hitting this bound should merge sections manually in the review
    UI, not be handed a 40-section wall."""
    by_category: dict[str, list[int]] = {}
    for r in requirements:
        rid = r.get("id")
        if rid is None:
            continue
        cat = (r.get("category") or "").strip() or "General"
        by_category.setdefault(cat, []).append(rid)

    ordered = sorted(by_category.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))
    ordered = ordered[:MAX_PROPOSED_SECTIONS]

    sections = []
    for i, (cat, req_ids) in enumerate(ordered, start=1):
        sections.append(ProposedSection(
            title=cat, section_num=f"{i}.0", requirement_ids=req_ids,
        ).to_dict())
    return sections


def evidence_readiness_bucket(assessment_status: str | None, evidence_strength: str | None) -> str:
    """Closed vocabulary (EVIDENCE_READINESS_VALUES), derived ONLY from
    already-persisted Proposal Intelligence fields
    (proposal_intelligence.ASSESSMENT_STATUSES / EVIDENCE_STRENGTH_VALUES)
    -- never a new scoring model. "None" means no PI-2 assessment exists
    yet for this requirement (never fabricated as "Weak" -- absence of
    evidence and WEAK evidence are different facts)."""
    if not assessment_status:
        return "None"
    if assessment_status == "Fully Addressed" and evidence_strength == "STRONG":
        return "Strong"
    if assessment_status == "Not Addressed" or evidence_strength == "WEAK":
        return "Weak"
    return "Moderate"


def weakest_readiness(buckets: list[str]) -> str:
    """Rolls up several requirements' individual readiness buckets to one
    section-level bucket -- a section is only as ready as its WEAKEST
    mapped requirement, never averaged/hidden by strong outliers. Empty
    input (no mapped requirements) rolls up to "None"."""
    valid = [b for b in buckets if b in _READINESS_ORDER]
    if not valid:
        return "None"
    return min(valid, key=lambda b: _READINESS_ORDER[b])


def summarize_section_intelligence(
    requirement_ids: list[int],
    criterion_by_req_id: dict | None = None,
    assessment_by_req_id: dict | None = None,
    draft_exists_by_req_id: dict | None = None,
) -> dict:
    """Pure rollup over ALREADY-COMPUTED per-requirement maps (matched
    evaluation criterion / PI-2 assessment / draft existence, all keyed by
    requirement `id`) -- the caller (tenancy.py) builds these maps ONCE
    per bid from existing canonical reads, never one query per requirement
    per section, and never a parallel evidence model.

    Returns {"requirement_count", "evaluation_criteria_count",
    "evidence_readiness", "unresolved_gap_count", "draft_status",
    "drafted_count"}. `draft_status` is "NOT_APPLICABLE" only when
    `requirement_ids` is empty (nothing to draft yet)."""
    criterion_by_req_id = criterion_by_req_id or {}
    assessment_by_req_id = assessment_by_req_id or {}
    draft_exists_by_req_id = draft_exists_by_req_id or {}

    readiness_buckets = []
    distinct_criteria = set()
    unresolved_gap_count = 0
    drafted_count = 0
    for rid in requirement_ids:
        crit = criterion_by_req_id.get(rid)
        if crit:
            label = crit.get("criterion_label") or crit.get("stage")
            if label:
                distinct_criteria.add(label)

        assessment = assessment_by_req_id.get(rid) or {}
        status = assessment.get("assessment_status")
        strength = assessment.get("evidence_strength")
        bucket = evidence_readiness_bucket(status, strength)
        readiness_buckets.append(bucket)
        if status in ("Partially Addressed", "Not Addressed", "Cannot Assess") or bucket in ("Weak", "None"):
            unresolved_gap_count += 1

        if draft_exists_by_req_id.get(rid):
            drafted_count += 1

    total = len(requirement_ids)
    if total == 0:
        draft_status = "NOT_APPLICABLE"
    elif drafted_count == 0:
        draft_status = "NOT_GENERATED"
    elif drafted_count == total:
        draft_status = "GENERATED"
    else:
        draft_status = "PARTIAL"

    return {
        "requirement_count": total,
        "evaluation_criteria_count": len(distinct_criteria),
        "evidence_readiness": weakest_readiness(readiness_buckets),
        "unresolved_gap_count": unresolved_gap_count,
        "draft_status": draft_status,
        "drafted_count": drafted_count,
    }


# ═══════════════════════════════════════════════════════════════════════════
# PI-3D1: Intelligent Proposal Outline Architecture
# ═══════════════════════════════════════════════════════════════════════════

DERIVATION_EXPLICIT_RFP_STRUCTURE = "EXPLICIT_RFP_STRUCTURE"
DERIVATION_DETERMINISTIC = "DETERMINISTIC_DERIVATION"
DERIVATION_MODEL_REFINEMENT = "MODEL_REFINEMENT"
DERIVATION_METHODS = (DERIVATION_EXPLICIT_RFP_STRUCTURE, DERIVATION_DETERMINISTIC, DERIVATION_MODEL_REFINEMENT)

# UI-facing labels -- instruction 3: "do not expose technical enum names
# directly in the UI unless appropriate."
DERIVATION_METHOD_LABELS = {
    DERIVATION_EXPLICIT_RFP_STRUCTURE: "From the RFP's own response structure",
    DERIVATION_DETERMINISTIC: "Derived from requirement & evaluation intelligence",
    DERIVATION_MODEL_REFINEMENT: "AI-refined architecture",
}

UNRESOLVED_SUBMISSION_FORM = "SUBMISSION_FORM_REQUIREMENT"
UNRESOLVED_COMMERCIAL_ITEM = "COMMERCIAL_RESPONSE_ITEM"
UNRESOLVED_APPENDIX_ITEM = "APPENDIX_SUPPORTING_ITEM"
UNRESOLVED_INFORMATIONAL = "NON_RESPONSE_INFORMATIONAL"
UNRESOLVED_NEEDS_DECISION = "UNRESOLVED"
UNRESOLVED_CLASSIFICATIONS = (
    UNRESOLVED_SUBMISSION_FORM, UNRESOLVED_COMMERCIAL_ITEM, UNRESOLVED_APPENDIX_ITEM,
    UNRESOLVED_INFORMATIONAL, UNRESOLVED_NEEDS_DECISION,
)
UNRESOLVED_LABELS = {
    UNRESOLVED_SUBMISSION_FORM: "Submission / form requirement",
    UNRESOLVED_COMMERCIAL_ITEM: "Commercial / pricing response item",
    UNRESOLVED_APPENDIX_ITEM: "Appendix / supporting item",
    UNRESOLVED_INFORMATIONAL: "Informational (no proposal response needed)",
    UNRESOLVED_NEEDS_DECISION: "Unresolved — requires your decision",
}

_UNCATEGORIZED_LABELS = {"", "uncategorized", "general", "none", "n/a"}
_FORM_KEYWORDS = ("form", "declaration", "certification", "questionnaire", "agreement", "appendix")
_PRICING_KEYWORDS = ("pricing", "price", "cost", "fee", "rate", "commercial")
_INFORMATIONAL_KEYWORDS = ("for information only", "informational purposes", "no response required")


def _contains_keyword(text: str, keywords: tuple) -> bool:
    """Word-boundary keyword match -- plain substring `in` checks false-
    positive badly on short keywords (e.g. "rate" inside "corpoRATE",
    "form" inside "INFORMation"); this never does."""
    return any(re.search(r'\b' + re.escape(k) + r'\b', text) for k in keywords)


def _match_requirement_to_occurrence(requirement: dict, occurrences: list[dict]) -> dict | None:
    """Reuses section_analyzer's OWN deterministic word-overlap matcher
    (imported, never reimplemented -- "do not create a parallel RFP
    interpretation model") against whichever evaluation-occurrence list
    the caller has available: structured_intelligence's `evaluation.
    raw_occurrences` (each already carries `criterion_label`/
    `category_scope`/`parent_heading`) or the advisory raw snapshot's own
    `evaluation_criteria` (`criterion_label` or `stage`) -- the matcher
    itself only ever reads `criterion_label`, so both shapes work
    unmodified. Lazy import (module-level, call-time) keeps this module's
    own import surface minimal, matching tenancy.py's own established
    convention for the same dependency."""
    if not occurrences:
        return None
    import section_analyzer as sa
    return sa._match_evaluation_criterion(requirement, occurrences)


def _sum_parseable_points(weights: list) -> int | None:
    """Sums whatever "N points" values parse out of a list of raw weight
    strings (e.g. "35 points", "5%", "PASS / FAIL") -- returns None (never
    0) when nothing in the list is a parseable point value, so a caller
    can tell "no weights stated" apart from "weights summed to zero"."""
    total = 0
    found = False
    for w in weights or []:
        if not isinstance(w, str):
            continue
        m = re.match(r'\s*(\d+(?:\.\d+)?)\s*points?\b', w, re.IGNORECASE)
        if m:
            total += float(m.group(1))
            found = True
    return int(total) if found else None


def _clean_category_title(label: str) -> str:
    """Strips a redundant leading "Category N — "/"Category N -- " prefix
    (the section's own ordinal already conveys that) while keeping the
    buyer's own wording otherwise completely verbatim -- never invents or
    rephrases a title the RFP itself did not use."""
    return re.sub(r'^\s*Category\s+\d+\s*[—–-]\s*', '', label or '').strip() or label


def extract_explicit_sections_from_structured_intelligence(
    structured_intelligence: dict | None, requirements: list[dict],
) -> list[dict]:
    """Tier 1. Reads ONLY already-persisted structured intelligence
    (`analysis_results.structured_intelligence`, built by
    fast_analysis_app_adapter.build_opportunity_intelligence -- never
    re-run, never re-derived). `evaluation.weights_by_category` is the
    RFP's OWN evaluation table already grouped under its own response-
    category headings (e.g. "Category 1 — Learning & Development (Form
    D1)") -- reading it verbatim, rather than re-clustering
    `raw_occurrences` ourselves, means this Tier can never disagree with
    the buyer's own stated grouping. A category with no rows, or the
    generic "Uncategorized" bucket procurement_intelligence itself uses
    for an unmatched occurrence, is skipped -- never presented as a real
    buyer-defined section.

    Each requirement is mapped INLINE here (not in a separate post-hoc
    pass) via `_match_requirement_to_occurrence` against `evaluation.
    raw_occurrences`, so a requirement only ever lands in the section
    whose criteria it was actually matched to.

    Returns [] (a real, meaningful "Tier 1 produced nothing") when
    `weights_by_category` is absent/empty -- the caller falls through to
    Tier 2, never fabricates a category."""
    structured_intelligence = structured_intelligence or {}
    evaluation = structured_intelligence.get("evaluation") or {}
    weights_by_category = evaluation.get("weights_by_category") or {}
    raw_occurrences = evaluation.get("raw_occurrences") or []

    sections = []
    for label, rows in weights_by_category.items():
        if not label or label.strip().lower() in _UNCATEGORIZED_LABELS:
            continue
        if not isinstance(rows, list) or not rows:
            continue
        criteria_labels = sorted({r.get("criterion") for r in rows if isinstance(r, dict) and r.get("criterion")})
        if not criteria_labels:
            continue
        total_weight = _sum_parseable_points([r.get("weight") for r in rows if isinstance(r, dict)])
        criteria_weights = {
            r["criterion"]: pts for r in rows if isinstance(r, dict) and r.get("criterion")
            for pts in [_sum_parseable_points([r.get("weight")])] if pts is not None
        }

        mapped_ids = []
        for r in requirements:
            rid = r.get("id")
            if rid is None:
                continue
            match = _match_requirement_to_occurrence(r, raw_occurrences)
            if match and match.get("criterion_label") in criteria_labels:
                mapped_ids.append(rid)

        sections.append({
            "title": _clean_category_title(label),
            "source_basis": DERIVATION_EXPLICIT_RFP_STRUCTURE,
            "purpose": f"Buyer-defined response category: {label}.",
            "criteria_labels": criteria_labels,
            "mapped_evaluation_criteria": criteria_labels,
            "criteria_weights": criteria_weights,
            "mapped_requirement_ids": mapped_ids,
            "response_constraints": {"total_weight_points": total_weight},
            "rationale": (
                f"Reflects the RFP's own evaluation table grouping "
                f"({len(criteria_labels)} criteria"
                + (f", {total_weight} points" if total_weight is not None else "")
                + ")."
            ),
        })
    return sections


def extract_pricing_section(structured_intelligence: dict | None, requirements: list[dict]) -> dict | None:
    """Tier 1 (standalone). Surfaces a dedicated Pricing/commercial
    section when `pricing_and_commercial` has real content -- the RFP's
    own pricing evaluation is typically staged/scored separately from its
    technical categories (see `evaluation.stages`), so it deserves its
    own response section rather than being folded into whichever
    technical category happens to also mention "Price". Requirements are
    mapped via the SAME occurrence matcher, plus a keyword fallback for a
    requirement whose own category is "Financial" but that matched no
    evaluation occurrence at all (a financial requirement must never be
    silently dropped -- instruction 10: "financial requirement routed
    appropriately"). Returns None when there is no pricing/commercial
    content at all."""
    structured_intelligence = structured_intelligence or {}
    pricing = structured_intelligence.get("pricing_and_commercial") or {}
    points = pricing.get("points") or []
    raw_occ = pricing.get("raw_pricing_occurrences") or []
    if not points and not raw_occ:
        return None

    evaluation = structured_intelligence.get("evaluation") or {}
    raw_occurrences = evaluation.get("raw_occurrences") or []
    price_criteria_labels = sorted({
        o.get("criterion_label") for o in raw_occurrences
        if isinstance(o, dict) and o.get("criterion_label")
        and _contains_keyword(o["criterion_label"].lower(), _PRICING_KEYWORDS)
    })

    mapped_ids = []
    for r in requirements:
        rid = r.get("id")
        if rid is None:
            continue
        match = _match_requirement_to_occurrence(r, raw_occurrences) if raw_occurrences else None
        if match and match.get("criterion_label") in price_criteria_labels:
            mapped_ids.append(rid)
        elif (r.get("category") or "").strip().lower() == "financial":
            mapped_ids.append(rid)

    return {
        "title": "Pricing",
        "source_basis": DERIVATION_EXPLICIT_RFP_STRUCTURE,
        "purpose": "Commercial/pricing response, evaluated and submitted separately from the technical response.",
        "criteria_labels": price_criteria_labels,
        "mapped_evaluation_criteria": price_criteria_labels,
        "mapped_requirement_ids": sorted(set(mapped_ids)),
        "response_constraints": {},
        "rationale": "The RFP's own pricing/commercial structure is distinct from its technical evaluation categories.",
    }


def extract_submission_form_section(structured_intelligence: dict | None) -> dict | None:
    """Tier 1 (standalone). Surfaces the RFP's own required-forms/
    appendices checklist (`response_requirements.checklist`) as its own
    section when at least one item looks like a standalone submittable
    form/declaration/appendix (never a re-derivation of the checklist
    itself -- reads it verbatim). These items are procedural submission
    documents, not technical content a `requirements` row maps to one-
    for-one, so this section carries `checklist_items` instead of
    `mapped_requirement_ids` (left empty; the checklist IS the content).
    Returns None when the checklist has no standalone-form-shaped item."""
    checklist = ((structured_intelligence or {}).get("response_requirements") or {}).get("checklist") or []
    form_items = [
        c for c in checklist
        if isinstance(c, dict)
        and _contains_keyword(f"{c.get('item','')} {c.get('description','')}".lower(), _FORM_KEYWORDS)
    ]
    if not form_items:
        return None
    return {
        "title": "Required Forms & Submission Documents",
        "source_basis": DERIVATION_EXPLICIT_RFP_STRUCTURE,
        "purpose": "Mandatory forms, declarations, and submission documents the RFP requires as part of the response package.",
        "criteria_labels": [],
        "mapped_evaluation_criteria": [],
        "mapped_requirement_ids": [],
        "checklist_items": [
            {"item": c.get("item"), "description": c.get("description"), "notes": c.get("notes")}
            for c in form_items
        ],
        "response_constraints": {},
        "rationale": f"{len(form_items)} explicit submission form/appendix item(s) from the RFP's own response-requirements checklist.",
    }


def extract_mandatory_requirements_section(
    structured_intelligence: dict | None, requirements: list[dict], already_mapped_ids: set,
) -> dict | None:
    """Tier 1 (standalone). The RFP's own evaluation process (`evaluation.
    stages`) typically separates PASS/FAIL mandatory submission/
    qualification gates from the SCORED rated-criteria table -- a
    Mandatory-category requirement that did not match any rated criterion
    is, by that same explicit process structure, a mandatory gate item
    (a confirmation, a form field, a qualification threshold), not an
    orphan. Grouping them into their own section reflects the RFP's own
    documented staged process rather than inventing a new category.

    Returns None when there are no such requirements left to claim, or
    when the RFP's own `evaluation.stages` signal has no pass/fail-basis
    stage at all -- in that case this section's own justification (an
    explicit staged process) does not hold, and Tier 2/`unresolved`
    classification handles those requirements instead."""
    stages = ((structured_intelligence or {}).get("evaluation") or {}).get("stages") or []
    has_gate_stage = any(isinstance(s, dict) and "pass" in (s.get("basis") or "").lower() for s in stages)
    if not has_gate_stage:
        return None
    mapped_ids = sorted(
        r["id"] for r in requirements
        if r.get("id") is not None and r["id"] not in already_mapped_ids
        and (r.get("category") or "").strip().lower() == "mandatory"
    )
    if not mapped_ids:
        return None
    return {
        "title": "Mandatory Submission Requirements & Qualifications",
        "source_basis": DERIVATION_EXPLICIT_RFP_STRUCTURE,
        "purpose": "Pass/fail mandatory submission and qualification gates the RFP's own evaluation process requires before scoring begins.",
        "criteria_labels": [],
        "mapped_evaluation_criteria": [],
        "mapped_requirement_ids": mapped_ids,
        "response_constraints": {},
        "rationale": f"{len(mapped_ids)} mandatory requirement(s) matching the RFP's own documented pass/fail submission-gate stage(s).",
    }


def _derive_tier2_sections(requirements: list[dict], occurrences: list[dict]) -> list[dict]:
    """Tier 2. When Tier 1 (the buyer's own explicit response-category
    grouping) produced nothing, cluster requirements by whichever
    evaluation criterion/heading they deterministically match -- a
    genuine structural signal, never the bare Mandatory/Rated/Supporting/
    Financial classification (instruction: "do not simply group by
    Mandatory/Rated/Supporting"). Only when there is no evaluation signal
    at all (no `occurrences`) does this fall back to
    `derive_outline_sections`' original category grouping -- kept, not
    removed, since it is still the correct behavior for a bid with no
    Fast Analysis evaluation intelligence yet."""
    if occurrences:
        clusters: dict[str, list[int]] = {}
        order: list[str] = []
        for r in requirements:
            rid = r.get("id")
            if rid is None:
                continue
            match = _match_requirement_to_occurrence(r, occurrences)
            if not match:
                continue
            key = match.get("parent_heading") or match.get("criterion_label")
            if not key:
                continue
            if key not in clusters:
                clusters[key] = []
                order.append(key)
            clusters[key].append(rid)
        if len(order) >= 2:
            return [
                {
                    "title": key,
                    "source_basis": DERIVATION_DETERMINISTIC,
                    "purpose": f'Groups requirements matched to the evaluation criterion/heading "{key}".',
                    "criteria_labels": [key],
                    "mapped_evaluation_criteria": [key],
                    "mapped_requirement_ids": clusters[key],
                    "response_constraints": {},
                    "rationale": f"{len(clusters[key])} requirement(s) deterministically matched to this criterion/heading.",
                }
                for key in order
            ]

    base = derive_outline_sections(requirements)
    for sec in base:
        sec["source_basis"] = DERIVATION_DETERMINISTIC
        sec["purpose"] = f'Groups requirements sharing the classification "{sec["title"]}".'
        sec["criteria_labels"] = []
        sec["mapped_evaluation_criteria"] = []
        sec["response_constraints"] = {"word_limit": sec.get("word_limit")}
        sec["rationale"] = (
            "Fallback grouping by requirement classification -- no explicit RFP response "
            "structure or evaluation-criterion signal was available for this bid."
        )
    return base


def classify_unresolved_requirement(requirement: dict) -> str:
    """Closed-vocabulary classification (UNRESOLVED_CLASSIFICATIONS) for a
    requirement that no outline section claimed -- so it is never simply
    dropped (instruction 4). Uses only the requirement's own `category`/
    `description` fields, never invents a classification the requirement
    doesn't support; the generic, unclassifiable case is
    UNRESOLVED_NEEDS_DECISION, never guessed toward a more specific one."""
    category = (requirement.get("category") or "").strip().lower()
    desc = (requirement.get("description") or "").lower()

    if _contains_keyword(desc, _INFORMATIONAL_KEYWORDS):
        return UNRESOLVED_INFORMATIONAL
    if category == "financial" or _contains_keyword(desc, _PRICING_KEYWORDS):
        return UNRESOLVED_COMMERCIAL_ITEM
    if _contains_keyword(desc, _FORM_KEYWORDS):
        return UNRESOLVED_SUBMISSION_FORM
    if category == "supporting":
        return UNRESOLVED_APPENDIX_ITEM
    return UNRESOLVED_NEEDS_DECISION


def _coverage_summary(requirements: list[dict], sections: list[dict], unresolved: list[dict]) -> dict:
    """Pure rollup (instruction 4): mapped/orphaned/unresolved counts, and
    whether the outline can be marked "ready" -- never while an orphaned
    MANDATORY requirement remains unresolved."""
    total = sum(1 for r in requirements if r.get("id") is not None)
    mapped_ids = {rid for sec in sections for rid in (sec.get("mapped_requirement_ids") or [])}
    mapped_count = len(mapped_ids)
    unresolved_by_id = {u["requirement_id"]: u["classification"] for u in unresolved}
    orphaned_mandatory = [
        r.get("id") for r in requirements
        if r.get("id") in unresolved_by_id
        and (r.get("category") or "").strip().lower() == "mandatory"
        and unresolved_by_id[r["id"]] == UNRESOLVED_NEEDS_DECISION
    ]
    return {
        "total_requirement_count": total,
        "mapped_requirement_count": mapped_count,
        "orphaned_requirement_count": len(unresolved),
        "unresolved_mapping_count": sum(1 for c in unresolved_by_id.values() if c == UNRESOLVED_NEEDS_DECISION),
        "orphaned_mandatory_count": len(orphaned_mandatory),
        "orphaned_mandatory_requirement_ids": orphaned_mandatory,
        "is_ready": len(orphaned_mandatory) == 0,
    }


def needs_model_refinement(sections: list[dict], coverage: dict) -> bool:
    """Tier 3 gate (instruction 2/12): a bounded model call is warranted
    ONLY when deterministic derivation (Tiers 1+2) failed to produce a
    coherent, adequately-covered structure -- never merely because a
    model call is available. With zero active requirements there is
    nothing to structure, so refinement is never needed regardless of
    section count. Otherwise "insufficient" means: fewer than 2 sections
    total, OR fewer than half of active requirements ended up mapped to
    any section."""
    total = coverage.get("total_requirement_count") or 0
    if total == 0:
        return False
    if len(sections) < 2:
        return True
    return coverage.get("mapped_requirement_count", 0) < (total / 2)


def derive_intelligent_outline(
    requirements: list[dict],
    structured_intelligence: dict | None = None,
    raw_evaluation_criteria: list[dict] | None = None,
) -> dict:
    """The PI-3D1 orchestrator -- deterministic only (Tiers 1+2); the
    caller (tenancy.py) invokes Tier 3's bounded model call separately,
    only when `needs_model_refinement` says so, since that is the one
    part of this pipeline that is not pure/I-O-free.

    `structured_intelligence` is `analysis_results.structured_
    intelligence` (Tier 1's primary source). `raw_evaluation_criteria` is
    the advisory raw snapshot's own `evaluation_criteria` list (section_
    analyzer.procurement_basis), used as a Tier-2 matching signal ONLY
    when structured_intelligence's own `evaluation.raw_occurrences` is
    empty -- the two are never merged (no policy either source implies
    exists for reconciling them).

    Returns {"sections", "unresolved", "coverage", "derivation_method",
    "needs_model_refinement"}. Every active requirement (an `id` is set)
    is accounted for exactly once, either inside some section's
    `mapped_requirement_ids` or inside `unresolved`."""
    structured_intelligence = structured_intelligence or {}
    evaluation = structured_intelligence.get("evaluation") or {}
    raw_occurrences = evaluation.get("raw_occurrences") or []
    occurrences_for_tier2 = raw_occurrences or (raw_evaluation_criteria or [])

    explicit_sections = extract_explicit_sections_from_structured_intelligence(
        structured_intelligence, requirements)
    pricing_section = extract_pricing_section(structured_intelligence, requirements)
    forms_section = extract_submission_form_section(structured_intelligence)

    if explicit_sections:
        derivation_method = DERIVATION_EXPLICIT_RFP_STRUCTURE
        sections = list(explicit_sections)
    else:
        derivation_method = DERIVATION_DETERMINISTIC
        sections = _derive_tier2_sections(requirements, occurrences_for_tier2)

    if pricing_section:
        sections.append(pricing_section)
    if forms_section:
        sections.append(forms_section)

    already_mapped_ids = {rid for sec in sections for rid in (sec.get("mapped_requirement_ids") or [])}
    mandatory_section = extract_mandatory_requirements_section(
        structured_intelligence, requirements, already_mapped_ids)
    if mandatory_section:
        sections.append(mandatory_section)

    for i, sec in enumerate(sections, start=1):
        sec.setdefault("section_num", f"{i}.0")
        sec["section_num"] = f"{i}.0"
        sec.setdefault("word_limit", DEFAULT_WORD_LIMIT)
        sec["derivation_method"] = sec.get("source_basis", derivation_method)

    already_mapped_ids = {rid for sec in sections for rid in (sec.get("mapped_requirement_ids") or [])}
    unresolved = []
    for r in requirements:
        rid = r.get("id")
        if rid is None or rid in already_mapped_ids:
            continue
        unresolved.append({
            "requirement_id": rid, "req_id": r.get("req_id"),
            "classification": classify_unresolved_requirement(r),
        })

    coverage = _coverage_summary(requirements, sections, unresolved)

    return {
        "sections": sections,
        "unresolved": unresolved,
        "coverage": coverage,
        "derivation_method": derivation_method,
        "needs_model_refinement": needs_model_refinement(sections, coverage),
    }


# ── Tier 3: ONE bounded model call (used only when Tiers 1+2 are insufficient) ──

_OUTLINE_REFINEMENT_SYSTEM = (
    "You are a proposal architect. You are given a CANDIDATE proposal outline "
    "(deterministically derived), a list of requirement summaries, evaluation "
    "criteria, and submission constraints for ONE procurement. Your job is to "
    "propose a coherent, submission-ready proposal section structure. "
    "Prefer the candidate structure where it is already coherent -- only "
    "reorganize where it genuinely improves clarity (e.g. merging near-"
    "duplicate sections, splitting an overloaded one, renaming a vague "
    "section title). Never invent a requirement, evaluation criterion, "
    "weight, or submission rule not present in your input. Never propose a "
    "generic consulting template (Executive Summary / Methodology / Team / "
    "Experience) unless the input evidence actually supports it for THIS "
    "procurement. Return ONLY valid JSON: "
    '{"sections": [{"title": str, "rationale": str, "requirement_ids": [int, ...]}]}'
)


def build_outline_refinement_prompt(
    candidate_sections: list[dict], requirements: list[dict],
    evaluation_summary: list[dict] | None = None, submission_constraints: dict | None = None,
) -> str:
    """Builds the ONE bounded prompt Tier 3 sends -- requirement
    summaries (id/req_id/category/description, already bounded to this
    bid's own active requirements), the Tier-1/2 candidate sections
    (title/rationale/mapped ids), evaluation criteria SUMMARIES (label/
    weight/category), and submission constraints (e.g. page limits) only.
    Deliberately excludes: the raw RFP text, Organizational Memory, any
    proposal draft, or any other bid's data -- instruction 2/12."""
    req_lines = "\n".join(
        f'- id={r.get("id")} [{r.get("req_id","—")}] ({r.get("category","")}) {(r.get("description") or "")[:200]}'
        for r in requirements if r.get("id") is not None
    )
    section_lines = "\n".join(
        f'- "{s.get("title")}" ({s.get("source_basis")}) -- {len(s.get("mapped_requirement_ids") or [])} requirements -- {s.get("rationale","")}'
        for s in candidate_sections
    )
    eval_lines = "\n".join(
        f'- {e.get("criterion_label") or e.get("label","")}: {e.get("weight","")} ({e.get("category_scope") or e.get("category","")})'
        for e in (evaluation_summary or [])
    )
    constraints_line = ", ".join(f"{k}={v}" for k, v in (submission_constraints or {}).items() if v) or "none stated"

    return (
        f"CANDIDATE OUTLINE (deterministic, Tier 1/2):\n{section_lines or '(none)'}\n\n"
        f"REQUIREMENTS ({sum(1 for r in requirements if r.get('id') is not None)} active):\n{req_lines or '(none)'}\n\n"
        f"EVALUATION CRITERIA:\n{eval_lines or '(none)'}\n\n"
        f"SUBMISSION CONSTRAINTS: {constraints_line}\n\n"
        "Propose the final proposal section structure as JSON."
    )


def _call_outline_refinement(prompt: str, *, bid_id: int | None, max_tokens: int = 1500) -> tuple:
    """The ONE new bounded Tier-3 model call -- reuses this codebase's
    existing structured-output infrastructure exactly like section_
    drafting._call_section_draft/evidence_strengthening._call_memory_
    adjudication. workflow="proposal_outline", operation="refine_outline"
    -- its own telemetry bucket. Never raises past this function; a
    failure returns (None, reason)."""
    from config import get_anthropic_client, execute_messages_create

    try:
        client = get_anthropic_client()
        response = execute_messages_create(
            client, model="claude-haiku-4-5-20251001", max_tokens=max_tokens,
            system=_OUTLINE_REFINEMENT_SYSTEM, messages=[{"role": "user", "content": prompt}],
            telemetry_context={"workflow": "proposal_outline", "operation": "refine_outline", "bid_id": bid_id},
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
    if not isinstance(parsed, dict) or not isinstance(parsed.get("sections"), list) or not parsed["sections"]:
        return None, "malformed_response"
    return parsed, None


def reconcile_model_refined_sections(parsed: dict, requirements: list[dict]) -> list[dict]:
    """Fail-closed reconciliation (mirrors section_drafting._reconcile_
    draft_response's discipline): a `requirement_ids` entry citing an id
    outside this bid's own active requirement set is DROPPED, never
    trusted -- the model never gets to invent a requirement mapping. A
    section with an empty/missing title is dropped entirely. Never
    raises on malformed input; degrades to an empty list."""
    valid_ids = {r["id"] for r in requirements if r.get("id") is not None}
    sections = []
    for i, raw_sec in enumerate((parsed or {}).get("sections") or [], start=1):
        if not isinstance(raw_sec, dict):
            continue
        title = (raw_sec.get("title") or "").strip()
        if not title:
            continue
        req_ids = [rid for rid in (raw_sec.get("requirement_ids") or []) if rid in valid_ids]
        sections.append({
            "title": title,
            "section_num": f"{i}.0",
            "source_basis": DERIVATION_MODEL_REFINEMENT,
            "derivation_method": DERIVATION_MODEL_REFINEMENT,
            "purpose": (raw_sec.get("rationale") or "").strip() or "AI-refined proposal section.",
            "criteria_labels": [],
            "mapped_evaluation_criteria": [],
            "mapped_requirement_ids": sorted(set(req_ids)),
            "response_constraints": {},
            "word_limit": DEFAULT_WORD_LIMIT,
            "rationale": (raw_sec.get("rationale") or "").strip(),
        })
    return sections


def refine_outline_with_model(
    candidate_sections: list[dict], requirements: list[dict],
    evaluation_summary: list[dict] | None = None, submission_constraints: dict | None = None,
    *, bid_id: int | None = None, call_fn=None,
) -> dict:
    """Public Tier-3 entry point (mirrors section_drafting.draft_section
    being the public wrapper around its own private `_call_section_draft`
    call+reconcile pair) -- builds the ONE bounded prompt, makes the
    model call (or uses the caller-injected `call_fn` for tests, the same
    `draft_fn`-style seam PI-3A established), and fail-closed reconciles
    the result via `reconcile_model_refined_sections`.

    Returns {"sections", "unresolved", "coverage", "failure_reason"} --
    on any failure (API error, parse error, malformed/empty response,
    everything dropped by reconciliation), `sections` is None and
    `failure_reason` names why; the caller keeps its own prior
    deterministic Tier 1/2 result untouched in that case, never a partial
    or corrupted structure."""
    prompt = build_outline_refinement_prompt(
        candidate_sections, requirements, evaluation_summary, submission_constraints)
    call = call_fn or _call_outline_refinement
    parsed, failure = call(prompt, bid_id=bid_id)
    if parsed is None:
        return {"sections": None, "unresolved": None, "coverage": None, "failure_reason": failure}

    refined = reconcile_model_refined_sections(parsed, requirements)
    if not refined:
        return {"sections": None, "unresolved": None, "coverage": None, "failure_reason": "empty_after_reconciliation"}

    already_mapped_ids = {rid for s in refined for rid in (s.get("mapped_requirement_ids") or [])}
    unresolved = []
    for r in requirements:
        rid = r.get("id")
        if rid is None or rid in already_mapped_ids:
            continue
        unresolved.append({
            "requirement_id": rid, "req_id": r.get("req_id"),
            "classification": classify_unresolved_requirement(r),
        })
    coverage = _coverage_summary(requirements, refined, unresolved)
    return {"sections": refined, "unresolved": unresolved, "coverage": coverage, "failure_reason": None}


# ── Evaluation coverage (instruction 5) ───────────────────────────────────

HIGH_WEIGHT_POINTS_THRESHOLD = 20
_DILUTION_CRITERIA_COUNT = 3


def evaluation_criteria_coverage(sections: list[dict], all_criteria_labels: list[str] | None = None) -> dict:
    """Instruction 5: which section(s) contribute to each criterion, and
    which criteria (if any) have no corresponding response section at
    all. `all_criteria_labels` -- the full set the RFP actually defines
    (e.g. every `criterion` across `evaluation.weights_by_category`) --
    is optional; when omitted, only the criteria already attached to
    `sections` are considered (every one of those is, by construction,
    covered)."""
    covered: dict[str, list[str]] = {}
    for sec in sections:
        for label in sec.get("mapped_evaluation_criteria") or []:
            covered.setdefault(label, []).append(sec.get("title", ""))
    all_labels = set(all_criteria_labels or []) | set(covered.keys())
    uncovered = sorted(all_labels - set(covered.keys()))
    return {"covered": covered, "uncovered_criteria": uncovered}


def surface_high_weight_structural_warnings(
    sections: list[dict], weight_threshold: int = HIGH_WEIGHT_POINTS_THRESHOLD,
) -> list[dict]:
    """Instruction 5: "if a heavily weighted criterion is buried inside
    an unrelated section, surface that as a structural warning rather
    than silently accepting it." Uses ONLY weight numbers already present
    in the RFP's own data (`criteria_weights`, built from `evaluation.
    weights_by_category`'s own weight strings) -- never invents or infers
    a weight the RFP itself did not state. A criterion is flagged as
    "diluted" when its own weight meets `weight_threshold` points but it
    shares a section with `_DILUTION_CRITERIA_COUNT` or more OTHER
    criteria -- high individual importance, low structural prominence.
    Returns [] when no section carries per-criterion weight data at all
    (nothing to evaluate, never a fabricated warning)."""
    warnings = []
    for sec in sections:
        weights = sec.get("criteria_weights") or {}
        if len(weights) < _DILUTION_CRITERIA_COUNT:
            continue
        for label, points in weights.items():
            if points is not None and points >= weight_threshold:
                warnings.append({
                    "criterion_label": label, "weight_points": points,
                    "section_title": sec.get("title"),
                    "sibling_criteria_count": len(weights) - 1,
                    "message": (
                        f'"{label}" ({points} points) shares "{sec.get("title")}" with '
                        f'{len(weights) - 1} other criteria -- consider whether it needs more '
                        f'structural prominence given its weight.'
                    ),
                })
    return warnings
