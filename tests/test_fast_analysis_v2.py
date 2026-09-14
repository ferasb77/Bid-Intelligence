"""
tests/test_fast_analysis_v2.py

Deterministic tests for the Fast Analysis V2 targeted-fidelity-correction
package. No live API calls anywhere in this file. Covers category-
description scoping, commercial multi-source assembly, date-table type
filtering, dynamic ambiguity cross-references (3 present / 1 present / 0
present), and non-regression of v1's unchanged routing / page-limit
behavior.

v1's own test file (tests/test_fast_analysis.py) is left entirely
untouched and must continue passing unmodified -- V2 is a targeted
correction, not a rewrite.

NOTE (V3): this file originally also covered the retry-on-truncation
mechanism (max_tokens -> bounded same-content retry). V3 replaced that
mechanism entirely with bounded split-on-truncation recovery (see
FAST_ANALYSIS_V3_IMPLEMENTATION_REPORT.md) after live evidence showed a
same-content retry at temperature 0 reproduces the identical truncation
point and cannot recover anything. Those tests were relocated and rewritten
for the new mechanism in tests/test_fast_analysis_v3.py rather than kept
here testing behavior that no longer exists.
"""
import json
import unittest
from unittest.mock import MagicMock

from fast_analysis import (
    DOCUMENT_ROUTING, PAGE_LIMIT_DOCUMENTS,
    extract_page_limit_deterministic, FastAnalysisResult,
)
from scripts.fast_analysis_report_adapter import (
    _service_category_rows, _discover_evaluation_categories, _looks_like_date, _presentation_dates,
    _pricing_and_term_commercial_rows, _build_ambiguities, _ambiguity_ref,
    build_fast_report_content, _AMBIGUITY_TYPE_EVAL_WEIGHT,
    _AMBIGUITY_TYPE_PRICING_STAGE, _AMBIGUITY_TYPE_CATEGORY_DATE,
)

MASTER_RFP_FILE = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"


def _fake_response(payload_dict, stop_reason="end_turn", input_tokens=100, output_tokens=100):
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(payload_dict))]
    resp.stop_reason = stop_reason
    resp.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return resp


class TestCategoryDescriptionScoping(unittest.TestCase):
    """6. Multiple discovered categories produce distinct, correctly
    associated descriptions.

    Phase 5 generalization: `_category_requirements` assumed exactly three
    hardcoded Bank-of-Canada categories (1/2/3) matched by a regex over
    "Category N" phrasing. It is replaced by `_service_category_rows`,
    which matches against whatever category labels
    `_discover_evaluation_categories` actually found for THIS corpus (via
    the focused rated-criteria task's own category_scope text) -- however
    many there are, under whatever names the corpus itself uses."""

    def test_exclusive_single_category_matches_route_correctly(self):
        categories = ["Category 1", "Category 2", "Category 3"]
        requirements = [
            {"description": "Category 1 covers leadership and management development programs."},
            {"description": "Category 2 covers strategic HR consulting and workforce planning."},
            {"description": "Category 3 covers facilitation and team-effectiveness sessions."},
        ]
        result = FastAnalysisResult()
        result.requirements = requirements
        rows = _service_category_rows(result, categories)
        self.assertEqual(rows[0][2], requirements[0]["description"])
        self.assertEqual(rows[1][2], requirements[1]["description"])
        self.assertEqual(rows[2][2], requirements[2]["description"])
        self.assertNotEqual(rows[0][2], rows[1][2])
        self.assertNotEqual(rows[1][2], rows[2][2])

    def test_category_with_no_matching_requirement_text_is_honestly_not_extracted(self):
        """Phase 5 instruction 4: a category with nothing genuinely matched
        must show the honest not-extracted marker, never another
        category's (or another corpus's) description substituted in."""
        result = FastAnalysisResult()
        result.requirements = [{"description": "Category 1 covers learning and development."}]
        rows = _service_category_rows(result, ["Category 1", "Category 2"])
        self.assertEqual(rows[0][2], "Category 1 covers learning and development.")
        self.assertEqual(rows[1][2], "Not stated in the extracted data.")

    def test_report_content_has_no_service_categories_when_none_discovered(self):
        """A flat/uncategorized corpus (e.g. CDA-AMC's single-scope RFSO)
        must render zero SERVICE_CATEGORIES rows, not three empty or
        substituted ones."""
        content = build_fast_report_content(FastAnalysisResult())
        self.assertEqual(content.SERVICE_CATEGORIES, [])


