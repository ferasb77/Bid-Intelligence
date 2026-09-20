"""
section_analyzer.py -- FORMATIVE, per-section proposal review for STAGE 3
(BUILD), integrated into the existing Proposal Outline & Integrated Section
Drafter (pages/stage_build.py).

Answers exactly one question, for ONE section, using its CURRENT editor
text: "Is this section heading in the right direction against the buyer's
actual requirements before the team invests significantly more effort?"

It does NOT answer "is the entire proposal submission-ready?" -- that
remains the later, holistic Proposal Alignment Analyzer / Submission Audit
in CHECK (analyst.py's proposal_alignment family, `_call_alignment_chunk`
etc.), which this module does not touch, call, or duplicate.

Architecture (mirrors analysis_service.py's shape, at a much smaller,
per-section scale):

    tenancy.analyze_section_for_organization()  [require_bid_access first]
        -> analyze_section(bid_id, section, section_text, mapped_requirement_ids, ...)
            -> procurement_basis(bid_id)          : source-truth hierarchy
            -> build_section_context(...)          : COMPACT context bundle
            -> find_matching_review(...)           : idempotency guard --
                                                       returns an existing
                                                       review instead of a
                                                       new model call when
                                                       nothing has changed
            -> _call_section_analyzer(...)         : ONE bounded model call
                                                       (+1 bounded retry)
            -> database.create_section_review(...) : immutable persistence

Never re-runs procurement analysis (fast_analysis.run_fast_analysis_corpus
is never imported here) -- only reads an already-persisted raw snapshot
(migrations/012_fast_analysis_result_snapshot.sql) if a compatible one
exists, via analysis_service.load_raw_fast_analysis_result().
"""
from __future__ import annotations

import hashlib
import re

from config import get_anthropic_client, execute_messages_create, classify_anthropic_error
import database as db
from fast_analysis import FAST_ANALYSIS_RAW_SNAPSHOT_SCHEMA_VERSION, FastAnalysisResult

SECTION_REVIEW_SCHEMA_VERSION = "1.0"

_MODEL = "claude-haiku-4-5-20251001"

DIRECTIONS = ("ON_TRACK", "NEEDS_ADJUSTMENT", "HIGH_RISK", "INSUFFICIENT_CONTEXT")
_REQ_STATUSES = {"COVERED", "PARTIAL", "MISSING", "CONTRADICTED", "CANNOT_ASSESS"}
_RG_STATUSES = {"ANSWERED", "PARTIAL", "NOT_ANSWERED"}
_DEPENDENCY_KINDS = {"IN_SECTION", "CROSS_REFERENCE_NEEDED", "OWNED_BY_OTHER_SECTION", "GLOBAL_REQUIREMENT"}

_CALL_FAILURE_API_ERROR = "api_error"
_CALL_FAILURE_PARSE_ERROR = "parse_error"
_CALL_FAILURE_MALFORMED_RESPONSE = "malformed_response"
_CALL_FAILURE_UNKNOWN = "unknown_error"


class SectionAnalyzerError(RuntimeError):
    """Raised when a review could not be produced. `category` is either one
    of config.classify_anthropic_error's safe categories or one of this
    module's own closed-vocabulary _CALL_FAILURE_* codes -- never the raw
    prompt, section text, or exception body (same safety contract as
    analyst.py's _call_alignment_chunk failure categories)."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


def content_hash(text: str) -> str:
    """The one place section content is hashed -- used for both the
    persisted section_content_hash column and staleness comparison. Never
    hash None; empty string hashes to a stable, well-defined value."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Source-truth hierarchy (instruction 7)
# ---------------------------------------------------------------------------

