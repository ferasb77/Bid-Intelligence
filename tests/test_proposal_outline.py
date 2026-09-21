"""
tests/test_proposal_outline.py -- PI-3D pure-domain tests for
proposal_outline.py (deterministic outline derivation + section
intelligence rollups). No I/O, no Anthropic, no database -- mirrors
tests/test_section_drafting.py's own posture for its pure domain module.
"""
import proposal_outline as po


def _req(rid, category, req_id=None):
    return {"id": rid, "req_id": req_id or f"R{rid}", "category": category,
            "description": f"Requirement {rid} about {category}."}


class TestDeriveOutlineSections:

    def test_groups_by_category(self):
        reqs = [_req(1, "Technical Approach"), _req(2, "Technical Approach"), _req(3, "Pricing")]
        sections = po.derive_outline_sections(reqs)
        titles = {s["title"] for s in sections}
        assert titles == {"Technical Approach", "Pricing"}
        tech = next(s for s in sections if s["title"] == "Technical Approach")
        assert set(tech["requirement_ids"]) == {1, 2}

    def test_blank_category_falls_back_to_general(self):
        reqs = [_req(1, ""), _req(2, None), _req(3, "   ")]
        sections = po.derive_outline_sections(reqs)
        assert len(sections) == 1
        assert sections[0]["title"] == "General"
        assert set(sections[0]["requirement_ids"]) == {1, 2, 3}

    def test_requirement_without_id_is_skipped(self):
        reqs = [_req(1, "Pricing"), {"req_id": "R-no-id", "category": "Pricing", "description": "x"}]
        sections = po.derive_outline_sections(reqs)
        assert sections[0]["requirement_ids"] == [1]

    def test_never_mutates_input(self):
        reqs = [_req(1, "Pricing")]
        original = [dict(r) for r in reqs]
        po.derive_outline_sections(reqs)
        assert reqs == original

    def test_deterministic_order_by_count_then_name(self):
        reqs = [_req(1, "B"), _req(2, "B"), _req(3, "A"), _req(4, "C")]
        sections = po.derive_outline_sections(reqs)
        # "B" has 2 requirements (most substantial first); "A" and "C" tie
        # at 1 each, broken alphabetically.
        assert [s["title"] for s in sections] == ["B", "A", "C"]

    def test_reproducible_for_the_same_input(self):
        reqs = [_req(1, "B"), _req(2, "A"), _req(3, "A")]
        first = po.derive_outline_sections(reqs)
        second = po.derive_outline_sections(reqs)
        assert first == second

    def test_bounded_to_max_proposed_sections(self):
        reqs = [_req(i, f"Category {i}") for i in range(po.MAX_PROPOSED_SECTIONS + 10)]
        sections = po.derive_outline_sections(reqs)
        assert len(sections) == po.MAX_PROPOSED_SECTIONS

    def test_section_numbers_are_sequential(self):
        reqs = [_req(1, "A"), _req(2, "B")]
        sections = po.derive_outline_sections(reqs)
        assert [s["section_num"] for s in sections] == ["1.0", "2.0"]

    def test_empty_requirements_yields_no_sections(self):
        assert po.derive_outline_sections([]) == []

    def test_no_anthropic_or_model_call_surface(self):
        """PI-3D1 instruction 12: derive_intelligent_outline (Tiers 1+2,
        the deterministic path) must have no module-level Anthropic/
        organizational_memory import to accidentally reach for --
        PI-3D1's ONE bounded Tier-3 model call (_call_outline_refinement)
        lazily imports `config` only inside its own function body, never
        at module scope, so a deterministic-only caller never even
        imports the Anthropic client."""
        assert not hasattr(po, "config")
        assert not hasattr(po, "organizational_memory")
        assert not hasattr(po, "anthropic")


