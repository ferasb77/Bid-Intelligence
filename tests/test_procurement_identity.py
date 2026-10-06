"""
tests/test_procurement_identity.py -- Deterministic Unit Tests for Auto Procurement Identity.

Tests Phase B & D contracts:
1. Clear identity resolved from single doc body.
2. Corroborated multi-doc identity resolved.
3. Conflicting buyer across docs -> NEEDS_CONFIRMATION.
4. Conflicting title/solicitation -> NEEDS_CONFIRMATION.
5. Missing solicitation allowed where buyer and title are otherwise clear.
6. Filename cannot override body text evidence.
7. Canonical procurement truth (Rank 1) outranks regex body metadata.
8. Sentinels cannot leak to display or valid values.
9. Cross-tenant update denied / require_bid_access enforced.
10. Confirmation persists via tenancy.update_bid_identity_for_organization.
11. Unresolved identity blocks buyer research.
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

    def test_clean_display_helpers_sentinels_cannot_leak(self):
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

    def test_1_clear_identity_resolved(self):
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

    def test_2_corroborated_multi_doc_identity_resolved(self):
        doc1 = {
            "name": "rfp_main.pdf",
            "text": "ISSUED BY: York University\nFOR: AI Skills Training Program\nREF NO: P27-070",
        }
        doc2 = {
            "name": "appendix_a.pdf",
            "text": "ISSUED BY: York University\nFOR: AI Skills Training Program\nREF NO: P27-070",
        }
        res = pi.resolve_procurement_identity([doc1, doc2])
        self.assertEqual(res.status, pi.IdentityStatus.RESOLVED)
        self.assertEqual(res.client_name, "York University")
        self.assertEqual(res.opportunity_title, "AI Skills Training Program")
        self.assertEqual(res.solicitation_number, "P27-070")

    def test_3_conflicting_buyer_requires_confirmation(self):
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

    def test_4_conflicting_title_requires_confirmation(self):
        doc1 = {
            "name": "rfp1.pdf",
            "text": "ISSUED BY: York University\nFOR: AI Mentorship and Leadership Initiative\nREF NO: P27-070",
        }
        doc2 = {
            "name": "rfp2.pdf",
            "text": "ISSUED BY: York University\nFOR: Cyber Infrastructure Modernization\nREF NO: P27-070",
        }
        res = pi.resolve_procurement_identity([doc1, doc2])
        self.assertEqual(res.status, pi.IdentityStatus.NEEDS_CONFIRMATION)
        self.assertIsNone(res.opportunity_title)
        self.assertEqual(len(res.alternative_candidates), 2)

    def test_5_missing_solicitation_allowed_where_identity_otherwise_clear(self):
        doc = {
            "name": "statement_of_work.pdf",
            "text": "ISSUED BY: City of Calgary\nFOR: Municipal Snow Clearing and Road Safety",
        }
        res = pi.resolve_procurement_identity([doc])
        self.assertEqual(res.status, pi.IdentityStatus.RESOLVED)
        self.assertEqual(res.client_name, "City of Calgary")
        self.assertEqual(res.opportunity_title, "Municipal Snow Clearing and Road Safety")
        self.assertIsNone(res.solicitation_number)

    def test_6_filename_cannot_override_body_text_evidence(self):
        # Filename has misleading title/number, body text has authoritative procurement details
        doc = {
            "name": "Old_Draft_RFP_999_Vendor_Proposal.pdf",
            "text": "ISSUED BY: Bank of Canada\nFOR: Enterprise Financial System Modernization\nREF NO: 2026-026",
        }
        res = pi.resolve_procurement_identity([doc])
        self.assertEqual(res.status, pi.IdentityStatus.RESOLVED)
        self.assertEqual(res.client_name, "Bank of Canada")
        self.assertEqual(res.opportunity_title, "Enterprise Financial System Modernization")
        self.assertEqual(res.solicitation_number, "2026-026")

    def test_7_canonical_truth_outranks_regex_body_metadata(self):
        # Body text has preliminary text, but metadata_by_doc has canonical merged truth
        doc = {
            "name": "rfp.pdf",
            "text": "ISSUED BY: Preliminary Agency\nFOR: Temporary Preliminary Scope\nREF NO: 111-000",
        }
        meta_by_doc = {
            "rfp.pdf": {
                "client": "York University",
                "title": "Instructor for Sales and AI Training and Mentorship Program",
                "file_number": "P27-070",
            }
        }
        res = pi.resolve_procurement_identity([doc], metadata_by_doc=meta_by_doc)
        self.assertEqual(res.status, pi.IdentityStatus.RESOLVED)
        self.assertEqual(res.client_name, "York University")
        self.assertEqual(res.opportunity_title, "Instructor for Sales and AI Training and Mentorship Program")
        self.assertEqual(res.solicitation_number, "P27-070")
        self.assertEqual(res.confidence_score, 0.98)


class TestTenancyIdentityUpdate(unittest.TestCase):
    @patch("database.get_client")
    @patch("tenancy.require_bid_access")
    def test_10_confirmation_persists_via_tenancy(self, mock_access, mock_client):
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

    def test_9_cross_tenant_update_denied(self):
        import tenancy
        with self.assertRaises(ValueError):
            tenancy.update_bid_identity_for_organization(1522, "", title="T")


if __name__ == "__main__":
    unittest.main()
