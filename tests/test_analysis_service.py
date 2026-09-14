"""
tests/test_analysis_service.py

Deterministic tests for analysis_service.py (Product Integration Phase 1).
No live API calls, no live Supabase connection -- every database.py and
fast_analysis.run_fast_analysis_corpus call is mocked. Covers exactly the
Phase 1 authorization's test list (instruction 26): analysis creation,
lifecycle, corpus association, successful/failed completion, duplicate-start
protection, structured-result persistence, source-reference persistence,
fact-origin persistence, report generation from persisted results, report
regeneration without extraction, Fast vs Deep mode separation, and
engine-version persistence.

"Ownership/access control" (instruction 26/21): this application has no
user-level authentication or multi-tenant model at all (confirmed by direct
inspection -- see FAST_ANALYSIS_PRODUCT_INTEGRATION_PHASE1_REPORT.md S1).
The only scoping boundary that exists anywhere in this schema is bid_id,
applied consistently to every table. The access-control tests here verify
that boundary is honored by this new code, which is the full extent of
"access control" this repository currently has to preserve.
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import analysis_service as svc
from fast_analysis import FastAnalysisResult

MASTER_RFP = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"
# Deliberately NOT in fast_analysis.DOCUMENT_ROUTING -- exercises
# route_document()'s generic fallback (ROUTE_IDENTITY_EVAL_REQ for any
# unrecognized document), so milestone tests aren't tied to one specific
# corpus.
GENERIC_RFP = "generic_master_rfp.pdf"
D1_DOC = "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx"  # ROUTE_EVAL_ONLY
APPENDIX_G = "OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx"  # ROUTE_COMMERCIAL_ONLY


def _sample_docs(bid_id=1):
    return [
        {"id": 10, "bid_id": bid_id, "name": MASTER_RFP, "doc_type": "RFP / Source",
         "version": 1, "storage_path": f"{bid_id}/abc123.pdf"},
    ]


def _sample_fast_result() -> FastAnalysisResult:
    r = FastAnalysisResult()
    r.doc_metadata_by_doc[MASTER_RFP] = {"client": "Bank of Canada", "file_number": "2026-026"}
    r.evaluation_occurrences = [
        {"criterion_label": "Corporate Profile", "weight": "5 points", "category_scope": "Appendix D1"},
    ]
    return r


class TestAnalysisCreationAndCorpusAssociation(unittest.TestCase):

    @patch("analysis_service.db")
    def test_start_creates_run_with_engine_version_and_corpus_snapshot(self, mock_db):
        mock_db.get_active_analysis_run.return_value = None
        mock_db.get_documents.return_value = _sample_docs(bid_id=7)
        mock_db.create_analysis_run.return_value = {"id": 99, "status": "QUEUED"}
        with patch("analysis_service.threading.Thread") as mock_thread:
            run = svc.start_fast_analysis(bid_id=7, api_key="fake")
        self.assertEqual(run["id"], 99)
        mock_db.create_analysis_run.assert_called_once()
        args, kwargs = mock_db.create_analysis_run.call_args
        self.assertEqual(args[0], 7)                             # bid_id
        self.assertEqual(args[1], "FAST")                        # analysis_mode
        self.assertEqual(args[2], svc.FAST_ANALYSIS_ENGINE_VERSION)  # engine_version
        corpus_ids = args[3]
        self.assertEqual(len(corpus_ids), 1)
        self.assertEqual(corpus_ids[0]["document_id"], 10)
        mock_thread.assert_called_once()

    @patch("analysis_service.db")
    def test_start_queries_documents_scoped_to_the_given_bid_id(self, mock_db):
        """Access-control boundary: this app has no user auth, only bid_id
        scoping (see module docstring above) -- confirm it's honored."""
        mock_db.get_active_analysis_run.return_value = None
        mock_db.get_documents.return_value = _sample_docs(bid_id=42)
        mock_db.create_analysis_run.return_value = {"id": 1, "status": "QUEUED"}
        with patch("analysis_service.threading.Thread"):
            svc.start_fast_analysis(bid_id=42, api_key="fake")
        mock_db.get_documents.assert_called_once_with(42)
        mock_db.get_active_analysis_run.assert_called_once_with(42, "FAST")

    @patch("analysis_service.db")
    def test_no_corpus_raises_before_any_run_is_created(self, mock_db):
        mock_db.get_active_analysis_run.return_value = None
        mock_db.get_documents.return_value = []  # no RFP / Source docs
        with self.assertRaises(svc.NoCorpusError):
            svc.start_fast_analysis(bid_id=1, api_key="fake")
        mock_db.create_analysis_run.assert_not_called()

    @patch("analysis_service.db")
    def test_documents_of_other_types_are_excluded_from_the_corpus(self, mock_db):
        mock_db.get_active_analysis_run.return_value = None
        mock_db.get_documents.return_value = [
            {"id": 1, "name": "x.pdf", "doc_type": "RFP / Source", "version": 1, "storage_path": "p"},
            {"id": 2, "name": "y.pdf", "doc_type": "Past Proposal", "version": 1, "storage_path": "p2"},
        ]
        mock_db.create_analysis_run.return_value = {"id": 1, "status": "QUEUED"}
        with patch("analysis_service.threading.Thread"):
            svc.start_fast_analysis(bid_id=1, api_key="fake")
        corpus_ids = mock_db.create_analysis_run.call_args[0][3]
        self.assertEqual(len(corpus_ids), 1)
        self.assertEqual(corpus_ids[0]["document_id"], 1)


