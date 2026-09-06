# SUBMISSION ARTIFACT PROJECTION INTEGRITY REPORT

**Date:** 2026-09-05  
**Branch:** `fix/submission-artifact-projection`  
**Code Commit SHA:** `802faa659905b07cbc081443c188fb644def1b35`  
**Base Commit SHA:** `797d1c4d88fbef44a9772d5e3b615f1d23c0b0ef` (PR #9 merged)  
**Author:** Antigravity  

---

## 1. Executive Summary & Root Cause Analysis

### Problem
In earlier iterations of the Bid Intelligence extraction and projection layer, genuine submission artifacts (such as `Annex 3 (Supplier Response)`) were silently dropped from the projected submission document checklist (`documents` table and Stage 5 SUBMIT checklist). Furthermore, cross-document observation conflicts could be silently collapsed in projected document metadata if conflicts occurred across duplicate rules.

### Root Cause
1. **Conflation of Format and Channel**: In Stage A extraction and downstream classification, delivery modes (`Portal`, `Email`, `Electronic Portal`) were recorded in the `format` field.
2. **Channel Functioning as a Drop Trigger**: In `_is_concrete_submission_document()`, items with `format="Portal"` or `"Portal/Email"` failed both `_EXPLICIT_INDEPENDENT_FORMAT_PHRASES` and generic document checks. Because `format` contained portal indicators, genuine required documents were rejected at the fallback step.
3. **Absence of Orthogonal Modeling**: The pipeline lacked an independent separation between:
   - **Artifact Identity**: What must be submitted (e.g., Annex 3, Pricing Approach, Signed Declaration).
   - **File Format**: Physical representation (PDF, DOCX, XLSX, Spreadsheet, Online Form, Unspecified).
   - **Submission Channel**: Delivery mechanism (Portal, Email, E-procurement, Courier, Unspecified).
4. **Silent Collapse of Projection Conflicts**: Multi-document conflict flags (`file_format_conflict`, `submission_channel_conflict`, `mandatory_conflict`, `artifact_type_conflict`) were tracked in normalization but not consistently preserved through projected document dictionaries and authoritative Stage D section rebuilding.

---

## 2. Orthogonal Solution Architecture & Generic Integrity Hardening

1. **Orthogonal Classifier (`classify_submission_rule`)**:
   - Classifies any submission rule into `ARTIFACT`, `PROCESS_ONLY`, `EMBEDDED_RESPONSE`, or `UNKNOWN`.
   - Independently detects `artifact_type`, `file_format`, and `submission_channel`.
   - **Authoritative Orthogonal Precedence**:
     - Explicit `artifact_type == "Process Instruction"` unconditionally resolves to `PROCESS_ONLY` (`is_concrete_document = False`).
     - `file_format == "Online Form"` with `artifact_type in ("Questionnaire / Workbook", "Form / Annex")` and no independence signals resolves to `EMBEDDED_RESPONSE` (`is_concrete_document = False`).
     - Explicit authoritative artifact types (`Proposal / Response`, `Declaration / Certification`, `Evidence / Attachment`, `Pricing / Financial`, `Form / Annex`) with non-online-form format resolve to `ARTIFACT` (`is_concrete_document = True`), guarded by `has_explicit_artifact_type` so inferred types never override format exclusions.
   - **Physical Format vs. Independence Signals**: Physical formats (`PDF`, `DOCX`, `XLSX`, `XLS`, `Spreadsheet`, `Online Form`, `Hard Copy`) are decoupled from independence phrases (`Separate File`, `Separate Document`, `Attachment`). `file_format` is never populated with `'Separate Document'`.
   - **Controlled Channel Enum**: Normalized channels via `_CONTROLLED_CHANNEL_MAP` (`Portal`, `Email`, `E-procurement`, `Courier`, `Physical`, `Upload`, `Unspecified`).
   - Preserves `_is_concrete_submission_document(item, fmt, details)` as a backward-compatible wrapper.

2. **Stage A Fact Extraction Prompt**:
   - Explicit instructions in `STAGE_A_FACT_EXTRACTION_PROMPT` explaining that artifact identity, file format, and submission channel are independent.
   - Dedicated schema fields: `artifact_type`, `file_format`, `submission_channel`, `format`, `details`, `mandatory`, and `source_refs`.

3. **Stage A & Stage B Provenance Preservation & Observation History**:
   - `aggregate_stage_a_facts()` and `normalize_package_facts()` preserve orthogonal dimensions and merge `source_refs` across chunks and documents.
   - **Zero Synthetic Fallbacks**: Never manufactures synthetic source references (`source_doc = filename`, `excerpt = item/details`) when the source model emitted none.
   - **Sheet-Aware Provenance Identity**: Merge keys and deduplication incorporate `(source_doc, page, sheet, section, excerpt)`.
   - **Observation History & Conflict Tracking**: Tracks multi-document observation history (`artifact_type_observations`, `file_format_observations`, `submission_channel_observations`, `mandatory_observations`) and flags conflicts across documents.
   - **Canonical Item Identity**: Stable canonical item mapping via `_canonical_submission_item_identity(item)` to ensure punctuation/spacing variants aggregate together cleanly.

4. **Deterministic Document Projection with Conflict Invariance (`build_submission_documents`)**:
   - Projects genuine artifacts into `documents` table records.
   - Maps `artifact_type == "Pricing / Financial"` directly to `doc_type = "Financial"`.
   - **Conflict Preservation and Conservative Semantics**:
     - `file_format_conflict == True` $\to$ `file_format = "Multiple / Mixed"`, observations preserved.
     - `submission_channel_conflict == True` $\to$ `submission_channel = "Unspecified"`, observations preserved.
     - `mandatory_conflict == True` $\to$ `mandatory` omitted (None), observations preserved.
     - `artifact_type_conflict == True` $\to$ `artifact_type = "Unknown"`, `doc_type` not chosen arbitrarily from first winner (falls back to keyword check or Submission).
     - Full order independence: (PDF then DOCX) == (DOCX then PDF).
   - Retains all existing fields: `name`, `doc_type`, `owner`, `due_date`, `status`, `notes`.
   - Attaches observation arrays and conflict flags: `artifact_type_observations`, `artifact_type_conflict`, `file_format_observations`, `file_format_conflict`, `submission_channel_observations`, `submission_channel_conflict`, `mandatory_observations`, `mandatory_conflict`.

5. **Stage D Authoritative Section Applicator**:
   - `apply_stage_d_authoritative_sections()` rebuilds `brief["submission_requirements"]` from normalized facts, preserving observation arrays and conflict flags, and preventing AI synthesis from dropping submission requirements.

---

## 3. Test Suite Verification

### Regression Test Suite: `tests/test_submission_artifact_projection.py`
- **49/49 tests passed**:
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
  - **Generic Integrity Items 1-9**:
    - Item 1: Explicit Process Instruction unconditionally excluded.
    - Item 1: Online Form questionnaire without independence signals classified as Embedded Response.
    - Item 1: Explicit artifact type overrides legacy format exclusion.
    - Item 2: Physical format separated from independence signal (`file_format != 'Separate Document'`).
    - Item 2: Format matching precedence (`.xlsx` over `.xls`).
    - Item 3: Electronic bid submission channel phrase not excluded when artifact noun is present.
    - Item 4: Controlled channel mapping (`Portal`, `Email`, `E-procurement`, etc.).
    - Item 5: No synthetic fallback source_refs manufactured in Stage A.
    - Item 5: No synthetic fallback source_refs manufactured in Stage B.
    - Item 5: Provenance state verified when source_refs present, unverified when empty.
    - Item 6: Sheet identity preserved in source reference merging.
    - Item 7: Observation history and conflict tracking in Stage A.
    - Item 7: Observation history and conflict tracking across Stage B package normalization.
    - Item 8: Canonical item identity aggregates slight name variations.
    - Item 9: Artifact type `Pricing / Financial` sets `doc_type = "Financial"`.
  - **Conflict & Permutation Invariance Suite (Tests A-H)**:
    - **Conflict Test A**: Consistent format observations produce no conflict (`PDF` format preserved).
    - **Conflict Test B**: Format conflict (`PDF` + `DOCX`) resolves to `Multiple / Mixed`, sets `file_format_conflict=True`, preserves observations under both permutation orders.
    - **Conflict Test C**: Channel conflict (`Portal` + `Email`) resolves to `Unspecified`, sets `submission_channel_conflict=True`, preserves observations under both permutation orders.
    - **Conflict Test D**: Mandatory conflict (`1` + `0`) omits `mandatory` key, sets `mandatory_conflict=True`, preserves observations under both permutation orders.
    - **Conflict Test E**: Artifact type conflict (`Form / Annex` + `Pricing / Financial`) resolves to `Unknown`, does not select arbitrary winner, falls back conservatively under both permutation orders.
    - **Conflict Test F**: Artifact type conflict with pricing keyword in item name correctly identifies `doc_type = "Financial"`.
    - **Conflict Test G**: Duplicate consistent observations do not trigger false conflicts.
    - **Conflict Test H**: `apply_stage_d_authoritative_sections()` preserves all observation arrays and conflict booleans in `brief["submission_requirements"]`.

### Existing Test Suites
- `tests/test_submission_document_provenance.py`: **75/75 passed** (including Bank of Canada frozen fixture replay).
- `tests/test_submit_state_consistency.py`: **22/22 passed**.
- `tests/test_stage_d_completeness.py`: **47/47 passed**.
- **Full test suite (`pytest tests/ -q`)**: **439 passed, 1 skipped, 0 failed, 19 subtests passed** in 62.6s.

---

## 4. Benchmark Replay: British Council IR67TVET42026

**Replay Runner:** `run_bc_submission_replay.py`  
**Replay Artifact:** `tests/acceptance/results/bc_submission_artifact_projection_replay.json`  
**Code Commit SHA:** `802faa659905b07cbc081443c188fb644def1b35`  
**Replay Mode:** `FROZEN` (Explicitly labeled; `--live` supported with full A$\to$D pipeline execution)  

### Projected Submission Document Checklist (7 Items)

| Document Name | doc_type | mandatory | File Format | Submission Channel | Provenance State | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Annex 2 (Procurement Specific Questionnaire)** | Submission | 1 (Required) | Unspecified | Unspecified | UNVERIFIED | Expected |
| **Annex 2a (Ratio Analysis)** | Submission | 1 (Required) | Unspecified | Unspecified | UNVERIFIED | Expected |
| **Audited Financial Accounts** | Financial | 1 (Required) | Unspecified | Unspecified | UNVERIFIED | Expected |
| **Annex 3 (Supplier Response)** | Submission | 1 (Required) | Unspecified | Portal | UNVERIFIED | Expected |
| **Annex 4 (Pricing Approach)** | Financial | 1 (Required) | Unspecified | Unspecified | UNVERIFIED | Expected |
| **Submission Checklist** | Submission | 1 (Required) | Unspecified | Portal | UNVERIFIED | Expected |
| **Appendix A (Confidential Information Declaration)** | Submission | 0 (Optional) | Unspecified | Unspecified | UNVERIFIED | Expected |

### Human Review Verification
1. **Annex 3 (Supplier Response)**: Correctly projected! Channel identified as `Portal`. Not dropped.
2. **Annex 4 (Pricing Approach)**: Correctly projected as `Financial`!
3. **Audited Financial Accounts**: Correctly projected as `Financial`!
4. **Pure Process Rules Excluded**:
   - `"Submission Portal"` (`https://tap.tcsapps.com...`) -> Excluded (`PROCESS_ONLY`).
   - `"Requirements Costs Tab"` (Workbook tab) -> Excluded (`EMBEDDED_RESPONSE`).
   - `"Assumptions and Exclusions Tab"` (Workbook tab) -> Excluded (`EMBEDDED_RESPONSE`).
   - `"Pricing Currency"` (Text entry rule) -> Excluded (`UNKNOWN` / non-artifact).
   - `"Portal Submission"` (Packaging instruction) -> Excluded (`PROCESS_ONLY`).
5. **No Invented Defaults**: 0 invented documents (no `Technical Proposal.pdf` or `Financial Envelope.pdf`).
6. **No Database Migration**: 0 migrations added (No Migration 004).
7. **Clean Provenance State**: All projected documents correctly report `provenance_state` without manufacturing synthetic refs.
8. **Explicit Replay Mode**: Replay artifacts and logs explicitly distinguish between `FROZEN` (deterministic baseline using Attempt 2 facts) and `LIVE` (full LLM pipeline execution).

---

## 5. Live Benchmark Replay & Stage D Capacity Block Record

**Live Failure Artifact:** `tests/acceptance/results/bc_submission_artifact_projection_live_failure.json`  
**Production Code SHA:** `802faa659905b07cbc081443c188fb644def1b35`  
**Model:** `claude-haiku-4-5-20251001`  
**Replay Mode:** `LIVE`  
**Outcome:** `BLOCKED_STAGE_D_CONTEXT_LIMIT`  
**Attempts Count:** 2 (both halted at the identical preflight guard; live replay attempted twice only)  

### Execution & Stage Metrics
- **Input Documents:** 8 fixture files preprocessed in 1.21s (279,258 characters).
- **Stage A (Live Document Fact Extraction):** Completed across all 8 files via live Claude Haiku calls in **2,929.66s** (~48.8 minutes).
  - Raw submission rules extracted: **106**.
- **Stage B (Package Normalization):** Completed in **0.3897s**.
  - Normalized submission rules: **76**.
- **Stage C (Cross-Document Reconciliation):** Completed in **0.0529s**.
  - Conflicts detected: **7**.
- **Stage D (Executive Bid Brief Synthesis):** **HALTED BEFORE API DISPATCH**.
  - Source requirements extracted across package: **559**.
  - Serialized Stage D context size: **1,045,967 characters**.
  - Safe Stage D input limit (`_STAGE_D_CONTEXT_CHAR_LIMIT`): **580,000 characters**.
  - Excess over safe threshold: **465,967 characters**.
  - Preflight guard triggered: `extractor.StageDContextTooLargeError`.
  - Stage D API dispatch did not occur.
  - No requirements were silently omitted.

### Integrity & Root Cause Analysis
> [!IMPORTANT]
> **Stage D Context Limit vs. Submission Projection Integrity**:
> The Submission Artifact Projection remediation itself is not known to have failed. Stages A, B, and C successfully extracted and normalized 76 orthogonal submission rules across the live 8-document package with observation tracking and conflict flags.
> Full live end-to-end acceptance could not complete because a separate, pre-existing downstream Stage D context-capacity constraint was encountered on the 559-requirement procurement package.
> 
> - **LIVE ACCEPTANCE PASSED is NOT claimed.**
> - The Stage D context-capacity block is **not** a submission-projection defect; it is an existing architectural constraint in Stage D synthesis when handling very large requirement registers (>500 requirements with source references).
> - No production code (`extractor.py`), test code, or replay runner code was altered after the failure.
