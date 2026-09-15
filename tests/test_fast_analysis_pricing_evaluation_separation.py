"""
tests/test_fast_analysis_pricing_evaluation_separation.py

Product Integration Phase 6 correction: pricing-formula weights must never
be presented as rated evaluation criteria, and genuine price/financial
evaluation weights must never be suppressed merely because they concern
price. Root cause (Phase 6 holdout, City of Calgary run_id=6): the shared
extraction schema (`fast_analysis.py`'s `_EVAL_SCHEMA` / `_EVAL_FOCUSED_
SCHEMA`) asked the model to "extract EVERY stated evaluation-criterion
point/weight value" with no semantic distinction between a weight that
scores/ranks a bidder's submission and a weight used only to calculate a
bidder's own price (e.g. a weighted blend of resource rates or cost
line-items into one price figure) -- so a real pricing-formula table
(Addendum Five's "Item / Weight / Weighted Cost" table, 55%/35%/10%) was
classified as `evaluation_criteria` at extraction time, before the report
adapter ever sees it.

This is a CASE B correction (Phase 5's diagnostic framework): the
generalizable fix is a small, procurement-agnostic clarification added to
both evaluation-extracting schemas, not an adapter/routing change -- the
report adapter (`scripts/fast_analysis_report_adapter.py`) was not
modified and has no logic that could distinguish these two kinds of
weight; it renders whatever `evaluation_criteria`/`evaluation_occurrences`
the engine returns. These tests are therefore adapter-level CONTRACT
tests proving the adapter's existing, unmodified pass-through behavior is
correct on both sides of the boundary the schema fix now draws:

  - Pricing-calculation weights that never appear in evaluation_criteria
    (as the corrected schema now instructs) do not fabricate an evaluation
    table, and the same facts remain visible as commercial/pricing
    content.
  - Genuine evaluation weights -- including price/financial treated as
    ONE OF SEVERAL factors used to select the winning bidder -- are never
    suppressed merely because they concern price or money.

No live LLM call is made by any test in this file. See
BID_INTELLIGENCE_PHASE6_THIRD_PROCUREMENT_HOLDOUT_REPORT.md's "POST-
HOLDOUT GENERALIZATION CORRECTION" section for the live validation this
deterministic layer was combined with.
"""
import unittest

from fast_analysis import (
    FastAnalysisResult, _EVAL_SCHEMA, _EVAL_FOCUSED_SCHEMA, _IDENTITY_EVAL_REQ_SCHEMA,
)
from scripts.fast_analysis_report_adapter import build_fast_report_content


class TestSchemaCarriesTheSemanticDistinction(unittest.TestCase):
    """The extraction schemas themselves state the evaluation-vs-pricing-
    calculation distinction -- procurement-agnostic, no buyer/corpus
    names, no numeric-pattern rule (instruction 6: not "sums to 100",
    not "three percentages", not any keyword-only test)."""

    def test_eval_schema_distinguishes_scoring_weight_from_pricing_calculation_weight(self):
        for schema in (_EVAL_SCHEMA, _EVAL_FOCUSED_SCHEMA):
            self.assertIn("CALCULATE a bidder's own price", schema)
            self.assertIn("Technical 80%, Price 20%", schema,
                         "must explicitly preserve legitimate price-as-a-factor evaluation weights")
        for schema in (_EVAL_SCHEMA, _EVAL_FOCUSED_SCHEMA):
            for buyer_specific in ("Calgary", "City of Calgary", "26-1603", "55%", "35%", "10%"):
                self.assertNotIn(buyer_specific, schema,
                                 f"schema must stay procurement-agnostic -- found {buyer_specific!r}")

    def test_excluded_weight_is_pointed_toward_a_home_that_preserves_it(self):
        """A weight excluded from evaluation_criteria must not simply be
        discarded -- the schema must point the model toward capturing it
        elsewhere (with its actual values), or the correction trades one
        defect (false evaluation criteria) for another (silently lost
        pricing intelligence)."""
        self.assertIn("capture the weighting there instead", _EVAL_SCHEMA)
        self.assertIn("preserved verbatim", _EVAL_SCHEMA)
        self.assertIn("pricing-calculation formula or", _IDENTITY_EVAL_REQ_SCHEMA)
        self.assertIn("preserve the actual", _IDENTITY_EVAL_REQ_SCHEMA)


