"""
tests/test_submission_package_alignment.py

Deterministic tests for the multi-file Submission Package extension of
the Proposal Alignment Analyzer (CHECK -> Proposal Alignment Analyzer).
No live LLM calls -- analyst._call() is mocked everywhere a package
audit runs one. No live network/Storage calls anywhere.

Covers:
  * TestPackageAssembly -- extractor.build_alignment_submission_package():
    multiple individual files, a .zip containing multiple files, stable
    file_id identity, byte-identical duplicate detection (including a
    direct-upload + zip duplicate), duplicate filenames at different
    paths staying distinct, explicit PPTX/legacy-format surfacing
    (never silently dropped), and primary-file auto-selection.
  * TestZipSafety -- path traversal (unix + Windows + UNC + drive
    letter), entry-count / per-file-size / total-size / compression-
    ratio limits, all enforced before decompression.
  * TestPackageChunkAllocation -- _allocate_package_chunk_budget()'s
    fair, size-proportional, deterministic allocation across files.
  * TestPackageAlignmentAudit -- analyst.analyze_proposal_alignment_
    package(): requirement evidence found only in a schedule (not the
    primary file) is aggregated correctly, filename-qualified evidence
    locations, XLSX sheet provenance, included-failed-file fail-closed
    behavior, excluded-file exclusion from the completeness calculus,
    and sampling-forces-incomplete behavior.
  * TestPdfPackageManifest -- the Submission Package Manifest renders in
    the exported PDF with filenames/statuses, and filename-qualified
    evidence locations appear in findings/coverage tables.
  * TestSessionIsolation -- bid-scoped Alignment session-state keys
    never leak across bids, and logout clears all of them.
"""
import io
import json
import os
import time
import unittest
import zipfile
from unittest.mock import MagicMock, patch

import fitz

import analyst
import extractor
import pdf_alignment


def _zip_bytes(entries: dict) -> bytes:
    """entries: {in-zip-path: bytes}. Uses real DEFLATE compression (not
    zipfile's default ZIP_STORED) so a genuinely compressible payload
    (e.g. repeated zero bytes) produces a real, measurable compression
    ratio -- needed for the compression-bomb test to exercise the actual
    ratio check rather than always seeing file_size == compress_size."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for path, data in entries.items():
            z.writestr(path, data)
    return buf.getvalue()


def _xlsx_bytes(sheets: dict) -> bytes:
    """sheets: {sheet_name: [[row values], ...]}"""
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _req(req_id, category="Rated", description="desc", weight=None):
    return {"req_id": req_id, "category": category, "description": description, "weight": weight}


def _chunk_response(assertions=None, findings=None):
    return json.dumps({"chunk_findings": findings or [], "requirement_assertions": assertions or []})


def _synthesis_response(summary="ok", strengths=None, next_steps=None):
    return json.dumps({"executive_summary": summary, "strengths": strengths or [], "next_steps": next_steps or []})


def _fake_call_factory(assertions_by_marker: dict):
    """Returns a fake analyst._call() that emits a requirement_assertion
    whenever a chunk prompt contains a given marker string -- lets tests
    plant evidence in one specific file/sheet and prove it surfaces with
    that file's own filename-qualified location."""
    def fake_call(system, user, max_tokens=2048, **kwargs):
        if "requirement_assertions" not in user:
            return _synthesis_response()
        for marker, assertion in assertions_by_marker.items():
            if marker in user:
                return _chunk_response(assertions=[assertion])
        return _chunk_response()
    return fake_call


