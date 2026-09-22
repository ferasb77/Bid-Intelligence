"""
tests/test_fast_analysis.py

Deterministic tests for the Fast Analysis sibling path (fast_analysis.py +
scripts/fast_analysis_report_adapter.py). No real model calls anywhere in
this file, per the explicit "test without live calls first" instruction.

A. Document routing matches the audit's classification for every one of the
   16 authoritative corpus documents.
B. Deterministic page-limit extraction (regex, no LLM) against real header
   sentences from D1/D2/D3.
C. Minimal schema validation -- the narrow prompts request only audit-
   approved families, never Deep Verify's full 8-family schema.
D. Source-reference retention -- merged results keep source_refs/source_doc.
E. Batching behavior -- the six small B/C forms route into one batch group.
F. Document skip rules -- the four audit-identified documents route to SKIP.
G. Scoring (evaluation-weight) ambiguity detection.
H. Pricing-stage ambiguity detection.
I. Category-specific date distinction detection.
J. Deterministic report-input assembly (the adapter produces the same
   content-module shape Deep Verify's PDF renderer expects).
"""
import unittest

from fast_analysis import (
    route_document, extract_page_limit_deterministic, DOCUMENT_ROUTING,
    BATCH_GROUP, PAGE_LIMIT_DOCUMENTS, ROUTE_SKIP, ROUTE_EVAL_ONLY,
    ROUTE_IDENTITY_EVAL_REQ, ROUTE_CONTRACT_NARROW, ROUTE_COMMERCIAL_ONLY,
    _build_prompt, _merge_chunk_result, _empty_result, _has_required_fields,
    detect_evaluation_weight_conflicts, detect_pricing_stage_ambiguity,
    detect_category_date_distinctions, FastAnalysisResult,
)

MASTER_RFP = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"


class TestDocumentRouting(unittest.TestCase):
    """A. Document routing matches the audit."""

    def test_all_16_authoritative_documents_are_routed(self):
        expected_documents = [
            "abstract.pdf",
            "Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx",
            "OriginalRevision/DP 2026-026 - Annexe F - Questionnaire ESG.xlsx",
            "OriginalRevision/RFP 2026-026 - Appendix A - Submission Form.docx",
            "OriginalRevision/RFP 2026-026 - Appendix B1 - Mandatory criteria.xlsx",
            "OriginalRevision/RFP 2026-026 - Appendix B2 - Mandatory criteria.xlsx",
            "OriginalRevision/RFP 2026-026 - Appendix B3 - Mandatory criteria.xlsx",
            "OriginalRevision/RFP 2026-026 - Appendix C1 - Minimum qualification requirements.xlsx",
            "OriginalRevision/RFP 2026-026 - Appendix C2 - Minimum qualification requirements.xlsx",
            "OriginalRevision/RFP 2026-026 - Appendix C3 - Minimum qualification requirement.xlsx",
            "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx",
            "OriginalRevision/RFP 2026-026 - Appendix D2 - Rated Criteria Response Form.docx",
            "OriginalRevision/RFP 2026-026 - Appendix D3 - Rated Criteria Response Form.docx",
            "OriginalRevision/RFP 2026-026 - Appendix E - Pricing Form.xlsx",
            "OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx",
            MASTER_RFP,
        ]
        self.assertEqual(len(expected_documents), 16)
        for name in expected_documents:
            self.assertIn(name, DOCUMENT_ROUTING, f"{name} is missing from DOCUMENT_ROUTING")

    def test_master_rfp_routes_to_deep_narrow_identity_eval_req(self):
        self.assertEqual(route_document(MASTER_RFP), ROUTE_IDENTITY_EVAL_REQ)

    def test_appendix_g_routes_to_commercial_only(self):
        self.assertEqual(
            route_document("OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx"),
            ROUTE_COMMERCIAL_ONLY)

    def test_appendix_e_routes_to_contract_narrow(self):
        self.assertEqual(
            route_document("OriginalRevision/RFP 2026-026 - Appendix E - Pricing Form.xlsx"),
            ROUTE_CONTRACT_NARROW)

    def test_unknown_document_falls_back_to_broadest_narrow_mode_not_silent_skip(self):
        self.assertEqual(route_document("some_future_addendum.pdf"), ROUTE_IDENTITY_EVAL_REQ)


