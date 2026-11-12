-- Migration 025: active-account authorization (Super Admin revocation correction)
--
-- Defect corrected (BID_INTELLIGENCE_SUPER_ADMIN_INDEPENDENT_VERIFICATION.md):
-- disabling a user in Supabase Auth (GoTrue `banned_until`) blocks new
-- sign-in and token refresh, but an access token issued BEFORE the disable
-- stays cryptographically valid until it expires (JWT_EXP), and PostgREST
-- only validates the signature. Every RLS policy in this schema keyed off
-- `auth.uid()` alone (directly, or through is_organization_member() /
-- can_access_bid()), so a disabled user's still-unexpired token kept
-- authorizing protected reads and writes.
--
-- This migration does NOT revoke tokens cryptographically. It makes the
-- database refuse to AUTHORIZE anything for a principal whose account is
-- not currently active, using the authoritative server-side record GoTrue
-- itself maintains (auth.users.banned_until / deleted_at):
--
--   1. public.user_account_is_active(uuid)   -- service_role only
--      public.current_user_is_active()       -- authenticated (no argument;
--                                               cannot probe other users)
--   2. public.is_organization_member(uuid) now also requires
--      current_user_is_active(). can_access_bid() and every tenant policy
--      (all 70 live policies route through one of these two helpers)
--      inherit it with no policy rewrite.
--   3. organization_members_select_own_rows -- the only policy that used
--      auth.uid() directly -- is recreated with the same active check.
--   4. public.session_access_status(uuid, uuid) -- service_role only; one
--      authoritative account-state + current-membership answer for the
--      application's per-request revalidation of service-role operations.
--   5. EXECUTE on every application SECURITY DEFINER RPC is re-asserted as
--      service_role-only, exactly as migrations 010/011/015-022 intended.
--      On the beta database these grants were observed to have drifted
--      (anon and authenticated held EXECUTE); the block at the end fails
--      the migration if any of them remains callable by anon/authenticated.
--
-- Membership removal needs no new code: the helpers read the CURRENT
-- organization_members row on every evaluation and never consult JWT
-- claims, so a stale token cannot carry a removed membership or an old
-- role. Apply as the table/function owner (supabase_admin on Supabase).

-- ── 1. account-state helpers ────────────────────────────────────────────
create or replace function public.user_account_is_active(p_user_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select p_user_id is not null and exists (
        select 1
        from auth.users u
        where u.id = p_user_id
          and u.deleted_at is null
          and (u.banned_until is null or u.banned_until <= now())
    );
$$;

revoke all on function public.user_account_is_active(uuid) from public, anon, authenticated;
grant execute on function public.user_account_is_active(uuid) to service_role;

create or replace function public.current_user_is_active()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select public.user_account_is_active(auth.uid());
$$;

revoke all on function public.current_user_is_active() from public, anon;
grant execute on function public.current_user_is_active() to authenticated, service_role;

-- ── 2. central membership helper (signature unchanged) ─────────────────
create or replace function public.is_organization_member(target_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select public.current_user_is_active()
       and exists (
        select 1
        from public.organization_members m
        where m.organization_id = target_organization_id
          and m.user_id = auth.uid()
    );
$$;

revoke all on function public.is_organization_member(uuid) from public, anon;
grant execute on function public.is_organization_member(uuid) to authenticated, service_role;

-- can_access_bid(bigint) is unchanged: it delegates to is_organization_member().
revoke all on function public.can_access_bid(bigint) from public, anon;
grant execute on function public.can_access_bid(bigint) to authenticated, service_role;

-- ── 3. the one policy that used auth.uid() directly ────────────────────
drop policy if exists organization_members_select_own_rows on public.organization_members;
create policy organization_members_select_own_rows
    on public.organization_members for select
    to authenticated
    using (user_id = auth.uid() and public.current_user_is_active());

-- ── 4. authoritative status for application revalidation ───────────────
create or replace function public.session_access_status(p_user_id uuid, p_organization_id uuid default null)
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_deleted_at timestamptz;
    v_banned_until timestamptz;
    v_role text;
begin
    if p_user_id is null then
        return jsonb_build_object('ok', false, 'reason', 'account_not_found');
    end if;
    select u.deleted_at, u.banned_until into v_deleted_at, v_banned_until
    from auth.users u where u.id = p_user_id;
    if not found or v_deleted_at is not null then
        return jsonb_build_object('ok', false, 'reason', 'account_not_found');
    end if;
    if v_banned_until is not null and v_banned_until > now() then
        return jsonb_build_object('ok', false, 'reason', 'account_disabled');
    end if;
    if p_organization_id is null then
        return jsonb_build_object('ok', true, 'reason', '', 'role', null);
    end if;
    select m.role into v_role
    from public.organization_members m
    where m.organization_id = p_organization_id and m.user_id = p_user_id;
    if not found then
        return jsonb_build_object('ok', false, 'reason', 'membership_removed');
    end if;
    return jsonb_build_object('ok', true, 'reason', '', 'role', v_role);
end;
$$;

revoke all on function public.session_access_status(uuid, uuid) from public, anon, authenticated;
grant execute on function public.session_access_status(uuid, uuid) to service_role;

-- ── 5. application RPCs: service_role only (re-asserted) ───────────────
do $$
declare
    r record;
    service_rpcs text[] := array[
        'apply_procurement_update_review', 'approve_organizational_memory_item',
        'compute_procurement_document_set_digest', 'create_organizational_memory_item',
        'create_procurement_update_review', 'create_proposal_intelligence_bundle',
        'create_submission_evidence_bundle', 'finalize_check_run', 'finalize_full_analysis_run',
        'get_or_create_proposal_package_snapshot', 'get_or_create_requirement_evidence_enrichment',
        'get_or_create_section_draft', 'ingest_organizational_source_document',
        'is_user_organization_member', 'record_change_review_decision', 'record_check_run_event',
        'record_full_analysis_event', 'refresh_bid_brief_projection', 'resolve_procurement_conflict',
        'start_check_run', 'start_full_analysis_run'];
    trigger_fns text[] := array[
        'prevent_applied_change_mutation', 'prevent_applied_review_document_mutation',
        'prevent_applied_review_mutation', 'prevent_resolved_conflict_mutation'];
begin
    for r in
        select p.oid::regprocedure as sig, p.proname
        from pg_proc p join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public' and p.proname = any(service_rpcs || trigger_fns)
    loop
        execute format('revoke all on function %s from public, anon, authenticated', r.sig);
        if r.proname = any(service_rpcs) then
            execute format('grant execute on function %s to service_role', r.sig);
        end if;
    end loop;
end $$;

-- ── self-check: fail (and roll back) if anything is still exposed ──────
do $$
declare
    v_bad text;
begin
    select string_agg(p.oid::regprocedure::text || ' -> ' || rl, ', ')
      into v_bad
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    cross join (values ('anon'), ('authenticated')) as roles(rl)
    where n.nspname = 'public'
      and p.prosecdef
      and has_function_privilege(rl, p.oid, 'EXECUTE')
      and not (rl = 'authenticated'
               and p.proname in ('is_organization_member', 'can_access_bid', 'current_user_is_active'));
    if v_bad is not null then
        raise exception 'migration 025: SECURITY DEFINER functions still executable by API roles: %', v_bad;
    end if;
end $$;