class TestDuplicateStartProtection(unittest.TestCase):

    @patch("analysis_service.db")
    def test_active_run_blocks_a_new_start(self, mock_db):
        mock_db.get_active_analysis_run.return_value = {"id": 5, "status": "ANALYZING"}
        with self.assertRaises(svc.DuplicateAnalysisRunError):
            svc.start_fast_analysis(bid_id=1, api_key="fake")
        mock_db.create_analysis_run.assert_not_called()

    @patch("analysis_service.db")
    def test_race_lost_at_insert_still_raises_duplicate_error(self, mock_db):
        """The DB-level partial unique index is the real, atomic guard --
        confirm the service surfaces that as the same error type even when
        the pre-check above raced and missed it."""
        mock_db.get_active_analysis_run.side_effect = [None, {"id": 8, "status": "ANALYZING"}]
        mock_db.get_documents.return_value = _sample_docs()
        mock_db.create_analysis_run.return_value = None  # insert lost the unique-index race
        with self.assertRaises(svc.DuplicateAnalysisRunError) as ctx:
            svc.start_fast_analysis(bid_id=1, api_key="fake")
        self.assertEqual(ctx.exception.existing_run["id"], 8)

    @patch("analysis_service.db")
    def test_terminal_run_does_not_block_a_new_start(self, mock_db):
        """A COMPLETE or FAILED run is not 'active' -- get_active_analysis_run
        itself only returns non-terminal rows (see its own docstring/index
        definition); confirm the service trusts that and proceeds."""
        mock_db.get_active_analysis_run.return_value = None  # COMPLETE/FAILED runs excluded upstream
        mock_db.get_documents.return_value = _sample_docs()
        mock_db.create_analysis_run.return_value = {"id": 2, "status": "QUEUED"}
        with patch("analysis_service.threading.Thread") as mock_thread:
            run = svc.start_fast_analysis(bid_id=1, api_key="fake")
        self.assertEqual(run["id"], 2)
        mock_thread.assert_called_once()


class TestAnalysisLifecycleSuccess(unittest.TestCase):

    @patch("analysis_service.db")
    @patch("analysis_service.extract_document_with_metadata")
    @patch("analysis_service.run_fast_analysis_corpus")
    def test_successful_run_transitions_through_full_lifecycle(self, mock_run, mock_extract, mock_db):
        mock_db.download_file.return_value = b"fake pdf bytes"
        mock_extract.return_value = ("parsed document text", {})
        mock_run.return_value = _sample_fast_result()
        mock_db.upload_analysis_report.return_value = "1/analysis_reports/1.pdf"

        svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=_sample_docs(), api_key="fake")

        statuses = [call.args[1].get("status") for call in mock_db.update_analysis_run.call_args_list
                   if "status" in call.args[1]]
        self.assertEqual(statuses, ["PREPARING", "ANALYZING", "ASSEMBLING", "COMPLETE"])
        mock_run.assert_called_once()
        # Frozen V4 concurrency (instruction 2) -- must never change.
        self.assertEqual(mock_run.call_args.kwargs.get("max_document_concurrency"),
                         svc.MAX_DOCUMENT_CONCURRENCY)
        self.assertEqual(svc.MAX_DOCUMENT_CONCURRENCY, 2)

    @patch("analysis_service.db")
    @patch("analysis_service.extract_document_with_metadata")
    @patch("analysis_service.run_fast_analysis_corpus")
    def test_structured_result_and_fact_origins_are_persisted(self, mock_run, mock_extract, mock_db):
        mock_db.download_file.return_value = b"fake pdf bytes"
        mock_extract.return_value = ("parsed document text", {})
        mock_run.return_value = _sample_fast_result()
        mock_db.upload_analysis_report.return_value = "path.pdf"

        svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=_sample_docs(), api_key="fake")

        mock_db.create_analysis_result.assert_called_once()
        args, kwargs = mock_db.create_analysis_result.call_args
        self.assertEqual(args[0], 1)   # run_id
        self.assertEqual(args[1], 1)   # bid_id
        structured = args[2]
        self.assertIn("opportunity_snapshot", structured)
        self.assertIn("evaluation", structured)
        # Phase 5 live acceptance validation tightened category discovery to
        # require >=2 criteria per scope group -- _sample_fast_result()'s
        # single "Appendix D1" occurrence no longer substantiates a real
        # category on its own, so this lands under the flat-table key.
        self.assertIn("EVAL_WEIGHTS.flat", args[3] or {})  # fact_origins
        self.assertIsNotNone(kwargs.get("report_content_snapshot"))

    @patch("analysis_service.db")
    @patch("analysis_service.extract_document_with_metadata")
    @patch("analysis_service.run_fast_analysis_corpus")
    def test_bid_brief_projection_is_upserted_on_completion(self, mock_run, mock_extract, mock_db):
        mock_db.download_file.return_value = b"fake pdf bytes"
        mock_extract.return_value = ("parsed document text", {})
        mock_run.return_value = _sample_fast_result()
        mock_db.upload_analysis_report.return_value = "path.pdf"

        svc._execute_fast_analysis_run(run_id=1, bid_id=55, docs=_sample_docs(bid_id=55), api_key="fake")

        mock_db.upsert_bid_brief.assert_called_once()
        payload = mock_db.upsert_bid_brief.call_args[0][0]
        self.assertEqual(payload["bid_id"], 55)
        self.assertIn("executive_summary", payload)

    @patch("analysis_service.db")
    @patch("analysis_service.extract_document_with_metadata")
    @patch("analysis_service.run_fast_analysis_corpus")
    def test_telemetry_summary_has_no_invented_cost_figure(self, mock_run, mock_extract, mock_db):
        """Instruction 23: token usage only; never fabricate a dollar cost."""
        mock_db.download_file.return_value = b"fake pdf bytes"
        mock_extract.return_value = ("parsed document text", {})
        mock_run.return_value = _sample_fast_result()
        mock_db.upload_analysis_report.return_value = "path.pdf"

        svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=_sample_docs(), api_key="fake")

        complete_call = [c for c in mock_db.update_analysis_run.call_args_list
                         if c.args[1].get("status") == "COMPLETE"][0]
        telemetry = complete_call.args[1]["telemetry"]
        self.assertIn("input_tokens", telemetry)
        self.assertIn("output_tokens", telemetry)
        self.assertNotIn("cost_usd", telemetry)
        self.assertNotIn("cost", telemetry)
        self.assertEqual(telemetry["engine_version"], svc.FAST_ANALYSIS_ENGINE_VERSION)


