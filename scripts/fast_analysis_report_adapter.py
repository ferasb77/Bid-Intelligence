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

# Generic Buyer Intelligence: Section 2 is populated whenever an external
# researched buyer intelligence payload is supplied with the result or passed to
# build_fast_report_content(). For Bank of Canada only, the legacy external DEEP
# layer is retained as a backwards-compatibility fallback for existing tests.

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


_SUBMISSION_CHANNEL_KEYWORDS = (
    "bc bid", "electronic submission", "email submission", "via email",
    "submission portal", "procurement portal", "in person", "hard copy",
    "courier", "by fax", "hand delivery",
)


def _submission_channel(result: FastAnalysisResult) -> str:
    """Generic (buyer-agnostic) extraction of how proponents actually submit
    a proposal -- e.g. an electronic bidding portal vs. email vs. hard copy.
    Scans the current procurement's own extracted requirements for a
    requirement whose description states the permitted submission method(s),
    using a fixed set of common public-procurement channel terms (not any
    one buyer's name). Prefers the requirement that most explicitly reads as
    the governing statement of permitted methods (mentions "method" and
    lists more than one channel keyword); falls back to the first requirement
    that mentions any channel keyword. Returns _NOT_EXTRACTED, like every
    other field here, when no source text supports it -- never invents a
    channel or a preference the source doesn't state."""
    candidates = []
    for r in result.requirements:
        desc = r.get("description") or ""
        dl = desc.lower()
        hits = sum(1 for kw in _SUBMISSION_CHANNEL_KEYWORDS if kw in dl)
        if hits:
            candidates.append((hits, "method" in dl or "methods" in dl, desc))
    if not candidates:
        return _NOT_EXTRACTED
    # Prefer the requirement naming the permitted method(s) explicitly and
    # covering the most channel terms -- typically the one governing clause,
    # not a downstream mechanic (e.g. how to withdraw via a given channel).
    candidates.sort(key=lambda c: (c[1], c[0]), reverse=True)
    return _shorten_to_sentence(candidates[0][2], limit=320)


_LEADING_NUMBER_RE = re.compile(r'^\s*(\d+(?:\.\d+)?)')
_TIME_UNIT_RE = re.compile(r'\b(year|month|week|day)s?\b', re.I)


def _term_phrase(number_text, *unit_sources) -> str | None:
    """Builds a clean 'N unit(s)' phrase from a number and one or more text
    sources that may or may not contain the unit word. Fast Analysis's
    CONTRACT_TERM extraction sometimes returns `duration` as a bare number
    ("2") and sometimes as a phrase that already embeds its own unit
    ("2 years", or even "3 years per option"), with the `unit` field
    separately holding the same unit word again -- naively concatenating
    both then duplicates the unit ("2 years years"). This searches every
    given source for a standard calendar-time unit word and uses the FIRST
    one found, so the unit is never rendered twice regardless of which
    field it actually landed in. Generic to any CONTRACT_TERM observation;
    not tied to a specific unit vocabulary beyond year/month/week/day, and
    not specific to any corpus or buyer."""
    m = _LEADING_NUMBER_RE.match(str(number_text or ""))
    if not m:
        return None
    number = m.group(1)
    unit_word = None
    for src in unit_sources:
        um = _TIME_UNIT_RE.search(str(src or ""))
        if um:
            unit_word = um.group(1).lower()
            break
    if not unit_word:
        return None
    try:
        plural = float(number) != 1
    except ValueError:
        plural = True
    n_display = number[:-2] if number.endswith(".0") else number
    return f"{n_display} {unit_word}{'s' if plural else ''}"


def _contract_term(typed_observations: list[dict]) -> str:
    terms = [o for o in typed_observations if o.get("family") == "CONTRACT_TERM"]
    initial = next((o for o in terms if (o.get("semantic_kind") or "").upper() == "INITIAL_DURATION"
                    and not (o.get("scope") or {}).get("component")), None)
    ext = next((o for o in terms if (o.get("semantic_kind") or "").upper() == "EXTENSION_OPTION"), None)

    base = None
    if initial and initial.get("duration"):
        base = _term_phrase(initial["duration"], initial.get("unit"), initial["duration"])
    if not base:
        return "term not confidently extracted"

    if ext and ext.get("option_count") and ext.get("duration"):
        ext_phrase = _term_phrase(ext["duration"], ext.get("unit"), ext["duration"])
        if ext_phrase:
            count_m = _LEADING_NUMBER_RE.match(str(ext.get("option_count") or ""))
            count = count_m.group(1) if count_m else str(ext["option_count"])
            ext_number, ext_unit = ext_phrase.split(" ", 1)
            # Singular unit for the hyphenated compound adjective before
            # "extensions" ("3-year extensions", not "3-years extensions").
            ext_unit_singular = re.sub(r's$', '', ext_unit)
            discretion = ""
            for src in (ext.get("original_value"),
                        initial.get("original_value") if initial else None):
                if src and "discretion" in str(src).lower():
                    discretion = " at the buyer's discretion"
                    break
            return f"{base}, with {count} optional {ext_number}-{ext_unit_singular} extensions{discretion}"
    return base


def _clarification_deadline_text(meta: dict, typed_observations: list[dict]) -> str:
    """Distinguishes 'not stated anywhere in the source documents' from
    'the buyer explicitly directs suppliers to an external procurement
    portal for this date' -- generic to any buyer's portal/referral
    phrasing, not just BC Bid. doc_metadata.clarification_deadline holds a
    concrete date when one was stated; when the buyer instead points
    suppliers to a portal tab/page rather than stating a date, that
    referral is still captured as a MILESTONE/CLARIFICATION_DEADLINE
    typed_observation (with date=null but a descriptive original_value) --
    this surfaces that text rather than falling back to a bare
    "not stated" that would misrepresent an explicit buyer instruction as
    silence."""
    explicit = meta.get("clarification_deadline")
    if explicit:
        return explicit
    obs = next((o for o in typed_observations
                if o.get("family") == "MILESTONE"
                and (o.get("semantic_kind") or "").upper() == "CLARIFICATION_DEADLINE"), None)
    if obs:
        raw = (obs.get("original_value") or "").strip()
        if raw:
            # Strip a redundant leading "<label> Deadline:" prefix -- the
            # report's own row label already says "Clarification /
            # Questions Deadline", so repeating a differently-worded label
            # here is noise, not new information.
            cleaned = re.sub(r'^.*?\bdeadline\s*:\s*', '', raw, flags=re.I).strip() or raw
            if not re.match(r'^(refer to|see\b)', cleaned, re.I):
                cleaned = f"See {cleaned[0].lower()}{cleaned[1:]}" if cleaned else cleaned
            return cleaned
    return _NOT_EXTRACTED


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


_FUZZY_DEDUP_STOPWORDS = frozenset((
    "the", "and", "for", "any", "that", "this", "will", "may", "with", "from",
    "are", "was", "were", "been", "have", "has", "had", "its", "their",
))


def _fuzzy_word_set(text: str) -> frozenset:
    words = re.sub(r'[^a-z0-9]', ' ', text.lower()).split()
    return frozenset(w for w in words if len(w) >= 4 and w not in _FUZZY_DEDUP_STOPWORDS)


def _is_near_duplicate(text_a: str, words_a: frozenset, text_b: str, words_b: frozenset,
                       threshold: float = 0.7) -> bool:
    """Word-set overlap (not just leading-word matching): extraction
    non-determinism can restate the same fact with the shared content
    positioned differently across occurrences -- confirmed live, the same
    final tie-break step captured once as "List Randomizer
    (www.random.org)" and again as "Random selection via List Randomizer
    (www.random.org)", where the overlap is in the middle, not the start,
    so comparing only leading words misses it. Two values are near-
    duplicates when the smaller one's significant words are mostly (>=70%)
    contained in the other's -- gated to sets of at least 3 significant
    words each, so two short, genuinely distinct labels that happen to
    reduce to the same one or two words after stopword filtering (e.g.
    "Criterion A" vs. "Criterion B", both reducing to just {"criterion"})
    are compared by their actual text instead, never falsely collapsed
    merely because their reduced word-sets coincide."""
    if len(words_a) < 3 or len(words_b) < 3:
        return text_a.strip().lower() == text_b.strip().lower()
    smaller, larger = (words_a, words_b) if len(words_a) <= len(words_b) else (words_b, words_a)
    return len(smaller & larger) / len(smaller) >= threshold