class TestDeterministicPageLimit(unittest.TestCase):
    """B. Deterministic page-limit extraction, no LLM."""

    def test_digit_only_form(self):
        text = ("[[SOURCE: d1.docx | Header]]\nResponses must not exceed 15 pages (excluding "
               "resumes or professional profiles, and work or product samples requested herein).")
        self.assertEqual(extract_page_limit_deterministic(text), 15)

    def test_word_plus_digit_form_ten(self):
        text = ("Responses must not exceed ten (10) pages (excluding resumes or professional "
               "profiles, and work or product samples requested herein).")
        self.assertEqual(extract_page_limit_deterministic(text), 10)

    def test_word_plus_digit_form_twelve(self):
        text = ("Responses must not exceed twelve (12) pages (excluding resumes or professional "
               "profiles, and work or product samples requested herein).")
        self.assertEqual(extract_page_limit_deterministic(text), 12)

    def test_no_match_returns_none_not_zero(self):
        self.assertIsNone(extract_page_limit_deterministic("No page limit language here at all."))

    def test_all_three_known_documents_registered_for_deterministic_extraction(self):
        self.assertEqual(len(PAGE_LIMIT_DOCUMENTS), 3)
        for name, label in PAGE_LIMIT_DOCUMENTS.items():
            self.assertIn(label, ("D1", "D2", "D3"))


class TestMinimalSchema(unittest.TestCase):
    """C. Minimal schema validation -- narrow prompts, not the universal schema."""

    def test_eval_only_prompt_does_not_mention_commercial_clauses_or_deliverables(self):
        prompt = _build_prompt(ROUTE_EVAL_ONLY, "b1.xlsx", "some chunk text")
        self.assertNotIn("commercial_clauses", prompt)
        self.assertNotIn("deliverables", prompt)
        self.assertIn("evaluation_criteria", prompt)

    def test_commercial_only_prompt_does_not_mention_evaluation_criteria(self):
        prompt = _build_prompt(ROUTE_COMMERCIAL_ONLY, "g.docx", "some chunk text")
        self.assertNotIn("evaluation_criteria", prompt)
        self.assertIn("commercial_clauses", prompt)

    def test_identity_eval_req_prompt_omits_contract_risks_and_deliverables_as_json_keys(self):
        """`deliverables` may legitimately appear in prose telling the model
        NOT to extract it (an exclusion instruction) -- what must never
        appear is a `"deliverables":` key in the JSON shape actually
        requested, since that would mean the model is asked to populate it."""
        prompt = _build_prompt(ROUTE_IDENTITY_EVAL_REQ, MASTER_RFP, "some chunk text")
        self.assertNotIn('"contract_risks":', prompt)
        self.assertNotIn('"deliverables":', prompt)
        # Required families per the audit ARE present as actual JSON keys:
        for family in ("doc_metadata", "typed_observations", "evaluation_criteria", "requirements"):
            self.assertIn(f'"{family}":', prompt)

    def test_preserve_every_distinct_occurrence_instruction_present_in_eval_schema(self):
        """The single most important instruction (audit S B/S F) must survive
        into the actual prompt text sent to the model."""
        prompt = _build_prompt(ROUTE_EVAL_ONLY, "b1.xlsx", "chunk")
        self.assertIn("do NOT merge, average, or pick one value", prompt)


class TestSourceReferenceRetention(unittest.TestCase):
    """D. Source references / source_doc survive merging."""

    def test_merge_preserves_source_refs_on_evaluation_criteria(self):
        result = _empty_result(ROUTE_EVAL_ONLY)
        chunk_data = {"evaluation_criteria": [
            {"stage": "Corporate Profile", "weight": "5 points",
             "source_refs": [{"source_doc": "b1.xlsx", "page": None, "sheet": "Sheet1",
                              "section": None, "excerpt": "Corporate Profile: 5 points"}]}
        ]}
        _merge_chunk_result(result, chunk_data)
        self.assertEqual(len(result["evaluation_criteria"]), 1)
        refs = result["evaluation_criteria"][0]["source_refs"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["source_doc"], "b1.xlsx")

    def test_has_required_fields_detects_missing_evaluation_criteria(self):
        self.assertFalse(_has_required_fields(ROUTE_EVAL_ONLY, {"evaluation_criteria": []}))
        self.assertTrue(_has_required_fields(ROUTE_EVAL_ONLY, {"evaluation_criteria": [{"stage": "x"}]}))


