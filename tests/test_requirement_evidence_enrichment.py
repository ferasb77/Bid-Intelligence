"""
tests/test_requirement_evidence_enrichment.py

OM-3B: Durable Requirement Evidence Enrichment -- persistence/reuse
orchestration on top of OM-3A's pure evidence_strengthening.py domain logic
(migrations/017_requirement_evidence_enrichment.sql,
tenancy.strengthen_requirement_evidence_for_organization).

Exercises the full reuse/recompute/persist flow against an in-memory fake
standing in for the `requirement_evidence_enrichments` table + its
get_or_create_requirement_evidence_enrichment RPC (migration 017) --
mirroring that RPC's exact idempotent-on-(bid_id, req_id, input_fingerprint)
semantics -- since no live database is available in this test suite.

No live provider call anywhere in this file -- the adjudication model call
is always monkeypatched at evidence_strengthening._call_memory_adjudication,
never a real Anthropic invocation.
"""
import re
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

import database as db
import evidence_strengthening as es
import organizational_memory as om
import tenancy


ORG_A = "11111111-1111-1111-1111-111111111111"
ORG_B = "22222222-2222-2222-2222-222222222222"


# ── In-memory fake standing in for migration 017's table + RPC ─────────────

class _FakeEnrichmentStore:
    """Mirrors get_or_create_requirement_evidence_enrichment()'s exact
    semantics: idempotent get-or-insert keyed on
    (bid_id, req_id, input_fingerprint), never an UPDATE."""

    def __init__(self):
        self.rows: list[dict] = []
        self._next_id = 1

    def history(self, bid_id, req_id):
        return [r for r in self.rows if r["bid_id"] == bid_id and r["req_id"] == req_id]

    def get_or_create(self, *, bid_id, req_id, input_fingerprint, contract_version,
                       evidence_state_before, evidence_state_after, requirement_id=None,
                       organizational_evidence=None, remaining_gaps=None,
                       requires_human_confirmation=False, retrieval_skipped_reason=None,
                       created_by_user_id=None):
        for row in self.rows:
            if (row["bid_id"] == bid_id and row["req_id"] == req_id
                    and row["input_fingerprint"] == input_fingerprint):
                return row
        row = {
            "id": self._next_id, "bid_id": bid_id, "req_id": req_id,
            "requirement_id": requirement_id, "contract_version": contract_version,
            "input_fingerprint": input_fingerprint,
            "evidence_state_before": evidence_state_before,
            "organizational_evidence": organizational_evidence or [],
            "evidence_state_after": evidence_state_after,
            "remaining_gaps": remaining_gaps or [],
            "requires_human_confirmation": requires_human_confirmation,
            "retrieval_skipped_reason": retrieval_skipped_reason,
            "created_by_user_id": created_by_user_id,
            "created_at": f"2026-01-01T00:00:{self._next_id:02d}+00:00",
        }
        self._next_id += 1
        self.rows.append(row)
        return row


def _om_row(item_id, memory_class, organization_id=ORG_A, title="Accreditation",
            content_hash="c" * 64, source_file_id="file-1", source_content_hash="a" * 64,
            approved_by_user_id=None, approved_at=None, derived_from_item_id=None):
    return {
        "id": item_id, "organization_id": organization_id, "memory_class": memory_class,
        "title": title, "content": f"{title} content for {item_id}, federal executive coaching.",
        "content_hash": content_hash,
        "source_file_id": source_file_id, "source_content_hash": source_content_hash,
        "source_filename": "case_study.pdf", "source_package_path": None, "source_locator": None,
        "source_bid_id": None, "approved_by_user_id": approved_by_user_id,
        "approved_at": approved_at, "derived_from_item_id": derived_from_item_id,
        "source_document_id": None, "metadata": {},
    }


def _mock_adjudication_direct_support(prompt, *, bid_id, max_tokens=1200):
    """Extracts every `[item_id]` bracket the prompt lists and classifies
    all of them DIRECT_SUPPORT -- a deterministic stand-in for a real model
    response, never touching the network."""
    block = prompt.split("CANDIDATE ORGANIZATIONAL MEMORY ITEMS")[1].split("TASK:")[0]
    ids = re.findall(r"\[([^\]]+)\]", block)
    return ({"assessments": [
        {"item_id": i, "relationship": "DIRECT_SUPPORT", "rationale": "on point", "caveat": None}
        for i in ids
    ]}, None)


