"""
tests/test_section_analyzer.py

Deterministic tests for the Section Analyzer (section_analyzer.py +
database.py's outline_section_requirements/section_reviews CRUD +
tenancy.py's authorization boundary). No live API calls, no live Supabase
connection, no Phoenix run anywhere in this file -- every provider call and
every database.py call is mocked, per this feature's own explicit
instruction to implement and test it without running Phoenix.
"""
import unittest
from unittest.mock import MagicMock, patch

import section_analyzer as sa
from fast_analysis import FastAnalysisResult


def _sample_section(section_id=1):
    return {"id": section_id, "bid_id": 1, "title": "Approach and Methodology",
           "notes": "Describe delivery model.", "word_limit": 500, "status": "Draft"}


def _sample_requirements():
    return [
        {"id": 101, "bid_id": 1, "req_id": "R1", "category": "Approach and Methodology",
         "description": "Describe your delivery methodology.", "weight": None, "source_refs": []},
        {"id": 102, "bid_id": 1, "req_id": "R2", "category": "Account Management and Relationship",
         "description": "Describe your account management approach.", "weight": None, "source_refs": []},
    ]


def _sample_raw_result() -> FastAnalysisResult:
    r = FastAnalysisResult()
    r.evaluation_criteria = [
        {"criterion_label": "Approach and Methodology", "weight": "10 points", "threshold": "6 points"},
        {"criterion_label": "Account Management and Relationship", "weight": "15 points", "threshold": "10 points"},
        {"criterion_label": "Pricing", "weight": "40 points", "threshold": None},
    ]
    r.deterministic_response_guidelines = [
        {"id": "RG1", "weight": "10", "minimum_score": "6",
         "evidence_prompts": ["Describe your delivery methodology."], "source_doc": "Appendix_B.docx"},
        {"id": "RG2", "weight": "15", "minimum_score": "10",
         "evidence_prompts": ["Describe your account management approach."], "source_doc": "Appendix_B.docx"},
    ]
    r.typed_observations = [
        {"family": "QUALIFICATION_MECHANISM", "semantic_kind": "REFERENCE_CHECK",
         "original_value": "Two references required.", "rank": None},
        {"family": "TIE_BREAK_RULE", "semantic_kind": "TIE_BREAK_CRITERION",
         "original_value": "Account Management governs first.", "rank": 1},
    ]
    r.buyer_intelligence = {
        "intro": "Buyer overview.",
        "verified_facts": [{"topic": "Operations", "detail": "Distributed retail and warehouse workforce.",
                            "source": "public filing"}],
    }
    return r


def _valid_llm_response(requirement_ids):
    return {
        "direction": "NEEDS_ADJUSTMENT",
        "summary": "The section describes methodology but lacks scale evidence.",
        "requirement_assessments": [
            {"requirement_id": rid, "criterion": f"Criterion {rid}", "status": "PARTIAL",
             "section_evidence": ["some text"], "gap": "No metrics", "recommended_action": "Add a metric",
             "dependency": "IN_SECTION"}
            for rid in requirement_ids
        ],
        "response_guideline_assessments": [
            {"guideline": "RG1", "prompt": "Describe your delivery methodology.", "status": "PARTIAL",
             "section_evidence": [], "recommended_action": "Add detail"},
        ],
        "evidence_assessment": {"strong_evidence": ["named methodology"],
                                "unsupported_claims": ["we are the best"],
                                "missing_evidence": ["scale example"]},
        "clarity_and_structure": ["Buried answer in paragraph 3"],
        "differentiation": [{"statement": "We are the best", "assessment": "UNSUPPORTED"}],
        "buyer_context": [{"external_fact": "Distributed workforce", "implication": "Add examples across sites",
                           "source": "Buyer Intelligence"}],
        "top_changes": ["Add a quantified example", "Answer RG1 explicitly", "Trim the introduction"],
    }


class TestContentHash(unittest.TestCase):

    def test_deterministic_and_matches_sha256(self):
        import hashlib
        self.assertEqual(sa.content_hash("hello"), hashlib.sha256(b"hello").hexdigest())

    def test_none_and_empty_string_both_hash_stably(self):
        self.assertEqual(sa.content_hash(None), sa.content_hash(""))

    def test_different_text_different_hash(self):
        self.assertNotEqual(sa.content_hash("a"), sa.content_hash("b"))


