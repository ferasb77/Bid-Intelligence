# Migration 028 Production Commissioning Package

**Target Database**: Supabase Production (`whonalbdpbubaqhpzrnw`)
**Target Migration**: `migrations/028_restrict_analysis_results_snapshot_select.sql`
**Candidate SQL SHA-256**: `7b5a668d7d320a448e60615585741ed2d07c4c4a3ff88c6380abd658b2c0153c` (1,849 bytes)
**Companion Test**: `tests/test_migration_028_analysis_results_privileges.py`
**Status**: CONSOLIDATED SPECIFICATION / READY FOR TWO-FINDING CONFIRMATION (DO NOT APPLY DDL)

---

## 1. Candidate SQL Identity & Privilege Design

### Candidate Artifact Identification
* File: `migrations/028_restrict_analysis_results_snapshot_select.sql`
* Byte Size: `1,849` bytes
* SHA-256 Digest: `7b5a668d7d320a448e60615585741ed2d07c4c4a3ff88c6380abd658b2c0153c`
* **Candidate Status**: This SHA-256 is the cryptographic identifier of the **candidate local migration text** proposed for production review. It is not assumed to be mathematical proof of byte-for-byte identity with what was manually pasted into the disposable project `qsycsgwjzmvlgtphuoqd` SQL Editor, because web dashboard executions do not persist input query hashes.

### Approved Migration SQL (Immutable Text)
```sql
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
```

### Privilege Scope & Non-SELECT Invariant
- **SELECT-Specific Remit**: Migration 028 alters **only SELECT privileges**. Non-SELECT table privileges (e.g. `INSERT`, `UPDATE`, `DELETE` grants held by `service_role` or other roles) are completely untouched. Unrelated non-SELECT privileges must never fail Migration 028 commissioning.
- **Role Permissions**:
  - `authenticated`: Granted column-level `SELECT` on exactly 6 columns: `id`, `run_id`, `bid_id`, `structured_intelligence`, `fact_origins`, `report_content_snapshot`.
  - `anon`: Revoked of all `SELECT` privileges (table-level and column-level).
  - `service_role`: Retains full table-level and column-level `SELECT` access, including internal snapshots.

---

## 2. Distinction: Column Privileges vs. Tenant-Row Isolation (RLS)

PostgreSQL implements security via two distinct, complementary enforcement layers:
1. **Column-Level Permissions** (`has_column_privilege`): Restricts **which columns** a role can name in a query. If an unauthorized column is projected, PostgreSQL rejects the query at parse/plan time with SQLSTATE `42501` (`insufficient_privilege`).
2. **Row-Level Security Policies** (`pg_policy`): Restricts **which rows** a role can read, dynamically applying tenant ownership filters (`organization_id`/`bid_id`).

Migration 028 configures Layer 1 (Column-Level Permissions) to prevent tenant users from projecting internal raw text snapshots (`fast_analysis_result_snapshot`). Existing Layer 2 (RLS) policies are completely unmodified.

---

## 3. Read-Only Production Baseline & Verification SQL (pg_catalog Only)

The owner must execute these read-only diagnostic queries in the Supabase SQL Editor for production project `whonalbdpbubaqhpzrnw`. These queries query only `pg_catalog` (no `information_schema`); they do not access or expose customer content.

### Query 0: PostgreSQL Server Version Probe
```sql
-- Check server version to choose version-compatible inheritance query (5A vs 5B)
SELECT
    current_setting('server_version_num')::integer AS server_version_num,
    version() AS server_version;
```
- If `server_version_num >= 160000`, run **Query 5A** (PostgreSQL 16+ `inherit_option`).
- If `server_version_num < 160000`, run **Query 5B** (PostgreSQL 15 and earlier legacy `rolinherit`).

### Query 1: Relation OID, Namespace, & RLS State
```sql
-- Properly qualified relation OID lookup for RLS state
SELECT
    c.oid AS relation_oid,
    n.nspname AS schema_name,
    c.relname AS table_name,
    c.relrowsecurity AS has_rls,
    c.relforcerowsecurity AS force_rls
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.oid = 'public.analysis_results'::regclass;
```
*Expected Result*: Exactly 1 row with `schema_name = 'public'`, `table_name = 'analysis_results'`, `has_rls = true`.