class TestCommercialMultiSourceAssembly(unittest.TestCase):
    """7. Section 7 merges commercial_clauses with pricing/term facts
    already present elsewhere in Fast Analysis's own output.

    Phase 5: pricing-structure requirements are matched generically by
    content across the whole corpus's requirements, no longer filtered to
    one hardcoded Bank-of-Canada filename (APPENDIX_E) -- a pricing
    requirement in ANY document (including one bundled into a single main
    RFP document, as in the CDA-AMC corpus) must be picked up the same
    way."""

    def test_pricing_structure_and_term_rows_derived_from_any_document_and_contract_term(self):
        result = FastAnalysisResult()
        result.requirements = [
            {"source_doc": "some_other_document.pdf", "description": "All-inclusive pricing must be "
                                                                      "provided for Years 1, 2, and 3."},
            {"source_doc": "some_other_document.pdf", "description": "The buyer may require an "
                                                                      "explanation if pricing appears "
                                                                      "abnormally low."},
        ]
        result.typed_observations = [
            {"family": "CONTRACT_TERM", "semantic_kind": "INITIAL_DURATION", "duration": "3",
             "unit": "years", "scope": {}},
            {"family": "CONTRACT_TERM", "semantic_kind": "EXTENSION_OPTION", "option_count": "2",
             "duration": "1", "unit": "year"},
        ]
        rows = _pricing_and_term_commercial_rows(result)
        labels = [r[0] for r in rows]
        self.assertIn("Pricing Structure", labels)
        self.assertIn("Abnormally Low Pricing", labels)
        self.assertIn("Contract Term & Extensions", labels)

    def test_commercial_clauses_take_precedence_over_derived_rows_for_same_label(self):
        """clause_kind labels are derived by title-casing the raw string, not
        validated against the enum -- use a clause_kind that title-cases to
        the same label a derived row would use, to exercise the dedup guard."""
        result = FastAnalysisResult()
        result.commercial_clauses = [
            {"clause_kind": "PRICING STRUCTURE", "topic": "Pricing Structure",
            "source_fact": "already covered by commercial_clauses"},
        ]
        result.requirements = [
            {"source_doc": "some_other_document.pdf", "description": "All-inclusive pricing must be "
                                                                      "provided for Years 1, 2, and 3."},
        ]
        content = build_fast_report_content(result)
        pricing_rows = [row for row in content.COMMERCIAL_POINTS if row[0] == "Pricing Structure"]
        self.assertEqual(len(pricing_rows), 1, "no duplicate row for a label already supplied")
        self.assertEqual(pricing_rows[0][1], "already covered by commercial_clauses")


