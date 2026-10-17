-- Migration 028: Restrict Data API reads of internal analysis result payloads
--
-- Forward-only privilege remediation. Migration 008 deliberately relied on
-- table-level SELECT plus RLS for analysis_results. That is insufficient once
-- fast_analysis_result_snapshot contains captured raw source text: RLS limits
-- rows, but does not hide the column from a member who can see the row.
--
-- This migration changes no rows, RLS policy, function, view, trigger, or
-- service_role privilege. It removes only anon/authenticated table SELECT and
-- restores the exact authenticated projection used by tenancy.py:
-- id, run_id, bid_id, structured_intelligence, fact_origins,
-- report_content_snapshot.
--
-- fast_analysis_result_snapshot, full_analysis_result, check_coverage_result,
-- and created_at deliberately receive no anon/authenticated grant. They remain
-- available to the trusted service_role client and SECURITY DEFINER database
-- functions that already own their controlled server-side workflows.
--
-- Apply manually through the Supabase dashboard only after review. This file
-- is not applied by application code and must never be executed against
-- production without separate authorization.

revoke select on table public.analysis_results from anon, authenticated;

-- Table-level revocation is sufficient for the currently installed ACL, but
-- revoke the internal columns explicitly as well so an unexpected prior
-- column-level grant cannot survive this remediation.
revoke select (
    fast_analysis_result_snapshot,
    full_analysis_result,
    check_coverage_result,
    created_at
) on table public.analysis_results from anon, authenticated;

grant select (
    id,
    run_id,
    bid_id,
    structured_intelligence,
    fact_origins,
    report_content_snapshot
) on table public.analysis_results to authenticated;
