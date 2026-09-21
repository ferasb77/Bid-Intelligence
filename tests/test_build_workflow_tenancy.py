"""
tests/test_build_workflow_tenancy.py -- PI-3D tenancy wiring for the
AI-assisted BUILD workflow (tenancy.get_build_intelligence_context_for_
organization / get_draft_existence_map_for_organization / the bulk
outline_section_requirements reader / the graceful-degradation behavior
when migrations/013_section_analyzer.sql is not yet live).

No live database, no live provider call -- mirrors tests/
test_section_drafting_tenancy.py's own mocking posture. Proves, via the
poisoned-function technique already used throughout this codebase, that
opening the BUILD workspace (this task's own instruction 12/instruction
11 test list) never calls Anthropic and never calls organizational_
memory.retrieve().
"""
from unittest.mock import patch

import pytest

import config
import database as db
import organizational_memory as om
import section_analyzer as sa
import tenancy


ORG_A = "11111111-1111-1111-1111-111111111111"
ORG_B = "22222222-2222-2222-2222-222222222222"


def _req(rid, category, req_id=None):
    return {"id": rid, "req_id": req_id or f"R{rid}", "category": category,
            "description": f"Requirement {rid}."}


class _Harness:
    def __init__(self):
        self.requirements = [_req(1, "Technical Approach", "R1"), _req(2, "Pricing", "R2")]
        self.run = {"id": 900}
        self.assessment_rows = [
            {"req_id": "R1", "assessment_status": "Fully Addressed", "evidence_strength": "STRONG"},
        ]
        self.raw_snapshot = None
        self.anthropic_calls = 0
        self.om_retrieve_calls = 0

    def _blow_up_anthropic(self, *a, **kw):
        self.anthropic_calls += 1
        raise AssertionError("config.execute_messages_create must never be called opening BUILD")

    def _blow_up_retrieve(self, *a, **kw):
        self.om_retrieve_calls += 1
        raise AssertionError("organizational_memory.retrieve() must never be called opening BUILD")

    def patches(self):
        return [
            patch.object(tenancy, "authorize_bid_access", return_value=True),
            patch.object(db, "get_requirements", side_effect=lambda bid_id: self.requirements),
            patch.object(db, "get_latest_usable_proposal_intelligence_run", side_effect=lambda bid_id: self.run),
            patch.object(db, "get_proposal_requirement_assessments", side_effect=lambda run_id: self.assessment_rows),
            patch.object(sa, "procurement_basis", return_value={
                "raw_snapshot": self.raw_snapshot, "procurement_truth_status": "GOVERNED",
            }),
            patch.object(config, "execute_messages_create", side_effect=self._blow_up_anthropic),
            patch.object(om, "retrieve", side_effect=self._blow_up_retrieve),
        ]

    def __enter__(self):
        self._patchers = self.patches()
        for p in self._patchers:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patchers):
            p.stop()


class TestGetBuildIntelligenceContext:

    def test_requires_bid_access(self):
        with patch.object(tenancy, "authorize_bid_access", return_value=False):
            with pytest.raises(tenancy.AccessDeniedError):
                tenancy.get_build_intelligence_context_for_organization(1, ORG_B)

    def test_never_calls_anthropic(self):
        with _Harness() as h:
            tenancy.get_build_intelligence_context_for_organization(1, ORG_A)
            assert h.anthropic_calls == 0

    def test_never_calls_organizational_memory_retrieve(self):
        with _Harness() as h:
            tenancy.get_build_intelligence_context_for_organization(1, ORG_A)
            assert h.om_retrieve_calls == 0

    def test_assessment_by_req_id_keyed_by_requirement_id(self):
        with _Harness() as h:
            ctx = tenancy.get_build_intelligence_context_for_organization(1, ORG_A)
            assert ctx["assessment_by_req_id"][1]["assessment_status"] == "Fully Addressed"
            assert 2 not in ctx["assessment_by_req_id"]

    def test_no_raw_snapshot_degrades_to_empty_criteria_never_raises(self):
        with _Harness() as h:
            h.raw_snapshot = None
            ctx = tenancy.get_build_intelligence_context_for_organization(1, ORG_A)
            assert ctx["advisory_intelligence_available"] is False
            assert ctx["criterion_by_req_id"] == {}
            assert ctx["page_limits"] == {}

    def test_no_proposal_intelligence_run_yields_empty_assessment_map(self):
        with _Harness() as h:
            h.run = None
            ctx = tenancy.get_build_intelligence_context_for_organization(1, ORG_A)
            assert ctx["assessment_by_req_id"] == {}


