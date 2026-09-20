# Bid Intelligence — Product Integration Phase 4: Cross-Procurement Generalization & Upload Robustness

**PRODUCT INTEGRATION PHASE 4: FAIL — GENERALIZATION NEEDS CORRECTION**

This is not a routing or upload-mechanics failure. Routing, upload handling, milestone progress, refresh/reconnect, PDF generation, report regeneration, and per-fact source provenance all generalized correctly, with concrete live evidence below. The failure is in the **report/UI content-assembly layer** (`scripts/fast_analysis_report_adapter.py`), which is deeply hardcoded to Bank of Canada RFP 2026-026 far beyond filenames — and which, for a materially different real procurement, produced a live report and UI that state "Bank of Canada" as the buyer's own procuring intent, reproduce Bank of Canada's evaluation table verbatim, and reproduce Bank of Canada's three ambiguities verbatim, all under a different buyer's cover page. This was found, evidenced with page numbers, and reported — not engineered around.

---

## 1. Preflight risk map (produced before any code change)

Inspected `fast_analysis.py`, `scripts/fast_analysis_report_adapter.py`, `fast_analysis_app_adapter.py`, and `analysis_service.py` for every place identity/routing/rendering depends on Bank of Canada-specific corpus assumptions.

| # | Location | Dependency | Predicted consequence for a new corpus |
|---|---|---|---|
| 1 | `fast_analysis.py::DOCUMENT_ROUTING` | Exact BoC filenames (incl. `OriginalRevision/`/`Amendment1/` subdirectory prefixes) | Every document falls back to `ROUTE_IDENTITY_EVAL_REQ` (the engine's own documented safe fallback). No document ever gets `ROUTE_COMMERCIAL_ONLY` -> `commercial_clauses` never requested by any schema -> commercial facts never extracted for any non-BoC corpus. |
| 2 | `fast_analysis.py::PAGE_LIMIT_DOCUMENTS`, `BATCH_GROUP` | Same, exact BoC filenames | Deterministic page-limit extraction and batching simply don't fire — an efficiency loss, not a correctness bug (already degrades to "not extracted" everywhere it's consumed). |
| 3 | `fast_analysis.py::find_section()` / `_SECTION_START_PATTERNS` | Literal heading text ("Rated criteria", "Stage 4. Pricing") | Content-dependent, not filename-dependent, but still BoC-specific wording. A different RFP's own headings won't match -> `evaluation_occurrences`/`pricing_occurrences` (the V4 focused-task, occurrence-level data) come back empty -> ambiguity detection falls back to the older, coarser heuristic; the Phase 2 per-criterion "View Source" table has nothing to show. **Engine-layer (fast_analysis.py); not modified, per instruction 7.** |
| 4a | `scripts/fast_analysis_report_adapter.py::MASTER_RFP` | `doc_metadata_by_doc.get(MASTER_RFP, {})`, an exact BoC filename | For any other corpus this returns `{}`, and every identity field then falls back to a Bank-of-Canada-shaped default (`buyer = meta.get("client") or "Bank of Canada"`). **Fixed** — see §6. |
| 4b | `scripts/fast_analysis_report_adapter.py::CATEGORY_NAMES`, `for cat in (1,2,3)` | Hardcoded assumption of exactly 3 named BoC categories | Any corpus with a different category count/structure still gets a report claiming exactly 3 BoC-named categories. **Not fixed** — see §14. |
| 4c | `scripts/fast_analysis_report_adapter.py` — unconditional `DEEP.*` copies (`EVAL_STAGES`, `BID_MECHANICS`, `PROCURED_INTRO`, `PROCURED_STRUCTURE`, `RESPONSE_CHECKLIST`, `SOURCE_DOCUMENTS`, etc.) and the literal `"Service Categories": "3 — Learning & Development, HR Advisory, Facilitation & Team Effectiveness"` string | Static Bank of Canada content copied regardless of the live corpus | Whole report sections (procurement intro, response-requirements checklist) show Bank of Canada's own content for any corpus. **Not fixed** — see §14. |
| 4d | `scripts/fast_analysis_report_adapter.py::_build_ambiguities()` | `if not tagged: tagged = [...DEEP.AMBIGUITIES]` | An empty (correctly-computed, genuine) ambiguity result was treated as "extraction incomplete" and silently replaced with Bank of Canada's own three real ambiguities. **Fixed** — see §6 (found live, not predicted in the original preflight pass — see §9). |
| 5 | `fast_analysis_app_adapter.py::build_opportunity_intelligence()` | Calls `build_fast_report_content()` internally | Inherits all of #4a-4d transitively — the live UNDERSTAND-stage UI shows the same fabricated content as the PDF, not just the PDF. |
| 6 | `database.save_upload()` / real browser upload | Browser file pickers never expose subdirectory paths | Confirmed empirically (§4): every real upload in this product's history, including the two pre-existing corpora used here, has flat, no-subdirectory filenames. This is why #1 always applies to any real, non-repository-fixture upload for any document other than the master RFP. |