def procurement_basis(bid_id: int) -> dict:
    """Resolves which procurement truth this review will be built against.

      A. requirements table is ALWAYS the requirement-identity/description/
         category/weight source of truth, governed or not -- procurement
         governance state only gates HOW those fields may change
         (database._guard_canonical_requirement_write), never where a
         reader gets them from. get_requirements() already returns exactly
         this (active, current-revision rows).
      B. Minimum-score thresholds, qualification mechanisms, tie-break
         ranks, Response-Guideline evidence prompts, and Buyer Intelligence
         exist ONLY inside a raw Fast Analysis snapshot (migration 012) --
         there is no governed/canonical version of any of them anywhere in
         this schema yet, so they are ALWAYS advisory, regardless of the
         bid's governance state, and are shown to the writer clearly marked
         as such (never silently presented as procurement fact).
      C. If no compatible raw snapshot exists at all, (B) is simply absent
         -- never fabricated, never reconstructed from
         structured_intelligence/report_content_snapshot (the same rule
         analysis_service.load_raw_fast_analysis_result already enforces).

    Never re-runs Fast Analysis -- only reads an already-COMPLETE run's
    already-persisted snapshot, most-recent first."""
    state = db.get_bid_procurement_state(bid_id)
    raw_snapshot: FastAnalysisResult | None = None
    run_id = None
    result_id = None
    unavailable_reason = None

    runs = db.list_analysis_runs(bid_id)
    complete_fast_runs = [r for r in runs
                          if r.get("analysis_mode") == "FAST" and r.get("status") == "COMPLETE"]
    if not complete_fast_runs:
        unavailable_reason = "NO_COMPLETE_FAST_ANALYSIS_RUN"
    else:
        import analysis_service  # deferred: avoids a module-load-time cycle with analysis_service
        latest = complete_fast_runs[0]  # list_analysis_runs orders created_at desc
        run_id = latest["id"]
        loaded = analysis_service.load_raw_fast_analysis_result(run_id)
        if isinstance(loaded, str):
            unavailable_reason = loaded
        else:
            raw_snapshot = loaded
            stored = db.get_analysis_result(run_id)
            result_id = stored.get("id") if stored else None

    return {
        "procurement_revision": state.get("procurement_revision"),
        "procurement_truth_status": state.get("procurement_truth_status"),
        "raw_snapshot": raw_snapshot,
        "raw_snapshot_run_id": run_id,
        "raw_snapshot_result_id": result_id,
        "raw_snapshot_unavailable_reason": unavailable_reason,
    }


# ---------------------------------------------------------------------------
# Compact, section-scoped context bundle (instruction 9) -- never the whole
# FastAnalysisResult.
# ---------------------------------------------------------------------------

_STOPWORDS = {"the", "and", "for", "with", "this", "that", "from", "shall", "will",
             "must", "have", "has", "are", "was", "were", "been", "being", "into"}


def _significant_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
           if len(w) >= 4 and w not in _STOPWORDS}


def _match_evaluation_criterion(requirement: dict, evaluation_criteria: list[dict]) -> dict | None:
    """Best-effort, deterministic match of a requirement to its parent
    evaluation criterion by word overlap between the requirement's own
    category/description and the criterion's label -- the same class of
    fuzzy, non-exact matching already used elsewhere in this codebase
    (fast_analysis_report_adapter._is_near_duplicate), reimplemented here
    narrowly rather than importing that module's private helpers, since
    the matching GOAL is different (requirement<->criterion linkage, not
    near-duplicate collapse). Returns None (never a guessed low-confidence
    match) when no criterion shares at least 2 significant words."""
    req_words = _significant_words(requirement.get("category", "")) | _significant_words(requirement.get("description", ""))
    if not req_words:
        return None
    best, best_overlap = None, 0
    for c in evaluation_criteria:
        label = c.get("criterion_label") or ""
        crit_words = _significant_words(label)
        if not crit_words:
            continue
        overlap = len(req_words & crit_words)
        if overlap > best_overlap:
            best, best_overlap = c, overlap
    return best if best_overlap >= 2 else None


def _non_pricing_criteria_order(evaluation_criteria: list[dict]) -> list[dict]:
    """Same ordinal-position convention scripts/fast_analysis_report_adapter
    ._rg_evidence_map() uses to pair Response Guidelines with weighted
    criteria (RGs have no other stable key to join on)."""
    return [c for c in evaluation_criteria if "pricing" not in (c.get("criterion_label") or "").lower()]


def _matching_response_guideline(criterion: dict, evaluation_criteria: list[dict],
                                 response_guidelines: list[dict]) -> dict | None:
    ordered = _non_pricing_criteria_order(evaluation_criteria)
    if criterion not in ordered:
        return None
    idx = ordered.index(criterion)
    return response_guidelines[idx] if idx < len(response_guidelines) else None


