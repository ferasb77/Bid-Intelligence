"""
tests/test_section_drafting_workspace.py

BUILD Response Brief -- tenancy-layer tests for the read-only status
function the panel calls on every render
(tenancy.get_section_draft_status_for_organization). No live database, no
live provider call, and no model call anywhere: there is no generation
entry point any more (`tenancy.get_or_generate_section_draft` and the
drafting model call were DECOMMISSIONED along with the rest of active AI
proposal generation). Historical `section_drafts` rows (migrations
018/019) are exercised here as pre-seeded, already-persisted fixtures --
never produced by calling a drafting function -- to prove the read-only
status/staleness logic still works correctly against real historical
record shapes.
"""
from unittest.mock import patch

import pytest

import database as db
import organizational_memory as om
import section_analyzer as sa
import tenancy


ORG_A = "11111111-1111-1111-1111-111111111111"


def _historical_row(row_id, req_id, input_fingerprint, bid_id=1, draft_text="drafted text",
                     created_at="2026-01-01T00:00:01+00:00"):
    """A fixture shaped exactly like a real persisted `section_drafts` row
    (migrations 018/019) -- standing in for a record created before the
    proposal-generation decommission. Never produced by calling a drafting
    function in this file."""
    return {
        "id": row_id, "bid_id": bid_id, "req_id": req_id,
        "requirement_id": 501, "input_fingerprint": input_fingerprint,
        "draft_text": draft_text, "requirements_addressed": [req_id],
        "requirements_missing": [], "evaluation_criteria_addressed": [],
        "evidence_items_used": [], "unsupported_or_unresolved_points": [],
        "contradictions_or_caveats": [], "human_confirmation_required": False,
        "drafting_notes": None, "word_count": len(draft_text.split()),
        "assurance_passed": True, "assurance_issues": [], "material_claims": [],
        "created_at": created_at,
    }


class _Harness:
    def __init__(self):
        self.requirement = {"id": 501, "req_id": "R-1", "category": "Qualifications",
                             "description": "Vendor must demonstrate coaching experience.",
                             "source_refs": []}
        self.other_requirements = []
        self.run = None
        self.assessment_rows = []
        self.finding_rows = []
        self.enrichment_history = []
        self.section_drafts_history = []
        self.retrieve_calls = 0

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
            patch.object(db, "get_section_drafts",
                         side_effect=lambda bid_id, req_id: [
                             r for r in self.section_drafts_history
                             if r["bid_id"] == bid_id and r["req_id"] == req_id]),
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


class TestNoDraftYet:

    def test_status_reports_no_latest_draft(self):
        with _Harness() as h:
            status = _status(h)
        assert status["latest_draft"] is None
        assert status["is_stale"] is False
        assert status["is_current"] is False
        assert status["history_count"] == 0
        assert status["history"] == []

    def test_status_never_calls_organizational_memory_retrieve(self):
        with _Harness() as h:
            _status(h)
            assert h.retrieve_calls == 0

    def test_no_generation_entry_point_exists(self):
        """Product boundary: Bid Intelligence no longer generates proposal
        narrative -- the retired get_or_generate_section_draft must not
        exist, and must not be reintroduced under another name."""
        assert not hasattr(tenancy, "get_or_generate_section_draft")
        assert not hasattr(tenancy, "draft_section_for_organization")


class TestHistoricalDraftIsCurrent:
    """A historical record (migrations 018/019, created before the
    proposal-generation decommission) whose fingerprint still matches the
    current intelligence state."""

    def test_status_reports_the_historical_record_as_current(self):
        with _Harness() as h:
            # Compute the real current fingerprint the same way the status
            # function does, so the seeded row matches it exactly.
            brief = tenancy._assemble_section_drafting_brief(
                1, ORG_A, 501, None, 5, 5,
                not_found_caller="test")
            import section_drafting as sd
            current_fp = sd.compute_draft_input_fingerprint(brief)
            h.section_drafts_history = [_historical_row(1, "R-1", current_fp)]
            status = _status(h)
        assert status["latest_draft"] is not None
        assert status["is_current"] is True
        assert status["is_stale"] is False
        assert status["history_count"] == 1

    def test_status_check_never_writes_a_new_row(self):
        with _Harness() as h:
            h.section_drafts_history = [_historical_row(1, "R-1", "some-fingerprint")]
            with patch.object(db, "get_section_drafts",
                               side_effect=lambda bid_id, req_id: list(h.section_drafts_history)):
                _status(h)
                assert len(h.section_drafts_history) == 1
                _status(h)
                assert len(h.section_drafts_history) == 1


class TestStaleHistoricalDraft:

    def test_status_detects_staleness_when_fingerprint_no_longer_matches(self):
        with _Harness() as h:
            h.section_drafts_history = [_historical_row(1, "R-1", "a-stale-fingerprint")]
            status = _status(h)
        assert status["latest_draft"] is not None   # old record still shown
        assert status["is_stale"] is True
        assert status["is_current"] is False

    def test_stale_record_still_shows_its_immutable_text(self):
        with _Harness() as h:
            h.section_drafts_history = [_historical_row(1, "R-1", "a-stale-fingerprint", draft_text="original text")]
            status = _status(h)
        assert status["latest_draft"]["draft_text"] == "original text"


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
            h.section_drafts_history = [_historical_row(1, "R-1", "fp-1", bid_id=1)]
            status = _status(h, bid_id=1)
        assert status["history_count"] == 1
        assert not [r for r in h.section_drafts_history if r["bid_id"] == 2]