def _qualification_mechanisms(typed_observations: list[dict]) -> list[str]:
    """Pass/fail qualification mechanisms (e.g. reference checks) that are
    distinct from both the mandatory submission gates and the weighted/
    rated criteria -- generic to any QUALIFICATION_MECHANISM typed
    observation Fast Analysis's extraction captured, not tied to any
    specific buyer's reference-check wording. Returns the raw stated
    text verbatim; never synthesizes a mechanism the source didn't state.
    Near-duplicate restatements (see _is_near_duplicate) are collapsed to
    the first occurrence."""
    items: list[str] = []
    seen: list[tuple[str, frozenset]] = []
    for o in typed_observations:
        if o.get("family") != "QUALIFICATION_MECHANISM":
            continue
        val = (o.get("original_value") or "").strip()
        if not val:
            continue
        words = _fuzzy_word_set(val)
        if any(_is_near_duplicate(val, words, sv, sw) for sv, sw in seen):
            continue
        seen.append((val, words))
        items.append(val)
    return items


def _tie_break_rules(typed_observations: list[dict]) -> list[str]:
    """Ordered tie-break rules, sorted by each observation's stated
    "rank" (1 = first tie-breaker applied, 2 = next, etc.) -- generic to
    any TIE_BREAK_RULE typed observation; never fabricates an order the
    source didn't state. An observation missing either its rank or text
    is skipped rather than guessed into a position. Near-duplicate
    restatements of the same step under a different rank (see
    _is_near_duplicate) are collapsed to whichever occurrence sorts
    first."""
    entries: list[tuple[float, str]] = []
    for o in typed_observations:
        if o.get("family") != "TIE_BREAK_RULE":
            continue
        val = (o.get("original_value") or "").strip()
        rank = o.get("rank")
        if not val or rank is None:
            continue
        try:
            rank_num = float(rank)
        except (TypeError, ValueError):
            continue
        entries.append((rank_num, val))
    entries.sort(key=lambda x: x[0])
    seen: list[tuple[str, frozenset]] = []
    ordered: list[str] = []
    for _, val in entries:
        words = _fuzzy_word_set(val)
        if any(_is_near_duplicate(val, words, sv, sw) for sv, sw in seen):
            continue
        seen.append((val, words))
        ordered.append(val)
    return ordered


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
        # Suppress milestone_kind == "OTHER" distinctions where the occurrences
        # represent clearly distinct, sequentially ordered milestones (e.g. "Anticipated
        # final selection" vs "Anticipated contract start date") rather than competing
        # dates for the same event. These share the OTHER bucket not because they are
        # the same milestone with conflicting dates, but because the LLM grouped them
        # under a generic kind. Only flag if all occurrences share the same raw wording,
        # indicating they genuinely represent the same milestone type.
        if dist.get("milestone_kind") == "OTHER":
            raw_labels = {
                (o.get("original_value") or o.get("date") or "").lower().strip()
                for o in occs if isinstance(o, dict)
            }
            if len(raw_labels) > 1:
                # Multiple distinct raw values: they are different milestones, not competing dates
                continue
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


def _canonical_procurement():
    """Lazy import of the CI-1 canonical contract. Deferred because
    `canonical_procurement` itself imports this module for its shared
    dedup primitives (the same convention `procurement_normalization`
    and `document_provenance` already follow)."""
    import canonical_procurement as _canon
    return _canon


def _re_norm_label(label: str) -> str:
    return re.sub(r'\s+', ' ', (label or "").strip()).lower()


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


def _minimum_scores_for_category(result: FastAnalysisResult, category_label: str | None,
                                 exclude_labels: frozenset[str] = frozenset()) -> dict[str, str]:
    """Per-criterion minimum-score thresholds for one discovered category
    (mirrors _weight_rows_for_category's own category-matching AND its
    occurrences-vs-evaluation_criteria fallback rule, kept as a separate
    lookup rather than widening that function's row shape -- every
    existing caller of _weight_rows_for_category assumes a 2-tuple
    (label, weight), and several of them mutate/rebuild rows from that
    exact shape -- so a parallel {criterion_label: minimum_score} dict is
    the safer, additive way to surface this new field).

    The fallback to evaluation_criteria's own "threshold" field is not
    optional polish: confirmed live, the focused rated-criteria task's
    section-finder (which looks for a line reading exactly "Rated
    criteria") never matches a corpus whose own heading vocabulary is
    different (e.g. "Weighted Criteria") -- for such a corpus,
    evaluation_occurrences is ALWAYS empty and _weight_rows_for_category
    itself already falls back to evaluation_criteria/"stage"/"threshold"
    to render the weight table at all; minimum-score must fall back the
    same way for the same corpora, via the same field the general
    extraction schema has always had, or it would silently never surface
    for exactly the corpora that need this fallback path.

    Only an occurrence/criterion whose extraction actually populated a
    minimum value contributes an entry; a criterion with no stated
    minimum is simply absent from the returned dict, never guessed."""
    def _clean(v) -> str | None:
        v = v.strip() if isinstance(v, str) else v
        return str(v) if v else None

    scores: dict[str, str] = {}
    occs = carry_forward_category_scope(result.evaluation_occurrences)
    for occ in occs:
        min_score = _clean(occ.get("minimum_score"))
        label = occ.get("criterion_label")
        if not min_score or not label:
            continue
        scope = (occ.get("category_scope") or "").strip()
        if category_label is not None:
            if scope.lower() != category_label.lower():
                continue
        elif scope.lower() in exclude_labels:
            continue
        scores[label] = min_score
    if scores or occs:
        # Focused task ran for this corpus -- trust its result (mirrors
        # _weight_rows_for_category's own rule for the weight rows
        # themselves).
        return scores
    for ec in result.evaluation_criteria:
        min_score = _clean(ec.get("threshold"))
        label = ec.get("stage")
        if not min_score or not label:
            continue
        parent = (ec.get("parent_stage") or "").strip()
        if category_label is not None:
            if parent.lower() != category_label.lower():
                continue
        elif parent.lower() in exclude_labels:
            continue
        scores[label] = min_score
    return scores


def _merged_doc_metadata(result: FastAnalysisResult) -> dict:
    """Canonical procurement IDENTITY resolution (CI-1 Defect A).

    Identity is resolved through `canonical_procurement.merge_identity_
    fields`, which applies the IDENTITY field-family authority ranking --
    NOT one universal "latest/first document wins" ranking. The concrete
    behaviour this fixes: an addendum carries the solicitation number in
    its own filename and its own doc_metadata, and the previous priority
    function scored it 1 (same as the master RFP), so "RFP 2026-026
    Addendum #2" could become the canonical opportunity title and a
    truncated buyer string could become the canonical buyer.

    An AMENDMENT-role document now has NO identity authority at all; it
    remains authoritative for the clauses it actually amends (handled in
    the clause/commercial layer, not here). It contributes an identity
    field only in the degenerate case where the package contains no
    identity-bearing document whatsoever."""
    import canonical_procurement as _canon

    merged: dict = dict(_canon.merge_identity_fields(
        {k: v for k, v in result.doc_metadata_by_doc.items() if isinstance(v, dict)},
        field_family="identity"))

    # Clean and normalize title: RFP / Solicitation title outranks draft SERVICES AGREEMENT.
    # Buyer-agnostic prefix strip -- e.g. "SERVICES AGREEMENT for Coaching and
    # Leadership Development Services" already reduces to the correct plain
    # title "Coaching and Leadership Development Services" for any corpus
    # using this or an equivalent draft-agreement/solicitation prefix.
    title = merged.get("title")
    if title:
        cleaned_title = re.sub(r'^(?:SERVICES\s+AGREEMENT\s+for|GENERAL\s+SERVICE\s+AGREEMENT|Request\s+for\s+Proposals\s+(?:RFP\d+[-\w]*\s+)?for)\s*', '', title, flags=re.I).strip()
        if cleaned_title:
            merged["title"] = cleaned_title

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


_SCOPE_TRIGGER_RE = re.compile(
    r'(?:service[\s\-]?(?:category\s+)?scope\s+includes?|'
    r'scope\s+of\s+services?\s+includes?|'
    r'services?\s+(?:categories|types)\s+(?:are|include)s?|'
    r'the\s+following\s+service\s+categories)\s*:?\s*(.*)', re.I)


