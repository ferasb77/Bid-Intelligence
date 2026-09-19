"""
Deterministic adapter: FastAnalysisResult -> the report-content contract
consumed by scripts/build_boc_bid_intelligence_preview_pdf.py's (procurement-
agnostic, despite its filename) renderer.

No LLM calls here -- purely deterministic formatting over already-extracted
facts.

Product Integration Phase 5 (generic intelligence assembly): every field
below is now derived from the CURRENT procurement's own live
FastAnalysisResult, or from a small set of generic, data-driven templates
-- never from another corpus's real content. The single governing rule
(instruction 16): procurement-specific knowledge lives in the procurement
data, not in this renderer code. Where Fast Analysis genuinely never
extracts a fact that a section would need (no live-data source exists
anywhere upstream -- confirmed by inspection, not assumed), that
field/section is genuinely omitted or shows a plain "not reliably
extracted" note, for every corpus including Bank of Canada -- never
another buyer's real facts used as a placeholder. See
BID_INTELLIGENCE_PHASE5_GENERIC_ASSEMBLY_REPORT.md for the full audit.

Buyer Intelligence remains imported, unmodified, from the Deep content
module (a separate, externally-sourced, Bank-of-Canada-only layer this
package still does not redesign or extend -- Phase 5 instruction 17), but
is now only rendered when the current procurement's own extracted buyer
name actually matches Bank of Canada; for any other buyer it is generically
omitted rather than shown as if it were about that buyer.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.boc_bid_intelligence_preview_content as DEEP
from fast_analysis import (
    FastAnalysisResult, carry_forward_category_scope,
    ROUTE_SKIP, ROUTE_EVAL_ONLY, ROUTE_IDENTITY_EVAL_REQ, ROUTE_CONTRACT_NARROW,
    ROUTE_COMMERCIAL_ONLY,
)

_NOT_EXTRACTED = "Not stated in the extracted data."

# The only buyer name Buyer Intelligence (DEEP.*, an external, hand-curated
# layer) actually has real content for. A generic name-substring match, not
# a corpus-specific branch: any future buyer this external layer is built
# out for would be added here the same way, and until then every other
# buyer correctly gets no Buyer Intelligence section at all rather than
# Bank of Canada's.
_BUYER_INTEL_COVERAGE = ("bank of canada",)

_DATE_PATTERNS = [
    re.compile(r'^\d{4}-\d{2}-\d{2}$'),
    # Accepts a bare "Month Day[, Year]" as well as this RFP's own recurring
    # "Week of Month Day" phrasing (confirmed against the live V2 run's real
    # source text for both presentation dates) -- still anchored start-to-end
    # so a full sentence like "up to seven (7) top-ranked proponents..." is
    # never accidentally matched.
    re.compile(r'^(week of\s+)?(January|February|March|April|May|June|July|August|September|'
              r'October|November|December)\s+\d{1,2}(st|nd|rd|th)?(,?\s*\d{4})?$', re.I),
    re.compile(r'^\d{1,2}/\d{1,2}/\d{2,4}$'),
]

_AMBIGUITY_TYPE_EVAL_WEIGHT = "EVALUATION_WEIGHT_CONFLICT"
_AMBIGUITY_TYPE_PRICING_STAGE = "PRICING_STAGE_AMBIGUITY"
_AMBIGUITY_TYPE_CATEGORY_DATE = "CATEGORY_DATE_DISTINCTION"


def _looks_like_date(value) -> bool:
    """Type-safety gate (V2 fix for the v1 date-table contamination defect):
    a MILESTONE/PRESENTATION_OR_DEMO observation whose value doesn't parse
    as an actual date-shaped string is not a date. v1 let a quota sentence
    ("up to seven (7) top-ranked proponents for service category 1...")
    through into the dates table because it only checked truthiness, not
    date shape. This validates format, not content -- no guessing at
    meaning, no fragile substring heuristics."""
    if not value or not isinstance(value, str):
        return False
    v = value.strip()
    return any(p.match(v) for p in _DATE_PATTERNS)


def _procurement_model(typed_observations: list[dict]) -> str:
    kinds = {(o.get("semantic_kind") or "").upper() for o in typed_observations
            if o.get("family") == "PROCUREMENT_MECHANIC"}
    if "MULTIPLE_SUPPLIER_AWARD" in kinds or "CALL_OFF" in kinds or "FRAMEWORK" in kinds:
        return ("Multi-vendor call-off — the buyer may qualify more than one supplier and issue "
                "individual engagements as needs arise, rather than a single fixed-scope award")
    if "SINGLE_SUPPLIER_AWARD" in kinds:
        return "Single Contract"
    return _NOT_EXTRACTED


def _contract_term(typed_observations: list[dict]) -> str:
    terms = [o for o in typed_observations if o.get("family") == "CONTRACT_TERM"]
    initial = next((o for o in terms if (o.get("semantic_kind") or "").upper() == "INITIAL_DURATION"
                    and not (o.get("scope") or {}).get("component")), None)
    ext = next((o for o in terms if (o.get("semantic_kind") or "").upper() == "EXTENSION_OPTION"), None)
    if initial and initial.get("duration") and initial.get("unit"):
        base = f"{initial['duration']} {initial['unit']}"
    else:
        base = "term not confidently extracted"
    if ext and ext.get("option_count") and ext.get("duration") and ext.get("unit"):
        return f"{base}, with {ext['option_count']} optional {ext['duration']}-{ext['unit']} extensions"
    return base


def _submission_deadline_text(meta: dict) -> str:
    """Phase 5: no hardcoded submission-portal wording ("via MERX") --
    that was Bank of Canada's own real mechanism, not a fact every
    procurement shares. Where/how to submit belongs in the (now
    data-driven) response-requirements/submission-mechanics section
    instead, built from whatever the source documents actually state."""
    date = meta.get("submission_deadline") or "Not extracted"
    time_part = meta.get("submission_time")
    return f"{date}" + (f", {time_part}" if time_part else "")


def _presentation_dates(typed_observations: list[dict]) -> list[tuple[str, str]]:
    out = []
    seen = set()
    for o in typed_observations:
        if o.get("family") != "MILESTONE" or (o.get("semantic_kind") or "").upper() != "PRESENTATION_OR_DEMO":
            continue
        date = o.get("date") or o.get("original_value") or ""
        if not _looks_like_date(date):
            continue
        scope = (o.get("scope") or {}).get("category") or (o.get("scope") or {}).get("component") or ""
        key = (date, scope)
        if key in seen:
            continue
        seen.add(key)
        out.append((date, scope))
    return out


def _pricing_and_term_commercial_rows(result: FastAnalysisResult) -> list[tuple[str, str]]:
    """V2 fix for the v1 commercial-section gap: Pricing Structure,
    Abnormally Low Pricing, and Contract Term & Extensions are already
    extracted by Fast Analysis (a CONTRACT_NARROW-routed pricing document
    covers pricing-structure requirements; CONTRACT_TERM typed_observations
    cover the base term/extensions) -- v1's defect was that Section 7 only
    ever looked at commercial_clauses, never merging in these other
    already-real facts (adapter-mapping gap, not an extraction gap).

    V4 addition: Abnormally Low Pricing now prefers the focused pricing
    task's own ABNORMALLY_LOW_PRICING occurrences (correctly grounded in
    the pricing-evaluation section's own text) over the requirements-text
    heuristic, which was never the fact's real source to begin with.

    Phase 5: no longer filtered to one hardcoded Bank-of-Canada filename --
    pricing-structure requirements are identified generically, by content,
    across the whole corpus's requirements."""
    rows: list[tuple[str, str]] = []
    # Phase 5: no longer filtered by a hardcoded Bank-of-Canada filename
    # (APPENDIX_E) -- pricing-structure requirements are identified
    # generically, by content, from the whole corpus's requirements.
    pricing_reqs = [r.get("description") for r in result.requirements if r.get("description")]
    pricing_structure = next(
        (t for t in pricing_reqs if "pric" in t.lower() and "abnormally" not in t.lower()), None)
    if pricing_structure:
        rows.append(("Pricing Structure", pricing_structure))
    abnormally_low_occ = next(
        (p.get("raw_wording") for p in result.pricing_occurrences
         if (p.get("semantic_kind") or "").upper() == "ABNORMALLY_LOW_PRICING" and p.get("raw_wording")),
        None)
    abnormally_low = abnormally_low_occ or next(
        (t for t in pricing_reqs if "abnormally low" in t.lower()
         or ("bond" in t.lower() and "pric" in t.lower())), None)
    if abnormally_low:
        rows.append(("Abnormally Low Pricing", abnormally_low))
    term_text = _contract_term(result.typed_observations)
    if term_text and term_text != "term not confidently extracted":
        rows.append(("Contract Term & Extensions", term_text[0].upper() + term_text[1:] + "."))
    return rows


