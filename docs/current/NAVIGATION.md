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
- `pages/stage_build.py` — the Streamlit page (outline, AI-assisted
  structure generation, evidence-aware drafter, Section Analyzer UI). See
  "Proposal Intelligence (PI-3D: AI-Assisted BUILD Workflow)" below for
  the current outline/drafting UI.
- `analyst.py`'s `draft_proposal_section` — no longer called from
  `stage_build.py` (PI-3D removed the competing, non-evidence-aware
  "quick draft" button); still used by `pages_extra.py`.

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
  Analyzer integration, archive-wide/bulk ingestion (single-file
  human-initiated upload only), auto-approval, scoring/win probability.

**Organizational Memory (OM-3A: requirement evidence strengthening)**
- `evidence_strengthening.py` — the first product-value integration
  reading Organizational Memory INTO existing requirement analysis. Pure,
  deterministic, no I/O of its own (same posture as `proposal_
  intelligence.py`). `RequirementEvidenceState` (current-bid evidence,
  built from `proposal_intelligence.ASSESSMENT_STATUSES`/
  `EVIDENCE_STRENGTH_VALUES` plus an existing CONTRADICTION/
  INTERNAL_INCONSISTENCY finding tied to the req_id — never from
  Organizational Memory) and its `gap_kind`/`needs_strengthening`
  properties (MISSING/PARTIAL/WEAK/CONFLICTED/SUFFICIENT — SUFFICIENT is
  the only state that skips retrieval entirely). `strengthen_requirement_
  evidence()` derives its `organizational_memory.retrieve()` query
  deterministically from the requirement's own description/category (no
  free-form query parameter — this is NOT a generic `searchOrganizational
  Memory(query)` capability), restricted to APPROVED_FIRM_KNOWLEDGE +
  SOURCE_MEMORY, `top_k`-bounded (default 5). `_call_memory_adjudication`
  is the one new bounded model call (reuses `config.get_anthropic_client`/
  `execute_messages_create`, `workflow="organizational_memory"`,
  `operation="evidence_adjudication"` — same structured-call pattern as
  `analyst._call_package_reasoning`); `_adjudicate_candidates` reconciles
  its response fail-closed (unknown/duplicate item_id, out-of-set item,
  bad relationship, or missing rationale drops that candidate only) into
  the closed `MemoryRelationship` vocabulary (DIRECT_SUPPORT/
  PARTIAL_SUPPORT/CONTEXT/CONTRADICTION). CONTRADICTION is structurally
  excluded from `evidence_state_after`'s support count and NEVER
  overrides `evidence_state_before`'s assessment_status/evidence_strength
  — current RFP/bid evidence always outranks Organizational Memory.
  `MemoryEvidenceCandidate` preserves item id, trust class, relationship,
  rationale, full provenance, and approval lineage.
  `EvidenceEnrichmentResult` is computed and returned; OM-3A itself never
  persists it (see OM-3B below for durable reuse on top of this same,
  unchanged pure logic). This module never mutates an Organizational
  Memory item, never converts SOURCE_MEMORY into APPROVED_FIRM_KNOWLEDGE,
  and never drafts proposal text. `compute_input_fingerprint()` (OM-3B) —
  a pure sha256 fingerprint over exactly this module's own inputs, see
  below.
- Tests: `tests/test_evidence_strengthening.py` (gap-state classification,
  strong-requirement retrieval skip, approved-knowledge/source-memory
  surfacing, irrelevant-candidate exclusion, contradiction handling and
  hierarchy precedence, organization isolation, provenance/lineage
  survival, bounded result count, no-mutation/no-proposal-text guards,
  default-adjudicator fail-closed reconciliation, tenancy wiring). No
  live provider call — the one model call is always injected via
  `adjudicate_fn` or monkeypatched at `_call_memory_adjudication`.

