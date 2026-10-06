"""
test_buyer_source_authority.py -- Deterministic Tests for BI-VALUE-2.3 Authority & Disambiguation
"""
import unittest
from unittest.mock import MagicMock

import buyer_source_authority as bsa
import buyer_research as br
from buyer_source_authority import (
    SourceAuthorityClass,
    SourceAuthorityStatus,
    VerifiedOfficialDomain,
)


class TestBuyerSourceAuthority(unittest.TestCase):
    """20 deterministic tests validating domain verification, disambiguation, and rejection."""

    def test_01_yorku_ca_verified_for_canadian_york_university(self):
        text = "York University is located in Toronto, Ontario, Canada. Founded in 1959."
        res = bsa.verify_buyer_domain_content("yorku.ca", "York University", text, jurisdiction_country="CA")
        self.assertEqual(res.status, SourceAuthorityStatus.VERIFIED)
        self.assertEqual(res.authority_class, SourceAuthorityClass.OFFICIAL_BUYER)
        self.assertTrue(res.is_official_buyer)

    def test_02_york_ac_uk_rejected_for_canadian_york_university(self):
        text = "University of York is a collegiate research university in York, England, United Kingdom."
        res = bsa.verify_buyer_domain_content("york.ac.uk", "York University", text, jurisdiction_country="CA")
        self.assertEqual(res.status, SourceAuthorityStatus.REJECTED)
        self.assertEqual(res.authority_class, SourceAuthorityClass.DIFFERENT_ORGANIZATION)
        self.assertFalse(res.is_official_buyer)

    def test_03_york_edu_rejected_for_canadian_york_university(self):
        text = "York University is a private university in York, Nebraska, United States."
        res = bsa.verify_buyer_domain_content("york.edu", "York University", text, jurisdiction_country="CA")
        self.assertEqual(res.status, SourceAuthorityStatus.REJECTED)
        self.assertEqual(res.authority_class, SourceAuthorityClass.DIFFERENT_ORGANIZATION)
        self.assertFalse(res.is_official_buyer)

    def test_04_arbitrary_edu_rejected_without_buyer_name(self):
        text = "Higher Education Portal for North American Universities."
        res = bsa.verify_buyer_domain_content("arbitrary.edu", "York University", text, jurisdiction_country="CA")
        self.assertEqual(res.status, SourceAuthorityStatus.REJECTED)
        self.assertEqual(res.authority_class, SourceAuthorityClass.DIFFERENT_ORGANIZATION)

    def test_05_arbitrary_org_rejected_without_buyer_name(self):
        text = "Organization for academic leadership and university standards."
        res = bsa.verify_buyer_domain_content("arbitrary.org", "York University", text, jurisdiction_country="CA")
        self.assertEqual(res.status, SourceAuthorityStatus.REJECTED)
        self.assertEqual(res.authority_class, SourceAuthorityClass.DIFFERENT_ORGANIZATION)

    def test_06_ontario_ca_classified_as_government_authority_not_buyer(self):
        res = bsa.classify_government_domain("ontario.ca", buyer_jurisdiction="CA")
        self.assertIsNotNone(res)
        self.assertEqual(res.status, SourceAuthorityStatus.VERIFIED)
        self.assertEqual(res.authority_class, SourceAuthorityClass.GOVERNMENT_AUTHORITY)
        self.assertFalse(res.is_official_buyer)
        self.assertTrue(res.is_government_authority)

    def test_07_canada_ca_classified_as_government_authority(self):
        res = bsa.classify_government_domain("canada.ca", buyer_jurisdiction="CA")
        self.assertIsNotNone(res)
        self.assertEqual(res.authority_class, SourceAuthorityClass.GOVERNMENT_AUTHORITY)
        self.assertFalse(res.is_official_buyer)

    def test_08_gc_ca_classified_as_government_authority(self):
        res = bsa.classify_government_domain("tpsgc-pwgsc.gc.ca", buyer_jurisdiction="CA")
        self.assertIsNotNone(res)
        self.assertEqual(res.authority_class, SourceAuthorityClass.GOVERNMENT_AUTHORITY)

    def test_09_gov_on_ca_classified_as_government_authority(self):
        res = bsa.classify_government_domain("mbs.gov.on.ca", buyer_jurisdiction="CA")
        self.assertIsNotNone(res)
        self.assertEqual(res.authority_class, SourceAuthorityClass.GOVERNMENT_AUTHORITY)

    def test_10_adversarial_fake_york_domain_rejected(self):
        res = bsa.verify_buyer_domain_content("fake-yorku.ca", "York University", "York University Toronto")
        self.assertEqual(res.status, SourceAuthorityStatus.REJECTED)

    def test_11_example_com_rejected(self):
        res = bsa.verify_buyer_domain_content("yorku.ca.example.com", "York University", "York University")
        self.assertEqual(res.status, SourceAuthorityStatus.REJECTED)

    def test_12_aggregator_merx_and_biddingo_rejected(self):
        self.assertTrue(bsa.is_adversarial_or_disallowed_domain("merx.com"))
        self.assertTrue(bsa.is_adversarial_or_disallowed_domain("biddingo.com"))
        self.assertTrue(bsa.is_adversarial_or_disallowed_domain("buyandsell.gc.ca"))

    def test_13_social_and_news_domains_rejected(self):
        self.assertTrue(bsa.is_adversarial_or_disallowed_domain("thestar.com"))
        self.assertTrue(bsa.is_adversarial_or_disallowed_domain("linkedin.com"))
        self.assertTrue(bsa.is_adversarial_or_disallowed_domain("wikipedia.org"))

    def test_14_token_only_match_fails_closed(self):
        text = "Visit York region for beautiful parks and local businesses."
        res = bsa.verify_buyer_domain_content("yorkregion.com", "York University", text, jurisdiction_country="CA")
        self.assertEqual(res.status, SourceAuthorityStatus.UNVERIFIED)

    def test_15_empty_page_content_fails_closed(self):
        res = bsa.verify_buyer_domain_content("yorku.ca", "York University", "", jurisdiction_country="CA")
        self.assertEqual(res.status, SourceAuthorityStatus.UNVERIFIED)
        self.assertEqual(res.authority_class, SourceAuthorityClass.UNVERIFIED)

    def test_16_is_official_source_allowed_rejects_unverified_domain(self):
        # Without verified_buyer_domain set, candidate URL is rejected
        allowed = br.is_official_source_allowed("https://york.ac.uk/about", "York University", verified_buyer_domain=None)
        self.assertFalse(allowed)

    def test_17_is_official_source_allowed_rejects_wrong_domain_even_with_verified_buyer(self):
        allowed = br.is_official_source_allowed("https://york.ac.uk/about", "York University", verified_buyer_domain="yorku.ca")
        self.assertFalse(allowed)

    def test_18_is_official_source_allowed_accepts_verified_buyer_subdomain(self):
        allowed = br.is_official_source_allowed("https://sfs.yorku.ca/procurement", "York University", verified_buyer_domain="yorku.ca")
        self.assertTrue(allowed)

    def test_19_is_official_source_allowed_accepts_government_authority(self):
        allowed = br.is_official_source_allowed("https://www.ontario.ca/page/procurement-directive", "York University", verified_buyer_domain="yorku.ca")
        self.assertTrue(allowed)

    def test_20_fingerprint_incorporates_authority_policy_version(self):
        fp1 = br.compute_research_fingerprint("York University", "P27-070", "AI", "v1")
        # In br.compute_research_fingerprint, SOURCE_AUTHORITY_POLICY_VERSION is part of the raw key
        self.assertIn("source-authority-policy/2", br.SOURCE_AUTHORITY_POLICY_VERSION)
        self.assertEqual(len(fp1), 64)


if __name__ == "__main__":
    unittest.main()
