"""
Unit tests for Requirement Semantic Separation:
- Controlled requirement_type taxonomy and prompt schemas.
- Semantic type normalization and fallback resolution.
- Stage D authoritative section rebuild (Mandatory qualification gates are a strict subset of Mandatory).
- Gate-to-requirement description identity matching.
- UI counting helpers and decision console separation.
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
    resolve_requirement_type,
    is_supplier_qualification,
    normalize_requirement_identity_text,
    select_qualification_requirements,
)
from extractor import (
    STAGE_A_FACT_EXTRACTION_PROMPT,
    STAGE_D_SYNTHESIS_PROMPT,
    apply_stage_d_authoritative_sections,
    _compact_requirement,
)


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
    """Test string normalization and deterministic fallback logic."""

    def test_normalize_requirement_type_variants(self):
        self.assertEqual(normalize_requirement_type("Supplier Qualification"), TYPE_SUPPLIER_QUALIFICATION)
        self.assertEqual(normalize_requirement_type("supplier_qualification"), TYPE_SUPPLIER_QUALIFICATION)
        self.assertEqual(normalize_requirement_type("Technical Specification"), TYPE_TECHNICAL_SPECIFICATION)
        self.assertEqual(normalize_requirement_type("technical"), TYPE_TECHNICAL_SPECIFICATION)
        self.assertEqual(normalize_requirement_type("submission compliance"), TYPE_SUBMISSION_COMPLIANCE)
        self.assertEqual(normalize_requirement_type("delivery / sla"), TYPE_DELIVERY_SLA)
        self.assertEqual(normalize_requirement_type("delivery/sla"), TYPE_DELIVERY_SLA)
        self.assertEqual(normalize_requirement_type("commercial / contractual"), TYPE_COMMERCIAL_CONTRACTUAL)
        self.assertEqual(normalize_requirement_type("evaluation / scored"), TYPE_EVALUATION_SCORED)
        self.assertEqual(normalize_requirement_type("general compliance"), TYPE_GENERAL_COMPLIANCE)

    def test_normalize_requirement_type_invalid_returns_none(self):
        self.assertIsNone(normalize_requirement_type(None))
        self.assertIsNone(normalize_requirement_type(""))
        self.assertIsNone(normalize_requirement_type(123))
        self.assertIsNone(normalize_requirement_type("random gibberish"))

    def test_mandatory_alone_does_not_default_to_supplier_qualification(self):
        req = {
            "category": "Mandatory",
            "description": "The contractor must submit monthly progress reports.",
        }
        res_type = resolve_requirement_type(req)
        self.assertNotEqual(res_type, TYPE_SUPPLIER_QUALIFICATION)
        self.assertEqual(res_type, TYPE_GENERAL_COMPLIANCE)

    def test_strong_eligibility_cues_resolve_to_supplier_qualification(self):
        req1 = {
            "category": "Mandatory",
            "description": "Conditions of participation: Bidder must have minimum 5 years corporate experience.",
        }
        self.assertEqual(resolve_requirement_type(req1), TYPE_SUPPLIER_QUALIFICATION)
        self.assertTrue(is_supplier_qualification(req1))

        req2 = {
            "category": "Mandatory",
            "description": "Manufacturer authorization letter required to bid.",
        }
        self.assertEqual(resolve_requirement_type(req2), TYPE_SUPPLIER_QUALIFICATION)
        self.assertTrue(is_supplier_qualification(req2))

    def test_rated_category_is_never_supplier_qualification(self):
        req = {
            "category": "Rated",
            "requirement_type": TYPE_SUPPLIER_QUALIFICATION,
            "description": "Scored evaluation of past bidder experience.",
        }
        self.assertFalse(is_supplier_qualification(req))


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


if __name__ == "__main__":
    unittest.main()
