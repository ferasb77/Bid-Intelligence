import json
import os
import unittest

from extractor import (
    build_stage_d_context,
    apply_stage_d_authoritative_sections,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_req(req_id, category, description, rfso_ref=None, requirement_type="Supplier Qualification"):
    return {
        "req_id":          req_id,
        "category":        category,
        "requirement_type": requirement_type,
        "description":     description,
        "rfso_ref":        rfso_ref,
        "weight":          None,
        "evidence":        None,
        "source_refs":     [{"source_doc": "Doc_" + category + ".pdf", "page": 1,
                             "sheet": None, "section": "Requirements",
                             "excerpt": description[:80]}],
        "qual_status":     "UNKNOWN",
        "evidence_status": "MISSING",
    }


def _large_normalized_facts(n_mandatory=40, n_rated=25, n_financial=5, n_supporting=20):
    reqs = []
    for i in range(1, n_mandatory + 1):
        reqs.append(_make_req(
            "M" + str(i), "Mandatory",
            "Mandatory requirement " + str(i) + ": supplier eligibility and conditions of participation " + str(i) + "."))
    for i in range(1, n_rated + 1):
        reqs.append(_make_req(
            "R" + str(i), "Rated",
            "Rated criterion " + str(i) + ": evaluate approach to service area " + str(i) + ".",
            rfso_ref="Appendix D, CR" + str(i)))
    for i in range(1, n_financial + 1):
        reqs.append(_make_req(
            "F" + str(i), "Financial",
            "Financial requirement " + str(i) + ": provide loaded rate for stream " + str(i) + "."))
    for i in range(1, n_supporting + 1):
        reqs.append(_make_req(
            "S" + str(i), "Supporting",
            "Supporting document " + str(i) + ": signed attestation form " + str(i) + "."))
    return {
        "doc_metadata":        {"title": "Large Package RFP", "client": "Test Department"},
        "requirements":        reqs,
        "dates":               [{"milestone": "Bid Closing", "date": "2026-12-01"}],
        "evaluation_criteria": [{"stage": "Technical", "weight": "70 points",
                                 "threshold": "50%", "notes": ""}],
        "submission_rules":    [{"item": "Technical Proposal", "format": "PDF",
                                 "details": "Max 50 pages"}],
        "deliverables":        [{"title": "Status Reports",
                                 "description": "Monthly reports", "category": "Core"}],
        "commercial_clauses":  [{"topic": "Rate Adjustment", "details": "CPI cap 3%"}],
        "contract_risks":      [{"risk": "Scope Creep", "severity": "Medium",
                                 "details": "SOW may expand."}],
    }


# ---------------------------------------------------------------------------
# Scenario 1: Large-package context builder (>15 requirements)
# ---------------------------------------------------------------------------

class TestStageDContextBuilderLargePackage(unittest.TestCase):
    """
    Verify that build_stage_d_context() includes ALL requirements in a package
    with 40 Mandatory + 25 Rated + 5 Financial + 20 Supporting = 90 requirements,
    well above the old [:15] slice limit.
    """

    N_MANDATORY  = 40
    N_RATED      = 25
    N_FINANCIAL  = 5
    N_SUPPORTING = 20

    def setUp(self):
        self.nf = _large_normalized_facts(
            self.N_MANDATORY, self.N_RATED, self.N_FINANCIAL, self.N_SUPPORTING)
        self.ctx = build_stage_d_context(self.nf, [])
        self.total = self.N_MANDATORY + self.N_RATED + self.N_FINANCIAL + self.N_SUPPORTING

    def test_source_count_matches_total(self):
        self.assertEqual(
            self.ctx["context_integrity"]["source_requirement_count"], self.total)

    def test_included_count_equals_source_count(self):
        ci = self.ctx["context_integrity"]
        self.assertEqual(ci["included_requirement_count"], ci["source_requirement_count"])

    def test_omitted_count_is_zero(self):
        self.assertEqual(self.ctx["context_integrity"]["omitted_requirement_count"], 0)

    def test_all_mandatory_included_flag(self):
        self.assertTrue(self.ctx["context_integrity"]["all_mandatory_included"])

    def test_all_financial_included_flag(self):
        self.assertTrue(self.ctx["context_integrity"]["all_financial_included"])

    def test_mandatory_count(self):
        self.assertEqual(
            len(self.ctx["requirements"]["mandatory"]), self.N_MANDATORY)

    def test_rated_count(self):
        self.assertEqual(
            len(self.ctx["requirements"]["rated"]), self.N_RATED)

    def test_financial_count(self):
        self.assertEqual(
            len(self.ctx["requirements"]["financial"]), self.N_FINANCIAL)

    def test_supporting_count(self):
        self.assertEqual(
            len(self.ctx["requirements"]["supporting"]), self.N_SUPPORTING)

    def test_mandatory_at_position_16_present(self):
        """M16 must not be lost to the old [:15] truncation."""
        ids = {r.get("req_id") for r in self.ctx["requirements"]["mandatory"]}
        self.assertIn("M16", ids)

    def test_last_mandatory_present(self):
        ids = {r.get("req_id") for r in self.ctx["requirements"]["mandatory"]}
        self.assertIn("M" + str(self.N_MANDATORY), ids)

    def test_last_rated_present(self):
        ids = {r.get("req_id") for r in self.ctx["requirements"]["rated"]}
        self.assertIn("R" + str(self.N_RATED), ids)

    def test_last_financial_present(self):
        ids = {r.get("req_id") for r in self.ctx["requirements"]["financial"]}
        self.assertIn("F" + str(self.N_FINANCIAL), ids)

    def test_last_supporting_present(self):
        ids = {r.get("req_id") for r in self.ctx["requirements"]["supporting"]}
        self.assertIn("S" + str(self.N_SUPPORTING), ids)

    def test_source_refs_preserved(self):
        for r in self.ctx["requirements"]["mandatory"]:
            self.assertIn("source_refs", r)
            self.assertGreater(len(r["source_refs"]), 0)

    def test_qual_status_not_altered(self):
        """qual_status UNKNOWN must not be upgraded to PASS."""
        for r in self.ctx["requirements"]["mandatory"]:
            self.assertEqual(r.get("qual_status"), "UNKNOWN")

    def test_dates_present_in_context(self):
        self.assertGreater(len(self.ctx["dates"]), 0)

    def test_detected_conflicts_key_present(self):
        self.assertIn("detected_conflicts", self.ctx)

    def test_context_integrity_key_present(self):
        self.assertIn("context_integrity", self.ctx)


# ---------------------------------------------------------------------------
# Scenario 2: Mocked model-omission resilience
# ---------------------------------------------------------------------------

class TestStageDAuthoritativeSections(unittest.TestCase):
    """
    Mock an AI response that returns only 1 qualification_gate even though
    there are 20 Mandatory requirements.  After apply_stage_d_authoritative_sections()
    all 20 must be present.
    """

    N_MANDATORY = 20
    N_RATED = 10

    def setUp(self):
        self.nf = _large_normalized_facts(
            n_mandatory=self.N_MANDATORY, n_rated=self.N_RATED,
            n_financial=2, n_supporting=5)
        # Deliberately incomplete AI response
        self.mock_synth = {
            "bid": {"title": "Test RFP", "client": "Test Department",
                    "file_number": "RFP-2026-TEST", "owner": None,
                    "sensitivity": "Standard", "submission_deadline": "2026-12-01",
                    "clarification_deadline": None, "value_cad": None,
                    "notes": "AI synthesis note."},
            "brief": {
                "executive_summary": "Executive summary synthesized by AI.",
                "opportunity_type": "Services RFP",
                "contract_term": "3 years",
                "procurement_model": "Single Contract",
                "scope_categories": ["Category 1"],
                # Deliberately only 1 gate
                "qualification_gates": [
                    {"requirement": "Only one gate returned by AI",
                     "type": "Mandatory Qualification", "rfp_ref": None,
                     "disqualification_risk": "High"}
                ],
                "evaluation_breakdown": [],
                "submission_requirements": [],
                "key_dates": [],
            },
            "outline": []
        }

    def test_gates_count_equals_mandatory_count(self):
        result = apply_stage_d_authoritative_sections(self.mock_synth, self.nf)
        self.assertEqual(len(result["brief"]["qualification_gates"]), self.N_MANDATORY)

    def test_all_mandatory_req_ids_in_gates(self):
        result = apply_stage_d_authoritative_sections(self.mock_synth, self.nf)
        ids = {g.get("req_id") for g in result["brief"]["qualification_gates"]}
        for i in range(1, self.N_MANDATORY + 1):
            self.assertIn("M" + str(i), ids)

    def test_evaluation_breakdown_populated(self):
        result = apply_stage_d_authoritative_sections(self.mock_synth, self.nf)
        self.assertGreater(len(result["brief"]["evaluation_breakdown"]), 0)

    def test_submission_requirements_populated(self):
        result = apply_stage_d_authoritative_sections(self.mock_synth, self.nf)
        items = [s["item"] for s in result["brief"]["submission_requirements"]]
        self.assertIn("Technical Proposal", items)

    def test_key_dates_populated(self):
        result = apply_stage_d_authoritative_sections(self.mock_synth, self.nf)
        milestones = [d["milestone"] for d in result["brief"]["key_dates"]]
        self.assertIn("Bid Closing", milestones)

    def test_ai_synthesis_fields_preserved(self):
        result = apply_stage_d_authoritative_sections(self.mock_synth, self.nf)
        brief = result["brief"]
        self.assertEqual(brief["executive_summary"], "Executive summary synthesized by AI.")
        self.assertEqual(brief["opportunity_type"], "Services RFP")
        self.assertEqual(brief["contract_term"], "3 years")

    def test_bid_fields_preserved(self):
        result = apply_stage_d_authoritative_sections(self.mock_synth, self.nf)
        self.assertEqual(result["bid"]["title"], "Test RFP")
        self.assertEqual(result["bid"]["client"], "Test Department")


# ---------------------------------------------------------------------------
# Scenario 3: Conflict coverage
# ---------------------------------------------------------------------------

class TestStageDConflictCoverage(unittest.TestCase):

    def test_all_conflicts_present_in_context(self):
        conflicts = [
            {"conflict_id": "CONF-DATE-1", "conflict_type": "DATE_CONFLICT",
             "classification": "TRUE_CONFLICT", "confidence": "HIGH",
             "reason": "Deadline differs.",
             "source_a": {"doc": "RFP.pdf", "text": "2026-09-15"},
             "source_b": {"doc": "Addendum.pdf", "text": "2026-09-30"}},
            {"conflict_id": "CONF-SUB-1", "conflict_type": "SUBMISSION_RULE_CONFLICT",
             "classification": "REVIEW_ITEM", "confidence": "MEDIUM",
             "reason": "Portal vs email.",
             "source_a": {"doc": "RFP.pdf", "text": "MERX"},
             "source_b": {"doc": "Instructions.pdf", "text": "email"}},
        ]
        nf = _large_normalized_facts(n_mandatory=3, n_rated=2, n_financial=1, n_supporting=1)
        ctx = build_stage_d_context(nf, conflicts)
        self.assertEqual(len(ctx["detected_conflicts"]), 2)
        ids = {c["conflict_id"] for c in ctx["detected_conflicts"]}
        self.assertIn("CONF-DATE-1", ids)
        self.assertIn("CONF-SUB-1", ids)
        classes = {c["classification"] for c in ctx["detected_conflicts"]}
        self.assertIn("TRUE_CONFLICT", classes)
        self.assertIn("REVIEW_ITEM", classes)

    def test_empty_conflicts_do_not_raise(self):
        nf = _large_normalized_facts(n_mandatory=2, n_rated=1, n_financial=0, n_supporting=0)
        ctx = build_stage_d_context(nf, [])
        self.assertEqual(ctx["detected_conflicts"], [])


# ---------------------------------------------------------------------------
# Scenario 4: Bank of Canada frozen coverage replay
# ---------------------------------------------------------------------------

class TestStageDFrozenBankOfCanadaCoverageReplay(unittest.TestCase):

    FIXTURE = os.path.join(
        os.path.dirname(__file__),
        "acceptance", "results", "boc_2026_026_normalized_facts.json"
    )

    def setUp(self):
        if not os.path.exists(self.FIXTURE):
            self.skipTest("Frozen BoC normalized facts not found: " + self.FIXTURE)
        with open(self.FIXTURE, encoding="utf-8") as fh:
            self.nf = json.load(fh)
        self.all_reqs = self.nf.get("requirements", [])

    def _count(self, cat):
        return sum(1 for r in self.all_reqs
                   if r.get("category", "").strip().lower() == cat.lower())

    def test_zero_omissions(self):
        ctx = build_stage_d_context(self.nf, [])
        ci = ctx["context_integrity"]
        self.assertEqual(ci["omitted_requirement_count"], 0)
        self.assertEqual(ci["included_requirement_count"], ci["source_requirement_count"])

    def test_mandatory_count_preserved(self):
        src = self._count("Mandatory")
        ctx = build_stage_d_context(self.nf, [])
        inc = len(ctx["requirements"]["mandatory"])
        self.assertEqual(inc, src,
                         "Mandatory source=" + str(src) + " included=" + str(inc))

    def test_financial_count_preserved(self):
        src = self._count("Financial")
        ctx = build_stage_d_context(self.nf, [])
        inc = len(ctx["requirements"]["financial"])
        self.assertEqual(inc, src,
                         "Financial source=" + str(src) + " included=" + str(inc))

    def test_rated_count_preserved(self):
        src = self._count("Rated")
        ctx = build_stage_d_context(self.nf, [])
        inc = len(ctx["requirements"]["rated"])
        self.assertEqual(inc, src,
                         "Rated source=" + str(src) + " included=" + str(inc))

    def test_supporting_count_preserved(self):
        src = self._count("Supporting")
        ctx = build_stage_d_context(self.nf, [])
        inc = len(ctx["requirements"]["supporting"])
        self.assertEqual(inc, src,
                         "Supporting source=" + str(src) + " included=" + str(inc))

    def test_last_requirement_present(self):
        last = self.all_reqs[-1]
        lid  = last.get("req_id")
        lcat = last.get("category", "").strip().lower()
        ldesc= last.get("description", "").strip()
        ctx  = build_stage_d_context(self.nf, [])
        cat_list = ctx["requirements"].get(lcat, [])
        found = any(r.get("req_id") == lid or r.get("description","").strip() == ldesc
                    for r in cat_list)
        self.assertTrue(found,
                        "Last req " + repr(lid) + " (" + lcat + ") missing from Stage D context.")

    def test_position_16_requirement_present(self):
        if len(self.all_reqs) <= 15:
            self.skipTest("Fixture has 15 or fewer requirements")
        req16 = self.all_reqs[15]
        rid   = req16.get("req_id")
        cat   = req16.get("category", "").strip().lower()
        desc  = req16.get("description", "").strip()
        ctx   = build_stage_d_context(self.nf, [])
        cat_list = ctx["requirements"].get(cat, [])
        found = any(r.get("req_id") == rid or r.get("description","").strip() == desc
                    for r in cat_list)
        self.assertTrue(found,
                        "Position-16 req " + repr(rid) + " missing — [:15] truncation not fixed.")

    def test_counts_by_category_accurate(self):
        from collections import Counter
        expected = Counter(r.get("category","").strip() for r in self.all_reqs)
        ctx = build_stage_d_context(self.nf, [])
        reported = ctx["context_integrity"]["counts_by_category"]
        for cat, count in expected.items():
            self.assertEqual(reported.get(cat, 0), count)


# ---------------------------------------------------------------------------
# Scenario 5: Edge cases
# ---------------------------------------------------------------------------

class TestStageDContextBuilderEdgeCases(unittest.TestCase):

    def test_empty_requirements(self):
        nf = {"requirements": [], "dates": [], "evaluation_criteria": [],
              "submission_rules": [], "deliverables": [], "commercial_clauses": [],
              "contract_risks": []}
        ctx = build_stage_d_context(nf, [])
        ci = ctx["context_integrity"]
        self.assertEqual(ci["source_requirement_count"], 0)
        self.assertEqual(ci["omitted_requirement_count"], 0)

    def test_long_excerpt_capped_not_dropped(self):
        from extractor import _EXCERPT_CAP
        long_exc = "x" * (_EXCERPT_CAP + 200)
        nf = {"requirements": [
            {"req_id": "M1", "category": "Mandatory", "description": "Long excerpt req",
             "source_refs": [{"source_doc": "Doc.pdf", "page": 1, "sheet": None,
                              "section": "Req", "excerpt": long_exc}],
             "qual_status": "UNKNOWN", "evidence_status": "MISSING"}
        ]}
        ctx = build_stage_d_context(nf, [])
        mandatory = ctx["requirements"]["mandatory"]
        self.assertEqual(len(mandatory), 1)
        exc = mandatory[0]["source_refs"][0]["excerpt"]
        self.assertEqual(len(exc), _EXCERPT_CAP)

    def test_apply_authoritative_sections_on_empty_synth(self):
        nf = _large_normalized_facts(n_mandatory=3, n_rated=2, n_financial=1, n_supporting=1)
        result = apply_stage_d_authoritative_sections({}, nf)
        self.assertIn("brief", result)
        self.assertEqual(len(result["brief"]["qualification_gates"]), 3)



# ---------------------------------------------------------------------------
# Scenario 6: Deduplication regression tests (items A-H) and robustness (I-J)
# ---------------------------------------------------------------------------

class TestStageDDeduplicationRegressions(unittest.TestCase):
    """
    Verify that materially distinct normalized facts produce distinct output entries,
    and that only exact duplicates (identical on all canonical fields) are collapsed.
    Also verifies no default values are invented for absent fields.
    """

    def _base_nf(self, **overrides):
        """Minimal normalized_facts dict, easily overridden per-test."""
        base = {
            "requirements":       [],
            "dates":              [],
            "evaluation_criteria":[],
            "submission_rules":   [],
            "deliverables":       [],
            "commercial_clauses": [],
            "contract_risks":     [],
        }
        base.update(overrides)
        return base

    # A: same milestone, different dates -> both preserved
    def test_A_same_milestone_different_dates_both_preserved(self):
        nf = self._base_nf(dates=[
            {"milestone": "Bid Closing", "date": "2026-09-15", "source_doc": "RFP.pdf"},
            {"milestone": "Bid Closing", "date": "2026-09-30", "source_doc": "Addendum.pdf"},
        ])
        result = apply_stage_d_authoritative_sections({}, nf)
        dates = result["brief"]["key_dates"]
        date_vals = [d["date"] for d in dates]
        self.assertIn("2026-09-15", date_vals, "RFP closing date must be preserved")
        self.assertIn("2026-09-30", date_vals, "Addendum closing date must be preserved")
        self.assertEqual(len(dates), 2,
            "Two same-milestone dates with different values must both appear in key_dates")

    # B: same evaluation stage, different weights -> one logical criterion with conflict & both observations tracked
    def test_B_same_eval_stage_different_weights_both_preserved(self):
        nf = self._base_nf(evaluation_criteria=[
            {"stage": "Technical", "weight": "70 points", "threshold": "50%",
             "notes": "Version 1",
             "source_refs": [{"source_doc": "RFP.pdf", "page": 1}]},
            {"stage": "Technical", "weight": "60 points", "threshold": "50%",
             "notes": "Version 2",
             "source_refs": [{"source_doc": "Addendum.pdf", "page": 1}]},
        ])
        result = apply_stage_d_authoritative_sections({}, nf)
        breakdown = result["brief"]["evaluation_breakdown"]
        self.assertEqual(len(breakdown), 1, "Logical criterion must not duplicate on weight observation difference")
        criterion = breakdown[0]
        self.assertTrue(criterion.get("weight_conflict"), "Conflicting weights must mark weight_conflict")
        obs_weights = [o.get("raw_weight") for o in criterion.get("weight_observations", [])]
        self.assertIn("70 points", obs_weights, "Original weight observation must be preserved")
        self.assertIn("60 points", obs_weights, "Addendum weight observation must be preserved")

    # C: same submission item, different format/details -> both preserved
    def test_C_same_submission_item_different_format_both_preserved(self):
        nf = self._base_nf(submission_rules=[
            {"item": "Technical Proposal", "format": "PDF",
             "details": "Max 50 pages", "mandatory": 1},
            {"item": "Technical Proposal", "format": "DOCX",
             "details": "Revised per addendum", "mandatory": 1},
        ])
        result = apply_stage_d_authoritative_sections({}, nf)
        sub = result["brief"]["submission_requirements"]
        fmts = [s["format"] for s in sub]
        self.assertIn("PDF", fmts, "PDF format must be preserved")
        self.assertIn("DOCX", fmts, "DOCX format must be preserved")
        self.assertEqual(len(sub), 2,
            "Same item with different format/details must produce two submission_requirements")

    # D: same commercial topic, different details -> both preserved
    def test_D_same_commercial_topic_different_details_both_preserved(self):
        nf = self._base_nf(commercial_clauses=[
            {"topic": "Rate Adjustment", "details": "CPI cap 3%", "source_doc": "RFP.pdf"},
            {"topic": "Rate Adjustment", "details": "CPI cap 5%", "source_doc": "Addendum.pdf"},
        ])
        result = apply_stage_d_authoritative_sections({}, nf)
        comm = result["brief"]["commercial_structure"]
        details_vals = [c["details"] for c in comm]
        self.assertIn("CPI cap 3%", details_vals)
        self.assertIn("CPI cap 5%", details_vals)
        self.assertEqual(len(comm), 2,
            "Same topic with different details must produce two commercial_structure entries")

    # E: same deliverable title, different category/details -> both preserved
    def test_E_same_deliverable_title_different_details_both_preserved(self):
        nf = self._base_nf(deliverables=[
            {"title": "Status Report", "description": "Monthly report",
             "category": "Core", "source_doc": "SOW_v1.pdf"},
            {"title": "Status Report", "description": "Quarterly summary",
             "category": "Optional", "source_doc": "SOW_v2.pdf"},
        ])
        result = apply_stage_d_authoritative_sections({}, nf)
        deliv = result["brief"]["deliverables_summary"]
        descs = [d["description"] for d in deliv]
        self.assertIn("Monthly report", descs)
        self.assertIn("Quarterly summary", descs)
        self.assertEqual(len(deliv), 2,
            "Same deliverable title with different description/category must produce two entries")

    # F: exact duplicate normalized items may deduplicate
    def test_F_exact_duplicate_normalized_items_are_collapsed(self):
        nf = self._base_nf(dates=[
            {"milestone": "Bid Closing", "date": "2026-09-30", "source_doc": "RFP.pdf"},
            {"milestone": "Bid Closing", "date": "2026-09-30", "source_doc": "RFP.pdf"},
        ])
        result = apply_stage_d_authoritative_sections({}, nf)
        dates = result["brief"]["key_dates"]
        self.assertEqual(len(dates), 1,
            "Identical duplicates on all canonical fields must be collapsed to one entry")
        self.assertEqual(dates[0]["date"], "2026-09-30")

    # G: missing risk severity -> no invented "Medium"
    def test_G_missing_risk_severity_not_invented(self):
        nf = self._base_nf(contract_risks=[
            {"risk": "Scope Creep", "details": "SOW may expand."}
            # No "severity" key at all
        ])
        result = apply_stage_d_authoritative_sections({}, nf)
        risk_list = result["brief"]["contract_risks"]
        self.assertEqual(len(risk_list), 1)
        self.assertNotIn("severity", risk_list[0],
            "severity=Medium must not be invented when absent from normalized facts")

    # H: missing deliverable category -> no invented "Core"
    def test_H_missing_deliverable_category_not_invented(self):
        nf = self._base_nf(deliverables=[
            {"title": "Final Report", "description": "End-of-contract deliverable"}
            # No "category" key
        ])
        result = apply_stage_d_authoritative_sections({}, nf)
        deliv = result["brief"]["deliverables_summary"]
        self.assertEqual(len(deliv), 1)
        self.assertNotIn("category", deliv[0],
            "category=Core must not be invented when absent from normalized facts")

    # I: brief=null / non-dict -> authoritative rebuild succeeds, bid preserved
    def test_I_brief_non_dict_authoritative_rebuild_succeeds(self):
        for bad_brief in [None, [], "invalid", 42, {}]:
            with self.subTest(brief=bad_brief):
                synth_input = {"bid": {"title": "Test"}, "brief": bad_brief}
                nf = {
                    "requirements": [
                        {"req_id": "M1", "category": "Mandatory",
                         "requirement_type": "Supplier Qualification",
                         "description": "Supplier eligibility and conditions of participation"}
                    ],
                    "dates": [], "evaluation_criteria": [], "submission_rules": [],
                    "deliverables": [], "commercial_clauses": [], "contract_risks": [],
                }
                result = apply_stage_d_authoritative_sections(synth_input, nf)
                self.assertIsInstance(result["brief"], dict,
                    "brief must be a dict after authoritative rebuild regardless of AI output")
                gates = result["brief"]["qualification_gates"]
                self.assertEqual(len(gates), 1,
                    "qualification_gates must be populated from normalized facts")
                self.assertEqual(gates[0]["req_id"], "M1")
                self.assertEqual(result.get("bid", {}).get("title"), "Test",
                    "bid-level fields must survive authoritative rebuild")

    # J: malformed requirement entry -> explicit integrity failure
    def test_J_malformed_requirement_raises_integrity_error(self):
        nf = {
            "requirements": [
                {"req_id": "M1", "category": "Mandatory", "description": "Valid req"},
                "this is not a dict",  # malformed entry
            ],
            "dates": [], "evaluation_criteria": [], "submission_rules": [],
            "deliverables": [], "commercial_clauses": [], "contract_risks": [],
        }
        with self.assertRaises(RuntimeError) as ctx:
            build_stage_d_context(nf, [])
        err_msg = str(ctx.exception).lower()
        self.assertIn("integrity", err_msg,
            "Error message must reference 'integrity'")


# ---------------------------------------------------------------------------
# Scenario 7: Context-size preflight tests (item K)
# ---------------------------------------------------------------------------

class TestStageDContextSizePreflight(unittest.TestCase):
    """
    K: Verify that an oversized Stage D context triggers StageDContextTooLargeError
    BEFORE the Anthropic API call, with a message confirming context completeness.
    """

    def _minimal_nf(self):
        return {
            "doc_metadata": {"title": "Test RFP"},
            "requirements": [
                {"req_id": "M1", "category": "Mandatory",
                 "description": "Only mandatory req", "source_refs": []}
            ],
            "dates": [], "evaluation_criteria": [], "submission_rules": [],
            "deliverables": [], "commercial_clauses": [], "contract_risks": [],
        }

    def test_K_forced_limit_low_raises_StageDContextTooLargeError(self):
        import extractor as _ext
        from extractor import StageDContextTooLargeError, synthesize_bid_brief
        import unittest.mock as mock

        original_limit = _ext._STAGE_D_CONTEXT_CHAR_LIMIT
        _ext._STAGE_D_CONTEXT_CHAR_LIMIT = 1  # Guarantee overflow on any real context
        try:
            with self.assertRaises(StageDContextTooLargeError) as ctx:
                with mock.patch("extractor.get_anthropic_client"):
                    synthesize_bid_brief(self._minimal_nf(), [], api_key="test")
            msg = str(ctx.exception)
            self.assertIn("complete", msg.lower(),
                "Error must confirm context is COMPLETE (no silent omission)")
            self.assertIn("silently omitted", msg.lower(),
                "Error must confirm no requirements were silently omitted")
            self.assertIn("source requirement count", msg.lower(),
                "Error must state the source requirement count")
            self.assertIn("characters", msg.lower(),
                "Error must report serialized context size in characters")
        finally:
            _ext._STAGE_D_CONTEXT_CHAR_LIMIT = original_limit

    def test_K_preflight_fires_before_api_call(self):
        """The API must never be called when the preflight limit is exceeded."""
        import extractor as _ext
        from extractor import StageDContextTooLargeError, synthesize_bid_brief
        import unittest.mock as mock

        original_limit = _ext._STAGE_D_CONTEXT_CHAR_LIMIT
        _ext._STAGE_D_CONTEXT_CHAR_LIMIT = 1
        try:
            mock_client = mock.MagicMock()
            with self.assertRaises(StageDContextTooLargeError):
                with mock.patch("extractor.get_anthropic_client", return_value=mock_client):
                    synthesize_bid_brief(self._minimal_nf(), [], api_key="test")
            mock_client.messages.create.assert_not_called()
        finally:
            _ext._STAGE_D_CONTEXT_CHAR_LIMIT = original_limit

    def test_K_normal_limit_does_not_raise_for_small_package(self):
        """A tiny package must not trigger the preflight under the real limit."""
        from extractor import synthesize_bid_brief
        import unittest.mock as mock

        mock_response = mock.MagicMock()
        # The preflight test supplies a valid v1 response. Empty JSON is now
        # explicitly rejected by the separate strict-response tests.
        response = {
            "synthesis": {
                "bid": {"title": None, "client": None, "file_number": None,
                        "owner": None, "sensitivity": "Standard",
                        "submission_deadline": None, "clarification_deadline": None,
                        "value_cad": None, "notes": None},
                "brief": {"executive_summary": None, "opportunity_type": None,
                          "contract_term": "Not stated", "procurement_model": None,
                          "scope_categories": []},
                "outline": [],
            },
            "citations": [],
        }
        mock_response.content = [mock.MagicMock(type="text", text=json.dumps(response))]
        mock_response.stop_reason = "end_turn"
        mock_client = mock.MagicMock()
        mock_client.with_options.return_value = mock_client
        mock_client.messages.create.return_value = mock_response

        with mock.patch("extractor.get_anthropic_client", return_value=mock_client), \
             mock.patch("database.create_model_usage_event", return_value=None):
            result = synthesize_bid_brief(self._minimal_nf(), [], api_key="test")
        self.assertIsInstance(result, dict)
        mock_client.messages.create.assert_called_once()
        self.assertIn("qualification_gates", result["brief"])


if __name__ == "__main__":
    unittest.main()
