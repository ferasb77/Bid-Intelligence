# Bid Intelligence — Phase 8 Remediation Package 3: Tenant RLS Policy Enforcement & Authenticated Access Cutover

**Date:** 2026-09-15 (UTC)
**Status:** `TENANT RLS POLICIES LIVE — AUTHENTICATED CUTOVER PENDING USER BOOTSTRAP`
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