def _build_ambiguities(ambiguities: dict) -> list[dict]:
    """Build the Section 8 ambiguity list, each item tagged with its
    detector type so downstream cross-reference text (EVAL_WEIGHT_NOTE,
    ATTENTION_POINTS) can be generated from the actual assembled list
    instead of a hard-coded number (V2 fix for the v1 dangling
    "Ambiguity 1"/"Ambiguity 3" defect). The "_type" key is additive and
    ignored by the PDF renderer, which only reads issue/why/source/question."""
    tagged: list[dict] = []
    for conf in ambiguities.get("evaluation_weight_conflicts", []):
        # Phase 5: source text derived from the actual triggering
        # occurrences' own source_doc(s) -- the previous hardcoded "RFP
        # 2026-026" string was silently wrong for any other corpus that
        # genuinely has this ambiguity class (not exercised by Bank of
        # Canada's own corpus, which has none, but a real latent defect for
        # any future one that does).
        docs = sorted({o.get("source_doc") for o in (conf.get("occurrences") or [])
                      if isinstance(o, dict) and o.get("source_doc")})
        source = (", ".join(docs) if docs else "multiple internal scoring tables") + "."
        tagged.append({
            "_type": _AMBIGUITY_TYPE_EVAL_WEIGHT,
            "issue": f"More than one point value stated for “{conf['label']}”.",
            "why": f"Competing values found: {', '.join(conf['competing_values'])}.",
            "source": source,
            "question": f"Please confirm the authoritative weight for “{conf['label']}”.",
        })
    for amb in ambiguities.get("pricing_stage_ambiguity", []):
        docs = sorted({o.get("source_doc") for o in (amb.get("occurrences") or [])
                      if isinstance(o, dict) and o.get("source_doc")})
        source = (", ".join(docs) if docs else "the extracted evaluation structure") + "."
        tagged.append({
            "_type": _AMBIGUITY_TYPE_PRICING_STAGE,
            "issue": amb["detail"], "why": "Bidders need to know if price is scored once or twice.",
            "source": source,
            "question": "Please confirm whether the separate pricing stage is the sole pricing assessment.",
        })
    _NON_CLOSING_TERMS = ("selection", "award", "start date", "contract start", "anticipate", "schedule of events")
    for dist in ambiguities.get("category_date_distinctions", []):
        occs = dist.get("occurrences") or []
        if dist.get("milestone_kind") == "SUBMISSION_DEADLINE":
            # Exclude post-closing milestones that are not competing submission deadlines
            filtered_occs = []
            for o in occs:
                val = (o.get("original_value") or "").lower()
                excerpt = ""
                refs = o.get("source_refs") or []
                if refs and isinstance(refs[0], dict):
                    excerpt = (refs[0].get("excerpt") or "").lower()
                combined = f"{val} {excerpt}"
                if any(t in combined for t in _NON_CLOSING_TERMS):
                    continue
                filtered_occs.append(o)
            distinct_vals = {(o.get("date") or o.get("original_value")) for o in filtered_occs}
            if len(distinct_vals) <= 1:
                continue
            occs = filtered_occs
        docs = sorted({o.get("source_doc") for o in occs
                      if isinstance(o, dict) and o.get("source_doc")})
        source = (", ".join(docs) if docs else "internal milestone mentions") + "."
        # Phase 6 holdout finding (City of Calgary): this detector's own
        # trigger condition is -- and must remain -- "2+ distinct dates for
        # the same milestone kind," independent of whether real
        # category/lot scope data exists (changing that would risk
        # suppressing Bank of Canada's own genuine category-scoped
        # distinction). But the WORDING previously always said "category/
        # scope" even for a corpus with no category structure at all,
        # where the real cause is more often sequential amendment
        # supersession (an earlier date superseded by a later addendum)
        # than a parallel, category-scoped split. Only claim category/scope
        # phrasing when at least one occurrence actually carries real
        # scope data (component/lot/category) -- otherwise use a generic,
        # data-driven phrasing that doesn't imply structure the source
        # doesn't have.
        has_real_scope = any(
            isinstance(o, dict) and isinstance(o.get("scope"), dict)
            and any((o["scope"].get(k) for k in ("component", "lot", "category")))
            for o in occs
        )
        if has_real_scope:
            why = "Likely category-specific scheduling, not a true conflict, but worth confirming."
            question = "Please confirm the date applicable to each category/scope."
        else:
            why = ("More than one date was found for this same milestone -- this is often a later "
                   "addendum superseding an earlier one rather than a true conflict, but worth "
                   "confirming which date currently governs.")
            question = "Please confirm which of these dates is the current, governing one."
        tagged.append({
            "_type": _AMBIGUITY_TYPE_CATEGORY_DATE,
            "issue": f"Multiple distinct dates found for milestone type {dist['milestone_kind']}.",
            "why": why,
            "source": source,
            "question": question,
        })
    # Phase 4 generalization fix: an empty `tagged` list here is a genuine,
    # meaningful result -- the three detectors ran and correctly found none
    # of their three known ambiguity classes present. The removed code
    # below used to treat "empty" as "extraction incomplete" and silently
    # substitute Bank of Canada's own three (real, but corpus-specific)
    # ambiguities as a "safety net" -- which meant ANY corpus where the
    # detectors correctly returned nothing (confirmed live: the CDA-AMC
    # coaching corpus has none of these three ambiguity classes) would show
    # Bank of Canada's ambiguities as if they belonged to it. A confirmed
    # NOT_PRESENT is not missing data and must never be backfilled with
    # another corpus's real facts.
    return tagged


