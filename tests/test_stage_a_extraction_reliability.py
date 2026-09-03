"""
tests/test_stage_a_extraction_reliability.py

Comprehensive tests for Stage A extraction reliability:
Part 1 (A-O): Pure / deterministic unit tests:
  A. deterministic chunk boundaries (same text produces identical chunks)
  B. marker preservation (every chunk retains relevant source marker)
  C. page-boundary chunking (multi-page PDF marker text divided without losing page attribution)
  D. DOCX section/table marker chunking (preserves source structure)
  E. deterministic aggregation (same chunk outputs produce byte-equivalent aggregation)
  F. duplicate material fact collapse (two materially identical facts with same provenance collapse)
  G. same req_id, different requirement text (must NOT collapse)
  H. same requirement text, different physical source_refs (preserves provenance correctly)
  I. metadata merge (non-null metadata retained conservatively; contradictions not invented)
  J. coverage guard — requirements (strong mandatory language + zero reqs => suspicious)
  K. coverage guard — evaluation (evaluation/weight language + zero criteria => suspicious)
  L. coverage guard — dates (deadline/timescale language + zero dates => suspicious)
  M. benign document (short document with no procurement signals not falsely flagged)
  N. retry bound (coverage recovery cannot recurse or retry indefinitely)
  O. null/malformed chunk output (fails safely without fabricating facts)

Part 2: Mocked Stage A Orchestration tests:
  - Multi-chunk extraction across families
  - Controlled recovery from suspiciously empty output
"""
import unittest
import json
from unittest.mock import MagicMock, patch

from extractor import (
    chunk_document_text,
    aggregate_stage_a_facts,
    inspect_stage_a_coverage,
    extract_document_facts,
    _extract_chunk_facts,
    _STAGE_A_MAX_CHUNK_CHARS,
)


