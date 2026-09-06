import io
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import xlrd

from canonical_opportunity import _validate_ref as validate_canonical_ref
from extractor import (
    _xls_cell_text,
    _xls_temporal_format_kind,
    extract_document_with_metadata,
    extract_xls_with_metadata,
    unpack_procurement_package,
    validate_source_refs,
)


FIXTURE = Path(__file__).parent / "fixtures" / "xls" / "synthetic_legacy.xls"


class TestLegacyXlsExtraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.file_bytes = FIXTURE.read_bytes()
        cls.text, cls.meta = extract_xls_with_metadata(cls.file_bytes, "synthetic_legacy.xls")

    def test_real_sheet_order_visibility_and_empty_sheet(self):
        self.assertEqual(
            self.meta["sheets"],
            ["Main Data", "Hidden Guidance", "Very Hidden", "Empty Sheet"],
        )
        self.assertEqual(self.meta["sheet_visibility"]["Hidden Guidance"], "HIDDEN")
        self.assertEqual(self.meta["sheet_visibility"]["Very Hidden"], "VERY_HIDDEN")
        self.assertEqual(self.meta["rows_per_sheet"]["Empty Sheet"], (0, 0, set()))

    def test_physical_rows_unicode_and_merged_heading(self):
        self.assertIn("Row 1: Commercial Response", self.text)
        self.assertIn("Row 10: Café – أسعار | 42 | 12.5 | False", self.text)
        self.assertNotIn("Row 2:", self.text)
        self.assertEqual(self.text.count("Commercial Response"), 1)
        self.assertEqual(self.meta["merged_ranges"]["Main Data"], ["A1:D1"])

    def test_numeric_boolean_percentage_date_and_datetime_rendering(self):
        self.assertIn("Row 11: 0", self.text)
        self.assertIn("Row 12: 25%", self.text)
        self.assertIn("Row 13: 12.5%", self.text)
        self.assertIn("Row 14: 2028-02-29", self.text)
        self.assertIn("Row 15: 2028-02-29T13:45:30", self.text)
        self.assertNotIn("+00:00", self.text)

    def test_time_only_values_do_not_invent_epoch_dates_or_timezone(self):
        self.assertIn("Row 17: 13:45:00", self.text)
        self.assertIn("Row 18: 13:45:30", self.text)
        self.assertNotRegex(self.text, r"(?:1899|1900|1904)-.*13:45")
        self.assertNotIn("+00:00", self.text)

    def test_elapsed_time_format_falls_back_to_non_calendar_numeric_text(self):
        self.assertIn("Row 19: 1.5", self.text)
        row = next(line for line in self.text.splitlines() if line.startswith("Row 19:"))
        self.assertNotRegex(row, r"\d{4}-\d{2}-\d{2}")

    def test_time_only_rendering_is_epoch_independent(self):
        cell = SimpleNamespace(ctype=xlrd.XL_CELL_DATE, value=0.5729166666666666, xf_index=0)
        for datemode in (0, 1):
            workbook = SimpleNamespace(
                datemode=datemode,
                xf_list=[SimpleNamespace(format_key=1)],
                format_map={1: SimpleNamespace(format_str="h:mm")},
            )
            rendered = _xls_cell_text(cell, workbook)
            self.assertEqual(rendered, "13:45:00")
            self.assertNotRegex(rendered, r"1899|1900|1904")

    def test_temporal_format_classifier_ignores_literals_and_metadata(self):
        self.assertEqual(_xls_temporal_format_kind('[$-409]yyyy-mm-dd'), "DATE_ONLY")
        self.assertEqual(_xls_temporal_format_kind('yyyy\\-mm\\-dd h\\:mm'), "DATE_TIME")
        self.assertEqual(_xls_temporal_format_kind('[Red]h:mm "local"'), "TIME_ONLY")
        self.assertEqual(_xls_temporal_format_kind('[h]:mm'), "ELAPSED")

    def test_cached_formula_is_not_evaluated_or_exposed(self):
        self.assertEqual(self.meta["formula_policy"], "CACHED_VALUES")
        self.assertNotIn("B10+C10", self.text)
        self.assertNotIn("Row 16:", self.text)

    def test_excel_error_code_maps_to_stable_token(self):
        cell = SimpleNamespace(ctype=xlrd.XL_CELL_ERROR, value=7, xf_index=0)
        self.assertEqual(_xls_cell_text(cell, SimpleNamespace()), "#DIV/0!")

    def test_direct_and_zip_xls_admission_while_doc_stays_rejected(self):
        direct, direct_warnings = unpack_procurement_package([
            ("pricing.xls", self.file_bytes), ("legacy.doc", b"legacy")
        ])
        self.assertEqual([name for name, _ in direct], ["pricing.xls"])
        self.assertTrue(any("legacy.doc" in warning for warning in direct_warnings))

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("annexes/Annex 2a.xls", self.file_bytes)
        unpacked, warnings = unpack_procurement_package([("package.zip", archive.getvalue())])
        self.assertEqual([name for name, _ in unpacked], ["Annex 2a.xls"])
        self.assertEqual(warnings, [])

    def test_xls_and_xlsx_have_separate_routes(self):
        with patch("extractor.extract_xls_with_metadata", return_value=("xls", {})) as xls, patch(
            "extractor.extract_xlsx_with_metadata", return_value=("xlsx", {})
        ) as xlsx:
            self.assertEqual(extract_document_with_metadata(b"a", "book.xls")[0], "xls")
            xls.assert_called_once()
            xlsx.assert_not_called()

        with patch("extractor.extract_xls_with_metadata", return_value=("xls", {})) as xls, patch(
            "extractor.extract_xlsx_with_metadata", return_value=("xlsx", {})
        ) as xlsx:
            self.assertEqual(extract_document_with_metadata(b"a", "book.xlsx")[0], "xlsx")
            xlsx.assert_called_once()
            xls.assert_not_called()

    def test_fake_and_truncated_xls_fail_safely(self):
        fake_text, fake_meta = extract_xls_with_metadata(b"plain text", "fake.xls")
        self.assertEqual(fake_meta["parse_status"], "UNSUPPORTED_XLS_VARIANT")
        self.assertIn("[[SOURCE: fake.xls]]", fake_text)
        self.assertNotIn("Traceback", fake_text)

        truncated = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 32
        corrupt_text, corrupt_meta = extract_xls_with_metadata(truncated, "corrupt.xls")
        self.assertEqual(corrupt_meta["parse_status"], "CORRUPT")
        self.assertIn("XLS parsing failed", corrupt_text)

    def test_failed_xls_warns_without_removing_other_files(self):
        unpacked, warnings = unpack_procurement_package([
            ("bad.xls", b"not a workbook"), ("instructions.txt", b"Submit response")
        ])
        self.assertEqual([name for name, _ in unpacked], ["bad.xls", "instructions.txt"])
        self.assertTrue(any("bad.xls" in warning for warning in warnings))

    def test_existing_and_canonical_provenance_accept_xls_markers(self):
        package = {
            "files": ["synthetic_legacy.xls"],
            "doc_metadata": {"synthetic_legacy.xls": self.meta},
            "doc_texts": {"synthetic_legacy.xls": self.text},
        }
        ref = {
            "source_doc": "synthetic_legacy.xls",
            "sheet": "Main Data",
            "rows": 10,
            "excerpt": "Café – أسعار",
        }
        validated = validate_source_refs([ref], package)
        self.assertTrue(validated[0]["verified"])
        _, state = validate_canonical_ref(ref, package)
        self.assertEqual(state, "VERIFIED")

    def test_public_extractor_contract_remains_text_and_metadata_tuple(self):
        result = extract_document_with_metadata(self.file_bytes, "synthetic_legacy.xls")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], str)
        self.assertIsInstance(result[1], dict)


if __name__ == "__main__":
    unittest.main()
