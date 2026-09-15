-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 009: coaches organization tenancy — Phase 8 remediation
-- package 3, coaches follow-up
-- ═══════════════════════════════════════════════════════════════════════════
-- Does not touch migrations 001-008. Additive-and-backfill only, following
-- the exact same nullable -> backfill -> NOT NULL pattern migration 007
-- already used for bids.organization_id, plus the same organization-scoped
-- RLS pattern migration 008 already used for firm_profiles.
--
-- ── Why this migration exists ────────────────────────────────────────────
-- Migration 008 deliberately left `coaches` untouched (see its own closing
-- comment: "it remains fail-closed to every authenticated user, which is
-- the correct, intentional state until a later package makes an explicit
-- product decision about whether the coach roster is organization-scoped
-- or genuinely firm-wide-global"). That decision was made explicitly, not
-- assumed, by auditing the live schema and every reachable code path that
-- touches `coaches`:
--
--   1. Is `coaches` organization-owned team/personnel data?  YES.
--      Its columns are name, credentials, icf_level, sectors, languages,
--      location, availability, email, phone, cv_summary,
--      reference_contact, notes -- real personal contact information
--      (email, phone) and a client reference contact for a named
--      individual, not abstract reference values. The 4 live rows are
--      real coach/assessor personnel with named credentials (ICF PCC,
--      BPS-certified assessor, etc.), populated by the application's own
--      "Proposal Analyzer" feature (pages_extra.py's coaches_found
--      auto-population, extracted from a firm's OWN past proposal
--      documents -- see page_proposal_analyzer()/page_team_roster()) --
--      i.e. this is one firm's own personnel roster, assembled from that
--      firm's own submitted work, not a shared industry directory anyone
--      contributed to or should see.
--   2. Is it genuinely platform-global reference data?  NO. There is no
--      sense in which "Mina Wasfi, ICF PCC, reachable at
--      <redacted email/phone>" is a fact true for every tenant on this
--      platform the way e.g. a list of ICF certification levels would
--      be. Exposing another organization's coach roster -- names, direct
--      contact details, CVs, client references -- to a different
--      organization's signed-in members would be a real, ordinary
--      information-disclosure vulnerability, not a hypothetical one.
--   3. Which reachable UI operations read/write it?  pages_extra.py's
--      page_team_roster() (the only reachable page whose entire purpose
--      is this table: full CRUD -- list, add via `st.form("add_coach")`,
--      edit via `st.form("edit_coach")`, and a real, wired
--      `delete_coach(eid)` call) and pages_extra.py's page_exec_dashboard()
--      (read-only roster summary counts + a name badge list + the PDF
--      export). page_proposal_analyzer() also reads/writes coaches, but
--      is confirmed dead code (zero call sites outside its own def line,
--      per the same repo-wide search method used throughout this
--      engagement) -- not a live interactive surface, not addressed by
--      this migration's RLS policies beyond simply existing consistently.
--
-- Conclusion: organization-owned. This migration completes the tenancy
-- model for `coaches` the same way migration 007 did for `firm_profiles`.
--
-- ── 1. coaches.organization_id (added nullable; made NOT NULL below, ────
--       only after every existing row is confirmed backfilled)
alter table public.coaches
    add column if not exists organization_id uuid references public.organizations(id);

create index if not exists idx_coaches_organization
    on public.coaches (organization_id);

-- ── 2. deterministic backfill -- no UUID hardcoded, resolved through the ──
--       same unique, deterministic slug migration 007 established. Safe
--       to re-run: only rows still NULL are touched.
update public.coaches
set organization_id = (select id from public.organizations where slug = 'emg-internal')
where organization_id is null;

-- ── 3. make ownership mandatory, but only if the backfill above actually ──
--       reached every row -- aborts (and rolls back) the whole migration
--       rather than silently leaving an orphaned coach row.
do $$
declare
    orphaned_count bigint;
begin
    select count(*) into orphaned_count from public.coaches where organization_id is null;
    if orphaned_count > 0 then
        raise exception
            'Migration 009 aborted: % coach row(s) still have a NULL organization_id after backfill -- not making the column NOT NULL',
            orphaned_count;
    end if;
end $$;

alter table public.coaches
    alter column organization_id set not null;

-- ── 4. RLS policies -- same auth.uid() -> organization_members -> ────────
--       organizations model established in migration 008, reusing its
--       existing is_organization_member(uuid) helper verbatim (no new
--       function needed; coaches is organization-scoped exactly like
--       firm_profiles, not bid-scoped, so can_access_bid() does not
--       apply here). RLS was already enabled on this table (migration
--       006/pre-existing state, confirmed live, zero policies existed
--       before this migration) -- this migration only adds the policies
--       themselves, it does not re-enable RLS.
--
--       Full CRUD, matching firm_profiles' organization-scoped pattern
--       plus a DELETE policy (unlike firm_profiles, delete_coach() IS a
--       real, wired UI action in page_team_roster() today).
create policy coaches_select_org_member on public.coaches for select to authenticated
    using (public.is_organization_member(organization_id));
create policy coaches_insert_org_member on public.coaches for insert to authenticated
    with check (public.is_organization_member(organization_id));
create policy coaches_update_org_member on public.coaches for update to authenticated
    using (public.is_organization_member(organization_id))
    with check (public.is_organization_member(organization_id));
create policy coaches_delete_org_member on public.coaches for delete to authenticated
    using (public.is_organization_member(organization_id));
