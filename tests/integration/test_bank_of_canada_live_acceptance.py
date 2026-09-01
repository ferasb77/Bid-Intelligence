"""
Integration Acceptance Harness: Bank of Canada RFP No. 2026-026 Live Package Acceptance
Executes actual package ingestion, document extraction, normalization, and Bid Brief synthesis
against real Bank of Canada procurement documents when supplied.

Gated by: RUN_LIVE_AI_TESTS=1 and physical presence of source documents.
"""
import os
import unittest


class TestBankOfCanadaLiveAcceptance(unittest.TestCase):
    """
    Live AI & Multi-Document Extraction Test for Bank of Canada RFP No. 2026-026.
    
    IMPORTANT: This test will NOT falsely report PASS when source documents or API keys are missing.
    It will explicitly report NOT EXECUTED.
    """

    def setUp(self):
        self.live_enabled = os.getenv("RUN_LIVE_AI_TESTS") == "1"
        self.fixtures_dir = os.path.join(os.path.dirname(__file__), "..", "fixtures", "bank_of_canada_2026_026")
        self.has_fixtures = os.path.exists(self.fixtures_dir) and len(os.listdir(self.fixtures_dir)) > 0
        self.has_api_key = bool(os.getenv("ANTHROPIC_API_KEY"))

    def test_live_bank_of_canada_package_extraction(self):
        if not self.live_enabled or not self.has_fixtures or not self.has_api_key:
            self.skipTest(
                "NOT EXECUTED: Bank of Canada source procurement package fixture files, "
                "live Anthropic API key, or RUN_LIVE_AI_TESTS=1 not configured in test environment."
            )

        # Execution path when live fixtures and environment are provided
        from extractor import extract_procurement_package, unpack_procurement_package
        raw_files = []
        for fname in os.listdir(self.fixtures_dir):
            fpath = os.path.join(self.fixtures_dir, fname)
            with open(fpath, "rb") as f:
                raw_files.append((fname, f.read()))

        pkg_files, _ = unpack_procurement_package(raw_files)
        api_key = os.getenv("ANTHROPIC_API_KEY")
        result, model_used = extract_procurement_package(pkg_files, api_key)

        brief = result.get("brief", {})
        scope_cats = brief.get("scope_categories", [])
        
        # Verify 3 service categories
        self.assertEqual(len(scope_cats), 3)
        # Verify 75/25 technical/pricing ratio
        eval_items = brief.get("evaluation_breakdown", [])
        self.assertTrue(any("75" in str(e) for e in eval_items))
        self.assertTrue(any("25" in str(e) for e in eval_items))


if __name__ == "__main__":
    unittest.main()
