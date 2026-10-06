-- ============================================================================
-- Migration 025: Bid Purge Referential Closure & Cascade Immutability
-- ============================================================================
--
-- Problem:
-- When performing a whole-bid deletion (e.g. tenancy.delete_bid_for_organization),
-- the deletion of parent public.bids failed on live Supabase due to missing
-- ON DELETE CASCADE clauses on bid-scoped child cross-references created in
-- Migration 010 (procurement revision governance):
--
-- 1. procurement_update_review_documents.document_id REFERENCES public.documents(id)
--    was declared without ON DELETE CASCADE (default NO ACTION/RESTRICT).
--    When parent bids deleted public.documents, this FK blocked the cascade.
-- 2. procurement_changes.source_document_id REFERENCES public.documents(id)
--    was declared without ON DELETE (default NO ACTION/RESTRICT).
-- 3. procurement_conflicts.target_requirement_id REFERENCES public.requirements(id)
--    was declared without ON DELETE (default NO ACTION/RESTRICT).
-- 4. procurement_changes.target_requirement_id REFERENCES public.requirements(id)
--    was declared without ON DELETE (default NO ACTION/RESTRICT).
-- 5. In Migration 024, prevent_applied_review_document_mutation() checked if the
--    parent review was 'applied', but was not cascade-aware regarding parent bid
--    existence. If the documents cascade reached the review_documents row before
--    the parent review was deleted, a cascade check depending only on review status
--    could block whole-bid deletion.
--
-- Solution:
-- 1. Make prevent_applied_review_document_mutation() bid-cascade aware:
--    - UPDATE: Always reject when parent review is applied (strict immutability).
--    - DELETE: If parent review doesn't exist, allow DELETE.
--              If parent review exists and is applied, check if the parent bid
--              (review.bid_id) still exists. If the parent bid still exists,
--              reject DELETE (blocks direct deletion of review documents and direct
--              deletion of source documents while the bid is alive).
--              If the parent bid is being/has been deleted, allow DELETE.
-- 2. Drop and re-add foreign key constraints with proper referential actions:
--    - procurement_update_review_documents.document_id: ON DELETE CASCADE
--    - procurement_changes.source_document_id: ON DELETE CASCADE
--    - procurement_conflicts.target_requirement_id: ON DELETE SET NULL
--    - procurement_changes.target_requirement_id: ON DELETE SET NULL
--
-- Strict Preservation of Invariants:
-- - Direct DELETE of review_document while parent bid exists: REJECTED.
-- - Direct DELETE of document while applied review and parent bid exist: REJECTED.
-- - UPDATE of applied review_document: REJECTED.
-- - Direct DELETE of applied procurement_change while parent bid exists: REJECTED (Migration 024).
-- - Direct DELETE of resolved procurement_conflict while parent bid exists: REJECTED (Migration 024).
-- ============================================================================

-- ── 1. Update prevent_applied_review_document_mutation() trigger function ─────
create or replace function public.prevent_applied_review_document_mutation() returns trigger
language plpgsql security definer set search_path = public, pg_temp as $$
declare
    v_status text;
    v_bid_id bigint;
begin
    select status, bid_id into v_status, v_bid_id
    from public.procurement_update_reviews
    where id = old.review_id;

    -- If parent review is applied
    if v_status = 'applied' then
        -- UPDATE is strictly immutable
        if tg_op = 'UPDATE' then
            raise exception 'applied_review_document_immutable';
        end if;

        -- DELETE: Reject if parent bid still exists
        if tg_op = 'DELETE' then
            if v_bid_id is not null and exists (
                select 1 from public.bids where id = v_bid_id
            ) then
                raise exception 'applied_review_document_immutable';
            end if;
            return old;
        end if;
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


-- ── 2. Add ON DELETE CASCADE to procurement_update_review_documents.document_id ─
alter table public.procurement_update_review_documents
    drop constraint if exists procurement_update_review_documents_document_id_fkey;

alter table public.procurement_update_review_documents
    add constraint procurement_update_review_documents_document_id_fkey
    foreign key (document_id) references public.documents(id) on delete cascade;


-- ── 3. Add ON DELETE CASCADE to procurement_changes.source_document_id ────────
alter table public.procurement_changes
    drop constraint if exists procurement_changes_source_document_id_fkey;

alter table public.procurement_changes
    add constraint procurement_changes_source_document_id_fkey
    foreign key (source_document_id) references public.documents(id) on delete cascade;


-- ── 4. Add ON DELETE SET NULL to procurement_conflicts.target_requirement_id ──
alter table public.procurement_conflicts
    drop constraint if exists procurement_conflicts_target_requirement_id_fkey;

alter table public.procurement_conflicts
    add constraint procurement_conflicts_target_requirement_id_fkey
    foreign key (target_requirement_id) references public.requirements(id) on delete set null;


-- ── 5. Add ON DELETE SET NULL to procurement_changes.target_requirement_id ────
alter table public.procurement_changes
    drop constraint if exists procurement_changes_target_requirement_id_fkey;

alter table public.procurement_changes
    add constraint procurement_changes_target_requirement_id_fkey
    foreign key (target_requirement_id) references public.requirements(id) on delete set null;
