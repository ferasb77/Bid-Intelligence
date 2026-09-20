# Stage A Extraction Reliability Report

**Repository:** `ferasb77/Bid-Intelligence`  
**Branch:** `fix/stage-a-extraction-reliability`  
**Base:** `main` at `6ff8654e0894acaa786ec146917af4506bace44b`  
**Date:** 2026-09-03  

---

## 1. Executive Summary

During British Council Blind Real-World Acceptance Test #2, a major extraction variance failure was discovered in Stage A:
- In Attempt 1, `annex_2_-_procurement_specific_questionnaire_1.docx` yielded 16 raw requirements.
- In Attempt 2, the exact same file yielded 0 raw requirements.
- In both attempts, the primary 25-page ITT (`itt_-_ir67tvet42026_-_smart_classroom_setup_-_updated.pdf`, 60,210 characters) yielded 0 raw requirements despite containing extensive qualification requirements, mandatory terms, milestone schedules, award criteria, and submission rules.

This branch resolves the root cause by removing single-pass monolithic extraction for substantial documents. It introduces deterministic marker-aware document chunking with hard chunk-size guarantees, deterministic factual aggregation with full-description deduplication, an automated Coverage Guard with family-specific bounded recovery, and sampling configuration (`temperature=0.0`).

---

## 2. Root Cause Analysis

1. **Context Satiation & Single-Pass Extraction:**
   Prior to this fix, `extract_document_facts()` passed entire document texts (up to 150,000 characters) in a single LLM request. For complex or dense procurement documents with dozens of pages and tables (e.g. 25-page ITT and 59-table PSQ), the LLM frequently suffered from instruction distraction or output token economization, skipping requirement extraction entirely or extracting only high-level metadata.

2. **Non-Deterministic Sampling Defaults:**
   The Anthropic API invocation previously used default sampling parameters, contributing to avoidable sampling variance between runs on identical inputs.

3. **Silent Under-Coverage:**
   There was no verification mechanism to check whether a document with strong procurement signals (e.g., "shall", "must", "mandatory", "evaluation criteria", "deadline") produced zero corresponding facts. Stage A silently accepted empty outputs and passed them downstream.

---

## 3. Architecture & Implementation