class TestPackageAssembly(unittest.TestCase):
    def test_multiple_individual_files_are_all_extracted(self):
        raw = [
            ("Technical Proposal.txt", b"We propose a robust methodology."),
            ("Schedule C - Pricing.txt", b"Our pricing is fixed at $100,000."),
        ]
        pkg = extractor.build_alignment_submission_package(raw)
        statuses = {f["filename"]: f["lifecycle_status"] for f in pkg["files"]}
        self.assertEqual(statuses, {"Technical Proposal.txt": "extracted", "Schedule C - Pricing.txt": "extracted"})

    def test_zip_with_multiple_supported_files_all_extracted(self):
        z = _zip_bytes({
            "Technical Proposal.txt": b"Methodology narrative.",
            "schedules/Schedule C.txt": b"Pricing details.",
        })
        pkg = extractor.build_alignment_submission_package([("submission.zip", z)])
        paths = {f["package_path"] for f in pkg["files"]}
        self.assertIn("submission.zip/Technical Proposal.txt", paths)
        self.assertIn("submission.zip/schedules/Schedule C.txt", paths)
        for f in pkg["files"]:
            self.assertEqual(f["lifecycle_status"], "extracted")

    def test_stable_file_id_distinguishes_duplicate_filenames_in_different_directories(self):
        z = _zip_bytes({
            "east/Schedule C.txt": b"East region pricing.",
            "west/Schedule C.txt": b"West region pricing -- different content.",
        })
        pkg = extractor.build_alignment_submission_package([("submission.zip", z)])
        file_ids = [f["file_id"] for f in pkg["files"]]
        self.assertEqual(len(file_ids), len(set(file_ids)), "two distinct files must never collide on file_id")
        statuses = {f["package_path"]: f["lifecycle_status"] for f in pkg["files"]}
        self.assertEqual(statuses["submission.zip/east/Schedule C.txt"], "extracted")
        self.assertEqual(statuses["submission.zip/west/Schedule C.txt"], "extracted")

    def test_byte_identical_duplicate_is_analyzed_once(self):
        content = b"Identical pricing schedule content."
        raw = [("Schedule C.txt", content), ("Schedule C (copy).txt", content)]
        pkg = extractor.build_alignment_submission_package(raw)
        by_name = {f["filename"]: f for f in pkg["files"]}
        self.assertEqual(by_name["Schedule C.txt"]["lifecycle_status"], "extracted")
        self.assertEqual(by_name["Schedule C (copy).txt"]["lifecycle_status"], "duplicate")
        self.assertEqual(by_name["Schedule C (copy).txt"]["duplicate_of_file_id"], by_name["Schedule C.txt"]["file_id"])
        self.assertFalse(by_name["Schedule C (copy).txt"]["included"])

    def test_direct_upload_and_zip_duplicate_is_deduplicated(self):
        content = b"Schedule C pricing content shared between direct upload and zip."
        z = _zip_bytes({"Schedule C.txt": content})
        raw = [("Schedule C.txt", content), ("submission.zip", z)]
        pkg = extractor.build_alignment_submission_package(raw)
        statuses = [f["lifecycle_status"] for f in pkg["files"]]
        self.assertEqual(statuses.count("extracted"), 1)
        self.assertEqual(statuses.count("duplicate"), 1)

    def test_duplicate_does_not_count_as_failure(self):
        content = b"Same content twice."
        raw = [("A.txt", content), ("B.txt", content)]
        pkg = extractor.build_alignment_submission_package(raw)
        summary = extractor.summarize_submission_package(pkg["files"])
        self.assertEqual(summary["files_failed"], 0)
        self.assertEqual(summary["files_duplicate"], 1)

    def test_pptx_is_surfaced_as_explicitly_unsupported_never_silently_dropped(self):
        pkg = extractor.build_alignment_submission_package([("Deck.pptx", b"fake pptx bytes")])
        self.assertEqual(len(pkg["files"]), 1)
        f = pkg["files"][0]
        self.assertEqual(f["lifecycle_status"], "unsupported")
        self.assertIn("unsupported", f["unusable_reason"].lower())
        self.assertIn("pptx", f["unusable_reason"].lower())

    def test_unsupported_file_visible_in_manifest_before_audit(self):
        pkg = extractor.build_alignment_submission_package([
            ("Technical Proposal.txt", b"Methodology."),
            ("Legacy.doc", b"fake legacy bytes"),
        ])
        summary = extractor.summarize_submission_package(pkg["files"])
        self.assertEqual(summary["files_unsupported"], 1)
        self.assertEqual(summary["files_supplied"], 2)

    def test_single_extracted_file_auto_selected_as_primary(self):
        pkg = extractor.build_alignment_submission_package([("Technical Proposal.txt", b"Methodology narrative.")])
        self.assertEqual(pkg["primary_file_id"], pkg["files"][0]["file_id"])
        self.assertEqual(pkg["files"][0]["role"], "primary")

    def test_multiple_files_no_primary_auto_selected(self):
        pkg = extractor.build_alignment_submission_package([
            ("A.txt", b"Content A."), ("B.txt", b"Content B."),
        ])
        self.assertIsNone(pkg["primary_file_id"])
        self.assertTrue(all(f["role"] is None for f in pkg["files"]))

    def test_included_failed_file_forces_incomplete_downstream_failed_status(self):
        # A genuinely corrupt XLSX (wrong signature) fails extraction.
        pkg = extractor.build_alignment_submission_package([("Broken.xlsx", b"not a real xlsx")])
        self.assertEqual(pkg["files"][0]["lifecycle_status"], "failed")
        self.assertIsNotNone(pkg["files"][0]["unusable_reason"])
        self.assertTrue(pkg["files"][0]["included"])  # defaults included -- must be actively excluded