**Organizational Memory (OM-3B: durable requirement evidence enrichment)**
- `migrations/017_requirement_evidence_enrichment.sql` (written, **applied
  and live-commissioned 2026-09-21** — see SYSTEM_STATE.md) — new
  bid-scoped `requirement_evidence_enrichments` table,
  mirroring migration 015's Proposal Intelligence persistence pattern
  exactly (bid_id-direct RLS via `can_access_bid`, authenticated SELECT
  only, service_role-only write). Stores OM-3A's `EvidenceEnrichmentResult`
  fields (evidence_state_before/organizational_evidence/
  evidence_state_after/remaining_gaps/requires_human_confirmation/
  retrieval_skipped_reason as jsonb/columns) plus `contract_version` and
  `input_fingerprint`, unique on `(bid_id, req_id, input_fingerprint)` —
  never a copy of a whole source document or memory-item chunk content
  (`MemoryEvidenceCandidate` never carries the item's own `content` field
  at all). `get_or_create_requirement_evidence_enrichment()` RPC mirrors
  `get_or_create_proposal_package_snapshot()` exactly: advisory lock keyed
  on `(bid_id, req_id)`, idempotent get-or-insert, never an UPDATE. The
  migration file's own header documents, in detail, why three existing
  tables (`proposal_requirement_assessments`, `proposal_intelligence_
  findings`, `organizational_memory_items`) were considered and rejected
  before adding this one.
- `evidence_strengthening.compute_input_fingerprint()` — deterministic
  sha256 (same canonicalization convention as `proposal_intelligence.
  compute_package_digest`) over the requirement's own req_id/description/
  category, the current `RequirementEvidenceState`, the FULL considered
  Organizational Memory candidate pool's identity (item_id +
  item_content_hash + memory_class, sorted — never raw content, never only
  the top_k actually ranked), and `EVIDENCE_STRENGTHENING_CONTRACT_
  VERSION`. A single fingerprint, not a dependency graph.
- `database.get_or_create_requirement_evidence_enrichment` / `get_
  requirement_evidence_enrichments` (bid-scoped read, most-recent-first) /
  `list_organizational_memory_item_identities` (live-commissioning fix
  below) — the persistence + cheap-identity read functions; no per-column
  UPDATE helper exists (rows are write-once, exactly like every other
  OM/PI persisted table).
