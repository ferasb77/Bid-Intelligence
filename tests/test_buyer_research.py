"""
tests/test_buyer_research.py -- Deterministic Unit Tests for Governed Buyer Research.

Tests Phase F-M contracts without network calls:
1. MAX_SEARCHES = 3 hard budget strictly enforced.
2. MAX_ACCEPTED_OFFICIAL_PAGES = 6 hard budget strictly enforced.
3. Official source domain boundary:
   - Accepts official domain (yorku.ca, bankofcanada.ca, .gc.ca, .gov).
   - Rejects blogs, directories, commercial aggregators, Wikipedia, LinkedIn.
4. Verbatim extract verification:
   - Accepts quotes that appear verbatim in fetched page text.
   - Refuses / rejects fabricated extracts not present in page text.
5. Separation of Truth Classes:
   - Signals are strictly FactClass.AUTHORITATIVE_BUYER_FACT or PUBLIC_ORGANIZATIONAL_INFORMATION.
6. Deterministic Fingerprint & Exact Reuse:
   - Query fingerprint is deterministic.
   - Second call with identical input yields cached result with 0 searches, 0 fetches.
7. Clean failure when provider / network is unavailable.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import buyer_research as br
from buyer_intelligence import FactClass


class TestBuyerResearchBudgetsAndSources(unittest.TestCase):
    def setUp(self):
        br.clear_research_cache()

    def tearDown(self):
        br.clear_research_cache()

    def test_budget_constants(self):
        self.assertEqual(br.MAX_SEARCHES, 3)
        self.assertEqual(br.MAX_ACCEPTED_OFFICIAL_PAGES, 6)

    def test_official_source_filtering(self):
        # Allowed official sources
        self.assertTrue(br.is_official_source_allowed("https://www.yorku.ca/procurement/policy", "York University"))
        self.assertTrue(br.is_official_source_allowed("https://www.bankofcanada.ca/about/", "Bank of Canada"))
        self.assertTrue(br.is_official_source_allowed("https://www.ontario.ca/page/public-procurement", "Ontario Government"))
        self.assertTrue(br.is_official_source_allowed("https://buyandsell.gc.ca/policy", "Government of Canada"))

        # Disallowed sources (social, wiki, blog, directories)
        self.assertFalse(br.is_official_source_allowed("https://en.wikipedia.org/wiki/York_University", "York University"))
        self.assertFalse(br.is_official_source_allowed("https://www.linkedin.com/school/york-university/", "York University"))
        self.assertFalse(br.is_official_source_allowed("https://myblog.com/york-procurement", "York University"))
        self.assertFalse(br.is_official_source_allowed("https://www.glassdoor.com/york", "York University"))
        self.assertFalse(br.is_official_source_allowed("invalid-url", "York University"))

    def test_hard_search_budget_enforcement(self):
        search_mock = MagicMock(return_value=[
            {"url": "https://www.yorku.ca/page1", "title": "Page 1"}
        ])
        fetch_mock = MagicMock(return_value="York University is an established teaching and research university located in Ontario Canada.")

        # Request with max_searches = 3
        res = br.run_governed_buyer_research(
            "York University",
            search_fn=search_mock,
            fetch_fn=fetch_mock,
            max_searches=3,
        )
        self.assertLessEqual(search_mock.call_count, 3)
        self.assertEqual(res.searches_executed, 3)
        self.assertEqual(res.status, br.ResearchStatus.COMPLETE)

    def test_hard_pages_budget_enforcement(self):
        # Return 10 candidate URLs from 1 search
        search_mock = MagicMock(return_value=[
            {"url": f"https://www.yorku.ca/page{i}", "title": f"Page {i}"}
            for i in range(12)
        ])
        fetch_mock = MagicMock(return_value="York University is an established teaching and research university located in Ontario Canada.")

        res = br.run_governed_buyer_research(
            "York University",
            search_fn=search_mock,
            fetch_fn=fetch_mock,
            max_searches=1,
            max_pages=6,
        )
        self.assertLessEqual(fetch_mock.call_count, 6)
        self.assertEqual(res.pages_accepted, 6)

    def test_verbatim_quote_verification(self):
        page_text = "York University provides comprehensive undergraduate and graduate programs across diverse faculties."
        search_mock = MagicMock(return_value=[{"url": "https://www.yorku.ca/about", "title": "About York"}])
        fetch_mock = MagicMock(return_value=page_text)

        res = br.run_governed_buyer_research(
            "York University",
            search_fn=search_mock,
            fetch_fn=fetch_mock,
        )
        self.assertEqual(res.status, br.ResearchStatus.COMPLETE)
        self.assertTrue(len(res.signals) > 0)
        for s in res.signals:
            self.assertIn(s.verbatim_quote, page_text)
            self.assertEqual(s.fact_class, FactClass.AUTHORITATIVE_BUYER_FACT.value)
            self.assertTrue(s.source_url.startswith("https://www.yorku.ca"))

    def test_exact_reuse_makes_zero_search_and_fetch_calls(self):
        search_mock = MagicMock(return_value=[{"url": "https://www.yorku.ca/about", "title": "About York"}])
        fetch_mock = MagicMock(return_value="York University is an established teaching and research university located in Ontario Canada.")

        # First run (populates cache)
        first_res = br.run_governed_buyer_research(
            "York University",
            search_fn=search_mock,
            fetch_fn=fetch_mock,
        )
        self.assertEqual(first_res.searches_executed, 3)
        self.assertFalse(first_res.cached_reuse)

        # Reset mocks
        search_mock.reset_mock()
        fetch_mock.reset_mock()

        # Second run with identical input (exact reuse)
        second_res = br.run_governed_buyer_research(
            "York University",
            search_fn=search_mock,
            fetch_fn=fetch_mock,
        )
        self.assertTrue(second_res.cached_reuse)
        self.assertEqual(second_res.searches_executed, 0)
        search_mock.assert_not_called()
        fetch_mock.assert_not_called()
        self.assertEqual(second_res.query_fingerprint, first_res.query_fingerprint)
        self.assertEqual(len(second_res.signals), len(first_res.signals))

    def test_unavailable_when_no_adapters_provided(self):
        res = br.run_governed_buyer_research("City of Edmonton")
        self.assertEqual(res.status, br.ResearchStatus.UNAVAILABLE)
        self.assertEqual(res.searches_executed, 0)
        self.assertEqual(res.pages_accepted, 0)


if __name__ == "__main__":
    unittest.main()