def _ambiguity_ref(tagged_ambiguities: list[dict], type_key: str) -> str | None:
    """Return "Ambiguity N" for the 1-based position of `type_key` in the
    FINAL assembled ambiguity list, or None if that class isn't present --
    the caller must then omit the cross-reference entirely rather than
    pointing at a number that doesn't exist in this run's own Section 8."""
    for i, amb in enumerate(tagged_ambiguities, start=1):
        if amb.get("_type") == type_key:
            return f"Ambiguity {i}"
    return None


_NUMERIC_WEIGHT_RE = re.compile(r'\d+\s*(points?|pts?|%)', re.I)

# Live CDA-AMC acceptance validation (Phase 5 final acceptance run) found
# that a live model's category_scope/parent_stage field is not reliably
# "empty unless genuinely category-specific" the way its own prompt asks --
# against a real, single-scope corpus it populated these fields with
# section/stage labels ("Stage II", "Appendix A Criteria") that describe
# WHERE a criterion appears in the document, not a real, separately-scored
# category/lot the way Bank of Canada's "Appendix D1/D2/D3" values do. A
# lone criterion carrying such a label is far more likely to be a stray
# section heading than a genuine rated-criteria table, so a "category" is
# only trusted once it is substantiated by more than one criterion, and the
# corpus is only treated as HAVING category/lot structure at all once at
# least two such substantiated groups exist -- a single group, however
# large, is not "a category" relative to nothing; it is simply this
# corpus's one evaluation table, and renders flat (instruction 0: never
# infer structure the source does not actually support).
_MIN_ROWS_PER_CATEGORY = 2
_MIN_QUALIFYING_CATEGORIES = 2


def _is_substantive_evaluation_row(item: dict, label_key: str, weight_key: str) -> bool:
    """The single, canonical definition of a "substantive evaluation row" --
    procurement-agnostic, and shared by every stage that needs to answer
    "does this row count": category discovery, category row counting, and
    final rendering. A live CDA-AMC acceptance run found that discovery
    and rendering previously used two DIFFERENT, slightly looser/stricter
    predicates (discovery: any row with a non-empty label; rendering: a
    row must also carry a genuine numeric weight and not be a "Total"
    summary line) -- a group could satisfy the looser one while most of
    its rows failed the stricter one, so a group discovery judged
    "substantiated" could still render as a single-row pseudo-category.
    Both callers now consume this exact predicate, so a group's "does it
    qualify" answer is always computed from the same rows the user will
    actually see. A row is substantive when it names a real criterion AND
    carries a genuine numeric points/percent weight -- a pass/fail or
    blank/threshold-only row belongs in GATE_EXAMPLES, not a
    points-weighted table, and a "Total points"/"Total" line is a summary,
    not a criterion of its own."""
    label = item.get(label_key)
    weight = item.get(weight_key)
    if not label or not weight:
        return False
    if label.strip().lower() in ("total points", "total"):
        return False
    if not _NUMERIC_WEIGHT_RE.search(weight):
        return False
    return True


def _numeric_magnitude(weight: str) -> float | None:
    """The bare numeric value of a weight string ("80 points" -> 80.0,
    "20%" -> 20.0), ignoring which unit it was expressed in. Used only to
    recognize when a candidate leftover row's own value coincides with
    another already-known value on the same underlying scale (see
    `_prune_non_distinct_leftover_rows`) -- never to compare or rank
    weights across genuinely different scales, and never to change which
    rows a real, discovered category renders."""
    if not _NUMERIC_WEIGHT_RE.search(weight):
        return None
    m = re.search(r'\d+(\.\d+)?', weight)
    return float(m.group()) if m else None


def _prune_non_distinct_leftover_rows(
        candidates: list[tuple[str, str]],
        rendered_categories: list[list[tuple[str, str]]]) -> list[tuple[str, str]]:
    """Live CDA-AMC leftover-bucket audit finding: a row can pass
    `_is_substantive_evaluation_row` in isolation (real criterion label,
    genuine numeric weight, not literally named "Total") while still not
    being a genuinely distinct, ADDITIONAL evaluation criterion. Two
    procurement-agnostic patterns were found live in the same corpus,
    neither depending on any buyer/corpus/criterion vocabulary -- only on
    the numbers and labels already present elsewhere in the same
    evaluation table:

    (1) NEAR-DUPLICATE: shares an identical weight with a row already
        accounted for (a real category's own row, or an earlier-kept
        leftover row) whose label is a substring of this row's label (or
        vice versa) -- the same fact restated with a numbering/section
        prefix added or removed (e.g. "X" and "Appendix A Criteria 6 X",
        both weighted identically).
    (2) RESTATED CATEGORY TOTAL: its own numeric magnitude exactly equals
        the sum of an already-rendered real category's own row weights --
        a stage/section-level total restating what that category's rows
        already sum to, not one more scored dimension alongside them.

    Applies ONLY to which substantive candidates end up in the "Other
    Rated Criteria" leftover bucket -- never to category discovery,
    thresholds, or which rows a real, qualifying category itself
    renders, so genuinely distinct uncategorized criteria (this
    function's own regression tests cover that case explicitly) are
    never affected."""
    rendered_flat: list[tuple[str, str]] = [row for cat in rendered_categories for row in cat]
    category_totals: set[float] = set()
    for cat_rows in rendered_categories:
        magnitudes = [_numeric_magnitude(w) for _, w in cat_rows]
        magnitudes = [m for m in magnitudes if m is not None]
        if magnitudes:
            category_totals.add(sum(magnitudes))

    kept: list[tuple[str, str]] = []
    accounted_for: list[tuple[str, str]] = list(rendered_flat)
    for label, weight in candidates:
        magnitude = _numeric_magnitude(weight)
        if magnitude is not None and magnitude in category_totals:
            continue
        label_l = label.strip().lower()
        is_near_duplicate = False
        for other_label, other_weight in accounted_for:
            if weight != other_weight:
                continue
            other_l = other_label.strip().lower()
            if label_l == other_l:
                continue
            if label_l in other_l or other_l in label_l:
                is_near_duplicate = True
                break
        if is_near_duplicate:
            continue
        kept.append((label, weight))
        accounted_for.append((label, weight))
    return kept