class TestAnalysisLifecycleFailure(unittest.TestCase):

    @patch("analysis_service.db")
    @patch("analysis_service.run_fast_analysis_corpus")
    def test_engine_exception_marks_run_failed_not_stuck(self, mock_run, mock_db):
        mock_db.download_file.return_value = b"fake bytes"
        with patch("analysis_service.extract_document_with_metadata", return_value=("text", {})):
            mock_run.side_effect = RuntimeError("simulated engine failure")
            svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=_sample_docs(), api_key="fake")

        statuses = [call.args[1].get("status") for call in mock_db.update_analysis_run.call_args_list
                   if "status" in call.args[1]]
        self.assertIn("FAILED", statuses)
        self.assertNotIn("COMPLETE", statuses)
        failed_call = [c for c in mock_db.update_analysis_run.call_args_list
                      if c.args[1].get("status") == "FAILED"][0]
        self.assertIn("simulated engine failure", failed_call.args[1]["failure_reason"])
        self.assertIn("traceback", failed_call.args[1]["failure_detail"])

    @patch("analysis_service.db")
    def test_missing_storage_path_fails_cleanly_before_any_api_call(self, mock_db):
        docs = [{"id": 1, "name": "x.pdf", "doc_type": "RFP / Source", "storage_path": None}]
        svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=docs, api_key="fake")
        statuses = [call.args[1].get("status") for call in mock_db.update_analysis_run.call_args_list
                   if "status" in call.args[1]]
        self.assertEqual(statuses, ["PREPARING", "FAILED"])

    @patch("analysis_service.db")
    def test_download_failure_fails_cleanly(self, mock_db):
        mock_db.download_file.return_value = None
        svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=_sample_docs(), api_key="fake")
        statuses = [call.args[1].get("status") for call in mock_db.update_analysis_run.call_args_list
                   if "status" in call.args[1]]
        self.assertEqual(statuses, ["PREPARING", "FAILED"])

    @patch("analysis_service.db")
    @patch("analysis_service.extract_document_with_metadata")
    @patch("analysis_service.run_fast_analysis_corpus")
    def test_failure_does_not_persist_a_structured_result(self, mock_run, mock_extract, mock_db):
        """No misleading partial-COMPLETE result (instruction 19)."""
        mock_db.download_file.return_value = b"bytes"
        mock_extract.return_value = ("text", {})
        mock_run.side_effect = RuntimeError("boom")
        svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=_sample_docs(), api_key="fake")
        mock_db.create_analysis_result.assert_not_called()
        mock_db.upsert_bid_brief.assert_not_called()