class TestOccurrenceIdentity(unittest.TestCase):
    """Occurrence ID vs content identity must be separate (pre-commit
    hardening item 1): a direct upload and a byte-identical root-level
    file inside a ZIP must never receive the same file_id merely because
    package_path + bytes happen to collide -- file_id folds in
    unpack_submission_package()'s discovery-order occurrence_index
    specifically to rule that out, for ANY collision shape, not just the
    one concrete example below."""

    # .txt (not .xlsx) deliberately -- these tests exercise identity/
    # dedup logic, not spreadsheet extraction, and a plain-text payload
    # named "Schedule C.xlsx" would (correctly) fail XLSX parsing and
    # muddy the assertions below with an unrelated "failed" status.

    def test_direct_upload_and_root_level_zip_duplicate_get_distinct_file_ids(self):
        content = b"Identical Schedule C pricing content, byte for byte."
        z = _zip_bytes({"Schedule C.txt": content})
        pkg = extractor.build_alignment_submission_package([
            ("Schedule C.txt", content), ("submission.zip", z),
        ])
        by_path = {f["package_path"]: f for f in pkg["files"]}
        direct = by_path["Schedule C.txt"]
        nested = by_path["submission.zip/Schedule C.txt"]
        self.assertNotEqual(direct["file_id"], nested["file_id"],
                             "two distinct occurrences must never share a file_id")

    def test_direct_upload_and_zip_duplicate_share_content_hash(self):
        content = b"Identical Schedule C pricing content, byte for byte."
        z = _zip_bytes({"Schedule C.txt": content})
        pkg = extractor.build_alignment_submission_package([
            ("Schedule C.txt", content), ("submission.zip", z),
        ])
        by_path = {f["package_path"]: f for f in pkg["files"]}
        self.assertEqual(by_path["Schedule C.txt"]["content_hash"],
                          by_path["submission.zip/Schedule C.txt"]["content_hash"])

    def test_only_one_occurrence_is_analyzable_and_included(self):
        content = b"Identical Schedule C pricing content, byte for byte."
        z = _zip_bytes({"Schedule C.txt": content})
        pkg = extractor.build_alignment_submission_package([
            ("Schedule C.txt", content), ("submission.zip", z),
        ])
        analyzable = [f for f in pkg["files"] if f["analyzable"]]
        included_extracted = [f for f in pkg["files"] if f["included"] and f["lifecycle_status"] == "extracted"]
        self.assertEqual(len(analyzable), 1)
        self.assertEqual(len(included_extracted), 1)

    def test_duplicate_points_to_the_retained_occurrences_own_file_id(self):
        content = b"Identical Schedule C pricing content, byte for byte."
        z = _zip_bytes({"Schedule C.txt": content})
        pkg = extractor.build_alignment_submission_package([
            ("Schedule C.txt", content), ("submission.zip", z),
        ])
        by_path = {f["package_path"]: f for f in pkg["files"]}
        retained = by_path["Schedule C.txt"]
        duplicate = by_path["submission.zip/Schedule C.txt"]
        self.assertEqual(retained["lifecycle_status"], "extracted")
        self.assertEqual(duplicate["lifecycle_status"], "duplicate")
        self.assertEqual(duplicate["duplicate_of_file_id"], retained["file_id"])
        self.assertNotEqual(duplicate["duplicate_of_file_id"], duplicate["file_id"])

    def test_no_streamlit_widget_key_collision_between_occurrences(self):
        content = b"Identical Schedule C pricing content, byte for byte."
        z = _zip_bytes({"Schedule C.txt": content})
        pkg = extractor.build_alignment_submission_package([
            ("Schedule C.txt", content), ("submission.zip", z),
        ])
        widget_keys = [f"align_inc_1_{f['file_id']}" for f in pkg["files"]]
        self.assertEqual(len(widget_keys), len(set(widget_keys)))

    def test_two_direct_uploads_with_same_name_and_content_get_distinct_file_ids(self):
        """Even without any ZIP involved: two direct uploads sharing both
        filename AND bytes (package_path is identical for both, since
        direct uploads carry no container disambiguator) must still get
        distinct occurrence file_ids."""
        content = b"Same name, same bytes, two separate uploads."
        pkg = extractor.build_alignment_submission_package([
            ("Schedule C.txt", content), ("Schedule C.txt", content),
        ])
        file_ids = [f["file_id"] for f in pkg["files"]]
        self.assertEqual(len(file_ids), len(set(file_ids)))
        statuses = [f["lifecycle_status"] for f in pkg["files"]]
        self.assertEqual(statuses.count("extracted"), 1)
        self.assertEqual(statuses.count("duplicate"), 1)

    def test_file_id_is_deterministic_for_a_stable_upload_list(self):
        """Same upload set, same order -> identical file_ids across two
        independent assembly calls -- required so Streamlit widget keys
        stay stable across reruns that don't change the upload set."""
        raw = [("A.txt", b"content A"), ("B.txt", b"content B")]
        pkg1 = extractor.build_alignment_submission_package(raw)
        pkg2 = extractor.build_alignment_submission_package(raw)
        self.assertEqual([f["file_id"] for f in pkg1["files"]], [f["file_id"] for f in pkg2["files"]])


