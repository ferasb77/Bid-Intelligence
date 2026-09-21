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

PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION = "proposal-intelligence-v4"

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
# PI-2A: closed vocabularies for the richer analyzer output. Any value
# outside these sets is treated as absent (fail-closed), never guessed.
# ---------------------------------------------------------------------------
EVIDENCE_STRENGTH_VALUES = ("STRONG", "MODERATE", "WEAK")

# The chunk-level deficiency vocabulary a single chunk can safely
# establish (analyst.py's _CHUNK_DEFICIENCY_TYPES) -- maps 1:1 onto this
# module's existing bounded FINDING_TYPES taxonomy (already had
# WEAK_EVIDENCE/UNSUPPORTED_CLAIM/CONTRADICTION/INTERNAL_INCONSISTENCY/
# OTHER from PI-1's forward-looking taxonomy design; PI-2A is the first
# phase to actually populate them from analyzer output).
_CHUNK_DEFICIENCY_TYPE_MAP = {
    "WEAK_EVIDENCE": FINDING_TYPE_WEAK_EVIDENCE,
    "UNSUPPORTED_CLAIM": FINDING_TYPE_UNSUPPORTED_CLAIM,
    "CONTRADICTION": FINDING_TYPE_CONTRADICTION,
    "INTERNAL_INCONSISTENCY": FINDING_TYPE_INTERNAL_INCONSISTENCY,
    "OTHER": FINDING_TYPE_OTHER,
}

_OBSERVATION_TYPE_TO_FINDING_TYPE = {
    "DELIVERY_COMMITMENT": FINDING_TYPE_DELIVERY_COMMITMENT,
    "COMMERCIAL_EXPOSURE": FINDING_TYPE_COMMERCIAL_EXPOSURE,
}


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


def _requirement_source_refs_lookup(requirements: list[dict]) -> dict[str, list]:
    """req_id -> that requirement's own canonical `source_refs` (PI-2A
    step 8) -- the procurement-side provenance Fast Analysis extraction
    already attaches to a requirement. Exact req_id identity only, never
    fuzzy matching. A requirement with no source_refs (or none at all)
    yields []; never synthesized from description text."""
    lookup = {}
    for r in requirements:
        req_id = r.get("req_id")
        if not req_id:
            continue
        refs = r.get("source_refs")
        lookup[req_id] = list(refs) if isinstance(refs, list) else []
    return lookup


def _proposal_source_refs_for_assessment(row: dict) -> list[dict]:
    """PI-2A step 13A: prefer the richer, structured `proposal_source_refs`
    analyst.py's aggregation now attaches directly to a coverage row (a
    list of ProposalSourceRef dicts already carrying file_id/content_hash/
    section/char coordinates + excerpt where known). Falls back to PI-1's
    free-text evidence_location/notes reconstruction for a legacy-shaped
    (PI-1) analyzer result that doesn't carry the new field at all -- this
    keeps old-shaped input from crashing (backward compatibility)."""
    refs = row.get("proposal_source_refs")
    if isinstance(refs, list) and refs:
        return refs
    if isinstance(refs, list):
        # Key present but genuinely empty (e.g. Not Addressed/Cannot
        # Assess) -- an empty structured list, not a legacy-shaped input;
        # do not fall back to the free-text reconstruction, which would
        # only ever be [] anyway for those rows.
        return []
    return _proposal_source_refs_from_coverage_row(row)


def _valid_evidence_strength(value) -> str | None:
    return value if value in EVIDENCE_STRENGTH_VALUES else None


def adapt_requirement_assessments(alignment_result: dict, requirements: list[dict]) -> list[dict]:
    """analyst.analyze_proposal_alignment_package()'s `requirement_coverage`
    list -> one proposal_requirement_assessments row per item, using
    analyst.py's EXISTING coverage/confidence vocabulary unchanged (see
    ASSESSMENT_STATUSES). requirement_id is populated only when the
    caller's requirements list actually carries a numeric id for that
    req_id -- otherwise left None, never guessed.

    PI-2A: proposal_source_refs now prefers the analyzer's structured,
    multi-evidence ProposalSourceRef list (falling back to PI-1's
    free-text reconstruction for legacy-shaped input); procurement_source_
    refs is resolved from the SAME canonical requirement's own existing
    `source_refs` (never synthesized); evidence_strength comes from the
    winning coverage row's own field, fail-closed to None when missing or
    not one of STRONG/MODERATE/WEAK."""
    id_lookup = _requirement_id_lookup(requirements)
    procurement_refs_lookup = _requirement_source_refs_lookup(requirements)
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
            "proposal_source_refs": _proposal_source_refs_for_assessment(row),
            "procurement_source_refs": procurement_refs_lookup.get(req_id, []),
            "evidence_strength": _valid_evidence_strength(row.get("evidence_strength")),
        })
    return rows