def _discover_service_categories_from_scope(result: FastAnalysisResult) -> list[str]:
    """Extract substantive service categories from scope requirements or
    descriptions when evaluation categories have leaked into discovered
    categories. The trigger regex accepts several generic phrasings a
    scope-enumeration sentence commonly uses (not tied to any one buyer's
    exact wording) so this doesn't depend on the extraction happening to
    reproduce one specific phrase verbatim."""
    discovered = []
    for r in result.requirements:
        text = r.get("description", "")
        m = _SCOPE_TRIGGER_RE.search(text)
        if not m:
            continue
        raw_items = re.split(r";\s*(?:and\s*)?(?:\([a-z0-9]+\))?|\([a-z0-9]+\)", m.group(1))
        for item in raw_items:
            clean = item.strip().strip(".").strip()
            if clean.lower().startswith("and "):
                clean = clean[4:].strip()
            # An item can run on with trailing descriptive clauses the
            # split above didn't fully separate (e.g. "X of Leaders in
            # the following roles: A, B, C"); generically salvage just
            # the leading name by truncating at the first colon before
            # applying the length gate below -- not tied to any specific
            # category name.
            if ":" in clean:
                clean = clean.split(":", 1)[0].strip()
            if len(clean) >= 40:
                # Still too long after colon-truncation: a short category
                # name is often followed by a descriptive clause joined by
                # a preposition ("X of Leaders in the following roles",
                # "X for..."); generically recover just the name portion
                # rather than dropping the category entirely. Not tied to
                # any specific category name.
                m2 = re.match(r'^(.{1,39}?)\s+(?:of|for|in|including|covering)\s+', clean, re.I)
                if m2:
                    clean = m2.group(1).strip()
            if clean and clean not in discovered and len(clean) < 40 and clean.lower() != "and":
                discovered.append(clean)
    return discovered


def _shorten_to_sentence(text: str, limit: int = 280) -> str:
    """Generic truncation to the nearest sentence/word boundary at or before
    `limit` characters -- used so a matched requirement paragraph (which can
    run to many sentences, especially when several service categories share
    one combined scope clause) renders as a readable snippet instead of a
    duplicated wall of text under every category it happens to mention.
    Not buyer- or corpus-specific: applies identically to any matched text."""
    if len(text) <= limit:
        return text
    truncated = text[:limit]
    last_period = truncated.rfind(". ")
    if last_period > limit * 0.4:
        return truncated[:last_period + 1]
    return truncated.rsplit(" ", 1)[0] + "..."


def _service_category_rows(result: FastAnalysisResult, categories: list[str]) -> list[tuple[str, str, str]]:
    """Phase 5 generic version of category loop: ensures evaluation terms
    (Weighted Criteria, Pricing) are never displayed as Service Categories.

    Full-Package Analysis Integrity Remediation Defect D: when the
    literal-substring match against requirement descriptions finds
    nothing (the common case -- a buyer's category LABEL, e.g. "Category
    1 — Learning & Development (Form D1)", rarely appears verbatim inside
    a requirement's own text), falls back to procurement_normalization.
    derive_category_scope_summaries -- source-grounded scope material
    from that SAME category's own criteria response prompts (Defect A)
    and any enumerated service-scope items, NEVER a summary invented from
    the category title alone. A category with neither signal still shows
    _NOT_EXTRACTED, honestly."""
    import procurement_normalization as _proc_norm

    clean_categories = [c for c in categories if not _is_evaluation_category_label(c)]
    if not clean_categories:
        clean_categories = _discover_service_categories_from_scope(result)

    rows: list[tuple[str, str, str]] = []
    for i, label in enumerate(clean_categories, start=1):
        matches = [r.get("description") for r in result.requirements
                  if r.get("description") and label.lower() in r["description"].lower()
                  and not _is_evaluation_category_label(label)]
        # Generic noise filter: excludes pricing-scoring-formula language (ranking
        # multipliers, evaluation formulas) from ANY procurement's category
        # descriptions -- these describe how price is scored, not what the
        # service is, regardless of buyer.
        clean_matches = [
            m for m in matches
            if not any(noise in m.lower() for noise in (
                "pricing -", "pricing-calculation", "formula:", "hourly rate", "statement of account",
                "pricing evaluation formula", "ranked lowest to highest", "multiplier", "points available",
            ))
        ]
        desc = " ".join((clean_matches or matches)[:2]) if matches else None

        if not desc:
            weight_rows = _weight_rows_for_category(result, label)
            weights_by_category = {label: [{"criterion": c, "weight": w} for c, w in weight_rows]} if weight_rows else {}
            # CI-1.1 gap 1: prefer the SCOPED prompt map (a label shared by
            # several categories keeps one prompt per category); the older
            # label-keyed map is used only when no scoped map exists.
            det_prompts = (getattr(result, "scoped_criterion_response_prompts", None)
                           or getattr(result, "deterministic_criterion_response_prompts", None) or {})
            summaries = _proc_norm.derive_category_scope_summaries(
                weights_by_category, det_prompts, getattr(result, "deterministic_service_scope", None),
                getattr(result, "category_scope_items", None))
            cat_summary = summaries.get(label) or {}
            if cat_summary.get("summary_available"):
                # CI-1.1 gap 2: genuine, source-grounded SOW material for
                # this category outranks anything derived from evaluation
                # material; both are already semantic-type gated.
                sourced = [si["text"] for si in cat_summary.get("source_scope_items") or []][:2]
                parts = [cp["response_prompt"] for cp in cat_summary["criteria_prompts"][:2]]
                if sourced:
                    desc = " ".join(sourced)
                elif parts:
                    desc = " ".join(parts)
                elif cat_summary.get("enumerated_scope_items"):
                    desc = "; ".join(cat_summary["enumerated_scope_items"][:5])

        if not desc:
            desc = _NOT_EXTRACTED
        else:
            desc = _shorten_to_sentence(desc, limit=320)
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
        "pricing evaluation mechanism", "maximum points available", "proportionately fewer points",
        "points available for that subsection",
        # Contract-execution obligations (as opposed to proposal-stage
        # submission requirements) that showed up leaking into the
        # response-requirements section in review: assignment,
        # subcontracting, key-personnel, conflict-of-interest, and
        # billing/time-of-performance clauses. These are genuine
        # commercial/contractual facts, not "what must the bid team
        # submit, answer, evidence, or price" -- Commercial &
        # Contractual Considerations (built from the same corpus's
        # commercial_clauses) is their correct home, not this section.
        "must not assign", "must not subcontract", "key personnel",
        "conflict of interest", "time is of the essence", "billing period",
        "billing date", "province's rights", "province may assign",
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
            # Compact description to concise sentence for decision-support
            # readability. Uses the shared _shorten_to_sentence helper (not
            # a bespoke first-sentence split) specifically because a bare
            # "first sentence" split has no upper bound: a requirement
            # written as semicolon-joined sub-clauses -- "(i)...; (ii)...;
            # ...; (viii)...ends." -- has no sentence-ending punctuation
            # until the very end, so "first sentence" is the entire,
            # multi-hundred-word requirement with nothing to cap it.
            clean_desc = _shorten_to_sentence(desc, limit=180) if len(desc) > 180 else desc
            # Compact citation: map long filenames to brief human-readable references
            def _compact_citation(raw: str) -> str:
                if not raw:
                    return _NOT_EXTRACTED
                rl = raw.lower()
                if "appendix_b" in rl or "appendix b" in rl or "proposal_response_form" in rl:
                    return "Appendix B — Proposal Response Form"
                if "appendix_a" in rl or "form_of_contract" in rl or "contract" in rl:
                    return "Appendix A — Form of Contract"
                if "rfp" in rl or "services-1" in rl or "services_1" in rl:
                    return "Main RFP §9.1"
                return raw
            checklist.append((f"Requirement {mandatory_idx}", clean_desc, _compact_citation(source_doc)))
        elif category == "mandatory" and not checklist and len(result.requirements) <= 25:
            # Fallback for small corpora where requirements are already pre-filtered to submission
            mandatory_idx += 1
            checklist.append((f"Requirement {mandatory_idx}", desc, source_doc or _NOT_EXTRACTED))
        elif not is_post_award:
            # Post-award items are dropped here entirely, not appended --
            # they belong in Commercial & Contractual Considerations
            # (already populated from this same corpus's commercial_clauses),
            # not in a section answering "what must the bid team submit?"
            if desc not in other:
                other.append(desc)

    # Decision-support compression: proposal submission checklist should focus on key gates (~10-12 items)
    if len(checklist) > 12:
        checklist = checklist[:12]
    if len(other) > 6:
        other = other[:6]

    return checklist, other


def _summarize_evidence_prompts(prompts: list[str], max_prompts: int = 3) -> str:
    """Summarize -- not dump -- a guideline's evidence prompts: the
    "Instructions for Proponents:" general framing line is skipped in
    favour of the more specific asks that follow it when any exist (it's
    still used alone if it's literally all the section has), and at most
    a few prompts are shown, each shortened for compact display. All
    wording is the source's own; nothing here is authored or corpus-
    specific."""
    if not prompts:
        return _NOT_EXTRACTED
    specific = [p for p in prompts if not p.lower().startswith("instructions for proponents")]
    chosen = (specific or prompts)[:max_prompts]
    shortened = [_shorten_to_sentence(p, limit=140) for p in chosen]
    return " • ".join(shortened)