class TestProcurementBasis(unittest.TestCase):

    @patch("analysis_service.load_raw_fast_analysis_result")
    @patch("database.list_analysis_runs")
    @patch("database.get_bid_procurement_state")
    def test_governed_basis_with_compatible_snapshot(self, mock_state, mock_runs, mock_load):
        mock_state.return_value = {"procurement_revision": 3, "procurement_truth_status": "governed"}
        mock_runs.return_value = [{"id": 13, "analysis_mode": "FAST", "status": "COMPLETE"}]
        mock_load.return_value = _sample_raw_result()
        with patch("database.get_analysis_result", return_value={"id": 55}):
            basis = sa.procurement_basis(bid_id=1)
        self.assertEqual(basis["procurement_truth_status"], "governed")
        self.assertEqual(basis["procurement_revision"], 3)
        self.assertIsInstance(basis["raw_snapshot"], FastAnalysisResult)
        self.assertEqual(basis["raw_snapshot_run_id"], 13)
        self.assertEqual(basis["raw_snapshot_result_id"], 55)
        self.assertIsNone(basis["raw_snapshot_unavailable_reason"])

    @patch("database.list_analysis_runs")
    @patch("database.get_bid_procurement_state")
    def test_ungoverned_basis_with_no_complete_run(self, mock_state, mock_runs):
        mock_state.return_value = {"procurement_revision": 1, "procurement_truth_status": "ungoverned"}
        mock_runs.return_value = []
        basis = sa.procurement_basis(bid_id=1)
        self.assertEqual(basis["procurement_truth_status"], "ungoverned")
        self.assertIsNone(basis["raw_snapshot"])
        self.assertEqual(basis["raw_snapshot_unavailable_reason"], "NO_COMPLETE_FAST_ANALYSIS_RUN")

    @patch("analysis_service.load_raw_fast_analysis_result")
    @patch("database.list_analysis_runs")
    @patch("database.get_bid_procurement_state")
    def test_snapshot_unavailable_reason_propagates_sentinel(self, mock_state, mock_runs, mock_load):
        """Phoenix run 13's exact situation reused here: a COMPLETE run
        exists but has no durable raw snapshot."""
        import analysis_service as real_svc
        mock_state.return_value = {"procurement_revision": 1, "procurement_truth_status": "ungoverned"}
        mock_runs.return_value = [{"id": 13, "analysis_mode": "FAST", "status": "COMPLETE"}]
        mock_load.return_value = real_svc.RAW_FAST_ANALYSIS_SNAPSHOT_UNAVAILABLE
        basis = sa.procurement_basis(bid_id=1)
        self.assertIsNone(basis["raw_snapshot"])
        self.assertEqual(basis["raw_snapshot_unavailable_reason"], "RAW_FAST_ANALYSIS_SNAPSHOT_UNAVAILABLE")

    @patch("database.list_analysis_runs")
    @patch("database.get_bid_procurement_state")
    def test_only_completed_fast_runs_are_considered(self, mock_state, mock_runs):
        mock_state.return_value = {"procurement_revision": 1, "procurement_truth_status": "ungoverned"}
        mock_runs.return_value = [
            {"id": 20, "analysis_mode": "FAST", "status": "ANALYZING"},
            {"id": 19, "analysis_mode": "DEEP_VERIFY", "status": "COMPLETE"},
        ]
        basis = sa.procurement_basis(bid_id=1)
        self.assertIsNone(basis["raw_snapshot_run_id"])
        self.assertEqual(basis["raw_snapshot_unavailable_reason"], "NO_COMPLETE_FAST_ANALYSIS_RUN")

    def test_never_calls_run_fast_analysis_corpus(self):
        """No procurement re-analysis (instruction 8) -- structural
        guarantee, not just a mocked absence-of-call check: the function's
        own source never references it."""
        import inspect
        src = inspect.getsource(sa.procurement_basis)
        self.assertNotIn("run_fast_analysis_corpus", src)


class TestBuildSectionContext(unittest.TestCase):

    def test_matches_requirement_to_criterion_weight_and_minimum_score(self):
        basis = {"raw_snapshot": _sample_raw_result(), "procurement_truth_status": "governed",
                "procurement_revision": 1, "raw_snapshot_unavailable_reason": None}
        ctx = sa.build_section_context(_sample_section(), "draft text", _sample_requirements(), basis)
        r1 = next(r for r in ctx["requirements"] if r["requirement_id"] == 101)
        self.assertEqual(r1["evaluation_weight"], "10 points")
        self.assertEqual(r1["minimum_score"], "6 points")
        self.assertEqual(r1["response_guideline"]["id"], "RG1")

    def test_qualification_mechanisms_and_tie_break_included(self):
        basis = {"raw_snapshot": _sample_raw_result(), "procurement_truth_status": "governed",
                "procurement_revision": 1, "raw_snapshot_unavailable_reason": None}
        ctx = sa.build_section_context(_sample_section(), "text", _sample_requirements(), basis)
        self.assertEqual(len(ctx["qualification_mechanisms"]), 1)
        self.assertEqual(ctx["tie_break_rules"][0]["rank"], 1)

    def test_buyer_intelligence_kept_as_its_own_key_not_merged_into_requirements(self):
        """Buyer Intelligence must stay visibly separate from procurement
        requirement facts (instruction 4.I) -- structurally enforced by
        living in its own top-level context key, never inside a
        requirement's own dict."""
        basis = {"raw_snapshot": _sample_raw_result(), "procurement_truth_status": "governed",
                "procurement_revision": 1, "raw_snapshot_unavailable_reason": None}
        ctx = sa.build_section_context(_sample_section(), "text", _sample_requirements(), basis)
        self.assertIn("buyer_intelligence", ctx)
        for r in ctx["requirements"]:
            self.assertNotIn("buyer_intelligence", r)

    def test_no_raw_snapshot_means_no_fabricated_enrichment(self):
        basis = {"raw_snapshot": None, "procurement_truth_status": "ungoverned",
                "procurement_revision": 1, "raw_snapshot_unavailable_reason": "NO_COMPLETE_FAST_ANALYSIS_RUN"}
        ctx = sa.build_section_context(_sample_section(), "text", _sample_requirements(), basis)
        for r in ctx["requirements"]:
            self.assertIsNone(r["evaluation_weight"])
            self.assertIsNone(r["minimum_score"])
            self.assertIsNone(r["response_guideline"])
        self.assertIsNone(ctx["buyer_intelligence"])
        self.assertFalse(ctx["procurement_basis"]["advisory_intelligence_available"])

    def test_context_excludes_unmapped_requirements(self):
        """Compact, section-scoped bundle (instruction 9) -- only the
        requirements actually passed in appear; the full corpus is never
        pulled in."""
        basis = {"raw_snapshot": None, "procurement_truth_status": "ungoverned",
                "procurement_revision": 1, "raw_snapshot_unavailable_reason": "x"}
        ctx = sa.build_section_context(_sample_section(), "text", [_sample_requirements()[0]], basis)
        self.assertEqual(len(ctx["requirements"]), 1)


