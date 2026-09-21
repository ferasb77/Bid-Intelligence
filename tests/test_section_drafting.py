"""
tests/test_section_drafting.py

PI-3A: Evidence-Aware Section Drafting (section_drafting.py) -- pure
domain-layer tests. No I/O, no live provider call anywhere in this file;
the one model call this module adds is always injected via `draft_fn`.
"""
import pytest

import section_drafting as sd


def _requirement(req_id="R-1", category="Mandatory",
                  description="Vendor must demonstrate executive coaching experience with federal clients.",
                  source_refs=None, requirement_id=501):
    return {
        "id": requirement_id, "req_id": req_id, "category": category,
        "description": description, "source_refs": source_refs or [],
    }


def _assessment(assessment_status="Partially Addressed", evidence_strength="MODERATE",
                 confidence="Medium", explanation="Some proposal evidence found.",
                 proposal_source_refs=None):
    return {
        "assessment_status": assessment_status, "evidence_strength": evidence_strength,
        "confidence": confidence, "explanation": explanation,
        "proposal_source_refs": proposal_source_refs or [],
    }


def _om_item(item_id="k1", memory_class="APPROVED_FIRM_KNOWLEDGE", relationship="DIRECT_SUPPORT",
             title="Federal coaching accreditation", rationale="Directly on point.", caveat=None,
             is_trusted_fact=True):
    return {
        "item_id": item_id, "memory_class": memory_class, "is_trusted_fact": is_trusted_fact,
        "title": title, "relationship": relationship, "rationale": rationale,
        "relevance_score": 0.4, "relevance_signal": "KEYWORD",
        "provenance": {"file_id": "file-1", "content_hash": "a" * 64},
        "approved_by": "user-1" if memory_class == "APPROVED_FIRM_KNOWLEDGE" else None,
        "approved_at": "2026-01-01T00:00:00+00:00" if memory_class == "APPROVED_FIRM_KNOWLEDGE" else None,
        "derived_from_item_id": "s1" if memory_class == "APPROVED_FIRM_KNOWLEDGE" else None,
        "source_document_id": None, "caveat": caveat,
    }


def _enrichment(organizational_evidence=None, remaining_gaps=None, requires_human_confirmation=False):
    return {
        "organizational_evidence": organizational_evidence or [],
        "remaining_gaps": remaining_gaps or [],
        "requires_human_confirmation": requires_human_confirmation,
    }


def _build_brief(**overrides):
    kwargs = dict(
        organization_id="org-a", bid_id=1, requirement=_requirement(),
        related_requirements=[], evaluation_criterion=None, response_guideline=None,
        evidence_state=None, assessment=_assessment(), persisted_enrichment=None,
        proposal_intelligence_findings=[], response_constraints=None,
    )
    kwargs.update(overrides)
    return sd.build_brief(**kwargs)


def _draft_fn_returning(payload):
    def _fn(prompt, *, bid_id, max_tokens=2000):
        return (payload, None)
    return _fn


def _failing_draft_fn(reason="api_error"):
    def _fn(prompt, *, bid_id, max_tokens=2000):
        return (None, reason)
    return _fn


# ── Grounding ────────────────────────────────────────────────────────────

