-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 018: Section Drafts — PI-3B durable persistence
-- ═══════════════════════════════════════════════════════════════════════════
-- Additive only. Does not modify migrations 001-017, does not touch any
-- bid/requirements/proposal_intelligence/organizational_memory/
-- requirement_evidence_enrichments table or column, does not backfill,
-- does not change any existing policy or GRANT.
--
-- Per this repo's established convention (migrations 004-017), this file is
-- NOT auto-applied by any code path and is NOT executed as part of this
-- authorization. Apply it manually via the Supabase SQL editor / dashboard,
-- after separate review, exactly the way migrations 004-017 were applied.
-- Live commissioning of this migration is an explicitly separate, later
-- task (PI-3A's own drafting call is already live-commissioned; this
-- migration is not). Migration 013 (Section Analyzer) remains unapplied
-- and is not a dependency of this one.
--
-- ── Why this table exists (why NOT an existing table) ──────────────────────
-- PI-3A (section_drafting.py) computes a structured SectionDraftResult for
-- one requirement but returns it ephemerally -- every call re-executes the
-- drafting model call from scratch, even for byte-identical inputs. PI-3B's
-- job is durable reuse: "analyze once, draft once, persist, reuse."
--
-- Three existing tables were considered and rejected before adding a new
-- one, per this phase's own "prefer reuse, do not automatically create a
-- new table" instruction (the same discipline migration 017 already
-- documented for OM-3B, extended here to the drafting result):
--
--   requirement_evidence_enrichments (migration 017) -- rejected: its rows
--     are OM-3B's EvidenceEnrichmentResult shape (evidence_state_before/
--     organizational_evidence/evidence_state_after/remaining_gaps) and
--     nothing else -- a section draft has an entirely different shape
--     (draft_text, requirements_addressed/missing, evaluation_criteria_
--     addressed, evidence_items_used in PI-3A's OWN evidence-id-registry
--     shape -- evidence_id/source_kind/claim_type/trust_class/note, never
--     OM-3B's memory-item-centric shape -- contradictions_or_caveats,
--     word_count, assurance_passed/assurance_issues). Overloading this
--     table with a second, unrelated result shape would be exactly the
--     "convert advisory AI reasoning into stated fact" / conflate-two-
--     domains anti-pattern this repo's standing rules forbid, and this
--     table's own rows are, by migration 017's design, immutable outputs
--     of ONE specific enrichment computation with no UPDATE path -- a
--     section draft is a materially different derived artifact with its
--     own independent freshness lifecycle (a draft can go stale from a
--     changed evaluation criterion or response constraint that never
--     touches OM-3B's own fingerprint inputs at all).
--   proposal_requirement_assessments / proposal_intelligence_findings
--     (migration 015) -- rejected for the same reasons migration 017's own
--     header already gives: both are immutable outputs of ONE specific
--     Proposal Alignment run (no UPDATE path), and a section draft must be
--     persistable even when no Proposal Intelligence run exists at all
--     (PI-3A's brief tolerates an absent `assessment` -- see
--     section_drafting.build_brief). Neither table's schema has any
--     column for drafted prose, evidence-id-registry citations, or
--     assurance results, and adding them would fabricate meaning these
--     tables were never designed to carry.
--   organizational_memory_items (migration 016) -- rejected outright, same
--     reasoning migration 017 already gave: a section draft references
--     MULTIPLE memory items (via PI-3A's evidence-id registry) and is
--     itself a new, bid-scoped derived artifact, not a single
--     organization-scoped memory item; writing it into this table would
--     violate migration 016's own immutable-provenance trigger's entire
--     purpose.
--
-- `section_drafts` is therefore a new, narrow, additive table, bid-scoped
-- (mirrors migration 015/017's own bid_id-direct convention -- RLS is
-- inherited transitively through can_access_bid, identical reasoning
-- here), storing ONLY the structured OUTPUT of section_drafting.
-- draft_section() + section_drafting.assure_section_draft() -- never a
-- copy of a whole source document, raw memory-item chunk content, or the
-- RFP (section_drafting.EvidenceItemUsed never carries a memory item's own
-- `content` field, exactly like OM-3B's MemoryEvidenceCandidate never
-- does -- see that module).
--
-- ── Freshness / invalidation (instruction 2) ────────────────────────────────
-- A single deterministic `input_fingerprint` (sha256, the SAME
-- canonicalization convention as proposal_intelligence.compute_package_
-- digest / evidence_strengthening.compute_input_fingerprint -- sorted-key
-- JSON, sha256 hex) computed by section_drafting.
-- compute_draft_input_fingerprint() over the ENTIRE PI-3A SectionDraftingBrief
-- (minus pure routing/identity keys -- organization_id/bid_id/
-- requirement_id, which already determine the cache KEY, not the drafting
-- CONTENT) -- the brief itself is already PI-3A's own bounded, exhaustive
-- statement of everything the draft depends on (requirement identity/text,
-- mandatory flag, related-requirement context, evaluation criterion/
-- response guideline, response constraints, current-bid evidence state,
-- the requirement's own current-RFP source refs, the FULL persisted OM-3B
-- enrichment content actually included in the brief, and bounded related
-- Proposal Intelligence findings), plus SECTION_DRAFTING_CONTRACT_VERSION
-- (bumping it -- a prompt/logic change -- invalidates every prior
-- fingerprint even when every other input is identical, exactly like
-- EVIDENCE_STRENGTHENING_CONTRACT_VERSION already does for OM-3B). A
-- `(bid_id, req_id, input_fingerprint)` row is the canonical cache key --
-- deliberately a single fingerprint over the brief rather than a broader,
-- separately-reasoned dependency graph, per this phase's own "reuse
-- existing canonical JSON -> sha256 conventions" instruction: since the
-- brief already IS PI-3A's exhaustive bounded input domain, hashing it
-- whole is both correct and the simplest sufficient mechanism -- no
-- parallel dependency-tracking model is introduced.
--
-- ── Reuse / concurrency (instruction 5) ─────────────────────────────────────
-- get_or_create_section_draft() below mirrors migration 017's get_or_
-- create_requirement_evidence_enrichment() exactly: a transaction-scoped
-- advisory lock keyed on (bid_id, req_id) serializes two callers racing to
-- persist the SAME fingerprint for the SAME requirement -- the loser of
-- the race receives the winner's already-persisted row back rather than
-- creating a duplicate. The (bid_id, req_id, input_fingerprint) UNIQUE
-- constraint remains the final authority even if this function were
-- bypassed. The actual freshness CHECK (does a fresh row already exist for
-- the currently-computed fingerprint, so the expensive drafting model call
-- can be skipped entirely) happens one layer up, in tenancy.
-- get_or_generate_section_draft, via a plain SELECT read -- exactly the
-- same layering OM-3B already established (the analysis/drafting itself is
-- orchestrated in Python; only identity/dedup persistence goes through a
-- dedicated SQL function).
--
-- ── Immutable history (instruction 4) ───────────────────────────────────────
-- Rows are write-once -- there is no UPDATE path anywhere in this schema.
-- A changed fingerprint always creates a NEW row (a new "version" of this
-- requirement's draft, distinguishable by created_at/id) rather than
-- overwriting the prior one; an identical fingerprint always reuses the
-- existing row. This preserves full draft history per requirement for a
-- future "what changed between the earlier draft and the current draft"
-- capability -- not built in this migration, but never foreclosed by it
-- either, since nothing here ever destroys a prior row.
--
-- ── RLS: identical posture to migrations 015/017 ────────────────────────────
-- Authenticated SELECT only (transitive `can_access_bid`), NO authenticated
-- INSERT/UPDATE/DELETE policy at all -- only service_role (bypasses RLS by
-- Postgres's own definition), in practice only through the RPC below, may
-- write. This is RLS as the actual enforcement mechanism (RLS enabled +
-- absence of a write policy), not table GRANTs -- identical reasoning to
-- migrations 015/016/017's own notes on the same topic.
-- ═══════════════════════════════════════════════════════════════════════════

create table if not exists section_drafts (
    id                                  bigserial primary key,
    bid_id                              bigint not null references bids(id) on delete cascade,

    -- Same nullable-FK-plus-label pattern as requirement_evidence_
    -- enrichments.requirement_id/req_id (migration 017) -- req_id is the
    -- stable per-bid label used for cache-key lookups; requirement_id is
    -- populated only when the caller's requirement row actually carries a
    -- numeric id (never guessed), and set null (never the whole row
    -- deleted) if the underlying requirement is later removed.
    requirement_id                      bigint references requirements(id) on delete set null,
    req_id                              text not null,

    -- section_drafting.SECTION_DRAFTING_CONTRACT_VERSION -- the PI-3A
    -- analytical CONTRACT version (never the model name), exactly like
    -- requirement_evidence_enrichments.contract_version. Also folded into
    -- input_fingerprint itself, so bumping it always invalidates prior
    -- rows even if every other input happens to be identical.
    contract_version                    text not null,
    input_fingerprint                   text not null,

    draft_text                          text not null,
    requirements_addressed              jsonb not null default '[]'::jsonb,
    requirements_missing                jsonb not null default '[]'::jsonb,
    evaluation_criteria_addressed       jsonb not null default '[]'::jsonb,
    evidence_items_used                 jsonb not null default '[]'::jsonb,
    unsupported_or_unresolved_points    jsonb not null default '[]'::jsonb,
    contradictions_or_caveats           jsonb not null default '[]'::jsonb,
    human_confirmation_required         boolean not null default true,
    drafting_notes                      text,
    word_count                          integer,

    -- Persisted alongside the draft so a caller can see known quality
    -- issues without recomputing section_drafting.assure_section_draft()
    -- -- a draft is still persisted even when assurance_passed is false
    -- (an advisory quality flag is not the same as a failed/invalid
    -- draft -- see "Failure safety" in tenancy.get_or_generate_section_
    -- draft's own docstring for the distinction this migration relies on).
    assurance_passed                    boolean not null,
    assurance_issues                    jsonb not null default '[]'::jsonb,

    created_by_user_id                  uuid references auth.users(id),
    created_at                          timestamptz not null default now(),

    -- The canonical cache key: a fresh, reusable row for this exact
    -- (bid, requirement, input state).
    unique (bid_id, req_id, input_fingerprint)
);

create index if not exists idx_section_drafts_bid_req
    on section_drafts (bid_id, req_id, created_at desc);

alter table section_drafts enable row level security;

create policy section_drafts_select_bid_access
    on public.section_drafts for select to authenticated
    using (public.can_access_bid(bid_id));

-- Deliberately no INSERT/UPDATE/DELETE policy for authenticated/anon -- see
-- "RLS: identical posture to migrations 015/017" above. Only service_role,
-- in practice only through get_or_create_section_draft() below, may write.

-- ═══════════════════════════════════════════════════════════════════════════
-- get_or_create_section_draft -- concurrency-safe, idempotent persistence
-- of one PI-3B section-draft row
-- ═══════════════════════════════════════════════════════════════════════════
-- service_role only (mirrors migrations 015/017's write-boundary pattern).
-- Table name is fixed in the function body; only DATA is parameterized.
-- Does not touch organizational_memory_items, proposal_intelligence_*,
-- requirement_evidence_enrichments, or requirements -- purely additive
-- persistence of an already-computed result.
create or replace function public.get_or_create_section_draft(
    p_bid_id bigint,
    p_req_id text,
    p_input_fingerprint text,
    p_contract_version text,
    p_draft_text text,
    p_assurance_passed boolean,
    p_requirement_id bigint default null,
    p_requirements_addressed jsonb default '[]'::jsonb,
    p_requirements_missing jsonb default '[]'::jsonb,
    p_evaluation_criteria_addressed jsonb default '[]'::jsonb,
    p_evidence_items_used jsonb default '[]'::jsonb,
    p_unsupported_or_unresolved_points jsonb default '[]'::jsonb,
    p_contradictions_or_caveats jsonb default '[]'::jsonb,
    p_human_confirmation_required boolean default true,
    p_drafting_notes text default null,
    p_word_count integer default null,
    p_assurance_issues jsonb default '[]'::jsonb,
    p_created_by_user_id uuid default null
) returns public.section_drafts
language plpgsql
security definer
set search_path = public
as $$
declare
    v_row public.section_drafts;
begin
    if p_bid_id is null or p_req_id is null or p_input_fingerprint is null then
        raise exception 'get_or_create_section_draft: bid_id, req_id, and input_fingerprint are required';
    end if;
    if p_contract_version is null then
        raise exception 'get_or_create_section_draft: contract_version is required';
    end if;
    if p_draft_text is null or length(trim(p_draft_text)) = 0 then
        raise exception 'get_or_create_section_draft: draft_text must be non-empty -- a failed/empty draft must never be persisted';
    end if;
    if p_assurance_passed is null then
        raise exception 'get_or_create_section_draft: assurance_passed is required';
    end if;

    -- Concurrency-safe get-or-create, mirroring migration 017's
    -- get_or_create_requirement_evidence_enrichment() exactly.
    perform pg_advisory_xact_lock(hashtext('section_draft:' || p_bid_id::text || ':' || p_req_id));

    select * into v_row
    from public.section_drafts
    where bid_id = p_bid_id and req_id = p_req_id and input_fingerprint = p_input_fingerprint;

    if found then
        return v_row;
    end if;

    insert into public.section_drafts (
        bid_id, requirement_id, req_id, contract_version, input_fingerprint,
        draft_text, requirements_addressed, requirements_missing,
        evaluation_criteria_addressed, evidence_items_used,
        unsupported_or_unresolved_points, contradictions_or_caveats,
        human_confirmation_required, drafting_notes, word_count,
        assurance_passed, assurance_issues, created_by_user_id
    ) values (
        p_bid_id, p_requirement_id, p_req_id, p_contract_version, p_input_fingerprint,
        p_draft_text, coalesce(p_requirements_addressed, '[]'::jsonb),
        coalesce(p_requirements_missing, '[]'::jsonb),
        coalesce(p_evaluation_criteria_addressed, '[]'::jsonb),
        coalesce(p_evidence_items_used, '[]'::jsonb),
        coalesce(p_unsupported_or_unresolved_points, '[]'::jsonb),
        coalesce(p_contradictions_or_caveats, '[]'::jsonb),
        coalesce(p_human_confirmation_required, true), p_drafting_notes, p_word_count,
        p_assurance_passed, coalesce(p_assurance_issues, '[]'::jsonb), p_created_by_user_id
    ) returning * into v_row;

    return v_row;
end;
$$;

revoke all on function public.get_or_create_section_draft(
    bigint, text, text, text, text, boolean, bigint, jsonb, jsonb, jsonb, jsonb,
    jsonb, jsonb, boolean, text, integer, jsonb, uuid
) from public;
revoke all on function public.get_or_create_section_draft(
    bigint, text, text, text, text, boolean, bigint, jsonb, jsonb, jsonb, jsonb,
    jsonb, jsonb, boolean, text, integer, jsonb, uuid
) from anon, authenticated;
grant execute on function public.get_or_create_section_draft(
    bigint, text, text, text, text, boolean, bigint, jsonb, jsonb, jsonb, jsonb,
    jsonb, jsonb, boolean, text, integer, jsonb, uuid
) to service_role;
