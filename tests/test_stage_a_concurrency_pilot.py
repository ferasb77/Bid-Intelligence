"""
tests/test_stage_a_concurrency_pilot.py

Stage A Optimization Package 4 -- Bounded Document-Level Concurrency.
Deterministic, mocked/delayed-worker tests proving the orchestrator's safety
properties BEFORE any live API call is made. No real model calls anywhere in
this file.

A. max concurrency never exceeds 2
B. one document remains internally serial (extract_fn called exactly once
   per document, as a single atomic unit -- never decomposed by the
   orchestrator itself)
C. recovery order remains unchanged (extract_fn's own call_kind sequence is
   passed through untouched by the orchestrator)
D. output document order remains corpus order even when completion order
   differs (forced via artificial per-document delays)
E. per-document telemetry remains correctly correlated (document_id /
   document_index / per_document_call_index tags are correct, no
   cross-document index collision after merge)
F. exceptions propagate correctly (a failing document's error is captured on
   its own DocumentResult; sibling documents are unaffected and still present)
G. no result is silently dropped (every submitted job appears exactly once
   in the returned, corpus-ordered results)
H. max_tokens remains 8000 (regression pin against extractor's constant)
I. Stage A prompt is unchanged (hash pin)
J. chunk size is unchanged (regression pin against extractor's constant)
"""
import hashlib
import threading
import time
import unittest

from scripts.stage_a_concurrency_orchestrator import (
    DocumentJob, run_concurrent_documents, merge_telemetry_deterministic,
    observed_max_simultaneous_requests,
)
from extractor import _STAGE_A_MAX_OUTPUT_TOKENS, _STAGE_A_MAX_CHUNK_CHARS, STAGE_A_FACT_EXTRACTION_PROMPT


class TestConcurrencyBound(unittest.TestCase):
    def test_A_max_concurrency_never_exceeds_2(self):
        """Force 5 jobs with overlapping artificial delays and confirm the
        observed number of simultaneously-running workers never exceeds 2."""
        active = {"count": 0, "peak": 0}
        lock = threading.Lock()

        def fake_extract(doc_text, filename, api_key, *, telemetry=None):
            with lock:
                active["count"] += 1
                active["peak"] = max(active["peak"], active["count"])
            time.sleep(0.05)
            with lock:
                active["count"] -= 1
            if telemetry is not None:
                telemetry.append({"call_index": 0, "call_kind": "initial", "filename": filename,
                                   "call_started_at": "2026-01-01T00:00:00+00:00",
                                   "call_ended_at": "2026-01-01T00:00:01+00:00",
                                   "latency_seconds": 1.0, "input_tokens": 1, "output_tokens": 1,
                                   "stop_reason": "end_turn", "parse_status": "COMPLETE", "error": None})
            return {"requirements": [], "_extraction_diagnostic": {"status": "VERIFIED_ADEQUATE"}}

        jobs = [DocumentJob(index=i, name=f"doc{i}.pdf", doc_text=f"text{i}") for i in range(5)]
        results, _ = run_concurrent_documents(jobs, fake_extract, "test_key", max_document_concurrency=2)
        self.assertEqual(len(results), 5)
        self.assertLessEqual(active["peak"], 2)
        self.assertGreaterEqual(active["peak"], 2)  # confirm concurrency actually happened, not accidentally serial


