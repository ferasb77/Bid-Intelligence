"""
tests/test_proposal_outline_intelligent.py -- PI-3D1: Intelligent Proposal
Outline Architecture. Pure-domain tests for the tiered derivation
hierarchy (proposal_outline.derive_intelligent_outline and its Tier 1/2/3
helpers). No I/O for Tiers 1/2; Tier 3's real Anthropic call is always
injected via `call_fn` here, mirroring section_drafting's own test posture
-- no live provider call in this file.
"""
import proposal_outline as po


def _req(rid, category, description, req_id=None):
    return {"id": rid, "req_id": req_id or f"R{rid}", "category": category, "description": description}


def _si_with_categories():
    """A synthetic structured_intelligence with two explicit buyer-
    defined response categories, mirroring the real Bank of Canada shape
    (weights_by_category + raw_occurrences with category_scope)."""
    return {
        "evaluation": {
            "weights_by_category": {
                "Category 1 — Technical Approach": [
                    {"weight": "40 points", "criterion": "Delivery Methodology"},
                    {"weight": "20 points", "criterion": "Team Experience"},
                ],
                "Category 2 — Corporate Capacity": [
                    {"weight": "15 points", "criterion": "Corporate Profile"},
                    {"weight": "25 points", "criterion": "Client References"},
                ],
            },
            "raw_occurrences": [
                {"criterion_label": "Delivery Methodology", "weight": "40 points",
                 "category_scope": "Category 1 — Technical Approach", "parent_heading": "Category 1 — Technical Approach"},
                {"criterion_label": "Team Experience", "weight": "20 points",
                 "category_scope": "Category 1 — Technical Approach", "parent_heading": "Category 1 — Technical Approach"},
                {"criterion_label": "Corporate Profile", "weight": "15 points",
                 "category_scope": "Category 2 — Corporate Capacity", "parent_heading": "Category 2 — Corporate Capacity"},
                {"criterion_label": "Client References", "weight": "25 points",
                 "category_scope": "Category 2 — Corporate Capacity", "parent_heading": "Category 2 — Corporate Capacity"},
            ],
            "stages": [
                {"stage": "Stage 1", "component": "Mandatory Submission Requirements", "basis": "Pass / fail"},
                {"stage": "Stage 2", "component": "Rated Criteria", "basis": "Scored"},
            ],
        },
        "response_requirements": {
            "checklist": [
                {"item": "Appendix A", "description": "Submission Form", "notes": "Signed declaration"},
                {"item": "Appendix B", "description": "Pricing Form", "notes": "All-inclusive pricing"},
            ],
        },
        "pricing_and_commercial": {
            "points": [{"topic": "Pricing model", "detail": "Fixed fee"}],
            "raw_pricing_occurrences": [],
        },
    }


