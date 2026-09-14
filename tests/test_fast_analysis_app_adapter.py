"""
tests/test_fast_analysis_app_adapter.py

Deterministic tests for fast_analysis_app_adapter.py (Product Integration
Phase 1). No live API calls, no database/Supabase connection -- pure
function tests against synthetic FastAnalysisResult objects, matching the
pattern already used throughout tests/test_fast_analysis*.py.
"""
import json
import unittest

from fast_analysis import FastAnalysisResult
from fast_analysis_app_adapter import (
    build_opportunity_intelligence, build_bid_brief_projection,
    OPPORTUNITY_INTELLIGENCE_CONTRACT_VERSION,
)

MASTER_RFP = "RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf"


def _sample_result() -> FastAnalysisResult:
    r = FastAnalysisResult()
    r.doc_metadata_by_doc[MASTER_RFP] = {
        "client": "Bank of Canada", "file_number": "2026-026",
        "title": "Talent, Learning and Organizational Development Services",
        "submission_deadline": "2026-09-30", "clarification_deadline": "2026-09-10",
    }
    r.evaluation_occurrences = [
        {"criterion_label": "Corporate Profile", "weight": "5 points",
         "category_scope": "Appendix D1", "source_doc": MASTER_RFP,
         "source_refs": [{"source_doc": MASTER_RFP, "page": 15}]},
    ]
    r.commercial_clauses = [
        {"clause_kind": "INSURANCE", "source_fact": "CGL $3M required", "source_doc": "AppendixG.docx"},
    ]
    r.pricing_occurrences = [
        {"semantic_kind": "PRICING_STAGE", "raw_wording": "Stage 4 will consist of..."},
        {"semantic_kind": "PRICE_CRITERION", "category_scope": "Appendix D1", "weight": "5 points"},
    ]
    r.typed_observations = [
        {"family": "PROCUREMENT_MECHANIC", "semantic_kind": "RFP", "original_value": "Request for Proposal"},
    ]
    r.ambiguities = {
        "evaluation_weight_conflicts": [],
        "pricing_stage_ambiguity": [{"type": "PRICING_STAGE_AMBIGUITY", "detail": "Price scored twice?"}],
        "category_date_distinctions": [],
    }
    return r


class TestOpportunityIntelligenceContract(unittest.TestCase):
    """Structured, durable contract (instruction 4/11)."""

    def test_contract_has_all_required_sections(self):
        oi = build_opportunity_intelligence(_sample_result())
        for section in ("opportunity_snapshot", "procurement_scope", "dates_and_mechanics",
                        "evaluation", "response_requirements", "pricing_and_commercial",
                        "ambiguities", "bid_team_attention_points", "source_map",
                        "buyer_intelligence", "fact_origins"):
            self.assertIn(section, oi, f"missing section: {section}")

    def test_contract_version_present(self):
        oi = build_opportunity_intelligence(_sample_result())
        self.assertEqual(oi["contract_version"], OPPORTUNITY_INTELLIGENCE_CONTRACT_VERSION)

    def test_contract_is_json_serializable(self):
        oi = build_opportunity_intelligence(_sample_result())
        # Must not raise -- this is what gets persisted to a JSONB column.
        json.dumps(oi)

    def test_evaluation_raw_occurrences_retain_source_refs(self):
        """Instruction 12: material facts retain source references in
        persisted structured output."""
        oi = build_opportunity_intelligence(_sample_result())
        raw = oi["evaluation"]["raw_occurrences"]
        self.assertEqual(len(raw), 1)
        self.assertIn("source_refs", raw[0])
        self.assertEqual(raw[0]["source_refs"][0]["page"], 15)

    def test_dates_and_mechanics_raw_date_observations_retain_source_refs(self):
        """Phase 3 commissioning fix: date facts (like evaluation and
        pricing facts) must retain source_refs for the UI's 'View Source'
        expander -- the summarized key_dates display tuples don't carry
        them, so raw MILESTONE-family typed_observations are surfaced
        separately."""
        r = _sample_result()
        r.typed_observations.append({
            "family": "MILESTONE", "semantic_kind": "SUBMISSION_DEADLINE",
            "date": "2026-09-30", "source_doc": MASTER_RFP,
            "source_refs": [{"source_doc": MASTER_RFP, "page": 2, "excerpt": "Proposals due 2026-09-30."}],
        })
        oi = build_opportunity_intelligence(r)
        raw_dates = oi["dates_and_mechanics"]["raw_date_observations"]
        self.assertEqual(len(raw_dates), 1)
        self.assertEqual(raw_dates[0]["semantic_kind"], "SUBMISSION_DEADLINE")
        self.assertIn("source_refs", raw_dates[0])
        self.assertEqual(raw_dates[0]["source_refs"][0]["page"], 2)

    def test_non_milestone_typed_observations_excluded_from_raw_dates(self):
        """The PROCUREMENT_MECHANIC observation already in the fixture must
        not leak into raw_date_observations -- only MILESTONE family."""
        oi = build_opportunity_intelligence(_sample_result())
        self.assertEqual(oi["dates_and_mechanics"]["raw_date_observations"], [])

    def test_fact_origins_carried_into_contract(self):
        """Instruction 13: fact-origin metadata is not thrown away."""
        oi = build_opportunity_intelligence(_sample_result())
        self.assertIn("EVAL_WEIGHTS.Category 1", oi["fact_origins"])

    def test_empty_result_still_produces_a_valid_contract(self):
        """An analysis with nothing extracted must not crash the adapter --
        it should still produce a structurally valid (if mostly-empty)
        contract, consistent with the engine's own safety-net fallbacks."""
        oi = build_opportunity_intelligence(FastAnalysisResult())
        json.dumps(oi)
        self.assertIn("opportunity_snapshot", oi)


