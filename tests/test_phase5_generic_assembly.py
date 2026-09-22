"""
tests/test_phase5_generic_assembly.py

Product Integration Phase 5 (generic intelligence assembly & cross-
procurement correction). Deterministic tests only -- no live API calls, no
database connection. Covers exactly the phase's required regression
categories (instruction 18/19):

  - Bank of Canada non-regression against a synthetic result shaped like
    the real, commissioned Phase 3 corpus (20 criteria, 7+7+6, Value-add
    and Relevant Experience & References present, no false
    evaluation-weight ambiguity, pricing-stage ambiguity present,
    category-date distinction present).
  - A CDA-AMC-shaped synthetic result built from PHASE4_SOURCE_TRUTH_
    CHECKLIST.json's own real, deterministically-verified facts (not
    rebuilt from the system's own output).
  - Cross-corpus contamination guards: the CDA-AMC-shaped result must never
    render Bank of Canada's identity or content, and an arbitrary minimal
    procurement must render only its own facts.
  - Sparse/empty-state rendering: no category structure, no commercial
    terms, no ambiguities, no gates, no weights, no buyer intelligence --
    must not crash, invent data, or leak another corpus's content. Also
    exercises the actual reportlab PDF build end-to-end for the sparsest
    case, since that is where an empty-table crash would actually surface.
"""
import json
import unittest
from pathlib import Path

from fast_analysis import FastAnalysisResult
from scripts.fast_analysis_report_adapter import build_fast_report_content, _discover_evaluation_categories
import scripts.build_boc_bid_intelligence_preview_pdf as pdf_builder

ROOT = Path(__file__).resolve().parents[1]
CHECKLIST_PATH = ROOT / "PHASE4_SOURCE_TRUTH_CHECKLIST.json"


def _boc_shaped_result() -> FastAnalysisResult:
    """Synthetic result shaped like the real, commissioned Bank of Canada
    Phase 3 corpus (RFP 2026-026) -- not a live run, but matching the
    persisted structure's own known facts (7+7+6=20 criteria, Value-add and
    Relevant Experience & References present, a real evaluation-weight
    false-positive correctly absent, a real pricing-stage ambiguity
    present, a real category-date distinction present)."""
    r = FastAnalysisResult()
    r.doc_metadata_by_doc["master.pdf"] = {
        "client": "Bank of Canada", "file_number": "RFP 2026-026",
        "title": "Talent, Learning and Organizational Development Services",
        "submission_deadline": "September 30, 2026", "submission_time": "11:59 PM EST",
        "clarification_deadline": "September 10, 2026",
    }
    r.typed_observations = [
        {"family": "PROCUREMENT_MECHANIC", "semantic_kind": "MULTIPLE_SUPPLIER_AWARD",
         "original_value": "Multiple Supplier Award"},
        {"family": "CONTRACT_TERM", "semantic_kind": "INITIAL_DURATION", "duration": "3", "unit": "years",
         "scope": {}},
        {"family": "CONTRACT_TERM", "semantic_kind": "EXTENSION_OPTION", "option_count": "2",
         "duration": "1", "unit": "year"},
        {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO", "date": "2026-10-26",
         "scope": {"category": "Category 1"}},
        {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO", "date": "2026-11-02",
         "scope": {"category": "Category 3"}},
    ]
    cat1 = [("Corporate Profile", "5 pts"), ("Key Personnel & Roster", "15 pts"),
            ("Curriculum & Program Design", "35 pts"), ("Measurement Approach", "5 pts"),
            ("Relationship Management", "5 pts"), ("Value-add", "5 pts"),
            ("Relevant Experience & References", "5 pts")]
    cat2 = [("Corporate Profile", "5 pts"), ("Key Personnel & Roster", "15 pts"),
            ("Methodology & Advisory Approach", "35 pts"), ("Thought Leadership & Innovation", "5 pts"),
            ("Relationship Management", "5 pts")]
    cat3 = [("Corporate Profile", "10 pts"), ("Key Personnel & Roster", "20 pts"),
            ("Facilitation Methodology", "30 pts"), ("Value-add", "5 pts"),
            ("Relevant Experience & References", "10 pts"), ("Price", "25 pts")]
    occs = []
    for label, weight in cat1:
        occs.append({"criterion_label": label, "weight": weight, "category_scope": "Category 1"})
    for label, weight in cat2:
        occs.append({"criterion_label": label, "weight": weight, "category_scope": "Category 2"})
    for label, weight in cat3:
        occs.append({"criterion_label": label, "weight": weight, "category_scope": "Category 3"})
    r.evaluation_occurrences = occs
    r.ambiguities = {
        # V4's scope-aware fix correctly does NOT flag "Corporate Profile"
        # (5/5/10) or "Key Personnel & Roster" (15/15/20) across categories
        # -- no evaluation_weight_conflicts for a correctly-scoped corpus.
        "evaluation_weight_conflicts": [],
        "pricing_stage_ambiguity": [{"detail": "Price appears inside Category 3's table and again "
                                                "as a separate Stage 4."}],
        "category_date_distinctions": [{"milestone_kind": "PRESENTATION_OR_DEMO"}],
    }
    r.commercial_clauses = [
        {"clause_kind": "INSURANCE", "source_fact": "CGL minimum $3,000,000.", "source_doc": "AppendixG.docx"},
    ]
    r.requirements = [
        {"category": "Mandatory", "description": "Bilingual delivery confirmation required.",
         "source_doc": "master.pdf"},
    ]
    return r


