# Stage D Synthesis Completeness Report

**Branch:** `fix/stage-d-synthesis-completeness`  
**Base:** `main` at `4a2eee1e6062c2f29eb94c9c0bc28ddcec2196c3`  
**Date:** 2026-09-02 (updated after review corrections)

---

## 1. Original Defect

`synthesize_bid_brief()` built the Stage D context with:

```python
"requirements_sample": [r.get("description", "")[:150]
                         for r in normalized_facts.get("requirements", [])[:15]]
```

Two compounding truncations: `[:15]` list slice (only 15 of 98 requirements reached Stage D) and `[:150]` description truncation. No error was raised. Silent omission.

---

## 2. Stage D Context Model

### 2.1 `build_stage_d_context(normalized_facts, conflicts) -> dict`

Deterministic, lossless, strictly integrity-checked context builder.

**Integrity rules (hardened in review correction):**
- `source_requirement_count` is derived from the ORIGINAL `len(requirements)` before any filtering, including non-dict entries.
- Non-dict entries in the requirements list raise `RuntimeError` immediately. Silent exclusion followed by reporting `omitted_requirement_count = 0` is forbidden.
- `all_mandatory_included` and `all_financial_included` are computed from actual source vs included category counts — not hard-coded `True`.

**Size control:** `_EXCERPT_CAP = 500` characters per source_ref excerpt. Caps excerpt prose; never drops requirements from the list.

**Context integrity block:**

```
context_integrity: {
  source_requirement_count:   N,
  included_requirement_count: N,
  counts_by_category:         { ... },
  omitted_requirement_count:  0,
  all_mandatory_included:     computed bool,
  all_financial_included:     computed bool
}
```

### 2.2 Context-Size Preflight (implemented in review correction)