### Query 2: Active Row-Level Security Policies
```sql
-- Enumerate all RLS policies via pg_policy
SELECT
    pol.polname AS policy_name,
    CASE pol.polpermissive WHEN true THEN 'PERMISSIVE' ELSE 'RESTRICTIVE' END AS policy_kind,
    CASE pol.polcmd
        WHEN 'r' THEN 'SELECT'
        WHEN 'a' THEN 'INSERT'
        WHEN 'w' THEN 'UPDATE'
        WHEN 'd' THEN 'DELETE'
        WHEN '*' THEN 'ALL'
    END AS command_scope,
    ARRAY(
        SELECT r.rolname
        FROM unnest(pol.polroles) AS role_oid
        JOIN pg_roles r ON r.oid = role_oid
    ) AS target_roles,
    pg_get_expr(pol.polqual, pol.polrelid) AS row_filter_qual,
    pg_get_expr(pol.polwithcheck, pol.polrelid) AS with_check_qual
FROM pg_policy pol
WHERE pol.polrelid = 'public.analysis_results'::regclass
ORDER BY pol.polname;
```
*Expected Result*: Verifies that tenant-row isolation policies exist and remain completely unmodified by Migration 028.

### Query 3: Non-Dropped User Columns & Effective SELECT Privileges
```sql
-- Enumerate all non-dropped user columns and calculate effective SELECT privileges
SELECT
    a.attnum,
    a.attname AS column_name,
    format_type(a.atttypid, a.atttypmod) AS data_type,
    a.attnotnull AS is_not_null,
    r.role_name,
    has_table_privilege(r.role_name, c.oid, 'SELECT') AS effective_table_select,
    has_column_privilege(r.role_name, c.oid, a.attname, 'SELECT') AS effective_column_select
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid
CROSS JOIN (VALUES ('anon'), ('authenticated'), ('service_role')) AS r(role_name)
WHERE c.oid = 'public.analysis_results'::regclass
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY a.attnum, r.role_name;
```

#### Pre-Migration 028 Expected Baseline (Query 3)
- `anon`: `effective_table_select = true`, `effective_column_select = true` for all 10 columns.
- `authenticated`: `effective_table_select = true`, `effective_column_select = true` for all 10 columns.
- `service_role`: `effective_table_select = true`, `effective_column_select = true` for all 10 columns.

#### Post-Migration 028 Expected Outcome (Query 3)
- `anon`:
  - `effective_table_select = false`
  - `effective_column_select = false` for **ALL 10 columns**.
- `authenticated`:
  - `effective_table_select = false`
  - `effective_column_select = true` for **EXACTLY the 6 approved columns**:
    - `id`, `run_id`, `bid_id`, `structured_intelligence`, `fact_origins`, `report_content_snapshot`
  - `effective_column_select = false` for the **4 internal columns**:
    - `fast_analysis_result_snapshot`, `full_analysis_result`, `check_coverage_result`, `created_at`
- `service_role`:
  - `effective_table_select = true`
  - `effective_column_select = true` for **ALL 10 columns**.

### Query 4: Recorded Table and Column SELECT ACLs (relacl, attacl, and aclexplode including PUBLIC)
```sql
-- Table-level recorded SELECT ACLs
SELECT
    'table' AS grant_level,
    NULL AS column_name,
    COALESCE(grantee.rolname, 'PUBLIC') AS grantee,
    grantor.rolname AS grantor,
    e.privilege_type,
    e.is_grantable
FROM pg_class c
CROSS JOIN LATERAL aclexplode(c.relacl) e
JOIN pg_roles grantor ON grantor.oid = e.grantor
LEFT JOIN pg_roles grantee ON grantee.oid = e.grantee
WHERE c.oid = 'public.analysis_results'::regclass
  AND e.privilege_type = 'SELECT'
UNION ALL
-- Column-level recorded SELECT ACLs
SELECT
    'column' AS grant_level,
    a.attname AS column_name,
    COALESCE(grantee.rolname, 'PUBLIC') AS grantee,
    grantor.rolname AS grantor,
    e.privilege_type,
    e.is_grantable
FROM pg_class c
JOIN pg_attribute a ON a.attrelid = c.oid
CROSS JOIN LATERAL aclexplode(a.attacl) e
JOIN pg_roles grantor ON grantor.oid = e.grantor
LEFT JOIN pg_roles grantee ON grantee.oid = e.grantee
WHERE c.oid = 'public.analysis_results'::regclass
  AND a.attnum > 0
  AND NOT a.attisdropped
  AND e.privilege_type = 'SELECT'
ORDER BY grant_level, column_name NULLS FIRST, grantee, privilege_type;
```
*Expected Pre-028*: Recorded table `SELECT` grants for `anon` and `authenticated`.
*Expected Post-028*:
- **No surviving table-level SELECT for `anon`**.
- **No surviving column-level SELECT for `anon`**.
- **Authenticated SELECT access to exactly the six approved columns**.
- **No authenticated SELECT access to private columns**.
- **No unexpected `PUBLIC` SELECT grant**.
- *Note*: Non-SELECT privileges (e.g. `INSERT`, `UPDATE`, `DELETE` held by `service_role` or table owner) are explicitly ignored and do not fail verification.

