"""
tests/test_evaluation_hierarchy_integrity.py

Focused unit and regression tests for evaluation hierarchy, weight parsing, deduplication,
tree construction, overall total calculations, and Stage D authoritative rebuild.
"""
import unittest
from evaluation_hierarchy import (
    parse_evaluation_weight,
    make_criterion_key,
    normalize_evaluation_criterion,
    deduplicate_evaluation_criteria,
    build_evaluation_hierarchy,
    calculate_evaluation_totals,
    format_evaluation_for_display,
    UNIT_PERCENT,
    UNIT_POINTS,
    UNIT_NONE,
    BASIS_OVERALL,
    BASIS_WITHIN_PARENT,
    BASIS_UNKNOWN,
    STATUS_VALID,
    STATUS_SOURCE_DISCREPANCY,
    STATUS_UNRESOLVED_HIERARCHY,
    STATUS_MIXED_UNITS,
    STATUS_INSUFFICIENT_DATA,
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
        self.assertEqual(basis, BASIS_OVERALL)

    def test_parse_percentage_text(self):
        val, unit, basis = parse_evaluation_weight("40 percent")
        self.assertEqual(val, 40.0)
        self.assertEqual(unit, UNIT_PERCENT)
        self.assertEqual(basis, BASIS_OVERALL)

    def test_parse_points(self):
        val, unit, basis = parse_evaluation_weight("25 points")
        self.assertEqual(val, 25.0)
        self.assertEqual(unit, UNIT_POINTS)
        self.assertEqual(basis, BASIS_OVERALL)

    def test_parse_pts(self):
        val, unit, basis = parse_evaluation_weight("25 pts")
        self.assertEqual(val, 25.0)
        self.assertEqual(unit, UNIT_POINTS)
        self.assertEqual(basis, BASIS_OVERALL)

    def test_parse_within_parent(self):
        val, unit, basis = parse_evaluation_weight("50% within Technical")
        self.assertEqual(val, 50.0)
        self.assertEqual(unit, UNIT_PERCENT)
        self.assertEqual(basis, BASIS_WITHIN_PARENT)

    def test_pass_fail_has_no_numeric_weight(self):
        val, unit, basis = parse_evaluation_weight("Pass/Fail")
        self.assertIsNone(val)
        self.assertEqual(unit, UNIT_NONE)

    def test_threshold_phrase_is_not_weight(self):
        val, unit, basis = parse_evaluation_weight("minimum 70% required")
        self.assertIsNone(val)
        self.assertEqual(unit, UNIT_NONE)

    def test_none_is_none(self):
        val, unit, basis = parse_evaluation_weight(None)
        self.assertIsNone(val)
        self.assertEqual(unit, UNIT_NONE)


class TestEvaluationHierarchyCalculations(unittest.TestCase):
    """Test mandated core evaluation hierarchy and aggregation test cases."""

    def test_A_flat_100(self):
        """TEST A — FLAT 100%: Technical 75%, Price 25% -> root total = 100%, status = VALID."""
        criteria = [
            {"stage": "Technical", "weight": "75%"},
            {"stage": "Price", "weight": "25%"},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_VALID)
        self.assertEqual(totals["overall_total"], 100.0)
        self.assertEqual(totals["overall_unit"], UNIT_PERCENT)

    def test_B_parent_plus_children_same_overall_scale(self):
        """
        TEST B — PARENT + CHILDREN, SAME OVERALL SCALE
        Technical 60%
            Social Value 10%
            Relevant Experience 15%
            Scope / Delivery 35%
        Commercial 40%
        Expected: root total = 100%, Technical child subtotal = 60%, children do NOT add again.
        """
        criteria = [
            {"stage": "Technical", "weight": "60%", "hierarchy_level": 1},
            {"stage": "Social Value", "parent_stage": "Technical", "weight": "10%", "weight_basis": "Overall", "hierarchy_level": 2},
            {"stage": "Relevant Experience", "parent_stage": "Technical", "weight": "15%", "weight_basis": "Overall", "hierarchy_level": 2},
            {"stage": "Scope / Delivery", "parent_stage": "Technical", "weight": "35%", "weight_basis": "Overall", "hierarchy_level": 2},
            {"stage": "Commercial", "weight": "40%", "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        self.assertEqual(len(hierarchy["roots"]), 2)
        tech_root = next(r for r in hierarchy["roots"] if r["stage"] == "Technical")
        self.assertEqual(len(tech_root["children"]), 3)

        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_VALID)
        self.assertEqual(totals["overall_total"], 100.0)
        self.assertNotEqual(totals["overall_total"], 160.0)
        self.assertEqual(totals["child_details"]["Technical"]["subtotal"], 60.0)

    def test_C_parent_plus_children_within_parent(self):
        """
        TEST C — PARENT + CHILDREN WITHIN PARENT
        Technical 60% overall
            Quality 50% within parent
            Methodology 50% within parent
        Commercial 40%
        Expected: overall total = 100%, Technical child allocation = 100% within parent.
        """
        criteria = [
            {"stage": "Technical", "weight": "60%", "weight_basis": "Overall", "hierarchy_level": 1},
            {"stage": "Quality", "parent_stage": "Technical", "weight": "50%", "weight_basis": "Within Parent", "hierarchy_level": 2},
            {"stage": "Methodology", "parent_stage": "Technical", "weight": "50%", "weight_basis": "Within Parent", "hierarchy_level": 2},
            {"stage": "Commercial", "weight": "40%", "weight_basis": "Overall", "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_VALID)
        self.assertEqual(totals["overall_total"], 100.0)
        self.assertEqual(totals["child_details"]["Technical"]["subtotal"], 100.0)

    def test_D_parent_child_same_weight_pricing_approach(self):
        """
        TEST D — PARENT / CHILD SAME WEIGHT
        Commercial 40%
            Pricing Approach 40%
        Expected: overall contribution = 40%, NOT 80%.
        """
        criteria = [
            {"stage": "Commercial", "weight": "40%", "hierarchy_level": 1},
            {"stage": "Pricing Approach", "parent_stage": "Commercial", "weight": "40%", "weight_basis": "Overall", "hierarchy_level": 2},
            {"stage": "Technical", "weight": "60%", "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_VALID)
        self.assertEqual(totals["overall_total"], 100.0)
        self.assertNotEqual(totals["overall_total"], 140.0)

    def test_E_genuine_source_discrepancy_110(self):
        """
        TEST E — GENUINE 110%
        Technical 60%, Commercial 50%, both roots.
        Expected: total = 110%, status = SOURCE_DISCREPANCY. Do NOT normalize.
        """
        criteria = [
            {"stage": "Technical", "weight": "60%", "hierarchy_level": 1},
            {"stage": "Commercial", "weight": "50%", "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_SOURCE_DISCREPANCY)
        self.assertEqual(totals["overall_total"], 110.0)

    def test_F_mixed_units(self):
        """
        TEST F — MIXED UNITS
        Technical 60%, Commercial 40 points.
        Expected: no combined arithmetic total, status = MIXED_UNITS.
        """
        criteria = [
            {"stage": "Technical", "weight": "60%", "hierarchy_level": 1},
            {"stage": "Commercial", "weight": "40 points", "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_MIXED_UNITS)
        self.assertIsNone(totals["overall_total"])

    def test_G_missing_weights(self):
        """
        TEST G — MISSING WEIGHTS
        Technical 60%, Commercial weight missing.
        Expected: do not invent Commercial weight, overall total not asserted complete, status = INSUFFICIENT_DATA.
        """
        criteria = [
            {"stage": "Technical", "weight": "60%", "hierarchy_level": 1},
            {"stage": "Commercial", "weight": None, "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_INSUFFICIENT_DATA)

    def test_H_threshold_is_not_weight(self):
        """
        TEST H — THRESHOLD IS NOT WEIGHT
        Technical Proposal: threshold = 70%, weight = null.
        Expected: 70% is NOT included in evaluation weighting.
        """
        criteria = [
            {"stage": "Technical Proposal", "threshold": "70%", "weight": None, "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_INSUFFICIENT_DATA)
        self.assertIsNone(hierarchy["roots"][0]["weight_value"])

    def test_I_duplicate_across_documents(self):
        """
        TEST I — DUPLICATE ACROSS DOCUMENTS
        Commercial — 40% appears in two physical procurement documents.
        Expected: one normalized criterion, all valid source refs preserved, overall contribution = 40%.
        """
        doc1 = {"stage": "Commercial", "weight": "40%", "source_refs": [{"source_doc": "ITT.pdf", "page": 10}]}
        doc2 = {"stage": "Commercial", "weight": "40%", "source_refs": [{"source_doc": "Annex_2.docx", "page": 2}]}
        deduped = deduplicate_evaluation_criteria([doc1, doc2])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(len(deduped[0]["source_refs"]), 2)
        docs = [r["source_doc"] for r in deduped[0]["source_refs"]]
        self.assertIn("ITT.pdf", docs)
        self.assertIn("Annex_2.docx", docs)

    def test_J_same_title_different_parents(self):
        """
        TEST J — SAME TITLE, DIFFERENT PARENTS
        Experience — 20% under Category A and Experience — 10% under Category B.
        Expected: two distinct criteria.
        """
        c1 = {"stage": "Experience", "parent_stage": "Category A", "weight": "20%", "hierarchy_level": 2}
        c2 = {"stage": "Experience", "parent_stage": "Category B", "weight": "10%", "hierarchy_level": 2}
        deduped = deduplicate_evaluation_criteria([c1, c2])
        self.assertEqual(len(deduped), 2)

    def test_K_uncertain_parentage(self):
        """
        TEST K — UNCERTAIN PARENTAGE
        Criterion references a non-existent parent.
        Expected: placed in unresolved, status = UNRESOLVED_HIERARCHY.
        """
        criteria = [
            {"stage": "Technical Approach", "parent_stage": "NonExistentSection", "weight": "30%", "hierarchy_level": 2},
            {"stage": "Commercial", "weight": "40%", "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        self.assertEqual(len(hierarchy["unresolved"]), 1)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertEqual(totals["status"], STATUS_UNRESOLVED_HIERARCHY)

    def test_L_child_parent_source_discrepancy(self):
        """
        TEST L — CHILD/PARENT SOURCE DISCREPANCY
        Technical 60%, children stated as overall: 30% + 40% = 70%.
        Expected: parent = 60, children = 70, flag discrepancy, do not alter numbers.
        """
        criteria = [
            {"stage": "Technical", "weight": "60%", "hierarchy_level": 1},
            {"stage": "Part 1", "parent_stage": "Technical", "weight": "30%", "weight_basis": "Overall", "hierarchy_level": 2},
            {"stage": "Part 2", "parent_stage": "Technical", "weight": "40%", "weight_basis": "Overall", "hierarchy_level": 2},
            {"stage": "Commercial", "weight": "40%", "hierarchy_level": 1},
        ]
        hierarchy = build_evaluation_hierarchy(criteria)
        totals = calculate_evaluation_totals(hierarchy)
        self.assertTrue(any("sum to 70.0% overall, but parent states 60.0%" in w for w in totals["warnings"]))


class TestStageAPreservationAndDAuthoritativeRebuild(unittest.TestCase):
    """Test Stage A -> Stage B preservation and Stage D authoritative rebuild."""

    def test_stage_a_chunk_aggregation_preserves_hierarchy(self):
        """Verify chunk aggregation preserves parent, weight basis, and source_refs."""
        chunk1 = {
            "evaluation_criteria": [
                {"stage": "Technical", "weight": "60%", "hierarchy_level": 1, "weight_basis": "Overall"},
                {"stage": "Social Value", "parent_stage": "Technical", "weight": "10%", "hierarchy_level": 2, "weight_basis": "Overall"},
            ]
        }
        chunk2 = {
            "evaluation_criteria": [
                {"stage": "Commercial", "weight": "40%", "hierarchy_level": 1, "weight_basis": "Overall"},
            ]
        }
        res = aggregate_stage_a_facts([chunk1, chunk2], "ITT.pdf")
        ec = res["evaluation_criteria"]
        self.assertEqual(len(ec), 3)
        stages = [x["stage"] for x in ec]
        self.assertIn("Technical", stages)
        self.assertIn("Social Value", stages)
        self.assertIn("Commercial", stages)
        sv = next(x for x in ec if x["stage"] == "Social Value")
        self.assertEqual(sv["parent_stage"], "Technical")
        self.assertEqual(sv["weight_basis"], "Overall")

    def test_stage_b_deduplication_preserves_distinct_weights(self):
        """Verify Stage B deduplication keeps same stage with differing weights."""
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
        self.assertEqual(len(ec), 2)
        weights = [x["weight"] for x in ec]
        self.assertIn("70 points", weights)
        self.assertIn("60 points", weights)

    def test_stage_d_authoritative_rebuild_prevents_160_double_counting(self):
        """
        Supply normalized facts with parent 60% and children 10%, 15%, 35% + commercial 40%.
        Have an intentionally WRONG LLM Stage D response containing flattened rows implying 160%.
        Verify authoritative post-processing preserves full hierarchy and computes overall total as 100%.
        """
        nf = {
            "evaluation_criteria": [
                {"stage": "Technical", "weight": "60%", "hierarchy_level": 1},
                {"stage": "Social Value", "parent_stage": "Technical", "weight": "10%", "weight_basis": "Overall", "hierarchy_level": 2},
                {"stage": "Relevant Experience", "parent_stage": "Technical", "weight": "15%", "weight_basis": "Overall", "hierarchy_level": 2},
                {"stage": "Scope / Delivery", "parent_stage": "Technical", "weight": "35%", "weight_basis": "Overall", "hierarchy_level": 2},
                {"stage": "Commercial", "weight": "40%", "hierarchy_level": 1},
            ],
            "requirements": [], "dates": [], "submission_rules": [], "deliverables": [], "commercial_clauses": [], "contract_risks": []
        }

        # Intentionally wrong LLM response flattening everything
        synth_data = {
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

        result = apply_stage_d_authoritative_sections(synth_data, nf)
        eb = result["brief"]["evaluation_breakdown"]
        
        # Verify hierarchy preserved in rebuilt breakdown
        display_rows, totals = format_evaluation_for_display(eb)
        self.assertEqual(totals["status"], STATUS_VALID)
        self.assertEqual(totals["overall_total"], 100.0)
        self.assertNotEqual(totals["overall_total"], 160.0)

    def test_stage_d_authoritative_rebuild_preserves_genuine_110(self):
        """
        Supply normalized facts with genuine source discrepancy (60% + 50% = 110%).
        Verify authoritative post-processing does NOT force or normalize it to 100%.
        """
        nf = {
            "evaluation_criteria": [
                {"stage": "Technical", "weight": "60%", "hierarchy_level": 1},
                {"stage": "Commercial", "weight": "50%", "hierarchy_level": 1},
            ],
            "requirements": [], "dates": [], "submission_rules": [], "deliverables": [], "commercial_clauses": [], "contract_risks": []
        }
        result = apply_stage_d_authoritative_sections({}, nf)
        eb = result["brief"]["evaluation_breakdown"]
        display_rows, totals = format_evaluation_for_display(eb)
        self.assertEqual(totals["status"], STATUS_SOURCE_DISCREPANCY)
        self.assertEqual(totals["overall_total"], 110.0)


if __name__ == "__main__":
    unittest.main()