def build_section_context(section: dict, section_text: str, mapped_requirements: list[dict],
                          basis: dict) -> dict:
    """Assembles the compact, section-scoped bundle the model actually
    sees. Every list here is bounded by what's actually relevant to THIS
    section's mapped requirements -- never the full corpus (instruction 9).

    Returns a plain dict (JSON-safe) with keys: section_title,
    section_guidance, section_text, word_limit, requirements (each with its
    matched evaluation criterion / weight / minimum_score / response
    guideline, when found), qualification_mechanisms, tie_break_rules,
    buyer_intelligence, procurement_basis (governed/ungoverned + advisory
    availability, for the "clearly show staleness/advisory state"
    requirement)."""
    raw = basis.get("raw_snapshot")
    evaluation_criteria = (raw.evaluation_criteria if raw else []) or []
    response_guidelines = (raw.deterministic_response_guidelines if raw else []) or []
    typed_obs = (raw.typed_observations if raw else []) or []

    qualification_mechanisms = [
        o for o in typed_obs if isinstance(o, dict) and o.get("family") == "QUALIFICATION_MECHANISM"
    ]
    tie_break_rules = sorted(
        (o for o in typed_obs if isinstance(o, dict) and o.get("family") == "TIE_BREAK_RULE"),
        key=lambda o: (o.get("rank") is None, o.get("rank")))

    req_bundle = []
    for r in mapped_requirements:
        criterion = _match_evaluation_criterion(r, evaluation_criteria)
        rg = _matching_response_guideline(criterion, evaluation_criteria, response_guidelines) if criterion else None
        req_bundle.append({
            "requirement_id": r.get("id"),
            "req_id": r.get("req_id"),
            "category": r.get("category"),
            "description": r.get("description"),
            "weight": r.get("weight"),
            "source_refs": r.get("source_refs") or [],
            "evaluation_weight": criterion.get("weight") if criterion else None,
            "minimum_score": criterion.get("threshold") if criterion else None,
            "response_guideline": rg,
        })

    return {
        "section_title": section.get("title"),
        "section_guidance": section.get("notes") or "",
        "section_text": section_text or "",
        "word_limit": section.get("word_limit"),
        "requirements": req_bundle,
        "qualification_mechanisms": qualification_mechanisms,
        "tie_break_rules": tie_break_rules,
        "buyer_intelligence": raw.buyer_intelligence if raw else None,
        "procurement_basis": {
            "procurement_truth_status": basis.get("procurement_truth_status"),
            "procurement_revision": basis.get("procurement_revision"),
            "advisory_intelligence_available": raw is not None,
            "advisory_unavailable_reason": basis.get("raw_snapshot_unavailable_reason"),
        },
    }


# ---------------------------------------------------------------------------
# Idempotency (instruction 19): no duplicate provider calls / review rows
# for the same analytical state.
# ---------------------------------------------------------------------------

def find_matching_review(bid_id: int, section_id: int, current_hash: str,
                         mapped_requirement_ids: list[int], basis: dict) -> dict | None:
    """An existing review is reusable (no new model call needed) only when
    EVERY input that would change its answer is unchanged: the exact
    section text, the exact mapped-requirement set, and the exact
    procurement basis it was run against. Returns the most recent such
    review, or None if a genuinely new call is needed. This is the same
    predicate is_section_review_stale() uses, inverted -- "not stale" and
    "safe to reuse instead of re-calling the model" are the same
    condition."""
    reviews = db.get_section_reviews(bid_id, section_id)
    mapped_set = set(mapped_requirement_ids)
    for review in reviews:  # most recent first (get_section_reviews orders desc)
        if not is_section_review_stale(review, current_hash, mapped_set, basis):
            return review
    return None


def is_section_review_stale(review: dict, current_hash: str, current_mapped_ids: set[int],
                            basis: dict) -> bool:
    """A review is STALE (instruction 12) when ANY of: the section content
    changed, the mapped-requirement set changed, the procurement revision
    changed, or the procurement truth basis changed materially (governed
    <-> ungoverned, or advisory-snapshot availability flipped)."""
    if review.get("section_content_hash") != current_hash:
        return True
    if set(review.get("mapped_requirement_ids") or []) != set(current_mapped_ids):
        return True
    if review.get("based_on_procurement_revision") != basis.get("procurement_revision"):
        return True
    if review.get("based_on_procurement_truth_status") != basis.get("procurement_truth_status"):
        return True
    review_had_snapshot = review.get("based_on_analysis_result_id") is not None
    basis_has_snapshot = basis.get("raw_snapshot") is not None
    if review_had_snapshot != basis_has_snapshot:
        return True
    return False


