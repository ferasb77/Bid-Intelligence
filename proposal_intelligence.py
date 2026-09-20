"""
proposal_intelligence.py -- PI-1: the durable Proposal Intelligence domain
foundation (migrations/015_proposal_intelligence.sql).

PRODUCT MODEL (see MANIFESTO.md/ANTI_GOALS.md for the full constitutional
grounding): this module owns exactly one layer --

    PROPOSAL INTELLIGENCE: what the proposal actually says, demonstrates,
    covers, contradicts, fails to evidence, or omits relative to the
    procurement.

It is advisory intelligence, never canonical procurement truth. It never
modifies canonical procurement truth, never silently repairs a procurement
fact, never turns Buyer Intelligence into a procurement requirement, never
promotes model inference into evidence, never invents proposal or
procurement evidence, never infers absence from a partially analyzed
proposal package, never overwrites a previous Proposal Intelligence run,
and is never authoritative merely because it is persisted.

PI-1 adds NO new LLM call and does not touch analyst.py's Proposal
Alignment Analyzer (prompts, schema, scoring, chunking, recovery
behavior all unchanged). This module is a pure, deterministic ADAPTER
from analyst.analyze_proposal_alignment_package()'s existing result
shape into the durable representation defined by migration 015 --
package identity, run identity, requirement assessments, and findings --
plus deterministic staleness helpers. It performs no I/O and no
persistence of its own; database.py/tenancy.py own writing its output to
Supabase.

ANALYSIS_VERSION represents the PI analytical CONTRACT/version (this
module's own adapter logic), never the model name -- a future change to
how alignment output is normalized into PI rows can invalidate or be
compared against prior runs explicitly via this constant, independent of
which Anthropic model analyst.py happens to call.
"""
from __future__ import annotations

import hashlib
import json

PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION = "proposal-intelligence-v1"

# ---------------------------------------------------------------------------
# Section 3: finding taxonomy -- bounded, sufficient to normalize CURRENT
# analyzer output. Only a type genuinely supported by today's analyzer
# result is ever emitted (see classify_findings() below) -- the remaining
# types exist for future PI phases to grow into, never manufactured now.
# ---------------------------------------------------------------------------
FINDING_TYPE_REQUIREMENT_COVERAGE = "REQUIREMENT_COVERAGE"
FINDING_TYPE_MISSING_REQUIREMENT = "MISSING_REQUIREMENT"
FINDING_TYPE_WEAK_EVIDENCE = "WEAK_EVIDENCE"
FINDING_TYPE_UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
FINDING_TYPE_CONTRADICTION = "CONTRADICTION"
FINDING_TYPE_RESPONSE_GUIDELINE_GAP = "RESPONSE_GUIDELINE_GAP"
FINDING_TYPE_SUBMISSION_ARTIFACT_GAP = "SUBMISSION_ARTIFACT_GAP"
FINDING_TYPE_INTERNAL_INCONSISTENCY = "INTERNAL_INCONSISTENCY"
FINDING_TYPE_DELIVERY_COMMITMENT = "DELIVERY_COMMITMENT"
FINDING_TYPE_COMMERCIAL_EXPOSURE = "COMMERCIAL_EXPOSURE"
FINDING_TYPE_OTHER = "OTHER"

FINDING_TYPES = (
    FINDING_TYPE_REQUIREMENT_COVERAGE, FINDING_TYPE_MISSING_REQUIREMENT,
    FINDING_TYPE_WEAK_EVIDENCE, FINDING_TYPE_UNSUPPORTED_CLAIM, FINDING_TYPE_CONTRADICTION,
    FINDING_TYPE_RESPONSE_GUIDELINE_GAP, FINDING_TYPE_SUBMISSION_ARTIFACT_GAP,
    FINDING_TYPE_INTERNAL_INCONSISTENCY, FINDING_TYPE_DELIVERY_COMMITMENT,
    FINDING_TYPE_COMMERCIAL_EXPOSURE, FINDING_TYPE_OTHER,
)

# Requirement-assessment status vocabulary -- borrowed VERBATIM from
# analyst._aggregate_requirement_coverage's existing "coverage" values,
# never a second invented vocabulary (instruction: "Use the EXISTING
# Proposal Alignment semantics rather than inventing a second status
# vocabulary").
ASSESSMENT_STATUSES = ("Fully Addressed", "Partially Addressed", "Not Addressed", "Cannot Assess")

