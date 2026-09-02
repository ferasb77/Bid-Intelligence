# Submit State Consistency Report

**Branch:** `fix/submit-state-consistency`  
**Base:** `main` at `7043c7eb0fccc5ae0ccee9db7c13f23b89a7d27e`  
**Date:** 2026-09-02  

---

## 1. Executive Summary & Original Contradictions

Stage 5 (SUBMIT) previously suffered from multiple architectural and presentation contradictions:

1. **Mandatory Qualification UNKNOWN Contradiction:**
   - The top banner displayed `READY WITH WARNINGS (Unverified Gates)` when mandatory requirements had `qual_status == 'UNKNOWN'`.
   - Meanwhile, the blocker list lower on the page flagged them as critical blockers preventing submission.

2. **Document Mandatory UNKNOWN Contradiction:**
   - When a submission document had `mandatory=None`, the top banner displayed `READY WITH WARNINGS`.
   - However, it was not added to critical blockers, allowing users to believe the gate was permissive, even though omission might disqualify the bid.

3. **Temporal Attestation Inversion:**
   - The top banner was calculated and rendered *before* the four human attestation checkboxes.
   - Consequently, the banner displayed `READY TO SUBMIT` while the final submission button at the bottom remained disabled with blockers because attestations were unchecked.

4. **Coerced Mandatory Representation in AI Check:**
   - `submission_readiness_check()` in `analyst.py` coerced `bool(d.get("mandatory"))`, collapsing `None` (UNKNOWN) into `False` (OPTIONAL).

This branch completely resolves these contradictions by introducing a pure deterministic submission state evaluator as the single source of truth.

---

## 2. Deterministic State Evaluator Architecture

The pure helper `evaluate_submission_state()` is defined in `evaluator.py`:

```python
evaluate_submission_state(
    requirements: list[dict[str, Any]] | None,
    documents: list[dict[str, Any]] | None,
    attestations: dict[str, bool] | None,
    warnings: list[str] | None = None,
) -> dict[str, Any]
```

It returns an authoritative dictionary:
```json
{
    "status": "NOT_READY" | "READY_WITH_WARNINGS" | "READY_TO_SUBMIT",
    "can_submit": true | false,
    "blockers": [...],
    "warnings": [...],
    "counts": {
        "mandatory_requirements": int,
        "mandatory_pass": int,
        "mandatory_fail": int,
        "mandatory_unknown": int,
        "required_documents": int,
        "required_documents_ready": int,
        "required_documents_missing": int,
        "unknown_document_mandatory": int,
        "unchecked_attestations": int
    }
}
```

### Strict Status Invariants
- `if blockers:` `status = "NOT_READY"`, `can_submit = False`
- `elif warnings:` `status = "READY_WITH_WARNINGS"`, `can_submit = True`
- `else:` `status = "READY_TO_SUBMIT"`, `can_submit = True`

There are **zero conditions** where:
- `status == "READY_WITH_WARNINGS"` and `can_submit == False`
- `status == "READY_TO_SUBMIT"` and `can_submit == False`

---

## 3. Explicit Blocker vs. Warning Doctrine

### Blockers:
1. **Mandatory Qualification Gate FAIL:** Any mandatory requirement with `qual_status == "FAIL"`.
2. **Mandatory Qualification Gate UNKNOWN / Unverified:** Any mandatory requirement with `qual_status in ("UNKNOWN", None, "")` or missing `qual_status`. UNKNOWN represents unresolved evidence, not an advisory warning.
3. **Required Submission Document Missing:** Any required submission document (`mandatory` in `(1, True, "1", "true")`) whose status is not in `{"Uploaded", "Approved", "Complete", "Submitted"}`.
4. **Submission Document with UNKNOWN Mandatory Status:** Any document whose mandatory status is `None`. Since the system cannot know if omission is fatal, it must be resolved prior to submission.
5. **Unchecked Pre-Submission Attestation:** Any of the four required human attestations that is unchecked (`False`):
   - Proposal formatting and separation verified
   - Mandatory qualification criteria verified PASS
   - Tender addenda and bulletins acknowledged
   - Authorized executive sign-off confirmed

### Warnings (Non-Blocking):
`READY_WITH_WARNINGS` strictly requires `can_submit == True`, `len(blockers) == 0`, and `len(warnings) > 0`. Non-blocking warnings represent quality advisories or polish notes, not unresolved compliance facts.

---

## 4. Human Resolution of UNKNOWN Mandatory Documents

For any submission document whose mandatory status is unestablished (`mandatory=None`), a human resolution interface is provided directly in Stage 5:

- Surfaces prompt: `"Requirement status not established from source evidence. Please classify:"`
- Provides actions: `[Mark Required]` and `[Mark Optional]`.
- Persists resolution directly to the existing `documents.mandatory` column using `upsert_document({"id": doc_id, "mandatory": 1 | 0})`.
- **No schema modifications, no Migration 004, no new database columns, and no automated guessing.**

For UNKNOWN mandatory requirements, Stage 5 displays guidance directing the user to Stage 2 (DECIDE) where qualification status is governed, preserving Stage 5 as a strict gatekeeper rather than a duplicate qualification editor.

---

## 5. UI Reorganization & Single Source of Truth

In `pages/stage_submit.py`:
- Checkbox states for the four attestations are captured first.
- `evaluate_submission_state()` is invoked once with `(reqs, docs, attestations)`.
- The top Final Gate banner, blocker breakdown, warning display, and the bottom submission execution button are rendered **exclusively** from the evaluator's returned `status`, `can_submit`, `blockers`, and `counts`.
- The top banner never shows `READY TO SUBMIT` while attestations remain unchecked.
- The advisory AI compliance check (`submission_readiness_check()`) is clearly labeled as an optional quality audit that has no authority over gate readiness or submission execution.
- String and boolean document mandatory values are explicitly formatted in `analyst.py` as `REQUIRED`, `OPTIONAL`, or `UNKNOWN`.

---

## 6. Verification & Test Suite Matrix

A new dedicated test suite `tests/test_submit_state_consistency.py` implements all required test cases A through M:

- **Test A:** Mandatory PASS + required docs ready + all attestations true -> `READY_TO_SUBMIT`, `can_submit=True`
- **Test B:** Mandatory FAIL -> `NOT_READY`, `can_submit=False`
- **Test C:** Mandatory UNKNOWN -> `NOT_READY`, `can_submit=False`
- **Test D:** Mandatory qual_status missing -> `NOT_READY`, `can_submit=False`
- **Test E:** Required document Expected -> `NOT_READY`, `can_submit=False`
- **Test F:** Required document Uploaded/Approved/Complete/Submitted -> no document blocker
- **Test G:** Document mandatory=None -> `NOT_READY`, `can_submit=False`
- **Test H:** Optional document missing/not uploaded -> does NOT block
- **Test I:** All evidence ready but one attestation unchecked -> `NOT_READY`, `can_submit=False`
- **Test J:** Status invariants (`NOT_READY`, `READY_WITH_WARNINGS`, `READY_TO_SUBMIT`) strictly upheld
- **Test K:** Synthetic non-blocking warning with no blockers -> `READY_WITH_WARNINGS`, `can_submit=True`
- **Test L:** Document mandatory resolution persistence (None -> 1, None -> 0)
- **Test M:** Empty submission documents package with all mandatory requirements PASS -> does not invent blocker

### Full Regression Results:
```
================================================================================
FULL REGRESSION SUITE
================================================================================
1. tests/test_stage_c_refinement.py:                60 /  60 PASSED
2. tests/test_streamlined_workflow.py:              27 /  27 PASSED
3. tests/test_stage_d_completeness.py:              52 /  52 PASSED
4. tests/test_submission_document_provenance.py:    75 /  75 PASSED
5. tests/test_submit_state_consistency.py:          13 /  13 PASSED
6. tests/integration/:                              5 /   5 PASSED (1 live AI skipped)
7. tests/smoke/ + live Supabase:                   12 /  12 PASSED
================================================================================
TOTAL DISCOVERED:                                 245
TOTAL PASSED:                                     244
TOTAL SKIPPED:                                      1 (live AI integration)
TOTAL FAILED / ERRORS:                              0
================================================================================
```

---

## 7. Modified Files

| File | Changes |
|---|---|
| `evaluator.py` | New pure deterministic submission state evaluator defining single source of truth for gate status, blocker aggregation, and invariants. |
| `pages/stage_submit.py` | Unified Stage 5 rendering from evaluator, eliminated attestation race condition, and added human resolution UI for UNKNOWN document mandatory status. |
| `analyst.py` | Corrected mandatory representation in `submission_readiness_check()` to explicitly distinguish `REQUIRED`, `OPTIONAL`, and `UNKNOWN`. |
| `tests/test_submit_state_consistency.py` | 13 deterministic offline unit tests covering cases A through M. |
| `SUBMIT_STATE_CONSISTENCY_REPORT.md` | Full architecture and verification report. |