# ---------------------------------------------------------------------------
# The model call -- ONE primary call, one bounded recovery retry
# (instruction 14). No 20-call mini Fast Analysis pipeline.
# ---------------------------------------------------------------------------

_ANALYZER_SYSTEM = (
    "You are a formative proposal-section reviewer. Your job is to tell a "
    "proposal writer, EARLY, whether the CURRENT DRAFT of one section is "
    "heading in the right direction against the buyer's actual requirements "
    "-- not whether the whole proposal is submission-ready (a separate, "
    "later, holistic audit does that). "
    "Derive every conclusion strictly from the section text and procurement "
    "context you are given -- never invent a procurement requirement, a "
    "buyer preference, or bidder evidence the text does not contain, never "
    "fabricate an example and present it as real, and never convert Buyer "
    "Intelligence (external context) into a stated evaluation requirement. "
    "If evidence is absent, say so plainly. If you lack enough context to "
    "assess something, say CANNOT_ASSESS or INSUFFICIENT_CONTEXT rather than "
    "guessing. Never predict a numeric score (e.g. 'you will score 8/10') -- "
    "only report a buyer's own stated weight/minimum-score facts verbatim "
    "when given. Never claim a competitor cannot do something -- you may "
    "only say a statement 'could be made by most suppliers'."
    # Phase 5B: the generic "respond with valid JSON only" directive
    # removed here is exact-redundancy, not lost meaning -- the user
    # prompt's own instructions_block already states it more specifically
    # ("Return ONLY valid JSON in exactly this shape:") immediately before
    # the schema it introduces. See tests/test_request_profiling.py's
    # TestSectionAnalyzerComponentExposure for the equivalence proof.
)


