"""
tests/test_section_drafting_tenancy.py

PI-3A tenancy wiring (tenancy.draft_section_for_organization) -- proves the
architecture-discipline claims that matter most at the I/O boundary:
brief assembly never triggers Organizational Memory retrieval or a fresh
OM-3A/OM-3B computation, never re-runs Proposal Alignment/Fast Analysis,
and organization/bid isolation holds. No live database, no live provider
call -- the drafting model call is always monkeypatched at
section_drafting._call_memory... er, section_drafting's own
_call_section_draft is never reached because draft_fn defaults are bypassed
via a controlled fake.
"""
from unittest.mock import patch

import pytest

import database as db
import evidence_strengthening as es
import organizational_memory as om
import section_analyzer as sa
import section_drafting as sd
import tenancy


ORG_A = "11111111-1111-1111-1111-111111111111"


def _requirement(req_id="R-1", category="Mandatory", requirement_id=501):
    return {"id": requirement_id, "req_id": req_id, "category": category,
            "description": "Vendor must comply with all applicable statutes and regulations.",
            "source_refs": []}


def _om_row(item_id, memory_class=om.MemoryClass.APPROVED_FIRM_KNOWLEDGE.value):
    return {
        "id": item_id, "organization_id": ORG_A, "memory_class": memory_class,
        "title": "x", "content": "x", "content_hash": "h",
        "source_file_id": None, "source_content_hash": "sch", "source_filename": None,
        "source_package_path": None, "source_locator": None, "source_bid_id": None,
        "approved_by_user_id": None, "approved_at": None, "derived_from_item_id": None,
        "source_document_id": None, "metadata": {},
    }


class _Harness:
    def __init__(self):
        self.requirement = _requirement()
        self.other_requirements = []
        self.run = None
        self.assessment_rows = []
        self.finding_rows = []
        self.enrichment_history = []
        self.om_full_reads = 0
        self.om_identity_reads = 0
        self.om_retrieve_calls = 0
        self.strengthen_calls = 0
        self.draft_calls = 0

    def _list_om_items(self, organization_id, memory_class=None):
        self.om_full_reads += 1
        return []

    def _list_om_identities(self, organization_id, memory_class=None):
        self.om_identity_reads += 1
        return []

    def _fake_draft_fn(self, prompt, *, bid_id, max_tokens=2000):
        self.draft_calls += 1
        return ({"draft_text": "drafted text", "requirements_addressed": [self.requirement["req_id"]]}, None)

    def patches(self):
        return [
            patch.object(tenancy, "authorize_bid_access", return_value=True),
            patch.object(db, "get_requirements_by_ids",
                         side_effect=lambda bid_id, ids: [self.requirement] if ids == [self.requirement["id"]] else []),
            patch.object(db, "get_requirements", side_effect=lambda bid_id: self.other_requirements),
            patch.object(db, "get_latest_usable_proposal_intelligence_run", side_effect=lambda bid_id: self.run),
            patch.object(db, "get_proposal_requirement_assessments", side_effect=lambda run_id: self.assessment_rows),
            patch.object(db, "get_proposal_intelligence_findings", side_effect=lambda run_id: self.finding_rows),
            patch.object(db, "get_requirement_evidence_enrichments",
                         side_effect=lambda bid_id, req_id: self.enrichment_history),
            patch.object(db, "list_organizational_memory_items", side_effect=self._list_om_items),
            patch.object(db, "list_organizational_memory_item_identities", side_effect=self._list_om_identities),
            patch.object(sa, "procurement_basis", return_value={"raw_snapshot": None}),
            patch.object(om, "retrieve", side_effect=self._blow_up_retrieve),
            patch.object(es, "strengthen_requirement_evidence", side_effect=self._blow_up_strengthen),
            patch.object(sd, "_call_section_draft", side_effect=self._fake_draft_fn),
        ]

    def _blow_up_retrieve(self, *a, **kw):
        self.om_retrieve_calls += 1
        raise AssertionError("organizational_memory.retrieve() must never be called during drafting")

    def _blow_up_strengthen(self, *a, **kw):
        self.strengthen_calls += 1
        raise AssertionError("evidence_strengthening.strengthen_requirement_evidence() must never be "
                              "called during drafting -- OM-3A/OM-3B must not be re-run")

    def __enter__(self):
        self._patchers = self.patches()
        for p in self._patchers:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patchers):
            p.stop()


def _call(h: _Harness, bid_id=1, requirement_id=501):
    return tenancy.draft_section_for_organization(
        bid_id=bid_id, organization_id=ORG_A, requirement_id=requirement_id)


class TestArchitectureDisciplineAtWiring:

    def test_drafting_never_calls_organizational_memory_retrieve(self):
        with _Harness() as h:
            _call(h)
            assert h.om_retrieve_calls == 0

    def test_drafting_never_reruns_om3a_om3b(self):
        with _Harness() as h:
            _call(h)
            assert h.strengthen_calls == 0

    def test_drafting_reads_only_persisted_enrichment_never_full_om_content(self):
        """draft_section_for_organization reads
        database.get_requirement_evidence_enrichments (a persisted-row
        READ) but must never call list_organizational_memory_items or
        list_organizational_memory_item_identities -- those are OM-3A/
        OM-3B's own concerns, not drafting's."""
        with _Harness() as h:
            _call(h)
            assert h.om_full_reads == 0
            assert h.om_identity_reads == 0

    def test_drafting_calls_the_model_exactly_once(self):
        with _Harness() as h:
            _call(h)
            assert h.draft_calls == 1

    def test_requires_bid_access_before_any_read(self):
        with _Harness() as h:
            with patch.object(tenancy, "authorize_bid_access", return_value=False):
                with pytest.raises(tenancy.AccessDeniedError):
                    _call(h)

    def test_missing_requirement_raises(self):
        with _Harness() as h:
            with pytest.raises(ValueError):
                _call(h, requirement_id=999999)


class TestResultShape:

    def test_returns_brief_result_and_assurance(self):
        with _Harness() as h:
            payload = _call(h)
        assert set(payload.keys()) == {"brief", "result", "assurance"}
        assert payload["result"]["draft_text"] == "drafted text"
        assert payload["brief"]["req_id"] == "R-1"
        assert "passed" in payload["assurance"]

    def test_no_persistence_write_function_is_called(self):
        """PI-3A is compute-and-return only this phase -- no draft
        persistence table/RPC exists, so nothing beyond the pre-existing
        OM-3B write path could even be invoked; confirm that path isn't
        touched either."""
        with _Harness() as h, patch.object(db, "get_or_create_requirement_evidence_enrichment") as mock_write:
            _call(h)
            mock_write.assert_not_called()

    def test_related_requirements_exclude_self_and_other_categories(self):
        with _Harness() as h:
            h.other_requirements = [
                {"id": 502, "req_id": "R-2", "category": "Mandatory", "description": "sibling"},
                {"id": 501, "req_id": "R-1", "category": "Mandatory", "description": "self, must be excluded"},
                {"id": 503, "req_id": "R-3", "category": "Rated", "description": "different category"},
            ]
            payload = _call(h)
        related_ids = {r["req_id"] for r in payload["brief"]["related_requirements"]}
        assert related_ids == {"R-2"}