class TestBatching(unittest.TestCase):
    """E. Batching behavior -- six small forms batch into one group."""

    def test_batch_group_has_exactly_the_six_b_c_forms(self):
        self.assertEqual(len(BATCH_GROUP), 6)
        for name in BATCH_GROUP:
            self.assertEqual(route_document(name), ROUTE_EVAL_ONLY)
            self.assertTrue("Appendix B" in name or "Appendix C" in name)

    def test_batch_group_excludes_d_and_e_and_g_forms(self):
        for name in BATCH_GROUP:
            self.assertNotIn("Appendix D", name)
            self.assertNotIn("Appendix E", name)
            self.assertNotIn("Appendix G", name)


class TestSkipRules(unittest.TestCase):
    """F. Document skip rules from the audit."""

    def test_four_documents_skip(self):
        skip_docs = [name for name, route in DOCUMENT_ROUTING.items() if route == ROUTE_SKIP]
        self.assertEqual(len(skip_docs), 4)
        self.assertIn("abstract.pdf", skip_docs)
        self.assertIn("OriginalRevision/RFP 2026-026 - Appendix A - Submission Form.docx", skip_docs)
        self.assertIn("OriginalRevision/DP 2026-026 - Annexe F - Questionnaire ESG.xlsx", skip_docs)
        self.assertIn(
            "OriginalRevision/RFP 2026-026 - Appendix D2 - Rated Criteria Response Form.docx",
            skip_docs, "the superseded, pre-amendment D2 must be skipped, not the current one")

    def test_current_amendment_d2_is_not_skipped(self):
        self.assertNotEqual(
            route_document("Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx"),
            ROUTE_SKIP)


class TestScoringAmbiguityDetection(unittest.TestCase):
    """G. Evaluation-weight conflict detection."""

    def test_detects_conflicting_weight_for_same_label(self):
        criteria = [
            {"stage": "Corporate Profile", "weight": "5 points"},
            {"stage": "Corporate Profile", "weight": "10 points"},
            {"stage": "Key Personnel", "weight": "15 points"},
        ]
        conflicts = detect_evaluation_weight_conflicts(criteria)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["type"], "EVALUATION_WEIGHT_CONFLICT")
        self.assertEqual(conflicts[0]["label"], "corporate profile")
        self.assertEqual(set(conflicts[0]["competing_values"]), {"5 points", "10 points"})

    def test_no_conflict_when_weights_agree(self):
        criteria = [{"stage": "Corporate Profile", "weight": "5 points"},
                    {"stage": "Corporate Profile", "weight": "5 points"}]
        self.assertEqual(detect_evaluation_weight_conflicts(criteria), [])

    def test_no_conflict_from_single_occurrence(self):
        criteria = [{"stage": "Corporate Profile", "weight": "5 points"}]
        self.assertEqual(detect_evaluation_weight_conflicts(criteria), [])


class TestPricingAmbiguityDetection(unittest.TestCase):
    """H. Pricing-stage structural ambiguity detection."""

    def test_detects_price_inside_table_plus_separate_pricing_stage(self):
        criteria = [
            {"stage": "Price", "parent_stage": "Category 3 Table", "weight": "25 points"},
            {"stage": "Stage 4. Pricing", "parent_stage": None, "weight": None},
        ]
        result = detect_pricing_stage_ambiguity(criteria)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "PRICING_STAGE_AMBIGUITY")

    def test_no_ambiguity_when_only_top_level_pricing_stage_exists(self):
        criteria = [{"stage": "Stage 4. Pricing", "parent_stage": None, "weight": None}]
        self.assertEqual(detect_pricing_stage_ambiguity(criteria), [])

    def test_no_ambiguity_when_only_price_in_table_exists(self):
        criteria = [{"stage": "Price", "parent_stage": "Category 1 Table", "weight": "25 points"}]
        self.assertEqual(detect_pricing_stage_ambiguity(criteria), [])