- `tenancy.strengthen_requirement_evidence_for_organization` (same
  function/signature OM-3A introduced, now with persistence) — an
  already-sufficient requirement is answered directly, exactly as OM-3A
  (never reads `organizational_memory_items` or the enrichment table).
  Otherwise: fetches the OM candidate pool's IDENTITY ONLY (`database.
  list_organizational_memory_item_identities` — id/memory_class/
  content_hash, never content/embedding), computes the fingerprint via
  `tenancy._MemoryItemIdentity` (a minimal duck-typed stand-in for
  `OrganizationalMemoryItem` carrying only the three fields the
  fingerprint reads), and searches this requirement's persisted history
  for an exact match — a hit skips retrieval AND the adjudication model
  call AND the full-content read entirely, live-proven (see commissioning
  note below), not merely inferred. Only on a miss does it fetch the FULL
  candidate rows (`database.list_organizational_memory_items`, content
  included — genuinely required for retrieval/ranking and the adjudication
  prompt) and recompute via `evidence_strengthening.
  strengthen_requirement_evidence` (unchanged), reusing the SAME
  fingerprint already computed from the identity pass (never recomputed a
  second time), then persists via `get_or_create_requirement_evidence_
  enrichment`. An exception during recomputation propagates without
  writing anything — a prior persisted row for a different fingerprint is
  never touched. `_enrichment_row_to_dict` adapts a persisted row back
  into the SAME dict shape `EvidenceEnrichmentResult.to_dict()` produces,
  so a cache hit and a fresh computation are indistinguishable to a
  caller.
- Tests: `tests/test_requirement_evidence_enrichment.py` (17: compute-once/
  reuse-without-a-model-call, invalidation on changed requirement text/
  assessment/OM pool, no-invalidation on an unrelated change, provenance/
  lineage survive the persistence round trip, bid-scoped isolation across
  a same-numbered requirement id in a different bid, cross-organization OM
  item never reaching adjudication, no OM write function ever called, no
  proposal text anywhere in the persisted or returned result,
  already-sufficient requirement skips the enrichment store entirely, a
  simulated persistence failure during recompute leaves a prior valid row
  byte-for-byte untouched and still raises, and `TestFreshnessCheckNever
  ReadsFullContent` guarding the live-commissioning fix below) — all
  against an in-memory fake standing in for migration 017's table/RPC, no
  live database, no live provider call.
- Live commissioning (2026-09-21, ledger `20260921142902
  requirement_evidence_enrichment`): full schema/RLS/grant/idempotency/
  round-trip verification against the real project, plus a genuinely live
  end-to-end run proving (not inferring) that a second identical call
  never invokes Anthropic — `_call_memory_adjudication` was temporarily
  replaced with a function that raises if called at all, and the call
  still succeeded with a byte-identical result — and that adding one new
  Organizational Memory item changes the fingerprint and forces a genuine
  new adjudication call. Found and fixed one real defect: the freshness
  check was calling `list_organizational_memory_items` (`select("*")`,
  full content/embedding) even on a cache hit; fixed with the identity-only
  projection above, used only for the check. No migration change needed.
  See SYSTEM_STATE.md for the full commissioning record.
- Explicitly still deferred: proposal-text generation, a UI, Ask CapOS
  integration, Section Analyzer integration, auto-approval of any kind.

**Proposal Intelligence (PI-3A: evidence-aware section drafting)**
- `section_drafting.py` — the first bounded proposal-generation
  capability, drafting ONE requirement's response. Pure, no I/O of its
  own (same posture as `evidence_strengthening.py`). `SectionDraftingBrief`
  keeps the evidence hierarchy STRUCTURAL, distinct fields per tier:
  `current_rfp_source_refs` (tier 1, the requirement's own `source_refs`),
  `bid_specific_evidence` (tier 2, the requirement's latest Proposal
  Intelligence assessment — assessment_status/evidence_strength/
  confidence/explanation/proposal_source_refs, reused verbatim),
  `organizational_evidence` (tiers 3/4, OM-3B's ALREADY-PERSISTED
  enrichment, read-only — `build_brief()` never fetches or computes one
  itself), `related_requirements` (same-category siblings, context only),
  `evaluation`/`response_constraints` (Fast Analysis's evaluation_
  criteria/response_guidelines, matched via `section_analyzer.
  _match_evaluation_criterion`/`_matching_response_guideline` — reused,
  not reimplemented), `proposal_intelligence_findings` (bounded,
  req_id-filtered). `build_brief()` is pure: no fetch, no model call, no
  Organizational Memory access.
- No independent retrieval during drafting: `section_drafting.py` never
  calls `organizational_memory.retrieve()`, never re-runs OM-3A/OM-3B,
  never re-runs Proposal Alignment/Fast Analysis. Extends to brief
  assembly too -- `build_brief()` takes an already-persisted OM-3B
  enrichment dict as a plain argument; a caller wanting fresh enrichment
  calls `strengthen_requirement_evidence_for_organization` separately,
  first.
- `_call_section_draft` — the ONE new bounded model call
  (`workflow="section_drafting"`, `operation="draft_section"`, same
  pattern as `analyst._call_package_reasoning`/`evidence_strengthening.
  _call_memory_adjudication`), instructed to tag every cited evidence item
  with a closed claim-type vocabulary (`VERIFIED_FACT`/`ORGANIZATIONAL_
  KNOWLEDGE`/`PROPOSED_APPROACH`/`UNSUPPORTED_GAP`) and insert an explicit
  `[SME confirmation required: ...]` placeholder rather than invent a
  missing fact. `_evidence_id_registry()` assigns bounded ids (`CE#`/
  `PE#`/`OM#`) from the brief, mirroring PI-2B1's P#/C# short-id ledger
  discipline (`analyst._build_package_intelligence_ledger`/
  `_reconcile_package_findings`) — reused, not reinvented;
  `_reconcile_draft_response()` fail-closed-drops any cited id outside
  that registry or an unrecognized claim type.
- `assure_section_draft()` — bounded, ENTIRELY DETERMINISTIC post-draft
  assurance (no second model call): mandatory-requirement coverage,
  evaluation-criterion reflection, evidence-id validity, a surfaced
  CONTRADICTION caveat, word-limit compliance, `human_confirmation_
  required` correctness. Not Red Team — section-level assurance only.
