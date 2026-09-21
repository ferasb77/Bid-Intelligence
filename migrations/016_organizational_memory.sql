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
-- OM-2 update (source ingestion + human approval lifecycle): this file
-- was edited IN PLACE (not a new migration 017) to add
-- `organizational_source_documents` (durable parent-file identity for
-- chunked uploads), `organizational_memory_items.source_document_id`
-- (chunk -> parent-file lineage), and `approve_organizational_memory_item()`
-- (the sole RPC allowed to create an APPROVED_FIRM_KNOWLEDGE row). See the
-- OM-2 section near the end of this file for full reasoning. Migration 016
-- remains entirely unapplied to any live database as of this edit.
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
-- ── Immutable provenance and trust/lineage history ─────────────────────────
-- organizational_memory_items_guard_immutable_provenance() (trigger below)
-- rejects any UPDATE that changes organization_id, memory_class, content,
-- content_hash, source_file_id, source_content_hash, source_filename,
-- source_package_path, source_locator, source_bid_id, or created_by_user_id
-- after creation. It ALSO rejects any UPDATE that changes
-- approved_by_user_id, approved_at, or derived_from_item_id once set --
-- these are trust-history fields, not ordinary mutable metadata: once an
-- item is approved with a given approver/timestamp/lineage, that history
-- must be exactly as immutable as the item's source identity, never
-- silently re-approved, re-timestamped, or re-derived. Only non-evidentiary
-- metadata (embedding/metadata/title) may change post-insert — matching
-- the instruction that a memory item's provenance and trust history can
-- never be silently altered after creation.
--
-- ── Write-boundary hardening (commissioning-review pass) ──────────────────
-- Four invariants enforced STRUCTURALLY, not merely by the Python dataclass
-- (organizational_memory.py's __post_init__), so a direct/buggy/future
-- insert that bypasses the dataclass is still rejected by Postgres itself:
--   1. organizational_memory_items_exact_source_identity (CHECK) —
--      SOURCE_MEMORY/PROPOSAL_MEMORY must carry source_file_id or
--      source_content_hash.
--   2. organizational_memory_items_approved_requires_lineage (CHECK) +
--      trg_organizational_memory_items_guard_derived_lineage (trigger) —
--      APPROVED_FIRM_KNOWLEDGE requires derived_from_item_id, the composite
--      FK forces it to be same-organization, and the trigger forces the
--      referenced row's own memory_class to be SOURCE_MEMORY.
--   3. create_organizational_memory_item() (RPC, below) rejects
--      memory_class = 'APPROVED_FIRM_KNOWLEDGE' outright — approved-
--      knowledge creation is reserved for a separate, explicit human-
--      approval write path this migration does not build. tenancy.py's
--      create_organizational_memory_item_for_organization() enforces the
--      same rejection at the application layer as defense-in-depth.
--   4. trg_organizational_memory_items_guard_source_bid_org (trigger) —
--      source_bid_id, when present, must belong to a bid in the SAME
--      organization_id as the memory item.
--
-- Reconciliation pass (second commissioning review): the Python dataclass
-- (organizational_memory.py's __post_init__) now enforces the same
-- lineage-required-for-APPROVED_FIRM_KNOWLEDGE rule as invariant 2 above,
-- so a bad item is rejected at construction time, not merely at the DB
-- boundary; the immutable-provenance trigger now also covers
-- approved_by_user_id/approved_at/derived_from_item_id (trust-history
-- fields, immutable exactly like source identity); and source_bid_id /
-- derived_from_item_id both changed from ON DELETE SET NULL to ON DELETE
-- RESTRICT so a referenced bid or SOURCE_MEMORY item can never be deleted
-- out from under a memory item that still depends on it for provenance.
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
    -- ON DELETE RESTRICT (not SET NULL): this column is provenance, and
    -- provenance must never be silently lost — deleting a bid that a
    -- memory item still depends on for provenance is blocked, not allowed
    -- to quietly null out that memory item's evidentiary trail.
    source_bid_id           bigint references public.bids(id) on delete restrict,

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
    -- ON DELETE RESTRICT (not SET NULL): derived_from_item_id is lineage,
    -- not ordinary metadata — deleting a SOURCE_MEMORY item that an
    -- APPROVED_FIRM_KNOWLEDGE item still depends on for its lineage is
    -- blocked, not allowed to silently sever that item's traceable origin.
    foreign key (derived_from_item_id, organization_id)
        references organizational_memory_items (id, organization_id) on delete restrict,

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
    ),

    -- Exact-source enforcement at the DB level (mirrors
    -- OrganizationalMemoryItem.__post_init__'s Python-side check, which is
    -- not sufficient on its own -- a direct/buggy/future insert that
    -- bypasses the dataclass must still be rejected here): SOURCE_MEMORY
    -- and PROPOSAL_MEMORY must carry at least one real source identity
    -- coordinate. APPROVED_FIRM_KNOWLEDGE is unconstrained by this check
    -- (its own lineage requirement is enforced separately below).
    constraint organizational_memory_items_exact_source_identity check (
        memory_class not in ('SOURCE_MEMORY', 'PROPOSAL_MEMORY')
        or source_file_id is not null
        or source_content_hash is not null
    ),

    -- APPROVED_FIRM_KNOWLEDGE must have traceable SOURCE_MEMORY lineage:
    -- derived_from_item_id is required whenever memory_class is
    -- APPROVED_FIRM_KNOWLEDGE. The composite FK above already forces same-
    -- organization; the additional constraint that the referenced item is
    -- ACTUALLY memory_class = 'SOURCE_MEMORY' cannot be expressed by a
    -- plain CHECK (it requires inspecting a different row) and is enforced
    -- by the trigger below instead.
    constraint organizational_memory_items_approved_requires_lineage check (
        memory_class <> 'APPROVED_FIRM_KNOWLEDGE' or derived_from_item_id is not null
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
        or new.approved_by_user_id is distinct from old.approved_by_user_id
        or new.approved_at      is distinct from old.approved_at
        or new.derived_from_item_id is distinct from old.derived_from_item_id
    then
        raise exception 'organizational_memory_items: provenance and trust/lineage history fields are immutable after creation';
    end if;
    return new;
end;
$$;

drop trigger if exists trg_organizational_memory_items_immutable_provenance on public.organizational_memory_items;
create trigger trg_organizational_memory_items_immutable_provenance
    before update on public.organizational_memory_items
    for each row execute function public.organizational_memory_items_guard_immutable_provenance();

-- ═══════════════════════════════════════════════════════════════════════════
-- APPROVED_FIRM_KNOWLEDGE lineage-class guard trigger
-- ═══════════════════════════════════════════════════════════════════════════
-- The composite FK on derived_from_item_id already forces same-organization
-- and referential existence. What a FK/CHECK cannot express is "the
-- referenced row's OWN memory_class column is SOURCE_MEMORY" -- that needs
-- to inspect a different row, so it is a trigger. Combined with the
-- organizational_memory_items_approved_requires_lineage CHECK above, an
-- APPROVED_FIRM_KNOWLEDGE row with no identified SOURCE_MEMORY lineage is
-- structurally impossible to insert or update into this table.
create or replace function public.organizational_memory_items_guard_derived_lineage()
returns trigger
language plpgsql
as $$
declare
    v_source_class text;
begin
    if new.derived_from_item_id is not null then
        select memory_class into v_source_class
        from public.organizational_memory_items
        where id = new.derived_from_item_id;

        if v_source_class is null then
            raise exception 'organizational_memory_items: derived_from_item_id % does not reference an existing item', new.derived_from_item_id;
        end if;

        if v_source_class <> 'SOURCE_MEMORY' then
            raise exception 'organizational_memory_items: derived_from_item_id must reference a SOURCE_MEMORY item, not %', v_source_class;
        end if;
    end if;
    return new;
end;
$$;

drop trigger if exists trg_organizational_memory_items_guard_derived_lineage on public.organizational_memory_items;
create trigger trg_organizational_memory_items_guard_derived_lineage
    before insert or update on public.organizational_memory_items
    for each row execute function public.organizational_memory_items_guard_derived_lineage();

-- ═══════════════════════════════════════════════════════════════════════════
-- source_bid_id cross-tenant integrity guard trigger
-- ═══════════════════════════════════════════════════════════════════════════
-- source_bid_id is provenance-only (never a retrieval/RLS scoping column --
-- see the column comment above), but when present it must still belong to
-- the SAME organization as the memory item itself. bids.organization_id
-- (migration 007) is a direct column, but a composite FK against it would
-- require altering the bids table, which this migration's own header
-- states it will not do -- so this is enforced with a trigger that looks
-- up the referenced bid's organization_id and rejects a mismatch.
create or replace function public.organizational_memory_items_guard_source_bid_org()
returns trigger
language plpgsql
as $$
declare
    v_bid_org uuid;
begin
    if new.source_bid_id is not null then
        select organization_id into v_bid_org
        from public.bids
        where id = new.source_bid_id;

        if v_bid_org is null then
            raise exception 'organizational_memory_items: source_bid_id % does not reference an existing bid', new.source_bid_id;
        end if;

        if v_bid_org <> new.organization_id then
            raise exception 'organizational_memory_items: source_bid_id % belongs to a different organization than this memory item', new.source_bid_id;
        end if;
    end if;
    return new;
end;
$$;

drop trigger if exists trg_organizational_memory_items_guard_source_bid_org on public.organizational_memory_items;
create trigger trg_organizational_memory_items_guard_source_bid_org
    before insert or update on public.organizational_memory_items
    for each row execute function public.organizational_memory_items_guard_source_bid_org();

-- ═══════════════════════════════════════════════════════════════════════════
-- OM-2: organizational_source_documents — durable parent-file identity
-- ═══════════════════════════════════════════════════════════════════════════
-- OM-1 built organizational_memory_items for the memory ITEMS themselves,
-- not a record of the original uploaded FILE that multiple SOURCE_MEMORY
-- chunks derive from. This table is that minimal addition: one row per
-- uploaded source file, organization-scoped, RLS-protected the same way as
-- organizational_memory_items, tracking exactly file identity/content hash/
-- filename/upload metadata -- nothing else. It does not itself carry
-- retrievable content (organizational_memory_items chunks do); it exists so
-- every SOURCE_MEMORY chunk derived from one file can point back at a
-- single durable parent record instead of only repeating the same
-- source_filename/source_content_hash on every chunk row.
--
-- Still governed by the same "migration 016 remains unapplied" note at the
-- top of this file -- this is an in-place edit to the one still-unapplied
-- migration, not a new migration file.
create table if not exists organizational_source_documents (
    id                      bigserial primary key,
    organization_id         uuid not null references public.organizations(id) on delete cascade,

    filename                text not null,
    content_hash            text not null,   -- sha256 of the raw uploaded bytes
    extracted_char_count    integer not null default 0,
    chunk_count             integer not null default 0,

    metadata                jsonb,

    uploaded_by_user_id     uuid references auth.users(id),
    uploaded_at             timestamptz not null default now(),

    -- Same duplicate-detection discipline extractor.py's package pipeline
    -- already uses for content_hash: the same file re-uploaded into the
    -- same organization is the same source document, not a new one.
    unique (organization_id, content_hash),
    -- Lets organizational_memory_items.source_document_id enforce
    -- "same organization" via a composite FK, mirroring the
    -- derived_from_item_id pattern above.
    unique (id, organization_id)
);

create index if not exists idx_organizational_source_documents_org
    on organizational_source_documents (organization_id, uploaded_at desc);

alter table organizational_source_documents enable row level security;

create policy organizational_source_documents_select_org_member
    on public.organizational_source_documents for select to authenticated
    using (public.is_organization_member(organization_id));

-- Deliberately no INSERT/UPDATE/DELETE policy for authenticated/anon --
-- identical "RLS enabled + no write policy, service_role/RPC only" pattern
-- organizational_memory_items already uses above.

-- Durable parent-file link from a SOURCE_MEMORY/PROPOSAL_MEMORY chunk back
-- to the organizational_source_documents row it was chunked from. Nullable
-- (a memory item may not originate from a chunked upload at all -- e.g. a
-- future manually-authored SOURCE_MEMORY item), never a fabricated link.
-- ON DELETE RESTRICT: the same "provenance must never be silently lost"
-- reasoning as source_bid_id/derived_from_item_id above.
alter table organizational_memory_items
    add column if not exists source_document_id bigint;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'organizational_memory_items_source_document_org_fk'
    ) then
        alter table organizational_memory_items
            add constraint organizational_memory_items_source_document_org_fk
            foreign key (source_document_id, organization_id)
            references organizational_source_documents (id, organization_id)
            on delete restrict;
    end if;
end $$;

create index if not exists idx_organizational_memory_items_source_document
    on organizational_memory_items (source_document_id) where source_document_id is not null;

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
    if p_item->>'memory_class' = 'APPROVED_FIRM_KNOWLEDGE' then
        raise exception 'create_organizational_memory_item: APPROVED_FIRM_KNOWLEDGE creation is reserved for the explicit human-approval flow, not this generic write path';
    end if;
    if p_item->>'content' is null or p_item->>'content_hash' is null then
        raise exception 'create_organizational_memory_item: content and content_hash are required';
    end if;

    insert into public.organizational_memory_items (
        organization_id, memory_class, title, content, content_hash,
        source_file_id, source_content_hash, source_filename,
        source_package_path, source_locator, source_bid_id, source_document_id,
        approved_by_user_id, approved_at, derived_from_item_id,
        embedding, metadata, created_by_user_id
    ) values (
        (p_item->>'organization_id')::uuid, p_item->>'memory_class',
        p_item->>'title', p_item->>'content', p_item->>'content_hash',
        p_item->>'source_file_id', p_item->>'source_content_hash', p_item->>'source_filename',
        p_item->>'source_package_path', p_item->>'source_locator',
        (p_item->>'source_bid_id')::bigint, (p_item->>'source_document_id')::bigint,
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


-- source_document_id joins the immutable-provenance trigger's guarded
-- column set -- it is provenance, exactly like source_file_id/source_
-- content_hash, and must never change after creation.
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
        or new.source_document_id is distinct from old.source_document_id
        or new.created_by_user_id is distinct from old.created_by_user_id
        or new.created_at       is distinct from old.created_at
        or new.approved_by_user_id is distinct from old.approved_by_user_id
        or new.approved_at      is distinct from old.approved_at
        or new.derived_from_item_id is distinct from old.derived_from_item_id
    then
        raise exception 'organizational_memory_items: provenance and trust/lineage history fields are immutable after creation';
    end if;
    return new;
end;
$$;

-- create_organizational_source_document — the ONLY supported write path
-- for the new table, mirroring create_organizational_memory_item's own
-- service_role-only RPC pattern exactly.
create or replace function public.create_organizational_source_document(
    p_doc jsonb
) returns public.organizational_source_documents
language plpgsql
security definer
set search_path = public
as $$
declare
    v_row public.organizational_source_documents;
begin
    if p_doc->>'organization_id' is null then
        raise exception 'create_organizational_source_document: organization_id is required';
    end if;
    if p_doc->>'filename' is null then
        raise exception 'create_organizational_source_document: filename is required';
    end if;
    if p_doc->>'content_hash' is null then
        raise exception 'create_organizational_source_document: content_hash is required';
    end if;

    insert into public.organizational_source_documents (
        organization_id, filename, content_hash, extracted_char_count,
        chunk_count, metadata, uploaded_by_user_id
    ) values (
        (p_doc->>'organization_id')::uuid, p_doc->>'filename', p_doc->>'content_hash',
        coalesce((p_doc->>'extracted_char_count')::integer, 0),
        coalesce((p_doc->>'chunk_count')::integer, 0),
        p_doc->'metadata', (p_doc->>'uploaded_by_user_id')::uuid
    ) returning * into v_row;

    return v_row;
end;
$$;

revoke all on function public.create_organizational_source_document(jsonb) from public;
revoke all on function public.create_organizational_source_document(jsonb) from anon, authenticated;
grant execute on function public.create_organizational_source_document(jsonb) to service_role;

-- ═══════════════════════════════════════════════════════════════════════════
-- OM-2: approve_organizational_memory_item — the ONLY write path allowed to
-- create an APPROVED_FIRM_KNOWLEDGE row
-- ═══════════════════════════════════════════════════════════════════════════
-- Separate, explicit RPC from create_organizational_memory_item(), which
-- rejects APPROVED_FIRM_KNOWLEDGE outright (see above). This function is
-- the ONLY server-side path that may insert that class. It re-derives
-- every provenance/lineage field from the PARENT row fetched inside this
-- function (never trusts a client-supplied copy of the parent), and
-- requires the caller (tenancy.py's approve_organizational_memory_item_
-- for_organization) to have already authenticated the human approver and
-- pass only p_approved_by_user_id -- approved_at is always now(), server-
-- side, never client-supplied.
create or replace function public.approve_organizational_memory_item(
    p_source_item_id bigint,
    p_organization_id uuid,
    p_approved_by_user_id uuid,
    p_fact_title text,
    p_fact_content text
) returns public.organizational_memory_items
language plpgsql
security definer
set search_path = public
as $$
declare
    v_parent public.organizational_memory_items;
    v_row public.organizational_memory_items;
    v_content text;
    v_content_hash text;
begin
    if p_source_item_id is null or p_organization_id is null or p_approved_by_user_id is null then
        raise exception 'approve_organizational_memory_item: source_item_id, organization_id, and approved_by_user_id are all required';
    end if;

    select * into v_parent
    from public.organizational_memory_items
    where id = p_source_item_id and organization_id = p_organization_id;

    if v_parent.id is null then
        raise exception 'approve_organizational_memory_item: source item % not found in organization %', p_source_item_id, p_organization_id;
    end if;
    if v_parent.memory_class <> 'SOURCE_MEMORY' then
        raise exception 'approve_organizational_memory_item: source item % is not SOURCE_MEMORY (found %)', p_source_item_id, v_parent.memory_class;
    end if;

    v_content := coalesce(nullif(p_fact_content, ''), v_parent.content);
    v_content_hash := encode(digest(v_content, 'sha256'), 'hex');

    insert into public.organizational_memory_items (
        organization_id, memory_class, title, content, content_hash,
        source_file_id, source_content_hash, source_filename,
        source_package_path, source_locator, source_bid_id, source_document_id,
        approved_by_user_id, approved_at, derived_from_item_id,
        created_by_user_id
    ) values (
        v_parent.organization_id, 'APPROVED_FIRM_KNOWLEDGE',
        coalesce(nullif(p_fact_title, ''), v_parent.title), v_content, v_content_hash,
        v_parent.source_file_id, v_parent.source_content_hash, v_parent.source_filename,
        v_parent.source_package_path, v_parent.source_locator, v_parent.source_bid_id, v_parent.source_document_id,
        p_approved_by_user_id, now(), v_parent.id,
        p_approved_by_user_id
    ) returning * into v_row;

    return v_row;
end;
$$;

revoke all on function public.approve_organizational_memory_item(bigint, uuid, uuid, text, text) from public;
revoke all on function public.approve_organizational_memory_item(bigint, uuid, uuid, text, text) from anon, authenticated;
grant execute on function public.approve_organizational_memory_item(bigint, uuid, uuid, text, text) to service_role;