class TestCategoryDateDistinction(unittest.TestCase):
    """I. Category-specific date handling -- distinguishes real distinctions
    from a true single-value conflict, using the same milestone family."""

    def test_different_categories_different_dates_is_not_an_ambiguity(self):
        """CI-1 Defect F deliberately overturns this case's previous
        expectation. A milestone's canonical identity is (event_type,
        scope): two categories' demo dates are two distinct scoped
        events, not one contradictory milestone. They are preserved as
        information by `derive_scope_distinct_milestones`, not raised as
        something the buyer must clarify."""
        from fast_analysis import derive_scope_distinct_milestones
        observations = [
            {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO", "date": "2026-10-26",
             "scope": {"category": "Category 1"}},
            {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO", "date": "2026-11-02",
             "scope": {"category": "Category 3"}},
        ]
        self.assertEqual(detect_category_date_distinctions(observations), [])
        preserved = derive_scope_distinct_milestones(observations)
        self.assertEqual(len(preserved), 1)
        self.assertEqual(preserved[0]["milestone_kind"], "PRESENTATION_OR_DEMO")
        self.assertEqual(len(preserved[0]["scopes"]), 2)

    def test_same_scope_conflicting_dates_is_still_an_ambiguity(self):
        observations = [
            {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO", "date": "2026-10-26",
             "scope": {"category": "Category 1"}},
            {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO", "date": "2026-11-02",
             "scope": {"category": "Category 1"}},
        ]
        result = detect_category_date_distinctions(observations)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["type"], "CATEGORY_DATE_DISTINCTION")
        self.assertEqual(result[0]["milestone_kind"], "PRESENTATION_OR_DEMO")

    def test_no_distinction_when_dates_agree(self):
        observations = [
            {"family": "MILESTONE", "semantic_kind": "SUBMISSION_DEADLINE", "date": "2026-09-30"},
            {"family": "MILESTONE", "semantic_kind": "SUBMISSION_DEADLINE", "date": "2026-09-30"},
        ]
        self.assertEqual(detect_category_date_distinctions(observations), [])

    def test_non_milestone_observations_are_ignored(self):
        observations = [{"family": "IDENTITY", "semantic_kind": "BUYER_NAME", "date": None}]
        self.assertEqual(detect_category_date_distinctions(observations), [])


class TestDeterministicReportAssembly(unittest.TestCase):
    """J. The adapter deterministically assembles the same content-module
    shape Deep Verify's PDF renderer expects, with no LLM call."""

    def test_adapter_produces_all_required_content_attributes(self):
        from scripts.fast_analysis_report_adapter import build_fast_report_content
        result = FastAnalysisResult()
        result.doc_metadata_by_doc[MASTER_RFP] = {
            "client": "Bank of Canada", "file_number": "RFP 2026-026",
            "title": "Talent, Learning and Organizational Development Services",
            "submission_deadline": "2026-09-30", "clarification_deadline": "2026-09-10",
        }
        content = build_fast_report_content(result)
        for attr in ("TITLE", "SNAPSHOT_FACTS", "SNAPSHOT_CATEGORY_CARDS", "VERIFIED_BUYER_FACTS",
                    "SERVICE_CATEGORIES", "KEY_DATES", "EVAL_STAGES", "EVAL_WEIGHTS",
                    "RESPONSE_CHECKLIST", "COMMERCIAL_POINTS", "AMBIGUITIES", "ATTENTION_POINTS",
                    "SOURCE_DOCUMENTS", "VALIDATION_FOOTER_NOTE"):
            self.assertTrue(hasattr(content, attr), f"missing content attribute: {attr}")

    def test_adapter_buyer_intelligence_is_byte_identical_to_deep_content(self):
        """Buyer Intelligence must be reused unchanged (explicit instruction
        S 6), not regenerated by this package.

        Phase 5 generalization: this external, hand-curated layer is only
        real content for Bank of Canada, so it is now only copied in when
        the current procurement's own extracted buyer actually matches --
        an empty/unknown-buyer result (the old fixture here) no longer
        receives it at all (that is the exact cross-corpus leakage the
        phase was authorized to fix). Use a Bank-of-Canada-identified
        result to exercise the byte-identical-copy behavior itself."""
        import scripts.boc_bid_intelligence_preview_content as DEEP
        from scripts.fast_analysis_report_adapter import build_fast_report_content
        result = FastAnalysisResult()
        result.doc_metadata_by_doc[MASTER_RFP] = {"client": "Bank of Canada"}
        content = build_fast_report_content(result)
        self.assertTrue(content.BUYER_INTEL_AVAILABLE)
        self.assertEqual(content.VERIFIED_BUYER_FACTS, DEEP.VERIFIED_BUYER_FACTS)
        self.assertEqual(content.BID_TEAM_PANEL_ITEMS, DEEP.BID_TEAM_PANEL_ITEMS)

    def test_adapter_snapshot_uses_extracted_buyer_when_present(self):
        from scripts.fast_analysis_report_adapter import build_fast_report_content
        result = FastAnalysisResult()
        result.doc_metadata_by_doc[MASTER_RFP] = {"client": "Bank of Canada",
                                                   "file_number": "RFP 2026-026"}
        content = build_fast_report_content(result)
        facts = dict(content.SNAPSHOT_FACTS)
        self.assertEqual(facts["Buyer"], "Bank of Canada")
        self.assertEqual(facts["Solicitation Number"], "RFP 2026-026")


if __name__ == "__main__":
    unittest.main()
