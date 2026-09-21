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
architecture-discipline).

**PI-3B (durable section drafts) is now implemented AND live-commissioned**
(migration 018 applied 2026-09-21) — "analyze once, draft once, persist,
reuse" on top of PI-3A's pure logic, which is completely unchanged. New
`migrations/018_section_drafts.sql`: one new bid-scoped table,
`section_drafts`, mirroring migration 017's OM-3B persistence pattern
exactly (bid_id-direct RLS via `can_access_bid`, authenticated SELECT
only, service_role-only write via one RPC, advisory-lock get-or-insert,
write-once rows — no UPDATE path, so a changed fingerprint always creates
a new row rather than overwriting history). A new table was justified only
after the SAME three-table rejection analysis migration 017 already did
was re-applied to this new result shape (documented in the migration
file's own header): `requirement_evidence_enrichments` cannot hold it
because a section draft has an entirely different shape (drafted prose,
PI-3A's own evidence-id-registry citations, assurance results) and its
own independent freshness lifecycle; `proposal_requirement_assessments`/
`proposal_intelligence_findings` are immutable single-run outputs with no
column for drafted prose or assurance; `organizational_memory_items`
would violate migration 016's immutable-provenance trigger's purpose.

Freshness: `section_drafting.compute_draft_input_fingerprint()` — a
single deterministic sha256 (same canonicalization convention as
`compute_input_fingerprint`/`compute_package_digest`) over the ENTIRE
PI-3A `SectionDraftingBrief` (minus pure routing/identity keys —
organization_id/bid_id/requirement_id). This is a direct consequence of
PI-3A's own design: the brief is already PI-3A's bounded, exhaustive
statement of everything the draft depends on, so hashing it whole is
correct and requires no separately-reasoned dependency graph. A new
`source_enrichment_fingerprint` field was added to `SectionDraftingBrief`
(backward-compatible, defaults to `None`) carrying the source OM-3B
enrichment row's own `input_fingerprint` — belt-and-suspenders alongside
the full `organizational_evidence` content already in the brief.
`contract_version` (`SECTION_DRAFTING_CONTRACT_VERSION`) is already a
brief field and therefore already covered — bumping it invalidates every
prior fingerprint regardless of any other input.

Reuse orchestration lives in `tenancy.get_or_generate_section_draft`,
sharing brief assembly with PI-3A's own `draft_section_for_organization`
via a new `tenancy._assemble_section_drafting_brief` helper (both now call
it — PI-3A's ephemeral semantics are completely unchanged): computes the
fingerprint, searches `database.get_section_drafts` (bid-scoped) for an
exact match — a hit returns the persisted row with **zero** drafting
model call, Organizational Memory retrieval, RFP read, or requirement
reanalysis; a miss runs PI-3A's drafting + assurance for real, then
persists via `database.get_or_create_section_draft`. Failure safety: a
FAILED drafting attempt (`result.failure_reason` set, no usable
`draft_text`) is never persisted — the RPC itself also rejects an empty
`draft_text` outright as defense-in-depth. An assurance FAILURE
(`assurance.passed` is `False`) is NOT the same as a failed draft — the
draft is still a valid, non-fabricated result, so it IS persisted, with
`assurance_passed`/`assurance_issues` recorded transparently. A genuine
persistence-layer exception propagates to the caller (never swallowed),
exactly matching OM-3B's own contract — and since this function only ever
INSERTs via get-or-create, a persistence failure can never corrupt or
silently replace a prior valid row.

Claim-level traceability assessment (instruction 7, explicitly not
redesigned this task): the current structure can answer "which evidence
items did this draft use, across the whole draft" (`evidence_items_used`,
each item fully traceable to its provenance/trust class/approval
lineage) but **cannot** answer "which evidence item supports THIS
SPECIFIC sentence/claim in `draft_text`" — there is no sentence-level or
claim-level link between prose and citation, only a draft-wide list. This
is a genuine, documented gap for a future PI-3C/assurance enhancement
(sentence-level or claim-span citation) before any whole-proposal
generation work that would need to audit individual claims — no schema or
structural change was made for it here, since PI-3A's existing shape was
judged safe to persist as-is and the task explicitly scoped this as
report-only.

Live commissioning (2026-09-21, project `whonalbdpbubaqhpzrnw`, ledger
entry `20260921155315 section_drafts`): schema/RLS/constraint/grant
verification (including a direct probe — a committed `authenticated`
UPDATE/DELETE against a real row affected zero rows and left it
byte-for-byte unchanged); RPC persistence/idempotency (first write
persists with full round-trip fidelity across every field including
assurance_passed/assurance_issues; an exact-fingerprint re-request returns
the SAME row un-mutated — a differing second payload could not overwrite
draft_text/evidence_items_used/assurance_passed; a changed fingerprint
creates a genuinely NEW immutable row while the prior row remains
untouched, proving append-only version history); malformed payload
(empty/whitespace-only `draft_text`) rejected outright with zero rows
written; an assurance-FAILED draft (`assurance_passed=false`) persists
correctly and distinctly from an assurance-passed one, with its issues
preserved. A genuinely live end-to-end run through `tenancy.
get_or_generate_section_draft` (real bid/requirement, a disposable
persisted OM-3B enrichment) proved the reuse claim conclusively: the
SECOND identical call was made with `section_drafting._call_section_draft`
temporarily replaced by a function that raises if invoked at all, and
that call still succeeded with a byte-identical result — a live cache hit
that provably never called Anthropic. A THIRD call, after replacing the
persisted OM-3B enrichment with a different one, produced a different
fingerprint, a new persisted row, and a genuine new drafting call,
live-proving OM-enrichment-change invalidation specifically (the property
this phase's own instructions called out as needing direct proof). What a
cache CHECK must load to compute the fingerprint was confirmed to be
exactly "already-persisted bounded intelligence" (the requirement row,
sibling requirements, the latest PI assessment/findings, Fast Analysis's
evaluation context, and the single latest persisted
`requirement_evidence_enrichments` row) — no semantic retrieval, no full
RFP/document load, no model work on a cache check; not a design defect.
Security advisors clean of any migration-018-attributable finding. All
disposable rows (2 section_drafts, 2 requirement_evidence_enrichments)
cleaned up, verified zero residue. No defect found this commissioning
pass — no code change was required.

Tests: `tests/test_section_drafts_persistence.py` (22 — compute-once/
reuse-without-a-model-call, invalidation on changed requirement text/
evaluation criterion/evidence state/OM enrichment/related PI finding,
no-invalidation on unrelated data, lossless round-trip, evidence-id/
provenance/assurance survival, failed-generation creates no row, a
simulated persistence failure leaves a prior valid row byte-for-byte
untouched and still raises, idempotent concurrent get-or-create, bid-scoped
isolation, no Organizational Memory item mutated/written, cache hit never
calls `organizational_memory.retrieve`/`evidence_strengthening.
strengthen_requirement_evidence`/the drafting model).

**PI-3C (Section Drafting Workspace) is now implemented** — the first
user-facing proposal-writing experience in Bid Intelligence, and the
first Phoenix-facing PoC surface for anything OM/PI built. Exposes the
requirement → evaluation intent → evidence → gaps → grounded draft →
assurance → evidence-behind-material-claims flow this phase's own
authorization names, for ONE requirement at a time.

UI integration point (smallest coherent one, per instruction 2): a new
"🧠 Requirement Drafting Workspace" expander inside `pages/stage_build.py`'s
EXISTING per-outline-section drafting panel (BUILD stage, the same tab
that already hosts the Section Analyzer), immediately after the existing
"Evaluation Criteria In View (Mapped Requirements)" expander — a
requirement picker (defaulting to the section's own mapped requirements)
opens `pages/section_drafting_workspace.py`'s
`render_requirement_drafting_workspace()` for the chosen requirement. Not
a new global-nav page, not a parallel editor — a natural continuation of
the existing BUILD workflow, reusing its dark-theme visual system
(`components/ui.py` badge/color conventions) rather than inventing a new
one.

Token/execution discipline (instruction 12, structural, not just
behavioral): rendering the workspace calls ONLY the new `tenancy.
get_section_draft_status_for_organization` — a read-only function that
assembles the SAME `SectionDraftingBrief` PI-3A/PI-3B already assemble
(via the shared `_assemble_section_drafting_brief` helper), computes the
CURRENT fingerprint, and reads (never writes) `database.get_section_drafts`
to determine `latest_draft`/`is_stale`/`is_current`/full version
`history` — it never calls the drafting model, Organizational Memory
retrieval, or Fast Analysis/Proposal Alignment reanalysis. A fresh
persisted draft (fingerprint matches) is shown immediately, with zero
extra work. A STALE draft (fingerprint differs — the underlying
intelligence materially changed) is still shown, explicitly marked
"🟠 Stale — intelligence has changed," never silently regenerated; the
user must click an explicit "Generate Updated Draft" button, which is the
ONLY thing in this workspace that calls `tenancy.
get_or_generate_section_draft` (PI-3B's own orchestration, unchanged).
Draft history: the full immutable version list is already fetched by the
status call (no extra round trip), exposed as a simple version selector
(instruction 10) — no visual diffing.

Draft state is never presented as equivalent to an approved/final
response (instruction 5): every draft view carries explicit badges —
🟢/🔴 assurance passed/requires remediation, 🟡 human confirmation
required, 🟠 stale — and the generated text itself is a disabled
(read-only) `st.text_area`, never an editable field (instruction 11: no
collaborative editor this phase; user-authored editing is an explicit
future follow-up, never silent overwrite of immutable draft history).
Trust classes are visually distinguished (instruction 3): APPROVED_FIRM_
KNOWLEDGE renders with a green "✅ Approved Firm Knowledge" badge,
SOURCE_MEMORY with a gold-but-explicitly-"(unapproved)" badge — SOURCE_
MEMORY is never presented as approved evidence. The coverage/assurance
panel exposes PI-3A's full structured result (requirements addressed/
missing, evaluation criteria addressed, unresolved points, contradictions/
caveats, word count, assurance issues) rather than hiding it behind prose.

Claim-level traceability (instruction 7 — the gap PI-3B identified and
explicitly deferred): `section_drafting.py` gained `MaterialClaim`
(claim_id/claim_text/claim_type/evidence_ids/support_status) and
`SectionDraftResult.material_claims` — a BOUNDED (`MAX_MATERIAL_CLAIMS =
12`), not sentence-level-exhaustive, mapping from a draft's material
factual claims to the SAME evidence-id registry `evidence_items_used`
already uses. Fail-closed reconciliation
(`_reconcile_material_claims`/`_permits_verified_fact`) mirrors
`_reconcile_draft_response`'s discipline plus new per-claim-type hierarchy
rules: an invented evidence id is dropped (never trusted); `UNSUPPORTED_
GAP` is forced to empty evidence_ids/`UNSUPPORTED` status regardless of
what the model returned (can never masquerade as supported);
`PROPOSED_APPROACH` is forced to a distinct `COMMITMENT` status (a future
promise is never presented as verified historical support);
`VERIFIED_FACT` is further restricted to evidence from current-RFP/
proposal evidence or `APPROVED_FIRM_KNOWLEDGE` only — a claim backed ONLY
by `SOURCE_MEMORY` (lower trust) is downgraded to `UNSUPPORTED_GAP` rather
than left falsely labeled verified; `ORGANIZATIONAL_KNOWLEDGE` keeps any
registry-valid evidence (including SOURCE_MEMORY, with its trust class
always readable) but is likewise downgraded if filtering leaves zero
evidence. This closes PI-3B's identified gap for "which evidence item
supports THIS claim" (vs. only "which evidence was used somewhere") —
the drafting prompt itself now also asks for up to `MAX_MATERIAL_CLAIMS`
material claims per draft.

Schema (instruction 8): `migrations/019_section_draft_claim_mappings.sql`
— a single backward-compatible `alter table section_drafts add column
material_claims jsonb not null default '[]'::jsonb` (existing rows read
as "not computed," never fabricated) plus a replaced `get_or_create_
section_draft()` RPC (dropped and recreated, not a bare `create or
replace`, so the identity is genuinely extended rather than left as an
ambiguous duplicate overload) accepting the new field — reusing PI-3B's
own `section_drafts` table rather than a new one, exactly mirroring why
migration 017/018 didn't reuse an earlier table either (documented in the
migration file's own header). **Live-commissioned 2026-09-21** (ledger
entry `20260921163500 section_draft_claim_mappings`).

**Live commissioning (2026-09-21)**: applied via the deliberate two-step
rollout migration 019's own header anticipated — migration 018's
`get_or_create_section_draft()` RPC was already live and already used by
production code, so the Python wiring (`material_claims` parameter in
`database.get_or_create_section_draft()`/`tenancy.
get_or_generate_section_draft()`) was deferred until this commissioning
task applied the schema/RPC change, avoiding any window where production
code called a signature that didn't exist yet. Both are now wired; no
code defects found during commissioning. Verified live: RLS/grants
unchanged (still service_role-write-only, `authenticated` INSERT
confirmed blocked via a committed transaction probe), old 18-arg RPC
overload genuinely dropped (not left ambiguous alongside the new one),
full material-claims round-trip fidelity (claim_id/claim_text/claim_type/
evidence_ids/support_status), idempotent reuse on identical fingerprint,
new immutable version on changed fingerprint with the prior row's claims
untouched, and a genuinely pre-019-shaped row (`material_claims` absent
from the insert) still returns the column default `[]` safely. A real,
disposable Anthropic drafting call (bid 1 / requirement M3, synthetic
Organizational Memory enrichment, deleted after) produced a correctly
distinguished mix in one draft — `ORGANIZATIONAL_KNOWLEDGE`/`SUPPORTED`
citing real evidence, `PROPOSED_APPROACH`/`COMMITMENT` claims with no
evidence required, and an `UNSUPPORTED_GAP` claim never marked supported
— proving the fail-closed reconciliation rules hold with real model
output, not just synthetic test fixtures. A poisoned-`_call_section_draft`
stub proved a second identical request is served entirely from the
persisted row (no drafting call) with material_claims byte-identical to
the first. UI smoke: `pages/section_drafting_workspace.py`'s real
`_render_draft_result`/`_render_claim` functions were executed directly
against the live persisted rows — the migration-019 draft (8 claims) and
a migration-018-shaped legacy row (no `material_claims` key populated) —
both rendered without exception; the legacy path exercises the existing
"No claim-level evidence mapping recorded" fallback caption. All
disposable rows deleted post-commissioning; zero residue confirmed.
Security advisors: 3 pre-existing findings (unrelated `model_usage_events`
RLS-no-policy, `can_access_bid`/`is_organization_member` SECURITY DEFINER
helpers, auth leaked-password-protection) — none attributable to
migration 019.

Tests: `tests/test_section_drafting.py` has `TestMaterialClaimMapping`
(12 tests — claim-to-valid-evidence-id mapping, unsupported claims never
verified, proposed-approach vs. historical-fact distinction, SOURCE_
MEMORY-only downgrade, APPROVED_FIRM_KNOWLEDGE/proposal-evidence
acceptance, unknown claim_type dropped, duplicate claim_id dedup, bounded
count, backward-compatible absence); `tests/
test_section_drafting_workspace.py` (12 — status-check behavior: no
draft/current/stale detection, no model call, no OM retrieval, no
auto-regeneration on staleness, prior immutable version still shown while
stale, bid-scoped isolation); `tests/test_section_drafts_persistence.py`
gained 2 more (material_claims round-trip fidelity across two identical
calls; claims persist correctly even when `evidence_ids` is empty) for 24
total. Explicitly still deferred: whole-proposal generation, a
collaborative editor, visual version diffing, Word export, automated SME
messaging, Ask CapOS, Red Team.

**PI-3D (AI-Assisted BUILD Workflow) is now implemented** — a product/UI
orchestration task, not a new domain phase: no new migration, no new
drafting architecture. Makes PI-3A/PI-3B/PI-3C's already-live, already-
commissioned evidence-aware drafting the PRIMARY BUILD experience instead
of a capability that existed but was never actually reachable in practice.

**Root cause (why PI-3C was live but not visible/useful from BUILD):**
two compounding defects, both pre-existing, neither introduced by PI-3A/
3B/3C themselves:
1. The PI-3C requirement drafting workspace was wired into `pages/
   stage_build.py`, but only inside the ACTIVE outline section's detail
   panel — reachable only after a user manually created a section first
   (the only offered action on an empty outline was "➕ Add Outline
   Section"), and even then it sat in a THIRD-level nested, collapsed-
   by-default expander ("🧠 Requirement Drafting Workspace (Bid
   Intelligence)", `expanded=False`) directly below a separate, more
   visually prominent (`type="primary"`, not in an expander) OLDER "✨
   Draft / Refine Section with Claude" button calling `analyst.
   draft_proposal_section` — a genuinely different, non-evidence-aware,
   non-persisted, non-claim-mapped drafting path with its own session-
   state-only draft text. A user had no reason to ever open the collapsed
   PI-3C expander when a more prominent AI button already sat right above
   the editor.
2. **A second, deeper, previously-undiscovered gap**: `migrations/
   013_section_analyzer.sql` (which creates `outline_section_requirements`
   and `section_reviews`) is written but **was never applied to any live
   database** (confirmed live via `information_schema.tables` during this
   task: only `outline_sections` exists; `outline_section_requirements`
   does not). This means the ENTIRE section-to-requirement mapping
   feature (the "🎯 Evaluation Criteria In View" multiselect, in
   production since before this series began) has never actually been
   able to persist a mapping for any bid with a real outline section --
   `tenancy.get_section_requirement_ids_authenticated`/`set_section_
   requirement_mapping_authenticated` would raise a raw PostgREST
   "relation does not exist" error the moment a user opened that
   expander on a section-bearing bid. It was invisible only because no
   bid in this environment happened to have both an outline section AND
   an attempt to map requirements to it before now. **This migration
   remains unapplied** -- applying it was out of this task's stated scope
   (UI orchestration only) and is not authorized by this task; a future
   "PI-3D Live Commissioning" task, mirroring this series' established
   write-then-commission pattern, should apply it. Until then, `tenancy.
   get_section_requirement_ids_authenticated`/`get_section_requirement_
   map_authenticated` degrade to an empty mapping and `set_section_
   requirement_mapping_authenticated` raises a new, distinctly-typed
   `tenancy.SectionMappingUnavailableError` (never a raw PostgREST
   traceback) -- the BUILD page shows an honest inline caption instead of
   crashing, and requirement-to-section mapping simply cannot persist
   across reloads yet. Drafting itself is unaffected: `render_requirement_
   drafting_workspace` falls back to the bid's full requirement list
   when no mapping is available, exactly as it already did before this
   task.

**Update, 2026-09-21: migration 013 is now live-commissioned** (see the
"Migration 013 Compatibility Audit" entry below for the audit and its
live-commissioning follow-up) — requirement-to-section mapping now
genuinely persists. The graceful-degradation behavior described above
(`SectionMappingUnavailableError`/empty-map fallback) is retained in the
code as a defensive fallback but is no longer triggered under normal live
operation, live-proved via a full `page_build(8)` render with zero
exceptions.

**Workflow changes** (`pages/stage_build.py`'s "Proposal Outline &
Section Drafter" tab only -- no other BUILD tab touched):
- A primary/secondary toggle ("🤖 AI-Assisted Build" / "✍️ Build
  Manually") at the top of the tab; AI-Assisted is the default whenever
  the bid has analyzed requirements, Manual is the default otherwise --
  every manual capability (add/edit/save/delete a section, map
  requirements, run the Section Analyzer) remains fully functional
  regardless of which is selected.
- Empty-state redesign (zero outline sections): when analyzed
  requirements exist, offers "🪄 Generate Proposal Structure" as the
  primary action (`proposal_outline.derive_outline_sections`) alongside
  "➕ Add Section Manually" (unchanged, always available); when no
  requirements exist yet, explains the upstream step (complete DECIDE-
  stage Fast Analysis first) instead of just showing an empty list.
- The generated structure is a PROPOSAL, never auto-committed: a review
  UI lets the user rename (text input), reorder (↑), remove (🗑), or add
  a blank section, then either "✅ Approve & Create Sections" (persists
  via the EXISTING `tenancy.upsert_section_authenticated`/`set_section_
  requirement_mapping_authenticated` -- no new table) or "❌ Cancel"
  (discards the proposal, nothing persisted). Outline generation and
  section drafting remain two separate explicit actions -- approving a
  structure never triggers drafting.
- The OLD "✨ Draft / Refine Section with Claude" button (`analyst.
  draft_proposal_section`, the competing non-evidence-aware path
  identified as the primary root cause above) is REMOVED from this page
  -- `analyst.draft_proposal_section` itself is untouched and still used
  elsewhere (`pages_extra.py`). PI-3C's `render_requirement_drafting_
  workspace` is now the SOLE AI drafting surface here, promoted out of
  its collapsed nested expander to a prominent, always-visible "🧠 Draft
  with BI — Evidence-Aware Section Drafting" section directly under a
  new intelligence summary card -- reused verbatim (instruction 6: "do
  not create a second drafting implementation"), never reproduced.
- New section-level intelligence rollup (`proposal_outline.
  summarize_section_intelligence`, pure): the section list shows "N
  reqs · M criteria · Evidence: <bucket>" per section; the active
  section's detail panel additionally shows unresolved-gap count and a
  draft-status rollup ("Not generated"/"Partially drafted"/"Drafted").
  Reuses existing canonical sources only -- `section_analyzer.
  _match_evaluation_criterion` (the SAME deterministic matcher PI-3A's
  own brief assembly uses) for evaluation-criteria mapping,
  `proposal_intelligence.ASSESSMENT_STATUSES`/`EVIDENCE_STRENGTH_VALUES`
  for the evidence-readiness bucket, `database.get_section_drafts` for
  draft existence -- never a parallel evidence/matching model.
- New `tenancy.get_build_intelligence_context_for_organization` (Category
  B, `require_bid_access` first) computes the criterion/assessment maps
  ONCE per bid (never once per requirement/section); new `tenancy.
  get_section_requirement_map_authenticated` (Category A) is the bulk
  equivalent of the existing per-section reader; new `tenancy.
  get_draft_existence_map_for_organization` (Category B) is a bounded,
  section-scoped, existence-only read (never the heavier fingerprint/
  staleness computation `get_section_draft_status_for_organization`
  performs). All three are read-only, NEVER call Anthropic, NEVER call
  `organizational_memory.retrieve()` -- proven via the poisoned-function
  technique in `tests/test_build_workflow_tenancy.py`, mirroring OM-3B/
  PI-3C's own "opening the workspace must not trigger expensive work"
  discipline.
- `tenancy.upsert_section_authenticated` now returns the section's id
  (existing on update, freshly assigned on insert) -- needed so the
  outline-approval flow can map requirements to a just-created section
  in the same script run; existing callers that ignored the return value
  are unaffected.

**No new drafting architecture**: `render_requirement_drafting_workspace`
is called from exactly one call site (proven by `tests/
test_build_workflow_ui.py::TestNoWholeProposalModelCall`, a structural
source-grep test), one requirement at a time, exactly as PI-3C built it --
no batch/whole-section/whole-proposal drafting call exists anywhere in
this task's changes.

Live-validated against the real Bank of Canada bid (bid_id=8, 98 real
requirements, 0 outline sections) with zero Anthropic calls: `tenancy.
get_build_intelligence_context_for_organization` and `proposal_outline.
derive_outline_sections` correctly proposed a 4-section structure
(Mandatory: 48 reqs, Rated: 39, Supporting: 10, Financial: 1) from the
bid's real requirement categories; a full `page_build(8)` render captured
via monkeypatched `st.button`/`st.markdown`/`st.expander` confirmed the
"🪄 Generate Proposal Structure" button and "BI has analyzed this RFP"
empty-state copy both actually appear, "➕ Add Section Manually" remains
available, and rendering raises no exception. Evaluation-criteria/
evidence-readiness rollups show 0/None for bid 8 specifically because its
only COMPLETE Fast Analysis run predates raw-snapshot persistence (`db.
get_analysis_result(run_id=1)` returns no row) -- a pre-existing data gap
already identical for PI-3A/PI-3B/PI-3C's own evaluation-criterion
matching on this bid, not a PI-3D defect; the rollup correctly shows
"None"/0 rather than fabricating a value.

Tests: `tests/test_proposal_outline.py` (28, pure -- category grouping,
determinism, bounding, evidence-readiness bucketing, rollup counting,
draft-status transitions, no-model-call-surface); `tests/
test_build_workflow_tenancy.py` (13 -- bid-access gating, no-Anthropic/
no-OM-retrieval proofs, migration-013-missing graceful degradation for
both the pre-existing per-section functions and PI-3D's new bulk one);
`tests/test_build_workflow_ui.py` (6 -- AI empty state offers generation,
manual Add Section always available, no-requirements state explains the
upstream step, AI drafting workspace actually invoked for a mapped
section, single call site / no whole-proposal call). Full existing
PI-3A/PI-3B/PI-3C suites (142 tests total across all PI-3 files) and the
whole-app smoke suite pass unchanged.

Explicitly NOT built (instruction 13): one-call whole-proposal
generation, Word export, collaborative editing, Red Team, Ask CapOS,
Arabic, SME messaging, a proposal template designer, visual draft diffs,
or any other BUILD redesign beyond this tab. Migration 013 was unapplied
at the time this task ran; it is now **applied and live-commissioned
2026-09-21** (see "Migration 013 Compatibility Audit" below) — a later,
separate task.

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
guardrails; no new migration, compute-and-return only this phase.
**PI-3B (durable section drafts, `migrations/018_section_drafts.sql`) is
now implemented AND live-commissioned** (migration 018 applied
2026-09-21) — persists PI-3A's result keyed by a deterministic input
fingerprint over PI-3A's own `SectionDraftingBrief`, and reuses it (no
drafting call, no OM retrieval, no RFP read, no reanalysis — live-proven,
not merely inferred) whenever the fingerprint is unchanged; identified
but did not close a claim-level traceability gap (draft-wide evidence
usage is tracked, sentence/claim-level citation is not — see the
Organizational Memory entry above for the full assessment). See that
entry for full detail on both PI-3A and PI-3B. **PI-3C (Section Drafting
Workspace, `pages/section_drafting_workspace.py` wired into
`pages/stage_build.py`) is now implemented AND live-commissioned**
(migration 019 applied 2026-09-21) — the first user-facing,
Phoenix-facing proposal-writing experience, and closes PI-3B's identified
claim-level traceability gap (`section_drafting.MaterialClaim`,
`migrations/019_section_draft_claim_mappings.sql`, live). See the
Organizational Memory entry above for the full commissioning detail
(round-trip fidelity, idempotency, backward compatibility, cache-hit
proof, live UI smoke, security advisors, cleanup). Deferred:
whole-proposal generation, a collaborative editor, visual version
diffing, Word export, Ask CapOS integration, Red Team, Section Analyzer
UI *redesign* (this phase integrates into it, not replaces it).

Absent an explicit task instruction otherwise, still do not: apply
migration 013, alter/reapply migration 015, 016, 017, 018, or 019,
activate the compact-wire prototype, change chunk sizes/max_tokens/model
routing/caching, or merge `main`/deploy.

## Migrations known in this repository (files, not live-database state)

Highest migration file present: **019**
(`019_section_draft_claim_mappings.sql`, **applied and live-commissioned
2026-09-21**, ledger entry `20260921163500 section_draft_claim_mappings`).
Migrations 017/018 (`017_requirement_evidence_enrichment.sql`/
`018_section_drafts.sql`) remain **applied and live-commissioned
2026-09-21**. Migration 013 (`013_section_analyzer.sql`) is also **applied
and live-commissioned 2026-09-21**, ledger entry `20260921182042
section_analyzer` — see "Migration 013 Compatibility Audit" below for
the audit and its live-commissioning follow-up. Files 001–019 exist in
`migrations/`. This describes what's
**written in the repo**, not
what's applied to any Supabase project — see the note below (which is the
current source of truth for live status; always verify explicitly rather
than trusting this sentence in isolation).

### Migration 013 Compatibility Audit (2026-09-21)

**Migration 013 (`013_section_analyzer.sql`) remains UNAPPLIED to any live
database — this audit did NOT apply it.** It creates two tables
(`outline_section_requirements`, `section_reviews`), both RLS-enabled,
both scoped via `public.can_access_bid(bid_id)` (the same helper every
bid-owned child table has used since migration 008) — no new function,
trigger, or RPC.

**Why it was likely skipped (inferred from git history, not documented
anywhere explicitly)**: authored 2026-09-20 in the same commit as the
Section Analyzer feature itself, immediately before this session's long
OM-1→OM-2→OM-3B→PI-1→…→PI-3D chain began. Every migration since (015
through 019) got its own dedicated live-commissioning task later in this
series; migration 013 (and, as this audit discovered, migration 012)
simply never did. Nothing in the code or history suggests it was found
broken or deliberately shelved — it reads as a backlog/sequencing gap,
not a technical block.

**Live dependency check (read-only, no live mutation)**: `bids`,
`outline_sections`, `requirements`, `analysis_runs`, `analysis_results`
all still have `bigint` primary keys (unchanged); `public.can_access_bid`/
`is_organization_member` still exist, still `SECURITY DEFINER`, still
`SET search_path = 'public'` (unchanged since migration 008 — no drift
that would reintroduce the search_path-hijacking class of defect this
repo already hardened once, in migration 011). No migration 014-019
alters `outline_sections`/`requirements`/`analysis_runs`/
`analysis_results`/`bids`/`can_access_bid`. No table/policy/index name
in migration 013 collides with anything currently live (`pg_policies`/
`pg_indexes`/`information_schema.tables` all confirm zero matches).
**Methodological note**: migration 012's own column
(`analysis_results.fast_analysis_result_snapshot`) was found to exist
live even though "012"/"fast_analysis_result_snapshot" never appears in
`list_migrations`' ledger — proof the ledger is NOT authoritative for
"is this applied," only `information_schema`/direct schema inspection is
(reinforces this repo's own standing rule, doesn't contradict it).

**Application-code alignment**: `database.create_section_review`'s write
keys and `section_analyzer.DIRECTIONS`' CHECK-constraint values are a
byte-for-byte match with migration 013's columns/constraint (verified via
`tests/test_migration_013_audit.py`, added this task) — the code was
written in lockstep with this migration and has never drifted since.
`outline_section_requirements` is still the correct, still-current
canonical model for durable section↔requirement mapping (PI-3A/PI-3B/
PI-3C's own drafting brief deliberately has NO dependency on it, by
design — see `tenancy._assemble_section_drafting_brief`'s docstring — so
nothing in that later architecture makes this table obsolete). PI-3D's
new BUILD outline workflow is a consumer, not a replacement: its own
`get_section_requirement_map_authenticated`/`get_draft_existence_map_for_
organization` read through the exact same table/columns migration 013
defines.

**Security finding (one, now fixed in the source file)**: `section_
reviews_insert_bid_access` granted `authenticated` INSERT rights that
application code never actually used (`database.create_section_review`
always writes via the service-role client, after `analyze_section_for_
organization`'s own `require_bid_access` + model-call gate) — an unused
policy that still let any bid-authorized user forge an arbitrary
`section_reviews` row directly via the REST API (fabricated `direction`/
`review_result`/`based_on_*` provenance, bypassing the model call and
idempotency check entirely). This is exactly the gap migrations 015-019
already closed for every other model-call-produced structured output
("RLS enabled, authenticated read-only, service-role-only write, no
authenticated write policy at all"). **Fixed directly in the still-
unapplied migration file** (editing an unapplied migration in place is
this repo's own established convention — a LIVE migration is instead
superseded by a new numbered file, e.g. migration 019 modifying 018's
RPC): `section_reviews_insert_bid_access` removed; `section_reviews` is
now SELECT-only for `authenticated`, matching the modern pattern exactly.
`outline_section_requirements`'s select/insert/delete policies are
UNCHANGED — that table genuinely IS written via the authenticated
RLS-scoped client (Category A, no model call), matching `outline_
sections`' own full-CRUD policy from migration 008, so its existing
policy set already matched its real access pattern and needed no change.

**Final classification: SAFE WITH SOURCE FIXES.** The one identified fix
(removing the unused `section_reviews` INSERT policy) is applied to
`migrations/013_section_analyzer.sql` in place; no other change is
needed. **Recommended commissioning procedure** (mirroring this series'
own established pattern, e.g. migrations 016-019): a SEPARATE, later,
explicitly-authorized task should (1) apply the now-fixed migration 013
live via the Supabase dashboard/SQL editor, (2) verify RLS/policies live
exactly as written (a committed `authenticated` INSERT-into-`section_
reviews` probe should be REJECTED, proving the fix took effect — this is
a NEW verification this audit could not itself perform without applying
the migration), (3) run one synthetic round-trip on `outline_section_
requirements` (map a section to a requirement via the real UI/tenancy
path, confirm PI-3D's BUILD section list rollup now shows a real
requirement count instead of the graceful-degradation empty map, confirm
`tenancy.SectionMappingUnavailableError` no longer raises), (4) run one
synthetic Section Analyzer review end-to-end (confirms `section_reviews`
insert-via-service-role and the idempotency index both work against the
live table), (5) clean up all disposable rows, (6) update SYSTEM_STATE.md/
NAVIGATION.md to mark migration 013 live. Until that task runs, `tenancy.
get_section_requirement_ids_authenticated`/`get_section_requirement_map_
authenticated` continue to degrade to an empty mapping and `set_section_
requirement_mapping_authenticated` continues to raise `tenancy.
SectionMappingUnavailableError` (PI-3D's own graceful-degradation
behavior, unaffected by this audit).

**Update, 2026-09-21 (Migration 013 Live Commissioning): migration 013 is
now APPLIED AND LIVE-COMMISSIONED**, formally recorded in Supabase's
migration ledger as `20260921182042 section_analyzer`. Schema verified
directly (not via the ledger) to match the file exactly: both tables'
columns/types, all 5 FKs (`ON DELETE CASCADE` on bid/section/requirement,
`ON DELETE SET NULL` on the two analysis-run/result links), the PK/unique
constraint, the `direction` CHECK constraint, all 8 indexes (including
the idempotency index), RLS enabled on both tables, and the exact 4-policy
set the audited source now defines (`outline_section_requirements`:
authenticated select/insert/delete; `section_reviews`: authenticated
select ONLY — no insert/update/delete policy at all). Security probes via
real role-switched, **committed** transactions (not rolled back) proved:
the authorized bid-owning user can select/insert/delete on `outline_
section_requirements` and select-only on `section_reviews`; an
unaffiliated `authenticated` user (this project has only one real
organization, so cross-org access was simulated via an `auth.uid()` with
no `organization_members` row — the same predicate `is_organization_
member` evaluates for a genuinely different org) and `anon` were both
rejected on every operation against both tables; critically, a direct
`authenticated` INSERT into `section_reviews` — the audit's own fix — was
rejected live (`new row violates row-level security policy`), and no
role (including the authorized owner) can UPDATE/DELETE a `section_
reviews` row at all, confirming genuine immutability. FK integrity
confirmed: mapping to a nonexistent requirement_id is rejected
(`23503`). One genuine, narrow **integrity gap** found and accepted as a
documented limitation, not fixed: `outline_section_requirements` has no
DB-level check that `requirement_id`'s own bid matches the mapping row's
`bid_id` — a bid-authorized user could theoretically insert a row
pointing `bid_id=1` at a requirement that actually belongs to a different
bid. This requires already having legitimate write access to the row's
OWN `bid_id` (no privilege escalation, no content exposure — only an
opaque foreign id reference), is never reachable through the real
application code path (the UI/tenancy layer only ever offers same-bid
requirement options), and matches this schema's own established pattern
of trusting application-layer consistency across joined FKs elsewhere
(no other "mapping" table in this schema enforces cross-FK bid
consistency via a DB trigger either) — adding one would be a genuinely
new mechanism, out of scope for commissioning an existing design.
Live-proved via the REAL application code paths (no separate
commissioning path invented): `tenancy.get_section_requirement_ids_
authenticated`/`set_section_requirement_mapping_authenticated`/`get_
section_requirement_map_authenticated` (PI-3D's bulk reader) round-trip
correctly (read → replace-all modify → replace-all modify again → bulk
read agrees) against bid 1; `tenancy.analyze_section_for_organization`
(ONE real, bounded Anthropic call, synthetic disposable text) persisted a
genuine `section_reviews` row, a second identical call reused it
idempotently (a poisoned `section_analyzer._call_section_analyzer` proved
zero second model call), and the authenticated read path saw it. PI-3D
BUILD integration re-verified on the real Bank of Canada bid (bid 8): one
disposable section created and mapped to 2 real requirements via the real
tenancy path, persisted correctly across a fresh read ("reopening BUILD"),
`section_analyzer.build_section_context` consumed the mapping without
error, and a full `page_build(8)` render completed with zero exceptions
and zero `tenancy.SectionMappingUnavailableError` — the graceful-
degradation path added during PI-3D now sits **unused in normal live
operation**, retained purely as defensive fallback (e.g. a future
environment where 013 genuinely isn't applied yet), not removed. Security
advisors re-checked post-commissioning: same 3 pre-existing findings as
before (`model_usage_events` RLS-no-policy, `can_access_bid`/`is_
organization_member` SECURITY DEFINER, auth leaked-password-protection)
— zero new findings attributable to migration 013, confirming the fix
introduced no regression. All disposable rows (2 `outline_sections`, their
cascaded `outline_section_requirements`/`section_reviews` children) were
deleted; verified zero residue and the original 24 legitimate `outline_
sections` rows fully intact. No further code changes were required this
pass — the audit's one fix was already correct as commissioned.

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
> cleaned up, verified zero residue. Migration 018 (Section Drafts, PI-3B)
> was written on 2026-09-21 and **applied live on 2026-09-21**, formally
> recorded in Supabase's migration ledger as `20260921155315
> section_drafts`. Live PI-3B commissioning also passed on 2026-09-21:
> schema/RLS/constraint/grant verification (including a committed
> `authenticated` UPDATE/DELETE probe proving zero rows affected and a
> real row left byte-for-byte unchanged); RPC persistence/idempotency/
> round-trip fidelity across every field; malformed-payload (empty
> `draft_text`) rejection with zero rows written; a changed fingerprint
> creating a genuinely new immutable row while the prior row remained
> untouched; an assurance-failed draft persisting correctly and distinctly
> from an assurance-passed one; and a genuinely live end-to-end run
> through `tenancy.get_or_generate_section_draft` in which a second
> identical call succeeded with `section_drafting._call_section_draft`
> temporarily replaced by a function that raises if invoked at all
> (proving the cache hit never calls Anthropic), and a third call after
> replacing the persisted OM-3B enrichment produced a new fingerprint, a
> new row, and a genuine new drafting call (proving OM-enrichment-change
> invalidation). No defect was found this commissioning pass — no code
> change was required. All disposable rows (2 section_drafts, 2
> requirement_evidence_enrichments) cleaned up, verified zero residue.
> Migration 019 (Section Draft Claim Mappings, PI-3C) was written on
> 2026-09-21 and is **NOT applied to any live database** — this task's own
> instruction explicitly excluded applying it. It modifies migration 018's
> ALREADY-LIVE `get_or_create_section_draft()` RPC signature (adds
> `p_material_claims`), so — unlike every earlier migration in this series
> — the application code was deliberately NOT wired to call the new
> parameter yet (`database.get_or_create_section_draft`/`tenancy.
> get_or_generate_section_draft` still call the RPC exactly as migration
> 018 defined it): wiring that parameter back in must ship together with
> migration 019's own future commissioning task, never ahead of it, or
> every live call to `get_or_generate_section_draft` would break
> immediately with a "no matching function" error. Treat any future "is
> migration N live" question as requiring a fresh check — `git log` and
> this file are not a substitute for checking the live database when a
> task depends on it.
>
> **Update, 2026-09-21 (later the same day):** Migration 019 (Section
> Draft Claim Mappings, PI-3C) was **applied live**, formally recorded in
> Supabase's migration ledger as `20260921163500
> section_draft_claim_mappings`. The deferred wiring step described just
> above is now complete: `database.get_or_create_section_draft`/`tenancy.
> get_or_generate_section_draft` pass `material_claims`/`p_material_claims`
> for real. Schema/RPC verification: the `material_claims jsonb not null
> default '[]'::jsonb` column exists with the correct type/default, all
> migration-018 columns/PK/unique/FK/index/RLS policy unchanged, the old
> 18-arg RPC overload was genuinely dropped (not left ambiguous alongside
> the new 19-arg one), grants remain service_role/postgres-only (a
> committed `authenticated` INSERT probe confirmed still blocked). RPC-
> level commissioning: full material-claims round-trip fidelity, identical-
> fingerprint idempotent reuse, changed-fingerprint immutable new version
> with the prior row's claims untouched, a pre-019-shaped insert (no
> `material_claims` supplied) reading back the column default `[]` safely.
> Python-level end-to-end commissioning via the real `tenancy.
> get_or_generate_section_draft` (bid 1 / requirement M3, a disposable
> synthetic Organizational Memory enrichment): one real, live Anthropic
> drafting call produced 8 material claims with correctly distinguished
> types/statuses (an `ORGANIZATIONAL_KNOWLEDGE`/`SUPPORTED` claim citing
> real evidence, five `PROPOSED_APPROACH`/`COMMITMENT` claims, one
> `PARTIALLY_SUPPORTED` claim, one `UNSUPPORTED_GAP` claim never marked
> supported) — live proof the fail-closed reconciliation rules hold
> against real model output. A second identical call, with `section_
> drafting._call_section_draft` temporarily replaced by a function that
> raises if invoked, returned `reused: True` with byte-identical
> material_claims (proving the cache hit never calls Anthropic). UI smoke:
> the real `_render_draft_result`/`_render_claim` functions in `pages/
> section_drafting_workspace.py` executed against the live persisted M3
> draft (8 claims) and a migration-018-shaped legacy row (no
> material_claims) without exception. Security advisors: 3 findings, all
> pre-existing and unrelated to migration 019 (`model_usage_events`
> RLS-no-policy, `can_access_bid`/`is_organization_member` SECURITY
> DEFINER, auth leaked-password-protection) — no fix required. No code
> defects found this commissioning pass. All disposable rows (3
> section_drafts, 1 requirement_evidence_enrichments) cleaned up, verified
> zero residue.

## Where NOT to look first

Do not begin ordinary task orientation by reading the ~99 root-level
`.md` files. Most are historical operational records (implementation
reports, commissioning reports, remediation reports) describing *completed
past work*, not current authoritative architecture. See
[NAVIGATION.md](NAVIGATION.md) and
[ROOT_DOC_INVENTORY.json](ROOT_DOC_INVENTORY.json) before reading any of
them.
