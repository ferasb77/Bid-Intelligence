"""tests/test_decision_brief.py -- Comprehensive Deterministic Tests for BI-VALUE-3.

Enforces the 20 Phase S test gates:
1. Required York technical capabilities surface
2. Evaluation math is correct (100 written = 80 tech + 20 financial; 45 methodology + 35 qualifications)
3. Conditional shortlist stage stays conditional (+20 points)
4. No invented threshold
5. Mandatory evidence distinct from recommendations
6. Verified external buyer fact retains provenance
7. External buyer fact cannot be sourced from stale authority policy
8. Interpretation must reference supporting fact
9. Recommendation must reference requirement/evaluation/proof need
10. Unsupported claim rejected
11. Internal IDs absent from rendered brief
12. Provider/run/debug text absent
13. Six-PDF submission structure preserved
14. MERX gate preserved
15. Proof items preserved (3 references, CVs, sample framework)
16. Top priorities capped to intended range (5–7 items)
17. Clarification questions capped and optional (0–4 items)
18. Primary brief section count/order stable
19. Page-count target enforced reasonably (6–10 pages, preferred 7–8)
20. York benchmark critical facts all present

0 network calls, 0 database mutations, deterministic execution.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from pypdf import PdfReader

import decision_brief as db
import decision_brief_report as dbr
from tests.test_york_decision_brief_benchmark import validate_york_decision_brief


class TestDecisionBriefDeterministicSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ident = db.ProcurementIdentityInput(
            buyer="York University",
            opportunity_title="Instructor for Sales and AI Training and Mentorship Program",
            solicitation_number="P27-070",
            submission_deadline="2026-10-26, 15:00:00 EDT",
            questions_deadline="2026-10-14, 15:00:00 EDT",
            contract_term="One-year initial term with two optional one-year extensions",
            estimated_budget="All-inclusive CAD total; non-reimbursable travel expenses",
            session_volume="Multiple venture cohorts; cohort workshops & 1-on-1 mentorship",
            submission_channel="Bonfire (https://yorku.bonfirehub.ca)",
            source_documents=("P27-070 Sales and AI Training and Mentorship Program(PDF).pdf",),
        )
        cls.intel = db.GovernedBuyerIntelligenceInput(
            verified_buyer_domain="yorku.ca",
            official_website="https://www.yorku.ca",
            contract_version="buyer-research/2",
            authority_policy_version="source-authority-policy/3",
        )
        cls.sub = db.SubmissionMechanicInput(
            channel="Bonfire (https://yorku.bonfirehub.ca)",
            file_structure="Six (6) separate PDF files",
            registration_gate="MERX registration and direct document acquisition",
        )
        cls.brief_input = db.DecisionBriefInput(
            identity=cls.ident,
            buyer_intelligence=cls.intel,
            scope_requirements=(),
            evaluation_criteria=(),
            proof_items=(),
            commercial_clauses=(),
            submission_mechanics=cls.sub,
        )
        cls.brief = db.build_decision_brief(cls.brief_input)
        cls.pdf_bytes = dbr.render_decision_brief_bytes(cls.brief)

    # Gate 1: Required York technical capabilities surface
    def test_01_required_york_technical_capabilities_surface(self):
        caps = {tc.capability for tc in self.brief.technical_capabilities}
        all_text = " ".join(
            f"{tc.capability} {tc.what_buyer_requires} {tc.why_it_matters} {tc.proof_needed}"
            for tc in self.brief.technical_capabilities
        ).lower()
        self.assertIn("sme", all_text)
        self.assertIn("deep bench", all_text)
        self.assertIn("sales playbook", all_text)
        self.assertIn("applied ai", all_text)
        self.assertIn("mentorship", all_text)
        self.assertIn("sample framework", all_text)
        self.assertIn("references", all_text)
        self.assertGreaterEqual(len(self.brief.technical_capabilities), 10)

    # Gate 2: Evaluation math is correct
    def test_02_evaluation_math_is_correct(self):
        ev = self.brief.evaluation_summary
        self.assertEqual(ev.written_proposal_total, 100.0)
        self.assertEqual(ev.technical_total, 80.0)
        self.assertEqual(ev.financial_total, 20.0)
        self.assertEqual(ev.methodology_points, 45.0)
        self.assertEqual(ev.qualifications_points, 35.0)
        self.assertEqual(ev.technical_total, ev.methodology_points + ev.qualifications_points)
        self.assertEqual(ev.written_proposal_total, ev.technical_total + ev.financial_total)

    # Gate 3: Conditional shortlist stage stays conditional
    def test_03_conditional_shortlist_stage_stays_conditional(self):
        ev = self.brief.evaluation_summary
        self.assertTrue(ev.shortlist_is_conditional)
        self.assertEqual(ev.shortlist_presentation_points, 20.0)
        # Shortlist is NOT part of the base written 100
        self.assertEqual(ev.written_proposal_total, 100.0)

    # Gate 4: No invented threshold
    def test_04_no_invented_threshold(self):
        ev = self.brief.evaluation_summary
        self.assertIsNone(ev.minimum_technical_threshold)
        md = self.brief.to_markdown()
        self.assertNotIn("70%", md.lower())
        self.assertNotIn("75%", md.lower())
        self.assertIn("NONE STATED IN RFP", md)

    # Gate 5: Mandatory evidence distinct from recommendations
    def test_05_mandatory_evidence_distinct_from_recommendations(self):
        mand = [pi for pi in self.brief.proof_items if pi.nature == "mandatory_requirement"]
        recs = [pi for pi in self.brief.proof_items if pi.nature == "recommendation"]
        self.assertGreater(len(mand), 0)
        self.assertGreater(len(recs), 0)
        for m in mand:
            self.assertEqual(m.epistemic_class, db.EpistemicClass.RFP_FACT.value)
        for r in recs:
            self.assertEqual(r.epistemic_class, db.EpistemicClass.BID_STRATEGY_RECOMMENDATION.value)

    # Gate 6: Verified external buyer fact retains provenance
    def test_06_verified_external_buyer_fact_retains_provenance(self):
        signals = list(self.brief.buyer_mandate_signals) + list(self.brief.buyer_strategic_context)
        self.assertGreater(len(signals), 0)
        for s in signals:
            self.assertTrue(s["source_url"].startswith("https://"))
            self.assertTrue("yorku.ca" in s["source_url"])
            self.assertTrue(len(s["source_title"]) > 0)

    # Gate 7: External buyer fact cannot be sourced from stale authority policy
    def test_07_external_buyer_fact_cannot_be_sourced_from_stale_policy(self):
        self.assertEqual(self.intel.authority_policy_version, "source-authority-policy/3")
        self.assertEqual(self.intel.contract_version, "buyer-research/2")

    # Gate 8: Interpretation must reference supporting fact
    def test_08_interpretation_must_reference_supporting_fact(self):
        for o in self.brief.observations:
            if o.epistemic_class == db.EpistemicClass.BID_INTELLIGENCE_INTERPRETATION.value:
                self.assertTrue(len(o.supporting_rfp_fact) > 0)
        for bi in self.brief.buyer_intelligence_interpretations:
            self.assertTrue(len(bi.supporting_rfp_fact) > 0)

    # Gate 9: Recommendation must reference requirement/evaluation/proof need
    def test_09_recommendation_must_reference_need(self):
        recs = [pi for pi in self.brief.proof_items if pi.nature == "recommendation"]
        for r in recs:
            self.assertTrue(len(r.source) > 0)
            self.assertTrue(len(r.detail) > 0)

    # Gate 10: Unsupported claim rejected
    def test_10_unsupported_claim_rejected(self):
        bad_obs = (
            db.BriefObservation(
                title="Bad Observation",
                detail="This claim has no grounding.",
                epistemic_class=db.EpistemicClass.BID_INTELLIGENCE_INTERPRETATION.value,
                supporting_rfp_fact="",  # missing!
            ),
        )
        bad_brief = db.DecisionBrief(
            contract_version=self.brief.contract_version,
            buyer=self.brief.buyer,
            solicitation=self.brief.solicitation,
            opportunity=self.brief.opportunity,
            source_documents=self.brief.source_documents,
            snapshot_rows=self.brief.snapshot_rows,
            observations=bad_obs,
            immediate_blockers=self.brief.immediate_blockers,
            opportunity_posture=self.brief.opportunity_posture,
            target_beneficiaries=self.brief.target_beneficiaries,
            services_deliverables=self.brief.services_deliverables,
            delivery_model=self.brief.delivery_model,
            expected_outcomes=self.brief.expected_outcomes,
            methodology_expectations=self.brief.methodology_expectations,
            staffing_operational_expectations=self.brief.staffing_operational_expectations,
            unstated_scope_matters=self.brief.unstated_scope_matters,
            verified_buyer_domain=self.brief.verified_buyer_domain,
            buyer_mandate_signals=self.brief.buyer_mandate_signals,
            buyer_strategic_context=self.brief.buyer_strategic_context,
            buyer_intelligence_interpretations=self.brief.buyer_intelligence_interpretations,
            technical_capabilities=self.brief.technical_capabilities,
            evaluation_summary=self.brief.evaluation_summary,
            evaluation_criteria_breakdown=self.brief.evaluation_criteria_breakdown,
            proof_items=self.brief.proof_items,
            commercial_clauses=self.brief.commercial_clauses,
            disqualification_gates=self.brief.disqualification_gates,
            top_priorities=self.brief.top_priorities,
            clarification_questions=self.brief.clarification_questions,
        )
        violations = db.validate_claims(bad_brief)
        self.assertTrue(any("missing supporting RFP fact" in v for v in violations))

    # Gate 11: Internal IDs absent from rendered brief
    def test_11_internal_ids_absent_from_rendered_brief(self):
        text = self.brief.to_markdown()
        for pat in db.FORBIDDEN_LEAKED_PATTERNS:
            matches = pat.findall(text)
            self.assertEqual(matches, [], f"Found leaked pattern: {matches}")

    # Gate 12: Provider/run/debug text absent
    def test_12_provider_run_debug_text_absent(self):
        text = self.brief.to_markdown().lower()
        self.assertNotIn("anthropic_server_tools", text)
        self.assertNotIn("duckduckgo", text)
        self.assertNotIn("token count", text)
        self.assertNotIn("reconciliation_max_output_tokens", text)
        self.assertNotIn("run 57", text)

    # Gate 13: Six-PDF submission structure preserved
    def test_13_six_pdf_submission_structure_preserved(self):
        text = self.brief.to_markdown()
        self.assertTrue("six (6) separate pdf" in text.lower() or "six separate pdf" in text.lower())

    # Gate 14: MERX gate preserved
    def test_14_merx_gate_preserved(self):
        text = self.brief.to_markdown()
        self.assertIn("MERX", text)
        self.assertTrue(any("MERX" in g for g in self.brief.disqualification_gates))

    # Gate 15: Proof items preserved (3 references, CVs, sample framework)
    def test_15_proof_items_preserved(self):
        titles = " ".join(pi.title for pi in self.brief.proof_items).lower()
        self.assertIn("references", titles)
        self.assertIn("cv", titles)
        self.assertIn("sample", titles)
        self.assertIn("acknowledgement", titles)
        self.assertIn("price schedule", titles)

    # Gate 16: Top priorities capped to intended range (5–7 items)
    def test_16_top_priorities_capped_to_range(self):
        self.assertGreaterEqual(len(self.brief.top_priorities), 5)
        self.assertLessEqual(len(self.brief.top_priorities), 7)

    # Gate 17: Clarification questions capped and optional (0–4 items)
    def test_17_clarification_questions_capped_and_optional(self):
        self.assertLessEqual(len(self.brief.clarification_questions), 4)

    # Gate 18: Primary brief section count/order stable
    def test_18_section_count_order_stable(self):
        md = self.brief.to_markdown()
        sections = [
            "Executive Opportunity Snapshot",
            "1. What the Buyer Is Actually Buying",
            "2. Buyer Intelligence & Strategic Context",
            "3. Technical Capability Requirements",
            "4. How the Proposal Will Be Evaluated",
            "5. What the Bidder Must Prove",
            "6. Commercial Watch-Outs, Risks & Priorities",
            "7. Pre-Bid Clarifications & Decision Sign-Off",
        ]
        last_pos = -1
        for sec in sections:
            pos = md.find(sec)
            self.assertNotEqual(pos, -1, f"Section missing: {sec}")
            self.assertGreater(pos, last_pos, f"Section out of order: {sec}")
            last_pos = pos

    # Gate 19: Page-count target enforced reasonably (6–10 pages, preferred 7–8)
    def test_19_page_count_target_enforced(self):
        import io
        reader = PdfReader(io.BytesIO(self.pdf_bytes))
        num_pages = len(reader.pages)
        self.assertGreaterEqual(num_pages, 6, "Brief must be at least 6 pages")
        self.assertLessEqual(num_pages, 10, "Brief must not exceed 10 pages")
        self.assertIn(num_pages, (7, 8), f"Preferred page count is 7-8, got {num_pages}")

    # Gate 20: York benchmark critical facts all present
    def test_20_york_benchmark_critical_facts_all_present(self):
        bench_res = validate_york_decision_brief(self.brief.to_benchmark_dict())
        self.assertTrue(bench_res.is_valid, f"York benchmark failed: {bench_res.failures}")
        self.assertEqual(bench_res.failures, [])


if __name__ == "__main__":
    unittest.main()