class TestExplicitStructurePrecedence:
    """Explicit RFP response headings take precedence; buyer-mandated
    order (as stated by weights_by_category) is preserved and never
    overridden by a model-generated alternative."""

    def test_explicit_categories_become_sections(self):
        si = _si_with_categories()
        reqs = [
            _req(1, "Rated", "Describe your methodology for delivering the engagement, including approach."),
            _req(2, "Rated", "Describe your corporate profile and organizational structure."),
        ]
        sections = po.extract_explicit_sections_from_structured_intelligence(si, reqs)
        titles = {s["title"] for s in sections}
        assert "Technical Approach" in titles
        assert "Corporate Capacity" in titles

    def test_derivation_method_is_explicit_rfp_structure(self):
        si = _si_with_categories()
        reqs = [_req(1, "Rated", "Methodology approach description.")]
        outline = po.derive_intelligent_outline(reqs, structured_intelligence=si)
        assert outline["derivation_method"] == po.DERIVATION_EXPLICIT_RFP_STRUCTURE
        for sec in outline["sections"]:
            if sec["source_basis"] == po.DERIVATION_EXPLICIT_RFP_STRUCTURE:
                assert sec["derivation_method"] == po.DERIVATION_EXPLICIT_RFP_STRUCTURE

    def test_uncategorized_bucket_never_becomes_a_section(self):
        si = _si_with_categories()
        si["evaluation"]["weights_by_category"]["Uncategorized"] = [{"weight": "5 points", "criterion": "Misc"}]
        sections = po.extract_explicit_sections_from_structured_intelligence(si, [])
        assert all(s["title"].lower() != "uncategorized" for s in sections)

    def test_empty_weights_by_category_yields_no_tier1_sections(self):
        assert po.extract_explicit_sections_from_structured_intelligence({}, []) == []
        assert po.extract_explicit_sections_from_structured_intelligence(
            {"evaluation": {"weights_by_category": {}}}, []) == []

    def test_mandatory_gate_requirements_get_their_own_explicit_section(self):
        """Mandatory pass/fail requirements are grouped by the RFP's own
        documented staged process (evaluation.stages), not dropped."""
        si = _si_with_categories()
        reqs = [_req(1, "Mandatory", "Proponent must sign the declaration.")]
        already_mapped = set()
        sec = po.extract_mandatory_requirements_section(si, reqs, already_mapped)
        assert sec is not None
        assert sec["source_basis"] == po.DERIVATION_EXPLICIT_RFP_STRUCTURE
        assert 1 in sec["mapped_requirement_ids"]

    def test_no_gate_stage_means_no_mandatory_section(self):
        si = {"evaluation": {"stages": [{"stage": "Stage 2", "component": "Rated", "basis": "Scored"}]}}
        reqs = [_req(1, "Mandatory", "Some mandatory item.")]
        assert po.extract_mandatory_requirements_section(si, reqs, set()) is None


class TestDeterministicDerivation:
    """Tier 2: workstreams/evaluation-criterion signals drive structure;
    bare Mandatory/Rated/Supporting classification is never the primary
    axis when a richer signal exists."""

    def test_criterion_based_clustering_when_no_explicit_categories(self):
        occurrences = [
            {"criterion_label": "Delivery Approach", "parent_heading": "Delivery Approach"},
            {"criterion_label": "Quality Assurance", "parent_heading": "Quality Assurance"},
        ]
        reqs = [
            _req(1, "Rated", "Describe your delivery approach and implementation plan."),
            _req(2, "Rated", "Describe your quality assurance and evaluation methods."),
        ]
        sections = po._derive_tier2_sections(reqs, occurrences)
        titles = {s["title"] for s in sections}
        assert titles == {"Delivery Approach", "Quality Assurance"}
        for s in sections:
            assert s["derivation_method"] if "derivation_method" in s else s["source_basis"] == po.DERIVATION_DETERMINISTIC

    def test_falls_back_to_category_grouping_only_when_no_occurrences_at_all(self):
        reqs = [_req(1, "Mandatory", "x"), _req(2, "Supporting", "y")]
        sections = po._derive_tier2_sections(reqs, occurrences=[])
        titles = {s["title"] for s in sections}
        assert titles == {"Mandatory", "Supporting"}
        for s in sections:
            assert s["source_basis"] == po.DERIVATION_DETERMINISTIC
            assert "no explicit RFP response structure" in s["rationale"]

    def test_generic_classification_alone_does_not_win_when_criteria_exist(self):
        """A single matched-criterion cluster (>= 2 distinct headings)
        must be preferred over the bare category fallback."""
        occurrences = [
            {"criterion_label": "Program Design", "parent_heading": "Program Design"},
            {"criterion_label": "Facilitator Team", "parent_heading": "Facilitator Team"},
        ]
        reqs = [
            _req(1, "Mandatory", "Describe your program design methodology and approach."),
            _req(2, "Rated", "Describe your facilitator team qualifications and experience."),
        ]
        sections = po._derive_tier2_sections(reqs, occurrences)
        titles = {s["title"] for s in sections}
        assert titles == {"Program Design", "Facilitator Team"}
        assert "Mandatory" not in titles and "Rated" not in titles

    def test_pricing_section_surfaces_from_pricing_and_commercial(self):
        si = {"pricing_and_commercial": {"points": [{"topic": "Fee structure", "detail": "x"}], "raw_pricing_occurrences": []}}
        sec = po.extract_pricing_section(si, [_req(1, "Financial", "Provide your pricing.")])
        assert sec is not None
        assert sec["title"] == "Pricing"
        assert 1 in sec["mapped_requirement_ids"]

    def test_no_pricing_content_yields_no_pricing_section(self):
        assert po.extract_pricing_section({}, []) is None

    def test_forms_section_surfaces_from_checklist(self):
        si = {"response_requirements": {"checklist": [
            {"item": "Appendix A", "description": "Signed Declaration Form", "notes": ""},
        ]}}
        sec = po.extract_submission_form_section(si)
        assert sec is not None
        assert len(sec["checklist_items"]) == 1

    def test_no_form_like_checklist_items_yields_no_forms_section(self):
        si = {"response_requirements": {"checklist": [
            {"item": "Note 1", "description": "Bidder should review the site conditions.", "notes": ""},
        ]}}
        assert po.extract_submission_form_section(si) is None