class TestDocumentInternalSerialism(unittest.TestCase):
    def test_B_extract_fn_called_exactly_once_per_document(self):
        """The orchestrator must treat one document's extraction as a single
        atomic call -- it must never call extract_fn more than once for the
        same job, and must never decompose a document's own chunk/recovery
        sequence itself (that sequencing belongs entirely to extract_fn)."""
        call_counts = {}
        lock = threading.Lock()

        def fake_extract(doc_text, filename, api_key, *, telemetry=None):
            with lock:
                call_counts[filename] = call_counts.get(filename, 0) + 1
            return {"requirements": [], "_extraction_diagnostic": {"status": "VERIFIED_ADEQUATE"}}

        jobs = [DocumentJob(index=i, name=f"doc{i}.pdf", doc_text=f"text{i}") for i in range(4)]
        run_concurrent_documents(jobs, fake_extract, "test_key", max_document_concurrency=2)
        self.assertEqual(call_counts, {f"doc{i}.pdf": 1 for i in range(4)})

    def test_C_recovery_call_kind_sequence_passes_through_unchanged(self):
        """The orchestrator must not reorder, filter, or reinterpret the
        call_kind sequence extract_fn produces -- it is passed straight
        through into that document's own telemetry list."""
        def fake_extract(doc_text, filename, api_key, *, telemetry=None):
            sequence = ["initial", "recovery_subchunk_truncated", "recovery_subchunk_truncated"]
            for i, kind in enumerate(sequence):
                telemetry.append({"call_index": i, "call_kind": kind, "filename": filename,
                                   "call_started_at": "2026-01-01T00:00:00+00:00",
                                   "call_ended_at": "2026-01-01T00:00:01+00:00",
                                   "latency_seconds": 1.0, "input_tokens": 1, "output_tokens": 1,
                                   "stop_reason": "end_turn", "parse_status": "COMPLETE", "error": None})
            return {"requirements": [], "_extraction_diagnostic": {"status": "RECOVERED_TRUNCATED"}}

        jobs = [DocumentJob(index=0, name="doc.pdf", doc_text="text")]
        results, _ = run_concurrent_documents(jobs, fake_extract, "test_key", max_document_concurrency=2)
        kinds = [rec["call_kind"] for rec in results[0].telemetry]
        self.assertEqual(kinds, ["initial", "recovery_subchunk_truncated", "recovery_subchunk_truncated"])


class TestDeterministicOrdering(unittest.TestCase):
    def test_D_output_order_is_corpus_order_not_completion_order(self):
        """Deliberately make the LAST job finish FIRST (shortest delay) and
        the FIRST job finish LAST (longest delay); the returned results list
        must still be in corpus (job.index) order, never completion order."""
        def fake_extract(doc_text, filename, api_key, *, telemetry=None):
            # doc0 sleeps longest, doc4 sleeps shortest -> completion order is reversed
            index = int(filename.replace("doc", "").replace(".pdf", ""))
            time.sleep(0.05 * (5 - index))
            return {"requirements": [], "_extraction_diagnostic": {"status": "VERIFIED_ADEQUATE"}}

        jobs = [DocumentJob(index=i, name=f"doc{i}.pdf", doc_text=f"text{i}") for i in range(5)]
        results, _ = run_concurrent_documents(jobs, fake_extract, "test_key", max_document_concurrency=2)
        self.assertEqual([r.index for r in results], [0, 1, 2, 3, 4])
        self.assertEqual([r.name for r in results], ["doc0.pdf", "doc1.pdf", "doc2.pdf", "doc3.pdf", "doc4.pdf"])


class TestTelemetryCorrelation(unittest.TestCase):
    def test_E_merged_telemetry_correctly_correlated_per_document(self):
        """After merging, every record must carry the correct document_id,
        document_index, and per_document_call_index -- with no collision or
        cross-document contamination, even though workers ran concurrently
        and each had its own independent, non-shared telemetry list."""
        def fake_extract(doc_text, filename, api_key, *, telemetry=None):
            for i in range(3):
                telemetry.append({"call_index": i, "call_kind": "initial", "filename": filename,
                                   "call_started_at": "2026-01-01T00:00:00+00:00",
                                   "call_ended_at": "2026-01-01T00:00:01+00:00",
                                   "latency_seconds": 1.0, "input_tokens": 1, "output_tokens": 1,
                                   "stop_reason": "end_turn", "parse_status": "COMPLETE", "error": None})
            return {"requirements": [], "_extraction_diagnostic": {"status": "VERIFIED_ADEQUATE"}}

        jobs = [DocumentJob(index=i, name=f"doc{i}.pdf", doc_text=f"text{i}") for i in range(3)]
        results, _ = run_concurrent_documents(jobs, fake_extract, "test_key", max_document_concurrency=2)
        merged = merge_telemetry_deterministic(results)
        self.assertEqual(len(merged), 9)  # 3 docs x 3 calls each
        for doc_index in range(3):
            doc_records = [r for r in merged if r["document_index"] == doc_index]
            self.assertEqual(len(doc_records), 3)
            self.assertEqual([r["per_document_call_index"] for r in doc_records], [0, 1, 2])
            self.assertTrue(all(r["document_id"] == f"doc{doc_index}.pdf" for r in doc_records))
        # merged_call_index must be globally unique and correspond to corpus order
        self.assertEqual([r["merged_call_index"] for r in merged], list(range(9)))

    def test_observed_max_simultaneous_requests_sweep_line(self):
        """Sweep-line overlap detection over call_started_at/call_ended_at
        must correctly report the true peak overlap count from timestamps
        alone, independent of any live counter."""
        merged = [
            {"call_started_at": "2026-01-01T00:00:00+00:00", "call_ended_at": "2026-01-01T00:00:05+00:00"},
            {"call_started_at": "2026-01-01T00:00:02+00:00", "call_ended_at": "2026-01-01T00:00:04+00:00"},
            {"call_started_at": "2026-01-01T00:00:06+00:00", "call_ended_at": "2026-01-01T00:00:07+00:00"},
        ]
        self.assertEqual(observed_max_simultaneous_requests(merged), 2)


