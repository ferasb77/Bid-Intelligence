-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 019: Section Draft Claim Mappings — PI-3C claim-level traceability
-- ═══════════════════════════════════════════════════════════════════════════
-- Additive only. Does not modify migrations 001-018 except a single
-- backward-compatible ADD COLUMN on section_drafts (migration 018); does
-- not touch any bid/requirements/proposal_intelligence/organizational_
-- memory/requirement_evidence_enrichments table or column, does not
-- backfill (existing rows simply get the column's own default, '[]'::jsonb
-- -- "no material-claim mapping was computed for this older draft", never
-- fabricated), does not change any existing RLS policy or GRANT.
--
-- Per this repo's established convention (migrations 004-018), this file is
-- NOT auto-applied by any code path and is NOT executed as part of this
-- authorization. Apply it manually via the Supabase SQL editor / dashboard,
-- after separate review, exactly the way migrations 004-018 were applied.
-- Live commissioning of this migration is an explicitly separate, later
-- task (PI-3B's own migration 018 is already live-commissioned; this
-- migration is not). Migration 013 (Section Analyzer) remains unapplied
-- and is not a dependency of this one.
--
-- ── Deliberate two-step rollout (avoids breaking a LIVE feature) ───────────
-- migration 018's get_or_create_section_draft() RPC is already live and
-- already used by production code (tenancy.get_or_generate_section_draft).
-- Unlike every prior migration in this series, this one modifies an
-- ALREADY-WORKING live RPC's signature rather than introducing a brand
-- new one -- so database.get_or_create_section_draft() and tenancy.
-- get_or_generate_section_draft() were DELIBERATELY NOT wired to pass
-- `material_claims`/`p_material_claims` in the same change that wrote this
-- migration file: doing so would make every live call to the CURRENT
-- (migration-018-only) RPC fail with a "no matching function" error the
-- moment this code ships, entirely independent of whether this migration
-- itself is ever applied. section_drafting.py's MaterialClaim/
-- SectionDraftResult.material_claims are fully implemented and tested
-- (the EPHEMERAL, non-persisted PI-3A response already carries them), and
-- this migration is fully written and ready -- but the ONE remaining step
-- (adding `p_material_claims` back into database.get_or_create_section_
-- draft's RPC call and `material_claims=...` into tenancy.
-- get_or_generate_section_draft's persistence call) must ship IN THE SAME
-- commissioning task that applies this migration, never ahead of it.
--
-- ── Why an additive column, not a new table (instruction 8) ────────────────
-- PI-3B's live-commissioned `section_drafts` table already exists as the
-- durable home for section_drafting.SectionDraftResult. PI-3C's
-- `material_claims` (section_drafting.MaterialClaim -- claim_id/claim_text/
-- claim_type/evidence_ids/support_status, see that module) is a NEW field
-- ON THAT SAME RESULT, produced by the SAME drafting call, at the SAME
-- point in the SAME lifecycle -- it is not a new derived artifact with its
-- own independent identity or freshness lifecycle the way
-- requirement_evidence_enrichments (a genuinely separate OM-3B artifact)
-- or section_drafts itself (a genuinely separate PI-3B artifact) were.
-- Introducing a second table here would fragment ONE result across two
-- rows for no benefit -- there is no scenario where material_claims exists
-- without draft_text or vice versa; they share one identity, one
-- fingerprint, and one immutable row. A single `jsonb not null default
-- '[]'::jsonb` column, exactly like every other structured PI-3A/PI-3B
-- result field already on this table (evidence_items_used,
-- contradictions_or_caveats, etc.), is the correct and minimal
-- representation -- backward-compatible by construction (existing rows
-- get an empty array, read as "not computed," never as "computed and
-- found zero material claims" -- callers reading old rows should not
-- conflate the two, though this migration does not attempt to distinguish
-- them structurally since PI-3C is opt-in additive, not retroactive).
--
-- ── Fail-closed claim-evidence traceability (instruction 7) ─────────────────
-- Every claim's `evidence_ids` were ALREADY fail-closed filtered against
-- the SAME bounded evidence-id registry evidence_items_used is filtered
-- against (section_drafting._evidence_id_registry) before this column is
-- ever written -- an invented id can never appear here, by construction of
-- section_drafting._reconcile_material_claims (Python-side, this migration
-- adds no NEW database-level validation of evidence_ids' contents beyond
-- storing whatever Python already fail-closed reconciled, exactly matching
-- how evidence_items_used/organizational_evidence already work on this
-- table and requirement_evidence_enrichments respectively -- validation
-- lives in the application layer that CONSTRUCTS the structured result,
-- not re-derived in SQL).
--
-- ── RLS / write boundary: unchanged ─────────────────────────────────────────
-- No RLS policy change -- the existing `section_drafts_select_bid_access`
-- policy (authenticated SELECT via can_access_bid) already covers this new
-- column transparently (SELECT * already returns it). The write boundary
-- (service_role only, via get_or_create_section_draft()) is unchanged in
-- kind; the function itself is replaced below ONLY to add the new
-- parameter -- dropped and recreated (not a bare CREATE OR REPLACE) so the
-- RPC's identity is genuinely extended, not left as an ambiguous duplicate
-- overload alongside migration 018's original 18-argument signature.
-- ═══════════════════════════════════════════════════════════════════════════

alter table section_drafts
    add column if not exists material_claims jsonb not null default '[]'::jsonb;

drop function if exists public.get_or_create_section_draft(
    bigint, text, text, text, text, boolean, bigint, jsonb, jsonb, jsonb, jsonb,
    jsonb, jsonb, boolean, text, integer, jsonb, uuid
);

create or replace function public.get_or_create_section_draft(
    p_bid_id bigint,
    p_req_id text,
    p_input_fingerprint text,
    p_contract_version text,
    p_draft_text text,
    p_assurance_passed boolean,
    p_requirement_id bigint default null,
    p_requirements_addressed jsonb default '[]'::jsonb,
    p_requirements_missing jsonb default '[]'::jsonb,
    p_evaluation_criteria_addressed jsonb default '[]'::jsonb,
    p_evidence_items_used jsonb default '[]'::jsonb,
    p_unsupported_or_unresolved_points jsonb default '[]'::jsonb,
    p_contradictions_or_caveats jsonb default '[]'::jsonb,
    p_human_confirmation_required boolean default true,
    p_drafting_notes text default null,
    p_word_count integer default null,
    p_assurance_issues jsonb default '[]'::jsonb,
    p_material_claims jsonb default '[]'::jsonb,
    p_created_by_user_id uuid default null
) returns public.section_drafts
language plpgsql
security definer
set search_path = public
as $$
declare
    v_row public.section_drafts;
begin
    if p_bid_id is null or p_req_id is null or p_input_fingerprint is null then
        raise exception 'get_or_create_section_draft: bid_id, req_id, and input_fingerprint are required';
    end if;
    if p_contract_version is null then
        raise exception 'get_or_create_section_draft: contract_version is required';
    end if;
    if p_draft_text is null or length(trim(p_draft_text)) = 0 then
        raise exception 'get_or_create_section_draft: draft_text must be non-empty -- a failed/empty draft must never be persisted';
    end if;
    if p_assurance_passed is null then
        raise exception 'get_or_create_section_draft: assurance_passed is required';
    end if;

    -- Concurrency-safe get-or-create, unchanged from migration 018.
    perform pg_advisory_xact_lock(hashtext('section_draft:' || p_bid_id::text || ':' || p_req_id));

    select * into v_row
    from public.section_drafts
    where bid_id = p_bid_id and req_id = p_req_id and input_fingerprint = p_input_fingerprint;

    if found then
        return v_row;
    end if;

    insert into public.section_drafts (
        bid_id, requirement_id, req_id, contract_version, input_fingerprint,
        draft_text, requirements_addressed, requirements_missing,
        evaluation_criteria_addressed, evidence_items_used,
        unsupported_or_unresolved_points, contradictions_or_caveats,
        human_confirmation_required, drafting_notes, word_count,
        assurance_passed, assurance_issues, material_claims, created_by_user_id
    ) values (
        p_bid_id, p_requirement_id, p_req_id, p_contract_version, p_input_fingerprint,
        p_draft_text, coalesce(p_requirements_addressed, '[]'::jsonb),
        coalesce(p_requirements_missing, '[]'::jsonb),
        coalesce(p_evaluation_criteria_addressed, '[]'::jsonb),
        coalesce(p_evidence_items_used, '[]'::jsonb),
        coalesce(p_unsupported_or_unresolved_points, '[]'::jsonb),
        coalesce(p_contradictions_or_caveats, '[]'::jsonb),
        coalesce(p_human_confirmation_required, true), p_drafting_notes, p_word_count,
        p_assurance_passed, coalesce(p_assurance_issues, '[]'::jsonb),
        coalesce(p_material_claims, '[]'::jsonb), p_created_by_user_id
    ) returning * into v_row;

    return v_row;
end;
$$;

revoke all on function public.get_or_create_section_draft(
    bigint, text, text, text, text, boolean, bigint, jsonb, jsonb, jsonb, jsonb,
    jsonb, jsonb, boolean, text, integer, jsonb, jsonb, uuid
) from public;
revoke all on function public.get_or_create_section_draft(
    bigint, text, text, text, text, boolean, bigint, jsonb, jsonb, jsonb, jsonb,
    jsonb, jsonb, boolean, text, integer, jsonb, jsonb, uuid
) from anon, authenticated;
grant execute on function public.get_or_create_section_draft(
    bigint, text, text, text, text, boolean, bigint, jsonb, jsonb, jsonb, jsonb,
    jsonb, jsonb, boolean, text, integer, jsonb, jsonb, uuid
) to service_role;