class TestCoverage:
    """Instruction 4: every active requirement is mapped or explicitly
    classified; orphaned mandatory blocks ready state; a section removal
    is detectable as newly orphaning requirements."""

    def test_every_active_requirement_is_accounted_for(self):
        si = _si_with_categories()
        reqs = [
            _req(1, "Rated", "Methodology approach for delivery."),
            _req(2, "Mandatory", "Sign the declaration form."),
            _req(3, "Supporting", "Provide additional background context."),
        ]
        outline = po.derive_intelligent_outline(reqs, structured_intelligence=si)
        mapped = {rid for s in outline["sections"] for rid in (s.get("mapped_requirement_ids") or [])}
        unresolved_ids = {u["requirement_id"] for u in outline["unresolved"]}
        assert mapped | unresolved_ids == {1, 2, 3}
        assert mapped.isdisjoint(unresolved_ids)

    def test_requirement_without_id_is_never_counted(self):
        reqs = [{"req_id": "X", "category": "Mandatory", "description": "no id"}]
        outline = po.derive_intelligent_outline(reqs, structured_intelligence={})
        assert outline["coverage"]["total_requirement_count"] == 0
        assert outline["unresolved"] == []

    def test_orphaned_mandatory_requirement_blocks_ready_state(self):
        reqs = [_req(1, "Mandatory", "Some genuinely unclassifiable mandatory clause with no keyword signal.")]
        outline = po.derive_intelligent_outline(reqs, structured_intelligence={})
        assert outline["coverage"]["is_ready"] is False
        assert outline["coverage"]["orphaned_mandatory_count"] == 1

    def test_non_mandatory_unresolved_does_not_block_ready_state(self):
        reqs = [_req(1, "Supporting", "Some generic supporting background material for context.")]
        outline = po.derive_intelligent_outline(reqs, structured_intelligence={})
        assert outline["coverage"]["is_ready"] is True

    def test_removing_a_section_detects_newly_orphaned_requirements(self):
        """Pure equivalent of the UI's remove-a-section warning: recompute
        coverage after dropping one section's requirement_ids."""
        si = _si_with_categories()
        reqs = [_req(1, "Rated", "Methodology approach for delivery.")]
        outline = po.derive_intelligent_outline(reqs, structured_intelligence=si)
        before_mapped = outline["coverage"]["mapped_requirement_count"]
        assert before_mapped >= 1

        remaining_sections = [s for s in outline["sections"] if 1 not in (s.get("mapped_requirement_ids") or [])]
        new_unresolved = list(outline["unresolved"])
        removed_ids = {1}
        for r in reqs:
            if r["id"] in removed_ids:
                new_unresolved.append({
                    "requirement_id": r["id"], "req_id": r["req_id"],
                    "classification": po.classify_unresolved_requirement(r),
                })
        new_coverage = po._coverage_summary(reqs, remaining_sections, new_unresolved)
        assert new_coverage["mapped_requirement_count"] < before_mapped
        assert 1 in {u["requirement_id"] for u in new_unresolved}


