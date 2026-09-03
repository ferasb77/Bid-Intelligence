"""
Unit tests for Requirement Semantic Separation:
- Controlled requirement_type taxonomy and prompt schemas.
- Semantic type normalization and fallback resolution.
- Conflict-safe, commutative semantic type merging.
- Stage D authoritative section rebuild (Mandatory qualification gates are a strict subset of Mandatory).
- Gate-to-requirement description identity matching.
- UI counting helpers and zero-gate state.
- Bid/No-Bid requirement partitioning by database id / material description.
"""
import unittest
from requirement_semantics import (
    TYPE_SUPPLIER_QUALIFICATION,
    TYPE_TECHNICAL_SPECIFICATION,
    TYPE_SUBMISSION_COMPLIANCE,
    TYPE_DELIVERY_SLA,
    TYPE_COMMERCIAL_CONTRACTUAL,
    TYPE_EVALUATION_SCORED,
    TYPE_GENERAL_COMPLIANCE,
    ALLOWED_REQUIREMENT_TYPES,
    normalize_requirement_type,
    merge_requirement_types,
    resolve_candidate_requirement_types,
    resolve_requirement_type,
    has_supplier_qualification_evidence,
    is_supplier_qualification,
    normalize_requirement_identity_text,
    select_qualification_requirements,
    get_qualification_gate_ui_alert,
)
from extractor import (
    STAGE_A_FACT_EXTRACTION_PROMPT,
    STAGE_D_SYNTHESIS_PROMPT,
    apply_stage_d_authoritative_sections,
    _compact_requirement,
)
from analyst import bid_no_bid_score


class TestRequirementTypeDefinitionsAndPrompts(unittest.TestCase):
    """Verify prompt schema integrity and controlled taxonomy."""

    def test_allowed_types_contains_all_seven_types(self):
        self.assertEqual(len(ALLOWED_REQUIREMENT_TYPES), 7)
        self.assertIn("Supplier Qualification", ALLOWED_REQUIREMENT_TYPES)
        self.assertIn("Technical Specification", ALLOWED_REQUIREMENT_TYPES)
        self.assertIn("Submission Compliance", ALLOWED_REQUIREMENT_TYPES)
        self.assertIn("Delivery / SLA", ALLOWED_REQUIREMENT_TYPES)
        self.assertIn("Commercial / Contractual", ALLOWED_REQUIREMENT_TYPES)
        self.assertIn("Evaluation / Scored", ALLOWED_REQUIREMENT_TYPES)
        self.assertIn("General Compliance", ALLOWED_REQUIREMENT_TYPES)

    def test_stage_a_prompt_defines_requirement_type(self):
        self.assertIn('"requirement_type":', STAGE_A_FACT_EXTRACTION_PROMPT)
        self.assertIn("Supplier Qualification", STAGE_A_FACT_EXTRACTION_PROMPT)
        self.assertIn("Technical Specification", STAGE_A_FACT_EXTRACTION_PROMPT)
        self.assertIn("Submission Compliance", STAGE_A_FACT_EXTRACTION_PROMPT)
        self.assertIn("Delivery / SLA", STAGE_A_FACT_EXTRACTION_PROMPT)
        self.assertIn("Commercial / Contractual", STAGE_A_FACT_EXTRACTION_PROMPT)
        self.assertIn("Evaluation / Scored", STAGE_A_FACT_EXTRACTION_PROMPT)
        self.assertIn("General Compliance", STAGE_A_FACT_EXTRACTION_PROMPT)
        self.assertIn("CRITICAL REQUIREMENT CLASSIFICATION RULES", STAGE_A_FACT_EXTRACTION_PROMPT)

    def test_stage_d_prompt_separates_mandatory_from_qualification(self):
        self.assertIn("Mandatory does NOT automatically mean supplier qualification", STAGE_D_SYNTHESIS_PROMPT)
        self.assertIn("Supplier Qualification", STAGE_D_SYNTHESIS_PROMPT)

    def test_compact_requirement_preserves_requirement_type(self):
        req = {
            "req_id": "M1",
            "category": "Mandatory",
            "requirement_type": TYPE_TECHNICAL_SPECIFICATION,
            "description": "System must support SAML 2.0 SSO",
            "rfso_ref": "Section 4.1",
        }
        compacted = _compact_requirement(req)
        self.assertEqual(compacted.get("requirement_type"), TYPE_TECHNICAL_SPECIFICATION)