class TestCase1CalgaryStylePricingFormulaExcludedFromEvaluation(unittest.TestCase):
    """A weighted blend of resource rates used to calculate a bidder's own
    price (the exact Calgary run_id=6 shape) must not fabricate an
    evaluation table -- and the pricing fact itself must remain visible
    as commercial/pricing content, not silently dropped."""

    def test_pricing_formula_not_in_evaluation_when_correctly_unextracted(self):
        """Simulates the CORRECTED extraction contract: a pricing-rate
        weighting table is never placed in evaluation_criteria/
        evaluation_occurrences at all (the schema fix's whole point) --
        confirming the adapter fabricates no evaluation table from
        commercial content it was never given as evaluation data."""
        result = FastAnalysisResult()
        result.evaluation_criteria = []
        result.evaluation_occurrences = []
        result.commercial_clauses = [
            {"clause_kind": "PRICING_ESCALATION",
             "source_fact": "Blended rate calculated as Senior resource rate x 55% + "
                            "Intermediate resource rate x 35% + Junior resource rate x 10%.",
             "source_doc": "pricing-form.pdf"},
        ]
        content = build_fast_report_content(result)
        self.assertEqual(content.EVAL_WEIGHTS, {}, "no evaluation table may be fabricated")
        self.assertEqual(content.FACT_ORIGINS.get("EVAL_WEIGHTS.flat"), "MISSING_NO_FALLBACK")
        labels = [row[0] for row in content.COMMERCIAL_POINTS]
        self.assertIn("Pricing Escalation", labels, "the pricing-formula fact itself must survive")


class TestCase2GenuineTechnicalFinancialEvaluationRetained(unittest.TestCase):
    """A real Technical/Financial evaluation split (e.g. Technical 80%,
    Financial 20%) is a genuine evaluation structure and must render as
    one -- price-as-a-selection-factor is not suppressed."""

    def test_technical_and_financial_weights_both_retained(self):
        result = FastAnalysisResult()
        result.evaluation_criteria = [
            {"stage": "Technical Proposal", "weight": "80%", "parent_stage": None},
            {"stage": "Financial Proposal", "weight": "20%", "parent_stage": None},
        ]
        content = build_fast_report_content(result)
        self.assertIn("Rated Criteria", content.EVAL_WEIGHTS)
        rows = dict(content.EVAL_WEIGHTS["Rated Criteria"])
        self.assertEqual(rows.get("Technical Proposal"), "80%")
        self.assertEqual(rows.get("Financial Proposal"), "20%")


class TestCase3PriceCriterionAmongMultipleRetained(unittest.TestCase):
    """A Price line item stated alongside Methodology/Experience/Team as
    one of several rated criteria is a genuine evaluation criterion and
    must be retained exactly like its siblings."""

    def test_all_four_criteria_including_price_retained(self):
        result = FastAnalysisResult()
        result.evaluation_criteria = [
            {"stage": "Methodology", "weight": "40 points", "parent_stage": None},
            {"stage": "Experience", "weight": "30 points", "parent_stage": None},
            {"stage": "Team", "weight": "10 points", "parent_stage": None},
            {"stage": "Price", "weight": "20 points", "parent_stage": None},
        ]
        content = build_fast_report_content(result)
        self.assertIn("Rated Criteria", content.EVAL_WEIGHTS)
        rows = dict(content.EVAL_WEIGHTS["Rated Criteria"])
        self.assertEqual(rows.get("Methodology"), "40 points")
        self.assertEqual(rows.get("Experience"), "30 points")
        self.assertEqual(rows.get("Team"), "10 points")
        self.assertEqual(rows.get("Price"), "20 points")
        self.assertEqual(len(content.EVAL_WEIGHTS["Rated Criteria"]), 4)


class TestCase4WeightedQuantityPricingTableExcludedFromEvaluation(unittest.TestCase):
    """A weighted mix of quantities/usage scenarios used to build a price
    (e.g. two workshop types weighted 60%/40% into one blended cost) is a
    pricing/commercial fact only -- never an evaluation criterion."""

    def test_weighted_workshop_mix_is_commercial_only_not_evaluation(self):
        result = FastAnalysisResult()
        result.evaluation_criteria = []
        result.evaluation_occurrences = []
        result.commercial_clauses = [
            {"clause_kind": "PRICING_ESCALATION",
             "source_fact": "Blended workshop rate calculated as Workshop Type A x 60% + "
                            "Workshop Type B x 40%.",
             "source_doc": "pricing-form.pdf"},
        ]
        content = build_fast_report_content(result)
        self.assertEqual(content.EVAL_WEIGHTS, {})
        labels = [row[0] for row in content.COMMERCIAL_POINTS]
        self.assertIn("Pricing Escalation", labels)


