# Bank of Canada RFP 2026-026 — Phase 3 / Stage C Commissioning Report

Fresh, real production run of **Stage C (conflict detection & governance)** — `extractor.reconcile_package_facts()` — against the persisted, remediated Stage B output. Neither Stage A nor Stage B was re-invoked. No Stage D, Opportunity Intelligence, Buyer Brief, Executive Opportunity Brief, or Executive Briefing Pack ran.

```
PHASE 2 INPUT LOCK: PASS
STAGE C EXECUTION: PASS
CONFLICT GOVERNANCE VALIDATION: PASS
PHASE 3 COMMISSIONING: PASS
```

One genuine Stage C implementation defect was found, fixed at the root cause, regression-tested, and the boundary was recommissioned — per your Section 10 process. See §0.1 and §J.

## 0. Stage C architecture, as the code actually implements it (read before running anything)

- **Production entry point**: `extractor.reconcile_package_facts(normalized_facts: dict, package_files: list[str]) -> list[dict]`. It **mutates its `normalized_facts` argument in place** (replaces `normalized_facts["_canonical_opportunity"]` with a resolved copy) in addition to returning the flat conflicts list.
- **Three conflict sources, called in sequence**:
  1. `detect_document_conflicts(normalized_facts, package_files)` — a large, deterministic, hand-written rule engine (~700 lines) covering dates, evaluation criteria, submission rules (envelope/channel/page-limit), mandatory requirements (years-of-experience, security clearance), commercial terms (caps, insurance), and scope/deliverable quantities. **Operates only on `requirements`/`submission_rules`/`commercial_clauses`/`deliverables` records that lack a `clause_id`/`deliverable_id`** — i.e. only the **legacy** (shape-invalid, pre-`contract_hygiene`) shape of those two families. Structured (contract_hygiene-verified) deliverables/clauses are explicitly excluded from this detector by construction (`if not c.get("clause_id")` / `if not d.get("deliverable_id")`).
  2. `contract_hygiene.structured_deliverable_conflicts(hygiene["deliverables"], ...)` — the dedicated comparator for **structured, verified deliverables only** (grouped by title+scope+conditions+frequency; flags a contradiction only on differing explicit quantities or mandatory-vs-optional state). **No equivalent function exists for structured commercial_clauses** — verified structured clauses have zero conflict detection in the current implementation (see §0.2).
  3. `canonical_opportunity.resolve_canonical_opportunity(canonical)` + `apply_legacy_conflict_fallback(canonical, conflicts)` — resolves 9 canonical fields (`client`, `submission_deadline`, `clarification_deadline`, `contract_term`, `headline_value`, `opportunity_type`, `procurement_model`, plus `title`/`file_number` via the generic `_resolve_simple`) from the `typed_observations` ledger built in Stage B.
- **Input/output schema**: input is the full Stage B `normalized_facts` dict plus a flat `package_files` list of filenames. Output is `list[dict]`, but this list mixes **two structurally different record shapes** with no shared schema:
  - **Legacy/structured-detector conflicts**: `conflict_id` (`CONF-<TYPE>-<n>`), `conflict_type`, `classification` (`TRUE_CONFLICT`/`REVIEW_ITEM`), `confidence`, `reason`, `source_validity` (`PHYSICAL_BOTH`/`PHYSICAL_PARTIAL`/`SYNTHESIZED`), `topic`, `source_a`/`source_b` (`{doc, ref, text}`), `assessment`, `recommended_action`. **No resolution/winner field exists on this shape at all** — it is detection-and-recommendation only, never automatic resolution.
  - **Canonical-opportunity conflicts**: `conflict_id` (`conf_<hash>`), `state`, `semantic_kind`, `scope`, `affected_fields`, `link_status`, `affected_observation_ids`, `incompatible_values`, `source_refs` (full ref objects), `resolution_basis`, `resolved_by`. This shape **is** resolution-adjacent — it is what `resolve_canonical_opportunity` attaches to a field left `CONFLICTED`.
