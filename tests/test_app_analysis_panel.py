"""
tests/test_app_analysis_panel.py

Deterministic tests for the Product Integration Phase 2 active-run UX. This
panel (_should_poll, _render_milestone_checklist, _render_active_run_progress,
the @st.fragment-decorated _poll_active_analysis, _render_fast_analysis_panel,
_start_fast_analysis) lives in pages/stage_understand.py -- moved there from
app.py during Phase 3 commissioning after discovering app.py's router never
actually called the page (page_bid_overview) it was originally wired into,
making it unreachable through any real user path since Phase 1. See
BID_INTELLIGENCE_PRODUCT_INTEGRATION_PHASE3_COMMISSIONING_REPORT.md.

A fragment's body does not execute outside a real Streamlit script run
context, so the plain function it wraps (_render_active_run_progress) is
what's actually tested; the fragment itself is a thin, untested
pass-through. No live API calls; pages.stage_understand.get_latest_analysis_run
and every Streamlit call are mocked, same pattern as
tests/smoke/test_all_pages_runtime.py.
"""
import unittest
from unittest.mock import patch

import pages.stage_understand as understand
import analysis_service as svc


class TestShouldPoll(unittest.TestCase):
    """Instruction 6: polling stops at COMPLETE, stops at FAILED, and never
    starts for a run that doesn't exist yet."""

    def test_none_run_does_not_poll(self):
        self.assertFalse(understand._should_poll(None))

    def test_empty_dict_does_not_poll(self):
        self.assertFalse(understand._should_poll({}))

    def test_complete_run_does_not_poll(self):
        self.assertFalse(understand._should_poll({"status": "COMPLETE"}))

    def test_failed_run_does_not_poll(self):
        self.assertFalse(understand._should_poll({"status": "FAILED"}))

    def test_every_non_terminal_status_polls(self):
        for status in ("QUEUED", "PREPARING", "ANALYZING", "ASSEMBLING"):
            self.assertTrue(understand._should_poll({"status": status}), status)


class TestMilestoneVocabularyConsistency(unittest.TestCase):

    def test_every_milestone_in_order_has_a_ui_label(self):
        for milestone in svc.MILESTONE_ORDER:
            self.assertIn(milestone, svc.MILESTONE_UI_LABEL)

    def test_no_orphaned_ui_labels(self):
        self.assertEqual(set(svc.MILESTONE_ORDER), set(svc.MILESTONE_UI_LABEL.keys()))

    def test_ui_labels_contain_no_internal_route_or_task_names(self):
        """Instruction 4: no internal route/task vocabulary in user-facing
        copy (e.g. 'ROUTE_IDENTITY_EVAL_REQ', 'focused_rated_criteria')."""
        forbidden_substrings = ("ROUTE_", "focused_", "batch", "chunk", "task_result")
        for label in svc.MILESTONE_UI_LABEL.values():
            for bad in forbidden_substrings:
                self.assertNotIn(bad, label)


class TestMilestoneChecklistRendering(unittest.TestCase):

    @patch("streamlit.markdown")
    def test_renders_without_exception_for_a_fresh_run_with_no_progress_yet(self, mock_markdown):
        understand._render_milestone_checklist({"status": "PREPARING"})
        mock_markdown.assert_called()

    @patch("streamlit.markdown")
    def test_renders_without_exception_with_full_progress(self, mock_markdown):
        run = {
            "status": "ANALYZING",
            "progress": {
                "milestones": [{"milestone": m, "reached_at": "x"} for m in
                               (svc.MILESTONE_CORPUS_PREPARED, svc.MILESTONE_OPPORTUNITY_IDENTIFIED)],
                "early_facts": {"title": "Talent Services RFP", "buyer": "Bank of Canada",
                                "submission_deadline": "2026-09-30",
                                "procurement_mechanic": "Request for Proposal"},
            },
        }
        understand._render_milestone_checklist(run)
        mock_markdown.assert_called()
        # The "what we know so far" box should have been rendered too.
        rendered = " ".join(str(c.args[0]) for c in mock_markdown.call_args_list)
        self.assertIn("Talent Services RFP", rendered)
        self.assertIn("What we know so far", rendered)

    @patch("streamlit.markdown")
    def test_no_early_facts_box_when_nothing_is_known_yet(self, mock_markdown):
        understand._render_milestone_checklist({"status": "ANALYZING", "progress": {}})
        rendered = " ".join(str(c.args[0]) for c in mock_markdown.call_args_list)
        self.assertNotIn("What we know so far", rendered)

    @patch("streamlit.markdown")
    def test_reached_milestones_get_a_checkmark_and_unreached_get_an_hourglass(self, mock_markdown):
        run = {"status": "ANALYZING", "progress": {
            "milestones": [{"milestone": svc.MILESTONE_CORPUS_PREPARED, "reached_at": "x"}],
        }}
        understand._render_milestone_checklist(run)
        rendered = " ".join(str(c.args[0]) for c in mock_markdown.call_args_list)
        self.assertIn("✅", rendered)
        self.assertIn("⏳", rendered)


