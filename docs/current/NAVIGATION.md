# Navigation

Where to look, not what everything means. Read
[SYSTEM_STATE.md](SYSTEM_STATE.md) first if you haven't.

## Discovery order for an ordinary task

1. `python scripts/agent_context.py` — branch, HEAD, working-tree status,
   recent commits, migration state, test command.
2. This file's section for the relevant subsystem, below.
3. The task-relevant source and test files it points to.
4. The specific governing architecture doc for that subsystem, **only if**
   the task needs the "why," not just the "how" — see
   [CURRENT_DOCUMENTS.md](CURRENT_DOCUMENTS.md) for exactly which root
   documents may be treated as current authority (most of the former root
   documentation has moved to `docs/archive/` — see below).
5. `docs/archive/` (its own `README.md` explains the structure) — **only
   when the task specifically requires historical evidence** (e.g. "what
   did we decide about X in the Phase 6 report," "reconstruct a past
   acceptance run"). Do not scan it for ordinary orientation.

## By subsystem

**Fast Analysis** (procurement extraction)
- `fast_analysis.py` — the engine itself (routing, extraction, LLM calls,
  `FastAnalysisResult`, `serialize_fast_analysis_result`/`deserialize_fast_analysis_result`).
- `analysis_service.py` — the application-level orchestration boundary
  (lifecycle, persistence, `regenerate_report_from_raw_snapshot`).
- `scripts/fast_analysis_report_adapter.py` — turns a `FastAnalysisResult`
  into report content.
- `migrations/012_fast_analysis_result_snapshot.sql` — the raw-snapshot
  column.
- Tests: `tests/test_fast_analysis_raw_snapshot.py`,
  `tests/test_phoenix_procurement_taxonomy.py`, `tests/test_analysis_service.py`.
- **Telemetry call taxonomy** (`fast_analysis.classify_telemetry_entry`/
  `_is_provider_call`/`_telemetry_audit_summary`, reused by
  `analysis_service._telemetry_summary`) — the precise measurement
  vocabulary for any future live A/B: `provider_calls` (real API calls
  only), `planned_primary_provider_calls`, `planned_focused_provider_calls`,
  `recovery_provider_calls` (split into `truncation_recovery_provider_calls`
  / `targeted_retry_provider_calls`), `non_provider_bookkeeping_rows`,
  `split_exhausted_rows`. The older `recovery_or_retry_calls`/`total_calls`
  fields are kept for backward compatibility but conflate planned focused
  calls and zero-cost bookkeeping rows with genuine recovery — do not use
  them for new measurement work. Tests: `tests/test_telemetry_taxonomy.py`.

**Procurement governance**
- `migrations/010_procurement_revision_governance.sql`,
  `migrations/011_harden_procurement_trigger_functions.sql`.
- `database.py`'s `_guard_canonical_requirement_write`,
  `get_bid_procurement_state`.
- Tests: `tests/test_tenant_rls_enforcement.py`, `tests/test_auth_tenancy.py`.

**Buyer Intelligence**
- Produced/threaded via `scripts/fast_analysis_report_adapter.py`
  (`buyer_intelligence` parameter), consumed in `pages/stage_understand.py`.

**BUILD (Proposal Workspace)**
- `pages/stage_build.py` — the Streamlit page (outline, drafter, Section
  Analyzer UI).
- `analyst.py`'s `draft_proposal_section`.

**Section Analyzer**
- `section_analyzer.py` — context assembly, the bounded model call,
  staleness/idempotency.
- `migrations/013_section_analyzer.sql` — `outline_section_requirements`,
  `section_reviews` (written, **not applied** — see SYSTEM_STATE.md).
- Tests: `tests/test_section_analyzer.py`.
- `tenancy.py`'s `analyze_section_for_organization` and the
  `*_authenticated` mapping/history CRUD functions.

**CHECK / Proposal Alignment**
- `pages/stage_check.py`.
- `analyst.py`'s `analyze_proposal_alignment` / `analyze_proposal_alignment_package`
  / `submission_readiness_check` — the analytical engine itself, unchanged
  by Proposal Intelligence (no new LLM call, no prompt/schema/scoring
  change).

**Proposal Intelligence (PI-1)** — durable persistence for CHECK's
Proposal Alignment output
- `proposal_intelligence.py` — the pure, deterministic adapter: package
  digest (`compute_package_digest`), the current-alignment-result → PI
  adapter (`adapt_requirement_assessments`/`adapt_findings`/
  `build_run_payload`/`build_failed_run_payload`), the inverse adapter for
  CHECK reload (`reconstruct_legacy_align_result`), and staleness helpers
  (`staleness_reasons`/`is_current`). `PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION`
  is the PI analytical-contract version, not the model name.
- `migrations/015_proposal_intelligence.sql` — `proposal_package_snapshots`,
  `proposal_intelligence_runs`, `proposal_requirement_assessments`,
  `proposal_intelligence_findings` (written, **not applied** — see
  SYSTEM_STATE.md). RLS: authenticated SELECT only (transitive
  `can_access_bid`), no authenticated INSERT/UPDATE/DELETE policy —
  writes are service-role only, reached exclusively through
  `tenancy.run_proposal_intelligence_for_organization`.
- `database.py`'s `create_proposal_package_snapshot`/
  `create_proposal_intelligence_run`/`create_proposal_requirement_assessments`/
  `create_proposal_intelligence_findings` (privileged, insert-only — no
  update/delete function exists on purpose) and their `get_*` counterparts.
- `tenancy.py`'s `run_proposal_intelligence_for_organization` (the
  authorization boundary + orchestration: `require_bid_access` first, then
  package-snapshot identity, the existing analyzer, the PI-1 adapter, then
  persistence) and the `get_*_authenticated` read functions CHECK uses on
  page reload.
- Tests: `tests/test_proposal_intelligence.py` (adapter),
  `tests/test_proposal_intelligence_tenancy.py` (authorization boundary),
  `tests/test_proposal_intelligence_database.py` (persistence helpers).

**Tenancy / RLS / auth boundary**
- `tenancy.py` — every `*_for_organization` (service-role, ownership-checked)
  and `*_authenticated` (user's own RLS-scoped client) function.
- `auth_client.py`, `auth_session.py`.
- `migrations/007_auth_tenancy_foundation.sql`,
  `migrations/008_tenant_rls_policy_enforcement.sql`.

**Database / migrations**
- `database.py` — every CRUD function, all going through `get_client()`
  (service-role) unless noted.
- `migrations/` — read the **highest-numbered file** for current schema
  intent; do not assume it's applied (see SYSTEM_STATE.md).

## Standing rules for this repo

- Do not scan `docs/archive/` (historical operational records, engagement
  history, superseded versions, proposed/not-yet-implemented designs)
  during ordinary task orientation. See [CURRENT_DOCUMENTS.md](CURRENT_DOCUMENTS.md)
  for what root documentation remains and may be treated as current.
- A filename alone (even one containing "ARCHITECTURE") is not a reliable
  currentness signal in this repo — several self-declare `Status:
  Proposed`. Check `docs/current/DOCUMENT_AUTHORITY_MAP.json` or a
  document's own metadata table when in doubt.
- A written migration file is not a live database change. Check explicitly
  before assuming one is applied.
- Full constitutional reading (`MANIFESTO.md` → `GOVERNANCE.md` →
  `ANTI_GOALS.md` → `AGENT.md`) is for proposing/reviewing/implementing
  product-philosophy-level work, not for an ordinary bounded bug fix or
  test addition — use judgment, don't default to reading all four for
  every task.
