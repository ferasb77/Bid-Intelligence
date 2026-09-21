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
  Findings / **Whole-Package Consistency** — PI-2B1), rendered from the
  same persisted PI result CHECK already reloads, never a new model call.
- `analyst.py`'s `analyze_proposal_alignment` / `analyze_proposal_alignment_package`
  / `submission_readiness_check` — the analytical engine itself. Core
  scoring/coverage-classification/mandatory-failure logic is unchanged by
  Proposal Intelligence; PI-2A additively enriched the EXISTING per-chunk
  request/response schema only (no new LLM call, no chunk-count/topology
  change) — see `_align_chunk_prompt`, `_build_proposal_source_ref`,
  `_attach_chunk_provenance`, `_aggregate_proposal_observations`. PI-2B1
  adds the `proposal_claims` field to that SAME per-chunk schema
  (`_aggregate_proposal_claims` for the deterministic package-wide claim
  ledger) plus one entirely new, bounded, whole-package call:
  `analyze_proposal_package_intelligence` →
  `_build_package_intelligence_ledger` (compact claims/requirement-
  evidence/observations/deficiencies + a `P#`/`C#` short-id source
  registry — the ONLY thing sent to the model, never raw proposal text)
  → `package_ledger_digest` → `_package_reasoning_prompt` →
  `_call_package_reasoning` (the one new provider call site) →
  `_reconcile_package_findings` (fail-closed validation: unknown claim/
  source id, bad finding_type/severity, or a non-ledger-verbatim req_id
  rejects that finding only; UNSUPPORTED_CLAIM is structurally rejected
  whenever local coverage is incomplete, regardless of model output).
  PI-2B2 adds Response Guideline coverage + evaluator usability into the
  SAME ledger/call (no second call): `_build_package_intelligence_ledger`
  now also accepts `response_guidelines` (threaded in by `tenancy.py` from
  `section_analyzer.procurement_basis(bid_id)`'s raw Fast Analysis
  snapshot — `FastAnalysisResult.deterministic_response_guidelines`, the
  ONLY existing source; never fabricated), producing a `G#`-id
  `response_guidelines` ledger section (also prunable under the same 60KB
  budget) → `_reconcile_guideline_assessments` (fail-closed: ANSWERED/
  PARTIAL rejected without validated claim/source/observation provenance;
  NOT_ANSWERED downgraded, not rejected, to CANNOT_ASSESS whenever
  coverage_complete/ledger_complete is false and no positive evidence is
  cited).

