# STREAMLINED WORKFLOW TARGETED REMEDIATION REPORT

**Document:** `STREAMLINED_WORKFLOW_REMEDIATION_REPORT.md`  
**Date:** September 1, 2026  
**Application:** Bid Intelligence (Enable My Growth)  
**Branch:** `refactor/streamlined-bid-workflow`  
**Target Milestone:** Final Pre-Migration 003 Correction Pass  
**Final Status / Recommendation:** **READY TO APPLY MIGRATION 003**

---

## 1. Executive Summary & Integrity Review

This targeted correction pass addresses the remaining implementation integrity, provenance validation, JSONB persistence, and staged architecture items prior to Migration 003 approval:

1. **Native JSONB Persistence:** `requirements.source_refs` and `bid_briefs.document_conflicts` pass Python `list`/`dict` values directly to the Supabase client without `json.dumps()` stringification, preventing double-encoded JSON strings in JSONB columns. Existing Migration 002 `TEXT` columns continue to serialize via `json.dumps()`.
2. **Genuinely Staged Extraction Pipeline:** Refactored extraction into 4 distinct logical stages:
   - **Stage A (Document Fact Extraction):** Extracts factual procurement items only (`requirements`, `dates`, `evaluation_criteria`, `submission_rules`, `deliverables`, `commercial_clauses`, `contract_risks`). No executive Bid Brief is generated at this stage.
   - **Stage B (Package Normalization & Provenance Validation):** Deduplicates identical requirements, aggregates `source_refs`, and validates source locations against physical document bounds.
   - **Stage C (Reconciliation & Conflict Analysis):** Compares normalized facts across 6 conflict classes (`MANDATORY_REQUIREMENT_CONFLICT`, `DATE_CONFLICT`, `EVALUATION_CONFLICT`, `SUBMISSION_RULE_CONFLICT`, `COMMERCIAL_TERM_CONFLICT`, `SCOPE_CONFLICT`).
   - **Stage D (Executive Bid Brief Synthesis):** Synthesizes the executive Bid Brief exclusively from the normalized/reconciled model (not from raw document dumps).
3. **Strict Source Provenance Validation:** AI-returned `source_refs` are verified against physical parse metadata: file existence in package, page range bounds ($1 \le \text{page} \le \text{page\_count}$), workbook sheet names, non-empty row coordinates, and excerpt presence. Fabricated or invalid references are flagged with validation errors.
4. **Correct Submission Gate Logic:** Package readiness evaluates mandatory submission documents (`mandatory = 1/True` or submission/financial types). Ready states include `Uploaded`, `Approved`, `Complete`, `Submitted`. `Expected` on mandatory items blocks submission. Optional items (`mandatory = 0/False`) do not block submission.
5. **Human Attestation Default False:** Pre-submission verification checkboxes default to `False`, requiring active affirmative user confirmation before the submission button unlocks.
6. **File Format Integrity:** Unsupported legacy formats (`.doc`, `.xls`) were removed from advertised support and rejected during upload. A deterministic CSV parser with row markers was implemented.
7. **Accurate XLSX Row Coordinates:** Worksheet row markers preserve actual 1-indexed Excel coordinates (e.g. `ROWS: 4-19`) even when preceding or intermediate rows are blank.
8. **Clean Migration 003:** Added idempotent `CHECK (evidence_status IN ('READY', 'PARTIAL', 'MISSING', 'NOT REQUIRED'))` constraint; removed redundant `decided_at` ALTER statement (already present in Migration 002).

---

## 2. Remediation Verification Matrix

