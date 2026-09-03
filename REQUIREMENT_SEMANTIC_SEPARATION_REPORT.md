# Requirement Semantic Separation Report

**Repository:** `ferasb77/Bid-Intelligence`  
**Branch:** `fix/requirement-semantic-separation`  
**Base Commit:** `39d237527822190da98bb1d6e306c95b26d90ad4`  
**Date:** 2026-09-03  
**Status:** `READY FOR REVIEW`

---

## 1. Executive Summary

British Council Acceptance Test #2 demonstrated that Bid Intelligence previously conflated two distinct procurement concepts:

1. **Mandatory** (`category == "Mandatory"`) — Describes whether compliance is compulsory (i.e. not optional or rated).
2. **Supplier Qualification Gate** — Describes pass/fail bidder eligibility, legal standing, financial standing, certifications, OEM authorization, and conditions of participation that determine whether the vendor is legally and operationally qualified to bid.

A procurement solicitation contains mandatory items across multiple functional domains:
- Supplier eligibility / qualification conditions
- Technical specifications
- Submission instructions and checklists
- Delivery obligations and SLAs
- Commercial, liability, and contract terms
- General mandatory compliance obligations

Under the previous implementation, all 35 mandatory requirements in the British Council procurement package were treated as qualification gates on the DECIDE and CHECK pages. This led to false alarms where technical specifications (e.g. 75" LED display 4K UHD) and submission checklist forms were counted as supplier qualification blockers.

This branch introduces orthogonal semantic typing (`requirement_type`) across Stage A, Stage B, and Stage D, confines `qualification_gates` to genuine supplier qualification requirements, preserves full mandatory blocking at the submission gate (`SUBMIT`), and creates clear separation throughout the user interface.

---

## 2. Core Architectural Principles & Scope Boundaries

### 2.1 Decoupling Category from Requirement Type
- `category` continues to use the existing controlled enum:
  - `Mandatory`
  - `Rated`
  - `Financial`
  - `Supporting`
- `requirement_type` is an orthogonal controlled enum:
  - `Supplier Qualification`: Genuine pass/fail bidder eligibility, legal standing, financial standing, certifications, OEM authorizations, required references, conditions of participation.
  - `Technical Specification`: Property or characteristic of the offered solution, product, technology, or technical response.
  - `Submission Compliance`: Forms, signatures, packaging, portal, formats, attachments, submission checklists.
  - `Delivery / SLA`: Implementation, response times, maintenance, uptime, training, delivery obligations.
  - `Commercial / Contractual`: Pricing mechanics, payment, insurance during contract, liability, IP, terms.
  - `Evaluation / Scored`: Scored/rated criteria or scoring mechanics.
  - `General Compliance`: Mandatory obligations that do not safely fit the above.

### 2.2 DECIDE vs. SUBMIT Separation
- **DECIDE Stage Qualification Gating is Narrowed:**
  - `qualification_gates` in the Bid Brief and DECIDE KPI cards now evaluate **only** requirements where:
    $$\text{category} == \text{"Mandatory"} \quad \land \quad \text{requirement\_type} == \text{"Supplier Qualification"}$$
  - The DECIDE matrix is renamed to **Requirement Assessment Matrix**, displaying all mandatory and scored requirements with semantic type badges without mislabeling technical specs as qualification gates.
- **SUBMIT Compliance Remains Strict:**
  - `evaluate_submission_state()` in `pages/stage_submit.py` was **not weakened**. All mandatory requirements (technical, submission, SLA, commercial) must still achieve `PASS` to enable proposal submission.

### 2.3 Database Integrity (No Migration 004)
- No database migration was introduced. The schema remains at Migration 003.
- No `requirement_type` database column was added.
- The semantic typing is preserved across Stage A, Stage B, and Stage D normalized models, and persisted indirectly via `bid_briefs.qualification_gates` JSON.

---

## 3. Implementation Details

### 3.1 New Semantic Helper Module: `requirement_semantics.py`
Defined in [`requirement_semantics.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/requirement_semantics.py):
- `ALLOWED_REQUIREMENT_TYPES`: Tuple of the 7 canonical types.
- `normalize_requirement_type(raw_type)`: Robust string normalization.
- `resolve_requirement_type(requirement)`: Deterministic resolution. If unclassified, applies conservative fallback:
  - `category in ("Rated", "Evaluation")` resolves to `Evaluation / Scored`.
  - Only explicit bidder eligibility/qualification cues (e.g. `conditions of participation`, `minimum qualifications`, `supplier eligibility`, `financial standing`, `oem authorization`) resolve to `Supplier Qualification`.
  - Generic modal words (`must`, `shall`, `mandatory`) do **not** default to `Supplier Qualification`; they default conservatively to `General Compliance`.
- `is_supplier_qualification(requirement)`: Evaluates `category == "Mandatory"` and resolved `requirement_type == "Supplier Qualification"`.
- `normalize_requirement_identity_text(text)`: Produces canonical alphanumeric keys (`\W+` stripped, lowercased).
- `select_qualification_requirements(requirements, qualification_gates)`: Matches authoritative qualification gates from `bid_briefs` back to persisted database requirement rows using full normalized description text. If `qualification_gates` is empty, returns `[]` (never falls back to all mandatory requirements).

### 3.2 Stage A Fact Extraction Prompt (`extractor.py`)
- Updated `STAGE_A_FACT_EXTRACTION_PROMPT` in [`extractor.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/extractor.py) with explicit rules distinguishing `category` from `requirement_type` with concrete examples.
- Updated `aggregate_stage_a_facts()`:
  - Deduplication key remains `(norm_desc, cat.lower(), rfso.lower())` — distinct requirements sharing prefixes or local IDs are preserved.
  - Resolves and preserves `requirement_type` on all merged requirements.

### 3.3 Stage B Package Normalization (`extractor.py`)
- Updated `normalize_package_facts()` in [`extractor.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/extractor.py):
  - Preserves `requirement_type` on all normalized requirement records.
  - Requirement identity continues to use the full normalized description without truncation. `requirement_type` is not used in the deduplication key.

### 3.4 Stage D Synthesis & Authoritative Rebuild (`extractor.py`)
- Updated `STAGE_D_SYNTHESIS_PROMPT` in [`extractor.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/extractor.py):
  - Informs Claude that `Mandatory` != qualification gate, and that `qualification_gates` must contain only pass/fail bidder eligibility conditions.
- Updated `_compact_requirement()`:
  - Added `"requirement_type"` to `_REQUIREMENT_FIELDS` so Stage D synthesis context includes semantic types.
- Updated `apply_stage_d_authoritative_sections()`:
  - Replaced the previous `qualification_gates` rebuild (which took all mandatory requirements) with:
    ```python
    qual_reqs = [r for r in all_reqs if is_supplier_qualification(r)]
    ```
  - Only requirements meeting both `category == Mandatory` and `is_supplier_qualification(r)` are placed into `qualification_gates`.
  - Sets gate `type` to `"Supplier Qualification"`.

### 3.5 Stage 1: UNDERSTAND (`pages/stage_understand.py`)
- Section C ("Conditions to Qualify") now resolves qualification gates by matching `brief_row.get("qualification_gates")` against persisted requirement rows using `select_qualification_requirements()`.
- Removed fallback that converted `mand[:8]` into qualification gates.
- When no qualification gates are identified, displays a clear informational empty state:
  > *"No explicit pass/fail supplier qualification gates were identified. Mandatory compliance requirements remain tracked in the compliance register."*

### 3.6 Stage 2: DECIDE (`pages/stage_decide.py` & `analyst.py`)
- Qualification KPI cards (Qualification Gates, Verified PASS, Concerns / Risks, Blockers) and hard-gate warnings evaluate **only** requirements matched to `qualification_gates`.
- Tab 1 renamed from `"🛡️ Hard-Gate Qualification Matrix"` to `"🛡️ Requirement Assessment Matrix"`.
- Matrix table includes semantic type subtitle under category (e.g. `Mandatory` / `Technical Specification`).
- Updated `bid_no_bid_score()` in [`analyst.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/analyst.py):
  - Accepts optional `qualification_requirements` argument.
  - Prompt strictly separates `TRUE SUPPLIER QUALIFICATION GATES (Pass/Fail Bidder Eligibility)` from `OTHER PROCUREMENT REQUIREMENTS (Technical, Submission, SLA, Commercial, Scored)`.

### 3.7 Stage 4: CHECK (`pages/stage_check.py`)
- Split readiness score strip into two distinct metrics:
  - **Qualification Gates**: Evaluates status of true pass/fail qualification gates.
  - **Mandatory Compliance**: Evaluates overall compliance across all mandatory procurement requirements.
  - Separate cards for **Qualification FAILs** (hard disqualification blockers) and **Unverified Mandatory** (needs evidence before submit).

---

## 4. Benchmark Replay & Empirical Results

### 4.1 Synthetic Rebuild Separation Verification
In unit tests ([`tests/test_requirement_semantic_separation.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/tests/test_requirement_semantic_separation.py)):
- A normalized fact package containing 7 mandatory requirements representing each semantic type (Supplier Qualification, Technical Specification, Submission Compliance, Delivery / SLA, Commercial / Contractual, Evaluation / Scored, General Compliance) was processed through `apply_stage_d_authoritative_sections()`.
- **Result:** Exactly **1** qualification gate was generated (`M1` - Supplier Qualification), while all 7 requirements were preserved in the complete normalized facts and requirements register.

