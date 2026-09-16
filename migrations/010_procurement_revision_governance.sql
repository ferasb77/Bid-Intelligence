-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 010: Procurement Revision & Addendum Governance
-- ═══════════════════════════════════════════════════════════════════════════
-- Does not touch migrations 001-009. Additive only -- no existing column is
-- dropped/renamed, no existing row is mutated beyond the explicit, narrow
-- defaults set below (every existing bid -> procurement_truth_status =
-- 'ungoverned'; every existing requirement -> lifecycle_status = 'active';
-- every existing document.content_hash stays NULL).
--
-- ── Why this migration exists ────────────────────────────────────────────
-- The CDA-AMC (Canada Drug Agency) provenance audit proved that
-- `requirements`/`bid_briefs` can silently diverge from the buyer's actual,
-- current procurement corpus: 25 requirement rows were extracted once from
-- the Main Document on 2026-07-15, before 4 buyer-issued bulletins existed,
-- and have never been revised since -- with zero structured provenance
-- (`requirements.source_refs` empty on every row) and no record that any
-- bulletin was ever considered. Separately, Fast Analysis was found to
-- silently overwrite `bid_briefs` on every run (a full, unconditional,
-- un-reviewed column overwrite), directly contradicting its own module
-- docstring's stated intent to never modify the governed pipeline's output.
--
-- This migration introduces the minimum schema needed to make procurement
-- truth an explicitly governed, revision-tracked, human-reviewed process:
-- a monotonic `bids.procurement_revision` counter, an explicit
-- `procurement_truth_status` (never silently implying revision 1 is
-- verified), an immutable `procurement_changes` history table, a
-- human-review staging/decision model, requirement lifecycle tracking
-- (never physically deleting a requirement with history), and atomic,
-- `SECURITY DEFINER` server-side RPCs that are the ONLY write path for all
-- of the above -- ordinary authenticated org members get SELECT only.
--
-- No CDA bulletin is processed by this migration. No baseline is silently
-- established for any existing bid. Every existing bid remains fully
-- functional and displays as 'ungoverned' until a human explicitly reviews
-- and approves its baseline through the new governed workflow.
-- ═══════════════════════════════════════════════════════════════════════════


-- pgcrypto provides digest()/encode() used by the document-set-digest
-- helper below. Most Supabase projects already have this enabled (it
-- backs Supabase Auth itself); this is a no-op if so.
create extension if not exists pgcrypto;


-- ═══════════════════════════════════════════════════════════════════════════
-- PART 1 — additive columns on existing tables
-- ═══════════════════════════════════════════════════════════════════════════

-- bids: the revision counter and the explicit (never-implicitly-verified)
-- governance state. Every existing bid defaults to procurement_revision=1,
-- procurement_truth_status='ungoverned' -- revision 1 is simply "the state
-- the corpus is currently in", never a claim that it has been verified.
alter table public.bids
    add column if not exists procurement_revision integer not null default 1;
alter table public.bids
    add column if not exists procurement_truth_status text not null default 'ungoverned'
        check (procurement_truth_status in ('ungoverned', 'governed'));