class TestReportRegeneration(unittest.TestCase):

    @patch("analysis_service.db")
    @patch("analysis_service.run_fast_analysis_corpus")
    def test_regenerate_report_makes_zero_extraction_calls(self, mock_run, mock_db):
        from fast_analysis import FastAnalysisResult as FAR
        from scripts.fast_analysis_report_adapter import build_fast_report_content
        content = build_fast_report_content(FAR())
        snapshot = svc._content_to_dict(content)

        mock_db.get_analysis_run.return_value = {"id": 1, "status": "COMPLETE"}
        mock_db.get_analysis_result.return_value = {"report_content_snapshot": snapshot}

        pdf_bytes = svc.regenerate_report(run_id=1)

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        mock_run.assert_not_called()  # zero extraction calls (instruction 16/17)

    @patch("analysis_service.db")
    def test_regenerate_report_rejects_incomplete_run(self, mock_db):
        mock_db.get_analysis_run.return_value = {"id": 1, "status": "ANALYZING"}
        with self.assertRaises(ValueError):
            svc.regenerate_report(run_id=1)

    @patch("analysis_service.db")
    def test_regenerate_report_rejects_missing_snapshot(self, mock_db):
        mock_db.get_analysis_run.return_value = {"id": 1, "status": "COMPLETE"}
        mock_db.get_analysis_result.return_value = {"report_content_snapshot": None}
        with self.assertRaises(ValueError):
            svc.regenerate_report(run_id=1)


class TestCorpusSnapshotDeterminism(unittest.TestCase):

    def test_same_documents_produce_the_same_digest(self):
        docs = _sample_docs()
        ids_a, digest_a = svc._corpus_snapshot(docs)
        ids_b, digest_b = svc._corpus_snapshot(docs)
        self.assertEqual(digest_a, digest_b)

    def test_different_document_versions_produce_a_different_digest(self):
        docs_v1 = _sample_docs()
        docs_v2 = [{**docs_v1[0], "version": 2}]
        _, digest_v1 = svc._corpus_snapshot(docs_v1)
        _, digest_v2 = svc._corpus_snapshot(docs_v2)
        self.assertNotEqual(digest_v1, digest_v2)

    def test_document_order_does_not_affect_the_digest(self):
        a = {"id": 1, "version": 1, "name": "a.pdf"}
        b = {"id": 2, "version": 1, "name": "b.pdf"}
        _, digest_ab = svc._corpus_snapshot([a, b])
        _, digest_ba = svc._corpus_snapshot([b, a])
        self.assertEqual(digest_ab, digest_ba)


class TestStuckRunSafetyNet(unittest.TestCase):
    """Phase 2: bounded, user-initiated stuck-run safety net (instruction 20
    -- never automatic). is_run_stuck() is pure/read-only;
    mark_run_failed_as_stuck() is the only function that writes, and only
    when the caller explicitly invokes it."""

    def _iso(self, seconds_ago):
        return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()

    def test_terminal_runs_are_never_stuck_regardless_of_age(self):
        for status in ("COMPLETE", "FAILED"):
            run = {"status": status, "started_at": self._iso(999999)}
            self.assertFalse(svc.is_run_stuck(run))

    def test_recent_non_terminal_run_is_not_stuck(self):
        run = {"status": "ANALYZING", "started_at": self._iso(30)}
        self.assertFalse(svc.is_run_stuck(run))

    def test_non_terminal_run_past_threshold_is_stuck(self):
        run = {"status": "ANALYZING", "started_at": self._iso(svc.STUCK_RUN_THRESHOLD_SECONDS + 60)}
        self.assertTrue(svc.is_run_stuck(run))

    def test_falls_back_to_created_at_when_started_at_missing(self):
        run = {"status": "QUEUED", "created_at": self._iso(svc.STUCK_RUN_THRESHOLD_SECONDS + 60)}
        self.assertTrue(svc.is_run_stuck(run))

    def test_no_timestamp_at_all_is_not_stuck(self):
        """Never crash or guess -- an ambiguous/malformed run is simply not
        offered as stuck rather than raising or false-positiving."""
        self.assertFalse(svc.is_run_stuck({"status": "ANALYZING"}))

    def test_empty_or_none_run_is_not_stuck(self):
        self.assertFalse(svc.is_run_stuck(None))
        self.assertFalse(svc.is_run_stuck({}))

    @patch("analysis_service.db")
    def test_mark_run_failed_as_stuck_writes_failed_status(self, mock_db):
        mock_db.get_analysis_run.return_value = {"id": 5, "status": "ANALYZING"}
        svc.mark_run_failed_as_stuck(5)
        mock_db.update_analysis_run.assert_called_once()
        args, _ = mock_db.update_analysis_run.call_args
        self.assertEqual(args[0], 5)
        self.assertEqual(args[1]["status"], "FAILED")
        self.assertIn("failure_reason", args[1])
        self.assertTrue(args[1]["failure_detail"]["marked_stuck_by_user"])

    @patch("analysis_service.db")
    def test_mark_run_failed_as_stuck_refuses_a_terminal_run(self, mock_db):
        """Bounded (instruction 20): must not silently overwrite a run that
        already reached a real terminal outcome."""
        mock_db.get_analysis_run.return_value = {"id": 5, "status": "COMPLETE"}
        with self.assertRaises(ValueError):
            svc.mark_run_failed_as_stuck(5)
        mock_db.update_analysis_run.assert_not_called()