class TestDateTableTypeSafety(unittest.TestCase):
    """9. Non-date facts cannot enter the dates table -- the exact v1
    quota-sentence-in-dates-table defect."""

    def test_looks_like_date_accepts_iso_and_prose_dates(self):
        self.assertTrue(_looks_like_date("2026-10-26"))
        self.assertTrue(_looks_like_date("October 26, 2026"))
        self.assertTrue(_looks_like_date("October 26 2026"))

    def test_looks_like_date_accepts_this_rfps_week_of_phrasing(self):
        """The live V2 run's actual source text states presentation dates as
        "Week of October 26" (no year) -- confirmed against the real RFP
        wording; the validator must accept this real format, not just an
        idealized one, or it silently regresses genuine dates to MISSING
        while fixing the quota-sentence contamination."""
        self.assertTrue(_looks_like_date("Week of October 26"))
        self.assertTrue(_looks_like_date("week of November 2"))

    def test_looks_like_date_rejects_quota_sentence(self):
        self.assertFalse(_looks_like_date(
            "up to seven (7) top-ranked proponents for service category 1 will be invited"))

    def test_presentation_dates_excludes_non_date_milestone_observation(self):
        observations = [
            {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO", "date": "2026-10-26",
             "scope": {"category": "Category 1"}},
            {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO",
             "original_value": "up to nine (9) top-ranked proponents for service category 3",
             "scope": {"category": "Category 3"}},
        ]
        dates = _presentation_dates(observations)
        self.assertEqual(len(dates), 1)
        self.assertEqual(dates[0][0], "2026-10-26")

    def test_presentation_dates_deduplicates_identical_occurrences(self):
        """Bounded-retry merging can add a duplicate identical observation;
        the dates table must not show it twice."""
        observations = [
            {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO", "date": "2026-10-26",
             "scope": {"category": "Category 1"}},
            {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO", "date": "2026-10-26",
             "scope": {"category": "Category 1"}},
        ]
        self.assertEqual(len(_presentation_dates(observations)), 1)