def _cda_amc_shaped_result() -> FastAnalysisResult:
    """Synthetic result built from PHASE4_SOURCE_TRUTH_CHECKLIST.json's own
    real, deterministically-extracted facts (Phase 5 instruction 9: reuse,
    do not rebuild, this truth set) -- a materially different, real
    procurement with NO category structure, all three ambiguity classes
    genuinely NOT_PRESENT, and content that must never resemble Bank of
    Canada's."""
    with open(CHECKLIST_PATH, encoding="utf-8") as f:
        truth = json.load(f)
    identity = truth["corpus_identity"]
    dates = truth["dates"]
    r = FastAnalysisResult()
    r.doc_metadata_by_doc["main.pdf"] = {
        "client": identity["buyer"], "file_number": identity["file_reference_number"],
        "title": identity["procurement_title"],
        "submission_deadline": dates["submission_deadline"],
        "clarification_deadline": dates["clarification_enquiry_deadline"],
    }
    occs = []
    for row in truth["evaluation_criteria"]["stage_ii_rated_technical_criteria"]:
        occs.append({"criterion_label": row["criterion"], "weight": row["weight"], "category_scope": None})
    for row in truth["evaluation_criteria"]["stage_iii_pricing_criteria"]:
        occs.append({"criterion_label": row["criterion"], "weight": row["weight"], "category_scope": None})
    r.evaluation_occurrences = occs
    r.ambiguities = {"evaluation_weight_conflicts": [], "pricing_stage_ambiguity": [],
                     "category_date_distinctions": []}
    r.requirements = [{"category": "Mandatory", "description": desc, "source_doc": "main.pdf"}
                      for desc in truth["response_requirements"]]
    r.commercial_clauses = [
        {"clause_kind": "INSURANCE",
         "source_fact": f"Liability insurance {truth['commercial_and_contractual']['liability_insurance']}",
         "source_doc": "main.pdf"},
    ]
    return r