-- documents: content hash, nullable. New uploads compute this server-side
-- at upload time (application-layer change, not this migration); legacy
-- documents stay NULL until first used in a governed review, at which
-- point it is computed server-side (downloaded + SHA-256'd) and persisted
-- only if still NULL -- never invented, never overwritten once set.
alter table public.documents
    add column if not exists content_hash text;

-- requirements: lifecycle tracking. A requirement row is NEVER physically
-- deleted once it has immutable procurement_changes history pointing at
-- it -- SUPERSEDED/REMOVED requirements stay queryable forever, they just
-- stop participating in "current truth" reads (enforced in application
-- code via database.get_requirements()/tenancy.get_requirements_
-- authenticated()'s default lifecycle_status='active' filter, not by RLS,
-- since a retired row must remain visible to an org member -- it is only
-- excluded from CURRENT-TRUTH reads, never from access entirely).
alter table public.requirements
    add column if not exists lifecycle_status text not null default 'active'
        check (lifecycle_status in ('active', 'superseded', 'removed'));
alter table public.requirements
    add column if not exists retired_at_procurement_revision integer;

-- analysis_runs: advisory-corpus provenance (Fast Analysis becomes
-- analytical-only -- see PART 5 -- but must still truthfully describe what
-- procurement revision it ran against, and whether its corpus included any
-- buyer document that has not yet been through a governed review). Both
-- columns stay NULL-able with NO default: this migration runs after many
-- analysis_runs rows already exist, and a historical run that predates
-- procurement-revision tracking entirely must never be silently made to
-- look current/fully-governed just because a new column defaulted to a
-- concrete value. NULL here means "predates tracking / basis unknown" --
-- never "revision 1" and never "0 documents outstanding". Application
-- code (analysis_service.py) always stamps an explicit integer on every
-- NEW run; NULL is reserved for rows this migration finds already
-- existing.
alter table public.analysis_runs
    add column if not exists based_on_procurement_revision integer;
alter table public.analysis_runs
    add column if not exists unreviewed_document_count integer;

-- bid_briefs: the C-field (analytical/narrative) freshness stamp only --
-- executive_summary/contract_risks/scope_categories/deliverables_summary.
-- Deliberately NOT named based_on_procurement_revision: the A/B
-- (canonical/deterministic) columns are rebuilt atomically inside every
-- governed apply and are always current by construction, so a single
-- row-level "based on revision N" field would misleadingly describe the
-- whole row when it only ever needs to describe these four narrative
-- fields' staleness. NULL means predates procurement-revision tracking /
-- basis unknown -- same rule as analysis_runs above, never "revision 1"
-- and never "current".
alter table public.bid_briefs
    add column if not exists narrative_based_on_procurement_revision integer;

-- bid_decisions: DECIDE already consumes qualification-gate information
-- derived from canonical procurement truth (bid_no_bid_score's
-- qualification_requirements argument) -- a real, current dependency, not
-- a hypothetical one. NULL means predates tracking / basis unknown, same
-- rule as above -- a legacy decision must never be displayed as if it
-- were made against a known, current procurement revision.
alter table public.bid_decisions
    add column if not exists based_on_procurement_revision integer;


-- ═══════════════════════════════════════════════════════════════════════════
-- PART 2 — governance tables
-- ═══════════════════════════════════════════════════════════════════════════
-- Creation order matters for FK validity: procurement_conflicts has no
-- dependency on procurement_update_reviews, so it is created FIRST;
-- procurement_update_reviews.conflict_id can then reference it directly
-- at CREATE TABLE time, with no ALTER-TABLE-after-the-fact FK patch needed.

-- ── procurement_conflicts ─────────────────────────────────────────────────
-- Conflicts live ONLY here. There is deliberately no cached
-- requirements.conflict_status column (rejected in architecture review --
-- a second, independently-mutable "is there a conflict" field would itself
-- be a drift risk of exactly the kind this migration exists to eliminate).
-- Any reader needing "does requirement X have an unresolved conflict"
-- queries this table directly.
create table if not exists public.procurement_conflicts (
    id bigserial primary key,
    bid_id bigint not null references public.bids(id) on delete cascade,
    organization_id uuid not null references public.organizations(id),
    entity_type text not null check (entity_type in
        ('requirement', 'bid_brief_field', 'deliverable', 'outline_section', 'other')),
    entity_id text,
    target_requirement_id bigint references public.requirements(id),
    topic text not null,
    competing_values jsonb not null,
    status text not null default 'unresolved' check (status in ('unresolved', 'resolved')),
    resolution_value jsonb,
    resolution_reason text,
    resolved_by_user_id uuid references auth.users(id),
    resolved_at timestamptz,
    resolving_procurement_revision integer,
    created_at timestamptz not null default now()
);
create index if not exists idx_procurement_conflicts_bid_entity
    on public.procurement_conflicts (bid_id, entity_type, entity_id, status);

-- ── procurement_update_reviews ────────────────────────────────────────────
-- One first-class governed review of ONE governance event: establishing
-- the original baseline, reviewing ONE buyer-issued update (which may
-- itself span multiple physical documents -- see
-- procurement_update_review_documents below), or resolving ONE conflict.
create table if not exists public.procurement_update_reviews (
    id bigserial primary key,
    bid_id bigint not null references public.bids(id) on delete cascade,
    organization_id uuid not null references public.organizations(id),
    review_kind text not null check (review_kind in ('baseline', 'buyer_update', 'conflict_resolution')),
    buyer_update_type text check (buyer_update_type in (
        'Original RFP', 'Bulletin', 'Addendum', 'Amendment', 'Clarification/Q&A',
        'Revised Schedule', 'Revised Pricing Form', 'Revised Submission Form', 'Other')),
    conflict_id bigint references public.procurement_conflicts(id),
    buyer_issued_date date,
    status text not null default 'analyzing'
        check (status in ('analyzing', 'ready_for_review', 'reviewed', 'applied', 'failed')),
    base_procurement_revision integer not null,
    resulting_procurement_revision integer,
    no_canonical_change boolean not null default false,
    document_set_digest text not null,
    analyzed_at timestamptz,
    reviewed_by_user_id uuid references auth.users(id),
    reviewed_at timestamptz,
    applied_by_user_id uuid references auth.users(id),
    applied_at timestamptz,
    review_note text,
    idempotency_key text,
    created_at timestamptz not null default now(),
    constraint review_kind_field_consistency check (
        (review_kind in ('baseline', 'buyer_update') and buyer_update_type is not null and conflict_id is null)
        or (review_kind = 'conflict_resolution' and conflict_id is not null and buyer_update_type is null)
    )
);
create unique index if not exists idx_procurement_update_reviews_dedup
    on public.procurement_update_reviews (bid_id, document_set_digest, base_procurement_revision)
    where status != 'failed';
create unique index if not exists idx_procurement_update_reviews_idempotency
    on public.procurement_update_reviews (idempotency_key)
    where idempotency_key is not null;
create index if not exists idx_procurement_update_reviews_bid
    on public.procurement_update_reviews (bid_id, status);

-- ── procurement_update_review_documents ───────────────────────────────────
-- Review-to-document membership. A governed review may legitimately span
-- more than one physical file (an RFP + separate pricing workbook, an
-- amendment letter + replacement pricing form, etc.) -- exactly one
-- 'primary' document per review is enforced by the partial unique index
-- below PLUS explicit "at least one, exactly one primary" validation
-- inside create_procurement_update_review() (the index alone only proves
-- "at most one primary", never "at least one document" or "exactly one
-- primary" -- both are enforced in the RPC, see PART 3).
create table if not exists public.procurement_update_review_documents (
    review_id bigint not null references public.procurement_update_reviews(id) on delete cascade,
    document_id bigint not null references public.documents(id),
    organization_id uuid not null references public.organizations(id),
    document_hash text,
    role text not null check (role in ('primary', 'supporting', 'replacement', 'attachment')),
    created_at timestamptz not null default now(),
    primary key (review_id, document_id)
);
create unique index if not exists idx_procurement_update_review_documents_primary
    on public.procurement_update_review_documents (review_id)
    where role = 'primary';

-- ── procurement_changes ───────────────────────────────────────────────────
-- Dual-purpose: pending-decision staging (review_decision='pending',
-- applied_at is null) AND, once applied, permanent immutable history
-- (enforced by a trigger in PART 4, not merely by application discipline).
create table if not exists public.procurement_changes (
    id bigserial primary key,
    review_id bigint not null references public.procurement_update_reviews(id) on delete cascade,
    bid_id bigint not null references public.bids(id) on delete cascade,
    organization_id uuid not null references public.organizations(id),
    review_decision text not null default 'pending' check (review_decision in ('pending', 'approved', 'rejected')),
    decided_by_user_id uuid references auth.users(id),
    decided_at timestamptz,
    applied_at timestamptz,
    procurement_revision integer,
    source_document_id bigint references public.documents(id),
    source_document_hash text,
    physical_source_ref text,
    entity_type text not null check (entity_type in
        ('requirement', 'bid_brief_field', 'deliverable', 'outline_section', 'other')),
    entity_id text,
    target_requirement_id bigint references public.requirements(id),
    related_requirement_ids jsonb,
    change_type text not null check (change_type in
        ('ADDED', 'MODIFIED', 'SUPERSEDED', 'REMOVED', 'CLARIFIED', 'UNCHANGED')),
    canonical_effect text not null check (canonical_effect in ('canonical_change', 'evidence_only')),
    previous_value jsonb,
    new_value jsonb,
    extraction_evidence jsonb,
    proposed_by text not null default 'system',
    review_note text,
    created_at timestamptz not null default now(),
    constraint change_effect_consistency check (
        (change_type in ('ADDED', 'MODIFIED', 'SUPERSEDED', 'REMOVED') and canonical_effect = 'canonical_change')
        or (change_type = 'UNCHANGED' and canonical_effect = 'evidence_only')
        or (change_type = 'CLARIFIED')
    )
);
create index if not exists idx_procurement_changes_bid_revision
    on public.procurement_changes (bid_id, procurement_revision);
create index if not exists idx_procurement_changes_entity
    on public.procurement_changes (bid_id, entity_type, entity_id);
create index if not exists idx_procurement_changes_review
    on public.procurement_changes (review_id);


-- ═══════════════════════════════════════════════════════════════════════════
-- PART 3 — governed RPCs (the ONLY write path for all four tables above)
-- ═══════════════════════════════════════════════════════════════════════════
-- Every function: SECURITY DEFINER, fixed search_path (prevents
-- search_path-hijacking), fully-qualified object names throughout, no
-- dynamic SQL, EXECUTE revoked from PUBLIC/anon/authenticated and granted
-- only to service_role -- application authorization (tenancy.py's
-- require_bid_access) happens BEFORE any of these are ever called; this is
-- defense in depth, not a substitute for it.

-- ── helper: even-odds-safe document-set digest ────────────────────────────
create or replace function public.compute_procurement_document_set_digest(
    p_review_kind text,
    p_document_ids bigint[],
    p_document_hashes text[],
    p_document_roles text[],
    p_conflict_id bigint,
    p_base_procurement_revision integer
) returns text
language plpgsql
stable
security definer
set search_path = public, pg_temp
as $$
declare
    v_combined text;
begin
    if p_review_kind = 'conflict_resolution' then
        return encode(digest(
            'conflict_resolution:' || coalesce(p_conflict_id::text, '') || ':' || p_base_procurement_revision::text,
            'sha256'
        ), 'hex');
    end if;

    -- Parallel array unnest, sorted by the combined "id:hash:role" string so
    -- upload/array order never affects the digest -- string sort is just as
    -- deterministic as numeric sort for this purpose, and far simpler than
    -- an index-lookup loop.
    select string_agg(part, ',' order by part) into v_combined
    from (
        select (t.document_id::text || ':' || coalesce(t.document_hash, '') || ':' || t.role) as part
        from unnest(p_document_ids, p_document_hashes, p_document_roles)
            as t(document_id, document_hash, role)
    ) parts;

    return encode(digest(p_review_kind || ':' || coalesce(v_combined, ''), 'sha256'), 'hex');
end;
$$;
revoke all on function public.compute_procurement_document_set_digest(text, bigint[], text[], text[], bigint, integer) from public;
revoke execute on function public.compute_procurement_document_set_digest(text, bigint[], text[], text[], bigint, integer) from anon;
revoke execute on function public.compute_procurement_document_set_digest(text, bigint[], text[], text[], bigint, integer) from authenticated;
grant execute on function public.compute_procurement_document_set_digest(text, bigint[], text[], text[], bigint, integer) to service_role;


-- ── create_procurement_update_review ──────────────────────────────────────
create or replace function public.create_procurement_update_review(
    p_bid_id bigint,
    p_organization_id uuid,
    p_review_kind text,
    p_buyer_update_type text,
    p_buyer_issued_date date,
    p_document_ids bigint[],
    p_document_roles text[],
    p_conflict_id bigint default null,
    p_idempotency_key text default null
) returns table (review_id bigint, is_new boolean)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_current_revision integer;
    v_truth_status text;
    v_digest text;
    v_existing_id bigint;
    v_new_id bigint;
    v_document_hashes text[];
    v_primary_count integer;
    v_doc_count integer;
begin
    select procurement_revision, procurement_truth_status
        into v_current_revision, v_truth_status
        from public.bids where id = p_bid_id and organization_id = p_organization_id;
    if v_current_revision is null then
        raise exception 'bid_not_found';
    end if;

    if p_review_kind not in ('baseline', 'buyer_update', 'conflict_resolution') then
        raise exception 'invalid_review_kind';
    end if;

    if p_review_kind in ('baseline', 'buyer_update') then
        v_doc_count := coalesce(array_length(p_document_ids, 1), 0);
        if v_doc_count < 1 then
            raise exception 'review_requires_at_least_one_document';
        end if;
        select count(*) into v_primary_count from unnest(p_document_roles) r where r = 'primary';
        if v_primary_count != 1 then
            raise exception 'review_requires_exactly_one_primary_document';
        end if;
        if exists (
            select 1 from public.documents d
            where d.id = any(p_document_ids)
              and (d.bid_id != p_bid_id or d.content_hash is null)
        ) then
            raise exception 'document_not_ready';
        end if;
        if p_review_kind = 'baseline' and v_truth_status != 'ungoverned' then
            raise exception 'baseline_already_governed';
        end if;
        if p_review_kind = 'buyer_update' and v_truth_status != 'governed' then
            raise exception 'baseline_not_governed';
        end if;
        select array_agg(d.content_hash order by array_position(p_document_ids, d.id))
            into v_document_hashes
            from public.documents d where d.id = any(p_document_ids);
    else
        if p_conflict_id is null then
            raise exception 'conflict_resolution_requires_conflict_id';
        end if;
        if not exists (select 1 from public.procurement_conflicts c
                       where c.id = p_conflict_id and c.bid_id = p_bid_id) then
            raise exception 'conflict_not_found_for_bid';
        end if;
    end if;

    v_digest := public.compute_procurement_document_set_digest(
        p_review_kind, p_document_ids, v_document_hashes, p_document_roles,
        p_conflict_id, v_current_revision
    );

    select id into v_existing_id from public.procurement_update_reviews
        where bid_id = p_bid_id and document_set_digest = v_digest
          and base_procurement_revision = v_current_revision and status != 'failed'
        limit 1;
    if v_existing_id is not null then
        return query select v_existing_id, false;
        return;
    end if;

    insert into public.procurement_update_reviews (
        bid_id, organization_id, review_kind, buyer_update_type, conflict_id,
        buyer_issued_date, base_procurement_revision, document_set_digest, idempotency_key
    ) values (
        p_bid_id, p_organization_id, p_review_kind, p_buyer_update_type, p_conflict_id,
        p_buyer_issued_date, v_current_revision, v_digest, p_idempotency_key
    ) returning id into v_new_id;

    if p_review_kind in ('baseline', 'buyer_update') then
        insert into public.procurement_update_review_documents (review_id, document_id, organization_id, document_hash, role)
        select v_new_id, d.id, p_organization_id, d.content_hash, r.role
        from unnest(p_document_ids) with ordinality as ids(document_id, ord)
        join unnest(p_document_roles) with ordinality as r(role, ord) on r.ord = ids.ord
        join public.documents d on d.id = ids.document_id;
    end if;

    return query select v_new_id, true;
end;
$$;
revoke all on function public.create_procurement_update_review(bigint, uuid, text, text, date, bigint[], text[], bigint, text) from public;
revoke execute on function public.create_procurement_update_review(bigint, uuid, text, text, date, bigint[], text[], bigint, text) from anon;
revoke execute on function public.create_procurement_update_review(bigint, uuid, text, text, date, bigint[], text[], bigint, text) from authenticated;
grant execute on function public.create_procurement_update_review(bigint, uuid, text, text, date, bigint[], text[], bigint, text) to service_role;


-- ── record_change_review_decision ─────────────────────────────────────────
-- The ONLY ordinary write path for an individual approve/reject decision.
create or replace function public.record_change_review_decision(
    p_change_id bigint,
    p_decision text,
    p_actor_user_id uuid,
    p_review_note text default null
) returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_applied_at timestamptz;
    v_org_id uuid;
begin
    if p_decision not in ('approved', 'rejected') then
        raise exception 'invalid_decision';
    end if;

    select applied_at, organization_id into v_applied_at, v_org_id
        from public.procurement_changes where id = p_change_id;
    if v_org_id is null then
        raise exception 'change_not_found';
    end if;
    if v_applied_at is not null then
        raise exception 'change_already_applied';
    end if;
    if p_actor_user_id is not null and not exists (
        select 1 from public.organization_members m
        where m.organization_id = v_org_id and m.user_id = p_actor_user_id
    ) then
        raise exception 'actor_not_in_organization';
    end if;

    update public.procurement_changes
        set review_decision = p_decision,
            decided_by_user_id = p_actor_user_id,
            decided_at = now(),
            review_note = coalesce(p_review_note, review_note)
        where id = p_change_id;
end;
$$;
revoke all on function public.record_change_review_decision(bigint, text, uuid, text) from public;
revoke execute on function public.record_change_review_decision(bigint, text, uuid, text) from anon;
revoke execute on function public.record_change_review_decision(bigint, text, uuid, text) from authenticated;
grant execute on function public.record_change_review_decision(bigint, text, uuid, text) to service_role;


-- ── refresh_bid_brief_projection ──────────────────────────────────────────
-- Internal helper, called only by apply_procurement_update_review() and
-- resolve_procurement_conflict() from WITHIN their own transaction (a
-- normal SQL function call inside plpgsql participates in the caller's
-- transaction automatically -- there is no cross-boundary issue, because
-- this never leaves Postgres). Rebuilds ONLY the A/B (canonical/
-- deterministic) columns; the four C-fields (executive_summary,
-- contract_risks, scope_categories, deliverables_summary) are
-- DELIBERATELY left untouched -- no LLM call belongs inside an atomic
-- transaction, and turning synthesized analytical prose into "canonical
-- procurement truth" was explicitly rejected during architecture review.
create or replace function public.refresh_bid_brief_projection(p_bid_id bigint) returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_qual_gates jsonb;
    v_eval_weights jsonb;
    v_source_citations jsonb;
    v_document_conflicts jsonb;
    v_exists boolean;
begin
    select coalesce(jsonb_agg(jsonb_build_object(
                'req_id', r.req_id, 'description', r.description, 'rfso_ref', r.rfso_ref
             )), '[]'::jsonb)
        into v_qual_gates
        from public.requirements r
        where r.bid_id = p_bid_id and r.lifecycle_status = 'active'
          and lower(coalesce(r.category, '')) = 'mandatory';

    select coalesce(jsonb_agg(jsonb_build_object(
                'req_id', r.req_id, 'description', r.description, 'weight', r.weight
             )), '[]'::jsonb)
        into v_eval_weights
        from public.requirements r
        where r.bid_id = p_bid_id and r.lifecycle_status = 'active'
          and lower(coalesce(r.category, '')) = 'rated';

    select coalesce(jsonb_agg(elem), '[]'::jsonb) into v_source_citations
        from public.requirements r, jsonb_array_elements(coalesce(r.source_refs, '[]'::jsonb)) elem
        where r.bid_id = p_bid_id and r.lifecycle_status = 'active';

    select coalesce(jsonb_agg(jsonb_build_object(
                'topic', c.topic, 'status', c.status, 'competing_values', c.competing_values
             )), '[]'::jsonb)
        into v_document_conflicts
        from public.procurement_conflicts c
        where c.bid_id = p_bid_id;

    select exists(select 1 from public.bid_briefs where bid_id = p_bid_id) into v_exists;

    if v_exists then
        update public.bid_briefs set
            qualification_gates = v_qual_gates::text,
            evaluation_breakdown = v_eval_weights::text,
            source_citations = v_source_citations::text,
            document_conflicts = v_document_conflicts
        where bid_id = p_bid_id;
    else
        insert into public.bid_briefs (
            bid_id, qualification_gates, evaluation_breakdown, source_citations, document_conflicts
        ) values (
            p_bid_id, v_qual_gates::text, v_eval_weights::text, v_source_citations::text, v_document_conflicts
        );
    end if;
end;
$$;
revoke all on function public.refresh_bid_brief_projection(bigint) from public;
revoke execute on function public.refresh_bid_brief_projection(bigint) from anon;
revoke execute on function public.refresh_bid_brief_projection(bigint) from authenticated;
grant execute on function public.refresh_bid_brief_projection(bigint) to service_role;


-- ── apply_procurement_update_review ───────────────────────────────────────
-- The single atomic transaction boundary for governed apply. Reads its
-- decision set from procurement_changes itself (populated exclusively by
-- record_change_review_decision) -- no second, competing approved/
-- rejected payload is accepted here.
create or replace function public.apply_procurement_update_review(
    p_review_id bigint,
    p_expected_base_revision integer,
    p_actor_user_id uuid
) returns table (resulting_revision integer, applied_change_count integer)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_bid_id bigint;
    v_org_id uuid;
    v_review_kind text;
    v_review_status text;
    v_truth_status text;
    v_current_revision integer;
    v_new_revision integer;
    v_pending_count integer;
    v_approved_count integer;
    v_canonical_change_count integer;
    v_applied_count integer := 0;
    v_change record;
    v_new_req_id bigint;
begin
    select r.bid_id, r.organization_id, r.review_kind, r.status
        into v_bid_id, v_org_id, v_review_kind, v_review_status
        from public.procurement_update_reviews r where r.id = p_review_id;
    if v_bid_id is null then
        raise exception 'review_not_found';
    end if;

    if p_actor_user_id is not null and not exists (
        select 1 from public.organization_members m
        where m.organization_id = v_org_id and m.user_id = p_actor_user_id
    ) then
        raise exception 'actor_not_in_organization';
    end if;

    select procurement_revision, procurement_truth_status into v_current_revision, v_truth_status
        from public.bids where id = v_bid_id for update;

    if v_current_revision != p_expected_base_revision then
        raise exception 'stale_revision';
    end if;

    if v_review_status = 'applied' then
        return query select r.resulting_procurement_revision, 0
            from public.procurement_update_reviews r where r.id = p_review_id;
        return;
    end if;

    if v_review_status not in ('ready_for_review', 'reviewed') then
        raise exception 'review_not_reviewable';
    end if;

    if v_review_kind = 'baseline' and v_truth_status != 'ungoverned' then
        raise exception 'baseline_already_governed';
    end if;
    if v_review_kind = 'buyer_update' and v_truth_status != 'governed' then
        raise exception 'baseline_not_governed';
    end if;

    select count(*) into v_pending_count from public.procurement_changes
        where review_id = p_review_id and review_decision = 'pending';
    if v_pending_count > 0 then
        raise exception 'incomplete_review_decisions';
    end if;

    select count(*) into v_approved_count from public.procurement_changes
        where review_id = p_review_id and review_decision = 'approved';
    if v_review_kind in ('baseline', 'conflict_resolution') and v_approved_count < 1 then
        raise exception 'no_approved_material_proposal';
    end if;

    select count(*) into v_canonical_change_count from public.procurement_changes
        where review_id = p_review_id and review_decision = 'approved' and canonical_effect = 'canonical_change';

    if v_canonical_change_count > 0 then
        v_new_revision := v_current_revision + 1;
    else
        v_new_revision := v_current_revision;
    end if;

    for v_change in
        select * from public.procurement_changes
        where review_id = p_review_id and review_decision = 'approved'
        order by id
    loop
        if v_change.entity_type = 'requirement' then
            if v_change.change_type = 'ADDED' then
                insert into public.requirements (
                    bid_id, req_id, category, description, rfso_ref, weight, evidence, lifecycle_status
                ) values (
                    v_bid_id, v_change.entity_id,
                    v_change.new_value->>'category', v_change.new_value->>'description',
                    v_change.new_value->>'rfso_ref',
                    nullif(v_change.new_value->>'weight', '')::numeric,
                    v_change.new_value->>'evidence', 'active'
                ) returning id into v_new_req_id;
                update public.procurement_changes set target_requirement_id = v_new_req_id where id = v_change.id;
            elsif v_change.change_type = 'MODIFIED' and v_change.target_requirement_id is not null then
                update public.requirements set
                    description = coalesce(v_change.new_value->>'description', description),
                    weight = coalesce(nullif(v_change.new_value->>'weight', '')::numeric, weight),
                    rfso_ref = coalesce(v_change.new_value->>'rfso_ref', rfso_ref),
                    evidence = coalesce(v_change.new_value->>'evidence', evidence)
                where id = v_change.target_requirement_id;
            elsif v_change.change_type in ('SUPERSEDED', 'REMOVED') and v_change.target_requirement_id is not null then
                update public.requirements set
                    lifecycle_status = lower(v_change.change_type),
                    retired_at_procurement_revision = v_new_revision
                where id = v_change.target_requirement_id;
            end if;

            -- current-governing-evidence cache refresh (never for REMOVED/SUPERSEDED --
            -- a retired requirement has no "current" evidence entry)
            if v_change.change_type != 'REMOVED' then
                update public.requirements
                    set source_refs = coalesce(source_refs, '[]'::jsonb) || jsonb_build_array(jsonb_build_object(
                        'document_id', v_change.source_document_id,
                        'document_hash', v_change.source_document_hash,
                        -- Baseline is the FIRST governed review for this bid -- there is no
                        -- prior GOVERNED source to "modify" or "confirm unchanged" against, so
                        -- every approved baseline fact (however it compares to the
                        -- pre-governance legacy extraction) is ESTABLISHING that requirement
                        -- under governance for the first time, including a baseline
                        -- UNCHANGED/evidence_only proposal that simply verifies a legacy row
                        -- was already correct. 'confirmed_unchanged'/'modified'/'clarified' only
                        -- ever describe a buyer_update (or conflict_resolution) review, which by
                        -- definition compares against an ALREADY-governed prior state.
                        'role', case
                                    when v_review_kind = 'baseline' then 'established'
                                    when v_change.change_type = 'MODIFIED' then 'modified'
                                    when v_change.change_type = 'SUPERSEDED' then 'modified'
                                    when v_change.change_type = 'CLARIFIED' then 'clarified'
                                    when v_change.change_type = 'UNCHANGED' then 'confirmed_unchanged'
                                    when v_change.change_type = 'ADDED' then 'established'
                                    else 'established' end,
                        'procurement_revision', v_new_revision
                    ))
                    where id = coalesce(v_change.target_requirement_id, v_new_req_id);
            end if;

        elsif v_change.entity_type = 'bid_brief_field' then
            -- whitelist only -- never dynamic SQL against an arbitrary column name
            if v_change.entity_id in (
                'opportunity_type', 'contract_term', 'procurement_model', 'commercial_structure',
                'submission_requirements', 'key_dates'
            ) then
                if not exists (select 1 from public.bid_briefs where bid_id = v_bid_id) then
                    insert into public.bid_briefs (bid_id) values (v_bid_id);
                end if;
                if v_change.entity_id = 'opportunity_type' then
                    update public.bid_briefs set opportunity_type = v_change.new_value->>'value' where bid_id = v_bid_id;
                elsif v_change.entity_id = 'contract_term' then
                    update public.bid_briefs set contract_term = v_change.new_value->>'value' where bid_id = v_bid_id;
                elsif v_change.entity_id = 'procurement_model' then
                    update public.bid_briefs set procurement_model = v_change.new_value->>'value' where bid_id = v_bid_id;
                elsif v_change.entity_id = 'commercial_structure' then
                    update public.bid_briefs set commercial_structure = v_change.new_value->>'value' where bid_id = v_bid_id;
                elsif v_change.entity_id = 'submission_requirements' then
                    update public.bid_briefs set submission_requirements = v_change.new_value->>'value' where bid_id = v_bid_id;
                elsif v_change.entity_id = 'key_dates' then
                    update public.bid_briefs set key_dates = v_change.new_value->>'value' where bid_id = v_bid_id;
                end if;
            else
                raise exception 'unknown_bid_brief_field';
            end if;
        end if;

        update public.procurement_changes
            set applied_at = now(), procurement_revision = v_new_revision
            where id = v_change.id;
        v_applied_count := v_applied_count + 1;
    end loop;

    update public.bids set
        procurement_revision = v_new_revision,
        procurement_truth_status = case when v_review_kind = 'baseline' then 'governed' else procurement_truth_status end
        where id = v_bid_id;

    update public.procurement_update_reviews set
        status = 'applied',
        applied_at = now(),
        applied_by_user_id = p_actor_user_id,
        resulting_procurement_revision = v_new_revision,
        no_canonical_change = (v_canonical_change_count = 0)
        where id = p_review_id;

    perform public.refresh_bid_brief_projection(v_bid_id);

    return query select v_new_revision, v_applied_count;
end;
$$;
revoke all on function public.apply_procurement_update_review(bigint, integer, uuid) from public;
revoke execute on function public.apply_procurement_update_review(bigint, integer, uuid) from anon;
revoke execute on function public.apply_procurement_update_review(bigint, integer, uuid) from authenticated;
grant execute on function public.apply_procurement_update_review(bigint, integer, uuid) to service_role;


-- ── resolve_procurement_conflict ──────────────────────────────────────────
-- A conflict resolution is itself a governed canonical change -- it always
-- creates a review_kind='conflict_resolution' review with one immutable
-- procurement_changes row and increments the revision. There is no path
-- that merely flips procurement_conflicts.status='resolved' without this.
create or replace function public.resolve_procurement_conflict(
    p_conflict_id bigint,
    p_expected_base_revision integer,
    p_resolution_value jsonb,
    p_resolution_reason text,
    p_actor_user_id uuid
) returns table (resulting_revision integer)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_bid_id bigint;
    v_org_id uuid;
    v_entity_type text;
    v_entity_id text;
    v_target_req_id bigint;
    v_current_revision integer;
    v_new_revision integer;
    v_review_id bigint;
    v_digest text;
begin
    select bid_id, organization_id, entity_type, entity_id, target_requirement_id
        into v_bid_id, v_org_id, v_entity_type, v_entity_id, v_target_req_id
        from public.procurement_conflicts where id = p_conflict_id and status = 'unresolved';
    if v_bid_id is null then
        raise exception 'conflict_not_found_or_already_resolved';
    end if;

    if p_actor_user_id is not null and not exists (
        select 1 from public.organization_members m
        where m.organization_id = v_org_id and m.user_id = p_actor_user_id
    ) then
        raise exception 'actor_not_in_organization';
    end if;

    select procurement_revision into v_current_revision from public.bids where id = v_bid_id for update;
    if v_current_revision != p_expected_base_revision then
        raise exception 'stale_revision';
    end if;

    v_digest := public.compute_procurement_document_set_digest(
        'conflict_resolution', array[]::bigint[], array[]::text[], array[]::text[],
        p_conflict_id, v_current_revision
    );

    insert into public.procurement_update_reviews (
        bid_id, organization_id, review_kind, conflict_id, status,
        base_procurement_revision, document_set_digest,
        reviewed_by_user_id, reviewed_at
    ) values (
        v_bid_id, v_org_id, 'conflict_resolution', p_conflict_id, 'reviewed',
        v_current_revision, v_digest, p_actor_user_id, now()
    ) returning id into v_review_id;

    v_new_revision := v_current_revision + 1;

    insert into public.procurement_changes (
        review_id, bid_id, organization_id, review_decision, decided_by_user_id, decided_at,
        applied_at, procurement_revision, entity_type, entity_id, target_requirement_id,
        change_type, canonical_effect, new_value, review_note
    ) values (
        v_review_id, v_bid_id, v_org_id, 'approved', p_actor_user_id, now(),
        now(), v_new_revision, v_entity_type, v_entity_id, v_target_req_id,
        'MODIFIED', 'canonical_change', p_resolution_value, p_resolution_reason
    );

    if v_entity_type = 'requirement' and v_target_req_id is not null then
        update public.requirements set weight = nullif(p_resolution_value->>'weight', '')::numeric
            where id = v_target_req_id and p_resolution_value ? 'weight';
    end if;

    update public.procurement_conflicts set
        status = 'resolved', resolution_value = p_resolution_value, resolution_reason = p_resolution_reason,
        resolved_by_user_id = p_actor_user_id, resolved_at = now(), resolving_procurement_revision = v_new_revision
        where id = p_conflict_id;

    update public.bids set procurement_revision = v_new_revision where id = v_bid_id;
    update public.procurement_update_reviews set
        status = 'applied', applied_at = now(), applied_by_user_id = p_actor_user_id,
        resulting_procurement_revision = v_new_revision
        where id = v_review_id;

    perform public.refresh_bid_brief_projection(v_bid_id);

    return query select v_new_revision;
end;
$$;
revoke all on function public.resolve_procurement_conflict(bigint, integer, jsonb, text, uuid) from public;
revoke execute on function public.resolve_procurement_conflict(bigint, integer, jsonb, text, uuid) from anon;
revoke execute on function public.resolve_procurement_conflict(bigint, integer, jsonb, text, uuid) from authenticated;
grant execute on function public.resolve_procurement_conflict(bigint, integer, jsonb, text, uuid) to service_role;


-- ═══════════════════════════════════════════════════════════════════════════
-- PART 4 — applied-history immutability triggers
-- ═══════════════════════════════════════════════════════════════════════════
-- Database-level protection, independent of RLS/grants and independent of
-- Python-side discipline: once applied_at/status='applied' (or, for
-- conflicts, status='resolved') is set, the row cannot be UPDATEd or
-- DELETEd through ANY role, including service_role code running outside
-- the sanctioned RPCs above. The RPCs themselves never re-update an
-- already-applied/resolved row (each only ever sets that terminal state
-- once, per change/review/conflict), so this never conflicts with
-- legitimate use. Four triggers total: applied procurement_changes,
-- applied procurement_update_reviews, applied review-document membership,
-- and resolved procurement_conflicts.

create or replace function public.prevent_applied_change_mutation() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
    if old.applied_at is not null then
        raise exception 'applied_change_immutable';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;
drop trigger if exists guard_applied_change_immutability on public.procurement_changes;
create trigger guard_applied_change_immutability
    before update or delete on public.procurement_changes
    for each row execute function public.prevent_applied_change_mutation();

create or replace function public.prevent_applied_review_mutation() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
    if old.status = 'applied' then
        raise exception 'applied_review_immutable';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;
drop trigger if exists guard_applied_review_immutability on public.procurement_update_reviews;
create trigger guard_applied_review_immutability
    before update or delete on public.procurement_update_reviews
    for each row execute function public.prevent_applied_review_mutation();

create or replace function public.prevent_applied_review_document_mutation() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
declare
    v_status text;
begin
    select status into v_status from public.procurement_update_reviews where id = old.review_id;
    if v_status = 'applied' then
        raise exception 'applied_review_document_immutable';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;
drop trigger if exists guard_applied_review_document_immutability on public.procurement_update_review_documents;
create trigger guard_applied_review_document_immutability
    before update or delete on public.procurement_update_review_documents
    for each row execute function public.prevent_applied_review_document_mutation();

-- A resolved conflict's historical resolution record must be just as
-- immutable as applied change/review history above -- once
-- status='resolved' (set exactly once, by resolve_procurement_conflict()
-- itself), no role -- including accidental service-role code running
-- outside that RPC -- may update or delete the row. The legitimate
-- unresolved -> resolved transition is unaffected: OLD.status is still
-- 'unresolved' at the moment resolve_procurement_conflict() performs that
-- one UPDATE, so this trigger only ever blocks what comes AFTER.
create or replace function public.prevent_resolved_conflict_mutation() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
    if old.status = 'resolved' then
        raise exception 'resolved_conflict_immutable';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;
drop trigger if exists guard_resolved_conflict_immutability on public.procurement_conflicts;
create trigger guard_resolved_conflict_immutability
    before update or delete on public.procurement_conflicts
    for each row execute function public.prevent_resolved_conflict_mutation();


-- ═══════════════════════════════════════════════════════════════════════════
-- PART 5 — RLS: SELECT only for authenticated org members, no direct writes
-- ═══════════════════════════════════════════════════════════════════════════
-- Matches the existing bid_briefs precedent (migration 008): a governance/
-- audit history table is not an ordinary user-writable CRUD table. Every
-- write happens through the SECURITY DEFINER RPCs in PART 3, which run as
-- service_role and therefore bypass RLS by definition -- these SELECT
-- policies exist only so an authenticated org member's own browser session
-- can read their own bid's governance history/pending proposals for the
-- review UI.

alter table public.procurement_update_reviews enable row level security;
alter table public.procurement_update_review_documents enable row level security;
alter table public.procurement_changes enable row level security;
alter table public.procurement_conflicts enable row level security;

create policy procurement_update_reviews_select_bid_access
    on public.procurement_update_reviews for select to authenticated
    using (public.can_access_bid(bid_id));

create policy procurement_update_review_documents_select_bid_access
    on public.procurement_update_review_documents for select to authenticated
    using (review_id in (select id from public.procurement_update_reviews where public.can_access_bid(bid_id)));

create policy procurement_changes_select_bid_access
    on public.procurement_changes for select to authenticated
    using (public.can_access_bid(bid_id));

create policy procurement_conflicts_select_bid_access
    on public.procurement_conflicts for select to authenticated
    using (public.can_access_bid(bid_id));

-- No insert/update/delete policy is created for any of the four tables --
-- ordinary authenticated org members get SELECT only, by omission (RLS
-- fails closed on any operation with no matching policy). Direct table
-- privileges are additionally revoked below as defense in depth, since
-- Supabase/Postgres RLS and GRANT are independent layers -- a table can be
-- RLS-enabled with no write policy AND still technically GRANTed UPDATE at
-- the privilege level, which would let a write through if RLS were ever
-- misconfigured. Both layers are closed here.
revoke insert, update, delete on public.procurement_update_reviews from authenticated;
revoke insert, update, delete on public.procurement_update_review_documents from authenticated;
revoke insert, update, delete on public.procurement_changes from authenticated;
revoke insert, update, delete on public.procurement_conflicts from authenticated;
revoke all on public.procurement_update_reviews from anon;
revoke all on public.procurement_update_review_documents from anon;
revoke all on public.procurement_changes from anon;
revoke all on public.procurement_conflicts from anon;
