# Bid Intelligence — Phase 8 Remediation Package 3: Tenant RLS Policy Enforcement & Authenticated Access Cutover

**Date:** 2026-09-15 (UTC)
**Status:** `TENANT RLS POLICIES LIVE — FINAL INTERACTIVE CUTOVER COMPLETE, INCLUDING COACHES ORGANIZATION TENANCY (migration 009, see Addendum 7) — LIVE-PROVEN, PASS DETERMINATION DEFERRED TO USER REVIEW, NOT YET COMMITTED/PUSHED`
**Live project:** `whonalbdpbubaqhpzrnw`

---

## Package 2 Checkpoint

- **Checkpoint SHA:** `b46ec1013bb0c457f08d9c4f4290e694fe9aba42`
- **Checkpoint tag:** `bid-intelligence-tenancy-foundation-v1` (annotated, local only, not pushed; tag target SHA verified equal to the checkpoint SHA)
- Two commits were made to reach this checkpoint (Package 1's migration 006 + its two reports had never been committed either, so both packages were checkpointed in sequence rather than leaving migration 006 absent from git history while 007 was present):
  1. `0013361` — "Commission production-readiness audit and close open RLS tables" (Package 1: migration 006, the production-readiness audit, the RLS remediation 1 report)
  2. `b46ec10` — "Establish Bid Intelligence auth and tenancy foundation" (Package 2: `auth_client.py`, `auth_session.py`, `tenancy.py`, migration 007, `database.py`'s legacy-org compatibility fix, tests, report)
- Pre-checkpoint verification: `py_compile` clean, `git diff --check` clean, full suite **1566 passed, 2 skipped**.

## 1. Pre-Policy Data Access Audit

Every `.table(...)` call site in `database.py`, `tenancy.py`, and `analysis_service.py` was enumerated by file:line (not assumed) and cross-referenced against every real, wired-up UI action in `app.py`/`pages/*.py` (in particular, every `delete_*()` call site was traced to confirm which deletions are genuinely user-facing today).

| Table | SELECT | INSERT | UPDATE | DELETE | Category | Notes |
|---|---|---|---|---|---|---|
| `bids` | user | user | user | **server-only** | A (mixed) | DELETE cascades to every downstream table — highest blast-radius action in the schema; left server-only despite an existing "Delete Bid" UI button (instruction 8 explicitly permits this) |
| `requirements` | user | user | user | user | A | real, wired `delete_requirement()` UI action |
| `tasks` | user | user | user | user | A | real, wired `delete_task()` UI action |
| `outline_sections` | user | user | user | user | A | real, wired `delete_section()` UI action |
| `deliverables` | user | user | user | user | A | real, wired `delete_deliverable()` UI action |
| `clarifications` | user | user | user | user | A | real, wired `delete_clarification()` UI action |
| `content_library` | user* | user* | user* | user* | A (bid-scoped rows only) | `bid_id IS NULL` "global" rows are a genuinely unresolved product decision — see §9 |
| `debriefs` | user | user | user | — | A | no `delete_debrief()` exists anywhere in the codebase — no DELETE policy granted |
| `bid_decisions` | user | user | — | — | A | `save_bid_decision()` only ever INSERTs (append-only by pre-existing design) — no UPDATE/DELETE policy |
| `documents` | user | server | server | server | B | write path (including delete) shares the service-role Storage client; deferred to package 4 alongside Storage authorization, not an oversight |
| `document_versions` | user | server | — | — | B | confirmed live-used at `app.py:1050`; only ever written internally by `save_upload()`'s version-archive step |
| `bid_briefs` | user | server | server | — | B | written only by the Fast Analysis background pipeline |
| `analysis_runs` | user | server | server | — | B | user-*initiated* but server-*executed*; see §17's authorization boundary |
| `analysis_results` | user | server | — | — | B | same |
| `firm_profiles` | user | user | user | — | D | organization-owned (via `organization_id`, not `bid_id`) — see Package 2's own decision |
| `organizations` | user (own only) | server | server | server | D | creation/admin mutation stays server-only |
| `organization_members` | user (own rows only) | server | server | server | D | membership creation/removal stays server/admin-controlled |
| `coaches` | **none** | **none** | **none** | **none** | C | no `bid_id`, no `organization_id` — cannot be correctly tenant-scoped without a schema change, which is out of this policy-only migration's scope |

## 2–4. Authorization Rule, Role Semantics, Recursion/Security-Definer Design

Core rule implemented exactly as specified: `auth.uid() → organization_members → organizations → bids.organization_id`, with every downstream bid-owned table inheriting through its own existing `bid_id` FK — **no `organization_id` column was added to any downstream table.**

Roles kept exactly as they already were (`owner`/`admin`/`member`, unchanged from Package 2) — Package 3 does not differentiate them anywhere; every policy treats "is a member" as the only gate, matching instruction 3's explicit "do not manufacture role complexity" where the product doesn't currently need the distinction.

**Two SECURITY DEFINER helper functions**, `is_organization_member(uuid)` and `can_access_bid(bigint)` — both `STABLE`, both with `SET search_path = public`, both `REVOKE`d from `PUBLIC` **and explicitly from `anon`** (see §5's mid-verification finding), both `GRANT EXECUTE`d only to `authenticated`, both returning only a boolean, both taking a single scalar id argument. **This schema has no actual recursion risk to avoid** — `organization_members`'s own policy checks only its own `user_id` column and queries no other table, so nothing here could ever recurse. The functions exist for single-source-of-truth/maintainability (avoiding the same 2–3-level join repeated inline across 40+ `CREATE POLICY` statements), the same discipline already applied elsewhere in this codebase (`database.py:_resolve_legacy_organization_id`, Fast Analysis's shared `_is_substantive_evaluation_row` predicate) — documented precisely as such in the migration file itself, per instruction 4's explicit requirement not to overstate why a SECURITY DEFINER function is safe.

## 5. Migration 008 — Full Contents

`migrations/008_tenant_rls_policy_enforcement.sql` — 42 policies across 17 tables plus the two helper functions. Full text in the repository; policy list by table/operation in §6–11 below. Does not touch migrations 001–007 (confirmed via `git status --porcelain` on each file before and after, empty both times).

**A defect found and fixed during live verification, disclosed transparently (same discipline as Package 2's `create_bid()` compatibility fix):** immediately after first applying the migration, `information_schema.routine_privileges` showed `anon` still had `EXECUTE` on both helper functions, despite `REVOKE ALL ... FROM PUBLIC` — Supabase grants `EXECUTE` on every newly-created function to `anon`/`authenticated`/`service_role` **directly**, independent of the `PUBLIC` pseudo-role, so revoking from `PUBLIC` alone does not remove `anon`'s access. **Not an actual data-exposure gap** — both functions key off `auth.uid()`, which is `NULL` for an unauthenticated `anon` caller, so every check already evaluated to `false` for `anon` regardless — but closed explicitly as defense in depth: `REVOKE EXECUTE ... FROM anon` added to the migration file and applied live (tracked as a small follow-up migration, `008b_revoke_anon_execute_on_tenant_helper_functions`, for a complete Supabase migration history). Live-reverified: `anon` now has zero `EXECUTE` privilege on either function.

## 6. `organizations` Policy

```sql
create policy organizations_select_own_membership
    on public.organizations for select to authenticated
    using (public.is_organization_member(id));
```
No insert/update/delete policy — creation/deletion/admin mutation remains server-only (instruction 6).

## 7. `organization_members` Policy

```sql
create policy organization_members_select_own_rows
    on public.organization_members for select to authenticated
    using (user_id = auth.uid());
```
Deliberately the smaller exposure named in instruction 7: a user sees only their own membership row(s) — enough to resolve their own `AuthContext` — never a directory of who else belongs to their organization. No insert/update/delete policy.

## 8. `bids` Policies

```sql
create policy bids_select_org_member on public.bids for select to authenticated
    using (public.is_organization_member(organization_id));
create policy bids_insert_org_member on public.bids for insert to authenticated
    with check (public.is_organization_member(organization_id));
create policy bids_update_org_member on public.bids for update to authenticated
    using (public.is_organization_member(organization_id))
    with check (public.is_organization_member(organization_id));
```
The `UPDATE` policy's paired `USING`/`WITH CHECK` (both gated on `organization_id`) is exactly what stops a member from reassigning a bid's `organization_id` to an organization they don't belong to — both the row's *current* organization and its *proposed new* organization must pass the same membership check. No `DELETE` policy — server-only, per §1's reasoning.

## 9. Bid-Owned Downstream Tables

Full member CRUD (`requirements`, `tasks`, `outline_sections`, `deliverables`, `clarifications`): 4 policies each, all gated by `public.can_access_bid(bid_id)`.

`debriefs`: select/insert/update only (no delete function exists in the product). `bid_decisions`: select/insert only (append-only by existing design).

`content_library`: full CRUD but every policy additionally requires `bid_id IS NOT NULL` — the `bid_id IS NULL` "global" library rows remain fail-closed to authenticated users. **This is a genuinely unresolved product decision, not an oversight**: does "global" mean visible to every organization, or scoped per-organization? Left unresolved and inaccessible rather than guessed at.

`documents`/`document_versions`/`bid_briefs`/`analysis_runs`/`analysis_results`: SELECT only, `public.can_access_bid(bid_id)` (or, for `document_versions`, one hop further through `documents.bid_id`). No authenticated write policy on any of these five — see §16/17 for how a user-*initiated* write to `analysis_runs`/`analysis_results`/`bid_briefs` is authorized instead.

## 10. `firm_profiles`

```sql
create policy firm_profiles_select_org_member on public.firm_profiles for select to authenticated
    using (organization_id is not null and public.is_organization_member(organization_id));
create policy firm_profiles_insert_org_member on public.firm_profiles for insert to authenticated
    with check (organization_id is not null and public.is_organization_member(organization_id));
create policy firm_profiles_update_org_member on public.firm_profiles for update to authenticated
    using (organization_id is not null and public.is_organization_member(organization_id))
    with check (organization_id is not null and public.is_organization_member(organization_id));
```
Uses `firm_profiles.organization_id` directly (added in migration 007) — not `can_access_bid()`, since this table is not bid-scoped. No delete policy (the app never deletes the firm profile).

## 11. Server-Only Tables

`coaches` — has neither `bid_id` nor `organization_id`; cannot be correctly tenant-scoped without a schema change, which migration 008 (policy-only, per instruction 5) is not authorized to make. RLS was already enabled with zero policies (pre-existing, unrelated to this migration); migration 008 adds none. Fail-closed, confirmed both by static policy absence and by the live negative-case test (§ below: a simulated authenticated non-member sees 0 `coaches` rows — the same as every other table).

## 12. No Anon Data Policies

Live-verified via `pg_policies`: **all 42 policies** created by this migration show `roles = {authenticated}` — none target `anon`, none omit the role clause (which would default to `PUBLIC` = both). `information_schema.role_table_grants` was checked first (before writing any policy) and confirmed Supabase's own default table-level GRANTs already cover `anon` on every table — meaning RLS, not GRANT, is this project's actual enforcement layer, and no GRANT/REVOKE change was needed or made at the table level (only the two function-level EXECUTE grants discussed in §5).

## 13–14. Client Separation

Three Supabase clients now exist, each with an explicit, hard-to-confuse name:

| Client | File | Key | Purpose |
|---|---|---|---|
| `database.get_service_client()` (alias of the pre-existing `get_client()`, kept for the ~60 existing call sites) | `database.py` | `SUPABASE_SERVICE_KEY` | Privileged server-side operations; bypasses RLS |
| `auth_client.get_auth_client()` | `auth_client.py` | `SUPABASE_ANON_KEY` | Sign-in / session validation / sign-out only — no user token attached |
| `auth_client.get_authenticated_client(access_token)` **(new this package)** | `auth_client.py` | `SUPABASE_ANON_KEY` + the signed-in user's own access token (`client.postgrest.auth(access_token)`) | User-scoped interactive data access, subject to every migration 008 policy |

Regression guard (`tests/test_tenant_rls_enforcement.py::TestClientSeparation`, 7 tests, all passing): `get_service_client()` receives the service-role value; `get_authenticated_client()` receives the anon value and never the service-role value; neither `auth_client.py` nor `auth_session.py` nor `tenancy.py`'s source contains an actual `SUPABASE_SERVICE_KEY` access pattern; `auth_session.py` never imports `database` or references `get_service_client`; `get_authenticated_client()` rejects an empty/`None` token before constructing anything.

## 15. Interactive Application Cutover — Not Performed This Package

**No page in `app.py`/`pages/*.py` was modified.** The current commissioned internal application continues to run exactly as before, entirely through the service-role path — confirmed unchanged by the full regression suite and (below) a live UI smoke pass. This is deliberate: instruction 21's bootstrap gate applies, and `auth.users` remains empty (0 rows, confirmed both before and after this package). Wiring dashboard listing / bid opening / analysis-result reads over to `get_authenticated_client()` is real, necessary, ready-to-do work — but doing it now, with no real session to test it against, would mean shipping unverified interactive-auth code. It is deferred to the cutover step of this same package once a real user is provisioned (§21/§32 Outcome A), or to the next explicit authorization.

## 16–17. Privileged-Operation Authorization Boundary & Analysis-Start Authorization

New functions in `tenancy.py`, all tested with mocks (`tests/test_tenant_rls_enforcement.py::TestPrivilegedOperationAuthorization`, 8 tests):

```python
class AccessDeniedError(Exception): ...

def authorize_bid_access(bid_id, organization_id) -> bool: ...
def require_bid_access(bid_id, organization_id) -> None:  # raises AccessDeniedError
def start_fast_analysis_for_organization(bid_id, organization_id, api_key, created_by=None) -> dict
def get_report_for_organization(bid_id, run_id, organization_id) -> bytes
```

`start_fast_analysis_for_organization()` calls `require_bid_access()` **before** ever calling `analysis_service.start_fast_analysis()` — an unauthorized call raises `AccessDeniedError` and never reaches the privileged function at all. Verified explicitly: `test_unauthorized_user_cannot_request_analysis` asserts `mock_start.assert_not_called()` — **zero `analysis_runs` rows created, zero calls into the code path that would ever start an LLM call, for an organization attempting to analyze another organization's bid.** `analysis_service.py`/`fast_analysis.py` themselves are completely untouched — this is a wrapper in front of the existing, frozen entry point, not a modification to it.

## 18. Report Access Authorization

`get_report_for_organization()` performs **two** checks before calling `analysis_service.regenerate_report()`: (1) the caller's organization owns `bid_id`; (2) the given `run_id` actually belongs to `bid_id` (not just *some* bid the caller owns) — closing the specific "guessed/adjacent run_id from a different bid" attack the instructions named. Both are tested independently (`test_unauthorized_report_retrieval_fails_bid_not_owned`, `test_unauthorized_report_retrieval_fails_run_belongs_to_different_bid`), and both fail closed before `regenerate_report()` is ever called (`mock_regen.assert_not_called()` in both cases). Storage-specific signed-URL hardening remains explicitly out of scope, deferred to package 4.

## 19–20. Authentication Enforcement / No Public Signup

**Not activated this package** — see §15/§21. `auth_session.py` (from Package 2, re-confirmed unchanged) still exposes no `sign_up`/`register`/`create_account` function of any kind.

## 21. Real User Bootstrap Gate

`auth.users` re-confirmed **empty (0 rows)** both immediately before and immediately after this entire package — no user was created, no UUID was invented, no row was inserted into `auth.users` through SQL. Per instruction 21, this package stops here rather than proceeding to a mandatory-auth cutover with no real user to validate it against.

**Bootstrap procedure for a real first user (documented, not performed — identical to Package 2's own documented procedure, repeated here for this package's context):**
1. Create/invite a real user through Supabase Auth (dashboard Auth → Users → Invite — *not* public self-registration).
2. Obtain that user's real `auth.users.id`.
3. Insert one `organization_members` row: `{organization_id: <emg-internal's UUID>, user_id: <that real id>, role: 'owner'}` (or another role, if specified).

## 22–26. Deferred Pending Bootstrap

Real user provisioning, membership linking, the live authenticated-client end-to-end test (§24: sign-in → `AuthContext` resolution → tenant-scoped Dashboard → opening an authorized bid → an existing result rendering), and session-expiry/logout behavior against a *real* session are all genuinely gated behind §21 and were not performed, per explicit instruction not to fabricate a user. `auth_session.py`'s expiry/logout logic was already deterministically tested in Package 2 (`tests/test_auth_tenancy.py::TestAuthSession`) and re-confirmed passing unchanged in this package's full regression run.

## 23. Live RLS Isolation Test — Precisely Documented

**Method used, exactly as instruction 23 requires being documented precisely:** a SQL transaction against the live database, `SET LOCAL role authenticated; SET LOCAL request.jwt.claims = '{"sub":"<a syntactically-valid but non-existent UUID>","role":"authenticated"}'`, followed by a batch of `SELECT COUNT(*)` queries across every table, then `ROLLBACK` (no data created, modified, or left behind).

**Negative case — fully, genuinely live-proven this way.** A simulated authenticated user who is a member of zero organizations sees **`0` rows in every single table**, including two direct-guessed-ID probes (`SELECT * FROM bids WHERE id = 8` → 0 rows; `SELECT * FROM analysis_runs WHERE id = 1` → 0 rows) — proving RLS blocks not just listing but also direct-ID access, and that `coaches` (no policy at all) is exactly as inaccessible as every properly-policied table.

**Positive case — NOT live-proven with a genuine role-switched session, and this is stated precisely rather than overclaimed, per instruction 23's own explicit requirement.** `organization_members.user_id` carries a hard foreign key to `auth.users(id)` (by design, from migration 007) — inserting a temporary membership row for a simulated user, even inside a rolled-back transaction, is impossible without a real `auth.users` row, because the FK check happens regardless of role or transaction rollback plan. Since `auth.users` is empty, no genuine "a real member sees their own organization's bid" RLS-role-switched test could be performed this package. Instead, the positive case was verified as **policy-logic equivalence**: a plain, service-role query reproducing the exact join `can_access_bid()`/`is_organization_member()` use (`bid.organization_id = organizations.id AND organizations.slug = 'emg-internal'`) confirms all 4 real bids would correctly evaluate as visible to a genuine `emg-internal` member — this is a logic check against real data, **not** a live authenticated-session proof, and is labeled as such here deliberately so it is never mistaken for one.

## 24. User-Client Live Test — Not Performed

Requires a real signed-in session (§21 gate). Not performed. `get_authenticated_client()` itself was unit-tested (correct anon key, correct token attachment, correct rejection of an empty token) but never exercised end-to-end against the live API with a real bearer token.

## 25. Cross-Tenant Application Test

- **Database RLS boundary:** covered by §23's negative-case live test (direct ID guesses of `bids`/`analysis_runs` both return 0 rows for a non-member).
- **Application/service authorization boundary:** covered by §16–18's `tenancy.py` tests — `start_fast_analysis_for_organization()` and `get_report_for_organization()` both deterministically deny access and touch zero privileged code paths for an unauthorized organization/bid/run combination, independent of whatever RLS policy is or isn't in place (defense in depth, by design — see §16's own reasoning for why these checks exist even though the underlying tables are already RLS-protected).

No URL/query-param manipulation test against a *running interactive UI* was performed, because no interactive page currently reads a bid/run ID from user-controllable UI state through the authenticated client (§15 — cutover not yet wired in); this becomes directly testable once that wiring exists.

## 26. Session Expiry — Unchanged, Re-Confirmed

`auth_session.py` is unmodified from Package 2. Its expiry/logout tests (valid session works; expired token fails closed with `"session expired"`; missing token fails closed with `"no session"`; sign-out clears session state even if the remote call fails) all re-ran and passed unchanged as part of this package's full regression. Organization-context clearing at logout has no code to test yet, since no page currently stores an `AuthContext` in session state (§15).

## 27. Migration 008 Static Gate — All Passed Before Live Apply

No data deletion; no table drops; migrations 001–007 untouched (file-diff-confirmed); no `anon` procurement-data policy (0 of 42); no unconditional `USING (true)`/`WITH CHECK (true)`; no unrestricted cross-org policy; no table-level `GRANT`/`REVOKE` change (function-level `EXECUTE` grants only, exactly as needed for the policies themselves to evaluate). Enforced by `tests/test_tenant_rls_enforcement.py::TestMigration008PolicyContract`, 21 tests, all passing — see that file's own module docstring for the comment-stripping technique used to avoid false positives from this migration's own explanatory prose (the same false-positive class fixed in Package 2's `create_bid()`/`emg-internal` tests).

## 28. Test Matrix — Coverage Summary

38 new tests in `tests/test_tenant_rls_enforcement.py` (1566 → 1604 passed): 21 static policy-contract tests, 8 privileged-operation authorization tests, 7 client-separation tests, 2 miscellaneous. Every item instruction 28 named is covered — membership isolation (policy existence + live negative test), bids isolation (policy existence + org-reassignment guard + live negative test), all six named downstream tables (policy existence, correct CRUD scope per §1's audit), firm-profiles isolation, all five privileged-action items (authorized succeeds, unauthorized denied with zero privileged calls, for both analysis-start and report-retrieval), and all three client-separation items.

## 29–30. Live Migration & Post-Migration Security Advisor

Applied via `apply_migration` (tracked mechanism), confirmed in Supabase's migration history as `20260915113656` (`008_tenant_rls_policy_enforcement`) plus the follow-up `20260915113836` (`008b_revoke_anon_execute_on_tenant_helper_functions`) — migrations 001–007 unchanged in the same history listing. 42 policies confirmed live via `pg_policies`, every one `roles = {authenticated}`.

**Security advisor, re-run after both applies:**
- `rls_disabled_in_public` (ERROR): **0 findings** — unchanged from Package 1's clearance.
- `rls_enabled_no_policy` (INFO): **1 finding** — `coaches` only (down from 16 before this package; every other table that needed one now has appropriate policies). Exactly the expected, intentional end state per instruction 30 ("server-only tables may legitimately remain `rls_enabled_no_policy`" / "do not eliminate INFO warnings by adding unnecessary policies").
- `authenticated_security_definer_function_executable` (WARN, **new**): flags `is_organization_member`/`can_access_bid` as SECURITY DEFINER functions callable by `authenticated` via PostgREST RPC. **Reviewed and accepted, not remediated further**: `authenticated` genuinely needs `EXECUTE` for the 42 policies themselves to evaluate at all (a policy's `USING`/`WITH CHECK` clause runs as the querying role); both functions return only a boolean, take only a scalar id, and key off `auth.uid()` — which resolves to the *calling* user's own JWT regardless of `SECURITY DEFINER`, so a direct RPC call can only ever answer "do **I** have access to this one id," nothing more. Documented precisely in migration 008's own comments and here, per instruction 4's explicit requirement to justify any SECURITY DEFINER function's safety rather than assert it.

## 31. Legacy Service-Role Compatibility Shim

**Not touched.** Instruction 31 applies "once authenticated cutover is complete" — this package explicitly has not reached that point (§21/Outcome A). `database.create_bid()`'s `_resolve_legacy_organization_id()` compatibility path (introduced in Package 2) remains exactly as-is, and remains necessary: it is the only thing keeping the current commissioned internal app's "New Bid" flow working. Revisiting its removal is correctly deferred to whenever a future package actually completes the authenticated cutover.

## Full-Suite & Legacy Application Compatibility

- `py_compile` clean; `git diff --check` clean.
- Full suite: **1604 passed, 2 skipped** (1566 + 38 new tests), before and after the live migration apply — identical count both times, zero failures, zero live LLM calls anywhere in the new tests.
- No interactive-UI smoke test was re-run for this specific package (Package 2's own UI pass already proved the app tolerates a schema change; this package made no application-code change to `app.py`/`pages/*.py` at all, so there is nothing new for a UI pass to exercise beyond what the full pytest suite — which does execute every page's render path via `tests/smoke/test_all_pages_runtime.py` — already covers).

## Remaining Security Gaps (honest, not resolved this package)

1. **No real authenticated user exists** — the entire authorization layer built this package is unexercised by any real session. This is the primary, expected, named gap (§21).
2. **Interactive application is not yet cut over** — every page still reads/writes through the service-role client; `get_authenticated_client()`/`tenancy`'s authorization functions exist and are tested but are not called from anywhere in `app.py`/`pages/*.py` yet.
3. **`coaches` remains entirely inaccessible to authenticated users** and has no tenant-scoping column — a genuine product decision (organization-scoped roster vs. truly global) is still needed before this can be resolved.
4. **`content_library`'s `bid_id IS NULL` rows** remain inaccessible to authenticated users for the same reason — an unresolved "global vs. per-organization" product decision.
5. **Storage/report path authorization** (signed URLs, bucket-level policy) remains entirely deferred to package 4, as scoped.
6. **The `authenticated_security_definer_function_executable` WARN** is reviewed and accepted (§30) but not eliminated — doing so would require moving the functions out of PostgREST's exposed schema, a project-configuration change out of this migration-only package's scope.
7. **The pre-auth `create_bid()` compatibility shim** remains active by design (§31) — a reminder that it must be revisited once real authenticated cutover happens, so it never quietly survives into a fully multi-tenant production state.

---

## Addendum: Real User Bootstrap & Live-Data Authorization Verification

**Date:** 2026-09-15 (UTC), same day, following explicit user authorization to provision a specific real user.

### Bootstrap (steps executed exactly as authorized)

1. Confirmed `auth.users` still had exactly 0 rows immediately before provisioning.
2. **Provisioned via Supabase Auth's normal invitation mechanism** — `sb.auth.admin.invite_user_by_email('feras@enablemygrowth.com')` (the GoTrue Admin API, not a raw SQL insert into `auth.users`). Result: real user created, `id = ed5ccf11-8f6e-4975-85db-f2d1cf84660b`, `email_confirmed_at = None` (invite email sent, pending the real human's acceptance).
3. **Linked to `emg-internal` with role `owner`** — a single `INSERT INTO organization_members` resolving both ids by their real values (the user's real `auth.users.id`; the organization's id via its `slug = 'emg-internal'`, never a hardcoded UUID), `ON CONFLICT DO NOTHING` for safety. Live-confirmed: exactly 1 `organization_members` row, exactly 1 `auth.users` row, exactly 1 `organizations` row (unchanged) — no additional users, no duplicate memberships.

### A credential-materialization action was blocked — disclosed precisely, not worked around

To obtain a genuine, live, GoTrue-issued session (access token) for the real user — the standard server-side technique being `admin.generate_link(type='magiclink', ...)` followed by exchanging the returned token for a session — the harness's auto-mode safety classifier refused the action under **"Credential Materialization."** The call was blocked before any network request was made: no email was sent by this attempt, no token was generated, no side effect occurred. Per the refusal's own explicit instruction, no workaround was attempted (no alternate tool, no re-framing of the same action) — the remainder of the acceptance plan that does **not** require a materialized session token was completed instead, and this gap is reported here for the user to decide how to proceed (e.g., complete the invite-acceptance flow themselves in a real browser, or explicitly authorize a scoped session-generation action).

**Practical consequence:** every acceptance-plan item that is checkable through real, live *data* (via SQL role/claim simulation against the real user's real UUID, or via server-side function calls using the real, already-resolved organization_id) was completed and is reported below as genuinely live-verified. Every item that specifically requires driving the actual Supabase Auth sign-in flow or the Streamlit UI with a live bearer token was **not** completed, and is reported as such — not glossed over.

### 1–2. AuthContext resolution / user-scoped client

- **`AuthContext` resolution: live-verified against real data.** `tenancy.resolve_organization_context('ed5ccf11-8f6e-4975-85db-f2d1cf84660b', 'feras@enablemygrowth.com')` (real code, real user_id, service-role read — no session token needed for this lookup itself) returned:
  `AuthContext(user_id='ed5ccf11-8f6e-4975-85db-f2d1cf84660b', email='feras@enablemygrowth.com', organization_id='4326b564-8cc5-4463-9304-9a589f08cc91', organization_name='Enable My Growth Internal', role='owner')` — correct in every field.
- **User-scoped client (`get_authenticated_client`) with a genuine bearer token: NOT live-verified** — blocked by the credential-materialization refusal above. Its unit tests (correct anon key, correct `postgrest.auth(token)` call, rejects an empty token) still pass, using a placeholder token string, not a real one.

### 3–4. Dashboard / bid access — verified at the data layer, not through the live UI

Not exercised through the actual Streamlit app with a real session (no session exists). Instead, live-verified at the exact layer the Dashboard/bid-open pages would rely on once wired to the authenticated client: a SQL transaction simulating `auth.uid()` as the real user's real UUID (`SET LOCAL role authenticated; SET LOCAL request.jwt.claims = '{"sub":"ed5ccf11-8f6e-4975-85db-f2d1cf84660b",...}'`, rolled back afterward, no data touched):

| Table | Rows visible to the real user | Matches known real total? |
|---|---|---|
| `organizations` | 1 | ✅ (their own) |
| `organization_members` | 1 | ✅ (their own row) |
| `bids` | 4 | ✅ (all of emg-internal's) |
| `requirements` | 185 | ✅ |
| `documents` | 108 | ✅ |
| `bid_briefs` | 4 | ✅ |
| `bid_decisions` | 3 | ✅ |
| `analysis_runs` | 8 | ✅ |
| `analysis_results` | 8 | ✅ |
| `firm_profiles` | 0 | ✅ (0 rows exist live) |
| `coaches` | 0 | ✅ (fail-closed for everyone) |
| Direct `bids WHERE id = 8` | 1 | ✅ |
| Direct `analysis_runs WHERE id = 1` | 1 | ✅ |
| `is_organization_member()` RPC for emg-internal | `true` | ✅ |
| `can_access_bid(8)` RPC | `true` | ✅ |

Every count matches the known real total exactly — proving the RLS layer grants complete, correct access to the real user's own organization's data, at the exact layer the interactive application would read through once wired.

### 5. Cross-tenant denial — both boundaries, live, using a genuine transactionally-rolled-back second tenant

**Database RLS boundary:** inside one transaction, a **temporary second organization and bid** were created under the privileged connection role (`INSERT INTO organizations (...) VALUES ('Temp Cross-Tenant Test Org (rolled back)', 'temp-crosstenant-test-org')`, then a bid owned by it), then the session switched to the real user's real UUID as `authenticated`, then:

| Check | Result |
|---|---|
| Temp org visible to real user | **0** |
| Temp bid visible to real user | **0** |
| Temp bid visible via direct `organization_id` filter | **0** |
| `can_access_bid()` RPC for the temp bid | **`false`** |
| Real user's own 4 `emg-internal` bids, same session | **4** (still correct — isolation is precise, not a blanket denial) |

Transaction rolled back; confirmed live afterward: `organizations` count still exactly 1, `bids` count still exactly 4 — zero residue.

**Application authorization boundary:** using the real `organization_id` (`4326b564-8cc5-4463-9304-9a589f08cc91`) and a fake/unrelated one, called through real `tenancy.py` code:
- `authorize_bid_access(8, real_org)` → `True`
- `authorize_bid_access(8, fake_org)` → `False`

### 6–7. Privileged operations — unauthorized denial and authorized success, both live

- `start_fast_analysis_for_organization(8, fake_org, "sk-ant-not-a-real-key")` → raised `AccessDeniedError("organization 00000000-0000-0000-0000-000000000000 does not have access to bid 8")`. **No `analysis_runs` row was created; `analysis_service.start_fast_analysis()` was never called; zero possibility of an LLM call.**
- `get_report_for_organization(8, 1, fake_org)` → raised `AccessDeniedError` for the same reason, before `regenerate_report()` was ever called.
- `get_report_for_organization(8, 1, real_org)` → **succeeded**, returning a real 83,317-byte PDF (`%PDF-` header confirmed) — regenerated from the persisted snapshot for real run 1 (Bank of Canada), **zero LLM/extraction calls**, proving the authorized path genuinely works end-to-end for real data, not just that the denial path works.

### 8. Logout / session-context clearing

Not live-tested — no live session was ever established (blocked by §above), so there is nothing real to log out of. `auth_session.py`'s deterministic tests (`sign_out()` clears session state even if the remote call fails; expired/missing-token restoration fails closed) are unchanged from Package 2/3 and re-passed in this round's full regression.

### 9. Legacy compatibility shim — NOT removed

`database.create_bid()`'s `_resolve_legacy_organization_id()` pre-auth compatibility path was **left in place, unchanged.** The instruction was to remove/disable it "if authenticated cutover is successful" — it is not: no page in the application was wired to require authentication, and no live session was ever established to validate such a cutover. Removing the shim now would break the current, still-service-role-only application (the only bid-creation path it has) for zero corresponding benefit, since nothing has replaced it yet. It remains exactly as necessary as it was before this round.

### 10. Full regression & security advisor — re-run after bootstrap

- Full suite: **1604 passed, 2 skipped** — identical to before bootstrap, zero regressions from provisioning the real user or any of the live SQL verification (all of which ran inside rolled-back transactions).
- Security advisor: `rls_disabled_in_public` — 0 (unchanged). `rls_enabled_no_policy` — 1, `coaches` only (unchanged). `authenticated_security_definer_function_executable` — 2, unchanged, still reviewed/accepted. **One new finding, now that a real user exists:** `auth_leaked_password_protection` (WARN) — Supabase Auth's HaveIBeenPwned compromised-password check is disabled by default on this project. This is an Auth *configuration* setting (Supabase dashboard → Auth → Policies), not a database migration, and was not in this package's scope to change — reported here as a genuine, low-cost, easy-to-enable recommendation for the user's own action, not silently fixed.

### Net state after this round

- Real user: **1** (`feras@enablemygrowth.com`, `owner` of `emg-internal`).
- Database-level tenant isolation: **genuinely live-proven**, both positive (real user sees exactly their own org's data, completely) and negative (cannot see a transactionally-created different org's data; direct ID guesses denied), using the real user's real UUID via SQL-layer claim simulation — the strongest proof available without a materialized session token.
- Application-level authorization boundary: **genuinely live-proven**, both denial and success paths, using real data and real code, no mocks.
- Interactive application: **unchanged, not cut over** — still runs entirely through the service-role path; no page reads a real session.
- Live browser/UI proof with the real human's own session: **not performed**, blocked by a safety guardrail on credential materialization, disclosed precisely rather than worked around.

---

*Nothing in this package or its addendum makes any claim of "multi-tenant security complete" or of a completed interactive cutover. Database- and application-layer tenant isolation is now genuinely live-proven against a real provisioned user. The interactive application continues operating exactly as it did before this package, through the same service-role path — completing the actual cutover requires either the real user finishing their own sign-in (setting a password via the invite email already sent to feras@enablemygrowth.com) so a genuine session can be tested, or explicit authorization for a scoped session-generation action this session was not permitted to take on its own.*

---

## Addendum 5: The Final Bounded Cutover Pass — Auth Gate, Dashboard, Bid-Open, Analysis Reads, Bid Creation

**Date:** 2026-09-15 (UTC), same day, following the explicit instruction to perform one final bounded cutover of the actual normal-UI routes (not just the earlier additive diagnostic panel).

### What changed

1. **Mandatory authentication gate (`app.py`, new, ~120 lines at the top of the script).** An unauthenticated request now sees a sign-in screen (email → magic-link request via `sign_in_with_otp(should_create_user=False)`) and nothing else — `st.stop()` before any Dashboard/bid rendering. `tenancy.resolve_organization_context()`'s three outcomes are each handled explicitly: `NoOrganizationAccess` → error + sign-out, stop (fail closed); exactly one membership → proceeds automatically; `OrganizationSelectionRequired` → an explicit `st.selectbox` + `Continue` button, never auto-chosen, stop until confirmed.
2. **Dashboard (`page_dashboard`) and All Bids (`page_all_bids`)** now read via `tenancy.list_bids_authenticated(_access_token)` — extended to include the same req/task-count rollup `database.get_all_bids()` used to compute, via the *same* authenticated client (so the rollup counts are themselves RLS-scoped, not just the bid list) — zero change to either page's own rendering logic.
3. **Bid-open (`go(page, bid_id)`)** is the single place `active_bid` is ever set anywhere in the codebase (confirmed: no other assignment exists) — it now calls `tenancy.get_bid_authenticated(_access_token, bid_id)` first and fails closed (`st.error`, no navigation, no state change) if that returns `None`. The sidebar's own "Active Bid" display was switched to the same authenticated lookup.
4. **UNDERSTAND-stage reads (`pages/stage_understand.py`)**: the top-level `bid = get_bid(bid_id)`, both analysis-run status-panel reads, and the full-intelligence analysis-result read now go through `tenancy.get_bid_authenticated()` / `tenancy.get_latest_analysis_run_authenticated()` / `tenancy.get_latest_analysis_result_authenticated()` (three new functions added this round, exactly mirroring the original service-role functions' semantics — same ordering, same mode filtering, same COMPLETE-only result lookup — so Fast Analysis's own status/result *meaning* is completely unchanged, only which client reads it).
5. **Fast Analysis start (`_start_fast_analysis`)** now calls `tenancy.start_fast_analysis_for_organization(bid_id, organization_id, ...)` — built in an earlier round but never actually wired into the real UI button until now — instead of calling `analysis_service.start_fast_analysis()` directly. `AccessDeniedError` is caught and shown as a normal error. `analysis_service.py`/`fast_analysis.py` are untouched.
6. **Bid creation** (`page_new_bid`'s manual form and `_render_extraction_review`'s "Create Bid with Extracted Package") both call `tenancy.create_bid_for_organization(data, organization_id=_ctx.organization_id)` — the real, resolved organization from the gate, never inferred, never defaulted. `database.create_bid()` is no longer called from `app.py` at all (confirmed: no bare `create_bid({` call remains in the file).
7. **Logout** consolidated into one function, `_clear_all_user_scoped_state()`, called from all three "Sign out" entry points (the no-access screen, the org-selection screen, and the normal sidebar) — clears the session dict, the resolved `AuthContext`, `active_bid`, and every Package-3 UI selection key (`pkg3_selected_bid`, `pkg3_org_choice`, `pkg3_login_email`, `pkg3_bid_access_denied`) in one place, so the full logout contract is defined exactly once rather than duplicated per button.

### Legacy shim — retained, with concrete evidence (instruction 6)

`database.create_bid()`'s `_resolve_legacy_organization_id()` compatibility path was **not removed**. The normal interactive application no longer calls `database.create_bid()` at all (confirmed above) — but the function itself still has real, demonstrated internal (non-interactive) callers: `tests/acceptance/populate_supabase_and_stats.py`, `tests/acceptance/process_frozen_pipeline.py`, `tests/acceptance/run_blind_acceptance.py`, and — critically — the **live smoke tests** in `tests/smoke/test_live_supabase_migration_003.py`, which this exact compatibility path was written in package 2 specifically to keep passing against the live database. Removing it now would break all of them for no corresponding benefit. Per the instruction's own stated criterion ("retain only if you can demonstrate a still-required internal non-user path; otherwise remove it") — this demonstrates exactly that. Documented precisely in `database.py`'s own updated docstring.

### A genuine dead-code discovery, made while auditing remaining call sites

Auditing every remaining `database.py` call site reachable from `app.py`'s actual router turned up something not previously documented at this scope: **`app.py` contains seven entire page functions — `page_bid_overview`, `page_compliance`, `page_tasks`, `page_documents`, `page_outline`, `page_ai_analyst`, `page_deliverables`, plus the helper `_auto_populate_services`(called only from `page_deliverables`) — that the router never calls, confirmed by a repo-wide search finding zero call sites for any of them outside their own `def` line.** The router's `page in (...)` alias tuples (e.g. `"tasks", "documents", "deliverables"` all routing to `pages.stage_build.page_build`) route to the *module* equivalents in `pages/*.py`, not to these same-named `app.py` functions — evidently left behind when the product was reorganized into the `pages/` package, with only `page_bid_overview` previously flagged (Phase 3's own commissioning report). **All ~52 service-role call sites inside these seven functions are therefore not reachable from any real user path at all** — they do not count against "remaining reachable service-role call sites," for the same reason `page_bid_overview`'s own calls never did. This was not fixed (out of this package's scope — no dead-code removal was requested), only discovered and reported precisely rather than silently left uninvestigated.

### The honest remaining-surface audit (instruction: report exact remaining service-role call sites)

**Cut over to the authenticated client this round:** Dashboard, All Bids, sidebar active-bid display, bid-open (`go()`), UNDERSTAND stage's top-level bid + analysis-run + analysis-result reads, both bid-creation call sites. **Zero remaining service-role reads in any of these.**

**Deliberately privileged, authorization-checked before crossing to service-role:** Fast Analysis start (`tenancy.start_fast_analysis_for_organization`).

**One partial gap found while auditing, disclosed rather than silently left:** the "⬇ Download Report PDF" button (`pages/stage_understand.py`) still calls `database.download_file()` directly — a raw service-role Storage read, not routed through `tenancy.get_report_for_organization()`'s explicit authorization wrapper (which exists and is tested, but isn't wired into this button). It is *indirectly* bounded — the button is only reachable once `run = get_latest_analysis_run_authenticated(...)` has already confirmed RLS-visibility of that run to the caller's organization — but the file read itself is not independently authorization-checked. Storage-level authorization (signed URLs, bucket policy) has been out of scope for every package this engagement has run, explicitly deferred to package 4 from the very first Phase 8 audit onward; this specific button is the concrete instance of that deferral.

**Genuinely remaining, reachable from normal interactive UI, NOT cut over this round — reported exhaustively, not "zero":**

| Module | Reachable via | Remaining service-role call sites |
|---|---|---|
| `app.py::_render_extraction_review` | New Bid → package extraction → review screen | 5 (`upsert_requirement`, `upsert_document`, `save_upload`, `upsert_section`, `upsert_bid_brief`) — the bid's own post-creation population, immediately after the bid itself is created under the caller's real organization |
| `pages/stage_decide.py::page_decide` | Sidebar "2. DECIDE" | 10 (`get_bid`, `get_bid_brief`, `get_bid_decision` ×3, `get_clarifications`, `get_firm_profile`, `get_requirements`, `save_bid_decision` ×2, `update_bid` ×2, `upsert_clarification`, `upsert_requirement`) |
| `pages/stage_build.py::page_build` | Sidebar "3. BUILD" (and the `outline`/`tasks`/`documents`/`deliverables`/`section_drafter` aliases) | 14 |
| `pages/stage_check.py::page_check` | Sidebar "4. CHECK" | 6 |
| `pages/stage_submit.py::page_submit` | Sidebar "5. SUBMIT" | 7 |
| `pages/stage_debrief.py::page_debrief` | Sidebar "Debrief" (contextual, post-submission) | 4 |
| `pages/settings_firm.py::page_settings_firm` | Sidebar "Firm Profile & Settings" | 2 |
| `pages_extra.py` (Content Library, Team Roster, **Executive View's own `get_all_bids()`**, Clarifications, Proposal Analyzer, Section Drafter, Submission Assembler) | Sidebar global nav + in-page tabs | ~35, including a **second, uncut-over bid-listing view** (`page_exec_dashboard`) directly analogous to the Dashboard this round did cut over |

This is a real, substantial remaining surface — not zero, and not represented as zero. It was not addressed this round for a concrete, stated reason: cutting over every write path across five workflow-stage pages and the executive/library/roster pages would mean relying on migration 008's `INSERT`/`UPDATE`/`DELETE` policies in real interactive use for the first time — those policies are live and unit/SQL-tested, but **no write through them has ever been exercised in this entire engagement, only `SELECT`**. Doing that untested, across dozens of call sites, in the same pass as the read-side cutover, was judged a materially different and larger risk than this "one final bounded pass" was scoped for. It is flagged here as the natural next step, not silently deferred.

### New tests (16, `tests/test_interactive_cutover.py`)

`TestCutoverArchitecture` (11): the gate exists before any page function is even defined-reachable; the login screen never touches bid data; no public signup; zero-membership fails closed; multi-membership requires an explicit `Continue` click (never auto-selected); Dashboard/All Bids/`go()` all use the authenticated client with zero remaining `get_all_bids()`/bare `get_bid(` calls in those specific functions; bid creation always passes an explicit `organization_id`, never `emg-internal`; `database.create_bid()` no longer called from `app.py`; Fast-Analysis-start crosses the authorization boundary before ever touching `analysis_service.start_fast_analysis()`; the sidebar has a real Sign-out control. `TestGoAuthorizesBidOpen` (3, behavioral, against the live imported `app` module): authorized bid_id navigates; unauthorized/nonexistent bid_id fails closed with an inline error, zero state change, zero rerun; navigation without a bid_id never even attempts an authorization check. `TestLoginGateBehavior` (1, behavioral via `importlib.reload`): with session state cleared and every live call mocked, reloading `app` genuinely reaches the login screen (`st.text_input` for email actually renders) and never calls `tenancy.list_bids_authenticated` — a real behavioral proof, not just a source-text check.

Six existing tests needed updating for the new call shapes (5 in `tests/test_app_analysis_panel.py`, patching the new `tenancy.*_authenticated()` functions instead of the old direct `database.py` imports; 1 in `tests/test_tenant_rls_enforcement.py`'s logout test, updated for the new shared `_clear_all_user_scoped_state()` function). `tests/smoke/test_all_pages_runtime.py` was updated to simulate an authenticated session before `import app` (the gate runs at import time) and to proxy the "authenticated" client to the real service-role client for that one file's purposes, so `import app` and every page-render test continue exercising full rendering bodies, not early-return "not found" branches.

A genuine, self-identified test-isolation bug was found and fixed mid-round: an initial version of the new test file left `tenancy.auth_client.get_authenticated_client` globally patched for its entire module lifetime (mirroring the smoke test's own pattern), which collided with a *different* file's tests that specifically exercise the real, unpatched function — two `TestClientSeparation` tests failed only when the full suite ran together, not in isolation. Fixed by scoping the patch tightly to the one `import app` statement that needs it, leaving nothing globally patched afterward. Full suite re-run twice after the fix to confirm stability, not just once.

### Full-suite, compile, diff-check, security advisor

- `py_compile` clean across every modified file. `git diff --check` clean.
- Full suite: **1635 passed, 2 skipped** (1619 → 1635: 16 new tests), run twice for stability, identical result both times.
- Security advisor: unchanged from every prior round — 0 ERROR, 1 INFO (`coaches`, intended), 2 WARN (SECURITY DEFINER functions, reviewed/accepted), 1 WARN (leaked-password protection, open recommendation, unchanged).

### Status

The 7 named items in this round's instructions are implemented, live-data-consistent with every prior round's RLS/authorization-boundary verification, and covered by 16 new deterministic tests plus a full, stable regression run. **This is not the same claim as "zero service-role call sites remain reachable from normal interactive UI"** — that broader bar is not met, and the honest, itemized remaining surface above (five workflow-stage pages, settings, and the executive/library/roster pages — none of which were in this round's named scope) is reported in full rather than omitted or minimized.

---

## Addendum 2: Compromised Session Revocation & Token-Hash Invite Flow

**Date:** 2026-09-15 (UTC), same day, following user-reported exposure of the first invite's tokens.

### What happened, confirmed against live data

The real user's account status was re-checked live: `email_confirmed_at` and `last_sign_in_at` are both set to `2026-09-15 11:52:53` — 21 seconds after the original invite was sent. This confirms the real human did click the original invite link, and Supabase's **default implicit flow** (the project's Site URL was never configured by this engagement, so it was whatever Supabase's own project default is) delivered `#access_token=...&refresh_token=...` directly in the URL fragment — exactly the flow the user identified as unsafe for a Streamlit server (which cannot read URL fragments at all; they never leave the browser) and exactly the flow whose tokens got exposed during troubleshooting.

### Session revocation — completed

The compromised session's actual access/refresh token values were never given to or held by this session — only the real human had them. Revoking a specific token by value was therefore not possible; instead, the user's password was **rotated to a new, cryptographically random, immediately-discarded value** via `sb.auth.admin.update_user_by_id(user_id, {"password": <random>})` — the standard, sanctioned Supabase/GoTrue mechanism for invalidating a user's outstanding refresh tokens without needing to know the specific compromised token. The random value was never printed, logged, or stored anywhere; it exists only to invalidate, and is discarded immediately after the call. Confirmed: same user id (`ed5ccf11-8f6e-4975-85db-f2d1cf84660b`), no new user created, no user deleted, `updated_at` advanced to `2026-09-15 12:03:14`.

### Token-hash invite callback — implemented and unit-tested, NOT yet live-exercised

New code in `auth_session.py`:

```python
def handle_invite_callback() -> AuthResult:
    ...  # reads st.query_params["token_hash"]/["type"], accepts only
         # type="invite", calls the ANON client's verify_otp(), resolves
         # AuthContext via tenancy.resolve_organization_context(), stores
         # both in st.session_state, strips token_hash/type from the URL
         # immediately after processing (success or failure), never logs
         # or prints any token value
```

Wired into `app.py` as one additive call immediately after `st.set_page_config()`/`init_db()`/`inject_css()` — a safe no-op on every ordinary page load (confirmed: the full smoke-test suite, which renders every page, still passes unchanged). Authentication is still **not** mandatory anywhere in the application; this only completes the bootstrap invite-verification mechanics and makes the resulting `AuthContext` inspectable.

6 new deterministic tests (`tests/test_auth_tenancy.py::TestInviteCallback`) — all passing: no-params is a safe no-op (never calls the auth client); an unsupported `type` (e.g. `magiclink`) is rejected without ever calling `verify_otp`, but still stripped from the URL; a successful `type=invite` verification resolves and stores a real-shaped `AuthContext` and strips the URL; an invalid/expired token fails closed with a generic error and still strips the URL; `sign_out()` now clears the `AuthContext` too, not just the session; the module's source contains no `print(`/`logging.`/`logger.` call that could echo a token value. Full suite: **1610 passed, 2 skipped** (1604 + 6).

### What could not be completed this round, and why — precisely, not glossed over

**Supabase Auth dashboard configuration (Site URL, Redirect URLs, Invite email template) could not be changed by this session — no tool in this environment exposes Supabase's Auth/project configuration API** (the Supabase MCP tool surface available here covers database migrations, SQL, advisors, and Auth *user* administration, but not Auth *settings*). This requires the user's own action in the Supabase dashboard. **Exact values to set** (Authentication → URL Configuration):

| Setting | Value |
|---|---|
| Site URL | `https://bid-intelligence-5uusebzvcg6ajrfgvgappot.streamlit.app/` |
| Redirect URLs | add `https://bid-intelligence-5uusebzvcg6ajrfgvgappot.streamlit.app/`; keep `http://localhost:8501/` only if local Streamlit testing still needs it; remove `http://localhost:3000` unless another real application actually uses it |

**Invite email template** (Authentication → Email Templates → Invite user) — replace the action link with:
```html
<a href="{{ .SiteURL }}?token_hash={{ .TokenHash }}&type=invite">Accept invitation</a>
```

**A fresh invitation was deliberately NOT sent this round.** Sending one before the Site URL/template fix above would only reproduce the exact same fragment-based, token-exposing flow that prompted this addendum — the dependency order in the original instructions (configure first, then invite) was preserved rather than executed out of sequence.

**A live end-to-end proof of this new callback code (a real `token_hash`, a real `verify_otp` call, a real resulting session) was not obtained**, for two compounding reasons: (1) the same "Credential Materialization" guardrail that blocked `generate_link` in the prior round would very likely block any other server-side attempt to manufacture a usable token for this real account, and this session does not attempt to work around that; (2) even with dashboard config fixed and a fresh invite sent, the code above is not yet deployed to the live Streamlit Cloud app (`app.py`/`auth_session.py` are modified locally, not committed or pushed) — the real human clicking a real invite link right now would still hit the *old*, undeployed version of the app.

### Recommended next steps, in dependency order

1. **You** configure the Site URL / Redirect URLs / Invite template in the Supabase dashboard, using the exact values above.
2. **You** confirm that's done (or ask me to verify what's checkable — I can re-read `auth.users`/live DB state but not the Auth *settings* themselves, since no tool exposes them for reading either).
3. Decide whether to commit and push this round's code (`app.py`, `auth_session.py`, plus the still-uncommitted Package 3 files from the prior round) so Streamlit Cloud deploys it — this is a real, live-production-affecting action I have not taken without your explicit go-ahead, consistent with this engagement's whole discipline around risky/hard-to-reverse actions.
4. Once deployed and dashboard-configured, I send one fresh invitation (`invite_user_by_email` — the same sanctioned mechanism as before, no direct `auth.users` insert) to the same existing user — no new user, no public signup.
5. You click the link in your own browser; the deployed `handle_invite_callback()` should complete verification, resolve `AuthContext` (organization `emg-internal`, role `owner`), and the app will show a success banner — that is the genuine, live, non-simulated proof the original acceptance plan asked for.
6. Once that live proof exists, the remaining original acceptance-plan items (Dashboard under authenticated scope, opening an authorized bid via the user-scoped client, logout clearing context, and finally deciding whether to remove the legacy `create_bid()` compatibility shim) can be completed for real, not simulated.

---

## Addendum 3: Live Magic-Link Authentication — Genuinely Proven

**Date:** 2026-09-15 (UTC), same day.

### What happened, in order

1. **Corrected the callback type.** `invite_user_by_email()` on the already-confirmed real user returned `422: A user with this email address has already been registered` (Supabase's invite endpoint only works for genuinely new users) — no side effect, confirmed user count stayed at 1. Switched to Supabase's passwordless magic-link sign-in (`sign_in_with_otp`) as the correct mechanism for an existing user, per explicit user direction. Along the way, corrected an initial mistake (`type=magiclink`) to the actual value Supabase's `verify_otp()` expects for this flow (`type=email`), and fixed a real bug the correction surfaced: `verify_otp()` was hardcoding `type="invite"` regardless of the type actually present in the URL. `INVITE_CALLBACK_ACCEPTED_TYPES` is now `("invite", "email")`; `"magiclink"` is explicitly tested as rejected. 2 new/updated tests, full suite green throughout.
2. **Committed and pushed** (`387a046373556ec7c7c76589f8eb18d263cf24da`, exact match between local HEAD and `origin/feature/evidence-explainability`).
3. **Verified the staging deployment** — the automatic redeploy did not pick up the new commit for several minutes; after a manual reboot (by the user), live-verified via two independent probes: `?token_hash=probe&type=email` reached token verification (`"invite verification failed: invalid or expired link"` — accepted, not rejected), while `?token_hash=probe&type=magiclink` was correctly still rejected (`"unsupported callback type: magiclink"`) — confirming the exact corrected code, not an intermediate draft, was live.
4. **Sent exactly one real magic-link email** via `auth_client.get_auth_client().auth.sign_in_with_otp()` (anon client only, `should_create_user=False`, `email_redirect_to` set to the staging URL). The response structurally cannot return a session/token to the caller (`AuthOtpResponse` has `user=None`, `session=None` always) — confirmed live: both fields were `None`. User count confirmed unchanged (still exactly 1) before and after.
5. **The real user clicked the email link in their own browser** and reported: the green **"Invitation accepted for feras@enablemygrowth.com"** banner, then the normal Dashboard, no errors.

### Independent, server-side confirmation (not just the user's own report)

- `auth.users.last_sign_in_at` advanced to a fresh timestamp (`2026-09-15 13:09:26`), matching the moment of the click — proof a genuine new session was established via GoTrue, not merely that a page loaded.
- `tenancy.resolve_organization_context()` re-run against the real user id after the click still resolves correctly: `AuthContext(organization_name='Enable My Growth Internal', role='owner', ...)`.
- Full suite re-run after all of this: **1612 passed, 2 skipped**, zero regressions.
- Security advisor re-run: identical to the prior round — 0 ERROR, 1 INFO (`coaches`, intended), 2 WARN (SECURITY DEFINER functions, reviewed/accepted), 1 WARN (leaked-password protection still disabled, still an open recommendation, not remediated).

### What this does and does NOT prove — stated precisely

**Genuinely, live proven now:** the entire bootstrap and callback mechanism, end to end, through a real human clicking a real emailed link in their own browser — no simulation, no mocks, no SQL-layer claim substitution. This is real.

**Still NOT done, and not claimed:** the interactive application itself does not yet *use* this session for anything. Every page still reads and writes exclusively through the service-role client (`database.get_client()`) — no page calls `auth_client.get_authenticated_client()`, no page checks whether a session exists, and nothing is gated behind login. The Dashboard the user saw after clicking rendered exactly as it always has, via the unauthenticated service-role path, not because RLS-scoped access was exercised through their new session. Proving *that* specifically — a page reading data through the user-scoped client, subject to the live RLS policies, using this real session — is the actual "Interactive Application Cutover" (the original spec's own §15), and remains a distinct, separate, not-yet-authorized step. So are logout-clears-context (no page has a logout control yet) and the legacy `create_bid()` compatibility-shim decision (correctly still in place, since nothing has replaced its one caller's need for it).

---

## Addendum 4: Interactive Cutover (Reads) — Built, Tested, Live-Re-Verified — Not Yet Deployed/Click-Tested

**Date:** 2026-09-15 (UTC), same day, following explicit authorization to proceed with the remaining Package 3 acceptance checks.

### New authenticated-read primitives (`tenancy.py`)

Three new functions, deliberately different in kind from every earlier `tenancy.py` function: they read through `auth_client.get_authenticated_client(access_token)`, not the service-role client, and carry **no `organization_id` argument at all** — whatever comes back is determined entirely by migration 008's RLS policies evaluating the real request, not by an application-level filter.

```python
def list_bids_authenticated(access_token: str) -> list[dict]: ...
def get_bid_authenticated(access_token: str, bid_id: int) -> dict | None: ...
def get_bid_analysis_authenticated(access_token: str, bid_id: int) -> dict: ...  # {"runs": [...], "latest_result": ...}
```

### UI wiring (`app.py`) — additive, invisible unless a session exists

A new "🔐 Authenticated View (Phase 8 Package 3)" panel, rendered immediately after the invite/magic-link callback block, **only when `auth_session.restore_session().ok` is true** — a complete no-op for the existing, still-unauthenticated single-operator flow (every existing page, every existing test, continues reading through the service-role path exactly as before; confirmed by the unchanged full-suite pass count for every other test). The panel shows the signed-in email/organization/role, a **Sign out** button, and a live bid list + bid-detail + analysis-result view built entirely from the three functions above.

**Sign-out handler clears everything the instruction named:** `auth_session.sign_out()` (clears the session dict and the resolved `AuthContext` — already unit-tested) **plus**, explicitly in `app.py`'s own button handler, `st.session_state.pop("active_bid", None)` and `st.session_state.pop("pkg3_selected_bid", None)` (the new panel's own bid-selection cache) — so no user-scoped state of any kind survives a sign-out. Verified two ways: a source-level test confirms the sign-out handler's code contains all three clearing calls (`test_app_py_sign_out_handler_clears_active_bid_and_selection_state`), and the existing `sign_out()` unit tests confirm the auth-module half of the contract.

### Tests

12 new tests (`TestAuthenticatedReads` ×5, `TestLogoutClearsAllUserScopedState` ×2, plus the earlier Addendum 3 work) — full suite: **1619 passed, 2 skipped** (1612 → 1619), `py_compile` clean, `git diff --check` clean, `tests/smoke/test_all_pages_runtime.py` (which renders every page including this new block) still passes unchanged.

### Live re-verification with fresh real data (this round)

**Cross-tenant RLS, both boundaries, re-proven fresh** — a *second*, independent temporary organization/bid (`temp-crosstenant-test-org-2`), created and rolled back in the same transaction:

| Check (real user's real UUID simulated via JWT claim) | Result |
|---|---|
| Own `emg-internal` bids visible | **4** |
| Temp org 2's bid visible | **0** |
| `can_access_bid()` RPC for temp org 2's bid | **`false`** |

Rolled back; confirmed live afterward: `organizations` = 1, `bids` = 4 — zero residue, same as every prior round.

**Application-layer authorization boundary, re-proven fresh:**
- Unauthorized analysis start (fake org, bid 8) → `AccessDeniedError`, zero calls into `analysis_service.start_fast_analysis()`, zero possibility of an LLM call.
- Unauthorized report access (fake org, bid 8, run 1) → `AccessDeniedError`, zero calls into `regenerate_report()`.
- **Authorized** report access (real `emg-internal` org, bid 8, run 1) → succeeded, real 83,317-byte PDF, `%PDF-` header, zero LLM calls (regeneration from snapshot).

### What this round does and does NOT prove — stated as precisely as every prior round

**Genuinely proven, live, with real data:** the RLS policies and the application authorization boundary both continue to hold exactly as designed, re-verified fresh rather than assumed from earlier rounds. The authenticated-read functions are correct by construction (they contain no filter logic of their own to get wrong — RLS is the only thing that can possibly be scoping the result) and are unit-tested against every response shape they handle.

**NOT yet proven live, and not claimed:** this round's new code (the authenticated-read functions and the `app.py` panel) has not been pushed, has not been deployed to staging, and has not been exercised by an actual browser holding a real session — neither the real user's own session (which exists only in their browser, which this session has no access to) nor a session obtained by this agent (which would require either another magic-link email and using this agent's own browser to click it, or some other credential-bearing action — not attempted, consistent with every prior round's discipline around not materializing or consuming credentials without explicit authorization). The Dashboard/bid-open/analysis-result items in the original acceptance checklist are therefore **code-complete and thoroughly tested, but not yet live-click-tested** — the same honest distinction this report has maintained at every step (Addendum 1's positive-case RLS caveat, Addendum 3's "mechanism proven, cutover not yet used" caveat) continues to apply here.

### Legacy `create_bid()` compatibility shim — determination

**Cannot be removed or disabled yet.** This round cut over *reads* (dashboard listing, bid detail, analysis results) to the authenticated path. It did **not** cut over bid *creation* — `pages/... page_new_bid()` (the application's only bid-creation entry point) still calls `database.create_bid()`, unauthenticated, through the service-role path, exactly as before. `_resolve_legacy_organization_id()` remains the only thing keeping that one call site working now that `bids.organization_id` is `NOT NULL`. Removing it now would break the application's only way to create a new bid, for no corresponding benefit — there is no authenticated bid-creation path yet for it to be replaced by. This determination will need revisiting once (and if) a future package cuts over bid creation too.

### Full-suite and advisor, re-run to close out this round

- Full suite: **1619 passed, 2 skipped**.
- Security advisor: unchanged from every prior round this session — 0 ERROR, 1 INFO (`coaches`, intended), 2 WARN (SECURITY DEFINER functions, reviewed/accepted), 1 WARN (leaked-password protection, still an open recommendation for the user's own action).

### Status

**`PHASE 8 TENANT RLS POLICY ENFORCEMENT: NOT YET COMPLETE`** — not because anything failed, but because two acceptance-checklist items (Dashboard/bid reads and analysis-result loading, specifically *through a live browser session*) remain code-complete-and-tested rather than live-click-proven, consistent with this report's discipline throughout. Nothing was merged to `main`. Nothing was pushed this round (no instruction to do so was given, and pushing without a plan to actually live-test the result would just repeat the earlier redeploy-then-wait cycle without new information).

---

## Addendum 5: Mandatory Authentication Gate + First Bounded Interactive Cutover — Live-Proven, Still Partial

**Date:** 2026-09-15 (UTC), same day, following the real human's live magic-link sign-in report ("received and accessed successfully" — the green "Invitation accepted" banner, then the normal Dashboard) and explicit authorization to complete the remaining Package 3 acceptance checks.

### The actual change in kind

Every earlier addendum in this report describes authenticated code that existed *alongside* the unauthenticated service-role path — additive, invisible unless a session already existed. This round is the first that makes authentication **mandatory**: `app.py` now opens with a gate (unauthenticated → sign-in screen only, `st.stop()`; zero organization membership → error + sign-out + `st.stop()`; exactly one membership → auto-resolved; more than one → an explicit `st.selectbox` + `Continue` button, never silently auto-chosen) before any page function, any bid data, or any sidebar navigation can render at all.

### What was cut over in this round

- **`go(page, bid_id=None)`** — the single choke point that ever sets `st.session_state.active_bid` anywhere in the codebase (confirmed via a repo-wide search finding zero other assignment sites) — now calls `tenancy.get_bid_authenticated(_access_token, bid_id)` first and fails closed (`st.error`, no navigation, no state change) for a guessed or cross-tenant `bid_id`.
- **`page_dashboard()` / `page_all_bids()`** — both now read via `tenancy.list_bids_authenticated(_access_token)`, never `database.get_all_bids()`.
- **Bid creation** — both call sites now use `tenancy.create_bid_for_organization(..., organization_id=_ctx.organization_id)`, never `database.create_bid()`. (`_render_extraction_review()`'s own further writes — requirements/outline/documents/bid_brief — were **not yet** cut over in this round; that gap was closed in Addendum 6 below.)
- **UNDERSTAND-stage top-level reads** (`pages/stage_understand.py`) — the bid fetch and both analysis-run/result reads moved to `tenancy.get_bid_authenticated()` / `tenancy.get_latest_analysis_run_authenticated()` / `tenancy.get_latest_analysis_result_authenticated()`. (Three further reads in the same page — `get_bid_brief`, `get_requirements`, `get_documents` — were missed in this round and remained bare service-role calls; also closed in Addendum 6.)
- **Fast-Analysis-start authorization** — `_start_fast_analysis()` now routes through `tenancy.start_fast_analysis_for_organization()`, catching `tenancy.AccessDeniedError`.
- **Logout** — a single shared `_clear_all_user_scoped_state()` function, called from all three "Sign out" buttons (no-access screen, org-selection screen, sidebar), clears the session dict, `AuthContext`, `active_bid`, and every Package-3 UI selection key.

### A real discovery: seven dead `app.py` page functions

While tracing what was and wasn't actually reachable, a repo-wide call-site search (not an assumption from naming) found that `page_bid_overview`, `page_compliance`, `page_tasks`, `page_documents`, `page_outline`, `page_ai_analyst`, `page_deliverables` (plus their shared helper `_auto_populate_services`) have **zero call sites anywhere outside their own `def` line** — the router's alias tuples (e.g. `"tasks","documents","deliverables"`) all resolve to the `pages/*.py` module equivalents, never to these same-named leftover functions from a pre-`pages/`-package reorganization. They were left untouched and explicitly out of scope, per direct instruction, in every subsequent round including this one.

### Live re-verification this round

- Cross-tenant RLS re-proven fresh with a second independent temporary org/bid, rolled back with zero residue afterward (`organizations` = 1, `bids` = 4, matching the live pre-test baseline).
- Application-layer authorization boundary re-proven fresh: unauthorized analysis start and unauthorized report access both denied with zero downstream calls; authorized report access succeeded with a real regenerated PDF and zero LLM calls.
- Full suite: **1635 passed, 2 skipped**, run twice for stability. `py_compile` and `git diff --check` clean. Security advisor unchanged (0 ERROR, 1 INFO `coaches`-no-policy intended, 2 WARN SECURITY DEFINER functions reviewed/accepted, 1 WARN leaked-password protection still an open recommendation).

### Status at the end of this round — explicitly NOT Package 3 PASS

A large remaining reachable service-role surface still existed across the five workflow-stage pages (`stage_decide`, `stage_build`, `stage_check`, `stage_submit`, `stage_debrief`), `settings_firm.py`, and `pages_extra.py` — all still reading and writing through `database.py`'s service-role client despite the auth gate now being mandatory in front of them. This was reported honestly as an **intermediate checkpoint, not Package 3 PASS** — exactly the determination the user then confirmed and used to scope Addendum 6's comprehensive final pass, below.

---

## Addendum 6: Final Comprehensive Interactive-Surface Cutover — Package 3 Acceptance Evidence

**Date:** 2026-09-15 (UTC), same day, per the explicit final-pass instruction: cut over every remaining service-role call reachable from normal interactive UI in `stage_decide`, `stage_build`, `stage_check`, `stage_submit`, `stage_debrief`, `settings_firm.py`, and `pages_extra.py` (including Executive View's second bid-listing surface), leave the seven confirmed-dead `app.py` functions untouched, retain the legacy `database.create_bid()` shim as internal/test-only, and stop before commit/push pending this report.

### (1) Exact files changed

| File | Nature of change |
|---|---|
| `tenancy.py` | Added ~30 new functions: full authenticated CRUD primitives for `requirements`, `tasks`, `outline_sections`, `deliverables`, `clarifications` (category A); `debriefs`, `bid_decisions` (category A, partial — no delete policy exists for either); `content_library` (category A, bid-scoped only) plus `semantic_library_search_authenticated`; select-only authenticated reads for `documents`, `document_versions`, `bid_briefs`, plus an aggregate `get_readiness_authenticated` (category B); organization-scoped `firm_profiles` CRUD (category D); five new **privileged, tenant-authorization-gated wrappers** for the writes that must stay server-side under the currently-live RLS policy set — `upload_document_for_organization`, `set_document_mandatory_for_organization`, `create_document_record_for_organization`, `save_bid_brief_for_organization` (all `require_bid_access()` first, matching the required "verified tenant authorization → explicit service-role client → privileged operation" architecture) — plus organization-scoped `content_library` privileged variants (`list_library_items_for_organization`, `upsert_library_item_for_organization`, `delete_library_item_for_organization`) for the one page that needs a cross-bid, cross-item view no RLS policy expresses. |
| `pages/stage_decide.py` | Fully rewired: `get_bid`, `get_requirements`, `get_clarifications`, `get_bid_decision`, `get_firm_profile`, `get_bid_brief` → authenticated reads; `upsert_requirement`, `upsert_clarification`, `save_bid_decision` (×2), `update_bid` (×2) → authenticated writes. |
| `pages/stage_build.py` | Fully rewired: 12 reads/writes → authenticated (`get_bid`, `get_requirements`, `get_outline`, `upsert_section` ×2, `delete_section`, `get_deliverables`, `upsert_deliverable`, `delete_deliverable`, `get_documents`, `get_tasks`, `upsert_task`, `delete_task`, `get_firm_profile`, `semantic_library_search`). `save_upload` (Storage + `documents`, category B) → routed through the new tenant-authorized `tenancy.upload_document_for_organization()`, not left as a bare call. |
| `pages/stage_check.py` | Fully rewired: all 6 call sites were reads only (`get_bid`, `get_requirements`, `get_documents`, `get_outline`, `get_clarifications`, `get_bid_brief`) → authenticated; no writes existed in this file. |
| `pages/stage_submit.py` | Fully rewired: `get_bid`, `get_requirements`, `get_documents`, `get_outline` → authenticated reads; `update_bid` → authenticated write; `upsert_document` (document mandatory-flag classification) → `tenancy.set_document_mandatory_for_organization()`; `save_upload` → `tenancy.upload_document_for_organization()`. |
| `pages/stage_debrief.py` | Fully rewired: `get_bid`, `get_debriefs` → authenticated reads; `upsert_debrief`, `update_bid` → authenticated writes. |
| `pages/settings_firm.py` | Fully rewired, organization-scoped: `get_firm_profile` → `tenancy.get_firm_profile_authenticated(_token, _org_id)`; `save_firm_profile` → `tenancy.save_firm_profile_authenticated(_token, _org_id, ...)`. |
| `pages_extra.py` | The only two *reachable* functions besides `page_team_roster()` were rewired: `page_content_library()` (`get_library_items`/`upsert_library_item`/`delete_library_item` → the new organization-scoped privileged wrappers) and `page_exec_dashboard()` (`get_all_bids()` → `tenancy.list_bids_authenticated()` — the flagged "second bid-listing surface"; `get_requirements`/`get_tasks`/`get_clarifications`/`get_debriefs`/`get_firm_profile` → authenticated equivalents). Five further functions in this same file (`page_proposal_analyzer`, `page_clarifications`, `page_section_drafter`, `page_submission_assembler`, and this file's own `page_debrief` — distinct from the live `pages.stage_debrief.page_debrief`) were confirmed, by the same repo-wide call-site method as the seven `app.py` functions, to have **zero real call sites** — imported into `app.py`'s namespace but never actually invoked by the router — and were left untouched, documented as category D. |
| `app.py` | One additional discovery beyond the named file list: `_render_extraction_review()` (the AI-extraction bid-creation confirmation screen, reachable from `page_new_bid()`) was still writing requirements/outline/documents/bid_brief via bare service-role calls even though bid creation itself had already been cut over in Addendum 5. Closed: `save_upload` → `_tenancy.upload_document_for_organization()`; `upsert_bid_brief` → `_tenancy.save_bid_brief_for_organization()`; `upsert_requirement` → `_tenancy.upsert_requirement_authenticated()`; `upsert_document` (checklist rows, no file bytes) → `_tenancy.create_document_record_for_organization()`; `upsert_section` → `_tenancy.upsert_section_authenticated()`. |
| `pages/stage_understand.py` | Second additional discovery: `page_understand()`'s `get_bid_brief`, `get_requirements`, `get_documents` calls were still bare (only the top bid fetch and the analysis-run/result reads had been cut over in Addendum 5) — closed via the existing `tenancy.get_bid_brief_authenticated` / `get_requirements_authenticated` / `get_documents_authenticated`. Unused bare imports removed. |
| `tests/test_final_interactive_cutover.py` | New — 18 deterministic tests: source-level "no forbidden bare call" checks per rewired file (including the two additional-discovery fixes), a live reachability re-confirmation of the five newly-classified dead `pages_extra.py` functions, and behavioral (mocked) tests proving every new privileged wrapper calls `require_bid_access()`/scopes its read before touching the service-role client, and raises `AccessDeniedError` with zero underlying `database.py` call made when that check fails. |
| `tests/test_app_analysis_panel.py` | One test updated: its patches now target `pages.stage_understand.tenancy.get_bid_brief_authenticated` / `get_requirements_authenticated` / `get_documents_authenticated` instead of the now-removed bare imports. |

Not touched: `database.py` (no service-role function signatures changed — every new privileged wrapper calls the existing functions unmodified), any migration/SQL, Storage/report-object authorization (explicitly deferred to Package 4), Fast Analysis / Deep Verify / PDF content / scoring logic, and all seven confirmed-dead `app.py` functions.

### (2) Classification of every formerly reachable service-role surface

Every table's RLS category, as it actually is in the live database (confirmed via `pg_policies`, not assumed from the migration file):

| Table | Live RLS (authenticated role) | Classification this pass applied |
|---|---|---|
| `bids` | SELECT/INSERT/UPDATE (`is_organization_member`), no DELETE | **A** — cut to authenticated everywhere reachable; DELETE has no policy (intentional, CASCADE blast radius) and stays server-only, matching migration 008's own design |
| `requirements`, `tasks`, `outline_sections`, `deliverables`, `clarifications` | full CRUD (`can_access_bid`) | **A** — fully cut to authenticated |
| `debriefs` | SELECT/INSERT/UPDATE, no DELETE | **A (partial)** — cut to authenticated; no delete UI action exists anywhere in the product, so nothing was left uncut |
| `bid_decisions` | SELECT/INSERT only | **A (partial, append-only by design)** — cut to authenticated; `save_bid_decision_authenticated` never attempts UPDATE, matching the pre-existing product design |
| `content_library` | full CRUD, but `bid_id IS NOT NULL` required | **A (bid-scoped)** for single-bid reads/writes (`stage_build.py`'s Section Drafter tab); **C (privileged, organization-scoped)** for the cross-bid browse view (`pages_extra.py`'s Content Library page), since no RLS policy expresses "every row across many of my own bids plus global rows" — closed server-side by scoping to the caller's own `bid_id`s explicitly, not left as an ungated whole-table read |
| `documents`, `document_versions`, `bid_briefs`, `analysis_runs`, `analysis_results` | SELECT only | **B** — reads cut to authenticated everywhere reachable; writes stay server-side (Storage-adjacent, Package 4 territory) but are now gated by an explicit `require_bid_access()` check immediately before the privileged call, via the new `upload_document_for_organization` / `set_document_mandatory_for_organization` / `create_document_record_for_organization` / `save_bid_brief_for_organization` wrappers, rather than a bare, ungated convenience call |
| `firm_profiles` | full CRUD, organization-scoped | **D** — cut to authenticated, organization-scoped (`settings_firm.py`, `pages_extra.py`'s Executive Dashboard header/export) |
| `coaches` | RLS enabled, **no policy at all** | **C (unchanged)** — correctly stays server-side (`page_team_roster()`, `page_exec_dashboard()`'s roster summary); no `organization_id` or `bid_id` column exists to scope it by, so the only boundary is the app-wide mandatory auth gate — exactly as documented in every prior round, not revisited or redesigned here |
| `organizations`, `organization_members` | SELECT-own only | unchanged — not written to by any application code path |

### (3) Remaining reachable service-role call sites, and why each is legitimate

A repo-wide, reachability-verified scan (every `database.py` function name searched across `app.py`, `pages_extra.py`, and every `pages/*.py` file, each hit classified as inside a confirmed-dead function or not) found exactly these remaining bare service-role calls in reachable code, after this pass:

1. **`app.py:32` — `init_db()`** — a documented no-op (`"""No-op — schema is created via supabase_schema.sql in Supabase dashboard."""`, `pass`). Zero risk, not a real data operation.
2. **`pages_extra.py`, `page_team_roster()` — `get_coaches()`, `upsert_coach()` (×2), `delete_coach()`** — category C, `coaches` has no RLS policy and no tenant column to scope by; correctly server-side, bounded by the mandatory auth gate.
3. **`pages_extra.py`, `page_exec_dashboard()` — `get_coaches()`** (roster summary section) — same category C reasoning as above.
4. **`pages/stage_understand.py`'s `_render_fast_analysis_panel()` — `download_file()` (aliased `_download_stored_file`)** — Storage read for a previously-generated report PDF; explicitly Package 4 territory ("Storage/report-object authorization remains Package 4; do not redesign Storage in this pass"), untouched by design.

No other bare service-role call exists in any reachable function across `app.py`, `pages/*.py`, or `pages_extra.py`. Every remaining service-role write (document uploads, document mandatory-flag classification, bid-brief writes, the cross-bid content-library view) is now reached exclusively through a `tenancy.py` wrapper that calls `require_bid_access()` (or, for `content_library`'s cross-bid view, explicitly scopes the read to the caller's own `bid_id`s) immediately before touching the privileged client — satisfying "Privileged/background operations: verified tenant authorization → explicit service-role client → privileged operation" for every one of them, not merely for the ones named in the original instruction list.

**Dead code, explicitly not counted, per instruction:** the seven `app.py` functions from Addendum 5, plus five further `pages_extra.py` functions newly confirmed dead this round (`page_proposal_analyzer`, `page_clarifications`, `page_section_drafter`, `page_submission_assembler`, `pages_extra.page_debrief`) — all imported but never called by the router, confirmed via the same repo-wide call-site search method, not assumed from naming.

### (4) Authenticated INSERT/UPDATE/DELETE evidence — live, real database, zero residue

Executed directly against the live project (`whonalbdpbubaqhpzrnw`) inside one transaction, ended with `ROLLBACK` regardless of outcome: fixture rows (a temp bid under the real `emg-internal` organization, a temp second organization + bid for cross-tenant checks) created as the connecting role, then `request.jwt.claims`/`SET LOCAL ROLE authenticated` set to simulate the real user (`ed5ccf11-8f6e-4975-85db-f2d1cf84660b`, real owner of `emg-internal`) for every subsequent statement — the same SQL-layer JWT claim simulation technique used for every prior round's live RLS proofs, now extended to writes.

**Own-organization writes, all ALLOWED as required:**

| Operation | Table | Result |
|---|---|---|
| INSERT | `requirements`, `tasks`, `outline_sections`, `deliverables`, `clarifications`, `content_library`, `bid_decisions`, `firm_profiles` | ✅ allowed (8/8) |
| UPDATE | `requirements`, `tasks`, `outline_sections`, `deliverables`, `clarifications`, `content_library`, `bids` | ✅ allowed (7/7) |
| DELETE | `requirements`, `tasks`, `outline_sections`, `deliverables`, `clarifications`, `content_library` | ✅ allowed (6/6) |
| UPDATE | `bid_decisions` (no update policy exists — append-only by design) | ✅ correctly denied, 0 rows |
| DELETE | `bids` (no delete policy exists — intentional) | ✅ correctly denied, 0 rows |
| UPDATE | `bids.organization_id` on the caller's own bid → the other org (tenant-escape attempt) | ✅ correctly denied — `new row violates row-level security policy for table "bids"`; post-check confirms `organization_id` unchanged |

### (5) Cross-tenant write-denial evidence

Every write above was repeated against a temporary **second** organization's bid (owned by neither the caller nor anything they belong to):

| Operation | Tables attempted | Result |
|---|---|---|
| INSERT (bid_id = other org's bid) | `requirements`, `tasks`, `outline_sections`, `deliverables`, `clarifications`, `content_library`, `bid_decisions`, `bids` (new bid inside the other org), `firm_profiles` | ✅ denied, all 9 — RLS policy violation on every one |
| UPDATE (pre-seeded rows in the other org) | `requirements`, `tasks`, `outline_sections`, `deliverables`, `clarifications`, `content_library`, `bids` | ✅ denied, 0 rows affected on all 7 |
| DELETE (pre-seeded rows in the other org) | `requirements`, `tasks`, `outline_sections`, `deliverables`, `clarifications`, `content_library`, `bids` | ✅ denied, 0 rows affected on all 7 |

**Total: 48/48 checks passed exactly as expected** — every intentional ALLOW allowed, every intentional DENY denied, including the two fail-closed-by-design cases (`bids` DELETE, `bid_decisions` UPDATE) and the tenant-escape (organization reassignment) attempt.

**Zero residue, confirmed afterward with a fresh query:** `organizations` rows matching the temp slug = 0, `bids` rows matching the temp titles = 0, `requirements` rows matching the proof text = 0, `firm_profiles` rows matching the temp company name = 0.

### (6) Regression-suite result

Full suite (including the 18 new tests this round added): **1653 passed, 2 skipped**, run twice consecutively for stability — identical result both times. `python -m py_compile` clean on every changed file. `git diff --check` clean (only pre-existing CRLF/LF line-ending notices, not errors).

### (7) Security-advisor result

Identical to every prior round in this engagement — confirming this round's application-layer changes introduced no new database-level finding (no migration or schema change was made):

- **0 ERROR**
- **1 INFO** — `coaches` has RLS enabled with no policy (intended, category C, documented above)
- **2 WARN** — `can_access_bid()` / `is_organization_member()` are `SECURITY DEFINER` and callable via RPC by any signed-in user (intentional and safe: both are `STABLE`, side-effect-free, return only a boolean about the caller's own access, fixed `search_path`, from migration 008 — reviewed and accepted in every prior round)
- **1 WARN** — leaked-password protection still disabled (a general Supabase Auth setting, unrelated to tenancy/RLS, still an open recommendation for the user's own action, out of this package's scope)

Performance advisor: unindexed-foreign-key INFO findings and one auth-RLS-initplan WARN (`organization_members`), all pre-existing schema-level characteristics from migration 008, unrelated to and unaffected by this round's application-layer-only changes — not remediated, out of scope.

### Final determination (superseded in part by Addendum 7 below — `coaches`'s classification here was accepted as an open item, not a pass, and subsequently resolved)

Every normal interactive read and write reachable from the live application now goes through the authenticated, RLS-backed client, or — where the live RLS policy set genuinely has no authenticated path for a table (`documents`/Storage writes, `bid_briefs` writes, `content_library`'s cross-bid browse view) — through an explicit, tenant-authorization-gated privileged wrapper in `tenancy.py`, never a bare, ungated service-role convenience call. `coaches` was left classified as category C (server-only, bounded only by the app-wide auth gate) at the time this section was written — that classification was challenged and replaced by real organization tenancy in Addendum 7. Executive View no longer uses a second service-role bid listing. Firm Profile is constrained to the authenticated organization. DECIDE/BUILD/CHECK/SUBMIT/DEBRIEF reads and writes fail closed for guessed cross-tenant bid IDs (proven live, both at the RLS layer and via `go()`'s own authorization check). Fast Analysis, Deep Verify, PDF content, and scoring logic were not touched. Storage/report-object authorization remains, as instructed, Package 4.

All normal interactive access now uses the authenticated/RLS path, and the remaining service-role use is deliberately privileged and authorization-gated — the condition the original instructions set for recommending the next step. Per this round's explicit instruction, **this report does not itself declare Package 3 PASS** and **nothing has been committed or pushed**; that determination is left to the user's own review of this addendum. The recommended next step, once reviewed, is the staging push and a live click-through (consistent with the discipline this report has maintained at every prior round: code-complete-and-tested is reported precisely as that, not conflated with live-click-proven).

---

## Addendum 7: `coaches` Tenancy Resolution — Migration 009, Live-Proven

**Date:** 2026-09-15 (UTC), same day, following the explicit instruction that Addendum 6's classification of `coaches` as category C ("an app-wide authentication gate alone is not a tenant authorization boundary") was not accepted as sufficient, and that its actual semantics needed to be audited from the real schema and code rather than assumed.

### The semantic audit — answered explicitly, from evidence, not assumption

**1. Is `coaches` intended to be organization-owned team/personnel data? YES.** Its live columns are `name, credentials, icf_level, sectors, languages, location, availability, email, phone, cv_summary, reference_contact, notes` — real personal contact information (a direct email and phone number per row) and a named client reference contact, not abstract or categorical reference values. The 4 live rows are real named personnel with real credentials (e.g. `M. W. (Mina Wasfi)`, Professional Certified Coach (ICF), Hogan Certified Assessor). These rows are populated by the application's own "Proposal Analyzer" feature (`pages_extra.py`'s `coaches_found` auto-population, sourced from a firm's **own past proposal documents** — see `page_proposal_analyzer()`) — i.e. this is one organization's own personnel roster, assembled from that organization's own submitted work product.

**2. Is it genuinely platform-global reference data? NO.** There is no sense in which one named individual's direct contact details and a specific client's reference contact are a fact true for every tenant on the platform, the way e.g. a list of ICF certification levels would be. Exposing this to a different, unrelated organization's signed-in members would be an ordinary, real information-disclosure vulnerability (personal contact data plus a named third-party reference), not a hypothetical one — exactly the scenario the instruction described.

**3. Which reachable UI operations read/write it?** `pages_extra.page_team_roster()` — the only reachable page whose entire purpose is this table: full CRUD (list with roster/availability/language metrics, add via a form, edit via a form, and a real, wired `delete_coach(eid)` call). `pages_extra.page_exec_dashboard()` — read-only (roster availability summary counts, a name-badge list, and the PDF export). `pages_extra.page_proposal_analyzer()` also reads/writes `coaches`, but was independently confirmed dead code in Addendum 6 (zero call sites outside its own `def` line) — not a live interactive surface.

**Conclusion: organization-owned.** The tenancy model was completed for real, not assumed or faked.

### Migration `009_coaches_organization_tenancy.sql` — new file, does not modify 001-008

Applied live to project `whonalbdpbubaqhpzrnw` via the Supabase migration tool (not raw `execute_sql`, consistent with every prior schema change in this engagement):

- `alter table public.coaches add column if not exists organization_id uuid references public.organizations(id);` — added nullable first, exactly like migration 007 did for `bids.organization_id`.
- `create index if not exists idx_coaches_organization on public.coaches (organization_id);`
- Deterministic backfill: `update public.coaches set organization_id = (select id from organizations where slug = 'emg-internal') where organization_id is null;` — no UUID hardcoded, resolved through the same unique slug migration 007 established.
- A `do $$ ... $$` safety block aborts the entire migration (rolling back everything above it) if any row is still `NULL` after the backfill — the same pattern migration 007 used, not a new invention.
- `alter table public.coaches alter column organization_id set not null;` — ownership made mandatory only after the safety check passed.
- Four RLS policies (`coaches_select_org_member`, `coaches_insert_org_member`, `coaches_update_org_member`, `coaches_delete_org_member`), all `to authenticated`, all using the **existing** `is_organization_member(organization_id)` helper from migration 008 verbatim — no new SECURITY DEFINER function was written; `coaches` is organization-scoped like `firm_profiles`, not bid-scoped, so `can_access_bid()` does not apply. A DELETE policy was included (unlike `firm_profiles`, which has none) because `delete_coach()` is a real, wired UI action in `page_team_roster()` today.

**Data preserved exactly:** all 4 pre-existing coach rows retained their `id`, `name`, and every other field unchanged; all 4 backfilled to `emg-internal`'s organization id (`4326b564-8cc5-4463-9304-9a589f08cc91`), confirmed by direct query immediately after applying the migration.

### Code changes

`tenancy.py` — three new functions, mirroring `firm_profiles`'s organization-scoped pattern: `get_coaches_authenticated(access_token)`, `upsert_coach_authenticated(access_token, organization_id, data)` (a genuinely new row is explicitly stamped with the caller's own `organization_id` server-side — never trusted from the caller's own data dict — while an update relies on RLS's own `USING` clause to confine it to a row the caller's organization already owns), `delete_coach_authenticated(access_token, coach_id)`.

`pages_extra.py` — `page_team_roster()` and `page_exec_dashboard()`'s roster-summary section both cut over from `database.get_coaches()` / `upsert_coach()` / `delete_coach()` to the three functions above; the now-unused local `from database import get_coaches` import in `page_exec_dashboard()` was removed. `page_proposal_analyzer()` (confirmed dead) was left untouched, still importing the original bare `database.py` functions, so it continues to compile.

### Required verification — repeated, and extended for `coaches`

**Live database proof (own-organization + cross-tenant), same SQL-layer JWT simulation technique as every prior round, one transaction, rolled back regardless of outcome:**

| Check | Result |
|---|---|
| own-org SELECT (the 4 pre-existing `emg-internal` rows) | ✅ all 4 visible |
| cross-tenant SELECT (a seeded other-organization coach row) | ✅ 0 visible |
| own-org INSERT | ✅ allowed |
| own-org UPDATE | ✅ allowed |
| own coach: reassign `organization_id` to the other org (tenant-escape attempt) | ✅ denied — `new row violates row-level security policy for table "coaches"`; post-check confirms `organization_id` unchanged |
| own-org DELETE (`delete_coach()` is a real, wired UI action, so intentionally user-facing) | ✅ allowed |
| cross-tenant INSERT (`organization_id` = the other org) | ✅ denied |
| cross-tenant UPDATE (the seeded other-organization row) | ✅ denied, 0 rows |
| cross-tenant DELETE (the seeded other-organization row) | ✅ denied, 0 rows |

**10/10 checks passed exactly as expected.** Zero residue confirmed afterward with a fresh query: the temporary organization and every temporary/attempted coach row are gone; `coaches` contains exactly the original 4 rows, unchanged.

**Full regression suite:** 4 new mocked/behavioral tests for the new `tenancy.py` coach functions (`TestCoachesOrganizationTenancy`), plus 2 updated source-level assertions in the existing `TestNoRemainingBareServiceRoleCalls` test (the old assertion that `page_exec_dashboard()` correctly kept `get_coaches()` bare was itself now the stale claim, and was corrected rather than deleted) — **1657 passed, 2 skipped**, run twice consecutively for stability, identical both times.

**Compile / diff:** `python -m py_compile` clean on every changed file. `git diff --check` clean (only pre-existing CRLF/LF notices).

**Security advisor:** the `rls_enabled_no_policy` INFO finding for `coaches` (present in every prior round's advisor run) is now **gone** — resolved, not merely unremarked. Remaining findings unchanged from every prior round: 0 ERROR, 2 WARN (the same reviewed/accepted `SECURITY DEFINER` RPC findings — this migration reused the existing helper function rather than adding a new one, so no new instance of this finding was created), 1 WARN (leaked-password protection, unrelated, still open).

### Final reachable service-role audit — repeated in full, not assumed carried over

A repo-wide, reachability-verified scan (every `database.py` function name searched across `app.py`, `pages_extra.py`, and every `pages/*.py` file, each hit classified as inside a confirmed-dead function or not) was re-run after this round's changes. Exactly two bare service-role calls remain in reachable code, both previously identified and both unchanged by this round:

1. **`app.py:32` — `init_db()`** — a documented no-op (`pass`). Zero risk, not a data operation.
2. **`pages/stage_understand.py`'s `_render_fast_analysis_panel()` — `download_file()` (aliased `_download_stored_file`)** — a Storage read for a previously-generated report PDF. **Explicitly Package 4 scope**, per this round's own instruction not to redesign Storage/report-object authorization here; untouched by design.

`coaches` no longer appears in this list at all — every reachable read and write goes through the new authenticated, organization-scoped functions above. **Zero ordinary interactive database reads or writes remain through the service-role client.** Every remaining service-role use in the entire reachable application is either the documented no-op, the documented Package-4 Storage read, or one of the explicitly privileged, tenant-authorization-gated `tenancy.py` wrappers established in Addendum 6 (each preceded by `require_bid_access()` or, for `coaches`/`firm_profiles`, scoped by an explicit `organization_id` the caller's own resolved `AuthContext` supplied, never a value trusted from the request body).

Fast Analysis, Deep Verify, PDF content, scoring, and procurement intelligence behavior were not touched. Package 4 was not started. **Nothing has been committed or pushed.**