### 3.1 Deterministic Marker-Aware Chunking & Hard Size Guarantee
- Located in [`extractor.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/extractor.py): `chunk_document_text(doc_text, max_chunk_chars=16000)`.
- Preprocessing embeds deterministic source markers:
  - `[[SOURCE: filename | PAGE: n]]` (PDFs)
  - `[[SOURCE: filename | SECTION: heading]]` or `[[SOURCE: filename | TABLE]]` (DOCX)
  - `[[SOURCE: filename | SHEET: sheet | ROWS: x-y]]` (XLSX)
- Chunking splits cleanly along marker boundaries without splitting inside markers.
- Short documents (length $\le 16,000$ characters) proceed in a single chunk.
- **Hard Chunk Size Guarantee:** If an individual block exceeds `max_chunk_chars`, it is subdivided on newline boundaries. If an individual line or paragraph itself exceeds `max_chunk_chars` (e.g. an uninterrupted 40,000-character line), a deterministic fallback slices the line into strictly bounded chunks ($\le \text{max\_chunk\_chars}$) while inheriting the active source marker, guaranteeing lossless substantive content.

### 3.2 Model Determinism Configuration
- `_extract_chunk_facts()` enforces:
  - `temperature=0.0`
  - Explicit model: `claude-haiku-4-5-20251001`
  - Fixed `max_tokens=8000`

### 3.3 Deterministic Aggregation Layer & Requirement Identity
- Implemented in `aggregate_stage_a_facts(chunk_facts_list, filename)`.
- Combines facts across 8 procurement families:
  1. `doc_metadata`: Conservative first-non-empty merge without inventing or overwriting conflicting values.
  2. `requirements`: Deduplicated using the **full normalized material description**, category, and reference `(norm_desc, cat.lower(), rfso.lower())` without character truncation. Requirements sharing the same local `req_id` (e.g., `M1` generated independently in Chunk 1 and Chunk 2) do **not** collapse if their descriptions differ. Distinct requirements sharing a long common prefix (>80 chars) are preserved without accidental collision. If descriptions match, physical `source_refs` are merged.
  3. `dates`: Deduplicated by `(milestone.lower(), date)`.
  4. `evaluation_criteria`: Deduplicated by `(stage.lower(), weight.lower(), notes.lower())`.
  5. `submission_rules`: Deduplicated by `(item.lower(), format.lower(), details.lower())`.
  6. `deliverables`: Deduplicated by `(title.lower(), description.lower())`.
  7. `commercial_clauses`: Deduplicated by `(topic.lower(), details.lower())`.
  8. `contract_risks`: Deduplicated by `(risk.lower(), details.lower())`.

### 3.4 Coverage Guard & Family-Specific Bounded Recovery
- Implemented in `inspect_stage_a_coverage(doc_text, facts, min_signal_count=5)`.
- Evaluates domain-general procurement indicators:
  - **Requirements:** `shall`, `must`, `required`, `mandatory`, `condition of participation`, `supplier will`, `tenderer shall`
  - **Dates:** `deadline`, `response deadline`, `clarification`, `timescale`, `closing date`, `site visit`
  - **Evaluation Criteria:** `evaluation`, `award criteria`, `scoring`, `weighted`, `%`, `marks`, `price weighting`
  - **Submission Rules:** `submit`, `submission`, `response checklist`, `annex`, `attachment`, `signed`, `portal`
- If strong signals ($\ge 5$) exist for a family but aggregated facts return 0 items, the extraction is flagged suspicious.
- **Family-Specific Recovery Merge:** When recovery is triggered, retry facts are **deterministically merged** with the original aggregated facts (`aggregate_stage_a_facts([aggregated, retry_aggregated], filename)`). Original facts are never discarded simply because a retry produced fewer items in another family. Coverage inspection is re-evaluated on the merged result.
- **Bounds:** Strictly limited to `max_recoveries = 2`. No infinite recursion.
- Non-schema internal diagnostic recorded under `_extraction_diagnostic`:
  - `status`: `"VERIFIED_ADEQUATE"` or `"SUSPICIOUS_UNDER_COVERAGE"`
  - `recovery_attempts`: integer
  - `suspicious_families`: list of under-covered categories

---

## 4. Known Benchmark Replay Observations

To verify the fix against the known British Council benchmark documents without retuning, 3 independent Stage A runs were executed for:
1. Main ITT (`itt_-_ir67tvet42026_-_smart_classroom_setup_-_updated.pdf`, 25 pages, 60,210 chars, divided into 4 chunks)
2. Annex 2 PSQ (`annex_2_-_procurement_specific_questionnaire_1.docx`, 24,452 chars, divided into 2 chunks)

Results recorded from live Anthropic calls:

| Target Document | Run | Chunks | API Calls | Requirements | Dates | Eval Criteria | Submission Rules | Recovery Triggered | Coverage Diagnostic |
|---|---|---|---|---|---|---|---|---|---|
| **Main ITT (PDF)** | Run 1 | 4 | 4 | 26 | 13 | 13 | 16 | False | `VERIFIED_ADEQUATE` |
| **Main ITT (PDF)** | Run 2 | 4 | 4 | 49 | 14 | 13 | 17 | False | `VERIFIED_ADEQUATE` |
| **Main ITT (PDF)** | Run 3 | 4 | 4 | 44 | 16 | 13 | 19 | False | `VERIFIED_ADEQUATE` |
| **Annex 2 PSQ (DOCX)** | Run 1 | 2 | 2 | 21 | 0 | 5 | 9 | False | `VERIFIED_ADEQUATE` |
| **Annex 2 PSQ (DOCX)** | Run 2 | 2 | 2 | 29 | 0 | 5 | 12 | False | `VERIFIED_ADEQUATE` |
| **Annex 2 PSQ (DOCX)** | Run 3 | 2 | 2 | 30 | 0 | 5 | 16 | False | `VERIFIED_ADEQUATE` |

### Realistic Reliability Assessment:
- **No Catastrophic Silent-Zero Failure:** In all 6 runs across both documents, zero runs collapsed to an empty extraction. The primary ITT consistently returned 26–49 requirements, 13–16 dates, 13 evaluation criteria, and 16–19 submission rules (compared to 0 in both Attempt 1 and Attempt 2). Annex 2 returned 21–30 requirements (compared to 0 in Attempt 2).
- **Model Variance Remains:** As demonstrated by the live benchmark numbers (ITT requirements: 26, 49, 44; Annex 2 requirements: 21, 29, 30), model-level extraction variance between runs continues to exist despite `temperature=0.0`. LLM generation is inherently non-deterministic across network calls.
- **Scope Boundary:** This branch establishes deterministic chunk boundaries, deterministic factual aggregation, bounded recovery, and protection against catastrophic omissions; it does **not** claim that LLM output counts are static or that procurement accuracy is solved.

---

## 5. Test Suite & Verification

### 5.1 Dedicated Test Module
[`tests/test_stage_a_extraction_reliability.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/tests/test_stage_a_extraction_reliability.py) covers 20 dedicated unit and mocked tests:
- `test_A_deterministic_chunk_boundaries`: Same text produces identical chunks.
- `test_B_marker_preservation`: Every chunk retains source markers.
- `test_C_page_boundary_chunking`: PDF page markers preserved at chunk boundaries.
- `test_D_docx_section_table_marker_chunking`: DOCX table and section structure preserved.
- `test_D2_hard_chunk_size_guarantee_single_oversized_line`: 40,000-char single line produces strictly bounded chunks ($\le 16,000$), inherits markers, and remains lossless.
- `test_E_deterministic_aggregation`: Exact byte equivalence on identical chunk inputs.
- `test_F_duplicate_material_fact_collapse`: Materially identical facts with same provenance collapse.
- `test_G_same_req_id_different_requirement_text`: Distinct facts sharing identical `req_id` (e.g. `M1`) do not collapse.
- `test_G2_long_common_prefix_different_suffix`: Requirements with >80 char identical prefix but distinct text afterward survive aggregation.
- `test_H_same_requirement_text_different_physical_source_refs`: Preserves distinct physical citations and merges references.
- `test_I_metadata_merge`: Conservative non-null metadata retention without contradiction invention.
- `test_J_coverage_guard_requirements`: Mandatory signals + 0 reqs flags suspicious.
- `test_K_coverage_guard_evaluation`: Weight/score signals + 0 criteria flags suspicious.
- `test_L_coverage_guard_dates`: Deadline signals + 0 dates flags suspicious.
- `test_M_benign_document`: Background document without signals is not falsely flagged.
- `test_N_retry_bound`: Recovery loop terminates strictly within retry limits.
- `test_O_null_malformed_chunk_output`: Malformed non-JSON chunk returns safely without fabricating facts.
- `test_multi_chunk_extraction_across_families`: Mocked model test merging facts across chunk boundaries.
- `test_controlled_recovery_from_suspiciously_empty_output`: Mocked model test verifying recovery triggers and succeeds.
- `test_controlled_recovery_family_specific_merge`: Mocked test verifying recovery merges family facts without discarding original valid requirements.