def adapt_findings(alignment_result: dict, requirements: list[dict] | None = None) -> list[dict]:
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
    id_lookup = _requirement_id_lookup(requirements) if requirements else {}
    procurement_refs_lookup_top = _requirement_source_refs_lookup(requirements) if requirements else {}

    # PI-2B1 step 17: every finding this adapter emits is a LOCAL
    # (per-chunk/per-requirement) finding -- tagged `payload["scope"] =
    # "local"` explicitly so CHECK/reload code can tell it apart from a
    # PI-2B1 whole-package finding (adapt_package_findings below, which
    # tags "package") without guessing from finding_type alone (a package
    # run can ALSO emit CONTRADICTION/INTERNAL_INCONSISTENCY/
    # UNSUPPORTED_CLAIM, so finding_type is not sufficient to distinguish
    # scope). Additive key on an existing jsonb column -- no migration.
    rows = []
    for mf in alignment_result.get("mandatory_failures") or []:
        mf_req_id = mf.get("req_id")
        rows.append({
            "finding_type": FINDING_TYPE_MISSING_REQUIREMENT,
            "severity": "Critical",
            "title": f"Mandatory requirement not met: {mf_req_id or ''}".strip(),
            "message": mf.get("reason"),
            "explanation": mf.get("description"),
            "related_req_id": mf_req_id,
            "related_requirement_id": id_lookup.get(mf_req_id),
            "proposal_source_refs": [],
            "procurement_source_refs": procurement_refs_lookup_top.get(mf_req_id, []) if mf_req_id else [],
            "payload": dict(mf, scope="local"),
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
            "payload": dict(uf, scope="local"),
        })

    procurement_refs_lookup = _requirement_source_refs_lookup(requirements) if requirements else {}

    for f in alignment_result.get("findings") or []:
        # PI-2A step 13B: map the chunk-level deficiency_type the analyzer
        # emitted (already validated fail-closed to OTHER-or-absent by
        # analyst._attach_chunk_provenance) into this module's existing
        # bounded taxonomy. Never guessed from title/message keywords --
        # missing/unrecognized always falls back to OTHER.
        deficiency_type = f.get("deficiency_type")
        finding_type = _CHUNK_DEFICIENCY_TYPE_MAP.get(deficiency_type, FINDING_TYPE_OTHER)
        req_id = f.get("req_id")
        proposal_refs = f.get("proposal_source_refs")
        if not isinstance(proposal_refs, list):
            proposal_refs = (
                [{"evidence_location": f["proposal_location"]}] if f.get("proposal_location") else []
            )
        rows.append({
            "finding_type": finding_type,
            "severity": f.get("severity"),
            "title": f.get("title") or "Finding",
            "message": f.get("issue"),
            "explanation": f.get("recommendation"),
            "related_req_id": req_id,
            "related_requirement_id": id_lookup.get(req_id),
            "proposal_source_refs": proposal_refs,
            "procurement_source_refs": procurement_refs_lookup.get(req_id, []) if req_id else [],
            "payload": dict(f, scope="local"),
        })

    # PI-2A step 13C: proposal_observations (DELIVERY_COMMITMENT /
    # COMMERCIAL_EXPOSURE) -> their own finding rows. These are NOT
    # deficiencies -- persisted as findings purely because migration 015's
    # findings table is the durable home for any typed, provenance-bearing
    # PI observation; CHECK's rendering keeps them in their own
    # "Commitments & Commercial Exposure" section, never mixed into Audit
    # Findings (see pages/stage_check.py).
    for o in alignment_result.get("proposal_observations") or []:
        observation_type = o.get("observation_type")
        finding_type = _OBSERVATION_TYPE_TO_FINDING_TYPE.get(observation_type)
        if not finding_type:
            continue  # fail-closed: an unrecognized observation type is never guessed into a type
        req_id = o.get("req_id")
        rows.append({
            "finding_type": finding_type,
            "severity": None,
            "title": o.get("title") or observation_type.replace("_", " ").title(),
            "message": o.get("statement"),
            "explanation": o.get("implication"),
            "related_req_id": req_id,
            "related_requirement_id": id_lookup.get(req_id),
            "proposal_source_refs": o.get("proposal_source_refs") or [],
            "procurement_source_refs": procurement_refs_lookup.get(req_id, []) if req_id else [],
            "payload": dict(o, scope="local"),
        })
    return rows