class TestGetDraftExistenceMap:

    def test_requires_bid_access(self):
        with patch.object(tenancy, "authorize_bid_access", return_value=False):
            with pytest.raises(tenancy.AccessDeniedError):
                tenancy.get_draft_existence_map_for_organization(1, ORG_B, [_req(1, "A")])

    def test_maps_true_when_a_draft_row_exists(self):
        with patch.object(tenancy, "authorize_bid_access", return_value=True), \
             patch.object(db, "get_section_drafts", side_effect=lambda bid_id, req_id: (
                 [{"id": 1}] if req_id == "R1" else [])):
            result = tenancy.get_draft_existence_map_for_organization(
                1, ORG_A, [_req(1, "A", "R1"), _req(2, "B", "R2")])
            assert result == {1: True, 2: False}

    def test_skips_requirements_without_id_or_req_id(self):
        with patch.object(tenancy, "authorize_bid_access", return_value=True), \
             patch.object(db, "get_section_drafts", return_value=[]):
            result = tenancy.get_draft_existence_map_for_organization(
                1, ORG_A, [{"id": None, "req_id": "R1"}, {"id": 5, "req_id": None}])
            assert result == {}


class TestSectionRequirementMappingGracefulDegradation:
    """migrations/013_section_analyzer.sql is written but NOT applied to
    any live database as of this task -- outline_section_requirements
    genuinely does not exist yet. These prove the BUILD workflow degrades
    (empty mapping / a clear typed exception) instead of crashing, both
    for the pre-existing per-section reader/writer and PI-3D's own new
    bulk reader."""

    def _missing_table_error(self):
        return Exception(
            "{'message': \"Could not find the table 'public.outline_section_requirements' "
            "in the schema cache\", 'code': 'PGRST205'}")

    def test_get_section_requirement_ids_degrades_to_empty_list(self):
        fake_client = type("C", (), {})()
        fake_table = type("T", (), {})()

        def _raise(*a, **kw):
            raise self._missing_table_error()

        fake_table.select = lambda *a, **kw: fake_table
        fake_table.eq = lambda *a, **kw: fake_table
        fake_table.execute = _raise
        fake_client.table = lambda name: fake_table
        with patch.object(tenancy.auth_client, "get_authenticated_client", return_value=fake_client):
            assert tenancy.get_section_requirement_ids_authenticated("tok", 1) == []

    def test_get_section_requirement_map_degrades_to_empty_dict(self):
        fake_client = type("C", (), {})()
        fake_table = type("T", (), {})()

        def _raise(*a, **kw):
            raise self._missing_table_error()

        fake_table.select = lambda *a, **kw: fake_table
        fake_table.eq = lambda *a, **kw: fake_table
        fake_table.execute = _raise
        fake_client.table = lambda name: fake_table
        with patch.object(tenancy.auth_client, "get_authenticated_client", return_value=fake_client):
            assert tenancy.get_section_requirement_map_authenticated("tok", 1) == {}

    def test_set_section_requirement_mapping_raises_typed_error(self):
        fake_client = type("C", (), {})()
        fake_table = type("T", (), {})()

        def _raise(*a, **kw):
            raise self._missing_table_error()

        fake_table.delete = lambda *a, **kw: fake_table
        fake_table.eq = lambda *a, **kw: fake_table
        fake_table.execute = _raise
        fake_client.table = lambda name: fake_table
        with patch.object(tenancy.auth_client, "get_authenticated_client", return_value=fake_client):
            with pytest.raises(tenancy.SectionMappingUnavailableError):
                tenancy.set_section_requirement_mapping_authenticated("tok", 1, 1, [1, 2])

    def test_other_errors_still_propagate(self):
        fake_client = type("C", (), {})()
        fake_table = type("T", (), {})()

        def _raise(*a, **kw):
            raise RuntimeError("a genuinely different failure")

        fake_table.select = lambda *a, **kw: fake_table
        fake_table.eq = lambda *a, **kw: fake_table
        fake_table.execute = _raise
        fake_client.table = lambda name: fake_table
        with patch.object(tenancy.auth_client, "get_authenticated_client", return_value=fake_client):
            with pytest.raises(RuntimeError):
                tenancy.get_section_requirement_ids_authenticated("tok", 1)