### 5.2 Regression Test Results
- `tests/test_stage_a_extraction_reliability.py`: **20 / 20 passed**
- `tests/test_stage_c_refinement.py`: **passed**
- `tests/test_streamlined_workflow.py`: **passed**
- `tests/test_stage_d_completeness.py`: **passed**
- `tests/test_submission_document_provenance.py`: **passed**
- `tests/test_submit_state_consistency.py`: **passed**
- `tests/smoke/`: **12 / 12 passed**
- `tests/integration/`: **6 discovered / 5 passed / 1 skipped (live AI)**
- Full unit test discovery (`tests/test_*.py`): **259 / 259 passed**
- Grand total suite across unit, smoke, and integration: **277 discovered / 276 passed / 1 skipped (live AI) / 0 failed**

---

## 6. Deferred Items & Architectural Boundaries

1. **Legacy `.xls` Parsing (Annex 2a):**
   Parsing for legacy `.xls` (BIFF8 binary format) remains deferred and was not addressed in this branch.
2. **No Downstream Semantic Changes:**
   No qualification heuristics, evaluation hierarchies, or Stage C/D logic were modified.
3. **No Database Migrations or Schema Changes:**
   `_extraction_diagnostic` is an internal dictionary key passed on the document-level Stage A fact object. No database schema or Supabase tables were modified.
4. **No Tender-Specific Production Rules:**
   All chunking boundaries, signal regexes, and recovery triggers are general procurement mechanisms. No British Council filenames, section titles, or strings exist in production code.

---

## 7. Conclusion

Stage A extraction now provides deterministic chunk boundaries, hard chunk-size limits, robust full-description factual deduplication, and automated coverage guarding with non-destructive family-specific recovery. Catastrophic silent-zero omissions are prevented while acknowledging that model-level extraction variation naturally persists across live LLM calls.
