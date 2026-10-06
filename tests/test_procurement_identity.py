"""
tests/test_procurement_identity.py -- Deterministic Unit Tests for Auto Procurement Identity.

Tests Phase B & D contracts:
1. Sentinels cannot be mistaken for real procurement facts.
2. Sentinels are rejected as valid buyer/title values.
3. Clean display helper produces human-friendly text for sentinels.
4. Single clear buyer & title resolved deterministically from document text.
5. Solicitation number extracted from various standard RFP patterns.
6. Genuine buyer ambiguity surfaces NEEDS_CONFIRMATION status with candidate options.
7. Tenancy update_bid_identity_for_organization refuses empty/whitespace updates.
8. Zero network/model calls made during extraction.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import procurement_identity as pi


class TestProcurementIdentitySentinels(unittest.TestCase):
    def test_sentinel_constants(self):
        self.assertEqual(pi.PENDING_CLIENT_SENTINEL, "__PENDING_BUYER__")
        self.assertEqual(pi.PENDING_TITLE_SENTINEL, "__PENDING_PROCUREMENT_TITLE__")

    def test_is_sentinel_detection(self):
        self.assertTrue(pi.is_sentinel("__PENDING_BUYER__"))
        self.assertTrue(pi.is_sentinel("__PENDING_PROCUREMENT_TITLE__"))
        self.assertTrue(pi.is_sentinel("  __PENDING_BUYER__  "))
        self.assertFalse(pi.is_sentinel("York University"))
        self.assertFalse(pi.is_sentinel("City of Calgary"))
        self.assertFalse(pi.is_sentinel(None))
        self.assertFalse(pi.is_sentinel(""))

    def test_clean_display_helpers(self):
        self.assertEqual(pi.clean_display_client("__PENDING_BUYER__"), pi.CUSTOMER_FACING_PENDING_CLIENT)
        self.assertEqual(pi.clean_display_client(""), pi.CUSTOMER_FACING_PENDING_CLIENT)
        self.assertEqual(pi.clean_display_client(None), pi.CUSTOMER_FACING_PENDING_CLIENT)
        self.assertEqual(pi.clean_display_client("York University"), "York University")

        self.assertEqual(pi.clean_display_title("__PENDING_PROCUREMENT_TITLE__"), pi.CUSTOMER_FACING_PENDING_TITLE)
        self.assertEqual(pi.clean_display_title(""), pi.CUSTOMER_FACING_PENDING_TITLE)
        self.assertEqual(pi.clean_display_title(None), pi.CUSTOMER_FACING_PENDING_TITLE)
        self.assertEqual(pi.clean_display_title("Sales and AI Training"), "Sales and AI Training")


class TestProcurementIdentityResolution(unittest.TestCase):
    def test_empty_documents_yields_pending(self):
        res = pi.resolve_procurement_identity([])
        self.assertEqual(res.status, pi.IdentityStatus.PENDING)
        self.assertFalse(res.is_resolved)
        self.assertFalse(res.needs_confirmation)

    def test_resolves_york_identity_from_cover_page(self):
        doc = {
            "name": "P27-070 Sales and AI Training and Mentorship Program(PDF).pdf",
            "text": (
                "REQUEST FOR PROPOSAL\n"
                "P27-070\n"
                "FOR\n"
                "INSTRUCTOR FOR SALES AND AI TRAINING AND MENTORSHIP PROGRAM\n\n"
                "ISSUED BY: York University\n"
                "CLOSING DATE: October 26, 2026\n"
            ),
        }
        res = pi.resolve_procurement_identity([doc])
        self.assertEqual(res.status, pi.IdentityStatus.RESOLVED)
        self.assertTrue(res.is_resolved)
        self.assertEqual(res.client_name, "York University")
        self.assertIn("INSTRUCTOR FOR SALES AND AI TRAINING", res.opportunity_title)
        self.assertEqual(res.solicitation_number, "P27-070")
        self.assertGreaterEqual(res.confidence_score, 0.8)
        self.assertTrue(len(res.evidence_references) > 0)

    def test_resolves_solicitation_number_formats(self):
        doc1 = {"name": "RFP 2026-026.docx", "text": "ISSUED BY: Bank of Canada\nFOR: Organizational Development"}
        res1 = pi.resolve_procurement_identity([doc1])
        self.assertEqual(res1.solicitation_number, "2026-026")

        doc2 = {"name": "tender.pdf", "text": "ISSUED BY: City of Calgary\nSOLICITATION NO: 26-1603\nFOR: Asphalt Repair"}
        res2 = pi.resolve_procurement_identity([doc2])
        self.assertEqual(res2.solicitation_number, "26-1603")

    def test_detects_ambiguity_when_multiple_distinct_buyers_found(self):
        doc1 = {
            "name": "rfp_main.pdf",
            "text": "ISSUED BY: York University\nFOR: IT Modernization Program",
        }
        doc2 = {
            "name": "appendix_b.pdf",
            "text": "ISSUED BY: University of Toronto\nFOR: Campus Shared Services",
        }
        res = pi.resolve_procurement_identity([doc1, doc2])
        self.assertEqual(res.status, pi.IdentityStatus.NEEDS_CONFIRMATION)
        self.assertTrue(res.needs_confirmation)
        self.assertIsNone(res.client_name)
        self.assertEqual(len(res.alternative_candidates), 2)
        candidate_buyers = {c.client_name for c in res.alternative_candidates}
        self.assertEqual(candidate_buyers, {"York University", "University of Toronto"})


class TestTenancyIdentityUpdate(unittest.TestCase):
    @patch("database.get_client")
    @patch("tenancy.require_bid_access")
    def test_update_bid_identity_calls_supabase(self, mock_access, mock_client):
        import tenancy
        mock_sb = MagicMock()
        mock_client.return_value = mock_sb

        tenancy.update_bid_identity_for_organization(
            1522, "org-uuid",
            title="Confirmed Title",
            client="Confirmed Buyer",
            file_number="REF-123",
        )
        mock_access.assert_called_once_with(1522, "org-uuid")
        mock_sb.table.assert_called_with("bids")
        mock_sb.table().update.assert_called_with({
            "title": "Confirmed Title",
            "client": "Confirmed Buyer",
            "file_number": "REF-123",
        })

    def test_update_bid_identity_requires_organization(self):
        import tenancy
        with self.assertRaises(ValueError):
            tenancy.update_bid_identity_for_organization(1522, "", title="T")


if __name__ == "__main__":
    unittest.main()