### Query 5A: Transitive Role Inheritance & Effective Parent SELECT Privileges (PostgreSQL 16+)
*Use when `current_setting('server_version_num')::integer >= 160000`*. Traverses role membership edges strictly where `pg_auth_members.inherit_option IS TRUE`, outputting `inherit_option`, cycle-protected paths, and evaluating parent table/column SELECT access across all non-dropped user columns:

```sql
WITH RECURSIVE role_inheritance_pg16 AS (
    -- Base: Target roles
    SELECT
        r.oid AS target_role_oid,
        r.rolname AS target_role,
        r.oid AS parent_role_oid,
        r.rolname AS parent_role,
        NULL::boolean AS inherit_option,
        0 AS depth,
        ARRAY[r.rolname::text] AS path
    FROM pg_roles r
    WHERE r.rolname IN ('anon', 'authenticated', 'service_role')

    UNION ALL

    -- Recursive step: follow memberships where pg_auth_members.inherit_option IS TRUE
    SELECT
        ri.target_role_oid,
        ri.target_role,
        parent.oid AS parent_role_oid,
        parent.rolname AS parent_role,
        m.inherit_option,
        ri.depth + 1,
        ri.path || parent.rolname::text
    FROM role_inheritance_pg16 ri
    JOIN pg_auth_members m ON m.member = ri.parent_role_oid
    JOIN pg_roles parent ON parent.oid = m.roleid
    WHERE m.inherit_option IS TRUE
      AND NOT (parent.rolname::text = ANY(ri.path))
)
SELECT
    ri.target_role,
    ri.parent_role,
    ri.depth,
    ri.inherit_option,
    array_to_string(ri.path, ' -> ') AS inheritance_path,
    a.attnum,
    a.attname AS column_name,
    has_table_privilege(ri.parent_role, c.oid, 'SELECT') AS parent_has_table_select,
    has_column_privilege(ri.parent_role, c.oid, a.attname, 'SELECT') AS parent_has_column_select
FROM role_inheritance_pg16 ri
CROSS JOIN pg_class c
JOIN pg_attribute a ON a.attrelid = c.oid
WHERE c.oid = 'public.analysis_results'::regclass
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY ri.target_role, ri.depth, ri.parent_role, a.attnum;
```

### Query 5B: Transitive Role Inheritance & Effective Parent SELECT Privileges (PostgreSQL 15 and Earlier)
*Use when `current_setting('server_version_num')::integer < 160000`*. Traverses role membership edges using legacy `rolinherit` behavior without referencing `inherit_option`:

```sql
WITH RECURSIVE role_inheritance_pg15 AS (
    -- Base: Target roles
    SELECT
        r.oid AS target_role_oid,
        r.rolname AS target_role,
        r.oid AS parent_role_oid,
        r.rolname AS parent_role,
        r.rolinherit,
        0 AS depth,
        ARRAY[r.rolname::text] AS path
    FROM pg_roles r
    WHERE r.rolname IN ('anon', 'authenticated', 'service_role')

    UNION ALL

    -- Recursive step: follow memberships where member role's rolinherit IS TRUE
    SELECT
        ri.target_role_oid,
        ri.target_role,
        parent.oid AS parent_role_oid,
        parent.rolname AS parent_role,
        parent.rolinherit,
        ri.depth + 1,
        ri.path || parent.rolname::text
    FROM role_inheritance_pg15 ri
    JOIN pg_auth_members m ON m.member = ri.parent_role_oid
    JOIN pg_roles parent ON parent.oid = m.roleid
    WHERE ri.rolinherit IS TRUE
      AND NOT (parent.rolname::text = ANY(ri.path))
)
SELECT
    ri.target_role,
    ri.parent_role,
    ri.depth,
    ri.rolinherit AS child_rolinherit,
    array_to_string(ri.path, ' -> ') AS inheritance_path,
    a.attnum,
    a.attname AS column_name,
    has_table_privilege(ri.parent_role, c.oid, 'SELECT') AS parent_has_table_select,
    has_column_privilege(ri.parent_role, c.oid, a.attname, 'SELECT') AS parent_has_column_select
FROM role_inheritance_pg15 ri
CROSS JOIN pg_class c
JOIN pg_attribute a ON a.attrelid = c.oid
WHERE c.oid = 'public.analysis_results'::regclass
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY ri.target_role, ri.depth, ri.parent_role, a.attnum;
```
*Expected Result (5A/5B)*: Confirms that after Migration 028, no parent role in the transitive inheritance path conveys unexpected table or column `SELECT` access to `anon`, or non-approved column access to `authenticated`.

