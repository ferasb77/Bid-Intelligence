-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 017: Requirement Evidence Enrichment — OM-3B durable persistence
-- ═══════════════════════════════════════════════════════════════════════════
-- Additive only. Does not modify migrations 001-016, does not touch any
-- bid/requirements/proposal_intelligence/organizational_memory table or
-- column, does not backfill, does not change any existing policy or GRANT.
--
-- Per this repo's established convention (migrations 004-016), this file is
-- NOT auto-applied by any code path and is NOT executed as part of this
-- authorization. Apply it manually via the Supabase SQL editor / dashboard,
-- after separate review, exactly the way migrations 004-016 were applied.
-- Migration 013 (Section Analyzer) remains unapplied and is not a
-- dependency of this one.
--
-- ── Why this table exists (why NOT an existing table) ──────────────────────
-- OM-3A (evidence_strengthening.py, PR "OM-3: add requirement evidence
-- strengthening") computes a structured `EvidenceEnrichmentResult` for one
-- requirement but returns it ephemerally -- every call recomputes retrieval
-- AND the adjudication model call from scratch, even for byte-identical
-- inputs. OM-3B's job is durable reuse: "reason once, persist structured
-- intelligence, reuse downstream."
--
-- Three existing tables were considered and rejected before adding a new
-- one, per this phase's own "prefer reuse, do not automatically create a
-- new table" instruction:
--
--   proposal_requirement_assessments (migration 015) -- rejected because an
--     enrichment must be computable and persistable even when NO Proposal
--     Intelligence run exists yet at all (evidence_strengthening.
--     RequirementEvidenceState with assessment_status=None is exactly the
--     MISSING gap case OM-3B most needs to cache) -- there is structurally
--     no parent assessment ROW to attach a column to in that case. This
--     table's rows are also, by migration 015's own design, immutable
--     outputs of one specific Proposal Alignment run (create_proposal_
--     intelligence_bundle only ever INSERTs, there is no UPDATE path
--     anywhere in this schema) -- adding a mutable/independently-
--     recomputable enrichment column here would be a new kind of write
--     entirely, not an additive column on an existing write pattern.
--   proposal_intelligence_findings (migration 015) -- rejected for the same
--     "tied to one run" reason, plus this table's finding_type CHECK
--     constraint has no vocabulary for "OM candidate + relationship +
--     provenance + approval lineage" without either overloading `payload`
--     with an entirely different domain's shape (mixing PI's own findings
--     with OM enrichment under one finding_type taxonomy) or altering the
--     CHECK constraint anyway -- either path fabricates meaning this
--     table's rows were never designed to carry.
--   organizational_memory_items (migration 016) -- rejected outright: an
--     enrichment references MULTIPLE memory items and is itself a NEW,
--     bid-scoped derived artifact, not a single organization-scoped memory
--     item, and migration 016's own immutable-provenance trigger exists
--     specifically so this table is NEVER used to store anything other
--     than an actual memory item -- writing an enrichment row into it would
--     be exactly the kind of "convert advisory AI reasoning into stated
--     fact" this repo's standing rules forbid.
--
-- `requirement_evidence_enrichments` is therefore a new, narrow, additive
-- table, bid-scoped (mirrors Proposal Intelligence's own bid_id-direct
-- convention, migration 015's note: "All four tables key off bid_id
-- directly (not organization_id)" -- RLS is inherited transitively through
-- can_access_bid, identical reasoning here), storing ONLY the structured
-- OUTPUT of evidence_strengthening.strengthen_requirement_evidence() --
-- never a copy of a whole source document or raw memory-item chunk content
-- (evidence_strengthening.MemoryEvidenceCandidate never carries the memory
-- item's own `content` field at all, by construction -- see that module).
--
-- ── Freshness / invalidation (instruction 3) ────────────────────────────────
-- A single deterministic `input_fingerprint` (sha256, the SAME
-- canonicalization convention as proposal_intelligence.compute_package_
-- digest -- sorted-key JSON, sha256 hex) computed by evidence_strengthening.
-- compute_input_fingerprint() over exactly what OM-3A's adjudication prompt
-- itself is built from: the requirement's own req_id/description/category,
-- the current RequirementEvidenceState (assessment_status/evidence_strength/
-- has_contradiction_finding -- i.e. bid-specific evidence, hierarchy tier 2),
-- the full considered Organizational Memory candidate pool's identity
-- (item_id + item_content_hash, sorted, never the pool's raw content), and
-- EVIDENCE_STRENGTHENING_CONTRACT_VERSION (bumped whenever the adjudication
-- prompt/logic itself changes, exactly like proposal_intelligence.
-- PROPOSAL_INTELLIGENCE_ANALYSIS_VERSION already does for Proposal
-- Intelligence). A `(bid_id, req_id, input_fingerprint)` row is the
-- canonical cache key -- deliberately a single fingerprint rather than a
-- broader dependency graph, per instruction 3's own "avoid designing a
-- broad dependency graph if a simpler deterministic input fingerprint is
-- sufficient." Any change to the requirement text, its current-bid evidence
-- state, or the relevant Organizational Memory pool changes the fingerprint
-- and therefore never reuses a stale row; unrelated Organizational Memory
-- items outside the candidate pool never affect it.
--
-- ── Reuse / concurrency (instruction 4) ─────────────────────────────────────
-- get_or_create_requirement_evidence_enrichment() below mirrors migration
-- 015's get_or_create_proposal_package_snapshot() exactly: a transaction-
-- scoped advisory lock keyed on (bid_id, req_id) serializes two callers
-- racing to persist the SAME fingerprint for the SAME requirement: the
-- loser of the race receives the winner's already-persisted row back
-- rather than creating a duplicate. The (bid_id, req_id, input_fingerprint)
-- UNIQUE constraint remains the final authority even if this function were
-- bypassed. The actual freshness CHECK (does a fresh row already exist for
-- the currently-computed fingerprint, so the expensive retrieval+
-- adjudication call can be skipped entirely) happens one layer up, in
-- tenancy.strengthen_requirement_evidence_for_organization, via a plain
-- SELECT read -- exactly the same layering Proposal Intelligence already
-- uses (the analysis itself is orchestrated in Python; only identity/dedup
-- persistence goes through a dedicated SQL function).
--
-- ── RLS: identical posture to migration 015 ─────────────────────────────────
-- Authenticated SELECT only (transitive `can_access_bid`), NO authenticated
-- INSERT/UPDATE/DELETE policy at all -- only service_role (bypasses RLS by
-- Postgres's own definition), in practice only through the RPC below, may
-- write. This is RLS as the actual enforcement mechanism (RLS enabled +
-- absence of a write policy), not table GRANTs -- identical reasoning to
-- migration 015's and migration 016's own notes on the same topic.
-- ═══════════════════════════════════════════════════════════════════════════

create table if not exists requirement_evidence_enrichments (
    id                              bigserial primary key,
    bid_id                          bigint not null references bids(id) on delete cascade,

    -- Same nullable-FK-plus-label pattern as proposal_requirement_
    -- assessments.requirement_id/req_id (migration 015) -- req_id is the
    -- stable per-bid label used for cache-key lookups; requirement_id is
    -- populated only when the caller's requirement row actually carries a
    -- numeric id (never guessed), and set null (never the whole row
    -- deleted) if the underlying requirement is later removed.
    requirement_id                  bigint references requirements(id) on delete set null,
    req_id                          text not null,

    -- evidence_strengthening.EVIDENCE_STRENGTHENING_CONTRACT_VERSION --
    -- the OM-3 analytical CONTRACT version (never the model name), exactly
    -- like proposal_intelligence_runs.analysis_version. Also folded into
    -- input_fingerprint itself, so bumping it always invalidates prior rows
    -- even if every other input happens to be identical.
    contract_version                text not null,
    input_fingerprint               text not null,

    evidence_state_before           jsonb not null,
    organizational_evidence         jsonb not null default '[]'::jsonb,
    evidence_state_after            jsonb not null,
    remaining_gaps                  jsonb not null default '[]'::jsonb,
    requires_human_confirmation     boolean not null default false,
    retrieval_skipped_reason        text,

    created_by_user_id              uuid references auth.users(id),
    created_at                      timestamptz not null default now(),

    -- The canonical cache key: a fresh, reusable row for this exact
    -- (bid, requirement, input state).
    unique (bid_id, req_id, input_fingerprint)
);

create index if not exists idx_requirement_evidence_enrichments_bid_req
    on requirement_evidence_enrichments (bid_id, req_id, created_at desc);

alter table requirement_evidence_enrichments enable row level security;

create policy requirement_evidence_enrichments_select_bid_access
    on public.requirement_evidence_enrichments for select to authenticated
    using (public.can_access_bid(bid_id));

-- Deliberately no INSERT/UPDATE/DELETE policy for authenticated/anon -- see
-- "RLS: identical posture to migration 015" above. Only service_role, in
-- practice only through get_or_create_requirement_evidence_enrichment()
-- below, may write.

-- ═══════════════════════════════════════════════════════════════════════════
-- get_or_create_requirement_evidence_enrichment -- concurrency-safe,
-- idempotent persistence of one OM-3B enrichment row
-- ═══════════════════════════════════════════════════════════════════════════
-- service_role only (mirrors migration 015's write-boundary pattern).
-- Table name is fixed in the function body; only DATA is parameterized.
-- Does not touch organizational_memory_items, proposal_intelligence_*, or
-- requirements -- purely additive persistence of an already-computed
-- result.
create or replace function public.get_or_create_requirement_evidence_enrichment(
    p_bid_id bigint,
    p_req_id text,
    p_input_fingerprint text,
    p_contract_version text,
    p_evidence_state_before jsonb,
    p_evidence_state_after jsonb,
    p_requirement_id bigint default null,
    p_organizational_evidence jsonb default '[]'::jsonb,
    p_remaining_gaps jsonb default '[]'::jsonb,
    p_requires_human_confirmation boolean default false,
    p_retrieval_skipped_reason text default null,
    p_created_by_user_id uuid default null
) returns public.requirement_evidence_enrichments
language plpgsql
security definer
set search_path = public
as $$
declare
    v_row public.requirement_evidence_enrichments;
begin
    if p_bid_id is null or p_req_id is null or p_input_fingerprint is null then
        raise exception 'get_or_create_requirement_evidence_enrichment: bid_id, req_id, and input_fingerprint are required';
    end if;
    if p_contract_version is null then
        raise exception 'get_or_create_requirement_evidence_enrichment: contract_version is required';
    end if;
    if p_evidence_state_before is null or p_evidence_state_after is null then
        raise exception 'get_or_create_requirement_evidence_enrichment: evidence_state_before and evidence_state_after are required';
    end if;

    -- Concurrency-safe get-or-create, mirroring migration 015's
    -- get_or_create_proposal_package_snapshot() exactly.
    perform pg_advisory_xact_lock(hashtext('requirement_evidence_enrichment:' || p_bid_id::text || ':' || p_req_id));

    select * into v_row
    from public.requirement_evidence_enrichments
    where bid_id = p_bid_id and req_id = p_req_id and input_fingerprint = p_input_fingerprint;

    if found then
        return v_row;
    end if;

    insert into public.requirement_evidence_enrichments (
        bid_id, requirement_id, req_id, contract_version, input_fingerprint,
        evidence_state_before, organizational_evidence, evidence_state_after,
        remaining_gaps, requires_human_confirmation, retrieval_skipped_reason,
        created_by_user_id
    ) values (
        p_bid_id, p_requirement_id, p_req_id, p_contract_version, p_input_fingerprint,
        p_evidence_state_before, coalesce(p_organizational_evidence, '[]'::jsonb),
        p_evidence_state_after, coalesce(p_remaining_gaps, '[]'::jsonb),
        coalesce(p_requires_human_confirmation, false), p_retrieval_skipped_reason,
        p_created_by_user_id
    ) returning * into v_row;

    return v_row;
end;
$$;

revoke all on function public.get_or_create_requirement_evidence_enrichment(
    bigint, text, text, text, jsonb, jsonb, bigint, jsonb, jsonb, boolean, text, uuid
) from public;
revoke all on function public.get_or_create_requirement_evidence_enrichment(
    bigint, text, text, text, jsonb, jsonb, bigint, jsonb, jsonb, boolean, text, uuid
) from anon, authenticated;
grant execute on function public.get_or_create_requirement_evidence_enrichment(
    bigint, text, text, text, jsonb, jsonb, bigint, jsonb, jsonb, boolean, text, uuid
) to service_role;
