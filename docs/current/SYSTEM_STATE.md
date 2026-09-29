# System State

The smallest current-state snapshot a fresh agent needs. Not a history, not
an architecture explanation — see [NAVIGATION.md](NAVIGATION.md) for where
to read either of those when a task actually requires them.

## Product lifecycle

`UNDERSTAND → DECIDE → BUILD → CHECK → SUBMIT`

## UNDERSTAND customer export

**Bid Intelligence Brief** is the primary customer-facing UNDERSTAND export.
It is a concise, normally 6-8-page (preferred maximum 10) selection over a
completed Fast Analysis raw snapshot, not a new analysis mode: rendering is
deterministic and requires zero provider/model calls. The historical long
Fast Analysis PDF remains available as the secondary **Full Intelligence
Appendix**.

The Brief has a strict presentation boundary: `understand_brief.py` is pure
selection/reconciliation and `understand_brief_report.py` is ReportLab-only
presentation. It never changes canonical procurement truth, Fast Analysis
prompts, provider architecture, an existing run, or database schema. The
model fails before export when a real opportunity title is not available;
appendix/form/proponent-acknowledgement titles are not accepted as the tender
identity. Scope appears only from positive source-supported scope items;
ordinary response verbs cannot become customer-facing service categories.
Submission mechanics exclude post-award invoice/payment noise, while material
contract terms can remain commercial watch-outs. Priorities are bounded and
fact-led rather than severity-score-led; source ambiguities remain
clarification questions.

The attached City of Calgary 26-1610 revised Brief is the authoritative
customer-facing structure and visual benchmark: restrained black/warm-gold
Letter presentation, source fact distinct from interpretation, and the six
sections (snapshot, scope, evaluation, submission, commercial, priorities).
It is a semantic benchmark, not a Calgary-specific code path. Acceptance of a
real 26-1610 durable run and a second real procurement still requires the
respective completed raw snapshots to be available; no synthetic fixture is
treated as that commissioning evidence.

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

### Fast Analysis v4 Calgary remediation (2026-09-29)

The authorized remediation pass added deterministic, provenance-preserving
capture for explicit budget, annual/session volume, objective bullets, and
timetable rows, and made Appendix C criterion prompts complete (the historical
1,500-character threshold is now informational only; the full passage is
retained). Deterministic fixtures pass. Run 45 remains immutable. The single
authorized real follow-up is run 47 over the exact same five-document corpus;
its snapshot contains the budget/volume/timetable facts and complete Firm and
Service Delivery prompts, but fails closed because the split-line
“Team Experience and Qualifications –” / “Weight (10 %)” heading was not
recognized in that run. A local parser repair covers that boundary, but no
second real provider run is authorized, so the Calgary remediation is not
commissioned as PASS and no report/export re-render was performed.
- **Buyer Intelligence** — external, advisory context attached to a
  `FastAnalysisResult`, always kept visibly separate from procurement
  requirement facts in every consumer.
- **BUILD workspace** (`pages/stage_build.py`) — Proposal Outline & Response
  Intelligence. **Product boundary: Bid Intelligence no longer generates
  proposal narrative** (see "Product boundary reversal" below) — BUILD
  surfaces requirements-to-section mapping, evaluation criteria, evidence
  and gaps (`pages/section_response_brief.py`'s
  `render_requirement_response_brief`), and manual section authoring; it
  never writes the response.
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

**PI-3D1 (Intelligent Proposal Outline Architecture) is now implemented**
— replaces PI-3D's original "group requirements by their own
Mandatory/Rated/Supporting/Financial classification" outline generator
(a requirement CLASSIFICATION scheme, not a proposal architecture) with a
three-tier derivation hierarchy in `proposal_outline.py`, reusing
already-persisted intelligence throughout — no new RFP-interpretation
model, no new migration.