class TestRequirementTypeNormalizationAndResolution(unittest.TestCase):
    """Test conservative string normalization and deterministic fallback logic."""

    def test_normalize_requirement_type_exact_and_aliases(self):
        self.assertEqual(normalize_requirement_type("Supplier Qualification"), TYPE_SUPPLIER_QUALIFICATION)
        self.assertEqual(normalize_requirement_type("supplier_qualification"), TYPE_SUPPLIER_QUALIFICATION)
        self.assertEqual(normalize_requirement_type("bidder qualification"), TYPE_SUPPLIER_QUALIFICATION)
        self.assertEqual(normalize_requirement_type("Technical Specification"), TYPE_TECHNICAL_SPECIFICATION)
        self.assertEqual(normalize_requirement_type("technical_specifications"), TYPE_TECHNICAL_SPECIFICATION)
        self.assertEqual(normalize_requirement_type("submission compliance"), TYPE_SUBMISSION_COMPLIANCE)
        self.assertEqual(normalize_requirement_type("delivery / sla"), TYPE_DELIVERY_SLA)
        self.assertEqual(normalize_requirement_type("delivery/sla"), TYPE_DELIVERY_SLA)
        self.assertEqual(normalize_requirement_type("commercial / contractual"), TYPE_COMMERCIAL_CONTRACTUAL)
        self.assertEqual(normalize_requirement_type("evaluation / scored"), TYPE_EVALUATION_SCORED)
        self.assertEqual(normalize_requirement_type("general compliance"), TYPE_GENERAL_COMPLIANCE)

    def test_ambiguous_type_labels_return_none_not_supplier_qualification(self):
        """Ambiguous compounds must return None rather than guessing Supplier Qualification."""
        ambiguous_cases = [
            "Technical Qualification",
            "technical qualification",
            "Qualification / Technical",
            "qualification / technical",
            "Submission Qualification",
            "submission qualification",
            "Commercial Qualification",
            "commercial qualification",
            "Random Qualification String",
            "qualification",
            "technical",
            "commercial",
            "submission",
            "delivery",
        ]
        for val in ambiguous_cases:
            with self.subTest(val=val):
                self.assertIsNone(
                    normalize_requirement_type(val),
                    f"Expected None for ambiguous label '{val}', got {normalize_requirement_type(val)}"
                )

    def test_normalize_requirement_type_invalid_returns_none(self):
        self.assertIsNone(normalize_requirement_type(None))
        self.assertIsNone(normalize_requirement_type(""))
        self.assertIsNone(normalize_requirement_type(123))
        self.assertIsNone(normalize_requirement_type([]))
        self.assertIsNone(normalize_requirement_type("random gibberish"))

    def test_mandatory_alone_does_not_default_to_supplier_qualification(self):
        req = {
            "category": "Mandatory",
            "description": "The contractor must submit monthly progress reports.",
        }
        res_type = resolve_requirement_type(req)
        self.assertNotEqual(res_type, TYPE_SUPPLIER_QUALIFICATION)
        self.assertEqual(res_type, TYPE_GENERAL_COMPLIANCE)

    def test_condition_of_participation_resolves_to_supplier_qualification(self):
        req = {
            "category": "Mandatory",
            "description": "Condition of participation: Proponent must have valid corporate registration in Ontario.",
        }
        self.assertEqual(resolve_requirement_type(req), TYPE_SUPPLIER_QUALIFICATION)
        self.assertTrue(is_supplier_qualification(req))

    def test_financial_standing_resolves_to_supplier_qualification(self):
        req = {
            "category": "Mandatory",
            "description": "The bidder must demonstrate financial standing with audited balance sheets for 3 fiscal years.",
        }
        self.assertEqual(resolve_requirement_type(req), TYPE_SUPPLIER_QUALIFICATION)
        self.assertTrue(is_supplier_qualification(req))

    def test_oem_authorization_for_participation_resolves_to_supplier_qualification(self):
        req = {
            "category": "Mandatory",
            "description": "Manufacturer authorization letter from OEM required to participate in the tender.",
        }
        self.assertEqual(resolve_requirement_type(req), TYPE_SUPPLIER_QUALIFICATION)
        self.assertTrue(is_supplier_qualification(req))

    def test_technical_specification_is_non_gate(self):
        req = {
            "category": "Mandatory",
            "description": "Technical specification: Interactive display must provide 4K UHD 60Hz resolution.",
        }
        self.assertEqual(resolve_requirement_type(req), TYPE_TECHNICAL_SPECIFICATION)
        self.assertFalse(is_supplier_qualification(req))

    def test_signed_submission_form_is_non_gate(self):
        req = {
            "category": "Mandatory",
            "description": "Proponent must submit a signed submission form and submission checklist.",
        }
        self.assertEqual(resolve_requirement_type(req), TYPE_SUBMISSION_COMPLIANCE)
        self.assertFalse(is_supplier_qualification(req))

    def test_incident_sla_response_is_non_gate(self):
        req = {
            "category": "Mandatory",
            "description": "Service level agreement requires 4-hour on-site incident resolution for severity 1 outages.",
        }
        self.assertEqual(resolve_requirement_type(req), TYPE_DELIVERY_SLA)
        self.assertFalse(is_supplier_qualification(req))

    def test_liability_payment_clause_is_non_gate(self):
        req = {
            "category": "Mandatory",
            "description": "Commercial terms: payment terms net 30 days and contractor limitation of liability $5M.",
        }
        self.assertEqual(resolve_requirement_type(req), TYPE_COMMERCIAL_CONTRACTUAL)
        self.assertFalse(is_supplier_qualification(req))

    def test_generic_mandatory_compliance_is_non_gate(self):
        req = {
            "category": "Mandatory",
            "description": "Contractor must comply with all applicable environmental protection regulations.",
        }
        self.assertEqual(resolve_requirement_type(req), TYPE_GENERAL_COMPLIANCE)
        self.assertFalse(is_supplier_qualification(req))

    def test_rated_category_is_never_supplier_qualification(self):
        req = {
            "category": "Rated",
            "requirement_type": TYPE_SUPPLIER_QUALIFICATION,
            "description": "Scored evaluation of past bidder experience.",
        }
        self.assertFalse(is_supplier_qualification(req))

    def test_hard_gate_evidence_safety_barrier_cases(self):
        """
        Verify hard-gate evidence barrier:
        A: 'Bidder must possess valid trade license and tax registration.' -> True
        B: 'Vendor must be an authorized OEM tier-1 gold partner.' -> True
        C: 'Display must support 4K resolution at 60Hz and include HDMI 2.1 ports.' -> False
        D: 'All items must be brand new and not refurbished, used, or end-of-life hardware.' -> False
        E: 'Supplier must confirm no historical grounds for mandatory exclusion or debarment.' -> True
        F: 'Interactive whiteboard must be wall-mounted and delivered with 3-year warranty.' -> False
        """
        test_cases = [
            ("A", "Bidder must possess valid trade license and tax registration.", True),
            ("B", "Vendor must be an authorized OEM tier-1 gold partner.", True),
            ("C", "Display must support 4K resolution at 60Hz and include HDMI 2.1 ports.", False),
            ("D", "All items must be brand new and not refurbished, used, or end-of-life hardware.", False),
            ("E", "Supplier must confirm no historical grounds for mandatory exclusion or debarment.", True),
            ("F", "Interactive whiteboard must be wall-mounted and delivered with 3-year warranty.", False),
        ]

        for label, text, expected_gate in test_cases:
            has_ev = has_supplier_qualification_evidence({"description": text})
            self.assertEqual(
                has_ev,
                expected_gate,
                f"Case {label} has_supplier_qualification_evidence mismatch for: {text}"
            )
            # Even if Stage A erroneously labelled it Supplier Qualification:
            req = {
                "category": "Mandatory",
                "requirement_type": TYPE_SUPPLIER_QUALIFICATION,
                "description": text,
            }
            self.assertEqual(
                is_supplier_qualification(req),
                expected_gate,
                f"Case {label} is_supplier_qualification mismatch for: {text}"
            )