class TestMilestoneProgress(unittest.TestCase):
    """Phase 2: durable progress driven only by real Fast Analysis
    task-completion events (fast_analysis.py's on_task_done hook), never by
    elapsed time. No live API calls -- every db call is mocked and every
    task_result below is a synthetic dict shaped like what the engine's own
    dispatch loop already produces."""

    def test_eval_tasks_total_counts_identity_and_eval_only_documents(self):
        documents = [(GENERIC_RFP, "some text"), (D1_DOC, "some other text")]
        self.assertEqual(svc._compute_eval_tasks_total(documents), 2)

    def test_eval_tasks_total_is_zero_when_no_eval_contributing_documents(self):
        documents = [(APPENDIX_G, "commercial-only text")]
        self.assertEqual(svc._compute_eval_tasks_total(documents), 0)

    def test_eval_tasks_total_counts_a_focused_rated_criteria_section_separately(self):
        section_text = "Rated criteria\nCorporate Profile 5 points\n\n4.1 Next heading\n"
        documents = [(D1_DOC, section_text)]
        # 1 for the EVAL_ONLY single-document task + 1 for the focused
        # rated_criteria job located in the same document's own text.
        self.assertEqual(svc._compute_eval_tasks_total(documents), 2)

    def test_commercial_tasks_total(self):
        """Phase 5: a ROUTE_IDENTITY_EVAL_REQ document now also contributes
        one commercial-contributing task of its own (the additive
        'commercial_supplement' pass, fast_analysis.py step 2c) -- so a
        corpus with both a generic identity-routed document AND a
        dedicated commercial appendix has 2 commercial-contributing tasks,
        not 1."""
        documents = [(GENERIC_RFP, "x"), (APPENDIX_G, "y")]
        self.assertEqual(svc._compute_commercial_tasks_total(documents), 2)
        # A lone ROUTE_IDENTITY_EVAL_REQ document still contributes exactly
        # one (its own commercial_supplement pass) -- no longer 0.
        self.assertEqual(svc._compute_commercial_tasks_total([(GENERIC_RFP, "x")]), 1)
        # Only a genuinely non-commercial-contributing route (no identity
        # document, no dedicated commercial document at all) is still 0.
        self.assertEqual(svc._compute_commercial_tasks_total([(D1_DOC, "x")]), 0)

    @patch("analysis_service.db")
    def test_mark_is_idempotent(self, mock_db):
        tracker = svc._ProgressTracker(run_id=1, documents=[(GENERIC_RFP, "x")])
        tracker.mark(svc.MILESTONE_CORPUS_PREPARED)
        tracker.mark(svc.MILESTONE_CORPUS_PREPARED)
        self.assertEqual(len(tracker._milestones), 1)
        self.assertEqual(mock_db.update_analysis_run.call_count, 1)

    @patch("analysis_service.db")
    def test_mark_persists_progress_shape(self, mock_db):
        tracker = svc._ProgressTracker(run_id=42, documents=[(GENERIC_RFP, "x")])
        tracker.mark(svc.MILESTONE_CORPUS_PREPARED)
        args, _ = mock_db.update_analysis_run.call_args
        self.assertEqual(args[0], 42)
        progress = args[1]["progress"]
        self.assertEqual(len(progress["milestones"]), 1)
        self.assertEqual(progress["milestones"][0]["milestone"], svc.MILESTONE_CORPUS_PREPARED)
        self.assertIn("reached_at", progress["milestones"][0])
        self.assertEqual(progress["early_facts"], {})

    @patch("analysis_service.db")
    def test_set_early_facts_never_overwrites_with_a_falsy_value(self, mock_db):
        tracker = svc._ProgressTracker(run_id=1, documents=[(GENERIC_RFP, "x")])
        tracker.set_early_facts(title="Real Title")
        tracker.set_early_facts(title=None)
        tracker.set_early_facts(title="")
        self.assertEqual(tracker._early_facts["title"], "Real Title")

    @patch("analysis_service.db")
    def test_set_early_facts_only_persists_when_something_actually_changed(self, mock_db):
        tracker = svc._ProgressTracker(run_id=1, documents=[(GENERIC_RFP, "x")])
        tracker.set_early_facts(title=None)
        mock_db.update_analysis_run.assert_not_called()
        tracker.set_early_facts(title="Real Title")
        mock_db.update_analysis_run.assert_called_once()

    @patch("analysis_service.db")
    def test_identity_task_marks_opportunity_and_dates_and_sets_early_facts(self, mock_db):
        documents = [(GENERIC_RFP, "x")]
        tracker = svc._ProgressTracker(run_id=1, documents=documents)
        task_result = {GENERIC_RFP: {
            "doc_metadata": {"title": "Talent Services RFP", "client": "Bank of Canada",
                              "file_number": "2026-026", "submission_deadline": "2026-09-30",
                              "clarification_deadline": "2026-09-10"},
            "typed_observations": [{"family": "PROCUREMENT_MECHANIC", "semantic_kind": "RFP",
                                     "original_value": "Request for Proposal"}],
            "requirements": [{"category": "Rated", "description": "Category 1 scope"}],
            "evaluation_criteria": [{"stage": "Corporate Profile", "weight": "5 points"}],
        }}
        tracker.on_task_done("single", [GENERIC_RFP], task_result)
        self.assertIn(svc.MILESTONE_OPPORTUNITY_IDENTIFIED, tracker._reached)
        self.assertIn(svc.MILESTONE_DATES_READY, tracker._reached)
        self.assertIn(svc.MILESTONE_PROCUREMENT_STRUCTURE_READY, tracker._reached)
        self.assertIn(svc.MILESTONE_QUALIFICATION_READY, tracker._reached)
        self.assertEqual(tracker._early_facts["title"], "Talent Services RFP")
        self.assertEqual(tracker._early_facts["buyer"], "Bank of Canada")
        self.assertEqual(tracker._early_facts["submission_deadline"], "2026-09-30")
        self.assertEqual(tracker._early_facts["procurement_mechanic"], "Request for Proposal")
        # No fabricated "procurement/category structure" early fact -- see
        # the Phase 2 report for why that candidate was rejected.
        self.assertNotIn("service_categories", tracker._early_facts)

    @patch("analysis_service.db")
    def test_incomplete_identity_data_does_not_fabricate_milestones(self, mock_db):
        documents = [(GENERIC_RFP, "x")]
        tracker = svc._ProgressTracker(run_id=1, documents=documents)
        tracker.on_task_done("single", [GENERIC_RFP], {GENERIC_RFP: {"doc_metadata": {}}})
        self.assertNotIn(svc.MILESTONE_OPPORTUNITY_IDENTIFIED, tracker._reached)
        self.assertNotIn(svc.MILESTONE_DATES_READY, tracker._reached)
        self.assertEqual(tracker._early_facts, {})

    @patch("analysis_service.db")
    def test_commercial_ready_only_after_every_commercial_task_completes(self, mock_db):
        """Phase 5: COMMERCIAL_READY is a counter now (2 commercial-
        contributing tasks for this corpus -- the dedicated APPENDIX_G
        document and GENERIC_RFP's own additive commercial_supplement
        pass), matching how EVALUATION_READY already worked."""
        documents = [(GENERIC_RFP, "x"), (APPENDIX_G, "y")]
        tracker = svc._ProgressTracker(run_id=1, documents=documents)
        self.assertEqual(tracker._commercial_tasks_total, 2)
        tracker.on_task_done("single", [APPENDIX_G],
                             {APPENDIX_G: {"commercial_clauses": [{"clause_kind": "INSURANCE"}]}})
        self.assertNotIn(svc.MILESTONE_COMMERCIAL_READY, tracker._reached)
        tracker.on_task_done("commercial_supplement", [GENERIC_RFP],
                             {GENERIC_RFP: {"commercial_clauses": []}})
        self.assertIn(svc.MILESTONE_COMMERCIAL_READY, tracker._reached)

    @patch("analysis_service.db")
    def test_commercial_supplement_task_merges_no_other_fields(self, mock_db):
        """The commercial_supplement task must only ever move
        COMMERCIAL_READY's counter -- it must never mark identity/date/
        evaluation milestones or set early facts, even if its payload
        happens to carry them (it shouldn't, but this guards the
        boundary)."""
        documents = [(GENERIC_RFP, "x")]
        tracker = svc._ProgressTracker(run_id=1, documents=documents)
        tracker.on_task_done("commercial_supplement", [GENERIC_RFP],
                             {GENERIC_RFP: {"commercial_clauses": [{"clause_kind": "INSURANCE"}],
                                            "doc_metadata": {"title": "should be ignored"}}})
        self.assertNotIn(svc.MILESTONE_OPPORTUNITY_IDENTIFIED, tracker._reached)
        self.assertEqual(tracker._early_facts, {})

    @patch("analysis_service.db")
    def test_evaluation_ready_only_after_every_eval_task_completes(self, mock_db):
        documents = [(GENERIC_RFP, "x"), (D1_DOC, "y")]
        tracker = svc._ProgressTracker(run_id=1, documents=documents)
        self.assertEqual(tracker._eval_tasks_total, 2)
        tracker.on_task_done("single", [GENERIC_RFP], {GENERIC_RFP: {"doc_metadata": {}}})
        self.assertNotIn(svc.MILESTONE_EVALUATION_READY, tracker._reached)
        tracker.on_task_done("single", [D1_DOC], {D1_DOC: {"evaluation_criteria": []}})
        self.assertIn(svc.MILESTONE_EVALUATION_READY, tracker._reached)

    @patch("analysis_service.db")
    def test_batch_task_counts_as_exactly_one_eval_task(self, mock_db):
        from fast_analysis import BATCH_GROUP
        documents = [(GENERIC_RFP, "x")] + [(n, "y") for n in BATCH_GROUP]
        tracker = svc._ProgressTracker(run_id=1, documents=documents)
        self.assertEqual(tracker._eval_tasks_total, 2)  # identity task + 1 batch task
        tracker.on_task_done("batch", BATCH_GROUP, {n: {} for n in BATCH_GROUP})
        self.assertEqual(tracker._eval_tasks_done, 1)

    @patch("analysis_service.db")
    def test_focused_rated_criteria_task_counts_toward_evaluation_ready(self, mock_db):
        tracker = svc._ProgressTracker(run_id=1, documents=[(GENERIC_RFP, "x")])
        tracker._eval_tasks_total = 2  # simulate identity task + one focused job pending
        tracker.on_task_done("focused", (GENERIC_RFP, "rated_criteria", "section text"), [])
        self.assertEqual(tracker._eval_tasks_done, 1)
        self.assertNotIn(svc.MILESTONE_EVALUATION_READY, tracker._reached)

    @patch("analysis_service.db")
    def test_focused_pricing_stage_task_does_not_count_toward_evaluation_ready(self, mock_db):
        tracker = svc._ProgressTracker(run_id=1, documents=[(GENERIC_RFP, "x")])
        tracker.on_task_done("focused", (GENERIC_RFP, "pricing_stage", "section text"), [])
        self.assertEqual(tracker._eval_tasks_done, 0)

    @patch("analysis_service.db")
    def test_vacuous_milestones_reached_immediately_when_no_such_documents_exist(self, mock_db):
        """Phase 5: a ROUTE_IDENTITY_EVAL_REQ document now always
        contributes its own commercial_supplement task, so
        commercial_tasks_total is only genuinely 0 for a corpus with
        neither an identity-routed nor a dedicated commercial document at
        all (e.g. only EVAL_ONLY-routed appendices)."""
        documents = [(D1_DOC, "x")]  # ROUTE_EVAL_ONLY only -- no identity, no commercial document
        tracker = svc._ProgressTracker(run_id=1, documents=documents)
        self.assertEqual(tracker._commercial_tasks_total, 0)
        tracker.mark_vacuous_milestones()
        self.assertIn(svc.MILESTONE_COMMERCIAL_READY, tracker._reached)
        self.assertNotIn(svc.MILESTONE_EVALUATION_READY, tracker._reached)  # eval total > 0 here

    @patch("analysis_service.db")
    def test_a_bug_in_task_handling_never_raises_out_of_on_task_done(self, mock_db):
        """A milestone-mapping bug must never fail the underlying analysis."""
        tracker = svc._ProgressTracker(run_id=1, documents=[(GENERIC_RFP, "x")])
        tracker.on_task_done("single", None, None)
        tracker.on_task_done("single", [], "not-a-dict")

    @patch("analysis_service.db")
    @patch("analysis_service.extract_document_with_metadata")
    @patch("analysis_service.run_fast_analysis_corpus")
    def test_full_run_wires_the_observational_hook_and_persists_milestones(self, mock_run, mock_extract, mock_db):
        mock_db.download_file.return_value = b"fake pdf bytes"
        mock_extract.return_value = ("parsed document text", {})
        mock_run.return_value = _sample_fast_result()
        mock_db.upload_analysis_report.return_value = "path.pdf"

        svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=_sample_docs(), api_key="fake")

        self.assertIn("on_task_done", mock_run.call_args.kwargs)
        self.assertEqual(mock_run.call_args.kwargs.get("max_document_concurrency"),
                         svc.MAX_DOCUMENT_CONCURRENCY)  # Phase 2 didn't touch this (instruction 9)
        progress_calls = [c.args[1]["progress"] for c in mock_db.update_analysis_run.call_args_list
                         if "progress" in c.args[1]]
        self.assertTrue(progress_calls)
        reached = {m["milestone"] for m in progress_calls[-1]["milestones"]}
        self.assertIn(svc.MILESTONE_CORPUS_PREPARED, reached)
        self.assertIn(svc.MILESTONE_AMBIGUITIES_READY, reached)
        self.assertIn(svc.MILESTONE_REPORT_ASSEMBLED, reached)

    @patch("analysis_service.db")
    def test_refresh_does_not_create_duplicate_run_and_returns_same_active_run(self, mock_db):
        """Instruction 5: start -> active -> refresh/reconnect must resume
        the SAME run, never create another one. The DB-native unique index
        (idx_analysis_runs_one_active) remains the actual guard; this
        confirms the service layer honors it across repeated 'page loads.'"""
        active_run = {"id": 77, "status": "ANALYZING"}
        mock_db.get_active_analysis_run.return_value = active_run
        for _ in range(3):  # simulate 3 refreshes/reconnects while active
            with self.assertRaises(svc.DuplicateAnalysisRunError) as ctx:
                svc.start_fast_analysis(bid_id=1, api_key="fake")
            self.assertEqual(ctx.exception.existing_run["id"], 77)
        mock_db.create_analysis_run.assert_not_called()


