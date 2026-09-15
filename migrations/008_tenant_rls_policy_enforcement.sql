-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 008: Tenant RLS policy enforcement — Phase 8 remediation
-- package 3
-- ═══════════════════════════════════════════════════════════════════════════
-- Policy/function only. Does not touch migrations 001-007, does not drop
-- or alter any table's columns, does not delete or modify any row, does
-- not change any GRANT (Supabase's default GRANTs already cover `anon`
-- and `authenticated` on every table here -- RLS, not table-level GRANT,
-- is this project's enforcement layer; confirmed live via
-- information_schema.role_table_grants before writing this file). No
-- policy in this file is ever created `to anon` -- every single policy
-- below is scoped `to authenticated` explicitly. No policy uses an
-- unconditional `using (true)`.
--
-- Core rule (instruction 2): an authenticated user may access a bid only
-- when they are a member of the organization that owns that bid.
-- Downstream bid-owned tables inherit this transitively through their own
-- existing `bid_id` foreign key -- no `organization_id` column is added
-- to any of them here (none needed; see
-- BID_INTELLIGENCE_PHASE8_AUTH_TENANCY_FOUNDATION.md's dependency map).
--
-- ── Helper functions ─────────────────────────────────────────────────────
-- Two small, narrowly-scoped SECURITY DEFINER functions used by every
-- policy below, instead of repeating the same 2-3-level join inline in
-- ten-plus CREATE POLICY statements. This project's specific schema has
-- NO recursive-policy risk to avoid (organization_members' own policy
-- checks only its own `user_id` column and queries no other table, so
-- nothing here could ever recurse) -- these functions exist for
-- single-source-of-truth/maintainability instead, the same discipline
-- already applied elsewhere in this codebase
-- (database.py:_resolve_legacy_organization_id, fast_analysis's shared
-- _is_substantive_evaluation_row predicate). Each function:
--   * is STABLE (no side effects; safe for the planner to treat as
--     constant within one statement),
--   * is SECURITY DEFINER with an explicit, fixed `search_path` (prevents
--     search_path hijacking -- the classic reason this pattern is unsafe
--     when done carelessly),
--   * returns ONLY a boolean, never row data -- it cannot be used to
--     exfiltrate anything beyond "yes/no, can this caller access this
--     one id",
--   * takes one scalar id argument, not arbitrary SQL or a table/column
--     name,
--   * is executable only by `authenticated` (revoked from the PUBLIC
--     pseudo-role AND explicitly from `anon` -- Supabase grants EXECUTE
--     on every newly-created function to `anon`/`authenticated`/
--     `service_role` directly by default, independent of the PUBLIC
--     grant, so `revoke ... from public` alone does not remove `anon`'s
--     access; this was confirmed live immediately after first applying
--     this migration and corrected in the same migration file below.
--     Note this is not a data-exposure gap even before the explicit
--     revoke: both functions key off auth.uid(), which is NULL for an
--     unauthenticated `anon` caller, so every membership/access check
--     already evaluates to false for `anon` regardless -- the explicit
--     revoke closes the access path itself, as defense in depth, rather
--     than fixing an actual leak).

create or replace function public.is_organization_member(target_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
        from public.organization_members m
        where m.organization_id = target_organization_id
          and m.user_id = auth.uid()
    );
$$;

revoke all on function public.is_organization_member(uuid) from public;
revoke execute on function public.is_organization_member(uuid) from anon;
grant execute on function public.is_organization_member(uuid) to authenticated;

create or replace function public.can_access_bid(target_bid_id bigint)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
        from public.bids b
        where b.id = target_bid_id
          and public.is_organization_member(b.organization_id)
    );
$$;

revoke all on function public.can_access_bid(bigint) from public;
revoke execute on function public.can_access_bid(bigint) from anon;
grant execute on function public.can_access_bid(bigint) to authenticated;

-- ── organizations: SELECT own membership's organization only ────────────
-- Creation/deletion/admin mutation remains server-only (instruction 6) --
-- no insert/update/delete policy is created here.
create policy organizations_select_own_membership
    on public.organizations for select
    to authenticated
    using (public.is_organization_member(id));

-- ── organization_members: SELECT own rows only ───────────────────────────
-- Deliberately the smaller exposure (instruction 7): a user can see their
-- own membership rows (enough to resolve their own AuthContext) but
-- cannot enumerate who else belongs to their organization. Membership
-- creation/removal remains server/admin controlled -- no insert/update/
-- delete policy is created here.
create policy organization_members_select_own_rows
    on public.organization_members for select
    to authenticated
    using (user_id = auth.uid());

