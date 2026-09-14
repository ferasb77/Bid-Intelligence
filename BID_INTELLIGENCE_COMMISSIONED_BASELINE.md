# Bid Intelligence — Commissioned Baseline

**Commissioned date:** 2026-09-14 (UTC)
**Status:** Live-commissioned. Product Integration Phases 1–3 complete, accepted, and hardened. Post-commissioning data-integrity fix applied. This document freezes that state as the reproducible commissioned baseline.

---

## What is commissioned

Fast Analysis V4 is the default, integrated analysis path of the Bid Intelligence application — reachable through the real product UI (Bid → UNDERSTAND stage → ⚡ Fast Analysis panel), backed by durable Supabase persistence, with live, truthful progress reporting while a run is active and a full structured-intelligence view once it completes.

| Component | Version / identifier |
|---|---|
| Fast Analysis engine | `fast-analysis-v4` |
| `MAX_DOCUMENT_CONCURRENCY` | 2 (frozen) |
| Application service boundary | `analysis_service.py` |
| Supabase migrations live | **004** (`analysis_runs`, `analysis_results`, RLS enabled) and **005** (`analysis_runs.progress` JSONB column) |
| UI entry point | `pages/stage_understand.py` (`page_understand()` → `_render_fast_analysis_panel()`) |

## Latest test result

**1464 passed, 2 skipped** (full repository suite, `pytest -q`), `py_compile` clean, `git diff --check` clean. The 2 skips are pre-existing, live-API-gated tests unrelated to this baseline (unchanged since Phase 1). Zero failures.

## Live commissioning result

One authorized live Fast Analysis run (Phase 3), started via the actual UI button, not a script:

- Bid: Bank of Canada, RFP 2026-026 (bid_id 8) · Run ID 1 · engine `fast-analysis-v4`
- 199.05s wall time · 22 LLM calls (11 recovery/retry) · 56,673 input / 51,265 output tokens
- Result: **COMPLETE**, structured intelligence persisted, `bid_briefs` projected correctly, 15-page PDF generated and downloadable, report regeneration proven to make zero extraction calls
- Full detail: `BID_INTELLIGENCE_PRODUCT_INTEGRATION_PHASE3_COMMISSIONING_REPORT.md`

## Authoritative Bank of Canada source-truth evaluation count

**20 total evaluation criteria (7 + 7 + 6)**, verified both as the accepted source-truth baseline (`BANK_OF_CANADA_SOURCE_TRUTH_REPORT_BASELINE.json`) and as an exact match against the Phase 3 live run's actual output:

- Category 1 (Learning & Development, Form D1): 7 criteria, 75 points
- Category 2 (HR Advisory, Form D2): 7 criteria, 75 points — includes "Value-add" and "Relevant Experience and References" (the two criteria the original Deep-derived report undercounted)
- Category 3 (Facilitation & Team Effectiveness, Form D3): 6 criteria, 100 points (incl. Price)

Ambiguity states: `evaluation_weight_conflict` = NOT_PRESENT (retired as a false positive from scope conflation); `pricing_stage_ambiguity` = PRESENT; `category_date_distinction` = PRESENT as a scoped, category-specific difference. The historical "18 primary weights" gate is retired in favor of this 20-item, source-verified count.

## Supabase migrations now live

- **004** (`migrations/004_analysis_runs.sql`) — `analysis_runs` and `analysis_results` tables, RLS enabled (no policies defined yet, by deliberate design), duplicate-active-run partial unique index.
- **005** (`migrations/005_analysis_run_progress.sql`) — additive `analysis_runs.progress` JSONB column (milestones + early facts for live progress reporting).

Both applied and independently re-verified against the live database. Migrations 001–003 predate this engagement and are unchanged.

## Current known limitations

1. **`app.py`'s `page_bid_overview()` remains unreachable dead code.** The Phase 3 fix relocated the Fast Analysis panel into `pages/stage_understand.py` (the page the router actually calls); `page_bid_overview()` itself — readiness-metric cards, its own RFP-upload section — was left as-is, still unreachable, since wiring or removing it was outside the scope of the specific defect being fixed.
2. **Fast Analysis V4's document routing is filename-identity-dependent.** `fast_analysis.py`'s `DOCUMENT_ROUTING` table is keyed on the exact historical Bank of Canada corpus filenames (including subdirectory prefixes like `OriginalRevision/...`). A document uploaded through a real browser file picker (which never preserves folder paths) for any file other than the master RFP falls back to the broadest safe extraction mode rather than its narrow, optimized route — functionally complete, but not the same call profile as the commissioned benchmark. Only the master RFP's filename is genuinely upload-path-independent.
3. **"View Source" for opportunity-snapshot/date facts requires a run committed after the Phase 3 fix.** The underlying `raw_date_observations` field was added to `fast_analysis_app_adapter.py` during Phase 3; the already-completed live commissioning run (run_id 1) predates it, so that specific run's persisted UI shows no date-level source expanders even though evaluation and pricing ones work. Any new run has full coverage.
4. **`database.update_bid()`'s fix is Bid Intelligence-specific and narrow.** It now does a true partial update (only writes keys present in the caller's dict). No other `database.py` update function was audited or changed as part of this fix; if a similar pattern exists elsewhere it has not been verified.
5. **Progress-tracking milestones can arrive in a non-obvious order.** Because Fast Analysis V4 dispatches document tasks concurrently, the live commissioning run showed identity/date facts arriving in the last ~15% of wall time rather than early — expected and documented behavior, not a defect, but worth knowing when interpreting a run's live progress panel.
6. **Live-run evidence (PDFs, telemetry, benchmark corpora under `evaluation/`, `output/`, `tmp/`) is intentionally excluded from version control** (see `.gitignore`) as regenerable, non-implementation output — not a product limitation, but relevant to anyone trying to reproduce a specific historical run's exact artifacts from git history alone.

## Deep Verify

**Deep Verify remains entirely separate and unchanged.** `extractor.extract_procurement_package()` (invoked from `app.py`'s `page_new_bid`) is Bid Intelligence's original, governed Stage A→D extraction pipeline. No file in Fast Analysis V4, `analysis_service.py`, or any Phase 1–3 UI work imports, calls, or modifies any Deep Verify entry point — enforced by a standing regression test (`test_module_never_imports_deep_verify_entry_points`). Deep Verify is triggered only by its own separate, explicit, synchronous "New Bid" path and was not exercised, touched, or validated as part of this commissioning effort beyond confirming it remains untouched.

---

*This document reflects the repository state at the commissioned-baseline commit. For narrative detail on how this state was reached, see the phase reports referenced above and `FAST_ANALYSIS_V4_SOURCE_TRUTH_RECONCILIATION.md`.*