---

## 4. Mandatory Pre-Migration Stop Conditions

The owner and auditor must **STOP and block execution** if any of the following conditions occur during preflight inspection:

1. **Surviving Anon SELECT**: An unexpected direct, `PUBLIC`, or transitively inherited `SELECT` grant exists that could survive Migration 028 and leave `anon` able to read any `analysis_results` column.
2. **Surviving Authenticated Non-Approved SELECT**: An unexpected direct, `PUBLIC`, or inherited grant exists that could leave `authenticated` able to read any column outside the approved six (`fast_analysis_result_snapshot`, `full_analysis_result`, `check_coverage_result`, `created_at`).
3. **Missing Approved Column**: Any of the 6 approved columns (`id`, `run_id`, `bid_id`, `structured_intelligence`, `fact_origins`, `report_content_snapshot`) is missing from `pg_attribute` for `'public.analysis_results'::regclass` (`attnum > 0 AND NOT attisdropped`).
4. **RLS Disabled or Changed Policy**: `has_rls` (`relrowsecurity`) is `false`, or the expected tenant-isolation policies on `analysis_results` are absent or altered.
5. **Loss of Service Role Access**: `has_table_privilege('service_role', 'public.analysis_results'::regclass, 'SELECT')` or column privileges for private snapshots are not established.
6. **Material Catalog Discrepancy**: The production catalog state differs materially from the disposable-accepted privilege model.
7. **Strict Invariant**: Do NOT modify the hashed migration to compensate for discrepancies automatically. If a discrepancy is found, stop and escalate.

---

## 5. Post-Migration Verification & API Expectations

Testing privilege denial through PostgREST requires inspecting the specific PostgreSQL error code and message. Generic HTTP status codes (400, 401, 403) are not proof of privilege denial (401 indicates missing/invalid authentication, 400 indicates malformed query syntax).

### Post-Migration Verification Checklist

| Check ID | Verification Action | Expected Diagnostic Result | Immediate Failure Condition |
|---|---|---|---|
| **V-01** | Query 1: Qualified RLS | `has_rls = true` (`relrowsecurity`) | RLS disabled |
| **V-02** | Query 2: Policies | Identical policy set to pre-migration baseline | Any policy altered, dropped, or added |
| **V-03** | Query 3: Anon Effective SELECT | `effective_table_select = false`, `effective_column_select = false` for all 10 columns | Any column readable by `anon` |
| **V-04** | Query 3: Authenticated Effective SELECT | `effective_table_select = false`; `effective_column_select = true` for exactly the 6 columns; `false` for 4 internal columns | Table select granted, internal column granted, or approved column missing |
| **V-05** | Query 3: Service Role Effective SELECT | `effective_table_select = true`, `effective_column_select = true` for all 10 columns | Service role lost table or column SELECT |
| **V-06** | Query 4: Recorded SELECT ACLs | • No surviving table-level SELECT for `anon`<br>• No surviving column-level SELECT for `anon`<br>• `authenticated` SELECT access to exactly the six approved columns<br>• No `authenticated` SELECT access to private columns<br>• No unexpected `PUBLIC` SELECT grant | Surviving table SELECT for `anon`/`authenticated`, internal column grant to `authenticated`, or unexpected `PUBLIC` SELECT grant |
| **V-07** | REST Probe: `anon` `select=*` | Response body is JSON with `"code": "42501"` | HTTP 200 OK, or error lacking `"code": "42501"` |
| **V-08** | REST Probe: `anon` `select=created_at` | Response body is JSON with `"code": "42501"` | HTTP 200 OK, or error lacking `"code": "42501"` |
| **V-09** | REST Probe: `authenticated` `select=*` | Response body is JSON with `"code": "42501"` | HTTP 200 OK, or error lacking `"code": "42501"` |
| **V-10** | REST Probe: `authenticated` `select=fast_analysis_result_snapshot` | Response body is JSON with `"code": "42501"` | HTTP 200 OK, or error lacking `"code": "42501"` |
| **V-11** | REST Probe: `service_role` `select=*` | HTTP 200 OK returning complete rows including internal snapshots | Service role query fails |