-- ── bids: full member CRUD except DELETE ─────────────────────────────────
-- DELETE is deliberately left server-only: it cascades to every
-- downstream bid-owned table (documents, requirements, analysis_runs,
-- analysis_results, bid_briefs, bid_decisions, and more, all
-- ON DELETE CASCADE per migration 004's/the original schema's own FKs),
-- making it the single highest-blast-radius destructive action in this
-- schema -- instruction 8 explicitly allows leaving it server-only when
-- normal-member self-service hard-delete is not clearly required, and
-- the risk asymmetry here (one click cascades away an entire bid's
-- history) makes that the least-privilege choice.
create policy bids_select_org_member
    on public.bids for select to authenticated
    using (public.is_organization_member(organization_id));

create policy bids_insert_org_member
    on public.bids for insert to authenticated
    with check (public.is_organization_member(organization_id));

-- The USING clause gates which existing rows may be targeted (must
-- already belong to one of the caller's organizations); the WITH CHECK
-- clause gates the proposed NEW row (the organization_id being written
-- must also be one of the caller's organizations) -- together these are
-- exactly what prevents a member from reassigning a bid's
-- organization_id to an organization they do not belong to (instruction
-- 8's explicit requirement), using Postgres's own standard RLS idiom
-- rather than a bespoke trigger.
create policy bids_update_org_member
    on public.bids for update to authenticated
    using (public.is_organization_member(organization_id))
    with check (public.is_organization_member(organization_id));

-- ── Bid-owned tables: full member CRUD (category A) ──────────────────────
-- requirements, tasks, outline_sections, deliverables, clarifications:
-- real, existing, wired-up delete_*() UI actions (app.py/pages/*.py) for
-- every one of these today -- policies preserve that existing product
-- behavior, scoped to the caller's own organization's bids.
create policy requirements_select_bid_access on public.requirements for select to authenticated using (public.can_access_bid(bid_id));
create policy requirements_insert_bid_access on public.requirements for insert to authenticated with check (public.can_access_bid(bid_id));
create policy requirements_update_bid_access on public.requirements for update to authenticated using (public.can_access_bid(bid_id)) with check (public.can_access_bid(bid_id));
create policy requirements_delete_bid_access on public.requirements for delete to authenticated using (public.can_access_bid(bid_id));

create policy tasks_select_bid_access on public.tasks for select to authenticated using (public.can_access_bid(bid_id));
create policy tasks_insert_bid_access on public.tasks for insert to authenticated with check (public.can_access_bid(bid_id));
create policy tasks_update_bid_access on public.tasks for update to authenticated using (public.can_access_bid(bid_id)) with check (public.can_access_bid(bid_id));
create policy tasks_delete_bid_access on public.tasks for delete to authenticated using (public.can_access_bid(bid_id));

create policy outline_sections_select_bid_access on public.outline_sections for select to authenticated using (public.can_access_bid(bid_id));
create policy outline_sections_insert_bid_access on public.outline_sections for insert to authenticated with check (public.can_access_bid(bid_id));
create policy outline_sections_update_bid_access on public.outline_sections for update to authenticated using (public.can_access_bid(bid_id)) with check (public.can_access_bid(bid_id));
create policy outline_sections_delete_bid_access on public.outline_sections for delete to authenticated using (public.can_access_bid(bid_id));

create policy deliverables_select_bid_access on public.deliverables for select to authenticated using (public.can_access_bid(bid_id));
create policy deliverables_insert_bid_access on public.deliverables for insert to authenticated with check (public.can_access_bid(bid_id));
create policy deliverables_update_bid_access on public.deliverables for update to authenticated using (public.can_access_bid(bid_id)) with check (public.can_access_bid(bid_id));
create policy deliverables_delete_bid_access on public.deliverables for delete to authenticated using (public.can_access_bid(bid_id));

create policy clarifications_select_bid_access on public.clarifications for select to authenticated using (public.can_access_bid(bid_id));
create policy clarifications_insert_bid_access on public.clarifications for insert to authenticated with check (public.can_access_bid(bid_id));
create policy clarifications_update_bid_access on public.clarifications for update to authenticated using (public.can_access_bid(bid_id)) with check (public.can_access_bid(bid_id));
create policy clarifications_delete_bid_access on public.clarifications for delete to authenticated using (public.can_access_bid(bid_id));

-- debriefs: no delete_debrief() exists in the codebase -- select/insert/
-- update only, no delete policy (least privilege: never grant an
-- operation the product doesn't use).
create policy debriefs_select_bid_access on public.debriefs for select to authenticated using (public.can_access_bid(bid_id));
create policy debriefs_insert_bid_access on public.debriefs for insert to authenticated with check (public.can_access_bid(bid_id));
create policy debriefs_update_bid_access on public.debriefs for update to authenticated using (public.can_access_bid(bid_id)) with check (public.can_access_bid(bid_id));

-- bid_decisions: represents human pursuit decisions (instruction 9's own
-- expectation). save_bid_decision() only ever INSERTs (append-only history
-- by existing design, not a Package 3 choice) -- select/insert only, no
-- update/delete policy.
create policy bid_decisions_select_bid_access on public.bid_decisions for select to authenticated using (public.can_access_bid(bid_id));
create policy bid_decisions_insert_bid_access on public.bid_decisions for insert to authenticated with check (public.can_access_bid(bid_id));

-- content_library: bid-scoped rows follow the same full-CRUD pattern as
-- the other library-style tables above (delete_library_item() is a real,
-- wired-up UI action). Global (bid_id IS NULL) rows are a deliberately
-- UNRESOLVED product decision (does "global" mean "every organization" or
-- "this organization"?) -- left fail-closed to authenticated users rather
-- than guessed at here; every policy below explicitly requires
-- bid_id IS NOT NULL.
create policy content_library_select_bid_access on public.content_library for select to authenticated using (bid_id is not null and public.can_access_bid(bid_id));
create policy content_library_insert_bid_access on public.content_library for insert to authenticated with check (bid_id is not null and public.can_access_bid(bid_id));
create policy content_library_update_bid_access on public.content_library for update to authenticated using (bid_id is not null and public.can_access_bid(bid_id)) with check (bid_id is not null and public.can_access_bid(bid_id));
create policy content_library_delete_bid_access on public.content_library for delete to authenticated using (bid_id is not null and public.can_access_bid(bid_id));

-- ── Bid-owned tables: user READ / server WRITE (category B) ─────────────
-- documents: write path (including delete) intentionally remains
-- server-only in this package -- documents.storage_path/upload/delete
-- interacts with Supabase Storage via the SAME privileged client, and
-- Storage-specific authorization (signed URLs, bucket policy hardening)
-- is explicit Phase 8 remediation package 4 scope. Wiring a DB-level
-- write policy now, ahead of the matching Storage policy, would create a
-- half-secured, inconsistent state -- deferred deliberately, not an
-- oversight.
create policy documents_select_bid_access on public.documents for select to authenticated using (public.can_access_bid(bid_id));

-- document_versions has no bid_id of its own -- inherits one hop further
-- through documents.bid_id, read-only for the same reason as documents
-- above (it is only ever written by save_upload()'s internal
-- version-archiving step, never a direct user action).
create policy document_versions_select_bid_access on public.document_versions for select to authenticated
    using (document_id in (select id from public.documents where public.can_access_bid(bid_id)));

-- bid_briefs, analysis_runs, analysis_results: written exclusively by the
-- Fast Analysis background pipeline (analysis_service.py) under the
-- service-role client -- read-only for authenticated users. See
-- tenancy.py's new authorization-boundary functions (start_fast_analysis_
-- for_organization / get_report_for_organization) for how a user-
-- initiated request to CREATE one of these privileged rows is authorized
-- BEFORE the privileged write happens, at the application layer, not via
-- an authenticated INSERT policy on these tables (there is none).
create policy bid_briefs_select_bid_access on public.bid_briefs for select to authenticated using (public.can_access_bid(bid_id));
create policy analysis_runs_select_bid_access on public.analysis_runs for select to authenticated using (public.can_access_bid(bid_id));
create policy analysis_results_select_bid_access on public.analysis_results for select to authenticated using (public.can_access_bid(bid_id));

-- ── firm_profiles: organization-owned (category D) ───────────────────────
-- Uses firm_profiles.organization_id (added in migration 007) directly,
-- not can_access_bid() -- this table is not bid-scoped. No delete policy:
-- the current application never deletes the firm profile (get/save only).
create policy firm_profiles_select_org_member on public.firm_profiles for select to authenticated
    using (organization_id is not null and public.is_organization_member(organization_id));
create policy firm_profiles_insert_org_member on public.firm_profiles for insert to authenticated
    with check (organization_id is not null and public.is_organization_member(organization_id));
create policy firm_profiles_update_org_member on public.firm_profiles for update to authenticated
    using (organization_id is not null and public.is_organization_member(organization_id))
    with check (organization_id is not null and public.is_organization_member(organization_id));

-- ── Server-only tables (category C): explicitly untouched ───────────────
-- `coaches` has no bid_id and no organization_id -- it cannot be
-- correctly tenant-scoped without a schema change, which is out of this
-- policy-only migration's scope (instruction 5). It already has RLS
-- enabled with zero policies (confirmed live, unrelated to this
-- migration) and this migration deliberately adds none -- it remains
-- fail-closed to every authenticated user, which is the correct,
-- intentional state until a later package makes an explicit product
-- decision about whether the coach roster is organization-scoped or
-- genuinely firm-wide-global.