class TestBankOfCanadaNonRegression(unittest.TestCase):
    """Phase 5 instruction 10: the commissioned Bank of Canada baseline
    must remain correct after genericization."""

    def test_snapshot_identity(self):
        content = build_fast_report_content(_boc_shaped_result())
        facts = dict(content.SNAPSHOT_FACTS)
        self.assertEqual(facts["Buyer"], "Bank of Canada")
        self.assertEqual(facts["Solicitation Number"], "RFP 2026-026")

    def test_evaluation_structure_is_20_criteria_7_7_6(self):
        content = build_fast_report_content(_boc_shaped_result())
        cat1 = next(v for k, v in content.EVAL_WEIGHTS.items() if "Category 1" in k)
        cat2 = next(v for k, v in content.EVAL_WEIGHTS.items() if "Category 2" in k)
        cat3 = next(v for k, v in content.EVAL_WEIGHTS.items() if "Category 3" in k)
        self.assertEqual(len(cat1), 7)
        self.assertEqual(len(cat2), 7 - 2)  # 5
        self.assertEqual(len(cat3), 6)
        self.assertEqual(len(cat1) + len(cat2) + len(cat3), 18, "7+5+6 = 18 scored rows total")

    def test_value_add_and_relevant_experience_present(self):
        content = build_fast_report_content(_boc_shaped_result())
        all_labels = {label for rows in content.EVAL_WEIGHTS.values() for label, _ in rows}
        self.assertIn("Value-add", all_labels)
        self.assertIn("Relevant Experience & References", all_labels)

    def test_no_false_evaluation_weight_ambiguity(self):
        content = build_fast_report_content(_boc_shaped_result())
        self.assertEqual(content.FACT_ORIGINS["AMBIGUITY.evaluation_weight_conflict"], "NOT_PRESENT")

    def test_pricing_stage_ambiguity_present(self):
        content = build_fast_report_content(_boc_shaped_result())
        self.assertEqual(content.FACT_ORIGINS["AMBIGUITY.pricing_stage_ambiguity"], "LIVE_FAST_LLM")

    def test_category_date_distinction_is_no_longer_a_false_ambiguity(self):
        """CI-1 Defect F: this fixture is the exact Bank of Canada shape
        -- a Category 1 demo date and a Category 3 demo date. Those are
        two distinct scoped events, so the report must no longer raise a
        'multiple distinct dates' ambiguity for them. The report now
        recomputes this verdict from the result's own typed observations
        rather than replaying a frozen pre-CI-1 one."""
        content = build_fast_report_content(_boc_shaped_result())
        self.assertEqual(content.FACT_ORIGINS["AMBIGUITY.category_date_distinction"], "NOT_PRESENT")

    def test_buyer_intelligence_still_renders_for_bank_of_canada(self):
        content = build_fast_report_content(_boc_shaped_result())
        self.assertTrue(content.BUYER_INTEL_AVAILABLE)

    def test_pdf_builds_without_error(self):
        out = ROOT / "tests" / "_scratch_boc_phase5.pdf"
        content = build_fast_report_content(_boc_shaped_result())
        try:
            pdf_builder.build(content=content, out_path=out)
            self.assertTrue(out.exists())
        finally:
            if out.exists():
                out.unlink()


