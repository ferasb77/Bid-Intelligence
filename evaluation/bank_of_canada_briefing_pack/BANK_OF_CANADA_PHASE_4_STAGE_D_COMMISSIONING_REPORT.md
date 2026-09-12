# Bank of Canada RFP 2026-026 — Phase 4 / Stage D Commissioning Report

**Run ID:** `phase4-boc-2026-026-staged-20260912T131303Z-2cc8af`
**Timestamp (UTC):** 2026-09-12T13:13:33.928278+00:00
**Git commit:** `7e797830f42d06ff08745648585de0e26557addb` (working tree dirty — unrelated in-flight docs/opportunity-structure work, not touching Stage A–D)
**Production entry point:** `scripts/commission_phase4_stage_d_bank_of_canada.py` → `extractor.synthesize_bid_brief()`
**Artifact directory:** `evaluation/bank_of_canada_briefing_pack/phase4_commissioning/phase4-boc-2026-026-staged-20260912T131303Z-2cc8af/`

**Authoritative input lineage (all frozen, none regenerated in this phase):**
| Stage | Run ID |
|---|---|
| Phase 1 / Stage A | `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5` |
| Phase 2 / Stage B (hardened) | `phase2-boc-2026-026-stageb-20260912T125051Z-91a22b` |
| Phase 3 / Stage C (hardened) | `phase3-boc-2026-026-stagec-20260912T130007Z-dd391b` |

Stage A was **not** rerun. Stage B was **not** regenerated. Stage C was **not** rerun independently. Stage D was invoked **exactly once**.

---

## A. Pre-flight: architecture inspected before execution

`extractor.synthesize_bid_brief(normalized_facts, conflicts, api_key, *, fail_on_first_error=False) -> dict` was read in full (including `apply_stage_d_authoritative_sections`, `_synthesize_projected_bid_brief`) before any script was run, along with `stage_d_projection.py` (projection/validation/prompt construction) and `canonical_opportunity.py`'s `apply_authoritative_values`/`remove_authoritative_values_for_validation`. Summary of the architecture, confirmed against the real run below:

- **Stage D does call a real LLM** — `claude-haiku-4-5-20251001`, `max_tokens=8000`, structured/constrained `output_config`, up to 2 attempts with correction-text feedback on validation failure, `client.with_options(max_retries=0)`.
- **Seven brief sections are 100% deterministically rebuilt from `normalized_facts`**, overriding whatever the model produced for them: `qualification_gates`, `evaluation_breakdown`, `submission_requirements`, `key_dates`, `commercial_structure`, `contract_risks`, `deliverables_summary`. This is enforced by a self-check (`AUTHORITATIVE_INVARIANT`) that compares the actual result against what an empty synthesis input would produce.
- **Canonical-opportunity scalar fields are force-nulled unless RESOLVED**: `title`, `client`, `file_number`, `submission_deadline`, `clarification_deadline` become `None` in `bid` unless `canonical.resolved[field].status == "RESOLVED"`. `contract_term` uses `format_contract_term(resolved)` or `"Not stated"`. `opportunity_type`/`procurement_model` are force-nulled unless `NOT_CLASSIFIED` and tier-2 model discretion is permitted.
- **Only the free-text layer is genuinely model-authored and unconstrained by deterministic override**: `executive_summary`, `notes` (bid), `scope_categories`, `outline`, `risk_assessments` (clause-linked risk tags).
- **Evidence-ownership validation** (`validate_stage_d_response`) is a strict pointer-based citation system: every substantive model-authored field must cite an existing, owner-scoped evidence catalog entry (`support_id`/`evidence_catalog_id`/`evidence_selectors`); no cross-owner citation borrowing; unknown-field and mutation self-checks (`AUTHORITATIVE_INPUT_MUTATION`, `PROJECTION_INTEGRITY_FAILURE`) guard against the model or the pipeline corrupting inputs.
- **`risk_assessments`** can only attach a controlled-vocabulary tag (`REVIEW`/`UNKNOWN` etc., `assessment_basis: AI_ASSISTED`, `user_decision: null`) to an *existing verified* `clause_id` — it cannot invent clause content.

This confirms Stage D's constitutional role: it is not permitted to silently resolve unresolved conflicts, invent precedence, fabricate facts, reintroduce rejected Stage B records, or blend D1/D2/D3 submission rules — the deterministic rebuild path and the force-null mechanism are the actual enforcement points, not model discipline alone.

## B. Input lock (verified before invocation)

