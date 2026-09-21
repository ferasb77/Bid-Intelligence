"""
tests/test_section_drafting_workspace.py

PI-3C: Section Drafting Workspace -- tenancy-layer tests for the read-only
status function the workspace UI calls on every render
(tenancy.get_section_draft_status_for_organization). No live database, no
live provider call -- mirrors tests/test_section_drafts_persistence.py's
harness.
"""
from unittest.mock import patch

import pytest

import database as db
import organizational_memory as om
import section_analyzer as sa
import section_drafting as sd
import tenancy


ORG_A = "11111111-1111-1111-1111-111111111111"


class _FakeDraftStore:
    def __init__(self):
        self.rows: list[dict] = []
        self._next_id = 1

    def history(self, bid_id, req_id):
        return [r for r in self.rows if r["bid_id"] == bid_id and r["req_id"] == req_id]

    def get_or_create(self, *, bid_id, req_id, input_fingerprint, contract_version,
                       draft_text, assurance_passed, requirement_id=None,
                       requirements_addressed=None, requirements_missing=None,
                       evaluation_criteria_addressed=None, evidence_items_used=None,
                       unsupported_or_unresolved_points=None, contradictions_or_caveats=None,
                       human_confirmation_required=True, drafting_notes=None, word_count=None,
                       assurance_issues=None, material_claims=None, created_by_user_id=None):
        for row in self.rows:
            if (row["bid_id"] == bid_id and row["req_id"] == req_id
                    and row["input_fingerprint"] == input_fingerprint):
                return row
        row = {
            "id": self._next_id, "bid_id": bid_id, "req_id": req_id,
            "requirement_id": requirement_id, "contract_version": contract_version,
            "input_fingerprint": input_fingerprint, "draft_text": draft_text,
            "requirements_addressed": requirements_addressed or [],
            "requirements_missing": requirements_missing or [],
            "evaluation_criteria_addressed": evaluation_criteria_addressed or [],
            "evidence_items_used": evidence_items_used or [],
            "unsupported_or_unresolved_points": unsupported_or_unresolved_points or [],
            "contradictions_or_caveats": contradictions_or_caveats or [],
            "human_confirmation_required": human_confirmation_required,
            "drafting_notes": drafting_notes, "word_count": word_count,
            "assurance_passed": assurance_passed, "assurance_issues": assurance_issues or [],
            "material_claims": material_claims or [],
            "created_by_user_id": created_by_user_id,
            "created_at": f"2026-01-01T00:00:{self._next_id:02d}+00:00",
        }
        self._next_id += 1
        self.rows.append(row)
        return row


def _mock_draft(prompt, *, bid_id, max_tokens=2000):
    return ({"draft_text": "drafted text", "requirements_addressed": ["R-1"]}, None)