class TestClassifyUnresolvedRequirement:

    def test_financial_category_is_commercial_item(self):
        assert po.classify_unresolved_requirement(_req(1, "Financial", "Provide pricing.")) == po.UNRESOLVED_COMMERCIAL_ITEM

    def test_form_keyword_is_submission_form(self):
        assert po.classify_unresolved_requirement(
            _req(1, "Mandatory", "Sign and submit the declaration form.")) == po.UNRESOLVED_SUBMISSION_FORM

    def test_supporting_category_is_appendix_item(self):
        assert po.classify_unresolved_requirement(
            _req(1, "Supporting", "Some generic background.")) == po.UNRESOLVED_APPENDIX_ITEM

    def test_generic_unclassifiable_is_needs_decision(self):
        assert po.classify_unresolved_requirement(
            _req(1, "Mandatory", "Some genuinely ambiguous clause with no keyword signal at all.")) == po.UNRESOLVED_NEEDS_DECISION

    def test_informational_keyword_is_informational(self):
        assert po.classify_unresolved_requirement(
            _req(1, "Supporting", "This section is for information only.")) == po.UNRESOLVED_INFORMATIONAL


class TestEvaluationCoverage:
    """Instruction 5: criterion-to-section mapping, uncovered-criterion
    surfacing, and a structural-prominence warning that never invents
    weighting the RFP itself did not state."""

    def test_criterion_maps_to_its_section(self):
        si = _si_with_categories()
        outline = po.derive_intelligent_outline([], structured_intelligence=si)
        cov = po.evaluation_criteria_coverage(outline["sections"])
        assert "Delivery Methodology" in cov["covered"]
        assert "Technical Approach" in cov["covered"]["Delivery Methodology"][0]

    def test_uncovered_criterion_is_surfaced(self):
        sections = [{"title": "A", "mapped_evaluation_criteria": ["Methodology"]}]
        cov = po.evaluation_criteria_coverage(sections, all_criteria_labels=["Methodology", "Orphan Criterion"])
        assert cov["uncovered_criteria"] == ["Orphan Criterion"]

    def test_high_weight_criterion_diluted_by_bundling_is_flagged(self):
        sections = [{
            "title": "Everything Technical",
            "criteria_weights": {"Methodology": 40, "Team": 10, "Tools": 5, "Reporting": 5},
        }]
        warnings = po.surface_high_weight_structural_warnings(sections)
        labels = {w["criterion_label"] for w in warnings}
        assert "Methodology" in labels
        assert "Team" not in labels  # below the points threshold

    def test_no_warning_when_section_has_few_criteria(self):
        sections = [{"title": "Focused Section", "criteria_weights": {"Methodology": 40}}]
        assert po.surface_high_weight_structural_warnings(sections) == []

    def test_never_invents_a_weight_when_none_present(self):
        sections = [{"title": "A", "criteria_weights": {}}]
        assert po.surface_high_weight_structural_warnings(sections) == []