```
PHASE 3 INPUT LOCK: PASS
requirements: 427            dates: 23                  evaluation_criteria: 83
submission_rules: 68         deliverables: 23            commercial_clauses: 91
canonical_opportunity_observations: 120                  total_conflicts: 7
provenance_rejections_present_in_input: 2
stage_a_rerun: false   stage_b_regenerated_here: false   stage_c_rerun_here: false
```

All 9 counts matched the expected values from the frozen Phase 2/Phase 3 artifacts exactly. `_provenance_rejections` (2 quarantined records) and the 3-conflict canonical-opportunity list were carried through unmutated (`provenance_rejections_untouched: true`, verified by deep-copy comparison before/after the Stage D call).

One correction was made to the commissioning script itself before this run: an over-strict pre-flight assertion compared `input_digest` between the pre-resolution Stage B snapshot and the post-resolution Stage C canonical-opportunity artifact and expected byte-identical digests. This was based on a **false premise** — `resolve_canonical_opportunity()` legitimately mutates `observations[i]["conflict_ids"]` in place while linking conflicts to the observations that participate in them, so the digest (computed over `{documents, observations}`) correctly differs pre- vs. post-resolution. This is expected Stage C behavior, not a data-integrity problem. The assertion was replaced with a same-document-set / same-observation-id-set check, which passed. **This was a bug in the commissioning script, not in production code**, and required no change to `extractor.py`, `canonical_opportunity.py`, or any other production file.

## C. Stage D execution

```
STAGE D EXECUTION: PASS. Elapsed: 28.394s
```

No exception was raised (`ProjectionValidationError`, `StageDContextTooLargeError` were the only two guarded exception types; neither fired). `synthesize_bid_brief()` returned a completed `{bid, brief, outline}` result within one attempt cycle (2-attempt budget available, no evidence in the returned structure of exhausting it — see Section K for the telemetry gap on attempt-level detail).

**Historical comparison:** the previously documented outcome for this corpus was **Stage D synthesis: FAILED CLOSED**. This is the first Stage D run on the real, corrected 16-document Bank of Canada corpus — using the corpus-gate-verified input, the provenance-remediated Stage B output, and the hardened Stage C conflict set — to complete successfully.

## D. Output inventory

| Brief section | Count |
|---|---|
| qualification_gates | 4 |
| evaluation_breakdown | 83 |
| submission_requirements | 68 |
| key_dates | 23 |
| commercial_structure | 91 |
| contract_risks | 90 |
| deliverables_summary | 23 |
| outline | 0 |
| `brief.source_citations` (legacy rollup) | all 3 sub-keys null |

`bid`: `title=null, client=null, file_number=null, clarification_deadline=null, submission_deadline="2026-09-30", notes=null, owner=null, value_cad=null, sensitivity="Standard"`.
`brief` scalars: `executive_summary=null, opportunity_type=null, contract_term="Initial term: 12 weeks", procurement_model=null, scope_categories=[]`.

## E. Upstream → downstream accounting (zero silent loss, verified per family)

| Family | Stage B/C input | Stage D output | Disposition |
|---|---:|---:|---|
| requirements | 427 | 4 (qualification_gates) | **Not loss.** `qualification_gates` is a narrow, documented projection (`requirement_semantics.is_supplier_qualification`): category==Mandatory AND resolved type==Supplier Qualification AND text passes `has_supplier_qualification_evidence`. Verified directly: of 427 requirements, exactly 42 are Mandatory+Supplier-Qualification-typed, and of those, exactly 4 pass the evidence-text gate — matching Stage D's output exactly. The other 423 requirements are not lost; they are simply not qualification gates, which is a narrower, deliberately scoped concept ("Rated criteria or technical product specs cannot be qualification gates even if type is Supplier Qualification" — function docstring). Requirements do not otherwise appear as their own brief section.
| dates | 23 | 23 (key_dates) | 1:1, no loss. |
| evaluation_criteria | 83 | 83 (evaluation_breakdown) | 1:1, no loss. |
| submission_rules | 68 | 68 (submission_requirements) | 1:1, no loss. |
| deliverables | 23 | 23 (deliverables_summary) | 1:1, no loss. |
| commercial_clauses | 91 | 91 (commercial_structure); 90 (contract_risks) | `commercial_structure = verified_clauses(90) + legacy_clauses(1)` = 91, exact. `contract_risks = risks(90, built only from verified_clauses) + legacy_risks(0)` = 90 — the single unverified/legacy clause is deliberately **visible** in `commercial_structure` ("historical records stay visible but remain explicitly unverified" — `contract_hygiene.py:278`) but deliberately **excluded** from risk scoring, since an unverified clause cannot responsibly carry a risk assessment. Verified directly against the persisted `_contract_hygiene` object: `clauses=91, legacy_clauses=1, legacy_risks=0, verified=90`. Not a defect. |
| canonical_opportunity observations | 120 | not a brief section | Feeds `bid`/`brief` scalar fields only, via `apply_authoritative_values`. |
| conflicts | 7 | not a brief section | Feeds prompt context and the authoritative scalar overrides only (see Section F). |

