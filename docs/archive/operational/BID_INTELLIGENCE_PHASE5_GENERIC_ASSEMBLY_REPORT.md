# Bid Intelligence — Product Integration Phase 5: Generic Intelligence Assembly & Cross-Procurement Correction

## 0. Root cause of Phase 4's failure

Phase 4 proved Fast Analysis V4's **engine** already generalizes: it ingested and
analyzed a materially different, real procurement (Canada's Drug Agency /
CDA-AMC's Coaching Services RFSO) correctly at the extraction level. The
**application/report assembly layer** did not generalize with it. Two
independent defects existed simultaneously:

1. **`scripts/fast_analysis_report_adapter.py`** (the deterministic
   `FastAnalysisResult → report-content` adapter) was written *for* Bank of
   Canada's RFP 2026-026, not *from* whatever procurement it was handed. It
   hardcoded: a fixed 3-category model (`CATEGORY_NAMES`, `D1_DOC`/`D2_DOC`/
   `D3_DOC` filename constants), a fixed 20-criterion / 7+7+6 weighting
   structure, Appendix-letter response-checklist assumptions, "the Bank" /
   "via MERX" / "Bank satisfaction" phrasing inside otherwise-generic helper
   functions, a hardcoded ambiguity source citing "RFP 2026-026" regardless
   of corpus, and — critically — an **unconditional, corpus-blind fallback**
   to `boc_bid_intelligence_preview_content.py` (the "DEEP" module, Bank of
   Canada's own hand-curated Buyer Intelligence and cover/snapshot content)
   whenever Fast Analysis genuinely extracted nothing for a field. For any
   other corpus, "nothing extracted" silently became "show Bank of Canada's
   real content instead" — the exact cross-corpus leakage Phase 5 §0
   forbids.
2. **`scripts/build_boc_bid_intelligence_preview_pdf.py`** (the reportlab
   PDF renderer) had its own, separate hardcodes: a literal
   `"Bank of Canada · RFP 2026-026"` string drawn on every body-page header
   via `canvas.drawRightString`, and a literal PDF metadata `title=` string
   — both independent of whatever `content` object was passed in.

Both defects were **application-layer**, not engine-layer. One genuine
engine-layer gap was also found during diagnosis (§7 below) and fixed
separately, narrowly, and additively.

## 1. Data-flow audit (summary matrix)

| Section | Data origin (pre-Phase 5) | Live/derived? | Corpus-specific fallback? |
|---|---|---|---|
| Cover / Snapshot identity | `doc_metadata_by_doc`, merged (`_merged_doc_metadata`, Phase 4) | Live, generic | **Yes** — `buyer or "Bank of Canada"`, `solnum or "RFP 2026-026"` |
| Service Categories (3 cards) | Hardcoded `(1,2,3)` loop + `CATEGORY_NAMES` | Partially live (description text only) | **Yes** — structure, names, page limits all hardcoded |
| Buyer Intelligence | `boc_bid_intelligence_preview_content.py` (DEEP), copied unconditionally | Static, external | **Yes** — copied regardless of buyer |
| Evaluation stages | `DEEP.EVAL_STAGES` | Static | **Yes** |
| Evaluation weights | `_occurrence_weight_rows`/`_weight_rows`, keyed to `D1_DOC`/`D2_DOC`/`D3_DOC`, falling back to `DEEP.EVAL_WEIGHTS` | Live, but doc-keyed | **Yes**, all-or-nothing fallback |
| Response checklist | `DEEP.RESPONSE_CHECKLIST` (Appendix A–G) | Static | **Yes** |
| Commercial points | `commercial_clauses` + `_pricing_and_term_commercial_rows` (filtered by hardcoded `APPENDIX_E` filename), falling back to `DEEP.COMMERCIAL_POINTS` | Live, filename-filtered | **Yes**, fallback |
| Ambiguities | Deterministic detectors (`_build_ambiguities`) | Live, already generic (fixed Phase 4) | No (correctly fixed in Phase 4) |
| Attention points | `DEEP.ATTENTION_POINTS`, 2 index-overridden | Static | **Yes** |
| Source map | `DEEP.SOURCE_DOCUMENTS`/`SOURCE_REF_TABLE` | Static | **Yes** |
| PDF header/footer/title | Literal strings in `build_boc_bid_intelligence_preview_pdf.py` | Static | **Yes** |
| UNDERSTAND UI (`fast_analysis_app_adapter.py`) | Reads the *same* `content` object as the PDF | Live, generic | Inherited whatever the adapter did |

## 2. Production hardcodes found and removed

All in `scripts/fast_analysis_report_adapter.py` unless noted.

- `MASTER_RFP`/`D1_DOC`/`D2_DOC`/`D3_DOC`/`APPENDIX_E`/`APPENDIX_G` filename
  constants and every function keyed to them (`_category_requirements`,
  `_weight_rows`, `_occurrence_weight_rows`, `_classify_category_scope`,
  `_CATEGORY_SCOPE_PATTERNS`) — **removed**, replaced by generic
  category-discovery functions (§5).
- `CATEGORY_NAMES` dict and the fixed `for cat in (1, 2, 3)` loops —
  **removed**.
- `buyer = meta.get("client") or "Bank of Canada"` /
  `solnum = meta.get("file_number") or "RFP 2026-026"` — **removed**,
  replaced by an honest `_NOT_EXTRACTED` marker.
- `"the Bank"` / `"via MERX"` / `"subject to Bank satisfaction"` phrasing
  embedded in `_procurement_model`, `_contract_term`,
  `_submission_deadline_text` — **removed/genericized**.
- Hardcoded ambiguity `"source"` text citing `"RFP 2026-026"` regardless of
  corpus — **removed**, now built from the triggering occurrences' own
  `source_doc` fields.
- Unconditional `DEEP.*` fallback for `EVAL_STAGES`, `RESPONSE_CHECKLIST`,
  `RESPONSE_OTHER_REQUIREMENTS`, `SOURCE_DOCUMENTS`, `SOURCE_REF_TABLE`,
  `PROCURED_INTRO`/`STRUCTURE`/`MODEL_NOTE`, `BID_MECHANICS`/`DATES_NOTE`,
  `GATE_EXAMPLES`, `COMMERCIAL_POINTS`, `EVAL_WEIGHTS`, `ATTENTION_POINTS`,
  and Buyer Intelligence — **all removed**. Every one of these now either
  derives from `result` or is honestly empty/`_NOT_EXTRACTED`.
- `scripts/build_boc_bid_intelligence_preview_pdf.py`: the literal
  `"Bank of Canada · RFP 2026-026"` page-header string in `on_body()` and
  the literal PDF metadata `title=` string in `build()` — **removed**,
  replaced by `doc._header_text` (stashed by `build()` from
  `content.HEADER_TEXT`, itself derived from the same buyer/solicitation
  fields the Snapshot section uses).

**Categorization**: all of the above were **INVALID PRODUCTION HARDCODE** or
**INVALID CROSS-CORPUS FALLBACK**. `fast_analysis.py`'s `DOCUMENT_ROUTING` /
`PAGE_LIMIT_DOCUMENTS` tables (which also name Bank of Canada's exact
filenames) were inspected and are **VALID BANK-OF-CANADA-SPECIFIC
BASELINE**: they are a per-document *optimization* for the one known
corpus, already proven (Phase 4's `TestRouteDocumentGeneralization`) to
fall back safely to the generic `ROUTE_IDENTITY_EVAL_REQ` route for any
filename that doesn't match — not a fallback of *content*, only of
*routing strategy*, and every non-matching corpus is unaffected by it.
`scripts/boc_bid_intelligence_preview_content.py` (DEEP) itself is **VALID
BANK-OF-CANADA-SPECIFIC BASELINE** in isolation — the defect was never the
module's existence, only the adapter's *unconditional* reuse of it for any
buyer.

## 3. Cross-corpus fallbacks removed

Every fallback listed in §2 that substituted Bank of Canada's real content
for a genuinely-missing fact is gone. The replacement policy, applied
uniformly:

- A scalar fact (buyer, solicitation number, opportunity title, contract
  term, procurement model, service-category description, …): missing →
  `"Not stated in the extracted data."`
- A list-shaped section (evaluation stages, gate examples, commercial
  points, response-other-requirements, attention points, service
  categories, ambiguities): missing → `[]` (the section renders its
  heading with nothing beneath, never invented rows).
- Buyer Intelligence: only rendered when the current procurement's own
  extracted buyer name actually matches Bank of Canada (`_BUYER_INTEL_
  COVERAGE`); otherwise the whole section is generically **omitted** — not
  shown empty, not shown with another buyer's real content. This required
  a small, non-visual-redesign fix to the PDF renderer (wrapping Section 2
  in `if getattr(C, "BUYER_INTEL_AVAILABLE", True):`) because the
  section's own tables (`VERIFIED_BUYER_FACTS`, `RELEVANT_BUYER_SIGNALS`,
  `BID_TEAM_PANEL_ITEMS`) are built as raw reportlab `Table()` objects with
  no header row — an empty list there would raise, not render blank, so
  the section had to be skippable, not merely empty-safe. The same
  necessity applied to `SNAPSHOT_CATEGORY_CARDS`' raw `Table()` in Section 1.

## 4. Generic report contract

`build_fast_report_content(result: FastAnalysisResult) -> SimpleNamespace`
no longer knows which buyer it is rendering. Every field is either:
(a) derived from `result` via a small set of new, generic helper functions
(`_discover_evaluation_categories`, `_weight_rows_for_category`,
`_service_category_rows`, `_response_requirements`, `_source_documents`,
`_source_ref_table`), or (b) a generic string template with data
substitution (e.g. `f"{buyer} is seeking one or more qualified service
providers..."`), or (c) the honest `_NOT_EXTRACTED` marker / empty list.

## 5. Generic evaluation model

`_discover_evaluation_categories(result)` replaces the fixed `(1, 2, 3)`
loop: it reads whatever raw `category_scope` text the focused rated-
criteria task actually extracted (falling back to `evaluation_criteria`'s
`parent_stage` only when no focused-task data exists at all for the
corpus), preserving the corpus's own terminology verbatim, first-seen
order, case-insensitive dedup. Zero categories is a valid, meaningful
result (a flat, single-scope corpus). `_weight_rows_for_category(result,
label_or_None)` builds the numeric-weight rows for one discovered category
(or, when `label is None`, the single flat table) — verified against both
shapes in tests: Bank of Canada's real 7+7+6 structure (still renders
correctly, non-regressed) and CDA-AMC's flat, uncategorized 11-row
structure (renders as a single "Rated Criteria" table, no category cards).

## 6. Generic response requirements

`_response_requirements(result)` replaces the Appendix-letter-shaped
`DEEP.RESPONSE_CHECKLIST`: `result.requirements` items already carry
exactly the facts this section needs (Fast Analysis's own schema restricts
`requirements` to category-scope description, submission mechanics, and
pricing-consequence rules — see `fast_analysis.py`'s
`_IDENTITY_EVAL_REQ_SCHEMA`). `category == "Mandatory"` items become
numbered checklist rows (`"Requirement N"`, since no per-item document
label like "Appendix A" is ever actually extracted), each carrying its own
`source_doc` in the Notes column; everything else becomes a plain bullet.
Verified against CDA-AMC's real 7 mandatory items from the source-truth
checklist (including its genuine MERX/email submission mechanics) and
against Bank of Canada's shape.

## 7. Commercial data — diagnosis and engine fix

Phase 4 found CDA-AMC's own commercial clauses (bundled inside its single
main document, not a separate appendix) were absent from extraction.
**Diagnosed before any change** (Phase 5 §7's required sequence): this is
**CASE B** — a genuine upstream extraction gap, not a downstream
adapter-mapping bug. `_IDENTITY_EVAL_REQ_SCHEMA` (the schema every document
in a no-`DOCUMENT_ROUTING`-match corpus is routed to) explicitly instructs
"do not extract commercial clauses" — correct when Bank of Canada's own
commercial terms live entirely in a separate `ROUTE_COMMERCIAL_ONLY`
document (Appendix G), but wrong when a corpus's *only* document bundles
its own commercial terms alongside identity/evaluation content.

**Engine modification: YES**, implemented in a prior session turn ahead of
this report and unit-tested (not re-touched this pass): a new,
procurement-agnostic `"commercial_supplement"` task kind in
`fast_analysis.py`. For every `ROUTE_IDENTITY_EVAL_REQ`-routed document,
one additional, **unmodified** `ROUTE_COMMERCIAL_ONLY` pass is dispatched
(same schema, same `extract_fast_document()` machinery, same
chunking/recovery), merging only into `result.commercial_clauses` — it
never touches that document's own existing `ROUTE_IDENTITY_EVAL_REQ`
output. This is keyed purely on *route*, not on any buyer/corpus name, so
Bank of Canada's own corpus (whose master RFP is `ROUTE_IDENTITY_EVAL_REQ`
and whose commercial terms already come from a dedicated `ROUTE_
COMMERCIAL_ONLY` Appendix G) is provably unaffected in every fact this
extra pass does not itself add — confirmed by the full, unchanged 98-test
engine regression suite plus 6 new dispatch/merge tests
(`tests/test_fast_analysis_commercial_generalization.py`) using mocked
`extract_fast_document`. The corresponding `analysis_service.py`
progress-tracking milestone (`_ProgressTracker`) was updated so
`MILESTONE_COMMERCIAL_READY` correctly waits for however many
commercial-contributing tasks a corpus now has (one dedicated document,
one supplement pass, or both) — not just the first one.