class TestFailureSemantics(unittest.TestCase):
    def test_F_one_document_failure_does_not_hide_sibling_results(self):
        """A worker exception must be captured onto its own DocumentResult
        (not silently disappear), and must not cancel or hide any other,
        successfully-completed document's result."""
        def fake_extract(doc_text, filename, api_key, *, telemetry=None):
            if filename == "doc2.pdf":
                raise RuntimeError("simulated API failure")
            return {"requirements": [{"req_id": "M1"}], "_extraction_diagnostic": {"status": "VERIFIED_ADEQUATE"}}

        jobs = [DocumentJob(index=i, name=f"doc{i}.pdf", doc_text=f"text{i}") for i in range(4)]
        results, _ = run_concurrent_documents(jobs, fake_extract, "test_key", max_document_concurrency=2)
        self.assertEqual(len(results), 4)
        failing = [r for r in results if r.name == "doc2.pdf"]
        self.assertEqual(len(failing), 1)
        self.assertIsNotNone(failing[0].error)
        self.assertIn("simulated API failure", failing[0].error)
        self.assertIsNone(failing[0].facts)
        others = [r for r in results if r.name != "doc2.pdf"]
        self.assertEqual(len(others), 3)
        for r in others:
            self.assertIsNone(r.error)
            self.assertIsNotNone(r.facts)

    def test_G_no_result_silently_dropped(self):
        """Every submitted job must appear exactly once in the returned
        results, regardless of success or failure, and regardless of
        completion order."""
        def fake_extract(doc_text, filename, api_key, *, telemetry=None):
            if "3" in filename:
                raise ValueError("boom")
            time.sleep(0.01)
            return {"requirements": [], "_extraction_diagnostic": {"status": "VERIFIED_ADEQUATE"}}

        jobs = [DocumentJob(index=i, name=f"doc{i}.pdf", doc_text=f"text{i}") for i in range(6)]
        results, _ = run_concurrent_documents(jobs, fake_extract, "test_key", max_document_concurrency=2)
        self.assertEqual(sorted(r.name for r in results), sorted(j.name for j in jobs))
        self.assertEqual(len(results), len(jobs))


class TestProductionConfigurationUnchanged(unittest.TestCase):
    def test_H_max_output_tokens_remains_8000(self):
        self.assertEqual(_STAGE_A_MAX_OUTPUT_TOKENS, 8000)

    def test_I_stage_a_prompt_hash_unchanged(self):
        """Regression pin: this package must not touch the Stage A
        extraction prompt in any way. If this fails, the prompt changed --
        which this package's own instructions explicitly forbid."""
        digest = hashlib.sha256(STAGE_A_FACT_EXTRACTION_PROMPT.encode("utf-8")).hexdigest()
        self.assertEqual(digest, "ef69b7cb5397ab32c4065d31ad69d023d668d36f7d97a8f13176026a7051e3ca")

    def test_J_chunk_size_unchanged(self):
        self.assertEqual(_STAGE_A_MAX_CHUNK_CHARS, 12000)


if __name__ == "__main__":
    unittest.main()
