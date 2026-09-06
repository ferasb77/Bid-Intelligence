"""
Integration Tests: Procurement Package Ingestion & Multi-Document Reconciliation
Deterministic synthetic fixtures testing multi-document extraction, safe ZIP handling,
XLSX / DOCX parsing, deterministic source markers, and conflict detection.
"""
import io
import os
import zipfile
import unittest
from extractor import (
    extract_text_from_file,
    unpack_procurement_package,
    detect_document_conflicts,
    STAGE_A_FACT_EXTRACTION_PROMPT,
    STAGE_D_SYNTHESIS_PROMPT
)


class TestProcurementPackageIngestion(unittest.TestCase):
    """Synthetic Multi-Document Package Ingestion & Security Tests."""

    def test_zip_safe_unpacking_and_path_traversal_rejection(self):
        """Verify ZIP unpacker extracts valid documents and rejects path traversal attacks."""
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
            # Valid supported files
            z.writestr("Main_RFP.txt", "Tender instructions and scope.")
            z.writestr("Appendix_A.docx", "Mandatory requirements document.")
            z.writestr("Pricing_Template.xlsx", "Financial workbook.")
            # Nested subfolder valid file
            z.writestr("schedules/Schedule_1.txt", "Delivery milestones.")
            # Malicious path traversal attempt
            z.writestr("../malicious_file.txt", "Malicious content.")
            z.writestr("../../etc/passwd", "Root exploit.")
            # Unsupported binary
            z.writestr("malicious_executable.exe", b"MZ\x90\x00BinaryExe")
            # Unsupported legacy DOC and supported-but-malformed legacy XLS
            z.writestr("legacy.doc", b"Old binary doc")
            z.writestr("legacy.xls", b"Old binary xls")
            # Hidden system file
            z.writestr(".DS_Store", b"\x00\x00")

        zip_bytes = zip_buffer.getvalue()
        raw_files = [("Procurement_Package.zip", zip_bytes)]

        unpacked, warnings = unpack_procurement_package(raw_files)
        unpacked_names = [f[0] for f in unpacked]

        # Valid files must be unpacked safely
        self.assertIn("Main_RFP.txt", unpacked_names)
        self.assertIn("Appendix_A.docx", unpacked_names)
        self.assertIn("Pricing_Template.xlsx", unpacked_names)
        self.assertIn("Schedule_1.txt", unpacked_names)

        # Path traversal files, binaries, and legacy DOC MUST be rejected.
        # XLS is admitted and its parser failure is reported without aborting the package.
        self.assertNotIn("../malicious_file.txt", unpacked_names)
        self.assertNotIn("../../etc/passwd", unpacked_names)
        self.assertNotIn("malicious_executable.exe", unpacked_names)
        self.assertNotIn("legacy.doc", unpacked_names)
        self.assertIn("legacy.xls", unpacked_names)
        self.assertNotIn(".DS_Store", unpacked_names)

        # Warnings should record the rejections
        self.assertTrue(any("Security Alert" in w for w in warnings))
        self.assertTrue(any("malicious_executable.exe" in w for w in warnings))
        self.assertTrue(any("legacy.xls" in w for w in warnings))

    def test_multi_document_preserves_filenames_and_markers(self):
        """Verify deterministic source markers are inserted for multi-document packages."""
        doc1_bytes = b"Section 1: Mandatory Scope. All bidders must deliver bilingual support."
        doc2_bytes = b"Section 2: Security. Reliability clearance required for all team members."

        parsed1 = extract_text_from_file(doc1_bytes, "Main_RFP.txt")
        parsed2 = extract_text_from_file(doc2_bytes, "Appendix_B.txt")

        self.assertIn("[[SOURCE: Main_RFP.txt", parsed1)
        self.assertIn("bilingual support", parsed1)
        self.assertIn("[[SOURCE: Appendix_B.txt", parsed2)
        self.assertIn("Reliability clearance", parsed2)

    def test_docx_xml_parsing_fallback(self):
        """Verify DOCX text extraction parses headings and body text cleanly."""
        docx_buffer = io.BytesIO()
        with zipfile.ZipFile(docx_buffer, "w", zipfile.ZIP_DEFLATED) as z:
            doc_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                <w:body>
                    <w:p><w:r><w:t>Mandatory Criteria for Bidder Experience</w:t></w:r></w:p>
                    <w:p><w:r><w:t>Minimum 5 years organizational advisory experience required.</w:t></w:r></w:p>
                </w:body>
            </w:document>"""
            z.writestr("word/document.xml", doc_xml)

        docx_bytes = docx_buffer.getvalue()
        extracted = extract_text_from_file(docx_bytes, "Mandatory_Form.docx")

        self.assertIn("[[SOURCE: Mandatory_Form.docx", extracted)
        self.assertIn("Mandatory Criteria for Bidder Experience", extracted)
        self.assertIn("Minimum 5 years organizational advisory experience required", extracted)

    def test_xlsx_xml_parsing_fallback(self):
        """Verify XLSX text extraction extracts shared strings and workbook values."""
        xlsx_buffer = io.BytesIO()
        with zipfile.ZipFile(xlsx_buffer, "w", zipfile.ZIP_DEFLATED) as z:
            sst_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="3" uniqueCount="3">
                <si><t>Category 1 Pricing Scenario</t></si>
                <si><t>Deliverable Cohorts: 21</t></si>
                <si><t>Fixed Price Cap: CAD 450,000</t></si>
            </sst>"""
            z.writestr("xl/sharedStrings.xml", sst_xml)

        xlsx_bytes = xlsx_buffer.getvalue()
        extracted = extract_text_from_file(xlsx_bytes, "Pricing_Workbook.xlsx")

        self.assertIn("[[SOURCE: Pricing_Workbook.xlsx", extracted)
        self.assertIn("Category 1 Pricing Scenario", extracted)
        self.assertIn("Deliverable Cohorts: 21", extracted)

    def test_addenda_deadline_conflict_reconciliation(self):
        """Verify that when an addendum amends the deadline, a conflict record is generated."""
        normalized_facts = {
            "dates": [
                {"milestone": "Submission Deadline", "date": "2026-09-30", "source_doc": "Main_RFP.pdf"},
                {"milestone": "Revised Extended Deadline (Addendum 1)", "date": "2026-10-02", "source_doc": "Addendum_No_1.pdf"}
            ]
        }
        package_files = ["Main_RFP.pdf", "Addendum_No_1.pdf"]

        conflicts = detect_document_conflicts(normalized_facts, package_files)

        self.assertTrue(len(conflicts) > 0)
        date_conflict = next((c for c in conflicts if c.get("conflict_type") == "DATE_CONFLICT"), None)
        self.assertIsNotNone(date_conflict)
        self.assertIn("2026-10-02", date_conflict["assessment"])


if __name__ == "__main__":
    unittest.main()
