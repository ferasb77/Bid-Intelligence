-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 016: Organizational Memory — OM-1 foundation
-- ═══════════════════════════════════════════════════════════════════════════
-- Additive only. Does not modify migrations 001-015, does not touch any
-- bid/requirements/proposal_intelligence table or column, does not
-- backfill, does not change any existing policy or GRANT.
--
-- Per this repo's established convention (migrations 004-015), this file
-- is NOT auto-applied by any code path and is NOT executed as part of
-- this authorization. Apply it manually via the Supabase SQL editor /
-- dashboard, after separate review, exactly the way migrations 004-015
-- were applied. Migration 013 (Section Analyzer) remains unapplied and is
-- not a dependency of this one.
--
-- ── Why this table exists ─────────────────────────────────────────────────
-- `content_library` (migration 001) is bid-scoped: it carries a single
-- nullable `bid_id` FK, its own RLS policy (migration 008) requires
-- `bid_id is not null and can_access_bid(bid_id)` for every operation, and
-- it has no organization_id column at all. It cannot represent knowledge
-- that must be visible across every bid an organization ever works on
-- (a capability statement, a resume, a past case study) without either
-- fabricating a bid_id or bypassing RLS. Organizational Memory is
-- explicitly NOT bid-scoped (this phase's own authorization) so a fresh,
-- organization-scoped table is used instead of forcing content_library's
-- existing bid-scoped semantics to mean something they do not.
--
-- `organizational_memory_items` holds exactly three, structurally
-- distinct memory classes (never conflatable, enforced by the CHECK
-- constraints below, not merely a docstring):
--
--   SOURCE_MEMORY          — raw attributable organizational source
--                             material (a case study, a capability
--                             statement, a resume) with immutable
--                             provenance. NOT itself canonical firm truth
--                             — it may only SUPPORT a claim.
--   APPROVED_FIRM_KNOWLEDGE — human-approved reusable organizational
--                             fact/evidence. Requires approved_by_user_id
--                             AND approved_at to be set (see the
--                             approval-coupling CHECK constraint below) —
--                             no code path can insert this class without
--                             supplying both, and no automated process in
--                             this codebase ever does so (no trigger,
--                             rule, or default populates them).
--   PROPOSAL_MEMORY         — reusable prior-proposal language/patterns.
--                             A proposal is marketing/persuasive content,
--                             not verified fact: PROPOSAL_MEMORY rows are
--                             structurally forbidden from ever carrying
--                             approval fields (the same CHECK constraint
--                             forces approved_by_user_id/approved_at to
--                             both be NULL for this class), so a
--                             PROPOSAL_MEMORY row can never read as, or be
--                             silently reinterpreted as, APPROVED_FIRM_
--                             KNOWLEDGE. There is no UPDATE path in this
--                             phase that changes memory_class at all (see
--                             the immutability trigger below) — promoting
--                             PROPOSAL_MEMORY into firm knowledge, if ever
--                             built, is deferred to a later OM phase and
--                             would require an explicit new human-approval
--                             write path, never an automatic rule.
--
-- ── Provenance (reuses the ProposalSourceRef / evidence.py discipline) ────
-- source_file_id/source_content_hash/source_filename/source_locator are
-- populated ONLY from values the application already deterministically
-- knows (file identity, content hash, extracted locator) — exactly the
-- same "never fabricate a coordinate the metadata doesn't carry" rule
-- analyst._build_proposal_source_ref already established for Proposal
-- Intelligence, and the same exact-identity discipline evidence.py's
-- EvidenceArtifact/EvidenceExtract enforce via content_sha256. content_hash
-- is the sha256 of this item's own `content` column, computed by the
-- application the same way (never guessed, never defaulted by the
-- database).
--
-- ── Immutable provenance ──────────────────────────────────────────────────
-- organizational_memory_items_guard_immutable_provenance() (trigger below)
-- rejects any UPDATE that changes organization_id, memory_class, content,
-- content_hash, source_file_id, source_content_hash, source_filename,
-- source_package_path, source_locator, source_bid_id, or created_by_user_id
-- after creation. Only approval fields (approved_by_user_id/approved_at)
-- and non-evidentiary metadata (embedding/metadata/title) may change post-
-- insert — matching the instruction that a memory item's provenance can
-- never be silently altered after creation.
--
-- ── Organization scoping / RLS ─────────────────────────────────────────────
-- Reuses `is_organization_member(uuid)` (migration 008) directly, the same
-- function firm_profiles' organization-scoped policies already use — no
-- new membership-check function is introduced. RLS is enabled with an
-- authenticated SELECT policy (transitive organization membership) but
-- deliberately NO authenticated INSERT/UPDATE/DELETE policy — the same
-- "RLS enabled + no write policy" fail-closed pattern PI-1 (migration 015)
-- established: only service_role (bypasses RLS by Postgres's own
-- definition) may write, and in practice only through the RPC function
-- below, called from tenancy.py's organization-boundary-checked wrappers.
-- This is RLS as the actual enforcement mechanism, not the absence of a
-- table GRANT — identical reasoning to migration 015's note on the same
-- topic.
-- ═══════════════════════════════════════════════════════════════════════════

create table if not exists organizational_memory_items (
    id                      bigserial primary key,
    organization_id         uuid not null references public.organizations(id) on delete cascade,

    memory_class            text not null
                             check (memory_class in
                                 ('SOURCE_MEMORY', 'APPROVED_FIRM_KNOWLEDGE', 'PROPOSAL_MEMORY')),

    title                   text not null,
    content                 text not null,
    content_hash            text not null,

    -- Provenance — populated only from values genuinely known; any field
    -- may be NULL when the originating source truly does not carry it,
    -- but NEVER a fabricated placeholder.
    source_file_id          text,
    source_content_hash     text,
    source_filename         text,
    source_package_path     text,
    source_locator          text,
    -- Provenance-only link to the bid a PROPOSAL_MEMORY item originated
    -- from (or, for SOURCE_MEMORY, an originating bid if applicable) —
    -- this is identity/provenance, NOT a scoping column: retrieval and
    -- RLS are governed entirely by organization_id, never by this field,
    -- so Organizational Memory items remain visible across every bid.
    source_bid_id           bigint references public.bids(id) on delete set null,

    -- Approval / trust gate. Populated together or not at all (see CHECK
    -- constraint below) — this is the ONLY thing that makes a row
    -- APPROVED_FIRM_KNOWLEDGE-eligible; no default, no trigger, no
    -- automated process ever sets these.
    approved_by_user_id     uuid references auth.users(id),
    approved_at             timestamptz,

    -- Optional link from an APPROVED_FIRM_KNOWLEDGE row back to the
    -- SOURCE_MEMORY item a human reviewed to approve it. Same-organization
    -- only, enforced by the composite FK below (never a bare same-table
    -- id FK that could point at another organization's row).
    derived_from_item_id    bigint,

    embedding                text,   -- JSON array string (matches embeddings.py's existing content_library convention; no pgvector dependency)
    metadata                 jsonb,

    created_by_user_id      uuid references auth.users(id),
    created_at              timestamptz not null default now(),

    -- Lets derived_from_item_id enforce "same organization" via a
    -- composite FK, mirroring migration 015's composite cross-tenant
    -- protection pattern.
    unique (id, organization_id),
    foreign key (derived_from_item_id, organization_id)
        references organizational_memory_items (id, organization_id) on delete set null,

    -- Approval-coupling: APPROVED_FIRM_KNOWLEDGE requires BOTH approval
    -- fields; every other class requires BOTH to be NULL. This is the
    -- structural enforcement of "never auto-promoted" and "PROPOSAL_MEMORY
    -- can never be mistaken for approved truth" — not a docstring promise.
    constraint organizational_memory_items_approval_coupling check (
        (memory_class = 'APPROVED_FIRM_KNOWLEDGE'
            and approved_by_user_id is not null and approved_at is not null)
        or
        (memory_class <> 'APPROVED_FIRM_KNOWLEDGE'
            and approved_by_user_id is null and approved_at is null)
    )
);

create index if not exists idx_organizational_memory_items_org
    on organizational_memory_items (organization_id, memory_class, created_at desc);
create index if not exists idx_organizational_memory_items_source_bid
    on organizational_memory_items (source_bid_id) where source_bid_id is not null;
create index if not exists idx_organizational_memory_items_derived_from
    on organizational_memory_items (derived_from_item_id) where derived_from_item_id is not null;

alter table organizational_memory_items enable row level security;

create policy organizational_memory_items_select_org_member
    on public.organizational_memory_items for select to authenticated
    using (public.is_organization_member(organization_id));

-- Deliberately no INSERT/UPDATE/DELETE policy for authenticated/anon --
-- see "Organization scoping / RLS" above. Only service_role, in practice
-- only through create_organizational_memory_item() below, may write.

-- ═══════════════════════════════════════════════════════════════════════════
-- Immutable-provenance trigger
-- ═══════════════════════════════════════════════════════════════════════════
create or replace function public.organizational_memory_items_guard_immutable_provenance()
returns trigger
language plpgsql
as $$
begin
    if new.organization_id      is distinct from old.organization_id
        or new.memory_class     is distinct from old.memory_class
        or new.content          is distinct from old.content
        or new.content_hash     is distinct from old.content_hash
        or new.source_file_id   is distinct from old.source_file_id
        or new.source_content_hash is distinct from old.source_content_hash
        or new.source_filename  is distinct from old.source_filename
        or new.source_package_path is distinct from old.source_package_path
        or new.source_locator   is distinct from old.source_locator
        or new.source_bid_id    is distinct from old.source_bid_id
        or new.created_by_user_id is distinct from old.created_by_user_id
        or new.created_at       is distinct from old.created_at
    then
        raise exception 'organizational_memory_items: provenance and identity fields are immutable after creation';
    end if;
    return new;
end;
$$;

drop trigger if exists trg_organizational_memory_items_immutable_provenance on public.organizational_memory_items;
create trigger trg_organizational_memory_items_immutable_provenance
    before update on public.organizational_memory_items
    for each row execute function public.organizational_memory_items_guard_immutable_provenance();

-- ═══════════════════════════════════════════════════════════════════════════
-- create_organizational_memory_item — the ONLY supported write path
-- ═══════════════════════════════════════════════════════════════════════════
-- service_role only (mirrors migration 015's write-boundary pattern).
-- Table name is fixed in the function body; only DATA is parameterized.
-- Does not touch any bid/requirements/proposal_intelligence table.
create or replace function public.create_organizational_memory_item(
    p_item jsonb
) returns public.organizational_memory_items
language plpgsql
security definer
set search_path = public
as $$
declare
    v_row public.organizational_memory_items;
begin
    if p_item->>'organization_id' is null then
        raise exception 'create_organizational_memory_item: organization_id is required';
    end if;
    if p_item->>'memory_class' is null then
        raise exception 'create_organizational_memory_item: memory_class is required';
    end if;
    if p_item->>'content' is null or p_item->>'content_hash' is null then
        raise exception 'create_organizational_memory_item: content and content_hash are required';
    end if;

    insert into public.organizational_memory_items (
        organization_id, memory_class, title, content, content_hash,
        source_file_id, source_content_hash, source_filename,
        source_package_path, source_locator, source_bid_id,
        approved_by_user_id, approved_at, derived_from_item_id,
        embedding, metadata, created_by_user_id
    ) values (
        (p_item->>'organization_id')::uuid, p_item->>'memory_class',
        p_item->>'title', p_item->>'content', p_item->>'content_hash',
        p_item->>'source_file_id', p_item->>'source_content_hash', p_item->>'source_filename',
        p_item->>'source_package_path', p_item->>'source_locator',
        (p_item->>'source_bid_id')::bigint,
        (p_item->>'approved_by_user_id')::uuid, (p_item->>'approved_at')::timestamptz,
        (p_item->>'derived_from_item_id')::bigint,
        p_item->>'embedding', p_item->'metadata', (p_item->>'created_by_user_id')::uuid
    ) returning * into v_row;

    return v_row;
end;
$$;

revoke all on function public.create_organizational_memory_item(jsonb) from public;
revoke all on function public.create_organizational_memory_item(jsonb) from anon, authenticated;
grant execute on function public.create_organizational_memory_item(jsonb) to service_role;