class TestReportSnapshotIsLightweight(unittest.TestCase):
    """Pre-commit hardening item 2: the frozen report snapshot
    (extractor.build_report_manifest(), stored by pages/stage_check.py as
    align_result_package_snapshot_<bid_id>) must never carry raw bytes or
    full extracted text -- only the slim manifest fields the report
    actually renders."""

    def test_report_manifest_excludes_text_and_extraction_meta_payloads(self):
        pkg = extractor.build_alignment_submission_package([
            ("Technical Proposal.txt", ("Long methodology narrative. " * 5000).encode()),
        ])
        manifest = extractor.build_report_manifest(pkg["files"])
        self.assertEqual(len(manifest), 1)
        record = manifest[0]
        self.assertNotIn("text", record)
        self.assertNotIn("extraction_meta", record)
        self.assertNotIn("bytes", record)

    def test_report_manifest_retains_required_report_fields(self):
        pkg = extractor.build_alignment_submission_package([("A.txt", b"content")])
        manifest = extractor.build_report_manifest(pkg["files"])
        record = manifest[0]
        for field in ("file_id", "content_hash", "filename", "package_path", "file_type", "role",
                      "included", "lifecycle_status", "duplicate_of_file_id",
                      "char_count", "unusable_reason"):
            self.assertIn(field, record)

    def test_report_manifest_content_hash_matches_live_package(self):
        """PI-1.2: the persisted manifest's content_hash must be the SAME
        identity value proposal_intelligence.compute_package_digest()
        reads -- not merely present, but the real SHA-256 the live
        package already carries."""
        pkg = extractor.build_alignment_submission_package([("A.txt", b"content")])
        manifest = extractor.build_report_manifest(pkg["files"])
        self.assertEqual(manifest[0]["content_hash"], pkg["files"][0]["content_hash"])
        self.assertEqual(len(manifest[0]["content_hash"]), 64)  # sha256 hex

    def test_report_manifest_is_dramatically_smaller_than_the_live_package(self):
        big_text = ("Long methodology narrative sentence. " * 20000).encode()
        pkg = extractor.build_alignment_submission_package([("Technical Proposal.txt", big_text)])
        live_size = len(json.dumps(pkg["files"], default=str))
        manifest_size = len(json.dumps(extractor.build_report_manifest(pkg["files"]), default=str))
        self.assertLess(manifest_size, live_size / 10)
        self.assertLess(manifest_size, 2000)


class TestZipSafety(unittest.TestCase):
    def test_unix_path_traversal_rejected(self):
        z = _zip_bytes({"../../etc/passwd": b"evil"})
        entries = extractor.unpack_submission_package([("evil.zip", z)])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], "rejected")
        self.assertIn("traversal", entries[0]["reason"].lower())

    def test_windows_style_traversal_rejected(self):
        z = _zip_bytes({"..\\..\\evil.txt": b"evil"})
        entries = extractor.unpack_submission_package([("evil.zip", z)])
        self.assertEqual(entries[0]["status"], "rejected")
        self.assertIn("traversal", entries[0]["reason"].lower())

    def test_windows_drive_path_rejected(self):
        self.assertEqual(extractor._zip_entry_path_is_unsafe("C:/Windows/System32/evil.txt"), "Windows drive path")

    def test_unc_path_rejected(self):
        self.assertEqual(extractor._zip_entry_path_is_unsafe("//server/share/evil.txt"), "UNC path")

    def test_absolute_unix_path_rejected(self):
        self.assertEqual(extractor._zip_entry_path_is_unsafe("/etc/passwd"), "absolute path")

    def test_safe_relative_path_accepted(self):
        self.assertIsNone(extractor._zip_entry_path_is_unsafe("schedules/Schedule C.xlsx"))

    def test_entry_count_limit_rejects_whole_archive(self):
        entries_dict = {f"file_{i}.txt": b"x" for i in range(extractor._ZIP_MAX_ENTRY_COUNT + 5)}
        z = _zip_bytes(entries_dict)
        entries = extractor.unpack_submission_package([("many.zip", z)])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], "rejected")
        self.assertIn("entries", entries[0]["reason"].lower())

    def test_individual_file_size_limit_enforced(self):
        info = MagicMock()
        info.file_size = extractor._ZIP_MAX_INDIVIDUAL_UNCOMPRESSED_BYTES + 1
        info.compress_size = 1000
        reason = extractor._zip_entry_exceeds_limits(info, running_total_bytes=0)
        self.assertIsNotNone(reason)
        self.assertIn("individual", reason.lower())

    def test_total_package_size_limit_enforced(self):
        info = MagicMock()
        info.file_size = 10 * 1024 * 1024
        info.compress_size = 1000
        reason = extractor._zip_entry_exceeds_limits(info, running_total_bytes=extractor._ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES)
        self.assertIsNotNone(reason)
        self.assertIn("total", reason.lower())

    def test_compression_bomb_ratio_rejected(self):
        # A genuinely compressible payload: 3,000,000 zero bytes compress
        # to well under 30,000 bytes -- a real >100:1 ratio, not a mock.
        bomb = _zip_bytes({"bomb.txt": b"\x00" * 3_000_000})
        entries = extractor.unpack_submission_package([("bomb.zip", bomb)])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["status"], "rejected")
        self.assertIn("compression", entries[0]["reason"].lower())

    def test_nested_zip_is_explicitly_unsupported(self):
        inner = _zip_bytes({"a.txt": b"hi"})
        outer = _zip_bytes({"inner.zip": inner})
        entries = extractor.unpack_submission_package([("outer.zip", outer)])
        self.assertEqual(entries[0]["status"], "unsupported")
        self.assertIn("nested", entries[0]["reason"].lower())