# Boilerplate `notes` strings analyst._aggregate_requirement_coverage emits
# when a requirement has no positive assertion (analyst.py:1260, 1266) --
# used here only to recognize "this coverage row has no real evidence
# text," never re-generated or altered.
_NO_EVIDENCE_NOTES = (
    "No supporting evidence found anywhere in the analyzed proposal.",
    "Proposal coverage is incomplete -- absence cannot be confirmed.",
)


# ---------------------------------------------------------------------------
# Section 2A / Section 16: package identity
# ---------------------------------------------------------------------------

# The exact per-file fields that determine ANALYSIS INPUT identity.
# Deliberately excludes `text`/`extraction_meta`/`lifecycle_status`/
# `duplicate_of_file_id`/`char_count`/`unusable_reason` -- lifecycle/
# diagnostic fields do not change what will be SENT to the analyzer
# (an excluded or unusable file contributes nothing to the request either
# way); only identity + the two analysis-relevant UI choices matter.
_PACKAGE_IDENTITY_FIELDS = ("file_id", "content_hash", "included", "role")


def compute_package_digest(files: list[dict]) -> str:
    """Deterministic sha256 over every file's (file_id, content_hash,
    included, role) tuple, sorted by file_id.

    PI-1.2: this sort makes the digest computation itself order-INSENSITIVE
    (feeding the same files in a different sequence produces the same
    sorted rows and the same digest), but that is not the same as the
    underlying identity being upload/discovery-order independent. file_id
    is derived from (occurrence_index, package_path, content_hash) in
    extractor.build_alignment_submission_package -- so re-uploading the
    exact same physical bytes in a different order legitimately produces
    different file_ids and therefore a different digest. This is
    intentional, not a defect: package ordering is analysis-relevant to
    analyze_proposal_alignment_package's chunk-budget allocation
    (analyst.py's _allocate_package_chunk_budget assigns package-wide
    chunk index/total by package order, and its ceiling-exceeded and
    largest-remainder-distribution branches can select different files/
    chunks depending on package order, including via file_id tie-breaks).
    Since ordering can change what the analyzer actually saw, ordering is
    deliberately part of Proposal Intelligence's input identity -- two
    uploads of the same bytes in a different order are treated as
    genuinely different package identities, matching that they can
    genuinely produce different analysis. Changing a file's bytes (-> new
    content_hash -> new file_id, since file_id is itself derived from
    content_hash), its inclusion state, or its role always changes the
    digest. Never includes raw extracted text -- the digest represents
    identity, not content, exactly like every other content-hash identity
    already established in this codebase
    (extractor.build_alignment_submission_package's own file_id/
    content_hash).

    PI-1.1 (instruction 6): `files` must be the COMPLETE SUBMITTED package
    -- every file the user uploaded, included and excluded, duplicate,
    rejected, and unsupported alike -- never just the analyzer's included-
    only subset. This makes "an excluded file is present in the package"
    and "that file was never supplied at all" deliberately DIFFERENT
    package identities (the excluded file still contributes a
    (file_id, content_hash, included=False, role) entry either way,
    changing the digest from a package that never had it), which matches
    what a historical audit needs to reconstruct: the exact submission a
    reviewer chose to exclude, not merely the subset the model saw. The
    analyzer itself still only ever receives the included subset --
    calling code must build that narrower list separately (see
    tenancy.run_proposal_intelligence_for_organization's
    `package_files_for_analysis` vs. `full_package_manifest` parameters)."""
    rows = sorted(
        (
            {field: f.get(field) for field in _PACKAGE_IDENTITY_FIELDS}
            for f in files
        ),
        key=lambda row: row["file_id"] or "",
    )
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Section 7: staleness
# ---------------------------------------------------------------------------
STALE_PROCUREMENT_CHANGED = "PROCUREMENT_CHANGED"
STALE_PROPOSAL_CHANGED = "PROPOSAL_CHANGED"
STALE_ANALYSIS_VERSION_CHANGED = "ANALYSIS_VERSION_CHANGED"


def staleness_reasons(run: dict, *, current_procurement_revision,
                      current_package_snapshot_id,
                      current_analysis_version: str = PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION) -> list[str]:
    """Every specific reason `run` is no longer CURRENT -- never collapsed
    into a single generic boolean (instruction 7). Empty list == current."""
    reasons = []
    if run.get("based_on_procurement_revision") != current_procurement_revision:
        reasons.append(STALE_PROCUREMENT_CHANGED)
    if run.get("proposal_package_snapshot_id") != current_package_snapshot_id:
        reasons.append(STALE_PROPOSAL_CHANGED)
    if run.get("analysis_version") != current_analysis_version:
        reasons.append(STALE_ANALYSIS_VERSION_CHANGED)
    return reasons