### 4.2 British Council Benchmark Analysis
Analyzing the 41 frozen requirements from British Council Attempt 2:
- Total Extracted Requirements: 41
- Total Mandatory Requirements: 35
- Total Scored/Rated Requirements: 6
- Semantic Breakdown:
  - `Evaluation / Scored`: 6
  - `Submission Compliance`: 8 (e.g. Submission checklists, signed Annex 3 tender response, pricing template submission)
  - `General Compliance / Technical Specs / Delivery`: 27 (e.g. Smart interactive screen specifications, LMS compatibility, pricing format instructions, terms and conditions)
- Under the previous implementation, all 35 mandatory requirements were surfaced as qualification gates in DECIDE. Under the new semantic separation:
  - Only genuine supplier qualification conditions populate `qualification_gates`.
  - All 35 mandatory requirements remain compulsory in the requirements register and must be verified before submission in Stage 5.

---

## 5. Verification & Test Coverage

### 5.1 New Dedicated Test Suite
[`tests/test_requirement_semantic_separation.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/tests/test_requirement_semantic_separation.py) (13 tests):
- `test_allowed_types_contains_all_seven_types`
- `test_stage_a_prompt_defines_requirement_type`
- `test_stage_d_prompt_separates_mandatory_from_qualification`
- `test_compact_requirement_preserves_requirement_type`
- `test_normalize_requirement_type_variants`
- `test_normalize_requirement_type_invalid_returns_none`
- `test_mandatory_alone_does_not_default_to_supplier_qualification`
- `test_strong_eligibility_cues_resolve_to_supplier_qualification`
- `test_rated_category_is_never_supplier_qualification`
- `test_only_supplier_qualification_mandatory_becomes_qualification_gate`
- `test_select_qualification_requirements_matching`
- `test_select_qualification_requirements_empty_gates_returns_empty`
- `test_select_qualification_requirements_does_not_match_non_mandatory`

### 5.2 Full Regression Test Suite Results
- `tests/test_requirement_semantic_separation.py`: **13 / 13 passed**
- `tests/test_stage_d_completeness.py`: **52 / 52 passed**
- `tests/test_stage_a_extraction_reliability.py`: **20 / 20 passed**
- `tests/test_stage_b_requirement_dedup_integrity.py`: **8 / 8 passed**
- Full unit test discovery (`tests/test_*.py`): **280 / 280 passed**
- Smoke test suite (`tests/smoke/`): **12 / 12 passed**
- Integration test suite (`tests/integration/`): **6 discovered / 5 passed / 1 skipped (live AI)**
- **Grand Total:** **298 discovered / 297 passed / 1 skipped / 0 failed**

---

## 6. Git Branch & Commit

- Current Branch: `fix/requirement-semantic-separation`
- Files Created:
  - `requirement_semantics.py`
  - `tests/test_requirement_semantic_separation.py`
  - `REQUIREMENT_SEMANTIC_SEPARATION_REPORT.md`
- Files Modified:
  - `extractor.py`
  - `analyst.py`
  - `pages/stage_understand.py`
  - `pages/stage_decide.py`
  - `pages/stage_check.py`
  - `tests/test_stage_d_completeness.py`