class TestStructuredOutputValidation(unittest.TestCase):

    def test_valid_response_passes(self):
        parsed = _valid_llm_response([101, 102])
        self.assertTrue(sa._validate_review_json(parsed, {101, 102}))

    def test_missing_direction_fails(self):
        parsed = _valid_llm_response([101])
        parsed["direction"] = "MAYBE"
        self.assertFalse(sa._validate_review_json(parsed, {101}))

    def test_invalid_requirement_status_fails(self):
        parsed = _valid_llm_response([101])
        parsed["requirement_assessments"][0]["status"] = "SORT_OF"
        self.assertFalse(sa._validate_review_json(parsed, {101}))

    def test_invalid_rg_status_fails(self):
        parsed = _valid_llm_response([101])
        parsed["response_guideline_assessments"][0]["status"] = "MOSTLY"
        self.assertFalse(sa._validate_review_json(parsed, {101}))

    def test_more_than_five_top_changes_fails(self):
        parsed = _valid_llm_response([101])
        parsed["top_changes"] = ["a", "b", "c", "d", "e", "f"]
        self.assertFalse(sa._validate_review_json(parsed, {101}))

    def test_no_numeric_score_field_in_schema(self):
        """The schema has no predicted-score field anywhere -- a response
        containing one is still valid (extra keys are fine) but nothing in
        validation ever requires or reads one, and the prompt template
        never asks for it."""
        self.assertNotIn('"score"', sa._analyzer_prompt.__doc__ or "")
        self.assertNotIn("predicted_score", sa._ANALYZER_SYSTEM)

    def test_reconcile_drops_hallucinated_requirement_ids(self):
        parsed = _valid_llm_response([101, 999])  # 999 was never sent
        reconciled = sa._reconcile_requirement_ids(parsed, {101})
        ids = {ra["requirement_id"] for ra in reconciled["requirement_assessments"]}
        self.assertEqual(ids, {101})


class TestBoundedModelCall(unittest.TestCase):

    def _mock_response(self, text):
        resp = MagicMock()
        resp.content = [MagicMock(text=text)]
        return resp

    @patch("section_analyzer.execute_messages_create")
    @patch("section_analyzer.get_anthropic_client")
    def test_success_on_first_attempt_makes_exactly_one_call(self, mock_client, mock_exec):
        import json
        mock_exec.return_value = self._mock_response(json.dumps(_valid_llm_response([101])))
        parsed, failure = sa._call_section_analyzer("prompt", {101})
        self.assertIsNone(failure)
        self.assertEqual(parsed["direction"], "NEEDS_ADJUSTMENT")
        self.assertEqual(mock_exec.call_count, 1)

    @patch("section_analyzer.execute_messages_create")
    @patch("section_analyzer.get_anthropic_client")
    def test_malformed_first_response_recovers_on_bounded_retry(self, mock_client, mock_exec):
        import json
        mock_exec.side_effect = [
            self._mock_response("not json at all"),
            self._mock_response(json.dumps(_valid_llm_response([101]))),
        ]
        parsed, failure = sa._call_section_analyzer("prompt", {101})
        self.assertIsNone(failure)
        self.assertEqual(mock_exec.call_count, 2)

    @patch("section_analyzer.execute_messages_create")
    @patch("section_analyzer.get_anthropic_client")
    def test_both_attempts_failing_returns_categorized_failure_not_exception(self, mock_client, mock_exec):
        mock_exec.side_effect = [Exception("boom"), Exception("boom again")]
        parsed, failure = sa._call_section_analyzer("prompt", {101})
        self.assertIsNone(parsed)
        self.assertIsNotNone(failure)
        self.assertEqual(mock_exec.call_count, 2)

    @patch("section_analyzer.execute_messages_create")
    @patch("section_analyzer.get_anthropic_client")
    def test_never_makes_a_third_call(self, mock_client, mock_exec):
        mock_exec.side_effect = Exception("always fails")
        sa._call_section_analyzer("prompt", {101})
        self.assertEqual(mock_exec.call_count, 2)  # bounded: 1 + 1 retry, never more