def _analyzer_prompt(context: dict, *, return_components: bool = False):
    """Builds the Section Analyzer user prompt. `return_components=True`
    additionally returns the named blocks the prompt is assembled from,
    for offline request-size profiling (Phase 5A) -- it changes nothing
    about the returned prompt string itself; every caller that doesn't
    pass it gets byte-identical behavior to before this parameter existed
    (see tests/test_request_profiling.py's equivalence test)."""
    reqs_block = "\n".join(
        f"- requirement_id={r['requirement_id']} req_id={r['req_id']!r} category={r['category']!r}\n"
        f"  buyer wording: {r['description']}\n"
        f"  evaluation weight: {r['evaluation_weight'] or 'not stated'}; "
        f"minimum score: {r['minimum_score'] or 'not stated'}\n"
        f"  response guideline: {r['response_guideline'] or 'none matched'}"
        for r in context["requirements"]
    ) or "(no requirements are mapped to this section)"

    qual_block = "\n".join(
        f"- {o.get('semantic_kind')}: {o.get('original_value')}" for o in context["qualification_mechanisms"]
    ) or "(none identified)"
    tie_block = "\n".join(
        f"- rank {o.get('rank')}: {o.get('original_value')}" for o in context["tie_break_rules"]
    ) or "(none identified)"
    buyer_intel = context.get("buyer_intelligence") or {}
    buyer_block = "\n".join(
        f"- {f.get('detail')} (source: {f.get('source')})" for f in (buyer_intel.get("verified_facts") or [])
    ) or "(no Buyer Intelligence available)"

    basis = context["procurement_basis"]
    basis_note = (
        f"Procurement truth status: {basis['procurement_truth_status']}. "
        f"Advisory (Fast Analysis) intelligence available: {basis['advisory_intelligence_available']}"
        + (f" (unavailable: {basis['advisory_unavailable_reason']})" if not basis["advisory_intelligence_available"] else ".")
    )

    section_block = f"""=== SECTION BEING REVIEWED ===
Title: {context['section_title']}
Guidance/scope note: {context['section_guidance'] or '(none)'}
Word-count target: {context['word_limit'] or 'not set'}

--- CURRENT DRAFT TEXT (exactly as the writer has it right now) ---
{context['section_text'] or '(section is currently empty)'}
--- END DRAFT TEXT ---"""

    requirements_block = f"""=== PROCUREMENT REQUIREMENTS MAPPED TO THIS SECTION ===
{basis_note}
{reqs_block}

=== MANDATORY / QUALIFICATION MECHANICS (advisory, from Fast Analysis; may be unrelated to this specific section) ===
{qual_block}

=== TIE-BREAK RULES (advisory, from Fast Analysis) ===
{tie_block}"""

    buyer_intelligence_block = f"""=== EXTERNAL BUYER CONTEXT (advisory only -- NEVER an evaluation requirement) ===
{buyer_block}"""

    instructions_block = """Return ONLY valid JSON in exactly this shape:
{
  "direction": "ON_TRACK|NEEDS_ADJUSTMENT|HIGH_RISK|INSUFFICIENT_CONTEXT",
  "summary": "<what this section currently communicates: what it tries to prove, what an evaluator can verify, what they'd still have to infer -- 2-4 sentences, analysis not a claim about the buyer's mental state>",
  "requirement_assessments": [
    {"requirement_id": <int, must be one of the requirement_ids above>, "criterion": "<short label>",
      "status": "COVERED|PARTIAL|MISSING|CONTRADICTED|CANNOT_ASSESS",
      "section_evidence": ["<short quote/paraphrase from the draft text, or empty if none>"],
      "gap": "<what's missing, or empty if COVERED>", "recommended_action": "<actionable next step>",
      "dependency": "IN_SECTION|CROSS_REFERENCE_NEEDED|OWNED_BY_OTHER_SECTION|GLOBAL_REQUIREMENT"}
  ],
  "response_guideline_assessments": [
    {"guideline": "<RG id>", "prompt": "<the evidence prompt>", "status": "ANSWERED|PARTIAL|NOT_ANSWERED",
      "section_evidence": ["..."], "recommended_action": "..."}
  ],
  "evidence_assessment": {"strong_evidence": ["<concrete, named, quantified points actually in the text>"],
    "unsupported_claims": ["<assertions with no supporting evidence in the text>"],
    "missing_evidence": ["<evidence referenced but not actually supplied>"]},
  "clarity_and_structure": ["<specific usability issues: buried answers, long generic intros, repetition, evidence separated from claims -- or empty list if none>"],
  "differentiation": [
    {"statement": "<a claim from the text>", "assessment": "SPECIFIC|GENERIC|UNSUPPORTED|DIFFERENTIATED"}
  ],
  "buyer_context": [
    {"external_fact": "<a Buyer Intelligence signal actually given above>", "implication": "<analytical implication for THIS section, clearly separate from the fact itself>", "source": "<source>"}
  ],
  "top_changes": ["<3-5 highly actionable, specific next changes -- never more than 5, never generic filler>"]
}
Rules: requirement_assessments must cover every requirement_id listed above, no more, no fewer. A requirement whose subject matter belongs to a different proposal section (e.g. pricing detail inside a technical-approach section) must be marked with dependency OWNED_BY_OTHER_SECTION or CROSS_REFERENCE_NEEDED, never MISSING, purely because it belongs elsewhere. If response guidelines were shown above, include one response_guideline_assessments entry per guideline shown; otherwise return an empty list. Never include more than 5 top_changes."""

    prompt = (section_block + "\n\n" + requirements_block + "\n\n"
             + buyer_intelligence_block + "\n\n" + instructions_block)
    if return_components:
        return prompt, {
            "section": section_block,
            "requirements": requirements_block,
            "buyer_intelligence": buyer_intelligence_block,
            "instructions": instructions_block,
        }
    return prompt


def _validate_review_json(parsed: dict, expected_requirement_ids: set[int]) -> bool:
    if not isinstance(parsed, dict):
        return False
    if parsed.get("direction") not in DIRECTIONS:
        return False
    if not isinstance(parsed.get("requirement_assessments"), list):
        return False
    for ra in parsed["requirement_assessments"]:
        if not isinstance(ra, dict) or ra.get("status") not in _REQ_STATUSES:
            return False
    if not isinstance(parsed.get("response_guideline_assessments"), list):
        return False
    for rga in parsed["response_guideline_assessments"]:
        if not isinstance(rga, dict) or rga.get("status") not in _RG_STATUSES:
            return False
    if not isinstance(parsed.get("top_changes"), list) or len(parsed["top_changes"]) > 5:
        return False
    return True


def _reconcile_requirement_ids(parsed: dict, expected_requirement_ids: set[int]) -> dict:
    """Never trust the model's own requirement_id references blindly (same
    discipline as analyst.py's _aggregate_requirement_coverage): drop any
    assessment referencing a requirement_id we did not actually send."""
    parsed["requirement_assessments"] = [
        ra for ra in parsed["requirement_assessments"]
        if ra.get("requirement_id") in expected_requirement_ids
    ]
    return parsed


