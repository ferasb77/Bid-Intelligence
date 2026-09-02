# Stage D Synthesis Completeness Report

**Branch:** `fix/stage-d-synthesis-completeness`  
**Base:** `main` at `4a2eee1e6062c2f29eb94c9c0bc28ddcec2196c3`  
**Date:** 2026-09-02

---

## 1. Original Defect

`synthesize_bid_brief()` built the Stage D context with:

```python
"requirements_sample": [r.get("description", "")[:150]
                         for r in normalized_facts.get("requirements", [])[:15]]
```

### Root Cause

Two compounding truncations:

| Truncation | Effect |
|---|---|
| `[:15]` list slice | Only the first 15 requirements reached Stage D |
| `[:150]` description truncation | Even those 15 lost most of their prose |

For the Bank of Canada package (98 requirements):
- **83 requirements (85%) were silently omitted** from every Stage D synthesis.
- Mandatory requirements at positions 16-48 never reached the executive Bid Brief.
- No error was raised. The AI received a partial model and produced a partial brief.

---

## 2. Previous Behavior Summary

```
normalized_facts.requirements  ->  98 items
                                        | [:15]
synthesize_bid_brief context   ->  15 items (description[:150] each)
                                        |
Stage D AI context             ->  ~13% of procurement facts
                                        |
Bid Brief                      ->  silently incomplete
```

---

## 3. New Stage D Context Model

### 3.1 `build_stage_d_context(normalized_facts, conflicts) -> dict`

Deterministic, lossless context builder. No list slicing. No requirement truncation.

**Output structure:**

```
{
  "metadata":            { ... },
  "requirements": {
    "mandatory":         [ all Mandatory reqs ],
    "financial":         [ all Financial reqs ],
    "rated":             [ all Rated reqs ],
    "supporting":        [ all Supporting reqs ],
    "other":             [ any uncategorised reqs ]  # only if present
  },
  "dates":               [ ... ],
  "evaluation_criteria": [ ... ],
  "submission_rules":    [ ... ],
  "deliverables":        [ ... ],
  "commercial_clauses":  [ ... ],
  "contract_risks":      [ ... ],
  "detected_conflicts":  [ ... ],
  "context_integrity": {
    "source_requirement_count":   N,
    "included_requirement_count": N,
    "counts_by_category":         { ... },
    "omitted_requirement_count":  0,
    "all_mandatory_included":     true,
    "all_financial_included":     true
  }
}
```

**Size control:** `_EXCERPT_CAP = 500` characters per source_ref excerpt. Excerpt cap controls prompt size without dropping requirements. If a future package genuinely exceeds supported context after safe compaction, `build_stage_d_context()` raises `RuntimeError` rather than silently producing a partial context.

**Per-requirement fields preserved:**  
`req_id`, `category`, `description`, `rfso_ref`, `weight`, `evidence`,  
`source_refs` (`source_doc`, `page`, `sheet`, `section`, `excerpt`),  
`qual_status`, `evidence_status`.  
No values invented. `qual_status` and `evidence_status` passed through unchanged.

### 3.2 `apply_stage_d_authoritative_sections(synth_data, normalized_facts) -> dict`

Post-synthesis applicator. After the AI returns its brief, deterministically rebuilds evidence-backed structured sections from normalized facts:

| Brief Section             | Derived From                     |
|---------------------------|----------------------------------|
| `qualification_gates`     | ALL Mandatory requirements       |
| `evaluation_breakdown`    | normalized `evaluation_criteria` |
| `submission_requirements` | normalized `submission_rules`    |
| `key_dates`               | normalized `dates`               |
| `commercial_structure`    | normalized `commercial_clauses`  |
| `contract_risks`          | normalized `contract_risks`      |
| `deliverables_summary`    | normalized `deliverables`        |

AI-synthesized interpretation fields preserved unchanged: `executive_summary`, `opportunity_type`, `contract_term`, `procurement_model`, `scope_categories`, `source_citations`, all `bid` fields, `outline`.

### 3.3 Updated `synthesize_bid_brief()`

Calls `build_stage_d_context()` then `apply_stage_d_authoritative_sections()`. The `[:15]` and `[:150]` truncations are removed.

### 3.4 Updated `STAGE_D_SYNTHESIS_PROMPT`

Added explicit contract rules:
- Context is the authoritative normalized procurement model.
- Mandatory requirements are hard gates; must not be omitted from reasoning.
- `qual_status = UNKNOWN` must not be converted to PASS.
- Detected conflicts (TRUE_CONFLICT and REVIEW_ITEM) must remain unresolved unless the source model explicitly resolves them.
- Do not invent submission documents, certifications, clearances, or pricing facts.

---

## 4. Stage D Coverage Verification

### 4.1 Large Synthetic Package (90 requirements)

| Category    | Supplied | Included | Omitted |
|-------------|---------|---------|--------|
| Mandatory   | 40      | 40      | 0      |
| Rated       | 25      | 25      | 0      |
| Financial   | 5       | 5       | 0      |
| Supporting  | 20      | 20      | 0      |
| **Total**   | **90**  | **90**  | **0**  |