- **Conflict grouping / comparison keys**: date milestones by classified event type; evaluation criteria by `(identity, scope)`; submission rules by classified dimension (envelope/channel/page-limit) then scope; mandatory requirements by `(topic, scope, subject)` for years-of-experience and security-clearance only; commercial terms by classified topic/insurance class; structured deliverables by `(title, scope, conditions, frequency)`; canonical fields by `(family, semantic_kind[, scope])` identity groups.
- **Semantic-family handling**: `typed_observations`' 6 families (IDENTITY/MILESTONE/CONTRACT_TERM/MONETARY/PROCUREMENT_MECHANIC/DOCUMENT_ROLE) each have a controlled `semantic_kind` set; anything outside that set is rejected at the Stage B canonical-ledger build step (`invalid_observations`, never reaches Stage C) — 17 such rejections exist in this real corpus (DOCUMENT_ROLE/PRICING_FORM/RATED_CRITERIA/CURRENCY kinds the model emitted that aren't in the controlled vocabulary).
- **Scope handling**: `_extract_operational_scope()` recognizes only **explicit** markers (`Category N`, `Cat N`, `Lot N`, `Stream N`, `Work Package N`) — deliberately, by its own docstring, **does not infer scope from subject-matter keywords** (e.g. "HR Advisory") and ignores bare `D1`/`D2`/`D3` filename substrings as unreliable. `contract_hygiene`'s structured comparators use the record's own explicit `scope` dict (`lot`/`phase`/`component`/`location`) instead.
- **Amendment/revision handling**: **no code path treats "amendment" or "revised" document status as authoritative by itself.** The only mechanism that can prefer one value over another is `_apply_supersession()`, and it acts **only** on a `typed_observation`'s own `supersession` block, which Stage A must have populated with an **explicit textual statement** (`basis` in `EXPLICIT_REVISED_VALUE`/`EXPLICIT_EXTENSION`/`EXPLICIT_REPLACEMENT`/`EXPLICIT_SUPERSEDES_STATEMENT`/`EXPLICIT_OLD_TO_NEW_RELATIONSHIP`) and Stage B must have verified its `source_refs`. **Zero such declarations exist anywhere in this real corpus** (`explicit_supersession_declarations_in_input: 0`) — confirmed empirically, not assumed.
- **Source precedence rules**: none exist beyond supersession. No "master RFP wins" rule, no "later-filed document wins" rule, no document-type hierarchy of any kind.
- **Confidence/status fields**: legacy conflicts carry `confidence` (`HIGH`/`MEDIUM`/`LOW`, heuristic, not a probability) and `classification`; canonical conflicts carry `state` (`ACTIVE`) and no confidence field — their canonical field's own `resolved.status` (`RESOLVED`/`CONFLICTED`/`UNVERIFIED`/`MISSING`/`NOT_CLASSIFIED`) is the closest analog.
- **Provenance requirements**: `validate_conflict_source_validity(source_a, source_b, package_files)` checks only that each cited **filename** exists in `package_files` — a weaker check than Stage B's own coordinate-level `validate_source_refs()`, appropriate here since `source_a`/`source_b` carry only `{doc, ref, text}` labels, not full locator objects. `TRUE_CONFLICT` is only permitted when `source_validity == PHYSICAL_BOTH` **and** the two documents differ (Section 7, "Final Source Validity Enforcement" — a same-file pair is always downgraded to `REVIEW_ITEM` even if otherwise `PHYSICAL_BOTH`). Canonical conflicts carry full `source_refs` inherited directly from the contributing `typed_observations` (already Stage-B-validated).
- **Deterministic?** Yes — every comparison is exact-string/regex/dict-keyed; no randomness anywhere.
- **LLM call?** **None.** Verified by reading every function in this call graph (`reconcile_package_facts`, `detect_document_conflicts`, `structured_deliverable_conflicts`, `resolve_canonical_opportunity`, `apply_legacy_conflict_fallback`, and every `classify_*`/`_extract_*`/`select_opposing_pair`/`validate_conflict_source_validity` helper) — zero occurrences of `client.messages.create`/`get_anthropic_client`. This run's own elapsed time (0.058 s) corroborates it.
- **Automatic, governed, deferred, or mixed?** **Mixed, and cleanly separated by shape.** The legacy/structured detectors (shape 1) never resolve anything automatically — every output is a flagged candidate with a `recommended_action` for a human, full stop. The canonical-opportunity resolver (shape 2) **does** resolve automatically, but only under two narrow, governed conditions: (a) `EXACT_AGREEMENT` — every surviving verified observation states the literal same normalized value, or (b) `RESOLVED_BY_SUPERSESSION` — an explicit, Stage-A-asserted, Stage-B-verified supersession statement exists. Anything else becomes `CONFLICTED` with `resolution_basis: null` — never a guessed winner.

