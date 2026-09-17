-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 011: Harden Procurement Governance Trigger Functions
-- ═══════════════════════════════════════════════════════════════════════════
-- Does not touch migration 010 or any earlier migration. Grant-only: no
-- table, column, index, constraint, or trigger is added/dropped/altered,
-- no trigger logic/semantics change, and no application data is mutated.
--
-- ── Why this migration exists ────────────────────────────────────────────
-- Migration 010's live verification (post-apply security advisor pass)
-- flagged all four of its BEFORE UPDATE OR DELETE trigger functions --
--   prevent_applied_change_mutation
--   prevent_applied_review_mutation
--   prevent_applied_review_document_mutation
--   prevent_resolved_conflict_mutation
-- -- as "SECURITY DEFINER function callable by anon/authenticated via
-- /rest/v1/rpc/<name>". Migration 010 explicitly REVOKE/GRANT'd EXECUTE on
-- its six application-facing RPCs (compute_procurement_document_set_digest,
-- create_procurement_update_review, record_change_review_decision,
-- refresh_bid_brief_projection, apply_procurement_update_review,
-- resolve_procurement_conflict) but never did the same for these four
-- trigger functions -- they were left at PostgreSQL's default behavior,
-- which grants EXECUTE on every newly created function to PUBLIC.
--
-- ── Investigation (instruction 1) ────────────────────────────────────────
-- All four are `security definer`, matching the other governance functions.
-- All four ALREADY have `set search_path = public, pg_temp` fixed inline in
-- their migration-010 definitions -- no search_path hardening is missing or
-- performed here. Only one of the four, prevent_applied_review_document_
-- mutation, even reads a table, and it already does so fully qualified
-- (`public.procurement_update_reviews`) -- no unqualified relation name in
-- any of the four. None has, or should ever have, a legitimate direct-
-- invocation use case: each references OLD/NEW/TG_OP, which PL/pgSQL binds
-- only during real trigger execution -- calling any of them as an ordinary
-- function (exactly what a PostgREST RPC call would do) fails at runtime
-- rather than doing anything, governed or otherwise. Expected answer
-- confirmed: these are internal trigger functions only and were never
-- intended to be application RPCs.
--
-- ── service_role EXECUTE decision (instruction 2) ────────────────────────
-- Per PostgreSQL's own documentation (CREATE TRIGGER, "Notes"): "To create
-- or replace a trigger on a table, the user must ... have EXECUTE privilege
-- on the trigger function." This EXECUTE check happens ONCE, at CREATE
-- TRIGGER time, against the role that creates the trigger (`postgres`, at
-- migration-010-apply time) -- it is never re-checked against whatever role
-- later performs the INSERT/UPDATE/DELETE that fires the trigger; trigger
-- firing is carried out by the executor directly, not as an ordinary
-- privileged function call. Revoking EXECUTE from every role -- including
-- service_role, which never calls these functions directly either, only
-- ever triggers them indirectly via DML on the governed tables -- therefore
-- cannot break any of the four triggers migration 010 already created.
-- service_role's EXECUTE on the six SEPARATE application RPCs (granted by
-- migration 010) is entirely unaffected by this migration.
-- ═══════════════════════════════════════════════════════════════════════════

revoke all on function public.prevent_applied_change_mutation() from public;
revoke all on function public.prevent_applied_change_mutation() from anon;
revoke all on function public.prevent_applied_change_mutation() from authenticated;
revoke all on function public.prevent_applied_change_mutation() from service_role;

revoke all on function public.prevent_applied_review_mutation() from public;
revoke all on function public.prevent_applied_review_mutation() from anon;
revoke all on function public.prevent_applied_review_mutation() from authenticated;
revoke all on function public.prevent_applied_review_mutation() from service_role;

revoke all on function public.prevent_applied_review_document_mutation() from public;
revoke all on function public.prevent_applied_review_document_mutation() from anon;
revoke all on function public.prevent_applied_review_document_mutation() from authenticated;
revoke all on function public.prevent_applied_review_document_mutation() from service_role;

revoke all on function public.prevent_resolved_conflict_mutation() from public;
revoke all on function public.prevent_resolved_conflict_mutation() from anon;
revoke all on function public.prevent_resolved_conflict_mutation() from authenticated;
revoke all on function public.prevent_resolved_conflict_mutation() from service_role;
