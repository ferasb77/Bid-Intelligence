# Fast Analysis — Product Integration Phase 1 — Implementation Report

**Verdict: PRODUCT INTEGRATION PHASE 1: PASS.** Fast Analysis V4 (frozen, unmodified) is now
callable through the real application, as a background-executed, durable, default analysis mode,
with structured results and source traceability persisted independently of any single PDF render,
zero live-request blocking, database-level duplicate-run protection, and Deep Verify left
completely untouched as a separate, explicit, synchronous path. Full test suite green
(1,403 passed, 2 skipped — up from the 1,364 pre-Phase-1 baseline by exactly the 39 new tests
added).

## 1. Existing application architecture (discovered, not assumed)

This is a **Streamlit app backed by Supabase** (Postgres + Storage bucket `bid-documents`),
**single-tenant with no user authentication** (RLS disabled on every table by explicit design —
`supabase_schema.sql`'s own comment: `-- RLS: disable for now (single-tenant app with API key
auth)`). There is **no background-job infrastructure of any kind** — no Celery/RQ/APScheduler/cron;
every page runs synchronously inside one Streamlit request.

- **Central domain object:** `bids` (not "opportunities") — this repo's existing name for a
  procurement pursuit. Phase 1 does not introduce a competing concept; `AnalysisRun.opportunity_id`
  from the design brief maps to `analysis_runs.bid_id`.
- **Existing structured-intelligence table:** `bid_briefs` (1:1 with `bids`, `migrations/002`),
  already holding fields that map closely to Fast Analysis's own report sections
  (`executive_summary`, `procurement_model`, `contract_term`, `scope_categories`,
  `qualification_gates`, `evaluation_breakdown`, `commercial_structure`, `contract_risks`,
  `submission_requirements`, `key_dates`, `source_citations`, `document_conflicts`). Already
  rendered, unchanged, by `pages/stage_understand.py` (the UNDERSTAND stage / Bid Brief page) —
  no regenerate button exists there today.
- **Existing ingestion path (`app.py:page_new_bid`)**: uploads a whole procurement package and
  calls `extractor.extract_procurement_package()` **synchronously**, which itself already runs
  the full governed Stage A→B→C→D pipeline (`extract_document_facts` per document, then
  normalize/reconcile/synthesize) — this **is** architecturally Deep Verify, just without that
  label in the UI. Phase 1 does not touch this call path at all.
- `opportunity_orchestration.py` and the rest of the Canonical-Opportunity/Opportunity-Intelligence
  machinery are **not wired into the live app anywhere** — only `scripts/commission_*` and tests
  reference them.
- `fast_analysis.py` had **zero references** anywhere in `app.py`/`pages/*.py`/`pages_extra.py`
  before this package.
- `documents` table already tracks per-bid file storage (`storage_path` in the `bid-documents`
  bucket) with a `doc_type` of `"RFP / Source"` for the relevant corpus, plus `version` for
  replace/re-upload tracking.
- `refactor/streamlined-bid-workflow` is fully merged into `main`; the current working branch
  (`feature/evidence-explainability`) is well past that, at the Bank of Canada commissioning
  baseline freeze.

## 2. Integration points used

| Concern | Reused existing mechanism |
|---|---|
| Opportunity/bid identity | `bids` table (unchanged) |
| Document corpus | `documents` table, `doc_type = "RFP / Source"`, existing `storage_path` in bucket `bid-documents` (unchanged) |
| API key | `config.get_api_key()` (unchanged) |
| Structured intelligence view | `bid_briefs` table + `pages/stage_understand.py` (unchanged — see S6) |
| File storage for the new report PDF | Same `bid-documents` bucket, new path convention `{bid_id}/analysis_reports/{run_id}.pdf` |
| UI entry point | `app.py:page_bid_overview` — one new panel, no new page, no navigation change |

## 3. Data model changes

One new migration, **additive only**, touches no existing table's data:

**`migrations/004_analysis_runs.sql`** — two new tables:

- **`analysis_runs`**: `bid_id` (FK), `analysis_mode` (`'FAST'` / `'DEEP_VERIFY'`),
  `engine_version`, `status` (6-state lifecycle, see S4), timestamps, `failure_reason` /
  `failure_detail` (JSONB), `corpus_document_ids` (JSONB snapshot) / `corpus_digest`,
  `telemetry` (JSONB), `report_storage_path`.
  - **Duplicate-run protection is database-native**, not just app-level:
    `create unique index idx_analysis_runs_one_active on analysis_runs (bid_id, analysis_mode)
    where status not in ('COMPLETE','FAILED')`. At most one non-terminal run per (bid, mode) can
    exist at the Postgres level — safe against double-click, browser refresh, network retry, or
    concurrent requests, not just a `st.session_state` flag.
- **`analysis_results`**: `run_id` (FK, unique), `bid_id` (denormalized for query convenience),
  `structured_intelligence` (JSONB — the full OpportunityIntelligence contract, S5),
  `fact_origins` (JSONB), `report_content_snapshot` (JSONB — see S7 for why this exists
  separately).

RLS left disabled on both, consistent with every other table (S1). **Per this repo's own existing
convention** (`database.py`'s `init_db()` docstring; `migrations/003`'s own header), this file is
**not auto-applied by any code path** — it must be run manually via the Supabase SQL editor, the
same way 001-003 were. Existing rows in every table are untouched; the app remains fully usable
before this migration is applied (instruction 30) — `analysis_service.py` and the new UI panel
simply won't have anywhere to write until it is.

## 4. Analysis run lifecycle

`QUEUED → PREPARING → ANALYZING → ASSEMBLING → COMPLETE` or `→ FAILED` at any point (enforced by a
Postgres `check` constraint on `analysis_runs.status`). No existing app-wide status enum was found
to reuse (`STATUSES` in `components/ui.py` is for the user-facing requirements/tasks Kanban
vocabulary — Not Started/In Progress/Blocked/Complete — a different concept); this lifecycle is
new but scoped narrowly to `analysis_runs` alone, not proposed as a replacement for anything.

## 5. Application-facing contract (`fast_analysis_app_adapter.py`)

`build_opportunity_intelligence(result)` produces the full, durable, JSON-serializable structured
contract (`analysis_results.structured_intelligence`): `opportunity_snapshot`, `procurement_scope`,
`dates_and_mechanics`, `evaluation` (including `raw_occurrences` with full `source_refs` — S9),
`response_requirements`, `pricing_and_commercial`, `ambiguities`, `bid_team_attention_points`,
`source_map`, `buyer_intelligence`, and `fact_origins`. This is independent of any one rendering —
future progressive-UI work (Phase 2) reads this, never the PDF.

This module contains **zero extraction logic and makes zero API calls** — it is a pure,
deterministic mapping over `scripts/fast_analysis_report_adapter.py`'s already-frozen,
already-tested `build_fast_report_content()` output, itself unmodified.

## 6. Report generation and the existing Bid Brief view (no UI redesign)

`build_bid_brief_projection(result)` is a second, separate deterministic mapping into the **existing**
`bid_briefs` row shape — matched field-for-field against what `pages/stage_understand.py` actually
reads (`_ensure_list`/`_ensure_dict` calls, `evaluation_hierarchy.build_evaluation_hierarchy()`'s
`stage`/`parent_stage`/`weight` keys, `_evidence_label()`'s `source_refs` expectations, and
`document_conflicts`' `source_a`/`source_b`/`classification`/`assessment` shape). On a COMPLETE run,
`analysis_service._execute_fast_analysis_run` upserts this projection via the existing
`database.upsert_bid_brief()` — **`pages/stage_understand.py` needed zero code changes** to display
Fast Analysis's output; it already reads from `bid_briefs`, which now gets populated by a new
source.

A genuine finding of the mapping exercise: `bid_briefs.evaluation_breakdown`'s consumer
(`evaluation_hierarchy.build_evaluation_hierarchy`) groups rows by shared `parent_stage` into a
derived container — this is expected to render correctly but has not been visually verified against
a live Streamlit render (would require a running app + browser session, out of this package's "no
UI redesign, no new live LLM calls" scope); flagged as a Phase 2 verification item, not a known
defect.

## 7. Report regeneration without extraction

`analysis_service.regenerate_report(run_id)` rebuilds the PDF from **only**
`analysis_results.report_content_snapshot`, never calling `run_fast_analysis_corpus` or any
extraction path. This snapshot is a dict-ified copy of the exact `SimpleNamespace` the PDF
renderer consumes (`vars(content)`), persisted alongside — not the summarized
`structured_intelligence`, deliberately, because the summarized contract loses information
(e.g. the exact `_type`-tagged ambiguity list, exact rendered prose) that would make faithful PDF
reconstruction from it lossy or require re-deriving through the report adapter a second time.
**Verified end-to-end** (round-trip: build → JSON-serialize → JSON-deserialize → render → confirm
valid `%PDF` bytes) with a real `FastAnalysisResult`/`build_fast_report_content()` call and no
mocking of the adapter itself — see `tests/test_analysis_service.py::TestReportRegeneration`.

## 8. Service boundary (`analysis_service.py`)

The **one** entry point UI/API code uses: `start_fast_analysis(bid_id, api_key)`,
`regenerate_report(run_id)`, plus the `database.py` read helpers
(`get_latest_analysis_run`/`get_analysis_run`/`list_analysis_runs`). Nothing outside
`fast_analysis.py` and `scripts/fast_analysis_report_adapter.py` knows about routes, prompts,
chunking, focused tasks, or ambiguity-detection internals — `app.py`'s new panel calls only
`analysis_service.start_fast_analysis()` / reads only `analysis_runs` rows.

**Background execution mechanism**: an in-process **daemon thread** (`threading.Thread`), started
from inside the Streamlit request that clicked "Run Fast Analysis," writing status transitions to
`analysis_runs` as it progresses. This repository has zero existing job-queue infrastructure
(confirmed by direct inspection, S1); a heavyweight platform (Celery/Redis/RQ) was explicitly not
introduced per instruction 6's own guidance. This is safe for Streamlit's actual deployment model
(one long-lived process per app instance, not one process per request — confirmed via
`database.py`'s own comment about persisting "across Streamlit Cloud redeploys"), and reuses the
exact same threading pattern `fast_analysis.py`'s own `run_fast_analysis_corpus()` already uses one
level down for concurrent document calls.

**Known limitation, stated plainly**: this mechanism is **not resilient to a process
restart** while a run is in-flight — if the Streamlit process is killed or redeployed mid-run, that
run's row is left in a non-terminal status with no thread left to finish it. No auto-recovery for
this was built in Phase 1 (would require a reconciliation sweep on app startup, or a real job
queue); a stuck run is currently only resolvable by the user manually observing it and (once a
Phase 2 addition provides it) an admin/force-fail action. This is disclosed here rather than
glossed over, per this whole engagement's established practice.

## 9. Source traceability and fact origin (preserved, not flattened)

`opportunity_intelligence["evaluation"]["raw_occurrences"]` and
`["pricing_and_commercial"]["raw_pricing_occurrences"]` retain each fact's `source_refs` exactly
as the engine produced them (verified: `tests/test_fast_analysis_app_adapter.py::
test_evaluation_raw_occurrences_retain_source_refs`). `fact_origins`
(`LIVE_FAST_LLM`/`DETERMINISTIC_FAST_EXTRACTION`/`BUYER_INTELLIGENCE_EXTERNAL_LAYER`/
`SAFETY_NET_FALLBACK`) is persisted both on `analysis_results.fact_origins` and inside the
structured contract itself — not exposed in the client-facing PDF, retained for diagnostics and a
future Deep Verify reconciliation, per instruction 13.

## 10. Failure and retry behavior

Every exception inside `_execute_fast_analysis_run` is caught and persisted as `FAILED` with
`failure_reason` (truncated message) and `failure_detail` (a bounded traceback) — a run can never
be left stuck in a non-terminal state, and a failure never produces a misleadingly-`COMPLETE` run
from partial data (`create_analysis_result`/`upsert_bid_brief` are only reached after the engine
call succeeds). Verified for: engine exception, missing `storage_path`, and storage-download
failure — all reach `FAILED`, none reach `COMPLETE`.

Application-level retry is the user clicking "Retry Fast Analysis" after a `FAILED` run — a
**new, distinct, deliberate** `analysis_runs` row, never an automatic loop; Fast Analysis's own
internal bounded recovery (split-on-truncation, targeted retry — both inside `fast_analysis.py`,
untouched) remains entirely separate and is not re-exposed at the application layer.

## 11. Fast/Deep separation

`analysis_service.py` never imports or calls `extractor.extract_procurement_package`,
`extract_document_facts`, `extract_rfp`, or anything from `opportunity_orchestration.py` — enforced
by a regression test checking the module's actual bound names, not just its prose
(`tests/test_analysis_service.py::test_module_never_imports_deep_verify_entry_points`). The
existing `page_new_bid` synchronous ingestion flow (which already **is** Deep Verify,
architecturally) is completely untouched — still there, still synchronous, still opt-in via its
own explicit upload-and-analyze action. Fast Analysis is additive, not a replacement of that path
in this phase; making it the ingestion default (vs. the current bid-overview-panel placement) is a
Phase 2 UX decision, not made here.

## 12. Tenancy / access control

**This application has no user-level authentication or multi-tenant model at all** (confirmed by
direct inspection: no `streamlit-authenticator`, no Supabase auth usage, RLS disabled everywhere,
no `user_id`/`organization_id`/`tenant_id` column anywhere in the schema). The only scoping
boundary that exists anywhere in this app is `bid_id`, applied consistently to every table. Phase 1
does not weaken this and does not invent a stronger boundary that doesn't exist elsewhere in the
app — `analysis_runs`/`analysis_results` are `bid_id`-scoped exactly like every other table, and
`analysis_service.start_fast_analysis()` is tested to always query documents and active runs
scoped to the given `bid_id` (`tests/test_analysis_service.py::
test_start_queries_documents_scoped_to_the_given_bid_id`). If/when real multi-tenant auth is added
to this application (out of scope here), `analysis_runs`/`analysis_results` will need the same
`organization_id`/RLS treatment as every other table at that time — no special exemption was
created.

## 13. Telemetry and cost

`_telemetry_summary()` persists `engine_version`, `wall_seconds`, `total_calls`,
`recovery_or_retry_calls`, `input_tokens`, `output_tokens`, `documents_skipped`,
`documents_batched` — never exposed in the client-facing PDF. No dollar cost figure is persisted;
the current Anthropic API response objects this codebase reads do not expose reliable per-call
cost, so a `cost_note` field states that explicitly rather than inventing one (instruction 23,
verified by test).

## 14. Tests

39 new deterministic tests, zero live API calls, zero live Supabase connection (every
`database.py` call and the engine call itself mocked):

- `tests/test_fast_analysis_app_adapter.py` (15): structured-contract shape, source-ref/fact-origin
  retention, JSON-serializability, `bid_briefs` field-shape matching, ambiguity→document_conflicts
  mapping (including the "no false conflict when none was detected" regression), generic
  (non-hardcoded) opportunity-type handling.
- `tests/test_analysis_service.py` (24): run creation + corpus association, duplicate-start
  protection (both the pre-check and the DB-race path), full lifecycle success (with the exact
  `PREPARING→ANALYZING→ASSEMBLING→COMPLETE` status sequence asserted), structured-result +
  fact-origin persistence, `bid_briefs` upsert on completion, telemetry shape / no invented cost,
  three distinct failure modes (engine exception, missing storage path, download failure) all
  reaching `FAILED` and never `COMPLETE`, no partial-result persistence on failure, report
  regeneration making zero engine calls (verified with a real, unmocked adapter call), corpus-digest
  determinism (order-independence, version-sensitivity), Fast/Deep import separation, and
  frozen `MAX_DOCUMENT_CONCURRENCY == 2`.

## 15. Regression gates

- New integration tests: 39/39 passed.
- Existing Fast Analysis tests (`test_fast_analysis*.py`, v1-v4): unmodified, all green.
- Deep Verify tests: unmodified, all green (no file under Deep Verify's ownership was touched).
- `py_compile` on every changed/new file: clean.
- `git diff --check`: clean.
- Full repository suite: **1,403 passed, 2 skipped** (pre-Phase-1 baseline: 1,364 — the +39 is
  exactly the new test count, net zero regressions).
- **Build**: this is a pure-Python Streamlit app with no separate build step (no bundler/transpiler
  config found) — `py_compile` succeeding on every file is the applicable equivalent.
- **Lint**: no lint tool is configured anywhere in this repository (no `ruff`/`flake8`/`pylint`
  config, no `pyproject.toml`/`setup.cfg`) — there is no existing standard to run against.

## 16. Files changed

| File | Change |
|---|---|
| `migrations/004_analysis_runs.sql` | New — `analysis_runs`, `analysis_results` tables |
| `analysis_service.py` | New — the service boundary |
| `fast_analysis_app_adapter.py` | New — structured contract + `bid_briefs` projection |
| `tests/test_analysis_service.py` | New — 24 tests |
| `tests/test_fast_analysis_app_adapter.py` | New — 15 tests |
| `database.py` | Additive — analysis-run/result CRUD helpers, report-PDF upload helper |
| `app.py` | Additive — one new panel (`_render_fast_analysis_panel`) wired into `page_bid_overview`; no navigation, no page, no existing function's behavior changed |

**No changes to**: `fast_analysis.py`, `scripts/fast_analysis_report_adapter.py`,
`scripts/build_boc_bid_intelligence_preview_pdf.py`, `extractor.py`, any Stage B/C/Canonical
Opportunity/`opportunity_orchestration.py` file, any `pages/*.py` file, `pages_extra.py`,
`components/ui.py`, `brand.py`, `pdf_export.py`, `pdf_styles.py`.

## 17. Known limitations / Phase 2 work

1. In-process background thread is not resilient to a process restart mid-run (S8) — no stuck-run
   reconciliation sweep exists yet.
2. `evaluation_hierarchy.build_evaluation_hierarchy()`'s grouping of the projected
   `evaluation_breakdown` has not been visually verified in a live browser session (S6).
3. The shared PDF renderer module is still named/located at
   `scripts/build_boc_bid_intelligence_preview_pdf.py` — a naming artifact of the pilot engagement.
   Its `build()` function is fully generic (content-parameterized) already; only the module's own
   name/path is BoC-specific. A rename/relocation is a safe, no-behavior-change cleanup item,
   deliberately not done here (out of this package's scope).
4. No progressive, section-by-section UI (explicitly deferred to Phase 2 per instruction 25) — the
   current panel is a single status line + action button.
5. `page_new_bid`'s ingestion flow still defaults to the old synchronous Deep-Verify-equivalent
   extraction; making Fast Analysis the ingestion-time default (rather than only available from the
   bid-overview panel after a bid already exists) is a UX decision for Phase 2, not made here.
6. No stuck/stale-run admin action (e.g. force-fail a run stuck in ANALYZING past a time bound) —
   related to limitation 1.
7. Deep Verify → Fast Analysis reconciliation (comparing/merging results once both have run for the
   same bid) is explicitly out of scope per instruction 18 and not attempted.