class TestConflictSafeSemanticMerging(unittest.TestCase):
    """Verify order-independent, commutative and associative semantic type merging."""

    def test_same_specific_types_preserve_type(self):
        self.assertEqual(
            merge_requirement_types(TYPE_SUPPLIER_QUALIFICATION, TYPE_SUPPLIER_QUALIFICATION),
            TYPE_SUPPLIER_QUALIFICATION
        )
        self.assertEqual(
            merge_requirement_types(TYPE_TECHNICAL_SPECIFICATION, TYPE_TECHNICAL_SPECIFICATION),
            TYPE_TECHNICAL_SPECIFICATION
        )

    def test_none_or_general_with_specific_preserves_specific(self):
        # Order A: None/General first, Specific second
        self.assertEqual(merge_requirement_types(None, TYPE_SUPPLIER_QUALIFICATION), TYPE_SUPPLIER_QUALIFICATION)
        self.assertEqual(merge_requirement_types(TYPE_GENERAL_COMPLIANCE, TYPE_TECHNICAL_SPECIFICATION), TYPE_TECHNICAL_SPECIFICATION)
        # Order B: Specific first, None/General second
        self.assertEqual(merge_requirement_types(TYPE_SUPPLIER_QUALIFICATION, None), TYPE_SUPPLIER_QUALIFICATION)
        self.assertEqual(merge_requirement_types(TYPE_TECHNICAL_SPECIFICATION, TYPE_GENERAL_COMPLIANCE), TYPE_TECHNICAL_SPECIFICATION)

    def test_conflicting_different_specific_types_resolves_to_general_compliance(self):
        # Order A
        res1 = merge_requirement_types(TYPE_SUPPLIER_QUALIFICATION, TYPE_TECHNICAL_SPECIFICATION)
        self.assertEqual(res1, TYPE_GENERAL_COMPLIANCE)
        # Order B (commutative)
        res2 = merge_requirement_types(TYPE_TECHNICAL_SPECIFICATION, TYPE_SUPPLIER_QUALIFICATION)
        self.assertEqual(res2, TYPE_GENERAL_COMPLIANCE)
        self.assertEqual(res1, res2)

    def test_all_permutations_commutative(self):
        types = [
            None,
            TYPE_GENERAL_COMPLIANCE,
            TYPE_SUPPLIER_QUALIFICATION,
            TYPE_TECHNICAL_SPECIFICATION,
            TYPE_SUBMISSION_COMPLIANCE,
            TYPE_DELIVERY_SLA,
            TYPE_COMMERCIAL_CONTRACTUAL,
            TYPE_EVALUATION_SCORED,
        ]
        for t1 in types:
            for t2 in types:
                r1 = merge_requirement_types(t1, t2)
                r2 = merge_requirement_types(t2, t1)
                self.assertEqual(r1, r2, f"Commutativity failed for ({t1}, {t2}): {r1} != {r2}")

    def test_n_way_candidate_aggregation_all_permutations(self):
        """
        Verify that 3+ conflicting types resolve identically to General Compliance
        under all 6 permutations.
        """
        import itertools
        conflicting_types = [
            TYPE_SUPPLIER_QUALIFICATION,
            TYPE_TECHNICAL_SPECIFICATION,
            TYPE_COMMERCIAL_CONTRACTUAL,
        ]
        for perm in itertools.permutations(conflicting_types):
            resolved = resolve_candidate_requirement_types(perm)
            self.assertEqual(
                resolved,
                TYPE_GENERAL_COMPLIANCE,
                f"Permutation {perm} did not resolve to General Compliance (got {resolved})"
            )

    def test_n_way_candidate_aggregation_with_general_and_duplicates(self):
        # General + Supplier + Supplier -> Supplier Qualification
        seq1 = [TYPE_GENERAL_COMPLIANCE, TYPE_SUPPLIER_QUALIFICATION, TYPE_SUPPLIER_QUALIFICATION]
        self.assertEqual(resolve_candidate_requirement_types(seq1), TYPE_SUPPLIER_QUALIFICATION)

        # Supplier + Technical + Supplier -> General Compliance (conflict once observed persists)
        seq2 = [TYPE_SUPPLIER_QUALIFICATION, TYPE_TECHNICAL_SPECIFICATION, TYPE_SUPPLIER_QUALIFICATION]
        self.assertEqual(resolve_candidate_requirement_types(seq2), TYPE_GENERAL_COMPLIANCE)


