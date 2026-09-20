# Bid Intelligence — Phase 8 Remediation Package 2: Authentication & Tenancy Foundation

**Date:** 2026-09-15 (UTC)
**Status:** `AUTHENTICATION/TENANCY FOUNDATION PRESENT — AUTHORIZATION ENFORCEMENT PENDING`
**Scope:** Establish the minimum `Authenticated User → Organization Membership → Organization → Bid` schema and identity contract. No RLS policies, no enforced authentication, no live auth users. Package 3 closes the authorization gap.
**Baseline going in:** commit `f6a6d25d9d906a44c378ff465afbedfb54cfe158` / package 1 (`006_close_open_rls_tables`) applied, regression baseline `1529 passed, 2 skipped`.
**Live project:** `whonalbdpbubaqhpzrnw`.

---

## 1. Pre-Implementation Audit

**`bids` FK dependency map** (confirmed live via `information_schema.table_constraints`/`key_column_usage`/`constraint_column_usage`/`referential_constraints` — not assumed from code alone):

| Child table | FK column | On delete | Inherits tenancy via `bid_id`? |
|---|---|---|---|
| `analysis_results` | `bid_id` → `bids.id` | CASCADE | Yes |
| `analysis_runs` | `bid_id` → `bids.id` | CASCADE | Yes |
| `bid_briefs` | `bid_id` → `bids.id` | CASCADE | Yes |
| `bid_decisions` | `bid_id` → `bids.id` | CASCADE | Yes |
| `clarifications` | `bid_id` → `bids.id` | CASCADE | Yes |
| `content_library` | `bid_id` → `bids.id` | SET NULL (nullable) | Yes when set; `bid_id IS NULL` rows are deliberately global library items — a policy decision left to package 3, not resolved here |
| `debriefs` | `bid_id` → `bids.id` | CASCADE | Yes |
| `deliverables` | `bid_id` → `bids.id` | CASCADE | Yes |
| `documents` | `bid_id` → `bids.id` | CASCADE | Yes |
| `outline_sections` | `bid_id` → `bids.id` | CASCADE | Yes |
| `requirements` | `bid_id` → `bids.id` | CASCADE | Yes |
| `tasks` | `bid_id` → `bids.id` | CASCADE | Yes |
| `document_versions` | `document_id` → `documents.id` | CASCADE | Yes, one hop further (via `documents.bid_id`) |

**Tables that cannot inherit via `bid_id` (no such column exists):**

