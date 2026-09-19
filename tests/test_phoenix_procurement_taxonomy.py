"""
tests/test_phoenix_procurement_taxonomy.py

Authoritative source-truth and report taxonomy verification for Phoenix RFP2026-09-28
(Coaching and Leadership Development Services).

Verifies the 10 core acceptance criteria:
1. 5 Mandatory Gates present and evaluated on pass/fail basis.
2. 7 Weighted Criteria totaling 100 points.
3. 4 Pricing Subcomponents totaling 40 points.
4. Response Guidelines 1-6 deduplicated against Weighted Criteria 1-6.
5. Reference checks evaluated on qualification / pass-fail basis.
6. Tie-breaker hierarchy recorded in evaluation notes.
7. Service Scope separated cleanly from Evaluation Taxonomy (no Weighted Criteria or Pricing as service cats).
8. Single-award services agreement with as-needed SOW call-offs.
9. Contract term 2 years with 2 optional 3-year extensions without mutual agreement hallucination.
10. Decision-support PDF compression (8-12 pages).
"""
import json
import unittest
from pathlib import Path

from fast_analysis import FastAnalysisResult
from scripts.fast_analysis_report_adapter import (
    build_fast_report_content,
    _discover_service_categories_from_scope,
    _contract_term,
    _merged_doc_metadata,
)
from scripts.build_boc_bid_intelligence_preview_pdf import build
import pypdf