class TestPackageChunkAllocation(unittest.TestCase):
    def _secs(self, n, prefix="s"):
        return [{"start": i, "end": i + 1, "heading": f"{prefix}{i}", "text": "x"} for i in range(n)]

    def test_under_ceiling_keeps_everything_nothing_skipped(self):
        f1, f2 = {"file_id": "f1", "filename": "A.txt"}, {"file_id": "f2", "filename": "B.txt"}
        kept, skipped = analyst._allocate_package_chunk_budget(
            [(f1, self._secs(3)), (f2, self._secs(2))], ceiling=10
        )
        self.assertEqual(len(kept), 5)
        self.assertEqual(skipped, [])

    def test_small_file_is_not_entirely_sacrificed_to_a_large_file(self):
        big = {"file_id": "big", "filename": "Big.txt"}
        small = {"file_id": "small", "filename": "Small.txt"}
        kept, skipped = analyst._allocate_package_chunk_budget(
            [(big, self._secs(50)), (small, self._secs(2))], ceiling=10
        )
        kept_file_ids = {c["source_file_id"] for c in kept}
        self.assertIn("small", kept_file_ids, "the small file must retain at least one kept chunk")
        small_kept = [c for c in kept if c["source_file_id"] == "small"]
        self.assertGreaterEqual(len(small_kept), 1)

    def test_bigger_file_gets_proportionally_more_of_the_remaining_budget(self):
        big = {"file_id": "big", "filename": "Big.txt"}
        small = {"file_id": "small", "filename": "Small.txt"}
        kept, _ = analyst._allocate_package_chunk_budget(
            [(big, self._secs(50)), (small, self._secs(2))], ceiling=10
        )
        big_count = sum(1 for c in kept if c["source_file_id"] == "big")
        small_count = sum(1 for c in kept if c["source_file_id"] == "small")
        self.assertGreater(big_count, small_count)
        self.assertEqual(big_count + small_count, 10)

    def test_more_files_than_ceiling_still_bounded_and_representative(self):
        files = [({"file_id": f"f{i}", "filename": f"F{i}.txt"}, self._secs(3)) for i in range(15)]
        kept, skipped = analyst._allocate_package_chunk_budget(files, ceiling=10)
        self.assertEqual(len(kept), 10)
        self.assertTrue(skipped)

    def test_package_wide_index_and_total_are_contiguous(self):
        f1, f2 = {"file_id": "f1", "filename": "A.txt"}, {"file_id": "f2", "filename": "B.txt"}
        kept, _ = analyst._allocate_package_chunk_budget([(f1, self._secs(2)), (f2, self._secs(2))], ceiling=10)
        self.assertEqual([c["index"] for c in kept], list(range(len(kept))))
        self.assertTrue(all(c["total"] == len(kept) for c in kept))


