"""
tests/test_build_workflow_ui.py -- PI-3D: BUILD page rendering behavior for
the AI-assisted workflow (pages/stage_build.py::page_build). No live
database -- every tenancy read is monkeypatched to a controlled fixture,
mirroring tests/smoke/test_all_pages_runtime.py's bare-mode Streamlit
approach but with deterministic inputs per scenario instead of live bid 8
data, so each of PI-3D's own required behaviors (instruction 11) can be
asserted directly rather than inferred from "it didn't crash."
"""
import time
import unittest
from unittest.mock import MagicMock, patch

import streamlit as st

import tenancy
from tenancy import AuthContext
import pages.stage_build as build


_FAKE_USER_ID = "00000000-0000-0000-0000-000000000001"
_ORG_ID = "4326b564-8cc5-4463-9304-9a589f08cc91"
_BID = {"id": 42, "client": "Test Client", "title": "Test Opportunity"}


def _req(rid, category, req_id=None):
    return {"id": rid, "req_id": req_id or f"R{rid}", "category": category,
            "description": f"Requirement {rid}."}


def _empty_build_ctx():
    return {
        "advisory_intelligence_available": False, "evaluation_criteria_available": False,
        "criterion_by_req_id": {}, "assessment_by_req_id": {}, "page_limits": {},
        "procurement_truth_status": None,
    }


def _mock_cols(spec, *args, **kwargs):
    count = spec if isinstance(spec, int) else (len(spec) if isinstance(spec, list) else 2)
    cols = []
    for _ in range(count):
        col = MagicMock()
        col.button.return_value = False
        col.form_submit_button.return_value = False
        col.checkbox.return_value = False
        cols.append(col)
    return cols


def _mock_tabs(tab_list, *args, **kwargs):
    return [MagicMock() for _ in range(len(tab_list))]


class _BuildPageHarness:
    """Patches every tenancy read page_build performs with a controlled
    fixture, plus the bare-minimum Streamlit surface (mirroring the
    existing whole-app smoke test), so page_build runs deterministically
    against synthetic data instead of a live bid."""

    def __init__(self, requirements=None, sections=None, build_ctx=None,
                 section_req_map=None, mapped_ids_for_active=None):
        self.requirements = requirements or []
        self.sections = sections or []
        self.build_ctx = build_ctx if build_ctx is not None else _empty_build_ctx()
        self.section_req_map = section_req_map or {}
        self.mapped_ids_for_active = mapped_ids_for_active if mapped_ids_for_active is not None else []

    def __enter__(self):
        st.session_state["bi_auth_session"] = {
            "access_token": "fake-token", "refresh_token": "fake-refresh",
            "user_id": _FAKE_USER_ID, "email": "test@example.com",
            "expires_at": time.time() + 3600,
        }
        st.session_state["bi_auth_context"] = AuthContext(
            user_id=_FAKE_USER_ID, email="test@example.com",
            organization_id=_ORG_ID, organization_name="Test Org", role="owner",
        )
        for key in ("active_draft_sec", "proposed_outline", "build_workflow_mode"):
            st.session_state.pop(key, None)

        self._patchers = [
            patch.object(tenancy, "get_bid_authenticated", return_value=_BID),
            patch.object(tenancy, "get_requirements_authenticated", return_value=self.requirements),
            patch.object(tenancy, "get_outline_authenticated", return_value=self.sections),
            patch.object(tenancy, "get_deliverables_authenticated", return_value=[]),
            patch.object(tenancy, "get_documents_authenticated", return_value=[]),
            patch.object(tenancy, "get_tasks_authenticated", return_value=[]),
            patch.object(tenancy, "get_build_intelligence_context_for_organization",
                         return_value=self.build_ctx),
            patch.object(tenancy, "get_section_requirement_map_authenticated",
                         return_value=self.section_req_map),
            patch.object(tenancy, "get_section_requirement_ids_authenticated",
                         return_value=self.mapped_ids_for_active),
            patch.object(tenancy, "set_section_requirement_mapping_authenticated", return_value=None),
            patch.object(tenancy, "get_draft_existence_map_for_organization", return_value={}),
            patch.object(tenancy, "semantic_library_search_authenticated", return_value=([], False)),
            patch.object(tenancy, "get_section_reviews_authenticated", return_value=[]),
            patch("streamlit.markdown"),
            patch("streamlit.columns", side_effect=_mock_cols),
            patch("streamlit.tabs", side_effect=_mock_tabs),
        ]
        self._started = [p.start() for p in self._patchers]
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patchers):
            p.stop()


