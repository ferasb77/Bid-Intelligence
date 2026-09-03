"""
tests/test_evaluation_hierarchy_integrity.py

Unit and regression tests for evaluation hierarchy and weighting integrity.
Covers:
- Weight parsing (percent, points, within parent, overall, bare numbers as other, pass/fail, threshold separation)
- Aggregation statuses (VALID, SOURCE_DISCREPANCY, UNRESOLVED_HIERARCHY, MIXED_UNITS, INSUFFICIENT_DATA)
- Status precedence: UNRESOLVED_HIERARCHY -> MIXED_UNITS -> SOURCE_DISCREPANCY -> INSUFFICIENT_DATA -> VALID
- Structural containers (explicit parent label creates container with no invented weight)
- Recursive hierarchy (Level 1 -> Level 2 -> Level 3 preserved and displayed)
- Ambiguous parentage / duplicate parent titles -> unresolved
- Weight basis enforcement (Unknown and Within Parent are not additive overall)
- Material identity independent of weight (conflicting weights tracked on single criterion)
- Child/parent mismatch affecting status (SOURCE_DISCREPANCY)
- Stage A -> Stage B hierarchy preservation
- Stage D authoritative rebuild preventing 160% double-counting
- Mandated tests A through S
"""
import unittest
from evaluation_hierarchy import (
    UNIT_PERCENT,
    UNIT_POINTS,
    UNIT_OTHER,
    UNIT_NONE,
    BASIS_OVERALL,
    BASIS_WITHIN_PARENT,
    BASIS_UNKNOWN,
    ROLE_AWARD_CRITERION,
    ROLE_SUBCRITERION,
    ROLE_QUALIFICATION_GATE,
    ROLE_SCORING_SCALE,
    ROLE_PROCESS_STAGE,
    ROLE_STRUCTURAL_CONTAINER,
    ROLE_UNKNOWN,
    STATUS_VALID,
    STATUS_SOURCE_DISCREPANCY,
    STATUS_UNRESOLVED_HIERARCHY,
    STATUS_MIXED_UNITS,
    STATUS_INSUFFICIENT_DATA,
    parse_evaluation_weight,
    normalize_criterion_title,
    make_criterion_key,
    normalize_evaluation_criterion,
    deduplicate_evaluation_criteria,
    build_evaluation_hierarchy,
    calculate_evaluation_totals,
    format_evaluation_for_display,
)
from extractor import (
    aggregate_stage_a_facts,
    normalize_package_facts,
    apply_stage_d_authoritative_sections,
)


class TestEvaluationWeightParsing(unittest.TestCase):
    """Test deterministic weight parser cases."""

    def test_parse_percentage(self):
        val, unit, basis = parse_evaluation_weight("40%")
        self.assertEqual(val, 40.0)
        self.assertEqual(unit, UNIT_PERCENT)
        self.assertEqual(basis, BASIS_UNKNOWN)

    def test_parse_percentage_text(self):
        val, unit, basis = parse_evaluation_weight("40 percent")
        self.assertEqual(val, 40.0)
        self.assertEqual(unit, UNIT_PERCENT)
        self.assertEqual(basis, BASIS_UNKNOWN)

    def test_parse_points(self):
        val, unit, basis = parse_evaluation_weight("25 points")
        self.assertEqual(val, 25.0)
        self.assertEqual(unit, UNIT_POINTS)
        self.assertEqual(basis, BASIS_UNKNOWN)

    def test_parse_pts(self):
        val, unit, basis = parse_evaluation_weight("25 pts")
        self.assertEqual(val, 25.0)
        self.assertEqual(unit, UNIT_POINTS)
        self.assertEqual(basis, BASIS_UNKNOWN)

    def test_parse_within_parent(self):
        val, unit, basis = parse_evaluation_weight("50% within Technical")
        self.assertEqual(val, 50.0)
        self.assertEqual(unit, UNIT_PERCENT)
        self.assertEqual(basis, BASIS_WITHIN_PARENT)

    def test_parse_overall_explicit(self):
        val, unit, basis = parse_evaluation_weight("40% of overall tender score")
        self.assertEqual(val, 40.0)
        self.assertEqual(unit, UNIT_PERCENT)
        self.assertEqual(basis, BASIS_OVERALL)

    def test_bare_numbers_are_not_percentages(self):
        """Bare numbers must be parsed as UNIT_OTHER and BASIS_UNKNOWN."""
        for bare in ["40", "10", 40, 10.0]:
            val, unit, basis = parse_evaluation_weight(bare)
            self.assertEqual(unit, UNIT_OTHER)
            self.assertEqual(basis, BASIS_UNKNOWN)

    def test_pass_fail_has_no_numeric_weight(self):
        val, unit, basis = parse_evaluation_weight("Pass/Fail")
        self.assertIsNone(val)
        self.assertEqual(unit, UNIT_NONE)
        self.assertEqual(basis, BASIS_UNKNOWN)

    def test_threshold_phrase_is_not_weight(self):
        for raw in ["minimum 70% required", "threshold 50 points", "passing score 60%"]:
            val, unit, basis = parse_evaluation_weight(raw)
            self.assertIsNone(val, f"Failed for {raw}")
            self.assertEqual(unit, UNIT_NONE)

    def test_none_is_none(self):
        val, unit, basis = parse_evaluation_weight(None)
        self.assertIsNone(val)
        self.assertEqual(unit, UNIT_NONE)
        self.assertEqual(basis, BASIS_UNKNOWN)