def is_current(run: dict, **kwargs) -> bool:
    return not staleness_reasons(run, **kwargs)


# ---------------------------------------------------------------------------
# Section 4: proposal provenance (ProposalSourceRef contract)
# ---------------------------------------------------------------------------

def _proposal_source_refs_from_coverage_row(row: dict) -> list[dict]:
    """One requirement_coverage row -> its ProposalSourceRef list.

    analyst.py's current coverage aggregation exposes only a free-text
    `evidence_location` label (a chunk_label such as "Schedule C.txt —
    Pricing" or one embedding "Sheet: <name>" for spreadsheets -- see
    analyst.py:1221/2144-2147) and a `notes` excerpt -- never a
    structured file_id/content_hash/page coordinate per requirement.
    Rather than heuristically re-parsing that label into fields it was
    never guaranteed to decompose into (risking a FABRICATED page/sheet/
    section -- explicitly forbidden), this preserves it verbatim as
    `evidence_location` and the notes text as `excerpt`. True structured
    file-linked coordinates per assessment is a PI-2 gap (see the module
    docstring / final report's "remaining PI-2 gaps") requiring analyst.py
    to carry source_file_id through to the coverage aggregate, which PI-1
    does not touch (no analyzer changes permitted this phase).

    Absence rows (evidence_location == "", the exact behavior of
    analyst._aggregate_requirement_coverage for Not Addressed/Cannot
    Assess) correctly return [] -- no fabricated proposal passage."""
    evidence_location = row.get("evidence_location") or ""
    if not evidence_location:
        return []
    ref = {"evidence_location": evidence_location}
    notes = row.get("notes")
    if notes and notes not in _NO_EVIDENCE_NOTES:
        ref["excerpt"] = notes
    return [ref]


# ---------------------------------------------------------------------------
# Section 8: current alignment -> PI adapter
# ---------------------------------------------------------------------------

def _requirement_id_lookup(requirements: list[dict]) -> dict[str, int]:
    """req_id (string label) -> numeric requirements.id, where both are
    available on the caller-supplied requirements list. Never guessed."""
    lookup = {}
    for r in requirements:
        req_id, numeric_id = r.get("req_id"), r.get("id")
        if req_id and numeric_id is not None:
            lookup[req_id] = numeric_id
    return lookup


def adapt_requirement_assessments(alignment_result: dict, requirements: list[dict]) -> list[dict]:
    """analyst.analyze_proposal_alignment_package()'s `requirement_coverage`
    list -> one proposal_requirement_assessments row per item, using
    analyst.py's EXISTING coverage/confidence vocabulary unchanged (see
    ASSESSMENT_STATUSES). requirement_id is populated only when the
    caller's requirements list actually carries a numeric id for that
    req_id -- otherwise left None, never guessed."""
    id_lookup = _requirement_id_lookup(requirements)
    rows = []
    for row in alignment_result.get("requirement_coverage") or []:
        req_id = row.get("req_id")
        rows.append({
            "requirement_id": id_lookup.get(req_id),
            "req_id": req_id,
            "category": row.get("category"),
            "description": row.get("description"),
            "assessment_status": row.get("coverage"),
            "confidence": row.get("confidence"),
            "explanation": None,  # analyzer does not currently produce a
                                  # per-requirement narrative distinct from
                                  # notes/evidence -- never fabricated here
            "proposal_source_refs": _proposal_source_refs_from_coverage_row(row),
            "procurement_source_refs": [],  # PI-2 gap: analyzer does not
                                            # currently return which
                                            # procurement evidence/source
                                            # produced the requirement text
            "evidence_strength": None,  # not yet supported by the analyzer
        })
    return rows


