"""
tests/test_evidence_strengthening.py

OM-3: Requirement Evidence Strengthening (evidence_strengthening.py) and its
tenancy.py wiring (tenancy.strengthen_requirement_evidence_for_organization).

No live provider call anywhere in this file -- the one model call this
module adds (_call_memory_adjudication) is always either replaced via the
`adjudicate_fn` injection point or monkeypatched directly; neither
config.get_anthropic_client nor config.execute_messages_create is ever
invoked for real.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import evidence_strengthening as es
import organizational_memory as om
import tenancy


ORG_A = "11111111-1111-1111-1111-111111111111"
ORG_B = "22222222-2222-2222-2222-222222222222"


def _approved_item(item_id="k1", organization_id=ORG_A, title="ICF ACTP accreditation",
                    content="Our firm holds ICF ACTP accreditation, renewed annually since 2015, "
                            "covering executive coaching engagements for federal clients.", **kw):
    kw.setdefault("provenance", om.SourceProvenance(file_id="file-2", content_hash="b" * 64))
    kw.setdefault("derived_from_item_id", "s1")
    return om.OrganizationalMemoryItem(
        id=item_id, organization_id=organization_id,
        memory_class=om.MemoryClass.APPROVED_FIRM_KNOWLEDGE,
        title=title, content=content,
        approved_by="user-1", approved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        **kw,
    )


def _source_item(item_id="s1", organization_id=ORG_A, title="Federal coaching case study",
                  content="We delivered executive coaching to 40 federal managers across three "
                          "departments over an 18-month engagement.", **kw):
    kw.setdefault("provenance", om.SourceProvenance(file_id="file-1", content_hash="a" * 64, filename="case_study.pdf"))
    return om.OrganizationalMemoryItem(
        id=item_id, organization_id=organization_id,
        memory_class=om.MemoryClass.SOURCE_MEMORY,
        title=title, content=content,
        **kw,
    )


def _requirement(req_id="R-1", description="Vendor must demonstrate executive coaching experience with federal clients.",
                  category="Qualifications", **kw):
    row = {"id": 501, "req_id": req_id, "description": description, "category": category}
    row.update(kw)
    return row


def _weak_state(**kw):
    kw.setdefault("assessment_status", "Not Addressed")
    kw.setdefault("evidence_strength", None)
    return es.RequirementEvidenceState(**kw)


def _strong_state(**kw):
    kw.setdefault("assessment_status", "Fully Addressed")
    kw.setdefault("evidence_strength", "STRONG")
    return es.RequirementEvidenceState(**kw)


def _support_adjudicator(relationship=es.MemoryRelationship.DIRECT_SUPPORT.value, rationale="matches directly"):
    def _fn(*, requirement, evidence_state, candidates, bid_id):
        return [
            es.MemoryEvidenceCandidate(
                item_id=c.item_id, memory_class=c.memory_class.value,
                is_trusted_fact=c.is_trusted_fact, title=c.title,
                relationship=relationship, rationale=rationale,
                relevance_score=c.relevance_score, relevance_signal=c.relevance_signal,
                provenance=c.provenance.to_dict(), approved_by=c.approved_by,
                approved_at=c.approved_at.isoformat() if c.approved_at else None,
                derived_from_item_id=c.derived_from_item_id,
                source_document_id=c.source_document_id,
            )
            for c in candidates
        ]
    return _fn


def _empty_adjudicator():
    def _fn(*, requirement, evidence_state, candidates, bid_id):
        return []
    return _fn


class _RaisingIterable:
    """A candidate pool that blows up the moment anything tries to iterate
    it -- used to prove a strong requirement never even looks at the
    candidate pool."""

    def __iter__(self):
        raise AssertionError("candidate pool must not be iterated for a requirement that needs no strengthening")


# ── EvidenceGapKind / RequirementEvidenceState ──────────────────────────

class TestRequirementEvidenceState:

    def test_missing_when_no_assessment(self):
        assert es.RequirementEvidenceState().gap_kind is es.EvidenceGapKind.MISSING

    def test_missing_when_not_addressed(self):
        state = es.RequirementEvidenceState(assessment_status="Not Addressed")
        assert state.gap_kind is es.EvidenceGapKind.MISSING
        assert state.needs_strengthening is True

    def test_partial_when_partially_addressed(self):
        state = es.RequirementEvidenceState(assessment_status="Partially Addressed", evidence_strength="MODERATE")
        assert state.gap_kind is es.EvidenceGapKind.PARTIAL

    def test_weak_when_fully_addressed_but_weak_evidence(self):
        state = es.RequirementEvidenceState(assessment_status="Fully Addressed", evidence_strength="WEAK")
        assert state.gap_kind is es.EvidenceGapKind.WEAK

    def test_conflicted_overrides_everything_else(self):
        state = es.RequirementEvidenceState(
            assessment_status="Fully Addressed", evidence_strength="STRONG",
            has_contradiction_finding=True,
        )
        assert state.gap_kind is es.EvidenceGapKind.CONFLICTED
        assert state.needs_strengthening is True

    def test_sufficient_when_strong(self):
        state = _strong_state()
        assert state.gap_kind is es.EvidenceGapKind.SUFFICIENT
        assert state.needs_strengthening is False


# ── Strong requirement never triggers retrieval (instruction 9) ────────

class TestStrongRequirementSkipsRetrieval:

    def test_strong_requirement_never_iterates_candidates(self):
        result = es.strengthen_requirement_evidence(
            organization_id=ORG_A, bid_id=1, requirement=_requirement(),
            evidence_state=_strong_state(),
            candidate_items=_RaisingIterable(),
        )
        assert result.organizational_evidence == ()
        assert result.requires_human_confirmation is False
        assert result.retrieval_skipped_reason is not None
        assert result.evidence_state_after["assessment_status"] == "Fully Addressed"

    def test_strong_requirement_never_calls_adjudicator(self):
        def _boom(**kw):
            raise AssertionError("adjudicator must not be called for a strong requirement")

        result = es.strengthen_requirement_evidence(
            organization_id=ORG_A, bid_id=1, requirement=_requirement(),
            evidence_state=_strong_state(), candidate_items=[_approved_item()],
            adjudicate_fn=_boom,
        )
        assert result.organizational_evidence == ()


# ── Weak/missing requirement receives relevant approved knowledge ──────

class TestWeakRequirementReceivesApprovedKnowledge:

    def test_direct_support_from_approved_firm_knowledge(self):
        item = _approved_item()
        result = es.strengthen_requirement_evidence(
            organization_id=ORG_A, bid_id=1, requirement=_requirement(),
            evidence_state=_weak_state(), candidate_items=[item],
            adjudicate_fn=_support_adjudicator(),
        )
        assert len(result.organizational_evidence) == 1
        candidate = result.organizational_evidence[0]
        assert candidate.item_id == "k1"
        assert candidate.memory_class == om.MemoryClass.APPROVED_FIRM_KNOWLEDGE.value
        assert candidate.is_trusted_fact is True
        assert candidate.relationship == es.MemoryRelationship.DIRECT_SUPPORT.value
        assert result.evidence_state_after["has_organizational_support"] is True
        assert result.evidence_state_after["organizational_support_count"] == 1
        assert result.requires_human_confirmation is True

    def test_relevant_source_memory_surfaced_with_lower_trust(self):
        item = _source_item()
        result = es.strengthen_requirement_evidence(
            organization_id=ORG_A, bid_id=1, requirement=_requirement(),
            evidence_state=_weak_state(), candidate_items=[item],
            adjudicate_fn=_support_adjudicator(relationship=es.MemoryRelationship.PARTIAL_SUPPORT.value),
        )
        assert len(result.organizational_evidence) == 1
        candidate = result.organizational_evidence[0]
        assert candidate.memory_class == om.MemoryClass.SOURCE_MEMORY.value
        assert candidate.is_trusted_fact is False
        assert candidate.relationship == es.MemoryRelationship.PARTIAL_SUPPORT.value


# ── Irrelevant memory is never force-classified ─────────────────────────

class TestIrrelevantMemoryExcluded:

    def test_adjudicator_omitting_a_candidate_excludes_it(self):
        relevant = _approved_item(item_id="k1")
        irrelevant = _source_item(
            item_id="s-unrelated", title="Office lease renewal notes",
            content="Building lease renewal terms for the downtown office through 2030.",
        )

        def _fn(*, requirement, evidence_state, candidates, bid_id):
            # Only classify the genuinely relevant candidate -- the
            # adjudicator is free to omit anything with no real relationship,
            # and this module must never backfill a classification for it.
            return [c for c in _support_adjudicator()(
                requirement=requirement, evidence_state=evidence_state,
                candidates=candidates, bid_id=bid_id,
            ) if c.item_id == "k1"]

        result = es.strengthen_requirement_evidence(
            organization_id=ORG_A, bid_id=1, requirement=_requirement(),
            evidence_state=_weak_state(), candidate_items=[relevant, irrelevant],
            adjudicate_fn=_fn,
        )
        ids = {c.item_id for c in result.organizational_evidence}
        assert ids == {"k1"}
        assert "s-unrelated" not in ids


# ── Contradiction is surfaced, never silently used as support ──────────

class TestContradictionNeverSilentlyUsedAsSupport:

    def test_contradiction_classified_candidate_not_counted_as_support(self):
        item = _approved_item()
        result = es.strengthen_requirement_evidence(
            organization_id=ORG_A, bid_id=1, requirement=_requirement(),
            evidence_state=_weak_state(), candidate_items=[item],
            adjudicate_fn=_support_adjudicator(relationship=es.MemoryRelationship.CONTRADICTION.value),
        )
        assert len(result.organizational_evidence) == 1
        assert result.organizational_evidence[0].relationship == es.MemoryRelationship.CONTRADICTION.value
        assert result.evidence_state_after["has_organizational_support"] is False
        assert result.evidence_state_after["organizational_support_count"] == 0
        assert result.evidence_state_after["has_organizational_contradiction"] is True
        assert any("contradiction" in gap for gap in result.remaining_gaps)
        assert result.requires_human_confirmation is True

    def test_current_bid_evidence_wins_over_contradiction(self):
        """Even when a candidate is classified CONTRADICTION, the
        requirement's own assessment_status/evidence_strength (tier 2 of
        the hierarchy) must be copied through completely unchanged -- OM
        (tiers 3-4) can never override current bid/RFP evidence."""
        item = _approved_item()
        state = es.RequirementEvidenceState(assessment_status="Partially Addressed", evidence_strength="MODERATE")
        result = es.strengthen_requirement_evidence(
            organization_id=ORG_A, bid_id=1, requirement=_requirement(),
            evidence_state=state, candidate_items=[item],
            adjudicate_fn=_support_adjudicator(relationship=es.MemoryRelationship.CONTRADICTION.value),
        )
        assert result.evidence_state_before["assessment_status"] == "Partially Addressed"
        assert result.evidence_state_after["assessment_status"] == "Partially Addressed"
        assert result.evidence_state_after["evidence_strength"] == "MODERATE"


# ── Organization isolation ──────────────────────────────────────────────

class TestOrganizationIsolation:

    def test_cross_organization_candidate_never_reaches_adjudication(self):
        own_org_item = _approved_item(item_id="k1", organization_id=ORG_A)
        other_org_item = _approved_item(item_id="k-other-org", organization_id=ORG_B,
                                         title="Executive coaching accreditation",
                                         content="Federal executive coaching accreditation held since 2015.")
        seen_ids = []

        def _fn(*, requirement, evidence_state, candidates, bid_id):
            seen_ids.extend(c.item_id for c in candidates)
            return _support_adjudicator()(requirement=requirement, evidence_state=evidence_state,
                                           candidates=candidates, bid_id=bid_id)

        result = es.strengthen_requirement_evidence(
            organization_id=ORG_A, bid_id=1, requirement=_requirement(),
            evidence_state=_weak_state(), candidate_items=[own_org_item, other_org_item],
            adjudicate_fn=_fn,
        )
        assert "k-other-org" not in seen_ids
        assert {c.item_id for c in result.organizational_evidence} == {"k1"}


# ── Provenance / approval lineage survive retrieval and enrichment ─────

class TestProvenanceAndLineageSurvive:

    def test_provenance_and_lineage_preserved_on_the_enrichment_result(self):
        item = _approved_item()
        result = es.strengthen_requirement_evidence(
            organization_id=ORG_A, bid_id=1, requirement=_requirement(),
            evidence_state=_weak_state(), candidate_items=[item],
            adjudicate_fn=_support_adjudicator(),
        )
        candidate = result.organizational_evidence[0]
        assert candidate.provenance["file_id"] == "file-2"
        assert candidate.provenance["content_hash"] == "b" * 64
        assert candidate.approved_by == "user-1"
        assert candidate.approved_at is not None
        assert candidate.derived_from_item_id == "s1"

    def test_to_dict_round_trips_all_fields(self):
        item = _approved_item()
        result = es.strengthen_requirement_evidence(
            organization_id=ORG_A, bid_id=1, requirement=_requirement(),
            evidence_state=_weak_state(), candidate_items=[item],
            adjudicate_fn=_support_adjudicator(),
        )
        payload = result.to_dict()
        assert payload["req_id"] == "R-1"
        assert payload["requirement_id"] == 501
        assert len(payload["organizational_evidence"]) == 1
        assert payload["organizational_evidence"][0]["item_id"] == "k1"


# ── Bounded result count ────────────────────────────────────────────────

class TestBoundedResultCount:

    def test_top_k_bounds_the_candidate_set_before_adjudication(self):
        items = [
            _approved_item(item_id=f"k{i}", title=f"Accreditation variant {i}",
                            content=f"Federal executive coaching accreditation variant {i}, renewed annually.")
            for i in range(10)
        ]
        seen = []

        def _fn(*, requirement, evidence_state, candidates, bid_id):
            seen.extend(candidates)
            return _support_adjudicator()(requirement=requirement, evidence_state=evidence_state,
                                           candidates=candidates, bid_id=bid_id)

        result = es.strengthen_requirement_evidence(
            organization_id=ORG_A, bid_id=1, requirement=_requirement(),
            evidence_state=_weak_state(), candidate_items=items, top_k=3,
            adjudicate_fn=_fn,
        )
        assert len(seen) <= 3
        assert len(result.organizational_evidence) <= 3


# ── No proposal text generated, no memory item mutated/auto-approved ───

class TestNoSideEffects:

    def test_adjudicator_never_receives_a_write_capable_handle(self):
        """MemoryEvidenceCandidate is a frozen dataclass built from a
        RetrievalResult snapshot -- there is no code path here that calls
        any organizational_memory write function or database.py mutation."""
        item = _approved_item()
        result = es.strengthen_requirement_evidence(
            organization_id=ORG_A, bid_id=1, requirement=_requirement(),
            evidence_state=_weak_state(), candidate_items=[item],
            adjudicate_fn=_support_adjudicator(),
        )
        # Frozen dataclasses raise on attempted mutation -- proves the
        # returned candidate is a read-only projection, not a live handle.
        with pytest.raises(Exception):
            result.organizational_evidence[0].relationship = "TAMPERED"

    def test_no_proposal_text_field_anywhere_in_result(self):
        item = _approved_item()
        result = es.strengthen_requirement_evidence(
            organization_id=ORG_A, bid_id=1, requirement=_requirement(),
            evidence_state=_weak_state(), candidate_items=[item],
            adjudicate_fn=_support_adjudicator(),
        )
        payload_str = str(result.to_dict())
        for forbidden in ("proposal_text", "draft_text", "drafted_section"):
            assert forbidden not in payload_str


# ── Default adjudicator: fail-closed reconciliation, no live call ──────

class TestDefaultAdjudicatorFailClosed:

    def test_unknown_item_id_from_model_is_dropped(self):
        item = _approved_item()
        with patch.object(es, "_call_memory_adjudication",
                           return_value=({"assessments": [
                               {"item_id": "not-a-real-id", "relationship": "DIRECT_SUPPORT", "rationale": "x"},
                           ]}, None)):
            result = es.strengthen_requirement_evidence(
                organization_id=ORG_A, bid_id=1, requirement=_requirement(),
                evidence_state=_weak_state(), candidate_items=[item],
            )
        assert result.organizational_evidence == ()

    def test_unrecognized_relationship_is_dropped(self):
        item = _approved_item()
        with patch.object(es, "_call_memory_adjudication",
                           return_value=({"assessments": [
                               {"item_id": "k1", "relationship": "SORT_OF_RELATED", "rationale": "x"},
                           ]}, None)):
            result = es.strengthen_requirement_evidence(
                organization_id=ORG_A, bid_id=1, requirement=_requirement(),
                evidence_state=_weak_state(), candidate_items=[item],
            )
        assert result.organizational_evidence == ()

    def test_valid_model_response_is_accepted(self):
        item = _approved_item()
        with patch.object(es, "_call_memory_adjudication",
                           return_value=({"assessments": [
                               {"item_id": "k1", "relationship": "DIRECT_SUPPORT",
                                "rationale": "directly on point", "caveat": None},
                           ]}, None)):
            result = es.strengthen_requirement_evidence(
                organization_id=ORG_A, bid_id=1, requirement=_requirement(),
                evidence_state=_weak_state(), candidate_items=[item],
            )
        assert len(result.organizational_evidence) == 1
        assert result.organizational_evidence[0].relationship == "DIRECT_SUPPORT"

    def test_api_failure_yields_zero_candidates_never_raises(self):
        item = _approved_item()
        with patch.object(es, "_call_memory_adjudication", return_value=(None, "api_error")):
            result = es.strengthen_requirement_evidence(
                organization_id=ORG_A, bid_id=1, requirement=_requirement(),
                evidence_state=_weak_state(), candidate_items=[item],
            )
        assert result.organizational_evidence == ()
        assert result.requires_human_confirmation is False


# ── tenancy.py wiring ────────────────────────────────────────────────────

class TestTenancyWiring:

    def test_requires_bid_access_before_any_read(self):
        with patch.object(tenancy, "authorize_bid_access", return_value=False):
            with pytest.raises(tenancy.AccessDeniedError):
                tenancy.strengthen_requirement_evidence_for_organization(
                    bid_id=1, organization_id=ORG_A, requirement_id=501)

    def test_strong_requirement_skips_organizational_memory_read_entirely(self):
        import database as db

        requirement_row = {"id": 501, "req_id": "R-1", "description": "x", "category": "y"}
        run_row = {"id": 9, "status": "COMPLETE"}
        assessment_row = {"req_id": "R-1", "assessment_status": "Fully Addressed", "evidence_strength": "STRONG"}

        with patch.object(tenancy, "authorize_bid_access", return_value=True), \
             patch.object(db, "get_requirements_by_ids", return_value=[requirement_row]), \
             patch.object(db, "get_latest_usable_proposal_intelligence_run", return_value=run_row), \
             patch.object(db, "get_proposal_requirement_assessments", return_value=[assessment_row]), \
             patch.object(db, "get_proposal_intelligence_findings", return_value=[]), \
             patch.object(db, "list_organizational_memory_items") as mock_list:
            result = tenancy.strengthen_requirement_evidence_for_organization(
                bid_id=1, organization_id=ORG_A, requirement_id=501)

        mock_list.assert_not_called()
        assert result["organizational_evidence"] == []
        assert result["retrieval_skipped_reason"] is not None

    def test_missing_requirement_raises(self):
        import database as db

        with patch.object(tenancy, "authorize_bid_access", return_value=True), \
             patch.object(db, "get_requirements_by_ids", return_value=[]):
            with pytest.raises(ValueError):
                tenancy.strengthen_requirement_evidence_for_organization(
                    bid_id=1, organization_id=ORG_A, requirement_id=999)