class TestProgressTrackerHardening(unittest.TestCase):
    """Phase 2 final acceptance hardening: closes the one gap between the
    documented contract ('a bug in this tracker must never fail the
    underlying analysis') and what was actually guarded -- construction of
    _ProgressTracker itself sat outside every individually-defensive
    method. No live API calls."""

    @patch("analysis_service.db")
    def test_mark_never_raises_even_if_persist_is_broken(self, mock_db):
        mock_db.update_analysis_run.side_effect = RuntimeError("db is down")
        tracker = svc._ProgressTracker(run_id=1, documents=[(GENERIC_RFP, "x")])
        tracker.mark(svc.MILESTONE_CORPUS_PREPARED)  # must not raise
        self.assertIn(svc.MILESTONE_CORPUS_PREPARED, tracker._reached)

    @patch("analysis_service.db")
    def test_mark_never_raises_even_if_its_own_internal_state_is_corrupted(self, mock_db):
        tracker = svc._ProgressTracker(run_id=1, documents=[(GENERIC_RFP, "x")])
        tracker._milestones = None  # simulate a future internal bug
        tracker.mark(svc.MILESTONE_CORPUS_PREPARED)  # must not raise

    @patch("analysis_service.db")
    def test_set_early_facts_never_raises_even_if_persist_is_broken(self, mock_db):
        mock_db.update_analysis_run.side_effect = RuntimeError("db is down")
        tracker = svc._ProgressTracker(run_id=1, documents=[(GENERIC_RFP, "x")])
        tracker.set_early_facts(title="Real Title")  # must not raise
        self.assertEqual(tracker._early_facts.get("title"), "Real Title")

    def test_null_progress_tracker_every_method_is_a_safe_no_op(self):
        null = svc._NullProgressTracker()
        null.mark("ANYTHING")
        null.mark_vacuous_milestones()
        null.set_early_facts(title="x")
        null.on_task_done("single", ["x"], {"x": {}})  # none of these may raise

    @patch("analysis_service.db")
    @patch("analysis_service.extract_document_with_metadata")
    @patch("analysis_service.run_fast_analysis_corpus")
    @patch("analysis_service._ProgressTracker", side_effect=RuntimeError("simulated construction bug"))
    def test_a_broken_progress_tracker_constructor_does_not_fail_the_run(
            self, mock_tracker_cls, mock_run, mock_extract, mock_db):
        """The single remaining gap this hardening pass closes: even if
        _ProgressTracker.__init__ itself raises, the analysis must still
        reach COMPLETE, just with zero progress reporting."""
        mock_db.download_file.return_value = b"fake pdf bytes"
        mock_extract.return_value = ("parsed document text", {})
        mock_run.return_value = _sample_fast_result()
        mock_db.upload_analysis_report.return_value = "path.pdf"

        svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=_sample_docs(), api_key="fake")

        statuses = [call.args[1].get("status") for call in mock_db.update_analysis_run.call_args_list
                   if "status" in call.args[1]]
        self.assertEqual(statuses, ["PREPARING", "ANALYZING", "ASSEMBLING", "COMPLETE"])
        mock_db.create_analysis_result.assert_called_once()  # the actual analysis still fully persisted

    @patch("analysis_service.db")
    @patch("analysis_service.extract_document_with_metadata")
    @patch("analysis_service.run_fast_analysis_corpus")
    def test_progress_persisted_before_a_mid_run_failure_is_not_lost_or_corrupted(
            self, mock_run, mock_extract, mock_db):
        """A failure inside the engine call must still leave whatever
        progress was already persisted intact (CORPUS_PREPARED at minimum)
        -- failure handling must not retroactively wipe real progress."""
        mock_db.download_file.return_value = b"fake pdf bytes"
        mock_extract.return_value = ("parsed document text", {})
        mock_run.side_effect = RuntimeError("simulated engine failure")

        svc._execute_fast_analysis_run(run_id=1, bid_id=1, docs=_sample_docs(), api_key="fake")

        progress_calls = [c.args[1]["progress"] for c in mock_db.update_analysis_run.call_args_list
                         if "progress" in c.args[1]]
        self.assertTrue(progress_calls)
        reached = {m["milestone"] for m in progress_calls[-1]["milestones"]}
        self.assertIn(svc.MILESTONE_CORPUS_PREPARED, reached)
        statuses = [call.args[1].get("status") for call in mock_db.update_analysis_run.call_args_list
                   if "status" in call.args[1]]
        self.assertEqual(statuses[-1], "FAILED")


