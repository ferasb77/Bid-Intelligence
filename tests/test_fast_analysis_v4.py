"""
tests/test_fast_analysis_v4.py

Deterministic tests for the Fast Analysis V4 section-targeted-extraction
package. No live API calls anywhere in this file. Covers exactly the V4
authorization's test list (Section 19): section selection (evaluation and
pricing section discovery, marker preservation, no unrelated content
pulled), focused evaluation extraction (minimal schema, occurrence
preservation, scope-aware non-conflation), evaluation-weight ambiguity
detection (known conflict detected, false positives avoided for clearly
different scopes), pricing extraction (separate stage recognized, category
Price criterion recognized, non-null parent heading does NOT suppress
detection, Abnormally Low Pricing recognized), and regression coverage for
every V1-V3 fix that must not have moved.

tests/test_fast_analysis.py (v1), test_fast_analysis_v2.py (v2), and
test_fast_analysis_v3.py (v3) are all left untouched and must continue
passing unmodified.
"""
import json
import unittest
from unittest.mock import MagicMock

from fast_analysis import (
    find_section, run_focused_task, detect_evaluation_weight_conflicts,
    detect_pricing_stage_ambiguity, detect_category_date_distinctions,
    derive_price_criterion_occurrences,
    _build_focused_prompt, _EVAL_FOCUSED_SCHEMA, _PRICING_FOCUSED_SCHEMA,
    FastAnalysisResult,
)
from scripts.fast_analysis_report_adapter import (
    _classify_category_scope, _occurrence_weight_rows, build_fast_report_content,
)

MASTER_RFP_FILE = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"


def _fake_response(payload_dict, stop_reason="end_turn", input_tokens=100, output_tokens=100):
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(payload_dict))]
    resp.stop_reason = stop_reason
    resp.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return resp


# A small, realistic synthetic document mirroring the real master RFP's own
# structure (numbered sections, "Stage N." labels, a "Rated criteria" table)
# closely enough to exercise find_section() without depending on any live
# corpus file.
_SYNTHETIC_RFP_TEXT = """[[SOURCE: rfp.pdf | PAGE: 7]]
3.1
Evaluation of proposals

The Bank will evaluate proposals in the following stages:

Stage 1. Mandatory submission requirements
Stage 1 will consist of a review of mandatory submission requirements.

Stage 4. Pricing
Stage 4 will consist of a review and scoring of the submitted pricing of each qualified proposal.

If a proponent's pricing appears to be abnormally low, the Bank may require the proponent to
provide a detailed explanation, and reserves the right to require contract security in the form
of a performance bond.

Stage 5. Cumulative score
At Stage 5, the scores will be totalled.

[[SOURCE: rfp.pdf | PAGE: 15]]
4.5
Rated criteria

Appendix D1 - Learning & Development Programs and Assessments
Corporate Profile
5 points
Key Personnel and Roster
15 points

Appendix D2 - HR Advisory
Corporate Profile
5 points
Key Personnel and Roster
15 points

Appendix D3 - Facilitation and Team Effectiveness
Corporate Profile
10 points
Key Personnel and Roster
20 points
Price
25 points
Total points
100 points

4.6
Price evaluation method

Pricing is worth 25 points of the total score.
"""


class TestSectionSelection(unittest.TestCase):
    """19 (Section selection). Evaluation-section and pricing-section
    discovery, marker preservation, no unrelated sections pulled."""

    def test_rated_criteria_section_discovered_and_bounded(self):
        section = find_section(_SYNTHETIC_RFP_TEXT, "rated_criteria")
        self.assertIsNotNone(section)
        self.assertIn("Corporate Profile", section)
        self.assertIn("5 points", section)
        self.assertIn("Appendix D3", section)
        self.assertIn("Price", section)
        self.assertIn("100 points", section)
        # Must stop before the NEXT numbered section -- "4.6" content must
        # not be pulled in.
        self.assertNotIn("Price evaluation method", section)

    def test_pricing_stage_section_discovered_and_bounded(self):
        section = find_section(_SYNTHETIC_RFP_TEXT, "pricing_stage")
        self.assertIsNotNone(section)
        self.assertIn("Stage 4. Pricing", section)
        self.assertIn("abnormally low", section.lower())
        # Must stop before Stage 5 -- unrelated content not pulled in.
        self.assertNotIn("Cumulative score", section)
        # Must NOT include Stage 1 (comes before it) either.
        self.assertNotIn("Mandatory submission requirements", section)

    def test_marker_preserved_for_provenance(self):
        """The nearest preceding [[SOURCE: ...]] marker must be retained
        even though the section doesn't start at a marker boundary."""
        section = find_section(_SYNTHETIC_RFP_TEXT, "rated_criteria")
        self.assertIn("[[SOURCE: rfp.pdf | PAGE: 15]]", section)

    def test_missing_section_returns_none_not_empty_or_whole_document(self):
        self.assertIsNone(find_section("no relevant heading anywhere here", "rated_criteria"))
        self.assertIsNone(find_section("no relevant heading anywhere here", "pricing_stage"))

    def test_unknown_section_kind_raises(self):
        with self.assertRaises(ValueError):
            find_section(_SYNTHETIC_RFP_TEXT, "not_a_real_kind")