| Table | Why | Decision this package |
|---|---|---|
| `firm_profiles` | Not bid-scoped by design — a single global capability profile (`.limit(1)` singleton, confirmed in `database.py:get_firm_profile()`) | Addressed explicitly — see §14: organization-owned, `organization_id` added |
| `coaches` | A firm-wide roster with no `bid_id` at all | **Not addressed in this package.** No `organization_id` added — adding one wasn't asked for in this package's explicit scope (§13's inheritance-check list names `documents, requirements, bid_briefs, bid_decisions, analysis_runs, analysis_results` specifically) and `coaches` genuinely cannot inherit via `bid_id` since it has none. Flagged here as a real, open gap for whichever later package decides whether a firm's coach roster should be organization-scoped. |

Conclusion: **12 of 13 downstream tables inherit tenant access through their existing `bid_id` FK with zero redundant `organization_id` columns needed** — exactly the design instruction 1/13 asked for. Only `firm_profiles` needed its own column (§14), and `coaches` is identified but deliberately left untouched.

**Database access functions, Streamlit session handling, client construction, existing user/profile concepts** — all previously inspected in the Phase 8 production-readiness audit and re-confirmed unchanged immediately before this package began: exactly one Supabase client construction site (`database.py:get_client()`, service-role only); no session identity anywhere in `app.py`/`pages/*.py`; `auth.users` provisioned but empty (0 rows, re-confirmed live both before and after this package).

## 2. Selected Authentication Approach

**Supabase Auth** (Option A from the Phase 8 audit's own recommendation) — already provisioned on this exact project, requires no new vendor relationship, and pairs natively with `auth.uid()`-based RLS policies once package 3 writes them. No other identity provider is introduced. The architecture (separate anon-key auth client, `organization_members.user_id → auth.users(id)`) does not preclude adding enterprise SSO later — Supabase Auth itself supports SAML/OIDC on top of the same `auth.users` table, so a future upgrade would not require re-deriving this schema.

## 3. Tenancy Schema (migration 007)

```sql
create table if not exists public.organizations (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    slug        text not null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    constraint organizations_slug_unique unique (slug)
);

create table if not exists public.organization_members (
    organization_id uuid not null references public.organizations(id) on delete cascade,
    user_id         uuid not null references auth.users(id) on delete cascade,
    role            text not null default 'member'
                    check (role in ('owner', 'admin', 'member')),
    created_at      timestamptz not null default now(),
    primary key (organization_id, user_id)
);

create index if not exists idx_organization_members_user on public.organization_members (user_id);

alter table public.bids add column if not exists organization_id uuid references public.organizations(id);
create index if not exists idx_bids_organization on public.bids (organization_id);
```

No permission framework beyond the three roles (`owner`/`admin`/`member`) — nothing finer was justified by anything in this codebase.

## 4. Legacy Data Migration & Backfill Strategy

- One legacy organization, `name = 'Enable My Growth Internal'`, `slug = 'emg-internal'`, created via `INSERT ... ON CONFLICT (slug) DO NOTHING` — **no UUID is hardcoded anywhere**; every later reference resolves the organization by its unique slug.
- Backfill: `UPDATE bids SET organization_id = (SELECT id FROM organizations WHERE slug = 'emg-internal') WHERE organization_id IS NULL` — idempotent (only touches still-NULL rows), safely rerunnable.
- Guard: a `DO $$ ... RAISE EXCEPTION ... $$` block counts any bid still NULL after the backfill and aborts the entire migration (rolling back everything in the same script) rather than silently proceeding — `ALTER TABLE bids ALTER COLUMN organization_id SET NOT NULL` only runs if the guard passes.
- Result, live-verified: all 4 existing bids (ids 1, 3, 8, 81) now belong to the single `emg-internal` organization (UUID `4326b564-8cc5-4463-9304-9a589f08cc91`, Postgres-generated).

## 5. Migration 007 — Full Contents

Applied via Supabase's tracked migration mechanism (`apply_migration`), not a one-off `execute_sql`. Migrations 001–006 were not re-run and are unmodified (confirmed via `git status --porcelain` on each file, empty).

```sql
-- (full text also at migrations/007_auth_tenancy_foundation.sql)

create table if not exists public.organizations (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    slug        text not null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    constraint organizations_slug_unique unique (slug)
);

create table if not exists public.organization_members (
    organization_id uuid not null references public.organizations(id) on delete cascade,
    user_id         uuid not null references auth.users(id) on delete cascade,
    role            text not null default 'member'
                    check (role in ('owner', 'admin', 'member')),
    created_at      timestamptz not null default now(),
    primary key (organization_id, user_id)
);

create index if not exists idx_organization_members_user
    on public.organization_members (user_id);

alter table public.bids
    add column if not exists organization_id uuid references public.organizations(id);

create index if not exists idx_bids_organization
    on public.bids (organization_id);

insert into public.organizations (name, slug)
values ('Enable My Growth Internal', 'emg-internal')
on conflict (slug) do nothing;

update public.bids
set organization_id = (select id from public.organizations where slug = 'emg-internal')
where organization_id is null;

do $$
declare
    orphaned_count bigint;
begin
    select count(*) into orphaned_count from public.bids where organization_id is null;
    if orphaned_count > 0 then
        raise exception
            'Migration 007 aborted: % bid(s) still have a NULL organization_id after backfill -- not making the column NOT NULL',
            orphaned_count;
    end if;
end $$;

alter table public.bids
    alter column organization_id set not null;

alter table public.firm_profiles
    add column if not exists organization_id uuid references public.organizations(id);

alter table public.analysis_runs
    add column if not exists created_by_user_id uuid references auth.users(id) on delete set null;

alter table public.organizations       enable row level security;
alter table public.organization_members enable row level security;
```

**Static review, performed before applying:** touches exactly 4 tables (`organizations` created, `organization_members` created, `bids`/`firm_profiles`/`analysis_runs` altered — additive columns only); no `DROP`; no `DELETE`/`TRUNCATE`; no `CREATE POLICY`; no `GRANT`/`REVOKE`; RLS enabled (not forced) on the two new tables only. Enforced by `tests/test_auth_tenancy.py::TestMigration007SchemaContract` (12 tests, static assertions on the migration file's own SQL text — see that file's module docstring for exactly what this class does and does not prove versus live verification below).

## 6. AuthContext Contract (`tenancy.py`)

```python
@dataclass(frozen=True)
class AuthContext:
    user_id: str
    email: str
    organization_id: str
    organization_name: str
    role: str
```

Plus two explicit non-success result types the resolver returns instead of ever guessing:

```python
@dataclass(frozen=True)
class NoOrganizationAccess:
    user_id: str

@dataclass(frozen=True)
class OrganizationSelectionRequired:
    user_id: str
    candidates: list[dict]   # [{"organization_id", "organization_name", "role"}, ...]
```

No code path in the current commissioned application calls into this yet — it exists, fully tested, ahead of the switch-over package 3 performs.

## 7. Organization Membership Resolution Behavior

`tenancy.resolve_organization_context(user_id, email)`:

| Case | Behavior | Verified by |
|---|---|---|
| Zero memberships | Returns `NoOrganizationAccess(user_id)` — fails closed, no default | `test_zero_memberships_fails_closed` |
| Exactly one membership | Returns a fully-populated `AuthContext` | `test_one_membership_resolves_to_auth_context` |
| Multiple memberships | Returns `OrganizationSelectionRequired(user_id, candidates=[...])` — never silently picks one; `candidates` carries exactly what a future selector UI needs (org id, name, role) | `test_multiple_memberships_do_not_silently_select` |

## 8. Tenant-Aware Database Primitives (`tenancy.py`)

Deliberately separate names from `database.py`'s existing `get_all_bids()`/`get_bid()`/`create_bid()` — those remain as unscoped compatibility wrappers the current commissioned internal app keeps using (§11 below) until package 3 switches the product over.

- `list_bids_for_organization(organization_id)` — the org-scoped equivalent of `get_all_bids()`, same req/task rollup.
- `get_bid_for_organization(bid_id, organization_id)` — a bid that exists but belongs to a *different* organization returns `None`, the same shape as "not found," so response shape cannot be used to probe for other organizations' bid IDs. Tested explicitly (`test_cross_organization_bid_lookup_rejected_at_application_boundary`).
- `create_bid_for_organization(data, organization_id)` — `organization_id` is a required, explicit argument with **no default**; raises `ValueError` if empty/`None` and never calls the database in that case (`test_create_bid_for_organization_requires_explicit_organization_id`). Never references the legacy `emg-internal` slug anywhere in its logic (`test_create_bid_for_organization_never_defaults_to_legacy_org`).

## 9. A Compatibility Gap Found and Fixed Mid-Package

**This is the one real defect this package surfaced, and it was fixed before any live migration was left in a broken state — disclosed here transparently rather than only in a diff.**

After applying migration 007, `bids.organization_id` became `NOT NULL` live. The full post-migration regression run then failed 4 live smoke tests in `tests/smoke/test_live_supabase_migration_003.py`, all with `null value in column "organization_id" of relation "bids" violates not-null constraint` — because `database.create_bid()` (the *existing*, already-commissioned bid-creation path the current internal app uses) had no knowledge of the new column and never set it. This is exactly the class of regression the package's own primary objective forbids ("current commissioned single-user application behavior must remain operational") — and exactly the situation instruction 11 anticipated an answer for: *"If a clearly named development-only compatibility path is necessary, make its status explicit and testable."*

**Fix:** `database.create_bid()` now resolves the legacy organization by its slug (never a hardcoded UUID — same discipline as the migration's own backfill) and attaches it, via a new, explicitly-named, fully-documented helper:

```python
_LEGACY_ORGANIZATION_SLUG = "emg-internal"

def _resolve_legacy_organization_id(sb):
    """PRE-AUTH DEVELOPMENT-ONLY COMPATIBILITY PATH ..."""
    row = _one(sb.table("organizations").select("id").eq("slug", _LEGACY_ORGANIZATION_SLUG).execute())
    return row["id"] if row else None
```

This is **not** the same thing instruction 12 forbids for the *new* tenant-aware primitive (`tenancy.create_bid_for_organization()` never defaults, full stop) — it is a named, documented, tested compatibility default scoped strictly to the pre-existing, pre-auth `database.create_bid()` path, which package 3 will retire once real authenticated bid creation exists. Verified:

- `tests/test_database.py::TestCreateBidUnchanged` (3 tests): the payload now includes the resolved `organization_id`; the lookup uses the slug, never a literal UUID; and if the legacy org cannot be resolved for any reason, `create_bid()` degrades to its pre-package-2 payload shape rather than raising, leaving the database's own constraint as the single source of truth.
- Re-ran the 4 previously-failing live smoke tests against the real database after the fix — all 5 tests in that file (including `test_05_legacy_records_compatibility`) now **pass live**, and no orphaned test rows were left behind (`SELECT ... WHERE title LIKE '%Smoke Test%'` → 0 rows, both before and after).

## 10. Auth/Data Client Separation (`auth_client.py`)

- `auth_client.py:get_auth_client()` — reads `SUPABASE_ANON_KEY` only; never `SUPABASE_SERVICE_KEY`. Used exclusively for sign-in/session/sign-out.
- `database.py:get_client()` — unchanged, reads `SUPABASE_SERVICE_KEY` only; never `SUPABASE_ANON_KEY`.
- `SUPABASE_ANON_KEY` populated in local `.env` (gitignored, never committed — confirmed) from the project's actual **publishable/legacy-anon** key (fetched read-only via Supabase's own key-listing API) — anon keys are safe-by-design for client-facing use, unlike the service-role key, so this is not a secret-handling regression; `.env.example` documents the new variable with a placeholder.
- Regression guard (`TestAuthDataClientSeparation`, 4 tests): neither module's source contains the other's actual credential-access pattern (docstring prose mentioning both key names for documentation purposes is fine and explicitly allowed by the test); and two live-mocked tests prove `database.create_client()` receives the service-role value while `auth_client.create_client()` receives the anon value, never the reverse.

## 11. Application Behavior — Nothing Made Mandatory

No page in `app.py`/`pages/*.py` calls `auth_client.py`, `auth_session.py`, or `tenancy.py` yet. The existing commissioned internal application continues to operate entirely through `database.py`'s service-role path, exactly as before this package — verified live (§16). Package 3 is what will switch the product over to enforced authenticated access, once a real user exists, membership exists, and RLS policies are written.

## 12. `firm_profiles` Tenancy Decision

**Decision: organization-owned.** `get_firm_profile()`/`save_firm_profile()` currently treat it as a single global (`.limit(1)`) row representing one bidding firm's capability profile — sensible for a single-operator tool, but not sensible for a real multi-tenant product where each organization using Bid Intelligence would have its *own* capabilities, certifications, and disclosure policy. Migration 007 adds `firm_profiles.organization_id` (nullable — the live table has 0 rows, confirmed immediately before writing the migration, so this is pure additive risk-free schema; left nullable rather than forced `NOT NULL` because no authenticated/tenant-aware write path exists yet to populate it, and forcing `NOT NULL` here would only be achievable by inventing a value, which this migration does not do).

## 13. `analysis_runs.created_by` / `created_by_user_id` Decision

**Decision: add a new, separate, nullable column; leave `created_by` completely untouched.** `created_by`'s historical and current values (e.g. `"app-ui"`, hardcoded at the one call site in `pages/stage_understand.py`) represent execution *origin/channel*, not a user identity, and reinterpreting them as user IDs would be a fabrication. Migration 007 adds `analysis_runs.created_by_user_id uuid references auth.users(id) on delete set null` — nullable, no backfill (historical runs correctly remain unattributed to any real user, because none exists for them). No code currently writes to this column; wiring it up is package 3's job, once `AuthContext` actually reaches the Fast Analysis start call site.

## 14. Session Handling (`auth_session.py`)

`sign_in(email, password)`, `sign_out()`, `current_session()`, `restore_session()` — see the module's own docstring for the full lifecycle/risk writeup required by instruction 16. Summary:

- **No password, and no service-role credential, is ever stored in `st.session_state`** — only the signed-in user's own short-lived access/refresh tokens (plus their expiry), which is the same thing any Supabase client-side app holds after sign-in.
- **Successful login:** populates session state, returns `AuthResult(ok=True, user_id, email)`.
- **Invalid login:** returns a fixed, generic error message — the real provider exception text is never echoed back (verified: `test_sign_in_invalid_credentials_returns_generic_error_not_raw_exception_text` asserts neither the raw exception detail nor an email appears in the returned error).
- **Logout:** clears local session state unconditionally, even if the remote Supabase sign-out call itself fails (`test_sign_out_clears_session_state_even_if_remote_call_fails`) — a failed remote call must never leave the UI looking signed-in.
- **Expired token:** `restore_session()` checks the locally-stored `expires_at` against wall-clock time and fails closed with `"session expired"` — no network call is made on every Streamlit rerun just to check this.
- **Missing token:** fails closed with `"no session"` / `"stored session is missing required token/identity fields"`.
- **Session restoration:** best-effort, in-process only — `st.session_state` lives only in the server process's memory for that browser session, same limitation already documented for Fast Analysis's background threads, and for the same underlying reason (no external session store exists).
- **No public sign-up:** `auth_session.py` exposes no `sign_up`/`register`/`create_account` function at all (`TestNoPublicSignUp`) — only `sign_in()` against an already-provisioned user.

## 15. Security Tests

35 new tests in `tests/test_auth_tenancy.py` plus 2 new tests in `tests/test_database.py` (37 total new tests; 1529 → 1566 passed), covering every item instruction 18 named:

organization creation model · slug uniqueness · membership uniqueness · valid roles only · bid requires valid organization after migration · existing bids backfilled correctly (live-verified, §16, not a unit test — see `TestMigration007SchemaContract`'s own docstring for why) · zero-membership fails closed · one-membership resolves · multi-membership does not silently select · AuthContext construction · tenant-aware bid listing · tenant-aware bid retrieval · cross-organization bid lookup rejected · service-role key never used by auth client · anon/public credential never used as privileged data client — plus additional coverage for session handling (sign-in/out/restore, expired/missing token, no-password-stored) and no-public-signup that instructions 16/6 also required be tested. No live LLM calls anywhere in this file.

## 16. Live Migration & Post-Migration Verification

**Pre-apply validation (all passed before touching the live database):** `py_compile` clean; `git diff --check` clean; migrations 001–006 confirmed untouched; full suite **1564 passed, 2 skipped** (1529 + the 35 auth/tenancy tests, before the compatibility-gap fix added 2 more).

**Applied via `apply_migration`** (tracked mechanism), name `007_auth_tenancy_foundation`, live-confirmed in Supabase's migration history as version `20260915072103`, alongside unchanged `004`/`005`/`006`.

**Live post-migration state** (direct SQL, re-verified independently of the migration's own success flag):

| Check | Result |
|---|---|
| `organizations` table exists, 1 row | YES — `emg-internal` / `Enable My Growth Internal` |
| `organizations` RLS enabled / policies | **YES / 0** |
| `organization_members` table exists, 0 rows | YES (expected — 0 auth users exist) |
| `organization_members` RLS enabled / policies | **YES / 0** |
| `bids.organization_id` exists, FK valid | YES |
| `bids.organization_id` NOT NULL | YES (`is_nullable = 'NO'`) |
| All 4 existing bids belong to `emg-internal` | YES (ids 1, 3, 8, 81 — verified by join) |
| `firm_profiles.organization_id` exists | YES (nullable, per §12) |
| `analysis_runs.created_by_user_id` exists | YES (nullable, per §13) |
| No existing bid/document/analysis result lost | YES — `analysis_runs`=8, `analysis_results`=8, `documents`=108, `requirements`=185, `bid_briefs`=4, `bid_decisions`=3, all unchanged from pre-migration counts; run IDs 1–8 preserved exactly, all still `COMPLETE`, all still `fast-analysis-v4` |

**A genuine compatibility break was found and fixed during this verification** — see §9. After the fix, full regression (including live smoke tests) re-run: **1566 passed, 2 skipped**, zero failures.

## 17. Application Smoke Test (§22) — Live, Through the Real UI

Performed through the actual Streamlit app (not a script), the same way every prior phase's UI verification was done. No new live LLM analysis was triggered.

- Dashboard loaded cleanly, showing **"4 total"** active bids — matching the live database exactly.
- All 4 bids correctly categorized by stage: Bank of Canada (Identified), CDA-AMC (Qualifying), The British Council (Qualifying), The City of Calgary (Submitted) — no bid disappeared, none miscategorized.
- Opened the Bank of Canada bid (a known, previously-analyzed bid): UNDERSTAND stage rendered correctly, "Fast Analysis complete in 199s," the persisted Document Discrepancies/Cross-Document Conflicts section rendered with its real, previously-established content (the pricing-stage ambiguity finding).
- Clicked **Download Report PDF** — triggered a Streamlit rerun; a transient client-side websocket reconnect banner appeared momentarily (a known Streamlit UX artifact after a blocking action), resolved instantly on page reload with no data loss and no re-navigation needed to see the same, correct state again. `preview_logs` (server-side) showed **zero errors** for the entire session — confirming this was a client-side connection blip, not an application or data defect.

**`LEGACY INTERNAL APP COMPATIBILITY: PASS`**

## 18. Auth Foundation Smoke Test (§23)

Since `auth.users` contains 0 rows (confirmed live, both before and after this entire package), no real sign-in could be tested end-to-end, and none was fabricated. Per instruction 23:

- Auth/session logic tested **deterministically with mocks** — see §15 (`TestAuthSession`, 7 tests: successful sign-in, invalid credentials, missing fields, missing/expired/valid token restoration, sign-out-clears-state-even-on-remote-failure).
- **Live Supabase Auth configuration confirmed reachable:** `auth.users` table itself is queryable (returns 0, not an error); the project's anon/publishable key was fetched read-only via Supabase's own key-listing API and is the exact value now wired into `auth_client.py`'s fallback path — i.e., the auth client is not just theoretically correct, it is configured with real, live-valid credentials, even though no sign-in was attempted against them.
- No `auth.users` row was created through SQL. No UUID was invented. No production user was created.

**`LIVE AUTH USER PROVISIONING: NOT PERFORMED`** — expected, as instructed.

**Bootstrap procedure for a real first user (documented, not performed):**
1. Create/invite a real user through Supabase Auth (Supabase dashboard's Auth → Users → Invite, or a future sign-up-adjacent admin flow — *not* public self-registration, per instruction 6).
2. Obtain that user's actual `auth.users.id` (a real UUID Supabase generates, not one invented here).
3. Insert one `organization_members` row: `{organization_id: <emg-internal's UUID>, user_id: <that real auth.users.id>, role: 'owner'}` (or `'admin'`/`'member'` as appropriate).

## 19. Remaining Authorization Gap (explicit, not overclaimed)

This package does **not** provide database-enforced tenant isolation. Specifically still missing, all deferred to package 3:

- No RLS policy exists on `organizations`, `organization_members`, or any of the 14 pre-existing tables — every one of them remains either fail-closed-with-no-policy (blocking everyone but service-role) or, for `bid_briefs`/`bid_decisions`/`firm_profiles`, RLS-enabled-no-policy as of package 1 (also fail-closed).
- No application code path uses `AuthContext`, `auth_session.py`, or the tenant-aware `tenancy.py` primitives yet — the current app is 100% unauthenticated and 100% service-role, unchanged in practice from before this package.
- `coaches` and `content_library`'s null-`bid_id` rows have no resolved tenancy story yet (§1).
- `firm_profiles.organization_id` and `analysis_runs.created_by_user_id` are populated by nothing yet (both nullable, both unwritten by any current code path).

Status, exactly as instructed: **`AUTHENTICATION/TENANCY FOUNDATION PRESENT — AUTHORIZATION ENFORCEMENT PENDING`**. Not `MULTI-TENANT SECURITY COMPLETE`.