**Derivation hierarchy** (in order of authority, never overridden by a
lower tier):
- **Tier 1 — `EXPLICIT_RFP_STRUCTURE`**: reads ONLY already-persisted
  `analysis_results.structured_intelligence` (built by
  `fast_analysis_app_adapter.build_opportunity_intelligence`, never re-
  derived here). `extract_explicit_sections_from_structured_intelligence`
  turns `evaluation.weights_by_category` — the RFP's OWN evaluation table
  already grouped under its own buyer-stated response-category headings,
  with real per-criterion weights — directly into proposal sections, one
  per category, requirements mapped inline via `section_analyzer.
  _match_evaluation_criterion` (reused, not reimplemented).
  `extract_pricing_section`/`extract_submission_form_section` add
  standalone Pricing / Required-Forms sections from `pricing_and_
  commercial`/`response_requirements.checklist` when present.
  `extract_mandatory_requirements_section` groups pass/fail mandatory
  gate requirements (signatures, bilingualism confirmations, security-
  clearance confirmations, qualification thresholds) that never appear in
  a scored criteria table, justified by the RFP's own `evaluation.
  stages` process split (Stage 1/2 pass/fail vs. scored) — this single
  addition was the difference between 12/98 and 59/98 requirements mapped
  on the real validation bid, since these ARE genuinely different from
  "orphaned," not a matching failure.
- **Tier 2 — `DETERMINISTIC_DERIVATION`**: when Tier 1 yields nothing,
  clusters requirements by whichever evaluation criterion/heading they
  deterministically match (same matcher, reused) — never the bare
  category label as the primary axis. Only when there is no evaluation
  signal at all does this fall back to the OLD PI-3D category-grouping
  (`derive_outline_sections`, kept, not removed — still correct for a bid
  with no Fast Analysis evaluation intelligence yet).
- **Tier 3 — `MODEL_REFINEMENT`**: ONE bounded model call
  (`proposal_outline._call_outline_refinement`/`refine_outline_with_
  model`, same injectable-`call_fn`/telemetry pattern as `section_
  drafting._call_section_draft`), gated by `needs_model_refinement`
  (fewer than 2 sections, or fewer than half of active requirements
  mapped) — never unconditional. Prompt (`build_outline_refinement_
  prompt`) contains ONLY candidate sections, bounded requirement
  summaries, evaluation-criteria summaries, and submission constraints —
  never the raw RFP, Organizational Memory, or a proposal draft. A Tier-3
  failure leaves the deterministic Tier 1/2 result completely untouched.

**Requirement coverage** (instruction 4) is deterministic and exhaustive:
every active requirement is either mapped to a section or explicitly
classified via `classify_unresolved_requirement` into one closed
vocabulary (`SUBMISSION_FORM_REQUIREMENT`/`COMMERCIAL_RESPONSE_ITEM`/
`APPENDIX_SUPPORTING_ITEM`/`NON_RESPONSE_INFORMATIONAL`/`UNRESOLVED`) —
never silently dropped. `_coverage_summary` exposes mapped/orphaned/
unresolved counts and `is_ready` (False while ANY orphaned Mandatory-
category requirement remains classified `UNRESOLVED`).

**Evaluation coverage** (instruction 5): `evaluation_criteria_coverage`
reports which section(s) each criterion maps to and any uncovered
criterion; `surface_high_weight_structural_warnings` flags a criterion
meeting a points threshold (default 20) that shares a section with 3+
other criteria — using ONLY weight numbers already present in the RFP's
own `weights_by_category` data (`criteria_weights`), never an invented
score. Real result on the Bank of Canada bid: 5 such notes (e.g.
"Methodology and Advisory Approach" at 35 points bundled with 6 other
criteria under one Category-D2 section) — genuinely useful, source-
grounded prompts for the writer, not fabricated analysis.

**UI** (`pages/stage_build.py`): "🪄 Generate Proposal Structure" now
calls `tenancy.derive_proposal_outline_for_organization` (new, Category
B) instead of the old bare category grouping. The review UI shows a
coverage banner (mapped/unresolved/ready-or-not, with an explicit warning
naming the orphaned-mandatory count), a structural-prominence-notes
expander, and each section's own rationale — still fully rename/reorder/
remove/add-able, still never auto-persisted (approve/cancel unchanged).
Removing a section now warns how many requirements it was covering
become unmapped. Approval persists exactly as before — `tenancy.
upsert_section_authenticated`/`set_section_requirement_mapping_
authenticated`, the same migration-013-backed Category A functions PI-3D
already used; no new mapping path.

**Bank of Canada validation result** (real bid_id=8, 98 requirements, 0
Anthropic calls needed): 6 sections — "HR Advisory (Form D2)" (9 reqs, 7
criteria, 75 pts), "Learning & Development (Form D1)" (8 reqs, 7 criteria,
75 pts), "Facilitation & Team Effectiveness (Form D3)" (5 reqs, 6
criteria, 100 pts), "Pricing" (1 req), "Required Forms & Submission
Documents" (0 reqs, 9 checklist items), "Mandatory Submission
Requirements & Qualifications" (47 reqs) — all genuinely bid-specific
titles, NONE of them "Mandatory"/"Rated"/"Supporting"/"Financial". 59/98
requirements mapped; the remaining 39 are ALL explicitly classified
(22 `UNRESOLVED`, 10 `APPENDIX_SUPPORTING_ITEM`, 5 `COMMERCIAL_RESPONSE_
ITEM`, 2 `SUBMISSION_FORM_REQUIREMENT`) — zero silently dropped, zero
orphaned Mandatory requirements, `is_ready=True`, `derivation_method=
EXPLICIT_RFP_STRUCTURE`, `needs_model_refinement=False`. Live-verified
via a poisoned `config.execute_messages_create` (never raised) that
deterministic derivation alone was sufficient for this bid, and via a
full `page_build(8)` render with the resulting outline pending review
(preview mode only — Approve never clicked, nothing persisted).

**Defect found and fixed during this task**: `_PRICING_KEYWORDS`'
substring matching false-positived "rate" inside "corpoRATE" (and
similarly risky for "form" inside e.g. "inFORMation") — a Corporate-
Profile-matched requirement was being miscounted into the Pricing
section. Fixed with a shared `_contains_keyword` word-boundary regex
helper, applied everywhere a keyword list is checked against free text;
caught by a dedicated test and confirmed corrected against the live Bank
of Canada data (Pricing section now correctly shows exactly the 1
genuine Financial-category requirement, not 2).

Tests: `tests/test_proposal_outline_intelligent.py` (39, pure — explicit-
structure precedence, deterministic clustering, coverage/orphan
detection, classification, evaluation-coverage/structural-warning logic,
Tier-3 gating and prompt-boundedness with an injected `call_fn`, fail-
closed reconciliation); `tests/test_build_workflow_tenancy.py` gained 4
(bid-access gating, zero-Anthropic proof when sufficient, exactly-one-
bounded-call proof when insufficient, section-drafting-model-never-
called proof); `tests/test_build_workflow_ui.py` gained 3 (generation
stores the derived outline, approval persists via the existing functions,
manual Add Section remains available with a proposal pending). Full
PI-3/PI-3D/PI-3D1/Section-Analyzer suite (250 tests) and whole-app smoke
pass unchanged.

Explicitly NOT built (instruction 14): whole-proposal generation, section
prose generation changes, new evidence architecture, new OM work, Word
export, collaborative editing, Ask CapOS, Red Team, Arabic support, a
proposal template designer, visual version diffing.

**Full-Package Analysis Integrity Remediation is now implemented**
(2026-09-22) -- corrects five real analysis-quality defects a full-
package run of the Bank of Canada RFP exposed, entirely inside the FAST
ANALYSIS engine (`fast_analysis.py`) and its report/structured-
intelligence rendering layer (`fast_analysis_app_adapter.py`, `scripts/
fast_analysis_report_adapter.py`, `scripts/build_boc_bid_intelligence_
preview_pdf.py`) -- no new migration, no live migration touched, no new
domain model beyond what the defects genuinely required.

**Two new pure, deterministic, no-Anthropic-call modules** -- deliberately
split along the SAME boundary this task's multi-agent-readiness framing
asks for (see below):
- `document_provenance.py` -- CANONICAL SOURCE LAYER. `classify_document_
  relationships` (Defect E): filename-pattern classification (CANONICAL/
  AMENDS/AMENDED_BY/SUPERSEDES/SUPERSEDED_BY/DUPLICATE_REPRESENTATION/
  REDUNDANT_DERIVATIVE/TRANSLATION_EQUIVALENT/INDEPENDENT_SOURCE), never
  inferring legal precedence beyond what an `Amendment1/`/`OriginalRevision/`
  directory or a "REVISED" filename marker itself states; defaults to
  INDEPENDENT_SOURCE (fails conservatively) rather than guessing. Found
  and fixed one real bug during live validation: short letter+digit
  identifiers ("D1"/"D2"/"C1"/"C2") were being dropped by the shared
  >=4-character word filter, so two genuinely DIFFERENT appendices
  ("Appendix C1"/"Appendix C2") shared enough generic wording to falsely
  cross the similarity threshold -- fixed with an explicit "disjoint
  short-identifier sets are never similar" guard, live-reverified against
  the real 32-document Bank of Canada corpus. `assess_package_
  completeness` (section 8): a bounded, deterministic warning
  ("Possible incomplete procurement package...") when no IDENTITY-family
  signal plus a substantive requirements/evaluation body was found
  alongside appendix/addendum-shaped filenames -- never blocks analysis.
- `procurement_normalization.py` -- CANONICAL PROCUREMENT INTELLIGENCE.
  `extract_criterion_response_prompts` (Defect A): deterministic
  "criterion label as its own heading, followed by prose" segmentation --
  a SECOND, independent deterministic convention alongside the existing
  `extract_response_guideline_sections`' "Response Guideline N | ..."
  table convention, never a replacement or a new evaluation model. Live-
  verified against the REAL Appendix D1/D2/D3 documents: 7/7, 5/7, 4/6
  criteria respectively captured with their real, buyer-written response
  instructions, zero LLM calls. `canonicalize_requirements` (Defect B):
  Tier 1 exact-normalized-text match (`requirement_semantics.
  normalize_requirement_identity_text`, reused) + Tier 2 near-duplicate
  match (`scripts.fast_analysis_report_adapter._is_near_duplicate`/
  `_fuzzy_word_set`, reused, the SAME primitive already used for
  qualification-mechanism/tie-break-rule collapsing) -- bounded to
  same-`category` candidate pairs only (never all-vs-all across the
  corpus), entirely deterministic (no model call). `canonicalize_
  milestones` (Defect C): groups by (scope, near-duplicate label,
  overlapping date window) -- an exact ISO date and a "Week of <Month>
  <Day>" mention of the SAME category-scoped event collapse to one
  canonical milestone with every original wording/source ref preserved;
  a genuinely different date, or an unparseable one, is NEVER merged
  (surfaces as a distinct `ambiguity_state` instead of a false dedup).
  `derive_category_scope_summaries` (Defect D): the ACTUAL root cause of
  "Not stated in the extracted data" under each service category was
  `scripts/fast_analysis_report_adapter.py`'s `_service_category_rows`
  requiring the category's own label to appear VERBATIM inside a
  requirement's description -- almost never true. Fixed by falling back
  to that category's own criteria's captured response prompts (Defect A)
  and any enumerated service-scope items, both already source-grounded
  -- never a summary invented from the category title alone.
- One real bug found and fixed in requirement-classification keyword
  matching too, while wiring these modules together: plain `in` substring
  checks for pricing/form/informational keywords false-positived ("rate"
  inside "corpoRATE") -- fixed with a shared word-boundary
  `_contains_keyword` helper (mirrors PI-3D1's own identical fix for the
  same class of bug).

**Wiring** (`fast_analysis.py`'s `run_fast_analysis_corpus`, step 5, after
all extraction/aggregation completes): `deterministic_criterion_response_
prompts`/`canonical_milestones`/`document_relationships`/`package_
completeness` are new `FastAnalysisResult` fields (raw-snapshot schema
MINOR-bumped to 1.1, purely additive, `deserialize_fast_analysis_result`
already tolerates unknown/missing fields across the same MAJOR version);
`result.requirements` is canonicalized IN PLACE (same field/shape, three
new keys added: `source_variants`/`source_docs`/`source_refs_all`/
`duplicate_count`) so every existing downstream consumer sees de-
duplicated requirements automatically, with zero opt-in wiring. `fast_
analysis_app_adapter.build_opportunity_intelligence` threads
`response_prompt`/`response_prompt_truncated` onto each `evaluation.
raw_occurrences` entry, adds top-level `package_completeness` and
`source_map.document_relationships`, and uses `canonical_milestones` for
`dates_and_mechanics.raw_date_observations` when available. `scripts/
fast_analysis_report_adapter.py`'s `_rg_evidence_map`/`_service_category_
rows`/`KEY_DATES`/`_source_documents` were extended (never replaced) with
these as ADDITIONAL fallback sources, in priority order, always keeping
`_NOT_EXTRACTED` as the final, honest fallback. `scripts/build_boc_bid_
intelligence_preview_pdf.py` (the shared PDF renderer every bid's report
uses, despite its Bank-of-Canada-era name) gained one new prominent
banner, rendered FIRST on the body pages, for `PACKAGE_COMPLETENESS_
WARNING` when present.

**FAST vs FULL analysis contract (section 9)**: no new analysis mode was
built -- `analysis_runs.analysis_mode` remains FAST-only in practice
(free-text column, no `COMPREHENSIVE`/`FULL` value ever populated). This
remediation genuinely improves FAST mode's OWN coverage guarantees
(deduplicated requirements/milestones, criterion-level requested-evidence
capture, category scope derivation, document-relationship/completeness
awareness) without making it read every document exhaustively -- the
`VALIDATION_FOOTER_NOTE` disclaimer was updated to state the new
guarantees honestly (deduplication/cross-referencing) while still
correctly calling itself "a narrowed, targeted extraction pass rather
than an exhaustive reading of every document." A genuine FULL/
comprehensive-coverage mode remains unbuilt; building one was explicitly
out of this task's scope ("do not implement an unnecessarily expensive
full-corpus workflow").

**Multi-agent readiness** (the user's own mid-task architecture
constraint): the two new modules' boundary is a DELIBERATE preview of the
four-layer structure a future multi-agent phase would need:
- CANONICAL SOURCE LAYER (`document_provenance.py`) and CANONICAL
  PROCUREMENT INTELLIGENCE (`procurement_normalization.py`) are already
  separate files with zero cross-imports between them -- a future
  "procurement/document structure" specialist would own exactly the
  first; a future "evaluation criteria and requested evidence"/"schedule/
  submission mechanics"/"SOW/scope/deliverables" specialist would each
  own one function group inside the second (`extract_criterion_response_
  prompts`, `canonicalize_milestones`, `derive_category_scope_summaries`
  respectively already have NO shared mutable state between them beyond
  read-only input).
- `canonicalize_requirements` is closest to a future "requirements/
  compliance" specialist's own concern, and is the one function among the
  four most likely to eventually need a genuine bounded LLM call (cross-
  language/deep-paraphrase duplicate detection -- explicitly deferred
  this task, see below) -- it is already isolated enough to become that
  specialist's own reconciliation step without touching the other three.
- Both modules share exactly ONE dependency
  (`scripts.fast_analysis_report_adapter._fuzzy_word_set`/
  `_is_near_duplicate`) -- a shared, stateless, pure primitive, not a
  shared mutable data structure -- so parallelizing these into
  independent specialist passes later requires no coordination beyond
  each one reading the same already-persisted `FastAnalysisResult`/
  `structured_intelligence`; nothing here holds a lock, a session, or
  in-process state across calls.
- What must remain CENTRALIZED even after a future multi-agent split:
  `fast_analysis.py`'s own step-5 orchestration order (Defect A's known-
  criterion-labels must exist before criterion-response-prompt extraction
  can run; Defect D's category summaries depend on Defect A's captured
  prompts) -- a RECONCILIATION/ASSURANCE layer coordinating specialist
  outputs' dependencies is still necessary, this task did not eliminate
  that need, only kept today's version of it small and in one place.
- No architectural blocker was found preventing a later multi-agent
  phase from building on this split -- the remaining work for that phase
  is orchestration (dispatching to N specialists and reconciling their
  outputs), not restructuring these two modules again.

**Explicitly deferred / out of scope for this task**: a genuine FULL/
comprehensive analysis mode; cross-language (e.g. EN/FR) duplicate-
requirement detection (deterministic dedup here correctly, conservatively
keeps a bilingual restatement pair as two separate, fully source-
traceable rows rather than guessing a translation-equivalence it cannot
verify -- see `TestBilingualRequirementHandling`); Section Analyzer/
SectionDraftingBrief wiring of `deterministic_criterion_response_prompts`
via the ADVISORY raw-snapshot path specifically (the structured_
intelligence path IS wired; the raw-snapshot path exists on the new
dataclass field and its serialization but bid 8 itself has no raw
snapshot to verify against, so this wiring was deferred rather than
shipped unverified); sub-parsing a captured response prompt into finer
categories ("required examples" vs. "required personnel evidence" vs.
"methodology description") -- the verbatim prompt already contains all of
these inline, and further splitting risked misclassifying real buyer text
via a naive heuristic.

**Live validation against the real Bank of Canada bid** (bid_id=8, 32
real documents, zero new Anthropic calls -- reused already-persisted
structured_intelligence plus direct, cheap file downloads of the 3 real
Appendix D documents): all 5 defects confirmed fixed against real data
(see the final report for the full before/after). A full re-run of Fast
Analysis's own 30-document extraction pass (a real, expensive multi-call
LLM operation) was deliberately NOT performed -- "do not repeatedly
regenerate expensive analysis while debugging if a smaller fixture can
prove the behavior first" (task's own instruction); each new function was
instead validated directly against real inputs assembled from already-
persisted data and cheap file downloads, which is sufficient to prove
correctness without spending a new expensive run.

No migration was required -- every new field lives inside the already-
JSON `structured_intelligence`/`report_content_snapshot` columns (via the
raw-snapshot dataclass's own additive-field convention), never a new
table or column.

Tests: `tests/test_document_provenance.py` (14), `tests/test_procurement_
normalization.py` (33, including the bilingual-handling regression),
`tests/test_fast_analysis_remediation_report.py` (11, report-rendering
wiring). Full existing fast_analysis/report-adapter/app-adapter/PI-3/
Section-Analyzer/migration-013 suites re-run and pass unchanged (zero
regressions) -- 2987 passed, 2 skipped (pre-existing) full-suite total.

### CI-1: Typed & Scoped Canonical Procurement Intelligence (2026-09-22)

Hardening of the shared canonical procurement model so that every future
specialist analyzer consumes the same correctly **typed**, **scoped** and
**authority-aware** source of truth. A correctness task, not a
report-cosmetics one: no report string was patched; the canonical model
was corrected and the report improved as a consequence. **No multi-agent
system was built.** No migration — every new field rides inside the
existing `structured_intelligence`/raw-snapshot JSON.

`canonical_procurement.py` (new, pure, deterministic, no I/O, no model
call) is now THE shared contract, sitting alongside the two layers the
2026-09-22 remediation introduced (`document_provenance.py` = Layer 1
source/provenance; `procurement_normalization.py` = Layer 2 canonical
procurement intelligence). It holds:

- **Semantic type vocabulary** (`SEMANTIC_*`, `classify_semantic_type`,
  `is_usable_as_scope`) — a closed 15-member vocabulary. An instruction
  addressed to the proponent is `RESPONSE_PROMPT`/`REQUESTED_EVIDENCE`
  **regardless of the structural slot it was found in**, and can never
  populate a scope field. `SEMANTIC_UNKNOWN` is a fail-closed answer, not
  a default bucket.
- **Per-field source authority** (`IDENTITY_ROLE_*`,
  `classify_identity_role(s)`, `AUTHORITY_BY_FIELD_FAMILY`,
  `merge_identity_fields[_with_provenance]`) — identity / clause /
  contract / response-form families each have their OWN ranking. An
  AMENDMENT has **zero identity authority** while remaining first
  authority for clauses it amends.
- **Category applicability** (`APPLICABILITY_*`,
  `derive_requirement_applicability`, `applicability_compatible`,
  `most_specific_applicability`) — precedence: explicit field → stated in
  text → source document's own category identifier → semantic type →
  `UNKNOWN`. "Appears in a shared summary document" never implies global.
- **Scoped evaluation identity** (`scoped_criterion_key`,
  `is_genuinely_global_criterion`) — a criterion is `(category, label)`,
  never label alone.
- **Scoped milestone identity** (`milestone_scope_key`).
- **Bounded commercial taxonomy** (`COMMERCIAL_TOPICS`,
  `classify_commercial_topic`, `clause_supports_topic`) — explicit source
  heading first, then ordered most-specific-first contextual rules, then
  `UNCLASSIFIED`. No model call was needed for any live clause.
- **Attention-point evidence contracts**
  (`attention_evidence_supports_topic`, `select_supporting_facts`).

Defect root causes and fixes (all live-verified against the real Bank of
Canada corpus, **bid_id 8 / analysis run 19**, with **zero Anthropic
calls**):

- **A — identity**: `_merged_doc_metadata`'s priority function scored an
  addendum 1, the same as the master RFP, so "first non-empty value wins"
  could let it define buyer/title. Now resolved through the identity
  field-family authority. Result: Bank of Canada / 2026-026 / "Request
  for Proposal for Talent, Learning and Organizational Development
  Services".
- **B — semantic type**: `derive_category_scope_summaries` treated any
  captured criterion response prompt as scope. Now type-gated; rejected
  prompts are preserved under `response_prompts_not_scope`. The three
  BoC categories now render an honest "Not stated in the extracted data"
  instead of a Corporate Profile prompt masquerading as SOW scope.
- **C — applicability**: requirements carried no applicability at all.
  `canonicalize_requirements` now emits `applicability` /
  `applicable_category_ids` / `applicability_basis` / `semantic_type` on
  every canonical requirement (BoC: 12 CONTRACT_WIDE, 8 UNKNOWN, 4
  CATEGORY_SPECIFIC, 1 ALL_CATEGORIES).
- **D/E — evaluation scope**: the "Other Rated Criteria" leftover bucket
  only pruned rows sharing an *identical weight*. Now any label already
  present in a category-scoped table is recognized as a scoped instance
  and never becomes a global criterion. BoC renders three clean
  category tables and no leftover bucket.
- **F — milestone scope**: `detect_category_date_distinctions` grouped by
  `semantic_kind` ALONE. Now grouped by `(event_type, scope)`, and within
  one scope alternate representations of one date ("Week of October 26"
  vs "2026-10-26") are reconciled through
  `procurement_normalization._extract_date_window` before any conflict is
  claimed (`_dates_genuinely_disagree`). Genuinely distinct scoped events
  are preserved, not deleted, by the new
  `fast_analysis.derive_scope_distinct_milestones`
  (`ambiguities["scope_distinct_milestones"]`) — information, not an
  ambiguity. The report **recomputes** this one verdict from
  `typed_observations` so regenerating from a pre-CI-1 snapshot also
  benefits. BoC: false "multiple distinct dates" ambiguity gone; both
  category demo dates coexist with original wording preserved.
- **G — commercial taxonomy**: the extraction's `clause_kind` was trusted
  outright. It is now a *candidate*: a clause must **positively** classify
  as a mapped slot's semantic topic to render under it, otherwise the
  slot is omitted. BoC dropped three misbound rows (a planning-work
  clause filed under Assignment, a pricing-clarification clause filed
  under Pricing Escalation, a records clause filed under Cybersecurity);
  the seven remaining rows each positively match their topic.
- **H — attention-point binding**: the reference-check point cited
  `QUALIFICATION_MECHANISMS[0]` unconditionally. Supporting facts are now
  validated against the point's own topic (fail-closed: no matching fact,
  no point), and bilingualism gets its own correctly-topiced point.
- **I — semantic duplicates**: added a bounded Tier 3 to
  `canonicalize_requirements` — same candidate bucket, same cited
  normative standard (`_cited_standards`, level-suffix-insensitive so
  "WCAG 2.1 Level AA" and "WCAG 2.1 AA" are one citation) and same
  obligation target (`_obligation_target`). Still no all-vs-all pass and
  no model call. Conflicting *stated* applicability is an absolute merge
  barrier; silence is not a conflict. BoC: 41 → 25 canonical
  requirements, 10 merged groups, every source ref retained.
- **J — document identity**: identity ROLE and source RELATIONSHIP are
  kept as two independent axes rather than one overloaded ranking;
  `document_provenance`'s existing short-identifier guard already keeps
  category-specific forms (D1/D2/D3) from collapsing.

Live validation used **zero Anthropic calls**: every canonical object was
recomputed from the already-persisted raw snapshot, and the single fresh
report preview came from `regenerate_report_from_raw_snapshot(19)`.

Tests: `tests/test_canonical_procurement.py` (46, all synthetic — no live
DB, no provider call). Six pre-CI-1 tests were deliberately updated where
they encoded behaviour CI-1 explicitly overturns (the false
category-date ambiguity in `test_fast_analysis.py`,
`test_fast_analysis_v3.py`, `test_fast_analysis_v4.py`,
`test_fast_analysis_pricing_evaluation_separation.py`,
`test_phase5_generic_assembly.py`; response-prompt-as-scope in
`test_procurement_normalization.py` and
`test_fast_analysis_remediation_report.py`) — each rewritten to assert
the corrected contract plus the previously-untested opposite case. Full
suite: **3045 passed, 2 skipped**.

**Multi-agent readiness**: Layers 1 and 2 are now stable and typed;
Layer 3 (specialist interpretation) and Layer 4 (cross-domain
reconciliation) remain unbuilt by design. No architectural blocker to
MA-1 was found. What must stay centralized and deterministic: document
identity/authority, semantic typing, applicability derivation, dedup, and
milestone reconciliation — a specialist must consume these, never
re-derive its own.

### CI-1.1: Canonical Evaluation Prompt Scoping + Scope Extraction Coverage (2026-09-22)

A narrowly bounded closure task on the two material gaps CI-1 left open.
No migration, no multi-agent work, no source-map lineage change (Defect
J's display enrichment stays deferred).

**Gap 1 — cross-category prompt collapse.** `FastAnalysisResult.
deterministic_criterion_response_prompts` was a `{criterion_label:
entry}` map, and `run_fast_analysis_corpus` filled it with `setdefault`
per document. A criterion label a buyer scores independently in several
service categories therefore kept only the FIRST document's prompt: for
the Bank of Canada corpus "Corporate Profile" is scored in Category 1
(5 points), Category 2 (5 points) and Category 3 (10 points), and two of
those three prompts were silently discarded. The canonical identity is
now `canonical_procurement.scoped_criterion_map_key(category,
criterion)` — the persistable string form of CI-1's own
`scoped_criterion_key` — and the new field
`scoped_criterion_response_prompts` is keyed by it. The old label-keyed
field is retained unchanged for older snapshots; every consumer prefers
the scoped map and, once it exists, NEVER falls back to the label map
(a scoped miss means "this category has no prompt", and falling back
would hand it another category's).
Three supporting pieces, all deterministic:
`procurement_normalization.extract_scoped_criterion_response_prompts`
(the same heading-convention scan, now tracking the category heading
each criterion sits under, with a new score-cell guard so a weights-table
row like "35 points" is not mistaken for a prompt),
`category_for_document_name` (a per-category response form states its
criteria without repeating the category heading inside — its filename is
the scope signal, the same source-document signal
`derive_requirement_applicability` already trusts), and
`select_authoritative_prompts` (which document wins a scoped prompt is
CI-1's `AUTHORITY_BY_FIELD_FAMILY["response_form"]` ranking, never scan
order).
Retention (task section 2) is `build_scoped_criterion_records` — ONE
canonical record per (category, criterion) carrying category/scope,
label, weight, minimum score, response prompt, requested evidence,
required examples, personnel/resource requirements, methodology
requirements, constraints/limits, authoritative source + role,
source docs/refs and provenance version. Typed facets come from
`canonical_procurement.extract_requested_evidence_elements`. Conflicting
stated weights/minimums are preserved in `weight_variants`/
`minimum_score_variants` rather than silently resolved. The record also
carries `criterion_label`, the SAME field name Fast Analysis occurrences
and `section_analyzer._match_evaluation_criterion` already use, so it
drops straight into PI-3A's existing `EvaluationContext` — no parallel
evaluation model. `criteria_for_category` is the future Evaluation
Agent's read contract (exact, normalized category match).

**Gap 2 — positive scope extraction.** CI-1 stopped prompts masquerading
as scope but added none, leaving Bank of Canada Categories 1/2/3
correct-but-empty. `procurement_normalization.extract_category_scope_
items` is the positive half: a deterministic pass over the SAME corpus
text, tracking scope-of-work section boundaries (`_SOW_SECTION_RE` opens,
an evaluation/submission/pricing/contract heading closes) and the same
category-heading tracker, extended so a statement of work naming
"CATEGORY 2:" binds to the evaluation tables' "Appendix D2 - ..."
category via the shared ordinal (registered as an ordinary
ambiguity-checked token). Enumerated service lines inside a scope
section are emitted as SEMANTIC_SERVICE; paragraphs are emitted only
when they pass `canonical_procurement.is_usable_as_scope` on their own
words. Fail-closed rejections before typing: bidder
certifications/representations, buyer reserved rights, and scoring
tables (two or more "N points") can never become scope. The
RESPONSE_PROMPT guarantee is structural — `classify_semantic_type` tests
RESPONSE_PROMPT/REQUESTED_EVIDENCE first and neither is in
`SCOPE_SEMANTIC_TYPES`, so an evaluation instruction cannot arrive here
even with an explicit structural hint. `scope_items_for_category` is the
future Scope Agent's read contract. `derive_category_scope_summaries`
gained the additive `category_scope_items` parameter and a
`source_scope_items` output; the report adapter prefers genuine SOW
material over anything evaluation-derived.

**Bank of Canada validation** (bid 8, analysis run 19, **zero Anthropic
calls** — the 17 documents with a storage path were downloaded and text
was re-extracted locally; the persisted run-19 snapshot predates Defect
A and contains no prompts at all, so both maps were recomputed
deterministically): label-keyed prompts 12 → scoped prompts 18, 23
scoped criterion records. Category 1: 7 criteria, 7 with a
category-specific prompt; Category 2: 7 criteria, 5 with one; Category
3: 7 criteria, 6 with one. Zero cross-category leakage (every retained
prompt's own category equals the record's). Each category's prompts now
come from that category's OWN Appendix D form rather than the main RFP,
via the response-form authority ranking. Scope: Category 1 = 4 items,
Category 2 = 11, Category 3 = 7 — all genuine SOW services ("Custom
curriculum and instructional design", "Competency framework development
and validation", "Team visioning, norming, and effectiveness sessions"),
so all three categories land on outcome A, not "explicitly empty". One
known imperfection, recorded honestly: one Category 2 item carries a
trailing fragment of the adjacent PDF table column ("HR strategy
consulting increase and/or be adjusted from year to year based on") —
verbatim source text, slightly over-captured, never fabricated. Three
criteria (D2 Methodology and Advisory Approach, D2/D3 Value-add) now
show "Not stated in the extracted data" where they previously showed a
weights-table cell ("35 points") — an honest loss of a wrong value.

Snapshot schema 1.1 → **1.2**, purely additive
(`scoped_criterion_response_prompts`, `scoped_criterion_evaluation`,
`category_scope_items`); an older 1.x payload still deserializes.

Tests: `tests/test_canonical_evaluation_scoping.py` (47, fully
synthetic — no live DB, no provider call, no file I/O), covering scoped
identity, three same-label criteria surviving independently, prompts
never overwriting each other, body never bleeding across a category
boundary, scoped requested evidence, revised/amended source authority,
a response prompt never becoming a scope item, real SOW text producing
scope items, scope staying empty rather than fabricated, per-category
form documents, snapshot round trip and older-snapshot tolerance, and
Section Analyzer / PI-3A DraftingBrief / PI-3D1 outline regressions.
Full suite: **3092 passed, 2 skipped**.

**Layers 1–2 are ready to freeze for MA-1.**

### MA-1: Bounded Specialist Full Analysis (2026-09-22)

The first genuine multi-agent Full Analysis backend, and the first
consumer of the now-FROZEN Layers 1–2. Backend only — no UI, no
animation, no drafting, no OM, no Fast Analysis feature work.

**Architecture** (`full_analysis.py`, new): one canonical procurement
package → six bounded specialist analyses (parallel) → one reconciliation
stage → one structured `FullAnalysisResult`. Specialists:
PROCUREMENT_STRUCTURE, REQUIREMENTS_COMPLIANCE, EVALUATION_INTELLIGENCE,
SCOPE_DELIVERABLES, COMMERCIAL_CONTRACTUAL, SCHEDULE_SUBMISSION.

**One shared canonical truth.** `build_canonical_package()` assembles a
FROZEN `CanonicalPackage` (frozen dataclass; tuples and
`MappingProxyType` throughout) from a completed Fast Analysis result —
live or reconstructed from a durable raw snapshot. It re-extracts
nothing: where an older snapshot predates a CI-1/CI-1.1 field, the
frozen Layer 1/2 function that produces that field is re-run over the
snapshot's own base material. Every object carries a deterministic
canonical id (`IDENT`, `SUBMISSION`, `PKG`, `DOC-*`, `REL-*`, `CAT-*`,
`REQ-*`, `CRIT-*`, `SCOPE-*`, `OBL-*`, `MS-*`) — **those ids are the
entire citation vocabulary**.

**Strict input boundaries.** `SPECIALIST_INPUT_TYPES` declares exactly
which canonical object types each specialist may see;
`build_specialist_input()` assembles only those, deeply read-only, so a
specialist cannot mutate canonical state and never holds another
domain's material. SCOPE_DELIVERABLES deliberately has NO
`SCOPED_EVALUATION_CRITERION` entry — CI-1 Defect B is enforced a second
time at the agent boundary, and `CATEGORY_SCOPE_ITEM` objects are
re-gated through `classify_semantic_type` on the way in. No specialist
reads raw document text, queries OM, re-runs ingestion, re-normalizes
requirements, invokes another specialist, or reaches drafting; the
module imports none of those systems and a test asserts that.

**Typed findings, fail closed.** Six types only — FACT, RISK, GAP,
AMBIGUITY, ATTENTION_ITEM, INTERPRETATION. `validate_findings()` rejects
(never repairs, never re-buckets) a finding with an unknown type, empty
body, or — for every type except INTERPRETATION — no canonical id **from
that specialist's own slice**. An INTERPRETATION may stand uncited but
is then `UNSUPPORTED_INTERPRETATION`, `SPECIALIST_INTERPRETATION`
authority, and human-confirmation-required: interpretation is never
presented as source fact.

**Parallelism.** Genuine `ThreadPoolExecutor`, `MAX_SPECIALIST_CONCURRENCY
= 3`, no shared mutable state (per-specialist telemetry lists merged in
fixed order afterwards), isolated failure handling (a failed specialist
returns `status=FAILED` with its reason and empty findings — never
generic substituted reasoning), and `SPECIALIST_RETRY_ATTEMPTS = 0`:
exactly one provider call per specialist.

**Reconciliation.** Deterministic assurance runs FIRST and survives a
model failure: cross-specialist finding consolidation (reusing CI-1's own
near-duplicate primitive, never merging across categories, preserving
every producing specialist), orphaned canonical requirements, category
scope inconsistencies, evaluation-vs-scope mismatches, and canonical
authority enforcement (a specialist FACT contradicting a canonical
category scope is demoted and recorded — agreement count is never
consulted, facts are never majority-voted). Then ONE bounded model call
over the specialists' structured outputs plus a MINIMAL canonical index
(ids/labels only — no clause text, no response prompts, no document
text). Reconciliation output citing an unknown id is dropped.

**Fast Analysis is untouched.** `fast_analysis.py` does not import or
dispatch any of this. Full Analysis is an explicit action:
`analysis_service.run_full_analysis_for_run(run_id, api_key)` against an
already-COMPLETE Fast Analysis run. Nothing in ingestion reaches it.

**Persistence: compute-and-return (known gap).** The existing
analysis_runs/analysis_results architecture was inspected first and is
the right future home, but `analysis_runs.analysis_mode` is constrained
to `('FAST','DEEP_VERIFY')` (migration 004) and analysis_results has no
Full Analysis column. MA-1 therefore does **not** persist, and does
**not** add a migration — see `analysis_service.
FULL_ANALYSIS_PERSISTENCE_GAP`. Highest migration in repo remains 019.

**Bank of Canada validation** (bid 8, analysis run 19; canonical digest
`e98b77538ce796a5`): package = 3 service categories, 41 canonical
requirements, 23 scoped criteria, 22 category scope items, 112 typed
commercial obligations, 15 scoped milestones, 13 typed documents. ONE
bounded live smoke: 7 provider calls (6 specialists + 1 reconciliation),
89.3s wall, 86,733 input / 18,144 output tokens, all six specialists
COMPLETE, completeness COMPLETE. Per-specialist prompts 12k–50k chars —
no specialist ever receives the whole package. Verified behaviors: the
multi-vendor call-off model with per-category award caps (5/3/7)
surfaced from canonical PROCUREMENT_MECHANIC material; D1/D2/D3 stayed
cleanly separated with per-category dominant criteria and Corporate
Profile's differing weights reported as scoped variation, not conflict;
Category 1 (week of Oct 26) and Category 3 (week of Nov 2) presentation
windows coexisted with an explicit "category-specific schedules are
normal, not conflicts" finding; Assignment / Indemnity / IP / tax
clauses stayed on their CI-1 topics (no Defect G misbinding); 7
cross-specialist duplicates consolidated with producers preserved; 14
orphaned requirements and 9 non-canonical category labels surfaced as
assurance signals rather than silently accepted.

Tests: `tests/test_full_analysis_ma1.py` (47, fully deterministic and
synthetic — **every model call mocked, zero provider calls, no DB, no
file I/O**). Full suite: **3139 passed, 2 skipped**.

### MA-2A: Durable Full Analysis Runs & Progress Events (2026-09-22)

Persistence / idempotency / progress layer around MA-1. Backend only — no
UI, no animation, no polling page (MA-2B). Frozen CI-1/CI-1.1 Layers 1–2
untouched (`fast_analysis.py`, `canonical_procurement.py`,
`procurement_normalization.py`, `document_provenance.py` unchanged).

**Persistence reuses `analysis_runs`/`analysis_results`** with
`analysis_mode='FULL'` (so `model_usage_events.analysis_run_id` links Full
Analysis telemetry with no new telemetry schema). New
`migrations/020_full_analysis_runs.sql` — **applied and live-commissioned
2026-09-22 by MA-2A.1 (below)**: widens the mode CHECK to
FAST/DEEP_VERIFY/FULL and the status CHECK with RUNNING + PARTIAL (PARTIAL
is terminal and was added to the one-active-run partial index's terminal
set); adds `input_fingerprint`, `source_analysis_run_id`,
`last_progress_at` (FULL rows must carry the first two); a unique index of
one COMPLETE FULL run per (bid, fingerprint);
`analysis_results.full_analysis_result`; two new append-only tables,
`full_analysis_events` (gap-free per-run `sequence`, closed event/status
vocabulary, bounded `detail` ≤4000 bytes, never model text) and
`full_analysis_specialist_results` (write-once, one per specialist,
persisted THE MOMENT that specialist finishes). Composite `(run_id,
bid_id)` FKs; RLS authenticated SELECT via `can_access_bid` only;
triggers make events append-only and a terminal FULL run immutable even
for service_role. Writes only through three service_role-only SECURITY
DEFINER RPCs: `start_full_analysis_run` (per-bid advisory lock; outcomes
CREATED / ACTIVE_RUN_EXISTS / REUSED_COMPLETE / EXISTING_FAILED /
EXISTING_PARTIAL — FAILED/PARTIAL need explicit `p_retry`),
`record_full_analysis_event` (per-run advisory lock, refuses terminal
runs), `finalize_full_analysis_run` (atomic result + terminal event +
status; refuses COMPLETE unless the result's `completeness_status` is
COMPLETE).

**Fingerprint** (`full_analysis.compute_full_analysis_fingerprint`):
sha256 over fingerprint-recipe version, `FULL_ANALYSIS_VERSION`, MA-1's
`package_digest`, a new complete `canonical_content_digest` (all 11
canonical object types — MA-1's digest omits completeness/relationships/
categories, which do reach specialists), per-specialist
`SPECIALIST_VERSION` + contract digest (brief, shared rules, input types,
model, limits), reconciliation version + prompt digest. No bid/run ids,
timestamps, buyer intelligence or UI state.

**Service** `full_analysis_service.py` (the only entry point a UI may
use, via `tenancy.start_full_analysis_for_organization` /
`get_full_analysis_status_for_organization` /
`get_full_analysis_result_for_organization` /
`mark_full_analysis_run_stuck_for_organization`): builds the package via
`analysis_service.build_full_analysis_package` (factored out of MA-1's
entry point; skips document download when the snapshot already has
CI-1.1 scope items), fingerprints, calls the start RPC, and only on
CREATED executes. Progress comes from a new observational
`full_analysis.run_full_analysis(on_event=...)` hook fired at real
boundaries (QUEUED before submit, STARTED in the worker before the call,
COMPLETED/FAILED when `run_specialist` returns, RECONCILIATION_*); no
percentages. Run statuses QUEUED/RUNNING/COMPLETE/PARTIAL/FAILED;
specialist states QUEUED/RUNNING/COMPLETE/FAILED/SKIPPED (SKIPPED only on
a terminal run for a domain that never finished).

**Background execution:** reuses Fast Analysis's existing in-process
daemon-thread pattern (no job queue exists in this repo). Honest limit:
not resilient to a process restart — mitigated by durable incremental
state and stuck detection (`is_full_run_stuck`: no progress for 10 min or
age > 30 min), with an explicit user-initiated FAILED marking that never
relaunches. `execution="inline"` runs synchronously.

**Telemetry:** each provider call is recorded through the existing
`execute_messages_create(telemetry_context=...)` path with
`workflow="full_analysis"`, `analysis_run_id=<FULL run>`,
`operation=specialist_<id>|reconciliation`; run-level usage summary in
`analysis_runs.telemetry`.

**MA-1 residual hardening** (`SPECIALIST_VERSION` ma-1.0 → ma-1.1):
specialist prompts now list the allowed category ids/labels and state
that ids must be copied exactly; `normalize_category_scope` (exact label,
CAT-id, punctuation/case-equal label, or unique whole-word sub-phrase →
canonical label; ambiguous/unknown fails closed and forces human
confirmation) and `normalize_canonical_id` (unique case/whitespace match
within the specialist's own slice only) — no validation loosened.
Post-hardening live rejection rates are NOT yet measured (no live call
made in MA-2A).

Also: `database.get_active_analysis_run` and
`tenancy.get_bid_analysis_authenticated` treat PARTIAL as terminal /
skip FULL rows so FAST consumers are unaffected. Tests:
`tests/test_full_analysis_ma2a.py` (62, zero provider calls, in-memory
stand-in for migration 020's RPC contract + static SQL assertions). Full
suite: **3201 passed, 2 skipped**. Highest migration in repo: **020
(applied live 2026-09-22, MA-2A.1)**.

### MA-2A.1: Live Commissioning of Durable Full Analysis (2026-09-22)

Commissioning only — no code change was required; no MA-2B UI; canonical
layer untouched. Project `whonalbdpbubaqhpzrnw`.

**Preflight** (actual schema, not only the ledger): 019 present in the
ledger, 020 absent; `analysis_runs` still had migration 004's
FAST/DEEP_VERIFY mode CHECK, the 6-value status CHECK, the
`idx_analysis_runs_one_active` index terminal on COMPLETE/FAILED only, no
triggers, no `full_analysis_*` objects; 17 FAST/COMPLETE rows, all valid
under the widened constraints — no drift. **Applied** via
`apply_migration` (ledger `20260922202352 full_analysis_runs`; statements
verbatim from the file, comments omitted).

**Verified live**: FULL mode + RUNNING/PARTIAL statuses, the three new
columns, `analysis_results.full_analysis_result`, both new tables, all
indexes/triggers. Transactional (rolled-back) RPC probes as postgres:
CREATED → ACTIVE_RUN_EXISTS for any fingerprint while active → gap-free
server sequencing → COMPLETE refused for a non-COMPLETE result → second
active FULL run and second COMPLETE-per-fingerprint both rejected by the
unique indexes → finalize writes result + RUN_COMPLETED + status
atomically → late event / re-finalize / direct UPDATE of a terminal FULL
run / FAST→FULL conversion / event UPDATE-DELETE / specialist-result
UPDATE all rejected → REUSED_COMPLETE on the same fingerprint →
EXISTING_FAILED without retry, CREATED with `p_retry`. RLS: org member
reads run/events/specialist rows; non-member and anon read 0; member
INSERT into both tables and forged FULL `analysis_runs` INSERT rejected
by RLS, member UPDATE affects 0 rows, member/anon EXECUTE on all three
RPCs denied; service_role RPC writes succeed; the append-only trigger
rejects even service_role. Security advisors: only the 3 pre-existing
findings. **Live PostgREST shapes** (supabase-py): `start_full_analysis_run`
→ a dict `{"outcome","run"}` (not a list); `record_full_analysis_event`
and `finalize_full_analysis_run` → a single dict row; `database._rpc_one`
handles all three correctly.

**Service against live RPCs** (disposable test bid 1286 / FAST run 18,
mocked model client — zero provider calls, telemetry sink disabled):
start/status/incremental `after_sequence`/result/specialist-result reads,
REUSED_COMPLETE with 0 prompts, a PARTIAL run (reconciliation failed)
visible with EXISTING_PARTIAL on restart, and stuck semantics (not stuck
at +30s, NO_PROGRESS at +11min, `mark_full_analysis_run_stuck` refused
when not stuck, marks FAILED when stuck, no new run created, a late
`_EventRecorder` write rejected and the recorder aborts, restart →
EXISTING_FAILED, every specialist SKIPPED). All probe rows (runs 28–31)
deleted afterwards; zero residue verified.

**One live Full Analysis** — bid 8 (Bank of Canada RFP 2026-026, source
FAST run 19), FULL **run 32**, fingerprint `e1ace9ef96e267f3…`
(CREATED — no prior FULL run existed), via
`tenancy.start_full_analysis_for_organization(execution="background")`.
All six specialists COMPLETE, reconciliation COMPLETE, run COMPLETE;
101.3s from RUN_CREATED to RUN_COMPLETED (engine `wall_seconds` 97.8).
7 provider calls (`claude-haiku-4-5-20251001`), 89,593 input / 18,870
output tokens; all 7 `model_usage_events` rows carry
`analysis_run_id=32`, `workflow=full_analysis`, per-specialist
`operation`. 23 gap-free events; each STARTED precedes its COMPLETED;
RECONCILIATION_STARTED (seq 21) follows the last SPECIALIST_COMPLETED
(seq 20); RUN_COMPLETED is last (seq 23). Observed concurrency from event
times: at most 3 specialists between STARTED and COMPLETED at any moment
(first wave 3 overlapping, then each completion admits the next).
Specialist rows were durable 33–67s before the run completed. A second
start **during** the run returned ACTIVE_RUN_EXISTS (same run); a start
**after** completion returned REUSED_COMPLETE (same run, same
fingerprint) with `model_usage_events` for the workflow unchanged at 7 —
**0 extra provider calls**. Fresh-process read-back via
`tenancy.get_full_analysis_result_for_organization` returned the
persisted result (6 specialist rows, 77 reconciled findings, 20 gaps, 4
ambiguities, 9 cross-domain risks, 25 human-confirmation items,
source/canonical ids and timing).

**MA-1.1 rejection-rate (vs MA-1 smoke: 3 discarded, 9 paraphrased-label
flags)**: 83 accepted, **1 discarded** (an uncited FACT), **0
unrecognized category labels**, 13 safe normalizations (all CAT-id →
canonical label; no paraphrase needed normalizing), 5 exact labels, 0
canonical-id normalizations, 0 unknown-id citations. Reconciliation
`category_scope_inconsistencies` 0 (MA-1 reported 9 non-canonical
labels). No validation was loosened; single-run sample.

**Semantic regression** (bid 8): multi-vendor call-off with 5/3/7 caps;
D1/D2/D3 criteria cited and scoped per category; Category 1 week-of-Oct-26
and Category 3 week-of-Nov-2 presentations stated as category-specific
FACTs, no conflict finding, 0 contradictions, 0 canonical-authority
overrides; Assignment findings bind to OBL-0/OBL-15 (canonical topic
INTELLECTUAL_PROPERTY), Indemnity to OBL-2/OBL-14 (INDEMNITY) — no
misbinding. Bilingualism/accessibility exist canonically (REQ-14; OBL-104/
105 bilingual, OBL-106/107 digital accessibility, category-scoped
headings) but no specialist surfaced them this run — not misrepresented,
simply not selected.

**Known issues found, NOT fixed (outside commissioning scope):**
1. **Silent output truncation.** 3 of 7 calls stopped on `max_tokens`
   (EVALUATION_INTELLIGENCE, COMMERCIAL_CONTRACTUAL, reconciliation, each
   exactly 3000 output tokens — `SPECIALIST_/RECONCILIATION_MAX_OUTPUT_
   TOKENS`). The tolerant JSON parse recovered usable output and the
   domains are reported COMPLETE / confidence HIGH; `stop_reason` is only
   visible in `model_usage_events`, not in the persisted specialist
   result. A future task should either raise the cap or surface
   truncation in the result (changes the fingerprint contract).
   **Fixed by MA-2A.2 (below)**; run 32 itself is left unmodified as
   historical evidence (its persisted rows still read COMPLETE).
2. **No scoped evaluation prompts in the package.** Run 19's snapshot
   predates CI-1.1's prompt fields and `build_canonical_package` re-derives
   only `category_scope_items` from documents, so all 23 criteria carry
   empty `response_prompt`/`requested_evidence` (identical canonical digest
   `e98b77538ce796a5` to MA-1's smoke — pre-existing, not an MA-2A
   regression). Two unscoped criteria (`CRIT-relationship-management`,
   `CRIT-relevant-experience-and-references`) also remain. A fresh Fast
   Analysis run would carry snapshot 1.2 prompts.
3. **Event-write latency.** Each event RPC took ~1.2–1.6s from this
   client and `_EventRecorder` serializes writes; STARTED is written in
   the worker before its call, so writes delay specialist starts slightly
   (run 32: 97.8s engine wall vs MA-1's 89.3s). Not a correctness issue.
4. Two service-category labels contain U+FFFD (source-extraction
   artifact in canonical data); normalization maps to them exactly.

### MA-2A.2: Specialist Output Truncation Integrity (2026-09-23)

**Diagnosis (read-only queries of live run 32):** `model_usage_events`
already stores the provider's `stop_reason`. EVALUATION_INTELLIGENCE
(3000 out, 14 findings), COMMERCIAL_CONTRACTUAL (3000 out, 14 accepted +
1 rejected = 15 emitted, above the prompt's cap of 14; mean finding detail
484 chars) and reconciliation (3000 out; `completeness_note` empty and
`contradictions` 0, so it was cut before its last keys) all ended with
`stop_reason="max_tokens"`; the other four ended `end_turn`. Root cause:
`run_specialist`/`run_reconciliation` set COMPLETE whenever parsing
produced a dict, ignoring `stop_reason`, and
`_safe_parse_json_with_status` silently repairs truncated JSON
(`RECOVERED_TRUNCATED`). Output was driven by verbose `detail` text
("2-4 sentences"), restated canonical text, and unbounded reconciliation
lists with `completeness_note` last.

**Contract:** new stage status `PARTIAL` (`fa.STATUS_PARTIAL`): the
provider's `stop_reason == "max_tokens"` and at least one valid finding
(or, for reconciliation, the model call returned) — validated output is
kept, `failure_reason` starts `OUTPUT_TRUNCATED:`. Truncated with nothing
recoverable → FAILED. Results carry `stop_reason`, `parse_status`,
`output_truncated`. Malformed `end_turn` output and provider exceptions
keep their pre-existing behavior. Overall: FAILED only when no specialist
is COMPLETE/PARTIAL; COMPLETE only when all six and reconciliation are
COMPLETE; otherwise PARTIAL (run status PARTIAL, failure_reason names
"(output truncated)" stages). Reconciliation lists PARTIAL domains as
incomplete (`output_truncated: true` in its input) and still consolidates
their findings.

**Persistence/events (no migration):** `SPECIALIST_COMPLETED` /
`RECONCILIATION_COMPLETED` now mean "finished with usable output"; the
event `status` column (migration 020 already allows `PARTIAL`) carries
COMPLETE vs PARTIAL, and event `detail` carries `stop_reason` /
`output_truncated`. `full_analysis_specialist_results.status` can only be
COMPLETE/FAILED/SKIPPED and the RPC writes COMPLETE for a COMPLETED event,
so the authoritative per-specialist state is `result->>'status'`, exposed
as `effective_status` by `get_full_analysis_result`. Run summary and
telemetry gain `truncated_stages`. `derive_execution_state` reports
QUEUED / RUNNING / COMPLETE / PARTIAL / FAILED / SKIPPED. A PARTIAL run is
never returned as REUSED_COMPLETE (EXISTING_PARTIAL; retry is explicit).

**Boundedness:** specialist prompt: at most 12 findings, detail ≤ 2 short
sentences, cite canonical ids, never restate source text; reconciliation:
`completeness_note` first, per-list caps (8/5/6/6). Output ceilings stay
3000 (no evidence yet that the bounded schema needs more). Versions:
specialist `ma-1.2`, reconciliation `ma-1.1` (invalidates prior
fingerprints). Not live-validated: no provider call was made.
Tests: `tests/test_full_analysis_ma2a2.py` (17).

**Execution limitation (production-hardening item):** execution is an
in-process daemon thread. The run row, every event and every finished
specialist result are durable, but **execution does not survive a process
restart**. A killed process leaves a non-terminal run that
`is_full_run_stuck` reports after 10 min without progress (or 30 min
age); while it is non-terminal every start returns ACTIVE_RUN_EXISTS (no
duplicate run); nothing auto-fails or relaunches; a user must call
`mark_full_analysis_run_stuck` (→ FAILED, finished specialists kept),
after which start returns EXISTING_FAILED until an explicit
`retry=True`. Any zombie thread's later writes are refused. This is
durable state, not durable execution; a real job runner is required
before production.

### MA-2B: Animated Multi-Agent Full Analysis Experience (2026-09-23)

The user-facing presentation layer for MA-1/MA-2A/MA-2A.2. Presentation
and interaction only: no migration, no specialist-logic change, no new
model call anywhere in the UI.

- **Entry point.** Active-bid sidebar "🧬 Full Bid Intelligence"
  (`page == "stage_full_analysis"`, routed in `app.py` to
  `pages/stage_full_analysis.page_full_analysis`), plus an "Open Full Bid
  Intelligence" navigation button in UNDERSTAND's completed Fast Analysis
  panel (navigation only; nothing starts from UNDERSTAND). Fast Analysis is
  unchanged and still the default quick orientation.
- **Service calls.** Only tenancy's MA-2A wrappers:
  `start_full_analysis_for_organization` (the single start path,
  `request_start`, debounced by a per-bid in-flight flag and a disabled
  button), `get_full_analysis_status_for_organization`,
  `get_full_analysis_result_for_organization`,
  `mark_full_analysis_run_stuck_for_organization`. All five start outcomes
  get a note; EXISTING_FAILED/EXISTING_PARTIAL are shown, never re-run —
  only an explicit "Run Full Analysis again" button passes `retry=True`.
  REUSED_COMPLETE opens the stored result directly (no animation replay).
- **State model** (`components/full_analysis_view.py`, pure). Bot state =
  persisted specialist row's `effective_status` when a row exists, else the
  event-derived state from `get_full_analysis_status`, else WAITING (no
  event yet — never fabricated). The raw migration-020 `status` column is
  never read, so a truncated (raw COMPLETE) specialist renders PARTIAL.
  Reconciliation is RUNNING only after a `RECONCILIATION_STARTED` event.
  Progress is counts only ("4 of 6 specialists finished · 3 working now ·
  Reconciliation pending") — no percentage exists anywhere. Hub counts come
  from the persisted `CANONICAL_PACKAGE_READY` event's `object_counts`.
- **Animation.** CSS/inline-SVG only: RUNNING bots scan/blink and their
  wire to the Shared Truth hub flows; one packet per real transition into
  COMPLETE/PARTIAL (diffed against the previous poll's bot states kept in
  session — a refresh/reconnect draws none); FAILED sends none; PARTIAL is
  dashed amber, distinct from COMPLETE. Every state also has a text label
  and glyph; `prefers-reduced-motion` disables all motion; below 860px
  viewport or 720px container width the radial layout stacks.
- **Reconnect / polling.** Canonical run state is re-read from the service
  on every render; session_state caches presentation only (previous bot
  states, specialist rows re-fetched only when the finished count changes,
  outcome note, in-flight flag). An `@st.fragment(run_every=3)` polls only
  while the run is non-terminal and not stuck; a transient read failure
  shows a caption and never restarts anything.
- **Stuck runs.** A run `is_full_run_stuck` reports is shown as "Analysis
  interrupted" with all animation stopped and polling off; the only action
  is the explicit "Mark this run as stopped" (→ FAILED), after which the
  user may explicitly run again. Nothing auto-reruns (daemon-thread caveat
  above still applies).
- **Completed result** (same page): a static specialist status strip, a
  COMPLETE / PARTIAL (naming each incomplete domain) / FAILED banner, then
  Executive Intelligence, Requirements & Compliance, Evaluation
  Intelligence, Scope & Delivery, Commercial & Contractual, Schedule &
  Submission (reconciled findings grouped by first producer, "also raised
  by" noted, canonical-fact vs specialist-interpretation tags,
  needs-confirmation tags) and Cross-Domain Risks & Gaps. Each section has
  an "Evidence references" expander of canonical/finding ids. With no
  reconciled findings it falls back to the persisted specialist findings.
- **Verified** against historical run 32 (bid 8) read-only: renders
  COMPLETE, 77 reconciled findings grouped 13/13/13/12/13/13, 9 risks / 20
  gaps / 4 ambiguities / 25 confirmation items; replaying its real 23-event
  log shows at most 3 concurrent RUNNING bots and one packet per
  completion. Run 32 was not modified and is not shown as PARTIAL.
- Tests: `tests/test_full_analysis_ma2b.py` (54, all mocked, zero provider
  or database calls).

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

**Product boundary reversal: Bid Intelligence no longer generates proposal
narrative.** Product strategy changed after PI-3C: the product is
UNDERSTAND (procurement intelligence) → DECIDE (bid/no-bid support) →
BUILD/Response Intelligence (tell the human proposal team what must be
addressed, what evidence exists, what is missing/risky, what the evaluator
expects — never write the proposal) → CHECK (independently assess the
human-written proposal). All active AI proposal-generation capability was
removed:

- **Removed**: `analyst.draft_proposal_section`/`DRAFTER_SYSTEM` (the
  original, non-evidence-aware drafter); `pages_extra.page_section_drafter`
  and its call site in `app.py`; `section_drafting._call_section_draft`/
  `_drafting_prompt`/`draft_section` (PI-3A's one model call and its
  orchestration); `tenancy.draft_section_for_organization` (PI-3A) and
  `tenancy.get_or_generate_section_draft` (PI-3B, the persist-on-generate
  path); `database.get_or_create_section_draft` (the Python writer for the
  migration-018 RPC — the RPC itself and the table are untouched); every
  "Draft"/"Generate"/"Refine with AI"/"Redraft" UI control. The
  `REQUEST_BUDGETS.json` entry and `scripts/request_profile.py` probe for
  `draft_proposal_section` were removed with it.
- **Preserved / renamed, not deleted**: `section_drafting.py`'s brief
  assembly (`build_brief`, now returning `SectionResponseBrief` —
  `SectionDraftingBrief` kept as a transitional alias) and its
  fail-closed claim/evidence-validation logic
  (`reconcile_structured_result` — formerly `_reconcile_draft_response`;
  `reconcile_material_claims`, `evidence_id_registry`,
  `permits_verified_fact`), `compute_draft_input_fingerprint`, and
  `assure_section_draft` all remain — pure, no model call, no I/O — as
  building blocks for BUILD's Response Brief and likely reuse in future
  CHECK claim-verification work. `pages/section_drafting_workspace.py` was
  renamed to `pages/section_response_brief.py`
  (`render_requirement_drafting_workspace` →
  `render_requirement_response_brief`); it renders ONLY
  `tenancy.get_section_draft_status_for_organization` (read-only: brief +
  historical-draft status, no generate action) and shows historical PI-3B/
  PI-3C drafts (migrations 018/019) read-only in a collapsed "retired
  capability" expander — never hidden, never destroyed, never
  regenerated. `tenancy.get_draft_existence_map_for_organization` (a plain
  existence read) is unchanged.
- **Historical data**: migrations 018/019 and every existing
  `section_drafts` row are untouched — no destructive migration, no schema
  change. `database.get_section_drafts` (read) remains the only
  `database.py` function touching that table; there is no write path left.
- **CHECK reuse candidates** identified while auditing this removal:
  `reconcile_structured_result`/`reconcile_material_claims` (fail-closed
  claim-to-evidence-id validation), `evidence_id_registry` (bounded
  evidence-id vocabulary construction from tier-1/tier-2/OM sources),
  `SectionResponseBrief`'s evidence-tier separation, and
  `assure_section_draft`'s mandatory-coverage/evaluation-criteria/
  word-limit/contradiction checks — all directly applicable to auditing a
  HUMAN-written response instead of a model-drafted one. CHECK V2 itself
  was explicitly NOT started this phase.

**CHECK-1 (Package-Aware Proposal Assurance Foundation) is implemented**
(`submission_package.py`, pure/deterministic, no model call, no I/O) --
ingestion, canonicalization and candidate mapping ONLY; no ADDRESSED/
PARTIAL/MISSING adjudication, score, claims assurance or recommendation
(that is CHECK-2, not started). CHECK now treats a bidder submission as a
PACKAGE of role-classified artifacts (`SubmissionDocument`: TECHNICAL_
PROPOSAL / PRICING_FORM / SUBMISSION_FORM / MULTI_PARTY_FORM / SOCIAL_
PROCUREMENT_RESPONSE / CERTIFICATE / EVIDENCE_ATTACHMENT / RESUME /
ORGANIZATION_CHART / SUPPORTING_DOCUMENT / UNKNOWN, deterministic
filename + content classification with embedded-section secondary roles
and human override), reusing extractor's file_id/content_hash identity
(`build_alignment_submission_package(include_bytes=True)`) and
`proposal_intelligence.compute_package_digest`. Structure is parsed per
artifact, never flattened: PDF heading hierarchy + page + table rows,
DOCX label->value form fields / checkbox declarations / tables, XLSX
sheet + cell + row label + column header + yellow/unlocked INPUT cells
(completed vs blank) + formula flags. ONE shared bid-bound evidence
registry (`EvidenceItem`, `evidence_id` = sha256 over bid_id/document/
kind/locator; cross-bid resolution fails closed). `derive_expected_
evidence` maps each canonical requirement to expected evidence ROLES
(or flexible / PORTAL_NATIVE); `map_requirements_to_submission` returns
bounded candidates plus a package-level ARTIFACT status
(ARTIFACT_PRESENT / MISSING_FROM_PACKAGE / POSSIBLY_PORTAL_NATIVE /
NOT_VERIFIABLE_FROM_FILES / FLEXIBLE_LOCATION) -- an absence claim is
permitted only for MISSING_FROM_PACKAGE, which structurally prevents the
"Price Form missing because the narrative has no prices" defect class;
`screen_absence_claim` checks any missing-artifact claim against the
package. `tenancy.build_submission_evidence_package_for_organization` is
the read-only auth boundary. Persistence: `migrations/021_submission_
evidence_registry.sql` (`submission_documents`, `submission_evidence_
items`, RPC `create_submission_evidence_bundle`, hanging off migration
015's `proposal_package_snapshots` by composite FK) -- see CHECK-1.1
below (now **applied and live-commissioned**). Tests:
`tests/test_check1_submission_package.py`.

**CHECK-1.1 (Real Calgary Package Commissioning) -- 2026-09-27.** CHECK-1
re-validated against the REAL City of Calgary RFP 26-1603 buyer package
and the REAL Phoenix Consulting Canada submission (replacing CHECK-1's
synthetic Price Form / Appendix E / B2). No CHECK-2 (no adjudication).

- **Migration 021 applied and live-commissioned** (project
  `whonalbdpbubaqhpzrnw`, ledger `20260926220922
  submission_evidence_registry`), after a direct preflight (020 live by
  object inspection; no 021 object/policy/name collision;
  `proposal_package_snapshots` has `UNIQUE(id,bid_id)`; `can_access_bid`
  SECURITY DEFINER + pinned search_path). Amended IN PLACE before its
  first application: logical-artifact / representation columns
  (`logical_artifact_id`, `representation_relationship` in AUTHORITATIVE /
  ALTERNATE_REPRESENTATION / SUPERSEDED_OR_DRAFT_VARIANT / TEMPLATE_VARIANT
  / BYTE_IDENTICAL_DUPLICATE, `representation_of`, `representation_basis`,
  plus `duplicate_of`/`unusable_reason` the payload always carried),
  deferred same-bid/same-snapshot self-FKs for `representation_of` /
  `duplicate_of`, a CHECK that exactly the authoritative member has no
  `representation_of`, a partial unique index (one AUTHORITATIVE per
  logical artifact per snapshot), and evidence uniqueness widened from
  `(bid_id, evidence_id)` to `(bid_id, package_snapshot_id, evidence_id)`
  (deterministic ids would otherwise make any re-submission keeping one
  unchanged file fail). Verified live: RLS on both tables, authenticated
  SELECT-only policies via `can_access_bid`; org member reads 13/294 rows,
  non-member authenticated 0/0, anon 0/0; authenticated INSERT rejected
  (42501 RLS), UPDATE/DELETE affect 0 rows, RPC EXECUTE denied to
  anon/authenticated (service_role only); constraint probes rejected a
  dangling `representation_of` (23503), a second AUTHORITATIVE (23505), an
  authoritative row with a link (23514), and cross-bid document/evidence
  rows (23503). RPC returns a bare integer (evidence rows inserted; `0` on
  an idempotent re-call); cross-bid snapshot and non-array payloads raise
  P0001. Security advisors: only the 3 pre-existing findings.
- **Python writer/reader now wired**: `database.create_submission_
  evidence_bundle` / `get_submission_documents` /
  `get_submission_evidence_items` (paged past PostgREST's 1000-row cap),
  `tenancy.persist_submission_evidence_package_for_organization`
  (require_bid_access first; reuses the migration-015 snapshot by
  package digest; idempotent) and `tenancy.load_submission_evidence_
  package_for_organization` (fresh rebuild from rows via
  `submission_package.package_from_persisted_rows`; foreign snapshot ->
  AccessDeniedError; foreign row -> CrossBidEvidenceError).
- **Canonical CHECK benchmark = bid 1360** ("RFP 26-1603 - Design and
  Delivery Services for Leadership Learning and Development", org
  `4326b564-...`). Buyer side: all 13 authoritative package files as `RFP
  / Source` documents 199-211 (RFP with Price V2.5, Proponent
  Acknowledgements V1.0, Appendix D Price Form template, CGC 2026-05-13,
  Addenda One-Five, four Q&A logs) + ONE Fast Analysis run **34**
  (COMPLETE, 45 provider calls). Bidder side is NOT in `documents`: it is
  package snapshot **9** (digest `9c3ffa6d...2307`) with 13
  `submission_documents` + 294 `submission_evidence_items`. Bid 1 (older,
  incomplete Calgary corpus without the RFP itself) is NOT the benchmark.
- **Real logical artifacts (4, from 13 files)**: Appendix C technical
  proposal PDF (TECHNICAL_PROPOSAL; embedded PRICING/MULTI_PARTY
  secondaries from its "PART 6 -- PRICING: Provided in Appendix D" and
  "PART 2 -- CONSORTIUM" headings; 18 pages, 16 sections, 181 evidence),
  completed Appendix D workbook (PRICING_FORM; sheet "Price Form", input
  cells D6/D7/D8 completed formulas; 32 evidence), Appendix E PDF
  (SUBMISSION_FORM; 13 evidence incl. 4 label->value fields), B2
  Multi-Party Confirmation PDF (MULTI_PARTY_FORM; Phoenix Consulting
  Canada lead + Inquisitive Talent; 68 evidence). All four authoritative
  members come from the nested `Appendices Submission_Phoenix Consulting
  Canada.zip` (the buyer's Q&A #50 confirms "a Zip folder is
  acceptable"); DOCX sources / re-saved workbooks are
  ALTERNATE_REPRESENTATION, the outer PDFs BYTE_IDENTICAL_DUPLICATE,
  `APPENDIX E.docx` SUPERSEDED_OR_DRAFT_VARIANT -- none double-counted.
- **Integration-shape fixes found on the real files** (all deterministic):
  opt-in ONE-level nested ZIP expansion
  (`extractor.unpack_submission_package(expand_nested_zips=True)`, same
  safety guards, default callers unchanged); representation linking
  (`submission_package.link_representations`); PDF label->value form
  tables (`_pdf_form_table_fields`, merged-cell continuation rows); PDF
  tables emitted in reading order (were attributed to the previous
  section); DOCX content controls (`w:sdt`) descended (real Appendix E
  labels were dropped); placeholder regex needs a word boundary
  ("Enterprise ..." read as an "enter" placeholder); buyer-named
  questionnaire without a document anchor -> possibly portal-native.
  Contract version `check-1.1.0`.
- **Known-bad regression now structurally prevented**: "Price Form
  missing", "Submission declarations missing", "Multi-party confirmation
  not provided" all screen CONTRADICTED_BY_PACKAGE against the persisted
  real package; 0 of 47 buyer requirement inputs permit an absence claim
  (45 ARTIFACT_PRESENT, 2 POSSIBLY_PORTAL_NATIVE: SAP Ariba registration
  and the Social Procurement Questionnaire).
- **Buyer-side gaps reported, not patched** (CHECK-2 preconditions):
  `full_analysis.build_canonical_package` projects `requirement_type=None`
  for this run (raw requirements carry `category`) and zero
  `scoped_criteria` (no `evaluation_occurrences`/`scoped_criterion_
  evaluation`; the 20 raw `evaluation_criteria` hold the real 30/20/30/10
  + Price 10 table plus conflicting Q&A-log weight restatements, flagged
  by Fast Analysis's own `evaluation_weight_conflicts`); identity merge
  chose the CGC title and the stale 2026-07-07 deadline although
  Addendum Four's 2026-07-16 16:00:59 MST is in `canonical_milestones`;
  `page_limits`/`submission_method` empty (the 20-page limit and SAP Ariba
  exist only as requirement text); the RFP's B2 "must include a
  Multi-Party Confirmation Form" sentence lives in a DOCX content control
  the buyer extractor does not read, so no canonical multi-party
  requirement exists (commissioning used it verbatim, labelled, never
  persisted).
- Tests: `tests/test_check11_real_calgary_benchmark.py` (derived fixtures
  `tests/fixtures/calgary_26_1603_real_submission_benchmark.json` --
  content-free -- and `calgary_26_1603_canonical_buyer_snapshot.json`;
  real-file tests skip unless `CHECK11_BIDDER_ZIP`/`CHECK11_BUYER_ZIP`
  or the default Downloads paths exist). One-off scripts:
  `scripts/commission_check11_calgary_buyer.py`,
  `scripts/commission_check11_calgary_bidder.py`.

**CHECK-1.2 (Calgary Buyer Canonicalization Closure) -- 2026-09-27.** Fixes
the three buyer-side canonicalization defects CHECK-1.1 found and
explicitly left unpatched (immediately above). All three are GENERAL
fixes in the frozen Layer 1/2 canonical modules (`canonical_procurement.py`
/ `procurement_normalization.py` / `fast_analysis.py` step 5) -- the first
change to those files since MA-1 froze them (`ee1cf42`); see
`tests/test_full_analysis_ma2a.py::test_frozen_canonical_layers_untouched_by_ma2a`,
whose historical range was narrowed to `ee1cf42..943623e` (the MA-2A
family's own commits) so it keeps proving what its name says without
blocking this authorized later amendment. No migration; no CHECK-2 work;
migration 021 / bidder-side evidence untouched. Zero Anthropic/model calls
anywhere in this task (verified: every fix is pure/deterministic; the real
bid 1360 recomputation below re-ran only local Python against the
already-downloaded RFP DOCX bytes and the already-persisted Fast Analysis
run 34 raw snapshot).

- **Defect A (scoped criteria empty) -- root cause**: `procurement_
  normalization.build_scoped_criterion_records` (and its `full_analysis.
  build_canonical_package` recompute fallback) only ever read `result.
  evaluation_occurrences` -- the V4 FOCUSED "rated_criteria" task's own
  shape. Run 34's routing never dispatched that focused task, so
  `evaluation_occurrences` was genuinely empty even though 20 real rated
  criteria sat in `result.evaluation_criteria` (the general route's own
  `stage`/`parent_stage`/`weight`/`threshold` shape) the whole time. Fix:
  new pure adapter `procurement_normalization.criteria_as_scoped_
  occurrences()` converts the general-route shape into the occurrence
  shape the existing scoping logic already consumes (never inventing a
  criterion/weight; `category_scope` deliberately left empty rather than
  guessing at `parent_stage`, which is a table heading, not a service
  category) -- wired as a fallback in `fast_analysis.py`'s step 5 (only
  when `evaluation_occurrences` is truly empty) and in `full_analysis.
  build_canonical_package`'s existing recompute path, so both a live run
  and a recompute from an already-persisted snapshot benefit. Live-proven
  against the real, already-persisted run 34 snapshot: 0 -> 13 scoped
  criteria records recovered (Firm Experience 30%/60% threshold, Team
  Experience and Qualifications 20%, Service Delivery 30%, Social
  Procurement 10%, Pricing/Price 10%, the 2.1/2.2 Key Personnel/Other
  Personnel 10%/10% subcriteria, Understanding of the Services, and the
  three pricing-formula line items 55%/35%/10%), each with its real
  authoritative source document -- zero new extraction, zero model call.
- **Defect B (stale deadline wins) -- root cause**: TWO compounding bugs
  in `canonical_procurement.py`. (1) `classify_identity_role` had no
  concept of a Q&A log; a filename like "QA Log ..._Updated _July
  08_2026.xlsx" fell through every pattern to the
  `IDENTITY_ROLE_PRIMARY_SOLICITATION` default. (2)
  `AUTHORITY_BY_FIELD_FAMILY["identity"]` (the ranking `merge_identity_
  fields_with_provenance` used for EVERY doc-metadata field, deadlines
  included) ranks `PRIMARY_SOLICITATION` above `AMENDMENT` -- correct for
  title/client/file_number, wrong for an amendable field like a
  submission deadline. Together: a Q&A log restating the OLD deadline
  outranked Addendum Four's genuine amendment of it. Fix: new
  `IDENTITY_ROLE_QA_LOG` role (recognized before the default fallback,
  never given authority in any ranking -- last-resort only, same
  treatment `AMENDMENT` already had for "identity"); new `"deadline"`
  field family (`AMENDMENT` > `PRIMARY_SOLICITATION` > `SUPPORTING`) and
  `FIELD_FAMILY_OVERRIDE_BY_FIELD` (`submission_deadline`/
  `clarification_deadline`/`submission_time` -> `"deadline"`, looked up
  PER FIELD inside `merge_identity_fields_with_provenance` regardless of
  the blanket family a caller passes, so the one existing `field_family=
  "identity"` call site needs no change); within the winning role, several
  same-authority documents (e.g. two addenda) now resolve to the LATEST
  ISO-date value rather than whichever was scanned first -- never a
  cross-role "latest wins" (a lower-authority role's date is never even
  compared once a higher role has an entry). Live-proven against the real
  run 34 snapshot: OLD merge (unmodified `canonical_procurement.py` from
  this task's starting commit) -> stale `2026-07-07`; FIXED merge ->
  correct `2026-07-16` (Addendum Four, `2026-07-15` clarification
  deadline), with `canonicalize_milestones` (unchanged, already correct)
  continuing to preserve `2026-07-07`/`2026-07-14`/`2026-07-16` as three
  distinct, non-collapsed provenance rows.
- **Defect C (DOCX content controls not extracted) -- root cause**:
  `extractor.extract_docx_with_metadata`'s python-docx path only ever read
  `doc.paragraphs`/`doc.tables` (direct top-level children), never
  descending a structured document tag (`w:sdt`, block or inline),
  `w:customXml`, or `w:smartTag` wrapper -- and it appended every table
  after all paragraphs regardless of true document position. Fix: a
  document-order block walker (`_docx_walk_blocks`) that descends content
  controls/custom XML at body, row, cell and run level (never emitting a
  wrapper's own aggregate text alongside its children -- no duplication),
  new `meta["content_controls"]` counts and a `meta["blocks"]` location
  trail. Live-proven against the real bid 1360 RFP DOCX: extracted text
  grew from 28,856 to 114,677 characters (342 block paragraphs + 19 inline
  paragraphs + 12 table rows recovered from content controls); the B2
  "Each proposal ... must include a Multi-Party Confirmation Form
  completed and signed by all Team Members" sentence (previously entirely
  absent -- the old extractor only surfaced surrounding checklist
  boilerplate that happened to sit outside a content control) is now
  present in the extracted text under its real `APPENDIX F` section
  marker, ready for the SAME existing requirement-extraction path every
  other buyer requirement already goes through (this task does not
  special-case the phrase, and does not fabricate a canonical requirement
  from the bidder's own B2 evidence -- getting this specific sentence into
  a NEW canonical `requirements` entry for the already-COMPLETE run 34
  would require either a full corpus re-run (forbidden by this task) or a
  new, bounded, requirement-schema-only model call over just this
  recovered passage, which this task did not make; a future targeted
  re-extraction pass is the correct next step, tracked here rather than
  silently declared done).
- Tests: `tests/test_check12_calgary_buyer_closure.py` (18 -- DOCX content
  control extraction incl. no-duplication and inline-run cases, general-
  route scoped-criteria fallback, deadline amendment authority incl. QA-log
  non-authority and multi-amendment tie-breaking, milestone-provenance
  preservation, multi-party-clause-now-extracted, bidder-form-alone-never-
  creates-a-buyer-requirement). Full suite: 3426 passed, 2 skipped (no
  change in skip count), 0 failed, run twice (once before the frozen-test
  range fix, once after).

**CHECK-1.3 (Final Multi-Party Requirement Gap) -- 2026-09-27.** Closes the
one gap CHECK-1.2 left open: the real City of Calgary B2 obligation now
exists as a canonical buyer requirement for bid 1360. **Zero Anthropic
calls** (the deterministic path sufficed; the authorized single bounded
call was not needed), no Fast Analysis rerun, no migration, no database
write, run 34 untouched (raw snapshot md5 `d9020f8e...` identical before
and after; still the bid's only analysis run). No CHECK-2 work.

- **Buyer source**: `S-PT-073-RFP with Price - V2.5_..._June 12.docx`
  (buyer document, bid 1360 `RFP / Source`), section `APPENDIX F - OTHER
  ATTACHMENTS`, sub-heading `B2:  MULTI-PARTY CONFIRMATION FORM`, a
  content-control paragraph (extractor `blocks[564]`, `content_control:
  true`): "Each proposal that is submitted on behalf of, and contemplates
  the provision of the Deliverables by a Multi-Party Team must include a
  Multi-Party Confirmation Form completed and signed by all Team Members."
  Next line (context): "THIS FORM TO BE COMPLETED ONLY IF THE PROPOSAL IS
  SUBMITTED BY A TEAM OF PROPONENTS ...".
- **Mechanism (general, not Calgary-specific)**: `procurement_
  normalization.recover_uncovered_required_form_obligations(documents,
  existing_requirements)` -- a normative ("must"/"shall"/"required to")
  obligation to include/submit a capitalized, buyer-NAMED "... Form" whose
  name no existing requirement mentions is carried VERBATIM in the existing
  Fast Analysis requirement schema (`category` "Mandatory" from the modal,
  `semantic_type` SUBMISSION_REQUIREMENT, restricting subject clause kept
  verbatim as `applicability_condition`, `source_refs`/`source_locator`/
  `source_context`, `requirement_origin =
  DETERMINISTIC_REQUIRED_FORM_RECOVERY`), then canonicalized with the SAME
  `canonicalize_requirements`. Fail-safe towards not adding (a form named
  anywhere in existing requirements is covered), idempotent, table rows /
  negated modals / lower-case "form" ignored, and only plain (filename,
  text) buyer-corpus pairs accepted (bidder `EvidenceItem`/
  `SubmissionDocument` -> TypeError). Wired in two places: `full_analysis.
  build_canonical_package` (the existing recompute path, only when
  `documents` are supplied; recovered requirements are APPENDED so every
  existing REQ-<i> is unchanged) and `fast_analysis.py` step 5 (future runs,
  before canonicalization). Against the real corpus it recovers exactly one
  requirement for Calgary (the Submission Form obligation is already
  covered by run 34) and none for Bank of Canada (run 19; package digest
  unchanged).
- **Persistence = recomputation, not a new row**: the canonical buyer model
  for bid 1360 is `analysis_service.build_full_analysis_package(34)` --
  immutable run 34 raw snapshot + the persisted buyer documents 199-211 --
  which now yields **REQ-46** (47 canonical requirements). This is the same
  existing mechanism CHECK-1.2's 13 scoped criteria use. Caveat:
  `documents_only_if_needed=True` (the durable FULL path's builder) skips
  corpus download when a snapshot already has `category_scope_items`; run
  34 has none, so the FULL path includes REQ-46 too.
- **Canonical requirement**: REQ-46, Mandatory, SUBMISSION_REQUIREMENT,
  applicability SUBMISSION_WIDE (conditional on a Multi-Party Team, per the
  verbatim condition). Expected evidence (`derive_expected_evidence`):
  MULTI_PARTY_FORM > SUBMISSION_FORM > TECHNICAL_PROPOSAL, basis
  STATED_IN_REQUIREMENT. `submission_package.map_requirement_to_submission`
  now accepts a CanonicalPackage requirement's `canonical_id` as its req_id.
- **Real B2 candidates** (package snapshot 9, reloaded from migration-021
  rows): ARTIFACT_PRESENT, primary role present, 5 candidates all in
  `B2 Multi-Party Confirmation Form_Phoenix Consulting Canada & Inquisitive
  Talent.pdf` (doc `916bc146885a9d0b7a44980f`, logical artifact
  `LA-9ff3a2721101c45d`, 68 evidence items): `EV-7117f788c301e7cb5c17`,
  `EV-02121fe4dcea4d8d98b6`, `EV-444aef958ab32b7900b8`,
  `EV-79daf9954929fb8d21e8`, `EV-334732da15da70757250`; both "Phoenix
  Consulting Canada" and "Inquisitive Talent" recoverable from the B2
  evidence; cross-bid resolution rejected. Candidates only -- no
  adjudication.
- **Side fix found on the real data**: `canonical_procurement.
  _CATEGORY_ID_RE` read a document VERSION token ("V2.5", "V4.0") as a
  category id, making every requirement derived from such a file
  CATEGORY_SPECIFIC to a phantom "V2"/"V4" category. Narrowly excluded
  `V<n>.<n>` only (D1.1-style numbering still yields D1). Affects fresh
  derivation only; run 34's stored applicability values (which carry the
  old phantom ids for 20 requirements) are untouched, as history.
- **Regression (live, `scripts/commission_check13_calgary_multiparty.py`,
  read-only, every Anthropic entry point poisoned, 0 attempts)**: 13
  bidder files / 4 logical artifacts / 294 evidence (evidence-id digest
  unchanged); Appendix C TECHNICAL_PROPOSAL, completed Appendix D
  PRICING_FORM, Appendix E SUBMISSION_FORM, B2 MULTI_PARTY_FORM; 13 scoped
  criteria; canonical deadline 2026-07-16 with 2026-07-07 / 2026-07-14
  milestones still preserved.
- Tests: `tests/test_check13_multiparty_requirement_closure.py` (21 -- 15
  synthetic incl. buyer/bidder separation, service-path read-only, step-5
  recovery with stubbed extraction; 6 real-chain, using the committed
  byte-identical run 34 raw snapshot fixture `tests/fixtures/calgary_26_
  1603_run34_raw_snapshot.json`, sha256 `45543c0a...`, plus the real
  buyer/bidder ZIPs, skipped when absent). Full suite: 3447 passed, 2
  skipped. `scripts/commission_check11_calgary_bidder.py`'s labelled
  `SUPP-B2-VERBATIM` input (and the CHECK-1.1 fixture row carrying it) is
  historical and now superseded by canonical REQ-46.
- **CHECK-2 readiness**: buyer source -> canonical REQ-46 -> MULTI_PARTY_FORM
  -> real B2 candidates is proven on real data. CHECK-2 must take buyer
  requirements from `build_full_analysis_package(run_id)` (documents
  included), not the raw snapshot's `requirements` list.

**CHECK-1 is COMPLETE and FROZEN** (CHECK-1 / 1.1 / 1.2 / 1.3 above).
`submission_package.py`, the migration-021 registry and the buyer-side
CHECK-1.x closures were NOT modified by CHECK-2A; reopen them only for a
concrete correctness defect, reported explicitly.

**CHECK-2A (Requirement & Evaluation Coverage Adjudication) -- 2026-09-27.**
The first CHECK adjudication layer: `check_coverage.py` (pure core, no
Streamlit, no DB/Storage I/O; the only side effect is the injected /
MA-1-shared bounded model call). Compute-and-return only -- nothing is
persisted, no migration 022 (durable CHECK runs are deferred to CHECK-2B).
No UI / report / PDF, no claim assurance, no score, no win probability, no
predicted evaluator marks, no strengths/weaknesses/recommendations.

- **Buyer truth**: `buyer_objects_from_canonical_package` -- every REQ-* and
  CRIT-* of `full_analysis.CanonicalPackage` (`build_canonical_package` with
  the buyer documents, i.e. incl. REQ-46), carried VERBATIM (the full
  unclipped Fast Analysis description is used only when the canonical clip
  provably came from it; raw `category` recovered the same way). Criteria keep
  label, `weight`, all `weight_variants`, `minimum_score` and source refs.
- **Scope gate** (`classify_assurance_scope`, deterministic, buyer-agnostic):
  SUBMISSION_RESPONSE_REQUIRED / SUBMISSION_EVIDENCE_REQUIRED /
  EVALUATION_RESPONSE are the only checkable scopes; PORTAL_NATIVE ->
  NOT_VERIFIABLE_FROM_FILES; POST_AWARD_OBLIGATION / BUYER_PROCESS /
  INFORMATIONAL / DEEMED_BY_SUBMISSION -> NOT_APPLICABLE (never a proposal
  gap); empty buyer wording -> HUMAN_REVIEW_REQUIRED. DEEMED_BY_SUBMISSION is
  established only from the buyer's OWN document ("By submitting a proposal
  ..., we (the proponent) acknowledge ...") with the requirement's source
  excerpt located after that sentence; an artifact-anchored instruction from
  the same document stays checkable.
- **Candidate retrieval** (`object_evidence`): the whole material-role
  artifact (pricing workbook / submission form / multi-party form) when the
  role is material; the heading-matched proposal section (`anchor_section`,
  hints = labels of the criteria that link to the requirement + its own
  heading); exact buyer-phrase matches (`phrase_matches`, IDF-weighted
  bigrams); then CHECK-1 `map_requirement_to_submission` candidates. Page
  furniture / derived restatements / content duplicates dropped; bounded
  (70 per object, 110 per batch) -- never the registry, never the package.
- **Deterministic adjudication** (`deterministic_adjudication`, sentence by
  sentence; any unhandled sentence -> model): required named form present +
  completed + parties identified + one completed signatory section per party
  (multi-party); pricing workbook input cells completed + lump-sum / travel /
  per-item rows; named submission-form table with an explicit value
  ("Not Applicable"); page limit vs parsed page count; portal sentences ->
  unverifiable element; prescribed pricing assumptions ("For the purposes of
  the Pricing Form, pricing shall be based on ...") and legal-status
  eligibility without a proof request -> NOT_VERIFIABLE; post-award /
  illustrative / arithmetic sentences -> non-obligation. Pricing evaluation
  criteria (label or buyer pricing-row excerpt) are adjudicated against the
  real workbook (item row -> price cell); price level is never judged.
- **Criteria**: `link_criterion_to_requirements` (label / >=2-word label
  segment in the requirement, criterion number heading the requirement's
  numbering, or >=60% buyer-excerpt containment) ->
  `derived_criterion_adjudication`: an independent record per criterion
  (own weight / variants / threshold) derived from the linked requirements'
  element-level results, missing elements tagged with `source_object_id`,
  evidence shared (not duplicated). A criterion with its own prompt goes to
  the model.
- **Model adjudication**: `plan_model_batches` groups by coherent domain
  (material artifact domain, else the mapped proposal section); target
  `MODEL_CALL_TARGET`=10, `MODEL_CALL_HARD_CEILING`=12 raises
  `BatchPlanningError` BEFORE any call. One call per batch via
  `full_analysis._call_model` (haiku-4-5, same helper/parse/telemetry),
  zero retries; the prompt carries only the batch's buyer objects (verbatim),
  the package file list and PE#-aliased evidence.
- **Evidence assurance** (`reconcile_batch_response`, fail closed): ids
  resolved through `section_drafting.evidence_id_registry` (PE# bidder /
  CE# buyer) + `reconcile_structured_result` + `reconcile_material_claims`,
  then `SubmissionEvidenceRegistry.filter_valid` (bid-bound) and the
  material-role gate; rejections recorded (NOT_ISSUED / BUYER_SOURCE /
  CROSS_BID / WRONG_ARTIFACT_ROLE). A requested element must be verbatim buyer
  wording; ADDRESSED/PARTIAL need surviving evidence; ADDRESSED with an
  absent element -> PARTIAL; NOT_ADDRESSED needs a checkable scope, no
  cited support, a CHECK-1 artifact status permitting absence and survival of
  `screen_absence_claim`; wording deleted by a buyer AMENDMENT
  (`amendment_supersessions`) and price properties a completed price cannot
  show are reclassified, never counted missing; an omitted object ->
  HUMAN_REVIEW_REQUIRED. `artifact_blind_regression_screen` re-checks the
  final output.
- **Real Calgary acceptance (bid 1360 / run 34 / snapshot 9)**,
  `scripts/commission_check2a_calgary.py` (reads only; every DB write fn and
  model_usage_events recording poisoned; run 34 snapshot sha256 `45543c0a...`
  unchanged): 60 buyer objects (47 requirements + 13 criteria); 23 excluded
  (5 post-award, 8 buyer-process, 3 informational, 7 deemed-by-submission),
  3 portal-native, 1 empty requirement (REQ-16); 26 scope-gate, 17
  deterministic, 9 model, 8 derived. Live provider calls: run 1 = 5 (its
  manual inspection found REQ-42's point-of-contact passage not retrieved,
  REQ-40 judged against wording Addendum One deleted, and pricing-assumption
  / eligibility sentences sent to the model -- logic fixed), final run 2 = 4
  (batches: pricing 4 objects / firm experience 2 / personnel 2 / service
  delivery 1; 36,004 input + 5,704 output tokens); 9 in total. The last
  post-validation rule (price properties) was applied to run 2's recorded
  output by deterministic replay (`... replay`, zero calls). Final status
  counts: ADDRESSED 18, PARTIALLY_ADDRESSED 11, NOT_ADDRESSED 0,
  NOT_APPLICABLE 23, NOT_VERIFIABLE_FROM_FILES 6, HUMAN_REVIEW_REQUIRED 2.
  REQ-46 ADDRESSED deterministically from the real B2 (Phoenix Consulting
  Canada + Inquisitive Talent, signatory blocks in both party sections);
  Price / Pricing / Items 1-3 ADDRESSED from the real Appendix D cells;
  REQ-33 / REQ-37 ADDRESSED from Appendix E's explicit "Not Applicable"
  tables; no artifact-blind false-missing finding. Known residual: one
  model element-level misjudgment (REQ-41 "three examples from the past five
  years" marked PARTIAL although all three are dated 2024-2026) that no
  evidence-id rule can catch -- REQ-41's overall PARTIAL is correct on other
  elements.
- Tests: `tests/test_check2a_coverage_adjudication.py` (49; synthetic,
  zero provider calls; the REAL Calgary section replays the content-free live
  record `tests/fixtures/calgary_26_1603_check2a_replay.json` against the
  real ZIPs, skipped when absent). Full suite: 3496 passed, 2 skipped.

**CHECK-2A is ACCEPTED** (commit `b488749`); its adjudication semantics are
unchanged by CHECK-2B (the only edits to `check_coverage.py` are additive: an
observation-only `on_event` hook on `run_check_coverage` and five component
version constants used by the fingerprint).

**CHECK-2B (Durable Proposal Assurance Runs) -- 2026-09-27.** Makes CHECK-2A
durable, reproducible, reopenable and safe against duplicate model spend,
mirroring MA-2A's Full Analysis architecture exactly. No UI, no PDF, no claim
assurance, no recommendations, no rewriting.

- **Run model**: `analysis_runs` row with `analysis_mode='CHECK'` (reused, not
  a parallel framework): `input_fingerprint`, `source_analysis_run_id` (the
  COMPLETE FAST run whose raw snapshot is the buyer canonical input), new
  `source_package_snapshot_id` (composite `(id, bid_id)` FK to
  `proposal_package_snapshots` -- the bidder package evaluated),
  `engine_version` (`check-coverage-check-2a.1.0/durable-check-2b.1.0`),
  status QUEUED -> RUNNING -> COMPLETE | PARTIAL | FAILED, timestamps,
  `last_progress_at`, failure reason/detail, telemetry summary. The existing
  one-active-run index gives CHECK one active slot per bid.
- **Service**: `check_run_service.py` -- `start_check_run` (inputs ->
  fingerprint -> ONE advisory-locked RPC: CREATED / ACTIVE_RUN_EXISTS /
  REUSED_COMPLETE / EXISTING_FAILED / EXISTING_PARTIAL; only CREATED executes;
  FAILED/PARTIAL need explicit `retry=True`), `get_check_run_status` (events +
  `derive_check_progress` counts + `is_check_run_stuck`),
  `get_check_run_result` (rows -> CHECK-2A `CheckCoverageResult`, zero
  provider calls, `result_digest` verified), `mark_check_run_stuck` (explicit
  only). `tenancy.*_check_run_*_for_organization` wrappers (require_bid_access
  first). `load_check_inputs` is the production loader (run raw snapshot +
  buyer 'RFP / Source' documents + migration-021 snapshot rows).
- **Fingerprint** (`check_fingerprint_inputs` / `compute_check_fingerprint`,
  `check-2b-fp-1`): buyer = canonical snapshot + content digests, requirement
  / criterion ids, digest of the exact `BuyerObject`s CHECK reads (verbatim
  wording, weights / variants / thresholds / prompts / applicability / source
  refs), expected evidence roles, normalized text sha of every buyer document
  (deeming statements); bidder = package digest, document roles / logical
  artifacts / representations, full evidence-registry content (sorted, order
  independent); architecture = CHECK-2A contract + scope-gate / retrieval /
  deterministic / adjudication / prompt-schema versions + CHECK-1 contract;
  model = provider, model id, output ceiling, call bounds, sha of the prompt
  rules. Excludes bid / run / event / snapshot row ids, timestamps, UI state.
- **Persistence** (migration 022): `analysis_results.check_coverage_result`
  (run-level counts / digests / fingerprint inputs / batch log /
  `run_integrity`); `check_adjudications` (one immutable row per buyer object,
  the full CHECK-2A contract, structured lists as jsonb arrays, plus
  `evidence_refs` = logical artifact / document / locator per cited id);
  `check_adjudication_evidence` (every verdict- AND element-level evidence id,
  FK to `submission_evidence_items (bid_id, package_snapshot_id,
  evidence_id)` -- an unknown, buyer-source, cross-bid or cross-snapshot id
  aborts the whole finalize); `check_semantic_batches` (objects, candidate
  evidence ids, alias map, structured model output, reconciled output,
  provider / model / stop_reason / parse_status / tokens / latency, prompt
  sha256 -- never the prompt, EFFECTIVE status); `check_run_events`
  (append-only, sequenced, counts only: RUN_CREATED, RUN_STARTED,
  BUYER_SCOPE_CLASSIFIED, CANDIDATE_RETRIEVAL_COMPLETE,
  DETERMINISTIC_ADJUDICATION_COMPLETE, SEMANTIC_BATCH_STARTED / COMPLETED /
  FAILED, EVIDENCE_ASSURANCE_COMPLETE, RUN_COMPLETED / PARTIAL / FAILED).
  Python re-validates before persisting (`validate_result_for_persistence`);
  a violation finalizes FAILED with no adjudication rows.
- **Status / truncation** (MA-2A.2 lesson): a batch is COMPLETE only if no
  adjudicator error, provider stop_reason normal, parse COMPLETE and every
  object returned; `max_tokens` / RECOVERED_TRUNCATED / abnormal stop /
  omitted object -> PARTIAL (FAILED if nothing survived). Any non-COMPLETE
  batch -> run PARTIAL; `finalize_check_run` refuses COMPLETE unless
  `run_integrity='COMPLETE'`, every batch row COMPLETE and batch count == plan.
  HUMAN_REVIEW_REQUIRED / NOT_VERIFIABLE_FROM_FILES objects never make a run
  partial.
- **Provider accounting**: calls go through `full_analysis._call_model`
  with `telemetry_context={workflow:'check_coverage', analysis_run_id:<CHECK
  run>}` -> existing `model_usage_events` (no second system). Run telemetry
  separates `adjudicator_invocations` from `live_provider_calls` and records
  `adjudication_source` (PROVIDER / INJECTED_ADJUDICATOR /
  REPLAY_OF_RECORDED_LIVE_OUTPUT). REUSED_COMPLETE = zero calls.
- **Stale runs**: `STALE_RUN_POLICY` (`check-2b-stale-1`: 10 min no durable
  progress / 45 min age), detection only; never auto-rerun.
- **Calgary acceptance (zero provider calls)**: `scripts/commission_check2b_
  calgary.py persist|reopen <out_dir>` loads the LIVE inputs read-only via
  `load_check_inputs` (bid 1360, run 34, snapshot 9: 294 evidence items),
  replays the recorded validated CHECK-2A output, persists into
  `tests/check2b_fake_db.FakeCheckDB` (the in-memory migration-022 contract --
  022 is not live) seeded with the live snapshot-9 ids, dumps it, and reopens
  it in a fresh process: 60 objects (47 req + 13 criteria), ADDRESSED 18 /
  PARTIAL 11 / NOT_APPLICABLE 23 / NOT_VERIFIABLE 6 / HUMAN_REVIEW 2 /
  NOT_ADDRESSED 0, 3 portal-native, all 74 distinct cited ids (269 links)
  present live in bid 1360 snapshot 9 and under no other bid, fingerprint
  `48e9a2e1...` recomputed identically, identical re-start ->
  REUSED_COMPLETE with 0 adjudicator invocations.
- **Known limitation retained (REQ-41)**: the CHECK-2A model judged REQ-41's
  "three (3) examples from the past five (5) years (other than The City)"
  element PARTIAL although the examples are dated 2024-2026. No general
  deterministic rule is justified: the recency years sit in bidder prose (not
  structured dates) and the element also carries "(other than The City)" and
  an example count -- legitimate semantic judgement. Persisted unchanged;
  regression test `test_req41_known_model_imperfection_is_preserved_not_
  overridden`.
- Tests: `tests/test_check2b_durable_runs.py` (fake: `tests/check2b_fake_db.py`).

**CHECK-2B.1 (Live Durable-Run Commissioning) -- 2026-09-27.** Migration 022
applied live (project `whonalbdpbubaqhpzrnw`, ledger `20260927153417
check_runs`) after a preflight of the live schema (021 highest, no CHECK
objects, analysis_runs / analysis_results / proposal_package_snapshots
`(id, bid_id)` / submission_evidence_items `(bid_id, package_snapshot_id,
evidence_id)` / model_usage_events / can_access_bid all as assumed, existing
FULL guard trigger compatible) and a review of every Python payload against
the columns / `->>` TEXT coercions / RPC signatures (all Calgary TEXT-bound
fields are str/None; no mismatch). The only pre-application edit to 022 was
its STATUS header comment (no SQL changed; a test asserts the executable SQL
equals `90945fd`'s). Directly verified live: 4 tables, RLS on, 4
authenticated-SELECT `can_access_bid` policies, 15 indexes, 5 triggers, 3
SECURITY DEFINER RPCs executable by service_role only.
- **Security probes (rolled back, zero residue)**: member reads run 37's
  rows; non-member authenticated and anon read 0; authenticated / anon direct
  INSERT rejected by RLS, UPDATE/DELETE affect 0 rows, RPC EXECUTE denied;
  service_role cannot UPDATE adjudications, DELETE events or touch a terminal
  run; cross-bid start / event / snapshot FK rejected; finalize citing another
  bid's evidence, a buyer id (`REQ-1`) or an unknown id aborts on the
  `submission_evidence_items` FK with nothing persisted.
- **Calgary durable CHECK run: bid 1360, run 37, COMPLETE** -- created through
  `check_run_service.start_check_run` (outcome CREATED) with the accepted
  CHECK-2A output replayed (`adjudication_source=REPLAY_OF_RECORDED_LIVE_
  OUTPUT`, `live_provider_calls=0`, `model_usage_events` unchanged at 355);
  fingerprint `48e9a2e172b2...` (source run 34, snapshot 9, 13 buyer docs,
  47 requirements + 13 criteria, 4 authoritative bidder artifacts, 294
  evidence items); 15 sequenced events, 4 COMPLETE batches, 60 adjudications,
  269 evidence links (74 distinct ids, all bid 1360 / snapshot 9). The
  source CHECK-2A provenance is stored as `source_adjudication_provenance`
  (`applies_to=SOURCE_ADJUDICATION_NOT_THIS_RUN`).
- **Fresh-process reconstruction from the DB only** (tenancy wrappers): every
  field of all 60 adjudications identical to the in-memory result, result
  digest `67b30896...` verified, statuses / methods / evidence ids identical
  to the accepted CHECK-2A record; REQ-46 ADDRESSED on B2, pricing criteria on
  Appendix D, REQ-33/37 on Appendix E, 3 portal-native NOT_VERIFIABLE, 2
  HUMAN_REVIEW, 23 excluded NOT_APPLICABLE, PARTIAL missing elements exact.
- **REUSED_COMPLETE against the real DB**: `tenancy.start_check_run_for_
  organization` with identical inputs (provider poisoned, no adjudicator) ->
  REUSED_COMPLETE run 37, zero new rows, zero calls. ACTIVE_RUN_EXISTS proven
  in rolled-back probes (RPC returns it for any fingerprint while a CHECK run
  is active; a direct second active row violates `idx_analysis_runs_one_
  active`; a second COMPLETE row for one fingerprint violates
  `idx_analysis_runs_check_complete_fingerprint`). Truncated / failed /
  abnormal-stop batches persist as PARTIAL / FAILED and finalize refuses
  COMPLETE over them.
- Historical integrity: run 34 row and result (legacy columns) byte-identical,
  snapshot-9 evidence (294) and submission documents unchanged.
- Observation (not changed): BUYER_SCOPE_CLASSIFIED's `portal_native` /
  `checkable` counts are plan-time scope-gate counts (2 / 34); the final result
  has 3 / 33 because one criterion's scope is set later by derivation.
- Characteristic (same as migration 020's FULL events): `check_run_events`
  rejects DELETE, so deleting a bid/run with CHECK events is blocked.
- REQ-41 remains the documented model limitation, persisted unchanged.
- Tests: `tests/test_check2b1_live_commissioning.py`. Full suite: 3589 passed,
  2 skipped.

**CHECK-2B is COMPLETE and FROZEN.** CHECK-2B persistence no longer relies
only on fake_db. The CHECK backend (`check_coverage.py`, `check_run_service.py`,
migration 022, canonical procurement / submission package logic) is frozen at
`e76e103`; CHECK-2C changed none of it.

**CHECK-2C (Client-Facing Proposal Assurance Workspace) -- 2026-09-27.** The
first customer-facing CHECK experience: an interactive review / comparison
workspace that RENDERS the durable CHECK-2B run. No PDF / export / report
in CHECK-2C itself (added by CHECK-2D, below), no claim-level assurance, no proposal generation,
no overall numeric score, readiness percentage, win probability or predicted
evaluator mark, no animation.

- **Navigation**: active-bid sidebar entry "🛡️ CHECK: Proposal Assurance"
  (`page == "stage_check_assurance"` in `app.py`), plus a link button on the
  existing CHECK page (`pages/stage_check.py`, link only, never a start). Its
  bid-scoped session keys (`chk_*`) are cleared on logout.
- **Architecture**: `pages/stage_check_assurance.py` (controller + Streamlit)
  and `components/check_workspace_view.py` (pure view model + HTML/CSS; no
  Streamlit / DB / model imports, status vocabulary pinned to check_coverage by
  a test). Reads ONLY `tenancy.get_check_run_status_for_organization` (durable
  run status, re-read every render -- never inferred from result rows),
  `tenancy.get_check_run_result_for_organization` (check_run_service's DB-row
  reconstruction) and CHECK-1.1's read-only `tenancy.load_submission_evidence_
  package_for_organization` (bounded evidence excerpts resolved only in THIS
  bid's registry; an unresolvable id is reported, never fabricated). A terminal
  run's bundle is cached per (bid, run) in the session, so filters / tabs /
  expanders / reruns never re-read it. It never imports `check_coverage` /
  `check_run_service` / a provider.
- **Explicit execution only**: "Run CHECK" (no run yet) / "Run CHECK again"
  call `tenancy.start_check_run_for_organization` (one call site) and inherit
  CHECK-2B's five outcomes unchanged; identical inputs -> REUSED_COMPLETE, zero
  calls. PARTIAL / FAILED -> labelled explicit retry. A RUNNING run shows
  durable progress counts (5 s status poll); a stale run offers only "Mark this
  run as stopped".
- **Hierarchy**: header (buyer, RFP id, run id / status / finish time,
  submission assessed) -> status banner (COMPLETE / PARTIAL with the
  non-complete semantic batches listed / FAILED falling back to the latest
  saved COMPLETE-or-PARTIAL run, labelled) -> five factual status counts
  (Addressed / Partially addressed / Not addressed / Not verifiable from files /
  Human review required) with the excluded non-submission count shown
  separately -> "Where to look first" (deterministic, documented ordering:
  criteria before requirements, highest buyer-stated weight, stated threshold,
  mandatory / submission-wide, status, persisted order -- `ATTENTION_ORDERING`)
  -> tabs: Evaluation criteria (every scoped criterion, attention-first, buyer
  weight / variants / threshold as buyer metadata), Requirements and filters
  (status / object type / assurance scope / expected evidence role /
  mandatory-only; defaults to partial + human review + not verifiable),
  Non-submission (grouped by scope, never gaps), Submitted files. Each finding
  is a card (PARTIAL: "Demonstrated" vs "Not demonstrated" from the persisted
  element lists, with a count sentence; ADDRESSED: compact, strongest evidence;
  NOT_VERIFIABLE / HUMAN_REVIEW: verbatim persisted reason + what to confirm)
  with an expander holding the side-by-side detail: LEFT "What the buyer asked
  for" (verbatim wording, scope, weight / threshold, buyer source doc /
  section / page / excerpt), RIGHT "What the bidder submitted" (filename, role,
  kind, page / section / sheet / cell / row / field locator, clipped excerpt or
  field value), CHECK conclusion beneath. Every status has a text label and a
  mark, never colour alone.
- **Real Calgary acceptance (bid 1360, run 37)**, rendered through a local
  read-only harness of the real page against the live DB (auth stubbed to the
  bid's organization; every provider / adjudication / CHECK-write path
  poisoned and logged): run 37 COMPLETE opened directly; counts 18 / 11 / 0 / 6
  / 2 plus 23 non-submission; 13 criteria with stored weights (Item 1 55%,
  Item 2 35%, Service Delivery 30%, Firm Experience 20% / 30% + 60% threshold,
  Team Experience 20%, others 10%, Understanding of the Services none stated);
  all 74 cited evidence ids resolved in snapshot 9; REQ-46 on the B2
  Multi-Party form, pricing criteria on Appendix D cells, REQ-33 / REQ-37 on
  Appendix E tables, portal-native REQ-38 / REQ-45 / Social Procurement
  NOT_VERIFIABLE, REQ-5 / REQ-16 HUMAN_REVIEW. `model_usage_events` 355 before
  and 355 after opening / navigating / filtering / expanding / refreshing:
  delta 0; zero poisoned-path hits; run 37 and its 60 adjudications / 15 events
  unchanged, no new CHECK run.
- REQ-41's documented model limitation is displayed as persisted (never
  overridden by the UI).
- Tests: `tests/test_check2c_assurance_workspace.py` (64; zero provider calls
  asserted across open / filter / detail / refresh / REUSED_COMPLETE; reuses
  CHECK-2B's `FakeCheckDB` for the real reconstruction path).

**CHECK-2C is COMPLETE.**

**CHECK-2D (Concise Proposal Assurance Report) -- 2026-09-27.** A client-ready
PDF rendered from the durable CHECK run. It never re-runs adjudication and
never calls a model: report generation is deterministic selection over the
persisted CHECK adjudications (zero provider calls, a release gate). No
migration, no report persistence (compute-and-render on demand), no CHECK
backend change (`check_coverage.py`, `check_run_service.py`, migration 022,
canonical procurement / submission package logic still frozen at `e76e103`).

- **Architecture**: durable CHECK result -> `components/check_report_model.py`
  (pure: no Streamlit / DB / PDF library / provider; `build_report_model`,
  `model_digest`, `report_filename`; reuses CHECK-2C's pure view helpers) ->
  `check_assurance_report.py` (reportlab renderer reusing the shared Bid
  Intelligence stack of `scripts/build_boc_bid_intelligence_preview_pdf.py`
  and MA-2C's `full_analysis_report.py` helpers: dark cover, brand fonts /
  tokens, table styling, running header / footer, page numbers). Entry point:
  `tenancy.export_check_assurance_report_for_organization(bid, org, run)` --
  bid ownership first, run must be a CHECK run of this bid, read-only
  (`check_run_service.get_check_run_result`, this bid's evidence registry, the
  bid row). Workspace: "Prepare / Download Proposal Assurance Report" in
  `pages/stage_check_assurance.py` (`export_labels`, `prepare_export`, cached
  per (bid, run) under `chk_export_*`; opening the page builds nothing).
- **Content**: cover; Assurance Overview (identity, five factual status
  counts, non-submission count separate, no score / percentage); Evaluation
  Criteria Overview (every scoped criterion: buyer weight / variants /
  threshold as buyer metadata, status, bounded buyer expectation, count-based
  conclusion); Findings Requiring Attention (index + detailed partials:
  Buyer expected / Demonstrated / Not demonstrated with [E#] citations);
  Human Review Required (verbatim persisted reasons; "what a reviewer should
  confirm" only from `element needs review:` segments or recorded
  unverifiable elements); Not Verifiable & Not Addressed (zero shown as zero);
  Addressed Mandatory Requirements (where the submission responded); Outside
  Proposal-Assurance Scope; Evidence Appendix (submitted artifacts + every
  cited reference, bounded excerpt / field value); Methodology & status
  definitions.
- **Deterministic selection** (`ATTENTION_CLASSES`): criterion PARTIAL / HR /
  NV / NOT_ADDRESSED, then mandatory / submission-wide requirements in the same
  status order, then other requirements; within a class higher buyer-stated
  weight, stated threshold, persisted order. A criterion derived from linked
  requirements points at those requirements' own element lists, so each
  element set appears once with every criterion it applies to. Citations E#
  are assigned in report order and only for ids that resolve in THIS bid's
  registry (unresolved ids are counted, never shown). The CHECK-2B replay
  placeholder segment "reason text omitted from content-free fixture" is not
  repeated in the report (`NON_SUBSTANTIVE_REASON_MARKERS`); persisted rows are
  unchanged. PARTIAL runs export as "Partial Proposal Assurance Report" with
  the non-complete batches disclosed; FAILED / RUNNING / QUEUED are not
  exportable. REQ-41's accepted model limitation is rendered as persisted.
- **Real Calgary acceptance (bid 1360, run 37)**: `scripts/export_check2d_
  calgary_report.py <out.pdf>` (production path, provider / adjudication /
  CHECK-write paths poisoned). Final PDF 14 pages (cover + 13), 86,167 bytes,
  semantic digest `c9407310790a...` (identical to an offline render of the
  same rows); counts 18 / 11 / 0 / 6 / 2 + 23 non-submission; all 13 criteria;
  11 attention findings (4 detailed partials REQ-41 / REQ-44 / REQ-42 /
  REQ-43, 2 human review REQ-5 / REQ-16, 5 not verifiable incl. portal-native
  REQ-38 / REQ-45); 33 evidence references across the 4 artifacts (Technical
  Proposal, Appendix D Price Form, Appendix E Submission Form, B2 Multi-Party
  Confirmation Form). `model_usage_events` 355 before and 355 after five live
  generations: delta 0; run 37 (60 adjudications, 15 events, 269 evidence
  links, adjudication-row md5) unchanged; still one CHECK run. Every page
  visually inspected; fixed during inspection: orphaned finding / sub-section
  headings, large blank areas from unsplittable blocks, a misaligned
  two-column element grid, old-style count numerals, ASCII table-rule noise in
  excerpts, double colons in field labels, glyphs missing from the brand font
  (mapped to plain equivalents).
- Tests: `tests/test_check2d_assurance_report.py` (47; zero provider calls
  asserted). `tests/test_check2c_assurance_workspace.py`'s "no export" guard
  replaced by "export only through the CHECK-2D read-only wrapper".

**CHECK-2D is COMPLETE; CHECK-2 is COMPLETE.** CHECK-3 is NOT started.

**CHECK-2D.1 (durable data & presentation hygiene) -- 2026-09-27.** Not a new
phase; CHECK-2 remains complete. Every customer-facing CHECK surface (CHECK-2C
workspace cards / finding detail / attention list / non-submission list and
the CHECK-2D report model + PDF) now renders ONE client-safe projection of
`ambiguity_or_review_reason`, `components/check_review_text.py`
(`client_safe_review_notes`, pure), applied at the single choke point
`check_workspace_view.review_notes` (`raw_review_notes` keeps the verbatim
segments for audit). It drops the CHECK-2B.1 commissioning placeholder
"recorded live adjudication (reason text omitted from content-free fixture)"
(written by `scripts/commission_check2a_calgary.py`'s `replay_adjudicator`,
because the content-free replay fixture deliberately omits model free text)
and restates check_coverage's validation-downgrade routing notation
("... -> HUMAN_REVIEW_REQUIRED") in plain language; an arrow is treated as
routing only when a known CHECK status token follows it, and buyer wording
("element needs review: ...") is never normalized. A HUMAN_REVIEW_REQUIRED
finding with no reason left shows a fixed neutral sentence, never an invented
one. Durable raw data is unchanged: run 37 was NOT modified and no
superseding run was created (migration 022's triggers make terminal runs
immutable and no audited correction path exists); run-37 adjudication /
evidence / batch / event / run-row hashes and `model_usage_events` (355)
verified identical before and after. Zero-call behavior preserved. Run-37
rows carrying the placeholder: 16 (9 MODEL requirements + 7 derived criteria;
REQ-5 is the only HUMAN_REVIEW_REQUIRED one); rows with routing notation: 5
(REQ-5, REQ-40, REQ-44, CRIT-service-delivery, CRIT-understanding-of-the-
services). Tests: `tests/test_check2d1_presentation_hygiene.py`.

**Calgary Prospect Pre-Demo Polish Pass -- 2026-09-28.** Final pre-demo polish pass following
the completed City of Calgary (RFP 26-1603, bid 1360, run 37) product rehearsal:
- P1: Suppressed internal benchmark/developer text ("check-1", "check-2", "migration 021",
  "fixture", "commissioning") in Calgary UNDERSTAND via permanent presentation-layer filter
  `_resolve_customer_safe_summary()` and updated factual bid notes in database.
- P2: Consolidated sidebar navigation to exactly ONE customer-facing CHECK entry point:
  `🛡️  4. CHECK: Proposal Assurance` (`app.py`), routing both `stage_check_assurance` and
  legacy `stage_check` cleanly to `page_check_assurance(bid_id)`.
- P2: Surfaced canonical procurement closing date (`2026-07-16`) dynamically in the top
  metric summary (`_resolve_canonical_deadlines()` via `canonical_procurement.merge_identity_fields()`
  and `analysis_result.canonical_milestones`) without hardcoding Calgary dates and without
  fabricating an Award Date.
- Zero model calls verified (`model_usage_events` delta: 0, 355 baseline preserved). Run 37
  COMPLETE with 60 adjudications and Run 34 COMPLETE preserved without modification.
- Tests: `tests/test_predemo_polish.py` (7 tests, all passing).

Absent an explicit task instruction otherwise, still do not: alter/reapply
migration 015, 016, 017, 018, 019, 020, 021 or 022,
activate the compact-wire prototype, change chunk sizes/max_tokens/model
routing/caching, reintroduce proposal-generation under another name, or
merge `main`/deploy.

## Migrations known in this repository (files, not live-database state)

Highest migration file present: **022** (`022_check_runs.sql`, CHECK-2B --
**applied and live-commissioned 2026-09-27 by CHECK-2B.1**, ledger entry
`20260927153417 check_runs`; first live CHECK run bid 1360 / run 37). Before it:
**021** (`021_submission_evidence_registry.sql`, CHECK-1, amended before first
application and **applied and live-commissioned 2026-09-27 by CHECK-1.1**,
ledger entry `20260926220922 submission_evidence_registry`). Before it: **020**
(`020_full_analysis_runs.sql`, **applied and live-commissioned
2026-09-22**, ledger entry `20260922202352 full_analysis_runs` — see
"MA-2A.1" below). Migration 019
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