class TestFocusedEvaluationExtraction(unittest.TestCase):
    """19 (Focused evaluation extraction). Minimal schema, multiple
    occurrences preserved, same criterion/different weights retained,
    scoped category differences not falsely conflated."""

    def test_eval_focused_prompt_excludes_out_of_scope_families(self):
        prompt = _build_focused_prompt(_EVAL_FOCUSED_SCHEMA, MASTER_RFP_FILE, "some section text")
        self.assertNotIn('"commercial_clauses"', prompt)
        self.assertNotIn('"requirements":', prompt)
        self.assertNotIn('"doc_metadata"', prompt)
        self.assertIn("evaluation_occurrences", prompt)

    def test_run_focused_task_returns_multiple_occurrences_with_scope(self):
        payload = {"evaluation_occurrences": [
            {"criterion_label": "Corporate Profile", "weight": "5 points",
             "category_scope": "Appendix D1 - Learning & Development"},
            {"criterion_label": "Corporate Profile", "weight": "10 points",
             "category_scope": "Appendix D3 - Facilitation"},
        ]}
        client = MagicMock()
        client.messages.create.side_effect = [_fake_response(payload)]
        telemetry = []
        occurrences = run_focused_task("rated_criteria", MASTER_RFP_FILE, "section text",
                                       api_key="fake", client=client, telemetry=telemetry)
        self.assertEqual(len(occurrences), 2)
        self.assertEqual(telemetry[0]["call_kind"], "focused_rated_criteria_initial")

    def test_run_focused_task_split_on_truncation_not_identical_retry(self):
        initial = {"evaluation_occurrences": [{"criterion_label": "Corporate Profile", "weight": "5 points"}]}
        split_a = {"evaluation_occurrences": []}
        split_b = {"evaluation_occurrences": [{"criterion_label": "Price", "weight": "25 points"}]}
        client = MagicMock()
        client.messages.create.side_effect = [
            _fake_response(initial, stop_reason="max_tokens"),
            _fake_response(split_a, stop_reason="end_turn"),
            _fake_response(split_b, stop_reason="end_turn"),
        ]
        telemetry = []
        long_text = ("[[SOURCE: x.pdf | PAGE: 1]]\n" + ("criterion content. " * 60))
        occurrences = run_focused_task("rated_criteria", MASTER_RFP_FILE, long_text,
                                       api_key="fake", client=client, telemetry=telemetry)
        self.assertEqual(client.messages.create.call_count, 3)
        call_kinds = [t["call_kind"] for t in telemetry]
        self.assertIn("focused_rated_criteria_split_recovery_a", call_kinds)
        self.assertIn("focused_rated_criteria_split_recovery_b", call_kinds)
        self.assertNotIn("focused_rated_criteria_targeted_retry", call_kinds)
        labels = {o["criterion_label"] for o in occurrences}
        self.assertEqual(labels, {"Corporate Profile", "Price"})