class TestStaleness(unittest.TestCase):

    def _current_review(self, **overrides):
        base = {
            "section_content_hash": sa.content_hash("original text"),
            "mapped_requirement_ids": [101, 102],
            "based_on_procurement_revision": 1,
            "based_on_procurement_truth_status": "ungoverned",
            "based_on_analysis_result_id": None,
        }
        base.update(overrides)
        return base

    def _current_basis(self, **overrides):
        base = {"procurement_revision": 1, "procurement_truth_status": "ungoverned", "raw_snapshot": None}
        base.update(overrides)
        return base

    def test_not_stale_when_nothing_changed(self):
        review = self._current_review()
        stale = sa.is_section_review_stale(review, sa.content_hash("original text"), {101, 102}, self._current_basis())
        self.assertFalse(stale)

    def test_stale_after_section_content_changes(self):
        review = self._current_review()
        stale = sa.is_section_review_stale(review, sa.content_hash("EDITED text"), {101, 102}, self._current_basis())
        self.assertTrue(stale)

    def test_stale_after_mapped_requirements_change(self):
        review = self._current_review()
        stale = sa.is_section_review_stale(review, sa.content_hash("original text"), {101}, self._current_basis())
        self.assertTrue(stale)

    def test_stale_after_procurement_revision_changes(self):
        review = self._current_review()
        stale = sa.is_section_review_stale(review, sa.content_hash("original text"), {101, 102},
                                           self._current_basis(procurement_revision=2))
        self.assertTrue(stale)

    def test_stale_after_procurement_truth_status_changes(self):
        review = self._current_review()
        stale = sa.is_section_review_stale(review, sa.content_hash("original text"), {101, 102},
                                           self._current_basis(procurement_truth_status="governed"))
        self.assertTrue(stale)

    def test_stale_when_snapshot_availability_flips(self):
        review = self._current_review()  # reviewed with no snapshot
        stale = sa.is_section_review_stale(review, sa.content_hash("original text"), {101, 102},
                                           self._current_basis(raw_snapshot=_sample_raw_result()))
        self.assertTrue(stale)


class TestIdempotency(unittest.TestCase):
    """No duplicate provider calls / review rows for one button action
    (instruction 19)."""

    @patch("database.get_section_reviews")
    def test_find_matching_review_returns_current_review_without_recomputation(self, mock_get_reviews):
        current_hash = sa.content_hash("text")
        existing = {"id": 1, "section_content_hash": current_hash, "mapped_requirement_ids": [101],
                   "based_on_procurement_revision": 1, "based_on_procurement_truth_status": "ungoverned",
                   "based_on_analysis_result_id": None}
        mock_get_reviews.return_value = [existing]
        basis = {"procurement_revision": 1, "procurement_truth_status": "ungoverned", "raw_snapshot": None}
        found = sa.find_matching_review(bid_id=1, section_id=1, current_hash=current_hash,
                                        mapped_requirement_ids=[101], basis=basis)
        self.assertEqual(found, existing)

    @patch("database.get_section_reviews")
    def test_find_matching_review_returns_none_when_only_stale_reviews_exist(self, mock_get_reviews):
        stale = {"id": 1, "section_content_hash": sa.content_hash("old text"), "mapped_requirement_ids": [101],
                "based_on_procurement_revision": 1, "based_on_procurement_truth_status": "ungoverned",
                "based_on_analysis_result_id": None}
        mock_get_reviews.return_value = [stale]
        basis = {"procurement_revision": 1, "procurement_truth_status": "ungoverned", "raw_snapshot": None}
        found = sa.find_matching_review(bid_id=1, section_id=1, current_hash=sa.content_hash("new text"),
                                        mapped_requirement_ids=[101], basis=basis)
        self.assertIsNone(found)

    @patch("database.create_section_review")
    @patch("database.get_section_reviews")
    @patch("database.get_requirements_by_ids")
    @patch("section_analyzer.procurement_basis")
    def test_analyze_section_reuses_matching_review_without_calling_model(
        self, mock_basis, mock_reqs, mock_get_reviews, mock_create
    ):
        section = _sample_section()
        mock_reqs.return_value = [_sample_requirements()[0]]
        mock_basis.return_value = {"procurement_revision": 1, "procurement_truth_status": "ungoverned",
                                   "raw_snapshot": None, "raw_snapshot_run_id": None,
                                   "raw_snapshot_result_id": None, "raw_snapshot_unavailable_reason": "x"}
        current_hash = sa.content_hash("the text")
        existing = {"id": 5, "section_content_hash": current_hash, "mapped_requirement_ids": [101],
                   "based_on_procurement_revision": 1, "based_on_procurement_truth_status": "ungoverned",
                   "based_on_analysis_result_id": None}
        mock_get_reviews.return_value = [existing]

        with patch("section_analyzer._call_section_analyzer") as mock_call:
            result = sa.analyze_section(bid_id=1, section=section, section_text="the text",
                                        mapped_requirement_ids=[101])
            mock_call.assert_not_called()
        mock_create.assert_not_called()
        self.assertEqual(result, existing)