### 0.1 Defect found and fixed: evaluation-criteria conflicts lost document identity (root cause, not workaround)

**Defect**: `detect_document_conflicts()`'s EVALUATION CONFLICTS section read `ec.get("source_doc", "Document")`. But `evaluation_hierarchy.normalize_evaluation_criterion()` (Stage B) never populates a top-level `source_doc` field on its output — only validated `source_refs[]` (confirmed by re-reading the function: its returned dict has no `source_doc` key at all). Every evaluation criterion therefore silently fell back to the same literal placeholder `"Document"`, for every one of the 83 real normalized evaluation criteria, in every corpus this code has ever run against — not something introduced by this commissioning.

**Why this is a correctness issue, not a style nit**: it made the `TRUE_CONFLICT` vs. `REVIEW_ITEM` distinction — the entire point of "conflict vs. duplicate discipline" your Section 5 asks for — structurally unable to fire for this family. Two weight values from two genuinely different physical documents would always compare `doc_a == doc_b == "Document"`, always classified as a spurious same-document "internal inconsistency" with `source_validity: SYNTHESIZED`, even when the two source documents were real, different, and both physically present. This directly undermines §6 (Scope Safety) and §5 (Conflict vs Duplicate Discipline): Stage C could not tell corroboration from cross-document contradiction for this entire family.

**Fix (root cause)**: mirror the pattern the adjacent MANDATORY REQUIREMENT CONFLICTS section already used correctly — derive `s_doc` from `ec.get("source_refs", [])[0]["source_doc"]`, falling back to the same `"Document"` placeholder only when no `source_refs` exist at all (e.g. hand-built legacy input with neither field). `extractor.py`, one function, ~14 lines changed.

**Regression tests added** (`tests/test_stage_c_evaluation_source_doc_regression.py`, 3 tests, all passing):
1. Two criteria from two real, different documents → correctly `TRUE_CONFLICT`, `source_validity: PHYSICAL_BOTH`, real filenames (not "Document").
2. Two criteria genuinely from the same real document → still correctly `REVIEW_ITEM` (not upgraded).
3. Criteria with no `source_refs` at all → still falls back to the `"Document"` placeholder, still correctly downgraded (never fabricates a false `TRUE_CONFLICT`).

4 pre-existing tests in `tests/test_stage_c_refinement.py` (`TestStageCEvaluationCriteriaIdentity`) had fixtures using the unrealistic top-level `source_doc` shape (which is how raw Stage A data looks, not real Stage B output) — updated to use `source_refs`, matching the real Stage B shape; their assertions (TRUE_CONFLICT expected) were unchanged.

**Validation**: `py_compile` clean · `git diff --check` exit 0 (pre-existing CRLF warnings only) · targeted (`test_stage_c_refinement.py` + new file): 71 passed · full suite: **1168 passed, 2 skipped, 0 failed** (baseline before this fix: 1165 passed; +3 new, 0 regressions).

**Effect on this run**: 8 pre-fix `SOURCE_NOT_IN_EVIDENCE_UNIVERSE` validation warnings (the literal string `"Document"` is not a real package file) → **0** after the fix. All 4 evaluation conflicts now correctly attribute to their real source document(s) — see §D/§E.

### 0.2 Architectural gap noted, not fixed (out of this remediation's authorized scope)

Structured (verified) `commercial_clauses` have **no** dedicated conflict detector analogous to `structured_deliverable_conflicts` — and are explicitly excluded from the legacy detector by the `if not c.get("clause_id")` filter. This means two structured, real, conflicting commercial-clause facts (e.g. two different liability caps) would currently generate **zero** Stage C conflict output. This corpus's real structured clauses happened not to exercise this gap (no such contradiction was found among the 91 admitted clauses), so it did not block this commissioning, and per your Section 10 process a defect is only remediated once it actually surfaces and is demonstrated — this is reported as a known gap, not silently patched.

## A. Run metadata

| Field | Value |
|---|---|
| Phase 3 run ID | `phase3-boc-2026-026-stagec-20260912T122912Z-0999a0` |
| Timestamp (UTC) | see `run_metadata.json` |
| Git commit | `7e797830f42d06ff08745648585de0e26557addb` (working tree dirty — pre-existing, unrelated) |
| Input Phase 2 run ID | `phase2-boc-2026-026-stageb-20260912T111643Z-1da5ab` |
| Production Stage C entry point | `extractor.reconcile_package_facts` |
| Runtime | 0.058 s |
| LLM/model usage | **None** |
| Token/cost data | Not applicable |

