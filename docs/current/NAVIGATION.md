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
- `pages/stage_check.py` — including the PI-2A "Proposal Intelligence"
  surface (Evidence Quality / Commitments & Commercial Exposure / Typed
  Findings), rendered from the same persisted PI result CHECK already
  reloads, never a new model call.
- `analyst.py`'s `analyze_proposal_alignment` / `analyze_proposal_alignment_package`
  / `submission_readiness_check` — the analytical engine itself. Core
  scoring/coverage-classification/mandatory-failure logic is unchanged by
  Proposal Intelligence; PI-2A additively enriched the EXISTING per-chunk
  request/response schema only (no new LLM call, no chunk-count/topology
  change) — see `_align_chunk_prompt`, `_build_proposal_source_ref`,
  `_attach_chunk_provenance`, `_aggregate_proposal_observations`.

**Proposal Intelligence (PI-1, hardened in PI-1.1/PI-1.2, deepened in
PI-2A)** — durable persistence for CHECK's Proposal Alignment output.
PI-2A added structured proposal/procurement provenance (`ProposalSourceRef`
built deterministically from chunk metadata, never the model), an
evidence-strength rating, locally-safe typed findings, and
`proposal_observations` (DELIVERY_COMMITMENT/COMMERCIAL_EXPOSURE) — all as
additive fields on the EXISTING per-chunk analyzer call/schema (zero new
model calls). `analysis_version` is `proposal-intelligence-v2`.
PI-2B (cross-document contradiction, package-wide unsupported-claim
adjudication, Response Guideline coverage, a proposal quality score, win
probability, proposal rewriting) is explicitly deferred, not started.
- `proposal_intelligence.py` — the pure, deterministic adapter: package
  digest over the FULL submitted package, included and excluded alike
  (`compute_package_digest`), the current-alignment-result → PI adapter
  (`adapt_requirement_assessments`/`adapt_findings`/`build_run_payload`/
  `build_failed_run_payload` — both now take explicit `started_at`/
  `completed_at`, captured by the caller around the actual analyzer call,
  never DB-defaulted), the inverse adapter for CHECK reload
  (`reconstruct_legacy_align_result`, `restore_package_manifest_dict` for
  the historical package manifest), and staleness helpers
  (`staleness_reasons`/`is_current`). `PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION`
  is the PI analytical-contract version, not the model name.
- `migrations/015_proposal_intelligence.sql` — the four PI tables
  (**applied and commissioned live**; formal ledger entry
  `20260920205721 proposal_intelligence`; a second ledger-only
  `20260920211025 proposal_intelligence_commissioning` records the
  disposable commissioning assertions and made no lasting schema/data
  changes; do not reapply or alter — PI-2A populates columns this schema
  already had (proposal_source_refs/procurement_source_refs/
  evidence_strength/finding_type/payload), no migration 016 needed),
  each child table tied
  to its parent by a COMPOSITE foreign key against `(id, bid_id)` (never a
  same-table `bid_id` column trusted independently — a run/assessment/
  finding cannot cross-link to another bid's parent row). Two SQL
  functions, service-role-only (anon/authenticated execute revoked):
  `get_or_create_proposal_package_snapshot` (concurrency-safe get-or-
  create via a per-bid advisory lock) and `create_proposal_intelligence_bundle`
  (the run + all its assessments + all its findings in one atomic call —
  never partial). RLS: authenticated SELECT only (transitive
  `can_access_bid`); the write protection is RLS-enabled-plus-no-write-
  policy, not table GRANTs.
- `database.py`'s `get_or_create_proposal_package_snapshot`/
  `create_proposal_intelligence_bundle` (the ONLY write paths — no
  per-table insert functions exist anymore) and `get_latest_proposal_intelligence_run`
  (any status) vs. `get_latest_usable_proposal_intelligence_run`
  (COMPLETE/INCOMPLETE only — a FAILED run never hides prior usable
  intelligence) plus the other `get_*` read functions.
- `tenancy.py`'s `run_proposal_intelligence_for_organization` (auth
  boundary + orchestration; takes `package_files` — the analyzer's
  included-only input — and a separate `full_package_manifest` for the
  durable snapshot) and the `get_*_authenticated` read functions,
  including `get_latest_usable_proposal_intelligence_run_authenticated`
  (what CHECK reload uses) and `get_proposal_package_snapshot_authenticated`
  (restores the historical manifest on reload).
- Tests: `tests/test_proposal_intelligence.py` (adapter),
  `tests/test_proposal_intelligence_pi2a.py` (PI-2A: structured provenance,
  evidence strength, procurement provenance, typed findings, observations,
  incomplete-coverage fail-closed behavior, versioning, legacy reload),
  `tests/test_proposal_intelligence_tenancy.py` (authorization boundary +
  atomic persistence), `tests/test_proposal_intelligence_database.py`
  (RPC-boundary persistence + migration DDL-intent checks).

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