def _rg_evidence_map(result: FastAnalysisResult, weighted_criteria: list[tuple[str, str]],
                     category: str | None = None) -> list[tuple[str, str, str]]:
    """An ordered 'RG1, RG2, ...' evidence map built from the weighted-
    criteria table's own criterion order (excluding Pricing, which has its
    own pricing-submission-rules section) -- generic to any corpus that
    numbers its response-guideline sections sequentially to match its
    weighted-criteria table order, a common RFP convention (confirmed for
    this corpus: RG1..RG6 map 1:1 to the first six WEIGHTED EVALUATION
    rows in table order). Not assumed true for a corpus where it
    doesn't hold -- this only affects the RG1/RG2/... LABEL, never the
    criterion name or evidence text, both of which are the corpus's own
    extracted data either way.

    Each row's "requested evidence" text tries THREE sources, most
    reliable first, never inventing one the source doesn't state:
      1. result.deterministic_criterion_response_prompts (Full-Package
         Analysis Integrity Remediation Defect A) -- an EXACT match on
         THIS criterion's own label against a response-form heading the
         buyer's own Appendix D-style document restated verbatim (e.g.
         "Curriculum & Program Design Capability" as a heading, followed
         by the buyer's own prose describing what to include). This is
         the most reliable source: an exact label match, not a
         positional or substring guess.
      2. result.deterministic_response_guidelines (structural, no-LLM
         parsing of the response form's own "Response Guideline N" table
         -- see extract_response_guideline_sections) by ordinal position
         matching the generic RG-numbers-match-table-order convention --
         a DIFFERENT response-form convention than (1), kept as a
         fallback for a corpus using that table layout instead.
      3. The substring-match technique _service_category_rows also uses,
         for a corpus with neither of the above. A criterion with none of
         the three shows _NOT_EXTRACTED rather than inventing one."""
    rows: list[tuple[str, str, str]] = []
    det_rgs = getattr(result, "deterministic_response_guidelines", None) or []
    # CI-1.1 gap 1: this table belongs to ONE evaluation category, so its
    # prompts are looked up by that category's own scoped criterion
    # identity. The label-keyed map is consulted only when no scoped map
    # exists (a snapshot persisted before CI-1.1).
    import canonical_procurement as _canon

    scoped_prompts = getattr(result, "scoped_criterion_response_prompts", None) or {}
    det_prompts = getattr(result, "deterministic_criterion_response_prompts", None) or {}
    rg_num = 0
    for label, _weight in weighted_criteria:
        if "pricing" in label.lower():
            continue
        rg_num += 1
        evidence = _NOT_EXTRACTED
        if scoped_prompts:
            entry = scoped_prompts.get(_canon.scoped_criterion_map_key(category, label)) or {}
        else:
            entry = det_prompts.get(label) or {}
        if entry.get("response_prompt"):
            evidence = _shorten_to_sentence(entry["response_prompt"], limit=280)
        if evidence == _NOT_EXTRACTED and rg_num <= len(det_rgs):
            evidence = _summarize_evidence_prompts(det_rgs[rg_num - 1].get("evidence_prompts") or [])
        if evidence == _NOT_EXTRACTED:
            matches = [r.get("description") for r in result.requirements
                      if r.get("description") and label.lower() in r["description"].lower()]
            evidence = _shorten_to_sentence(" ".join(matches[:2]), limit=280) if matches else _NOT_EXTRACTED
        rows.append((f"RG{rg_num}", label, evidence))
    return rows


_PRICING_SUBMISSION_KEYWORDS = (
    "unconditional", "unqualified pricing", "pricing must be", "pricing should not be expressed as a range",
    "not be expressed as a range", "lowest numerical value", "enter \"$0\"", "enter '$0'",
    "entering \"$0\"", "entering '$0'", "$zero", "elimination from competition", "rejection of the proposal",
)


_PRICING_FORMULA_REJECT_KEYWORDS = (
    "multiplier", "points available", "ranked lowest to highest", "pricing evaluation formula",
    "pricing-calculation formula", "resulting in a multiplier", "divided by the number of",
)


def _pricing_submission_rules(result: FastAnalysisResult) -> list[str]:
    """Proposal-stage pricing COMPLIANCE rules -- what makes a submitted
    price valid/complete (unconditional/unqualified, no ranges, the
    consequence of a prohibited zero/blank/range entry) -- as distinct
    from (a) the pricing-scoring FORMULA (a sentence can mention "$0"/
    "$zero" purely as part of describing how a scoring multiplier counts
    distinct prices, which is evaluation mechanics, not a submission
    compliance rule -- rejected generically via the same pricing-formula
    noise terms _service_category_rows already screens for) and (b)
    contract-execution pricing terms like escalation (already covered in
    Commercial & Contractual Considerations). Generic keyword set
    describing common RFP pricing-compliance phrasing, not tied to any
    specific buyer."""
    rules = []
    for r in result.requirements:
        desc = (r.get("description") or "").strip()
        dl = desc.lower()
        if not desc or "pricing" not in dl and "price" not in dl and "$" not in desc:
            continue
        if not any(kw in dl for kw in _PRICING_SUBMISSION_KEYWORDS):
            continue
        sentences = re.split(r'(?<=[.!?])\s+', desc)
        hit = next((s for s in sentences
                   if any(kw in s.lower() for kw in _PRICING_SUBMISSION_KEYWORDS)
                   and not any(rk in s.lower() for rk in _PRICING_FORMULA_REJECT_KEYWORDS)),
                   None)
        if not hit:
            continue
        hit = _shorten_to_sentence(hit, limit=220)
        if hit not in rules:
            rules.append(hit)
    return rules


def _compact_citation(raw: str) -> str:
    """Map long file paths or raw filenames to brief, human-readable labels."""
    if not raw:
        return _NOT_EXTRACTED
    rl = raw.lower()
    if "appendix_b" in rl or "appendix b" in rl or "proposal_response_form" in rl:
        return "Appendix B — Proposal Response Form"
    if "appendix_a" in rl or "form_of_contract" in rl or "contract" in rl:
        return "Appendix A — Form of Contract"
    if "services-1" in rl or "services_1" in rl or "coaching_and_leadership" in rl:
        return "Main RFP — Services Agreement"
    return raw


_RELATIONSHIP_ANNOTATIONS = {
    "AMENDS": "amends {related}",
    "AMENDED_BY": "amended by {related}",
    "SUPERSEDES": "supersedes {related}",
    "SUPERSEDED_BY": "superseded by {related}",
    "DUPLICATE_REPRESENTATION": "duplicate representation of {related}",
    "REDUNDANT_DERIVATIVE": "redundant derivative of {related}",
    "TRANSLATION_EQUIVALENT": "translation-equivalent of {related}",
}


def _relationship_annotation(result: FastAnalysisResult, name: str) -> str:
    """Full-Package Analysis Integrity Remediation Defect E: a short,
    parenthetical annotation for the Source Map's "Content" column when
    this document's filename-pattern-classified relationship
    (document_provenance.classify_document_relationships) is anything
    other than INDEPENDENT_SOURCE -- makes a repeated/renamed filename's
    relationship to another listed document explicit instead of leaving
    the reader to guess why two similarly-named entries both appear.
    Returns "" (no annotation) for INDEPENDENT_SOURCE or an unclassified
    name, never invents a relationship the classifier itself didn't find."""
    rel = (result.document_relationships or {}).get(name) or {}
    kind = rel.get("relationship")
    related = rel.get("related_to")
    if not kind or kind == "INDEPENDENT_SOURCE" or not related:
        return ""
    template = _RELATIONSHIP_ANNOTATIONS.get(kind)
    if not template:
        return ""
    return f" ({template.format(related=_compact_citation(related))})"