## B. Input lock

```
PHASE 2 INPUT LOCK: PASS
```

| Check | Value |
|---|---|
| requirements | 427 |
| dates | 23 |
| evaluation_criteria | 83 |
| submission_rules | 62 |
| deliverables | 23 |
| commercial_clauses | 91 |
| canonical_opportunity observations | 120 |
| `_provenance_rejections` present in input | 2 (untouched by Stage C — confirmed identical before/after by byte-for-byte comparison) |
| Stage A rerun | No |
| Stage B recomputed | No — the persisted `stage_b_normalized_result.json` was loaded and used verbatim |

The 2 rejected zero-provenance records (1 deliverable, 1 commercial_clause) **never entered Stage C**: `reconcile_package_facts()` reads only `requirements`/`dates`/`evaluation_criteria`/`submission_rules`/`deliverables`/`commercial_clauses`/`_contract_hygiene`/`_canonical_opportunity` — `_provenance_rejections` is never referenced anywhere in the Stage C call graph (confirmed by reading every function; also empirically confirmed by this run — the field was byte-identical before and after).

## C. Actual Stage C output schema

Documented in full in §0 above. Two coexisting shapes in one flat list — no single uniform "conflict" type exists in the current implementation.

## D. Conflict summary

| Metric | Count |
|---|---:|
| Conflict candidates examined | all 427+23+83+62+23+91 = 709 normalized records, plus 120 canonical observations |
| Governed conflicts emitted (total) | **7** |
| — from the legacy/structured detector | 4 (all `EVALUATION_CONFLICT`) |
| — from canonical-opportunity resolution | 3 (`SOLICITATION_NUMBER`, `BUYER_NAME`, `OPPORTUNITY_TITLE`) |
| `TRUE_CONFLICT` | **0** |
| `REVIEW_ITEM` | 4 |
| Canonical `CONFLICTED` fields | 3 (`file_number`, `client`, `title`) |
| Canonical `RESOLVED` fields | 2 (`contract_term` via `STRUCTURED_COMPONENTS`; `submission_deadline` via `EXACT_AGREEMENT`) |
| Canonical `UNVERIFIED`/`MISSING`/`NOT_CLASSIFIED` fields | 4 (`clarification_deadline`=UNVERIFIED, `headline_value`=MISSING, `opportunity_type`=NOT_CLASSIFIED, `procurement_model`=NOT_CLASSIFIED) |
| Amendment-driven resolutions | **0** |
| Supersession relationships applied | **0** |
| Explicit supersession declarations in the input | **0** |
| Corroborations (excluded from conflict handling by design) | not separately counted by production code; see §E worked examples |
| False candidates rejected because scope differed | not separately counted by production code (rejection is implicit — no conflict is ever emitted for them); see §F worked examples |
| Validation failures | 0 (post-fix) |

By family: `dates` 0 conflicts, `evaluation_criteria` 4, `submission_rules` 0, `requirements` (mandatory) 0, `commercial_clauses` (legacy path) 0, `deliverables` (structured path) 0, canonical-opportunity 3.

## E. Complete conflict inventory (all 7)

### CONF-EVAL-1 — REVIEW_ITEM
- **Family**: evaluation_criteria (internal same-document inconsistency)
- **Subject**: "Title Corporate Profile"
- **Competing values**: 5 points vs. 10 points
- **Source document (both)**: `RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf` (master RFP)
- **Source validity**: `PHYSICAL_BOTH` · **Confidence**: HIGH
- **Recommended action**: "Submit clarification to confirm authoritative evaluation weighting formula."

### CONF-EVAL-2 — REVIEW_ITEM
- **Subject**: "Team Experience" (label derived from `_extract_eval_criterion_identity`; underlying stage title "Key Personnel and Roster")
- **Competing values**: 15 points vs. 20 points (a third value, 100 points, was also present in the group but not selected by the opposing-pair heuristic)
- **Source document (both)**: master RFP
- **Source validity**: `PHYSICAL_BOTH` · **Confidence**: HIGH

### CONF-EVAL-3 — REVIEW_ITEM
- **Subject**: "Methodology"
- **Competing values**: 5 points vs. 35 points (30 points also present in the group)
- **Source document (both)**: master RFP
- **Source validity**: `PHYSICAL_BOTH` · **Confidence**: HIGH

