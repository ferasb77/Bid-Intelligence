# Bank of Canada RFP 2026-026 — Phase 2 / Stage B Remediation Report

Targeted remediation of the two Stage B boundary defects found by the fresh Phase 2 commissioning run (`phase2-boc-2026-026-stageb-20260912T094351Z-b489a1`), using the same frozen Phase 1 input (`phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5`). Stage A was not re-invoked. No Stage C, Stage D, or conflict resolution occurred.

```
STAGE B REMEDIATION: PASS
```

## 1. Matrix — every Stage B family, inspected before any code change

| Family | Normalization function | Dedup key/strategy | Provenance-validation function (before) | Valid physical provenance | Behavior: missing refs (before) | Behavior: invalid refs (before) | Retained? | Dropped? | Diagnostic emitted? | Fail-open/closed (before) |
|---|---|---|---|---|---|---|---|---|---|---|
| requirements | inline loop in `normalize_package_facts` | exact normalized-description hash | `extractor.validate_source_refs` | doc exists + page bounds + sheet exists + excerpt-substring plausibility | admitted, empty `source_refs` | admitted, ref flagged `verified: false` inline | Yes, always | No | Yes (inline `verified` flag per ref) | **Fail-open** at record level (no ref ever excludes the record) — pre-existing, out of this remediation's scope |
| dates | `normalized["dates"].extend()` (raw) | **none** | **none** | **none (defect 1)** | admitted, unflagged | n/a — never checked | Yes, always | No | No | Fail-open, unvalidated |
| evaluation_criteria | `evaluation_hierarchy.deduplicate_evaluation_criteria` | `(criterion_id or normalized title, normalized parent, hierarchy level)` | **none** | **none (defect 1)** | admitted, unflagged | n/a — never checked | Yes, always | No | No | Fail-open, unvalidated |
| submission_rules | inline loop in `normalize_package_facts` | `_canonical_submission_item_identity(item)` | `extractor.validate_source_refs` | same as requirements | admitted, empty `source_refs` | admitted, ref flagged `verified: false` inline | Yes, always | No | Yes (inline flag) | Fail-open at record level — pre-existing, out of scope |
| deliverables | `contract_hygiene.normalize_deliverable_occurrence` + `_logical_records` | `(title, obligation_state, quantity, unit, frequency, conditions, scope, due_milestone, acceptance_criteria, responsible_actor)` | `extractor.validate_source_refs` via `_verified_refs` (refs dropped if unverified, before occurrence built) | doc+page/sheet/section resolve (excerpt no longer required — see §3) | occurrence still built, `evidence_state=UNVERIFIED` | ref dropped from occurrence's `source_refs`, not flagged | **Yes (defect 2 — inconsistent with clauses)** | No | Only inside `_contract_hygiene` (not in the trusted `normalized["deliverables"]` array) | **Fail-open** — the actual defect |
| commercial_clauses | `contract_hygiene.normalize_clause_occurrence` + `_logical_records` | `(clause_kind, source_fact, conditions, scope, linked_observation_ids)` | same as deliverables | same as deliverables | occurrence still built, `evidence_state=UNVERIFIED` | ref dropped, not flagged | Retained in `_contract_hygiene["clauses"]`, **but silently excluded from `normalized["commercial_clauses"]`** | **Yes, silently (defect 2)** | Only inside `_contract_hygiene`, invisible at the trusted-array level | **Fail-closed at the trusted array, but silent** — the actual defect |
| contract_risks | pass-through to `legacy_risks` | none (always legacy) | **none** | **none** | n/a | n/a | Yes, always, unconditionally | No | Tagged `LEGACY_EXTRACTION` | Fail-open — Stage A's own prompt schema never populates this family (0 real records); not remediated (out of the two named defects, and no live records exist to validate) |
| typed_observations → `_canonical_opportunity.observations` | `canonical_opportunity.build_canonical_opportunity` | exact identity (family+kind+value+doc+coords+scope+pointer) | `canonical_opportunity._validate_ref` — a **separate**, already-existing three-tier validator (VERIFIED/PARTIAL/UNVERIFIED) | doc exists + excerpt grounded in local segment + locator coordinate present | admitted, `provenance_status=UNVERIFIED` | admitted, `provenance_status` reflects it | Yes, always (never excluded — this is a governed ledger, not a filtered array) | No | Yes (`provenance_status` field on every observation) | Intentional fail-open ledger design — already adequate, not part of either defect, unchanged |