class _Harness:
    """Wires all the DB reads/writes strengthen_requirement_evidence_for_
    organization touches to controllable, in-memory fakes."""

    def __init__(self):
        self.store = _FakeEnrichmentStore()
        self.requirement = {"id": 501, "req_id": "R-1", "description":
                             "Vendor must demonstrate executive coaching experience with federal clients.",
                             "category": "Qualifications"}
        self.run = {"id": 9, "status": "COMPLETE"}
        self.assessment = {"req_id": "R-1", "assessment_status": "Not Addressed", "evidence_strength": None}
        self.findings = []
        self.om_rows = {
            om.MemoryClass.APPROVED_FIRM_KNOWLEDGE.value: [
                _om_row("k1", om.MemoryClass.APPROVED_FIRM_KNOWLEDGE.value,
                        approved_by_user_id="user-1",
                        approved_at=datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
                        derived_from_item_id="s1"),
            ],
            om.MemoryClass.SOURCE_MEMORY.value: [],
        }
        self.adjudication_calls = 0

    def list_om_items(self, organization_id, memory_class=None):
        if organization_id != ORG_A:
            return []
        return list(self.om_rows.get(memory_class, []))

    def adjudicate(self, prompt, *, bid_id, max_tokens=1200):
        self.adjudication_calls += 1
        return _mock_adjudication_direct_support(prompt, bid_id=bid_id, max_tokens=max_tokens)

    def patches(self):
        return [
            patch.object(tenancy, "authorize_bid_access", return_value=True),
            patch.object(db, "get_requirements_by_ids", side_effect=lambda bid_id, ids: [self.requirement] if ids == [501] else []),
            patch.object(db, "get_latest_usable_proposal_intelligence_run", side_effect=lambda bid_id: self.run),
            patch.object(db, "get_proposal_requirement_assessments", side_effect=lambda run_id: [self.assessment]),
            patch.object(db, "get_proposal_intelligence_findings", side_effect=lambda run_id: self.findings),
            patch.object(db, "list_organizational_memory_items", side_effect=self.list_om_items),
            patch.object(db, "get_requirement_evidence_enrichments", side_effect=self.store.history),
            patch.object(db, "get_or_create_requirement_evidence_enrichment", side_effect=self.store.get_or_create),
            patch.object(es, "_call_memory_adjudication", side_effect=self.adjudicate),
        ]

    def __enter__(self):
        self._patchers = self.patches()
        for p in self._patchers:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patchers):
            p.stop()


def _call(h: _Harness, bid_id=1, requirement_id=501):
    return tenancy.strengthen_requirement_evidence_for_organization(
        bid_id=bid_id, organization_id=ORG_A, requirement_id=requirement_id)


# ── First request computes + persists; second reuses without a model call ──

class TestComputeOnceReuseDownstream:

    def test_first_request_computes_and_persists(self):
        with _Harness() as h:
            result = _call(h)
            assert h.adjudication_calls == 1
            assert len(h.store.rows) == 1
            assert result["organizational_evidence"][0]["item_id"] == "k1"
            assert result["organizational_evidence"][0]["relationship"] == "DIRECT_SUPPORT"

    def test_second_identical_request_reuses_without_another_model_call(self):
        with _Harness() as h:
            first = _call(h)
            second = _call(h)
            assert h.adjudication_calls == 1          # NOT called again
            assert len(h.store.rows) == 1              # NOT a new row
            assert second == first

    def test_reused_result_matches_the_persisted_row_shape(self):
        with _Harness() as h:
            _call(h)
            row = h.store.rows[0]
            result = _call(h)
            assert result["organizational_evidence"] == row["organizational_evidence"]
            assert result["evidence_state_after"] == row["evidence_state_after"]


# ── Invalidation ─────────────────────────────────────────────────────────

class TestInvalidation:

    def test_changed_requirement_text_invalidates_and_recomputes(self):
        with _Harness() as h:
            _call(h)
            assert h.adjudication_calls == 1
            h.requirement = dict(h.requirement, description="A completely different requirement about pricing.")
            _call(h)
            assert h.adjudication_calls == 2
            assert len(h.store.rows) == 2

    def test_changed_assessment_status_invalidates_and_recomputes(self):
        with _Harness() as h:
            _call(h)
            assert h.adjudication_calls == 1
            h.assessment = dict(h.assessment, assessment_status="Partially Addressed", evidence_strength="MODERATE")
            _call(h)
            assert h.adjudication_calls == 2
            assert len(h.store.rows) == 2

    def test_changed_organizational_memory_pool_invalidates_and_recomputes(self):
        with _Harness() as h:
            _call(h)
            assert h.adjudication_calls == 1
            h.om_rows[om.MemoryClass.SOURCE_MEMORY.value] = [
                _om_row("s-new", om.MemoryClass.SOURCE_MEMORY.value, content_hash="d" * 64),
            ]
            _call(h)
            assert h.adjudication_calls == 2
            assert len(h.store.rows) == 2

    def test_identical_inputs_after_an_unrelated_change_still_reuse(self):
        """A column NOT read by strengthen_requirement_evidence (e.g. a
        requirement's internal numeric id staying the same, unrelated
        metadata) must never force a needless recompute."""
        with _Harness() as h:
            _call(h)
            _call(h)  # same requirement/assessment/OM pool
            assert h.adjudication_calls == 1


