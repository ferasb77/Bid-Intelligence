# Bid Intelligence — Commissioned Baseline (Generic Assembly)

**Commissioned date:** 2026-09-15 (UTC)
**Status:** Live-commissioned, generic-assembly baseline. Product Integration Phases 1–5 complete, accepted, and hardened. This document supersedes the earlier single-procurement (Bank of Canada only) baseline and freezes the current, cross-procurement-validated state as the reproducible commissioned baseline.

---

## What is commissioned

Fast Analysis V4 is the default, integrated analysis path of the Bid Intelligence application — reachable through the real product UI (Bid → UNDERSTAND stage → ⚡ Fast Analysis panel), backed by durable Supabase persistence, with live, truthful progress reporting while a run is active and a full structured-intelligence view once it completes. As of Phase 5, the application/report assembly layer between the engine and the product surfaces (`OpportunityIntelligence`, `bid_briefs`, the UNDERSTAND UI, and the PDF) is procurement-agnostic: it derives every rendered fact from the current procurement's own extracted data, never from another corpus's real content.

| Component | Version / identifier |
|---|---|
| Fast Analysis engine | `fast-analysis-v4` |
| `MAX_DOCUMENT_CONCURRENCY` | 2 (frozen) |
| Application service boundary | `analysis_service.py` |
| Supabase migrations live | **004** (`analysis_runs`, `analysis_results`, RLS enabled) and **005** (`analysis_runs.progress` JSONB column) — unchanged from the earlier commissioned baseline |
| UI entry point | `pages/stage_understand.py` (`page_understand()` → `_render_fast_analysis_panel()`) |
| Report/application adapters | `scripts/fast_analysis_report_adapter.py` (deterministic `FastAnalysisResult → report content` assembly), `fast_analysis_app_adapter.py` (`OpportunityIntelligence` + `bid_briefs` projection) |

## Latest test result

**1520 passed, 2 skipped** (full repository suite, `pytest -q`), `py_compile` clean, `git diff --check` clean. The 2 skips are pre-existing, live-API-gated tests unrelated to this baseline (unchanged since Phase 1). Zero failures.

## Product state (Phase 5 additions)

- **Progressive analysis lifecycle**: QUEUED → PREPARING → ANALYZING → ASSEMBLING → COMPLETE/FAILED, with a durable, milestone-based progress record (`analysis_runs.progress`) that survives page reloads and reconnects.
- **Persisted structured intelligence**: every Fast Analysis run persists a full, durable `OpportunityIntelligence` contract (`analysis_results.structured_intelligence`) and a `fact_origins` map (LIVE_FAST_LLM / DETERMINISTIC_FAST_EXTRACTION / BUYER_INTELLIGENCE_EXTERNAL_LAYER / MISSING_NO_FALLBACK for every material section) — independent of any one rendering.
- **Source provenance**: dates, evaluation criteria, response requirements, and (as of Phase 5) commercial/contractual facts all carry real `source_doc`/page/excerpt provenance through to the UI's "View Source" expanders, verified live for a genuinely new fact class (a commercial clause extracted by the additive `commercial_supplement` engine path).
- **Generic report assembly**: `scripts/fast_analysis_report_adapter.py`'s `build_fast_report_content()` derives buyer identity, evaluation structure (however many real categories exist, including zero — a single flat table), response requirements, and commercial content entirely from the current procurement's own `FastAnalysisResult`. No procurement-specific knowledge (buyer names, category counts, appendix letters) remains in this code path; procurement-specific content lives only in the data, per Phase 5's governing architecture rule.
- **Cross-procurement contamination protections**: a permanent regression suite (`tests/test_phase5_generic_assembly.py::TestCrossCorpusContamination`) proves one procurement's rendered report can never contain another's identity or content, verified deterministically and confirmed live against two real, materially different procurements (below).
- **`commercial_supplement` engine path**: one additive, procurement-agnostic Fast Analysis task kind — for every document routed to the generic `ROUTE_IDENTITY_EVAL_REQ` fallback (i.e. any corpus with no exact `DOCUMENT_ROUTING` match), one extra `ROUTE_COMMERCIAL_ONLY` extraction pass runs so commercial/contractual facts bundled inside a broadly-routed document are not silently lost. Purely additive: never modifies a document's own existing extraction, and the `analysis_service.py` progress tracker's `COMMERCIAL_READY` milestone correctly waits for however many commercial-contributing tasks a corpus has (a dedicated commercial document, the additive supplement pass, or both) before firing, exactly once.
- **Generic evaluation assembly**: category/lot structure (however many categories exist, including a fully flat single-table corpus) is discovered from the procurement's own extracted `category_scope`/`parent_stage` text, using one canonical "substantive evaluation row" predicate (`_is_substantive_evaluation_row`) shared identically by category discovery, category row-counting, and final rendering — so a candidate group can never be judged "real" on rows that would not themselves survive into what the user actually sees. A candidate group that fails the category threshold does not lose its criteria: they render in a data-driven "Other Rated Criteria" leftover section, itself pruned of near-duplicate and restated-total rows via the same structural (label/weight-only, procurement-agnostic) logic.
- **Generic response-requirements assembly**: mandatory-category requirements render as a data-driven checklist with real per-item source attribution; no Appendix-letter assumptions.