class _Harness:
    def __init__(self):
        self.store = _FakeDraftStore()
        self.requirement = {"id": 501, "req_id": "R-1", "category": "Qualifications",
                             "description": "Vendor must demonstrate coaching experience.",
                             "source_refs": []}
        self.other_requirements = []
        self.run = None
        self.assessment_rows = []
        self.finding_rows = []
        self.enrichment_history = []
        self.draft_calls = 0
        self.retrieve_calls = 0

    def _draft_fn(self, prompt, *, bid_id, max_tokens=2000):
        self.draft_calls += 1
        return _mock_draft(prompt, bid_id=bid_id, max_tokens=max_tokens)

    def _blow_up_retrieve(self, *a, **kw):
        self.retrieve_calls += 1
        raise AssertionError("organizational_memory.retrieve() must never be called by the status check")

    def patches(self):
        return [
            patch.object(tenancy, "authorize_bid_access", return_value=True),
            patch.object(db, "get_requirements_by_ids",
                         side_effect=lambda bid_id, ids: [self.requirement] if ids == [501] else []),
            patch.object(db, "get_requirements", side_effect=lambda bid_id: self.other_requirements),
            patch.object(db, "get_latest_usable_proposal_intelligence_run", side_effect=lambda bid_id: self.run),
            patch.object(db, "get_proposal_requirement_assessments", side_effect=lambda run_id: self.assessment_rows),
            patch.object(db, "get_proposal_intelligence_findings", side_effect=lambda run_id: self.finding_rows),
            patch.object(db, "get_requirement_evidence_enrichments",
                         side_effect=lambda bid_id, req_id: self.enrichment_history),
            patch.object(sa, "procurement_basis", return_value={"raw_snapshot": None}),
            patch.object(db, "get_section_drafts", side_effect=self.store.history),
            patch.object(db, "get_or_create_section_draft", side_effect=self.store.get_or_create),
            patch.object(sd, "_call_section_draft", side_effect=self._draft_fn),
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


def _status(h: _Harness, bid_id=1, requirement_id=501):
    return tenancy.get_section_draft_status_for_organization(
        bid_id=bid_id, organization_id=ORG_A, requirement_id=requirement_id)


def _generate(h: _Harness, bid_id=1, requirement_id=501):
    return tenancy.get_or_generate_section_draft(
        bid_id=bid_id, organization_id=ORG_A, requirement_id=requirement_id)


class TestNoDraftYet:

    def test_status_reports_no_latest_draft(self):
        with _Harness() as h:
            status = _status(h)
        assert status["latest_draft"] is None
        assert status["is_stale"] is False
        assert status["is_current"] is False
        assert status["history_count"] == 0
        assert status["history"] == []

    def test_status_never_calls_the_drafting_model(self):
        with _Harness() as h:
            _status(h)
            assert h.draft_calls == 0

    def test_status_never_calls_organizational_memory_retrieve(self):
        with _Harness() as h:
            _status(h)
            assert h.retrieve_calls == 0


class TestCurrentDraft:

    def test_status_is_current_immediately_after_generation(self):
        with _Harness() as h:
            _generate(h)
            status = _status(h)
        assert status["latest_draft"] is not None
        assert status["is_current"] is True
        assert status["is_stale"] is False
        assert status["history_count"] == 1

    def test_status_check_after_generation_makes_no_new_model_call(self):
        with _Harness() as h:
            _generate(h)
            assert h.draft_calls == 1
            _status(h)
            assert h.draft_calls == 1

    def test_status_check_never_writes_a_new_row(self):
        with _Harness() as h:
            _generate(h)
            assert len(h.store.rows) == 1
            _status(h)
            assert len(h.store.rows) == 1


class TestStaleDraft:

    def test_status_detects_staleness_after_requirement_change(self):
        with _Harness() as h:
            _generate(h)
            h.requirement = dict(h.requirement, description="A completely different requirement text.")
            status = _status(h)
        assert status["latest_draft"] is not None   # old draft still shown
        assert status["is_stale"] is True
        assert status["is_current"] is False

    def test_stale_status_check_does_not_auto_regenerate(self):
        with _Harness() as h:
            _generate(h)
            assert h.draft_calls == 1
            h.requirement = dict(h.requirement, description="A completely different requirement text.")
            _status(h)
            # The status check itself must NEVER trigger a new model call
            # or a new persisted row merely because it detected staleness.
            assert h.draft_calls == 1
            assert len(h.store.rows) == 1

    def test_stale_draft_still_shows_the_prior_immutable_version(self):
        with _Harness() as h:
            first = _generate(h)
            h.requirement = dict(h.requirement, description="A completely different requirement text.")
            status = _status(h)
        assert status["latest_draft"]["draft_text"] == first["result"]["draft_text"]


class TestIsolation:

    def test_requires_bid_access_before_any_read(self):
        with _Harness() as h:
            with patch.object(tenancy, "authorize_bid_access", return_value=False):
                with pytest.raises(tenancy.AccessDeniedError):
                    _status(h)

    def test_missing_requirement_raises(self):
        with _Harness() as h:
            with pytest.raises(ValueError):
                _status(h, requirement_id=999999)

    def test_history_is_bid_scoped(self):
        with _Harness() as h:
            _generate(h, bid_id=1)
        assert h.store.history(1, "R-1")
        assert h.store.history(2, "R-1") == []