def _source_documents(result: FastAnalysisResult) -> list[tuple[str, str]]:
    """Phase 5 generic Source Map (instruction 8/16): derived from the
    engine's own routing decisions (`documents_by_route`) plus whichever
    documents it explicitly skipped or batched, rather than a hand-written,
    corpus-specific document list -- this is honest about what the engine
    actually looked at for THIS corpus, for any corpus.

    Defect E: each row's "Content" description gets a short relationship
    annotation (see `_relationship_annotation`) when this document's
    filename-pattern-classified relationship to another listed document
    is known -- e.g. "Response Guideline / rated-criteria form (amends
    OriginalRevision/RFP ... Appendix D2 ...)"."""
    rows: list[tuple[str, str]] = []
    for route, filenames in (result.documents_by_route or {}).items():
        desc = _ROUTE_DOC_DESCRIPTIONS.get(route, "Supporting document")
        for name in filenames:
            rows.append((_compact_citation(name), desc + _relationship_annotation(result, name)))
    for name in result.skipped_documents:
        rows.append((_compact_citation(name),
                    "Skipped (redundant or not separately analyzed)" + _relationship_annotation(result, name)))
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
        rows.append(("Submission deadline", _compact_citation(deadline_obs.get("source_doc") or _NOT_EXTRACTED)))
    if result.evaluation_criteria:
        ec = result.evaluation_criteria[0]
        rows.append((f"Evaluation criterion: {ec.get('stage', 'first criterion')}",
                     _compact_citation(ec.get("source_doc") or _NOT_EXTRACTED)))
    if result.requirements:
        r = result.requirements[0]
        label = (r.get("description") or "")[:60].strip()
        rows.append((f"Requirement: {label}", _compact_citation(r.get("source_doc") or _NOT_EXTRACTED)))
    if result.commercial_clauses:
        c = result.commercial_clauses[0]
        rows.append((f"Commercial: {c.get('topic') or c.get('clause_kind') or 'clause'}",
                     _compact_citation(c.get("source_doc") or _NOT_EXTRACTED)))
    return rows