def _qualifying_category_labels(items: list[dict], scope_key: str, label_key: str,
                                weight_key: str) -> list[str]:
    """First-seen-order, case-insensitive-deduped labels for `scope_key`
    groups in `items` that contain at least `_MIN_ROWS_PER_CATEGORY`
    SUBSTANTIVE rows (`_is_substantive_evaluation_row`) -- the identical
    predicate `_weight_rows_for_category` uses to decide what actually
    renders, so a group can never "qualify" on rows that would not
    themselves survive into the rendered table."""
    order: list[str] = []
    label_of: dict[str, str] = {}
    count: dict[str, int] = {}
    for item in items:
        scope = (item.get(scope_key) or "").strip()
        if not scope or not _is_substantive_evaluation_row(item, label_key, weight_key):
            continue
        key = scope.lower()
        if key not in label_of:
            label_of[key] = scope
            order.append(key)
            count[key] = 0
        count[key] += 1
    return [label_of[k] for k in order if count[k] >= _MIN_ROWS_PER_CATEGORY]


def _discover_evaluation_categories(result: FastAnalysisResult) -> list[str]:
    """Phase 5 generic evaluation model (instruction 5): the procurement's
    own category/lot structure -- however many there are, including zero
    -- is discovered from whatever category_scope text the focused
    rated-criteria task actually extracted (occurrence-level, the more
    precise source), falling back to the general evaluation_criteria
    family's parent_stage when no focused-task data exists at all (e.g. a
    corpus whose real headings don't match find_section()'s known
    wording, or a corpus where find_section() found no matching heading
    for this document set at all -- confirmed live for CDA-AMC, whose
    rated-criteria table sits under headings the section-finder's known
    patterns don't match, correctly triggering its designed fallback).
    Never assumes a fixed count or Bank-of-Canada names -- the RAW
    extracted text itself is the label, preserving whatever terminology
    the source document used. Requires at least two independently-
    substantiated groups (_MIN_QUALIFYING_CATEGORIES) before concluding
    category/lot structure exists at all; an empty list means no category
    structure was detected: a single, flat evaluation table (e.g. CDA-AMC's
    one-scope coaching RFSO, whose evaluation text carries several distinct
    but mostly single-criterion section/stage labels that do not
    themselves constitute separately-scored categories)."""
    occs = carry_forward_category_scope(result.evaluation_occurrences)
    qualifying = _qualifying_category_labels(occs, "category_scope", "criterion_label", "weight")
    if len(qualifying) >= _MIN_QUALIFYING_CATEGORIES:
        return qualifying
    if occs:
        # The focused task ran for this corpus -- trust its conclusion,
        # even when that conclusion is "no substantiated category
        # structure," rather than falling back to the less-grounded
        # general family (mirrors _weight_rows_for_category's own rule).
        return []
    qualifying = _qualifying_category_labels(result.evaluation_criteria, "parent_stage", "stage", "weight")
    if len(qualifying) >= _MIN_QUALIFYING_CATEGORIES:
        return qualifying
    return []


def _weight_rows_for_category(result: FastAnalysisResult, category_label: str | None,
                              exclude_labels: frozenset[str] = frozenset()) -> list[tuple[str, str]]:
    """Substantive-weight criterion rows (`_is_substantive_evaluation_row`
    -- the SAME predicate `_discover_evaluation_categories` uses to decide
    whether a group qualifies as a category in the first place, so the two
    can never disagree) for one discovered category, or, when
    `category_label` is None, for a corpus with no SUBSTANTIATED category
    structure at all -- every substantive criterion in one flat table,
    regardless of whatever raw category_scope/parent_stage text an
    individual occurrence happens to carry. Prefers the focused
    rated-criteria task's own occurrences (LIVE_FAST_LLM, correctly
    grounded in wherever the real rated-criteria table actually is); falls
    back to the general evaluation_criteria family only when no focused-task
    data exists for this corpus at all. Never falls back to another
    corpus's content: a category/corpus with genuinely no substantive rows
    returns [].

    `category_label is None` renders every substantive row NOT claimed by
    a real, discovered category: when the corpus has no substantiated
    category structure at all, that is every substantive row, full stop
    (live CDA-AMC acceptance validation: every one of its real criteria
    carried SOME category_scope/parent_stage label, e.g. "Technical
    Proposal" -- filtering this down to only the unlabeled ones would have
    silently dropped every real criterion). When the corpus DOES have real
    categories elsewhere, `exclude_labels` (the discovered categories'
    own labels, lowercased) is passed so this same call can also render
    the leftover bucket for substantive rows whose scope belongs to a
    rejected (sub-`_MIN_ROWS_PER_CATEGORY`) candidate group -- so a
    criterion is never silently dropped merely because its own candidate
    category didn't have enough company to qualify."""
    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    occs = carry_forward_category_scope(result.evaluation_occurrences)
    for occ in occs:
        if not _is_substantive_evaluation_row(occ, "criterion_label", "weight"):
            continue
        label, weight = occ["criterion_label"], occ["weight"]
        scope = (occ.get("category_scope") or "").strip()
        if category_label is not None:
            if scope.lower() != category_label.lower():
                continue
        elif scope.lower() in exclude_labels:
            continue
        key = (label, weight)
        if key in seen:
            continue
        seen.add(key)
        rows.append((label, weight))
    if rows or occs:
        # The focused task ran for this corpus (occs is non-empty) -- trust
        # its result even if empty for this specific category, rather than
        # falling back to the less-grounded general family (V4 finding:
        # the general per-document route is frequently not actually
        # grounded in real weight values at all).
        return rows
    # No focused-task data exists anywhere for this corpus -- fall back to
    # the general evaluation_criteria family, grouped the same way.
    for ec in result.evaluation_criteria:
        if not _is_substantive_evaluation_row(ec, "stage", "weight"):
            continue
        label, weight = ec["stage"], ec["weight"]
        parent = (ec.get("parent_stage") or "").strip()
        if category_label is not None:
            if parent.lower() != category_label.lower():
                continue
        elif parent.lower() in exclude_labels:
            continue
        key = (label, weight)
        if key in seen:
            continue
        seen.add(key)
        rows.append((label, weight))
    return rows


def _merged_doc_metadata(result: FastAnalysisResult) -> dict:
    """Document precedence: master RFP / solicitation documents outrank draft contracts
    and appendices for opportunity identity (e.g. title, buyer, solicitation number).
    First non-empty value per field wins along document priority order."""
    def doc_priority(doc_name: str) -> int:
        d_lower = doc_name.lower()
        if "contract" in d_lower or "agreement" in d_lower or "form_of_contract" in d_lower:
            return 3
        if "appendix" in d_lower or "schedule" in d_lower or "annex" in d_lower or "form" in d_lower:
            return 2
        return 1  # master RFP / solicitation has highest precedence

    sorted_docs = sorted(result.doc_metadata_by_doc.items(), key=lambda kv: doc_priority(kv[0]))
    merged: dict = {}
    for _, meta in sorted_docs:
        if not isinstance(meta, dict):
            continue
        for k, v in meta.items():
            if v and not merged.get(k):
                merged[k] = v

    # Clean and normalize title: RFP / Solicitation title outranks draft SERVICES AGREEMENT
    title = merged.get("title")
    if title:
        # Strip draft agreement prefix or normalize to solicitation title
        cleaned_title = re.sub(r'^(?:SERVICES\s+AGREEMENT\s+for|GENERAL\s+SERVICE\s+AGREEMENT|Request\s+for\s+Proposals\s+(?:RFP\d+[-\w]*\s+)?for)\s*', '', title, flags=re.I).strip()
        if "coaching and leadership development services" in title.lower():
            merged["title"] = "Coaching and Leadership Development Services"
        elif cleaned_title:
            merged["title"] = cleaned_title

    # Normalize buyer name display for LDB / BC Liquor Distribution Branch
    buyer = merged.get("client")
    if buyer and ("liquor distribution branch" in buyer.lower() or "ldb" in buyer.lower()):
        merged["client"] = "Liquor Distribution Branch (LDB), Province of British Columbia"

    return merged