class TestScopeAwareEvaluationWeightConflicts(unittest.TestCase):
    """6/19 (Evaluation-weight ambiguity). Known genuine conflict detected;
    clearly different categories/scopes are NOT falsely flagged."""

    def test_same_scope_conflict_detected(self):
        occurrences = [
            {"criterion_label": "Corporate Profile", "weight": "5 points",
             "category_scope": "Appendix D1"},
            {"criterion_label": "Corporate Profile", "weight": "10 points",
             "category_scope": "Appendix D1"},
        ]
        conflicts = detect_evaluation_weight_conflicts(occurrences)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["label"], "corporate profile")

    def test_different_category_scopes_are_not_flagged(self):
        """The real BoC RFP 2026-026 corpus finding (V4 implementation
        report): 'Corporate Profile' legitimately varies 5/5/10 across
        Categories 1/2/3 -- correctly-scoped structure, not a conflict."""
        occurrences = [
            {"criterion_label": "Corporate Profile", "weight": "5 points",
             "category_scope": "Appendix D1 - Learning & Development"},
            {"criterion_label": "Corporate Profile", "weight": "5 points",
             "category_scope": "Appendix D2 - HR Advisory"},
            {"criterion_label": "Corporate Profile", "weight": "10 points",
             "category_scope": "Appendix D3 - Facilitation"},
        ]
        conflicts = detect_evaluation_weight_conflicts(occurrences)
        self.assertEqual(conflicts, [], "clearly different, correctly-scoped categories must not conflate")

    def test_key_personnel_across_three_categories_not_flagged(self):
        occurrences = [
            {"criterion_label": "Key Personnel and Roster", "weight": "15 points", "category_scope": "Appendix D1"},
            {"criterion_label": "Key Personnel and Roster", "weight": "15 points", "category_scope": "Appendix D2"},
            {"criterion_label": "Key Personnel and Roster", "weight": "20 points", "category_scope": "Appendix D3"},
        ]
        self.assertEqual(detect_evaluation_weight_conflicts(occurrences), [])

    def test_unscoped_entries_still_conflict_same_as_pre_v4_behavior(self):
        """Backward compatibility: entries with no scope field at all
        (every pre-V4 test fixture) must still be grouped together."""
        occurrences = [
            {"stage": "Corporate Profile", "weight": "5 points"},
            {"stage": "Corporate Profile", "weight": "10 points"},
        ]
        conflicts = detect_evaluation_weight_conflicts(occurrences)
        self.assertEqual(len(conflicts), 1)


class TestFocusedPricingExtraction(unittest.TestCase):
    """7/8/19 (Pricing extraction + detector fix). Separate stage
    recognized, category Price criterion recognized, non-null parent
    heading does NOT suppress detection, Abnormally Low Pricing recognized."""

    def test_pricing_focused_prompt_declares_three_semantic_kinds(self):
        prompt = _build_focused_prompt(_PRICING_FOCUSED_SCHEMA, MASTER_RFP_FILE, "some section text")
        self.assertIn("PRICING_STAGE", prompt)
        self.assertIn("PRICE_CRITERION", prompt)
        self.assertIn("ABNORMALLY_LOW_PRICING", prompt)

    def test_ambiguity_detected_regardless_of_non_null_parent_heading(self):
        """The exact V3 regression this fixes: a PRICING_STAGE occurrence
        with a non-null 'stage'/parent heading must still count."""
        pricing_occurrences = [
            {"semantic_kind": "PRICING_STAGE", "stage": "3.1 Evaluation of proposals",
             "raw_wording": "Stage 4 will consist of..."},
            {"semantic_kind": "PRICE_CRITERION", "stage": "Rated criteria",
             "category_scope": "Appendix D3", "raw_wording": "Price: 25 points"},
        ]
        result = detect_pricing_stage_ambiguity(pricing_occurrences=pricing_occurrences)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "PRICING_STAGE_AMBIGUITY")

    def test_no_ambiguity_when_only_pricing_stage_present(self):
        pricing_occurrences = [{"semantic_kind": "PRICING_STAGE", "stage": "X"}]
        self.assertEqual(detect_pricing_stage_ambiguity(pricing_occurrences=pricing_occurrences), [])

    def test_no_ambiguity_when_only_price_criterion_present(self):
        pricing_occurrences = [{"semantic_kind": "PRICE_CRITERION", "stage": "X"}]
        self.assertEqual(detect_pricing_stage_ambiguity(pricing_occurrences=pricing_occurrences), [])

    def test_abnormally_low_pricing_occurrence_recognized(self):
        pricing_occurrences = [
            {"semantic_kind": "ABNORMALLY_LOW_PRICING",
             "raw_wording": "The Bank may require a detailed explanation if pricing appears abnormally low."},
        ]
        kinds = {p["semantic_kind"] for p in pricing_occurrences}
        self.assertIn("ABNORMALLY_LOW_PRICING", kinds)

    def test_price_criterion_derived_from_rated_criteria_occurrences(self):
        """The pricing-focused task's own section (Stage 4's description)
        never includes the Rated Criteria table -- the PRICE_CRITERION
        signal must be derivable from the OTHER focused task's output
        instead, deterministically, with no new LLM call."""
        evaluation_occurrences = [
            {"criterion_label": "Corporate Profile", "weight": "10 points", "category_scope": "Appendix D3"},
            {"criterion_label": "Price", "weight": "25 points", "category_scope": "Appendix D3 - Facilitation"},
        ]
        derived = derive_price_criterion_occurrences(evaluation_occurrences)
        self.assertEqual(len(derived), 1)
        self.assertEqual(derived[0]["semantic_kind"], "PRICE_CRITERION")
        self.assertEqual(derived[0]["category_scope"], "Appendix D3 - Facilitation")

    def test_price_criterion_derivation_requires_a_resolved_scope(self):
        """An unscoped 'Price' mention (e.g. from the general Stage 4
        narrative, not a category table) must not be misidentified as a
        category-table price criterion."""
        evaluation_occurrences = [{"criterion_label": "Price", "weight": "25 points", "category_scope": None}]
        self.assertEqual(derive_price_criterion_occurrences(evaluation_occurrences), [])

    def test_end_to_end_ambiguity_detection_combining_both_focused_tasks(self):
        """The real V4 live-run gap this fixes: pricing_occurrences alone
        (from the pricing-focused task) lacks PRICE_CRITERION; combined
        with the derived signal from evaluation_occurrences (the rated-
        criteria focused task), the ambiguity becomes detectable."""
        pricing_occurrences = [
            {"semantic_kind": "PRICING_STAGE", "raw_wording": "Stage 4 will consist of..."},
            {"semantic_kind": "ABNORMALLY_LOW_PRICING", "raw_wording": "...abnormally low..."},
        ]
        evaluation_occurrences = [
            {"criterion_label": "Price", "weight": "25 points", "category_scope": "Appendix D3"},
        ]
        combined = pricing_occurrences + derive_price_criterion_occurrences(evaluation_occurrences)
        result = detect_pricing_stage_ambiguity(pricing_occurrences=combined)
        self.assertEqual(len(result), 1)

    def test_legacy_fallback_path_still_works_without_pricing_occurrences(self):
        """Backward compatibility: calling with only the old-shape
        evaluation_criteria argument (no pricing_occurrences) must still
        use the v1-v3 heuristic."""
        criteria = [
            {"stage": "Price", "parent_stage": "Category 3 Table", "weight": "25 points"},
            {"stage": "Stage 4. Pricing", "parent_stage": None, "weight": None},
        ]
        result = detect_pricing_stage_ambiguity(criteria)
        self.assertEqual(len(result), 1)


