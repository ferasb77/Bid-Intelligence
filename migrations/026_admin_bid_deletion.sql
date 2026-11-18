-- Migration 026: organization Admin/Owner bid deletion
--
-- Lets an active Owner or Admin of the organization that owns a bid delete
-- that bid and everything that belongs only to it, in one transaction.
--
--   1. public.bid_storage_cleanup -- durable queue of the bid's Storage
--      objects. The deletion transaction records them; the application
--      removes the objects through the Storage API afterwards and clears
--      each entry, so a Storage failure stays visible and can be retried
--      instead of being lost. RLS on, no policies, service_role only.
--   2. public.bid_deletion_permits(bigint) -- true only inside the deletion
--      transaction below, for the bid being deleted. The append-only and
--      immutability triggers on bid-owned history tables keep rejecting
--      every other UPDATE/DELETE exactly as before; they let rows go only
--      when their whole bid is being deleted.
--   3. public.delete_bid_as_organization_admin(bid, organization, actor) --
--      service_role only (the application calls it after its own session
--      check, like every other application RPC). It re-checks in the
--      database that the actor's account is active and that the actor
--      CURRENTLY holds 'owner' or 'admin' in the organization that owns the
--      bid, refuses while an analysis of the bid is still running, and
--      refuses when organization-wide memory was derived from the bid.
--
-- Rows of other bids and organization-wide records are untouched:
-- content_library.bid_id and model_usage_events.bid_id/analysis_run_id are
-- ON DELETE SET NULL (shared library content and usage accounting stay);
-- organizational_memory_items.source_bid_id is RESTRICT (refused, see 3).
-- Apply as the table/function owner (supabase_admin on Supabase).

-- ── 1. Storage cleanup queue ────────────────────────────────────────────
create table if not exists public.bid_storage_cleanup (
    id              bigserial primary key,
    organization_id uuid not null,
    bid_id          bigint not null,          -- no FK: the bid is gone
    bucket_id       text not null,
    object_name     text not null,
    queued_at       timestamptz not null default now(),
    attempts        integer not null default 0,
    last_error      text,
    last_attempt_at timestamptz
);
create index if not exists bid_storage_cleanup_org_idx on public.bid_storage_cleanup (organization_id);
alter table public.bid_storage_cleanup enable row level security;
revoke all on table public.bid_storage_cleanup from public, anon, authenticated;
grant select, insert, update, delete on table public.bid_storage_cleanup to service_role;
grant usage, select on sequence public.bid_storage_cleanup_id_seq to service_role;

-- ── 2. deletion scope for the history guards ────────────────────────────
create or replace function public.bid_deletion_permits(p_bid_id bigint)
returns boolean
language sql
stable
set search_path = ''
as $$
    select coalesce(current_setting('bid_intelligence.deleting_bid_id', true), '') <> ''
       and (p_bid_id is null
            or current_setting('bid_intelligence.deleting_bid_id', true) = p_bid_id::text);