class TestAnalyzeSectionOrchestration(unittest.TestCase):

    @patch("database.create_section_review")
    @patch("database.get_section_reviews")
    @patch("database.get_requirements_by_ids")
    @patch("section_analyzer.procurement_basis")
    @patch("section_analyzer._call_section_analyzer")
    def test_new_review_persisted_with_correct_provenance(
        self, mock_call, mock_basis, mock_reqs, mock_get_reviews, mock_create
    ):
        section = _sample_section()
        mock_reqs.return_value = [_sample_requirements()[0]]
        mock_get_reviews.return_value = []  # no existing review -> must call the model
        mock_basis.return_value = {"procurement_revision": 4, "procurement_truth_status": "governed",
                                   "raw_snapshot": _sample_raw_result(), "raw_snapshot_run_id": 13,
                                   "raw_snapshot_result_id": 55, "raw_snapshot_unavailable_reason": None}
        mock_call.return_value = (_valid_llm_response([101]), None)
        mock_create.return_value = {"id": 9, "direction": "NEEDS_ADJUSTMENT"}

        result = sa.analyze_section(bid_id=1, section=section, section_text="the current text",
                                    mapped_requirement_ids=[101], created_by_user_id="user-123")

        mock_create.assert_called_once()
        payload = mock_create.call_args[0][0]
        self.assertEqual(payload["section_content_snapshot"], "the current text")
        self.assertEqual(payload["section_content_hash"], sa.content_hash("the current text"))
        self.assertEqual(payload["mapped_requirement_ids"], [101])
        self.assertEqual(payload["based_on_procurement_revision"], 4)
        self.assertEqual(payload["based_on_procurement_truth_status"], "governed")
        self.assertEqual(payload["based_on_analysis_run_id"], 13)
        self.assertEqual(payload["based_on_analysis_result_id"], 55)
        self.assertEqual(payload["created_by_user_id"], "user-123")
        self.assertEqual(payload["review_schema_version"], sa.SECTION_REVIEW_SCHEMA_VERSION)
        self.assertEqual(result["id"], 9)

    @patch("database.get_outline")
    @patch("database.get_section_reviews")
    @patch("database.get_requirements_by_ids")
    @patch("section_analyzer.procurement_basis")
    @patch("section_analyzer._call_section_analyzer")
    def test_current_editor_text_is_what_gets_analyzed_not_a_db_refetch(
        self, mock_call, mock_basis, mock_reqs, mock_get_reviews, mock_get_outline
    ):
        """instruction 2/18: analyze_section must use exactly the
        section_text the caller passed in, and must never re-fetch section
        content from the database to get it -- database.get_outline (the
        only function that could return a different, possibly-stale
        'notes' value for this section) is never called at all."""
        section = _sample_section()
        mock_reqs.return_value = []
        mock_get_reviews.return_value = []
        mock_basis.return_value = {"procurement_revision": 1, "procurement_truth_status": "ungoverned",
                                   "raw_snapshot": None, "raw_snapshot_run_id": None,
                                   "raw_snapshot_result_id": None, "raw_snapshot_unavailable_reason": "x"}
        mock_call.return_value = (_valid_llm_response([]), None)

        with patch("database.create_section_review", return_value={"id": 1}):
            sa.analyze_section(bid_id=1, section=section, section_text="the CURRENT unsaved editor text",
                               mapped_requirement_ids=[])

        prompt_arg = mock_call.call_args[0][0]
        self.assertIn("the CURRENT unsaved editor text", prompt_arg)
        mock_get_outline.assert_not_called()

    @patch("database.get_section_reviews")
    @patch("database.get_requirements_by_ids")
    @patch("section_analyzer.procurement_basis")
    @patch("section_analyzer._call_section_analyzer")
    def test_provider_failure_raises_categorized_error_and_persists_nothing(
        self, mock_call, mock_basis, mock_reqs, mock_get_reviews
    ):
        section = _sample_section()
        mock_reqs.return_value = []
        mock_get_reviews.return_value = []
        mock_basis.return_value = {"procurement_revision": 1, "procurement_truth_status": "ungoverned",
                                   "raw_snapshot": None, "raw_snapshot_run_id": None,
                                   "raw_snapshot_result_id": None, "raw_snapshot_unavailable_reason": "x"}
        mock_call.return_value = (None, "api_error")

        with patch("database.create_section_review") as mock_create:
            with self.assertRaises(sa.SectionAnalyzerError) as ctx:
                sa.analyze_section(bid_id=1, section=section, section_text="text", mapped_requirement_ids=[])
            self.assertEqual(ctx.exception.category, "api_error")
            mock_create.assert_not_called()

    @patch("database.get_section_reviews")
    @patch("database.get_requirements_by_ids")
    @patch("section_analyzer.procurement_basis")
    @patch("section_analyzer._call_section_analyzer")
    def test_persistence_failure_raises_not_silently_ignored(
        self, mock_call, mock_basis, mock_reqs, mock_get_reviews
    ):
        section = _sample_section()
        mock_reqs.return_value = []
        mock_get_reviews.return_value = []
        mock_basis.return_value = {"procurement_revision": 1, "procurement_truth_status": "ungoverned",
                                   "raw_snapshot": None, "raw_snapshot_run_id": None,
                                   "raw_snapshot_result_id": None, "raw_snapshot_unavailable_reason": "x"}
        mock_call.return_value = (_valid_llm_response([]), None)

        with patch("database.create_section_review", return_value=None):
            with self.assertRaises(sa.SectionAnalyzerError) as ctx:
                sa.analyze_section(bid_id=1, section=section, section_text="text", mapped_requirement_ids=[])
            self.assertEqual(ctx.exception.category, "PERSISTENCE_FAILED")