class TestStageDAuthoritativeSectionRebuild(unittest.TestCase):
    """
    Given a package containing 7 mandatory requirements representing each semantic type,
    verify that qualification_gates rebuilds ONLY the true Supplier Qualification gate.
    """

    def test_only_supplier_qualification_mandatory_becomes_qualification_gate(self):
        all_reqs = [
            # 1. Supplier Qualification (TRUE GATE)
            {
                "req_id": "M1",
                "category": "Mandatory",
                "requirement_type": TYPE_SUPPLIER_QUALIFICATION,
                "description": "Bidder must possess valid security clearance and OEM authorization.",
                "rfso_ref": "Sec 2.1",
            },
            # 2. Technical Specification (MANDATORY BUT NOT A GATE)
            {
                "req_id": "M2",
                "category": "Mandatory",
                "requirement_type": TYPE_TECHNICAL_SPECIFICATION,
                "description": "Smart classroom display must support 4K resolution at 60Hz.",
                "rfso_ref": "Sec 4.2",
            },
            # 3. Submission Compliance (MANDATORY BUT NOT A GATE)
            {
                "req_id": "M3",
                "category": "Mandatory",
                "requirement_type": TYPE_SUBMISSION_COMPLIANCE,
                "description": "Proponent must sign and seal Appendix B Submission Form.",
                "rfso_ref": "Sec 5.1",
            },
            # 4. Delivery / SLA (MANDATORY BUT NOT A GATE)
            {
                "req_id": "M4",
                "category": "Mandatory",
                "requirement_type": TYPE_DELIVERY_SLA,
                "description": "Vendor must provide 4-hour on-site response for severe outages.",
                "rfso_ref": "Sec 6.3",
            },
            # 5. Commercial / Contractual (MANDATORY BUT NOT A GATE)
            {
                "req_id": "M5",
                "category": "Mandatory",
                "requirement_type": TYPE_COMMERCIAL_CONTRACTUAL,
                "description": "Rates must remain firm for the entire initial 3-year term.",
                "rfso_ref": "Sec 7.1",
            },
            # 6. Evaluation / Scored (MANDATORY / SCORED CRITERIA NOT A GATE)
            {
                "req_id": "M6",
                "category": "Mandatory",
                "requirement_type": TYPE_EVALUATION_SCORED,
                "description": "Pass mark of 75% on technical proposal evaluation is mandatory.",
                "rfso_ref": "Sec 8.1",
            },
            # 7. General Compliance (MANDATORY BUT NOT A GATE)
            {
                "req_id": "M7",
                "category": "Mandatory",
                "requirement_type": TYPE_GENERAL_COMPLIANCE,
                "description": "Supplier must adhere to all local health and safety regulations.",
                "rfso_ref": "Sec 9.1",
            },
        ]

        nf = {
            "requirements": all_reqs,
            "dates": [],
            "evaluation_criteria": [],
            "submission_rules": [],
            "deliverables": [],
            "commercial_clauses": [],
            "contract_risks": [],
        }

        synth_result = apply_stage_d_authoritative_sections({}, nf)
        brief = synth_result.get("brief", {})
        gates = brief.get("qualification_gates", [])

        # Crucial assertion: Exactly 1 qualification gate extracted from 7 mandatory requirements!
        self.assertEqual(len(gates), 1)
        self.assertEqual(gates[0]["req_id"], "M1")
        self.assertEqual(gates[0]["type"], "Supplier Qualification")
        self.assertEqual(gates[0]["requirement"], all_reqs[0]["description"])

    def test_hardware_product_spec_with_supplier_qual_label_not_rebuilt_as_gate(self):
        """
        Verify that a hardware/product spec (such as 'All items must be brand new...'),
        even if carrying requirement_type == 'Supplier Qualification', is NOT rebuilt
        into qualification_gates in Stage D.
        """
        reqs = [
            {
                "req_id": "M1",
                "category": "Mandatory",
                "requirement_type": TYPE_SUPPLIER_QUALIFICATION,
                "description": "Vendors must be authorized by the respective OEM, certified, and have demonstrable experience.",
                "rfso_ref": "Section 2.1",
            },
            {
                "req_id": "M3",
                "category": "Mandatory",
                "requirement_type": TYPE_SUPPLIER_QUALIFICATION,
                "description": "All items must be brand new and not refurbished, used, or end-of-life hardware.",
                "rfso_ref": "Section 8.2 - General Requirements",
            },
        ]
        nf = {
            "requirements": reqs,
            "dates": [],
            "evaluation_criteria": [],
            "submission_rules": [],
            "deliverables": [],
            "commercial_clauses": [],
            "contract_risks": [],
        }
        synth_result = apply_stage_d_authoritative_sections({}, nf)
        brief = synth_result.get("brief", {})
        gates = brief.get("qualification_gates", [])

        self.assertEqual(len(gates), 1)
        self.assertEqual(gates[0]["req_id"], "M1")
        self.assertNotIn("All items must be brand new", [g["requirement"] for g in gates])