class TestGrounding:

    def test_strong_evidence_produces_grounded_draft(self):
        om_item = _om_item()
        brief = _build_brief(persisted_enrichment=_enrichment(organizational_evidence=[om_item]))
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "Our firm has delivered federal executive coaching engagements...",
            "requirements_addressed": ["R-1"],
            "evaluation_criteria_addressed": [],
            "evidence_items_used": [{"evidence_id": "OM1", "claim_type": "ORGANIZATIONAL_KNOWLEDGE", "note": "firm accreditation"}],
            "unsupported_or_unresolved_points": [],
            "contradictions_or_caveats": [],
            "human_confirmation_required": False,
            "word_count": 12,
        }))
        assert result.draft_text
        assert "R-1" in result.requirements_addressed
        assert len(result.evidence_items_used) == 1
        assert result.evidence_items_used[0].claim_type == "ORGANIZATIONAL_KNOWLEDGE"
        assert result.evidence_items_used[0].source_kind == sd.SOURCE_KIND_ORGANIZATIONAL_MEMORY

    def test_bid_specific_evidence_supports_a_verified_fact_claim(self):
        assessment = _assessment(proposal_source_refs=[{"section": "3.2", "file_id": "prop-1"}])
        brief = _build_brief(assessment=assessment)
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "As demonstrated in our proposal...",
            "requirements_addressed": ["R-1"],
            "evidence_items_used": [{"evidence_id": "PE1", "claim_type": "VERIFIED_FACT", "note": "proposal section 3.2"}],
            "human_confirmation_required": False,
        }))
        assert result.evidence_items_used[0].evidence_id == "PE1"
        assert result.evidence_items_used[0].source_kind == sd.SOURCE_KIND_PROPOSAL
        assert result.evidence_items_used[0].claim_type == "VERIFIED_FACT"

    def test_approved_firm_knowledge_can_support_a_factual_claim(self):
        om_item = _om_item(memory_class="APPROVED_FIRM_KNOWLEDGE")
        brief = _build_brief(persisted_enrichment=_enrichment(organizational_evidence=[om_item]))
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text",
            "evidence_items_used": [{"evidence_id": "OM1", "claim_type": "VERIFIED_FACT", "note": "x"}],
        }))
        assert result.evidence_items_used[0].trust_class == "APPROVED_FIRM_KNOWLEDGE"

    def test_source_memory_remains_explicitly_lower_trust(self):
        om_item = _om_item(item_id="s1", memory_class="SOURCE_MEMORY", is_trusted_fact=False)
        brief = _build_brief(persisted_enrichment=_enrichment(organizational_evidence=[om_item]))
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text",
            "evidence_items_used": [{"evidence_id": "OM1", "claim_type": "ORGANIZATIONAL_KNOWLEDGE", "note": "x"}],
        }))
        assert result.evidence_items_used[0].trust_class == "SOURCE_MEMORY"

    def test_source_memory_is_never_presented_as_verified_fact_by_the_registry(self):
        """The registry itself carries trust_class through untouched -- a
        SOURCE_MEMORY item's trust_class is never upgraded to
        APPROVED_FIRM_KNOWLEDGE regardless of what claim_type the model
        used."""
        om_item = _om_item(item_id="s1", memory_class="SOURCE_MEMORY", is_trusted_fact=False)
        brief = _build_brief(persisted_enrichment=_enrichment(organizational_evidence=[om_item]))
        registry = sd._evidence_id_registry(brief)
        assert registry["OM1"]["detail"]["memory_class"] == "SOURCE_MEMORY"


# ── Missing evidence ─────────────────────────────────────────────────────

class TestMissingEvidence:

    def test_missing_evidence_produces_an_unresolved_point(self):
        brief = _build_brief(assessment=_assessment(assessment_status="Not Addressed", evidence_strength=None))
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "[SME confirmation required: quantified delivery outcome]",
            "unsupported_or_unresolved_points": ["quantified delivery outcome unavailable"],
            "human_confirmation_required": True,
        }))
        assert result.unsupported_or_unresolved_points

    def test_missing_evidence_does_not_produce_fabricated_facts(self):
        """The reconciler drops any evidence_items_used entry citing an id
        the brief never offered -- a model 'inventing' a fact by citing a
        nonexistent id cannot survive reconciliation."""
        brief = _build_brief()
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text",
            "evidence_items_used": [{"evidence_id": "OM99", "claim_type": "VERIFIED_FACT", "note": "invented"}],
        }))
        assert result.evidence_items_used == ()

    def test_human_confirmation_required_becomes_true_when_needed(self):
        brief = _build_brief(persisted_enrichment=_enrichment(requires_human_confirmation=True))
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
            "human_confirmation_required": True,
        }))
        assurance = sd.assure_section_draft(brief, result)
        assert result.human_confirmation_required is True
        assert assurance.passed


# ── Conflicts ────────────────────────────────────────────────────────────