def adapt_findings(alignment_result: dict) -> list[dict]:
    """analyst.py's `mandatory_failures` and `findings` (plus
    coverage_metadata's `unusable_files`) -> proposal_intelligence_findings
    rows. Only classifications the CURRENT analyzer output genuinely
    supports are emitted:

      mandatory_failures  -> MISSING_REQUIREMENT (an explicit mandatory-
                              requirement failure is exactly that finding
                              type, not a guess)
      coverage_metadata.unusable_files -> SUBMISSION_ARTIFACT_GAP (a file
                              the package included but could not be
                              analyzed is exactly a submission-artifact
                              gap in what was actually reviewed)
      findings             -> OTHER (analyst.py's generic findings carry
                              severity/stage/issue but no sub-classification
                              distinguishing e.g. WEAK_EVIDENCE from
                              CONTRADICTION -- mapping them to a more
                              specific type would manufacture semantics the
                              analyzer never asserted; PI-2 gap)

    `unresolved_items`/`priority_actions`/`next_steps` are intentionally
    NOT mapped to findings here -- their shape/semantics were not
    confirmed against the live analyzer during PI-1's audit, and guessing
    a mapping would risk fabricating structure. They remain available,
    unmodified, in the run's `legacy_result` (see build_run_payload)."""
    rows = []
    for mf in alignment_result.get("mandatory_failures") or []:
        rows.append({
            "finding_type": FINDING_TYPE_MISSING_REQUIREMENT,
            "severity": "Critical",
            "title": f"Mandatory requirement not met: {mf.get('req_id', '')}".strip(),
            "message": mf.get("reason"),
            "explanation": mf.get("description"),
            "related_req_id": mf.get("req_id"),
            "proposal_source_refs": [],
            "procurement_source_refs": [],
            "payload": dict(mf),
        })

    coverage_metadata = alignment_result.get("coverage_metadata") or {}
    for uf in coverage_metadata.get("unusable_files") or []:
        rows.append({
            "finding_type": FINDING_TYPE_SUBMISSION_ARTIFACT_GAP,
            "severity": None,
            "title": f"Submission artifact could not be analyzed: {uf.get('filename', '')}".strip(),
            "message": uf.get("reason"),
            "explanation": None,
            "related_req_id": None,
            "proposal_source_refs": [],
            "procurement_source_refs": [],
            "payload": dict(uf),
        })

    for f in alignment_result.get("findings") or []:
        rows.append({
            "finding_type": FINDING_TYPE_OTHER,
            "severity": f.get("severity"),
            "title": f.get("title") or "Finding",
            "message": f.get("issue"),
            "explanation": f.get("recommendation"),
            "related_req_id": f.get("req_id"),
            "proposal_source_refs": (
                [{"evidence_location": f["proposal_location"]}] if f.get("proposal_location") else []
            ),
            "procurement_source_refs": [],
            "payload": dict(f),
        })
    return rows


def build_run_payload(alignment_result: dict, *, procurement_state: dict,
                      started_at: str | None = None, completed_at: str | None = None) -> dict:
    """The proposal_intelligence_runs row body (minus id/bid_id/
    proposal_package_snapshot_id/created_by_user_id, which the caller/
    persistence layer supplies). Never mutates canonical procurement
    truth -- procurement_state is stamped verbatim (governed/ungoverned
    both recorded explicitly, never collapsed into one "trusted" state --
    instruction 5's "never make it look equivalent to a governed run").

    status mirrors the analyzer's own existing vocabulary ("complete" ->
    COMPLETE, "incomplete" -> INCOMPLETE) rather than inventing a third
    one; FAILED is reserved for a caller-detected provider/model exception
    with no analyzer result at all (see build_failed_run_payload).

    PI-1.1 (instruction 7): `started_at` must be the timestamp the caller
    captured BEFORE invoking the analyzer, and `completed_at` the
    timestamp captured immediately after it returned -- never left to
    default at INSERT time, which would record when the row was written,
    not when analysis actually ran."""
    status = "COMPLETE" if alignment_result.get("status") == "complete" else "INCOMPLETE"
    legacy_result = {
        k: alignment_result.get(k) for k in (
            "overall_score", "score_basis", "score_rationale", "recommendation",
            "executive_summary", "strengths", "next_steps", "unresolved_items",
            "priority_actions", "partial_summary", "message", "reason",
        ) if k in alignment_result
    }
    return {
        "based_on_procurement_revision": procurement_state.get("procurement_revision"),
        "based_on_procurement_truth_status": procurement_state.get("procurement_truth_status"),
        "analysis_version": PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION,
        "status": status,
        "failure_reason": None,
        "coverage_metadata": alignment_result.get("coverage_metadata"),
        "legacy_result": legacy_result,
        "started_at": started_at,
        "completed_at": completed_at,
    }


