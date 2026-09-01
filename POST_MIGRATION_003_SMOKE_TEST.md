# POST-MIGRATION 003 SMOKE TEST REPORT

**Document:** `POST_MIGRATION_003_SMOKE_TEST.md`  
**Date:** September 1, 2026  
**Application:** Bid Intelligence (Enable My Growth)  
**Branch:** `refactor/streamlined-bid-workflow`  
**Target Milestone:** Live Post-Migration 003 Supabase Smoke Test Execution  
**Supabase Instance:** `https://whonalbdpbubaqhpzrnw.supabase.co`  
**Status:** **LIVE SUPABASE SMOKE TESTS VERIFIED**

---

## 1. Live Smoke Suite Execution Output

The live smoke test suite was executed against the live Supabase instance:

```powershell
python -m unittest discover -s tests/smoke -p "test_*.py" -v
```

### Exact Terminal Output:
```text
test_01_live_jsonb_source_refs_persistence (test_live_supabase_migration_003.TestLiveSupabaseMigration003.test_01_live_jsonb_source_refs_persistence)
Verify source_refs persists and returns as native Python list (not string). ... ok
test_02_live_jsonb_document_conflicts_persistence (test_live_supabase_migration_003.TestLiveSupabaseMigration003.test_02_live_jsonb_document_conflicts_persistence)
Verify document_conflicts persists and returns as native Python list (not string). ... ok
test_03_live_evidence_status_valid_values (test_live_supabase_migration_003.TestLiveSupabaseMigration003.test_03_live_evidence_status_valid_values)
Verify writing and reading all 4 valid evidence_status values. ... ok
test_04_live_check_constraint_rejects_invalid_evidence_status (test_live_supabase_migration_003.TestLiveSupabaseMigration003.test_04_live_check_constraint_rejects_invalid_evidence_status)
Verify PostgreSQL check constraint 'check_requirements_evidence_status' rejects invalid values. ... ok
test_05_legacy_records_compatibility (test_live_supabase_migration_003.TestLiveSupabaseMigration003.test_05_legacy_records_compatibility)
Verify pre-existing records load safely with default values and without errors. ... ok

----------------------------------------------------------------------
Ran 5 tests in 22.159s

OK
```

---

## 2. Live Verification Results

| # | Test Case | Target Verification | Live Database Outcome | Status |
|---|---|---|---|---|
| **1** | **`source_refs` JSONB Persistence** | Write native `list` of dicts; read back as native `list` (not string). | Persisted and retrieved as native Python `list`. Nested attributes (`page=2`, `verified=True`, `source_doc`) verified. | **VERIFIED** |
| **2** | **`document_conflicts` JSONB Persistence** | Write native `list` of conflict dicts; read back as native `list`. | Persisted and retrieved as native Python `list`. Discrepancy details (`conflict_type='DATE_CONFLICT'`, source citations) verified. | **VERIFIED** |
| **3** | **Valid `evidence_status` Values** | Write and read `READY`, `PARTIAL`, `MISSING`, `NOT REQUIRED`. | All 4 statuses successfully stored and retrieved from PostgreSQL `requirements` table. | **VERIFIED** |
| **4** | **Constraint Enforcement** | Attempt insert with `evidence_status = 'INVALID'`. | Rejected by PostgreSQL check constraint `check_requirements_evidence_status`. | **VERIFIED** |
| **5** | **Legacy Record Compatibility** | Query pre-existing bids and requirements. | All pre-existing records loaded cleanly with automatic defaults (`evidence_status='MISSING'`, `source_refs=[]`, `document_conflicts=[]`). Zero serialization errors. | **VERIFIED** |

---

## 3. Offline / Unit & Integration Test Suite Status

```powershell
python -m unittest discover -s tests -p "test_*.py"
Ran 27 tests in 0.210s — OK (27/27 Passed)

python -m unittest discover -s tests/integration -p "test_*.py"
Ran 6 tests in 0.243s — OK (5 Passed, 1 Skipped / NOT EXECUTED)
```

1. **Native JSONB Payload Formatting:** Verified in unit tests.
2. **Staged Extraction Architecture:** Fact extraction (Stage A) separated from executive synthesis (Stage D).
3. **Source Provenance Validation:** Active bound checking against physical document parse metadata.
4. **Deterministic Conflict Detection:** 6 conflict categories supported.
5. **Submission Gate Logic:** Enforced with human attestation default `False`.
6. **Live Bank of Canada Acceptance Test:** Harness ready; reported as `SKIPPED / NOT EXECUTED` pending raw procurement source files.

---

## 4. Final Status

# **LIVE SUPABASE SMOKE TESTS VERIFIED**
