"""
proposal_outline.py -- PI-3D: deterministic proposal-outline derivation and
BUILD-section intelligence rollups.

Pure domain module (no I/O, no Anthropic call -- same posture as
evidence_strengthening.py/section_drafting.py): given a bid's already-
analyzed requirements (canonical `requirements` table rows, already the
same grouping BUILD's own requirement picker displays as
"[req_id] (category) description"), proposes a grouped BUILD-stage outline
-- one section per requirement category -- for the user to review, edit,
and explicitly approve before anything is persisted. Persistence and the
approval UI live in pages/stage_build.py, reusing the EXISTING
outline_sections/outline_section_requirements CRUD (tenancy.
upsert_section_authenticated/set_section_requirement_mapping_authenticated)
-- no new table, no new migration.

Deterministic only. PI-3D's own instruction 3 ("prefer deterministic
derivation... one bounded model call only where proposal architecture
requires reasoning beyond deterministic extraction") is satisfied by NOT
reaching for a model call at all here: a requirement's own `category`
(already Fast-Analysis-derived) is a sufficient, already-available signal
for a first proposed structure. A user who wants a different one is one
rename/merge/reorder away in the review UI, never blocked on this
module's own judgment.

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