# ---------------------------------------------------------------------------
# PI-2B1: whole-package finding adapter (analyst.analyze_proposal_package_
# intelligence()'s output -> proposal_intelligence_findings rows). Reuses
# the EXISTING findings table/vocabulary (CONTRADICTION/
# INTERNAL_INCONSISTENCY/UNSUPPORTED_CLAIM were already part of
# FINDING_TYPES from PI-1's forward-looking taxonomy -- see the module's
# taxonomy comment above) -- no migration. Every row's payload carries
# `scope: "package"` (see adapt_findings' "local" tagging above) plus the
# model-cited claim/source IDs and the ledger digest that produced it, for
# audit traceability, never raw ledger content.
# ---------------------------------------------------------------------------

def adapt_package_findings(package_result: dict, requirements: list[dict] | None = None) -> list[dict]:
    """analyst.analyze_proposal_package_intelligence()'s already-reconciled,
    fail-closed `package_findings` -> proposal_intelligence_findings rows.
    Only ALREADY-VALIDATED findings reach this adapter (analyst.py's
    _reconcile_package_findings rejected anything with an unknown claim/
    source id, unknown finding_type/severity, or a non-ledger-verbatim
    req_id) -- this function does no further semantic validation, only
    requirement-id RESOLUTION via the SAME `_requirement_id_lookup`/
    `_requirement_source_refs_lookup` helpers every other adapter here
    uses (step 14: 'reuse, don't reimplement'; exact req_id identity only,
    never fuzzy-matched -- an req_id that doesn't resolve is simply left
    with related_requirement_id=None and no procurement_source_refs,
    never guessed).

    A FAILED/SKIPPED_EMPTY_LEDGER package_reasoning_status naturally
    yields package_findings == [] here -- callers persist the (empty)
    result list plus the run's own package_reasoning_status/ledger digest
    metadata (see build_run_payload's coverage_metadata carrying a
    `package_intelligence` block) themselves; this adapter never invents
    a placeholder finding to represent a failure."""
    id_lookup = _requirement_id_lookup(requirements) if requirements else {}
    procurement_refs_lookup = _requirement_source_refs_lookup(requirements) if requirements else {}
    digest = package_result.get("package_ledger_digest")

    rows = []
    for pf in package_result.get("package_findings") or []:
        req_id = pf.get("req_id")
        rows.append({
            "finding_type": pf.get("finding_type"),
            "severity": pf.get("severity"),
            "title": pf.get("title") or "Whole-package finding",
            "message": pf.get("explanation"),
            "explanation": pf.get("recommended_action"),
            "related_req_id": req_id,
            "related_requirement_id": id_lookup.get(req_id) if req_id else None,
            "proposal_source_refs": pf.get("proposal_source_refs") or [],
            "procurement_source_refs": procurement_refs_lookup.get(req_id, []) if req_id else [],
            "payload": dict(
                pf,
                scope="package",
                package_ledger_digest=digest,
                # Carried into payload too (not just the top-level finding
                # row) so reconstruct_legacy_align_result -> CHECK's reload
                # path can render every cited proposal source without a
                # DB round trip, exactly like a local finding's payload
                # already self-contains everything it needs.
                proposal_source_refs=pf.get("proposal_source_refs") or [],
            ),
        })
    return rows