class TestDynamicAmbiguityCrossReferences(unittest.TestCase):
    """10. All 3 / only 1 / zero ambiguities present -- cross-references
    must be generated from the actual assembled list, never hard-coded."""

    def test_all_three_present_gives_sequential_refs(self):
        ambiguities = {
            "evaluation_weight_conflicts": [{"label": "corporate profile", "competing_values": ["5", "10"]}],
            "pricing_stage_ambiguity": [{"detail": "price appears twice"}],
            "category_date_distinctions": [{"milestone_kind": "PRESENTATION_OR_DEMO"}],
        }
        tagged = _build_ambiguities(ambiguities)
        self.assertEqual(len(tagged), 3)
        self.assertEqual(_ambiguity_ref(tagged, _AMBIGUITY_TYPE_EVAL_WEIGHT), "Ambiguity 1")
        self.assertEqual(_ambiguity_ref(tagged, _AMBIGUITY_TYPE_PRICING_STAGE), "Ambiguity 2")
        self.assertEqual(_ambiguity_ref(tagged, _AMBIGUITY_TYPE_CATEGORY_DATE), "Ambiguity 3")

    def test_only_one_present_omits_missing_refs(self):
        ambiguities = {"evaluation_weight_conflicts": [], "pricing_stage_ambiguity": [],
                       "category_date_distinctions": [{"milestone_kind": "PRESENTATION_OR_DEMO"}]}
        tagged = _build_ambiguities(ambiguities)
        self.assertEqual(len(tagged), 1)
        self.assertIsNone(_ambiguity_ref(tagged, _AMBIGUITY_TYPE_EVAL_WEIGHT))
        self.assertEqual(_ambiguity_ref(tagged, _AMBIGUITY_TYPE_CATEGORY_DATE), "Ambiguity 1")

    def test_zero_present_is_a_genuine_empty_result_not_a_boc_fallback(self):
        """Superseded by Product Integration Phase 4 (cross-procurement
        generalization commissioning): this test originally asserted that
        zero detected ambiguities falls back to substituting Bank of
        Canada's own three (real, but corpus-specific) ambiguities, on the
        assumption that 'zero found' could only mean an extraction gap for
        a corpus known to always have exactly these three. Phase 4's live
        commissioning run against a materially different, real procurement
        (Canada's Drug Agency coaching RFSO -- which genuinely has none of
        these three ambiguity classes) proved that assumption false: the
        old fallback showed Bank of Canada's own ambiguities as if they
        belonged to a different buyer's procurement. A confirmed
        NOT_PRESENT is a real, meaningful result and must never be
        backfilled with another corpus's facts -- zero detected must yield
        zero reported, for every corpus including Bank of Canada's own (it
        simply never takes this path today because its real corpus always
        has all three)."""
        ambiguities = {"evaluation_weight_conflicts": [], "pricing_stage_ambiguity": [],
                       "category_date_distinctions": []}
        tagged = _build_ambiguities(ambiguities)
        self.assertEqual(tagged, [])
        self.assertIsNone(_ambiguity_ref(tagged, _AMBIGUITY_TYPE_EVAL_WEIGHT))

    def test_eval_weight_note_omits_dangling_reference_when_class_absent(self):
        result = FastAnalysisResult()
        result.ambiguities = {"evaluation_weight_conflicts": [], "pricing_stage_ambiguity": [],
                              "category_date_distinctions": [{"milestone_kind": "PRESENTATION_OR_DEMO"}]}
        content = build_fast_report_content(result)
        self.assertNotIn("Ambiguity", content.EVAL_WEIGHT_NOTE)

    def test_eval_weight_note_includes_live_reference_when_class_present(self):
        result = FastAnalysisResult()
        result.ambiguities = {
            "evaluation_weight_conflicts": [{"label": "corporate profile", "competing_values": ["5", "10"]}],
            "pricing_stage_ambiguity": [], "category_date_distinctions": [],
        }
        content = build_fast_report_content(result)
        self.assertIn("Ambiguity 1", content.EVAL_WEIGHT_NOTE)

    def test_attention_points_reference_matches_actual_ambiguity_position(self):
        """Phase 5: ATTENTION_POINTS is no longer a fixed, 8-item
        Bank-of-Canada-specific list with two hardcoded index overrides --
        it is generated only from conditions the current procurement's own
        data actually supports (data-driven cross-references only, no
        static advice list reused as a template for another corpus)."""
        result = FastAnalysisResult()
        result.ambiguities = {
            "evaluation_weight_conflicts": [],
            "pricing_stage_ambiguity": [{"detail": "price appears twice"}],
            "category_date_distinctions": [{"milestone_kind": "PRESENTATION_OR_DEMO"}],
        }
        content = build_fast_report_content(result)
        self.assertFalse(any("evaluation weighting" in p.lower() for p in content.ATTENTION_POINTS),
                         "eval-weight class absent -> no eval-weight attention point at all")
        date_points = [p for p in content.ATTENTION_POINTS if "(Ambiguity 2)" in p]
        self.assertEqual(len(date_points), 1,
                         "category-date class present at position 2 (pricing=1, date=2)")


class TestUnchangedRoutingAndPageLimits(unittest.TestCase):
    """11/12/17. Document routing and deterministic page-limit extraction
    must remain byte-identical to v1 -- V2's strict scope forbids touching
    these."""

    def test_routing_table_unchanged_count_and_skip_set(self):
        self.assertEqual(len(DOCUMENT_ROUTING), 16)
        skip_docs = [n for n, r in DOCUMENT_ROUTING.items() if r == "SKIP"]
        self.assertEqual(len(skip_docs), 4)

    def test_page_limit_documents_unchanged(self):
        self.assertEqual(len(PAGE_LIMIT_DOCUMENTS), 3)

    def test_d1_d2_d3_deterministic_extraction_still_correct(self):
        d1 = "Responses must not exceed 15 pages (excluding resumes)."
        d2 = "Responses must not exceed twelve (12) pages (excluding resumes)."
        d3 = "Responses must not exceed ten (10) pages (excluding resumes)."
        self.assertEqual(extract_page_limit_deterministic(d1), 15)
        self.assertEqual(extract_page_limit_deterministic(d2), 12)
        self.assertEqual(extract_page_limit_deterministic(d3), 10)


if __name__ == "__main__":
    unittest.main()
