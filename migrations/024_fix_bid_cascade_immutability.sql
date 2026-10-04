-- ============================================================================
-- Migration 024: Cascade-Aware Immutability for Bid Cascade Deletion
-- ============================================================================
--
-- Problem:
-- Tables recording append-only/immutable history (full_analysis_events,
-- check_run_events, procurement_changes, procurement_update_reviews,
-- procurement_update_review_documents, and procurement_conflicts) declare
-- foreign keys to public.bids (or parent review) with ON DELETE CASCADE.
-- However, their BEFORE UPDATE OR DELETE triggers unconditionally raised
-- exceptions on ANY delete, which blocked parent bid cascading deletion.
--
-- Solution:
-- Make the trigger functions cascade-aware:
-- 1. On UPDATE: preserve strict immutability (always reject when immutable).
-- 2. On direct DELETE while parent bid exists: reject with existing error.
-- 3. On parent bid cascade DELETE: allow child rows to be deleted.
--
-- Does NOT weaken append-only semantics: direct deletion of child history
-- while the parent bid exists remains strictly prohibited.
-- ============================================================================

-- ── 1. Full Analysis Events ───────────────────────────────────────────────────
create or replace function public.full_analysis_reject_mutation()
returns trigger language plpgsql set search_path = public as $$
begin
    if tg_op = 'DELETE' then
        if exists (
            select 1
            from public.bids
            where id = old.bid_id
        ) then
            raise exception '% rows are append-only', tg_table_name;
        end if;
        return old;
    end if;

    raise exception '% rows are append-only', tg_table_name;
end;
$$;

drop trigger if exists trg_full_analysis_events_append_only on public.full_analysis_events;
create trigger trg_full_analysis_events_append_only
    before update or delete on public.full_analysis_events
    for each row execute function public.full_analysis_reject_mutation();

-- ── 2. Check Run Events ───────────────────────────────────────────────────────
create or replace function public.check_run_reject_mutation()
returns trigger language plpgsql set search_path = public as $$
begin
    if tg_op = 'DELETE' then
        if exists (
            select 1
            from public.bids
            where id = old.bid_id
        ) then
            raise exception '% rows are immutable', tg_table_name;
        end if;
        return old;
    end if;

    raise exception '% rows are immutable', tg_table_name;
end;
$$;

drop trigger if exists trg_check_run_events_append_only on public.check_run_events;
create trigger trg_check_run_events_append_only
    before update or delete on public.check_run_events
    for each row execute function public.check_run_reject_mutation();

-- ── 3. Applied Procurement Changes ───────────────────────────────────────────
create or replace function public.prevent_applied_change_mutation() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
    if old.applied_at is not null then
        if tg_op = 'DELETE' then
            if exists (
                select 1
                from public.bids
                where id = old.bid_id
            ) then
                raise exception 'applied_change_immutable';
            end if;
            return old;
        end if;
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

-- ── 4. Applied Procurement Reviews ───────────────────────────────────────────
create or replace function public.prevent_applied_review_mutation() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
    if old.status = 'applied' then
        if tg_op = 'DELETE' then
            if exists (
                select 1
                from public.bids
                where id = old.bid_id
            ) then
                raise exception 'applied_review_immutable';
            end if;
            return old;
        end if;
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

-- ── 5. Applied Review Documents ───────────────────────────────────────────────
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

-- ── 6. Resolved Procurement Conflicts ─────────────────────────────────────────
create or replace function public.prevent_resolved_conflict_mutation() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
begin
    if old.status = 'resolved' then
        if tg_op = 'DELETE' then
            if exists (
                select 1
                from public.bids
                where id = old.bid_id
            ) then
                raise exception 'resolved_conflict_immutable';
            end if;
            return old;
        end if;
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