# ---------------------------------------------------------------------------
# PI-2B2: Response Guideline coverage / evaluator-usability adapter
# (analyst.analyze_proposal_package_intelligence()'s already-reconciled,
# fail-closed `guideline_assessments` -> proposal_intelligence_findings
# rows). No new table/migration (see this module's docstring's "no new LLM
# call" discipline extended here to "no new persistence mechanism" --
# migration 015's generic finding_type/payload columns, already sufficient
# for PI-2A/PI-2B1, are reused verbatim): every guideline assessment is
# persisted as its own finding row, `payload["kind"] = "guideline_
# assessment"` distinguishing it from a local/package finding row exactly
# the way `payload["scope"]` already distinguishes local vs. package
# (requirement 9 -- CHECK reload renders the whole "Response Guideline /
# Evaluator Usability" section, every status, purely from these rows).
# A genuine gap (status == NOT_ANSWERED, meaning coverage_complete AND
# ledger_complete both held AND no evidence was found -- see
# analyst._reconcile_guideline_assessments' fail-closed downgrade) is ALSO
# tagged with finding_type RESPONSE_GUIDELINE_GAP (requirement 7 -- the
# existing, already-bounded taxonomy type, no new finding-type mechanism);
# every other status (ANSWERED/PARTIAL/CANNOT_ASSESS) persists as
# FINDING_TYPE_OTHER, since it documents coverage, not a deficiency.
# ---------------------------------------------------------------------------

def adapt_guideline_assessments(package_result: dict, requirements: list[dict] | None = None) -> list[dict]:
    """analyst.analyze_proposal_package_intelligence()'s already-reconciled
    `guideline_assessments` -> proposal_intelligence_findings rows. Only
    ALREADY-VALIDATED assessments reach this adapter (analyst.py's
    _reconcile_guideline_assessments rejected anything with an unknown
    guideline/claim/source/observation id, unknown status, or an
    unprovenanced positive conclusion, and structurally downgraded an
    incomplete-coverage NOT_ANSWERED to CANNOT_ASSESS) -- this function does
    no further semantic validation, only persistence shaping. A FAILED/
    SKIPPED_* package_reasoning_status or a bid with no Response Guidelines
    at all naturally yields `guideline_assessments == []` here -- never a
    fabricated placeholder row."""
    digest = package_result.get("package_ledger_digest")
    rows = []
    for ga in package_result.get("guideline_assessments") or []:
        status = ga.get("status")
        is_gap = status == "NOT_ANSWERED"
        rows.append({
            "finding_type": FINDING_TYPE_RESPONSE_GUIDELINE_GAP if is_gap else FINDING_TYPE_OTHER,
            "severity": "Medium" if is_gap else None,
            "title": f"Response Guideline {ga.get('guideline_id') or ''}: {status or ''}".strip(),
            "message": ga.get("rationale"),
            "explanation": None,
            "related_req_id": None,
            "related_requirement_id": None,
            "proposal_source_refs": ga.get("proposal_source_refs") or [],
            "procurement_source_refs": [],
            "payload": dict(
                ga,
                kind="guideline_assessment",
                scope="package",
                package_ledger_digest=digest,
                proposal_source_refs=ga.get("proposal_source_refs") or [],
            ),
        })
    return rows