class TestCrossDomainSemanticBoundary(unittest.TestCase):
    """Permanent standing regression: commercial numeric weights cannot
    enter evaluation merely because they look like weighted criteria, and
    conversely, legitimate financial evaluation weights are never removed
    merely because they concern price -- both directions verified
    together against one mixed corpus."""

    def test_pricing_weights_and_genuine_price_evaluation_coexist_correctly(self):
        result = FastAnalysisResult()
        # Genuine evaluation structure: Technical vs. Price, both real
        # rated factors used to select the winner.
        result.evaluation_criteria = [
            {"stage": "Technical Proposal", "weight": "70%", "parent_stage": None},
            {"stage": "Price", "weight": "30%", "parent_stage": None},
        ]
        # A separate, purely pricing-calculation weighting -- never placed
        # in evaluation_criteria at all (this is what the schema fix
        # ensures at extraction time; here we assert the adapter does not
        # invent a bridge between the two even when both are present in
        # the same corpus).
        result.commercial_clauses = [
            {"clause_kind": "PRICING_ESCALATION",
             "source_fact": "Blended hourly rate calculated as Senior rate x 55% + Junior rate x 45%.",
             "source_doc": "pricing-form.pdf"},
        ]
        content = build_fast_report_content(result)

        rows = dict(content.EVAL_WEIGHTS.get("Rated Criteria", []))
        self.assertEqual(rows.get("Technical Proposal"), "70%",
                         "genuine evaluation weight must not be removed for concerning price")
        self.assertEqual(rows.get("Price"), "30%",
                         "genuine price-as-a-factor evaluation weight must not be removed")
        self.assertNotIn("Senior rate", str(content.EVAL_WEIGHTS),
                         "pricing-calculation weight must never enter the evaluation table")

        commercial_labels = [row[0] for row in content.COMMERCIAL_POINTS]
        self.assertIn("Pricing Escalation", commercial_labels,
                      "pricing-calculation fact must remain visible as commercial content")


class TestScopedDateAmbiguityFramingMatchesActualData(unittest.TestCase):
    """Phase 6 holdout minor defect (City of Calgary run_id=6):
    `CATEGORY_DATE_DISTINCTION` always used "category/scope" wording even
    for a corpus with no category structure at all, where the real cause
    is typically sequential amendment supersession, not a parallel,
    category-scoped split. The detector's own trigger condition (2+
    distinct dates for one milestone kind) is unchanged -- only the
    wording now reflects whether the triggering occurrences actually
    carry real scope data, so Bank of Canada's genuine category-scoped
    finding renders exactly as before."""

    def test_no_real_scope_data_uses_generic_wording(self):
        import fast_analysis as fa
        result = FastAnalysisResult()
        result.typed_observations = [
            {"family": "MILESTONE", "semantic_kind": "SUBMISSION_DEADLINE", "date": "2026-07-07",
             "scope": {"component": None, "lot": None, "category": None}, "source_doc": "a.pdf"},
            {"family": "MILESTONE", "semantic_kind": "SUBMISSION_DEADLINE", "date": "2026-07-16",
             "scope": {"component": None, "lot": None, "category": None}, "source_doc": "b.pdf"},
        ]
        result.ambiguities = {
            "evaluation_weight_conflicts": [], "pricing_stage_ambiguity": [],
            "category_date_distinctions": fa.detect_category_date_distinctions(result.typed_observations),
        }
        content = build_fast_report_content(result)
        self.assertEqual(len(content.AMBIGUITIES), 1)
        self.assertNotIn("category/scope", content.AMBIGUITIES[0]["question"])
        self.assertNotIn("category", content.AMBIGUITIES[0]["why"].lower())

    def test_real_scope_data_still_uses_category_scope_wording_boc_unregressed(self):
        """The exact Bank of Canada shape -- category-scoped presentation
        dates -- must render with the original, unchanged wording."""
        import fast_analysis as fa
        result = FastAnalysisResult()
        result.typed_observations = [
            {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO", "date": "2026-10-26",
             "scope": {"component": None, "lot": None, "category": "Category 1"}, "source_doc": "a.pdf"},
            {"family": "MILESTONE", "semantic_kind": "PRESENTATION_OR_DEMO", "date": "2026-11-02",
             "scope": {"component": None, "lot": None, "category": "Category 3"}, "source_doc": "b.pdf"},
        ]
        result.ambiguities = {
            "evaluation_weight_conflicts": [], "pricing_stage_ambiguity": [],
            "category_date_distinctions": fa.detect_category_date_distinctions(result.typed_observations),
        }
        content = build_fast_report_content(result)
        self.assertEqual(len(content.AMBIGUITIES), 1)
        self.assertEqual(content.AMBIGUITIES[0]["question"],
                         "Please confirm the date applicable to each category/scope.")
        self.assertEqual(content.AMBIGUITIES[0]["why"],
                         "Likely category-specific scheduling, not a true conflict, but worth confirming.")


if __name__ == "__main__":
    unittest.main()