class TestFastDeepSeparationAndEngineVersion(unittest.TestCase):

    def test_engine_version_constant_is_stable(self):
        self.assertEqual(svc.FAST_ANALYSIS_ENGINE_VERSION, "fast-analysis-v4")

    def test_module_never_imports_deep_verify_entry_points(self):
        """Regression guard (instruction 18): this service boundary must
        never call Deep Verify's governed pipeline. Checks the module's
        actual bound names (not prose in comments/docstrings, which
        legitimately explain what this module deliberately does NOT do)."""
        for forbidden in ("extract_procurement_package", "extract_document_facts",
                          "extract_rfp", "opportunity_orchestration",
                          "orchestrate_opportunity_intelligence"):
            self.assertNotIn(forbidden, vars(svc),
                            f"analysis_service.py must not import/bind {forbidden}")

    @patch("analysis_service.db")
    def test_start_fast_analysis_always_persists_mode_fast(self, mock_db):
        mock_db.get_active_analysis_run.return_value = None
        mock_db.get_documents.return_value = _sample_docs()
        mock_db.create_analysis_run.return_value = {"id": 1, "status": "QUEUED"}
        with patch("analysis_service.threading.Thread"):
            svc.start_fast_analysis(bid_id=1, api_key="fake")
        self.assertEqual(mock_db.create_analysis_run.call_args[0][1], "FAST")


if __name__ == "__main__":
    unittest.main()