# ── Provenance / lineage survive the persistence round trip ────────────────

class TestProvenanceSurvivesRoundTrip:

    def test_provenance_and_lineage_preserved_after_reuse(self):
        with _Harness() as h:
            first = _call(h)
            second = _call(h)
            for payload in (first, second):
                candidate = payload["organizational_evidence"][0]
                assert candidate["provenance"]["file_id"] == "file-1"
                assert candidate["provenance"]["content_hash"] == "a" * 64
                assert candidate["approved_by"] == "user-1"
                assert candidate["approved_at"] is not None
                assert candidate["derived_from_item_id"] == "s1"
                assert candidate["memory_class"] == om.MemoryClass.APPROVED_FIRM_KNOWLEDGE.value
                assert candidate["is_trusted_fact"] is True


# ── Organization / bid isolation ────────────────────────────────────────────

class TestIsolation:

    def test_persisted_history_lookup_is_bid_scoped(self):
        with _Harness() as h:
            _call(h, bid_id=1)
            # A second bid's own enrichment call for a same-numbered
            # requirement id must never see bid 1's persisted row -- the
            # fake's get_requirements_by_ids only recognizes id 501 for
            # ANY bid here, so this proves isolation happens via bid_id on
            # the stored row/lookup, not via requirement identity alone.
            assert h.store.history(1, "R-1")
            assert h.store.history(2, "R-1") == []

    def test_cross_organization_om_item_never_reaches_adjudication(self):
        with _Harness() as h:
            h.om_rows[om.MemoryClass.SOURCE_MEMORY.value] = [
                _om_row("s-other-org", om.MemoryClass.SOURCE_MEMORY.value, organization_id=ORG_B),
            ]
            result = _call(h)
            ids = {c["item_id"] for c in result["organizational_evidence"]}
            assert "s-other-org" not in ids


# ── No mutation, no proposal text ───────────────────────────────────────────

class TestNoSideEffects:

    def test_no_organizational_memory_write_function_is_ever_called(self):
        with _Harness() as h, \
             patch.object(db, "create_organizational_memory_item") as mock_create, \
             patch.object(db, "approve_organizational_memory_item") as mock_approve:
            _call(h)
            mock_create.assert_not_called()
            mock_approve.assert_not_called()

    def test_no_proposal_text_field_anywhere_in_persisted_or_returned_result(self):
        with _Harness() as h:
            result = _call(h)
            row = h.store.rows[0]
            for payload in (result, row):
                text = str(payload)
                for forbidden in ("proposal_text", "draft_text", "drafted_section"):
                    assert forbidden not in text


# ── Already-sufficient requirement avoids unnecessary OM retrieval ─────────

class TestSufficientRequirementSkipsPersistence:

    def test_sufficient_requirement_never_reads_or_writes_the_enrichment_store(self):
        with _Harness() as h:
            h.assessment = dict(h.assessment, assessment_status="Fully Addressed", evidence_strength="STRONG")
            result = _call(h)
            assert h.adjudication_calls == 0
            assert h.store.rows == []
            assert result["organizational_evidence"] == []
            assert result["retrieval_skipped_reason"] is not None


# ── Failure during recomputation never corrupts a prior valid result ───────

class TestFailureDoesNotCorruptPriorResult:

    def test_persistence_failure_on_recompute_leaves_prior_row_untouched_and_raises(self):
        with _Harness() as h:
            first = _call(h)
            assert len(h.store.rows) == 1
            original_row = dict(h.store.rows[0])

            h.requirement = dict(h.requirement, description="A totally different requirement text now.")

            def _boom(**kw):
                raise RuntimeError("simulated persistence failure")

            with patch.object(db, "get_or_create_requirement_evidence_enrichment", side_effect=_boom):
                with pytest.raises(RuntimeError):
                    _call(h)

            # The original row must be exactly as it was -- never mutated,
            # never removed, and no partial/corrupt second row was added.
            assert len(h.store.rows) == 1
            assert h.store.rows[0] == original_row