- `tenancy.draft_section_for_organization` — `require_bid_access` first;
  `database.get_requirements_by_ids`/`get_requirements` (siblings);
  `tenancy._requirement_evidence_context`/`_requirement_evidence_state_
  from_assessment` (factored out of OM-3B's own function this task, pure
  refactor, no behavior change, now shared); `section_analyzer.
  procurement_basis` + its matching functions for evaluation context
  (advisory-only, failure never blocks drafting); `database.
  get_requirement_evidence_enrichments` for the LATEST persisted row only
  (plain read, never triggers computation); optional caller-supplied
  `outline_section` dict for word_limit/title/notes (never fetched here —
  no dependency on migration 013's unapplied mapping table). Returns
  `{"brief", "result", "assurance"}`. Read-only end to end — no draft
  persistence this phase, no migration.
- Tests: `tests/test_section_drafting.py` (30, pure domain layer — grounding,
  missing-evidence, conflicts, coverage, traceability, architecture
  discipline, safety, constraints, failure handling),
  `tests/test_section_drafting_tenancy.py` (9, wiring — proves via
  monkeypatched `organizational_memory.retrieve`/`evidence_strengthening.
  strengthen_requirement_evidence` that drafting never calls either,
  result shape, related-requirement filtering). No live provider call in
  either file — the model call is always injected via `draft_fn` or
  monkeypatched at `_call_section_draft`.
- Live commissioning (2026-09-21): `section_drafting.draft_section` run
  ONCE against the real Anthropic API with synthetic disposable inputs
  (strong APPROVED_FIRM_KNOWLEDGE fact, partial caveated SOURCE_MEMORY,
  CONTRADICTION-classified SOURCE_MEMORY, one evaluation criterion, a
  120-word limit) — cited the strong fact appropriately (tagged
  ORGANIZATIONAL_KNOWLEDGE, not overclaimed), avoided citing the partial
  fact's missing metric, inserted an explicit placeholder for the missing
  fact, explicitly declined to let the contradiction override current-bid
  evidence, reflected the evaluation criterion, stayed within the word
  limit (119/120), set `human_confirmation_required=True` correctly;
  `assure_section_draft()` passed with zero issues. No defect found.
- Explicitly still deferred: whole-proposal generation, a UI, Word export,
  Ask CapOS integration, Red Team, Section Analyzer UI wiring.

**Proposal Intelligence (PI-3B: durable section drafts)**
- `migrations/018_section_drafts.sql` (written, **applied and
  live-commissioned 2026-09-21** — see SYSTEM_STATE.md) — new bid-scoped
  `section_drafts` table, mirroring migration 017's OM-3B
  persistence pattern exactly (bid_id-direct RLS via `can_access_bid`,
  authenticated SELECT only, service_role-only write, advisory-lock
  get-or-insert, write-once rows — no UPDATE path). Stores PI-3A's
  `SectionDraftResult` fields (draft_text/requirements_addressed/
  requirements_missing/evaluation_criteria_addressed/evidence_items_used/
  unsupported_or_unresolved_points/contradictions_or_caveats/
  human_confirmation_required/drafting_notes/word_count as jsonb/columns)
  plus `assurance_passed`/`assurance_issues` (persisted alongside the
  draft so a caller sees known quality flags without recomputing),
  `contract_version`, `input_fingerprint`, unique on `(bid_id, req_id,
  input_fingerprint)`. `get_or_create_section_draft()` RPC mirrors
  `get_or_create_requirement_evidence_enrichment()` exactly: advisory lock
  keyed on `(bid_id, req_id)`, idempotent get-or-insert, never an UPDATE;
  also rejects an empty `draft_text` outright (a failed/empty draft can
  never be persisted through this path). The migration file's own header
  documents why the same three tables migration 017 rejected are also
  unsuitable for this new result shape.
- `section_drafting.compute_draft_input_fingerprint()` — deterministic
  sha256 (same canonicalization convention as `evidence_strengthening.
  compute_input_fingerprint`/`proposal_intelligence.compute_package_
  digest`) over the ENTIRE `SectionDraftingBrief` (minus organization_id/
  bid_id/requirement_id, pure routing keys) — the brief is already PI-3A's
  bounded, exhaustive input domain, so hashing it whole needs no
  separately-reasoned dependency graph. `SectionDraftingBrief` gained a
  backward-compatible `source_enrichment_fingerprint` field (defaults to
  `None`) carrying the source OM-3B enrichment row's own
  `input_fingerprint`.
- `tenancy._assemble_section_drafting_brief` — factored out of
  `draft_section_for_organization` this task (pure refactor, no behavior
  change, verified by PI-3A's own existing test suite), now shared by
  both `draft_section_for_organization` (PI-3A, ephemeral) and
  `get_or_generate_section_draft` (PI-3B, persisted) so persistence never
  changes PI-3A's own drafting semantics.
- `tenancy.get_or_generate_section_draft` — computes the fingerprint,
  searches `database.get_section_drafts` (bid-scoped) for an exact match:
  a hit returns the persisted row with ZERO drafting model call,
  Organizational Memory retrieval, RFP read, or requirement reanalysis; a
  miss runs PI-3A's `draft_section`/`assure_section_draft` for real, then
  persists via `database.get_or_create_section_draft`. A FAILED drafting
  attempt (`result.failure_reason` set) is never persisted. An assurance
  FAILURE (`assurance.passed` is `False`) IS still persisted — a quality
  flag, not an invalid draft — with the issues recorded transparently. A
  genuine persistence-layer exception propagates to the caller (never
  swallowed, matching OM-3B's own contract); since this function only
  ever INSERTs via get-or-create, a persistence failure can never corrupt
  or replace a prior valid row. `tenancy._section_draft_row_to_dict`
  adapts a persisted row back into the SAME dict shape
  `SectionDraftResult.to_dict()` produces. Returns `{"brief", "result",
  "assurance", "reused"}`.
- Claim-level traceability assessment (explicitly not redesigned this
  task): the current structure answers "which evidence items did this
  draft use, across the whole draft" but NOT "which evidence item
  supports THIS SPECIFIC sentence/claim" — no sentence/claim-level
  citation exists yet. Documented as a required future PI-3C/assurance
  enhancement before any whole-proposal-generation work that would need
  to audit individual claims; no schema/structural change was made for it
  here (PI-3A's existing shape was judged safe to persist as-is).
- Tests: `tests/test_section_drafts_persistence.py` (22 — compute-once/
  reuse-without-a-model-call, invalidation on changed requirement text/
  evaluation criterion/evidence state/OM enrichment/related PI finding,
  no-invalidation on unrelated data, lossless round-trip, evidence-id/
  provenance/assurance survival, failed-generation creates no row, a
  simulated persistence failure leaves a prior valid row byte-for-byte
  untouched and still raises, idempotent concurrent get-or-create,
  bid-scoped isolation, no Organizational Memory item mutated/written,
  cache hit never calls `organizational_memory.retrieve`/
  `evidence_strengthening.strengthen_requirement_evidence`/the drafting
  model) — against an in-memory fake standing in for migration 018's
  table/RPC, no live database, no live provider call.
- Live commissioning (2026-09-21, ledger `20260921155315 section_drafts`):
  full schema/RLS/grant/idempotency/immutable-version/round-trip
  verification against the real project (including a committed
  `authenticated` UPDATE/DELETE probe proving zero rows affected and a
  real row left byte-for-byte unchanged), plus a genuinely live
  end-to-end run proving (not inferring) that a second identical call
  never invokes Anthropic — `section_drafting._call_section_draft` was
  temporarily replaced with a function that raises if called at all, and
  the call still succeeded with a byte-identical result — and that
  replacing the persisted OM-3B enrichment changes the fingerprint and
  forces a genuine new drafting call. Confirmed a cache CHECK loads only
  already-persisted bounded intelligence (the requirement row, siblings,
  latest PI assessment/findings, Fast Analysis's evaluation context, and
  the single latest `requirement_evidence_enrichments` row) — no semantic
  retrieval, no full-document load, no model work; not a design defect.
  No code defect found this pass. See SYSTEM_STATE.md for the full
  commissioning record.
- Explicitly still deferred: Section Analyzer/UI integration, user
  editing, draft comparison UI, whole-proposal generation, proposal-
  outline orchestration, Word export, Ask CapOS, Red Team.

**Proposal Intelligence (PI-3C: Section Drafting Workspace)**
- `pages/section_drafting_workspace.py` — `render_requirement_drafting_
  workspace(bid_id, requirement, outline_section=None)`, the public entry
  point. Calls ONLY `tenancy.get_section_draft_status_for_organization` on
  render (read-only, no Anthropic/OM-retrieval/reanalysis); an explicit
  "Generate/Refresh" button click is the ONLY thing that calls `tenancy.
  get_or_generate_section_draft`. Renders: requirement identity/mandatory
  flag/related requirements; evaluation intent (criterion/weight/minimum
  score/response guidance/word limit); evidence state (current-bid
  assessment_status/evidence_strength, Organizational Memory evidence with
  trust-class badges — `_TRUST_LABELS` distinguishes APPROVED_FIRM_
  KNOWLEDGE (✅ green) from SOURCE_MEMORY (explicitly "(unapproved)"),
  relationship labels including ⚠ Contradiction, remaining gaps); draft
  state badges (🟢/🔴 assurance, 🟡 human confirmation required, 🟠 stale);
  the generated draft as a disabled/read-only `st.text_area` (no editor
  this phase); the coverage/assurance panel (requirements addressed/
  missing, evaluation criteria addressed, unresolved points, contradictions/
  caveats, word count, assurance issues); the claim-level evidence mapping
  (`_render_claim`, PI-3C's own new field — see below); a version-history
  selector reading the already-fetched `history` list (no extra round
  trip, no visual diffing).
- `tenancy.get_section_draft_status_for_organization` — the new read-only
  status function: shares `_assemble_section_drafting_brief` with PI-3A/
  PI-3B, computes the current fingerprint, reads `database.
  get_section_drafts` (never writes), and returns `latest_draft`/
  `is_stale`/`is_current`/`history_count`/full `history` (each entry
  already `_section_draft_row_to_dict`-shaped, no second fetch needed to
  view an older version).
- `pages/stage_build.py` — one new expander, "🧠 Requirement Drafting
  Workspace (Bid Intelligence)," added immediately after the existing
  "🎯 Evaluation Criteria In View (Mapped Requirements)" expander in the
  Proposal Outline & Integrated Section Drafter tab — a requirement picker
  (defaults to the active section's own mapped requirements) opens the
  workspace for one requirement. This is the smallest coherent
  integration point: no new page, no parallel editor, reuses the existing
  BUILD tab and visual system.
- Claim-level traceability (closes the gap PI-3B identified, instruction
  7): `section_drafting.py` gained `MaterialClaim` (claim_id/claim_text/
  claim_type/evidence_ids/support_status) and `SectionDraftResult.
  material_claims`, bounded to `MAX_MATERIAL_CLAIMS = 12`.
  `_reconcile_material_claims`/`_permits_verified_fact` apply fail-closed
  hierarchy rules per claim_type: `UNSUPPORTED_GAP` forced to empty
  evidence_ids/`UNSUPPORTED` status; `PROPOSED_APPROACH` forced to a
  distinct `COMMITMENT` status (never presented as verified historical
  fact); `VERIFIED_FACT` restricted to current-RFP/proposal evidence or
  `APPROVED_FIRM_KNOWLEDGE` only (a SOURCE_MEMORY-only citation downgrades
  the WHOLE claim to `UNSUPPORTED_GAP`); `ORGANIZATIONAL_KNOWLEDGE` keeps
  any registry-valid evidence (SOURCE_MEMORY included, trust class always
  readable) but is likewise downgraded if left with zero evidence. New
  `SUPPORT_STATUS_*` closed vocabulary (`SUPPORTED`/`PARTIALLY_SUPPORTED`/
  `UNSUPPORTED`/`COMMITMENT`).
- `migrations/019_section_draft_claim_mappings.sql` — **live-commissioned
  2026-09-21** (ledger entry `20260921163500 section_draft_claim_mappings`)
  — a single backward-compatible `alter table section_drafts add column
  material_claims jsonb not null default '[]'::jsonb` plus a
  dropped-and-recreated `get_or_create_section_draft()` RPC accepting the
  new field. Applied via the deliberate two-step rollout the migration's
  own header anticipated: migration 018's RPC was already live and
  already used by production code, so the Python wiring
  (`database.get_or_create_section_draft`/`tenancy.
  get_or_generate_section_draft` passing `material_claims`/
  `p_material_claims`) was deferred until this commissioning task applied
  the schema/RPC change — now complete, live-proven via a real Anthropic
  drafting call plus a poisoned-`_call_section_draft` cache-hit proof
  (see `docs/current/SYSTEM_STATE.md`'s PI-3C commissioning entry for
  full detail). `tenancy._section_draft_row_to_dict` still reads
  `row.get("material_claims")` defensively (a pre-019-shaped row remains
  theoretically possible, though none occur post-migration).
- Tests: `tests/test_section_drafting.py`'s `TestMaterialClaimMapping`
  (12), `tests/test_section_drafting_workspace.py` (12 — status/staleness/
  no-model-call/no-OM-retrieval/isolation), `tests/
  test_section_drafts_persistence.py` (24 total, incl. 2 material-claims
  round-trip tests), `tests/smoke/
  test_all_pages_runtime.py::test_requirement_drafting_workspace_executes`
  (calls the render function directly against real bid 8/requirement R1
  data, read-only).
- Explicitly still deferred: whole-proposal generation, a collaborative
  editor, visual version diffing, Word export, automated SME messaging,
  Ask CapOS, Red Team.

**Proposal Intelligence (PI-3D: AI-Assisted BUILD Workflow)**
- Product/UI orchestration only -- no new migration, no new drafting
  architecture. `proposal_outline.py` (new, pure, no I/O) --
  `derive_outline_sections` groups active requirements by `category` into
  a proposed outline (deterministic only, no model call in this
  increment); `evidence_readiness_bucket`/`weakest_readiness`/
  `summarize_section_intelligence` are the pure rollups the section list/
  detail views render from maps `tenancy.py` builds once per bid.
- `tenancy.get_build_intelligence_context_for_organization` (new,
  Category B) -- `criterion_by_req_id` via `section_analyzer.
  _match_evaluation_criterion` (reused, not reimplemented) and
  `assessment_by_req_id` via the latest usable Proposal Intelligence
  run's assessments, each computed ONCE per bid. `tenancy.
  get_section_requirement_map_authenticated` (new, Category A, bulk) and
  `get_draft_existence_map_for_organization` (new, Category B, bounded
  existence read via `database.get_section_drafts`) round out the section
  list/detail rollups. None call Anthropic or `organizational_memory.
  retrieve()` -- proven via poisoned-function tests.
- `pages/stage_build.py`'s "Proposal Outline & Section Drafter" tab: a
  primary "🤖 AI-Assisted Build" / secondary "✍️ Build Manually" toggle;
  an empty-state "🪄 Generate Proposal Structure" action (offered
  alongside the unchanged, always-available "➕ Add Section Manually")
  that computes a PROPOSED structure via `derive_outline_sections` into
  `st.session_state["proposed_outline"]` -- reviewable (rename/reorder/
  remove/add), never auto-committed; "✅ Approve & Create Sections"
  persists it via the EXISTING `tenancy.upsert_section_authenticated`/
  `set_section_requirement_mapping_authenticated` (no new table).
  `upsert_section_authenticated` now returns the section's id (existing
  callers unaffected) so approval can map requirements to a
  just-created section in the same run.
- The OLD "✨ Draft / Refine Section with Claude" button (`analyst.
  draft_proposal_section`, a non-evidence-aware, non-persisted, session-
  state-only draft path) is REMOVED from this page -- PI-3C's `render_
  requirement_drafting_workspace` is now the sole AI drafting surface
  here, promoted from a collapsed, third-level-nested expander to a
  prominent, always-visible "🧠 Draft with BI" section under a new
  section-level intelligence summary card. Reused verbatim (one call
  site, one requirement at a time) -- no batch/whole-proposal drafting
  call introduced.
- **Root-cause discovery**: `migrations/013_section_analyzer.sql`
  (`outline_section_requirements`/`section_reviews`) is confirmed live-
  verified as still NOT applied to any live database -- the pre-existing
  per-section requirement-mapping expander would have raised a raw
  PostgREST error the moment any bid actually had both an outline section
  and a mapping attempt. `tenancy.get_section_requirement_ids_
  authenticated`/`get_section_requirement_map_authenticated` now degrade
  to an empty mapping and `set_section_requirement_mapping_authenticated`
  raises the new, distinctly-typed `tenancy.SectionMappingUnavailableError`
  instead of a raw traceback; the BUILD page shows an inline caption
  instead of crashing. Migration 013 remains unapplied -- see
  SYSTEM_STATE.md's PI-3D entry; applying it needs its own future,
  explicitly-authorized commissioning task.
- Tests: `tests/test_proposal_outline.py` (28, pure), `tests/
  test_build_workflow_tenancy.py` (13 -- bid-access gating, no-Anthropic/
  no-OM-retrieval proofs, migration-013-missing degradation), `tests/
  test_build_workflow_ui.py` (6 -- AI empty state, manual-always-available,
  AI drafting workspace actually invoked, single-call-site/no-whole-
  proposal-call structural check).
- Explicitly still deferred/excluded: one-call whole-proposal generation,
  Word export, collaborative editing, Red Team, Ask CapOS, Arabic, SME
  messaging, a proposal template designer, visual draft diffs, applying
  migration 013.

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