class TestPackageAlignmentAudit(unittest.TestCase):
    def _pf(self, file_id, filename, text, file_type="txt", extraction_meta=None):
        return {
            "file_id": file_id, "filename": filename, "package_path": filename, "file_type": file_type,
            "text": text, "analyzable": True, "unusable_reason": None,
            "extraction_meta": extraction_meta or {},
        }

    def test_requirement_absent_from_primary_but_present_in_schedule_is_not_not_addressed(self):
        primary = self._pf("p1", "Technical Proposal.txt", "General methodology narrative with no pricing detail. " * 50)
        schedule = self._pf("s1", "Schedule C - Pricing.txt", "PRICING_MARKER: our fixed price is $500,000 as required.")
        fake_call = _fake_call_factory({
            "PRICING_MARKER": {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "fixed price is $500,000"},
        })
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[primary, schedule],
                requirements=[_req("R1", description="Provide firm fixed pricing")],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        self.assertEqual(result["status"], "complete")
        row = next(r for r in result["requirement_coverage"] if r["req_id"] == "R1")
        self.assertEqual(row["coverage"], "Fully Addressed")

    def test_evidence_location_includes_source_filename(self):
        schedule = self._pf("s1", "Schedule C - Pricing.txt", "PRICING_MARKER: fixed price detail here.")
        fake_call = _fake_call_factory({
            "PRICING_MARKER": {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "fixed price detail"},
        })
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[schedule], requirements=[_req("R1")],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        row = next(r for r in result["requirement_coverage"] if r["req_id"] == "R1")
        self.assertIn("Schedule C - Pricing.txt", row["evidence_location"])

    def test_xlsx_sheet_provenance_in_evidence_location(self):
        xlsx = _xlsx_bytes({"Professional Fees": [["SHEET_MARKER", "Row of fee data for the audit"]]})
        text, meta = extractor.extract_document_with_metadata(xlsx, "Rates.xlsx")
        pf = self._pf("x1", "Rates.xlsx", text, file_type="xlsx", extraction_meta=meta)
        fake_call = _fake_call_factory({
            "SHEET_MARKER": {"req_id": "R1", "coverage": "Fully Addressed", "confidence": "High", "evidence": "fee data present"},
        })
        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[pf], requirements=[_req("R1")],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        row = next(r for r in result["requirement_coverage"] if r["req_id"] == "R1")
        self.assertIn("Rates.xlsx", row["evidence_location"])
        self.assertIn("Sheet: Professional Fees", row["evidence_location"])

    def test_included_failed_substantive_file_makes_audit_incomplete(self):
        good = self._pf("g1", "Technical Proposal.txt", "Solid methodology narrative. " * 30)
        failed = {
            "file_id": "f1", "filename": "Corrupt.xlsx", "package_path": "Corrupt.xlsx", "file_type": "xlsx",
            "text": "", "analyzable": False, "unusable_reason": "unreadable spreadsheet", "extraction_meta": {},
        }
        with patch("analyst._call", side_effect=lambda system, user, max_tokens=2048, **kwargs: (_chunk_response() if "requirement_assertions" in user else _synthesis_response())):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[good, failed], requirements=[_req("R1")],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result.get("overall_score"))
        self.assertIn("Corrupt.xlsx", result["reason"])

    def test_excluded_unsupported_file_does_not_make_audit_incomplete(self):
        """The caller (stage_check.py) never passes an excluded file into
        package_files at all -- proving the analyzer only ever sees what
        was actually included, so exclusion alone is sufficient to keep
        an otherwise-complete audit complete."""
        good = self._pf("g1", "Technical Proposal.txt", "Solid methodology narrative. " * 30)
        with patch("analyst._call", side_effect=lambda system, user, max_tokens=2048, **kwargs: (_chunk_response() if "requirement_assertions" in user else _synthesis_response())):
            result = analyst.analyze_proposal_alignment_package(
                package_files=[good],  # the unsupported .pptx was excluded by the caller, never passed
                requirements=[], rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        self.assertEqual(result["status"], "complete")

    def test_package_bounding_does_not_omit_all_content_of_a_small_included_file(self):
        """A package with many files, forcing sampling, must still give
        every included file at least one analyzed chunk (via the fair
        allocator) -- and because sampling occurred, status must be
        incomplete, never a silently degraded score."""
        big_files = [self._pf(f"big{i}", f"Big{i}.txt", ("Filler content sentence. " * 400) + f"BIGMARK{i}") for i in range(20)]
        small = self._pf("small1", "Small.txt", "SMALLMARK_UNIQUE: tiny file content.")
        seen_prompts = []

        def fake_call(system, user, max_tokens=2048, **kwargs):
            seen_prompts.append(user)
            if "requirement_assertions" in user:
                return _chunk_response()
            return _synthesis_response()

        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=big_files + [small], requirements=[],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        self.assertTrue(any("SMALLMARK_UNIQUE" in p for p in seen_prompts),
                         "the small file's only chunk must still reach a prompt even under package-wide sampling")
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result.get("overall_score"))
        self.assertTrue(result["coverage_metadata"]["sampled"])
        # Every file received at least one analyzed chunk in this case
        # (fair per-file guarantee), so nothing is explicitly "skipped".
        self.assertEqual(result["coverage_metadata"]["skipped_files"], [])

    def test_pathological_more_files_than_ceiling_exposes_skipped_file_names(self):
        """Pre-commit hardening item 4: when the number of analyzable
        files itself exceeds the 24-chunk ceiling (the pathological
        branch of _allocate_package_chunk_budget), some included files
        get ZERO analyzed chunks. The audit must go incomplete with no
        score, AND the specific skipped filenames must be explicitly
        named in coverage_metadata -- never left for the user to infer."""
        files = [self._pf(f"f{i}", f"File{i}.txt", f"UNIQUE_MARK_{i}: tiny single-section content.") for i in range(30)]

        def fake_call(system, user, max_tokens=2048, **kwargs):
            if "requirement_assertions" in user:
                return _chunk_response()
            return _synthesis_response()

        with patch("analyst._call", side_effect=fake_call):
            result = analyst.analyze_proposal_alignment_package(
                package_files=files, requirements=[],
                rfp_text="context", bid_info={"title": "T", "client": "C"},
            )
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result.get("overall_score"))
        self.assertIsNone(result.get("score_basis"))

        skipped_files = result["coverage_metadata"]["skipped_files"]
        self.assertEqual(len(skipped_files), 30 - analyst._ALIGN_MAX_CHUNKS)
        skipped_names = {f["filename"] for f in skipped_files}
        self.assertTrue(all(name.startswith("File") for name in skipped_names))
        # Every skipped file must also be named in the human-readable
        # incomplete-audit reason string (UI/PDF both render this today).
        for name in skipped_names:
            self.assertIn(name, result["reason"])

    def test_zero_llm_calls_are_never_made_for_duplicate_content(self):
        """Package assembly-level dedup means analyst never even sees
        the duplicate's text -- there is nothing further to assert about
        analyst here beyond confirming a duplicate carries no text for
        the caller to pass in (extractor-level proof, re-affirmed for
        the package-audit boundary)."""
        content = b"Same schedule content."
        pkg = extractor.build_alignment_submission_package([("A.txt", content), ("B.txt", content)])
        dup = next(f for f in pkg["files"] if f["lifecycle_status"] == "duplicate")
        self.assertEqual(dup["text"], "")
        self.assertFalse(dup["analyzable"])