No new LLM stage was added (reuses `ROUTE_COMMERCIAL_ONLY`'s existing
schema and `extract_fast_document` entirely), and this is not renamed Fast
Analysis V5 — intelligence *semantics* did not change, only dispatch
breadth for one specific, well-scoped route.

## 8. Source-truth preservation

Every rendered fact that carries a `source_doc`/`source_refs` upstream
still carries it downstream: the new `_service_category_rows` and
`_response_requirements` helpers preserve `source_doc` per row (visible in
the CDA-AMC preview PDF's Response Requirements "Notes" column); the new
`_source_ref_table(result)` builds a small, representative View Source
sample — one row each for identity/date, evaluation, a response
requirement, and a commercial fact where that class of fact exists —
rather than a hand-curated, corpus-specific citation list. Verified in
`tests/test_fast_analysis_app_adapter.py` (unchanged, still passing:
`test_evaluation_raw_occurrences_retain_source_refs`,
`test_dates_and_mechanics_raw_date_observations_retain_source_refs`) and
newly in `tests/test_phase5_generic_assembly.py`.

## 9. CDA-AMC correction (before/after)

Reused `PHASE4_SOURCE_TRUTH_CHECKLIST.json` (deterministic-extraction-only,
zero-LLM-call ground truth) rather than rebuilding it. Validated via a
synthetic `FastAnalysisResult` built directly from that checklist's own
fields (`tests/test_phase5_generic_assembly.py::_cda_amc_shaped_result`),
and via a real PDF build from it (`CDA_AMC_PHASE5_PREVIEW.pdf`, committed
to the repo root alongside the Bank of Canada baseline artifacts).

| | Before (Phase 4 output) | After (Phase 5, this fixture) |
|---|---|---|
| Buyer | *(adapter would show "Bank of Canada" for any unresolved field)* | "Canada's Drug Agency (CDA-AMC)" |
| Solicitation number | — | "C-262700410" |
| Category structure | 3 hardcoded BoC category cards | `[]` — correctly flat, one "Rated Criteria" table |
| Evaluation rows | N/A (never rendered generically) | 11 rows, all from the checklist's real Stage II/III criteria |
| Response checklist | Appendix A–G (BoC's own) | 7 numbered rows, CDA-AMC's own real submission mechanics (MERX/email, 20MB limit, etc.) |
| Commercial | Missing (CASE B gap, §7) | Liability Insurance $2,000,000 (from the checklist) |
| Ambiguities | N/A | `[]` — correctly NOT_PRESENT for all 3 classes (matches the checklist's own finding) |
| Buyer Intelligence | Bank of Canada's real content (leaked) | Section omitted entirely |
| "Bank of Canada" occurrences in rendered PDF text | N/A (Phase 4 did not reach report rendering) | **0** (confirmed via `pypdf` text extraction) |
| "2026-026" occurrences | N/A | **0** |

## 10. Bank of Canada non-regression

Verified against a synthetic result shaped to match the real, commissioned
Phase 3 corpus's own known structure (not a live re-run — Phase 5 §10/§13
explicitly forbid re-running Bank of Canada live):

- Buyer = "Bank of Canada", Solicitation = "RFP 2026-026" ✓
- 7 + 5 + 6 = 18 category-scoped rows (Category 2 correctly has 5, not 7 —
  matching the real DEEP.EVAL_WEIGHTS structure) ✓
- "Value-add" and "Relevant Experience & References" present ✓
- No false evaluation-weight ambiguity (`AMBIGUITY.evaluation_weight_
  conflict` = `NOT_PRESENT`, V4's scope-aware fix correctly not
  re-triggered) ✓
- Pricing-stage ambiguity present (`LIVE_FAST_LLM`) ✓
- Category-date distinction present (`LIVE_FAST_LLM`) ✓
- Buyer Intelligence still renders, byte-identical to `DEEP.
  VERIFIED_BUYER_FACTS`/`DEEP.BID_TEAM_PANEL_ITEMS` ✓
- PDF builds without error (`BOC_PHASE5_NONREGRESSION_PREVIEW.pdf`,
  0 CDA-AMC/leakage occurrences) ✓

`tests/test_fast_analysis.py`, `_v2.py`, `_v3.py`, `_v4.py` (98+ pre-
existing engine/adapter regression tests) all still pass — 3 tests whose
old assertions encoded exactly the behavior Phase 5 was authorized to
remove (an unconditional `"Bank of Canada"` fallback buyer, a
`"BUYER_INTELLIGENCE_EXTERNAL_LAYER"` origin for every corpus regardless of
buyer, and doc-filename-keyed weight/category helpers) were **renamed and
rewritten with an explicit "Phase 5:" rationale**, never silently deleted
or weakened — per the standing engagement discipline and Phase 5 §18's
explicit instruction.

## 11. Contamination regression (new, permanent guard)

`tests/test_phase5_generic_assembly.py::TestCrossCorpusContamination`:

- CDA-AMC-shaped result's full rendered content (every string field
  `build_fast_report_content` produces, flattened) never contains "Bank of
  Canada", "RFP 2026-026", or "2026-026".
- Bank-of-Canada-shaped result's content never contains "CDA-AMC",
  "Canada's Drug Agency", or "C-262700410".
- An arbitrary minimal procurement (buyer="Example Agency", title=
  "Leadership Coaching Services", one criterion, one deadline, zero
  ambiguities) renders **only** those facts — checked against leakage from
  both real corpora simultaneously (7 forbidden strings, including
  "Corporate Profile" and "MERX").

## 12. Sparse/empty-state behavior

`tests/test_phase5_generic_assembly.py::TestSparseEmptyStateRendering`:
a completely empty `FastAnalysisResult()` produces a structurally valid
`content` object (no category cards, no service categories, no eval
weights, no gate examples, no commercial points, no ambiguities, Buyer
Intelligence unavailable, buyer = the honest not-extracted marker) **and**
builds a real, non-empty PDF without raising — the sparsest case
deliberately exercises the two raw-`Table()` empty-list crash points fixed
in §3. A single-flat-criterion corpus (no category structure at all)
renders one correct "Rated Criteria" row.

## 13. Provenance result

Pass — see §8. No `source_refs` stripped, no synthetic provenance created;
the new generic helpers all read real `source_doc`/`source_refs` fields
off `result`'s own data rather than fabricating attribution.

## 14. Live LLM calls made this session

**Zero.** The entire Phase 5 correction (report/PDF assembly layer) is
deterministic, no-LLM code, validated via synthetic fixtures built from
`PHASE4_SOURCE_TRUTH_CHECKLIST.json`'s real, human-verified facts — per
§13's instruction to validate against persisted/known structured state
first. The one engine-layer change (`commercial_supplement`, §7) was
implemented and mock-validated in a prior session turn (6 dispatch/merge
tests, zero live calls). Per §13, that engine fix — because it adds new
upstream commercial extraction — is a legitimate candidate for **one**
additional authorized live CDA-AMC run to validate it against real
extraction (the currently-persisted CDA-AMC run, `bid_id=3`/`run_id=2`,
predates the fix and does not benefit from it). **That live run was not
executed in this session**: it requires a real Anthropic API call and a
write to the production analysis pipeline/database, which this session
treats as an action needing your explicit go-ahead rather than something
to trigger autonomously mid-task, given the cost and the fact that no
correctness question actually depends on it (the dispatch/merge logic is
already fully covered by mocked tests, and the report layer's correctness
does not depend on what real text CDA-AMC's document contains). Say the
word and I'll kick it off.

## 15. UI/PDF consistency

`fast_analysis_app_adapter.py::build_opportunity_intelligence()` calls
`fast_report_adapter.build_fast_report_content(result)` directly and
projects every UI field from that *same* `content` object the PDF renders
from — consistency is structural, not merely tested. The one place this
was actually broken (Buyer Intelligence: the app adapter unconditionally
read `content.BUYER_INTEL_INTRO`/`VERIFIED_BUYER_FACTS`/etc., which no
longer exist on `content` for a non-Bank-of-Canada buyer) was fixed by
gating `oi["buyer_intelligence"]` on `content.BUYER_INTEL_AVAILABLE`,
yielding `None` when unavailable — `pages/stage_understand.py` already
guards `oi.get("buyer_intelligence")` through `_ensure_dict()`, so the UI
degrades gracefully in lockstep with the PDF's section-skip.

## 16. Full-suite result

`python -m pytest tests/ -q` → **1508 passed, 2 skipped** (unrelated
pre-existing skips), 0 failed. `python -m py_compile` clean on every
touched file. `git diff --check` clean (line-ending-only warnings, no
actual whitespace errors).

## 17. Fast Analysis V4 / Deep Verify behavior changes

- **Fast Analysis V4 intelligence semantics**: unchanged except the one
  additive `commercial_supplement` task (§7) — no prompt text changed for
  any existing task, no existing task's output altered, no new required
  field added to any schema.
- **Deep Verify**: completely untouched this session (no Deep Verify file
  was read or modified); the standing
  `test_module_never_imports_deep_verify_entry_points`-style isolation
  guard is part of the passing full-suite run in §16.

## 18. Report path

- Bank of Canada non-regression preview: `BOC_PHASE5_NONREGRESSION_PREVIEW.pdf`
- CDA-AMC corrected preview: `CDA_AMC_PHASE5_PREVIEW.pdf`
- This report: `BID_INTELLIGENCE_PHASE5_GENERIC_ASSEMBLY_REPORT.md`

## Acceptance gate

| # | Requirement | Result |
|---|---|---|
| 1 | CDA-AMC renders only CDA-AMC intelligence | PASS |
| 2 | Zero unsupported Bank of Canada leakage | PASS (0 occurrences, text-extracted from the actual PDF) |
| 3 | Evaluation/report structure driven by current procurement data | PASS |
| 4 | Empty results stay empty, no corpus-specific fallback | PASS |
| 5 | Response requirements data-driven | PASS |
| 6 | Commercial content correctly mapped where available upstream | PASS |
| 7 | Upstream commercial correction is general, not buyer-specific | PASS (route-keyed, not name-keyed) |
| 8 | View Source remains valid | PASS |
| 9 | UNDERSTAND and PDF materially agree | PASS (structural, not incidental) |
| 10 | Bank of Canada baseline remains correct | PASS |
| 11 | Cross-corpus contamination regression tests pass | PASS (new, permanent guard) |
| 12 | Deep Verify unchanged | PASS |

**Recommendation (as of the deterministic-only pass): `BID INTELLIGENCE
GENERIC ASSEMBLY COMMISSIONED`**, with the one open item noted in §14 (the
optional live CDA-AMC validation run for the `commercial_supplement`
engine path) flagged for your explicit authorization rather than treated
as blocking.

---

## LIVE CDA-AMC ACCEPTANCE VALIDATION

Authorized follow-up session: perform the one live CDA-AMC run Phase 5 §13
conditionally authorized, to validate the `commercial_supplement` engine
path against real extraction, through the real application UI, against
the existing `bid_id=3`.

### Run identity & telemetry

- **New run ID:** 3 (bid_id=3; existing Phase 4 run_id=2 left untouched)
- **Engine version:** `fast-analysis-v4`
- **Corpus digest:** `ec0b9d8ff52a4e0b46711881f44389cc69bfc408cd240780bbc098aac1d9a624`
- **Corpus:** the 5 documents tagged `doc_type == "RFP / Source"` for this
  bid (main RFSO document + Bulletins #02–#05) — matching
  `PHASE4_SOURCE_TRUTH_CHECKLIST.json`'s corpus exactly. 8 other attached
  documents (`Submission`/`Supporting` doc_types — the firm's own
  proposal-building templates) were correctly excluded by
  `start_fast_analysis()`'s existing `doc_type == "RFP / Source"` filter,
  unchanged this session.
- **Started:** 2026-09-14T19:06:50Z · **Completed:** 2026-09-14T19:11:53Z
- **Wall time:** 219.06s
- **LLM calls:** 20 total (`recovery_or_retry_calls`: 6 bounded split-recovery
  subcalls; 0 documents batched, 0 skipped)
- **Tokens:** 66,342 input / 35,545 output
- **Started via:** the real Streamlit UI (`pages/stage_understand.py`'s
  "🔁 Re-run Fast Analysis" button → `analysis_service.start_fast_analysis`)
  — the engine was never called directly.

### Freeze compliance

No prompts, schemas, concurrency, token limits, retry/recovery behavior,
buyer-specific logic, or Deep Verify code were touched before or during
this run. The only pre-existing engine delta under validation was the
already-implemented, generic `commercial_supplement` task (Phase 5 §7).

### Commercial-supplement path verification

All 5 analyzed documents are outside `DOCUMENT_ROUTING` (a Bank-of-Canada-
only table) and therefore route to `ROUTE_IDENTITY_EVAL_REQ` (confirmed by
directly calling `route_document()` against each real filename this
session). Per `fast_analysis.py`'s unmodified step 2c, every
`ROUTE_IDENTITY_EVAL_REQ` document deterministically gets exactly one
additive `commercial_supplement` task — so **5 commercial-supplement tasks
executed**, one per document, none redundant (no document in this corpus
matched `ROUTE_COMMERCIAL_ONLY`/`ROUTE_EVAL_ONLY`, so none was skipped or
double-counted). Fine-grained per-call telemetry (individual `call_kind`
values) is not persisted separately from the run's aggregate summary, so
this count is a deterministic, code-guaranteed figure — traced from the
real, confirmed routing decisions for this exact corpus — rather than a
raw call log; the mechanism itself is exercised end-to-end by the 6
existing mocked dispatch tests in
`tests/test_fast_analysis_commercial_generalization.py`.

Merge correctness is confirmed positively: the persisted
`pricing_and_commercial.points` contains 13 distinct, richly-detailed,
CDA-AMC-specific commercial facts (Confidentiality, **Insurance**,
Personnel/Key Staff, Payment terms, Validity, Subcontracting,
Cybersecurity/AI-use restrictions, Data Protection, Change Control,
Pricing Escalation, Pricing Structure, Contract Term), every one tagged
`LIVE_FAST_LLM` in `fact_origins` — none present in the OLD, pre-fix
persisted CDA-AMC run (run_id=2). **The critical acceptance target — the
liability-insurance requirement identified during Phase 5 §7 diagnosis —
is present, from real extraction:** *"Supplier must maintain requested
liability insurance coverage. Although most services will be delivered
via remote virtual platform, in-person meetings cannot be ruled out,
therefore liability insurance coverage is required."*

### COMMERCIAL_READY milestone

Real, persisted milestone timeline for this run (`analysis_runs.progress`):

| Milestone | Reached at (UTC) |
|---|---|
| CORPUS_PREPARED | 19:07:56.615644 |
| OPPORTUNITY_IDENTIFIED | 19:08:05.769347 |
| PROCUREMENT_STRUCTURE_READY | 19:08:11.221489 |
| QUALIFICATION_READY | 19:08:12.701031 |
| **COMMERCIAL_READY** | **19:09:35.863498** |
| DATES_READY | 19:11:32.856299 |
| EVALUATION_READY | 19:11:36.400168 |
| AMBIGUITIES_READY | 19:11:37.803055 |
| REPORT_ASSEMBLED | 19:11:47.059032 |

Each of the 9 milestones appears **exactly once** — no duplicates, no
spurious entries. `COMMERCIAL_READY` fired once, after
`QUALIFICATION_READY` and well before `DATES_READY`/`EVALUATION_READY`,
consistent with the counter now correctly waiting for all
commercial-contributing tasks (the additive supplement passes) rather
than firing on the first one. No evaluation-task miscounting was
observed (`EVALUATION_READY` and `AMBIGUITIES_READY` both fired,
distinctly, after their own real work completed).

### A genuine defect was found — stop-and-document, then fixed

Inspecting the live-persisted result against
`PHASE4_SOURCE_TRUTH_CHECKLIST.json` surfaced a real, acceptance-blocking
problem **unrelated to the commercial_supplement engine path**:
`opportunity_snapshot.facts` showed `"Service Categories": "7 — Appendix A
Criteria, Appendix A Financial Proposal Criteria, Stage I, Stage II, Stage
III, Technical Proposal, Financial Proposal"`, with 7 fabricated "Category
1–7" cards — even though the checklist is explicit:
`"has_scored_service_categories_like_bank_of_canada": false`. CDA-AMC has
no category/lot structure at all.

**Root cause**: the live model's `category_scope`/`parent_stage` fields
(engine-frozen; not touched this session) were populated, for this real
corpus, with section/stage labels ("Stage II", "Appendix A Criteria")
rather than left null — the schema's own docstring says "or null if not
category-specific," but a real model, faced with a document that has no
true category/lot structure, evidently still filled in *something*
descriptive. `_discover_evaluation_categories()`'s original rule ("any
non-empty scope label counts") took every one of these at face value,
fabricating structure the source does not support. (Separately, but not
itself a defect: the focused rated-criteria task found no data for this
corpus at all — `evaluation_occurrences` was empty — because CDA-AMC's
real headings don't match `find_section()`'s known patterns; this
correctly triggered the designed fallback to the general
`evaluation_criteria`/`parent_stage` family, which is where the
mislabeled data actually came from.)

**Classification: ADAPTER DEFECT** (per instruction 12's taxonomy) — not
source-truth error (the checklist was correct), not stochastic/non-
material (a fabricated "7 Categories" claim is materially wrong and
user-visible), not an engine defect (the frozen schema's own instructions
are correctly worded; a live model not perfectly following "null if not
category-specific" is exactly the kind of raw-data imperfection the
deterministic adapter layer exists to guard against), not a rendering
defect (the renderer faithfully displayed what the adapter gave it).

**Fix** (`scripts/fast_analysis_report_adapter.py`, deterministic, no
engine/prompt/schema change): a "category" is now only trusted once
substantiated by at least 2 criteria (`_MIN_ROWS_PER_CATEGORY`), and the
corpus is only treated as having category/lot structure once at least 2
such substantiated groups exist (`_MIN_QUALIFYING_CATEGORIES`) — a single
group, however large, renders flat rather than as "the one category."
`_weight_rows_for_category`'s flat-table path was correspondingly widened
to include every qualifying criterion regardless of its (now-untrusted)
scope label, rather than only unlabeled ones — otherwise every real
CDA-AMC criterion (all of which carried *some* label) would have vanished
from the flat table entirely.

**Re-validated deterministically, zero new LLM calls**: the fix was
proven by reconstructing a `FastAnalysisResult` from the SAME real
criteria/weights already extracted live in this run (`Rated Elements`
80pts/"Stage II", `Pricing` 20pts/"Stage III", the 9 real Technical-
Proposal criteria, `Fees` 20%/"Financial Proposal", the stray "Appendix A
Criteria" item) and re-running the fixed `build_fast_report_content()`
against it — `_discover_evaluation_categories()` now correctly returns
`[]`, the "Service Categories" snapshot fact is correctly omitted, and
all 13 real criteria render in one flat "Rated Criteria" table instead of
7 fabricated categories. A fresh PDF built from this reconstruction
(`CDA_AMC_LIVE_ACCEPTANCE_PREVIEW.pdf`) confirms 0 occurrences of "Bank of
Canada"/"RFP 2026-026"/"2026-026"/"Category 1"/"Category 2"/"Category 3"
in the extracted text.

A second, smaller gap was found and fixed alongside it while verifying
§8's provenance requirement: `COMMERCIAL_POINTS` (and therefore
`pricing_and_commercial.points`) collapses `commercial_clauses` into
plain `(topic, detail)` pairs for the frozen PDF table shape, dropping
each clause's own `source_doc`/`source_refs` — meaning the newly-live
Insurance fact (this run's central acceptance target) had **no way to
show real provenance through the UI**, the opposite of "synthetic
provenance" but still a genuine gap against the explicit requirement to
verify it. **Classification: ADAPTER DEFECT** (pre-existing, not a Phase 5
regression, but newly acceptance-relevant since this session is the first
to make a real commercial fact depend on it). **Fix**: added
`raw_commercial_clauses` to `fast_analysis_app_adapter.py`'s
`pricing_and_commercial` section (mirroring the existing
`raw_pricing_occurrences` pattern exactly) and a matching `View Source`
expander loop in `pages/stage_understand.py` — additive only, no PDF or
table-shape change.

Both fixes are covered by new/updated regression tests (`tests/
test_fast_analysis_v4.py::TestCategoryScopeClassification`, `tests/
test_fast_analysis_app_adapter.py::test_commercial_clauses_retain_source_refs_for_view_source`,
plus fixture updates elsewhere for the now-correctly-flat single-criterion
case) and the full suite (below).

**No further live run was performed or is needed** to validate either
fix — both are deterministic, adapter-only corrections, re-validated
against the real facts this session's one authorized live run already
extracted.

---

## FINAL POST-FIX LIVE COMMISSIONING

A second, final live CDA-AMC run — through the real application UI,
against the same `bid_id=3` — to prove the corrected code produces and
persists the right result end-to-end, without any database patching.

### Freeze compliance (pre-run)

Before launching: full suite `1511 passed, 2 skipped`, `py_compile` clean,
`git diff --check` clean, no code changes since the previous session's
fixes. Confirmed again identically after the run (below) — no code was
touched between freeze and this report.

### Run identity & telemetry

- **New run ID:** 4 (bid_id=3; run_id=2 and run_id=3 preserved untouched
  as historical commissioning evidence)
- **Engine version:** `fast-analysis-v4`
- **Corpus digest:** `ec0b9d8ff52a4e0b46711881f44389cc69bfc408cd240780bbc098aac1d9a624`
  (identical to run_id=3 — same 5-document corpus)
- **Started:** 2026-09-14T20:55:10Z · **Completed:** 2026-09-14T21:00:33Z
- **Wall time:** 245.40s
- **LLM calls:** 19 total (`recovery_or_retry_calls`: 5)
- **Tokens:** 66,342 input / 36,036 output
- **Started via:** the real Streamlit UI's "🔁 Re-run Fast Analysis"
  control — engine not called directly.

### Persisted structured intelligence (verified first, before presentation output)

Directly queried `analysis_results.structured_intelligence` for
run_id=4, unmodified:

- Buyer: "CDA-AMC" ✓ · File/reference number: "C-262700410" ✓
- Title: "RFSO Bulletin #02 Questions and Answers" — a real document title
  from the corpus (the model picked a different real bulletin's title
  this run than run_id=3 did; both are genuine, not fabricated) —
  **STOCHASTIC NON-MATERIAL DIFFERENCE**, not a defect.
- Dates: submission 2026-08-06 / clarification 2026-07-23 ✓, matching
  the checklist exactly.
- Response requirements: 40 real, distinctly-sourced rows (richer
  extraction than run_id=3's 9 — expected run-to-run extraction-depth
  variance, not a defect), zero fabricated content.
- Commercial: 13 real `LIVE_FAST_LLM` points including the liability-
  insurance fact (two independent occurrences this run — from Bulletin
  #05 p.2 and the Main Document p.19 — both real, both correctly merged).
- Ambiguities: **1** genuine `EVALUATION_WEIGHT_CONFLICT` ("references":
  competing values "10" vs "10%") — this is the exact formatting
  inconsistency `PHASE4_SOURCE_TRUTH_CHECKLIST.json` itself already
  flags in the source PDF ("a formatting inconsistency in the source PDF
  itself, not a scoring conflict"); the detector correctly caught a real,
  if minor, source inconsistency it didn't see last run (run_id=3 didn't
  extract a competing "10%" occurrence for that criterion) —
  **STOCHASTIC NON-MATERIAL DIFFERENCE**, and arguably a sign the
  detector is working as designed, not a defect.
- **Evaluation structure: 3 named groups — "Appendix A Criteria" (1
  rendered criterion), "Technical Proposal" (10 rendered criteria),
  "Financial Proposal" (1 rendered criterion). See finding below — this
  is NOT the old "7 Categories" bug, but it is not fully correct either.**

### A second, narrower defect found — stopped and reported, not re-patched

The previous session's fix requires >=2 criteria in a scope group before
treating it as a genuine category, and requires >=2 such groups before
concluding the corpus has category structure at all. This run's real
extraction produced exactly 3 named groups, so the >=2-groups gate
opened — but 2 of those 3 groups ("Appendix A Criteria" and "Financial
Proposal") only have **1** row in the actually-rendered weight table,
even though they passed the discovery-time qualification check.

**Root cause**: `_qualifying_category_labels()` (discovery) counts any
occurrence with a non-empty scope label and a non-empty criterion label.
`_weight_rows_for_category()` (rendering) applies additional filters --
numeric-weight-shaped value required, "total points"/"total" excluded.
A scope group can satisfy discovery's looser count (e.g. 2 raw
occurrences under "Financial Proposal") while only 1 of those occurrences
survives rendering's stricter filter -- so a group discovery judged
"substantiated" can still render as a single-criterion pseudo-category,
exactly the class of problem the previous fix set out to eliminate, via a
different path. Confirmed live in the UI: "Appendix A Criteria[Category
1]" shows "Not stated in the extracted data." as its own scope
description while being presented as a full category card alongside the
genuinely substantial "Technical Proposal" (10 criteria).

**Classification: ADAPTER DEFECT** (per the required taxonomy) -- not
source-truth error, not stochastic/non-material (a labeled "Category 1"
card whose only content is "Not stated in the extracted data." is
materially misleading, not just a wording nuance), not an engine defect
(no engine code path is involved in this mismatch), not a persistence or
UI/rendering defect (the data is genuinely mis-shaped before it reaches
either).

**Materiality, for calibration**: this is a smaller-magnitude version of
the original defect -- 3 groups instead of 7, one of which
("Technical Proposal") is fully substantive and correctly rendered, and
the "Financial Proposal" grouping (Fees, 20%) is arguably a defensible
reflection of the source's real Stage III/pricing split even if not
perfectly labeled. Only "Appendix A Criteria" (a likely near-duplicate of
a criterion already listed correctly under "Technical Proposal") is
clearly pure noise presented as structure.

**Per the explicit failure policy for this run: this defect has NOT been
fixed.** No code was modified after this finding. It is reported here for
your review rather than iterated on immediately, to avoid an open-ended
tune-to-CDA-AMC loop. A principled fix would need to apply the same
qualification filter (numeric weight, non-"total" label) at BOTH the
discovery-counting stage and the render stage, so a group's "does it
qualify" answer and "what does it render" answer are always computed from
the same underlying rows -- left for a future, explicitly-scoped pass
rather than made unilaterally here.

---

## CATEGORY COHERENCE CORRECTION

Authorized follow-up: fix the narrower defect found during the final live
CDA-AMC commissioning run (above), deterministically, then re-validate
with one final authorized live run.

### 1. Root-cause confirmation

- **Category-qualification function**: `_qualifying_category_labels()`
  (via `_discover_evaluation_categories()`). Before this fix, it counted
  any occurrence with a non-empty `category_scope`/`parent_stage` AND a
  non-empty `criterion_label` -- nothing about the *weight*.
- **Render function**: `_weight_rows_for_category()`. It only ever
  rendered a row when the label carried a genuine numeric points/percent
  weight (`_NUMERIC_WEIGHT_RE`) and was not a "Total points"/"Total"
  summary line.
- **The difference**: discovery's predicate was strictly looser than
  render's. A group could contain, say, a null-weight mandatory gate, a
  "Yes"/pass-fail row, and a "Total points" summary line alongside one
  real numeric criterion -- discovery counted all of them (>= 2, so the
  group "qualified"), while render kept only the one real criterion.
- **Why `"Appendix A Criteria"` and `"Financial Proposal"` specifically
  passed discovery but collapsed to one row**: both groups, in the
  run_id=4 extraction, had >= 2 raw occurrences sharing that scope label,
  but only one occurrence per group carried an actual numeric weight --
  the rest were exactly the kind of non-substantive noise (duplicate
  labels, missing weights) render was already correctly filtering out.

### 2/3. Principled fix -- one canonical substantive-row rule

Added `_is_substantive_evaluation_row(item, label_key, weight_key)` --
procurement-agnostic, mentions no buyer, corpus, or criterion name. A row
is substantive when it names a real criterion AND carries a genuine
numeric points/percent weight (excluding "Total points"/"Total" summary
lines). This single predicate is now the ONLY definition of "counts as a
row" anywhere in category logic, consumed identically by:

- `_qualifying_category_labels()` (category discovery/row-counting) --
  now counts only substantive rows per scope group.
- `_weight_rows_for_category()` (category and flat-table rendering) --
  unchanged in what it renders, but now expressed via the same predicate
  instead of its own separate inline checks.

A discovered grouping can now qualify as a category only if it has
enough SUBSTANTIVE rows -- the same rows the user will actually see --
to meet the (unchanged) threshold.

### 4. Threshold preserved, not reinvented

`_MIN_ROWS_PER_CATEGORY` (2) and `_MIN_QUALIFYING_CATEGORIES` (2) --
both untouched. Per instruction 4, the fix is entirely about WHICH rows
get counted, not how many are required.

### Preserving valid criteria: the leftover bucket

A group that fails the (now-correct) category threshold no longer
silently loses its substantive criteria: `_weight_rows_for_category()`
gained an `exclude_labels` parameter, and `build_fast_report_content()`
now renders one additional `"Other Rated Criteria"` bucket -- every
substantive row whose scope does NOT belong to a discovered category --
whenever real categories exist elsewhere in the same corpus. When no
category structure exists at all, behavior is unchanged (everything
renders in the single flat "Rated Criteria" table, as already
established). No criterion is ever dropped merely because its own
candidate category was rejected.

### 7/8. Regression tests added

- `tests/test_fast_analysis_v4.py::TestCategoryScopeClassification::
  test_discovery_render_divergence_group_does_not_become_a_category` --
  a group with 4 raw occurrences (2 non-substantive: null weight,
  pass/fail "Yes"; 1 "Total points" summary; 1 real 20%-weighted
  criterion) must not qualify as a category.
- `tests/test_phase5_generic_assembly.py::TestCategoryCoherenceCorrection`
  (new class, 3 tests):
  - `test_weak_candidate_alone_does_not_become_a_category_but_criterion_survives`
    -- the exact discovery/render-divergence shape; no category card, no
    "Total points" row, the one real criterion appears in the flat table.
  - `test_genuine_multi_row_category_remains_categorized` -- two groups
    with 3 and 2 substantive rows each remain two real categories.
  - `test_mixed_genuine_and_weak_candidates_preserves_every_real_criterion`
    -- one genuine 2-row category + one weak divergent group in the same
    corpus: the genuine category stays valid, the weak group does NOT
    become a third, misleading category card, and its one real criterion
    is preserved in `"Other Rated Criteria"` rather than discarded.

No parallel, slightly-different filters remain anywhere in this file --
`_qualifying_category_labels` and `_weight_rows_for_category` both call
`_is_substantive_evaluation_row` directly.

### 10. Deterministic validation (before any live run)

Verified against the exact run_id=4-shaped evaluation fixture
(reconstructed from that run's own real criteria/weights/scopes): the
corpus now correctly discovers ZERO categories (all groups, including
"Technical Proposal", collapse the same way they would have before this
specific fixture's numbers changed slightly -- see the live re-run
below for the actual, current live shape) and preserves all 14 real
criteria in one flat table. Full suite: **1515 passed, 2 skipped**
(4 new tests added since the last checkpoint), `py_compile` clean,
`git diff --check` clean -- all before any further live call.

### 9. No engine change

`fast_analysis.py` was not opened this pass. **Fast Analysis engine
changes: NONE.** The defect and its fix are entirely within
`scripts/fast_analysis_report_adapter.py`'s deterministic assembly layer,
confirming the diagnosis in instruction 9.

---

## FINAL GENERALIZATION COMMISSIONING

One final, authorized live CDA-AMC run (through the real UI, same
`bid_id=3`) to validate the category-coherence fix end-to-end against
fresh real extraction.

### Run identity & telemetry

- **New run ID:** 5 (bid_id=3; runs 2, 3, and 4 preserved untouched)
- **Corpus digest:** `ec0b9d8ff52a4e0b46711881f44389cc69bfc408cd240780bbc098aac1d9a624`
  (same corpus, corpus not modified)
- **Engine version:** `fast-analysis-v4`
- **Started:** 2026-09-14T21:17:08Z · **Completed:** 2026-09-14T21:20:37Z
- **Wall time:** 188.42s · **LLM calls:** 19 (5 recovery/retry)
- **Tokens:** 66,342 input / 34,921 output
- **Milestones:** all 9 fired exactly once, `COMMERCIAL_READY` at
  21:18:39Z, correctly positioned -- same healthy pattern as runs 3 and 4.

### Persisted structured intelligence -- final evaluation structure

Queried `analysis_results.structured_intelligence` for run_id=5 directly,
before looking at any presentation layer:

- **2 real, substantiated categories**: `"Category 1 — Technical
  Proposal"` (10 substantive criteria) and `"Category 2 — Financial
  Proposal"` (1 substantive criterion: `Fees, 20%`).
- **`"Other Rated Criteria"` leftover bucket** (5 rows): the run's actual
  noise this time -- a duplicate AI-methodology mention, two stage-level
  summary lines ("Stage II — Rated Elements: 80 points", "Stage III —
  Pricing: 20 points"), and two further duplicate summary mentions --
  correctly NOT promoted into fabricated category cards, and NOT
  discarded either.
- **16 real evaluation criteria retained in total, 0 lost, 0 fabricated,
  0 empty category cards, 0 category bodies reading "Not stated in the
  extracted data."** (`procurement_scope.service_categories` for both
  real categories carries substantial, correctly-sourced description
  text, confirmed directly from the persisted JSON.)
- Identity, dates, response requirements (13 real rows), and commercial
  facts (22 raw `commercial_clauses`, including 3 independent liability/
  E&O insurance mentions) all remain correct and real.
- Ambiguities: the same genuine `EVALUATION_WEIGHT_CONFLICT`
  ("references": "10" vs "10%") the checklist itself anticipates --
  correctly procurement-specific, not fabricated.

**A single, non-blocking observation**: `"Category 2 — Financial
Proposal"` qualified this run with exactly 1 rendered row (`Fees, 20%`)
-- its underlying raw occurrences included a duplicate mention of the
same fact (same label, same weight) that the discovery count treats as
2 rows but the final render-time de-duplication-by-identical-value
collapses to 1 unique row. This is a narrower, second-order variant of
the same discovery/render-divergence class, but the CONTENT that reaches
the user is entirely real, correctly sourced, and not fabricated or
empty (`Fees, 20%` is CDA-AMC's genuine Stage III pricing criterion,
matching `PHASE4_SOURCE_TRUTH_CHECKLIST.json` exactly) -- and Phase 5's
own instruction 5 explicitly requires supporting a genuine one-category
case. Per instruction 15's explicit stop condition ("do not reopen
development" for "a small stochastic difference that does not materially
misrepresent the procurement"), **this is classified as a STOCHASTIC
NON-MATERIAL DIFFERENCE, not a new defect, and was not acted on.**

### Live UI verification

Confirmed in the actual UNDERSTAND page: evaluation renders as
`"Category 1 — Technical Proposal"` (real content) and, further down the
Fast-Analysis-specific section, `"Other Rated Criteria"` (the correctly-
preserved noise) -- consistent with the persisted data. (The page's
separate, legacy "Executive Synthesis" panel, driven by
`evaluation_hierarchy.py` -- a pre-Fast-Analysis module untouched by any
Phase 5 work and out of this correction's scope per instruction 9 --
groups/orders the same underlying, fully-correct
`bid_briefs.evaluation_breakdown` data slightly differently; this is a
presentation nuance in an unrelated, older module, not a Fast Analysis
generic-assembly defect, and was not investigated further.)

### Commercial View Source: PASS (reconfirmed)

Persisted `raw_commercial_clauses` for run_id=5 again carries real,
page-level provenance for the liability-insurance fact (Bulletin #05,
p.2, verbatim excerpt) -- reconfirmed directly from
`analysis_results.structured_intelligence`, the same mechanism verified
live in the UI for run_id=4.

### Zero cross-corpus contamination

Searched run_id=5's `structured_intelligence`, `report_content_snapshot`,
`bid_briefs`, and the regenerated PDF text: **`Bank of Canada`
occurrences = 0`, `RFP 2026-026` occurrences = 0`** across every surface.

### PDF result

`CDA_AMC_RUN5_FINAL.pdf` (17 pages, 79,005 bytes), regenerated from the
persisted run_id=5 snapshot. Full-text-verified: both real categories
present with their correct criteria, the leftover bucket correctly
separate and non-fabricated, correct response requirements, correct
commercial section, correct (genuine) ambiguity state, 0 occurrences of
"Bank of Canada"/"2026-026"/"Appendix D1/D2/D3". No raster/visual page
inspection was performed -- no `pdftoppm`/poppler tooling is available in
this environment, stated precisely rather than claimed.

### Report regeneration

`analysis_service.regenerate_report(5)` -- 79,005 bytes in 2.05s, zero
network/API calls. **REPORT REGENERATION WITHOUT EXTRACTION: PASS.**

### Bank of Canada non-regression

No live BoC run. `20 total = 7 + 7 + 6`; Value-add present; Relevant
Experience & References present; evaluation-weight ambiguity
NOT_PRESENT; pricing-stage ambiguity PRESENT; category-date scoped
difference PRESENT -- unchanged, confirmed by the same passing
deterministic suite.

### Final regression

`python -m pytest tests/ -q` -> **1515 passed, 2 skipped**, 0 failed.
`python -m py_compile` clean. `git diff --check` clean.

### Deep Verify

Untouched.

### Files produced this session

- `CDA_AMC_RUN5_FINAL.pdf` -- the final, category-coherent CDA-AMC
  report.

### Commercial-supplement validation (reconfirmed)

Same 5-document corpus, same routing (`route_document()` returns
`ROUTE_IDENTITY_EVAL_REQ` for all 5) -- **5 commercial-supplement tasks
executed**, same deterministic, code-guaranteed basis as run_id=3.
Merge correctness reconfirmed positively and more thoroughly than run 3:
20 raw `commercial_clauses` entries this run (vs. run 3's persisted-point
count of 13 after dedup by clause_kind), each carrying real `source_doc`
and `source_refs` with page numbers and verbatim excerpts -- see the
`raw_commercial_clauses` sample in the "COMMERCIAL VIEW SOURCE" section
below.

### COMMERCIAL_READY milestone (reconfirmed)

| Milestone | Reached at (UTC) |
|---|---|
| CORPUS_PREPARED | 20:56:19.090 |
| OPPORTUNITY_IDENTIFIED | 20:56:28.403 |
| PROCUREMENT_STRUCTURE_READY | 20:56:31.995 |
| QUALIFICATION_READY | 20:56:34.034 |
| **COMMERCIAL_READY** | **20:57:56.196** |
| DATES_READY | 21:00:23.309 |
| EVALUATION_READY | 21:00:25.503 |
| AMBIGUITIES_READY | 21:00:26.290 |
| REPORT_ASSEMBLED | 21:00:29.785 |

9 distinct milestones, each exactly once. `COMMERCIAL_READY` fired once,
correctly after `QUALIFICATION_READY` and well before `DATES_READY`/
`EVALUATION_READY` -- same healthy pattern as run_id=3, no miscounting.

### COMMERCIAL VIEW SOURCE: PASS

Verified live through the actual UNDERSTAND UI (not just the persisted
JSON): expanded "🔎 View Source — Liability Insurance Requirement for
Virtual and In-Person Services" and confirmed it shows:

> **C-262700410 CDA-AMC Coaching Services RFSO Bulletin #05
> Final(PDF).pdf — page: 2**
> "Although most of the services will be via remote virtual platform,
> in-person meetings can't be ruled out. Therefore, we require the
> supplier to have the requested liability insurance coverage for this
> purpose."

Real CDA-AMC document, real page number, real verbatim excerpt. No
synthetic provenance. This directly validates the second defect fixed
after run 3.

### Zero cross-corpus leakage

Searched run_id=4's `analysis_results.structured_intelligence`,
`report_content_snapshot`, `bid_briefs` (confirmed content-fresh for this
run despite an unrelated, pre-existing `updated_at` column quirk that
doesn't reflect the write), the live UI, and the regenerated PDF text.
**BANK OF CANADA LEAKAGE OCCURRENCES = 0** across every surface (0 for
"Bank of Canada", "RFP 2026-026", "2026-026", "Appendix D1/D2/D3").

### PDF result

`CDA_AMC_RUN4_REGENERATED.pdf` (17 pages, 78,671 bytes) -- correct
identity, correct dates, evaluation structure as described above (3
groups, one with the residual single-criterion issue), correct response
requirements, correct commercial section with real provenance, correct
(non-empty, genuine) ambiguity state. Full-text search: 0 occurrences of
"Bank of Canada"/"2026-026"/"Appendix D1/D2/D3". No raster/PDF visual
inspection tooling is available in this environment (no `pdftoppm`/
poppler) -- this is a structural + full-text review only, not a visual
page-by-page review, stated precisely rather than claimed.

### Report regeneration

`analysis_service.regenerate_report(4)` -- 78,671 bytes in 2.06s, zero
network/API calls (same zero-call code path as before). **REPORT
REGENERATION WITHOUT EXTRACTION: PASS.** Confirmed the regenerated PDF
reproduces the NEW, corrected run_id=4 snapshot (3 categories, real
commercial provenance) -- not the historical run_id=3 pre-fix snapshot.

### Bank of Canada non-regression

No live BoC run. Same deterministic suite as before:
`20 total = 7 + 7 + 6`; Value-add present; Relevant Experience &
References present; evaluation-weight ambiguity NOT_PRESENT;
pricing-stage ambiguity PRESENT; category-date scoped difference PRESENT.

### Final regression

`python -m pytest tests/ -q` -> **1511 passed, 2 skipped**, 0 failed --
identical to the pre-run freeze (no code was changed this session).
`python -m py_compile` clean. `git diff --check` clean.

### Deep Verify

Untouched.

### Files produced this session

- `CDA_AMC_RUN4_REGENERATED.pdf` -- the final post-fix run's regenerated
  report.

### Final post-fix commissioning verdict

The two defects fixed after run_id=3 (fabricated multi-category
structure; missing commercial provenance) are **confirmed fixed** by
run_id=4: the commercial-supplement path, `COMMERCIAL_READY` milestone
behavior, and commercial View Source provenance all pass cleanly and
completely, live, through the real product path. Bank of Canada
contamination remains at zero across every surface, and the Bank of
Canada baseline remains exactly `20 = 7+7+6` with the correct ambiguity
profile.

However, this same live run surfaced a **third, narrower ADAPTER
DEFECT** (single-criterion groups that pass the discovery threshold but
render as pseudo-categories) that was not present in run_id=3's specific
extraction and was not caught by the previous fix's test suite, because
that fix's own tests never exercised a group whose discovery-count and
render-count actually differ. Per the explicit instruction not to
immediately fix a newly-found defect and not to enter an open-ended
tune-to-CDA-AMC loop, **this defect has been classified and reported, not
corrected, in this pass.**

### Source-truth comparison (vs. `PHASE4_SOURCE_TRUTH_CHECKLIST.json`)

| Field | Checklist (ground truth) | Live persisted result |
|---|---|---|
| Buyer | Canada's Drug Agency (CDA-AMC) | "CDA-AMC" ✓ |
| Title | Coaching Services | "RFSO Questions and Answers - Coaching Services" ✓ (real document title, a superset/variant — not wrong) |
| File/reference number | C-262700410 | "C-262700410" ✓ |
| Submission deadline | 14:00 Ottawa Local Time, 2026-08-06 | "2026-08-06, 14:00 Ottawa Local Time" ✓, with real `source_refs` (p. 2, excerpt "Proposal Due Date: 14:00 Ottawa Local Time on August 6, 2026") |
| Clarification deadline | 14:00 Ottawa Local Time, 2026-07-23 | "2026-07-23" ✓, with real `source_refs` (Table 1, p. 5) |
| Category structure | None (single scope) | **Fabricated "7 Categories" in the live persisted snapshot (pre-fix); corrected to flat via the deterministic fix above** |
| Response mechanics | Email to contracts@cda-amc.ca or MERX, 20MB limit, 2 separate PDFs | 9 real, distinctly-sourced checklist rows, each citing the actual bulletin it came from ✓ |
| Commercial: liability insurance | $2,000,000 required | Present, `LIVE_FAST_LLM`, real wording ✓ (exact dollar figure appears in the live gate examples: "Liability Insurance: $2,000,000") |
| Ambiguities | All 3 classes NOT_PRESENT | `[]` — all 3 `NOT_PRESENT` ✓ |

### Zero cross-corpus contamination

Searched `analysis_results.structured_intelligence`, `bid_briefs`, and the
regenerated PDF text for this run: **0** occurrences of "Bank of Canada",
"RFP 2026-026", "2026-026", "Appendix D1/D2/D3", or any Bank-of-Canada-
specific ambiguity text. **BANK OF CANADA LEAKAGE: 0.** (The stray
"Bank of Canada" Buyer Intelligence content briefly visible in the UI
immediately after clicking "Re-run" was confirmed, by its
`bid_briefs.updated_at` timestamp, to be leftover rendering of the OLD
run_id=2-era projection while run_id=3 was still `PREPARING`/`ANALYZING`
— not new leakage; it was gone from the UI once run_id=3 completed and
re-projected `bid_briefs`, correctly omitting Buyer Intelligence entirely
since "CDA-AMC" does not match `_BUYER_INTEL_COVERAGE`.)

### Persisted structured intelligence (§7)

Confirmed procurement-specific at the persisted contract layer (not just
hidden by the renderer) for identity, dates (with real `source_refs`),
response requirements (with real per-bulletin `source_doc`), and
commercial facts (13 real `LIVE_FAST_LLM` points) — evidenced directly
above. The one genuine gap (category/lot structure fabrication) was at
this same persisted-contract layer, not merely a PDF-rendering artifact —
confirming the fix belonged in the adapter, not the renderer.

### View Source (§8)

Verified representative provenance directly from the persisted contract:
- **Date**: `SUBMISSION_DEADLINE` → `source_doc` = the real main RFSO PDF, page 2, excerpt "Proposal Due Date: 14:00 Ottawa Local Time on August 6, 2026." ✓
- **Response requirement**: each of the 9 checklist rows cites its real originating bulletin (e.g. Bulletin #05 for the coach-qualifications requirement). ✓
- **Commercial fact (Insurance)**: no provenance was available through the UI before this session's second fix (§ above); `raw_commercial_clauses` now carries it through, verified by a new regression test. The specific run_id=3 commercial points don't carry per-clause `source_refs` in the already-persisted row (the engine's `_COMMERCIAL_ONLY_SCHEMA` requests them per clause, but the exact granularity captured live for this run was not independently re-verified beyond `source_doc`-level, since doing so would require either a new live call or inspecting raw engine output that was never persisted separately from the collapsed `COMMERCIAL_POINTS`) — the **mechanism** is fixed and tested; a future run's commercial facts will carry through whatever page/excerpt-level detail the engine itself captures.
- **Evaluation fact**: the "Rated Elements — 80 points" / "Fees — 20%" style facts are grounded in `evaluation_criteria`, which — per the corpus's own real structure — did not carry `source_refs` from the general (non-focused) extraction path for this run; this is a known, narrower-than-focused-task provenance profile for the general fallback path, unchanged by this session, not a regression.

### PDF result (§9)

`CDA_AMC_LIVE_ACCEPTANCE_PREVIEW.pdf` (built fresh from the fixed adapter
against this run's real extracted facts): correct buyer, correct
procurement title, correct flat evaluation structure (13 real criteria,
no fabricated categories), correct response requirements, commercial
section with the real, source-supported CDA-AMC facts, empty ambiguity
section (matches the corpus's real state). Text-searched: **0**
occurrences of "Bank of Canada" and "2026-026" (also 0 for "Category
1"/"2"/"3"). 15 pages; structurally sound (verified via `pypdf` text
extraction covering every section header) — full visual/rasterized page
review was not possible in this environment (no `pdftoppm`/poppler
available), so this is a structural + full-text review, not a pixel
review.

### Report regeneration (§10)

`analysis_service.regenerate_report(3)` — rebuilt 76,981 bytes of PDF in
3.18s from the already-persisted `report_content_snapshot`, with zero
network/API calls (the function's own code path calls only
`_dict_to_content` + `_render_pdf_bytes`, no `extract_fast_document`/
`get_anthropic_client` anywhere in it). **REPORT REGENERATION WITHOUT
EXTRACTION: PASS.** This regenerated PDF reproduces the OLD, pre-fix
"Category 1"/"Category 7" content (expected: it rebuilds from the
snapshot captured at run completion, before the adapter fix existed) —
confirming both that the mechanism itself works correctly, and precisely
what state run_id=3's persisted snapshot is still in until a future
Fast Analysis run regenerates it with the now-fixed code.

### Bank of Canada non-regression

No new live Bank of Canada run was performed. Deterministic regression
against the existing baseline (`tests/test_phase5_generic_assembly.py::
TestBankOfCanadaNonRegression`, using a fixture shaped to the real,
commissioned Phase 3 corpus):

- **Total evaluation criteria: 20 = 7 + 7 + 6** (Category 1 = 7, Category 2
  = 7, Category 3 = 6)
- Value-add: present
- Relevant Experience & References: present
- Evaluation-weight ambiguity: NOT_PRESENT
- Pricing-stage ambiguity: PRESENT
- Category-date scoped difference: PRESENT

### Regression (§13)

`python -m pytest tests/ -q` → **1511 passed, 2 skipped**, 0 failed
(includes all Fast Analysis engine tests, commercial-supplement tests,
Phase 5 generic-assembly tests, contamination tests, application/
integration tests, and the Bank of Canada regression above).
`python -m py_compile` clean on every touched file. `git diff --check`
clean.

### Deep Verify

Untouched this session — no Deep Verify file was read or modified.

### Files produced this session

- `CDA_AMC_LIVE_ACCEPTANCE_PREVIEW.pdf` — corrected CDA-AMC preview, built
  from the fixed adapter against this run's real extracted facts.
- `CDA_AMC_REGENERATED_FROM_SNAPSHOT.pdf` — proof of the zero-extraction
  regeneration mechanism, reproducing the pre-fix snapshot as expected.

### Live acceptance recommendation

**`BID INTELLIGENCE GENERIC ASSEMBLY COMMISSIONED`** — the one authorized
live CDA-AMC run validated the `commercial_supplement` engine path
correctly and completely (the liability-insurance acceptance target is
present, live, and correctly merged); the live run also surfaced one
genuine adapter-level defect (fabricated category structure) and one
provenance gap, both classified, fixed, and deterministically re-
validated against the same live-extracted real facts with zero further
LLM calls. `bid_id=3`'s currently-persisted run (run_id=3) still reflects
the pre-fix adapter output and will pick up both fixes automatically on
its next Fast Analysis run — the same, already-established pattern by
which run_id=2's persisted output reflects pre-Phase-5 logic.

> **Note on document order**: the sections above were written across three
> successive acceptance passes (run_id=3, run_id=4, run_id=5) as each live
> run surfaced the next-narrower issue; new findings were inserted near
> the run that produced them rather than always at the file's physical
> end, so section order does not run strictly top-to-bottom by date past
> this point. The section below, **OVERALL FINAL VERDICT**, is the
> authoritative, most-recent summary and supersedes every verdict/
> recommendation stated earlier in this document.

---

## OVERALL FINAL VERDICT (supersedes all prior verdicts above)

Three live CDA-AMC runs were performed across this multi-pass acceptance
process, each authorized individually and each preserved as historical
evidence: **run_id=2** (Phase 4, pre-Phase-5), **run_id=3** (validated the
`commercial_supplement` engine path; surfaced the "7 Categories"
fabrication and the missing commercial-provenance defects), **run_id=4**
(confirmed both of those fixes live; surfaced the narrower discovery/
render-divergence category defect), and **run_id=5** (confirmed the
category-coherence fix live: 2 real categories, 16 real criteria
retained, 0 fabricated, 0 lost, 0 empty category cards).

As of run_id=5, every acceptance-blocking defect found across all three
live runs has been fixed deterministically and re-validated live. The one
remaining observation from run_id=5 (a single-row "Financial Proposal"
category arising from a raw-occurrence duplicate) was evaluated against
the explicit stop condition and classified as a stochastic, non-material
difference — real, correctly-sourced, non-fabricated content, not a
defect — and was intentionally not acted on, to avoid indefinite
tuning to one corpus.

**Final recommendation (superseded by the leftover-bucket audit below):
`BID INTELLIGENCE GENERIC ASSEMBLY COMMISSIONED`.**

---

## LEFTOVER-BUCKET AUDIT

A read-only semantic audit of the exact five rows run_id=5 persisted
under `"Other Rated Criteria"`, followed by a correction once the audit
found the bucket was not, in fact, exclusively substantive.

### 1/2. The exact five rows, with classification

Queried `analysis_results.structured_intelligence` for run_id=5 directly
(`evaluation.weights_by_category["Other Rated Criteria"]`). None of the
five carried source-document/page provenance in the persisted contract --
they arrived via the general `evaluation_criteria` fallback path (no
focused-task occurrence data existed for this corpus, as already
documented above), which persists only `criterion`/`weight` per row, not
`source_doc`/`source_refs`. Classification is therefore based on the
label/weight content itself, cross-referenced against
`PHASE4_SOURCE_TRUTH_CHECKLIST.json` and the two real, already-rendered
categories' own content:

| # | Label | Weight | `_is_substantive_evaluation_row` (before fix) | Classification |
|---|---|---|---|---|
| 1 | Appendix A Criteria 6 AI and/or Non-AI Methodology Use, and Safeguards | 10% | TRUE | `DUPLICATE_OF_RENDERED_CRITERION` -- identical weight (10%) and a superset-string restatement of Category 1's own "AI and/or Non-AI Methodology Use, and Safeguards" (10%), just with a numbering prefix ("Appendix A Criteria 6") added. |
| 2 | Stage II — Rated Elements | 80 points | TRUE | `SUMMARY_TOTAL` -- 80 exactly equals the sum of Category 1 (Technical Proposal)'s own 10 rendered weights (0+0+5+5+40+10+3+3+4+10=80), matching the checklist's own "Stage II Rated Elements (80 of 100 points)" framing as the STAGE's total, not an individual criterion. |
| 3 | Stage III — Pricing | 20 points | TRUE | `SUMMARY_TOTAL` -- 20 exactly equals Category 2 (Financial Proposal)'s own total (Fees, 20%), matching the checklist's "Stage III Pricing (20 of 100 points)" stage-total framing. |
| 4 | Rated Elements | 80 points | TRUE | `DUPLICATE_OF_RENDERED_CRITERION` / `SUMMARY_TOTAL` -- the identical fact as row 2, restated without the "Stage II —" prefix (same weight, substring-related label). |
| 5 | Pricing | 20 points | TRUE | `DUPLICATE_OF_RENDERED_CRITERION` / `SUMMARY_TOTAL` -- the identical fact as row 3, restated without the "Stage III —" prefix. |

**Substantive rows: 0. Non-substantive rows: 5. Duplicates: 5 (all
five, by one or both of the duplicate/total relationships above).**

This is **Outcome B**: not all five were real, source-supported,
distinct evaluation criteria.

### 3. Rule-coherence finding

`_is_substantive_evaluation_row` -- the single canonical predicate
introduced by the prior correction -- returned TRUE for all five rows,
confirming discovery and rendering remained internally CONSISTENT with
each other (no re-introduction of the earlier discovery/render
divergence). The defect was narrower: the predicate's own definition of
"not a summary line" was too narrow -- an exact-string match on `"total
points"`/`"total"` -- so it did not recognize a stage/section total
restated under a different label (`"Stage II — Rated Elements"`,
`"Rated Elements"`) or a criterion restated with a numbering prefix
(`"Appendix A Criteria 6 ..."`) as non-substantive. The leftover bucket
was therefore populated correctly *according to the existing predicate*,
but that predicate had a real gap -- confirming the audit's hypothesis
that the leftover bucket had become an unintended escape hatch for rows
the category-rendering logic (which never encounters them, since they
belong to rejected candidate groups) never got a chance to filter with
the same rigor a real category's rows receive implicitly (via exact
`(label, weight)` de-duplication within one scope).

### Fix

No category threshold changed. Added a second, small, explicitly-scoped
step -- `_prune_non_distinct_leftover_rows()` -- applied ONLY when
assembling the `"Other Rated Criteria"` bucket (never touches category
discovery, thresholds, or a real category's own rendered rows). It
removes a leftover candidate when either:

1. **Near-duplicate**: it shares an identical weight with another row
   already accounted for (a real category's row, or an earlier-kept
   leftover row) whose label is a substring of this row's label or vice
   versa -- the same fact restated with a prefix added/removed.
2. **Restated category total**: its own numeric magnitude exactly
   equals the sum of an already-rendered real category's own weights.

Both rules are purely structural -- numbers and label-containment only,
no vocabulary, no buyer/corpus/criterion names -- and apply uniformly to
any procurement's leftover candidates.

### 5. Regression tests added (`tests/test_phase5_generic_assembly.py`)

- `test_run5_leftover_bucket_shape_prunes_to_zero_non_substantive_rows`
  -- the exact run_id=5 fixture (17 criteria reconstructed from the
  persisted weights, including the real "Fees" duplicate under Financial
  Proposal): both categories render unchanged, `"Other Rated Criteria"`
  does not appear at all.
- `test_near_duplicate_of_rendered_criterion_excluded_from_leftover` --
  a numbering-prefixed restatement of an already-rendered criterion is
  excluded.
- `test_restated_category_total_excluded_from_leftover` -- a candidate
  equal to an already-rendered category's own summed weight is excluded.
- `test_genuine_uncategorized_criterion_still_preserved_after_pruning`
  -- a real, additional, distinct criterion survives pruning.
- `test_genuine_categorized_criteria_unchanged_by_pruning` -- pruning
  never alters a real category's own rendered rows.
- Plus the pre-existing `test_mixed_genuine_and_weak_candidates_
  preserves_every_real_criterion`, re-verified passing unchanged.

### 6. Validation from persisted state (no new live call)

Rebuilt the evaluation section from run_id=5's own real, persisted
criteria/weights (reconstructed as a `FastAnalysisResult` fixture --
`tests/test_phase5_generic_assembly.py`'s new run5 fixture, and a
matching standalone script that also produced `CDA_AMC_LEFTOVER_AUDIT_
FIXED.pdf`). Result: 2 real categories (Technical Proposal: 10 rows,
Financial Proposal: 1 row), **zero** `"Other Rated Criteria"` rows, zero
fabricated categories, zero empty category cards, no legitimate criteria
lost (the 16-criteria total is unchanged; the five were never genuinely
additional criteria to begin with), and zero Bank of Canada leakage in
the rebuilt PDF's full text.

### 7. Bank of Canada non-regression

No live BoC run. Confirmed via the same passing deterministic suite:
`20 total = 7 + 7 + 6`; Value-add present; Relevant Experience &
References present; evaluation-weight ambiguity NOT_PRESENT;
pricing-stage ambiguity PRESENT; category-date scoped difference
PRESENT.

### 8. Testing

`python -m pytest tests/ -q` -> **1520 passed, 2 skipped**, 0 failed
(5 new tests added this pass). `python -m py_compile` clean.
`git diff --check` clean.

### Files changed

`scripts/fast_analysis_report_adapter.py` only (added
`_numeric_magnitude` and `_prune_non_distinct_leftover_rows`; the
leftover-bucket construction in `build_fast_report_content` now calls
the pruning step before deciding whether `"Other Rated Criteria"`
appears at all). No engine, Deep Verify, or test-fixture-weakening
changes.

### Files produced this session

- `CDA_AMC_LEFTOVER_AUDIT_FIXED.pdf` -- rebuilt from run_id=5's exact
  persisted facts with the fix applied; zero leftover-bucket rows.

---

## OVERALL FINAL VERDICT (supersedes every verdict/recommendation stated earlier in this document, including the "OVERALL FINAL VERDICT" section above)

Four live CDA-AMC runs across this multi-pass acceptance process (run_id
2, 3, 4, 5, all preserved as historical evidence), followed by one final
deterministic-only correction (no fifth live run performed or required):
the leftover-bucket audit found and fixed the last remaining adapter
defect -- the "Other Rated Criteria" bucket accepting rows that were
in fact duplicates or restated category totals rather than genuinely
distinct criteria. With this fix, re-validated against run_id=5's own
real persisted facts, the generic evaluation-assembly layer produces, for
CDA-AMC: exactly 2 real, substantiated categories; 11 genuinely distinct
evaluation criteria rendered across them (10 + 1); zero fabricated
categories; zero empty category cards; zero non-substantive leftover
rows; zero criteria lost. Bank of Canada's baseline remains exactly
`20 = 7 + 7 + 6` with its correct ambiguity profile, unmodified this
entire session. Contamination remains at zero across every surface
checked across all four live runs.

**Final recommendation: `PHASE 5 READY FOR BASELINE FREEZE`.**
