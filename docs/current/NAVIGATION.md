# Navigation

Where to look, not what everything means. Read
[SYSTEM_STATE.md](SYSTEM_STATE.md) first if you haven't.

## Discovery order for an ordinary task

1. `python scripts/agent_context.py` — branch, HEAD, working-tree status,
   recent commits, migration state, test command.
2. This file's section for the relevant subsystem, below.
3. The task-relevant source and test files it points to.
4. The specific governing architecture doc for that subsystem, **only if**
   the task needs the "why," not just the "how."
5. Historical reports (root `.md` files, `docs/current/ROOT_DOC_INVENTORY.json`)
   — **only when the task specifically requires historical evidence** (e.g.
   "what did we decide about X in the Phase 6 report," "reconstruct a past
   acceptance run"). Do not scan them for ordinary orientation.

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
  / `submission_readiness_check`.

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

- Do not scan root historical reports (`*_REPORT.md`, `*_AUDIT.md`,
  `*_COMMISSIONING_REPORT.md`, `BANK_OF_CANADA_*`, etc.) during ordinary
  task orientation.
- A written migration file is not a live database change. Check explicitly
  before assuming one is applied.
- Full constitutional reading (`MANIFESTO.md` → `GOVERNANCE.md` →
  `ANTI_GOALS.md` → `AGENT.md`) is for proposing/reviewing/implementing
  product-philosophy-level work, not for an ordinary bounded bug fix or
  test addition — use judgment, don't default to reading all four for
  every task.