class TestConflicts:

    def test_conflicting_om_cannot_override_current_bid_evidence(self):
        """The brief's bid_specific_evidence is copied through unchanged
        by build_brief regardless of what Organizational Memory says --
        this module never re-derives or overwrites tier-2 evidence."""
        assessment = _assessment(assessment_status="Fully Addressed", evidence_strength="STRONG")
        om_item = _om_item(relationship="CONTRADICTION")
        brief = _build_brief(assessment=assessment, persisted_enrichment=_enrichment(organizational_evidence=[om_item]))
        assert brief.bid_specific_evidence["assessment_status"] == "Fully Addressed"
        assert brief.bid_specific_evidence["evidence_strength"] == "STRONG"

    def test_contradictory_evidence_surfaced_as_caveat_not_hidden(self):
        om_item = _om_item(relationship="CONTRADICTION", caveat="Conflicts with stated delivery timeline.")
        brief = _build_brief(persisted_enrichment=_enrichment(organizational_evidence=[om_item]))
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
            "contradictions_or_caveats": ["Organizational memory suggests a conflicting timeline."],
            "human_confirmation_required": True,
        }))
        assurance = sd.assure_section_draft(brief, result)
        assert result.contradictions_or_caveats
        assert assurance.passed

    def test_assurance_flags_a_hidden_contradiction(self):
        om_item = _om_item(relationship="CONTRADICTION")
        brief = _build_brief(persisted_enrichment=_enrichment(organizational_evidence=[om_item]))
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text",
            "contradictions_or_caveats": [],   # hidden -- assurance should catch this
            "human_confirmation_required": True,
        }))
        assurance = sd.assure_section_draft(brief, result)
        assert assurance.passed is False
        assert any("CONTRADICTION" in issue for issue in assurance.issues)


# ── Coverage ─────────────────────────────────────────────────────────────

class TestCoverage:

    def test_mandatory_response_element_represented(self):
        brief = _build_brief(requirement=_requirement(category="Mandatory"))
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
        }))
        assurance = sd.assure_section_draft(brief, result)
        assert brief.is_mandatory is True
        assert "not present in requirements_addressed" not in " ".join(assurance.issues)

    def test_missing_mandatory_element_is_detected(self):
        brief = _build_brief(requirement=_requirement(category="Mandatory"))
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": [],
        }))
        assurance = sd.assure_section_draft(brief, result)
        assert assurance.passed is False
        assert any("mandatory requirement" in issue for issue in assurance.issues)

    def test_evaluation_criteria_appear_in_the_brief(self):
        criterion = {"criterion_label": "Corporate Experience", "weight": "20 points", "threshold": None}
        brief = _build_brief(evaluation_criterion=criterion)
        assert brief.evaluation.criterion_label == "Corporate Experience"
        assert brief.evaluation.weight == "20 points"

    def test_relevant_evaluation_criteria_reflected_in_result(self):
        criterion = {"criterion_label": "Corporate Experience", "weight": "20 points", "threshold": None}
        brief = _build_brief(evaluation_criterion=criterion)
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
            "evaluation_criteria_addressed": ["Corporate Experience"],
        }))
        assurance = sd.assure_section_draft(brief, result)
        assert "Corporate Experience" in result.evaluation_criteria_addressed
        assert assurance.passed

    def test_assurance_flags_missing_evaluation_criterion_reflection(self):
        criterion = {"criterion_label": "Corporate Experience", "weight": "20 points", "threshold": None}
        brief = _build_brief(evaluation_criterion=criterion)
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "evaluation_criteria_addressed": [],
        }))
        assurance = sd.assure_section_draft(brief, result)
        assert assurance.passed is False


# ── Traceability ─────────────────────────────────────────────────────────