class TestEvidenceReadinessBucket:

    def test_no_assessment_is_none(self):
        assert po.evidence_readiness_bucket(None, None) == "None"

    def test_fully_addressed_strong_is_strong(self):
        assert po.evidence_readiness_bucket("Fully Addressed", "STRONG") == "Strong"

    def test_not_addressed_is_weak(self):
        assert po.evidence_readiness_bucket("Not Addressed", None) == "Weak"

    def test_weak_strength_is_weak_even_if_partially_addressed(self):
        assert po.evidence_readiness_bucket("Partially Addressed", "WEAK") == "Weak"

    def test_partially_addressed_moderate_strength_is_moderate(self):
        assert po.evidence_readiness_bucket("Partially Addressed", "MODERATE") == "Moderate"

    def test_fully_addressed_without_strong_strength_is_moderate_not_strong(self):
        assert po.evidence_readiness_bucket("Fully Addressed", "MODERATE") == "Moderate"


class TestWeakestReadiness:

    def test_rolls_up_to_the_weakest(self):
        assert po.weakest_readiness(["Strong", "Weak", "Moderate"]) == "Weak"

    def test_all_strong_is_strong(self):
        assert po.weakest_readiness(["Strong", "Strong"]) == "Strong"

    def test_empty_is_none(self):
        assert po.weakest_readiness([]) == "None"

    def test_unknown_values_are_ignored(self):
        assert po.weakest_readiness(["bogus", "Strong"]) == "Strong"


class TestSummarizeSectionIntelligence:

    def test_empty_requirement_ids_is_not_applicable(self):
        summary = po.summarize_section_intelligence([])
        assert summary["draft_status"] == "NOT_APPLICABLE"
        assert summary["requirement_count"] == 0
        assert summary["evidence_readiness"] == "None"

    def test_counts_distinct_evaluation_criteria(self):
        criterion_by_req_id = {
            1: {"criterion_label": "Technical Merit"},
            2: {"criterion_label": "Technical Merit"},
            3: {"stage": "Price"},
        }
        summary = po.summarize_section_intelligence([1, 2, 3], criterion_by_req_id)
        assert summary["evaluation_criteria_count"] == 2

    def test_evidence_readiness_rolls_up_from_assessments(self):
        assessment_by_req_id = {
            1: {"assessment_status": "Fully Addressed", "evidence_strength": "STRONG"},
            2: {"assessment_status": "Not Addressed", "evidence_strength": None},
        }
        summary = po.summarize_section_intelligence([1, 2], assessment_by_req_id=assessment_by_req_id)
        assert summary["evidence_readiness"] == "Weak"

    def test_unresolved_gap_count(self):
        assessment_by_req_id = {
            1: {"assessment_status": "Fully Addressed", "evidence_strength": "STRONG"},
            2: {"assessment_status": "Not Addressed", "evidence_strength": None},
            3: {"assessment_status": "Partially Addressed", "evidence_strength": "MODERATE"},
        }
        summary = po.summarize_section_intelligence([1, 2, 3], assessment_by_req_id=assessment_by_req_id)
        assert summary["unresolved_gap_count"] == 2

    def test_draft_status_not_generated(self):
        summary = po.summarize_section_intelligence([1, 2], draft_exists_by_req_id={})
        assert summary["draft_status"] == "NOT_GENERATED"
        assert summary["drafted_count"] == 0

    def test_draft_status_partial(self):
        summary = po.summarize_section_intelligence([1, 2], draft_exists_by_req_id={1: True})
        assert summary["draft_status"] == "PARTIAL"
        assert summary["drafted_count"] == 1

    def test_draft_status_generated(self):
        summary = po.summarize_section_intelligence([1, 2], draft_exists_by_req_id={1: True, 2: True})
        assert summary["draft_status"] == "GENERATED"
        assert summary["drafted_count"] == 2

    def test_missing_maps_default_safely(self):
        # No criterion/assessment/draft maps supplied at all -- must not raise.
        summary = po.summarize_section_intelligence([1, 2, 3])
        assert summary["requirement_count"] == 3
        assert summary["evidence_readiness"] == "None"