class TestEvaluationHierarchyMandatedSuite(unittest.TestCase):
    """
    Mandated test suite covering scenarios A through S:
    A. Explicit missing parent label creates structural container.
    B. Structural container has no invented weight.
    C. Award Criteria structural container + 10/15/35/40 children gives 100 VALID.
    D. Scoring Model structural container + point-scale children does not affect overall total.
    E. Conditions of Participation structural container with thresholds does not affect overall total.
    F. Three-level hierarchy is fully preserved/displayed.
    G. Duplicate parent titles without explicit disambiguation -> unresolved.
    H. 40% with no explicit basis -> basis Unknown in parser.
    I. Bare '40' is NOT Percent.
    J. Root weight with basis Unknown is NOT added overall.
    K. Root weight with basis Within Parent is NOT added overall.
    L. Same logical criterion 40% repeated across docs -> one criterion + merged refs.
    M. Same logical criterion 40% vs 50% -> one logical criterion + conflict, not 90%.
    N. Parent 60 children 30+40 Overall -> SOURCE_DISCREPANCY.
    O. Parent 60 children 50+50 Within Parent -> valid child allocation.
    P. Process/gate roots with no weights do not invalidate a complete 100% award weighting.
    Q. Missing weight on actual Award Criterion -> INSUFFICIENT_DATA even when other award criteria sum to 100%.
    R. Stage D authoritative rebuild survives an intentionally flattened LLM response.
    S. No source numbers are silently normalized.
    """

    def test_A_structural_container_created_from_missing_parent_label(self):
        """A. Explicit missing parent label creates structural container."""
        criteria = [
            {"stage": "Social Value", "parent_stage": "Award Criteria", "weight": "10%", "weight_basis": "Overall"},
            {"stage": "Relevant Experience", "parent_stage": "Award Criteria", "weight": "15%", "weight_basis": "Overall"},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        root_stages = [r["stage"] for r in hierarchy["roots"]]
        self.assertIn("Award Criteria", root_stages)
        container = [r for r in hierarchy["roots"] if r["stage"] == "Award Criteria"][0]
        self.assertTrue(container.get("is_structural_container"))

    def test_B_structural_container_has_no_invented_weight(self):
        """B. Structural container has no invented weight or threshold."""
        criteria = [
            {"stage": "Social Value", "parent_stage": "Award Criteria", "weight": "10%", "weight_basis": "Overall", "source_doc": "ITT.pdf"},
            {"stage": "Commercial", "parent_stage": "Award Criteria", "weight": "40%", "weight_basis": "Overall", "source_doc": "ITT.pdf"},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        container = [r for r in hierarchy["roots"] if r["stage"] == "Award Criteria"][0]
        self.assertIsNone(container.get("weight"))
        self.assertIsNone(container.get("weight_value"))
        self.assertIsNone(container.get("threshold"))
        self.assertTrue(len(container.get("source_refs", [])) > 0)

    def test_C_award_criteria_container_plus_children_gives_100_valid(self):
        """C. Award Criteria structural container + 10/15/35/40 children gives 100 VALID."""
        criteria = [
            {"stage": "Social Value", "parent_stage": "Award Criteria", "weight": "10%", "weight_basis": "Overall"},
            {"stage": "Relevant Experience", "parent_stage": "Award Criteria", "weight": "15%", "weight_basis": "Overall"},
            {"stage": "Scope / Delivery", "parent_stage": "Award Criteria", "weight": "35%", "weight_basis": "Overall"},
            {"stage": "Commercial", "parent_stage": "Award Criteria", "weight": "40%", "weight_basis": "Overall"},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_VALID)
        self.assertEqual(totals["overall_total"], 100.0)
        self.assertEqual(totals["overall_unit"], UNIT_PERCENT)

    def test_D_scoring_model_container_points_does_not_affect_overall_total(self):
        """D. Scoring Model structural container + point-scale children does not affect overall total."""
        criteria = [
            {"stage": "Technical", "weight": "60%", "weight_basis": "Overall", "hierarchy_level": 1},
            {"stage": "Commercial", "weight": "40%", "weight_basis": "Overall", "hierarchy_level": 1},
            {"stage": "Scoring Scale - Excellent", "parent_stage": "Scoring Model", "weight": "10 points", "weight_basis": "Within Parent"},
            {"stage": "Scoring Scale - Good", "parent_stage": "Scoring Model", "weight": "7 points", "weight_basis": "Within Parent"},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_VALID)
        self.assertEqual(totals["overall_total"], 100.0)

    def test_E_conditions_of_participation_container_does_not_affect_overall(self):
        """E. Conditions of Participation structural container with thresholds does not affect overall total."""
        criteria = [
            {"stage": "Award Criteria", "hierarchy_level": 1},
            {"stage": "Technical", "parent_stage": "Award Criteria", "weight": "60%", "weight_basis": "Overall"},
            {"stage": "Commercial", "parent_stage": "Award Criteria", "weight": "40%", "weight_basis": "Overall"},
            {"stage": "Legal Eligibility", "parent_stage": "Conditions of Participation", "weight": None, "threshold": "Yes/No"},
            {"stage": "Financial Standing", "parent_stage": "Conditions of Participation", "weight": None, "threshold": "Pass/Fail"},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_VALID)
        self.assertEqual(totals["overall_total"], 100.0)

    def test_F_three_level_hierarchy_fully_preserved_and_displayed(self):
        """F. Three-level hierarchy (Level 1 -> Level 2 -> Level 3) is preserved and displayed."""
        criteria = [
            {"criterion_id": "root_1", "stage": "Award Framework", "hierarchy_level": 1},
            {"criterion_id": "tech_2", "parent_criterion_id": "root_1", "stage": "Technical", "weight": "60%", "weight_basis": "Overall", "hierarchy_level": 2},
            {"criterion_id": "meth_3", "parent_criterion_id": "tech_2", "stage": "Methodology", "weight": "30%", "weight_basis": "Overall", "hierarchy_level": 3},
            {"criterion_id": "team_3", "parent_criterion_id": "tech_2", "stage": "Team Experience", "weight": "30%", "weight_basis": "Overall", "hierarchy_level": 3},
            {"criterion_id": "comm_2", "parent_criterion_id": "root_1", "stage": "Commercial", "weight": "40%", "weight_basis": "Overall", "hierarchy_level": 2},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        self.assertEqual(len(hierarchy["roots"]), 1)
        root = hierarchy["roots"][0]
        self.assertEqual(len(root["children"]), 2)
        tech_node = [c for c in root["children"] if c["stage"] == "Technical"][0]
        self.assertEqual(len(tech_node["children"]), 2)

        display_rows, totals = format_evaluation_for_display(criteria)
        indents = {row["stage"]: row["indent"] for row in display_rows}
        self.assertEqual(indents["Award Framework"], 0)
        self.assertEqual(indents["Technical"], 1)
        self.assertEqual(indents["Methodology"], 2)
        self.assertEqual(indents["Team Experience"], 2)
        self.assertEqual(indents["Commercial"], 1)

    def test_G_duplicate_parent_titles_without_disambiguation_unresolved(self):
        """G. Duplicate parent titles without explicit disambiguation -> unresolved."""
        # Two distinct physical parent categories that share the same title but different source refs or IDs
        criteria = [
            {"criterion_id": "cat_1", "stage": "Category A", "hierarchy_level": 1, "source_refs": [{"source_doc": "Doc1.pdf"}]},
            {"criterion_id": "cat_2", "stage": "Category A", "hierarchy_level": 1, "source_refs": [{"source_doc": "Doc2.pdf"}]},
            {"stage": "Subcriterion", "parent_stage": "Category A", "weight": "10%"},
        ]
        # Bypassing deduplication merge for distinct candidate nodes to test tree builder disambiguation failure
        norm_criteria = [normalize_evaluation_criterion(c) for c in criteria]
        # Give them distinct canonical keys by forcing different IDs
        hierarchy = build_evaluation_hierarchy(norm_criteria)
        self.assertEqual(len(hierarchy["unresolved"]), 1)
        self.assertIn("Ambiguous parent", hierarchy["unresolved"][0]["unresolved_reason"])
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_UNRESOLVED_HIERARCHY)

    def test_H_percentage_with_no_explicit_basis_is_unknown(self):
        """H. 40% with no explicit basis -> basis Unknown in parse_evaluation_weight."""
        val, unit, basis = parse_evaluation_weight("40%")
        self.assertEqual(basis, BASIS_UNKNOWN)

    def test_I_bare_40_is_not_percent(self):
        """I. Bare '40' is NOT Percent."""
        val, unit, basis = parse_evaluation_weight("40")
        self.assertEqual(val, 40.0)
        self.assertEqual(unit, UNIT_OTHER)
        self.assertEqual(basis, BASIS_UNKNOWN)

    def test_J_root_weight_with_basis_unknown_not_added_overall(self):
        """J. Root weight with basis Unknown is NOT added overall."""
        criteria = [
            {"stage": "Technical", "weight": "60%", "weight_basis": "Unknown", "hierarchy_level": 1},
            {"stage": "Commercial", "weight": "40%", "weight_basis": "Overall", "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        # Technical has basis Unknown, so it does not add to overall total. Overall total is only 40.0 (Commercial).
        self.assertEqual(totals["overall_total"], 40.0)
        self.assertIn(totals["status"], (STATUS_SOURCE_DISCREPANCY, STATUS_INSUFFICIENT_DATA))

    def test_K_root_weight_with_basis_within_parent_not_added_overall(self):
        """K. Root weight with basis Within Parent is NOT added overall."""
        criteria = [
            {"stage": "Special Item", "weight": "50%", "weight_basis": "Within Parent", "hierarchy_level": 1},
            {"stage": "Commercial", "weight": "40%", "weight_basis": "Overall", "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        # Special Item has basis Within Parent, so it does not add to overall total. Overall total is only 40.0 (Commercial).
        self.assertEqual(totals["overall_total"], 40.0)
        self.assertIn(totals["status"], (STATUS_SOURCE_DISCREPANCY, STATUS_INSUFFICIENT_DATA))

    def test_L_same_logical_criterion_repeated_across_docs_merges(self):
        """L. Same logical criterion 40% repeated across docs -> one criterion + merged refs."""
        c1 = {"stage": "Commercial", "weight": "40%", "weight_basis": "Overall", "source_refs": [{"source_doc": "Doc1.pdf"}]}
        c2 = {"stage": "Commercial", "weight": "40%", "weight_basis": "Overall", "source_refs": [{"source_doc": "Doc2.pdf"}]}
        deduped = deduplicate_evaluation_criteria([c1, c2])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(len(deduped[0]["source_refs"]), 2)
        hierarchy = build_evaluation_hierarchy([c1, c2])
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["overall_total"], 40.0)

    def test_M_conflicting_weights_on_same_criterion_marks_conflict_not_sum(self):
        """M. Same logical criterion 40% vs 50% -> one logical criterion + conflict, not 90%."""
        c1 = {"stage": "Technical", "weight": "40%", "weight_basis": "Overall", "source_refs": [{"source_doc": "RFP.pdf"}]}
        c2 = {"stage": "Technical", "weight": "50%", "weight_basis": "Overall", "source_refs": [{"source_doc": "Addendum.pdf"}]}
        deduped = deduplicate_evaluation_criteria([c1, c2])
        self.assertEqual(len(deduped), 1)
        self.assertTrue(deduped[0]["weight_conflict"])
        self.assertEqual(len(deduped[0]["weight_observations"]), 2)

        hierarchy = build_evaluation_hierarchy([c1, c2])
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_SOURCE_DISCREPANCY)
        # Does NOT sum to 90%
        self.assertNotEqual(totals["overall_total"], 90.0)

    def test_N_child_parent_overall_mismatch_is_source_discrepancy(self):
        """N. Parent 60% children 30%+40% Overall -> SOURCE_DISCREPANCY."""
        criteria = [
            {"stage": "Technical", "weight": "60%", "weight_basis": "Overall", "hierarchy_level": 1},
            {"stage": "Tech A", "parent_stage": "Technical", "weight": "30%", "weight_basis": "Overall"},
            {"stage": "Tech B", "parent_stage": "Technical", "weight": "40%", "weight_basis": "Overall"},
            {"stage": "Commercial", "weight": "40%", "weight_basis": "Overall", "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_SOURCE_DISCREPANCY)
        self.assertTrue(any("correlation discrepancy" in w for w in totals["warnings"]))

    def test_O_child_parent_within_parent_valid_allocation(self):
        """O. Parent 60% children 50%+50% Within Parent -> valid child allocation."""
        criteria = [
            {"stage": "Technical", "weight": "60%", "weight_basis": "Overall", "hierarchy_level": 1},
            {"stage": "Quality", "parent_stage": "Technical", "weight": "50%", "weight_basis": "Within Parent"},
            {"stage": "Approach", "parent_stage": "Technical", "weight": "50%", "weight_basis": "Within Parent"},
            {"stage": "Commercial", "weight": "40%", "weight_basis": "Overall", "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_VALID)
        self.assertEqual(totals["overall_total"], 100.0)

    def test_P_process_and_gate_roots_do_not_invalidate_complete_award_weighting(self):
        """P. Process/gate roots with no weights do not invalidate a complete 100% award weighting."""
        criteria = [
            {"stage": "Stage 1: Mandatory Eligibility Check", "evaluation_role": ROLE_QUALIFICATION_GATE, "weight": None, "hierarchy_level": 1},
            {"stage": "Stage 2: Process & Governance", "evaluation_role": ROLE_PROCESS_STAGE, "weight": None, "hierarchy_level": 1},
            {"stage": "Technical", "weight": "60%", "weight_basis": "Overall", "hierarchy_level": 1},
            {"stage": "Commercial", "weight": "40%", "weight_basis": "Overall", "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_VALID)
        self.assertEqual(totals["overall_total"], 100.0)

    def test_Q_missing_weight_on_actual_award_criterion_is_insufficient_data(self):
        """Q. Missing weight on actual Award Criterion -> INSUFFICIENT_DATA even when other award criteria sum to 100%."""
        criteria = [
            {"stage": "Technical", "weight": "60%", "weight_basis": "Overall", "hierarchy_level": 1},
            {"stage": "Commercial", "weight": "40%", "weight_basis": "Overall", "hierarchy_level": 1},
            {"stage": "Sustainability & CSR", "evaluation_role": ROLE_AWARD_CRITERION, "weight": None, "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_INSUFFICIENT_DATA)

    def test_R_stage_d_authoritative_rebuild_prevents_160_double_counting(self):
        """R. Stage D authoritative rebuild survives an intentionally flattened LLM response implying 160%."""
        nf = {
            "evaluation_criteria": [
                {"stage": "Technical", "weight": "60%", "weight_basis": "Overall", "hierarchy_level": 1},
                {"stage": "Social Value", "parent_stage": "Technical", "weight": "10%", "weight_basis": "Overall", "hierarchy_level": 2},
                {"stage": "Relevant Experience", "parent_stage": "Technical", "weight": "15%", "weight_basis": "Overall", "hierarchy_level": 2},
                {"stage": "Scope / Delivery", "parent_stage": "Technical", "weight": "35%", "weight_basis": "Overall", "hierarchy_level": 2},
                {"stage": "Commercial", "weight": "40%", "weight_basis": "Overall", "hierarchy_level": 1},
            ]
        }
        flawed_llm_synthesis = {
            "brief": {
                "evaluation_breakdown": [
                    {"stage": "Technical", "weight": "60%"},
                    {"stage": "Social Value", "weight": "10%"},
                    {"stage": "Relevant Experience", "weight": "15%"},
                    {"stage": "Scope / Delivery", "weight": "35%"},
                    {"stage": "Commercial", "weight": "40%"},
                ]
            }
        }
        rebuilt = apply_stage_d_authoritative_sections(flawed_llm_synthesis, nf)
        eb = rebuilt["brief"]["evaluation_breakdown"]
        hierarchy = build_evaluation_hierarchy(eb)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_VALID)
        self.assertEqual(totals["overall_total"], 100.0)

    def test_S_no_source_numbers_are_silently_normalized(self):
        """S. Genuine 110% source discrepancy is retained and flagged as SOURCE_DISCREPANCY."""
        criteria = [
            {"stage": "Technical", "weight": "60%", "weight_basis": "Overall", "hierarchy_level": 1},
            {"stage": "Commercial", "weight": "50%", "weight_basis": "Overall", "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_SOURCE_DISCREPANCY)
        self.assertEqual(totals["overall_total"], 110.0)


class TestStageAPreservationAndDAuthoritativeRebuild(unittest.TestCase):
    """Pipeline integration tests for Stage A -> Stage B and Stage D."""

    def test_stage_a_chunk_aggregation_preserves_hierarchy(self):
        c1 = {
            "evaluation_criteria": [
                {"stage": "Technical", "hierarchy_level": 1, "weight": "60%", "source_refs": [{"source_doc": "ITT.pdf", "page": 10}]}
            ]
        }
        c2 = {
            "evaluation_criteria": [
                {"stage": "Social Value", "parent_stage": "Technical", "hierarchy_level": 2, "weight": "10%", "weight_basis": "Overall", "source_refs": [{"source_doc": "ITT.pdf", "page": 11}]}
            ]
        }
        agg = aggregate_stage_a_facts([c1, c2], filename="ITT.pdf")
        ec = agg["evaluation_criteria"]
        self.assertEqual(len(ec), 2)
        sv = [x for x in ec if x["stage"] == "Social Value"][0]
        self.assertEqual(sv["parent_stage"], "Technical")
        self.assertEqual(sv["weight_basis"], "Overall")

    def test_stage_b_deduplication_tracks_weight_conflicts(self):
        df1 = {
            "evaluation_criteria": [
                {"stage": "Technical", "weight": "70 points", "source_doc": "RFP.pdf"}
            ],
            "requirements": [], "dates": [], "submission_rules": [], "deliverables": [], "commercial_clauses": [], "contract_risks": []
        }
        df2 = {
            "evaluation_criteria": [
                {"stage": "Technical", "weight": "60 points", "source_doc": "Addendum.pdf"}
            ],
            "requirements": [], "dates": [], "submission_rules": [], "deliverables": [], "commercial_clauses": [], "contract_risks": []
        }
        norm = normalize_package_facts([df1, df2], {"doc_texts": {}})
        ec = norm["evaluation_criteria"]
        self.assertEqual(len(ec), 1)
        self.assertTrue(ec[0]["weight_conflict"])
        self.assertEqual(len(ec[0]["weight_observations"]), 2)


if __name__ == "__main__":
    unittest.main()