class TestPdfPackageManifest(unittest.TestCase):
    def _pdf_text(self, pdf_bytes):
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return "\n".join(page.get_text() for page in doc)

    def _align_result(self):
        return {
            "status": "complete", "overall_score": 80.0, "score_basis": "Buyer-weighted evaluation criteria",
            "score_rationale": "80/100.", "recommendation": "REVISE BEFORE SUBMITTING",
            "executive_summary": "Solid overall.", "strengths": [], "findings": [],
            "mandatory_failures": [],
            "requirement_coverage": [{"req_id": "R1", "category": "Rated", "coverage": "Fully Addressed",
                                       "confidence": "High", "evidence_location": "Schedule C.xlsx — Sheet: Fees",
                                       "notes": "covered"}],
            "next_steps": [],
            "coverage_metadata": {"chars_total": 1000, "chars_processed": 1000, "percentage_covered": 100.0,
                                   "chunk_count": 1, "successful_chunks": 1, "failed_or_skipped_chunks": 0,
                                   "files": [{"file_id": "f1", "filename": "Schedule C.xlsx", "chars_processed": 1000,
                                              "chunk_count": 1, "analyzable": True, "unusable_reason": None}]},
        }

    def _manifest(self):
        return [
            {"file_id": "f1", "filename": "Schedule C.xlsx", "package_path": "Schedule C.xlsx", "file_type": "xlsx",
             "lifecycle_status": "extracted", "duplicate_of_file_id": None, "char_count": 1000,
             "analyzable": True, "unusable_reason": None, "included": True, "role": "primary"},
            {"file_id": "f2", "filename": "Deck.pptx", "package_path": "Deck.pptx", "file_type": "pptx",
             "lifecycle_status": "unsupported", "duplicate_of_file_id": None, "char_count": 0,
             "analyzable": False, "unusable_reason": "PPTX is unsupported in this version.",
             "included": True, "role": None},
        ]

    def test_manifest_renders_in_pdf_with_filenames_and_statuses(self):
        pdf_bytes = pdf_alignment.generate_alignment_audit_pdf(
            {"client": "Test Client", "title": "Test Opp"}, self._align_result(),
            proposal_filename="Schedule C.xlsx", package_manifest=self._manifest(),
        )
        text = self._pdf_text(pdf_bytes)
        self.assertIn("SUBMISSION PACKAGE MANIFEST", text)
        self.assertIn("Schedule C.xlsx", text)
        self.assertIn("Deck.pptx", text)
        self.assertIn("Unsupported", text)

    def test_filename_qualified_evidence_location_appears_in_coverage_table(self):
        pdf_bytes = pdf_alignment.generate_alignment_audit_pdf(
            {"client": "Test Client", "title": "Test Opp"}, self._align_result(),
            package_manifest=self._manifest(),
        )
        text = " ".join(self._pdf_text(pdf_bytes).split())
        self.assertIn("Schedule C.xlsx", text)

    def test_no_manifest_when_package_manifest_omitted_backward_compatible(self):
        pdf_bytes = pdf_alignment.generate_alignment_audit_pdf(
            {"client": "Test Client", "title": "Test Opp"}, self._align_result(),
        )
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        text = self._pdf_text(pdf_bytes)
        self.assertNotIn("SUBMISSION PACKAGE MANIFEST", text)

    @patch("anthropic.Anthropic")
    def test_report_generation_still_makes_zero_llm_calls_with_manifest(self, mock_anthropic_cls):
        pdf_alignment.generate_alignment_audit_pdf(
            {"client": "Test Client", "title": "Test Opp"}, self._align_result(),
            package_manifest=self._manifest(),
        )
        mock_anthropic_cls.assert_not_called()

    def test_generated_at_timestamp_includes_time_not_just_date(self):
        """Pre-commit hardening item 3: the report must show a full
        generated-AT timestamp (date + time), not only a date."""
        import re
        pdf_bytes = pdf_alignment.generate_alignment_audit_pdf(
            {"client": "Test Client", "title": "Test Opp"}, self._align_result(),
        )
        text = self._pdf_text(pdf_bytes)
        self.assertIn("Report generated:", text)
        # Time-of-day component, e.g. "at 02:47 PM" -- proves this is a
        # real timestamp, not a re-rendering of cover_header()'s existing
        # date-only "Generated <date>" line.
        self.assertIsNotNone(
            re.search(r"Report generated:.*\bat\s+\d{1,2}:\d{2}\s*(AM|PM)\b", text),
            f"no time-of-day found alongside the date in: {text!r}",
        )

    def test_skipped_file_is_explicitly_labelled_in_pdf_manifest(self):
        """Pre-commit hardening item 4: a file the package ceiling gave
        zero analyzed chunks to must be labelled explicitly in the PDF
        manifest (never left to be inferred from a '0 sections' count)."""
        align_result = self._align_result()
        align_result["status"] = "incomplete"
        align_result["overall_score"] = None
        align_result["coverage_metadata"]["coverage_complete"] = False
        align_result["coverage_metadata"]["skipped_files"] = [{"file_id": "f2", "filename": "Deck.pptx"}]
        manifest = self._manifest()
        # Make the "skipped" file a real, analyzable-but-unlucky file
        # rather than the fixture's unsupported pptx, so the SKIPPED
        # label is being tested independently of the unsupported label.
        manifest[1] = {"file_id": "f2", "filename": "Team CVs.pdf", "package_path": "Team CVs.pdf",
                        "file_type": "pdf", "lifecycle_status": "extracted", "duplicate_of_file_id": None,
                        "char_count": 5000, "analyzable": True, "unusable_reason": None,
                        "included": True, "role": None}
        align_result["coverage_metadata"]["skipped_files"] = [{"file_id": "f2", "filename": "Team CVs.pdf"}]

        pdf_bytes = pdf_alignment.generate_alignment_audit_pdf(
            {"client": "Test Client", "title": "Test Opp"}, align_result, package_manifest=manifest,
        )
        text = self._pdf_text(pdf_bytes)
        self.assertIn("Team CVs.pdf", text)
        self.assertIn("Skipped", text)
        self.assertIn("package-wide chunk ceiling", text)