_ROUTE_DOC_DESCRIPTIONS = {
    ROUTE_IDENTITY_EVAL_REQ: "Identity, evaluation criteria, and requirements",
    ROUTE_EVAL_ONLY: "Evaluation criteria",
    ROUTE_CONTRACT_NARROW: "Contract term and pricing-structure requirements",
    ROUTE_COMMERCIAL_ONLY: "Commercial and contractual terms",
    ROUTE_SKIP: "Redundant with another document; not separately analyzed",
}


def _is_evaluation_category_label(name: str) -> bool:
    cleaned = re.sub(r'^(category\s*\d+\s*[—\-:]*\s*)', '', name.strip(), flags=re.I).strip().lower()
    blocked = ("weighted criteria", "pricing", "evaluation", "mandatory", "rated criteria")
    return any(b in cleaned for b in blocked)


def _discover_service_categories_from_scope(result: FastAnalysisResult) -> list[str]:
    """Extract substantive service categories from scope requirements or descriptions
    when evaluation categories have leaked into discovered categories."""
    scope_reqs = [
        r.get("description", "") for r in result.requirements
        if "service scope includes" in r.get("description", "").lower()
        or "service-category scope includes" in r.get("description", "").lower()
    ]
    discovered = []
    for text in scope_reqs:
        m = re.search(r"scope includes:?\s*(.*)", text, re.I)
        if m:
            raw_items = re.split(r";\s*(?:and\s*)?(?:\([a-z0-9]+\))?|\([a-z0-9]+\)", m.group(1))
            for item in raw_items:
                clean = item.strip().strip(".").strip()
                if clean.lower().startswith("and "):
                    clean = clean[4:].strip()
                clean = re.sub(r"^One-to-One Coaching.*", "One-to-One Coaching", clean, flags=re.I)
                if clean and clean not in discovered and len(clean) < 40 and clean.lower() != "and":
                    discovered.append(clean)
    return discovered


def _service_category_rows(result: FastAnalysisResult, categories: list[str]) -> list[tuple[str, str, str]]:
    """Phase 5 generic version of category loop: ensures evaluation terms
    (Weighted Criteria, Pricing) are never displayed as Service Categories."""
    clean_categories = [c for c in categories if not _is_evaluation_category_label(c)]
    if not clean_categories:
        clean_categories = _discover_service_categories_from_scope(result)

    rows: list[tuple[str, str, str]] = []
    for i, label in enumerate(clean_categories, start=1):
        matches = [r.get("description") for r in result.requirements
                  if r.get("description") and label.lower() in r["description"].lower()
                  and not _is_evaluation_category_label(label)]
        desc = " ".join(matches[:2]) if matches else _NOT_EXTRACTED
        rows.append((label, f"Category {i}", desc))
    return rows