| # | Remediation Item | Target Requirement | Implementation Details | Status |
|---|---|---|---|---|
| **1** | **JSONB Persistence** | Pass native list/dict to Supabase for JSONB columns | `format_requirement_payload` and `format_bid_brief_payload` preserve Python `list`/`dict` for `source_refs` and `document_conflicts`. | **FIXED / VERIFIED** |
| **2** | **Staged Extraction** | Separate document fact extraction from Bid Brief synthesis | Implemented genuine 4-stage pipeline (Stage A $\rightarrow$ Stage B $\rightarrow$ Stage C $\rightarrow$ Stage D). | **FIXED / VERIFIED** |
| **3** | **Source Provenance Validation** | Reject fabricated pages, sheets, rows, or files | `validate_source_refs()` checks bounds against physical document parse metadata and excerpt tokens. | **FIXED / VERIFIED** |
| **4** | **Deterministic Conflict Detection** | Expand reconciliation across 6 conflict classes | `detect_document_conflicts()` detects Mandatory, Date, Evaluation, Submission, Commercial, and Scope contradictions. | **FIXED / VERIFIED** |
| **5** | **Submission Gating Document Logic** | Recognize ready states; optional items do not block | `READY_DOC_STATUSES = {"Uploaded", "Approved", "Complete", "Submitted"}`. Optional `Expected` files do not block. | **FIXED / VERIFIED** |
| **6** | **Human Attestation Checkboxes** | Checkboxes must default to False | Changed `chk1`, `chk2`, `chk3`, `chk4` in `pages/stage_submit.py` to default `False`. | **FIXED / VERIFIED** |
| **7** | **File Format Support** | Remove `.doc`/`.xls`; implement CSV parser | Removed `.doc`/`.xls` from uploaders; implemented `extract_csv_with_metadata` with row markers. | **FIXED / VERIFIED** |
| **8** | **XLSX Source Coordinates** | Real worksheet row numbers even with blank rows | `extract_xlsx_with_metadata` calculates `min_r` and `max_r` from non-empty row indices and prepends `Row {r_idx}: `. | **FIXED / VERIFIED** |
| **9** | **Firm Profile Credentials** | Zero invented capabilities in default profile | `DEFAULT_FIRM_PROFILE` fields set to `""`. Warning banner shown for unconfigured profile fields. | **VERIFIED** |
| **10** | **Decision Governance** | AI recommendation must NOT overwrite human decision | `save_bid_decision` sets `human_decision = None` on initial AI run and preserves prior human decisions. | **VERIFIED** |
| **11** | **Lifecycle Consistency** | `Withdrawn` and `No Bid` formal stages | Formalized `Withdrawn` and `No Bid` in `STAGES`, `STAGE_COLOURS`, and win-rate formula: $\frac{\text{Won}}{\text{Won} + \text{Lost}}$. | **VERIFIED** |
| **12** | **Clean Migration 003** | Idempotent CHECK constraint and remove redundant columns | Added `check_requirements_evidence_status` constraint; removed duplicate `decided_at`. | **FIXED / VERIFIED** |
| **13** | **Bank of Canada Live Package** | Honest reporting of live execution | Reported as `NOT EXECUTED` due to absence of raw procurement files in test environment. | **NOT EXECUTED** |

---

## 3. Migration 003 Specification (NOT APPLIED)

File: [`migrations/003_intelligence_integrity.sql`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/migrations/003_intelligence_integrity.sql)

```sql
-- ============================================================================
-- Migration 003: Intelligence & Governance Integrity
-- Application: Bid Intelligence (Enable My Growth)
--
-- PURPOSE:
-- 1. Evidence readiness status with CHECK constraint (READY, PARTIAL, MISSING, NOT REQUIRED)
-- 2. Structural source provenance / traceability as native JSONB on requirements
-- 3. Cross-document conflict & discrepancy detection as native JSONB on bid briefs
--
-- NOTE: DO NOT EXECUTE AUTOMATICALLY. Leave for explicit user review & approval.
-- ============================================================================

-- 1. Evidence readiness status on requirements with CHECK constraint
ALTER TABLE requirements
ADD COLUMN IF NOT EXISTS evidence_status TEXT DEFAULT 'MISSING';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_requirements_evidence_status'
    ) THEN
        ALTER TABLE requirements
        ADD CONSTRAINT check_requirements_evidence_status
        CHECK (evidence_status IN ('READY', 'PARTIAL', 'MISSING', 'NOT REQUIRED'));
    END IF;
END $$;

-- 2. Structural source references / provenance as native JSONB on requirements
ALTER TABLE requirements
ADD COLUMN IF NOT EXISTS source_refs JSONB DEFAULT '[]'::jsonb;

-- 3. Cross-document conflict and discrepancy detection as native JSONB on bid briefs
ALTER TABLE bid_briefs
ADD COLUMN IF NOT EXISTS document_conflicts JSONB DEFAULT '[]'::jsonb;

-- Indices for query performance
CREATE INDEX IF NOT EXISTS idx_requirements_evidence_status ON requirements(bid_id, evidence_status);
```