## Validated procurements

### 1. Bank of Canada — RFP 2026-026 (source-truth baseline, unchanged since Phase 3)

One authorized live Fast Analysis run (Phase 3), started via the actual UI button, not a script:

- Bid: Bank of Canada, RFP 2026-026 (bid_id 8) · Run ID 1 · engine `fast-analysis-v4`
- 199.05s wall time · 22 LLM calls (11 recovery/retry) · 56,673 input / 51,265 output tokens
- Result: **COMPLETE**, structured intelligence persisted, `bid_briefs` projected correctly, 15-page PDF generated and downloadable, report regeneration proven to make zero extraction calls

**Authoritative source-truth evaluation count** (re-verified deterministically after every Phase 5 change; no live BoC re-run has been or should be performed to check this):

- **Total evaluation criteria: 20 = 7 + 7 + 6**
- Category 1 (Learning & Development, Form D1): 7 criteria, 75 points
- Category 2 (HR Advisory, Form D2): 7 criteria, 75 points — includes "Value-add" and "Relevant Experience & References," both **present**
- Category 3 (Facilitation & Team Effectiveness, Form D3): 6 criteria, 100 points (incl. Price)
- Ambiguity states: evaluation-weight ambiguity = **NOT_PRESENT** (retired as a false positive from scope conflation); pricing-stage ambiguity = **PRESENT**; category-date scoped difference = **PRESENT**

Full detail: `BID_INTELLIGENCE_PRODUCT_INTEGRATION_PHASE3_COMMISSIONING_REPORT.md`.

### 2. Canada's Drug Agency (CDA-AMC) — Coaching Services RFSO (Phase 4/5 generalization target)

Four live Fast Analysis runs, each through the real UI, against the same real 5-document corpus (`bid_id=3`), all preserved as historical commissioning evidence:

| Run ID | Purpose | Result |
|---|---|---|
| 2 | Phase 4 initial live commissioning (pre-generalization) | Confirmed the engine generalizes; the application/report layer did not yet |
| 3 | Validate the `commercial_supplement` engine path | Confirmed live; also surfaced the "7 fabricated categories" and missing-commercial-provenance defects |
| 4 | Confirm both fixes live | Confirmed; surfaced a narrower discovery/render-divergence category defect |
| 5 | Confirm the category-coherence fix live | Confirmed: 2 real categories, correct criteria, correct provenance |