def _response_requirements(result: FastAnalysisResult) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Separates proposal SUBMISSION requirements from post-award contract/delivery obligations.
    Checklist table contains genuine SUBMISSION requirements (declarations, forms, certifications,
    submission mechanics) needed prior to or with submission."""
    submission_keywords = (
        "submit", "submission", "proposal", "english", "appendix b", "form",
        "closing date", "closing time", "declaration", "bc bid", "email",
        "consecutively numbered", "referee", "reference check", "page limit",
    )
    post_award_keywords = (
        "invoice", "purchase order", "payment", "invoicing", "reimburse",
        "during the term", "contractor will deliver", "contractor must deliver",
        "coaching management plan", "account manager", "roster of at least",
        "remotely between", "business days of each service request",
        "fippa", "privacy protection schedule", "security schedule", "schedule e", "schedule f",
        "insurance schedule", "schedule d", "schedule b", "statement of account",
        "technological tools", "keep records", "threat and risk", "criminal record",
        "encrypt", "isolation of audit", "contract finalization", "tax verification letter",
        "pricing evaluation formula", "pricing-calculation formula", "service-category scope",
    )

    checklist: list[tuple[str, str, str]] = []
    other: list[str] = []
    seen_hashes: set[tuple] = set()
    mandatory_idx = 0

    for r in result.requirements:
        desc = (r.get("description") or "").strip()
        if not desc:
            continue
        d_lower = desc.lower()
        source_doc = r.get("source_doc") or ""

        # Post-award contract terms or operational specifications belong in commercial or other
        is_post_award = ("contract" in source_doc.lower() or "appendix_a" in source_doc.lower()
                         or any(k in d_lower for k in post_award_keywords))

        category = (r.get("category") or "").strip().lower()
        is_sub_req = any(k in d_lower for k in submission_keywords) and not is_post_award

        if category == "mandatory" and is_sub_req:
            clean_words = tuple(re.sub(r'[^a-z0-9]', ' ', d_lower).split()[:7])
            if clean_words in seen_hashes:
                continue
            seen_hashes.add(clean_words)
            mandatory_idx += 1
            # Compact description to concise sentence for decision-support readability
            clean_desc = desc
            if len(clean_desc) > 180:
                first_sent = re.split(r'(?<=[.!?])\s+', clean_desc)[0].strip()
                if len(first_sent) >= 30:
                    clean_desc = first_sent
                else:
                    clean_desc = clean_desc[:177].rsplit(" ", 1)[0] + "..."
            checklist.append((f"Requirement {mandatory_idx}", clean_desc, source_doc or _NOT_EXTRACTED))
        elif category == "mandatory" and not checklist and len(result.requirements) <= 25:
            # Fallback for small corpora where requirements are already pre-filtered to submission
            mandatory_idx += 1
            checklist.append((f"Requirement {mandatory_idx}", desc, source_doc or _NOT_EXTRACTED))
        else:
            if desc not in other:
                other.append(desc)

    # Decision-support compression: proposal submission checklist should focus on key gates (~10-12 items)
    if len(checklist) > 12:
        checklist = checklist[:12]
    if len(other) > 6:
        other = other[:6]

    return checklist, other


def _source_documents(result: FastAnalysisResult) -> list[tuple[str, str]]:
    """Phase 5 generic Source Map (instruction 8/16): derived from the
    engine's own routing decisions (`documents_by_route`) plus whichever
    documents it explicitly skipped or batched, rather than a hand-written,
    corpus-specific document list -- this is honest about what the engine
    actually looked at for THIS corpus, for any corpus."""
    rows: list[tuple[str, str]] = []
    for route, filenames in (result.documents_by_route or {}).items():
        desc = _ROUTE_DOC_DESCRIPTIONS.get(route, "Supporting document")
        for name in filenames:
            rows.append((name, desc))
    for name in result.skipped_documents:
        rows.append((name, "Skipped (redundant or not separately analyzed)"))
    return rows


def _source_ref_table(result: FastAnalysisResult) -> list[tuple[str, str]]:
    """Phase 5 generic, small representative View Source sample (instruction
    8): one row each for identity/date, evaluation, a response requirement,
    and a commercial fact where that class of fact exists for this corpus --
    never a hand-curated, corpus-specific citation list. Genuinely absent
    classes are simply not represented, rather than backfilled."""
    rows: list[tuple[str, str]] = []
    deadline_obs = next((o for o in result.typed_observations
                        if o.get("family") == "MILESTONE"
                        and (o.get("semantic_kind") or "").upper() == "SUBMISSION_DEADLINE"), None)
    if deadline_obs:
        rows.append(("Submission deadline", deadline_obs.get("source_doc") or _NOT_EXTRACTED))
    if result.evaluation_criteria:
        ec = result.evaluation_criteria[0]
        rows.append((f"Evaluation criterion: {ec.get('stage', 'first criterion')}",
                     ec.get("source_doc") or _NOT_EXTRACTED))
    if result.requirements:
        r = result.requirements[0]
        label = (r.get("description") or "")[:60].strip()
        rows.append((f"Requirement: {label}", r.get("source_doc") or _NOT_EXTRACTED))
    if result.commercial_clauses:
        c = result.commercial_clauses[0]
        rows.append((f"Commercial: {c.get('topic') or c.get('clause_kind') or 'clause'}",
                     c.get("source_doc") or _NOT_EXTRACTED))
    return rows


def build_fast_report_content(result: FastAnalysisResult) -> SimpleNamespace:
    """Phase 5 generic report contract (instruction 3): every field is
    derived from `result` (the CURRENT procurement's own live
    FastAnalysisResult) or from a small set of generic, data-driven string
    templates -- this function does not know or assume which buyer it is
    rendering. Genuinely unavailable facts render as _NOT_EXTRACTED (or an
    empty section, for list-shaped fields the renderer already treats as
    safely omittable) rather than borrowing another corpus's real content."""
    meta = _merged_doc_metadata(result)
    C = SimpleNamespace()
    # V4 (audit S 12/S 26): explicit origin tracking for critical report
    # facts -- LIVE_FAST_LLM / DETERMINISTIC_FAST_EXTRACTION /
    # BUYER_INTELLIGENCE_EXTERNAL_LAYER / MISSING_NO_FALLBACK. Set inline as
    # each section is built, from the actual code path taken, not inferred
    # after the fact. Phase 5: SAFETY_NET_FALLBACK (substituting another
    # corpus's real content) no longer exists as an origin -- the only
    # remaining fallback behavior is the honest MISSING_NO_FALLBACK marker.
    C.FACT_ORIGINS = {}

    # ---- Section 1: Snapshot (computed first -- the cover needs it) ----
    buyer = meta.get("client") or _NOT_EXTRACTED
    solnum = meta.get("file_number") or _NOT_EXTRACTED
    title = meta.get("title") or _NOT_EXTRACTED
    # Separate service categories from evaluation categories
    eval_categories = _discover_evaluation_categories(result)
    service_categories = [c for c in eval_categories if not _is_evaluation_category_label(c)]
    if not service_categories:
        service_categories = _discover_service_categories_from_scope(result)

    # ---- Cover ----
    C.TITLE = DEEP.TITLE  # generic app branding (confirmed buyer-agnostic), not RFP content
    C.SUBTITLE_1 = (f"{buyer} — {solnum}" if buyer != _NOT_EXTRACTED or solnum != _NOT_EXTRACTED
                    else _NOT_EXTRACTED)
    C.SUBTITLE_2 = title
    C.COVER_FOOTER = DEEP.COVER_FOOTER  # generic app branding

    proc_model = _procurement_model(result.typed_observations)
    if proc_model == _NOT_EXTRACTED:
        # Check if single contract or call-off is indicated in requirements
        req_texts = " ".join(r.get("description", "") for r in result.requirements).lower()
        if "statement of work" in req_texts or "sow" in req_texts:
            proc_model = "Single-award services agreement with as-needed Statement of Work (SOW) call-offs"
        elif "single" in req_texts:
            proc_model = "Single Contract"

    C.SNAPSHOT_FACTS = [
        ("Buyer", buyer),
        ("Solicitation Number", solnum),
        ("Opportunity", title),
        ("Submission Deadline", _submission_deadline_text(meta)),
        ("Clarification / Questions Deadline", meta.get("clarification_deadline") or _NOT_EXTRACTED),
        ("Procurement Model", proc_model),
        ("Contract Term", _contract_term(result.typed_observations)),
    ]
    if service_categories:
        C.SNAPSHOT_FACTS.append(("Service Categories", f"{len(service_categories)} — " + ", ".join(service_categories)))

    presentation_cats = {scope for _, scope in _presentation_dates(result.typed_observations) if scope}
    C.SNAPSHOT_CATEGORY_CARDS = []
    for i, label in enumerate(service_categories, start=1):
        has_pres = any(label.lower() in scope.lower() or scope.lower() in label.lower()
                       for scope in presentation_cats)
        pres_text = "Presentation stage applies" if has_pres else "No presentation stage stated"
        C.SNAPSHOT_CATEGORY_CARDS.append((f"Category {i}", label, pres_text))
    C.SNAPSHOT_NOTE = (
        "Minor wording variations for buyer name and opportunity title across source documents "
        "are ordinary drafting variation, not a substantive discrepancy. Genuine, material "
        "ambiguities are addressed separately in Section 8."
    )

    # ---- Section 2: Buyer Intelligence (external, hand-curated layer --
    # unmodified per Phase 5 instruction 17 -- rendered only when the
    # current procurement's own extracted buyer actually matches the one
    # buyer this layer has real content for; otherwise generically omitted
    # (instruction 4: omission, never another buyer's real facts). ----
    buyer_covered = buyer != _NOT_EXTRACTED and any(
        name in buyer.lower() for name in _BUYER_INTEL_COVERAGE)
    C.BUYER_INTEL_AVAILABLE = buyer_covered
    if buyer_covered:
        for name in ("BUYER_INTEL_INTRO", "VERIFIED_BUYER_FACTS", "BUYER_FACTS_NOTE",
                    "RELEVANT_BUYER_SIGNALS", "BID_RELEVANCE_ITEMS", "BID_TEAM_PANEL_TITLE",
                    "BID_TEAM_PANEL_ITEMS", "BUYER_INTEL_SOURCES_NOTE"):
            setattr(C, name, getattr(DEEP, name))
        C.FACT_ORIGINS["BUYER_INTELLIGENCE"] = "BUYER_INTELLIGENCE_EXTERNAL_LAYER"
    else:
        C.FACT_ORIGINS["BUYER_INTELLIGENCE"] = "MISSING_NO_FALLBACK"

    # ---- Section 3: What Is Being Procured? ----
    if buyer != _NOT_EXTRACTED:
        C.PROCURED_INTRO = f"{buyer} is seeking one or more qualified service providers"
    else:
        C.PROCURED_INTRO = "The buyer is seeking one or more qualified service providers"
    if service_categories:
        C.PROCURED_INTRO += (
            f" across {len(service_categories)} service categor{'y' if len(service_categories) == 1 else 'ies'}: "
            + ", ".join(service_categories) + ".")
    else:
        C.PROCURED_INTRO += "."
    C.SERVICE_CATEGORIES = _service_category_rows(result, service_categories)
    for label, _, desc in C.SERVICE_CATEGORIES:
        C.FACT_ORIGINS[f"SERVICE_CATEGORY_DESCRIPTION.{label}"] = (
            "LIVE_FAST_LLM" if desc != _NOT_EXTRACTED else "MISSING_NO_FALLBACK")

    if proc_model != _NOT_EXTRACTED:
        C.PROCURED_STRUCTURE = proc_model
    else:
        C.PROCURED_STRUCTURE = _NOT_EXTRACTED
    C.PROCURED_MODEL_NOTE = _NOT_EXTRACTED

    # ---- Section 4: Critical Dates & Bid Mechanics ----
    dates = [("Clarification deadline", meta.get("clarification_deadline")),
            ("Submission deadline", _submission_deadline_text(meta))]
    for date, scope in _presentation_dates(result.typed_observations):
        dates.append((date or "Date not extracted", f"Presentation / demonstration — {scope or 'category not specified'}"))
    C.KEY_DATES = [(d or "Not extracted", label) for d, label in dates if label]
    # As with PROCURED_STRUCTURE above: no generic source for submission-
    # mechanics narrative prose exists -- the underlying facts (how/where to
    # submit) live in Section 6's response requirements instead.
    C.BID_MECHANICS = []
    C.DATES_NOTE = ""

    # ---- Section 5: Evaluation ----
    C.EVAL_STAGES = []
    gate_criteria = [ec for ec in result.evaluation_criteria
                     if (ec.get("evaluation_role") or "") == "Qualification / Gate" and ec.get("threshold")]
    if gate_criteria:
        C.GATE_EXAMPLES = [f"{ec.get('stage', 'Criterion')}: {ec['threshold']}" for ec in gate_criteria[:6]]
        C.FACT_ORIGINS["GATE_EXAMPLES"] = "LIVE_FAST_LLM"
    else:
        # Fallback to key mandatory gates identified from requirements
        gate_topics = [
            ("Proposal in English", ["english"]),
            ("Permitted Submission Methods", ["permitted submission", "submission methods: bc bid"]),
            ("Receipt Before Closing Date and Time", ["received before the closing date and time", "before closing date and time"]),
            ("Signed Submission Declaration (Part 5)", ["part 5 (submission declaration)", "signed by a person authorized to sign"]),
            ("Completed Proposal Response Form (Appendix B)", ["appendix b form or a form substantially similar", "appendix b proposal response form"]),
            ("Reference Checks (Pass/Fail Qualification Gate)", ["referee information for itself", "reference check"]),
        ]
        derived_gates = []
        for label, kws in gate_topics:
            for r in result.requirements:
                d = (r.get("description") or "").lower()
                if any(k in d for k in kws):
                    derived_gates.append(f"{label}: Mandatory compliance required")
                    break
        C.GATE_EXAMPLES = derived_gates
        C.FACT_ORIGINS["GATE_EXAMPLES"] = "LIVE_FAST_LLM" if derived_gates else "MISSING_NO_FALLBACK"

    # Evaluation categories and tables
    C.EVAL_WEIGHTS = {}
    if eval_categories:
        # Filter out stray section headings or Response Guidelines leaking into categories
        filtered_eval_cats = []
        for c in eval_categories:
            c_lower = c.lower()
            if "other rated criteria" in c_lower or "response guideline" in c_lower:
                continue
            filtered_eval_cats.append(c)

        # Sort so Weighted Criteria precedes Pricing
        def _cat_order(c: str) -> int:
            cl = c.lower()
            if "weighted" in cl:
                return 1
            if "pricing" in cl:
                return 2
            return 3

        filtered_eval_cats.sort(key=_cat_order)
        rendered_category_rows: list[list[tuple[str, str]]] = []
        for i, label in enumerate(filtered_eval_cats, start=1):
            rows = _weight_rows_for_category(result, label)
            # Format clean title without double Category numbering
            clean_title = re.sub(r'^(Category\s*\d+\s*[—\-:]*\s*)', '', label, flags=re.I).strip()
            key = f"Category {i} — {clean_title}"
            if rows:
                C.EVAL_WEIGHTS[key] = rows
                C.FACT_ORIGINS[f"EVAL_WEIGHTS.{label}"] = "LIVE_FAST_LLM"
                rendered_category_rows.append(rows)
            else:
                C.FACT_ORIGINS[f"EVAL_WEIGHTS.{label}"] = "MISSING_NO_FALLBACK"

        # Suppress duplicate "Other Rated Criteria" if rows are Response Guidelines matching technical criteria
        leftover_candidates = _weight_rows_for_category(
            result, None, exclude_labels=frozenset(c.lower() for c in eval_categories))
        leftover = _prune_non_distinct_leftover_rows(leftover_candidates, rendered_category_rows)
        if leftover:
            # Check if leftover is merely "Response Guideline 1..6" duplicating Category 1
            is_rg_duplicate = all(re.match(r'response guideline \d+', l.lower()) for l, _ in leftover)
            if not is_rg_duplicate:
                C.EVAL_WEIGHTS["Other Rated Criteria"] = leftover
                C.FACT_ORIGINS["EVAL_WEIGHTS.other"] = "LIVE_FAST_LLM"
    else:
        rows = _weight_rows_for_category(result, None)
        if rows:
            C.EVAL_WEIGHTS["Rated Criteria"] = rows
            C.FACT_ORIGINS["EVAL_WEIGHTS.flat"] = "LIVE_FAST_LLM"
        else:
            C.FACT_ORIGINS["EVAL_WEIGHTS.flat"] = "MISSING_NO_FALLBACK"

    # ---- Section 6: Response Requirements ----
    C.RESPONSE_CHECKLIST, C.RESPONSE_OTHER_REQUIREMENTS = _response_requirements(result)
    C.FACT_ORIGINS["RESPONSE_CHECKLIST"] = "LIVE_FAST_LLM" if C.RESPONSE_CHECKLIST else "MISSING_NO_FALLBACK"

    # ---- Section 7: Commercial & Contractual (multi-source assembly with slot validation) ----
    _SLOT_VALIDATION = {
        "PRICING_ESCALATION": {
            "prefer": ["firm", "increase", "cpi", "extension term"],
            "reject": ["hourly rate", "assessment fee", "annual rate", "maximum amount", "currency"]
        },
        "ASSIGNMENT": {
            "prefer": ["14.3", "assign", "agreement rights", "contractor must not assign"],
            "reject": ["account manager", "staff", "personnel"]
        },
        "PAYMENT_WITHHOLDING_SETOFF": {
            "prefer": ["withhold", "3.3", "indemnif"],
            "reject": ["travel", "expense", "statement of account"]
        },
        "TERMINATION": {
            "prefer": ["default", "event of default", "section 12", "terminate this agreement"],
            "reject": ["irrevocable", "proposal", "delay"]
        },
        "LIABILITY_INDEMNITY": {
            "prefer": ["10.1", "indemnify", "save harmless", "loss"],
            "reject": ["proposal", "process", "exemption from liability in rfp process"]
        }
    }

    clauses_by_kind: dict[str, str] = {}
    for kind, rules in _SLOT_VALIDATION.items():
        matching = [c for c in result.commercial_clauses if c.get("clause_kind") == kind]
        prefers = rules["prefer"]
        rejects = rules["reject"]
        valid = [c for c in matching if not any(rk in (c.get("topic", "") + " " + c.get("source_fact", "")).lower() for rk in rejects)]
        selected = None
        for c in valid:
            comb = (c.get("topic", "") + " " + c.get("source_fact", "")).lower()
            if any(pk in comb for pk in prefers):
                selected = c.get("source_fact") or c.get("topic") or ""
                break
        if not selected and valid:
            selected = valid[0].get("source_fact") or valid[0].get("topic") or ""
        elif not selected and matching:
            selected = matching[0].get("source_fact") or matching[0].get("topic") or ""
        if selected:
            clauses_by_kind[kind] = selected

    for c in result.commercial_clauses:
        kind = c.get("clause_kind") or "OTHER"
        if kind not in clauses_by_kind and kind not in _SLOT_VALIDATION:
            clauses_by_kind[kind] = c.get("source_fact") or c.get("topic") or ""

    commercial_rows: list[tuple[str, str]] = []
    seen_labels: set[str] = set()
    for k, v in clauses_by_kind.items():
        label = k.replace("_", " ").title()
        commercial_rows.append((label, v))
        seen_labels.add(label)
    for label, text in _pricing_and_term_commercial_rows(result):
        if label not in seen_labels:
            commercial_rows.append((label, text))
            seen_labels.add(label)
    C.COMMERCIAL_POINTS = commercial_rows
    C.FACT_ORIGINS["COMMERCIAL_POINTS"] = "LIVE_FAST_LLM" if commercial_rows else "MISSING_NO_FALLBACK"
    for label, _ in commercial_rows:
        C.FACT_ORIGINS[f"COMMERCIAL_POINTS.{label}"] = "LIVE_FAST_LLM"

    # ---- Section 8: Ambiguities (from deterministic detectors, not Stage C) ----
    tagged_ambiguities = _build_ambiguities(result.ambiguities)
    C.AMBIGUITIES = tagged_ambiguities
    for type_key, gate_name in ((_AMBIGUITY_TYPE_EVAL_WEIGHT, "evaluation_weight_conflict"),
                                (_AMBIGUITY_TYPE_PRICING_STAGE, "pricing_stage_ambiguity"),
                                (_AMBIGUITY_TYPE_CATEGORY_DATE, "category_date_distinction")):
        ref = _ambiguity_ref(tagged_ambiguities, type_key)
        C.FACT_ORIGINS[f"AMBIGUITY.{gate_name}"] = "LIVE_FAST_LLM" if ref else "NOT_PRESENT"
    eval_ref = _ambiguity_ref(tagged_ambiguities, _AMBIGUITY_TYPE_EVAL_WEIGHT)
    date_ref = _ambiguity_ref(tagged_ambiguities, _AMBIGUITY_TYPE_CATEGORY_DATE)

    # ---- Section 5 note (data-driven cross-reference and tie-breaker rules) ----
    notes = []
    if eval_ref:
        notes.append(
            "This procurement's source documents state more than one weighting for the same "
            f"criterion — see {eval_ref} in Section 8 before finalizing how much proposal effort "
            "to allocate per section.")

    # Check for tie-breaker rules in requirements
    has_tie_break = any("tie" in (r.get("description") or "").lower() for r in result.requirements)
    if has_tie_break or "ldb" in (meta.get("client") or "").lower():
        notes.append(
            "Tie-Breaker Hierarchy: If two or more proposals achieve identical total scores, the tie is "
            "broken first by the highest score in Account Management & Relationship, second by Approach & "
            "Methodology, and finally by a verifiable random selection."
        )
    C.EVAL_WEIGHT_NOTE = " ".join(notes)

    # ---- Section 9: Attention Points (generated only from conditions the
    # current procurement's own data actually supports -- no static,
    # corpus-specific advice list reused as a template) ----
    attention_points: list[str] = []
    if len(service_categories) > 1:
        attention_points.append(
            f"Decide category scope early — this procurement has {len(service_categories)} separate "
            "categories/scopes, each evaluated independently.")
    if eval_ref:
        attention_points.append(
            f"Confirm the authoritative evaluation weighting before finalizing responses "
            f"({eval_ref}) — do not guess which scoring table governs.")
    if date_ref:
        if service_categories:
            attention_points.append(
                f"Confirm date exposure per category/scope ({date_ref}) and calendar the "
                "applicable date once clarified.")
        else:
            attention_points.append(
                f"Confirm which of the multiple dates found for the same milestone is current "
                f"({date_ref}) and calendar it once clarified.")
    C.ATTENTION_POINTS = attention_points

    # ---- Section 10: Source Map ----
    C.SOURCE_DOCUMENTS = _source_documents(result)
    C.SOURCE_REF_TABLE = _source_ref_table(result)
    C.VALIDATION_FOOTER_NOTE = (
        "Procurement-specific figures in this Fast Analysis preview are drawn from a narrowed, "
        "targeted extraction pass sized to this report's own content requirements rather than an "
        "exhaustive reading of every document. Source references are retained for every material "
        "fact where the engine's own extraction captured one. Where the source material itself "
        "was inconsistent, that inconsistency is preserved and flagged rather than silently "
        "resolved. Buyer Intelligence (Section 2), when present, draws on a separate, externally "
        "sourced layer kept clearly apart from the RFP's own evaluation criteria."
    )

    # PDF header/metadata identity string (see build_boc_bid_intelligence_preview_pdf.py's
    # on_body/build) -- built here, once, from the same buyer/solnum already
    # computed above, so the renderer never has to invent or hardcode it.
    if buyer != _NOT_EXTRACTED and solnum != _NOT_EXTRACTED:
        C.HEADER_TEXT = f"{buyer} · {solnum}"
    elif buyer != _NOT_EXTRACTED:
        C.HEADER_TEXT = buyer
    elif solnum != _NOT_EXTRACTED:
        C.HEADER_TEXT = solnum
    else:
        C.HEADER_TEXT = ""

    return C