class TestDatabaseCrud(unittest.TestCase):
    """database.py's new CRUD -- mocked Supabase client, no live connection."""

    def test_get_section_requirement_ids(self):
        import database as db
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[{"requirement_id": 101}, {"requirement_id": 102}])
        with patch("database.get_client", return_value=mock_sb):
            ids = db.get_section_requirement_ids(section_id=1)
        self.assertEqual(ids, [101, 102])

    def test_set_section_requirement_mapping_replace_all(self):
        import database as db
        mock_sb = MagicMock()
        with patch("database.get_client", return_value=mock_sb):
            db.set_section_requirement_mapping(bid_id=1, section_id=1, requirement_ids=[102, 101])
        mock_sb.table.return_value.delete.return_value.eq.assert_called_once_with("section_id", 1)
        insert_call = mock_sb.table.return_value.insert.call_args[0][0]
        self.assertEqual([r["requirement_id"] for r in insert_call], [101, 102])  # sorted, deduped

    def test_set_section_requirement_mapping_empty_list_only_deletes(self):
        import database as db
        mock_sb = MagicMock()
        with patch("database.get_client", return_value=mock_sb):
            db.set_section_requirement_mapping(bid_id=1, section_id=1, requirement_ids=[])
        mock_sb.table.return_value.insert.assert_not_called()

    def test_create_section_review_only_inserts_known_keys(self):
        import database as db
        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": 1}])
        with patch("database.get_client", return_value=mock_sb):
            row = db.create_section_review({"bid_id": 1, "section_id": 1, "direction": "ON_TRACK",
                                            "malicious_extra_field": "x", "review_result": {}})
        inserted = mock_sb.table.return_value.insert.call_args[0][0]
        self.assertNotIn("malicious_extra_field", inserted)
        self.assertEqual(row, {"id": 1})

    def test_get_requirements_by_ids_empty_list_returns_empty_without_querying(self):
        import database as db
        with patch("database.get_client") as mock_get_client:
            result = db.get_requirements_by_ids(bid_id=1, requirement_ids=[])
        self.assertEqual(result, [])
        mock_get_client.assert_not_called()


class TestReviewImmutability(unittest.TestCase):

    def test_no_update_or_delete_function_exists_for_section_reviews(self):
        import database as db
        self.assertFalse(hasattr(db, "update_section_review"))
        self.assertFalse(hasattr(db, "delete_section_review"))

    def test_create_section_review_is_insert_only(self):
        import inspect
        import database as db
        src = inspect.getsource(db.create_section_review)
        self.assertIn(".insert(", src)
        self.assertNotIn(".update(", src)
        self.assertNotIn(".delete(", src)


class TestTenancyAuthorizationBoundary(unittest.TestCase):
    """Mirrors the established convention (tests/test_fast_analysis_raw_
    snapshot.py::TestTenantIsolationThroughNormalServiceBoundary) for the
    Section Analyzer's own privileged action."""

    def test_analyze_section_never_calls_get_client_directly(self):
        import inspect
        import tenancy
        src = inspect.getsource(tenancy.analyze_section_for_organization)
        self.assertNotIn("get_client()", src)

    @patch("tenancy.db.get_client")
    def test_unauthorized_org_cannot_reach_the_analyzer_at_all(self, mock_get_client):
        import tenancy
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[])  # bid not owned by this organization
        mock_get_client.return_value = sb

        with patch("section_analyzer.analyze_section") as mock_analyze:
            with self.assertRaises(tenancy.AccessDeniedError):
                tenancy.analyze_section_for_organization(8, 1, "text", [], "org-999-unrelated")
            mock_analyze.assert_not_called()

    @patch("tenancy.db.get_outline")
    @patch("tenancy.db.get_client")
    def test_authorized_org_but_section_from_different_bid_is_denied(self, mock_get_client, mock_get_outline):
        import tenancy
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[{"id": 8, "organization_id": "org-1"}])  # caller owns bid 8
        mock_get_client.return_value = sb
        mock_get_outline.return_value = []  # section 1 does not belong to bid 8

        with patch("section_analyzer.analyze_section") as mock_analyze:
            with self.assertRaises(tenancy.AccessDeniedError):
                tenancy.analyze_section_for_organization(8, 1, "text", [], "org-1")
            mock_analyze.assert_not_called()

    @patch("tenancy.db.get_outline")
    @patch("tenancy.db.get_client")
    def test_authorized_org_and_matching_section_succeeds(self, mock_get_client, mock_get_outline):
        import tenancy
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = \
            MagicMock(data=[{"id": 8, "organization_id": "org-1"}])
        mock_get_client.return_value = sb
        mock_get_outline.return_value = [_sample_section(section_id=1)]

        with patch("section_analyzer.analyze_section", return_value={"id": 1}) as mock_analyze:
            result = tenancy.analyze_section_for_organization(8, 1, "text", [101], "org-1", user_id="u-1")
            self.assertEqual(result, {"id": 1})
            mock_analyze.assert_called_once_with(8, _sample_section(section_id=1), "text", [101],
                                                 created_by_user_id="u-1")

    def test_crud_wrappers_use_authenticated_client_never_service_role(self):
        """Category A CRUD (get/set mapping, get review history) must go
        through auth_client.get_authenticated_client(access_token) -- the
        user-scoped, RLS-respecting client -- never database.get_client()
        (the service-role client that bypasses RLS)."""
        import inspect
        import tenancy
        for fn in (tenancy.get_section_requirement_ids_authenticated,
                  tenancy.set_section_requirement_mapping_authenticated,
                  tenancy.get_section_reviews_authenticated):
            src = inspect.getsource(fn)
            self.assertIn("get_authenticated_client", src)
            self.assertNotIn("db.get_client", src)