> [!IMPORTANT]
> **Migration 003 has NOT been executed against Supabase.** It is ready for user review and execution in the Supabase SQL editor. The application code in [`database.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/database.py) includes multi-tier defensive fallbacks to operate smoothly both prior to and after Migration 003 is executed.

---

## 4. Test Suite Execution Results

### Unit Tests:
```powershell
python -m unittest discover -s tests -p "test_*.py"
Ran 27 tests in 0.231s — OK (27/27 Passed)
```

1. `test_source_refs_jsonb_payload_remains_native_list` — **PASS**
2. `test_document_conflicts_jsonb_payload_remains_native_list` — **PASS**
3. `test_stage_a_prompt_extracts_facts_only_not_brief` — **PASS**
4. `test_stage_d_prompt_synthesizes_from_normalized_model` — **PASS**
5. `test_valid_deterministic_source_reference_accepted` — **PASS**
6. `test_invalid_page_source_reference_rejected` — **PASS**
7. `test_invalid_sheet_source_reference_rejected` — **PASS**
8. `test_invalid_filename_source_reference_rejected` — **PASS**
9. `test_date_conflict_detected` — **PASS**
10. `test_evaluation_weight_conflict_detected` — **PASS**
11. `test_submission_rule_conflict_detected` — **PASS**
12. `test_mandatory_requirement_conflict_detected` — **PASS**
13. `test_commercial_term_conflict_detected` — **PASS**
14. `test_scope_conflict_detected` — **PASS**
15. `test_mandatory_uploaded_is_ready` — **PASS**
16. `test_mandatory_approved_is_ready` — **PASS**
17. `test_mandatory_complete_is_ready` — **PASS**
18. `test_mandatory_submitted_is_ready` — **PASS**
19. `test_mandatory_expected_is_blocker` — **PASS**
20. `test_optional_expected_does_not_block` — **PASS**
21. `test_doc_and_xls_rejected_as_unsupported` — **PASS**
22. `test_csv_parser_with_row_markers` — **PASS**
23. `test_xlsx_blank_rows_preserve_real_row_coordinates` — **PASS**
24. `test_default_firm_profile_unconfigured` — **PASS**
25. `test_ai_evaluation_preserves_human_decision` — **PASS**
26. `test_withdrawn_and_nobid_in_stages` — **PASS**
27. `test_win_rate_calculation` — **PASS**

### Integration Tests:
```powershell
python -m unittest discover -s tests/integration -p "test_*.py"
Ran 6 tests in 0.285s — OK (5 Passed, 1 Skipped / NOT EXECUTED)
```

1. `test_zip_safe_unpacking_and_path_traversal_rejection` — **PASS**
2. `test_multi_document_preserves_filenames_and_markers` — **PASS**
3. `test_docx_xml_parsing_fallback` — **PASS**
4. `test_xlsx_xml_parsing_fallback` — **PASS**
5. `test_addenda_deadline_conflict_reconciliation` — **PASS**
6. `test_live_bank_of_canada_package_extraction` — **SKIPPED (NOT EXECUTED)**

---

## 5. Live Acceptance & Source Fixture Status

### Bank of Canada RFP No. 2026-026 Live Acceptance:
- **Status:** `NOT EXECUTED` (Harness ready at [`tests/integration/test_bank_of_canada_live_acceptance.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/tests/integration/test_bank_of_canada_live_acceptance.py)).
- **Explanation:** The physical raw source documents for Bank of Canada RFP No. 2026-026 were not present in the local workspace. Per project directives, source documents were **not fabricated**.
- **Execution Condition:** Setting `RUN_LIVE_AI_TESTS=1`, populating `fixtures/bank_of_canada_2026_026/`, and providing `ANTHROPIC_API_KEY` will execute the live package test.

---

## 6. Final Recommendation

# **READY TO APPLY MIGRATION 003**