**Practical consequence determined before writing any code:** routing itself was expected to behave safely (generic fallback, not a crash) for any corpus; the real risk was that the *report-assembly* layer would silently substitute Bank of Canada's own facts wherever it couldn't find something under an exact BoC filename or dict key. This was confirmed exactly, with two distinct manifestations (#4a, #4d) findable and fixable, and two (#4b, #4c) requiring a genuine report redesign that is out of this phase's "smallest generalizable fix" scope.

---

## 2. Second procurement selected

**Canada's Drug Agency (CDA-AMC) — Coaching Services (Request for Standing Offers, File #C-262700410)**, bid_id **3**, a pre-existing real bid record in the live application (inspected before use; not created for this phase, and never duplicated).

| Property | Bank of Canada RFP 2026-026 | CDA-AMC Coaching RFSO |
|---|---|---|
| Buyer | Bank of Canada (central bank) | Canada's Drug Agency (federal health-technology-assessment agency) |
| Instrument | RFP, category-based multi-service award | RFSO (Request for **Standing Offers**) with Call-ups, single scope |
| File count | 16 | 5 |
| File naming | `RFP 2026-026 - Appendix D1 - ...` + `OriginalRevision/`/`Amendment1/` subdirectories | `C-262700410 CDA-AMC Coaching Services RFSO <part> Final(PDF).pdf`, flat, no subdirectories |
| Category structure | 3 separately-scored categories (D1/D2/D3, each its own form) | 1 scope, no scored categories (3 non-scored coaching "groups" by seniority tier) |
| Evaluation structure | Per-category weighted tables, 20 criteria total (7+7+6) | One combined table: Stage I (mandatory Yes/No) + Stage II (80 pts, 10 rated criteria) + Stage III (20 pts, 1 pricing criterion) |
| Approximate size | ~1.5MB, 21-page master + appendices | ~1.36MB, 27-page main document + 4 short bulletins (2-4 pages each) |
| Genuine quirk found | — | The two earliest bulletins' **filenames** ("Bulletin #02"/"#03") are one number ahead of their own **internal document text** ("Bulletin #01"/"#02") — a real, pre-existing, unmanufactured filename/identity inconsistency. |

## 3. Human source-truth checklist

Built **before** running Fast Analysis, from deterministic-only text extraction (`extractor.extract_document_with_metadata` — zero LLM calls) plus direct human reading of all 5 documents. Saved as [PHASE4_SOURCE_TRUTH_CHECKLIST.json](PHASE4_SOURCE_TRUTH_CHECKLIST.json). Key facts: buyer CDA-AMC, file #C-262700410, submission 2026-08-06 14:00 Ottawa, clarification 2026-07-23, contract term 2026-10-01 to 2029-09-30, 10 evaluation criteria (5%/5%/40%/10%/3%/3%/4%/10% Stage II + 20% Stage III, verified internally consistent), 6 mandatory/gate items (incl. $2M liability + $2M E&O insurance treated as scored-but-mandatory rows), and — deliberately — **no genuine ambiguity of Fast Analysis V4's three detector classes was found anywhere in the corpus** (no repeated-criterion weight conflict, no embedded price-in-category-table alongside a separate pricing stage, no category-scoped date distinction, since there are no scored categories at all). This last point matters: for this corpus, the *correct* answer for all three ambiguity classes is NOT_PRESENT.

## 4. Real browser upload path

The 5 CDA-AMC documents were **not** uploaded by this phase — they were already present in the live application (uploaded via `database.save_upload()`, storage paths confirming the standard `{bid_id}/{uuid}.pdf` convention, not a repository fixture path), a genuine prior real use of the product. Confirmed their filenames reaching Fast Analysis are exactly the flat, no-subdirectory names a browser `st.file_uploader` produces (see §2 table) — directly confirming the previously-documented commissioned-baseline limitation ("browser upload strips original path context") without needing to re-upload anything.

## 5. Preflight routing test (before any live LLM call)

Ran `route_document()`, `find_section()`, and `BATCH_GROUP` membership against all 5 real filenames and their deterministically-extracted text:

| Uploaded filename | Route selected | In `DOCUMENT_ROUTING`? | Batched? | `rated_criteria` section found? | `pricing_stage` section found? | Verdict |
|---|---|---|---|---|---|---|
| `...Main Document FINAL(PDF) (1).pdf` | `ROUTE_IDENTITY_EVAL_REQ` | No | No | No | No | **QUESTIONABLE** — broadest available schema; correctly extracts identity/dates/general evaluation_criteria, but structurally cannot request `commercial_clauses` (only `ROUTE_COMMERCIAL_ONLY` does) even though this document genuinely contains commercial clauses (insurance, payment terms, AI policy). Not "obviously misrouted" — no better route exists without a schema/dispatch change (out of scope, §7). |
| `...Bulletin #02 Final(PDF).pdf` | `ROUTE_IDENTITY_EVAL_REQ` | No | No | No | No | QUESTIONABLE — generic fallback for a short Q&A addendum; not incorrect, not optimally narrow. |
| `...Bulletin #03 Final(PDF).pdf` | `ROUTE_IDENTITY_EVAL_REQ` | No | No | No | No | QUESTIONABLE (same reason) |
| `...Bulletin #04 Final(PDF).pdf` | `ROUTE_IDENTITY_EVAL_REQ` | No | No | No | No | QUESTIONABLE (same reason) |
| `...Bulletin #05 Final(PDF).pdf` | `ROUTE_IDENTITY_EVAL_REQ` | No | No | No | No | QUESTIONABLE (same reason) |

No document was classified INCORRECT (nothing crashed, nothing was silently skipped, no route was actively wrong for the content it received). Confirmed live after the run: the general-schema evaluation_criteria path DID correctly populate from the Main Document (used by the older `evaluation_breakdown`/`bid_briefs` rendering), so the "no optimized route" finding did not, on its own, prevent evaluation data from reaching the UI — it only meant the V4 occurrence-level data (§1 row 3) stayed empty. Proceeded to the live run per instruction 5 (no critical document was obviously misrouted **due only to filename/path handling** — the identity/routing layer behaved exactly as its own documented generic-fallback design intends).

## 6. Routing/adapter fixes made (smallest generalizable issue only)

Two fixes, both in the **application/adapter layer** (`scripts/fast_analysis_report_adapter.py`) — **`fast_analysis.py` (the frozen V4 engine) was not modified**, and neither fix adds anything specific to Bank of Canada or to CDA-AMC.

**Fix 1 — `_merged_doc_metadata()` (predicted in the preflight pass, §1 row 4a).** Replaced `result.doc_metadata_by_doc.get(MASTER_RFP, {})` (exact BoC filename lookup) with a merge across every document's `doc_metadata`, first non-empty value per field wins — mirroring the engine's own per-chunk merge pattern (`fast_analysis.py::_merge_chunk_result`). Verified live: buyer now correctly reads "CDA-AMC" instead of defaulting to "Bank of Canada." 11 new deterministic tests (`tests/test_fast_analysis_report_adapter.py`), covering generic/arbitrary/mixed-case/renamed filenames and a Bank of Canada regression check (exact original filename still resolves correctly, unchanged).

**Fix 2 — removed `_build_ambiguities()`'s empty-result fallback (found live, not predicted — see §9).** The pre-Phase-4 code treated a genuinely empty ambiguities result as "extraction incomplete" and silently substituted Bank of Canada's own three real ambiguities. Live commissioning proved this assumption false: CDA-AMC's corpus genuinely has none of the three detector classes, and the old code showed Bank of Canada's ambiguities — citing "RFP 2026-026" and BoC's own October/November presentation dates — as if they belonged to the coaching RFSO. Removed the substitution; an empty list is now reported as empty. One existing V2 test (`test_zero_present_falls_back_to_validated_content_with_correct_tags`) was explicitly asserting the old (now-understood-to-be-wrong) behavior; renamed and updated with a comment explaining why, rather than deleted silently.

**Not attempted:** a generalizable routing-table redesign, a new document-classification stage, embeddings, or any schema/prompt/concurrency change — none were necessary to make these two specific fixes, and Phase 4 explicitly prohibits all of them.

## 7. Fast Analysis V4 intelligence protected

No change to `fast_analysis.py`: extraction prompts, token limits, recovery strategy, concurrency (`MAX_DOCUMENT_CONCURRENCY` still 2), evaluation logic, ambiguity-detection logic, or routing table. All 98 pre-existing Fast Analysis engine tests (V1-V4) pass unchanged. Both fixes are in the report-adapter/application layer only.

## 8. One authorized live run

| Field | Value |
|---|---|
| Bid ID | 3 |
| Analysis run ID | 2 |
| Engine version | `fast-analysis-v4` |
| Corpus digest | `ec0b9d8ff52a4e0b46711881f44389cc69bfc408cd240780bbc098aac1d9a624` |
| `created_by` | `app-ui` (started by clicking the real "⚡ Run Fast Analysis" button) |
| Wall time (engine-internal) | 202.11s |
| Total LLM calls | 12 |
| Recovery/retry calls | 5 |
| Input / output tokens | 43,920 / 29,540 |
| Documents batched / skipped | 0 / 0 |
| Final status | COMPLETE |

**Milestone sequence** (real task-completion events, not elapsed time — note the non-obvious order, consistent with the concurrent-dispatch behavior already documented in Phase 2/3): `CORPUS_PREPARED` (t+5s) -> `COMMERCIAL_READY` (t+6s, **vacuously** — this corpus has 0 `ROUTE_COMMERCIAL_ONLY` documents, so the milestone fires immediately rather than waiting for an event that can never happen) -> `OPPORTUNITY_IDENTIFIED` (t+15s) -> `PROCUREMENT_STRUCTURE_READY` (t+21s) -> `QUALIFICATION_READY` (t+22s) -> `DATES_READY` (t+223s) -> `EVALUATION_READY` (t+225s) -> `AMBIGUITIES_READY` (t+226s) -> `REPORT_ASSEMBLED` (t+233s). No repeat run was performed or needed — the fixes in §6 were verified by targeted deterministic tests against the exact triggering condition observed live, per instruction 8's own "unless necessary to verify" exception being judged unnecessary here.

## 9. Source-truth comparison

| Category | Result | Evidence |
|---|---|---|
| **Identity** (buyer/title/reference) | **Buyer correct** ("CDA-AMC"); **reference number correct** ("C-262700410"); **title incorrect** ("RFSO Questions and Answers - Coaching Services" — picked up one of the Bulletin documents' own header text rather than the Main Document's actual subject, since multiple documents concurrently returned partial identity guesses under the broad fallback schema and the merge's first-arrival tie-break isn't perfect when several documents legitimately return *some* identity data, unlike Bank of Canada where only one document ever does). Not fixed — see §14. | `opportunity_snapshot.facts` |
| **Dates** | **Correct.** Submission 2026-08-06, clarification 2026-07-23 both match the source-truth checklist exactly, plus additional correctly-extracted dates (intent-to-bid 2026-07-09, amendment 2026-07-28, presentation 2026-08-31) not requested in the compact snapshot but present in the full per-fact detail. | `dates_and_mechanics.raw_date_observations`, live-verified in the browser (see §12) |
| **Scope** | **Incorrect — severe.** Shows Bank of Canada's own 3 categories (Learning & Development / HR Advisory / Facilitation & Team Effectiveness) verbatim; CDA-AMC's actual single-scope coaching structure (3 non-scored seniority tiers) does not appear anywhere. | `procurement_scope`, PDF Section 3, live UI |
| **Qualification** | **Partial.** The 6 mandatory-gate items rendered are generic placeholder-style labels ("Stage I – Mandatory Requirements: Yes", "Mandatory Requirements: Yes") rather than CDA-AMC's actual named gate items (Submission Form, AI Disclosure, Technical/Financial Proposal, the two $2M insurance items) — the underlying `requirements`-family extraction ran under the broad schema but didn't cleanly separate CDA-AMC's actual gate structure. | PDF/UI "Minimum-Qualification Gates" |
| **Evaluation** (criteria and weights) | **Incorrect — severe.** Shows Bank of Canada's exact 20-criterion, 3-category table (Corporate Profile 5pts, Key Personnel 15pts, etc.); none of CDA-AMC's real 10 criteria (References, ESG, Reconciliation, IDEA, AI Methodology, etc.) or its 80/20 Stage II/III point split appear anywhere. | `evaluation.weights_by_category`, PDF Section 5 |
| **Response requirements** | **Incorrect — severe.** Shows Bank of Canada's Appendix A-G checklist (including Appendix D1/D2/D3 rated-criteria forms, which don't exist in this procurement at all). CDA-AMC's real requirements (Supplement A, Schedule A AI Disclosure, 2 separate emailed documents, 20MB limit) do not appear. | `response_requirements.checklist`, PDF Section 6 |
| **Commercial** | **Missing, not wrong.** Only "Contract Term & Extensions" (itself carrying a "3 years years" duplication-formatting bug, pre-existing and unrelated to filenames) is present. The $2M liability/E&O insurance, 30-day payment terms, and AI-use restrictions genuinely present in the source were never extracted, because no document ever received the `ROUTE_COMMERCIAL_ONLY` schema (§1 row 1/§5) — this corpus bundles commercial clauses into the same document as its identity/evaluation content, a structural pattern the current one-schema-per-document routing model cannot serve without a schema or dispatch change (explicitly out of scope, §7). | `pricing_and_commercial.points` |
| **Ambiguities** | **Correct, after the fix in §6.** Before the fix: Bank of Canada's 3 ambiguities shown verbatim (severe leakage). After the fix (verified deterministically against the exact empty-input condition observed live — see §6/§8): correctly empty, matching the source-truth checklist's own conclusion that this corpus genuinely has none of the 3 detector classes. | `_build_ambiguities()` unit tests; live run's persisted result predates the fix (documented, not re-run) |