class TestActiveRunProgressRendering(unittest.TestCase):
    """Instruction 2/5/6: each call re-fetches DB-truthful state and stops
    polling (via a full rerun) the moment the run is no longer non-terminal
    -- it never renders progress from anything other than what the database
    currently says. In production this logic runs inside the
    @st.fragment(run_every=...) -decorated _poll_active_analysis, so a real
    run re-executes it automatically every ANALYSIS_POLL_INTERVAL_SECONDS."""

    @patch("streamlit.button", return_value=False)
    @patch("streamlit.markdown")
    @patch("pages.stage_understand.get_latest_analysis_run")
    def test_renders_progress_for_an_active_run_without_exception(self, mock_get_run, mock_markdown, mock_button):
        mock_get_run.return_value = {
            "id": 5, "status": "ANALYZING", "started_at": "2026-09-14T10:00:00+00:00",
            "progress": {"milestones": [{"milestone": svc.MILESTONE_CORPUS_PREPARED, "reached_at": "x"}],
                        "early_facts": {}},
        }
        understand._render_active_run_progress(1)
        mock_markdown.assert_called()

    @patch("streamlit.rerun")
    @patch("streamlit.markdown")
    @patch("pages.stage_understand.get_latest_analysis_run")
    def test_triggers_a_full_rerun_once_the_run_becomes_complete(self, mock_get_run, mock_markdown, mock_rerun):
        mock_get_run.return_value = {"id": 5, "status": "COMPLETE"}
        understand._render_active_run_progress(1)
        mock_rerun.assert_called_once()

    @patch("streamlit.rerun")
    @patch("streamlit.markdown")
    @patch("pages.stage_understand.get_latest_analysis_run")
    def test_triggers_a_full_rerun_once_the_run_becomes_failed(self, mock_get_run, mock_markdown, mock_rerun):
        mock_get_run.return_value = {"id": 5, "status": "FAILED", "failure_reason": "boom"}
        understand._render_active_run_progress(1)
        mock_rerun.assert_called_once()

    @patch("streamlit.button", return_value=False)
    @patch("streamlit.markdown")
    @patch("pages.stage_understand.get_latest_analysis_run")
    @patch("analysis_service.is_run_stuck", return_value=True)
    def test_offers_the_stuck_run_action_when_is_run_stuck_is_true(self, mock_stuck, mock_get_run,
                                                                    mock_markdown, mock_button):
        mock_get_run.return_value = {"id": 5, "status": "ANALYZING", "started_at": "x", "progress": {}}
        understand._render_active_run_progress(1)
        rendered = " ".join(str(c.args[0]) for c in mock_markdown.call_args_list)
        self.assertIn("may be stuck", rendered)


class TestFastAnalysisPanelReachability(unittest.TestCase):
    """Phase 3 commissioning regression guard: the exact defect found was
    that _render_fast_analysis_panel was wired into a page app.py's router
    never calls. Confirm it is now reachable both directly (moved into
    stage_understand.py) and via page_understand()'s actual call to it."""

    def test_render_fast_analysis_panel_lives_in_stage_understand(self):
        self.assertTrue(hasattr(understand, "_render_fast_analysis_panel"))
        self.assertTrue(hasattr(understand, "_start_fast_analysis"))

    @patch("streamlit.markdown")
    @patch("streamlit.expander")
    @patch("streamlit.button", return_value=False)
    @patch("streamlit.columns", side_effect=lambda spec, *a, **k: [unittest.mock.MagicMock()
                                                                     for _ in range(spec if isinstance(spec, int) else len(spec))])
    @patch("pages.stage_understand.get_latest_analysis_result", return_value=None)
    @patch("pages.stage_understand.get_latest_analysis_run", return_value=None)
    @patch("pages.stage_understand.get_documents")
    @patch("pages.stage_understand.get_requirements", return_value=[])
    @patch("pages.stage_understand.get_bid_brief", return_value={})
    @patch("pages.stage_understand.get_bid")
    def test_page_understand_actually_calls_the_fast_analysis_panel(
            self, mock_get_bid, mock_get_brief, mock_get_reqs, mock_get_docs,
            mock_get_run, mock_get_result, mock_columns, mock_button, mock_expander, mock_markdown):
        mock_get_bid.return_value = {
            "id": 1, "client": "Test Buyer", "title": "Test RFP", "stage": "Identified",
            "sensitivity": "Standard", "submission_deadline": None, "clarification_deadline": None,
            "value_cad": None, "owner": None,
        }
        mock_get_docs.return_value = [
            {"id": 1, "name": "rfp.pdf", "doc_type": "RFP / Source", "storage_path": "1/x.pdf", "version": 1},
        ]
        mock_expander.return_value.__enter__.return_value = unittest.mock.MagicMock()
        mock_expander.return_value.__exit__.return_value = False

        understand.page_understand(1)

        rendered = " ".join(str(c.args[0]) for c in mock_markdown.call_args_list if c.args)
        self.assertIn("Fast Analysis", rendered)


if __name__ == "__main__":
    unittest.main()
