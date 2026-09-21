# System State

The smallest current-state snapshot a fresh agent needs. Not a history, not
an architecture explanation — see [NAVIGATION.md](NAVIGATION.md) for where
to read either of those when a task actually requires them.

## Product lifecycle

`UNDERSTAND → DECIDE → BUILD → CHECK → SUBMIT`

One Streamlit page per stage under `pages/stage_*.py`. This lifecycle is
implemented, not aspirational — it replaced an earlier flat, fragmented
navigation (see `docs/BID_INTELLIGENCE_STREAMLINING_AUDIT.md` if the task
needs that history).

## Current major subsystems

- **Fast Analysis** (`fast_analysis.py`, orchestrated by `analysis_service.py`) — the
  primary, LLM-driven procurement extraction engine. Advisory only; never
  writes canonical procurement truth.
- **Procurement governance** — `requirements`/`bids.procurement_revision`/
  `bids.procurement_truth_status` (`governed` | `ungoverned`). Canonical
  requirement facts (description/category/rfso_ref/weight) can only change
  through the governed review RPCs once a bid is `governed`
  (`database._guard_canonical_requirement_write`).
- **Raw FastAnalysisResult persistence** — `fast_analysis.serialize_fast_analysis_result()`
  / `deserialize_fast_analysis_result()`, written to
  `analysis_results.fast_analysis_result_snapshot`. Lets a completed run's
  minimum-score thresholds, qualification mechanisms, tie-break ranks, and
  deterministic service-scope/Response-Guideline parses be regenerated into
  a report with zero further LLM calls.
- **Buyer Intelligence** — external, advisory context attached to a
  `FastAnalysisResult`, always kept visibly separate from procurement
  requirement facts in every consumer.
- **BUILD workspace** (`pages/stage_build.py`) — the Proposal Outline &
  Integrated Section Drafter.
- **Section Analyzer** (`section_analyzer.py`) — a *formative*, per-section
  review inside BUILD ("is this section heading in the right direction?"),
  distinct from the later, holistic CHECK-stage audit below.
- **CHECK / Proposal Alignment** (`analyst.py`'s `analyze_proposal_alignment*`
  family) — the holistic, whole-package submission-readiness audit.