### CONF-EVAL-4 — REVIEW_ITEM
- **Subject**: "Title Relevant Experience And References"
- **Competing values**: 5 points vs. 10 points
- **Source document (both)**: master RFP
- **Source validity**: `PHYSICAL_BOTH` · **Confidence**: HIGH

**Root cause of CONF-EVAL-1..4, confirmed against the master RFP's own extracted text** (page 13–14): the master RFP's own summary evaluation table lists the same generic criterion titles ("Corporate Profile", "Key Personnel and Roster", methodology-named criteria) **three times**, once under each of "Appendix D1 – Learning & Development Programs and Assessments" (5/15/5 pts), "Appendix D2 - HR Advisory" (5/15/35 pts), and "Appendix D3 – Facilitation and Team Effectiveness" (10/20/30 pts) — three legitimately different, compatible, per-service-category scoring tables within **one physical document**. `_extract_operational_scope()` only recognizes explicit `Category N`/`Cat N`/`Lot N` markers — by its own documented design, it does **not** infer scope from named-appendix or subject-matter text — so it cannot tell these three category-specific tables apart, and correctly declines to guess. Per your Section 2 instruction ("Where no rule permits deterministic resolution, preserve the conflict as unresolved"), the system does exactly this: it does not silently merge these three legitimately-different facts as duplicates, and does not silently assume they're compatible — it flags the ambiguity as a human-reviewable `REVIEW_ITEM`. This is intended, conservative, correct behavior, **not a second defect** — no code change was made here.

### Canonical conflict `conf_14f51c...dd8f` — CONFLICTED, `file_number` (SOLICITATION_NUMBER)
- **20 contributing observations**, values `"2026-026"` vs. `"rfp 2026-026"` — a normalization/prefix-text variance (both refer to the same real solicitation), not a genuine numeric disagreement
- **Source documents** (20 refs): master RFP (×11, pages 1,3,4,5,9,10,12,13,14,15,19), abstract.pdf (p.4), Appendix B1/B2/B3 (Mandatory Criteria sheets), C1/C2/C3 (Minimum qualification sheets), D1 (Header), **revised D2** (Header). Original D2 does **not** appear among its refs.
- **Resolution**: `resolution_basis: null` — left `CONFLICTED`, correctly, since no `EXACT_AGREEMENT` and no verified supersession exist.

### Canonical conflict `conf_90315c...087a` — CONFLICTED, `client` (BUYER_NAME)
- **13 observations**, values `"bank of canada"` / `"bank"` / `"the bank"` — genuinely different text spans (full legal name vs. shorthand references), correctly not collapsed
- **Source documents**: Appendix A (§2), master RFP (×6), Appendix B1 (Mandatory Criteria), Appendix G (×2, Header)
- **Resolution**: `CONFLICTED`, `resolution_basis: null`

### Canonical conflict `conf_cc97de...5bc` — CONFLICTED, `title` (OPPORTUNITY_TITLE)
- **10 observations**, values `"rfp 2026-026 - talent, learning and organizational development services"` vs. `"talent, learning and organizational development services"` (with/without the RFP-number prefix)
- **Source documents**: Appendix C1/B2/C2/B3/B1/C3 (all Mandatory/Minimum-qualification sheets), master RFP (×2)
- **Resolution**: `CONFLICTED`, `resolution_basis: null`

Complete raw JSON: `stage_c_conflicts.json` (all 7, non-truncated).

## F. Original vs. revised D2 audit

| Metric | Original D2 | Revised D2 (Amendment1) |
|---|---:|---:|
| Requirements admitted (post-Stage-B) | 8 unique descriptions (11 raw before dedup) | 9 unique descriptions (10 raw) |
| Submission rules admitted | 4 (Rated Criteria Response, Key Personnel Profiles, Published Thought Leadership Samples, Relevant Experience Case Studies) | 3 (Rated Criteria Response Form, Professional Profiles/Resumes, Work or Product Samples) |
| Evaluation criteria citing this document | 7 stages (Corporate Profile, Key Personnel and Roster, Methodology & Advisory Approach, Thought Leadership & Innovation, Relationship Management, Value-added, Relevant Experience and References) — `weight: null` on all 7 in the final merged records (weight values for these titles come from the master RFP's own table, not from D2's own extracted criteria rows) | same 7 stages, same `weight: null` pattern |

**Semantic matches (exact text, both documents)**: 1 — *"Proponents will be evaluated only on the service category(ies) for which they submit a response."*