**Proposal Intelligence (PI-1, hardened in PI-1.1/PI-1.2, deepened in
PI-2A/PI-2A.1, extended in PI-2B1)** — durable persistence for CHECK's
Proposal Alignment output. PI-2A added structured proposal/procurement
provenance (`ProposalSourceRef` built deterministically from chunk
metadata, never the model), an evidence-strength rating, locally-safe
typed findings, and `proposal_observations` (DELIVERY_COMMITMENT/
COMMERCIAL_EXPOSURE) — all as additive fields on the EXISTING per-chunk
analyzer call/schema (zero new model calls).
PI-2B1 (**implemented, NOT live-provider commissioned** — every real call
site is exercised only against mocked/frozen responses in tests) adds
whole-package claim/contradiction/consistency reasoning: `proposal_claims`
on the per-chunk schema, a deterministic `proposal_claim_ledger`, a
compact short-ID package ledger, and exactly ONE new bounded whole-package
model call producing CONTRADICTION/INTERNAL_INCONSISTENCY/UNSUPPORTED_CLAIM
findings — persisted into the SAME `proposal_intelligence_findings` table
(those finding_types already existed in migration 015's enum; no new
migration) tagged `payload.scope = "package"` (a PI-2A/local finding is
now tagged `payload.scope = "local"`, for the same reason).
PI-2B2 (**implemented, NOT live-provider commissioned**, same mocked-only
status as PI-2B1) adds Response Guideline coverage / evaluator usability
to that SAME package-reasoning call (no second model call):
`proposal_intelligence.adapt_guideline_assessments` maps `analyze_
proposal_package_intelligence`'s already-reconciled `guideline_
assessments` into finding rows in the SAME `proposal_intelligence_findings`
table — a genuine NOT_ANSWERED gap uses the EXISTING `RESPONSE_GUIDELINE_
GAP` finding type (already in migration 015's taxonomy from PI-1), every
other status (ANSWERED/PARTIAL/CANNOT_ASSESS) uses `FINDING_TYPE_OTHER`,
both tagged `payload.kind = "guideline_assessment"` (distinguishing them
from local/package findings the same way `payload.scope` already does).
`reconstruct_legacy_align_result` splits these out into their own
`guideline_assessments` list, rendered by `pages/stage_check.py`'s
"Response Guideline / Evaluator Usability" area — hidden when empty, no
score shown, purely from persisted rows on reload. `analysis_version` is
now `proposal-intelligence-v4`. A proposal quality score, win probability,
and proposal rewriting remain explicitly out of scope for the whole PI-2
program. Organizational Memory (a later, unrelated phase) is explicitly
deferred, not started.
- `proposal_intelligence.py` — the pure, deterministic adapter: package
  digest over the FULL submitted package, included and excluded alike
  (`compute_package_digest`), the current-alignment-result → PI adapter
  (`adapt_requirement_assessments`/`adapt_findings`/`build_run_payload`/
  `build_failed_run_payload` — both now take explicit `started_at`/
  `completed_at`, captured by the caller around the actual analyzer call,
  never DB-defaulted), the PI-2B1 whole-package finding adapter
  (`adapt_package_findings` — maps `analyze_proposal_package_intelligence`'s
  already-reconciled output into finding rows, `payload.scope = "package"`,
  requirement linking via the SAME `_requirement_id_lookup` every other
  adapter uses), the inverse adapter for CHECK reload
  (`reconstruct_legacy_align_result`, `restore_package_manifest_dict` for
  the historical package manifest — now also splits `package_findings` out
  from local `findings` by `payload.scope`), and staleness helpers
  (`staleness_reasons`/`is_current`). `PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION`
  is the PI analytical-contract version, not the model name.
- `migrations/015_proposal_intelligence.sql` — the four PI tables
  (**applied and commissioned live**; formal ledger entry
  `20260920205721 proposal_intelligence`; a second ledger-only
  `20260920211025 proposal_intelligence_commissioning` records the
  disposable commissioning assertions and made no lasting schema/data
  changes; do not reapply or alter — PI-2A populates columns this schema
  already had (proposal_source_refs/procurement_source_refs/
  evidence_strength/finding_type/payload), no migration 016 needed; PI-2B1
  reuses the SAME columns again — its package-reasoning status/ledger
  digest metadata rides inside the existing `coverage_metadata` jsonb
  column on the run, and its CONTRADICTION/INTERNAL_INCONSISTENCY/
  UNSUPPORTED_CLAIM finding rows use finding_type values already in this
  table's check constraint — no migration 016 needed for PI-2B1 either),
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
  `tests/test_proposal_intelligence_pi2b1.py` (PI-2B1: claim schema/
  provenance/aggregation, ledger determinism/digest/byte-budget
  prioritization, package-finding fail-closed reconciliation, contradiction/
  inconsistency/unsupported-claim standards including the incomplete-
  coverage structural rejection, package-call failure behavior, persistence
  mapping, scope separation on reload, call-count, version bump),
  `tests/test_proposal_intelligence_pi2b2.py` (PI-2B2: guideline ledger
  extraction/basis, positive-coverage provenance requirement, incomplete-
  coverage fail-closed downgrade, evidence provenance validation,
  evaluator-traceability, persistence/reload, historical compatibility,
  unchanged one-call topology, version bump/staleness),
  `tests/test_proposal_intelligence_tenancy.py` (authorization boundary +
  atomic persistence), `tests/test_proposal_intelligence_database.py`
  (RPC-boundary persistence + migration DDL-intent checks).

**Organizational Memory (OM-1)**
- `organizational_memory.py` — the retrieval contract module: `MemoryClass`
  (SOURCE_MEMORY/APPROVED_FIRM_KNOWLEDGE/PROPOSAL_MEMORY),
  `OrganizationalMemoryItem` (structural approval-coupling + exact-source-
  identity validation in `__post_init__`), `SourceProvenance` (mirrors
  `analyst._build_proposal_source_ref`'s file_id/content_hash/filename/
  package_path/locator fields), and `retrieve()` (deterministic,
  organization-scoped, class/trust-filtered, `top_k`-bounded ranking; an
  optional `embed_fn` — matching `embeddings.embed_query` — enables
  cosine-similarity ranking, degrading to keyword/Jaccard filtering on any
  failure or when no candidate has a usable embedding).
- `migrations/016_organizational_memory.sql` — `organizational_memory_items`
  (written, **applied and live-commissioned 2026-09-21** — see
  SYSTEM_STATE.md), organization-scoped via
  `organization_id` (reuses `is_organization_member(uuid)` from migration
  008, the same function firm_profiles' policies use), RLS-enabled with
  authenticated SELECT only (no write policy — service_role only, via
  `create_organizational_memory_item()`), an approval-coupling CHECK
  constraint, and a `BEFORE UPDATE` trigger rejecting any change to
  provenance/identity columns after insert.
- `database.py`'s `create_organizational_memory_item` (the only write
  path), `list_organizational_memory_items`, `get_organizational_memory_item`.
- `tenancy.py`'s `create_organizational_memory_item_for_organization`
  (forces `organization_id` server-side, recomputes `content_hash` from
  the actual content — never trusts a caller-supplied hash),
  `list_organizational_memory_for_organization`,
  `retrieve_organizational_memory_for_organization` (fetches only the
  caller's own organization's rows, then calls `organizational_memory.
  retrieve()`).
- `content_library` (migration 001) was audited for reuse and rejected:
  bid-scoped (`bid_id` FK, RLS requires `bid_id is not null`), so it
  cannot represent organization-wide truth — see SYSTEM_STATE.md.
- Tests: `tests/test_organizational_memory.py` (memory-class structural
  distinctness, approval semantics, exact source linkage, immutable
  write-path behavior, organization isolation via direct access AND via
  the retrieval contract, deterministic filtering/ranking, graceful
  embedding-unavailable fallback, proposal-memory-never-truth behavior,
  tenancy wiring, provenance-shape compatibility with the existing PI/
  evidence discipline).
- Explicitly deferred to a later OM phase (still true after OM-2):
  proposal-text generation from memory, auto-insertion of evidence, Section
  Analyzer integration, win-probability/scoring, and any PROPOSAL_MEMORY →
  APPROVED_FIRM_KNOWLEDGE promotion mechanism.

**Organizational Memory (OM-2: source ingestion + human approval lifecycle)**
- `organizational_memory.py`'s `split_source_into_chunks()` — deterministic
  paragraph bin-packing chunker (fixed-window fallback for one oversized
  paragraph); every chunk carries exact `char_start`/`char_end` into the
  original extracted text.
- `migrations/016_organizational_memory.sql` (edited in place, same file,
  **applied and live-commissioned 2026-09-21**) — new `organizational_source_documents` table
  (organization-scoped, RLS SELECT-only, unique on `(organization_id,
  content_hash)`), new nullable `organizational_memory_items.
  source_document_id` column (composite same-org FK, `ON DELETE RESTRICT`,
  added to the immutable-provenance trigger's guarded columns), new
  service-role-only RPCs `create_organizational_source_document()` and
  `approve_organizational_memory_item()` (the ONLY path that may insert
  `memory_class = 'APPROVED_FIRM_KNOWLEDGE'` — fetches the SOURCE_MEMORY
  parent server-side, verifies same-org and `memory_class = 'SOURCE_MEMORY'`,
  sets `approved_at` via `now()`, copies provenance from the parent row).
- `database.py`'s `create_organizational_source_document`,
  `list_organizational_source_documents`, `get_organizational_source_document`,
  `approve_organizational_memory_item`.
- `tenancy.py`'s `ingest_organizational_source_document_for_organization`
  (extracts via `extractor.extract_text_from_file`, chunks via
  `split_source_into_chunks`, creates one source-document parent row + one
  SOURCE_MEMORY item per chunk; re-uploading an identical file reuses the
  existing document/chunks instead of duplicating them),
  `list_organizational_source_documents_for_organization`,
  `approve_organizational_memory_item_for_organization` (the human-approval
  entry point — see migration RPC guarantees above; never trusts client-
  supplied provenance, approver identity, or timestamp).
- `pages/stage_memory.py`'s `page_memory()` — new global-nav Streamlit page
  (`app.py` sidebar: "🧠 Organizational Memory", `page == "org_memory"`):
  upload a source file, browse/review SOURCE_MEMORY chunks, approve one as
  firm knowledge, browse APPROVED_FIRM_KNOWLEDGE and PROPOSAL_MEMORY with
  explicit trust-label badges per memory class.
- Tests: `tests/test_organizational_memory_om2.py` (chunking determinism/
  contiguity, ingestion determinism + org isolation + dedup-on-re-upload,
  approval authorization/lineage incl. cross-org and non-SOURCE_MEMORY
  rejection, provenance copying, generic-create-path regression guard,
  retrieval-after-approval, embedding-failure fallback, migration DDL-intent
  assertions for the OM-2 schema/RPC additions).
- Explicitly still deferred (unchanged from OM-1): proposal-text generation
  from memory, auto-insertion of evidence into a proposal, Section
  Analyzer/Proposal Intelligence integration, archive-wide/bulk ingestion
  (single-file human-initiated upload only), auto-approval, scoring/win
  probability.

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