class TestTraceability:

    def test_evidence_used_by_the_draft_is_present_in_the_brief(self):
        om_item = _om_item()
        brief = _build_brief(persisted_enrichment=_enrichment(organizational_evidence=[om_item]))
        registry = sd._evidence_id_registry(brief)
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text",
            "evidence_items_used": [{"evidence_id": "OM1", "claim_type": "ORGANIZATIONAL_KNOWLEDGE", "note": "x"}],
        }))
        for item in result.evidence_items_used:
            assert item.evidence_id in registry

    def test_evidence_not_in_brief_cannot_appear_as_cited(self):
        brief = _build_brief()  # empty registry -- no OM, no proposal refs, no RFP refs
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text",
            "evidence_items_used": [{"evidence_id": "OM1", "claim_type": "VERIFIED_FACT", "note": "fabricated"}],
        }))
        assert result.evidence_items_used == ()

    def test_provenance_survives_into_the_structured_result(self):
        om_item = _om_item()
        brief = _build_brief(persisted_enrichment=_enrichment(organizational_evidence=[om_item]))
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text",
            "evidence_items_used": [{"evidence_id": "OM1", "claim_type": "ORGANIZATIONAL_KNOWLEDGE", "note": "x"}],
        }))
        item = result.evidence_items_used[0]
        assert item.label == "Federal coaching accreditation"
        assert item.trust_class == "APPROVED_FIRM_KNOWLEDGE"


# ── Token / architecture discipline ─────────────────────────────────────

class TestArchitectureDiscipline:

    def test_draft_section_never_imports_organizational_memory(self):
        import sys
        assert "organizational_memory" not in getattr(sd, "__dict__", {}) or not any(
            name == "organizational_memory" for name in dir(sd))

    def test_draft_section_calls_only_the_injected_draft_fn(self):
        calls = {"n": 0}

        def _fn(prompt, *, bid_id, max_tokens=2000):
            calls["n"] += 1
            return ({"draft_text": "text"}, None)

        brief = _build_brief()
        sd.draft_section(brief=brief, draft_fn=_fn)
        assert calls["n"] == 1

    def test_build_brief_performs_no_io(self):
        """build_brief is a pure function over already-supplied arguments
        -- calling it with no persisted_enrichment/assessment/evaluation
        data must never raise or attempt any fetch."""
        brief = sd.build_brief(
            organization_id="org-a", bid_id=1, requirement=_requirement(),
        )
        assert brief.organizational_evidence == ()
        assert brief.bid_specific_evidence == {}


# ── Safety / tenancy ─────────────────────────────────────────────────────

class TestSafety:

    def test_no_underlying_evidence_object_is_mutated(self):
        om_item = _om_item()
        original = dict(om_item)
        brief = _build_brief(persisted_enrichment=_enrichment(organizational_evidence=[om_item]))
        sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text",
            "evidence_items_used": [{"evidence_id": "OM1", "claim_type": "ORGANIZATIONAL_KNOWLEDGE", "note": "x"}],
        }))
        assert om_item == original

    def test_brief_is_frozen(self):
        brief = _build_brief()
        with pytest.raises(Exception):
            brief.req_id = "TAMPERED"

    def test_result_is_frozen(self):
        brief = _build_brief()
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({"draft_text": "text"}))
        with pytest.raises(Exception):
            result.draft_text = "TAMPERED"


# ── Constraints ──────────────────────────────────────────────────────────

class TestConstraints:

    def test_word_limit_respected_flagged_by_assurance_when_exceeded(self):
        constraints = sd.ResponseConstraints(word_limit=100)
        brief = _build_brief(response_constraints=constraints)
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "word_count": 500,
        }))
        assurance = sd.assure_section_draft(brief, result)
        assert assurance.passed is False
        assert any("word_count" in issue for issue in assurance.issues)

    def test_word_limit_within_bound_passes(self):
        constraints = sd.ResponseConstraints(word_limit=100)
        brief = _build_brief(response_constraints=constraints)
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "word_count": 95, "requirements_addressed": ["R-1"],
        }))
        assurance = sd.assure_section_draft(brief, result)
        assert not any("word_count" in issue for issue in assurance.issues)


# ── Failure handling ─────────────────────────────────────────────────────