class TestGateToRequirementMatchingAndUIHelpers(unittest.TestCase):
    """Verify description-based matching of brief qualification gates back to persisted requirement rows."""

    def test_select_qualification_requirements_matching(self):
        persisted_reqs = [
            {"id": 101, "req_id": "M1", "category": "Mandatory", "description": "Valid vendor registration in good standing required."},
            {"id": 102, "req_id": "M1", "category": "Mandatory", "description": "Duplicate req_id but different text: ISO 9001 certification."},
            {"id": 103, "req_id": "M2", "category": "Mandatory", "description": "Interactive whiteboard 85 inch touchscreen."},
            {"id": 104, "req_id": "R1", "category": "Rated", "description": "Project manager experience exceeding 10 years."},
        ]

        brief_gates = [
            {"requirement": "Valid vendor registration in good standing required.", "type": "Supplier Qualification", "req_id": "M1"},
        ]

        matched = select_qualification_requirements(persisted_reqs, brief_gates)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["id"], 101)
        self.assertEqual(matched[0]["description"], "Valid vendor registration in good standing required.")

    def test_select_qualification_requirements_empty_gates_returns_empty(self):
        persisted_reqs = [
            {"id": 101, "req_id": "M1", "category": "Mandatory", "description": "Some mandatory requirement."},
        ]
        # Never falls back to all Mandatory!
        matched = select_qualification_requirements(persisted_reqs, [])
        self.assertEqual(matched, [])

    def test_select_qualification_requirements_does_not_match_non_mandatory(self):
        persisted_reqs = [
            {"id": 201, "req_id": "R1", "category": "Rated", "description": "Scored criteria for team credentials."},
        ]
        brief_gates = [
            {"requirement": "Scored criteria for team credentials.", "type": "Supplier Qualification"},
        ]
        matched = select_qualification_requirements(persisted_reqs, brief_gates)
        self.assertEqual(matched, [])

    def test_substring_containment_does_not_falsely_match(self):
        """A shorter gate description that is a substring of an unrelated longer Mandatory requirement must NOT match."""
        persisted_reqs = [
            {
                "id": 301,
                "req_id": "M1",
                "category": "Mandatory",
                "description": "Smart classroom setup requires installation of 75-inch interactive displays with accessories."
            }
        ]
        brief_gates = [
            {
                "requirement": "installation of 75-inch interactive displays",
                "type": "Supplier Qualification",
                "req_id": "M1"
            }
        ]
        matched = select_qualification_requirements(persisted_reqs, brief_gates)
        self.assertEqual(matched, [], "Substring containment must NOT produce a false match.")

    def test_zero_gate_ui_alert_state(self):
        """Zero gates must render a neutral informative message, never 'ALL QUALIFICATION GATES VERIFIED'."""
        alert = get_qualification_gate_ui_alert(q_total=0, q_fail=0, q_unknown=0)
        self.assertEqual(alert["state"], "ZERO_GATES")
        self.assertIn("No explicit pass/fail supplier qualification gates were identified", alert["html"])
        self.assertNotIn("ALL QUALIFICATION GATES VERIFIED", alert["html"])

        # Compare with non-zero verified
        alert_verified = get_qualification_gate_ui_alert(q_total=3, q_fail=0, q_unknown=0)
        self.assertEqual(alert_verified["state"], "ALL_VERIFIED")
        self.assertIn("ALL QUALIFICATION GATES VERIFIED", alert_verified["html"])