**Critical-fact accuracy:** of the 8 comparison categories, 2 fully correct (Dates, Ambiguities-post-fix), 1 partially correct (Identity: buyer/reference right, title wrong), 1 partially correct (Qualification: gates present but mislabeled), 3 severely incorrect (Scope, Evaluation, Response requirements — all three showing fabricated Bank of Canada content), 1 missing-not-wrong (Commercial).
**Missing critical facts:** all CDA-AMC-specific commercial/insurance/payment terms; CDA-AMC's real 10 evaluation criteria and their weights; CDA-AMC's real qualification-gate item names.
**Unsupported/fabricated facts presented as real:** Bank of Canada's 3 service categories, Bank of Canada's 20-criterion evaluation table, Bank of Canada's Appendix A-G checklist, Bank of Canada's own procurement-scope narrative text ("Bank of Canada is seeking...") — all shown under CDA-AMC's own cover page and buyer name.
**Incorrect scope conflations:** CDA-AMC's single, uncategorized Coaching Services scope was rendered as if it had Bank of Canada's exact 3-category structure.

## 10. Overfitting check

**`BANK-OF-CANADA OVERFITTING DETECTED: YES`**

Concrete evidence, all captured live (database, PDF, and browser UI, independently):
- PDF page 1 (cover): *"Bank of Canada — RFP 2026-026 / Talent, Learning and Organizational Development Services"* for a CDA-AMC coaching procurement.
- PDF page 4 / UI: *"Bank of Canada is seeking one or more qualified service providers to deliver talent, learning, and organizational development services..."*
- PDF page 6 / UI: Bank of Canada's exact evaluation weighting table (Corporate Profile, Key Personnel & Roster, Curriculum & Program Design, etc., 7+7+6 = 20 criteria) presented as CDA-AMC's own scoring structure.
- PDF page 8 / UI: Bank of Canada's Appendix A-G response-requirements checklist, including forms (D1/D2/D3) that do not exist in this procurement.
- PDF page 10 / UI (before the §6 fix; still true of this run's already-persisted data): Bank of Canada's own 3 ambiguities, citing "RFP 2026-026" and Bank of Canada's own October 26/November 2, 2026 presentation dates, shown as CDA-AMC's ambiguities.
- Buyer Intelligence section (PDF page 3 / UI): profiles Bank of Canada as an organization — **this one is expected and already-accepted, not new leakage**: Buyer Intelligence has been an explicitly unchanged, externally-sourced, Bank-of-Canada-only layer since Phase 1, and Phase 4 explicitly prohibits building new Buyer Intelligence features (instruction 14). Listed here for completeness, not counted as a newly-discovered defect.

Terminology/document-type assumptions: "the Bank" appears in `_pricing_and_term_commercial_rows()`'s hardcoded submission-mechanics text, in the procurement-model description, and in the attention-points text — all copied unconditionally from `DEEP.*` regardless of corpus.

## 11. Product UX verification

- **Progressive milestones:** verified live, real task-completion events, correct plausible-order behavior including one genuinely vacuous milestone (`COMMERCIAL_READY` fired immediately since this corpus has 0 commercial-only documents) — see §8.
- **Early facts:** verified live — buyer, file number, and (later) dates appeared progressively during the run, matching the design (no fabricated "procurement/category structure" early fact was shown, consistent with the Phase 2 design decision).
- **Refresh/reconnect:** not re-tested mid-ANALYZING for this run (same reasoning as documented in the Phase 3 report: polling was done via direct, timestamped DB reads for milestone-timeline precision rather than driving the browser simultaneously); the completion-transition test below exercises the same underlying DB-truthful mechanism.
- **Completed UNDERSTAND stage:** verified live in the browser — clean automatic transition from active-progress to "✅ Fast Analysis complete in 202s," no manual refresh/restart/new-run/page-recreation needed.
- **Source expanders:** verified live and working correctly for date facts (§12). Correctly absent (not broken/blank) for evaluation and pricing facts, since the underlying occurrence data is genuinely empty for this corpus (§1 row 3) — the UI's existing `if raw_occ:`/`if raw_pricing_occ:` guards degrade gracefully rather than rendering an empty or broken section.
- **Report generation:** PDF generated successfully through the real application path, 76,828 bytes, 12 pages, no clipping/overflow/broken-table/malformed-character defects — the PDF is *structurally* clean; its *content* is the subject of §9/§10.
- **Report regeneration without extraction:** **PASS**, proven by patching `run_fast_analysis_corpus` to raise `AssertionError` if invoked at all — regeneration still succeeded (2.51s, valid 76,858-byte PDF).

## 12. Source traceability verification

| Fact type | Result |
|---|---|
| Date | **PASS** — live-clicked the "View Source — SUBMISSION_DEADLINE" expander in the browser; it showed the exact real excerpt "Proposal Due Date: 14:00 Ottawa Local Time on August 6, 2026" from `C-262700410 CDA-AMC Coaching Services RFSO Main Document FINAL(PDF) (1).pdf`, page 2 — the correct uploaded document and page. |
| Qualification requirement | Not applicable to this check — qualification gates have never had per-fact "View Source" expanders (a pre-existing Phase 2 scope boundary, not something Phase 4 broke; they use the older compact "SOURCE / EVIDENCE: UNVERIFIED" label, unaffected either way). |
| Evaluation criterion | Not applicable — `evaluation.raw_occurrences` is empty for this corpus (§1 row 3), so no expander is offered; correctly absent, not fabricated. |
| Commercial requirement | Not applicable — `pricing_and_commercial.raw_pricing_occurrences` is empty for the same reason; correctly absent. |
| Ambiguity | Not applicable by design — ambiguity `source` is a plain descriptive string, not a `source_refs` list, unchanged since Phase 1/2. |

**Conclusion: browser-upload normalization did not break provenance anywhere it was actually exercised.** The one fact type genuinely tested (dates) traced correctly to the right document and page.

## 13. Bank of Canada regression

Not re-run live (per instruction 13). Verified two ways:
1. **Deterministic suite:** all 98 pre-existing Fast Analysis engine tests (V1-V4) pass unchanged; the one V2 test whose assertion encoded the now-corrected fallback behavior was updated with a clear rationale (§6), not silently changed.
2. **Already-persisted Phase 3 live commissioning data** (`analysis_results` for run_id 1, untouched by any Phase 4 code change since neither fix retroactively alters stored data) re-inspected read-only:

| Requirement | Result |
|---|---|
| 20 evaluation criteria | ✅ 21 raw occurrences (20 numeric-weighted + 1 "Presentations" pass/fail continuation row), 7+7+6 confirmed |
| 7+7+6 split | ✅ Category D1=7, D2=7, D3=7-occurrences-including-continuation (6 weighted) |
| Pricing-stage ambiguity present | ✅ `PRICING_STAGE_AMBIGUITY` present |
| Scoped category-date difference present | ✅ `CATEGORY_DATE_DISTINCTION` present |
| False evaluation-weight ambiguity absent | ✅ `EVALUATION_WEIGHT_CONFLICT` absent |

**The commissioned baseline does not regress.**

## 14. Remaining generalization risks (not fixed in this phase)

These require redesigning `scripts/fast_analysis_report_adapter.py`'s category-based report structure to be category-count-agnostic and to derive `EVAL_STAGES`/`RESPONSE_CHECKLIST`/`PROCURED_INTRO`/etc. from live data instead of static Bank of Canada content — genuine feature/report-redesign work, explicitly out of this phase's scope ("no new visual design," "smallest generalizable issue," "do not redesign routing/PDF"). Per instruction ("if it reveals a limitation that cannot be fixed without [expanding scope]: do not modify further in this phase, report the limitation and fail the gate"):

1. **Category-based evaluation/scope/response-checklist rendering does not generalize** to a corpus with a different category count or structure (§1 row 4b/4c, §9, §10). This is the dominant, severity-driving finding of this phase.
2. **No document ever receives the `ROUTE_COMMERCIAL_ONLY` schema** unless a document's exact filename matches the BoC Appendix G convention — for a corpus (like this one) that bundles commercial clauses into its main document rather than a separate appendix, commercial facts are never extracted (§1 row 1, §9 Commercial row). Fixing this generally would require either a schema change (prohibited) or a dispatch-layer change that sends more than one schema per document (a genuine architectural change, judged too large for this phase).
3. **`find_section()`'s heading-text matching is corpus-specific wording**, not just BoC-filename-specific — a different RFP's real heading text will very likely never match "Rated criteria"/"Stage 4. Pricing" verbatim, so the V4 occurrence-level (`evaluation_occurrences`/`pricing_occurrences`) data will likely stay empty for most other real procurements too. Engine-layer; explicitly not modified.
4. **Identity merge tie-break is imperfect when multiple documents concurrently return partial identity guesses** (§9 Identity row: title picked from a bulletin instead of the main document). Only manifests for corpora where more than one document gets the broad identity schema — i.e., exactly the corpora this phase is about generalizing to. A more sophisticated tie-break (e.g., preferring the document with the most populated identity fields) was considered and deliberately not implemented, to avoid iterating a heuristic specifically until it looks right for this one corpus.
5. **Buyer Intelligence remains Bank-of-Canada-only content for every corpus** — expected and already-accepted (Phase 1 decision, unchanged, explicitly out of this phase's scope), not a new defect, but worth restating plainly: any future procurement's report will carry a Buyer Intelligence section that is not about that procurement's actual buyer, until that separate, externally-sourced layer is itself built out per-buyer (real feature work, not attempted here).
6. **The "3 years years" duplication-formatting bug** in `_contract_term()` is pre-existing, unrelated to filenames/corpus identity, and was left unfixed as out of this phase's specific scope (identity/routing generalization).

---

## FINAL RESPONSE

**`PRODUCT INTEGRATION PHASE 4: FAIL`**

- Procurement tested: **Canada's Drug Agency (CDA-AMC) — Coaching Services (RFSO), File #C-262700410**
- Bid ID: **3**
- Analysis run ID: **2**
- Corpus digest: **ec0b9d8ff52a4e0b46711881f44389cc69bfc408cd240780bbc098aac1d9a624**
- Browser-upload result: **PASS** — no manual filename/path preparation used or needed; documents were already real, flat-filename browser uploads
- Routing result: **PASS (generic fallback, as designed)** — all 5 documents routed to `ROUTE_IDENTITY_EVAL_REQ`, none INCORRECT, none critically misrouted; the fallback is safe but not optimized (documented, not a defect)
- Routing changes made: **NONE to `fast_analysis.py`**; two small adapter-layer fixes in `scripts/fast_analysis_report_adapter.py` (merged document-identity lookup; removed the empty-ambiguities-substitutes-Bank-of-Canada fallback)
- Critical-fact accuracy: **2/8 categories fully correct (Dates, Ambiguities-post-fix), 2/8 partially correct (Identity, Qualification), 3/8 severely incorrect (Scope, Evaluation, Response requirements), 1/8 missing-not-wrong (Commercial)**
- Missing critical facts: CDA-AMC's real evaluation criteria/weights, real qualification-gate names, real commercial/insurance/payment terms
- Unsupported critical facts: Bank of Canada's 3 service categories, 20-criterion evaluation table, and Appendix A-G checklist, all shown as if belonging to CDA-AMC
- Evaluation result: **FAIL** — Bank of Canada's evaluation table shown verbatim in place of CDA-AMC's real 10-criterion structure
- Commercial result: **FAIL (missing)** — only a formatting-buggy contract-term line; no insurance/payment/AI-policy facts extracted
- Ambiguity result: **PASS, after the live-discovered fix** — correctly empty (matching source truth) once `_build_ambiguities()`'s Bank-of-Canada fallback was removed; this run's own already-persisted PDF/UI still shows the pre-fix fabricated content, documented as such
- Provenance result: **PASS** for every fact type actually exercised (dates, live-verified in-browser); correctly absent (not fabricated) elsewhere
- Overfitting detected: **YES** — concrete, page-numbered, multi-source (DB + PDF + live UI) evidence in §10
- PDF result: **Structurally PASS** (12 clean pages, no rendering defects) / **Content FAIL** (fabricated Bank of Canada content, §9/§10)
- Bank of Canada regression result: **PASS** — commissioned baseline confirmed unchanged, both via the full deterministic suite and by re-inspecting the already-persisted Phase 3 live result
- Full-suite result: **1480 passed, 2 skipped** (`py_compile` clean, `git diff --check` clean)
- Fast Analysis V4 behavior changes: **NONE**
- Deep Verify behavior changes: **NONE**
- Report path: `BID_INTELLIGENCE_PHASE4_GENERALIZATION_REPORT.md`

**Recommendation: `GENERALIZATION NEEDS CORRECTION`**

The routing/upload/persistence/progress/provenance layers generalize correctly and needed only two small, non-buyer-specific adapter fixes. The report/UI content-assembly layer does not generalize and requires real redesign work (§14) — categorized here, evidenced, and explicitly not attempted, per instruction: do not modify further in this phase when a fix would require expanding beyond the smallest generalizable issue; report the limitation and fail the gate.

Then STOP. Not starting another product-development phase automatically.