---

## 6. Two-Tenant Isolation Verification

To verify that column permissions and RLS tenant-row isolation operate correctly in concert, execute two independent authenticated sessions against an existing production record:

1. **Owner-Tenant Session**:
   - Authenticate as a user belonging to the organization owning a known existing analysis result.
   - Execute query with approved projection:
     `GET /rest/v1/analysis_results?id=eq.<id>&select=id,run_id,bid_id,structured_intelligence,fact_origins,report_content_snapshot`
   - **Expected Result**: HTTP 200 OK with non-empty response containing exactly the 6 approved fields.
2. **Different-Tenant Session**:
   - Authenticate as a user belonging to a *different* tenant organization.
   - Execute the identical query against the same record:
     `GET /rest/v1/analysis_results?id=eq.<id>&select=id,run_id,bid_id,structured_intelligence,fact_origins,report_content_snapshot`
   - **Expected Result**: HTTP 200 OK with empty array `[]` (or 404 for single-object endpoint). RLS filters out the row entirely. No row content, metadata, or schema information is revealed.
3. **Strict Constraints**:
   - Do NOT create production fixtures or temporary rows.
   - Do NOT substitute `service_role` credentials for either tenant session.
   - If an authorized second-tenant account is unavailable, mark tenant-isolation verification **NOT VERIFIED** and retain the corresponding readiness gate.

---

## 7. Rollback Constraints & Recovery Doctrine

> [!IMPORTANT]
> **Preferred Recovery: Preserve Compatible Application Version**
> The application code currently deployed on `main` (`ee8ad0a9e55513b899f06ac1f114924479726aa1`) is compatible with both pre-028 and post-028 database states because it projects only the 6 approved columns.
>
> 1. **Do Not Revert Application Code**:
>    Under no circumstances should the application be rolled back to pre-028 wildcard-reading commits (e.g. `5f87d32`). Rolling back application code after Migration 028 is active will immediately break all authenticated analysis reads with SQLSTATE `42501`.
> 2. **Privilege Restoration Requires Independent Authorization**:
>    Reverting database privileges (i.e. re-granting broad `SELECT on analysis_results to authenticated, anon`) re-exposes internal captured raw source text, creating an immediate security regression. Any privilege-restoring SQL rollback must be independently approved, security-reviewed, and manually applied. It must never be triggered automatically.

---

## 8. Streamlit Deployment Attestation Findings

* **Authoritative GitHub Webhook Record**:
  - Delivery ID: `3848782228484022272`
  - Timestamp: `2026-10-17T09:21:27.085Z`
  - Target: `https://share.streamlit.io/hook`
  - Ref: `refs/heads/main`
  - Head SHA: `ee8ad0a9e55513b899f06ac1f114924479726aa1`
  - Response: HTTP 200 OK (`Set-Cookie: _streamlit_csrf=...`)
* **Running Attestation Requirement**:
  Streamlit Community Cloud does not expose an unauthenticated API or HTTP response header reporting the active container's Git SHA (returns HTTP 303 to OAuth). Therefore, the application owner must visually confirm on `share.streamlit.io` that app `bid-intelligence-vcayfdyp4udxytdyxgzh6u` is actively running commit `ee8ad0a` before applying Migration 028.

---

## 9. Correct Safe Git Isolation Procedure

To cleanly version-control Migration 028 without disturbing the dirty development worktree or the deployed `main` release, the procedure (to be executed only upon separate owner authorization) is:

1. **Create an Isolated Clean Worktree Outside the Development Tree**:
   ```bash
   git worktree add -b release/migration-028-privilege-remediation ../Bid-Intelligence-m028 origin/main
   cd ../Bid-Intelligence-m028
   ```
2. **Copy Exactly These Three Clean Artifacts**:
   - `migrations/028_restrict_analysis_results_snapshot_select.sql`
   - `tests/test_migration_028_analysis_results_privileges.py`
   - `docs/current/MIGRATION_028_COMMISSIONING_PACKAGE.md`
3. **Stage Only Those Files When Authorized**:
   ```bash
   git add migrations/028_restrict_analysis_results_snapshot_select.sql \
           tests/test_migration_028_analysis_results_privileges.py \
           docs/current/MIGRATION_028_COMMISSIONING_PACKAGE.md
   ```
4. **Do Not Commit, Push, or Merge**:
   No commit, push, or merge is executed during this preparation. Staging and commit occur only upon explicit separate authorization.