class TestStageAChunkingAndAggregation(unittest.TestCase):
    """Part 1: Pure / deterministic Stage A tests A through O."""

    def test_A_deterministic_chunk_boundaries(self):
        """Same text twice produces identical chunks."""
        text = "\n".join([
            f"[[SOURCE: tender.pdf | PAGE: {i}]]\nPage {i} content text with multiple paragraphs."
            for i in range(1, 100)
        ])
        chunks1 = chunk_document_text(text, max_chunk_chars=2000)
        chunks2 = chunk_document_text(text, max_chunk_chars=2000)
        self.assertEqual(len(chunks1), len(chunks2))
        self.assertEqual(chunks1, chunks2)

    def test_B_marker_preservation(self):
        """Every chunk retains relevant source marker(s)."""
        text = "\n".join([
            f"[[SOURCE: tender.pdf | PAGE: {i}]]\nPage {i} content text."
            for i in range(1, 20)
        ])
        chunks = chunk_document_text(text, max_chunk_chars=150)
        self.assertGreater(len(chunks), 1)
        for idx, ch in enumerate(chunks):
            self.assertIn("[[SOURCE:", ch, f"Chunk {idx+1} must contain a source marker")

    def test_C_page_boundary_chunking(self):
        """Multi-page PDF-style marker text is divided without losing page attribution."""
        p1 = "[[SOURCE: doc.pdf | PAGE: 1]]\nContent of first page."
        p2 = "[[SOURCE: doc.pdf | PAGE: 2]]\nContent of second page."
        p3 = "[[SOURCE: doc.pdf | PAGE: 3]]\nContent of third page."
        text = f"{p1}\n{p2}\n{p3}"
        chunks = chunk_document_text(text, max_chunk_chars=60)
        self.assertGreater(len(chunks), 1)
        for ch in chunks:
            self.assertTrue(ch.startswith("[[SOURCE: doc.pdf | PAGE:"))

    def test_D_docx_section_table_marker_chunking(self):
        """Long section/table input preserves source structure."""
        text = (
            "[[SOURCE: spec.docx | SECTION: Header]]\nIntroduction\n"
            "[[SOURCE: spec.docx | SECTION: Part 1]]\n" + ("Text " * 200) + "\n"
            "[[SOURCE: spec.docx | TABLE]] Row 1 | Val 1\n"
            "[[SOURCE: spec.docx | SECTION: Part 2]]\n" + ("More text " * 200) + "\n"
            "[[SOURCE: spec.docx | TABLE]] Row 2 | Val 2"
        )
        chunks = chunk_document_text(text, max_chunk_chars=500)
        self.assertGreater(len(chunks), 1)
        for ch in chunks:
            self.assertIn("[[SOURCE: spec.docx", ch)

    def test_D2_hard_chunk_size_guarantee_single_oversized_line(self):
        """One source marker + one 40,000-char single line with max_chunk_chars=16,000."""
        marker = "[[SOURCE: spec.pdf | PAGE: 1]]\n"
        single_line = "B" * 40000
        text = marker + single_line
        chunks = chunk_document_text(text, max_chunk_chars=16000)

        # Every resulting chunk <= 16,000
        for idx, ch in enumerate(chunks):
            self.assertLessEqual(len(ch), 16000, f"Chunk {idx+1} length {len(ch)} exceeds 16,000")
            self.assertIn("[[SOURCE: spec.pdf | PAGE: 1]]", ch, f"Chunk {idx+1} missing inherited source marker")

        # Substantive content is lossless
        recovered_parts = []
        for ch in chunks:
            lines = ch.splitlines(keepends=True)
            body = [l for l in lines if not l.startswith("[[SOURCE:")]
            recovered_parts.append("".join(body))
        recovered_content = "".join(recovered_parts)
        self.assertEqual(len(recovered_content), 40000)
        self.assertEqual(recovered_content, single_line)

    def test_E_deterministic_aggregation(self):
        """Same chunk outputs in same order produce byte-equivalent normalized document aggregation."""
        chunk1 = {
            "doc_metadata": {"title": "Tender Alpha", "client": "Buyer 1"},
            "requirements": [{"req_id": "M1", "category": "Mandatory", "description": "Req Alpha", "source_refs": []}],
            "dates": [{"milestone": "Deadline", "date": "2026-10-01"}],
        }
        chunk2 = {
            "doc_metadata": {"file_number": "SOL-101"},
            "requirements": [{"req_id": "R1", "category": "Rated", "description": "Req Beta", "source_refs": []}],
            "dates": [{"milestone": "Award", "date": "2026-11-01"}],
        }
        res1 = aggregate_stage_a_facts([chunk1, chunk2], "file.pdf")
        res2 = aggregate_stage_a_facts([chunk1, chunk2], "file.pdf")
        self.assertEqual(json.dumps(res1, sort_keys=True), json.dumps(res2, sort_keys=True))

    def test_F_duplicate_material_fact_collapse(self):
        """Two materially identical facts with same provenance collapse."""
        fact1 = {
            "requirements": [{
                "req_id": "M1",
                "category": "Mandatory",
                "description": "Supplier must provide 3 references",
                "rfso_ref": "Section 4.1",
                "source_refs": [{"source_doc": "doc.pdf", "page": 4, "excerpt": "provide 3 references"}]
            }]
        }
        fact2 = {
            "requirements": [{
                "req_id": "M1",
                "category": "Mandatory",
                "description": "Supplier must provide 3 references",
                "rfso_ref": "Section 4.1",
                "source_refs": [{"source_doc": "doc.pdf", "page": 4, "excerpt": "provide 3 references"}]
            }]
        }
        merged = aggregate_stage_a_facts([fact1, fact2], "doc.pdf")
        self.assertEqual(len(merged["requirements"]), 1)
        self.assertEqual(len(merged["requirements"][0]["source_refs"]), 1)

    def test_G_same_req_id_different_requirement_text(self):
        """Two requirements with same req_id but different text must NOT collapse."""
        chunk1 = {
            "requirements": [{
                "req_id": "M1",
                "category": "Mandatory",
                "description": "Must possess ISO 9001 certification",
                "rfso_ref": "Section 2",
                "source_refs": [{"source_doc": "doc.pdf", "page": 2, "excerpt": "ISO 9001"}]
            }]
        }
        chunk2 = {
            "requirements": [{
                "req_id": "M1",
                "category": "Mandatory",
                "description": "Must possess 5 years corporate experience",
                "rfso_ref": "Section 3",
                "source_refs": [{"source_doc": "doc.pdf", "page": 5, "excerpt": "5 years corporate"}]
            }]
        }
        merged = aggregate_stage_a_facts([chunk1, chunk2], "doc.pdf")
        self.assertEqual(len(merged["requirements"]), 2, "Must preserve both distinct requirements despite duplicate req_id M1")

    def test_G2_long_common_prefix_different_suffix(self):
        """Two requirements with identical >80 char normalized prefix but different text afterward must NOT collapse."""
        prefix = "The contractor and all dedicated personnel shall strictly comply with quality management system standards under ISO 9001 and ensure that all documentation is audited annually by an accredited registrar "
        self.assertGreater(len(prefix), 80)
        chunk1 = {
            "requirements": [{
                "req_id": "M1",
                "category": "Mandatory",
                "rfso_ref": "Section 4.1",
                "description": prefix + "specifically covering hardware assembly processes.",
                "source_refs": [{"source_doc": "doc.pdf", "page": 4, "excerpt": "assembly"}]
            }]
        }
        chunk2 = {
            "requirements": [{
                "req_id": "M1",
                "category": "Mandatory",
                "rfso_ref": "Section 4.1",
                "description": prefix + "specifically covering software testing and quality control.",
                "source_refs": [{"source_doc": "doc.pdf", "page": 8, "excerpt": "software"}]
            }]
        }
        merged = aggregate_stage_a_facts([chunk1, chunk2], "doc.pdf")
        self.assertEqual(len(merged["requirements"]), 2, "Both requirements sharing >80 char prefix must survive aggregation")

    def test_H_same_requirement_text_different_physical_source_refs(self):
        """Same requirement text with different physical source_refs preserves provenance correctly."""
        chunk1 = {
            "requirements": [{
                "req_id": "M1",
                "category": "Mandatory",
                "description": "Must possess ISO 9001 certification",
                "rfso_ref": "Section 2",
                "source_refs": [{"source_doc": "doc.pdf", "page": 2, "excerpt": "ISO 9001"}]
            }]
        }
        chunk2 = {
            "requirements": [{
                "req_id": "M1",
                "category": "Mandatory",
                "description": "Must possess ISO 9001 certification",
                "rfso_ref": "Section 2",
                "source_refs": [{"source_doc": "doc.pdf", "page": 15, "excerpt": "ISO 9001 verification"}]
            }]
        }
        merged = aggregate_stage_a_facts([chunk1, chunk2], "doc.pdf")
        self.assertEqual(len(merged["requirements"]), 1)
        refs = merged["requirements"][0]["source_refs"]
        self.assertEqual(len(refs), 2)
        pages = {r.get("page") for r in refs}
        self.assertEqual(pages, {2, 15})

    def test_I_metadata_merge(self):
        """Non-null metadata is retained conservatively; contradictory values are not invented/resolved."""
        chunk1 = {"doc_metadata": {"title": "Primary RFP", "client": "Ministry of Transport", "file_number": None}}
        chunk2 = {"doc_metadata": {"title": "Annex A", "client": None, "file_number": "MOT-2026-99"}}
        merged = aggregate_stage_a_facts([chunk1, chunk2], "doc.pdf")
        meta = merged["doc_metadata"]
        self.assertEqual(meta["title"], "Primary RFP")
        self.assertEqual(meta["client"], "Ministry of Transport")
        self.assertEqual(meta["file_number"], "MOT-2026-99")

    def test_J_coverage_guard_requirements(self):
        """Strong mandatory language + zero requirements => suspicious."""
        text = (
            "The supplier shall provide all materials. The contractor must be certified.\n"
            "It is mandatory that all equipment complies. All staff required to hold degrees.\n"
            "As a condition of participation, supplier will present accounts. Tenderer shall submit bonds."
        )
        empty_facts = {"requirements": [], "dates": [], "evaluation_criteria": [], "submission_rules": []}
        res = inspect_stage_a_coverage(text, empty_facts, min_signal_count=5)
        self.assertTrue(res["is_suspicious"])
        self.assertIn("requirements", res["suspicious_families"])

    def test_K_coverage_guard_evaluation(self):
        """Evaluation/weight language + zero criteria => suspicious."""
        text = (
            "Technical evaluation will be weighted at 60% with scoring threshold of 70%.\n"
            "Award criteria include quality marks of 40% and price weighting of 40%.\n"
            "Overall evaluation scoring is cumulative."
        )
        empty_facts = {"requirements": [{"req_id": "M1"}], "dates": [], "evaluation_criteria": [], "submission_rules": []}
        res = inspect_stage_a_coverage(text, empty_facts, min_signal_count=5)
        self.assertTrue(res["is_suspicious"])
        self.assertIn("evaluation_criteria", res["suspicious_families"])

    def test_L_coverage_guard_dates(self):
        """Deadline/timescale language + zero dates => suspicious."""
        text = (
            "The deadline for clarification questions is firm. Response deadline is final.\n"
            "Please observe the timescales outlined. The closing date will not be extended.\n"
            "Mandatory site visit will take place per timescale."
        )
        empty_facts = {"requirements": [{"req_id": "M1"}], "dates": [], "evaluation_criteria": [], "submission_rules": []}
        res = inspect_stage_a_coverage(text, empty_facts, min_signal_count=5)
        self.assertTrue(res["is_suspicious"])
        self.assertIn("dates", res["suspicious_families"])

    def test_M_benign_document(self):
        """A short document with no procurement signals and empty facts must not be falsely flagged."""
        text = "This document is blank or contains general background context about the project history."
        empty_facts = {"requirements": [], "dates": [], "evaluation_criteria": [], "submission_rules": []}
        res = inspect_stage_a_coverage(text, empty_facts, min_signal_count=5)
        self.assertFalse(res["is_suspicious"])
        self.assertEqual(res["suspicious_families"], [])

    def test_N_retry_bound(self):
        """Coverage recovery cannot recurse or retry indefinitely."""
        text = (
            "Supplier shall deliver. Contractor must deliver. It is mandatory. "
            "Supplier will comply. Tenderer shall submit. Required condition."
        )
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text='{"requirements": []}')]
        mock_client.messages.create.return_value = mock_resp

        with patch("extractor.get_anthropic_client", return_value=mock_client):
            facts = extract_document_facts(text, "test.pdf", "test_key")

        self.assertIn("_extraction_diagnostic", facts)
        diag = facts["_extraction_diagnostic"]
        self.assertEqual(diag["status"], "SUSPICIOUS_UNDER_COVERAGE")
        self.assertLessEqual(diag["recovery_attempts"], 2)

    def test_O_null_malformed_chunk_output(self):
        """Fails safely with a clear error/diagnostic and does not fabricate facts."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="INVALID NON-JSON OUTPUT")]
        mock_client.messages.create.return_value = mock_resp

        with patch("extractor.get_anthropic_client", return_value=mock_client):
            facts = extract_document_facts("Some text", "test.pdf", "test_key")

        self.assertIsInstance(facts, dict)
        self.assertEqual(facts.get("requirements"), [])
        self.assertEqual(facts.get("dates"), [])
        self.assertEqual(facts.get("evaluation_criteria"), [])
        self.assertEqual(facts.get("submission_rules"), [])


class TestMockedStageAOrchestration(unittest.TestCase):
    """Part 2: Mocked Model Stage A Orchestration tests."""

    def test_multi_chunk_extraction_across_families(self):
        """Chunk 1 returns requirements, Chunk 2 returns dates, Chunk 3 returns evaluation criteria."""
        page1 = "[[SOURCE: doc.pdf | PAGE: 1]]\n" + ("Section 1 text. " * 300)
        page2 = "[[SOURCE: doc.pdf | PAGE: 2]]\n" + ("Section 2 text. " * 300)
        page3 = "[[SOURCE: doc.pdf | PAGE: 3]]\n" + ("Section 3 text. " * 300)
        full_text = f"{page1}\n{page2}\n{page3}"

        mock_client = MagicMock()

        def side_effect(*args, **kwargs):
            content_str = kwargs["messages"][0]["content"][0]["text"]
            resp = MagicMock()
            if "PAGE: 1" in content_str:
                data = {"requirements": [{"req_id": "M1", "category": "Mandatory", "description": "Req from chunk 1"}]}
            elif "PAGE: 2" in content_str:
                data = {"dates": [{"milestone": "Closing Date", "date": "2026-10-31"}]}
            elif "PAGE: 3" in content_str:
                data = {"evaluation_criteria": [{"stage": "Technical", "weight": "70%"}]}
            else:
                data = {}
            resp.content = [MagicMock(text=json.dumps(data))]
            return resp

        mock_client.messages.create.side_effect = side_effect

        with patch("extractor.get_anthropic_client", return_value=mock_client), \
             patch("extractor._STAGE_A_MAX_CHUNK_CHARS", 3000):
            facts = extract_document_facts(full_text, "doc.pdf", "test_key")

        self.assertEqual(len(facts["requirements"]), 1)
        self.assertEqual(facts["requirements"][0]["description"], "Req from chunk 1")
        self.assertEqual(len(facts["dates"]), 1)
        self.assertEqual(facts["dates"][0]["date"], "2026-10-31")
        self.assertEqual(len(facts["evaluation_criteria"]), 1)
        self.assertEqual(facts["evaluation_criteria"][0]["weight"], "70%")

    def test_controlled_recovery_from_suspiciously_empty_output(self):
        """First extraction returns suspiciously empty output; controlled recovery returns valid facts."""
        text = (
            "[[SOURCE: doc.pdf | PAGE: 1]]\n"
            "The contractor shall deliver goods. All suppliers must be registered.\n"
            "It is mandatory that documentation is verified. Tenderer shall submit bond.\n"
            "Supplier will guarantee delivery. Condition of participation requires compliance.\n"
            + ("Additional text content. " * 600)
        )

        call_count = [0]
        mock_client = MagicMock()

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            if call_count[0] == 1:
                resp.content = [MagicMock(text='{"requirements": []}')]
            else:
                data = {"requirements": [{"req_id": "M1", "category": "Mandatory", "description": "Contractor shall deliver goods"}]}
                resp.content = [MagicMock(text=json.dumps(data))]
            return resp

        mock_client.messages.create.side_effect = side_effect

        with patch("extractor.get_anthropic_client", return_value=mock_client):
            facts = extract_document_facts(text, "doc.pdf", "test_key")

        self.assertGreaterEqual(call_count[0], 2, "Must trigger controlled recovery")
        self.assertEqual(len(facts["requirements"]), 1)
        self.assertEqual(facts["requirements"][0]["description"], "Contractor shall deliver goods")
        self.assertEqual(facts["_extraction_diagnostic"]["status"], "VERIFIED_ADEQUATE")

    def test_controlled_recovery_family_specific_merge(self):
        """Original extraction has 100 reqs but zero dates; dates flagged suspicious; recovery has fewer reqs but valid date."""
        text = (
            "[[SOURCE: doc.pdf | PAGE: 1]]\n"
            "Supplier shall deliver goods. Contractor must follow guidelines.\n"
            "The tender deadline is strict. The closing date is 2026-11-15.\n"
            "Response deadline is firm. Timescale for completion is 6 months.\n"
            "Clarification deadline must be observed per timescale.\n"
            + ("Additional tender content. " * 500)
        )

        call_count = [0]
        mock_client = MagicMock()

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            if call_count[0] == 1:
                # First pass: returns 100 requirements, but 0 dates (dates flagged suspicious)
                reqs = [
                    {"req_id": f"M{i}", "category": "Mandatory", "description": f"Mandatory requirement number {i}"}
                    for i in range(1, 101)
                ]
                data = {"requirements": reqs, "dates": []}
                resp.content = [MagicMock(text=json.dumps(data))]
            else:
                # Recovery pass: returns fewer requirements (e.g. 5) but returns the valid date
                reqs = [
                    {"req_id": f"M{i}", "category": "Mandatory", "description": f"Mandatory requirement number {i}"}
                    for i in range(1, 6)
                ]
                dates = [{"milestone": "Closing Date", "date": "2026-11-15"}]
                data = {"requirements": reqs, "dates": dates}
                resp.content = [MagicMock(text=json.dumps(data))]
            return resp

        mock_client.messages.create.side_effect = side_effect

        with patch("extractor.get_anthropic_client", return_value=mock_client):
            facts = extract_document_facts(text, "doc.pdf", "test_key")

        # Must trigger recovery
        self.assertGreaterEqual(call_count[0], 2, "Must trigger controlled recovery")
        # All 100 original requirements must remain (never discarded)
        self.assertEqual(len(facts["requirements"]), 100, "All original 100 requirements must remain")
        # Recovered date must be present
        self.assertEqual(len(facts["dates"]), 1, "Recovered date must be present in aggregated facts")
        self.assertEqual(facts["dates"][0]["milestone"], "Closing Date")
        self.assertEqual(facts["dates"][0]["date"], "2026-11-15")
        # Date under-coverage resolved
        self.assertEqual(facts["_extraction_diagnostic"]["status"], "VERIFIED_ADEQUATE")



class TestTruncatedExtractionSafetyPass(unittest.TestCase):
    """
    Directive 5 Test Suite (A-F):
    Truncated JSON recovery must not masquerade as complete extraction.
    """

    def test_A_direct_valid_json_reports_complete(self):
        """Direct valid JSON reports COMPLETE parse status."""
        from extractor import _safe_parse_json_with_status
        raw = '{"requirements": [{"req_id": "REQ-1", "description": "Vendor must comply"}]}'
        data, status = _safe_parse_json_with_status(raw)
        self.assertEqual(status, "COMPLETE")
        self.assertEqual(len(data.get("requirements", [])), 1)

    def test_B_stack_repaired_json_reports_recovered_truncated(self):
        """Truncated JSON repaired via balanced stack returns RECOVERED_TRUNCATED."""
        from extractor import _safe_parse_json_with_status
        # Simulated cut-off JSON mid-array
        raw = '{"requirements": [{"req_id": "REQ-1", "description": "Vendor must comply"}, {"req_id": "REQ-2", "description": "Incomplete'
        data, status = _safe_parse_json_with_status(raw)
        self.assertEqual(status, "RECOVERED_TRUNCATED")
        self.assertIn("requirements", data)
        # Stack repair closes the string and object, preserving items up to cut point
        self.assertGreaterEqual(len(data["requirements"]), 1)

    def test_C_backward_compatible_wrapper_returns_dict_only(self):
        """_safe_parse_json returns a dict directly regardless of completion or repair."""
        from extractor import _safe_parse_json
        raw = '{"requirements": [{"req_id": "REQ-1", "description": "Vendor must comply"}]}'
        res = _safe_parse_json(raw)
        self.assertIsInstance(res, dict)
        self.assertEqual(len(res.get("requirements", [])), 1)

    def test_D_successful_retry_yields_verified_adequate(self):
        """When chunk is truncated, bounded retry is triggered; if retry succeeds completely, extraction is VERIFIED_ADEQUATE."""
        mock_client = MagicMock()
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            if call_count[0] == 1:
                # First pass: returns truncated JSON
                raw_truncated = '{"requirements": [{"req_id": "R1", "description": "Req 1"}], "dates": [{"milestone": "M1'
                resp.content = [MagicMock(text=raw_truncated)]
            else:
                # Retry passes: return complete valid JSON
                raw_complete = '{"requirements": [{"req_id": "R1", "description": "Req 1"}], "dates": [{"milestone": "Closing Date", "date": "2026-12-01"}]}'
                resp.content = [MagicMock(text=raw_complete)]
            return resp

        mock_client.messages.create.side_effect = side_effect
        text = "Tender document with closing date 2026-12-01 and requirements. " * 30

        with patch("extractor.get_anthropic_client", return_value=mock_client):
            facts = extract_document_facts(text, "doc.pdf", "test_key")

        self.assertGreaterEqual(call_count[0], 2, "Must have retried the truncated chunk")
        self.assertEqual(facts["_extraction_diagnostic"]["status"], "VERIFIED_ADEQUATE")

    def test_E_unrecovered_truncation_never_masquerades_as_verified_adequate(self):
        """If only recovered partial facts remain after retries, status is RECOVERED_TRUNCATED, never VERIFIED_ADEQUATE."""
        mock_client = MagicMock()

        def side_effect(*args, **kwargs):
            resp = MagicMock()
            # Every call returns truncated JSON that stack-repair can only partially recover
            raw_truncated = '{"requirements": [{"req_id": "R1", "description": "Req 1"}], "dates": [{"milestone": "M1'
            resp.content = [MagicMock(text=raw_truncated)]
            return resp

        mock_client.messages.create.side_effect = side_effect
        text = "Tender content. " * 50

        with patch("extractor.get_anthropic_client", return_value=mock_client):
            facts = extract_document_facts(text, "doc.pdf", "test_key")

        # Recovered partial facts must be preserved
        self.assertGreaterEqual(len(facts.get("requirements", [])), 1)
        # Status MUST be RECOVERED_TRUNCATED (or SUSPICIOUS_UNDER_COVERAGE), NEVER VERIFIED_ADEQUATE
        diag = facts["_extraction_diagnostic"]
        self.assertNotEqual(diag["status"], "VERIFIED_ADEQUATE")
        self.assertTrue(diag.get("has_recovered_truncation"))

    def test_F_coverage_inspection_rejects_verified_adequate_with_recovered_truncation(self):
        """Presence of unrecovered chunk truncation precludes VERIFIED_ADEQUATE in extract_document_facts."""
        mock_client = MagicMock()
        resp = MagicMock()
        resp.content = [MagicMock(text='{"requirements": [{"req_id": "R1", "description": "Vendor must supply"}], "dates": [{"milestone": "M1')]
        mock_client.messages.create.return_value = resp

        # Minimal document with low signals so coverage guard wouldn't flag it solely on signals
        text = "Simple brief statement."
        with patch("extractor.get_anthropic_client", return_value=mock_client):
            facts = extract_document_facts(text, "brief.txt", "test_key")

        self.assertNotEqual(facts["_extraction_diagnostic"]["status"], "VERIFIED_ADEQUATE")

if __name__ == "__main__":
    unittest.main()