_FAKE_USER_ID = "00000000-0000-0000-0000-000000000003"
_FAKE_ORG_ID = "00000000-0000-0000-0000-000000000004"


def _fake_authenticated_session_state():
    import streamlit as st
    st.session_state["bi_auth_session"] = {
        "access_token": "test-submission-package-token",
        "refresh_token": "test-submission-package-refresh",
        "user_id": _FAKE_USER_ID,
        "email": "submission-package-test@example.com",
        "expires_at": time.time() + 3600,
    }
    from tenancy import AuthContext
    st.session_state["bi_auth_context"] = AuthContext(
        user_id=_FAKE_USER_ID, email="submission-package-test@example.com",
        organization_id=_FAKE_ORG_ID, organization_name="Submission Package Test Org", role="owner",
    )


_fake_authenticated_session_state()

with patch(
    "tenancy.auth_client.get_authenticated_client",
    return_value=MagicMock(**{
        "table.return_value.select.return_value.order.return_value.execute.return_value": MagicMock(data=[]),
        "table.return_value.select.return_value.eq.return_value.execute.return_value": MagicMock(data=[]),
    }),
):
    import app as _app
    import pages.stage_check as stage_check


class TestSessionIsolation(unittest.TestCase):
    """Uses deliberately unusual, high-numbered bid_ids (90101, 90202,
    90303) rather than 1/2/3 -- st.session_state is process-global across
    this whole pytest run, and tests/test_proposal_alignment_analyzer.py's
    TestStageCheckRendering hardcodes page_check(1). Small integer bid_ids
    here previously leaked a stale align_package_1 into that other test
    file (whichever ran second), so isolation tests must not themselves
    collide with another file's fixed bid_id. Belt-and-suspenders: also
    tears down every align_-prefixed key after each test regardless of
    pass/fail."""

    _BID_A, _BID_B, _BID_MISSING = 90101, 90202, 90303

    def _sweep_align_keys(self):
        import streamlit as st
        for key in list(st.session_state.keys()):
            if key.startswith(("align_package_", "align_result_", "align_inc_", "align_primary_")):
                st.session_state.pop(key, None)

    def setUp(self):
        self._sweep_align_keys()

    def tearDown(self):
        self._sweep_align_keys()

    def test_bid_scoped_keys_do_not_leak_between_bids(self):
        import streamlit as st
        st.session_state[stage_check._align_result_key(self._BID_A)] = {"status": "complete", "overall_score": 90.0}
        st.session_state[stage_check._align_result_key(self._BID_B)] = {"status": "incomplete", "overall_score": None}
        self.assertNotEqual(
            st.session_state[stage_check._align_result_key(self._BID_A)],
            st.session_state[stage_check._align_result_key(self._BID_B)],
        )
        self.assertIsNone(st.session_state.get(stage_check._align_result_key(self._BID_MISSING)))

    def test_package_state_is_bid_scoped(self):
        import streamlit as st
        pkg_a = {"files": [{"file_id": "a", "filename": "A.txt"}], "primary_file_id": "a"}
        pkg_b = {"files": [{"file_id": "b", "filename": "B.txt"}], "primary_file_id": "b"}
        st.session_state[stage_check._align_package_key(self._BID_A)] = pkg_a
        st.session_state[stage_check._align_package_key(self._BID_B)] = pkg_b
        self.assertEqual(st.session_state[stage_check._align_package_key(self._BID_A)]["primary_file_id"], "a")
        self.assertEqual(st.session_state[stage_check._align_package_key(self._BID_B)]["primary_file_id"], "b")

    def test_logout_clears_all_bid_scoped_alignment_state(self):
        import streamlit as st
        st.session_state[stage_check._align_package_key(self._BID_A)] = {"files": []}
        st.session_state[stage_check._align_result_key(self._BID_A)] = {"status": "complete"}
        st.session_state[stage_check._align_result_snapshot_key(self._BID_A)] = {"files": []}
        st.session_state[stage_check._align_package_key(self._BID_B)] = {"files": []}
        st.session_state[stage_check._align_result_key(self._BID_B)] = {"status": "incomplete"}
        st.session_state[f"align_inc_{self._BID_A}_abcd1234"] = True
        st.session_state[f"align_primary_{self._BID_A}"] = "abcd1234"

        with patch("app._auth_session.sign_out"):
            _app._clear_all_user_scoped_state()

        for key in list(st.session_state.keys()):
            self.assertFalse(
                key.startswith(("align_package_", "align_result_", "align_inc_", "align_primary_")),
                f"logout must clear every Alignment session-state key, found surviving: {key}",
            )


if __name__ == "__main__":
    unittest.main()
