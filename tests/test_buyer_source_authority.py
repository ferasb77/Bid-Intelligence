"""
test_buyer_source_authority.py -- Deterministic Tests for BI-VALUE-2.4 Authority & Disambiguation
"""
import unittest
from unittest.mock import MagicMock

import buyer_source_authority as bsa
import buyer_research as br
import procurement_identity as pi
from buyer_source_authority import (
    DomainVerificationMethod,
    SourceAuthorityClass,
    SourceAuthorityStatus,
    VerifiedOfficialDomain,
)


class TestBuyerSourceAuthority(unittest.TestCase):
    """20 deterministic tests validating domain verification, disambiguation, ownership proof, and canonical root."""

    def test_01_positive_root_self_identity_verified_for_yorku_ca(self):
        root_text = "Welcome to York University in Toronto, Ontario, Canada. York University acknowledges its presence on traditional territory."
        fetch_root = MagicMock(return_value=root_text)
        res = bsa.verify_buyer_domain_content(
            "yorku.ca", "York University", root_text, jurisdiction_country="CA", fetch_root_fn=fetch_root,
        )
        self.assertEqual(res.status, SourceAuthorityStatus.VERIFIED)
        self.assertEqual(res.authority_class, SourceAuthorityClass.OFFICIAL_BUYER)
        self.assertEqual(res.verification_method, DomainVerificationMethod.OFFICIAL_ROOT_PAGE_IDENTITY.value)
        self.assertTrue(res.is_official_buyer)
        self.assertEqual(res.canonical_buyer_domain, "yorku.ca")
        fetch_root.assert_called_once_with("https://yorku.ca")

    def test_02_weak_signals_alone_rejected_without_positive_ownership(self):
        # Token in hostname + full buyer name + Canadian cues, but no ownership proof
        text = "York Region News: In an article announced today, York University in Toronto, Ontario received a provincial grant."
        res = bsa.verify_buyer_domain_content("yorkregion.com", "York University", text, jurisdiction_country="CA")
        self.assertEqual(res.status, SourceAuthorityStatus.UNVERIFIED)
        self.assertFalse(res.is_official_buyer)
        # Self-identity phrasing on a NON-root page is only a mention, never ownership proof
        mention = "York University is a public research university in Toronto, Ontario, Canada with many campuses."
        res2 = bsa.verify_buyer_domain_content("yorkregion.com", "York University", mention, jurisdiction_country="CA")
        self.assertFalse(res2.is_official_buyer)
        # Root page of the third-party site does not self-identify as the buyer
        root = MagicMock(return_value="YorkRegion.com - local news for Newmarket, Markham and Vaughan, Ontario. Weather, sports and events.")
        res3 = bsa.verify_buyer_domain_content(
            "yorkregion.com", "York University", mention, jurisdiction_country="CA", fetch_root_fn=root,
        )
        self.assertFalse(res3.is_official_buyer)

    def test_03_third_party_news_mention_calgaryherald_rejected(self):
        text = "According to a staff reporter, City of Calgary in Alberta announced a municipal budget update yesterday."
        res = bsa.verify_buyer_domain_content("calgaryherald.com", "City of Calgary", text, jurisdiction_country="CA")
        self.assertEqual(res.status, SourceAuthorityStatus.UNVERIFIED)
        self.assertFalse(res.is_official_buyer)

    def test_04_procurement_document_url_provides_positive_proof(self):
        res = bsa.verify_buyer_domain_content(
            "yorku.ca",
            "York University",
            "Minimal text",
            jurisdiction_country="CA",
            procurement_document_domains=["www.yorku.ca/procurement"],
        )
        self.assertEqual(res.status, SourceAuthorityStatus.VERIFIED)
        self.assertEqual(res.authority_class, SourceAuthorityClass.OFFICIAL_BUYER)
        self.assertEqual(res.verification_method, DomainVerificationMethod.PROCUREMENT_DOCUMENT_URL.value)
        # A vendor/software URL cited in the RFP is NOT buyer ownership proof
        vendor = bsa.verify_buyer_domain_content(
            "zoom.us", "York University", "Minimal text", jurisdiction_country="CA",
            procurement_document_domains=["https://zoom.us/j/123"],
        )
        self.assertFalse(vendor.is_official_buyer)

    def test_05_procurement_contact_email_domain_provides_positive_proof(self):
        res = bsa.verify_buyer_domain_content(
            "yorku.ca",
            "York University",
            "Minimal text",
            jurisdiction_country="CA",
            procurement_document_domains=["procurement@yorku.ca"],
        )
        self.assertEqual(res.status, SourceAuthorityStatus.VERIFIED)
        self.assertEqual(res.authority_class, SourceAuthorityClass.OFFICIAL_BUYER)

    def test_06_subdomain_canonicalized_to_registrable_root_domain(self):
        leaf_text = "York University Schulich Executive Education Centre provides professional development programs."
        root_text = "York University is a top research university in Toronto, Ontario, Canada."
        fetch_root = MagicMock(return_value=root_text)
        res = bsa.verify_buyer_domain_content(
            "execed.schulich.yorku.ca", "York University", leaf_text, jurisdiction_country="CA", fetch_root_fn=fetch_root,
        )
        fetch_root.assert_called_once_with("https://yorku.ca")
        self.assertEqual(res.observed_domain, "execed.schulich.yorku.ca")
        self.assertEqual(res.registrable_domain, "yorku.ca")
        self.assertEqual(res.canonical_buyer_domain, "yorku.ca")
        self.assertEqual(res.status, SourceAuthorityStatus.VERIFIED)

    def test_07_canadian_provincial_sld_canonicalization(self):
        self.assertEqual(bsa.get_registrable_domain("edmonton.ab.ca"), "edmonton.ab.ca")
        self.assertEqual(bsa.get_registrable_domain("services.edmonton.ab.ca"), "edmonton.ab.ca")
        self.assertEqual(bsa.get_registrable_domain("sub.domain.toronto.on.ca"), "toronto.on.ca")

    def test_08_york_ac_uk_rejected_for_canadian_york_university(self):
        text = "University of York is a collegiate research university in York, England, United Kingdom."
        res = bsa.verify_buyer_domain_content("york.ac.uk", "York University", text, jurisdiction_country="CA")
        self.assertEqual(res.status, SourceAuthorityStatus.REJECTED)
        self.assertEqual(res.authority_class, SourceAuthorityClass.DIFFERENT_ORGANIZATION)
        self.assertFalse(res.is_official_buyer)

    def test_09_york_edu_rejected_for_canadian_york_university(self):
        text = "York University is a private university in York, Nebraska, United States."
        res = bsa.verify_buyer_domain_content("york.edu", "York University", text, jurisdiction_country="CA")
        self.assertEqual(res.status, SourceAuthorityStatus.REJECTED)
        self.assertEqual(res.authority_class, SourceAuthorityClass.DIFFERENT_ORGANIZATION)
        self.assertFalse(res.is_official_buyer)

    def test_10_foreign_gov_domain_rejected_for_canadian_buyer(self):
        # US state gov domain rejected as authority for Canadian buyer
        res = bsa.classify_government_domain("texas.gov", buyer_jurisdiction="CA")
        self.assertIsNone(res)
        # But accepted if buyer jurisdiction is US
        res_us = bsa.classify_government_domain("texas.gov", buyer_jurisdiction="US")
        self.assertIsNotNone(res_us)
        self.assertEqual(res_us.authority_class, SourceAuthorityClass.GOVERNMENT_AUTHORITY)

    def test_11_ontario_ca_classified_as_government_authority_not_buyer(self):
        res = bsa.classify_government_domain("ontario.ca", buyer_jurisdiction="CA")
        self.assertIsNotNone(res)
        self.assertEqual(res.status, SourceAuthorityStatus.VERIFIED)
        self.assertEqual(res.authority_class, SourceAuthorityClass.GOVERNMENT_AUTHORITY)
        self.assertFalse(res.is_official_buyer)
        self.assertTrue(res.is_government_authority)

    def test_12_gc_ca_and_canada_ca_classified_as_government_authority(self):
        res1 = bsa.classify_government_domain("canada.ca", buyer_jurisdiction="CA")
        self.assertEqual(res1.authority_class, SourceAuthorityClass.GOVERNMENT_AUTHORITY)
        res2 = bsa.classify_government_domain("tpsgc-pwgsc.gc.ca", buyer_jurisdiction="CA")
        self.assertEqual(res2.authority_class, SourceAuthorityClass.GOVERNMENT_AUTHORITY)

    def test_13_adversarial_fake_york_domain_rejected(self):
        res = bsa.verify_buyer_domain_content("fake-yorku.ca", "York University", "York University Toronto")
        self.assertEqual(res.status, SourceAuthorityStatus.REJECTED)

    def test_14_example_com_rejected(self):
        res = bsa.verify_buyer_domain_content("yorku.ca.example.com", "York University", "York University")
        self.assertEqual(res.status, SourceAuthorityStatus.REJECTED)

    def test_15_aggregator_and_third_party_portals_rejected(self):
        self.assertTrue(bsa.is_adversarial_or_disallowed_domain("merx.com"))
        self.assertTrue(bsa.is_adversarial_or_disallowed_domain("biddingo.com"))
        self.assertTrue(bsa.is_adversarial_or_disallowed_domain("bonfirehub.com"))
        self.assertTrue(bsa.is_adversarial_or_disallowed_domain("canadabuys.canada.ca"))

    def test_16_empty_page_content_fails_closed(self):
        res = bsa.verify_buyer_domain_content("yorku.ca", "York University", "", jurisdiction_country="CA")
        self.assertEqual(res.status, SourceAuthorityStatus.UNVERIFIED)
        self.assertEqual(res.authority_class, SourceAuthorityClass.UNVERIFIED)

    def test_17_is_official_source_allowed_accepts_verified_canonical_and_subdomains(self):
        # Canonical root domain
        self.assertTrue(br.is_official_source_allowed("https://yorku.ca", "York University", verified_buyer_domain="yorku.ca"))
        # Subdomain
        self.assertTrue(br.is_official_source_allowed("https://sfs.yorku.ca/services", "York University", verified_buyer_domain="yorku.ca"))
        # Unrelated domain rejected
        self.assertFalse(br.is_official_source_allowed("https://york.ac.uk/about", "York University", verified_buyer_domain="yorku.ca"))

    def test_18_is_official_source_allowed_accepts_government_authority_with_jurisdiction(self):
        self.assertTrue(br.is_official_source_allowed("https://www.ontario.ca/procurement", "York University", verified_buyer_domain="yorku.ca", jurisdiction_country="CA"))
        # US gov domain rejected for Canadian buyer
        self.assertFalse(br.is_official_source_allowed("https://www.texas.gov/rules", "York University", verified_buyer_domain="yorku.ca", jurisdiction_country="CA"))

    def test_19_procurement_identity_extracts_package_candidate_domains(self):
        docs = [
            {
                "name": "RFP_Document.pdf",
                "text": "York University is issuing RFP P27-070 in Toronto, Ontario. For inquiries visit https://www.yorku.ca or email procurement@yorku.ca. Tenders posted on https://bonfirehub.com."
            }
        ]
        ident = pi.resolve_procurement_identity(docs)
        self.assertEqual(ident.client_name, "York University")
        self.assertIn("www.yorku.ca", ident.candidate_domains)
        self.assertIn("yorku.ca", ident.candidate_domains)
        self.assertNotIn("bonfirehub.com", ident.candidate_domains)

    def test_20_fingerprint_incorporates_authority_policy_v3(self):
        fp = br.compute_research_fingerprint("York University", "P27-070", "context", "buyer-research/2")
        self.assertEqual(bsa.SOURCE_AUTHORITY_POLICY_VERSION, "source-authority-policy/3")
        self.assertIn("source-authority-policy/3", br.SOURCE_AUTHORITY_POLICY_VERSION)
        self.assertEqual(len(fp), 64)


if __name__ == "__main__":
    unittest.main()