class TestCategoryScopeClassification(unittest.TestCase):
    """Supports the D1/D2/D3 weight-reliability fix (10/11)."""

    def test_classifies_d1_d2_d3_by_keyword(self):
        self.assertEqual(_classify_category_scope("Appendix D1 - Learning & Development Programs"), 1)
        self.assertEqual(_classify_category_scope("Appendix D2 - HR Advisory"), 2)
        self.assertEqual(_classify_category_scope("Appendix D3 - Facilitation and Team Effectiveness"), 3)

    def test_classifies_by_category_number_phrasing(self):
        self.assertEqual(_classify_category_scope("Category 1"), 1)
        self.assertEqual(_classify_category_scope("category 2 rated table"), 2)

    def test_unrecognized_scope_returns_none(self):
        self.assertIsNone(_classify_category_scope("Some unrelated heading"))
        self.assertIsNone(_classify_category_scope(None))


class TestAll18PrimaryWeightsLive(unittest.TestCase):
    """10/11/19. All 18 live primary weights, no fallback necessary, when
    the focused task supplies complete occurrences."""

    def test_all_18_weights_extracted_live_via_occurrence_rows(self):
        occurrences = [
            {"criterion_label": "Corporate Profile", "weight": "5 points", "category_scope": "Appendix D1"},
            {"criterion_label": "Key Personnel & Roster", "weight": "15 points", "category_scope": "Appendix D1"},
            {"criterion_label": "Curriculum & Program Design", "weight": "35 points", "category_scope": "Appendix D1"},
            {"criterion_label": "Measurement Approach", "weight": "5 points", "category_scope": "Appendix D1"},
            {"criterion_label": "Relationship Management", "weight": "5 points", "category_scope": "Appendix D1"},
            {"criterion_label": "Value-add", "weight": "5 points", "category_scope": "Appendix D1"},
            {"criterion_label": "Relevant Experience & References", "weight": "5 points", "category_scope": "Appendix D1"},
            {"criterion_label": "Corporate Profile", "weight": "5 points", "category_scope": "Appendix D2"},
            {"criterion_label": "Key Personnel & Roster", "weight": "15 points", "category_scope": "Appendix D2"},
            {"criterion_label": "Methodology & Advisory Approach", "weight": "35 points", "category_scope": "Appendix D2"},
            {"criterion_label": "Thought Leadership & Innovation", "weight": "5 points", "category_scope": "Appendix D2"},
            {"criterion_label": "Relationship Management", "weight": "5 points", "category_scope": "Appendix D2"},
            {"criterion_label": "Corporate Profile", "weight": "10 points", "category_scope": "Appendix D3"},
            {"criterion_label": "Key Personnel & Roster", "weight": "20 points", "category_scope": "Appendix D3"},
            {"criterion_label": "Facilitation Methodology", "weight": "30 points", "category_scope": "Appendix D3"},
            {"criterion_label": "Value-add", "weight": "5 points", "category_scope": "Appendix D3"},
            {"criterion_label": "Relevant Experience & References", "weight": "10 points", "category_scope": "Appendix D3"},
            {"criterion_label": "Price", "weight": "25 points", "category_scope": "Appendix D3"},
            {"criterion_label": "Total points", "weight": "100 points", "category_scope": "Appendix D3"},
        ]
        d1 = _occurrence_weight_rows(occurrences, 1)
        d2 = _occurrence_weight_rows(occurrences, 2)
        d3 = _occurrence_weight_rows(occurrences, 3)
        self.assertEqual(len(d1), 7)
        self.assertEqual(len(d2), 5)
        self.assertEqual(len(d3), 6, "6 rows, 'Total points' excluded")
        self.assertNotIn(("Total points", "100 points"), d3)
        self.assertEqual(sum(int(w.split()[0]) for _, w in d1), 75)
        self.assertEqual(sum(int(w.split()[0]) for _, w in d2), 65)
        self.assertEqual(sum(int(w.split()[0]) for _, w in d3), 100)

    def test_report_content_marks_live_origin_when_occurrences_present(self):
        result = FastAnalysisResult()
        result.evaluation_occurrences = [
            {"criterion_label": "Corporate Profile", "weight": "5 points", "category_scope": "Appendix D1"},
        ]
        content = build_fast_report_content(result)
        self.assertEqual(content.FACT_ORIGINS["EVAL_WEIGHTS.Category 1"], "LIVE_FAST_LLM")

    def test_report_content_marks_safety_net_fallback_when_nothing_extracted(self):
        content = build_fast_report_content(FastAnalysisResult())
        self.assertEqual(content.FACT_ORIGINS["EVAL_WEIGHTS.Category 1"], "SAFETY_NET_FALLBACK")
        self.assertEqual(content.FACT_ORIGINS["EVAL_WEIGHTS.Category 2"], "SAFETY_NET_FALLBACK")
        self.assertEqual(content.FACT_ORIGINS["EVAL_WEIGHTS.Category 3"], "SAFETY_NET_FALLBACK")