class TestFailureHandling:

    def test_api_failure_yields_no_fabricated_prose(self):
        brief = _build_brief()
        result = sd.draft_section(brief=brief, draft_fn=_failing_draft_fn("api_error"))
        assert result.draft_text == ""
        assert result.human_confirmation_required is True
        assert result.failure_reason == "api_error"

    def test_malformed_response_yields_no_fabricated_prose(self):
        brief = _build_brief()

        def _fn(prompt, *, bid_id, max_tokens=2000):
            return ({"not_draft_text": "oops"}, None)

        result = sd.draft_section(brief=brief, draft_fn=_fn)
        assert result.draft_text == ""
        assert result.failure_reason is not None

    def test_assurance_flags_a_failed_draft(self):
        brief = _build_brief()
        result = sd.draft_section(brief=brief, draft_fn=_failing_draft_fn())
        assurance = sd.assure_section_draft(brief, result)
        assert assurance.passed is False


# ── PI-3C: claim-level evidence support mapping ─────────────────────────

class TestMaterialClaimMapping:

    def test_claim_maps_only_to_valid_evidence_ids(self):
        om_item = _om_item()
        brief = _build_brief(persisted_enrichment=_enrichment(organizational_evidence=[om_item]))
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
            "material_claims": [
                {"claim_id": "C1", "claim_text": "Our firm holds the accreditation.",
                 "claim_type": "ORGANIZATIONAL_KNOWLEDGE", "evidence_ids": ["OM1", "OM99"],
                 "support_status": "SUPPORTED"},
            ],
        }))
        assert len(result.material_claims) == 1
        claim = result.material_claims[0]
        assert claim.evidence_ids == ("OM1",)   # OM99 (invented) silently dropped

    def test_unsupported_claim_never_appears_as_verified(self):
        brief = _build_brief()
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
            "material_claims": [
                {"claim_id": "C1", "claim_text": "We have delivered this exact scope before.",
                 "claim_type": "UNSUPPORTED_GAP", "evidence_ids": ["OM1", "PE1"],
                 "support_status": "SUPPORTED"},
            ],
        }))
        claim = result.material_claims[0]
        assert claim.claim_type == sd.CLAIM_TYPE_UNSUPPORTED_GAP
        assert claim.evidence_ids == ()
        assert claim.support_status == sd.SUPPORT_STATUS_UNSUPPORTED

    def test_proposed_approach_distinguishable_from_historical_fact(self):
        brief = _build_brief()
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
            "material_claims": [
                {"claim_id": "C1", "claim_text": "We will assign a dedicated compliance lead.",
                 "claim_type": "PROPOSED_APPROACH", "evidence_ids": [], "support_status": "SUPPORTED"},
            ],
        }))
        claim = result.material_claims[0]
        assert claim.claim_type == sd.CLAIM_TYPE_PROPOSED_APPROACH
        assert claim.support_status == sd.SUPPORT_STATUS_COMMITMENT
        assert claim.support_status != sd.SUPPORT_STATUS_SUPPORTED

    def test_verified_fact_backed_only_by_source_memory_is_downgraded(self):
        """SOURCE_MEMORY (lower trust) can never by itself back a claim
        tagged VERIFIED_FACT -- the claim is downgraded to
        UNSUPPORTED_GAP rather than left as a falsely-verified fact."""
        om_item = _om_item(item_id="s1", memory_class="SOURCE_MEMORY", is_trusted_fact=False)
        brief = _build_brief(persisted_enrichment=_enrichment(organizational_evidence=[om_item]))
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
            "material_claims": [
                {"claim_id": "C1", "claim_text": "This is a verified historical fact.",
                 "claim_type": "VERIFIED_FACT", "evidence_ids": ["OM1"], "support_status": "SUPPORTED"},
            ],
        }))
        claim = result.material_claims[0]
        assert claim.claim_type == sd.CLAIM_TYPE_UNSUPPORTED_GAP
        assert claim.evidence_ids == ()
        assert claim.support_status == sd.SUPPORT_STATUS_UNSUPPORTED

    def test_verified_fact_backed_by_approved_firm_knowledge_is_accepted(self):
        om_item = _om_item(memory_class="APPROVED_FIRM_KNOWLEDGE")
        brief = _build_brief(persisted_enrichment=_enrichment(organizational_evidence=[om_item]))
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
            "material_claims": [
                {"claim_id": "C1", "claim_text": "We hold ICF ACTP accreditation.",
                 "claim_type": "VERIFIED_FACT", "evidence_ids": ["OM1"], "support_status": "SUPPORTED"},
            ],
        }))
        claim = result.material_claims[0]
        assert claim.claim_type == sd.CLAIM_TYPE_VERIFIED_FACT
        assert claim.evidence_ids == ("OM1",)
        assert claim.support_status == sd.SUPPORT_STATUS_SUPPORTED

    def test_verified_fact_backed_by_proposal_evidence_is_accepted(self):
        assessment = _assessment(proposal_source_refs=[{"section": "3.2", "file_id": "prop-1"}])
        brief = _build_brief(assessment=assessment)
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
            "material_claims": [
                {"claim_id": "C1", "claim_text": "As stated in our submitted proposal.",
                 "claim_type": "VERIFIED_FACT", "evidence_ids": ["PE1"], "support_status": "SUPPORTED"},
            ],
        }))
        claim = result.material_claims[0]
        assert claim.claim_type == sd.CLAIM_TYPE_VERIFIED_FACT
        assert claim.evidence_ids == ("PE1",)

    def test_organizational_knowledge_with_no_valid_evidence_is_downgraded(self):
        brief = _build_brief()
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
            "material_claims": [
                {"claim_id": "C1", "claim_text": "Our firm has relevant experience.",
                 "claim_type": "ORGANIZATIONAL_KNOWLEDGE", "evidence_ids": ["OM1"], "support_status": "SUPPORTED"},
            ],
        }))
        claim = result.material_claims[0]
        assert claim.claim_type == sd.CLAIM_TYPE_UNSUPPORTED_GAP
        assert claim.evidence_ids == ()

    def test_unknown_claim_type_drops_the_whole_claim(self):
        brief = _build_brief()
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
            "material_claims": [
                {"claim_id": "C1", "claim_text": "x", "claim_type": "SORT_OF_TRUE",
                 "evidence_ids": [], "support_status": "SUPPORTED"},
            ],
        }))
        assert result.material_claims == ()

    def test_duplicate_claim_ids_keep_only_first(self):
        brief = _build_brief()
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
            "material_claims": [
                {"claim_id": "C1", "claim_text": "first", "claim_type": "PROPOSED_APPROACH", "evidence_ids": []},
                {"claim_id": "C1", "claim_text": "second", "claim_type": "PROPOSED_APPROACH", "evidence_ids": []},
            ],
        }))
        assert len(result.material_claims) == 1
        assert result.material_claims[0].claim_text == "first"

    def test_material_claims_bounded(self):
        brief = _build_brief()
        many = [
            {"claim_id": f"C{i}", "claim_text": f"claim {i}", "claim_type": "PROPOSED_APPROACH", "evidence_ids": []}
            for i in range(sd.MAX_MATERIAL_CLAIMS + 5)
        ]
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"], "material_claims": many,
        }))
        assert len(result.material_claims) == sd.MAX_MATERIAL_CLAIMS

    def test_missing_material_claims_key_defaults_to_empty(self):
        """Backward compatible -- a draft_fn (or a real model response)
        that omits material_claims entirely must never raise."""
        brief = _build_brief()
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
        }))
        assert result.material_claims == ()

    def test_material_claim_to_dict_round_trips(self):
        om_item = _om_item()
        brief = _build_brief(persisted_enrichment=_enrichment(organizational_evidence=[om_item]))
        result = sd.draft_section(brief=brief, draft_fn=_draft_fn_returning({
            "draft_text": "text", "requirements_addressed": ["R-1"],
            "material_claims": [
                {"claim_id": "C1", "claim_text": "Firm accreditation claim.",
                 "claim_type": "ORGANIZATIONAL_KNOWLEDGE", "evidence_ids": ["OM1"],
                 "support_status": "SUPPORTED"},
            ],
        }))
        payload = result.to_dict()
        assert payload["material_claims"][0]["claim_id"] == "C1"
        assert payload["material_claims"][0]["evidence_ids"] == ["OM1"]
