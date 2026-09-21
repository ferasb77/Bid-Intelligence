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
`EvidenceEnrichmentResult`/its contents were computed and returned, not
persisted, by OM-3A — see OM-3B immediately below, which adds durable
reuse on top of this same pure logic without changing it. Tests:
`tests/test_evidence_strengthening.py`.

**OM-3B (durable requirement evidence enrichment) is now implemented AND
live-commissioned** (migration 017 applied 2026-09-21) — "reason once,
persist structured intelligence, reuse downstream" on top of OM-3A's pure
logic, which is unchanged in its analytical behavior (see the live-fix
note below for one caller-side query-shape fix). New `migrations/017_
requirement_evidence_enrichment.sql`: one new bid-scoped table,
`requirement_evidence_enrichments`, mirroring migration 015's Proposal
Intelligence persistence pattern exactly (bid_id-direct RLS via
`can_access_bid`, authenticated SELECT only, service_role-only write via
one RPC). A new table was
justified only after three existing tables were considered and rejected
(documented in the migration file's own header): `proposal_requirement_
assessments` cannot hold it because an enrichment must be persistable even
when NO Proposal Intelligence run exists at all (the MISSING gap case) —
there is structurally no parent assessment row to attach a column to, and
that table's rows are immutable outputs of one specific PI run with no
UPDATE path anywhere in this schema; `proposal_intelligence_findings`
would conflate two unrelated finding taxonomies under one CHECK
constraint; `organizational_memory_items` would mean writing a
multi-item-referencing derived artifact into the table migration 016's own
immutable-provenance trigger exists specifically to protect. The
`get_or_create_requirement_evidence_enrichment()` RPC mirrors migration
015's `get_or_create_proposal_package_snapshot()` exactly — a
transaction-scoped advisory lock keyed on `(bid_id, req_id)`, idempotent
get-or-insert keyed on `(bid_id, req_id, input_fingerprint)`, never an
UPDATE.

Freshness: `evidence_strengthening.compute_input_fingerprint()` — a single
deterministic sha256 (same canonicalization convention as
`proposal_intelligence.compute_package_digest`: sorted-key JSON, sha256
hex) over exactly what the enrichment output depends on — the
requirement's own req_id/description/category, the current
`RequirementEvidenceState` (assessment_status/evidence_strength/
has_contradiction_finding/gap_kind — bid-specific evidence, hierarchy tier
2), the FULL considered Organizational Memory candidate pool's identity
(item_id + item_content_hash + memory_class for every candidate handed to
`retrieve()`, not only the top_k actually ranked — a newly-added item that
would change what top_k selects still invalidates a prior result even if
it never makes the final ranked set), and
`EVIDENCE_STRENGTHENING_CONTRACT_VERSION` (bumping it invalidates every
prior fingerprint, exactly like `PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION`).
Deliberately a single fingerprint rather than a broader dependency graph
(per this phase's own instruction) — content OM items outside the
candidate pool, or unrelated requirement columns, never affect it.

Reuse orchestration lives in `tenancy.strengthen_requirement_evidence_
for_organization` (rewritten, same function/signature OM-3A introduced,
now with persistence): an already-sufficient requirement is answered
directly, exactly as OM-3A, without ever reading `organizational_memory_
items` or the enrichment table (nothing worth caching). Otherwise: fetches
the OM candidate pool, computes the fingerprint, searches this
requirement's persisted history (`database.get_requirement_evidence_
enrichments`, bid-scoped) for an exact match — a match is returned
directly with retrieval AND the adjudication model call both skipped
entirely; no match recomputes via `evidence_strengthening.
strengthen_requirement_evidence()` (completely unchanged from OM-3A) and
persists the result via `database.get_or_create_requirement_evidence_
enrichment`. A genuine exception during recomputation propagates to the
caller without writing anything — any previously persisted row for a
different (now-stale) fingerprint is left completely untouched. Evidence
hierarchy is unaffected: `evidence_state_after` on a persisted row is
still the OM-3A `before` state copied verbatim, extended only with
additive support/contradiction flags — Organizational Memory can never
override tier-2 current-bid evidence, cached or not.

Live commissioning (2026-09-21, project `whonalbdpbubaqhpzrnw`, ledger entry
`20260921142902 requirement_evidence_enrichment`): schema/RLS/constraint/
grant verification (including a direct probe — a committed `authenticated`
UPDATE/DELETE against a real row affected zero rows and left it byte-for-
byte unchanged, not merely a rolled-back no-op); RPC persistence (first
write persists; an exact-fingerprint re-request returns the SAME row
un-mutated, no duplicate; full payload — requirement identity, both
evidence states, every organizational-evidence field including trust
class/relationship/provenance/approval lineage/caveat, remaining gaps,
`requires_human_confirmation` — round-trips exactly); a malformed payload
(`NULL` evidence_state) is rejected outright with zero rows written; a
genuinely live end-to-end run (`tenancy.strengthen_requirement_evidence_
for_organization` against a real bid/requirement with disposable
Organizational Memory rows) proved the reuse claim conclusively, not just
by inference: the SECOND identical call was made with
`_call_memory_adjudication` temporarily replaced by a function that raises
if invoked at all, and that call still succeeded and returned a
byte-identical result — a live cache hit that provably never called
Anthropic; a THIRD call, after adding one new (irrelevant) Organizational
Memory item to the pool, produced a different fingerprint, a new persisted
row, and a genuine new adjudication call, live-proving pool-change
invalidation specifically (the property this phase's own instructions
called out as needing direct proof, not inference). Security advisors
clean of any migration-017-attributable finding. All disposable
commissioning rows (4 enrichment rows, 3 Organizational Memory items)
cleaned up, verified zero residue in both tables.

One real defect was found and fixed during commissioning — application
code, not migration 017's SQL: `tenancy.strengthen_requirement_evidence_
for_organization`'s freshness CHECK (the "does a fresh row already exist"
read, meant to be a cheap identity-only query per this phase's own
instructions) was calling `database.list_organizational_memory_items`,
which does `select("*")` — loading every candidate's full `content` and
`embedding` text on EVERY check, including a guaranteed cache hit, even
though `compute_input_fingerprint()` only ever reads `id`/`memory_class`/
`content_hash`. Fixed by adding `database.
list_organizational_memory_item_identities` (a `select("id,memory_class,
content_hash")` projection) and a matching lightweight `tenancy.
_MemoryItemIdentity` duck-type, used ONLY for the freshness check; the
full-content read now happens only on a genuine cache MISS, where
retrieval/adjudication legitimately need it. No migration change was
required — purely a query-shape fix, verified by three new tests
(`TestFreshnessCheckNeverReadsFullContent`) plus the live end-to-end proof
above.

One pre-existing architectural characteristic was observed, not changed:
`requirement_evidence_enrichments.requirement_id` has no composite FK
tying it to the SAME `bid_id` as its own row (a live probe confirmed a
requirement belonging to a DIFFERENT bid's numeric id CAN be attached) —
this exactly matches `proposal_requirement_assessments.requirement_id`'s
own existing, deliberate precedent (migration 015 has the identical
characteristic) and is not a regression introduced by migration 017.
In practice this column is only ever populated from `database.
get_requirements_by_ids(bid_id, ...)`, which is itself already bid_id-
scoped at the fetch, so the application's own calling code cannot exercise
this gap; documented here rather than silently left unmentioned or
speculatively "fixed" with a schema change beyond this task's scope.

Tests: `tests/test_requirement_evidence_enrichment.py` (17, including the
new freshness-content-read guard). Explicitly still deferred: a UI, Ask
CapOS integration, Section Analyzer integration, proposal-generation
integration.

**PI-3A (evidence-aware section drafting) is now implemented** — the
first bounded proposal-generation capability in Bid Intelligence, drafting
ONE requirement's response from EXISTING persisted intelligence only
(never whole-proposal generation). New `section_drafting.py`: a pure
domain module (no I/O of its own, same posture as `evidence_
strengthening.py`/`proposal_intelligence.py`). `SectionDraftingBrief`
keeps the evidence hierarchy structural, not just behavioral — separate,
distinctly-named fields per tier: `current_rfp_source_refs` (tier 1, the
requirement's own canonical `source_refs`), `bid_specific_evidence` (tier
2, the requirement's latest Proposal Intelligence assessment —
assessment_status/evidence_strength/confidence/explanation/
proposal_source_refs, reused verbatim, never re-derived),
`organizational_evidence` (tiers 3/4, OM-3B's ALREADY-PERSISTED
enrichment, read-only), plus `related_requirements` (same-category
siblings, context only), `evaluation`/`response_constraints` (Fast
Analysis's `evaluation_criteria`/`deterministic_response_guidelines`,
matched via `section_analyzer._match_evaluation_criterion`/
`_matching_response_guideline` — REUSED, not reimplemented), and
`proposal_intelligence_findings` (bounded, `related_req_id`-filtered).
`build_brief()` is pure and performs no I/O; it never fetches, never calls
a model, never touches Organizational Memory.

No independent retrieval during drafting (this phase's core architectural
claim, live-proven — see below): `section_drafting.py` never calls
`organizational_memory.retrieve()`, never re-runs OM-3A/OM-3B, never
re-runs Proposal Alignment/Fast Analysis, never fetches full RFP/proposal
text — it consumes ONLY the already-assembled brief. This discipline
extends to brief ASSEMBLY too: `build_brief()` takes an
ALREADY-PERSISTED OM-3B enrichment dict as a plain argument and never
triggers a fresh OM-3A/OM-3B computation itself — a caller that wants
fresh Organizational Memory enrichment must call `strengthen_requirement_
evidence_for_organization` separately, first, as its own step
("analyze once, persist, draft from persisted intelligence").

The ONE new bounded model call (`section_drafting._call_section_draft`,
`workflow="section_drafting"`, `operation="draft_section"`, same
structured-call pattern as `analyst._call_package_reasoning`/
`evidence_strengthening._call_memory_adjudication`) is instructed to tag
every cited evidence item with a closed claim-type vocabulary
(`VERIFIED_FACT`/`ORGANIZATIONAL_KNOWLEDGE`/`PROPOSED_APPROACH`/
`UNSUPPORTED_GAP`), never fabricate names/metrics/certifications/
personnel/outcomes/commitments/references, and insert an explicit
`[SME confirmation required: ...]` placeholder rather than invent a
missing fact. Traceability is enforced structurally, mirroring PI-2B1's
own P#/C# short-id ledger discipline (`analyst._build_package_
intelligence_ledger`/`_reconcile_package_findings`) rather than
reinventing it: `_evidence_id_registry()` assigns bounded ids (`CE#`
current-RFP, `PE#` bid-specific proposal evidence, `OM#` Organizational
Memory) from the brief's own contents, and `_reconcile_draft_response()`
fail-closed-drops any `evidence_items_used` entry citing an id outside
that registry or an unrecognized claim type — an invented id can never
survive into the structured result. A CONTRADICTION-classified OM item
already present in the brief is carried through unchanged (never
re-adjudicated); the draft is expected to surface it as a caveat, and
`assure_section_draft()` flags a hidden one.

`assure_section_draft()` is bounded, post-draft assurance — ENTIRELY
DETERMINISTIC, no second model call: cross-checks the draft's own
structured output against the brief (mandatory-requirement coverage,
evaluation-criterion reflection, evidence-id validity, a surfaced
CONTRADICTION caveat, word-limit compliance, and
`human_confirmation_required` correctness given unresolved points/
contradictions/the enrichment's own flag/gap_kind). Not the full Red Team
capability — section-level drafting assurance only.

`tenancy.draft_section_for_organization` wires it to real, already-
persisted intelligence: `require_bid_access` first; `database.
get_requirements_by_ids`/`get_requirements` (same-category siblings);
`_requirement_evidence_context`/`_requirement_evidence_state_from_
assessment` (factored out of OM-3B's own function during this task, pure
refactor, no behavior change — now shared by both); `section_analyzer.
procurement_basis` + its own matching functions for evaluation context
(advisory-only, a resolution failure never blocks drafting); `database.
get_requirement_evidence_enrichments` for the LATEST persisted OM-3B row
only (a plain read, never triggering computation); an optional
caller-supplied `outline_section` dict for word_limit/title/notes (never
fetched by this function itself, so no new dependency on migration 013's
still-unapplied `outline_section_requirements` mapping table). Returns
`{"brief", "result", "assurance"}`. Read-only end to end — writes nothing
anywhere, including no draft persistence (PI-3A is compute-and-return
only this phase; no migration, no new table — the existing `requirements`/
`proposal_requirement_assessments`/`proposal_intelligence_findings`/
`requirement_evidence_enrichments` schema was already sufficient).

Live commissioning (2026-09-21): `section_drafting.draft_section` was run
ONCE against the real Anthropic API with entirely synthetic, disposable
in-memory inputs (no Supabase interaction) — a requirement with one
strongly supported APPROVED_FIRM_KNOWLEDGE fact, one partial/caveated
SOURCE_MEMORY item, one CONTRADICTION-classified SOURCE_MEMORY item, one
evaluation criterion, and a 120-word limit. The live draft cited the
strong fact appropriately (tagged `ORGANIZATIONAL_KNOWLEDGE`, not
overclaimed as `VERIFIED_FACT`), avoided citing the partial fact's missing
metric at all (explicitly noted in its own `drafting_notes`), inserted an
explicit `[SME confirmation required: ...]` placeholder for the genuinely
missing fact instead of inventing one, explicitly declined to let the
CONTRADICTION item override the bid's own stated evidence (articulating
why in `contradictions_or_caveats`), reflected the evaluation criterion,
stayed within the word limit (119/120), and set
`human_confirmation_required=True` correctly.
`assure_section_draft()` passed with zero issues. No defect found this
commissioning pass. Tests: `tests/test_section_drafting.py` (30, pure
domain layer), `tests/test_section_drafting_tenancy.py` (9, wiring/
architecture-discipline). Explicitly still deferred: whole-proposal
generation, draft persistence, a UI, Word export, Ask CapOS integration,
Red Team, Section Analyzer UI wiring.

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
above for full detail. **OM-3A (requirement evidence strengthening,
`evidence_strengthening.py` + `tenancy.strengthen_requirement_evidence_
for_organization`) is now implemented** — the first product-value
integration reading Organizational Memory INTO existing Bid Intelligence
requirement analysis (Proposal Intelligence's per-requirement
assessment_status/evidence_strength/finding vocabulary), read-only, no
new migration. **OM-3B (durable requirement evidence enrichment,
`migrations/017_requirement_evidence_enrichment.sql`) is now implemented
AND live-commissioned** (migration 017 applied 2026-09-21) — persists
OM-3A's result, keyed by a deterministic input fingerprint, and reuses it
(no retrieval, no model call — live-proven, not merely inferred) whenever
the fingerprint is unchanged; see the Organizational Memory entry above
for full detail on both, including the one live-commissioning defect found
and fixed (a caller-side query-shape fix, no migration change). Deferred
to a later OM phase: proposal-text generation from memory, auto-insertion
of evidence, Section Analyzer integration, a UI, Ask CapOS integration,
win-probability/scoring, and any PROPOSAL_MEMORY → APPROVED_FIRM_KNOWLEDGE
promotion mechanism.

**PI-3A (evidence-aware section drafting, `section_drafting.py` +
`tenancy.draft_section_for_organization`) is now implemented and
live-commissioned** — the first bounded proposal-generation capability,
drafting ONE requirement's response from EXISTING persisted intelligence
(Proposal Intelligence's assessment, Fast Analysis's evaluation criteria,
and OM-3B's already-persisted enrichment) with no independent
retrieval/re-analysis and structural claim/evidence-traceability
guardrails; no new migration, compute-and-return only this phase. See the
Organizational Memory entry above for full detail. Deferred: whole-
proposal generation, draft persistence, a UI, Word export, Ask CapOS
integration, Red Team, Section Analyzer UI wiring.

Absent an explicit task instruction otherwise, still do not: apply
migration 013, alter/reapply migration 015, 016, or 017, activate the
compact-wire prototype, change chunk sizes/max_tokens/model
routing/caching, or merge `main`/deploy.

## Migrations known in this repository (files, not live-database state)

Highest migration file present: **017**
(`017_requirement_evidence_enrichment.sql`, **applied and
live-commissioned 2026-09-21**). Files 001–017 exist in `migrations/`.
This describes what's **written in the repo**, not what's applied to any
Supabase project — see the note below (which is the current source of
truth for live status; always verify explicitly rather than trusting this
sentence in isolation).

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
> dependency of 016 and out of scope for this commissioning pass. Migration
> 017 (Requirement Evidence Enrichment, OM-3B) was written on 2026-09-21
> and **applied live on 2026-09-21**, formally recorded in Supabase's
> migration ledger as `20260921142902 requirement_evidence_enrichment`.
> Live OM-3B commissioning also passed on 2026-09-21: schema/RLS/
> constraint/grant verification including a direct committed-transaction
> probe proving `authenticated` UPDATE/DELETE affect zero rows and leave a
> real row byte-for-byte unchanged; RPC persistence/idempotency/round-trip
> fidelity; malformed-payload rejection with zero partial rows; and — the
> specific claim this phase's own instructions singled out for direct
> proof rather than inference — a genuinely live end-to-end run through
> `tenancy.strengthen_requirement_evidence_for_organization` in which a
> second identical call succeeded with `_call_memory_adjudication`
> temporarily replaced by a function that raises if invoked at all (proving
> the cache hit never calls Anthropic), and a third call after adding one
> new Organizational Memory item produced a different fingerprint, a new
> row, and a genuine new adjudication call (proving pool-change
> invalidation). One real defect was found and fixed during this
> commissioning pass — in application code, not migration 017's SQL: the
> freshness check was fetching every candidate's full content/embedding
> via `select("*")` even on a cache hit; fixed with a new identity-only
> projection (`database.list_organizational_memory_item_identities`) used
> only for the freshness check, with the full-content read reserved for a
> genuine cache miss. No migration change was needed for this fix. All
> disposable rows (4 enrichment rows, 3 Organizational Memory items)
> cleaned up, verified zero residue. Treat any future "is migration N
> live" question as requiring a fresh check — `git log` and this file are
> not a substitute for checking the live database when a task depends on
> it.

## Where NOT to look first

Do not begin ordinary task orientation by reading the ~99 root-level
`.md` files. Most are historical operational records (implementation
reports, commissioning reports, remediation reports) describing *completed
past work*, not current authoritative architecture. See
[NAVIGATION.md](NAVIGATION.md) and
[ROOT_DOC_INVENTORY.json](ROOT_DOC_INVENTORY.json) before reading any of
them.