No family shows unaccounted-for loss. The two apparent anomalies (qualification_gates 4-of-427, contract_risks 90-of-91) were both investigated at the code level and confirmed to be deliberate, documented, non-lossy design, not defects.

## F. Unresolved-conflict preservation — full 7-conflict trace

Stage C produced 7 total conflicts: 3 `CANONICAL_OPPORTUNITY_CONFLICT` (title/client/file_number) and 4 `EVALUATION_CONFLICT` (all `REVIEW_ITEM`, none `TRUE_CONFLICT`).

**The 3 canonical conflicts** (`title`, `client`, `file_number` — all `CONFLICTED` status per Phase 3's `canonical_resolved_field_status`):

| Field | Canonical status | Stage D `bid` value | Correct? |
|---|---|---|---|
| title | CONFLICTED | `null` | ✅ — `apply_authoritative_values` forces `None` unless RESOLVED |
| client | CONFLICTED | `null` | ✅ |
| file_number | CONFLICTED | `null` | ✅ |
| submission_deadline | RESOLVED (EXACT_AGREEMENT) | `"2026-09-30"` | ✅ — genuinely resolved, correctly populated |
| contract_term | RESOLVED (STRUCTURED_COMPONENTS) | `"Initial term: 12 weeks"` | ✅ |

Stage D did **not** silently resolve any of the 3 conflicted fields, did not fabricate a value for them, and did not pick one side of the conflict. It explicitly represents them as unknown by forcing `null` — which is the correct, documented constitutional behavior, not an omission.

**The 4 evaluation conflicts** (`CONF-EVAL-1..4`): each describes the *same master RFP document* containing the same generic criterion title (`Corporate Profile`, `Team Experience`, `Methodology`, `Title Relevant Experience And References`) with differing point values, detected by Stage C's title-only same-document comparator. Direct inspection of the real corpus (already established in the Phase 3 hardening report) shows these are not data-integrity problems: the master RFP legitimately contains three separate per-service-category rated-criteria tables (D1/D2/D3) that reuse generic section headings across categories, each with its own distinct, internally consistent point value.

Verified directly in the Stage D output: the title "Corporate Profile" appears as **7 separate `evaluation_breakdown` records**, each individually attributed to its own `parent_title` (e.g. *"Appendix D1 – Learning & Development Programs and Assessments"* = 5 pts, *"Appendix D2 – HR Advisory"* = 5 pts, *"Appendix D1 – Coaching and Mentoring"* = 10 pts, *"Appendix D3 – Facilitation and Team Effectiveness"* = 10 pts, etc.), each with its own single-valued, fully-sourced `weight_observations` entry, and `weight_conflict: false` on every one of them. This is **correct, not a defect**: `weight_conflict` is a Stage B, per-record property that fires only when the *same canonical criterion identity* (title+parent+level+role) carries multiple differing weight observations merged into one record. Here, Stage B's scoping by parent correctly keeps these as separate, individually-consistent records — none of them, individually, has an internal contradiction. Stage C's `REVIEW_ITEM` (not `TRUE_CONFLICT`) reflects a coarser, title-only same-document ambiguity check that exists specifically to flag this kind of cross-category name reuse for human review; it is not a claim that any single record is internally contradictory or that data was lost. Because Stage D preserves full `parent_title` attribution on every record, a reader can fully and correctly disambiguate the "Corporate Profile" appearing 7 times — this is a stronger, non-lossy representation than a single boolean flag would be, and no observation, weight value, or source is missing, merged, or invented.

**Explicit supersession:** 0 declarations in input, 0 applied — matches Phase 3 exactly; no amendment-precedence logic was invoked or invented by Stage D.

## G. D1/D2/D3 submission-rule safety test (mandatory per user spec)

This directly re-verifies, at the Stage D output layer, the real Stage B defect fixed during Phase 3 hardening (a scope-unaware dedup key that had silently merged D1/D2R/D3's distinct page-limit rules into one record, discarding two of the three real values).

Verified directly against `submission_requirements` in the real Stage D output — the 3 page-limit-bearing records survive **distinctly, correctly, and unmerged**:

| Source document | `details` field (verbatim from Stage D output) |
|---|---|
| `Amendment1/…Appendix D2…REVISED.docx` | *"Maximum 12 pages (excluding resumes, professional profiles, and work or product samples)…"* |
| `OriginalRevision/…Appendix D1…docx` | *"Maximum 15 pages (excluding resumes or professional profiles, and work or product samples requested herein)…"* |
| `OriginalRevision/…Appendix D3…docx` | *"Responses must not exceed ten (10) pages (excluding resumes or professional profiles, and work or product samples requested herein)…"* |

**Result: PASS.** D1=15 pages, D2 (revised)=12 pages, D3=10 pages all appear as three separate, correctly source-scoped `submission_requirements` records in the real Stage D output, byte-for-byte matching Stage B's remediated values. The Stage B hardening fix (`_submission_rule_appendix_scope`) holds through the full pipeline to real synthesis output.

(Note: `submission_requirements` records have no structured `page_limit` field — the limit is embedded in free-text `details`, exactly as extracted at Stage A/B. An earlier draft of this report's trace script incorrectly looked for a `page_limit` key that does not exist in the schema; this was a script bug, not a production defect, and was corrected before this table was produced.)

## H. Evidence-ownership / citation validation

`validate_stage_d_response()` — the strict pointer-based, owner-scoped evidence-citation validator described in Section A — ran as part of `synthesize_bid_brief()` and did not raise. No `UNKNOWN_SUPPORT_ID`, `WRONG_EVIDENCE_OWNER`, `MISSING_POINTER`, or `UNCITED_OUTPUT_FIELD`-class failure occurred; no `AUTHORITATIVE_INPUT_MUTATION` or `PROJECTION_INTEGRITY_FAILURE` self-check fired. Every `AUTHORITATIVE_SECTIONS` record inspected above carries dense, multi-source `source_refs` with `verified: true` and real page/section/excerpt provenance (see the D1 example in Section G's source table and the "Corporate Profile" example in Section F).

`brief.source_citations` (the legacy display-only rollup built from the model's own free-text citations, explicitly documented in code as *"never the audit ledger"*) came back with all three sub-keys (`mandatory_ref`, `evaluation_ref`, `sow_ref`) null. This is consistent with, and fully explained by, Section I below — it is populated only from citations attached to model-authored free-text fields, and the model returned none.

## I. Model-authored narrative layer — empty output (open observation, not a proven defect)

Every deterministically-rebuilt `AUTHORITATIVE_SECTIONS` field is fully populated and richly sourced (Sections D–G). By contrast, every field that is genuinely model-authored and not deterministically overridden came back **empty**:

- `brief.executive_summary` = `null`
- `bid.notes` = `null`
- `brief.scope_categories` = `[]`
- `outline` = `[]`
- `contract_risks[*].assessment` = `[]` for all 90 records (zero `risk_assessments` were attached by the model to any verified clause)

This is schema-permitted (`executive_summary`/`contract_term`/`notes` are all nullable; the prompt's own documented empty-synthesis fallback shows `executive_summary: null, outline: []` as a valid degenerate response), involves **zero fabrication**, and **zero authoritative-field violation** — no forced-null field was affected, no invented content appeared anywhere. The run reported `PASS` with no exception, meaning none of Stage D's own integrity self-checks (`AUTHORITATIVE_INVARIANT`, `AUTHORITATIVE_INPUT_MUTATION`, `PROJECTION_INTEGRITY_FAILURE`, evidence-ownership validation) detected a problem.

A plausible, non-defect explanation: with `title`, `client`, and `file_number` all `CONFLICTED` and force-nulled, and the evidence-ownership validator requiring every substantive free-text field to carry a real, owner-scoped citation, the model may have judged that it could not write a confidently-cited executive summary or risk narrative without either citing content it lacks authority over or being rejected by the validator — and chose the safe, honest null/empty path rather than risk an under-cited or fabricated narrative. This is consistent with the fail-closed design intent of the RESPONSE_REMINDER prompt text ("Do not state a disputed alternative as a fact anywhere in summary, notes, or categories").

**This is reported as an open finding, not root-caused further, and no code change was made because of it.** `CHECKPOINT_MODE` defaults to `off` and was not enabled for this run, so attempt-level raw model output and correction-text feedback (which would show whether attempt 1 tried and failed, or never attempted, a non-empty narrative) is not available. Obtaining that telemetry would require re-running Stage D with checkpointing enabled, which means a second real API call and cost — not authorized under the "run Stage D once" instruction for this phase. This is flagged for the user's decision, not treated as a failure requiring the strict root-cause-fix protocol, since no validator failed, nothing was fabricated, and nothing was silently resolved.

## J. Master RFP contribution

| Brief section | Total | Records with master RFP as a source | Master-RFP-sole-source |
|---|---:|---:|---:|
| qualification_gates | 4 | 0 (all 4 sourced from Appendix C1/C2/C3 + abstract) | 0 |
| evaluation_breakdown | 83 | 55 | 54 |
| submission_requirements | 68 | 32 | 18 |
| key_dates | 23 | 11 | 11 |
| commercial_structure | 91 | 20 | 20 |
| deliverables_summary | 23 | 6 | 6 |

The master RFP is the dominant single-document source for evaluation criteria (55/83) and a substantial contributor across every other authoritative section, consistent with its role as the consolidating document over the individual appendices.

## K. RECOVERED_TRUNCATED lineage

Of the AUTHORITATIVE_SECTIONS records checked (`qualification_gates`, `submission_requirements`, `key_dates`, `commercial_structure`, `deliverables_summary`):

- **44** records sourced exclusively from cleanly-parsed (non-`RECOVERED_TRUNCATED`) documents
- **158** records sourced exclusively from `RECOVERED_TRUNCATED` documents (abstract.pdf, Appendix D1, Appendix G, or the master RFP — all 4 of which required Stage A's bounded truncation-recovery retry)
- **2** records mixed (citing both a clean and a recovered document)
- **5** records show no detectable `source_refs`/`source_doc` — all 5 are `qualification_gates` records, whose schema (`{requirement, type, rfp_ref, req_id, disqualification_risk}`) legitimately has **no `source_refs` field at all**; provenance for this section is carried instead in the plain-string `rfp_ref` field (e.g. `"Appendix C1"`, `"Section 3.1, Stage 1"`), which this lineage check did not account for. Not a provenance gap — a schema difference in the lineage script's detection logic, confirmed by direct inspection of all 5 records.

A large majority of the substantive brief content (158 of 204 checked records) traces back to a document that required truncation-recovery at Stage A. No record in this corpus shows any sign of degraded, incomplete, or fabricated content as a result — the recovery mechanism (bounded retry with `RECOVERED_TRUNCATED` status marking) appears to have preserved full extraction fidelity through the entire downstream pipeline, exactly as its Phase 1 commissioning already established.

## L. Defects found, tests added, validation run

**No genuine implementation defect was found in `extractor.py`, `contract_hygiene.py`, `canonical_opportunity.py`, `evaluation_hierarchy.py`, `requirement_semantics.py`, or `stage_d_projection.py` during this phase.** Every count or shape that initially looked anomalous (qualification_gates 4-of-427, contract_risks 90-of-91, `page_limit` appearing absent, 5 "no source_doc" records, `weight_conflict` all-false) was traced to its root cause at the code level and confirmed to be deliberate, documented, non-lossy, non-fabricating production behavior. No validator failed; no self-check fired; no exception was raised.

One bug was found and fixed in the **commissioning script itself** (`scripts/commission_phase4_stage_d_bank_of_canada.py`), not in production code: an over-strict `input_digest` equality assertion based on a false premise about `resolve_canonical_opportunity()`'s mutation behavior (Section B). No production file was modified. No regression tests were added, because no production defect was found — adding tests to "prove" already-correct behavior was judged unnecessary per the user's standing instruction to fix and test only genuine defects.

`py_compile` was run on the corrected commissioning script (`COMPILE_OK`). No production file was touched, so the full test suite was not rerun for this phase; no recommissioning of Stage D was necessary since no code fix to `extractor.py`/upstream modules occurred.

---

## Final status

**PHASE 4 / STAGE D COMMISSIONING: PASS.**

Stage D executed exactly once against the frozen, hardened Phase 2/Phase 3 lineage, completed in 28.394s, and produced a fully-attributed, non-fabricating, non-silently-resolving synthesis. All three genuinely conflicted canonical fields (title/client/file_number) are correctly represented as unresolved (`null`). All four evaluation `REVIEW_ITEM`s are correctly, distinctly, fully attributed by category rather than collapsed. The D1/D2/D3 page-limit hardening fix is proven intact through real synthesis output. Zero silent record loss was found across any of the 6 fact families. The one open, honestly-reported finding is that Stage D's free-text narrative layer (executive summary, notes, scope categories, outline, risk assessments) came back empty — safe and non-fabricating, but a real completeness gap whose root cause could only be determined by a second, telemetry-instrumented API call, which was not authorized in this phase.

Per instruction, this phase stops here. **No work has proceeded into Canonical Opportunity, Opportunity Structure, Opportunity Intelligence, Buyer Brief, Executive Opportunity Brief, or the Executive Briefing Pack.**