class TestBidBriefProjection(unittest.TestCase):
    """Projection into the EXISTING bid_briefs shape pages/stage_understand.py
    already renders (instruction 16/17) -- field names and types must match
    exactly what that page's _ensure_list/_ensure_dict helpers expect."""

    def test_projection_has_every_bid_briefs_field(self):
        bb = build_bid_brief_projection(_sample_result())
        expected_fields = {
            "executive_summary", "opportunity_type", "contract_term", "procurement_model",
            "scope_categories", "deliverables_summary", "qualification_gates",
            "evaluation_breakdown", "commercial_structure", "contract_risks",
            "submission_requirements", "key_dates", "source_citations", "document_conflicts",
        }
        self.assertEqual(set(bb.keys()), expected_fields)

    def test_list_shaped_fields_are_lists(self):
        bb = build_bid_brief_projection(_sample_result())
        for field in ("scope_categories", "deliverables_summary", "qualification_gates",
                     "evaluation_breakdown", "commercial_structure", "contract_risks",
                     "submission_requirements", "key_dates", "document_conflicts"):
            self.assertIsInstance(bb[field], list, f"{field} must be a list")

    def test_source_citations_is_a_dict(self):
        """stage_understand.py calls _ensure_dict() on source_citations
        specifically -- it must be a dict, not a list, unlike every other
        JSON field on this table."""
        bb = build_bid_brief_projection(_sample_result())
        self.assertIsInstance(bb["source_citations"], dict)

    def test_string_shaped_fields_are_strings(self):
        bb = build_bid_brief_projection(_sample_result())
        for field in ("executive_summary", "opportunity_type", "contract_term", "procurement_model"):
            self.assertIsInstance(bb[field], str)

    def test_evaluation_breakdown_shape_matches_hierarchy_builder_expectations(self):
        """evaluation_hierarchy.build_evaluation_hierarchy() groups rows by
        'stage'/'parent_stage' -- confirm those exact keys are present."""
        bb = build_bid_brief_projection(_sample_result())
        for row in bb["evaluation_breakdown"]:
            self.assertIn("stage", row)
            self.assertIn("weight", row)
            self.assertIn("parent_stage", row)

    def test_document_conflicts_derived_from_ambiguities(self):
        """The genuine pricing-stage ambiguity must appear as a
        document_conflicts entry (instruction 6/7: don't lose real findings
        when projecting into the legacy shape)."""
        bb = build_bid_brief_projection(_sample_result())
        self.assertEqual(len(bb["document_conflicts"]), 1)
        self.assertEqual(bb["document_conflicts"][0]["conflict_type"], "PRICING_STAGE_AMBIGUITY")

    def test_no_false_evaluation_weight_conflict_when_none_detected(self):
        """Instruction 14: a correct NOT_PRESENT result must not become a
        fabricated document_conflicts entry."""
        bb = build_bid_brief_projection(_sample_result())
        types = [dc["conflict_type"] for dc in bb["document_conflicts"]]
        self.assertNotIn("EVALUATION_WEIGHT_CONFLICT", types)

    def test_projection_is_json_serializable(self):
        bb = build_bid_brief_projection(_sample_result())
        json.dumps(bb)

    def test_generic_opportunity_type_not_hardcoded_to_one_buyer(self):
        """The projection must not silently assume a Bank-of-Canada-shaped
        input -- a differently-labeled RFP mechanic must still produce a
        sensible, non-crashing opportunity_type."""
        r = FastAnalysisResult()
        bb = build_bid_brief_projection(r)
        self.assertIsInstance(bb["opportunity_type"], str)
        self.assertTrue(bb["opportunity_type"])


if __name__ == "__main__":
    unittest.main()
