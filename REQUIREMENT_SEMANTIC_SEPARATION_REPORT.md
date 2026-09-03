# Requirement Semantic Separation Report

**Repository:** `ferasb77/Bid-Intelligence`  
**Branch:** `fix/requirement-semantic-separation`  
**Base Commit:** `39d237527822190da98bb1d6e306c95b26d90ad4`  
**Date:** 2026-09-03  
**Status:** `READY FOR FINAL REVIEW`

---

## 1. Executive Summary

British Council Acceptance Test #2 demonstrated that Bid Intelligence previously conflated two distinct procurement concepts:

1. **Mandatory** (`category == "Mandatory"`) — Describes whether compliance is compulsory (i.e. not optional or rated).
2. **Supplier Qualification Gate** — Describes pass/fail bidder eligibility, legal standing, financial standing, certifications, OEM authorization, and conditions of participation that determine whether the vendor is legally and operationally qualified to bid.

A procurement package contains mandatory requirements across multiple functional domains:
- Supplier eligibility / qualification conditions
- Technical specifications
- Submission instructions and checklists
- Delivery obligations and SLAs
- Commercial, liability, and contract terms
- General mandatory compliance obligations

Under the previous implementation, all 35 mandatory requirements in the British Council procurement package were treated as qualification gates on the DECIDE and CHECK pages. This led to false alarms where technical specifications (e.g. 75" LED display 4K UHD) and submission checklist forms were counted as supplier qualification blockers.

This branch introduces orthogonal semantic typing (`requirement_type`) across Stage A, Stage B, and Stage D, confines `qualification_gates` strictly to genuine supplier qualification requirements, preserves full mandatory blocking at the submission gate (`SUBMIT`), ensures conflict-safe, order-independent semantic type merging, provides exact description-based gate matching, and creates clear separation throughout the user interface.

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

## 3. Implementation Details & Pre-PR Remediations

### 3.1 Conservative Type Normalization (`requirement_semantics.py`)
- Removed arbitrary substring matching from `normalize_requirement_type()`.
- Accepts only:
  - Exact canonical enum values (case-insensitive, normalized whitespace/separators)
  - Explicit exact aliases from `_EXACT_ALIAS_MAP`
- Ambiguous compounds (such as `Technical Qualification`, `Qualification / Technical`, `Submission Qualification`, `Commercial Qualification`, `Random Qualification String`) strictly return `None` rather than guessing `Supplier Qualification`.

### 3.2 Conflict-Safe Semantic Merging (`merge_requirement_types`)
- Implemented `merge_requirement_types(current_type, incoming_type)` in [`requirement_semantics.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/requirement_semantics.py):
  - Same canonical specific types $\rightarrow$ preserve type.
  - `None` / `General Compliance` + specific $\rightarrow$ preserve specific.
  - Specific + `None` / `General Compliance` $\rightarrow$ preserve specific.
  - Two **different** specific types (e.g. `Supplier Qualification` + `Technical Specification`) $\rightarrow$ `General Compliance`.
  - Strictly commutative and order-independent:
    $$\text{merge}(A, B) == \text{merge}(B, A) \quad \forall A, B$$
- Applied consistently across Stage A chunk aggregation and Stage B package normalization in [`extractor.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/extractor.py).

### 3.3 Exact Qualification Gate Matching (`select_qualification_requirements`)
- Removed fuzzy substring matching from `select_qualification_requirements()`.
- Uses full normalized description identity (`normalize_requirement_identity_text`).
- Shorter gate descriptions that happen to be substrings of unrelated longer mandatory requirements strictly result in **no match**.

### 3.4 Zero-Gate UI State (`get_qualification_gate_ui_alert`)
- When `q_total == 0` in Stage 2 (DECIDE), the console never displays `"ALL QUALIFICATION GATES VERIFIED"`.
- Instead, it renders a neutral informational state:
  > *"No explicit pass/fail supplier qualification gates were identified. Mandatory compliance requirements remain tracked separately."*

### 3.5 Bid / No-Bid Requirement Partition (`analyst.py`)
- In `bid_no_bid_score()`, requirements are partitioned using database `id` when present, or normalized material description identity when no database ID exists.
- Does not use `req_id` alone. Requirements sharing the same `req_id` (e.g. `M1` Supplier Qualification and `M1` Technical Specification) are correctly partitioned without collision.

### 3.6 Authoritative Stage D Rebuild & Stale Documentation Correction
- In [`extractor.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/extractor.py), corrected the post-synthesis authoritative rebuild docstring:
  - Previously stated: `qualification_gates <- ALL Mandatory requirements`
  - Now accurately states: `qualification_gates <- Mandatory Supplier Qualification requirements only`

---

## 4. Current British Council Production Replay (Stage A → B → D)

A complete live benchmark replay was executed through the production pipeline using current Anthropic API configuration on the frozen British Council package:
- Primary ITT: `itt_-_ir67tvet42026_-_smart_classroom_setup_-_updated.pdf` (60,210 chars)
- Annex 2 PSQ: `annex_2_-_procurement_specific_questionnaire_1.docx` (24,452 chars)

### 4.1 Replay Execution Statistics
- **Stage A Execution Time:** 679.66s
- **Stage B Execution Time:** 0.0514s
- **Stage C Execution Time:** 0.0184s
- **Stage D Execution Time:** 91.58s
- **Total Pipeline Execution Time:** 771.31s (~12.8 minutes)

### 4.2 Requirement Counts & Semantic Breakdown
- **Total Extracted Requirements:** 148
  - `Mandatory`: 138
  - `Rated`: 4
  - `Financial`: 0
  - `Supporting`: 6
- **Semantic Type Distribution:**
  - `Supplier Qualification`: 30
  - `Technical Specification`: 7
  - `Submission Compliance`: 47
  - `Delivery / SLA`: 15
  - `Commercial / Contractual`: 11
  - `Evaluation / Scored`: 4
  - `General Compliance`: 34
- **Authoritative `qualification_gates` Count:** **30** (Exactly matches the 30 Mandatory Supplier Qualification requirements; strict semantic subset of the 138 Mandatory requirements).

### 4.3 Verification of Semantic Separation
- **Sample True Qualification Gates in `qualification_gates`:**
  - `M1` (Sec 2.1): *"Vendors must be authorized by the respective OEM, certified, and have demonstrable experience in executing similar comprehensive IT projects."*
  - `M2` (Sec 2.1): *"Vendors must be certified"*
  - `M3` (Sec 2.1): *"Vendors must have demonstrable experience in executing similar comprehensive IT projects"*
  - `M4` (Sec 2.1): *"Suppliers must be eligible and reputable firms"*
  - `M4` (Sec 8.2): *"Vendor must be able to demonstrate proof of authorized Partner/Reseller/Manufacturer status. British Council reserves the right to seek proof in the form of OEM certificates or Manufacturer Authorization letter."*
  - `M1` (Sec 15.1, PSQ Q1): *"Participant must confirm legal eligibility and authorization to perform services in all specified cities (Peshawar, Haripur, D.I Khan, Gilgit, Skardu, Quetta), including compliance with all applicable tax registration and regulatory requirements."*
  - `M3` (Sec 15.1, PSQ Q2): *"Participant must provide valid Original Equipment Manufacturer (OEM) Authorization Letters or equivalent documentary evidence confirming authorization to supply, install, support, and provide warranty services for all proposed solution components."*
  - `M5` (Sec 14, Schedule 7): *"Participant must not be an Excluded or Excludable supplier under Schedule 7 grounds..."*
  - `M8` (Part 3A, Q14): *"Supplier must satisfy minimum financial requirements set as conditions of participation: Operating Profit Margin > 20%; Current Ratio (Liquidity) > 1; Debt Ratio < 0.8."*

- **Sample Mandatory Non-Gates (Tracked in Requirements Register & Blocking at SUBMIT, NOT in Qualification Gates):**
  - `M2` (Submission Compliance): *"Tender responses must comprise the relevant documents specified by the British Council completed in all areas and in the format specified..."*
  - `M3` (Submission Compliance): *"Tender responses may be rejected if they contain gaps, omissions, misrepresentations, errors, uncompleted sections..."*
  - `M4` (Submission Compliance): *"Handwritten amendments must be initialled by the authorised signatory."*
  - `M5` (General Compliance): *"By submitting a tender response, potential suppliers confirm they will comply with all applicable laws, codes of practice..."*
  - `M6` (Commercial / Contractual): *"By submitting a tender response, you are agreeing to be bound by the terms of the ITT and the Contract (Annex 1 - Terms and Conditions)..."*
  - `M7` (General Compliance): *"Tender responses must reflect and confirm full and unconditional compliance with all of the documents issued by the British Council..."*
  - Technical Specifications (e.g. 75" Interactive Flat Panel 4K UHD specifications, LMS compatibility) remain compulsory compliance requirements without being mislabeled as supplier qualification gates.

*Note: As observed in previous staged benchmarks, LLM generation naturally exhibits variance across runs even at `temperature=0.0`. This implementation guarantees structural, deterministic separation and non-destructive preservation; it does not claim complete procurement accuracy.*

---

## 5. Test Coverage & Regression Suite

### 5.1 Expanded Test Suite
[`tests/test_requirement_semantic_separation.py`](file:///C:/Users/feras/Documents/Projects/Bid-Intelligence/tests/test_requirement_semantic_separation.py) (28 tests):
- `test_allowed_types_contains_all_seven_types`
- `test_stage_a_prompt_defines_requirement_type`
- `test_stage_d_prompt_separates_mandatory_from_qualification`
- `test_compact_requirement_preserves_requirement_type`
- `test_normalize_requirement_type_exact_and_aliases`
- `test_ambiguous_type_labels_return_none_not_supplier_qualification`
- `test_normalize_requirement_type_invalid_returns_none`
- `test_mandatory_alone_does_not_default_to_supplier_qualification`
- `test_condition_of_participation_resolves_to_supplier_qualification`
- `test_financial_standing_resolves_to_supplier_qualification`
- `test_oem_authorization_for_participation_resolves_to_supplier_qualification`
- `test_technical_specification_is_non_gate`
- `test_signed_submission_form_is_non_gate`
- `test_incident_sla_response_is_non_gate`
- `test_liability_payment_clause_is_non_gate`
- `test_generic_mandatory_compliance_is_non_gate`
- `test_rated_category_is_never_supplier_qualification`
- `test_same_specific_types_preserve_type`
- `test_none_or_general_with_specific_preserves_specific`
- `test_conflicting_different_specific_types_resolves_to_general_compliance`
- `test_all_permutations_commutative`
- `test_only_supplier_qualification_mandatory_becomes_qualification_gate`
- `test_select_qualification_requirements_matching`
- `test_select_qualification_requirements_empty_gates_returns_empty`
- `test_select_qualification_requirements_does_not_match_non_mandatory`
- `test_substring_containment_does_not_falsely_match`
- `test_zero_gate_ui_alert_state`
- `test_partition_by_material_description_when_no_db_id`

### 5.2 Full Regression Suite Totals
- `tests/test_requirement_semantic_separation.py`: **28 / 28 passed**
- `tests/test_stage_d_completeness.py`: **52 / 52 passed**
- `tests/test_stage_a_extraction_reliability.py`: **20 / 20 passed**
- `tests/test_stage_b_requirement_dedup_integrity.py`: **8 / 8 passed**
- Full unit test discovery (`tests/test_*.py`): **295 / 295 passed**
- Smoke test suite (`tests/smoke/`): **12 / 12 passed**
- Integration test suite (`tests/integration/`): **6 discovered / 5 passed / 1 skipped (live AI) / 0 failed**
- **Grand Total:** **313 discovered / 312 passed / 1 skipped live AI / 0 failed**

---

## 6. Git Summary

- **Branch:** `fix/requirement-semantic-separation`
- **Files Created:**
  - `requirement_semantics.py`
  - `tests/test_requirement_semantic_separation.py`
  - `REQUIREMENT_SEMANTIC_SEPARATION_REPORT.md`
- **Files Modified:**
  - `extractor.py`
  - `analyst.py`
  - `pages/stage_understand.py`
  - `pages/stage_decide.py`
  - `pages/stage_check.py`
  - `tests/test_stage_d_completeness.py`