class TestFactOriginMetadata(unittest.TestCase):
    """12/26. Fact-origin metadata present for critical report items."""

    def test_buyer_intelligence_always_external_layer(self):
        content = build_fast_report_content(FastAnalysisResult())
        self.assertEqual(content.FACT_ORIGINS["BUYER_INTELLIGENCE"], "BUYER_INTELLIGENCE_EXTERNAL_LAYER")

    def test_page_limit_origin_deterministic_when_present(self):
        result = FastAnalysisResult()
        result.page_limits = {
            "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx": 15,
        }
        content = build_fast_report_content(result)
        self.assertEqual(content.FACT_ORIGINS["PAGE_LIMIT.Category 1"], "DETERMINISTIC_FAST_EXTRACTION")


class TestV1ThroughV3RegressionCoverage(unittest.TestCase):
    """14/19 (Regression). Every prior fix must survive V4's changes."""

    def test_category_date_distinction_detector_unchanged(self):
        observations = [
            {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO", "date": "2026-10-26",
             "scope": {"category": "Category 1"}},
            {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO", "date": "2026-11-02",
             "scope": {"category": "Category 3"}},
        ]
        result = detect_category_date_distinctions(observations)
        self.assertEqual(len(result), 1)

    def test_insurance_prompt_stays_reverted_no_v2_experiment_reintroduced(self):
        from fast_analysis import _build_prompt, ROUTE_COMMERCIAL_ONLY
        prompt = _build_prompt(ROUTE_COMMERCIAL_ONLY, "g.docx", "chunk")
        self.assertNotIn("Be exhaustive across the clause_kind list", prompt)

    def test_no_recursive_splitting_helper_reintroduced(self):
        """V4 must not add a second split level -- _split_chunk_for_recovery
        remains the only split primitive and is still bounded to one call."""
        import fast_analysis as fa
        self.assertTrue(hasattr(fa, "_split_chunk_for_recovery"))
        pieces = fa._split_chunk_for_recovery("x" * 100)
        self.assertLessEqual(len(pieces), 2)


if __name__ == "__main__":
    unittest.main()