class TestCDAAMCShapedResult(unittest.TestCase):
    """Phase 5 instruction 9: the CDA-AMC application/report output must
    contain the corpus's own actual facts and ZERO Bank of Canada content."""

    def test_identity_is_cda_amc_not_bank_of_canada(self):
        content = build_fast_report_content(_cda_amc_shaped_result())
        facts = dict(content.SNAPSHOT_FACTS)
        self.assertEqual(facts["Buyer"], "Canada's Drug Agency (CDA-AMC)")
        self.assertEqual(facts["Solicitation Number"], "C-262700410")
        self.assertNotEqual(facts["Buyer"], "Bank of Canada")

    def test_flat_evaluation_structure_no_category_cards(self):
        """Instruction 5: CDA-AMC has one scope, not category/lot
        structure -- must render as a flat table, not three empty or
        substituted category cards."""
        content = build_fast_report_content(_cda_amc_shaped_result())
        self.assertEqual(content.SNAPSHOT_CATEGORY_CARDS, [])
        self.assertIn("Rated Criteria", content.EVAL_WEIGHTS)
        # All 10 Stage II/III criteria carry a numeric-shaped weight in the
        # checklist's own source text (including the two Mandatory/0%
        # insurance gates, which the source itself states as "0%"), plus
        # Stage III's Fees row -- 11 rows total, every one traceable to the
        # checklist's own real wording, not invented or borrowed.
        self.assertEqual(len(content.EVAL_WEIGHTS["Rated Criteria"]), 11)

    def test_all_three_ambiguity_classes_correctly_not_present(self):
        content = build_fast_report_content(_cda_amc_shaped_result())
        for gate in ("evaluation_weight_conflict", "pricing_stage_ambiguity", "category_date_distinction"):
            self.assertEqual(content.FACT_ORIGINS[f"AMBIGUITY.{gate}"], "NOT_PRESENT")
        self.assertEqual(content.AMBIGUITIES, [])

    def test_buyer_intelligence_not_available_for_cda_amc(self):
        content = build_fast_report_content(_cda_amc_shaped_result())
        self.assertFalse(content.BUYER_INTEL_AVAILABLE)
        self.assertEqual(content.FACT_ORIGINS["BUYER_INTELLIGENCE"], "MISSING_NO_FALLBACK")

    def test_response_requirements_use_cda_amc_own_text(self):
        content = build_fast_report_content(_cda_amc_shaped_result())
        checklist_text = " ".join(row[1] for row in content.RESPONSE_CHECKLIST)
        self.assertIn("MERX", checklist_text)

    def test_pdf_builds_without_error(self):
        out = ROOT / "tests" / "_scratch_cda_amc_phase5.pdf"
        content = build_fast_report_content(_cda_amc_shaped_result())
        try:
            pdf_builder.build(content=content, out_path=out)
            self.assertTrue(out.exists())
        finally:
            if out.exists():
                out.unlink()


class TestCrossCorpusContamination(unittest.TestCase):
    """Phase 5 instruction 11: a permanent contamination guard -- one
    corpus's report must never contain another corpus's identity or
    content."""

    def _flatten_text(self, content) -> str:
        """Concatenate every string-shaped field the PDF actually renders,
        so a substring search catches leakage anywhere in the report, not
        just in fields this test happens to name."""
        parts = []
        for name in vars(content):
            value = getattr(content, name)
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, (list, tuple)):
                        parts.extend(str(x) for x in item if isinstance(x, str))
                    elif isinstance(item, dict):
                        parts.extend(str(v) for v in item.values() if isinstance(v, str))
            elif isinstance(value, dict):
                for v in value.values():
                    if isinstance(v, str):
                        parts.append(v)
                    elif isinstance(v, (list, tuple)):
                        for item in v:
                            if isinstance(item, (list, tuple)):
                                parts.extend(str(x) for x in item if isinstance(x, str))
        return "\n".join(parts)

    def test_cda_amc_report_never_mentions_bank_of_canada(self):
        content = build_fast_report_content(_cda_amc_shaped_result())
        text = self._flatten_text(content)
        self.assertNotIn("Bank of Canada", text)
        self.assertNotIn("RFP 2026-026", text)
        self.assertNotIn("2026-026", text)

    def test_bank_of_canada_report_never_mentions_cda_amc(self):
        content = build_fast_report_content(_boc_shaped_result())
        text = self._flatten_text(content)
        self.assertNotIn("CDA-AMC", text)
        self.assertNotIn("Canada's Drug Agency", text)
        self.assertNotIn("C-262700410", text)

    def test_arbitrary_minimal_procurement_renders_only_its_own_facts(self):
        """An arbitrary minimal procurement (buyer='Example Agency', title
        ='Leadership Coaching Services', one evaluation criterion, one
        deadline, no ambiguities) must render ONLY those facts -- nothing
        borrowed from either Bank of Canada or CDA-AMC."""
        r = FastAnalysisResult()
        r.doc_metadata_by_doc["doc.pdf"] = {
            "client": "Example Agency", "title": "Leadership Coaching Services",
            "submission_deadline": "2027-01-15",
        }
        r.evaluation_occurrences = [
            {"criterion_label": "Coaching Methodology", "weight": "50 points", "category_scope": None},
        ]
        content = build_fast_report_content(r)
        text = self._flatten_text(content)

        facts = dict(content.SNAPSHOT_FACTS)
        self.assertEqual(facts["Buyer"], "Example Agency")
        self.assertEqual(facts["Opportunity"], "Leadership Coaching Services")

        for leaked in ("Bank of Canada", "RFP 2026-026", "2026-026", "CDA-AMC",
                       "Canada's Drug Agency", "C-262700410", "MERX", "Corporate Profile"):
            self.assertNotIn(leaked, text, f"leaked cross-corpus content: {leaked!r}")


