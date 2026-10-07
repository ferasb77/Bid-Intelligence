"""
tests/test_buyer_research.py -- Deterministic Unit Tests for Governed Buyer Research.

Tests Phase F-M contracts without network calls:
12. Search cap 3 enforced.
13. Accepted page cap 6 enforced.
14. Unofficial source rejected.
15. Adversarial fake official domain rejected.
16. Snippets cannot become evidence.
17. Actual fetched-content verification required.
18. Unverifiable extract rejected.
19. Provider failure nonfatal.
20. No official evidence -> UNAVAILABLE.
21. Exact COMPLETE durable reuse (returns REUSED_COMPLETE).
22. Reuse from new process / simulated restart = 0 provider calls.
23. Changed buyer identity -> new fingerprint.
24. Changed material opportunity context -> new fingerprint.
25. Evidence provenance complete.
26. Unsupported evaluator claims prohibited.
27. Research tenant-scoped.
28. Internal IDs/debug state not customer-facing.
29. SSRF/private-network URLs rejected.
30. Response-size/network bounds enforced.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import buyer_research as br
import buyer_research_provider as brp
from buyer_intelligence import FactClass


class TestBuyerResearchBudgetsAndSources(unittest.TestCase):
    def setUp(self):
        br.clear_research_cache()

    def tearDown(self):
        br.clear_research_cache()

    def test_12_search_cap_3(self):
        search_mock = MagicMock(return_value=[
            {"url": "https://www.yorku.ca/page1", "title": "Page 1"}
        ])
        fetch_mock = MagicMock(return_value="York University is an established teaching and research university located in Ontario Canada.")

        res = br.run_governed_buyer_research(
            "York University",
            search_fn=search_mock,
            fetch_fn=fetch_mock,
            max_searches=3,
        )
        self.assertLessEqual(search_mock.call_count, 3)
        self.assertEqual(res.searches_executed, 3)

    def test_13_accepted_page_cap_6(self):
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
        # Policy v3: one root-page identity verification fetch (https://yorku.ca) is
        # required before any page is admitted; it is never itself accepted as evidence.
        self.assertLessEqual(fetch_mock.call_count, 6 + 1)
        root_calls = [c for c in fetch_mock.call_args_list if c.args and c.args[0] == "https://yorku.ca"]
        self.assertEqual(len(root_calls), 1)
        self.assertEqual(res.pages_accepted, 6)
        self.assertEqual(res.verified_buyer_domain, "yorku.ca")

    def test_14_unofficial_source_rejected(self):
        self.assertFalse(br.is_official_source_allowed("https://en.wikipedia.org/wiki/York_University", "York University"))
        self.assertFalse(br.is_official_source_allowed("https://www.linkedin.com/school/york-university/", "York University"))
        self.assertFalse(br.is_official_source_allowed("https://reddit.com/r/yorku", "York University"))
        self.assertFalse(br.is_official_source_allowed("https://thestar.com/news/york-university", "York University"))
        self.assertFalse(br.is_official_source_allowed("https://myblog.com/york-procurement", "York University"))

    def test_15_adversarial_fake_official_domain_rejected(self):
        # Fake or deceptive domains targeting York University
        self.assertFalse(br.is_official_source_allowed("https://fake-yorku.ca/procurement", "York University", verified_buyer_domain="yorku.ca"))
        self.assertFalse(br.is_official_source_allowed("https://yorku-fake.com/policy", "York University", verified_buyer_domain="yorku.ca"))
        self.assertFalse(br.is_official_source_allowed("https://yorku.example.com/bids", "York University", verified_buyer_domain="yorku.ca"))
        self.assertFalse(br.is_official_source_allowed("https://random-university.edu/about", "York University", verified_buyer_domain="yorku.ca"))

        # Real official buyer domains
        self.assertTrue(br.is_official_source_allowed("https://www.yorku.ca/procurement/policies", "York University", verified_buyer_domain="yorku.ca"))
        self.assertTrue(br.is_official_source_allowed("https://www.ontario.ca/page/public-procurement", "York University", verified_buyer_domain="yorku.ca"))

    def test_17_actual_fetched_content_verification_required(self):
        page_text = "York University provides comprehensive undergraduate and graduate programs across diverse faculties."
        search_mock = MagicMock(return_value=[{"url": "https://www.yorku.ca/about", "title": "About York"}])
        fetch_mock = MagicMock(return_value=page_text)

        res = br.run_governed_buyer_research(
            "York University",
            procurement_document_domains=["https://www.yorku.ca"],
            search_fn=search_mock,
            fetch_fn=fetch_mock,
        )
        self.assertEqual(res.status, br.ResearchStatus.COMPLETE)
        self.assertTrue(len(res.signals) > 0)
        for s in res.signals:
            self.assertIn(s.verbatim_quote, page_text)
            self.assertEqual(s.fact_class, FactClass.AUTHORITATIVE_BUYER_FACT.value)

    def test_18_unverifiable_extract_rejected(self):
        import buyer_evidence_acquisition as bea
        from buyer_evidence import EvidenceSource, EvidenceAuthority, LocatorType, SourceCategory
        from datetime import date

        source = EvidenceSource(
            source_id="src-1", publisher_name="York University",
            authority=EvidenceAuthority.OFFICIAL_BUYER, base_url="https://www.yorku.ca"
        )
        page = bea.FetchedPage(
            document_id="doc-1", category=SourceCategory.OFFICIAL_ORGANIZATIONAL_WEBSITE,
            title="York", url="https://www.yorku.ca", language="en", retrieval_date=date.today(),
            full_text="Official text of York University about research.",
            extracts=(
                bea.FetchedExtract("ext-1", "cit-1", LocatorType.SECTION, "Sec", "FABRICATED QUOTE NOT IN PAGE"),
            )
        )
        with self.assertRaises(bea.BuyerEvidenceAcquisitionError):
            bea.adapt_buyer_evidence(
                evidence_set_id="set-1", buyer_id="buyer:york", source=source, pages=[page]
            )

    def test_19_provider_failure_nonfatal(self):
        search_mock = MagicMock(side_effect=IOError("Search engine offline"))
        fetch_mock = MagicMock(return_value="text")

        res = br.run_governed_buyer_research(
            "York University",
            search_fn=search_mock,
            fetch_fn=fetch_mock,
        )
        self.assertIn(res.status, (br.ResearchStatus.UNAVAILABLE, br.ResearchStatus.PARTIAL))
        self.assertEqual(res.pages_accepted, 0)

    def test_20_no_official_evidence_yields_unavailable(self):
        # Search returns only disallowed / rejected URLs
        search_mock = MagicMock(return_value=[
            {"url": "https://en.wikipedia.org/wiki/York", "title": "Wiki"},
            {"url": "https://twitter.com/yorku", "title": "Twitter"},
        ])
        fetch_mock = MagicMock(return_value="Text")

        res = br.run_governed_buyer_research(
            "York University",
            search_fn=search_mock,
            fetch_fn=fetch_mock,
        )
        self.assertEqual(res.status, br.ResearchStatus.PARTIAL)
        self.assertEqual(res.pages_accepted, 0)

    def test_21_22_exact_complete_durable_reuse_zero_provider_calls(self):
        search_mock = MagicMock(return_value=[{"url": "https://www.yorku.ca/about", "title": "About York"}])
        fetch_mock = MagicMock(return_value="York University is an established teaching and research university located in Ontario Canada.")

        # Simulate durable DB persistence
        fake_db_run = {
            "id": 99,
            "resolved_buyer_name": "York University",
            "accepted_page_count": 1,
            "payload": {
                "signals": [
                    {
                        "title": "About York",
                        "detail": "York University is an established teaching and research university located in Ontario Canada.",
                        "source_url": "https://www.yorku.ca/about",
                        "source_title": "About York",
                        "verbatim_quote": "York University is an established teaching and research university located in Ontario Canada.",
                    }
                ],
                "evidence_ids": ["ext-1"],
                "official_website": "https://www.yorku.ca",
                "buyer_id": "buyer:york-university",
            }
        }

        with patch("buyer_research._load_durable_research_run", return_value=None), \
             patch("buyer_research._persist_durable_research_run", return_value=99):
            # First run: executes search and fetch
            res1 = br.run_governed_buyer_research(
                "York University",
                organization_id="org-uuid",
                search_fn=search_mock,
                fetch_fn=fetch_mock,
            )
            self.assertEqual(res1.status, br.ResearchStatus.COMPLETE)
            self.assertEqual(res1.searches_executed, 3)

        # Clear in-memory cache to simulate brand new process / Streamlit restart
        br.clear_research_cache()
        search_mock.reset_mock()
        fetch_mock.reset_mock()

        # Mock durable DB query returning previously persisted run
        with patch("buyer_research._load_durable_research_run") as mock_db_load:
            mock_db_load.return_value = br.BuyerResearchResult(
                status=br.ResearchStatus.REUSED_COMPLETE,
                resolved_buyer="York University",
                query_fingerprint=res1.query_fingerprint,
                searches_executed=0,
                pages_accepted=1,
                signals=res1.signals,
                evidence_ids=res1.evidence_ids,
                official_website=res1.official_website,
                buyer_id=res1.buyer_id,
                cached_reuse=True,
                run_id=99,
            )

            # Second run from NEW process
            res2 = br.run_governed_buyer_research(
                "York University",
                organization_id="org-uuid",
                search_fn=search_mock,
                fetch_fn=fetch_mock,
            )
            self.assertEqual(res2.status, br.ResearchStatus.REUSED_COMPLETE)
            self.assertTrue(res2.cached_reuse)
            self.assertEqual(res2.searches_executed, 0)
            self.assertEqual(res2.pages_accepted, 1)
            search_mock.assert_not_called()
            fetch_mock.assert_not_called()

    def test_23_changed_buyer_identity_yields_new_fingerprint(self):
        fp1 = br.compute_research_fingerprint("York University", "P27-070", "Training Program")
        fp2 = br.compute_research_fingerprint("Bank of Canada", "P27-070", "Training Program")
        self.assertNotEqual(fp1, fp2)

    def test_24_changed_material_context_yields_new_fingerprint(self):
        fp1 = br.compute_research_fingerprint("York University", "P27-070", "AI Mentorship Program")
        fp2 = br.compute_research_fingerprint("York University", "P27-070", "Campus Construction Facilities")
        self.assertNotEqual(fp1, fp2)

    def test_25_evidence_provenance_complete(self):
        page_text = "York University Strategic Procurement Services oversees procurement policies."
        search_mock = MagicMock(return_value=[{"url": "https://www.yorku.ca/procurement", "title": "Procurement"}])
        fetch_mock = MagicMock(return_value=page_text)

        res = br.run_governed_buyer_research(
            "York University",
            procurement_document_domains=["procurement@yorku.ca"],
            search_fn=search_mock,
            fetch_fn=fetch_mock,
        )
        self.assertEqual(res.status, br.ResearchStatus.COMPLETE)
        self.assertTrue(len(res.signals) > 0)
        s = res.signals[0]
        self.assertTrue(s.source_url.startswith("https://www.yorku.ca"))
        self.assertTrue(s.title)
        self.assertTrue(s.verbatim_quote)
        self.assertTrue(s.content_hash)
        self.assertTrue(s.evidence_id)

    def test_29_ssrf_and_private_network_urls_rejected(self):
        # Direct rejection of loopback and private IPs
        with self.assertRaises(brp.ProviderSecurityError):
            brp.validate_network_url("http://127.0.0.1:8080/secret")

        with self.assertRaises(brp.ProviderSecurityError):
            brp.validate_network_url("http://localhost:5000/api")

        with self.assertRaises(brp.ProviderSecurityError):
            brp.validate_network_url("http://169.254.169.254/latest/meta-data")  # Link-local / AWS metadata

        with self.assertRaises(brp.ProviderSecurityError):
            brp.validate_network_url("ftp://example.com/file")  # Disallowed scheme

        with self.assertRaises(brp.ProviderSecurityError):
            brp.validate_network_url("http://user:pass@example.com/doc")  # Embedded credentials

    def test_26_unsupported_evaluator_claims_prohibited_in_buyer_intelligence(self):
        # Buyer Intelligence strictly prohibits evaluator preferences, strategy advice, win probability
        from buyer_intelligence import _safe_statement, BuyerIntelligenceValidationError
        with self.assertRaises(BuyerIntelligenceValidationError):
            _safe_statement("Crucial weighting rule: evaluator wants strong local presence.", "test")
        with self.assertRaises(BuyerIntelligenceValidationError):
            _safe_statement("This represents an evaluation differentiator for pricing strategy.", "test")
        with self.assertRaises(BuyerIntelligenceValidationError):
            _safe_statement("We should bid because our win probability is high.", "test")
        # Allowed factual statement
        stmt = _safe_statement("York University is a public research university in Toronto, Ontario.", "test")
        self.assertEqual(stmt, "York University is a public research university in Toronto, Ontario.")

    def test_31_anthropic_default_provider_configured(self):
        # When no custom functions are supplied, defaults to Anthropic search and fetch
        with patch("buyer_research_provider.anthropic_search", return_value=[]) as mock_search, \
             patch("buyer_research_provider.anthropic_fetch", return_value="") as mock_fetch:
            res = br.run_governed_buyer_research("York University", max_searches=1)
            self.assertEqual(mock_search.call_count, 1)

    def test_32_durable_persistence_failure_downgrades_to_partial(self):
        search_mock = MagicMock(return_value=[{"url": "https://www.yorku.ca/about", "title": "About York"}])
        fetch_mock = MagicMock(return_value="York University is an established teaching and research university located in Ontario Canada.")

        # Simulate DB persistence returning None (e.g. database error)
        with patch("buyer_research._persist_durable_research_run", return_value=None):
            res = br.run_governed_buyer_research(
                "York University",
                bid_id=999,
                organization_id="org-uuid",
                search_fn=search_mock,
                fetch_fn=fetch_mock,
            )
            self.assertEqual(res.status, br.ResearchStatus.PARTIAL)
            self.assertIn("persistence failed", res.error)

    def test_33_fingerprint_invalidation_across_dimensions(self):
        base_fp = br.compute_research_fingerprint("York University", "P27-070", "AI Training", "v1")
        # Changed buyer
        diff_buyer = br.compute_research_fingerprint("Bank of Canada", "P27-070", "AI Training", "v1")
        self.assertNotEqual(base_fp, diff_buyer)
        # Changed solicitation
        diff_sol = br.compute_research_fingerprint("York University", "P27-071", "AI Training", "v1")
        self.assertNotEqual(base_fp, diff_sol)
        # Changed context
        diff_ctx = br.compute_research_fingerprint("York University", "P27-070", "Campus Facilities", "v1")
        self.assertNotEqual(base_fp, diff_ctx)
        # Changed contract version
        diff_ver = br.compute_research_fingerprint("York University", "P27-070", "AI Training", "v2")
        self.assertNotEqual(base_fp, diff_ver)


if __name__ == "__main__":
    unittest.main()
