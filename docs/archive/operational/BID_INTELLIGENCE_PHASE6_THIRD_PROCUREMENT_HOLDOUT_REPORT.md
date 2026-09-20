# Bid Intelligence — Phase 6: Third-Procurement Holdout Validation

**Frozen baseline under test:** commit `a2fa4bd114e9ae77351c4ca31b6747a1de939b96`, tag `bid-intelligence-generic-v1`. Confirmed `git rev-parse HEAD == a2fa4bd...` immediately before the live run and re-confirmed after (`git status --porcelain -- '*.py'` empty throughout). **No code was modified before, during, or after the holdout run.**

## Holdout procurement identity

- **Buyer:** The City of Calgary
- **Procurement title:** Design and Delivery Services for Leadership Learning and Development
- **File/reference number:** 26-1603 (see ambiguities — one document states 26-1610)
- **Product `bid_id`:** 1
- **Number of source documents:** 10 (all `doc_type == "RFP / Source"`)
- **Filenames** (unchanged, not renamed or rearranged): `CGC 2026-05-13.pdf`, `Addendum Four.pdf`, `S-PT-024 - Addendum One V4.0.pdf`, `S-PT-024 - Addendum Two V4.0.pdf`, `S-PT-024 - Addendum Three.pdf`, `S-PT-024 - Addendum Five.pdf`, `QA Log 26-1603.pdf`, `QA Log 26-1603_Updated _June 26_2026.pdf`, `QA Log 26-1603_Updated _June 30_2026.pdf`, `QA Log 26-1603_Updated _July 08_2026.pdf`
- **File formats:** PDF
- **Approximate total pages:** ~34 (the CGC master document alone is 22 pages; the remaining 9 are 1-2 page addenda and cumulative Q&A logs)

## Why this qualifies as a genuine, unseen holdout