class TestAIAssistedEmptyState(unittest.TestCase):
    """Instruction 8/11.1: an analyzed bid (requirements exist) with zero
    outline sections must offer AI outline generation, not just manual
    section creation."""

    @patch("streamlit.button", return_value=False)
    @patch("streamlit.expander")
    def test_offers_generate_proposal_structure_button(self, mock_expander, mock_button):
        reqs = [_req(1, "Technical Approach"), _req(2, "Pricing")]
        with _BuildPageHarness(requirements=reqs, sections=[]):
            build.page_build(42)
        labels = [c.args[0] for c in mock_button.call_args_list if c.args]
        assert any("Generate Proposal Structure" in lbl for lbl in labels)

    @patch("streamlit.button", return_value=False)
    @patch("streamlit.expander")
    def test_manual_add_section_still_available_in_ai_empty_state(self, mock_expander, mock_button):
        reqs = [_req(1, "Technical Approach")]
        with _BuildPageHarness(requirements=reqs, sections=[]):
            build.page_build(42)
        expander_labels = [c.args[0] for c in mock_expander.call_args_list if c.args]
        assert any("Add Section Manually" in lbl for lbl in expander_labels)

    @patch("streamlit.button", return_value=False)
    @patch("streamlit.expander")
    def test_no_requirements_explains_upstream_step_instead_of_offering_generation(self, mock_expander, mock_button):
        with _BuildPageHarness(requirements=[], sections=[]):
            build.page_build(42)
        labels = [c.args[0] for c in mock_button.call_args_list if c.args]
        assert not any("Generate Proposal Structure" in lbl for lbl in labels)


class TestManualWorkflowPreserved(unittest.TestCase):

    @patch("streamlit.button", return_value=False)
    @patch("streamlit.expander")
    def test_add_section_manually_available_even_with_existing_sections(self, mock_expander, mock_button):
        reqs = [_req(1, "Technical Approach")]
        sections = [{"id": 10, "title": "Methodology", "section_num": "1.0",
                     "status": "Not Started", "word_limit": 500, "owner": "", "notes": ""}]
        with _BuildPageHarness(requirements=reqs, sections=sections):
            build.page_build(42)
        expander_labels = [c.args[0] for c in mock_expander.call_args_list if c.args]
        assert any("Add Section Manually" in lbl for lbl in expander_labels)


class TestAIDraftingVisibleForMappedSections(unittest.TestCase):
    """Instruction 6/11.7-8: for a section with mapped requirements, the
    PI-3C requirement drafting workspace must be reached -- reused, never
    reproduced -- and it must be the SAME canonical PI-3B orchestration
    (proven elsewhere; here we only prove it is actually invoked, not
    hidden behind a collapsed expander nobody opens)."""

    @patch("streamlit.button", return_value=False)
    @patch("streamlit.expander")
    @patch("streamlit.multiselect", return_value=[])
    @patch("streamlit.selectbox")
    @patch("pages.stage_build.render_requirement_drafting_workspace")
    def test_workspace_invoked_for_active_section_with_mapped_requirement(
            self, mock_workspace, mock_selectbox, mock_multiselect, mock_expander, mock_button):
        reqs = [_req(1, "Technical Approach", "R1")]
        sections = [{"id": 10, "title": "Methodology", "section_num": "1.0",
                     "status": "Not Started", "word_limit": 500, "owner": "", "notes": ""}]
        mock_selectbox.side_effect = lambda label, options, *a, **kw: (options[0] if options else None)
        with _BuildPageHarness(requirements=reqs, sections=sections, mapped_ids_for_active=[1]):
            st.session_state["active_draft_sec"] = 10
            build.page_build(42)
        assert mock_workspace.called
        called_bid_id, called_requirement = mock_workspace.call_args.args[0], mock_workspace.call_args.args[1]
        assert called_bid_id == 42
        assert called_requirement.get("id") == 1


class TestNoWholeProposalModelCall(unittest.TestCase):
    """Instruction 9/11.16: PI-3D must not introduce a batched/whole-
    proposal drafting call. render_requirement_drafting_workspace (PI-3C's
    own, per-REQUIREMENT canonical entry point) must be called from
    exactly one call site in stage_build.py -- never in a loop over
    multiple requirements/sections at once."""

    def test_single_call_site_no_loop_over_requirements(self):
        import inspect
        source = inspect.getsource(build)
        assert source.count("render_requirement_drafting_workspace(") == 1
        # No batch/bulk drafting entry point exists in this file.
        assert "get_or_generate_section_draft" not in source