- **Proposal Intelligence** (`proposal_intelligence.py` +
  `migrations/015_proposal_intelligence.sql`, **live and commissioned** —
  see below) — the durable, immutable, provenance-aware persistence layer
  for CHECK's Proposal Alignment output: what the proposal actually says,
  demonstrates, covers, contradicts, fails to evidence, or omits relative
  to the procurement. Advisory intelligence, never canonical procurement
  truth. Adds NO new LLM call — a pure adapter over the existing
  `analyze_proposal_alignment_package()` result, persisted via
  `tenancy.run_proposal_intelligence_for_organization()`.
  `PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION` is `proposal-intelligence-v2`
  (PI-2A): the analyzer's existing per-chunk schema now also carries
  structured, deterministically-attached proposal-side provenance
  (`ProposalSourceRef` — file_id/content_hash/filename/package_path/
  file_type/section/char_start/char_end, built entirely from chunk
  metadata the application already has, never from the model),
  procurement-side provenance (a requirement's own canonical
  `source_refs`), a closed-vocabulary evidence-strength rating (STRONG/
  MODERATE/WEAK), locally-safe typed findings (WEAK_EVIDENCE/
  UNSUPPORTED_CLAIM/CONTRADICTION/INTERNAL_INCONSISTENCY — only ever
  established from within one chunk's own visible passage), and separate
  `proposal_observations` (DELIVERY_COMMITMENT/COMMERCIAL_EXPOSURE) —
  all additive to the unchanged chunk request/response call topology
  (still exactly one call per chunk plus the existing optional narrative
  synthesis call).
  `PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION` is now `proposal-intelligence-v3`
  (PI-2B1, implemented, **NOT live-provider commissioned** — every
  provider-call site is exercised only against mocked/frozen responses in
  tests; the real `_call_package_reasoning` code path has never been
  invoked against the live Anthropic API): a whole-package reasoning layer
  on top of PI-2A's per-chunk output. Each chunk call now also extracts
  `proposal_claims` (a closed-vocabulary, provenance-bearing affirmative
  proposal statement — EXPERIENCE/CAPABILITY/RESOURCE/CREDENTIAL/
  METHODOLOGY/DELIVERY/QUANTITY/DATE/DURATION/STAFFING/COMMERCIAL/PRICING/
  COMPLIANCE/OTHER), deterministically deduped into a package-wide
  `proposal_claim_ledger` (`analyst._aggregate_proposal_claims`) — never
  merging claims that actually conflict (e.g. "8 coaches" vs "10
  coaches" stay two claims). `analyst._build_package_intelligence_ledger`
  compresses the claim ledger + requirement evidence + observations +
  local deficiencies into a compact ledger addressed only by short IDs
  (`C#` claims, `P#` sources) — the raw proposal is NEVER resent.
  `analyst.analyze_proposal_package_intelligence()` issues exactly ONE
  new bounded provider call (`_call_package_reasoning`, telemetry
  workflow="proposal_intelligence" operation="package_reasoning") per
  completed alignment run, asking only for CONTRADICTION/
  INTERNAL_INCONSISTENCY/UNSUPPORTED_CLAIM findings that cite ledger IDs;
  every returned finding is individually validated fail-closed
  (`analyst._reconcile_package_findings` — unknown claim/source id, an
  unrecognized finding_type/severity, or a non-ledger-verbatim req_id
  rejects that finding only) and an UNSUPPORTED_CLAIM is structurally
  rejected outright whenever local coverage is incomplete, regardless of
  what the model returned. A package-call failure never destroys the
  already-valid local PI-2A result — it's recorded as
  `coverage_metadata.package_intelligence.package_reasoning_status =
  "FAILED"` alongside zero fabricated findings. Package findings persist
  into the SAME `proposal_intelligence_findings` table (no migration —
  CONTRADICTION/INTERNAL_INCONSISTENCY/UNSUPPORTED_CLAIM were already in
  migration 015's enum) tagged `payload.scope = "package"` (a local
  finding is now tagged `payload.scope = "local"` for the same reason);
  CHECK's "Proposal Intelligence" section renders them in their own
  "Whole-Package Consistency" cards, labeled "Package-level", from
  persisted rows only (no rerun).
  `PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION` is now `proposal-intelligence-v4`
  (PI-2B2, implemented, **NOT live-provider commissioned** — same mocked-
  only status as PI-2B1 above): Response Guideline coverage + evaluator-
  usability, added to the SAME single `package_reasoning` call PI-2B1
  established — no second model call. Response Guidelines are used ONLY
  when Fast Analysis's own deterministic (no-LLM) table parser
  (`fast_analysis.extract_response_guideline_sections`) already extracted
  them for that bid into `FastAnalysisResult.deterministic_response_
  guidelines` — there is no governed/canonical version of a guideline
  anywhere in this schema, so PI-2B2 reaches the raw Fast Analysis
  snapshot the same way BUILD's `section_analyzer.procurement_basis()`
  already does, and a bid with none gets no fabricated guideline section.
  `analyst._build_package_intelligence_ledger` now also carries a
  `response_guidelines` section (`G#` ids), prunable under the SAME
  60KB ledger-wide byte budget as every other section. The model assesses
  each guideline into a closed, fail-closed status vocabulary — ANSWERED/
  PARTIAL/NOT_ANSWERED/CANNOT_ASSESS — plus an evaluator-usability read
  (CLEAR/FRAGMENTED traceability, **never a numeric score, never win
  probability, never automatic rewriting**). `analyst._reconcile_
  guideline_assessments` validates fail-closed: ANSWERED/PARTIAL is
  REJECTED outright without validated claim/source/observation provenance
  (same contract as UNSUPPORTED_CLAIM/CONTRADICTION); NOT_ANSWERED is
  structurally DOWNGRADED to CANNOT_ASSESS whenever coverage_complete or
  ledger_complete is false, unless genuine positive evidence already
  justifies ANSWERED/PARTIAL instead. A genuine NOT_ANSWERED gap persists
  through the EXISTING `RESPONSE_GUIDELINE_GAP` finding type (already
  part of migration 015's taxonomy from PI-1); every other status
  persists as `FINDING_TYPE_OTHER`, both tagged `payload.kind =
  "guideline_assessment"` in the SAME `proposal_intelligence_findings`
  table (no migration). CHECK's "Proposal Intelligence" section renders a
  "Response Guideline / Evaluator Usability" area, hidden when empty,
  from persisted rows only (no rerun, no score shown). A proposal quality
  score, win probability, and proposal rewriting remain explicitly
  deferred (not implemented). See [NAVIGATION.md](NAVIGATION.md) for the
  full file map.
- **Organizational Memory** (`organizational_memory.py` +
  `migrations/016_organizational_memory.sql`, **OM-1/OM-2, implemented AND
  live-commissioned on 2026-09-21** — see Migrations section below) — a new,
  organization-scoped (never bid-scoped) durable memory foundation,
  unrelated to and never mixed with Proposal Intelligence's bid-scoped
  persistence. Three structurally distinct memory classes, enforced by
  both a DB CHECK constraint (migration 016) and `OrganizationalMemoryItem.
  __post_init__` (`organizational_memory.py`): **SOURCE_MEMORY** (raw
  attributable organizational source material — may SUPPORT a claim, never
  itself canonical truth), **APPROVED_FIRM_KNOWLEDGE** (human-approved
  reusable firm fact — requires `approved_by`/`approved_at` both set by an
  explicit human action; no automated process in this codebase ever sets
  them), and **PROPOSAL_MEMORY** (reusable prior-proposal language — never
  usable to PROVE a fact, structurally forbidden from ever carrying
  approval fields). `content_library` (migration 001) was audited and NOT
  reused: it is bid-scoped (nullable `bid_id` FK, RLS requires
  `bid_id is not null`), so it cannot represent organization-wide truth
  without fabricating a bid_id or bypassing RLS — Organizational Memory
  uses a fresh table instead. Provenance (`SourceProvenance`) reuses the
  same file_id/content_hash/filename/package_path/locator discipline
  `analyst._build_proposal_source_ref` established for Proposal
  Intelligence, and the same exact-identity requirement `evidence.py`
  enforces via `content_sha256` — SOURCE_MEMORY/PROPOSAL_MEMORY items must
  carry a real file_id or content_hash, never a vague/fabricated one.
  `organizational_memory.retrieve()` is the deterministic retrieval
  contract: organization-scoped, always bounded by `top_k`, filters by
  memory class/trust state before ranking, and exposes memory class,
  trust/approval state, provenance, and a relevance score/signal on every
  result — never bare text. It optionally accepts an `embed_fn` matching
  `embeddings.embed_query`'s signature to rank via cosine similarity
  (`relevance_signal="SEMANTIC"`); when no `embed_fn` is supplied, it
  fails, returns None, or no candidate item has a usable embedding, it
  deterministically degrades to keyword/Jaccard filtering
  (`relevance_signal="KEYWORD"`) — this fallback is a required, tested
  scenario. Zero live Voyage/Anthropic calls anywhere in this phase; the
  existing Voyage-backed `embeddings.py` interface is wired through
  `embed_fn` but exercised only via mocks in tests. `tenancy.py`'s
  `create_organizational_memory_item_for_organization` /
  `list_organizational_memory_for_organization` /
  `retrieve_organizational_memory_for_organization` provide the
  organization-boundary-checked persistence/retrieval wiring, following
  the same `*_for_organization` pattern every other subsystem uses;
  `content_hash` is always recomputed server-side from the actual content,
  never trusted from caller input. Explicitly deferred to a later OM
  phase: proposal-text generation from memory, auto-insertion of evidence,
  Section Analyzer integration, a full ingestion UI, any win-
  probability/scoring, and any PROPOSAL_MEMORY → APPROVED_FIRM_KNOWLEDGE
  promotion path (none exists in this phase — promoting requires a brand
  new, separately human-approved item, never a mutation of an existing
  row).

**OM-2 (source ingestion + human approval lifecycle) is now implemented
AND live-commissioned (2026-09-21)** on top of OM-1, same files plus
additions. New durable parent-file record
**`organizational_source_documents`** (migration 016, edited in place —
applied and live-commissioned 2026-09-21) tracks one row per uploaded
source file: organization-scoped, RLS-protected identically to
`organizational_memory_items`, unique on `(organization_id,
content_hash)` for re-upload dedup, minimal fields only (filename,
content_hash, extracted_char_count, chunk_count, uploader, timestamp).
`organizational_memory_items` gained a nullable `source_document_id`
column (composite same-organization FK, `ON DELETE RESTRICT`, added to
the existing immutable-provenance trigger's guarded-column set).

Ingestion: `tenancy.ingest_organizational_source_document_for_
organization()` — single-file, human-initiated (not a crawler). Extracts
text via the existing `extractor.extract_text_from_file()` entry point
(no new extraction logic), then splits it with a new deterministic
chunker, `organizational_memory.split_source_into_chunks()` (paragraph
bin-packing toward a target chunk size with a fixed-window fallback for
one oversized/unbroken paragraph — mirrors the bin-packing principle
`analyst._merge_and_size_bound_sections()` established for Proposal
Alignment, but is a smaller self-contained implementation, not a shared
import). Every chunk becomes its own SOURCE_MEMORY item via the existing
`create_organizational_memory_item_for_organization` path, with an exact
`source_locator` of the form `chars:<start>-<end>` into the original
extracted text — never a fabricated coordinate. Re-ingesting a
byte-identical file into the same organization detects the existing
`organizational_source_documents` row (by content_hash) and reuses its
already-created chunks rather than duplicating them.

Human approval — the only path that may create an APPROVED_FIRM_KNOWLEDGE
row: `tenancy.approve_organizational_memory_item_for_organization()`,
calling a new migration-016 RPC, `approve_organizational_memory_item()`.
Guarantees: fetches the SOURCE_MEMORY parent server-side by id (never
trusts a client-supplied copy); verifies same-organization; verifies the
parent's `memory_class` is genuinely `SOURCE_MEMORY` (rejects any other
class, including an already-approved item); requires an explicit
`approved_by_user_id` from the caller's authenticated context (never
inferred/defaulted); sets `approved_at` via the database's own `now()`,
never from client input; creates a brand-new `APPROVED_FIRM_KNOWLEDGE` row
— the parent SOURCE_MEMORY row is never mutated (the immutable-provenance
trigger would reject a mutation attempt regardless); copies
source_file_id/source_content_hash/source_filename/source_package_path/
source_locator/source_bid_id/source_document_id from the fetched parent
row automatically inside the RPC; sets `derived_from_item_id` to the exact
parent id. The human may edit/tighten the approved fact's title/content
text (`fact_title`/`fact_content`), which changes only content — lineage
still points at the exact reviewed SOURCE_MEMORY row regardless. The
generic `create_organizational_memory_item_for_organization` path
continues, unchanged, to reject `APPROVED_FIRM_KNOWLEDGE` outright
(regression-tested).

UI: new page `pages/stage_memory.py` (`page_memory()`), wired into
`app.py`'s global sidebar navigation (org-scoped, not bid-scoped — same
nav tier as Content Library) as "🧠 Organizational Memory". Four tabs:
upload a source file; browse/review SOURCE_MEMORY chunks and approve one
as firm knowledge; browse APPROVED_FIRM_KNOWLEDGE; browse PROPOSAL_MEMORY
(read-only, no ingestion path for that class in this phase). Every item
renders with an explicit trust-label badge distinguishing the three
memory classes so none is ever mistaken for another.

Zero live Voyage/Anthropic calls in OM-2, same as OM-1 — ingestion does
not call `embeddings.py` directly (embedding remains opt-in via
`retrieve()`'s existing `embed_fn` parameter). Explicitly still deferred
after OM-2: proposal-text generation from memory, auto-insertion of
evidence into a proposal, Section Analyzer integration, archive-wide/bulk
ingestion (this phase is single-file human-initiated upload only),
auto-approval of any kind, and any scoring/win-probability signal.

**OM-3 (requirement evidence strengthening) is now implemented** — the
first product-value integration between Organizational Memory and Bid
Intelligence's existing requirement/evidence model. New module
`evidence_strengthening.py`: a pure, deterministic domain layer (no I/O of
its own, exactly like `proposal_intelligence.py`) that lets ONE
requirement whose CURRENT-BID evidence is weak/partial/missing/conflicted
retrieve a small, ranked set of Organizational Memory candidates and
return a structured `EvidenceEnrichmentResult` — never a second
requirement/evidence model. "Current evidence state"
(`RequirementEvidenceState`) is built entirely from EXISTING, already-
persisted vocabulary: `proposal_intelligence.ASSESSMENT_STATUSES`/
`EVIDENCE_STRENGTH_VALUES` (the requirement's latest
`proposal_requirement_assessments` row) plus whether an existing
`CONTRADICTION`/`INTERNAL_INCONSISTENCY` finding is already tied to that
`req_id` — never a second invented status vocabulary, and Organizational
Memory is never consulted to build it. `EvidenceGapKind` (MISSING/PARTIAL/
WEAK/CONFLICTED/SUFFICIENT) is a pure function of that state;
`RequirementEvidenceState.needs_strengthening` is `False` only for
SUFFICIENT (Fully Addressed + STRONG/MODERATE evidence + no known
contradiction) — a strong requirement never triggers Organizational
Memory retrieval at all, not even a candidate-pool read (enforced both
inside `evidence_strengthening.strengthen_requirement_evidence` and, one
layer up, in `tenancy.strengthen_requirement_evidence_for_organization`,
which skips the `organizational_memory_items` read entirely for a
sufficient requirement).

Retrieval reuses OM-1's EXISTING `organizational_memory.retrieve()`
contract verbatim (no re-ranking/re-filtering logic duplicated here),
restricted to `APPROVED_FIRM_KNOWLEDGE` and eligible `SOURCE_MEMORY`
(never `PROPOSAL_MEMORY` — marketing language can never be cited as
requirement evidence), bounded by `top_k` (default 5). The retrieval
query is derived DETERMINISTICALLY from the requirement's own
`description`/`category` fields — there is no free-form query parameter
anywhere on this boundary, and this phase deliberately does NOT add a
generic agent-facing `searchOrganizationalMemory(query)` capability (the
existing OM-1 `retrieve_organizational_memory_for_organization` free-form
path is untouched and unexposed to this new boundary).

Each retrieved candidate is classified by a bounded, closed
`MemoryRelationship` vocabulary — `DIRECT_SUPPORT`/`PARTIAL_SUPPORT`/
`CONTEXT`/`CONTRADICTION` — via exactly ONE new bounded model call
(`evidence_strengthening._call_memory_adjudication`, reusing
`config.get_anthropic_client`/`execute_messages_create` with
`workflow="organizational_memory"`, `operation="evidence_adjudication"` —
the same structured-call pattern as `analyst._call_package_reasoning`,
its own separate telemetry bucket). Reconciliation is fail-closed exactly
like `analyst._reconcile_package_findings`: an unknown/duplicate
`item_id`, an item outside the candidate set, an unrecognized
relationship, or a missing rationale drops THAT candidate only; a
candidate the model omits entirely (no genuine relationship) is simply
absent from the result — never force-classified merely because it was
retrieved. `CONTRADICTION` is structurally excluded from
`evidence_state_after`'s support count — a conflicting memory item is
surfaced for human review, never silently treated as support, and NEVER
overrides `evidence_state_before`'s `assessment_status`/
`evidence_strength` (hierarchy: current RFP/bid evidence always outranks
Organizational Memory). `MemoryEvidenceCandidate` preserves memory item
id, trust class (`is_trusted_fact`), relationship, rationale, full
provenance, and approval lineage (`approved_by`/`approved_at`/
`derived_from_item_id`/`source_document_id`) — never bare text.
`requires_human_confirmation` is `True` whenever any Organizational Memory
evidence was surfaced at all (support or contradiction) — this module
never auto-approves, never converts `SOURCE_MEMORY` into
`APPROVED_FIRM_KNOWLEDGE`, never mutates an Organizational Memory item,
and never drafts proposal language.

`tenancy.strengthen_requirement_evidence_for_organization(bid_id,
organization_id, requirement_id)` is the auth-boundary wrapper —
`require_bid_access` first, then `database.get_requirements_by_ids`
(bid-scoped), `database.get_latest_usable_proposal_intelligence_run` +
`get_proposal_requirement_assessments`/`get_proposal_intelligence_findings`
for the current-bid evidence state, and (only when strengthening is
actually needed) `database.list_organizational_memory_items` for the
organization-scoped candidate pool, reusing `tenancy._row_to_memory_item`
verbatim. Read-only end to end — writes nothing, and this task added no
migration: the existing `requirements` / `proposal_requirement_
assessments` / `proposal_intelligence_findings` / `organizational_memory_
items` schema (migrations 015/016, both live) was already sufficient.
`EvidenceEnrichmentResult`/its contents are computed and returned, not
persisted, by this phase — persistence, a UI, Ask CapOS integration, and
proposal-generation integration are all explicitly deferred to a later OM
phase. Tests: `tests/test_evidence_strengthening.py`.

## Architectural fact-type separation

Every subsystem above keeps these categories distinct, never merges them:
**evidence** (what a source document actually says) → **canonical
procurement truth** (`requirements`, governed once a bid is `governed`) →
**intelligence** (AI-derived reasoning, advisory, never silently promoted
to fact). See `AGENT.md` / `MANIFESTO.md` for the full doctrine if a task
requires it.

## Current development state

The **BI Token/Context Optimization Program is complete for now** (Phases
2–5E.1) — its development freeze on BI product features no longer applies.
Live A/B experiments identified by that program (density-aware chunking,
the compact provenance wire format) remain **not activated**, pending paid
credits; do not activate them without a task explicitly requesting it.

**Proposal Intelligence development is explicitly active** (PI-1
established the durable domain foundation on this branch; PI-2A added
richer per-chunk evidence/provenance/observation depth on top of it, with
no new model call). PI-2A.1 hardened the deterministic post-response dedup
in `analyst._deduplicate_findings()`/`_aggregate_proposal_observations()`
so it never collapses findings across different `deficiency_type` values
or observations with matching statements but different implications, and
always unions (never drops) distinct structured `proposal_source_refs`
across a merged cluster (exact-match-per-field; stable first-seen order).
PI-2B1 (cross-document/whole-package claim, contradiction, and consistency
reasoning) is now **implemented** but **NOT live-provider commissioned** —
see above. PI-2B2 (Response Guideline coverage / evaluator usability) is
now also **implemented** (analysis_version `proposal-intelligence-v4`) but
likewise **NOT live-provider commissioned**. Future work should
build on PI-2A/PI-2A.1/PI-2B1/PI-2B2, not re-litigate their schema/
adapter/ledger design without cause.

**Organizational Memory (OM-1) is now implemented and live-commissioned**
— a new, unrelated product area (`organizational_memory.py`,
`migrations/016_organizational_memory.sql`), organization-scoped (never
bid-scoped) durable memory with three structurally distinct classes
(SOURCE_MEMORY / APPROVED_FIRM_KNOWLEDGE / PROPOSAL_MEMORY) and a
deterministic, retrieval-first contract (`organizational_memory.retrieve()`).
Zero live model/embedding calls this phase. **OM-2 (source ingestion +
human approval lifecycle) is now also implemented and live-commissioned**
(migration 016 applied 2026-09-21) — see the Organizational Memory entry
above for full detail. **OM-3 (requirement evidence strengthening,
`evidence_strengthening.py` + `tenancy.strengthen_requirement_evidence_
for_organization`) is now implemented** — the first product-value
integration reading Organizational Memory INTO existing Bid Intelligence
requirement analysis (Proposal Intelligence's per-requirement
assessment_status/evidence_strength/finding vocabulary), read-only, no
new migration; see the Organizational Memory entry above for full detail.
Deferred to a later OM phase: proposal-text generation from memory,
auto-insertion of evidence, Section Analyzer integration, persisting an
`EvidenceEnrichmentResult`, a UI for it, Ask CapOS integration,
win-probability/scoring, and any PROPOSAL_MEMORY → APPROVED_FIRM_KNOWLEDGE
promotion mechanism.

Absent an explicit task instruction otherwise, still do not: apply
migration 013, alter/reapply migration 015 or 016, activate the
compact-wire prototype, change chunk sizes/max_tokens/model
routing/caching, or merge `main`/deploy.

## Migrations known in this repository (files, not live-database state)

Highest migration file present: **016** (`016_organizational_memory.sql`).
Files 001–016 exist in `migrations/`. This describes what's **written in
the repo**, not what's applied to any Supabase project — see the note
below.

> **LAST VERIFIED EXTERNAL STATE** (as of the audit that wrote this file):
> migration 012 was applied to the project's Supabase database by the repo
> owner. Migration 013 (Section Analyzer) was written but explicitly NOT
> applied — still true. Migration 014 (`model_usage_events`, telemetry)
> was found already live during Phase 5's commissioning work. Migration
> 015 (Proposal Intelligence, PI-1) was applied live on 2026-09-20 and is
> formally recorded in Supabase's migration ledger as
> `20260920205721 proposal_intelligence`. Live PI-1 commissioning also
> passed on 2026-09-20: service-role RPC execution, snapshot reuse/versioning,
> atomic bundle rollback, composite cross-bid rejection, authenticated RLS
> read isolation/write denial, latest-usable-run semantics, and disposable
> cleanup were all exercised against the real project. The ledger also
> contains `20260920211025 proposal_intelligence_commissioning`, a
> commissioning-only assertion run with no lasting schema or data changes
> and no corresponding numbered repo migration file. Migration 013 remains
> unapplied. PI-2A added richer per-chunk evidence/provenance/observation
> fields on top of the SAME live migration 015 schema — no new migration
> was needed or created. PI-2B1 (whole-package reasoning) reuses the same
> migration 015 `proposal_intelligence_findings` table/enum again — its
> CONTRADICTION/INTERNAL_INCONSISTENCY/UNSUPPORTED_CLAIM finding_type
> values already existed there from PI-1's forward-looking taxonomy — so
> no new migration was needed for PI-2B1 either. Migration 016
> (Organizational Memory, OM-1) was written on 2026-09-21 — a fresh table
> was required (see the Organizational Memory entry above for why
> `content_library`'s existing bid-scoped schema could not be reused). OM-2
> (source ingestion + human approval lifecycle) EDITED migration 016 IN
> PLACE (no new migration 017) to add `organizational_source_documents`,
> `organizational_memory_items.source_document_id`, and the
> `approve_organizational_memory_item()` RPC. Migration 016 was **applied
> live on 2026-09-21** and is formally recorded in Supabase's migration
> ledger as `20260921132121 organizational_memory`. Live OM-1/OM-2
> commissioning also passed on 2026-09-21: table/RLS/policy/constraint/
> trigger/RPC-grant verification, RLS write-boundary denial for both
> `anon` and `authenticated` on both new tables (despite default Supabase
> schema-level table GRANTs to those roles — same baseline pattern as
> migration 015's tables; RLS absence-of-policy still fail-closed, verified
> by direct probe, not assumed), atomic multi-chunk ingestion, idempotent
> byte-identical re-ingest (zero duplicate rows), zero-chunk/null-storage-
> identity/bad-chunk-hash/non-member-uploader rejection, generic-create
> APPROVED_FIRM_KNOWLEDGE rejection, human approval with provenance/lineage
> copy-through and canonical CRLF/CR→LF content-hash normalization,
> non-member-approver rejection, immutable-provenance mutation rejection,
> fail-closed FK deletion restriction on both `source_document_id` and
> `derived_from_item_id`, and correct SOURCE_MEMORY-only completeness
> counting (a linked APPROVED_FIRM_KNOWLEDGE row does not mask/inflate
> completeness) were all exercised against the real project with disposable
> rows, all cleaned up afterward (verified zero remaining). Two real defects
> were found and fixed during commissioning, both in migration 016 only:
> (1) `ingest_organizational_source_document()` and
> `approve_organizational_memory_item()` called `digest()` unqualified
> while running `set search_path = public`; on this project pgcrypto lives
> in the `extensions` schema (not `public`), so `create extension if not
> exists pgcrypto` was a silent no-op and both RPCs failed at runtime until
> the `digest()` calls were schema-qualified to `extensions.digest(...)`;
> (2) the three OM guard-trigger functions
> (`organizational_memory_items_guard_immutable_provenance`,
> `_guard_derived_lineage`, `_guard_source_bid_org`) were missing
> `set search_path = public`, inconsistent with every other function in
> this migration and with migration 010's established "every function:
> fixed search_path" convention (flagged as a live WARN by Supabase's
> security advisor, resolved and re-verified clean). Real Storage smoke
> (upload/readback/SHA-256 verify/delete via the OM storage helper's
> `org/{organization_id}/sources/{content_hash}` path convention) was
> **not exercised** — the task's `bid-supabase` MCP server exposes no
> Storage read/write tool, so this was explicitly reported as unexercised
> rather than fabricated. Migration 013 remains unapplied — not a
> dependency of 016 and out of scope for this commissioning pass. Treat any
> future "is migration N live" question as requiring a fresh check —
> `git log` and this file are not a substitute for checking the live
> database when a task depends on it.

## Where NOT to look first

Do not begin ordinary task orientation by reading the ~99 root-level
`.md` files. Most are historical operational records (implementation
reports, commissioning reports, remediation reports) describing *completed
past work*, not current authoritative architecture. See
[NAVIGATION.md](NAVIGATION.md) and
[ROOT_DOC_INVENTORY.json](ROOT_DOC_INVENTORY.json) before reading any of
them.