$$;
-- Not SECURITY DEFINER; it only reads a transaction-local setting. The
-- guards call it as whichever role touches the table, so that role needs
-- EXECUTE (a refused mutation must still fail with the guard's own error).
revoke all on function public.bid_deletion_permits(bigint) from public, anon;
grant execute on function public.bid_deletion_permits(bigint) to authenticated, service_role;

-- Same bodies as migrations 010/020/022, plus the whole-bid deletion exit.
create or replace function public.full_analysis_reject_mutation()
returns trigger language plpgsql set search_path = public as $$
begin
    if tg_op = 'DELETE' and public.bid_deletion_permits(old.bid_id) then
        return old;
    end if;
    raise exception '% rows are append-only', tg_table_name;
end;
$$;

create or replace function public.check_run_reject_mutation()
returns trigger language plpgsql set search_path = public as $$
begin
    if tg_op = 'DELETE' and public.bid_deletion_permits(old.bid_id) then
        return old;
    end if;
    raise exception '% rows are immutable', tg_table_name;
end;
$$;

create or replace function public.prevent_applied_change_mutation() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
    if tg_op = 'DELETE' and public.bid_deletion_permits(old.bid_id) then
        return old;
    end if;
    if old.applied_at is not null then
        raise exception 'applied_change_immutable';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;

create or replace function public.prevent_applied_review_mutation() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
    if tg_op = 'DELETE' and public.bid_deletion_permits(old.bid_id) then
        return old;
    end if;
    if old.status = 'applied' then
        raise exception 'applied_review_immutable';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;

create or replace function public.prevent_resolved_conflict_mutation() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
    if tg_op = 'DELETE' and public.bid_deletion_permits(old.bid_id) then
        return old;
    end if;
    if old.status = 'resolved' then
        raise exception 'resolved_conflict_immutable';
    end if;
    if tg_op = 'DELETE' then
        return old;
    end if;
    return new;
end;
$$;

-- procurement_update_review_documents has no bid_id; it is only ever
-- deleted through its review, which belongs to the bid being deleted.
create or replace function public.prevent_applied_review_document_mutation() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
declare
    v_status text;
begin
    if tg_op = 'DELETE' and public.bid_deletion_permits(null) then
        return old;
    end if;
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

revoke all on function public.prevent_applied_change_mutation() from public, anon, authenticated;
revoke all on function public.prevent_applied_review_mutation() from public, anon, authenticated;
revoke all on function public.prevent_resolved_conflict_mutation() from public, anon, authenticated;
revoke all on function public.prevent_applied_review_document_mutation() from public, anon, authenticated;

-- ── 3. the deletion ─────────────────────────────────────────────────────
create or replace function public.delete_bid_as_organization_admin(
    p_bid_id bigint, p_organization_id uuid, p_actor_user_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_role text;
    v_bid record;
    v_objects text[];
    v_left integer;
    v_cleanup bigint[];
begin
    if p_bid_id is null or p_organization_id is null or p_actor_user_id is null
       or not public.user_account_is_active(p_actor_user_id) then
        return jsonb_build_object('ok', false, 'reason', 'not_authorized');
    end if;
    select m.role into v_role from public.organization_members m
     where m.organization_id = p_organization_id and m.user_id = p_actor_user_id;
    if v_role is null or v_role not in ('owner', 'admin') then
        return jsonb_build_object('ok', false, 'reason', 'not_authorized');
    end if;

    -- Lock the bid: a run being started for it waits on this lock and then
    -- fails on the foreign key, so nothing new attaches to a deleted bid.
    select b.id, b.title, b.file_number into v_bid from public.bids b
     where b.id = p_bid_id and b.organization_id = p_organization_id
     for update;
    if not found then
        -- also another organization's bid: indistinguishable from none
        return jsonb_build_object('ok', false, 'reason', 'not_found');
    end if;

    if exists (select 1 from public.analysis_runs r
                where r.bid_id = p_bid_id and r.status not in ('COMPLETE', 'PARTIAL', 'FAILED')) then
        return jsonb_build_object('ok', false, 'reason', 'analysis_in_progress');
    end if;
    if exists (select 1 from public.organizational_memory_items i where i.source_bid_id = p_bid_id) then
        return jsonb_build_object('ok', false, 'reason', 'used_by_organizational_memory');
    end if;

    -- The bid's Storage objects: everything under its own prefix plus any
    -- path its records name (the application stores all of them under it).
    select coalesce(array_agg(distinct x.name order by x.name), '{}') into v_objects
    from (
        select o.name from storage.objects o
         where o.bucket_id = 'bid-documents' and o.name like p_bid_id::text || '/%'
        union select d.storage_path from public.documents d where d.bid_id = p_bid_id
        union select v.storage_path from public.document_versions v
               join public.documents d on d.id = v.document_id where d.bid_id = p_bid_id
        union select r.report_storage_path from public.analysis_runs r where r.bid_id = p_bid_id
    ) x
    where x.name is not null and x.name <> '';

    with ins as (
        insert into public.bid_storage_cleanup (organization_id, bid_id, bucket_id, object_name)
        select p_organization_id, p_bid_id, 'bid-documents', n from unnest(v_objects) n
        returning id
    )
    select coalesce(array_agg(id), '{}') into v_cleanup from ins;

    perform set_config('bid_intelligence.deleting_bid_id', p_bid_id::text, true);

    -- Runs first, dependants before the runs they were based on: a FULL or
    -- CHECK run must keep its source run while it exists (constraint and
    -- terminal-run guard), so the cascade from the bid must not reach a
    -- source run before its dependants.
    loop
        delete from public.analysis_runs r
         where r.bid_id = p_bid_id
           and not exists (select 1 from public.analysis_runs d where d.source_analysis_run_id = r.id);
        get diagnostics v_left = row_count;
        exit when v_left = 0;
    end loop;
    if exists (select 1 from public.analysis_runs r where r.bid_id = p_bid_id) then
        raise exception 'bid % has analysis runs referenced by another bid', p_bid_id;
    end if;

    delete from public.bids b where b.id = p_bid_id and b.organization_id = p_organization_id;

    perform set_config('bid_intelligence.deleting_bid_id', '', true);

    return jsonb_build_object('ok', true, 'reason', '', 'bid_id', p_bid_id,
                              'title', v_bid.title, 'reference', v_bid.file_number,
                              'storage_objects', to_jsonb(v_objects),
                              'cleanup_ids', to_jsonb(v_cleanup));
end;
$$;

revoke all on function public.delete_bid_as_organization_admin(bigint, uuid, uuid) from public, anon, authenticated;
grant execute on function public.delete_bid_as_organization_admin(bigint, uuid, uuid) to service_role;

-- ── self-check: nothing new is callable by the API roles ────────────────
do $$
begin
    if has_function_privilege('authenticated', 'public.delete_bid_as_organization_admin(bigint, uuid, uuid)', 'EXECUTE')
       or has_function_privilege('anon', 'public.delete_bid_as_organization_admin(bigint, uuid, uuid)', 'EXECUTE')
       or has_table_privilege('authenticated', 'public.bid_storage_cleanup', 'SELECT')
       or has_table_privilege('anon', 'public.bid_storage_cleanup', 'SELECT') then
        raise exception 'migration 026: deletion objects are reachable by API roles';
    end if;
end $$;