class TestAcceptanceDemoWithoutLiveRfpAnalysis(unittest.TestCase):
    """instruction 25: a synthetic bid/section, two mapped requirements
    (one covered, one partial), one relevant RG block, one explicit
    evaluation weight, one minimum-score threshold, and one Buyer
    Intelligence signal, reviewed twice across a content edit -- proving
    the full formative-review loop end-to-end with zero live LLM/RFP
    analysis calls anywhere."""

    def _synthetic_section(self):
        return {"id": 501, "bid_id": 900, "title": "Approach and Methodology",
               "notes": "Explain the delivery model.", "word_limit": 400, "status": "Draft"}

    def _synthetic_requirements(self):
        return [
            {"id": 9001, "bid_id": 900, "req_id": "R1", "category": "Approach and Methodology",
             "description": "Describe your delivery methodology in detail.", "weight": None, "source_refs": []},
            {"id": 9002, "bid_id": 900, "req_id": "R2", "category": "Approach and Methodology",
             "description": "Describe how you measure delivery outcomes.", "weight": None, "source_refs": []},
        ]

    def _synthetic_raw_result(self):
        r = FastAnalysisResult()
        r.evaluation_criteria = [
            {"criterion_label": "Approach and Methodology", "weight": "10 points", "threshold": "6 points"},
        ]
        r.deterministic_response_guidelines = [
            {"id": "RG1", "weight": "10", "minimum_score": "6",
             "evidence_prompts": ["Describe your delivery methodology in detail."],
             "source_doc": "Appendix_B.docx"},
        ]
        r.buyer_intelligence = {
            "verified_facts": [{"topic": "Operations", "detail": "Distributed retail and warehouse workforce.",
                                "source": "public filing"}],
        }
        return r

    def _imperfect_review_response(self):
        return {
            "direction": "NEEDS_ADJUSTMENT",
            "summary": "The section explains the delivery model but does not describe how outcomes are measured.",
            "requirement_assessments": [
                {"requirement_id": 9001, "criterion": "Delivery methodology", "status": "COVERED",
                 "section_evidence": ["We use a phased coaching model."], "gap": "",
                 "recommended_action": "None needed", "dependency": "IN_SECTION"},
                {"requirement_id": 9002, "criterion": "Outcome measurement", "status": "MISSING",
                 "section_evidence": [], "gap": "No measurement approach is described.",
                 "recommended_action": "Add a specific outcome-measurement method", "dependency": "IN_SECTION"},
            ],
            "response_guideline_assessments": [
                {"guideline": "RG1", "prompt": "Describe your delivery methodology in detail.",
                 "status": "ANSWERED", "section_evidence": ["phased coaching model"], "recommended_action": ""},
            ],
            "evidence_assessment": {
                "strong_evidence": ["phased coaching model"],
                "unsupported_claims": ["We are the industry leader in coaching outcomes"],
                "missing_evidence": ["a quantified outcome metric"],
            },
            "clarity_and_structure": [],
            "differentiation": [{"statement": "We are the industry leader", "assessment": "UNSUPPORTED"}],
            "buyer_context": [{"external_fact": "Distributed retail and warehouse workforce",
                               "implication": "Examples limited to head-office roles may feel unrepresentative",
                               "source": "Buyer Intelligence"}],
            "top_changes": [
                "Add a specific outcome-measurement method to answer R2",
                "Replace the unsupported leadership claim with a quantified example",
                "Add an example spanning both retail and warehouse roles",
            ],
        }

    @patch("database.create_section_review")
    @patch("database.get_section_reviews")
    @patch("database.get_requirements_by_ids")
    @patch("section_analyzer.procurement_basis")
    @patch("section_analyzer._call_section_analyzer")
    def test_first_review_identifies_expected_findings(
        self, mock_call, mock_basis, mock_reqs, mock_get_reviews, mock_create
    ):
        section = self._synthetic_section()
        mock_reqs.return_value = self._synthetic_requirements()
        mock_get_reviews.return_value = []
        mock_basis.return_value = {"procurement_revision": 1, "procurement_truth_status": "ungoverned",
                                   "raw_snapshot": self._synthetic_raw_result(), "raw_snapshot_run_id": 1,
                                   "raw_snapshot_result_id": 1, "raw_snapshot_unavailable_reason": None}
        response = self._imperfect_review_response()
        mock_call.return_value = (response, None)
        mock_create.return_value = {"id": 1, "direction": "NEEDS_ADJUSTMENT", "review_result": response,
                                    "section_content_hash": sa.content_hash("We use a phased coaching model."),
                                    "mapped_requirement_ids": [9001, 9002],
                                    "based_on_procurement_revision": 1,
                                    "based_on_procurement_truth_status": "ungoverned",
                                    "based_on_analysis_result_id": 1}

        review = sa.analyze_section(bid_id=900, section=section, section_text="We use a phased coaching model.",
                                    mapped_requirement_ids=[9001, 9002])

        result = review["review_result"]
        statuses = {ra["requirement_id"]: ra["status"] for ra in result["requirement_assessments"]}
        self.assertEqual(statuses[9001], "COVERED")
        self.assertEqual(statuses[9002], "MISSING")
        self.assertEqual(result["evidence_assessment"]["unsupported_claims"],
                         ["We are the industry leader in coaching outcomes"])
        self.assertEqual(result["evidence_assessment"]["missing_evidence"], ["a quantified outcome metric"])
        self.assertEqual(len(result["buyer_context"]), 1)
        self.assertEqual(len(result["top_changes"]), 3)
        mock_call.assert_called_once()  # exactly one model call for this review

    @patch("database.create_section_review")
    @patch("database.get_section_reviews")
    @patch("database.get_requirements_by_ids")
    @patch("section_analyzer.procurement_basis")
    @patch("section_analyzer._call_section_analyzer")
    def test_edit_makes_review_stale_then_reanalyzing_persists_a_new_separate_review(
        self, mock_call, mock_basis, mock_reqs, mock_get_reviews, mock_create
    ):
        section = self._synthetic_section()
        mock_reqs.return_value = self._synthetic_requirements()
        basis = {"procurement_revision": 1, "procurement_truth_status": "ungoverned",
                "raw_snapshot": self._synthetic_raw_result(), "raw_snapshot_run_id": 1,
                "raw_snapshot_result_id": 1, "raw_snapshot_unavailable_reason": None}
        mock_basis.return_value = basis

        first_text = "We use a phased coaching model."
        first_review = {"id": 1, "section_content_hash": sa.content_hash(first_text),
                        "mapped_requirement_ids": [9001, 9002], "based_on_procurement_revision": 1,
                        "based_on_procurement_truth_status": "ungoverned", "based_on_analysis_result_id": 1}

        # Old review is on record; the writer has since edited the text.
        mock_get_reviews.return_value = [first_review]
        second_text = "We use a phased coaching model AND we measure outcomes quarterly."
        current_hash = sa.content_hash(second_text)

        self.assertTrue(sa.is_section_review_stale(first_review, current_hash, {9001, 9002}, basis))

        mock_call.return_value = (self._imperfect_review_response(), None)
        mock_create.return_value = {"id": 2, "section_content_hash": current_hash}

        new_review = sa.analyze_section(bid_id=900, section=section, section_text=second_text,
                                        mapped_requirement_ids=[9001, 9002])

        mock_call.assert_called_once()  # the edit forced exactly one new model call
        mock_create.assert_called_once()
        self.assertNotEqual(new_review["id"], first_review["id"])  # a NEW row, old one untouched

    @patch("database.create_section_review")
    @patch("database.get_section_reviews")
    @patch("database.get_requirements_by_ids")
    @patch("section_analyzer.procurement_basis")
    @patch("section_analyzer._call_section_analyzer")
    def test_rerun_with_unchanged_state_never_duplicates_the_model_call(
        self, mock_call, mock_basis, mock_reqs, mock_get_reviews, mock_create
    ):
        """Simulates a Streamlit rerun re-invoking analyze_section for the
        exact same on-screen state (instruction 19) -- must reuse the
        existing review, not spend a second model call or create a
        duplicate row."""
        section = self._synthetic_section()
        mock_reqs.return_value = self._synthetic_requirements()
        basis = {"procurement_revision": 1, "procurement_truth_status": "ungoverned",
                "raw_snapshot": self._synthetic_raw_result(), "raw_snapshot_run_id": 1,
                "raw_snapshot_result_id": 1, "raw_snapshot_unavailable_reason": None}
        mock_basis.return_value = basis
        text = "We use a phased coaching model."
        existing = {"id": 1, "section_content_hash": sa.content_hash(text),
                   "mapped_requirement_ids": [9001, 9002], "based_on_procurement_revision": 1,
                   "based_on_procurement_truth_status": "ungoverned", "based_on_analysis_result_id": 1}
        mock_get_reviews.return_value = [existing]

        result = sa.analyze_section(bid_id=900, section=section, section_text=text,
                                    mapped_requirement_ids=[9001, 9002])

        mock_call.assert_not_called()
        mock_create.assert_not_called()
        self.assertEqual(result["id"], 1)


if __name__ == "__main__":
    unittest.main()