Before the Anthropic API call, `synthesize_bid_brief()` serializes the complete Stage D context to JSON and compares its length against `_STAGE_D_CONTEXT_CHAR_LIMIT = 580_000` characters (conservative safe limit for Claude Haiku's 200k-token context window at ~3 chars/token, minus prompt and output reservation).

If the limit is exceeded:

```python
raise StageDContextTooLargeError(
    "Stage D context is complete but too large for safe synthesis. "
    "No requirements were silently omitted. "
    "Source requirement count: N. "
    "Serialized context size: X characters (limit: 580,000 characters). "
    "Reduce excerpt verbosity or split the package before synthesis."
)
```

The API call is **never made** when the preflight fails. The error message explicitly confirms completeness (no silent omission) and states both the source requirement count and the serialized size.

### 2.3 `apply_stage_d_authoritative_sections(synth_data, normalized_facts) -> dict`

Post-synthesis applicator. Deterministically rebuilds evidence-backed structured sections.

**Hardened in review correction:**

1. **Robust brief coercion** — handles `brief = null`, `[]`, `"string"`, `42`, or missing key without crashing. Always produces `brief = {}`.

2. **Material canonical tuple deduplication** — replaced broad single-key dedup with full-field canonical tuples:

| Section | Canonical Key |
|---------|---------------|
| `key_dates` | `(milestone, date, source_doc)` |
| `evaluation_breakdown` | `(stage, weight, threshold, notes, source_doc)` |
| `submission_requirements` | `(item, format, details, mandatory, source_doc)` |
| `commercial_structure` | `(topic, details, source_doc)` |
| `contract_risks` | `(risk_title, severity, details)` |
| `deliverables_summary` | `(title, description, category, source_doc)` |
| `qualification_gates` | `(description, rfso_ref, req_id)` |

Same milestone/stage/topic with **different values** are preserved as distinct entries. Only entries identical on **all** canonical fields are collapsed.

3. **No invented defaults** — `severity` and `category` are omitted from the output entry when absent in normalized facts. `"Medium"` and `"Core"` are never added.

**Sections replaced deterministically:**

| Brief Section             | Derived From                     |
|---------------------------|----------------------------------|
| `qualification_gates`     | ALL Mandatory requirements       |
| `evaluation_breakdown`    | normalized `evaluation_criteria` |
| `submission_requirements` | normalized `submission_rules`    |
| `key_dates`               | normalized `dates`               |
| `commercial_structure`    | normalized `commercial_clauses`  |
| `contract_risks`          | normalized `contract_risks`      |
| `deliverables_summary`    | normalized `deliverables`        |

AI-synthesized interpretation fields preserved: `executive_summary`, `opportunity_type`, `contract_term`, `procurement_model`, `scope_categories`, `source_citations`, all `bid` fields, `outline`.

### 2.4 Updated `STAGE_D_SYNTHESIS_PROMPT`

Added authoritative context contract rules: mandatory gates must not be omitted, `UNKNOWN` must not become `PASS`, conflicts must not be silently resolved, no fact invention.

---

## 3. Bank of Canada Frozen Coverage Replay

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

> Under the original `[:15]` implementation, 83 of 98 requirements (85%) were silently dropped from every Bank of Canada Bid Brief synthesis.

---

## 4. Full Test Matrix

```
================================================================================
FULL REGRESSION + STAGE D TEST SUITE (post-review corrections)
================================================================================
1. tests/test_stage_c_refinement.py:              60 / 60 PASSED
2. tests/test_streamlined_workflow.py:             27 / 27 PASSED
3. tests/test_stage_d_completeness.py:             52 / 52 PASSED
   Scenario 1 - Large Package Context Builder:    17 / 17
   Scenario 2 - Mocked Model-Omission Resilience:  7 /  7
   Scenario 3 - Conflict Coverage:                 2 /  2
   Scenario 4 - BoC Frozen Coverage Replay:        8 /  8
   Scenario 5 - Edge Cases:                        3 /  3
   Scenario 6 - Dedup Regressions A-J:            10 / 10 (NEW)
   Scenario 7 - Context Preflight K:               3 /  3 (NEW)
4. tests/integration/:                             5 /  5 PASSED (1 skipped live AI)
5. tests/smoke/ + live Supabase:                  12 / 12 PASSED
================================================================================
TOTAL TESTS DISCOVERED:                          157
TOTAL PASSED:                                    156
TOTAL SKIPPED:                                     1 (live AI integration)
TOTAL FAILED / ERRORS:                             0
================================================================================
```

**Live AI integration test:** Skipped (requires Anthropic key in test environment). The live AI test is NOT claimed as passed.

---

## 5. Files Changed

| File | Change |
|---|---|
| `extractor.py` | Added `StageDContextTooLargeError`, `_STAGE_D_CONTEXT_CHAR_LIMIT`, context-size preflight in `synthesize_bid_brief()`; hardened `build_stage_d_context()` integrity rules; replaced broad dedup with canonical tuple keys and removed invented defaults in `apply_stage_d_authoritative_sections()`; robust brief coercion |
| `tests/test_stage_d_completeness.py` | Extended from 39 to 52 tests: added Scenario 6 (A-J deduplication regressions) and Scenario 7 (K preflight) |
| `tests/acceptance/results/STAGE_D_BANK_OF_CANADA_COVERAGE_REPLAY.md` | Unchanged |
| `STAGE_D_SYNTHESIS_COMPLETENESS_REPORT.md` | This file (updated) |

Not changed: Stage A, Stage B, Stage C, migrations 001/002/003, database schema, submission gating, five-stage workflow, RC1 tag, frozen Bank of Canada acceptance artifacts, existing Stage C tests.

---

## 6. Known Out-of-Scope Follow-Up

The orchestrator (`extract_procurement_package()`) invents default submission documents (`Technical Proposal.pdf`, `Financial Envelope.pdf`) when normalized submission rules produce no documents. This is explicitly not fixed in this branch per the scope directive. A dedicated follow-up branch is required.
