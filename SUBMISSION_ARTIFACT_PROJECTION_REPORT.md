# SUBMISSION ARTIFACT PROJECTION INTEGRITY REPORT

**Date:** 2026-09-04  
**Branch:** `fix/submission-artifact-projection`  
**Code Commit SHA:** `81fbaa779133a922eb12b7cd65935a8725822c7a`  
**Base Commit SHA:** `797d1c4d88fbef44a9772d5e3b615f1d23c0b0ef` (PR #9 merged)  
**Author:** Antigravity  

---

## 1. Executive Summary & Root Cause Analysis

### Problem
In earlier iterations of the Bid Intelligence extraction and projection layer, genuine submission artifacts (such as `Annex 3 (Supplier Response)`) were silently dropped from the projected submission document checklist (`documents` table and Stage 5 SUBMIT checklist).

### Root Cause
1. **Conflation of Format and Channel**: In Stage A extraction and downstream classification, delivery modes (`Portal`, `Email`, `Electronic Portal`) were recorded in the `format` field.
2. **Channel Functioning as a Drop Trigger**: In `_is_concrete_submission_document()`, items with `format="Portal"` or `"Portal/Email"` failed both `_EXPLICIT_INDEPENDENT_FORMAT_PHRASES` and generic document checks. Because `format` contained portal indicators, genuine required documents were rejected at the fallback step.
3. **Absence of Orthogonal Modeling**: The pipeline lacked an independent separation between:
   - **Artifact Identity**: What must be submitted (e.g., Annex 3, Pricing Approach, Signed Declaration).
   - **File Format**: Physical representation (PDF, DOCX, XLSX, Spreadsheet, Online Form, Unspecified).
   - **Submission Channel**: Delivery mechanism (Portal, Email, E-procurement, Courier, Unspecified).

---

## 2. Orthogonal Solution Architecture

1. **Orthogonal Classifier (`classify_submission_rule`)**:
   - Classifies any submission rule into `ARTIFACT`, `PROCESS_ONLY`, `EMBEDDED_RESPONSE`, or `UNKNOWN`.
   - Independently detects `artifact_type`, `file_format`, and `submission_channel`.
   - Strips delivery channel noise from legacy format strings so that genuine artifacts (`Annex 3 (Supplier Response)`) with `format="Portal/Email"` resolve with `submission_channel="Portal"` and clean artifact projection.
   - Preserves `_is_concrete_submission_document(item, fmt, details)` as a backward-compatible wrapper.

2. **Stage A Fact Extraction Prompt**:
   - Explicit instructions in `STAGE_A_FACT_EXTRACTION_PROMPT` explaining that artifact identity, file format, and submission channel are independent.
   - Dedicated schema fields: `artifact_type`, `file_format`, `submission_channel`, `format`, `details`, `mandatory`, and `source_refs`.

3. **Stage A & Stage B Provenance Preservation**:
   - `aggregate_stage_a_facts()` and `normalize_package_facts()` preserve orthogonal dimensions and merge `source_refs` across chunks and documents.

4. **Deterministic Document Projection (`build_submission_documents`)**:
   - Projects genuine artifacts into `documents` table records.
   - Retains all existing fields: `name`, `doc_type` (`Financial` vs `Submission`), `owner`, `due_date`, `status`, `notes`, `mandatory` (1, 0, or omitted if None).
   - Attaches `file_format`, `submission_channel`, `artifact_type`, and merged `source_refs`.

5. **Stage D Authoritative Section Applicator**:
   - `apply_stage_d_authoritative_sections()` rebuilds `brief["submission_requirements"]` from normalized facts, preventing AI synthesis from dropping submission requirements.

---

## 3. Test Suite Verification

### New Test Suite: `tests/test_submission_artifact_projection.py`
- **24/24 tests passed**:
  - **Test A**: Pure portal delivery instruction (`"Submit via portal"`) -> `PROCESS_ONLY` -> excluded.
  - **Test B**: Named annex with Portal channel (`"Annex 3 (Supplier Response)"`, `format="Portal"`) -> `ARTIFACT` -> included.
  - **Test C**: Legacy `format="Portal/Email"` with artifact evidence -> channel normalized, artifact preserved.
  - **Test D**: Explicit pricing XLSX via portal -> `ARTIFACT`, `file_format="XLSX"`, `submission_channel="Portal"`, `doc_type="Financial"`.
  - **Test E**: Pure email instruction -> `PROCESS_ONLY` -> excluded.
  - **Test F**: Signed declaration via email -> `ARTIFACT`, `submission_channel="Email"` -> included.
  - **Test G**: Embedded portal form entry (`format="Form Entry"`) -> `EMBEDDED_RESPONSE` -> excluded.
  - **Test H**: Portal in details text does not override explicit PDF format.
  - **Test I**: Portal in format field does not kill strong standalone artifact.
  - **Test J**: Page limit instruction in item text -> `PROCESS_ONLY` -> excluded.
  - **Test K**: Workbook tab inside another submitted workbook -> `EMBEDDED_RESPONSE` -> excluded.
  - **Test L**: Reference document not submitted -> `PROCESS_ONLY` -> excluded.
  - **Test M**: Attached evidence item (`"Audited Financial Accounts"`) -> `ARTIFACT` -> included.
  - **Test N**: Online questionnaire completed in portal -> `EMBEDDED_RESPONSE` -> excluded.
  - **Test O**: Multiple artifacts sharing same channel -> all projected independently.
  - **Test P**: Channel in details only -> channel captured without affecting artifact projection.
  - **Test Q**: Document name from source not mutated with invented extension.
  - **Test R**: Missing mandatory field -> key omitted (UNKNOWN).
  - **Test S**: `mandatory=0` -> preserved.
  - **Test T**: Source references merged on duplicate artifacts.
  - **Test U**: Mixed package containing both process instructions and artifacts on same channel.
  - **Pipeline Tests**: Stage A aggregation, Stage B normalization, and Stage D authoritative rebuild preservation.

### Existing Test Suites
- `tests/test_submission_document_provenance.py`: **75/75 passed** (including Bank of Canada frozen fixture replay).
- `tests/test_submit_state_consistency.py`: **22/22 passed**.
- `tests/test_stage_d_completeness.py`: **47/47 passed**.
- Full test suite: **414 passed**, 1 skipped, 0 failed.

---

## 4. Benchmark Replay: British Council IR67TVET42026

**Replay Artifact:** `tests/acceptance/results/bc_submission_artifact_projection_replay.json`  
**Code Commit SHA:** `81fbaa779133a922eb12b7cd65935a8725822c7a`  

### Projected Submission Document Checklist (7 Items)

| Document Name | doc_type | mandatory | File Format | Submission Channel | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Annex 2 (Procurement Specific Questionnaire)** | Submission | 1 (Required) | Separate Document | Unspecified | Expected |
| **Annex 2a (Ratio Analysis)** | Submission | 1 (Required) | Separate Document | Unspecified | Expected |
| **Audited Financial Accounts** | Financial | 1 (Required) | Separate Document | Unspecified | Expected |
| **Annex 3 (Supplier Response)** | Submission | 1 (Required) | Unspecified | Portal | Expected |
| **Annex 4 (Pricing Approach)** | Financial | 1 (Required) | Separate Document | Unspecified | Expected |
| **Submission Checklist** | Submission | 1 (Required) | Unspecified | Portal | Expected |
| **Appendix A (Confidential Information Declaration)** | Submission | 0 (Optional) | Separate Document | Unspecified | Expected |

### Human Review Verification
1. **Annex 3 (Supplier Response)**: Correctly projected! Channel identified as `Portal`. Not dropped.
2. **Annex 4 (Pricing Approach)**: Correctly projected as `Financial`!
3. **Audited Financial Accounts**: Correctly projected as `Financial`!
4. **Pure Process Rules Excluded**:
   - `"Submission Portal"` (`https://tap.tcsapps.com...`) -> Excluded.
   - `"Requirements Costs Tab"` (Workbook tab) -> Excluded.
   - `"Assumptions and Exclusions Tab"` (Workbook tab) -> Excluded.
   - `"Pricing Currency"` (Text entry rule) -> Excluded.
   - `"Portal Submission"` (Packaging instruction) -> Excluded.
5. **No Invented Defaults**: 0 invented documents (no `Technical Proposal.pdf` or `Financial Envelope.pdf`).
6. **No Database Migration**: 0 migrations added (No Migration 004).
