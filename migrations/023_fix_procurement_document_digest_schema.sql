-- ===========================================================================
-- Migration 023: Fix procurement document digest pgcrypto schema qualification
-- ===========================================================================
-- In Supabase, the pgcrypto extension is installed in the `extensions` schema.
-- Because compute_procurement_document_set_digest enforces a hardened
-- `search_path = public, pg_temp` (SECURITY DEFINER safety), unqualified
-- calls to digest() fail with:
--   function digest(text, unknown) does not exist (code 42883)
--
-- This migration recreates ONLY compute_procurement_document_set_digest,
-- explicitly qualifying calls as `extensions.digest(...)` while preserving
-- identical semantics, search_path, stability, and permissions.
-- ===========================================================================

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
        return encode(extensions.digest(
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

    return encode(extensions.digest(p_review_kind || ':' || coalesce(v_combined, ''), 'sha256'), 'hex');
end;
$$;

revoke all on function public.compute_procurement_document_set_digest(text, bigint[], text[], text[], bigint, integer) from public;
revoke execute on function public.compute_procurement_document_set_digest(text, bigint[], text[], text[], bigint, integer) from anon;
revoke execute on function public.compute_procurement_document_set_digest(text, bigint[], text[], text[], bigint, integer) from authenticated;
grant execute on function public.compute_procurement_document_set_digest(text, bigint[], text[], text[], bigint, integer) to service_role;