**Substantive difference identified**: the revised D2 **restructures** the same underlying requirement content — it merges the criterion label directly into the requirement text (e.g. original R1 *"Proponents must describe their organisation..."* → revised R4 *"Corporate Profile: Proponents must describe their organisation..."*) and **combines** the original's two page-format sentences (R2: page size, and the earlier sentence about not exceeding pages) into one requirement. Because Stage B's requirement dedup is an **exact** post-normalization string match, none of these reworded/restructured pairs match — they remain as 8 + 9 = 17 distinct requirement records, each correctly attributed to its own real document, with **zero** Stage C conflict raised between any of them.

**Conflicts generated involving either D2 document**: 1 — the canonical `file_number` (SOLICITATION_NUMBER) conflict above, and only because the revised D2's own "2026-026" mention normalizes differently from other sources' "rfp 2026-026" mentions; the original D2 is not even among that conflict's contributing refs. **No conflict compares original-D2 content against revised-D2 content directly.**

**Resolution rule used**: none — `resolution_basis: null`; both documents' evidence survives untouched.

**Is amendment precedence explicit or inferred?** **Neither — it does not exist in the current implementation.** `explicit_supersession_declarations_in_input: 0`. Stage A never asserted an explicit old→new statement anywhere touching D2 (its own prompt rule requires one, and none was extracted); Stage C has no fallback "amendment beats original" heuristic. Per your instruction, **no rule was invented for commissioning** — the architectural gap is reported here rather than papered over: **there is currently no mechanism, anywhere in the production pipeline, that would cause the revised D2 to take precedence over the original D2**, even though a human reading both documents would very likely conclude the revised version (issued as a formal amendment) supersedes the original. Both survive side by side, undifferentiated, as of this Stage C boundary.

## G. Conflict vs. duplicate discipline — representative examples from this corpus