def build_run_payload(alignment_result: dict, *, procurement_state: dict,
                      started_at: str | None = None, completed_at: str | None = None,
                      package_intelligence: dict | None = None) -> dict:
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
    # PI-2B1 step 17/26: no new run-level column -- the package reasoning
    # call's own status/digest/rejected-count metadata (never raw ledger
    # content, never raw proposal text) rides inside the EXISTING
    # coverage_metadata jsonb column, alongside (never replacing) the
    # local-analysis coverage_metadata it already carries. Absent when the
    # caller never ran PI-2B1 (e.g. a historical v2 run, or this run's
    # local PI-2A result itself failed before PI-2B1 could run) -- never
    # fabricated as a placeholder.
    coverage_metadata = alignment_result.get("coverage_metadata")
    if package_intelligence is not None:
        coverage_metadata = dict(coverage_metadata or {})
        coverage_metadata["package_intelligence"] = {
            "package_reasoning_status": package_intelligence.get("package_reasoning_status"),
            "package_ledger_digest": package_intelligence.get("package_ledger_digest"),
            "rejected_count": package_intelligence.get("rejected_count"),
            "claims_dropped_for_budget": package_intelligence.get("claims_dropped_for_budget"),
            "failure_reason": package_intelligence.get("failure_reason"),
            # PI-2B2: never a run-level column -- the same additive-jsonb
            # discipline PI-2B1 already established for this block.
            "rejected_guideline_count": package_intelligence.get("rejected_guideline_count"),
        }
    return {
        "based_on_procurement_revision": procurement_state.get("procurement_revision"),
        "based_on_procurement_truth_status": procurement_state.get("procurement_truth_status"),
        "analysis_version": PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION,
        "status": status,
        "failure_reason": None,
        "coverage_metadata": coverage_metadata,
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
            # PI-2A additive reload fields -- absent/empty on a historical
            # PI-1 run (never crashes; CHECK renders them only when present).
            "proposal_source_refs": refs,
            "evidence_strength": a.get("evidence_strength"),
            "procurement_source_refs": a.get("procurement_source_refs") or [],
        })
    mandatory_failures = [f["payload"] for f in findings
                          if f.get("finding_type") == FINDING_TYPE_MISSING_REQUIREMENT and f.get("payload")]
    # PI-2A: a "general audit finding" for legacy CHECK rendering purposes
    # is any finding NOT already reconstructed above/below into its own
    # dedicated section -- MISSING_REQUIREMENT (mandatory_failures),
    # SUBMISSION_ARTIFACT_GAP (folded into coverage_metadata already, never
    # duplicated here), and DELIVERY_COMMITMENT/COMMERCIAL_EXPOSURE
    # (proposal_observations below). This now correctly includes the new
    # locally-typed deficiency findings (WEAK_EVIDENCE/UNSUPPORTED_CLAIM/
    # CONTRADICTION/INTERNAL_INCONSISTENCY) as well as plain OTHER --
    # a PI-1 run only ever had OTHER, so this is a strict superset, never
    # a behavior change for historical rows.
    _non_general_types = {
        FINDING_TYPE_MISSING_REQUIREMENT, FINDING_TYPE_SUBMISSION_ARTIFACT_GAP,
        FINDING_TYPE_DELIVERY_COMMITMENT, FINDING_TYPE_COMMERCIAL_EXPOSURE,
    }
    # PI-2B1 step 21/22: a package-scope finding (payload["scope"] ==
    # "package", stamped by adapt_package_findings) is split into its own
    # `package_findings` list here rather than mixed into general_findings
    # -- CHECK's "Whole-Package Consistency" section (below) renders these
    # separately and MUST be able to tell one apart from a same-typed
    # LOCAL finding (a package run can also emit CONTRADICTION/
    # INTERNAL_INCONSISTENCY/UNSUPPORTED_CLAIM, so finding_type alone
    # cannot distinguish scope -- see adapt_findings' scope tagging
    # comment). A historical run with no package findings at all yields
    # [] here and renders safely (step 22).
    # PI-2B2: a guideline-assessment row (payload["kind"] ==
    # "guideline_assessment", stamped by adapt_guideline_assessments) is
    # carved out of BOTH general_findings and package_findings, exactly
    # like proposal_observations already is above -- finding_type alone
    # cannot distinguish it (a genuine gap shares FINDING_TYPE_
    # RESPONSE_GUIDELINE_GAP with nothing else, but ANSWERED/PARTIAL/
    # CANNOT_ASSESS rows share FINDING_TYPE_OTHER with ordinary local
    # findings). A historical pre-PI-2B2 run has none and renders an empty
    # list safely (same "never crashes on absence" contract as every other
    # additive PI-2 field).
    guideline_assessments = [
        f["payload"] for f in findings
        if f.get("payload") and (f["payload"] or {}).get("kind") == "guideline_assessment"
    ]
    general_findings = [
        f["payload"] for f in findings
        if f.get("finding_type") not in _non_general_types and f.get("payload")
        and (f["payload"] or {}).get("scope") != "package"
        and (f["payload"] or {}).get("kind") != "guideline_assessment"
    ]
    package_findings = [
        f["payload"] for f in findings
        if f.get("payload") and (f["payload"] or {}).get("scope") == "package"
        and (f["payload"] or {}).get("kind") != "guideline_assessment"
    ]
    proposal_observations = [
        f["payload"] for f in findings
        if f.get("finding_type") in (FINDING_TYPE_DELIVERY_COMMITMENT, FINDING_TYPE_COMMERCIAL_EXPOSURE)
        and f.get("payload")
    ]
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
        "findings": general_findings,
        "package_findings": package_findings,
        "guideline_assessments": guideline_assessments,
        "proposal_observations": proposal_observations,
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