class TestModelFallback:
    """Tier 3: bounded model refinement used only when Tiers 1+2 are
    insufficient; the model never receives the full RFP; OM is never
    queried; the section-drafting model is never called."""

    def test_needs_model_refinement_false_when_tier1_covers_most_requirements(self):
        si = _si_with_categories()
        reqs = [
            _req(1, "Rated", "Methodology approach for delivery."),
            _req(2, "Rated", "Corporate profile and organizational structure."),
        ]
        outline = po.derive_intelligent_outline(reqs, structured_intelligence=si)
        assert outline["needs_model_refinement"] is False

    def test_needs_model_refinement_true_when_fewer_than_two_sections(self):
        assert po.needs_model_refinement([{"title": "Only One"}], {"total_requirement_count": 5, "mapped_requirement_count": 5}) is True

    def test_needs_model_refinement_true_when_majority_unmapped(self):
        sections = [{"title": "A"}, {"title": "B"}]
        coverage = {"total_requirement_count": 10, "mapped_requirement_count": 2}
        assert po.needs_model_refinement(sections, coverage) is True

    def test_needs_model_refinement_false_with_zero_requirements(self):
        assert po.needs_model_refinement([{"title": "A"}], {"total_requirement_count": 0, "mapped_requirement_count": 0}) is False

    def test_prompt_never_contains_full_rfp_marker(self):
        """The bounded prompt must be built ONLY from requirement
        summaries/candidate sections/evaluation summaries/constraints --
        never a raw-RFP-text placeholder or an OM-retrieval marker."""
        reqs = [_req(1, "Rated", "Short description.")]
        prompt = po.build_outline_refinement_prompt([{"title": "A", "rationale": "x"}], reqs)
        assert "organizational_memory" not in prompt.lower()
        assert "raw rfp" not in prompt.lower()

    def test_refine_outline_with_model_uses_injected_call_fn_not_real_anthropic(self):
        calls = []

        def _fake_call(prompt, *, bid_id, max_tokens=1500):
            calls.append(prompt)
            return {"sections": [{"title": "Refined Section", "rationale": "test", "requirement_ids": [1]}]}, None

        reqs = [_req(1, "Rated", "x")]
        result = po.refine_outline_with_model(
            [{"title": "Candidate", "rationale": "y", "mapped_requirement_ids": []}],
            reqs, call_fn=_fake_call)
        assert len(calls) == 1
        assert result["failure_reason"] is None
        assert result["sections"][0]["title"] == "Refined Section"
        assert result["sections"][0]["derivation_method"] == po.DERIVATION_MODEL_REFINEMENT

    def test_refine_outline_with_model_never_calls_twice(self):
        calls = []

        def _fake_call(prompt, *, bid_id, max_tokens=1500):
            calls.append(1)
            return {"sections": [{"title": "S", "requirement_ids": []}]}, None

        po.refine_outline_with_model([], [_req(1, "Rated", "x")], call_fn=_fake_call)
        assert len(calls) == 1

    def test_reconcile_drops_requirement_ids_outside_this_bids_set(self):
        parsed = {"sections": [{"title": "S", "requirement_ids": [1, 999]}]}
        reqs = [_req(1, "Rated", "x")]
        sections = po.reconcile_model_refined_sections(parsed, reqs)
        assert sections[0]["mapped_requirement_ids"] == [1]

    def test_reconcile_drops_titleless_sections(self):
        parsed = {"sections": [{"title": "", "requirement_ids": [1]}, {"title": "Real", "requirement_ids": []}]}
        sections = po.reconcile_model_refined_sections(parsed, [_req(1, "Rated", "x")])
        assert len(sections) == 1
        assert sections[0]["title"] == "Real"

    def test_api_failure_leaves_no_sections_and_names_the_failure(self):
        def _fail(prompt, *, bid_id, max_tokens=1500):
            return None, "api_error"

        result = po.refine_outline_with_model([], [_req(1, "Rated", "x")], call_fn=_fail)
        assert result["sections"] is None
        assert result["failure_reason"] == "api_error"

    def test_no_section_drafting_model_surface_reachable_from_outline_module(self):
        """proposal_outline.py must never import section_drafting -- Tier
        3 is its OWN bounded call, never a re-use of the drafting model's
        call site."""
        assert not hasattr(po, "section_drafting")