**No additional family beyond `dates` and `evaluation_criteria` was found lacking provenance validation entirely.** `contract_risks` has none either, but Stage A's own prompt schema never produces this category (confirmed 0 raw records in the real commissioning), so there is no live defect to fix there; this is noted rather than silently ignored. `typed_observations`' canonical-opportunity ledger already has its own adequate, pre-existing validator and was left untouched.

## 2. The corrected boundary rule (implemented)

For **dates**, **evaluation_criteria**, **deliverables**, and **commercial_clauses**: a record is admitted into the trusted normalized array only if at least one of its physical source references validates (`verified: true`, via the same `extractor.validate_source_refs()` already used for requirements/submission_rules). A record left with zero valid references is excluded from the trusted array and quarantined into a new top-level diagnostic field, `normalized["_provenance_rejections"]`, preserving:
- `family` — which array it was excluded from
- `reason` — `"ZERO_VALID_PROVENANCE"`
- `record` — the full record as it would otherwise have been admitted
- `source_refs` — the checked references (with `verified`/`validation_error` where applicable)

`requirements` and `submission_rules` keep their pre-existing, unchanged fail-open-with-inline-flag behavior (per DEFECT 1's own framing, these two families already validate adequately, and the acceptance conditions explicitly require "existing valid requirement/submission-rule provenance behavior remains unchanged").

## 3. Root cause investigation — the 3 pre-remediation zero-provenance records

### 3a. Deliverable "After-Sales Services" (`dlv_8c3cbc83de79a8d001e888f5`)

- **Original Stage A source record** (`OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx`): `"source_refs": []` — genuinely empty at extraction time.
- **Root cause: genuinely invalid/missing Stage A provenance.** Not a Stage B defect. Stage B's ref-filtering behaved correctly (kept zero refs because zero were ever supplied). The pre-remediation *defect* was only that this zero-provenance record was silently **retained** in the trusted `deliverables` array rather than being excluded/flagged.
- **Fix applied**: none to Stage A or the ref-validation logic — this record now correctly moves to `_provenance_rejections` (reason `ZERO_VALID_PROVENANCE`) instead of sitting unflagged in the trusted array.

### 3b. Commercial clause "Data Breach Investigation and Cooperation" (`clause_8e80706aeb773fb11116b130`)

- **Original Stage A source record**: `"source_refs": [{}]` — a single, entirely empty dict (no `source_doc`, no `excerpt`, nothing).
- **Root cause: genuinely invalid Stage A provenance** (a malformed/empty reference object). Not a Stage B defect — `validate_source_refs()` correctly marks an empty-dict ref as unresolvable (`source_doc` blank → "not found in procurement package").
- **Fix applied**: none to the validation logic. This record correctly remains excluded — but is now **quarantined with a diagnostic** in `_provenance_rejections` instead of silently vanishing from `normalized["commercial_clauses"]`.

### 3c. Commercial clause "Preservation of Bank Rights Upon Termination" (previously dropped; now admitted)

- **Original Stage A source record**: `"source_refs": [{"source_doc": "OriginalRevision/RFP 2026-06 - Appendix G - Form of Agreement.docx", "page": null, "section": "Header", "sheet": null}]` — a **real, resolvable document + section citation**, simply with no quotable excerpt attached.
- **`validate_source_refs()` itself already considered this ref VALID**: page/sheet are absent (no bounds to check), and the excerpt-plausibility check only runs `if excerpt and len(excerpt) > 15` — an empty excerpt skips that check entirely, so `is_valid` stayed `True`.
- **Root cause: a Stage B–internal inconsistency, not a Stage A defect.** `contract_hygiene._verified_refs()` (used only by deliverables/commercial_clauses) imposed an **additional, stricter requirement** beyond what `validate_source_refs()` itself demands — `and _text(ref.get("excerpt"))` — discarding a reference the shared validator had already accepted as a real physical location. This is exactly the "Stage B rewriting/canonicalizing source references incorrectly" case: the physical location (document + Header section) was real and resolvable; Stage B's own stricter internal filter, not missing Stage A data, caused the loss.
- **Fix applied (root cause, not quarantine)**: removed the redundant excerpt-non-empty requirement from `contract_hygiene._verified_refs()` (`contract_hygiene.py`). A reference now counts as valid physical provenance on the same terms `validate_source_refs()` itself uses — no stricter, second, inconsistent bar. This clause is now correctly **admitted** into `normalized["commercial_clauses"]` with `evidence_state: VERIFIED`.

## 4. Code changes

| File | Change |
|---|---|
| `extractor.py` | Added `_partition_zero_provenance()` helper (admits only records with ≥1 verified ref; quarantines the rest with a structured reason). `normalize_package_facts()`: (a) `dates` are now wrapped as a synthetic one-element `source_refs` (`{"source_doc": ...}`) and validated via `validate_source_refs()` instead of raw-concatenated; (b) `evaluation_criteria` source_refs are now pre-validated (mirroring `evaluation_hierarchy.normalize_evaluation_criterion()`'s own bare-`source_doc` fallback, so that fallback-synthesized reference is validated too, not silently unverifiable); (c) both families are partitioned via `_partition_zero_provenance()` after their existing finalization steps; (d) deliverables/commercial_clauses are now partitioned symmetrically by `evidence_state` from the full `_contract_hygiene` diagnostic ledger (which is unchanged in shape) before building the trusted arrays; (e) all rejections are collected into `normalized["_provenance_rejections"]`. |
| `contract_hygiene.py` | `_verified_refs()`: removed the extra `_text(ref.get("excerpt"))` requirement — a verified ref is valid on `validate_source_refs()`'s own terms (root-cause fix for §3c). `build_contract_hygiene()`'s return shape is **unchanged** (still the full diagnostic ledger for both families — preserving existing tests and Stage D's `authoritative_sections()`, which already filters to `VERIFIED` itself). |
| `stage_d_projection.py` | Added `"_provenance_rejections"` to the existing allowlist of recognized private/diagnostic top-level `normalized_facts` keys (alongside `_contract_hygiene`, `_canonical_opportunity`) so Stage D's own fail-closed unknown-field check does not reject the new field — Stage D itself was not otherwise touched, and does not read the new field's contents. |
| `tests/test_evaluation_hierarchy_integrity.py` | 4 pre-existing tests updated to supply a realistic `files` list in their `package_metadata` fixtures (previously `{"doc_texts": {}}` alone, which never validated anything because `evaluation_criteria` had no validation at all before this remediation — these fixtures' intent was always to test weight/role-conflict preservation, not provenance, so this is a fixture correction, not a behavior change). |
| `tests/test_stage_b_provenance_remediation.py` | New — 17 tests (see §8). |

**Preserved, not touched**: deduplication keys/thresholds for every family, requirement/submission-rule wording, source hierarchy, Stage A, extraction prompts, `RECOVERED_TRUNCATED` upstream diagnostics (never relabeled), Stage C/D logic.

## 5. RECOVERED_TRUNCATED lineage

Unchanged upstream — the 4 Stage A diagnostics were not touched, and Stage A was not rerun. The lineage classification (computed externally by the commissioning script from `normalized["requirements"]`/`["submission_rules"]`/`["evaluation_criteria"]`'s `source_refs`, not stored inside the Stage B schema) is identical before and after remediation, as expected since none of the touched families (dates/deliverables/commercial_clauses) feed that classification and the touched dates/evaluation_criteria composition itself didn't change (0 rejections in real data):

| Category | Before | After |
|---|---:|---:|
| Exclusively clean | 126 | 126 |
| Mixed clean + truncated | 16 | 16 |
| Exclusively `RECOVERED_TRUNCATED` | 429 | 429 |
| No source doc | 1 | 1 |

Per instruction, this stays a commissioning-report-only concern — no diagnostic-lineage field was added to Stage B's schema.

## 6. Tests

### 6a. New targeted tests — `tests/test_stage_b_provenance_remediation.py` (17 tests, all passing)

1. `test_valid_pdf_date_provenance_passes`
2. `test_invalid_date_source_document_fails_closed`
3. `test_date_with_no_source_doc_is_rejected_not_admitted_unflagged`
4. `test_valid_xlsx_evaluation_criterion_provenance_passes`
5. `test_invalid_evaluation_criterion_sheet_fails_closed`
6. `test_multi_source_evaluation_criterion_preserves_valid_provenance_union`
7. `test_evaluation_criterion_partial_provenance_survives_on_one_valid_ref`
8. `test_commercial_clause_with_valid_provenance_survives`
9. `test_commercial_clause_with_valid_section_only_reference_survives_no_excerpt_required` (§3c regression)
10. `test_commercial_clause_with_zero_valid_provenance_is_quarantined_not_dropped`
11. `test_deliverable_and_clause_zero_provenance_behavior_is_consistent`
12. `test_deduplicated_records_are_distinguishable_from_rejected_records`
13. `test_no_fabricated_locator_is_introduced_for_any_family`
14. `test_existing_valid_requirement_provenance_behavior_is_unchanged`
15. `test_requirement_with_invalid_reference_still_admitted_inline_flagged_unchanged`
16. `test_existing_valid_submission_rule_provenance_behavior_is_unchanged`
17. `test_recovered_truncated_upstream_diagnostic_is_not_a_stage_b_field`

All 12 of the user-specified minimum scenarios are covered (tests 1–2 → dates; 4–5 → evaluation_criteria; 6 → multi-source union; 8/10 → clause survive/quarantine; 11 → deliverable/clause consistency; 12 → dedup vs. rejection distinguishability; 13 → no fabrication; 14/15/16 → requirement/submission-rule behavior unchanged).

```
tests/test_stage_b_provenance_remediation.py: 17 passed
```

### 6b. Validation commands

```
py -3.13 -m py_compile extractor.py contract_hygiene.py stage_d_projection.py tests/test_stage_b_provenance_remediation.py tests/test_evaluation_hierarchy_integrity.py
→ COMPILE_OK

git diff --check
→ exit 0 (pre-existing CRLF-conversion warnings only, no whitespace errors)

py -3.13 -m pytest -q
→ 1165 passed, 2 skipped, 0 failed (baseline before this remediation: 1148 passed, 2 skipped; +17 new tests, 0 regressions)
```

## 7. Recommissioning — before vs. after

Before: `phase2-boc-2026-026-stageb-20260912T094351Z-b489a1`
After: `phase2-boc-2026-026-stageb-20260912T111643Z-1da5ab`
Both consumed the identical frozen Phase 1 input (`phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5`); both produced the identical `_canonical_opportunity.input_digest` = `input_fb12798abe44bc3a925f988351ab83b11ff2c56d03736399ef4c8b19ddf9c895`, confirming Stage A was not rerun and the input truly did not change.

| Metric | Before | After | Change |
|---|---:|---:|---|
| requirements | 427 | 427 | unchanged (not in scope; 0 zero-provenance records existed) |
| dates | 23 | 23 | unchanged — validation added, 0 rejected (all 23 already had a real `source_doc`) |
| evaluation_criteria | 83 | 83 | unchanged — validation added, 0 rejected (all references resolved) |
| submission_rules | 62 | 62 | unchanged (not in scope) |
| deliverables | 24 | **23** | **−1** (the zero-provenance "After-Sales Services" record now quarantined instead of silently admitted) |
| commercial_clauses | 90 | **91** | **+1 net** (−1 quarantined "Data Breach…" clause, +2 from the excerpt-bug fix rescuing "Preservation of Bank Rights…" as newly VERIFIED — net effect: 89 verified fresh → 90 verified fresh; 90 total (89+1 legacy) → 91 total (90+1 legacy)) |
| canonical_opportunity observations | 120 | 120 | unchanged (untouched family) |
| Valid physical references (requirements+submission_rules) | 446+143=589 | 446+143=589 | unchanged |
| Invalid/unresolved references (requirements+submission_rules) | 0 | 0 | unchanged |
| **Records rejected for zero valid provenance** | 0 explicitly tracked (silent) | **2** (1 deliverable + 1 commercial_clause), each with a full diagnostic | now explicit and auditable |
| **Records silently dropped** | 2 (the two clauses, invisible at the trusted-array level) | **0** | **defect eliminated** |
| Deduplication merge counts (all families) | identical | identical | unchanged — no dedup semantics were touched |
| Master RFP contribution (req+rules+eval) | 192 records, 206 refs, 55/55 eval retained | 192 records, 206 refs, 55/55 eval retained | unchanged |
| `RECOVERED_TRUNCATED` lineage | 429 exclusive / 16 mixed / 126 clean / 1 none | 429 / 16 / 126 / 1 | unchanged |

**`records silently dropped` after remediation = 0, as required.**

## 8. Complete raw artifacts

`evaluation/bank_of_canada_briefing_pack/phase2_commissioning/phase2-boc-2026-026-stageb-20260912T111643Z-1da5ab/`

| File | Notes |
|---|---|
| `run_metadata.json` | Run identity, zero-LLM confirmation, input digest match |
| `input_lock.json` | Frozen Phase 1 identity + digest-match confirmation |
| `metadata_reconstruction_check.json` | 16/16 match |
| `stage_b_normalized_result.json` | Complete, non-truncated production Stage B output, including `_provenance_rejections` |
| `provenance_rejections.json` | The 2 quarantined records in full, with original record + checked refs |
| `provenance_rejection_summary.json` | `{total_rejections: 2, by_family: {deliverables: 1, commercial_clauses: 1}}` |
| `dedup_audit.json`, `example_merge_groups.json` | Unchanged dedup behavior, reconfirmed |
| `provenance_audit.json` | Per-family reference validation counts, now including dates/evaluation_criteria |
| `per_document_contribution.json`, `master_rfp_contribution.json`, `amendment_d2_safety_check.json`, `recovered_truncated_lineage.json` | Unchanged from the before run, reconfirmed |
| `summary.json` | Top-line counts including the new rejection totals |

Also updated (real production code, not commissioning artifacts): `extractor.py`, `contract_hygiene.py`, `stage_d_projection.py`, `tests/test_stage_b_provenance_remediation.py`, `tests/test_evaluation_hierarchy_integrity.py`.

## FINAL RESPONSE

```
STAGE B REMEDIATION: PASS
```

- **Root cause, missing date provenance validation**: `normalize_package_facts()` raw-concatenated `dates` (`normalized["dates"].extend(df.get("dates", []))`) with no call to `validate_source_refs()` at all — a straightforward gap, not a bug in any existing validator.
- **Root cause, missing evaluation_criteria provenance validation**: `evaluation_hierarchy.normalize_evaluation_criterion()` copies `source_refs` verbatim from Stage A (or synthesizes one from a bare `source_doc`) with no validation call anywhere in that path — same class of gap.
- **Root cause, the 2 silently dropped/retained clauses/deliverable**: (1) "After-Sales Services" deliverable and (2) "Data Breach…" clause both had genuinely empty/malformed Stage A provenance (not a Stage B defect) but were handled inconsistently — the deliverable silently admitted, the clause silently dropped; (3) "Preservation of Bank Rights…" clause was a **real Stage B defect**: `contract_hygiene._verified_refs()` imposed a stricter excerpt-required bar than `validate_source_refs()` itself, discarding a genuine document+section citation.
- **Files changed**: `extractor.py`, `contract_hygiene.py`, `stage_d_projection.py`, `tests/test_evaluation_hierarchy_integrity.py` (4 fixture updates), `tests/test_stage_b_provenance_remediation.py` (new).
- **Tests added**: 17, all passing.
- **Targeted test result**: `tests/test_stage_b_provenance_remediation.py`: 17 passed. Full affected-file sweep (contract_hygiene, dedup integrity, evaluation hierarchy, requirement semantics, submission provenance/projection, stage_c, stage_d, streamlined workflow, opportunity intelligence): 510 passed, 1 skipped.
- **Full suite result**: 1165 passed, 2 skipped, 0 failed (baseline 1148 passed + 17 new, 0 regressions).
- **New Phase 2 run ID**: `phase2-boc-2026-026-stageb-20260912T111643Z-1da5ab`
- **Before/after normalized-family counts**: requirements 427→427, dates 23→23, evaluation_criteria 83→83, submission_rules 62→62, deliverables 24→**23**, commercial_clauses 90→**91**, canonical_opportunity observations 120→120
- **Before/after provenance counts**: requirements/submission_rules unchanged (589 valid, 0 invalid); dates and evaluation_criteria now validated for the first time (23/23 and 106/106 references valid, 0 rejected in this real corpus)
- **Records rejected after remediation**: 2 (1 deliverable, 1 commercial_clause), each with a full `ZERO_VALID_PROVENANCE` diagnostic in `_provenance_rejections`
- **Records silently dropped after remediation**: **0**
- **Master RFP impact**: none — 192 records (req+rules+eval), 206 references, 55/55 evaluation criteria retained, identical before and after
- **Runtime**: 0.294 s (Stage B itself; zero LLM calls, zero cost)
- **Report path**: `evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_PHASE_2_STAGE_B_REMEDIATION_REPORT.md`
- **Raw artifact paths**: `evaluation/bank_of_canada_briefing_pack/phase2_commissioning/phase2-boc-2026-026-stageb-20260912T111643Z-1da5ab/` (index in §8)
- **Remaining warnings**: (1) `requirements`/`submission_rules` still fail-open at the whole-record level if every reference is invalid (pre-existing, explicitly out of this remediation's scope per the acceptance conditions — 0 live occurrences in the real corpus, so no current impact); (2) `contract_risks` has no provenance validation, but Stage A's schema never populates it (0 live records); (3) `typed_observations`/canonical-opportunity provenance uses its own separate, already-adequate three-tier validator, left untouched; (4) 75% of normalized req/rules/eval records still depend on a `RECOVERED_TRUNCATED` source document, unchanged and not remediated per instruction.

Stopping here. Stage C is not started.