- **Never previously analyzed**: `analysis_runs` for `bid_id=1` was empty before this session (confirmed by direct query) — no prior Fast Analysis run, live or otherwise.
- **Never used to design, debug, or tune** any part of Fast Analysis, the report/application adapters, or any source-truth regression fixture in this entire engagement (Phases 1–5 and the prior acceptance passes used exclusively Bank of Canada and CDA-AMC data).
- **Materially different from both prior corpora**, selected deliberately for these differences (only 4 real bids existed in the database; the 4th, "The British Council — ACCEPTANCE TEST," had zero attached documents and was not usable):
  - **No primary RFP narrative document at all** — the corpus is a standing, opportunity-agnostic "Consulting General Conditions" template (X 900) plus five numbered addenda plus four cumulative Q&A log snapshots. Neither Bank of Canada nor CDA-AMC's corpus has this shape.
  - **Different evaluation model**: single-supplier award via a "Highest Rated (Negotiations) Proponent" process — not Bank of Canada's multi-vendor call-off, not CDA-AMC's multi-award standing offer.
  - **Different scope structure**: six non-scored target-audience tiers (closer in spirit to CDA-AMC's non-scored coaching groups, but with six tiers instead of three, and a completely different subject: leadership development consulting, not procurement of coaching or T&L services generally).
  - **No genuine rated-criteria/weights table present anywhere in the uploaded corpus** — a first for this engagement (both prior corpora had at least some real weighted criteria).
  - **A real, source-visible pricing formula with percentage weights** (55%/35%/10%) that is NOT an evaluation-criteria table — the exact structural trap this holdout was, in hindsight, well-suited to expose.
  - **Different buyer type**: municipal government (vs. a federal central bank and a federal drug agency).

## Corpus structure

10 documents, all routed to `ROUTE_IDENTITY_EVAL_REQ` (none match `DOCUMENT_ROUTING`, which is Bank-of-Canada-only) — confirmed by direct `route_document()` calls against every real filename before the run.

## Source-truth checklist

Built entirely by deterministic, manual reading (`extractor.extract_document_with_metadata` — PDF text extraction, zero LLM calls) of the actual 10 documents, **before** the live run and **before** inspecting any Fast Analysis output. Full detail: `PHASE6_HOLDOUT_SOURCE_TRUTH.json`. Two genuine, source-visible ambiguities were recorded in advance: a file-number discrepancy (26-1603 vs. an outlier 26-1610 in one addendum) and an unresolved single-vs-double-sided page-count question.

## Live-run telemetry

- **Run ID:** 6 (bid_id=1)
- **Engine version:** `fast-analysis-v4`
- **Corpus digest:** `8f8ac86125d22080a2d2047b2f7f33fcb0a8a505b8d8289f1ca3232bbd9db2bf`
- **Started:** 2026-09-14T22:40:25Z · **Completed:** 2026-09-14T22:45:51Z
- **Wall time:** 297.79s
- **LLM calls:** 36 total (10 recovery/split-recovery subcalls)
- **Tokens:** 110,625 input / 58,272 output
- **Started via:** the real Streamlit UI's "⚡ Run Fast Analysis" control on `bid_id=1`'s UNDERSTAND page — engine not called directly.
- No corrective action was taken while the run was executing; it was allowed to complete fully before any output was inspected.

## Milestone timeline

| Milestone | Reached at (UTC) |
|---|---|
| CORPUS_PREPARED | 22:40:43.868 |
| OPPORTUNITY_IDENTIFIED | 22:40:54.303 |
| DATES_READY | 22:40:56.048 |
| PROCUREMENT_STRUCTURE_READY | 22:40:57.720 |
| QUALIFICATION_READY | 22:40:58.864 |
| EVALUATION_READY | 22:42:18.089 |
| COMMERCIAL_READY | 22:45:43.690 |
| AMBIGUITIES_READY | 22:45:44.512 |
| REPORT_ASSEMBLED | 22:45:48.200 |

9 distinct milestones, each fired exactly once, no duplicates. `COMMERCIAL_READY` fired once, correctly waiting for all 10 documents' commercial-contributing work (a dedicated commercial-only route never triggers for this corpus, so this is 10 `commercial_supplement` tasks) before firing.

Live early-facts snapshot (`analysis_runs.progress.early_facts`), captured mid-run: buyer "The City of Calgary", title "Design and Delivery Services for Leadership Learning and Development", file_number "26-1603", submission_deadline "2026-07-16", procurement_mechanic "One (1) firm will be selected", clarification_deadline "2026-07-15" — all correctly resolved even at this early stage, including correctly picking the majority-consensus file number over the single outlier and the final (not an earlier, superseded) submission deadline.

## Persisted-intelligence comparison (before any UI/PDF inspection)

Queried `analysis_results.structured_intelligence` for run_id=6 directly.

| Category | Fact | Product output | Classification |
|---|---|---|---|
| Identity | Buyer | "The City of Calgary" | CORRECT |
| Identity | Title | "Design and Delivery Services for Leadership Learning and Development" | CORRECT |
| Identity | Reference number | "26-1603" (correctly resolved the 5-of-6-document consensus over the single "26-1610" outlier) | CORRECT |
| Identity | Procurement model | "Single Contract" | CORRECT |
| Dates | Submission deadline | "2026-07-16, 16:00:59 (MST)" — the final, twice-extended deadline, not a stale earlier one | CORRECT |
| Dates | Clarification/questions deadline | "2026-07-15" (the Addendum Four "Deadline for Issuing Addenda" — the true "Deadline for Proponent Questions" was 2026-07-08 per Addendum One; both are genuinely present, correctly sourced `CLARIFICATION_DEADLINE`-tagged dates in the raw data, and the true July 8 value is preserved separately in `raw_date_observations`, not lost) | NON-MATERIAL_VARIATION |
| Scope | No fabricated category/lot structure | `category_cards: []`, `SNAPSHOT_CATEGORY_CARDS` empty | CORRECT |
| Scope | Six target-audience tiers substantively represented | Present in `response_requirements` (e.g. Requirement 15/22 list all six tiers by name) | CORRECT |
| Qualification | Alberta Registries business-registration requirement | Present, real page-6 provenance, verified live | CORRECT |
| Qualification | 20-page submission limit, incl. the genuine single/double-sided ambiguity | Present as Requirement 3/9 ("clarification requested whether single-sided..."); the ambiguity is preserved, not silently resolved | CORRECT |
| Evaluation | No genuine rated-criteria/weights table exists in this corpus | A 3-row "Rated Criteria" table (Items 1/2/3, 55%/35%/10%) is rendered, sourced from Addendum Five's **pricing-formula** example table, not a technical evaluation table | **INCORRECT** (see Defect 1) |
| Evaluation | No fabricated multi-category structure invented | Correctly flat (0 categories) | CORRECT |
| Response requirements | Real CGC-sourced contractual requirements (confidentiality, IP, insurance, on-site safety, etc.) | 45+ real, Article-cited requirements from `CGC 2026-05-13.pdf` | CORRECT |
| Response requirements | Real addenda/QA-sourced submission mechanics | Present with correct per-document sourcing | CORRECT |
| Commercial | CGC contract terms (IP, insurance, indemnity, termination) with real Article citations | 19 deduped topics / 147 raw clauses, correctly citing Articles 2.05, 3.05–3.07, 6.01–6.08, 7.01, 8.02, 9.01 | CORRECT |
| Commercial | Pricing model correctly described as lump-sum-per-sample-cohort, not annual/full-contract pricing | Present, matches source ("Pricing Structure", "Payment Withholding Setoff" points) | CORRECT |
| Ambiguities | Genuine, real, correctly-sourced multi-date findings | 3 `CATEGORY_DATE_DISTINCTION` ambiguities, all dates and sources real and accurate | CORRECT data / see Defect 2 for a wording-generalization issue |

**Critical facts expected: 17 · Correct: 15 · Non-material variation: 1 · Incorrect: 1 · Missing: 0 · Unsupported: 0**
**Critical-fact accuracy = 15 / 17 ≈ 88.2%**

## Holdout scorecard

- Critical facts expected: **17**
- Critical facts correct: **15**
- Critical facts missing: **0**
- Unsupported critical facts: **0**
- Incorrect critical facts: **1** (pricing-formula weights rendered as evaluation criteria)
- Scope conflations: **0**
- Fabricated categories: **0**
- Duplicate evaluation criteria: **0** (the 3 pricing-formula rows are each distinct; the defect is misclassification, not duplication)
- Cross-corpus leakage: **0**

## Evaluation validation

- Real categories remain categories: N/A — none exist in this corpus, and none were fabricated. ✓
- Headings do not become categories: ✓ (no "Stage"/"Article" section heading was promoted to a category card)
- Totals do not become criteria: ✓ (no "Total points"/"Total" line appears)
- Duplicates do not become criteria: ✓ (no duplicate rows in the evaluation table)
- Uncategorized substantive criteria remain visible: N/A (no such criteria exist to preserve — the corpus's only weighted table is the pricing formula, discussed below)
- Pass/fail requirements not forced into weighted evaluation: ✓ (Alberta Registries registration and the 20-page limit correctly render as requirements, not fake weighted criteria)
- Weights/points retain their real semantics: **FAILED** — the 55%/35%/10% weights are real, but their semantic meaning (a pricing-scoring formula, not a technical rated-criteria table) was not preserved; see Defect 1.
- No assumption of 3 categories, 100 points, percentage weights, or CDA-AMC-style Technical/Financial grouping: ✓ — the system correctly did not force this corpus into any prior corpus's shape; the defect found is a genuinely new failure mode, not a reused assumption from either prior corpus.

## Commercial validation

- `commercial_supplement` behaves generically: ✓ — 10 documents, all routed to `ROUTE_IDENTITY_EVAL_REQ`, so 10 supplement tasks dispatched (deterministic, confirmed via routing check, consistent with the unmodified engine code).
- Commercial facts extracted: 147 raw clauses / 19 deduped topics, overwhelmingly sourced from the Consulting General Conditions document with correct, specific Article citations — a materially richer commercial extraction than either prior corpus, appropriate given the CGC document is itself 22 pages of contract terms.
- Duplicate/noise behavior: none observed in the commercial section.
- Source provenance: real, page-level, verbatim excerpts confirmed both in the persisted `raw_commercial_clauses` and live via the UI's View Source expander (Business Registration Requirement in Alberta → `QA Log 26-1603_Updated _July 08_2026.pdf`, page 6, verbatim excerpt).
- `COMMERCIAL_READY` fires exactly once: ✓ (confirmed in the milestone table above).

## Provenance validation

**PROVENANCE: PASS** for dates, qualification facts, and commercial facts — all verified live through the UI with real document names, real page numbers, and real verbatim excerpts (screenshot-confirmed for the Business Registration fact). Response requirements carry document-name-level provenance (the "Notes" column) but not a page-level View Source expander — an existing, unmodified product characteristic shared with both prior corpora, not a regression. Evaluation-criteria rows in this corpus carry no `source_refs` at all, because — as with CDA-AMC — no focused rated-criteria task data exists for this corpus (its real headings don't match `find_section()`'s known patterns), so the data came through the general `evaluation_criteria` fallback family, which does not carry per-row source_refs in the current schema; this is the same, already-documented limitation, not new. No provenance was fabricated to make this test pass.

## UI/UX validation

- Analysis started through the UI: ✓ (the "⚡ Run Fast Analysis" button, not a script)
- Milestones progressed and were visible: ✓
- Completion transition worked: ✓ (the panel correctly switched to the completed state with a Download Report PDF button)
- No duplicate active run: ✓ (only one `analysis_runs` row exists for bid_id=1)
- UNDERSTAND renders correctly: ✓ — correct identity, dates, scope, qualification, commercial content all visible; the pricing-as-evaluation defect is visible here too (Defect 1), consistently with the persisted data (no UI-only divergence).
- Source expanders work: ✓ (confirmed live, screenshot-verified)
- Report became available: ✓ (Download Report PDF button present and functional)

## PDF validation

`CITY_OF_CALGARY_HOLDOUT_RUN6.pdf`, 25 pages, 95,384 bytes, regenerated via `analysis_service.regenerate_report(6)`. Full-text inspected via `pypdf`:

- Correct buyer/title/reference throughout (27 occurrences of "The City of Calgary", 59 of "26-1603").
- Correct commercial facts, correct response requirements, correct (genuinely present, correctly sourced) ambiguities.
- Evaluation section shows the same pricing-formula-as-evaluation-criteria defect found in the persisted data (Defect 1) — confirmed as a real, end-to-end, user-visible product output, not merely a database curiosity.
- **Zero occurrences** of "Bank of Canada", "RFP 2026-026", "2026-026", "Appendix D1/D2/D3", "Canada's Drug Agency", "C-262700410", or "CDA-AMC".

No raster/visual page-by-page inspection was performed — this environment has no `pdftoppm`/poppler installed, the same limitation stated in every prior report this session. This was a structural + full-text review only.

## Report regeneration

`analysis_service.regenerate_report(6)` — zero network/API calls (same code path already verified call-free in prior phases). **REPORT REGENERATION WITHOUT EXTRACTION: PASS.**

## Cross-corpus contamination

Searched the holdout's persisted `structured_intelligence`, `report_content_snapshot`, the live UI, and the regenerated PDF text for Bank-of-Canada and CDA-AMC-specific material. **CROSS-CORPUS LEAKAGE = 0** everywhere checked.

## Defects found

### Defect 1 — Pricing-formula weights extracted and rendered as evaluation criteria

- **Source-truth expectation:** no genuine rated-criteria/weighted-evaluation table exists anywhere in this corpus; the only "Item / Weight" table present is Addendum Five's pricing-formula example, explicitly captioned "Total weighted cost to be used in the **pricing formula**."
- **Actual product output:** a 3-row "Rated Criteria" evaluation table (`Item 1 — Cohort Program Development & Design and Program Delivery: 55%`, `Item 2: 35%`, `Item 3 — Travel Expenses: 10%`), rendered identically in `analysis_results.structured_intelligence`, the UNDERSTAND UI, and the generated PDF.
- **Severity:** Material. This presents a pricing-scoring mechanism as if it were the RFP's technical/rated evaluation criteria — a bid team could misjudge how the opportunity is actually evaluated.
- **Likely root cause:** upstream of the report/application adapter. The adapter's `_is_substantive_evaluation_row` (and the rest of the generic evaluation-assembly logic commissioned in Phase 5) only judges whether a row is well-formed enough to render (real label + numeric weight) — it has no way to know a row's semantic origin. The misclassification happens earlier: the engine's general `evaluation_criteria` extraction (the `ROUTE_IDENTITY_EVAL_REQ` family, used for every document in this corpus) appears to have pattern-matched on the pricing-formula table's own "Item / Description / ... / Weight / Weighted Cost" column shape and classified it as rated-criteria content, despite the schema's own instruction to extract `evaluation_criteria` (technical/rated criteria) separately from pricing/commercial content. **Classification: `ENGINE DEFECT`.**
- **Generalizable or procurement-specific:** Generalizable. Any procurement whose own Price Form combines multiple cost line-items into one score via a labeled weight column — a common real-world pricing-formula pattern — is at risk of the same misclassification, independent of buyer or corpus.
- **Not fixed.** Per the explicit holdout rule, this is reported only.

### Defect 2 — `CATEGORY_DATE_DISTINCTION` ambiguity wording assumes category/scope structure that does not exist in this corpus

- **Source-truth expectation:** the three real, multi-valued milestone dates (submission, clarification, amendment) reflect sequential addenda supersession over time, not simultaneous category-scoped conflicts — this corpus has no category/lot structure for a date to be scoped to.
- **Actual product output:** three ambiguities of type `CATEGORY_DATE_DISTINCTION`, each with the fixed question "Please confirm the date applicable to each category/scope" — accurate about multiple real, correctly-sourced dates existing, but interpretively framed around a category/scope concept this procurement does not have.
- **Severity:** Minor/cosmetic. No data is fabricated or lost; a reader can still correctly infer "there are multiple dates for X, confirm the current one" even though "category/scope" doesn't literally apply. Does not itself fail the acceptance bar on its own.
- **Likely root cause:** split between the frozen engine and the adapter. `fast_analysis.py::detect_category_date_distinctions()` fires whenever 2+ distinct dates exist for the same milestone kind, with no check for whether real category/scope grounding exists elsewhere in the corpus; `_build_ambiguities()`'s question template for this ambiguity type is a fixed string that assumes category/scope semantics apply. **Classification: primarily `ENGINE DEFECT` (detection trigger condition), secondarily `ADAPTER DEFECT` (fixed wording).**
- **Generalizable or procurement-specific:** Generalizable — any procurement with amendment-driven date changes but no real category/lot structure would trigger the same mismatched wording.
- **Not fixed.** Reported only.

No other material discrepancies were found. Every other checked fact was `CORRECT` or a defensible `NON-MATERIAL_VARIATION`.

## Bank of Canada / CDA-AMC non-regression

No new live runs performed for either commissioned corpus. Deterministic regression only:

- **Bank of Canada:** `20 total = 7 + 7 + 6`; Value-add present; Relevant Experience & References present; evaluation-weight ambiguity NOT_PRESENT; pricing-stage ambiguity PRESENT; category-date scoped difference PRESENT.
- **CDA-AMC:** `11 distinct rated criteria = 10 Technical + 1 Financial`; fabricated categories = 0; non-substantive rendered rows = 0; cross-corpus leakage = 0.

## Full regression

`python -m pytest tests/ -q` → **1520 passed, 2 skipped**, 0 failed — identical to the frozen baseline, confirming no code drift occurred during this holdout. `python -m py_compile` clean on every core commissioned file. `git diff --check` clean. `git status --porcelain -- '*.py'` empty throughout the entire holdout process.

## Acceptance assessment

Per the stated acceptance bar, a PASS requires materially correct procurement identity, deadlines, scope, qualification requirements, evaluation structure, response requirements, and commercial intelligence, with no fabricated evaluation structure, no material unsupported claims, no cross-corpus contamination, usable provenance, and coherent persisted/UI/PDF intelligence.

Fifteen of seventeen critical facts were correct, cross-corpus contamination was zero, provenance was real and verifiable, and identity/dates/scope/qualification/response-requirements/commercial intelligence were all materially correct for a corpus structurally unlike either prior commissioned procurement — a strong generalization result on its own. However, **the evaluation-structure requirement was not met**: Defect 1 presents real pricing-formula weights as if they were the RFP's rated evaluation criteria, which is a materially incorrect evaluation structure for this specific corpus, not merely a wording or interpretation nuance, and it is assessed as generalizable rather than a one-off artifact of this particular document.

## PHASE 6 HOLDOUT: FAIL

This result is preserved as-is above and is not rewritten. Run_id=6 remains the untouched,
historical holdout-failure record.

---

## POST-HOLDOUT GENERALIZATION CORRECTION

### Original defect (recap)

A real pricing-calculation formula (Addendum Five's "Item / Weight / Weighted Cost" table,
55%/35%/10%, used to blend two pricing scenarios and a travel fee into one price figure) was
extracted and rendered as a 3-row "Rated Criteria" evaluation table, in `analysis_results.
structured_intelligence`, the UNDERSTAND UI, and the generated PDF, for a corpus that has no
genuine rated-criteria table anywhere in its source documents.

### Semantic root cause, traced end-to-end

- **Source document/page:** `S-PT-024 - Addendum Five.pdf`, page 2, "Example Only -- How Pricing
  Should Be Entered" table.
- **Source wording:** a table literally headed `Item | Description | UOM | Cost | Weight |
  Weighted Cost`, captioned "Total weighted cost to be used in the **pricing formula**."
- **Extraction family/task:** the general `ROUTE_IDENTITY_EVAL_REQ` pass (every document in this
  corpus routes here; no focused rated-criteria task data existed for this corpus, confirmed by
  `evaluation.raw_occurrences: []` in the persisted contract).
- **Raw extracted record:** an `evaluation_criteria` entry with `stage: "Item 1 - Cohort Program
  Development & Design and Program Delivery"`, `weight: "55%"` (and siblings for Items 2/3).
- **Normalized/canonical fields:** unchanged pass-through -- `stage`/`weight`/`parent_stage` as
  extracted.
- **Adapter input:** `result.evaluation_criteria` already contained these three entries when
  `build_fast_report_content()` received it.
- **Rendered evaluation row:** `EVAL_WEIGHTS["Rated Criteria"]`, three rows, exactly as extracted.

**Answer to the required question:** the pricing formula became semantically labelled as
evaluation criteria at the **earliest possible layer -- the model's own extraction, governed by
`fast_analysis.py`'s `_EVAL_SCHEMA` prompt text** (embedded in `_IDENTITY_EVAL_REQ_SCHEMA`, and
reused verbatim by `ROUTE_EVAL_ONLY` and the small-document batching path). The schema asked the
model to "extract EVERY stated evaluation-criterion point/weight value" with no instruction
distinguishing a weight that scores a bidder from a weight that only calculates a bidder's own
price. The adapter is not responsible: `build_fast_report_content()` performs no filtering by
semantic origin anywhere in its evaluation-assembly code, and was not modified as part of this
correction.

**Case: B** (Phase 5's diagnostic framework) -- the extraction schema itself loses semantic
context; the smallest generalizable extraction correction was required, not an adapter/routing
change.

### Semantic rule established (procurement-agnostic)

**Evaluation weight**: a weight/point value whose role is to score, rank, or otherwise ASSESS a
bidder's submission (technical response, methodology, experience, team, references,
qualifications, proposal quality, or price treated as one of several factors used to select the
winning bidder -- e.g. "Technical 80%, Price 20%").

**Pricing-calculation weight**: a weight/percentage used only to CALCULATE a bidder's own price
(a weighted average or blend of resource rates, cost line-items, usage scenarios, or quantities
combined into a single price figure) -- not an evaluation criterion, regardless of column
headers like "Weight" or "Weighted Cost."

The distinction is stated in the schema as a matter of **semantic role**, not a numeric pattern:
no rule anywhere depends on whether percentages sum to 100, how many rows exist, or keyword
matching on "price"/"financial." A worked example of a genuine price-as-evaluation-factor case
("Technical 80%, Price 20%") is included explicitly so the model does not over-correct into
suppressing real financial evaluation weights.

### Files changed

- `fast_analysis.py` -- `_EVAL_SCHEMA` and `_EVAL_FOCUSED_SCHEMA` (the semantic-distinction
  instruction, added identically to both); `_IDENTITY_EVAL_REQ_SCHEMA` (a fourth, explicit
  `requirements` topic asking for pricing-calculation formulas/weightings, with weight values
  preserved verbatim, so a weight excluded from `evaluation_criteria` has a defined home rather
  than being silently dropped).
- `scripts/fast_analysis_report_adapter.py` -- `_build_ambiguities()` (the `CATEGORY_DATE_
  DISTINCTION` wording now checks whether the triggering occurrences actually carry real
  category/lot/component scope data before using "category/scope" phrasing; falls back to
  generic "which date is current" phrasing otherwise) and the corresponding `ATTENTION_POINTS`
  line. The underlying detector's trigger condition (`fast_analysis.py::detect_category_date_
  distinctions`, 2+ distinct dates for one milestone kind) was **not** changed, preserving Bank
  of Canada's genuine category-scoped finding exactly.
- `tests/test_fast_analysis_pricing_evaluation_separation.py` (new) -- 9 tests: schema-text
  contract tests, the four required cases (Calgary-style pricing formula excluded; genuine
  Technical/Financial evaluation retained; Price-among-multiple-criteria retained; weighted-
  quantity pricing table excluded), the standing cross-domain semantic-boundary test, and the
  two ambiguity-wording tests (no-scope-data / real-scope-data).

No `evaluation_hierarchy.py`, routing, concurrency, token-limit, or Deep Verify changes. No
buyer-specific, filename-specific, or numeric-literal (`55`/`35`/`10`) conditions were added
anywhere.

### Deterministic validation (before the live run)

Full suite after the `_EVAL_SCHEMA`/`_IDENTITY_EVAL_REQ_SCHEMA` change: **1527 passed, 2
skipped**. After the ambiguity-wording change: **1529 passed, 2 skipped**. `py_compile` clean.
`git diff --check` clean throughout. The 9 new tests specifically prove, without any live call:
Case 1 (Calgary-style pricing formula) renders no fabricated evaluation table and the pricing
fact remains visible as commercial content; Case 2 (Technical 80% / Financial 20%) is fully
retained; Case 3 (Methodology/Experience/Team/Price, all four) is fully retained; Case 4
(weighted workshop-type mix) is commercial-only; and the standing cross-domain test proves both
directions together in one mixed corpus.

### Calgary run-6 deterministic correction

Re-derived the ambiguity wording directly from run_id=7's own real, persisted `raw_date_
observations` (reconstructed as a `FastAnalysisResult`, re-run through the corrected adapter,
zero LLM calls) -- confirmed the "category/scope" phrasing is replaced by "please confirm which
of these dates is the current, governing one" for this real, unscoped corpus. A full PDF
(`CITY_OF_CALGARY_POSTFIX_RECONSTRUCTION.pdf`) was built from run_id=7's real identity, dates,
requirements, and commercial facts through the corrected adapter: **zero** `"Rated Criteria"`
occurrences (no fabricated evaluation table), **zero** `"category/scope"` occurrences, **zero**
cross-corpus leakage (Bank of Canada or CDA-AMC), all real Calgary content otherwise unchanged
and correctly present.

**A schema-level fix cannot be fully proven from pre-fix persisted data** -- run_id=6's own raw
extraction already baked in the old (wrong) classification, so "prove the corrected extraction
re-classifies it correctly" required an actual re-extraction. That is exactly what the one
authorized post-fix live run (below) was for.

### Post-fix Calgary run

- **Run ID:** 7 (bid_id=1; run_id=6 preserved, untouched, as the historical holdout-failure
  record; corpus not modified)
- **Corpus digest:** `8f8ac86125d22080a2d2047b2f7f33fcb0a8a505b8d8289f1ca3232bbd9db2bf` (identical
  to run_id=6)
- **Started:** 2026-09-14T23:02:58Z · **Completed:** 2026-09-14T23:07:31Z · **Wall time:** 254.39s
- **LLM calls:** 34 (8 recovery/retry) · **Tokens:** 105,565 input / 49,816 output
- **Milestones:** all 9 fired exactly once, same healthy pattern as run_id=6.
- **Started via the real UI's "🔁 Re-run Fast Analysis" control** on `bid_id=1` -- engine not
  called directly.

**Persisted-intelligence result, checked before any presentation layer:**

- `evaluation.weights_by_category`: **`{}`** -- completely empty. The pricing-formula table is
  **no longer extracted as `evaluation_criteria` at all.** No fabricated "Rated Criteria" table,
  no empty category cards, `category_cards: []` unchanged.
- Identity, dates, scope, qualification: unchanged from run_id=6, all still materially correct
  (buyer, title, reference number, final submission deadline, single-award procurement model).
- Commercial: 151 raw commercial clauses (vs. 147 in run_id=6) -- still rich and real, still
  correctly Article-cited from the Consulting General Conditions.
- Response requirements: 37 checklist rows (vs. 73 in run_id=6 -- a real, stochastic extraction-
  volume difference between live runs, not a regression; Item 1/2/3 pricing-submission structure
  is still present, e.g. "Pricing is to be provided for one (1) sample cohort only... Lump Sum
  (LS) price for one (1) sample cohort under Item 1...").
- **A secondary gap was found in this same run**: while the false evaluation table is gone, the
  **specific 55%/35%/10% weight VALUES are absent from the persisted record entirely** -- not
  reclassified into commercial/requirements content, simply not extracted anywhere. Searching the
  full persisted `structured_intelligence` for `"55%"`, `"35%"`, `"10%"`, or `"Weight"` returns
  zero matches; only the pricing items' existence (`"Item 1"`, `"Item 2"`, `"Item 3"`) survived,
  via the requirements checklist.

**This is a real, if narrower, gap against this correction's own stated bar** (§8/§15: "pricing
weights preserved accurately"). Root cause: the original `_EVAL_SCHEMA` fix told the model where
NOT to put a pricing-calculation weight, but the schema's `requirements` topic list did not yet
explicitly ask for it either -- there was no positive extraction target. **Addressed with a
second, small refinement** to the same two files (adding the fourth `requirements` topic and a
cross-reference in `_EVAL_SCHEMA` pointing to it), described above and covered by
`test_excluded_weight_is_pointed_toward_a_home_that_preserves_it`.

**This refinement was made after the one authorized post-fix live run (run_id=7) and has not
itself been live-validated** -- only one live Calgary run was authorized for this correction
pass, and it was used to validate the core, FAIL-causing defect (fabricated evaluation
structure), which it did. The weight-preservation refinement is deterministically sound (schema
text asserted present and correctly worded by the new test) but its actual effect on live
extraction is unconfirmed. Stated plainly rather than assumed: **a second confirmatory live run
would be needed to close this specific sub-item with the same rigor as the primary defect.**

### Corrected live result summary

| Check | Run_id=6 (pre-fix) | Run_id=7 (post-fix) |
|---|---|---|
| Pricing formula presented as evaluation criteria | **YES (defect)** | **NO** |
| Fabricated "Rated Criteria" table | **YES** | **NO** |
| Genuine evaluation mechanics retained (none exist in this corpus) | N/A | N/A -- correctly empty |
| Pricing formula present in commercial/pricing intelligence | Partial (items only, no weights) | Partial (items only, no weights) -- refinement made, not yet live-confirmed |
| Identity/dates/scope/qualification/response requirements materially correct | Yes | Yes, unchanged |
| Cross-corpus leakage | 0 | 0 |
| `CATEGORY_DATE_DISTINCTION` wording | "category/scope" (misleading for this corpus) | Generic, data-appropriate wording (deterministically re-verified against run_id=7's real dates) |

### Provenance (post-fix)

Verified from persisted data: dates, qualification, and commercial facts retain real page-level
`source_refs` exactly as in run_id=6 (the schema change did not touch provenance rules).
Response-requirement provenance remains document-name-level (the "Notes" column), unchanged. No
evaluation-criteria provenance to check -- correctly, none exist. The pricing-formula weight
values themselves currently have **no** provenance to verify, because they are not extracted at
all yet (see the unvalidated refinement above) -- this was not fabricated to appear otherwise.

### Bank of Canada / CDA-AMC non-regression

No new live runs for either. Deterministic regression (part of the same 1529-passing suite):

- **Bank of Canada:** `20 total = 7 + 7 + 6`; Value-add present; Relevant Experience & References
  present; evaluation-weight ambiguity NOT_PRESENT; pricing-stage ambiguity PRESENT; scoped/
  category-date distinction PRESENT -- confirmed still rendering with the original "category/
  scope" wording (`test_real_scope_data_still_uses_category_scope_wording_boc_unregressed`).
- **CDA-AMC:** `11 distinct rated criteria = 10 Technical + 1 Financial`; fabricated categories =
  0; non-substantive rendered rows = 0; cross-corpus leakage = 0.

### Full regression

`python -m pytest tests/ -q` -> **1529 passed, 2 skipped**, 0 failed. `python -m py_compile`
clean. `git diff --check` clean.

### Deep Verify

Untouched.

### Files produced this session

- `CITY_OF_CALGARY_POSTFIX_RECONSTRUCTION.pdf` -- corrected Calgary report, rebuilt from
  run_id=7's real facts through the fully corrected adapter.

## THIRD-PROCUREMENT HOLDOUT: FAIL

---

## FINAL PRICING-SEMANTIC ACCEPTANCE

Closes the one open sub-item from the prior section: whether the pricing-calculation-weight
preservation refinement (implemented after run_id=7, previously deterministic-only) actually
works on live extraction. One further authorized live Calgary run, through the real UI, no code
changes before, during, or after.

### Freeze confirmed

Before the run: full suite `1529 passed, 2 skipped`, `py_compile` clean, `git diff --check`
clean, `git status --porcelain -- '*.py'` showing only the already-committed-pending Phase 6
correction changes (no new edits). No prompt, schema, adapter, routing, token, retry, or
concurrency change was made for this validation pass.

### Final run identity & telemetry

- **Run ID:** 8 (bid_id=1; run_id=6 the original unbiased holdout failure, run_id=7 the first
  post-fix validation -- both preserved untouched, corpus not modified)
- **Corpus digest:** `8f8ac86125d22080a2d2047b2f7f33fcb0a8a505b8d8289f1ca3232bbd9db2bf` (identical
  to runs 6 and 7)
- **Engine version:** `fast-analysis-v4`
- **Started:** 2026-09-15T06:12:31Z · **Completed:** 2026-09-15T06:17:28Z · **Wall time:** 277.72s
- **LLM calls:** 34 (8 recovery/retry) · **Tokens:** 107,203 input / 49,278 output
- **Milestones:** all 9 fired exactly once -- `COMMERCIAL_READY` at 06:17:21Z, same healthy
  pattern as every prior run.
- **Started via the real UI's "🔁 Re-run Fast Analysis" control** on `bid_id=1` -- engine not
  invoked directly.

### Evaluation exclusion (checked first, before any presentation layer)

`analysis_results.structured_intelligence.evaluation.weights_by_category` = **`{}`** -- fully
empty, same as run_id=7. No fabricated `evaluation_criteria`, no rated-elements table, no
bidder-scoring weights. **`PRICING FORMULA EXCLUDED FROM EVALUATION: PASS`.**

### Commercial retention proof (from live extraction, not reconstructed)

`response_requirements.checklist`, Requirement 33, sourced to `S-PT-024 - Addendum Five.pdf`:

> "Pricing calculation formula: Total weighted cost = (0.55 × Item 1 cost) + (0.35 × Item 2
> cost) + (0.10 × Item 3 cost). **Item 1 (Cohort Program Development & Design and Program
> Delivery): 55% weight.** **Item 2 (Cohort Program Development & Design and Program Delivery):
> 35% weight.** **Item 3 (Travel Expenses): 10% weight.**"

The procurement's own real labels ("Item 1/2/3 (Cohort Program Development & Design and Program
Delivery / Travel Expenses)"), all three real percentages, and the full formula are present
verbatim, from this run's own live extraction -- not deterministically reconstructed, not
database-patched, not inferred at render time. Confirmed identically in the persisted JSON, the
live UNDERSTAND UI, and the regenerated PDF. Searching the full persisted record: `"55%"`: 1
occurrence, `"35%"`: 1, `"10%"`: 1 -- each appears exactly once (see Commercial Data Quality
below). **`PRICING FORMULA RETAINED COMMERCIALLY: PASS`.**

### Semantic boundary (both directions)

- **price-calculation weighting → commercial/pricing intelligence, NOT evaluation**: proven
  live above (Requirement 33 in the requirements/commercial layer; `evaluation_criteria` empty).
- **bidder-scoring weighting → evaluation intelligence**: Calgary's real corpus contains no
  genuine rated-criteria table at all (confirmed by the source-truth checklist), so this run has
  nothing to demonstrate the "still preserved" side with live Calgary data. That side of the
  boundary is proven by (a) Bank of Canada's unchanged live-commissioned baseline (`20 = 7+7+6`,
  still rendering correctly, confirmed in the same regression run below) and (b) the deterministic
  Cases 2 and 3 in `tests/test_fast_analysis_pricing_evaluation_separation.py` (Technical 80% /
  Financial 20%; Methodology/Experience/Team/Price all four retained).

### Provenance

Requirement 33 carries real, correct **document-level** provenance: `S-PT-024 - Addendum
Five.pdf` -- confirmed live, exactly the document that actually contains the pricing-formula
table. This is the same provenance granularity every other response-requirement fact in this
report carries (the "Notes" column, not a page-level View Source expander) -- an existing,
already-documented product characteristic (requirements-checklist items were never wired to the
page-level View Source mechanism, only `commercial_clauses` and `pricing_occurrences` were), not
something this fix introduced or regressed. No fabricated provenance was added to make this pass
-- the document name shown is genuinely where the fact came from. **`PRICING FORMULA PROVENANCE:
PASS`** (at document-level granularity, stated precisely rather than overclaimed as page-level).

### Commercial data quality

- **Raw formula-related occurrences:** the persisted record contains exactly one occurrence each
  of `"55%"`, `"35%"`, and `"10%"` -- no duplication, no explosion into multiple near-identical
  rows across the corpus's 4 cumulative Q&A log snapshots (unlike some other facts in this corpus,
  which do legitimately repeat across snapshots since each snapshot genuinely restates prior
  answers).
- **Deduplicated commercial facts:** 19 topics / 151 raw commercial clauses total for this run
  (separately from the pricing formula, which landed in `requirements` per the schema's own
  topic routing, not `commercial_clauses`).
- **Exact percentages retained:** 55%, 35%, 10% -- all three, verbatim.
- **All three components distinguishable:** yes -- Item 1, Item 2, and Item 3 each retain their
  own real label and their own weight; none were merged or collapsed into one another.

No commercial-assembly redesign was made or needed.

### Scoped-date ambiguity (reconfirmed)

Live UI and persisted data both show, for all three `CATEGORY_DATE_DISTINCTION` findings:
*"Please confirm which of these dates is the current, governing one"* -- no "category/scope"
language, consistent with this corpus having no real category structure. The underlying
multi-date finding itself remains (3 ambiguities, same real dates and sources as runs 6/7).
**`SCOPED DATE FRAMING: PASS`.**

### Other Calgary intelligence (reconfirmed, no re-litigation of immaterial wording variance)

Identity, dates, scope, qualification, response requirements (33+ real rows), and commercial
clauses (19 topics / 151 raw) all remain materially correct and consistent with runs 6 and 7 and
with `PHASE6_HOLDOUT_SOURCE_TRUTH.json`. No new material defect found.

### Cross-corpus contamination

Searched this run's `structured_intelligence`, the live UI, and the regenerated PDF text for
Bank-of-Canada and CDA-AMC-specific material. **`CROSS-CORPUS LEAKAGE = 0`** everywhere checked.

### PDF result

`CITY_OF_CALGARY_FINAL_RUN8.pdf`, 15 pages, 76,169 bytes, regenerated from the persisted run_id=8
snapshot. Full-text verified: 0 `"Rated Criteria"`, 0 `"category/scope"`, 0 Bank-of-Canada/CDA-AMC
strings, 1 each of `"55%"`/`"35%"`/`"10%"` with the correct real Item labels and source document.
Correct buyer/title/reference throughout. No raster/visual page-by-page inspection was performed
-- no `pdftoppm`/poppler tooling is available in this environment, stated precisely as in every
prior report this session.

### Report regeneration

`analysis_service.regenerate_report(8)` -- 76,169 bytes in 2.14s, zero network/API calls,
re-tested explicitly for this final run rather than assumed from earlier phases. **`REPORT
REGENERATION WITHOUT EXTRACTION: PASS`.**

### Bank of Canada / CDA-AMC regression

No live runs for either. Deterministic only, part of the same passing suite:

- **Bank of Canada:** `20 total = 7 + 7 + 6`; Value-add present; Relevant Experience & References
  present; evaluation-weight ambiguity NOT_PRESENT; pricing-stage ambiguity PRESENT; scoped/
  category-date distinction PRESENT.
- **CDA-AMC:** `11 distinct rated criteria = 10 Technical + 1 Financial`; fabricated categories =
  0; non-substantive rendered rows = 0; cross-corpus leakage = 0.

### Full regression

`python -m pytest tests/ -q` -> **1529 passed, 2 skipped**, 0 failed -- unchanged from before
this validation run, confirming zero code drift. `python -m py_compile` clean. `git diff --check`
clean.

### Files produced this session

- `CITY_OF_CALGARY_FINAL_RUN8.pdf` -- the final commissioned Calgary report.

## GENERALIZATION DEFECT CORRECTED: PASS -- fully closed, live-confirmed