class TestBidNoBidRequirementPartition(unittest.TestCase):
    """Verify separation of qualification requirements and other requirements without req_id collision."""

    def test_partition_by_material_description_when_no_db_id(self):
        """
        When requirements have the same req_id (e.g. M1) but different material descriptions,
        bid_no_bid_score partitioning must preserve both without colliding on req_id alone.
        """
        qual_m1 = {
            "req_id": "M1",
            "category": "Mandatory",
            "requirement_type": TYPE_SUPPLIER_QUALIFICATION,
            "description": "Bidder must possess valid vendor license.",
            "qual_status": "PASS",
        }
        tech_m1 = {
            "req_id": "M1",
            "category": "Mandatory",
            "requirement_type": TYPE_TECHNICAL_SPECIFICATION,
            "description": "Interactive whiteboard hardware specification.",
            "qual_status": "UNKNOWN",
        }
        all_reqs = [qual_m1, tech_m1]

        # Use mock call to inspect prompt partitioning inside bid_no_bid_score
        from unittest.mock import patch

        captured_prompts = []

        def mock_call(system, user, max_tokens=2048):
            captured_prompts.append(user)
            return '{"recommendation": "GO", "confidence": "High", "overall_score": 85, "summary": "Test", "dimensions": {"qualification_alignment": 9, "technical_feasibility": 8, "commercial_viability": 8, "capacity_capability": 8, "strategic_fit": 8}, "hard_blockers": [], "conditions": [], "win_themes": [], "red_flags": []}'

        with patch("analyst._call", side_effect=mock_call):
            bid_no_bid_score({"title": "Test Bid"}, all_reqs, qualification_requirements=[qual_m1])

        self.assertEqual(len(captured_prompts), 1)
        prompt = captured_prompts[0]

        # In prompt: qual_m1 must be in TRUE SUPPLIER QUALIFICATION GATES, tech_m1 must be in OTHER PROCUREMENT REQUIREMENTS
        self.assertIn("TRUE SUPPLIER QUALIFICATION GATES", prompt)
        self.assertIn("Bidder must possess valid vendor license", prompt)
        self.assertIn("OTHER PROCUREMENT REQUIREMENTS", prompt)
        self.assertIn("Interactive whiteboard hardware specification", prompt)

        qual_section, other_section = prompt.split("OTHER PROCUREMENT REQUIREMENTS")
        self.assertIn("Bidder must possess valid vendor license", qual_section)
        self.assertNotIn("Interactive whiteboard hardware specification", qual_section)
        self.assertIn("Interactive whiteboard hardware specification", other_section)
        self.assertNotIn("Bidder must possess valid vendor license", other_section)


if __name__ == "__main__":
    unittest.main()