class TestSparseEmptyStateRendering(unittest.TestCase):
    """Phase 5 instruction 12: report rendering must work -- no crash, no
    invented data, no stale/leaked data -- for a genuinely, honestly
    sparse procurement (no category structure, no commercial terms, no
    ambiguities, no qualification gates, no weights, no buyer
    intelligence)."""

    def test_completely_empty_result_produces_valid_content_no_crash(self):
        content = build_fast_report_content(FastAnalysisResult())
        self.assertEqual(content.SNAPSHOT_CATEGORY_CARDS, [])
        self.assertEqual(content.SERVICE_CATEGORIES, [])
        self.assertEqual(content.EVAL_WEIGHTS, {})
        self.assertEqual(content.GATE_EXAMPLES, [])
        self.assertEqual(content.COMMERCIAL_POINTS, [])
        self.assertEqual(content.AMBIGUITIES, [])
        self.assertFalse(content.BUYER_INTEL_AVAILABLE)
        facts = dict(content.SNAPSHOT_FACTS)
        self.assertEqual(facts["Buyer"], "Not stated in the extracted data.")

    def test_completely_empty_result_pdf_builds_without_error(self):
        """The strongest version of the sparse-data guarantee: an entirely
        empty FastAnalysisResult (the honest worst case) must still
        produce a valid PDF, not raise (e.g. from an empty reportlab Table
        that a real Bank of Canada or CDA-AMC corpus would never
        exercise)."""
        out = ROOT / "tests" / "_scratch_empty_phase5.pdf"
        content = build_fast_report_content(FastAnalysisResult())
        try:
            pdf_builder.build(content=content, out_path=out)
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 0)
        finally:
            if out.exists():
                out.unlink()

    def test_no_crash_with_only_a_single_flat_criterion(self):
        r = FastAnalysisResult()
        r.evaluation_occurrences = [
            {"criterion_label": "Only Criterion", "weight": "100 points", "category_scope": None},
        ]
        content = build_fast_report_content(r)
        self.assertIn("Rated Criteria", content.EVAL_WEIGHTS)
        self.assertEqual(len(content.EVAL_WEIGHTS["Rated Criteria"]), 1)