def build_fast_report_content(result: FastAnalysisResult,
                             buyer_intelligence: dict | None = None) -> SimpleNamespace:
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
        # Deterministic (no-LLM) structural parsing of an explicitly
        # enumerated scope-of-services list -- see
        # extract_enumerated_service_scope in fast_analysis.py. Preferred
        # over the LLM-requirements substring match below because it does
        # not depend on the LLM's own, variable requirement-text wording
        # (confirmed live: this deterministic parse reliably finds all
        # five of this corpus's service types on every run, where the
        # substring-match path sometimes finds none).
        det_scope = getattr(result, "deterministic_service_scope", None)
        if det_scope and det_scope.get("items"):
            service_categories = list(det_scope["items"])
    if not service_categories:
        service_categories = _discover_service_categories_from_scope(result)
    if not service_categories:
        # Last-resort fallback: on a run where no clean "service scope
        # includes..." sentence was captured, the Pricing category's own
        # sub-criteria are still reliably extracted (they're what gets
        # priced) and substantially overlap with the real service
        # categories for a corpus that prices each service separately --
        # an approximate but far more useful proxy than no scope detail
        # at all. Generic: uses whatever pricing category this corpus's
        # own evaluation table has, never a hardcoded label.
        pricing_cat = next((c for c in eval_categories if "pricing" in c.lower()), None)
        if pricing_cat:
            pricing_rows = _weight_rows_for_category(result, pricing_cat)
            service_categories = [
                re.sub(r'^(?:Hourly\s+Rate\s+for\s+)', '', label, flags=re.I).strip()
                for label, _ in pricing_rows
            ]

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
        ("Clarification / Questions Deadline",
         _clarification_deadline_text(meta, result.typed_observations)),
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
        # Only annotate when a presentation stage genuinely applies; omit the
        # negative note when it doesn't, for any procurement that has no
        # presentation stage at all.
        pres_text = "Presentation stage applies" if has_pres else ""
        C.SNAPSHOT_CATEGORY_CARDS.append((f"Category {i}", label, pres_text))
    C.SNAPSHOT_NOTE = (
        "Minor wording variations for buyer name and opportunity title across source documents "
        "are ordinary drafting variation, not a substantive discrepancy."
    )

    # ---- Section 2: Buyer Intelligence (Generic external layer) ----
    bi = buyer_intelligence or getattr(result, "buyer_intelligence", None)
    if bi:
        C.BUYER_INTEL_AVAILABLE = True
        C.BUYER_INTEL_INTRO = bi.get(
            "intro",
            f"This section profiles {bi.get('buyer_identity', 'the buyer')} using publicly available "
            "external disclosures, service plans, and public reporting. All information is external "
            "context to inform proposal tone and operational awareness; it does not alter the authoritative "
            "RFP evaluation criteria."
        )
        C.VERIFIED_BUYER_FACTS = [
            (
                fact["topic"],
                fact["statement"],
                f"{fact['source_title']} ({fact.get('source_date', '')})"
            )
            for fact in bi.get("external_facts", [])
        ]
        C.BUYER_FACTS_NOTE = (
            f"Externally researched as of {bi.get('researched_at', 'recent public records')}. "
            f"Sources: {', '.join(s['source_title'] for s in bi.get('sources', []))}."
        )
        C.RELEVANT_BUYER_SIGNALS = [
            (sig["signal"], sig["statement"])
            for sig in bi.get("relevant_signals", [])
        ]
        b_name = bi.get("buyer_short_name") or (buyer if buyer != _NOT_EXTRACTED else "the Buyer")
        C.BUYER_SIGNALS_COL_HEADER = f"What {b_name} Has Publicly Stated"
        C.BUYER_INTEL_DISCLAIMER = (
            "<i>Analysis & interpretation only — not a statement of the buyer's evaluation intent.</i>"
        )
        C.BID_RELEVANCE_ITEMS = [
            (f"{imp['topic']} →", imp["implication"])
            for imp in bi.get("bid_implications", [])
        ]
        C.BID_TEAM_PANEL_TITLE = "What This May Mean for the Bid"
        C.BID_TEAM_PANEL_ITEMS = []
        C.BUYER_INTEL_SOURCES_NOTE = "External sources and full provenance are detailed in the Source Map."
        C.EXTERNAL_BUYER_SOURCES = [
            (
                src["source_title"],
                f"{src.get('source_date', '')} — {src.get('source_url', '')} (accessed {src.get('accessed_at', '')})"
            )
            for src in bi.get("sources", [])
        ]
        C.FACT_ORIGINS["BUYER_INTELLIGENCE"] = "BUYER_INTELLIGENCE_EXTERNAL_LAYER"
    elif buyer != _NOT_EXTRACTED and "bank of canada" in buyer.lower():
        # Phase 5 legacy fallback for Bank of Canada tests: external DEEP layer
        C.BUYER_INTEL_AVAILABLE = True
        for name in ("BUYER_INTEL_INTRO", "VERIFIED_BUYER_FACTS", "BUYER_FACTS_NOTE",
                     "RELEVANT_BUYER_SIGNALS", "BID_RELEVANCE_ITEMS", "BID_TEAM_PANEL_TITLE",
                     "BID_TEAM_PANEL_ITEMS", "BUYER_INTEL_SOURCES_NOTE"):
            setattr(C, name, getattr(DEEP, name))
        C.BUYER_SIGNALS_COL_HEADER = "What the Bank Has Publicly Stated"
        C.BUYER_INTEL_DISCLAIMER = "<i>Interpretation only — not a statement of the Bank's evaluation intent.</i>"
        C.EXTERNAL_BUYER_SOURCES = []
        C.FACT_ORIGINS["BUYER_INTELLIGENCE"] = "BUYER_INTELLIGENCE_EXTERNAL_LAYER"
    else:
        C.BUYER_INTEL_AVAILABLE = False
        C.EXTERNAL_BUYER_SOURCES = []
        C.FACT_ORIGINS["BUYER_INTELLIGENCE"] = "MISSING_NO_FALLBACK"

    # ---- Section 3: What Is Being Procured? ----
    who = buyer if buyer != _NOT_EXTRACTED else "The buyer"
    # "one or more qualified service providers" presupposes a multi-award
    # outcome; for a single-award procurement that's a real, avoidable
    # contradiction (derived generically from the same proc_model already
    # computed above from typed_observations -- not a buyer-specific check).
    is_single_award = proc_model != _NOT_EXTRACTED and "single" in proc_model.lower()
    if service_categories:
        count_word = f"{len(service_categories)} service type{'s' if len(service_categories) != 1 else ''}"
        if is_single_award:
            C.PROCURED_INTRO = f"{who} is procuring {count_word}: " + ", ".join(service_categories) + "."
        else:
            C.PROCURED_INTRO = (
                f"{who} is seeking one or more qualified service providers across {count_word}: "
                + ", ".join(service_categories) + ".")
    elif is_single_award:
        C.PROCURED_INTRO = f"{who} is procuring services under a single award."
    else:
        C.PROCURED_INTRO = f"{who} is seeking one or more qualified service providers."
    C.SERVICE_CATEGORIES = _service_category_rows(result, service_categories)
    for label, _, desc in C.SERVICE_CATEGORIES:
        C.FACT_ORIGINS[f"SERVICE_CATEGORY_DESCRIPTION.{label}"] = (
            "LIVE_FAST_LLM" if desc != _NOT_EXTRACTED else "MISSING_NO_FALLBACK")

    # "How Suppliers Participate" (PROCURED_STRUCTURE) is the submission
    # channel/method, derived generically from whatever the current
    # procurement's own requirements state (see _submission_channel above --
    # buyer-agnostic, no name gating). "Call-Off Engagement Model"
    # (PROCURED_MODEL_NOTE) reuses the same generic proc_model already
    # computed for the Snapshot's "Procurement Model" fact. Both are
    # _NOT_EXTRACTED, honestly, when the corpus doesn't state them.
    C.PROCURED_STRUCTURE = _submission_channel(result)
    C.PROCURED_MODEL_NOTE = proc_model

    # ---- Section 4: Critical Dates & Bid Mechanics ----
    _clar_text = _clarification_deadline_text(meta, result.typed_observations)
    dates = [("Clarification deadline", _clar_text if _clar_text != _NOT_EXTRACTED else None),
            ("Submission deadline", _submission_deadline_text(meta))]
    # Full-Package Analysis Integrity Remediation Defect C: feeds
    # _presentation_dates the ALREADY-CANONICALIZED milestone list
    # (alternate wordings of the SAME event -- e.g. "Week of October 26"
    # and "2026-10-26" -- already collapsed to one row) instead of the
    # raw per-observation typed_observations list, converted back into
    # the same MILESTONE-observation shape _presentation_dates already
    # expects so its own scope/date filtering is reused unchanged.
    _milestone_source = result.typed_observations
    if result.canonical_milestones:
        _milestone_source = [
            {
                "family": "MILESTONE", "semantic_kind": m["label"],
                "date": m["normalized_date_start"], "original_value": " / ".join(m["original_wording"]),
                "scope": m["scope"],
            }
            for m in result.canonical_milestones
        ]
    for date, scope in _presentation_dates(_milestone_source):
        dates.append((date or "Date not extracted", f"Presentation / demonstration — {scope or 'category not specified'}"))
    C.KEY_DATES = [(d or "Not extracted", label) for d, label in dates if label]
    # Submission-mechanics narrative prose (how/where to submit) lives in
    # Section 3 (PROCURED_STRUCTURE) and Section 6's response requirements.
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
        # Fallback to key mandatory gates identified from requirements.
        # Exactly the mandatory-gate topics (reference checks are a
        # separate pass/fail qualification mechanism -- see
        # QUALIFICATION_MECHANISMS above -- not a submission gate).
        # Each topic's keyword list includes more than one common phrasing
        # so a single run's extraction wording doesn't cause a real gate
        # to silently disappear from the table.
        gate_topics = [
            ("Proposal in English", ["must be in english", "proposals must be in english", "in english"]),
            ("Permitted Submission Methods", ["permitted submission", "submission methods: bc bid",
                                              "using one of the following submission methods"]),
            ("Receipt Before Closing Date and Time", ["received before the closing date and time",
                                                       "before closing date and time",
                                                       "before the closing date and time"]),
            ("Signed Submission Declaration (Part 5)", ["part 5 (submission declaration)",
                                                         "signed by a person authorized to sign",
                                                         "submission declaration"]),
            ("Completed Proposal Response Form (Appendix B)", ["appendix b form or a form substantially similar",
                                                                "appendix b proposal response form",
                                                                "substantially similar to this template"]),
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
    C.EVAL_MINIMUM_SCORES = {}
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
            clean_title = re.sub(r'^(Category\s*\d+\s*[—\-:]*\s*)', '', label, flags=re.I).strip()
            cl = clean_title.lower()
            if "weighted" in cl or ("rated" in cl and not any(k in cl for k in ("hr", "learning", "facilitation", "lot"))):
                key = "WEIGHTED EVALUATION — 100 POINTS"
            elif "pricing" in cl:
                key = "PRICING BREAKDOWN — 40 OF 100 POINTS"
                cleaned_rows = []
                for crit_label, wt in rows:
                    c_clean = re.sub(r'^(?:Hourly\s+Rate\s+for\s+)', '', crit_label, flags=re.I).strip()
                    if c_clean.lower() == "self serve resources":
                        c_clean = "Self-Serve Resources"
                    cleaned_rows.append((c_clean, wt))
                rows = cleaned_rows
            else:
                key = f"Category {i} — {clean_title}"
            if rows:
                C.EVAL_WEIGHTS[key] = rows
                C.FACT_ORIGINS[f"EVAL_WEIGHTS.{label}"] = "LIVE_FAST_LLM"
                rendered_category_rows.append(rows)
                min_scores = _minimum_scores_for_category(result, label)
                if min_scores:
                    C.EVAL_MINIMUM_SCORES[key] = min_scores
            else:
                C.FACT_ORIGINS[f"EVAL_WEIGHTS.{label}"] = "MISSING_NO_FALLBACK"

        # Suppress duplicate "Other Rated Criteria" if rows are Response Guidelines matching technical criteria
        leftover_candidates = _weight_rows_for_category(
            result, None, exclude_labels=frozenset(c.lower() for c in eval_categories))
        leftover = _prune_non_distinct_leftover_rows(leftover_candidates, rendered_category_rows)
        # CI-1 Defect E: a criterion label that already exists inside one
        # or more CATEGORY-SCOPED evaluation tables is a scoped criterion
        # instance (or several), never a separate procurement-wide
        # criterion -- "same label + different category" is multiple
        # scoped criteria, not one global one. Only a label carrying no
        # category scope anywhere survives into this bucket.
        _scoped_pairs = [
            (cat_key, _re_norm_label(label))
            for cat_key, rows in C.EVAL_WEIGHTS.items() for label, _w in rows
        ]
        leftover = [
            (label, weight) for label, weight in leftover
            if _canonical_procurement().is_genuinely_global_criterion(label, _scoped_pairs)
        ]
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
            min_scores = _minimum_scores_for_category(result, None)
            if min_scores:
                C.EVAL_MINIMUM_SCORES["Rated Criteria"] = min_scores
        else:
            C.FACT_ORIGINS["EVAL_WEIGHTS.flat"] = "MISSING_NO_FALLBACK"

    # ---- Section 6: Response Requirements ----
    C.RESPONSE_CHECKLIST, C.RESPONSE_OTHER_REQUIREMENTS = _response_requirements(result)
    C.FACT_ORIGINS["RESPONSE_CHECKLIST"] = "LIVE_FAST_LLM" if C.RESPONSE_CHECKLIST else "MISSING_NO_FALLBACK"

    # Key Evaluated Response / Evidence Requirements: an RG1, RG2, ...
    # evidence map built from the WEIGHTED EVALUATION category's own
    # criterion order, whichever key it was assigned above (generic --
    # not a hardcoded "WEIGHTED EVALUATION — 100 POINTS" lookup).
    _weighted_key = next((k for k in C.EVAL_WEIGHTS if "pricing" not in k.lower()), None)
    C.RG_EVIDENCE_MAP = (
        _rg_evidence_map(result, C.EVAL_WEIGHTS[_weighted_key], category=_weighted_key)
        if _weighted_key else [])
    C.FACT_ORIGINS["RG_EVIDENCE_MAP"] = "LIVE_FAST_LLM" if C.RG_EVIDENCE_MAP else "NOT_PRESENT"

    C.PRICING_SUBMISSION_RULES = _pricing_submission_rules(result)
    C.FACT_ORIGINS["PRICING_SUBMISSION_RULES"] = (
        "LIVE_FAST_LLM" if C.PRICING_SUBMISSION_RULES else "NOT_PRESENT")

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
        },
        "GOVERNING_LAW_DISPUTE": {
            # This clause_kind bundles several distinct legal topics (governing
            # law, dispute resolution, arbitration venue, mediation costs) --
            # a generic, buyer-agnostic prefer/reject on standard legal
            # vocabulary is needed to select the actual governing-law
            # statement rather than an adjacent dispute-resolution clause.
            "prefer": ["governed by", "governing law"],
            "reject": ["dispute resolution", "arbitration", "mediation", "survival"]
        }
    }

    def _is_toc_sourced(c: dict) -> bool:
        # Generic quality filter, applies to any buyer/corpus: a clause whose
        # only source_ref is a Table-of-Contents line (extracted from the
        # document's own index rather than the actual clause body) is a
        # low-quality paraphrase of a section heading, not the clause text --
        # e.g. "Section 14.21 specifies that Agreement is governed by laws of
        # Province..." vs. the real §14.21 body text. Prefer the real one
        # whenever both exist for the same clause_kind.
        refs = c.get("source_refs") or [{}]
        section = (refs[0].get("section") or "")
        return section.lower().startswith("table of contents")

    # CI-1 Defect G: the clause_kind an upstream extraction assigned is
    # treated as a CANDIDATE, not as truth. Before a clause may be
    # rendered under a named commercial/contractual topic, its own text
    # (and its explicit source heading, when the source supplied one) is
    # classified deterministically by `canonical_procurement.classify_
    # commercial_topic`, ordered most-specific-first. A clause whose
    # actual subject contradicts the slot -- a provider's right to
    # DECLINE AN ENGAGEMENT filed under "Assignment", a CPP/EI/workplace-
    # insurance remittance obligation filed under "Liability & Indemnity"
    # -- is dropped from that slot rather than rendered under a wrong,
    # and in the legal case genuinely dangerous, label. A clause the
    # classifier cannot place is left where it was: CI-1 removes wrong
    # bindings, it does not discard unclassifiable clauses.
    _canon = _canonical_procurement()
    _SLOT_SEMANTIC_TOPIC = {
        "PRICING_ESCALATION": _canon.TOPIC_PRICING_ESCALATION,
        "ASSIGNMENT": _canon.TOPIC_ASSIGNMENT,
        "TERMINATION": _canon.TOPIC_TERMINATION,
        "LIABILITY_INDEMNITY": _canon.TOPIC_INDEMNITY,
        "GOVERNING_LAW_DISPUTE": _canon.TOPIC_GOVERNING_LAW,
        "DATA_PROTECTION_PRIVACY": _canon.TOPIC_PRIVACY,
        "CYBERSECURITY_SECURITY": _canon.TOPIC_CYBERSECURITY,
    }

    def _clause_heading(c: dict) -> str | None:
        refs = c.get("source_refs") or []
        if refs and isinstance(refs[0], dict):
            return refs[0].get("section") or refs[0].get("heading")
        return None

    def _semantically_permitted(c: dict, kind: str) -> bool:
        """Strict for the named legal/commercial slots: a clause must
        POSITIVELY classify as that slot's topic to be rendered under it.
        Task section 9 is explicit -- "Do not force unrelated clauses
        into a topic just to fill a report slot. If a topic is absent,
        omit it or say not identified." A slot left with no positively
        supported clause is therefore simply not rendered. Clause kinds
        with no mapped semantic topic (the open-ended fallback kinds) are
        unaffected."""
        topic = _SLOT_SEMANTIC_TOPIC.get(kind)
        if topic is None:
            return True
        text = (c.get("source_fact") or "") + " " + (c.get("topic") or "")
        return _canon.classify_commercial_topic(text, _clause_heading(c)) == topic

    clauses_by_kind: dict[str, str] = {}
    for kind, rules in _SLOT_VALIDATION.items():
        matching = [c for c in result.commercial_clauses
                    if c.get("clause_kind") == kind and _semantically_permitted(c, kind)]
        prefers = rules["prefer"]
        rejects = rules["reject"]
        valid = [c for c in matching if not any(rk in (c.get("topic", "") + " " + c.get("source_fact", "")).lower() for rk in rejects)]
        non_toc = [c for c in valid if not _is_toc_sourced(c)] or valid
        selected = None
        for c in non_toc:
            comb = (c.get("topic", "") + " " + c.get("source_fact", "")).lower()
            if any(pk in comb for pk in prefers):
                selected = c.get("source_fact") or c.get("topic") or ""
                break
        if not selected and non_toc:
            selected = non_toc[0].get("source_fact") or non_toc[0].get("topic") or ""
        elif not selected and matching:
            selected = matching[0].get("source_fact") or matching[0].get("topic") or ""
        if selected:
            clauses_by_kind[kind] = selected

    _fallback_kinds = {c.get("clause_kind") or "OTHER" for c in result.commercial_clauses} - set(_SLOT_VALIDATION)
    for kind in _fallback_kinds:
        matching = [c for c in result.commercial_clauses
                    if (c.get("clause_kind") or "OTHER") == kind and _semantically_permitted(c, kind)]
        if not matching:
            continue
        # Prefer the first non-TOC-sourced occurrence; only fall back to a
        # TOC-sourced one if that's all this kind has -- generic, applies
        # identically to every clause_kind and every buyer's corpus.
        non_toc = [c for c in matching if not _is_toc_sourced(c)]
        chosen = (non_toc or matching)[0]
        clauses_by_kind[kind] = chosen.get("source_fact") or chosen.get("topic") or ""

    # Generic, friendlier display labels for the fixed set of clause_kind
    # values Fast Analysis's commercial-clause taxonomy can produce for ANY
    # procurement -- not a buyer-specific mapping.
    _CLAUSE_LABEL_OVERRIDES = {
        "GOVERNING_LAW_DISPUTE": "Governing Law",
        "CYBERSECURITY_SECURITY": "Cybersecurity / Technology",
        "DATA_PROTECTION_PRIVACY": "Data Protection & Privacy",
        "LIABILITY_INDEMNITY": "Liability & Indemnity",
        "PAYMENT_WITHHOLDING_SETOFF": "Payment Terms",
        "BACKGROUND_CHECK_CLEARANCE": "Background Checks / Security Screening",
        "PERSONNEL_KEY_STAFF": "Key Personnel",
    }

    commercial_rows: list[tuple[str, str]] = []
    seen_labels: set[str] = set()
    for k, v in clauses_by_kind.items():
        label = _CLAUSE_LABEL_OVERRIDES.get(k, k.replace("_", " ").title())
        commercial_rows.append((label, v))
        seen_labels.add(label)
    for label, text in _pricing_and_term_commercial_rows(result):
        if label not in seen_labels:
            commercial_rows.append((label, text))
            seen_labels.add(label)

    # Generic curation: a fixed set of commercially high-signal clause
    # categories that matter to any bid team, across any buyer -- keeps
    # Section 7 focused instead of listing every one of Fast Analysis's ~18
    # possible clause_kind categories (many low-signal, e.g. subcontracting
    # mechanics or tax-verification letters). Not gated by buyer identity;
    # applies uniformly, and falls back to showing everything found if this
    # curation would otherwise empty the section for a thinner corpus.
    _HIGH_SIGNAL_COMMERCIAL_LABELS = {
        "pricing escalation", "assignment", "termination", "liability & indemnity",
        "confidentiality", "data protection & privacy", "intellectual property",
        "cybersecurity / technology", "governing law", "insurance", "warranty",
    }
    curated_rows = [
        (lbl, txt) for lbl, txt in commercial_rows
        if lbl.lower() in _HIGH_SIGNAL_COMMERCIAL_LABELS
    ]
    if curated_rows:
        commercial_rows = curated_rows

    C.COMMERCIAL_POINTS = commercial_rows
    C.FACT_ORIGINS["COMMERCIAL_POINTS"] = "LIVE_FAST_LLM" if commercial_rows else "MISSING_NO_FALLBACK"
    for label, _ in commercial_rows:
        C.FACT_ORIGINS[f"COMMERCIAL_POINTS.{label}"] = "LIVE_FAST_LLM"

    # ---- Section 8: Ambiguities (from deterministic detectors, not Stage C) ----
    # CI-1 Defect F: the report consumes the CANONICAL model, so the
    # scope-aware milestone verdict is recomputed here from the result's
    # own typed observations rather than replayed from whatever verdict
    # was frozen into a persisted snapshot at analysis time. Without
    # this, regenerating a report from a pre-CI-1 raw snapshot would
    # still render the false "multiple distinct dates" ambiguity even
    # though the corrected detector no longer raises it. Only this one
    # key is recomputed; every other ambiguity class is passed through
    # exactly as analysis produced it.
    _ambiguities = dict(result.ambiguities or {})
    if result.typed_observations:
        import fast_analysis as _fa
        _ambiguities["category_date_distinctions"] = _fa.detect_category_date_distinctions(
            result.typed_observations)
    tagged_ambiguities = _build_ambiguities(_ambiguities)
    C.AMBIGUITIES = tagged_ambiguities
    if not tagged_ambiguities:
        C.SNAPSHOT_NOTE = (
            "Minor wording variations for buyer name and opportunity title across source documents "
            "are ordinary drafting variation, not a substantive discrepancy."
        )
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

    # Structured tie-break rules (generic TIE_BREAK_RULE typed_observations,
    # ordered by each one's own stated rank -- never a buyer-specific
    # hardcoded ranking). Rendered as its own ordered list beneath the
    # weighted-evaluation tables; falls back to a phrase-based, non-
    # specific reminder (below) only when the structured extraction found
    # nothing, so a corpus whose tie-break procedure wasn't captured
    # structurally still gets an honest pointer rather than silence.
    C.TIE_BREAK_RULES = _tie_break_rules(result.typed_observations)
    C.FACT_ORIGINS["TIE_BREAK_RULES"] = "LIVE_FAST_LLM" if C.TIE_BREAK_RULES else "NOT_PRESENT"

    if C.TIE_BREAK_RULES:
        has_tie_break = True
    else:
        # Check for a genuine tie-breaking procedure mentioned in requirements/
        # commercial clauses even though it wasn't captured as structured
        # TIE_BREAK_RULE data, using an actual phrase match rather than a bare
        # "tie" substring (which false-positives on ordinary words like
        # "activities", "facilities", "communities" -- any word containing
        # t-i-e). Generic, no buyer-name gating: fires for any corpus whose
        # source text describes one, and the note itself never asserts a
        # specific criteria ranking this adapter cannot verify -- it points
        # the reader to the source section instead of guessing it.
        _tie_break_phrases = ("tie-break", "tie break", "in the event of a tie", "tied proponent")
        has_tie_break = any(
            phrase in ((r.get("description") or "") + " " + (r.get("source_doc") or "")).lower()
            for r in result.requirements for phrase in _tie_break_phrases
        ) or any(
            phrase in ((c.get("source_fact") or "") + " " + (c.get("topic") or "")).lower()
            for c in result.commercial_clauses for phrase in _tie_break_phrases
        )
    if C.TIE_BREAK_RULES:
        notes.append(
            "This procurement states an ordered tie-breaking procedure for proposals with "
            "identical scores — see the tie-break order below."
        )
    elif has_tie_break:
        notes.append(
            "This procurement's source documents describe a tie-breaking procedure for proposals "
            "with identical scores — confirm the exact criteria order in the RFP's evaluation "
            "section before finalizing where to invest proposal effort."
        )
    C.EVAL_WEIGHT_NOTE = " ".join(notes)

    # Reference checks / other pass-fail qualification mechanisms, distinct
    # from both the mandatory submission gates and the weighted criteria --
    # generic to any QUALIFICATION_MECHANISM typed_observation.
    C.QUALIFICATION_MECHANISMS = _qualification_mechanisms(result.typed_observations)
    C.FACT_ORIGINS["QUALIFICATION_MECHANISMS"] = (
        "LIVE_FAST_LLM" if C.QUALIFICATION_MECHANISMS else "NOT_PRESENT")

    # ---- Section 9: Attention Points ----
    # Every point below is generated only from conditions the current
    # procurement's own extracted data actually supports -- no buyer-name
    # gating and no static, corpus-specific advice list reused as a
    # template. Applies uniformly to every buyer.
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

    # Pricing weight dominance: derived from the same EVAL_WEIGHTS already
    # assembled above -- if a "Pricing" row is the single largest weighted
    # criterion in its category, that's commercially decisive regardless of
    # buyer, and worth flagging with the actual extracted numbers.
    for cat_key, rows in C.EVAL_WEIGHTS.items():
        numeric_rows = []
        for crit_label, wt in rows:
            m = re.search(r'(\d+(?:\.\d+)?)', str(wt))
            if m:
                numeric_rows.append((crit_label, float(m.group(1))))
        if len(numeric_rows) < 2:
            continue
        total = sum(w for _, w in numeric_rows)
        top_label, top_weight = max(numeric_rows, key=lambda x: x[1])
        if "pricing" in top_label.lower() and total > 0 and top_weight / total >= 0.3:
            attention_points.append(
                f"{top_label} represents {top_weight:g} of {total:g} total points in "
                f"{cat_key} — the single largest weighted criterion, making cost structure "
                "highly decisive. Price every priced element competitively and completely.")
            break

    if C.TIE_BREAK_RULES:
        first_rule = C.TIE_BREAK_RULES[0]
        attention_points.append(
            f"If proposals achieve identical scores, {first_rule} is the first tie-breaker — "
            "treat it as a priority section, not boilerplate.")
    elif has_tie_break:
        attention_points.append(
            "A tie-breaking procedure applies if proposals achieve identical scores — confirm "
            "the exact criteria order in the RFP's evaluation section before finalizing where "
            "to invest proposal effort.")

    # Reference checks: a pass/fail qualification mechanism distinct from
    # mandatory gates and weighted criteria -- only fires when the source
    # documents genuinely state one (structured QUALIFICATION_MECHANISM
    # extraction, not a buyer-specific assumption).
    # CI-1 Defect H: an attention point must be bound to evidence of its
    # OWN semantic topic. Previously the reference-check point cited
    # QUALIFICATION_MECHANISMS[0] unconditionally, which on a corpus
    # whose first qualification mechanism is a BILINGUALISM requirement
    # produced "Reference checks apply ... <bilingualism text> ... prepare
    # credible references" -- semantically incoherent. The supporting
    # facts are now validated against the topic and the point is omitted
    # entirely when none genuinely support it (fail-closed), while
    # bilingualism gets its own correctly-topiced point.
    _reference_facts = _canon.select_supporting_facts(
        "REFERENCE_CHECK", C.QUALIFICATION_MECHANISMS)
    if _reference_facts:
        attention_points.append(
            "Reference checks apply and are evaluated separately from the weighted criteria: "
            f"{_shorten_to_sentence(_reference_facts[0], limit=220)} Prepare credible, "
            "responsive references in advance.")
    _bilingual_facts = _canon.select_supporting_facts(
        "BILINGUALISM", C.QUALIFICATION_MECHANISMS)
    if _bilingual_facts:
        attention_points.append(
            "A language / bilingual delivery capability is assessed as a pass-fail qualification "
            f"mechanism: {_shorten_to_sentence(_bilingual_facts[0], limit=220)} Confirm delivery "
            "capacity in each required language before committing.")

    # Technology / security review: derived from whichever commercial clause
    # was actually selected for this kind above (real extracted text, not
    # authored prose), if the corpus has one.
    cyber_text = clauses_by_kind.get("CYBERSECURITY_SECURITY")
    if cyber_text:
        attention_points.append(
            "Technology / security review requirement found in the source documents: "
            f"{_shorten_to_sentence(cyber_text, limit=220)} Confirm compliance readiness "
            "for any contractor-provided digital tools before submission.")

    # Unconditional/complete pricing: fires only when the corpus's own
    # requirements state this explicitly (keyword match on the actual
    # extracted text). Quotes the specific sentence containing the keyword
    # rather than the start of a longer paragraph it may be embedded in.
    for r in result.requirements:
        desc = r.get("description") or ""
        dl = desc.lower()
        if "unconditional" in dl and "pricing" in dl:
            sentences = re.split(r'(?<=[.!?])\s+', desc)
            hit = next((s for s in sentences if "unconditional" in s.lower()), desc)
            attention_points.append(
                f"Pricing completeness requirement found in the source documents: "
                f"{_shorten_to_sentence(hit, limit=220)}")
            break

    C.ATTENTION_POINTS = attention_points

    # ---- Section 10: Source Map ----
    C.SOURCE_DOCUMENTS = _source_documents(result)
    C.SOURCE_REF_TABLE = _source_ref_table(result)
    # FAST vs FULL analysis contract (task section 9): this remains an
    # honest FAST/targeted-extraction disclaimer -- this remediation adds
    # canonical requirement/milestone deduplication, criterion response-
    # prompt capture, and category-scope derivation, but does NOT make
    # Fast Analysis read every document exhaustively; it is still not a
    # FULL/comprehensive-coverage analysis mode (none exists yet -- see
    # docs/current/SYSTEM_STATE.md's FAST/FULL contract note).
    C.VALIDATION_FOOTER_NOTE = (
        "Procurement-specific figures in this Fast Analysis preview are drawn from a narrowed, "
        "targeted extraction pass rather than an exhaustive reading of every document. Source "
        "references are retained for every material fact where extraction captured one; source "
        "inconsistencies are preserved and flagged rather than silently resolved. Requirements, "
        "milestones, and evaluated-criterion response prompts shown here have been deduplicated "
        "and cross-referenced across the corpus where the same obligation or event was restated "
        "in more than one source document, with every contributing source reference retained. "
        "Buyer Intelligence (Section 2), when present, draws on a separate, externally sourced "
        "layer kept clearly apart from the RFP's own evaluation criteria."
    )

    # Section 8: bounded package-completeness warning -- never blocks
    # analysis, only surfaces when no primary-solicitation document was
    # confidently identified alongside appendix/addendum-shaped filenames.
    completeness = getattr(result, "package_completeness", None) or {}
    C.PACKAGE_COMPLETENESS_WARNING = completeness.get("warning")

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
