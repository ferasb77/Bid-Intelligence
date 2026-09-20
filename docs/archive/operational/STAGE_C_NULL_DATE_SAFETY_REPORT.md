# Stage C Null Date Safety Report

**Branch:** `fix/stage-c-null-date-safety`  
**Base:** `main` at `d8e9292252e16a384f07904bf7a6956e20abb753`  
**Date:** 2026-09-02  

---

## 1. Exact Acceptance Test #2 Failure

During Blind Real-World Acceptance Test #2 (Tender: British Council `IR67TVET42026`, "Smart Classroom setup in Centre of Excellence"), the production extraction pipeline halted at Stage C with the following exception:

```
Traceback (most recent call last):
  File ".../run_acceptance_bc.py", line 104, in <module>
    conflicts = reconcile_package_facts(normalized_facts, package_metadata["files"])
  File "C:\Users\feras\Documents\Projects\Bid-Intelligence\extractor.py", line 1954, in reconcile_package_facts
    return detect_document_conflicts(normalized_facts, package_files)
  File "C:\Users\feras\Documents\Projects\Bid-Intelligence\extractor.py", line 1137, in detect_document_conflicts
    dt = d.get("date", "").strip()
         ^^^^^^^^^^^^^^^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'strip'
```

---

## 2. Root Cause Analysis

In Stage A / Stage B ingestion, date extraction can legitimately produce a date dictionary where the `"date"` key is explicitly mapped to `None` (e.g. `{"milestone": "Submission Deadline", "date": None, "source_doc": "..."}`).

In Python dictionaries:
```python
d = {"date": None}
val = d.get("date", "")  # returns None, NOT ""!
```
Because the key `"date"` exists in the dictionary, `d.get("date", "")` returns the value associated with the key (`None`). Subsequently executing `.strip()` on `None` raises:
`AttributeError: 'NoneType' object has no attribute 'strip'`.

Furthermore, equivalent unsafe expressions existed across the date reconciliation block:
- Line 1137: `dt = d.get("date", "").strip()`
- Line 1145: `pair = select_opposing_pair(internal_list, lambda x: x.get("date", "").strip())`
- Line 1170: `cross_pair = select_opposing_pair(cross_candidates, lambda x: x.get("date", "").strip(), ...)`

---

## 3. Production Code Correction

In `extractor.py`, introduced a focused, non-destructive, null-safe text cleaner:

```python
def _clean_optional_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""
```

And replaced all unsafe date `.strip()` accesses within Stage C date conflict detection:
1. `dt = _clean_optional_text(d.get("date"))`
2. `select_opposing_pair(internal_list, lambda x: _clean_optional_text(x.get("date")))`
3. `select_opposing_pair(cross_candidates, lambda x: _clean_optional_text(x.get("date")), source_fn=..., require_different_sources=True)`

### Key Invariants Maintained:
- `None`, missing key, empty string `""`, and whitespace-only `"   "` all resolve cleanly to `""`.
- An empty string is treated as having no comparable conflict value (`if dt:` evaluates to `False`) and is safely excluded from conflict evaluation.
- Does NOT convert `None` to the string `"None"`.
- Does NOT invent dates.
- Does NOT mutate `normalized_facts`.
- Does NOT drop or rewrite source evidence.
- Preserves all existing valid date conflict semantics (different semantic milestones are not conflicts, identical valid dates are not conflicts, distinct valid dates across physical documents produce `TRUE_CONFLICT`, differing dates in the same document produce `REVIEW_ITEM`).

---

## 4. Tests Added

Added dedicated test class `TestStageCDateNullSafety` to `tests/test_stage_c_refinement.py` covering tests A through H:

| Test | Name | Scenario | Expected Result |
|---|---|---|---|
| **A** | `test_null_date_does_not_crash_no_conflict` | `date=None` | No exception, 0 conflicts |
| **B** | `test_missing_date_key_does_not_crash_no_conflict` | missing `"date"` key | No exception, 0 conflicts |
| **C** | `test_blank_date_does_not_crash_no_conflict` | `date=""` | No exception, 0 conflicts |
| **D** | `test_whitespace_date_does_not_crash_no_conflict` | `date="   \t\n  "` | No exception, 0 conflicts |
| **E** | `test_null_date_alongside_valid_date_no_false_conflict` | `None` alongside `"2026-10-01"` | No false conflict, valid date remains usable |
| **F** | `test_two_valid_identical_dates_no_conflict` | `"2026-10-01"` vs `"2026-10-01"` | 0 conflicts |
| **G** | `test_two_valid_differing_dates_across_physical_docs_conflict` | `"2026-10-01"` vs `"2026-10-15"` across docs | 1 `TRUE_CONFLICT` (`PHYSICAL_BOTH`) |
| **H** | `test_internal_valid_differing_dates_review_item` | `"2026-10-01"` vs `"2026-10-15"` same doc | 1 `REVIEW_ITEM` |

---

## 5. Regression Results

### Discovered Suites:
```
================================================================================
FULL REGRESSION SUITE RUN
================================================================================
1. tests/test_stage_c_refinement.py:                68 /  68 PASSED (+8 new tests)
2. tests/test_streamlined_workflow.py:              27 /  27 PASSED
3. tests/test_stage_d_completeness.py:              52 /  52 PASSED
4. tests/test_submission_document_provenance.py:    75 /  75 PASSED
5. tests/test_submit_state_consistency.py:          17 /  17 PASSED
6. tests/integration/:                              6 discovered / 5 passed / 1 skipped (live AI)
7. tests/smoke/ + live Supabase:                   12 /  12 PASSED
================================================================================
TOTAL DISCOVERED:                                 257
TOTAL PASSED:                                     256
TOTAL SKIPPED:                                      1 (live AI integration)
TOTAL FAILED / ERRORS:                              0
================================================================================
```

---

## 6. Confirmations & Scope Boundaries

1. **No Tender-Specific Logic Introduced:**
   - The fix is a universal, deterministic null-safety guard (`_clean_optional_text()`) for optional date fields in dictionaries.
   - No British Council tender IDs, file names, or patterns were introduced.

2. **Acceptance Test #2 Attempt 1 Artifacts Preserved Byte-for-Byte:**
   - `BRITISH_COUNCIL_IR67TVET42026_BLIND_EXECUTION_REPORT.md` remains intact as the unedited historical record of Attempt 1.
   - `tests/acceptance/BRITISH_COUNCIL_IR67TVET42026_INPUT_MANIFEST.md` remains intact.

3. **No Source Benchmarking Performed:**
   - The British Council source documents were NOT inspected for expected answers, scoring, or requirements.
   - Bank of Canada acceptance fixtures and RC1 tag (`dfa934d55ca6d2a5a460866193a62a49f57c585f`) remain frozen and intact.

4. **No Database Changes:**
   - No migration files created (no Migration 004).
   - Live Supabase schema unmodified.