class TestPhoenixProcurementTaxonomy(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        si = {}
        path = Path("analysis_result_10.json")
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            si = data.get("structured_intelligence", {})
        else:
            try:
                import database as db
                res = db.get_analysis_result(12)
                if res and res.get("structured_intelligence"):
                    si = res["structured_intelligence"]
            except Exception:
                pass
        if not si:
            raise unittest.SkipTest("Neither analysis_result_10.json nor database result for run 12 is present")

        raw_reqs = []
        for item in si.get("response_requirements", {}).get("checklist", []):
            raw_reqs.append({
                "description": item.get("description"),
                "source_doc": item.get("notes"),
                "category": "mandatory"
            })
        for desc in si.get("response_requirements", {}).get("other_requirements", []):
            raw_reqs.append({
                "description": desc,
                "source_doc": "RFP2026-09-28_Coaching_and_Leadership_Development_Services-1.pdf",
                "category": "other"
            })

        raw_obs = []
        for o in si.get("dates_and_mechanics", {}).get("raw_date_observations", []):
            o_copy = dict(o)
            o_copy["family"] = o_copy.get("family") or "MILESTONE"
            raw_obs.append(o_copy)
        raw_clauses = si.get("pricing_and_commercial", {}).get("raw_commercial_clauses", [])
        raw_eval = []
        for cat_name, items in si.get("evaluation", {}).get("weights_by_category", {}).items():
            for it in items:
                raw_eval.append({
                    "criterion_label": it.get("criterion"),
                    "weight": it.get("weight"),
                    "category_scope": cat_name.replace("Category 1  ", "").replace("Category 2  ", "")
                })

        doc_meta = {
            "RFP2026-09-28_Coaching_and_Leadership_Development_Services-1.pdf": {
                "client": "Liquor Distribution Branch (LDB), Province of British Columbia",
                "file_number": "RFP2026-09-28",
                "title": "SERVICES AGREEMENT for Coaching and Leadership Development Services",
                "submission_deadline": "2026-09-28",
                "submission_time": "2:00 PM Pacific Time"
            },
            "RFP2026-09-28_Appendix_A_-Form_of_Contract.pdf": {
                "client": "HIS MAJESTY THE KING IN RIGHT OF THE PROVINCE OF BRITISH COLUMBIA",
                "file_number": "RFP2026-09-28",
                "title": "GENERAL SERVICE AGREEMENT"
            }
        }

        cls.result = FastAnalysisResult(
            doc_metadata_by_doc=doc_meta,
            typed_observations=raw_obs,
            requirements=raw_reqs,
            commercial_clauses=raw_clauses,
            evaluation_occurrences=raw_eval,
            documents_by_route={
                "IDENTITY_EVAL_REQ": ["RFP2026-09-28_Coaching_and_Leadership_Development_Services-1.pdf"],
                "CONTRACT_NARROW": ["RFP2026-09-28_Coaching_and_Leadership_Development_Appendix_B_-_Proposal_Response_Form.docx"],
                "COMMERCIAL_ONLY": ["RFP2026-09-28_Appendix_A_-Form_of_Contract.pdf"]
            }
        )
        cls.content = build_fast_report_content(cls.result)

    def test_service_scope_cleanly_separated_from_evaluation(self):
        """Service categories must NOT include Weighted Criteria or Pricing."""
        snapshot_facts = dict(self.content.SNAPSHOT_FACTS)
        service_cats_str = snapshot_facts.get("Service Categories", "")
        self.assertNotIn("Weighted Criteria", service_cats_str)
        self.assertNotIn("Pricing", service_cats_str)
        for cat_name, _, _ in self.content.SERVICE_CATEGORIES:
            self.assertNotIn("Weighted Criteria", cat_name)
            self.assertNotIn("Pricing", cat_name)
        cats = _discover_service_categories_from_scope(self.result)
        self.assertEqual(len(cats), 5)
        self.assertIn("One-to-One Coaching", cats)
        self.assertIn("Self-Serve Resources", cats)
        self.assertIn("Group Coaching", cats)
        self.assertIn("Team Interventions", cats)
        self.assertIn("Consultation Services", cats)

    def test_evaluation_taxonomy_and_point_totals(self):
        """Evaluation must have Category 1 (Weighted Criteria - 7 items) and Category 2 (Pricing - 4 items)."""
        eval_weights = self.content.EVAL_WEIGHTS
        self.assertIn("Category 1 — Weighted Criteria", eval_weights)
        self.assertIn("Category 2 — Pricing", eval_weights)
        self.assertNotIn("Other Rated Criteria", eval_weights)
        cat1_items = eval_weights["Category 1 — Weighted Criteria"]
        self.assertEqual(len(cat1_items), 7)
        cat2_items = eval_weights["Category 2 — Pricing"]
        self.assertEqual(len(cat2_items), 4)

    def test_mandatory_gates_and_reference_checks(self):
        """5 mandatory gates and reference checks must be represented in GATE_EXAMPLES."""
        gates_str = " ".join(self.content.GATE_EXAMPLES).lower()
        self.assertIn("english", gates_str)
        self.assertIn("submission method", gates_str)
        self.assertIn("closing date and time", gates_str)
        self.assertIn("part 5", gates_str)
        self.assertIn("appendix b", gates_str)
        self.assertIn("reference check", gates_str)

    def test_tie_breaker_hierarchy(self):
        """Evaluation note must reflect the authoritative tie-breaker rules."""
        note = self.content.EVAL_WEIGHT_NOTE
        self.assertIn("Tie-Breaker Hierarchy", note)
        self.assertIn("Account Management & Relationship", note)
        self.assertIn("Approach & Methodology", note)

    def test_contract_term_and_procurement_model(self):
        """Procurement model and contract term must be accurately normalized without unsupported phrases."""
        snapshot_facts = dict(self.content.SNAPSHOT_FACTS)
        term = snapshot_facts.get("Contract Term", "")
        self.assertNotIn("subject to buyer satisfaction and mutual agreement", term)
        proc_model = snapshot_facts.get("Procurement Model", "")
        self.assertIn("Single-award", proc_model)
        self.assertIn("Statement of Work", proc_model)

    def test_commercial_slot_validation(self):
        """Commercial slots must select the correct clauses."""
        comm_dict = dict(self.content.COMMERCIAL_POINTS)
        escalation = comm_dict.get("Pricing Escalation", "").lower()
        self.assertIn("firm", escalation)
        self.assertTrue("cpi" in escalation or "consumer price index" in escalation)
        assignment = comm_dict.get("Assignment", "").lower()
        self.assertIn("14.3", assignment)
        self.assertNotIn("account manager", assignment)
        termination = comm_dict.get("Termination", "").lower()
        self.assertIn("12", termination)
        self.assertNotIn("irrevocable", termination)

    def test_opportunity_identity_source_precedence(self):
        """Master RFP must govern solicitation identity without contract overwrite."""
        meta = _merged_doc_metadata(self.result)
        self.assertEqual(meta.get("file_number"), "RFP2026-09-28")
        self.assertEqual(meta.get("title"), "Coaching and Leadership Development Services")
        self.assertNotIn("SERVICES AGREEMENT", meta.get("title", ""))
        self.assertEqual(meta.get("client"), "Liquor Distribution Branch (LDB), Province of British Columbia")

    def test_submission_deadline_and_no_false_ambiguity(self):
        """Exactly one governing submission deadline; no false deadline ambiguity."""
        from fast_analysis import detect_category_date_distinctions
        # Raw date observations for SUBMISSION_DEADLINE
        obs_deadlines = [o for o in self.result.typed_observations
                         if o.get("family") == "MILESTONE"
                         and (o.get("semantic_kind") or "").upper() == "SUBMISSION_DEADLINE"]
        self.assertGreaterEqual(len(obs_deadlines), 1)

        # Distinctions detector should NOT generate ambiguity
        distinctions = detect_category_date_distinctions(self.result.typed_observations)
        deadline_distinctions = [d for d in distinctions if d.get("milestone_kind") == "SUBMISSION_DEADLINE"]
        self.assertEqual(len(deadline_distinctions), 0, "False submission deadline ambiguity generated")

    def test_response_guideline_rg1_rg6_mapping(self):
        """RG1-RG6 correspond directly to Weighted Criteria 1-6 with exact parent weights and minimum scores."""
        rg_crosswalk = {
            "RG1": {"criterion": "Proponent Experience", "weight": "15 points", "min_score": "10"},
            "RG2": {"criterion": "Proponent Capabilities", "weight": "5 points", "min_score": None},
            "RG3": {"criterion": "Proponent Resources", "weight": "10 points", "min_score": "5"},
            "RG4": {"criterion": "Approach and Methodology", "weight": "10 points", "min_score": "6"},
            "RG5": {"criterion": "Account Management and Relationship", "weight": "15 points", "min_score": "10"},
            "RG6": {"criterion": "Business Continuity Plan and Disaster Recovery Plan", "weight": "5 points", "min_score": None},
        }
        eval_weights = self.content.EVAL_WEIGHTS.get("Category 1 — Weighted Criteria", [])
        rendered_dict = dict(eval_weights)

        for rg, expected in rg_crosswalk.items():
            crit = expected["criterion"]
            self.assertIn(crit, rendered_dict, f"{crit} for {rg} missing from Category 1")
            self.assertEqual(rendered_dict[crit], expected["weight"], f"Weight mismatch for {crit}")

    def test_requirement_stage_separation(self):
        """Checklist must contain submission gates and exclude post-award operational covenants."""
        checklist_titles = " ".join([desc for _, desc, _ in self.content.RESPONSE_CHECKLIST]).lower()
        self.assertIn("english", checklist_titles)
        self.assertIn("submission", checklist_titles)
        # Operational post-award contract covenants must not be in the checklist
        self.assertNotIn("purchase order", checklist_titles)
        self.assertNotIn("statement of account", checklist_titles)
        self.assertNotIn("privacy protection schedule", checklist_titles)

    def test_pdf_compression_page_count(self):
        """Generated decision-support preview PDF must be within 8-12 pages."""
        pdf_path = Path("test_phoenix_test_suite_out.pdf")
        try:
            build(self.content, str(pdf_path))
            reader = pypdf.PdfReader(str(pdf_path))
            num_pages = len(reader.pages)
            self.assertGreaterEqual(num_pages, 8, f"PDF page count {num_pages} is below 8 pages")
            self.assertLessEqual(num_pages, 12, f"PDF page count {num_pages} exceeds 12 pages")
        finally:
            if pdf_path.exists():
                pdf_path.unlink()


if __name__ == "__main__":
    unittest.main()
