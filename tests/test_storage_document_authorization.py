"""
tests/test_storage_document_authorization.py

Comprehensive security regression tests for Package R2A.2:
Phoenix Beta Application Authorization.

Validates that all Document and Storage access paths enforce:
  1. Authentication and organization tenancy verification.
  2. Strict bid-ownership validation.
  3. Document-to-bid foreign key integrity (preventing cross-bid tampering).
  4. Fail-closed behavior on missing or unverified caller context.
  5. Storage-path traversal and manipulation defenses.
  6. Positive controls for legitimate authorized tenant operations.
"""
import unittest
from unittest.mock import MagicMock, patch

import database as db
import tenancy
from tenancy import AccessDeniedError


class TestStorageDocumentAuthorization(unittest.TestCase):
    def setUp(self):
        self.org_a = "org-alpha-1111"
        self.org_b = "org-beta-2222"
        self.bid_a = 101
        self.bid_b = 202
        self.doc_a = 1001
        self.doc_b = 2002
        self.run_a = 5001
        self.run_b = 6002

        self.mock_bid_a = {"id": self.bid_a, "organization_id": self.org_a, "title": "Alpha RFP"}
        self.mock_bid_b = {"id": self.bid_b, "organization_id": self.org_b, "title": "Beta RFP"}

        self.mock_doc_a = {
            "id": self.doc_a,
            "bid_id": self.bid_a,
            "name": "Alpha_Proposal.pdf",
            "storage_path": f"{self.bid_a}/alpha_uuid.pdf",
            "file_path": f"supabase://bid-documents/{self.bid_a}/alpha_uuid.pdf",
            "version": 1,
        }
        self.mock_doc_b = {
            "id": self.doc_b,
            "bid_id": self.bid_b,
            "name": "Beta_Proposal.pdf",
            "storage_path": f"{self.bid_b}/beta_uuid.pdf",
            "file_path": f"supabase://bid-documents/{self.bid_b}/beta_uuid.pdf",
            "version": 1,
        }

        self.mock_run_a = {
            "id": self.run_a,
            "bid_id": self.bid_a,
            "report_storage_path": f"{self.bid_a}/analysis_reports/{self.run_a}.pdf",
            "status": "COMPLETE",
        }
        self.mock_run_b = {
            "id": self.run_b,
            "bid_id": self.bid_b,
            "report_storage_path": f"{self.bid_b}/analysis_reports/{self.run_b}.pdf",
            "status": "COMPLETE",
        }

    # ── Negative Control 1: Cross-Tenant Document Download ───────────────────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.download_file")
    def test_cross_tenant_document_download_denied(self, mock_download, mock_get_bid):
        # Org A attempts to download Org B's bid document
        mock_get_bid.return_value = None  # Org A does not own Bid B
        with self.assertRaises(AccessDeniedError):
            tenancy.download_document_for_organization(self.bid_b, self.doc_b, self.org_a)
        mock_download.assert_not_called()

    # ── Negative Control 2: Foreign Document ID (Cross-Bid Tampering) ────────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.get_document")
    @patch("tenancy.db.download_file")
    def test_foreign_document_id_download_denied(self, mock_download, mock_get_doc, mock_get_bid):
        # Caller owns Bid A, but doc_b belongs to Bid B
        mock_get_bid.return_value = self.mock_bid_a
        mock_get_doc.return_value = self.mock_doc_b  # mismatched bid_id
        with self.assertRaises(AccessDeniedError):
            tenancy.download_document_for_organization(self.bid_a, self.doc_b, self.org_a)
        mock_download.assert_not_called()

    # ── Positive Control 1: Legitimate Document Download ─────────────────────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.get_document")
    @patch("tenancy.db.download_file")
    def test_authorized_document_download_success(self, mock_download, mock_get_doc, mock_get_bid):
        mock_get_bid.return_value = self.mock_bid_a
        mock_get_doc.return_value = self.mock_doc_a
        mock_download.return_value = b"%PDF-1.4 authorized alpha document bytes"

        result = tenancy.download_document_for_organization(self.bid_a, self.doc_a, self.org_a)
        self.assertEqual(result, b"%PDF-1.4 authorized alpha document bytes")
        mock_download.assert_called_once_with(self.mock_doc_a["storage_path"])

    # ── Negative Control 3: Cross-Tenant Signed URL Generation ───────────────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.get_signed_url")
    def test_cross_tenant_signed_url_denied(self, mock_signed_url, mock_get_bid):
        mock_get_bid.return_value = None
        with self.assertRaises(AccessDeniedError):
            tenancy.get_signed_url_for_document_for_organization(self.bid_b, self.doc_b, self.org_a)
        mock_signed_url.assert_not_called()

    # ── Negative Control 4: Foreign Document ID for Signed URL ───────────────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.get_document")
    @patch("tenancy.db.get_signed_url")
    def test_foreign_document_id_signed_url_denied(self, mock_signed_url, mock_get_doc, mock_get_bid):
        mock_get_bid.return_value = self.mock_bid_a
        mock_get_doc.return_value = self.mock_doc_b
        with self.assertRaises(AccessDeniedError):
            tenancy.get_signed_url_for_document_for_organization(self.bid_a, self.doc_b, self.org_a)
        mock_signed_url.assert_not_called()

    # ── Positive Control 2: Legitimate Signed URL Generation ─────────────────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.get_document")
    @patch("tenancy.db.get_signed_url")
    def test_authorized_signed_url_success(self, mock_signed_url, mock_get_doc, mock_get_bid):
        mock_get_bid.return_value = self.mock_bid_a
        mock_get_doc.return_value = self.mock_doc_a
        mock_signed_url.return_value = "https://storage.supabase.co/signed/alpha_uuid.pdf?token=valid"

        url = tenancy.get_signed_url_for_document_for_organization(self.bid_a, self.doc_a, self.org_a)
        self.assertEqual(url, "https://storage.supabase.co/signed/alpha_uuid.pdf?token=valid")
        mock_signed_url.assert_called_once_with(self.mock_doc_a["storage_path"], expires_in=3600)

    # ── Negative Control 5: Cross-Tenant Document Deletion ───────────────────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.delete_document")
    def test_cross_tenant_document_delete_denied(self, mock_delete, mock_get_bid):
        mock_get_bid.return_value = None
        with self.assertRaises(AccessDeniedError):
            tenancy.delete_document_for_organization(self.bid_b, self.doc_b, self.org_a)
        mock_delete.assert_not_called()

    # ── Negative Control 6: Foreign Document ID Deletion ─────────────────────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.get_document")
    @patch("tenancy.db.delete_document")
    def test_foreign_document_id_delete_denied(self, mock_delete, mock_get_doc, mock_get_bid):
        mock_get_bid.return_value = self.mock_bid_a
        mock_get_doc.return_value = self.mock_doc_b
        with self.assertRaises(AccessDeniedError):
            tenancy.delete_document_for_organization(self.bid_a, self.doc_b, self.org_a)
        mock_delete.assert_not_called()

    # ── Positive Control 3: Legitimate Document Deletion ─────────────────────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.get_document")
    @patch("tenancy.db.delete_document")
    def test_authorized_document_delete_success(self, mock_delete, mock_get_doc, mock_get_bid):
        mock_get_bid.return_value = self.mock_bid_a
        mock_get_doc.return_value = self.mock_doc_a

        tenancy.delete_document_for_organization(self.bid_a, self.doc_a, self.org_a)
        mock_delete.assert_called_once_with(self.doc_a, bid_id=self.bid_a)

    # ── Negative Control 7: Cross-Tenant Document Version Replacement ────────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.get_document")
    @patch("tenancy.db.save_upload")
    def test_cross_tenant_document_replacement_denied(self, mock_save_upload, mock_get_doc, mock_get_bid):
        # Attacker in Org A specifies doc_b belonging to Org B
        mock_get_bid.return_value = self.mock_bid_a
        mock_get_doc.return_value = self.mock_doc_b  # doc belongs to Bid B
        with self.assertRaises(AccessDeniedError):
            tenancy.upload_document_for_organization(
                self.bid_a, self.org_a, "Tampered.pdf", b"bytes", doc_id=self.doc_b
            )
        mock_save_upload.assert_not_called()

    # ── Positive Control 4: Legitimate Document Version Replacement ──────────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.get_document")
    @patch("tenancy.db.save_upload")
    def test_authorized_document_replacement_success(self, mock_save_upload, mock_get_doc, mock_get_bid):
        mock_get_bid.return_value = self.mock_bid_a
        mock_get_doc.return_value = self.mock_doc_a
        mock_save_upload.return_value = (self.mock_doc_a["file_path"], self.doc_a)

        tenancy.upload_document_for_organization(
            self.bid_a, self.org_a, "Alpha_v2.pdf", b"new bytes", doc_id=self.doc_a
        )
        mock_save_upload.assert_called_once_with(
            self.bid_a, "Alpha_v2.pdf", b"new bytes", doc_type="RFP / Source", owner=None, doc_id=self.doc_a
        )

    # ── Negative Control 8: Cross-Tenant Analysis Report Download ────────────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.download_file")
    def test_cross_tenant_analysis_report_download_denied(self, mock_download, mock_get_bid):
        mock_get_bid.return_value = None
        with self.assertRaises(AccessDeniedError):
            tenancy.download_analysis_report_for_organization(self.bid_b, self.run_b, self.org_a)
        mock_download.assert_not_called()

    # ── Negative Control 9: Foreign Run ID for Analysis Report ───────────────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.get_analysis_run")
    @patch("tenancy.db.download_file")
    def test_foreign_run_id_analysis_report_download_denied(self, mock_download, mock_get_run, mock_get_bid):
        mock_get_bid.return_value = self.mock_bid_a
        mock_get_run.return_value = self.mock_run_b  # belongs to bid_b
        with self.assertRaises(AccessDeniedError):
            tenancy.download_analysis_report_for_organization(self.bid_a, self.run_b, self.org_a)
        mock_download.assert_not_called()

    # ── Positive Control 5: Legitimate Analysis Report Download ──────────────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.get_analysis_run")
    @patch("tenancy.db.download_file")
    def test_authorized_analysis_report_download_success(self, mock_download, mock_get_run, mock_get_bid):
        mock_get_bid.return_value = self.mock_bid_a
        mock_get_run.return_value = self.mock_run_a
        mock_download.return_value = b"%PDF-1.4 report bytes"

        result = tenancy.download_analysis_report_for_organization(self.bid_a, self.run_a, self.org_a)
        self.assertEqual(result, b"%PDF-1.4 report bytes")
        mock_download.assert_called_once_with(self.mock_run_a["report_storage_path"])

    # ── Negative Control 10: Storage Path Traversal and Manipulation ─────────
    def test_storage_path_manipulation_defense(self):
        # Verify database.download_file fails closed against directory traversal or malformed paths
        self.assertIsNone(db.download_file("../../../etc/passwd"))
        self.assertIsNone(db.download_file("/root/secret.pdf"))
        self.assertIsNone(db.download_file(""))
        self.assertIsNone(db.download_file("   "))
        self.assertIsNone(db.download_file(None))

        # Verify database.get_signed_url fails closed against traversal or malformed paths
        self.assertEqual(db.get_signed_url("../../../etc/passwd"), "")
        self.assertEqual(db.get_signed_url("/root/secret.pdf"), "")
        self.assertEqual(db.get_signed_url(""), "")
        self.assertEqual(db.get_signed_url("   "), "")
        self.assertEqual(db.get_signed_url(None), "")

    # ── Defense in Depth: database.get_document_signed_url ───────────────────
    @patch("database.get_client")
    def test_database_get_document_signed_url_cross_tenant_denied(self, mock_get_client):
        mock_sb = MagicMock()
        mock_get_client.return_value = mock_sb

        # Mock document query returning doc belonging to bid_b
        mock_doc_table = MagicMock()
        mock_doc_table.select.return_value.eq.return_value.execute.return_value.data = [self.mock_doc_b]
        
        # Mock bids query returning bid_b belonging to org_b
        mock_bid_table = MagicMock()
        mock_bid_table.select.return_value.eq.return_value.execute.return_value.data = [self.mock_bid_b]

        def table_side_effect(name):
            if name == "documents":
                return mock_doc_table
            if name == "bids":
                return mock_bid_table
            return MagicMock()

        mock_sb.table.side_effect = table_side_effect

        # Org A attempts to sign Org B's doc via database primitive directly
        result = db.get_document_signed_url(self.doc_b, self.org_a)
        self.assertEqual(result, "")

    @patch("database.get_signed_url")
    @patch("database.get_client")
    def test_database_get_document_signed_url_authorized(self, mock_get_client, mock_get_signed_url):
        mock_sb = MagicMock()
        mock_get_client.return_value = mock_sb
        mock_get_signed_url.return_value = "https://storage.supabase.co/signed/valid"

        mock_doc_table = MagicMock()
        mock_doc_table.select.return_value.eq.return_value.execute.return_value.data = [self.mock_doc_a]
        mock_bid_table = MagicMock()
        mock_bid_table.select.return_value.eq.return_value.execute.return_value.data = [self.mock_bid_a]

        def table_side_effect(name):
            if name == "documents":
                return mock_doc_table
            if name == "bids":
                return mock_bid_table
            return MagicMock()

        mock_sb.table.side_effect = table_side_effect

        result = db.get_document_signed_url(self.doc_a, self.org_a)
        self.assertEqual(result, "https://storage.supabase.co/signed/valid")

    # ── Defense in Depth: database.save_upload Mismatched Bid & Doc ID ───────
    @patch("database.get_client")
    def test_database_save_upload_mismatched_bid_and_doc_id_raises(self, mock_get_client):
        mock_sb = MagicMock()
        mock_get_client.return_value = mock_sb

        # Mock document query returning doc belonging to bid_b
        mock_doc_table = MagicMock()
        mock_doc_table.select.return_value.eq.return_value.execute.return_value.data = [self.mock_doc_b]
        mock_sb.table.return_value = mock_doc_table

        with self.assertRaises(ValueError) as ctx:
            db.save_upload(self.bid_a, "Tampered.pdf", b"bytes", doc_id=self.doc_b)
        self.assertIn(f"document {self.doc_b} does not belong to bid {self.bid_a}", str(ctx.exception))

    # ── Negative Control 11: Missing Caller Context Fails Closed ─────────────
    def test_missing_caller_context_fails_closed(self):
        with self.assertRaises(AccessDeniedError):
            tenancy.require_bid_access(self.bid_a, "")
        with self.assertRaises(AccessDeniedError):
            tenancy.require_bid_access(self.bid_a, None)
        with self.assertRaises(AccessDeniedError):
            tenancy.download_document_for_organization(self.bid_a, self.doc_a, "")
        with self.assertRaises(AccessDeniedError):
            tenancy.get_signed_url_for_document_for_organization(self.bid_a, self.doc_a, None)

    # ── Negative Control 12: Cross-Tenant Document Metadata Modification ─────
    @patch("tenancy.get_bid_for_organization")
    @patch("tenancy.db.get_document")
    @patch("tenancy.db.upsert_document")
    def test_upsert_document_cross_tenant_denied(self, mock_upsert, mock_get_doc, mock_get_bid):
        mock_get_bid.return_value = self.mock_bid_a
        mock_get_doc.return_value = self.mock_doc_b  # belongs to bid_b
        with self.assertRaises(AccessDeniedError):
            tenancy.upsert_document_for_organization(
                self.bid_a, self.org_a, {"id": self.doc_b, "name": "Hacked Name"}
            )
        mock_upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