def _call_section_analyzer(prompt: str, expected_requirement_ids: set[int],
                           max_tokens: int = 3000, *, bid_id: int | None = None,
                           section_id: int | None = None) -> tuple[dict | None, str | None]:
    """ONE attempt plus ONE bounded retry (instruction 14) -- mirrors
    analyst.py's _call_alignment_chunk exactly. Returns (validated dict,
    None) or (None, failure_category).

    Each attempt is attributed to workflow="section_analyzer",
    operation="formative_review" via config.execute_messages_create's
    `telemetry_context` (Phase 4) -- this never adds a call; the normal
    path is still exactly one model call, with the retry attributed as
    retry_number=1 on the (at most one) second attempt."""
    last_category = _CALL_FAILURE_UNKNOWN
    for _attempt in range(2):
        try:
            client = get_anthropic_client()
            response = execute_messages_create(
                client, model=_MODEL, max_tokens=max_tokens,
                system=_ANALYZER_SYSTEM, messages=[{"role": "user", "content": prompt}],
                telemetry_context={"workflow": "section_analyzer", "operation": "formative_review",
                                   "bid_id": bid_id, "document_id": str(section_id) if section_id else None},
                retry_number=_attempt,
            )
            raw = response.content[0].text.strip()
        except Exception as exc:
            last_category = classify_anthropic_error(exc).get("category", _CALL_FAILURE_API_ERROR)
            continue
        try:
            from analyst import _parse_json
            parsed = _parse_json(raw)
        except Exception:
            last_category = _CALL_FAILURE_PARSE_ERROR
            continue
        if not _validate_review_json(parsed, expected_requirement_ids):
            last_category = _CALL_FAILURE_MALFORMED_RESPONSE
            continue
        return _reconcile_requirement_ids(parsed, expected_requirement_ids), None
    return None, last_category


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def analyze_section(bid_id: int, section: dict, section_text: str,
                    mapped_requirement_ids: list[int],
                    created_by_user_id: str | None = None) -> dict:
    """The one entry point. `section_text` MUST be the caller's CURRENT
    editor text (instruction 2/18) -- this function never re-fetches
    section content from the database, so it cannot accidentally analyze a
    stale saved value.

    Returns the persisted section_reviews row (a NEW one, or a matching
    existing one reused via the idempotency guard -- instruction 19).
    Raises SectionAnalyzerError on a failure that survived the bounded
    retry; never persists a false/partial review (instruction 20)."""
    mapped_requirements = db.get_requirements_by_ids(bid_id, mapped_requirement_ids)
    basis = procurement_basis(bid_id)
    current_hash = content_hash(section_text)

    existing = find_matching_review(bid_id, section["id"], current_hash, mapped_requirement_ids, basis)
    if existing is not None:
        return existing

    context = build_section_context(section, section_text, mapped_requirements, basis)
    expected_ids = {r["id"] for r in mapped_requirements}
    prompt = _analyzer_prompt(context)
    parsed, failure = _call_section_analyzer(prompt, expected_ids, bid_id=bid_id, section_id=section["id"])
    if parsed is None:
        raise SectionAnalyzerError(failure, "Section analysis failed after a bounded retry.")

    row = db.create_section_review({
        "bid_id": bid_id,
        "section_id": section["id"],
        "section_content_snapshot": section_text or "",
        "section_content_hash": current_hash,
        "mapped_requirement_ids": sorted(mapped_requirement_ids),
        "based_on_procurement_revision": basis.get("procurement_revision"),
        "based_on_procurement_truth_status": basis.get("procurement_truth_status"),
        "based_on_analysis_run_id": basis.get("raw_snapshot_run_id"),
        "based_on_analysis_result_id": basis.get("raw_snapshot_result_id"),
        "raw_snapshot_schema_version": FAST_ANALYSIS_RAW_SNAPSHOT_SCHEMA_VERSION if basis.get("raw_snapshot") else None,
        "review_schema_version": SECTION_REVIEW_SCHEMA_VERSION,
        "direction": parsed["direction"],
        "review_result": parsed,
        "created_by_user_id": created_by_user_id,
    })
    if not row:
        raise SectionAnalyzerError("PERSISTENCE_FAILED", "Review was computed but could not be durably saved.")
    return row