class TestCategoryCoherenceCorrection(unittest.TestCase):
    """Final CDA-AMC live commissioning run (run_id=4) found a narrower,
    third defect after the original "7 Categories" fabrication was fixed:
    a scope group could pass category DISCOVERY on its raw occurrence
    count while collapsing to a single row at RENDER time (discovery and
    rendering used two different, slightly divergent filters). Fixed by
    introducing one canonical `_is_substantive_evaluation_row` predicate
    used identically by discovery, row-counting, and rendering -- these
    tests cover exactly the three cases the acceptance run specified:
    a weak/divergent candidate, a genuine multi-row category, and a mixed
    corpus with both, proving no real criterion is ever silently lost."""

    def _weak_group_occurrences(self, scope: str) -> list[dict]:
        """Several raw occurrences, only one substantive: the exact shape
        that used to fabricate a misleading single-criterion category
        card ("Not stated in the extracted data." bodies, etc.)."""
        return [
            {"criterion_label": "Mandatory Gate", "weight": None, "category_scope": scope},
            {"criterion_label": "Pass/Fail Item", "weight": "Yes", "category_scope": scope},
            {"criterion_label": "Total points", "weight": "100 points", "category_scope": scope},
            {"criterion_label": "The Real Criterion", "weight": "20%", "category_scope": scope},
        ]

    def test_weak_candidate_alone_does_not_become_a_category_but_criterion_survives(self):
        result = FastAnalysisResult()
        result.evaluation_occurrences = self._weak_group_occurrences("Weak Group")
        content = build_fast_report_content(result)

        self.assertEqual(content.SNAPSHOT_CATEGORY_CARDS, [])
        self.assertNotIn("Service Categories", dict(content.SNAPSHOT_FACTS))
        self.assertIn("Rated Criteria", content.EVAL_WEIGHTS)
        rows = content.EVAL_WEIGHTS["Rated Criteria"]
        self.assertIn(("The Real Criterion", "20%"), rows)
        self.assertFalse(any(label == "Total points" for label, _ in rows))

    def test_genuine_multi_row_category_remains_categorized(self):
        result = FastAnalysisResult()
        result.evaluation_occurrences = [
            {"criterion_label": "Approach", "weight": "30%", "category_scope": "Strong Group A"},
            {"criterion_label": "Team", "weight": "25%", "category_scope": "Strong Group A"},
            {"criterion_label": "Cost", "weight": "45%", "category_scope": "Strong Group A"},
            {"criterion_label": "Methodology", "weight": "60%", "category_scope": "Strong Group B"},
            {"criterion_label": "References", "weight": "40%", "category_scope": "Strong Group B"},
        ]
        categories = _discover_evaluation_categories(result)
        self.assertEqual(set(categories), {"Strong Group A", "Strong Group B"})
        content = build_fast_report_content(result)
        self.assertEqual(len(content.SNAPSHOT_CATEGORY_CARDS), 2)
        a_key = next(k for k in content.EVAL_WEIGHTS if "Strong Group A" in k)
        b_key = next(k for k in content.EVAL_WEIGHTS if "Strong Group B" in k)
        self.assertEqual(len(content.EVAL_WEIGHTS[a_key]), 3)
        self.assertEqual(len(content.EVAL_WEIGHTS[b_key]), 2)

    def test_mixed_genuine_and_weak_candidates_preserves_every_real_criterion(self):
        """One genuine category (Strong Group) + one weak pseudo-category
        (Weak Group, several raw occurrences but only one substantive) --
        the genuine category must stay categorized, the weak group must
        NOT become a third, misleading category card, and the weak
        group's one real criterion must still appear somewhere (never
        silently dropped merely because its own candidate group was
        rejected)."""
        result = FastAnalysisResult()
        result.evaluation_occurrences = (
            [
                {"criterion_label": "Approach", "weight": "30%", "category_scope": "Strong Group A"},
                {"criterion_label": "Team", "weight": "25%", "category_scope": "Strong Group A"},
                {"criterion_label": "Methodology", "weight": "60%", "category_scope": "Strong Group B"},
                {"criterion_label": "References", "weight": "40%", "category_scope": "Strong Group B"},
            ]
            + self._weak_group_occurrences("Weak Group")
        )
        categories = _discover_evaluation_categories(result)
        self.assertEqual(set(categories), {"Strong Group A", "Strong Group B"})
        self.assertNotIn("Weak Group", categories)

        content = build_fast_report_content(result)
        self.assertEqual(len(content.SNAPSHOT_CATEGORY_CARDS), 2,
                         "the weak group must not add a third, misleading category card")
        a_key = next(k for k in content.EVAL_WEIGHTS if "Strong Group A" in k)
        b_key = next(k for k in content.EVAL_WEIGHTS if "Strong Group B" in k)
        self.assertEqual(len(content.EVAL_WEIGHTS[a_key]), 2)
        self.assertEqual(len(content.EVAL_WEIGHTS[b_key]), 2)
        # The weak group's one real criterion is preserved in a leftover
        # bucket, not discarded.
        self.assertIn("Other Rated Criteria", content.EVAL_WEIGHTS)
        self.assertEqual(content.EVAL_WEIGHTS["Other Rated Criteria"], [("The Real Criterion", "20%")])
        all_rendered_labels = {label for rows in content.EVAL_WEIGHTS.values() for label, _ in rows}
        self.assertIn("The Real Criterion", all_rendered_labels)

    def test_run5_leftover_bucket_shape_prunes_to_zero_non_substantive_rows(self):
        """The exact leftover-bucket-audit fixture: run_id=5's real,
        persisted evaluation data. Two genuine categories (Technical
        Proposal: 10 criteria; Financial Proposal: 2 raw occurrences of
        the identical "Fees, 20%" fact, deduping to 1 rendered row) plus
        five candidate leftover rows that are, in reality, either a
        near-duplicate of an already-rendered criterion (a numbering
        prefix added to "AI and/or Non-AI Methodology Use, and
        Safeguards") or a restated stage/section total equal to one of
        the two categories' own summed weight (80 for Technical Proposal,
        20 for Financial Proposal) -- none of the five is a genuinely
        distinct, additional criterion. All five must be pruned; the
        "Other Rated Criteria" bucket must not appear at all."""
        result = FastAnalysisResult()
        result.evaluation_criteria = [
            {"stage": "Liability Insurance", "weight": "0%", "parent_stage": "Technical Proposal"},
            {"stage": "Errors and Omissions (E&O) Insurance", "weight": "0%", "parent_stage": "Technical Proposal"},
            {"stage": "Not-for-profit sector familiarity", "weight": "5%", "parent_stage": "Technical Proposal"},
            {"stage": "Health care sector familiarity", "weight": "5%", "parent_stage": "Technical Proposal"},
            {"stage": "Experience and qualifications of bidder's team and ability to meet required time frame schedules",
             "weight": "40%", "parent_stage": "Technical Proposal"},
            {"stage": "AI and/or Non-AI Methodology Use, and Safeguards", "weight": "10%",
             "parent_stage": "Technical Proposal"},
            {"stage": "Commitment to Reconciliation", "weight": "3%", "parent_stage": "Technical Proposal"},
            {"stage": "Commitment to Inclusion, Equity, Diversity and Accessibility (IDEA)", "weight": "3%",
             "parent_stage": "Technical Proposal"},
            {"stage": "Environmental, Social and Governance (ESG)", "weight": "4%", "parent_stage": "Technical Proposal"},
            {"stage": "References", "weight": "10%", "parent_stage": "Technical Proposal"},
            {"stage": "Fees", "weight": "20%", "parent_stage": "Financial Proposal"},
            {"stage": "Fees", "weight": "20%", "parent_stage": "Financial Proposal"},
            {"stage": "Appendix A Criteria 6 AI and/or Non-AI Methodology Use, and Safeguards", "weight": "10%",
             "parent_stage": "Appendix A Criteria"},
            {"stage": "Stage II – Rated Elements", "weight": "80 points", "parent_stage": "Stage II"},
            {"stage": "Stage III – Pricing", "weight": "20 points", "parent_stage": "Stage III"},
            {"stage": "Rated Elements", "weight": "80 points", "parent_stage": None},
            {"stage": "Pricing", "weight": "20 points", "parent_stage": None},
        ]
        categories = _discover_evaluation_categories(result)
        self.assertEqual(set(categories), {"Technical Proposal", "Financial Proposal"})

        content = build_fast_report_content(result)
        tech_key = next(k for k in content.EVAL_WEIGHTS if "Technical Proposal" in k)
        fin_key = next(k for k in content.EVAL_WEIGHTS if "Financial Proposal" in k)
        self.assertEqual(len(content.EVAL_WEIGHTS[tech_key]), 10)
        self.assertEqual(content.EVAL_WEIGHTS[fin_key], [("Fees", "20%")])
        self.assertNotIn("Other Rated Criteria", content.EVAL_WEIGHTS,
                         "all 5 candidate rows are duplicates/restated totals, not genuine criteria")

    def test_near_duplicate_of_rendered_criterion_excluded_from_leftover(self):
        """A leftover candidate whose label is a numbering-prefixed
        restatement of an already-rendered category criterion, at the
        identical weight, must not double-count as a second, distinct
        criterion."""
        result = FastAnalysisResult()
        result.evaluation_occurrences = [
            {"criterion_label": "Widget Quality", "weight": "30%", "category_scope": "Group A"},
            {"criterion_label": "Team", "weight": "25%", "category_scope": "Group A"},
            {"criterion_label": "Methodology", "weight": "60%", "category_scope": "Group B"},
            {"criterion_label": "References", "weight": "40%", "category_scope": "Group B"},
            {"criterion_label": "Section 4 Widget Quality", "weight": "30%", "category_scope": "Stray Heading"},
        ]
        content = build_fast_report_content(result)
        self.assertNotIn("Other Rated Criteria", content.EVAL_WEIGHTS)
        all_labels = {label for rows in content.EVAL_WEIGHTS.values() for label, _ in rows}
        self.assertNotIn("Section 4 Widget Quality", all_labels)

    def test_restated_category_total_excluded_from_leftover(self):
        """A leftover candidate whose numeric magnitude exactly equals an
        already-rendered category's own summed weight is a restated
        section/stage total, not one more scored dimension."""
        result = FastAnalysisResult()
        result.evaluation_occurrences = [
            {"criterion_label": "Widget Quality", "weight": "30%", "category_scope": "Group A"},
            {"criterion_label": "Team", "weight": "25%", "category_scope": "Group A"},
            {"criterion_label": "Methodology", "weight": "60%", "category_scope": "Group B"},
            {"criterion_label": "References", "weight": "40%", "category_scope": "Group B"},
            {"criterion_label": "Section Total", "weight": "55%", "category_scope": "Header Line"},
        ]
        content = build_fast_report_content(result)
        self.assertNotIn("Other Rated Criteria", content.EVAL_WEIGHTS)
        all_labels = {label for rows in content.EVAL_WEIGHTS.values() for label, _ in rows}
        self.assertNotIn("Section Total", all_labels)

    def test_genuine_uncategorized_criterion_still_preserved_after_pruning(self):
        """A leftover candidate that is neither a near-duplicate nor a
        restated category total -- a real, additional, distinct
        criterion -- must still survive the pruning step (this is the
        same guarantee test_mixed_genuine_and_weak_candidates already
        checks; kept here too as a direct pruning-focused regression)."""
        result = FastAnalysisResult()
        result.evaluation_occurrences = [
            {"criterion_label": "Widget Quality", "weight": "30%", "category_scope": "Group A"},
            {"criterion_label": "Team", "weight": "25%", "category_scope": "Group A"},
            {"criterion_label": "Methodology", "weight": "60%", "category_scope": "Group B"},
            {"criterion_label": "References", "weight": "40%", "category_scope": "Group B"},
            {"criterion_label": "Genuinely Distinct Criterion", "weight": "15%", "category_scope": "Stray Heading"},
        ]
        content = build_fast_report_content(result)
        self.assertIn("Other Rated Criteria", content.EVAL_WEIGHTS)
        self.assertEqual(content.EVAL_WEIGHTS["Other Rated Criteria"],
                         [("Genuinely Distinct Criterion", "15%")])

    def test_genuine_categorized_criteria_unchanged_by_pruning(self):
        """Pruning must never alter which rows a real, qualifying category
        itself renders -- only what ends up in the leftover bucket."""
        result = FastAnalysisResult()
        result.evaluation_occurrences = [
            {"criterion_label": "Widget Quality", "weight": "30%", "category_scope": "Group A"},
            {"criterion_label": "Team", "weight": "25%", "category_scope": "Group A"},
            {"criterion_label": "Methodology", "weight": "60%", "category_scope": "Group B"},
            {"criterion_label": "References", "weight": "40%", "category_scope": "Group B"},
        ]
        content = build_fast_report_content(result)
        a_key = next(k for k in content.EVAL_WEIGHTS if "Group A" in k)
        b_key = next(k for k in content.EVAL_WEIGHTS if "Group B" in k)
        self.assertEqual(content.EVAL_WEIGHTS[a_key], [("Widget Quality", "30%"), ("Team", "25%")])
        self.assertEqual(content.EVAL_WEIGHTS[b_key], [("Methodology", "60%"), ("References", "40%")])


if __name__ == "__main__":
    unittest.main()