- M16 (first requirement beyond old [:15] limit): **present** ✓
- M40 (last mandatory): **present** ✓
- R25 (last rated): **present** ✓
- F5 (last financial): **present** ✓
- S20 (last supporting): **present** ✓
- `omitted_requirement_count`: **0** ✓
- `all_mandatory_included`: **True** ✓
- `all_financial_included`: **True** ✓

### 4.2 Mocked Model-Omission Test

The AI was mocked to return only 1 `qualification_gate` for a package with 20 Mandatory requirements.

After `apply_stage_d_authoritative_sections()`:
- `qualification_gates` count: **20** (all mandatory) ✓
- All M1-M20 `req_id` values present in gates ✓
- `evaluation_breakdown` populated from normalized criteria ✓
- `submission_requirements` populated from normalized rules ✓
- `key_dates` populated from normalized dates ✓
- AI interpretation fields preserved unchanged ✓

### 4.3 Conflict Coverage

Package with both `TRUE_CONFLICT` and `REVIEW_ITEM` records:
- Both conflict classifications present in Stage D context ✓
- `REVIEW_ITEM` records not silently dropped ✓

---

## 5. Bank of Canada Frozen Coverage Replay

**Fixture:** `tests/acceptance/results/boc_2026_026_normalized_facts.json`  
**Stage A, B, C:** NOT re-run. **Anthropic:** NOT called.

| Category    | Source Count | Stage D Included | Omitted |
|-------------|-------------|-----------------|--------|
| Mandatory   | 48          | 48              | 0      |
| Financial   | 1           | 1               | 0      |
| Rated       | 39          | 39              | 0      |
| Supporting  | 10          | 10              | 0      |
| **Total**   | **98**      | **98**          | **0**  |

- Last requirement `R6` (Rated): **FOUND** ✓
- Requirement at position 16 `R4` (Rated): **FOUND** ✓
- `omitted_requirement_count`: **0** ✓
- `counts_by_category` accurate for all 4 categories ✓

**Verdict: PASS**

> Under the previous implementation, only 15 of 98 requirements reached Stage D. 83 requirements (85%) were silently dropped from every Bank of Canada Bid Brief synthesis.

---

## 6. Full Test Matrix

```
================================================================================
FULL REGRESSION + STAGE D TEST SUITE EXECUTION SUMMARY
================================================================================
1. tests/test_stage_c_refinement.py:              60 / 60 PASSED  (0.021s)
2. tests/test_streamlined_workflow.py:             27 / 27 PASSED  (0.257s)
3. tests/test_stage_d_completeness.py:             39 / 39 PASSED  (0.025s)
   Scenario 1 - Large Package Context Builder:    17 / 17 PASSED
   Scenario 2 - Mocked Model-Omission Resilience:  7 /  7 PASSED
   Scenario 3 - Conflict Coverage:                 2 /  2 PASSED
   Scenario 4 - BoC Frozen Coverage Replay:        8 /  8 PASSED
   Scenario 5 - Edge Cases:                        3 /  3 PASSED
4. tests/integration/:                             5 /  5 PASSED  (1 skipped live AI)
5. tests/smoke/ + live Supabase:                  12 / 12 PASSED  (63.076s)
================================================================================
TOTAL TESTS DISCOVERED:                          144
TOTAL PASSED:                                    143
TOTAL SKIPPED:                                     1 (Live AI integration smoke)
TOTAL FAILED / ERRORS:                             0
================================================================================
```

**Live AI integration test:** Skipped (requires Anthropic key in test environment). The live AI test is NOT claimed as passed.

---

## 7. Files Changed

| File | Change |
|---|---|
| `extractor.py` | Added `_compact_requirement()`, `build_stage_d_context()`, `apply_stage_d_authoritative_sections()`; updated `synthesize_bid_brief()` and `STAGE_D_SYNTHESIS_PROMPT` |
| `tests/test_stage_d_completeness.py` | New — 39 Stage D completeness tests |
| `tests/acceptance/results/STAGE_D_BANK_OF_CANADA_COVERAGE_REPLAY.md` | New — BoC coverage replay report |
| `STAGE_D_SYNTHESIS_COMPLETENESS_REPORT.md` | This file |

Not changed: Stage A, Stage B, Stage C, all migrations (001/002/003), database schema, submission gating, five-stage workflow, RC1 tag, frozen Bank of Canada acceptance artifacts, existing Stage C tests.

---

## 8. Known Out-of-Scope Follow-Up

The orchestrator (`extract_procurement_package()`) currently contains a fallback that creates default submission documents when normalized submission rules produce no documents:

```python
# If no documents generated, create standard default package items
if not documents:
    documents = [
        {"name": "Technical Proposal.pdf", "doc_type": "Submission", ...},
        {"name": "Financial Envelope.pdf",  "doc_type": "Financial",  ...}
    ]
```

This invents document names when no real submission rules are normalized. It is explicitly **not fixed in this branch** per the scope directive.

**Follow-up action required:** Remove or replace the invented default submission document fallback in a dedicated subsequent branch.