**Accepted final deterministic interpretation** (Phase 5 leftover-bucket audit, applied to run_id=5's real persisted facts, zero further live calls):

- Buyer: **Canada's Drug Agency (CDA-AMC)** · Solicitation: **C-262700410**
- Evaluation structure: **Technical Proposal — 10 distinct criteria**, **Financial Proposal — 1 distinct criterion**
- **Total genuinely distinct rated criteria: 11**
- Valid uncategorized criteria: **0** · Fabricated categories: **0** · Non-substantive rendered evaluation rows: **0**
- Bank of Canada leakage: **0** (searched `structured_intelligence`, `report_content_snapshot`, `bid_briefs`, the live UI, and PDF text across all four runs)
- `commercial_supplement`: **validated live** (5 tasks, one per analyzed document, all routed to `ROUTE_IDENTITY_EVAL_REQ`)
- Liability insurance: extracted with **real page-level provenance** (Bulletin #05, p. 2, verbatim excerpt), confirmed live via the UI's View Source expander
- Commercial View Source: **validated live**
- Report regeneration without extraction: **PASS** (zero network/API calls, reproduces the current persisted snapshot)

Full detail: `BID_INTELLIGENCE_PHASE5_GENERIC_ASSEMBLY_REPORT.md`.

## Supabase migrations now live

- **004** (`migrations/004_analysis_runs.sql`) — `analysis_runs` and `analysis_results` tables, RLS enabled (no policies defined yet, by deliberate design), duplicate-active-run partial unique index.
- **005** (`migrations/005_analysis_run_progress.sql`) — additive `analysis_runs.progress` JSONB column (milestones + early facts for live progress reporting).

Both unchanged since the earlier commissioned baseline and independently re-confirmed unmodified as part of this freeze. Migrations 001–003 predate this engagement and are unchanged.

## Known limitations

Limitations the earlier baseline listed that Phase 5 has since resolved (Bank-of-Canada-only rendering, hardcoded evaluation-category assumptions, missing commercial provenance for supplement-extracted facts) have been removed from this list. What remains genuinely open:

1. **Only two materially different real procurements have been live-commissioned so far** (Bank of Canada and CDA-AMC). The generic assembly layer's rules (category-discovery threshold, substantive-row predicate, leftover-bucket pruning) were designed and tuned against these two corpora's real extraction behavior. Broader generalization confidence — a third, structurally different real procurement, deliberately not yet analyzed so this baseline stays clean and reproducible — still requires a dedicated holdout-validation phase.
2. **Fast Analysis remains probabilistic.** Two live runs against the identical CDA-AMC corpus (run_id 3 and run_id 5) produced different opportunity-title picks, different response-requirement counts, and a different evaluation-weight ambiguity finding — all non-material, correctly-sourced variation, not defects, but a real characteristic of live extraction that any consumer of this product should expect.
3. **`app.py`'s `page_bid_overview()` remains unreachable dead code**, unchanged since Phase 3 (out of scope for every phase since).
4. **Fast Analysis V4's document routing (`DOCUMENT_ROUTING`) is filename-identity-dependent for Bank of Canada's own optimized routes.** A document uploaded through a real browser file picker for any file other than the master RFP falls back to the broadest safe extraction mode (`ROUTE_IDENTITY_EVAL_REQ`) rather than its narrow, optimized route. This is by design (the safe generic fallback is exactly what makes the engine work correctly for every other real corpus, CDA-AMC included) but means Bank of Canada's own call profile depends on exact historical filenames.
5. **Visual PDF inspection depends on available local tooling.** This engagement's environment has no `pdftoppm`/poppler installed, so every PDF verification this session was a structural + full-text review (via `pypdf` text extraction), not a rasterized, page-by-page visual review. Anyone reproducing this baseline with visual-inspection tooling available should still perform one.
6. **The general (non-focused-task) evaluation-extraction fallback path does not carry `source_refs`.** When a corpus's real section headings don't match `find_section()`'s known patterns (confirmed live for CDA-AMC), evaluation data falls back to the broader `evaluation_criteria` family, which — unlike the focused rated-criteria task's own occurrences — does not carry per-criterion source page/excerpt provenance in the current schema. Identity, dates, response requirements, and commercial facts are unaffected.
7. **Live-run evidence (PDFs, telemetry, benchmark corpora under `evaluation/`, `output/`, `tmp/`) is intentionally excluded from version control** (see `.gitignore`) as regenerable, non-implementation output — not a product limitation, but relevant to anyone trying to reproduce a specific historical run's exact artifacts from git history alone.

## Deep Verify

**Deep Verify remains entirely separate and unchanged.** `extractor.extract_procurement_package()` (invoked from `app.py`'s `page_new_bid`) is Bid Intelligence's original, governed Stage A→D extraction pipeline. No file in Fast Analysis V4, `analysis_service.py`, the Phase 5 report/application adapters, or any UI work touched in Phases 1–5 imports, calls, or modifies any Deep Verify entry point — enforced by a standing regression test (`test_module_never_imports_deep_verify_entry_points`). Deep Verify is triggered only by its own separate, explicit, synchronous "New Bid" path and was not exercised, touched, or validated as part of this commissioning effort beyond confirming it remains untouched.

---

*This document reflects the repository state at the `bid-intelligence-generic-v1` commissioned-baseline commit. For narrative detail on how this state was reached, see `BID_INTELLIGENCE_PHASE4_GENERALIZATION_REPORT.md`, `BID_INTELLIGENCE_PHASE5_GENERIC_ASSEMBLY_REPORT.md`, and `BID_INTELLIGENCE_GENERIC_ASSEMBLY_RELEASE_NOTES.md`. The earlier, Bank-of-Canada-only baseline remains available at the `bid-intelligence-commissioned-v1` tag.*