def reconstruct_legacy_align_result(run: dict, assessments: list[dict], findings: list[dict]) -> dict:
    """The inverse of adapt_requirement_assessments()/adapt_findings() --
    rebuilds a dict CHECK's EXISTING rendering code can read exactly as it
    reads analyst.analyze_proposal_alignment_package()'s own live return
    value, from persisted rows alone (no re-run of the analyzer,
    instruction 12: 'previously completed PI runs must be discoverable/
    readable without rerunning the model').

    `mandatory_failures`/`findings` are recovered losslessly from each
    finding row's own `payload` column (the ORIGINAL analyzer dict,
    preserved verbatim at adaptation time) rather than re-derived from
    the normalized PI fields -- this is exact, not approximate."""
    legacy = dict((run.get("legacy_result")) or {})
    requirement_coverage = []
    for a in assessments:
        refs = a.get("proposal_source_refs") or []
        ref = refs[0] if refs else {}
        requirement_coverage.append({
            "req_id": a.get("req_id"), "category": a.get("category") or "",
            "description": a.get("description") or "",
            "coverage": a.get("assessment_status"), "confidence": a.get("confidence"),
            "evidence_location": ref.get("evidence_location", ""),
            "notes": ref.get("excerpt") or (
                "No supporting evidence found anywhere in the analyzed proposal."
                if a.get("assessment_status") == "Not Addressed"
                else "Proposal coverage is incomplete -- absence cannot be confirmed."
                if a.get("assessment_status") == "Cannot Assess" else ""
            ),
        })
    mandatory_failures = [f["payload"] for f in findings
                          if f.get("finding_type") == FINDING_TYPE_MISSING_REQUIREMENT and f.get("payload")]
    other_findings = [f["payload"] for f in findings
                      if f.get("finding_type") == FINDING_TYPE_OTHER and f.get("payload")]
    return {
        "status": "complete" if run.get("status") == "COMPLETE" else "incomplete",
        "message": legacy.get("message"), "reason": legacy.get("reason"),
        "overall_score": legacy.get("overall_score"), "score_basis": legacy.get("score_basis"),
        "score_rationale": legacy.get("score_rationale"), "recommendation": legacy.get("recommendation"),
        "executive_summary": legacy.get("executive_summary"), "strengths": legacy.get("strengths") or [],
        "next_steps": legacy.get("next_steps") or [],
        "unresolved_items": legacy.get("unresolved_items") or [],
        "priority_actions": legacy.get("priority_actions") or [],
        "partial_summary": legacy.get("partial_summary"),
        "requirement_coverage": requirement_coverage,
        "mandatory_failures": mandatory_failures,
        "findings": other_findings,
        "coverage_metadata": run.get("coverage_metadata") or {},
        "based_on_procurement_revision": run.get("based_on_procurement_revision"),
        "based_on_procurement_truth_status": run.get("based_on_procurement_truth_status"),
    }


def restore_package_manifest_dict(snapshot: dict) -> dict:
    """PI-1.1 instruction 8: the exact shape CHECK's
    _align_result_snapshot_key session-state entry needs, rebuilt from a
    persisted proposal_package_snapshots row's `manifest` column -- the
    FULL submitted package (included AND excluded/duplicate/rejected/
    unsupported files alike, each still carrying its own `role`, so a
    primary-file designation survives reload exactly as it was at audit
    time), never re-derived from whatever the live uploader currently
    holds."""
    return {"files": snapshot.get("manifest") or []}


def build_failed_run_payload(*, procurement_state: dict, failure_reason: str,
                             started_at: str | None = None, completed_at: str | None = None) -> dict:
    """A FAILED run when a provider/model exception left no analyzer
    result at all (instruction 13: 'A provider/model failure should
    create a FAILED run only where sufficient run identity already
    exists' -- i.e. a package snapshot id -- never invents findings).

    PI-1.1 (instruction 7): a FAILED run also carries real start/
    completion timing -- the caller captures both around the (failed)
    analyzer invocation exactly as it does for a successful run."""
    return {
        "based_on_procurement_revision": procurement_state.get("procurement_revision"),
        "based_on_procurement_truth_status": procurement_state.get("procurement_truth_status"),
        "analysis_version": PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION,
        "status": "FAILED",
        "failure_reason": failure_reason,
        "coverage_metadata": None,
        "legacy_result": None,
        "started_at": started_at,
        "completed_at": completed_at,
    }
