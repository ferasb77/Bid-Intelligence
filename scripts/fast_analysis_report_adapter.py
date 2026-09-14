"""
Deterministic adapter: FastAnalysisResult -> the same report-content
contract used by scripts/boc_bid_intelligence_preview_content.py, so the
existing PDF renderer (build_boc_bid_intelligence_preview_pdf.py) can
produce a directly comparable Fast Analysis PDF with zero rendering-code
changes.

No LLM calls here -- purely deterministic formatting over already-extracted
facts. Buyer Intelligence content is imported unchanged from the Deep
content module, per the explicit instruction that Buyer Intelligence is a
separate, externally-sourced layer this package does not redesign.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.boc_bid_intelligence_preview_content as DEEP
from fast_analysis import FastAnalysisResult, carry_forward_category_scope

MASTER_RFP = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"
D1_DOC = "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx"
D2_DOC = "Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx"
D3_DOC = "OriginalRevision/RFP 2026-026 - Appendix D3 - Rated Criteria Response Form.docx"
APPENDIX_E = "OriginalRevision/RFP 2026-026 - Appendix E - Pricing Form.xlsx"
APPENDIX_G = "OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx"

_CATEGORY_PATTERNS = [
    (1, re.compile(r"category\s*1\b", re.I)),
    (2, re.compile(r"category\s*2\b", re.I)),
    (3, re.compile(r"category\s*3\b", re.I)),
]
CATEGORY_NAMES = {
    1: "Learning & Development Programs",
    2: "HR Advisory Services",
    3: "Facilitation & Team Effectiveness",
}

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
        return ("Multi-vendor call-off — the Bank may qualify more than one supplier and issue "
                "individual engagements as needs arise, rather than a single fixed-scope award")
    if "SINGLE_SUPPLIER_AWARD" in kinds:
        return "Single Contract"
    return "Not stated in the extracted data"


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
        return (f"{base}, with {ext['option_count']} optional {ext['duration']}-{ext['unit']} "
                "extensions (subject to Bank satisfaction and mutual agreement)")
    return base


def _submission_deadline_text(meta: dict) -> str:
    date = meta.get("submission_deadline") or "Not extracted"
    time_part = meta.get("submission_time")
    return f"{date}" + (f", {time_part}" if time_part else "") + " — via MERX (electronic only)"


def _category_requirements(requirements: list[dict]) -> dict[int, list[str]]:
    """V2 fix for the v1 category-description defect: a requirement is
    category-specific only if it names EXACTLY ONE category. v1's boilerplate
    bug ("Proponents may submit a proposal for one or more of the service
    categories: Category 1, Category 2, Category 3...") mentions all three
    categories in one sentence, so under the old any-match rule it was tagged
    to all three identically. Requiring an exclusive match routes that kind
    of cross-category summary sentence to none of them instead of all of
    them."""
    by_cat: dict[int, list[str]] = {1: [], 2: [], 3: []}
    for r in requirements:
        desc = r.get("description") or ""
        matched = {cat for cat, pat in _CATEGORY_PATTERNS if pat.search(desc)}
        if len(matched) != 1:
            continue
        cat = next(iter(matched))
        if desc not in by_cat[cat]:
            by_cat[cat].append(desc)
    return by_cat


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
    extracted by Fast Analysis (Appendix E's CONTRACT_NARROW route covers
    pricing-structure requirements; CONTRACT_TERM typed_observations cover
    the base term/extensions) -- v1's defect was that Section 7 only ever
    looked at commercial_clauses, never merging in these other already-real
    facts (adapter-mapping gap, not an extraction gap).

    V4 addition: Abnormally Low Pricing now prefers the focused pricing
    task's own ABNORMALLY_LOW_PRICING occurrences (correctly grounded in
    the master RFP's Stage 4 Pricing section -- see the V4 implementation
    report's root-cause investigation) over the old Appendix-E-requirements
    heuristic, which was never the fact's real source to begin with."""
    rows: list[tuple[str, str]] = []
    e_reqs = [r.get("description") for r in result.requirements
             if r.get("source_doc") == APPENDIX_E and r.get("description")]
    pricing_structure = next(
        (t for t in e_reqs if "pric" in t.lower() and "abnormally" not in t.lower()), None)
    if pricing_structure:
        rows.append(("Pricing Structure", pricing_structure))
    abnormally_low_occ = next(
        (p.get("raw_wording") for p in result.pricing_occurrences
         if (p.get("semantic_kind") or "").upper() == "ABNORMALLY_LOW_PRICING" and p.get("raw_wording")),
        None)
    abnormally_low = abnormally_low_occ or next(
        (t for t in e_reqs if "abnormally low" in t.lower()
         or ("bond" in t.lower() and "pric" in t.lower())), None)
    if abnormally_low:
        rows.append(("Abnormally Low Pricing", abnormally_low))
    term_text = _contract_term(result.typed_observations)
    if term_text and term_text != "term not confidently extracted":
        rows.append(("Contract Term & Extensions",
                     f"{term_text[0].upper() + term_text[1:]}. Individual call-off engagements "
                     "run within that umbrella on their own, typically shorter, timelines."))
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
        tagged.append({
            "_type": _AMBIGUITY_TYPE_EVAL_WEIGHT,
            "issue": f"More than one point value stated for “{conf['label']}”.",
            "why": f"Competing values found: {', '.join(conf['competing_values'])}.",
            "source": "RFP 2026-026, multiple internal scoring tables.",
            "question": f"Please confirm the authoritative weight for “{conf['label']}”.",
        })
    for amb in ambiguities.get("pricing_stage_ambiguity", []):
        tagged.append({
            "_type": _AMBIGUITY_TYPE_PRICING_STAGE,
            "issue": amb["detail"], "why": "Bidders need to know if price is scored once or twice.",
            "source": "RFP 2026-026 evaluation structure.",
            "question": "Please confirm whether Stage 4 pricing is the sole pricing assessment.",
        })
    for dist in ambiguities.get("category_date_distinctions", []):
        tagged.append({
            "_type": _AMBIGUITY_TYPE_CATEGORY_DATE,
            "issue": f"Multiple distinct dates found for milestone type {dist['milestone_kind']}.",
            "why": "Likely category-specific scheduling, not a true conflict, but worth confirming.",
            "source": "RFP 2026-026 internal milestone mentions.",
            "question": "Please confirm the date applicable to each category.",
        })
    if not tagged:
        tagged = [
            {**DEEP.AMBIGUITIES[0], "_type": _AMBIGUITY_TYPE_EVAL_WEIGHT},
            {**DEEP.AMBIGUITIES[1], "_type": _AMBIGUITY_TYPE_PRICING_STAGE},
            {**DEEP.AMBIGUITIES[2], "_type": _AMBIGUITY_TYPE_CATEGORY_DATE},
        ]
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


def _weight_rows(evaluation_criteria: list[dict], source_doc: str) -> list[tuple[str, str]]:
    """Legacy path: weight rows sourced from the general per-document
    evaluation_criteria family, filtered by source_doc == one of D1/D2/D3.
    V4 finding: D1/D2/D3's own source text contains ZERO weight values (no
    tables, no numeric point/percent mentions tied to any criterion,
    confirmed by direct inspection of all three files) -- the general
    route's per-document LLM call was never actually grounded when it
    returned a weight for these documents. Kept only as a secondary
    fallback behind the V4 focused-task occurrences (_occurrence_weight_rows),
    which are correctly sourced from the master RFP's own Rated Criteria
    table -- the table's real, sole location."""
    rows = []
    seen = set()
    for ec in evaluation_criteria:
        if ec.get("source_doc") != source_doc:
            continue
        weight = ec.get("weight")
        label = ec.get("stage")
        if not weight or not label:
            continue
        key = (label, weight)
        if key in seen:
            continue
        seen.add(key)
        rows.append((label, weight))
    return rows


_CATEGORY_SCOPE_PATTERNS = {
    1: re.compile(r'\bd1\b|category\s*1\b|learning\s*(&|and)\s*development', re.I),
    2: re.compile(r'\bd2\b|category\s*2\b|hr\s*advisory', re.I),
    3: re.compile(r'\bd3\b|category\s*3\b|facilitation', re.I),
}


def _classify_category_scope(scope_text) -> int | None:
    """Map a focused-task occurrence's free-text category_scope (e.g.
    'Appendix D1 - Learning & Development Programs and Assessments') to a
    category number, by generic keyword matching -- not by exact string
    equality, since the model may phrase the scope slightly differently
    call to call."""
    if not scope_text:
        return None
    for cat, pattern in _CATEGORY_SCOPE_PATTERNS.items():
        if pattern.search(scope_text):
            return cat
    return None


_NUMERIC_WEIGHT_RE = re.compile(r'\d+\s*(points?|pts?|%)', re.I)


def _occurrence_weight_rows(evaluation_occurrences: list[dict], category_num: int) -> list[tuple[str, str]]:
    """V4: weight rows sourced from the focused rated-criteria task's own
    occurrences (LIVE_FAST_LLM, correctly grounded in the master RFP's
    Rated Criteria table -- see _weight_rows' docstring for why the old
    per-D-document path was never actually grounded). Only numeric
    points/percent weights qualify -- a pass/fail gate row (e.g.
    'Presentations: PASS / FAIL') is real content but belongs in
    GATE_EXAMPLES, not a points-weighted table."""
    rows = []
    seen = set()
    for occ in evaluation_occurrences:
        label = occ.get("criterion_label")
        weight = occ.get("weight")
        if not label or not weight:
            continue
        if label.strip().lower() in ("total points", "total"):
            continue
        if not _NUMERIC_WEIGHT_RE.search(weight):
            continue
        if _classify_category_scope(occ.get("category_scope")) != category_num:
            continue
        key = (label, weight)
        if key in seen:
            continue
        seen.add(key)
        rows.append((label, weight))
    return rows


def build_fast_report_content(result: FastAnalysisResult) -> SimpleNamespace:
    meta = result.doc_metadata_by_doc.get(MASTER_RFP, {})
    C = SimpleNamespace()
    # V4 (audit S 12/S 26): explicit origin tracking for critical report
    # facts -- LIVE_FAST_LLM / DETERMINISTIC_FAST_EXTRACTION /
    # BUYER_INTELLIGENCE_EXTERNAL_LAYER / SAFETY_NET_FALLBACK. Set inline as
    # each section is built, from the actual code path taken, not inferred
    # after the fact.
    C.FACT_ORIGINS = {}

    # ---- Cover (unchanged shape) ----
    C.TITLE = DEEP.TITLE
    C.SUBTITLE_1 = DEEP.SUBTITLE_1
    C.SUBTITLE_2 = DEEP.SUBTITLE_2
    C.COVER_FOOTER = DEEP.COVER_FOOTER

    # ---- Section 1: Snapshot ----
    buyer = meta.get("client") or "Bank of Canada"
    solnum = meta.get("file_number") or "RFP 2026-026"
    title = meta.get("title") or DEEP.SUBTITLE_2
    C.SNAPSHOT_FACTS = [
        ("Buyer", buyer),
        ("Solicitation Number", solnum),
        ("Opportunity", title),
        ("Submission Deadline", _submission_deadline_text(meta)),
        ("Clarification / Questions Deadline", meta.get("clarification_deadline") or "Not extracted"),
        ("Procurement Model", _procurement_model(result.typed_observations)),
        ("Contract Term", _contract_term(result.typed_observations)),
        ("Service Categories", "3 — Learning & Development, HR Advisory, Facilitation & Team Effectiveness"),
    ]
    category_page_limits = {1: result.page_limits.get(D1_DOC), 2: result.page_limits.get(D2_DOC),
                            3: result.page_limits.get(D3_DOC)}
    presentation_cats = {scope for _, scope in _presentation_dates(result.typed_observations)}
    C.SNAPSHOT_CATEGORY_CARDS = []
    for cat in (1, 2, 3):
        pl = category_page_limits.get(cat)
        pl_text = f"{pl}-page limit" if pl else "page limit not extracted"
        has_pres = any(str(cat) in c for c in presentation_cats) if presentation_cats else (cat in (1, 3))
        pres_text = "Presentation stage applies" if has_pres else "No presentation stage"
        C.SNAPSHOT_CATEGORY_CARDS.append(
            (f"Category {cat}", CATEGORY_NAMES[cat], f"{pl_text} · {pres_text}")
        )
    C.SNAPSHOT_NOTE = DEEP.SNAPSHOT_NOTE

    # ---- Section 2: Buyer Intelligence (unchanged, external layer) ----
    for name in ("BUYER_INTEL_INTRO", "VERIFIED_BUYER_FACTS", "BUYER_FACTS_NOTE",
                "RELEVANT_BUYER_SIGNALS", "BID_RELEVANCE_ITEMS", "BID_TEAM_PANEL_TITLE",
                "BID_TEAM_PANEL_ITEMS", "BUYER_INTEL_SOURCES_NOTE"):
        setattr(C, name, getattr(DEEP, name))
    C.FACT_ORIGINS["BUYER_INTELLIGENCE"] = "BUYER_INTELLIGENCE_EXTERNAL_LAYER"

    # Deterministic (regex, no LLM) page-limit facts.
    for cat, doc in ((1, D1_DOC), (2, D2_DOC), (3, D3_DOC)):
        C.FACT_ORIGINS[f"PAGE_LIMIT.Category {cat}"] = (
            "DETERMINISTIC_FAST_EXTRACTION" if result.page_limits.get(doc) else "SAFETY_NET_FALLBACK")

    # ---- Section 3: What Is Being Procured? ----
    C.PROCURED_INTRO = DEEP.PROCURED_INTRO
    cat_reqs = _category_requirements(result.requirements)
    C.SERVICE_CATEGORIES = []
    for idx, cat in enumerate((1, 2, 3)):
        items = cat_reqs.get(cat) or []
        # Exclusively-matched, category-specific text when Fast extracted it;
        # otherwise fall back to the validated, corpus-structural category
        # scope description rather than a placeholder or (worse) the same
        # cross-category boilerplate for all three (the v1 defect).
        desc = " ".join(items[:2]) if items else DEEP.SERVICE_CATEGORIES[idx][2]
        C.SERVICE_CATEGORIES.append((CATEGORY_NAMES[cat], f"Category {cat}", desc))
        C.FACT_ORIGINS[f"SERVICE_CATEGORY_DESCRIPTION.Category {cat}"] = (
            "LIVE_FAST_LLM" if items else "SAFETY_NET_FALLBACK")
    C.PROCURED_STRUCTURE = DEEP.PROCURED_STRUCTURE
    C.PROCURED_MODEL_NOTE = DEEP.PROCURED_MODEL_NOTE

    # ---- Section 4: Critical Dates & Bid Mechanics ----
    dates = [("Clarification deadline", meta.get("clarification_deadline")),
            ("Submission deadline", _submission_deadline_text(meta))]
    for date, scope in _presentation_dates(result.typed_observations):
        dates.append((date or "Date not extracted", f"Presentation / demonstration — {scope or 'category not specified'}"))
    C.KEY_DATES = [(d or "Not extracted", label) for d, label in dates if label]
    C.BID_MECHANICS = DEEP.BID_MECHANICS
    C.DATES_NOTE = DEEP.DATES_NOTE

    # ---- Section 5: Evaluation ----
    C.EVAL_STAGES = DEEP.EVAL_STAGES
    gate_criteria = [ec for ec in result.evaluation_criteria
                     if (ec.get("evaluation_role") or "") == "Qualification / Gate" and ec.get("threshold")]
    C.GATE_EXAMPLES = [f"{ec.get('stage', 'Criterion')}: {ec['threshold']}" for ec in gate_criteria[:6]] \
        or DEEP.GATE_EXAMPLES
    C.FACT_ORIGINS["GATE_EXAMPLES"] = "LIVE_FAST_LLM" if gate_criteria else "SAFETY_NET_FALLBACK"

    # V4: prefer the focused rated-criteria task's own occurrences (LIVE_FAST_LLM,
    # correctly grounded in the master RFP's Rated Criteria table); fall back to
    # the legacy per-D-document path (kept for resilience, though investigation
    # established D1/D2/D3's own text carries no weight values at all -- see
    # _weight_rows' docstring); fall back to the validated Deep Verify content
    # only if BOTH live sources returned nothing for ALL three categories.
    C.EVAL_WEIGHTS = {}
    category_specs = ((1, "Category 1 — Learning & Development (Form D1)", D1_DOC),
                      (2, "Category 2 — HR Advisory (Form D2)", D2_DOC),
                      (3, "Category 3 — Facilitation & Team Effectiveness (Form D3)", D3_DOC))
    scoped_occurrences = carry_forward_category_scope(result.evaluation_occurrences)
    for cat, label, doc in category_specs:
        rows = _occurrence_weight_rows(scoped_occurrences, cat)
        origin = "LIVE_FAST_LLM"
        if not rows:
            rows = _weight_rows(result.evaluation_criteria, doc)
        if rows:
            C.EVAL_WEIGHTS[label] = rows
            C.FACT_ORIGINS[f"EVAL_WEIGHTS.Category {cat}"] = origin
        else:
            # Genuinely missing for this one category, no fallback applied
            # (the all-or-nothing DEEP substitution below only fires when
            # ALL three categories are simultaneously empty) -- not one of
            # the 4 canonical origin labels because no origin actually
            # produced this row; flagged distinctly so a partial gap is
            # never silently mistaken for either a live success or a
            # fallback substitution.
            C.FACT_ORIGINS[f"EVAL_WEIGHTS.Category {cat}"] = "MISSING_NO_FALLBACK"
    if not C.EVAL_WEIGHTS:
        C.EVAL_WEIGHTS = DEEP.EVAL_WEIGHTS
        for cat, _, _ in category_specs:
            C.FACT_ORIGINS[f"EVAL_WEIGHTS.Category {cat}"] = "SAFETY_NET_FALLBACK"

    # ---- Section 6: Response Requirements ----
    C.RESPONSE_CHECKLIST = DEEP.RESPONSE_CHECKLIST  # structural checklist -- corpus-manifest-derived, not per-doc LLM
    C.RESPONSE_OTHER_REQUIREMENTS = DEEP.RESPONSE_OTHER_REQUIREMENTS

    # ---- Section 7: Commercial & Contractual (multi-source assembly) ----
    clauses_by_kind: dict[str, str] = {}
    for c in result.commercial_clauses:
        kind = c.get("clause_kind") or "OTHER"
        if kind not in clauses_by_kind:
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
    C.COMMERCIAL_POINTS = commercial_rows or DEEP.COMMERCIAL_POINTS
    C.FACT_ORIGINS["COMMERCIAL_POINTS"] = "LIVE_FAST_LLM" if commercial_rows else "SAFETY_NET_FALLBACK"
    for label in ("Insurance", "Pricing Structure", "Abnormally Low Pricing", "Contract Term & Extensions"):
        present = any(row[0] == label for row in C.COMMERCIAL_POINTS)
        C.FACT_ORIGINS[f"COMMERCIAL_POINTS.{label}"] = (
            ("LIVE_FAST_LLM" if commercial_rows else "SAFETY_NET_FALLBACK") if present else "MISSING")

    # ---- Section 8: Ambiguities (from deterministic detectors, not Stage C) ----
    tagged_ambiguities = _build_ambiguities(result.ambiguities)
    C.AMBIGUITIES = tagged_ambiguities
    live_ambiguity_found = any(result.ambiguities.get(k) for k in
                               ("evaluation_weight_conflicts", "pricing_stage_ambiguity",
                                "category_date_distinctions"))
    for type_key, gate_name in ((_AMBIGUITY_TYPE_EVAL_WEIGHT, "evaluation_weight_conflict"),
                                (_AMBIGUITY_TYPE_PRICING_STAGE, "pricing_stage_ambiguity"),
                                (_AMBIGUITY_TYPE_CATEGORY_DATE, "category_date_distinction")):
        ref = _ambiguity_ref(tagged_ambiguities, type_key)
        C.FACT_ORIGINS[f"AMBIGUITY.{gate_name}"] = (
            "LIVE_FAST_LLM" if (ref and live_ambiguity_found) else
            ("SAFETY_NET_FALLBACK" if ref else "MISSING"))
    eval_ref = _ambiguity_ref(tagged_ambiguities, _AMBIGUITY_TYPE_EVAL_WEIGHT)
    date_ref = _ambiguity_ref(tagged_ambiguities, _AMBIGUITY_TYPE_CATEGORY_DATE)

    # ---- Section 5 note (data-driven cross-reference, no dangling number) ----
    eval_weight_note = ("Category 3's table includes Price within its 100-point total; Categories "
                        "1 and 2 show technical scoring only, with pricing evaluated separately at "
                        "Stage 4.")
    if eval_ref:
        eval_weight_note += (
            " The RFP also contains additional scoring language elsewhere that does not fully "
            f"match these tables — see {eval_ref} in Section 8 before finalizing how much "
            "proposal effort to allocate per section.")
    C.EVAL_WEIGHT_NOTE = eval_weight_note

    # ---- Section 9: Attention Points (same advice text; cross-references data-driven) ----
    attention_points = list(DEEP.ATTENTION_POINTS)
    attention_points[1] = (
        "Confirm the authoritative evaluation weighting before drafting Appendix D responses"
        + (f" ({eval_ref})" if eval_ref else "") + " — do not guess which scoring table governs.")
    attention_points[4] = (
        "Confirm presentation-stage exposure per category"
        + (f" ({date_ref})" if date_ref else "") + " and calendar the applicable date once clarified.")
    C.ATTENTION_POINTS = attention_points

    # ---- Section 10: Source Map ----
    C.SOURCE_DOCUMENTS = DEEP.SOURCE_DOCUMENTS
    C.SOURCE_REF_TABLE = DEEP.SOURCE_REF_TABLE
    C.VALIDATION_FOOTER_NOTE = (
        "Procurement-specific figures in this Fast Analysis preview are drawn from a narrowed, "
        "targeted extraction pass sized to this report's own content requirements (see "
        "FAST_ANALYSIS_MINIMUM_VIABLE_INTELLIGENCE_AUDIT.md) rather than an exhaustive reading of "
        "every document. Source references are retained for every material fact. Where the source "
        "material itself was inconsistent, that inconsistency is preserved and flagged rather than "
        "silently resolved."
    )

    return C