| Category | Example found in this run |
|---|---|
| Same fact, same value, different sources → corroboration, not conflict | `submission_deadline` RESOLVED via `EXACT_AGREEMENT`: every verified source states the same date; 0 conflict emitted |
| Same semantic fact, differing values → conflict candidate | `file_number`/`client`/`title` canonical conflicts (§E); CONF-EVAL-1..4 (§E) |
| Same wording, different scope/category → separate facts, not necessarily conflict | The master RFP's 3 per-appendix evaluation tables (§E root-cause note) — correctly flagged as ambiguous rather than silently treated as either duplicates or compatible, because explicit scope markers are absent |
| Amendment replacing prior value → supersession candidate | **None found** — 0 explicit supersession declarations exist in this corpus |
| Master RFP and appendix expressing compatible constraints → corroboration | The bilingualism mandatory requirement (Appendix B1/B2/B3 + master RFP) merged into one Stage B requirement record citing all 4 documents (see the Phase 2 remediation report's dedup examples) — never reaches Stage C as a conflict because Stage B already merged it as one exact-agreement fact |
| Source hierarchy disagreement without explicit precedence → unresolved unless governed | The D2 original-vs-revised restructuring (§F) — genuinely different wording, no governed rule to prefer one, and Stage C's exact-match detectors don't even compare them — left entirely unaddressed rather than guessed |

## H. Scope safety audit

No cross-scope false-candidate was found being incorrectly merged in this run: `_extract_operational_scope()`'s conservative "explicit markers only" design means a Category-1 fact and a differently-scoped Category-2 fact would only ever share a comparison bucket if **neither** carried an explicit marker (both fall to `GENERAL_SCOPE`) — which is exactly what happened for CONF-EVAL-1..4 (§E), correctly surfaced as a human-reviewable ambiguity rather than silently merged or silently ignored. No genuinely-scoped (`CATEGORY_N`-tagged) pair was found colliding with a different category in this corpus's real data — the corpus's 3 service categories are distinguished in the master RFP by appendix name and free text ("Learning & Development", "HR Advisory", "Facilitation and Team Effectiveness"), not by the numeric/lettered markers the scope extractor recognizes, which is precisely why they fell into `GENERAL_SCOPE` and required human review rather than being automatically and safely separated.

## I. Unresolved conflicts

All 4 `REVIEW_ITEM`s (CONF-EVAL-1..4) and all 3 `CONFLICTED` canonical fields (`file_number`, `client`, `title`) are unresolved. Reasons, per the production code's own logic:

| Conflict | Why unresolved |
|---|---|
| CONF-EVAL-1..4 | Same physical document, ambiguous/incompatible scope — no explicit `Category N` marker exists to safely separate the 3 per-appendix scoring tables; the code declines to guess (§E) |
| `file_number` CONFLICTED | 20 verified observations do not all normalize to the same text; no explicit supersession statement exists to prefer one |
| `client` CONFLICTED | 13 verified observations state genuinely different text spans ("Bank of Canada" vs. "the Bank"); no rule equates a shorthand reference with the full legal name |
| `title` CONFLICTED | 10 verified observations differ only by an RFP-number prefix; same reasoning as `file_number` |

None of these were resolved manually in this commissioning. All remain exactly as the production code left them.

## J. Stage C validation

All checks specified in your instructions were run (see `stage_c_validation_warnings.json` for the post-fix result and the pre-fix comparison below).

| Check | Pre-fix (`...9094T122454Z-3b1dd9`) | Post-fix (`...T122912Z-0999a0`, authoritative) |
|---|---:|---:|
| Conflicts with fewer than two candidates | 0 | 0 |
| Conflicts with identical values masquerading as disagreements | 0 | 0 |
| Winning values not present among candidates | 0 | 0 |
| Missing physical provenance | 0 | 0 |
| Dangling candidate identities | 0 | 0 |
| Invalid scopes | 0 | 0 |
| Circular supersession | 0 (also confirmed by the production code's own `supersession_cycles: []`) | 0 |
| Duplicate conflict IDs | 0 | 0 |
| Contradictory resolution status | 0 | 0 |
| Unresolved conflicts carrying a winner | 0 | 0 |
| Resolved conflicts lacking a governed basis | 0 | 0 |
| Source refs not resolvable to the evidence universe | **8** (`"Document"` placeholder on CONF-EVAL-1..4, 2 refs each) | **0** |
| **Total warnings** | **8** | **0** |

```
CONFLICT GOVERNANCE VALIDATION: PASS
```

## K. Artifact index

`evaluation/bank_of_canada_briefing_pack/phase3_commissioning/phase3-boc-2026-026-stagec-20260912T122912Z-0999a0/` (authoritative, post-fix)

| File | Type | Notes |
|---|---|---|
| `input_lock.json` | production commissioning artifact | Frozen Phase 2 identity + count confirmation |
| `run_metadata.json` | production commissioning artifact | Run identity, zero-LLM confirmation, `_provenance_rejections` untouched confirmation |
| `stage_c_conflicts.json` | **production Stage C output** | Complete, non-truncated `reconcile_package_facts()` return value — all 7 conflicts |
| `stage_c_canonical_opportunity_resolved.json` | **production Stage C output** | The mutated `_canonical_opportunity` (resolved fields, conflicts, integrity_diagnostics) |
| `conflict_summary.json` | derived analysis | Counts by type/classification, canonical field status/basis |
| `d2_original_vs_revised_audit.json` | derived analysis | §F source data |
| `conflict_vs_duplicate_audit.json` | derived analysis | Conflict-ID lists by classification |
| `master_rfp_conflict_contribution.json` | derived analysis | §H-adjacent master RFP counts |
| `stage_c_validation_warnings.json` | derived analysis | §J source data |
| `summary.json` | derived analysis | Top-line counts, also printed to console |

Superseded (pre-fix, retained only as before/after evidence, not authoritative): `evaluation/bank_of_canada_briefing_pack/phase3_commissioning/phase3-boc-2026-026-stagec-20260912T122454Z-3b1dd9/`.

Production code changed (not commissioning artifacts): `extractor.py` (root-cause fix), `tests/test_stage_c_refinement.py` (4 fixture corrections), `tests/test_stage_c_evaluation_source_doc_regression.py` (new, 3 tests).

## Historical comparison

| Metric | Historical corrected run | Fresh Stage C |
|---|---:|---:|
| Governed conflicts | 9 | **7** |
| Resolved | not reported in the historical artifacts available | 2 (canonical: `contract_term`, `submission_deadline`) |
| Unresolved | not reported | 5 (4 REVIEW_ITEM + 3 CONFLICTED − wait, see note) |

Note on the "unresolved" row: 4 `REVIEW_ITEM`s + 3 canonical `CONFLICTED` fields = 7 unresolved items total; all 7 governed conflicts in this run are unresolved (0 TRUE_CONFLICT, 0 RESOLVED-with-conflict). The historical corrected run's own breakdown of its 9 conflicts by resolved/unresolved was not found in the available historical artifacts (`CORRECTED_CORPUS_REGENERATION_REPORT.md` reports the Stage C conflict *count* only, not a resolved/unresolved split), so that comparison is marked not available rather than estimated.

**What can be established from code/artifacts about the 9-vs-7 difference**: the historical corrected run used the historical evaluation harness's own Stage A/B pipeline (a different code path, run at a different time, by a different tool session) as Stage C's input — not the same remediated Stage B object this run used. The two runs' underlying Stage A extractions are independently-generated (temperature-0 but not byte-identical across separate live sessions, as already established in the Phase 1/Phase 2 reports), and this run's Stage B requirement/evaluation-criteria counts (427/83) already differ from the historical run's own Stage B counts (413/113) for the same reason. Since Stage C's conflict candidates are built directly from Stage B's normalized output, a different Stage B input mechanically produces different Stage C candidates — this is the only cause demonstrable from the available artifacts. No claim is made about which of the two conflict sets is "more correct"; no tuning was performed to move 7 toward 9.

## FINAL RESPONSE

```
PHASE 2 INPUT LOCK: PASS
STAGE C EXECUTION: PASS
CONFLICT GOVERNANCE VALIDATION: PASS
PHASE 3 COMMISSIONING: PASS
```

- **Phase 3 run ID**: `phase3-boc-2026-026-stagec-20260912T122912Z-0999a0`
- **Stage C implementation/function**: `extractor.reconcile_package_facts` (→ `detect_document_conflicts`, `contract_hygiene.structured_deliverable_conflicts`, `canonical_opportunity.resolve_canonical_opportunity`, `apply_legacy_conflict_fallback`)
- **LLM usage/cost**: none, $0 — fully deterministic, confirmed by code inspection and 0.058 s runtime
- **Conflict candidates**: 709 normalized records + 120 canonical observations examined
- **Governed conflicts**: 7 (4 legacy-detector `EVALUATION_CONFLICT` + 3 canonical-opportunity)
- **Resolved conflicts**: 0 of the 7 conflict records (2 separate canonical *fields* — `contract_term`, `submission_deadline` — resolved without ever becoming conflicts, via `EXACT_AGREEMENT`/`STRUCTURED_COMPONENTS`)
- **Unresolved conflicts**: 7 of 7 (4 `REVIEW_ITEM`, 3 `CONFLICTED`)
- **Amendment-driven resolutions**: 0
- **Supersession count**: 0 relationships applied, 0 explicit declarations in the input
- **Conflicts involving master RFP**: 7 of 7 (all of them)
- **D2 original/revised conflict count and outcome**: 1 conflict touches revised D2 (canonical `file_number`, incidental — 20-source normalization variance, original D2 not among its refs); 0 conflicts compare original-D2 content to revised-D2 content directly; outcome for both: `CONFLICTED`/unresolved, no precedence applied, no rule exists to apply one (architectural gap reported in §F, not invented)
- **Invalid provenance count**: 0
- **Validation warning/error count**: 0 (post-fix; was 8 pre-fix — see §0.1/§J)
- **Historical 9-conflict comparison**: fresh run produced 7; cause of the difference is a different (independently remediated) Stage B input, not a Stage C tuning choice — see Historical Comparison section
- **Runtime**: 0.058 s
- **Report path**: `evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_PHASE_3_STAGE_C_COMMISSIONING_REPORT.md`
- **Raw artifact paths**: `evaluation/bank_of_canada_briefing_pack/phase3_commissioning/phase3-boc-2026-026-stagec-20260912T122912Z-0999a0/` (index in §K)

**One defect found, fixed, tested, and recommissioned** during this run (§0.1): evaluation-criteria conflicts lost document identity due to a Stage B/C schema mismatch (`source_doc` never populated on Stage B's evaluation_criteria output; Stage C read it anyway, always got the fallback placeholder). Root-cause fixed in `extractor.py`; 3 new regression tests + 4 corrected pre-existing test fixtures; full suite 1168 passed / 2 skipped / 0 failed; Stage C recommissioned from the same frozen Stage B input, dropping validation warnings from 8 to 0.

**One architectural gap reported, not fixed** (§0.2, out of authorized scope since it did not block this real commissioning): structured commercial_clauses have no dedicated conflict detector.

Stopping here. Stage D is not started.
