/*
 * Manual disposable-only acceptance harness for migration 028.
 *
 * This script intentionally performs writes only when explicitly launched
 * after the migration has been manually applied. It never applies DDL.
 * It creates two synthetic Auth users and organizations, exercises the real
 * Supabase REST API with their JWTs, then deletes exact recorded fixtures and
 * independently audits for residue. Do not run against production.
 *
 * Required environment variables (values are never printed):
 * MIGRATION_027_TEST_DATABASE_URL, MIGRATION_027_DISPOSABLE,
 * MIGRATION_028_ALLOW_FIXTURES=I_CONFIRM_MIGRATION_028_FIXTURES,
 * SUPABASE_TEST_URL, SUPABASE_TEST_ANON_KEY, SUPABASE_TEST_SERVICE_ROLE_KEY.
 */
const { spawnSync } = require('child_process');
const crypto = require('crypto');

const REF = 'qsycsgwjzmvlgtphuoqd';
const PROD = 'whonalbdpbubaqhpzrnw';
const FIXTURE_OK = 'I_CONFIRM_MIGRATION_028_FIXTURES';
const SENTINEL = 'must-not-leak';
const SEED_PREFIX = 'M028_FIXTURE_SEED:';

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const POSITIVE_INT_REGEX = /^[1-9]\d*$/;

const url = process.env.MIGRATION_027_TEST_DATABASE_URL;
const apiUrl = process.env.SUPABASE_TEST_URL;
const anonKey = process.env.SUPABASE_TEST_ANON_KEY;
const serviceKey = process.env.SUPABASE_TEST_SERVICE_ROLE_KEY;
const fixture = {};

function fail(message) {
  const safeMessage = String(message || '').split(SENTINEL).join('[REDACTED_SENTINEL]');
  throw new Error(`M028_SNAPSHOT_API_TEST_FAILED: ${safeMessage}`);
}

function assert(condition, message) {
  if (!condition) fail(message);
}

function requireEnv(name, value) {
  if (!value) fail(`${name} is required`);
}

function isValidUuid(val) {
  return typeof val === 'string' && UUID_REGEX.test(val.trim());
}

function isValidPositiveInt(val) {
  if (typeof val === 'number') {
    return Number.isInteger(val) && val > 0;
  }
  return typeof val === 'string' && POSITIVE_INT_REGEX.test(val.trim());
}

function sanitizeUuid(val) {
  return isValidUuid(val) ? val.trim().toLowerCase() : null;
}

function sanitizePositiveInt(val) {
  return isValidPositiveInt(val) ? String(val).trim() : null;
}

function verifiedTarget() {
  requireEnv('MIGRATION_027_TEST_DATABASE_URL', url);
  const parsed = new URL(url);
  const identity = `${parsed.hostname}\n${decodeURIComponent(parsed.username || '')}`.toLowerCase();
  assert(['postgres:', 'postgresql:'].includes(parsed.protocol), 'test URL must be PostgreSQL');
  assert(identity.includes(REF) && !identity.includes(PROD), 'database target is not the authorized disposable project');
  requireEnv('SUPABASE_TEST_URL', apiUrl);
  assert(new URL(apiUrl).hostname === `${REF}.supabase.co`, 'REST target is not the authorized disposable project');
  assert(process.env.MIGRATION_027_DISPOSABLE === 'I_CONFIRM_THIS_IS_A_DISPOSABLE_DATABASE', 'disposable safeguard missing');
  assert(process.env.MIGRATION_028_ALLOW_FIXTURES === FIXTURE_OK, 'fixture authorization safeguard missing');
  requireEnv('SUPABASE_TEST_ANON_KEY', anonKey);
  requireEnv('SUPABASE_TEST_SERVICE_ROLE_KEY', serviceKey);
}

function psql(sql, tuples = false) {
  const args = [url, '--no-psqlrc', '--set', 'ON_ERROR_STOP=1', '--command', sql];
  if (tuples) args.push('--tuples-only', '--no-align');
  const out = spawnSync('psql', args, { encoding: 'utf8', timeout: 15000, env: process.env });
  if (out.error || out.status !== 0) {
    const errText = (out.stderr || out.error?.message || '').trim().split(SENTINEL).join('[REDACTED]');
    fail(`psql failed: ${errText}`);
  }
  return out.stdout.trim();
}

function scalar(sql) {
  return psql(sql, true).split(/\r?\n/).map(x => x.trim()).find(x => x && !/^(BEGIN|COMMIT|ROLLBACK|INSERT|DELETE|SELECT|DO)$/.test(x));
}

async function request(path, { token, method = 'GET', body } = {}) {
  const headers = { apikey: anonKey };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['content-type'] = 'application/json';
  const response = await fetch(`${apiUrl}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: response.status, text: await response.text() };
}

function parseSqlState(text) {
  if (!text || typeof text !== 'string') return null;
  try {
    const data = JSON.parse(text);
    if (data && typeof data === 'object' && !Array.isArray(data) && typeof data.code === 'string') {
      return data.code.trim();
    }
  } catch {
    // Strictly reject malformed JSON; no regex fallback
  }
  return null;
}

function isAuthorizationDenial(response) {
  if (!response || typeof response.status !== 'number') return false;
  if (response.status === 401 || response.status === 403) return true;
  if (response.status === 400) {
    const code = parseSqlState(response.text || '');
    return code === '42501';
  }
  return false;
}

function assertPermissionDenied(response, opName) {
  assert(response && typeof response.status === 'number', `${opName}: transport error or malformed response`);
  assert(!String(response.text || '').includes(SENTINEL), `${opName}: private sentinel leaked in response`);
  const sqlState = parseSqlState(response.text || '');
  assert(
    isAuthorizationDenial(response),
    `${opName}: expected authorization denial (401/403 or 400 with SQLSTATE 42501), got HTTP ${response.status}${sqlState ? ` [SQLSTATE ${sqlState}]` : ''}`
  );
}

function assertEmptyOrDenied(response, opName) {
  assert(response && typeof response.status === 'number', `${opName}: transport error or malformed response`);
  assert(!String(response.text || '').includes(SENTINEL), `${opName}: private sentinel leaked in response`);
  if (response.status === 200) {
    assert(String(response.text || '').trim() === '[]', `${opName}: expected empty array [], got non-empty payload [HTTP 200]`);
    return;
  }
  const sqlState = parseSqlState(response.text || '');
  assert(
    isAuthorizationDenial(response),
    `${opName}: expected authorization denial or HTTP 200 [], got HTTP ${response.status}${sqlState ? ` [SQLSTATE ${sqlState}]` : ''}`
  );
}

function buildRecoveryIdentities(seedNonce) {
  const nonce = seedNonce || crypto.randomBytes(8).toString('hex');
  const label = `m028_${Date.now()}_${nonce}`;
  return {
    label,
    ownerEmail: `${label}_owner@example.invalid`,
    otherEmail: `${label}_other@example.invalid`,
    ownerOrgSlug: `${label}_owner_org`,
    otherOrgSlug: `${label}_other_org`,
    bidTitle: `${label}_bid`,
  };
}

function initFixtureIdentities() {
  const identities = buildRecoveryIdentities();
  Object.assign(fixture, {
    label: identities.label,
    ownerEmail: identities.ownerEmail,
    otherEmail: identities.otherEmail,
    ownerOrgSlug: identities.ownerOrgSlug,
    otherOrgSlug: identities.otherOrgSlug,
    bidTitle: identities.bidTitle,
    ownerUser: null,
    otherUser: null,
    bidId: null,
    ownerOrg: null,
    otherOrg: null,
    runId: null,
    resultId: null,
  });
}

function validateFixtureOwnership(f) {
  assert(f && typeof f === 'object', 'cleanup_blocked_missing_fixture_object');
  assert(
    typeof f.label === 'string' &&
    f.label.length >= 10 &&
    /^m028_[a-z0-9_]+$/.test(f.label),
    'cleanup_blocked_invalid_fixture_label'
  );
  assert(
    typeof f.ownerEmail === 'string' &&
    f.ownerEmail === `${f.label}_owner@example.invalid`,
    'cleanup_blocked_ambiguous_owner_email'
  );
  assert(
    typeof f.otherEmail === 'string' &&
    f.otherEmail === `${f.label}_other@example.invalid`,
    'cleanup_blocked_ambiguous_other_email'
  );
  assert(
    f.ownerEmail !== f.otherEmail,
    'cleanup_blocked_ambiguous_user_emails'
  );
  assert(
    typeof f.ownerOrgSlug === 'string' &&
    f.ownerOrgSlug === `${f.label}_owner_org`,
    'cleanup_blocked_ambiguous_owner_slug'
  );
  assert(
    typeof f.otherOrgSlug === 'string' &&
    f.otherOrgSlug === `${f.label}_other_org`,
    'cleanup_blocked_ambiguous_other_slug'
  );
  assert(
    f.ownerOrgSlug !== f.otherOrgSlug,
    'cleanup_blocked_ambiguous_org_slugs'
  );
  assert(
    typeof f.bidTitle === 'string' &&
    f.bidTitle === `${f.label}_bid`,
    'cleanup_blocked_ambiguous_bid_title'
  );
}

function buildCleanupQueries(f) {
  validateFixtureOwnership(f);

  const safeBidTitle = f.bidTitle;
  const safeOwnerSlug = f.ownerOrgSlug;
  const safeOtherSlug = f.otherOrgSlug;
  const safeOwnerEmail = f.ownerEmail;
  const safeOtherEmail = f.otherEmail;
  const safeLabel = f.label;

  // 1. Destructive queries: exact pre-recorded synthetic identities are the sole authoritative selectors
  const bidClause = `DELETE FROM public.bids WHERE title = '${safeBidTitle}' AND organization_id IN (SELECT id FROM public.organizations WHERE slug = '${safeOwnerSlug}');`;
  const orgClause = `DELETE FROM public.organizations WHERE slug = '${safeOwnerSlug}' OR slug = '${safeOtherSlug}';`;
  const dbSql = `BEGIN; ${bidClause} ${orgClause} COMMIT;`;

  const authSql = `DELETE FROM auth.users WHERE email = '${safeOwnerEmail}' OR email = '${safeOtherEmail}';`;

  // 2. Independent residue audit: independently locates runs/results by marker without join to parent bid
  const residueSql = `SELECT count(*) FROM (
    SELECT 1 FROM public.bids
      WHERE title = '${safeBidTitle}'
        AND organization_id IN (SELECT id FROM public.organizations WHERE slug = '${safeOwnerSlug}')
    UNION ALL
    SELECT 1 FROM public.analysis_runs
      WHERE engine_version = '${safeLabel}'
    UNION ALL
    SELECT 1 FROM public.analysis_results
      WHERE structured_intelligence->>'fixture_label' = '${safeLabel}'
    UNION ALL
    SELECT 1 FROM public.organizations
      WHERE slug = '${safeOwnerSlug}' OR slug = '${safeOtherSlug}'
    UNION ALL
    SELECT 1 FROM auth.users
      WHERE email = '${safeOwnerEmail}' OR email = '${safeOtherEmail}'
  ) residue;`.replace(/\s+/g, ' ').trim();

  // 3. Retain returned IDs solely for consistency diagnostics
  const diagnostic = {
    recordedBidId: sanitizePositiveInt(f.bidId),
    recordedRunId: sanitizePositiveInt(f.runId),
    recordedResultId: sanitizePositiveInt(f.resultId),
    recordedOwnerOrg: sanitizeUuid(f.ownerOrg),
    recordedOtherOrg: sanitizeUuid(f.otherOrg),
    recordedOwnerUser: sanitizeUuid(f.ownerUser),
    recordedOtherUser: sanitizeUuid(f.otherUser),
  };

  return { dbSql, authSql, residueSql, diagnostic };
}

async function createUser(email) {
  const password = crypto.randomBytes(24).toString('base64url');
  const response = await fetch(`${apiUrl}/auth/v1/admin/users`, {
    method: 'POST',
    headers: { apikey: serviceKey, Authorization: `Bearer ${serviceKey}`, 'content-type': 'application/json' },
    body: JSON.stringify({ email, password, email_confirm: true })
  });
  const data = await response.json();
  assert(response.status >= 200 && response.status < 300, 'user_creation_failed_status');
  assert(data && typeof data === 'object', 'user_creation_invalid_response');
  const userId = sanitizeUuid(data.id);
  assert(userId !== null, 'user_creation_invalid_uuid');
  return { id: userId, email, password };
}

async function login(user) {
  const response = await fetch(`${apiUrl}/auth/v1/token?grant_type=password`, {
    method: 'POST',
    headers: { apikey: anonKey, 'content-type': 'application/json' },
    body: JSON.stringify({ email: user.email, password: user.password })
  });
  const data = await response.json();
  assert(response.status === 200 && data.access_token, 'user_login_failed');
  return data.access_token;
}

function parseSeedOutput(rawOutput) {
  assert(rawOutput && typeof rawOutput === 'string', 'fixture_seed_output_missing');
  const lines = rawOutput.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
  const seedLines = lines.filter(x => x.startsWith(SEED_PREFIX));
  assert(seedLines.length > 0, 'fixture_seed_output_missing');
  assert(seedLines.length === 1, 'fixture_seed_format_invalid');

  const payload = seedLines[0].slice(SEED_PREFIX.length).trim();
  const parts = payload.split('|').map(x => x.trim());
  assert(parts.length === 5, 'fixture_seed_format_invalid');

  const [rawBidId, rawOwnerOrg, rawOtherOrg, rawRunId, rawResultId] = parts;
  const bidId = sanitizePositiveInt(rawBidId);
  const ownerOrg = sanitizeUuid(rawOwnerOrg);
  const otherOrg = sanitizeUuid(rawOtherOrg);
  const runId = sanitizePositiveInt(rawRunId);
  const resultId = sanitizePositiveInt(rawResultId);

  assert(bidId !== null, 'fixture_seed_bid_id_invalid');
  assert(ownerOrg !== null, 'fixture_seed_owner_org_invalid');
  assert(otherOrg !== null, 'fixture_seed_other_org_invalid');
  assert(runId !== null, 'fixture_seed_run_id_invalid');
  assert(resultId !== null, 'fixture_seed_result_id_invalid');

  return { bidId, ownerOrg, otherOrg, runId, resultId };
}

function seed(ownerId, otherId) {
  const validOwnerId = sanitizeUuid(ownerId);
  const validOtherId = sanitizeUuid(otherId);
  assert(validOwnerId !== null && validOtherId !== null, 'seed_invalid_input_user_uuids');

  const raw = psql(`BEGIN; DO $$ DECLARE owner_org uuid; other_org uuid; b bigint; r bigint; result_id bigint; BEGIN
    INSERT INTO public.organizations(name,slug) VALUES ('${fixture.bidTitle} owner','${fixture.ownerOrgSlug}') RETURNING id INTO owner_org;
    INSERT INTO public.organizations(name,slug) VALUES ('${fixture.bidTitle} other','${fixture.otherOrgSlug}') RETURNING id INTO other_org;
    INSERT INTO public.organization_members(organization_id,user_id) VALUES (owner_org,'${validOwnerId}'),(other_org,'${validOtherId}');
    INSERT INTO public.bids(title,client,organization_id) VALUES ('${fixture.bidTitle}','Synthetic only',owner_org) RETURNING id INTO b;
    INSERT INTO public.analysis_runs(bid_id,analysis_mode,status,engine_version,corpus_document_ids) VALUES (b,'FAST','COMPLETE','${fixture.label}','[]'::jsonb) RETURNING id INTO r;
    INSERT INTO public.analysis_results(run_id,bid_id,structured_intelligence,fact_origins,report_content_snapshot,fast_analysis_result_snapshot) VALUES (r,b,'{"safe":true,"fixture_label":"${fixture.label}"}'::jsonb,'{}'::jsonb,'{"safe":true}'::jsonb,'{"m028_private_sentinel":"must-not-leak","fixture_label":"${fixture.label}"}'::jsonb) RETURNING id INTO result_id;
    PERFORM set_config('m028.fixture', b::text || '|' || owner_org::text || '|' || other_org::text || '|' || r::text || '|' || result_id::text, false); END $$; SELECT '${SEED_PREFIX}' || current_setting('m028.fixture'); COMMIT;`, true);

  const seedData = parseSeedOutput(raw);
  Object.assign(fixture, seedData);
}

async function cleanup() {
  const cleanupErrors = [];
  const { dbSql, authSql, residueSql } = buildCleanupQueries(fixture);

  try {
    psql(dbSql);
  } catch (err) {
    cleanupErrors.push(`db_cleanup_error`);
  }

  try {
    psql(authSql);
  } catch (err) {
    cleanupErrors.push(`auth_cleanup_error`);
  }

  try {
    const residue = scalar(residueSql);
    assert(residue === '0', `residue_count_${residue}`);
  } catch (err) {
    cleanupErrors.push(`residue_audit_error: ${err.message}`);
  }

  if (cleanupErrors.length > 0) {
    fail(`cleanup_encountered_errors: ${cleanupErrors.join('; ')}`);
  }
}

async function main() {
  verifiedTarget();
  initFixtureIdentities();
  let primaryError = null;

  try {
    const owner = await createUser(fixture.ownerEmail);
    fixture.ownerUser = owner.id;
    const other = await createUser(fixture.otherEmail);
    fixture.otherUser = other.id;

    seed(owner.id, other.id);
    const ownerToken = await login(owner);
    const otherToken = await login(other);

    // 1. Approved projection: owner can safely read approved columns
    const safe = await request(`/rest/v1/analysis_results?bid_id=eq.${fixture.bidId}&select=id,run_id,bid_id,structured_intelligence,fact_origins,report_content_snapshot`, { token: ownerToken });
    assert(safe.status === 200, `owner_safe_read: expected HTTP 200, got ${safe.status}`);
    assert(safe.text.includes(`"bid_id":${fixture.bidId}`), 'owner_safe_read: bid_id missing in projection');
    assert(!safe.text.includes(SENTINEL), 'owner_safe_read: sentinel leaked');

    // 2. Default wildcard selection: omitting select parameter must fail closed
    const defaultWildcard = await request(`/rest/v1/analysis_results?bid_id=eq.${fixture.bidId}`, { token: ownerToken });
    assertPermissionDenied(defaultWildcard, 'owner_default_wildcard');

    // 3. Explicit wildcard selection: select=* must fail closed
    const explicitWildcard = await request(`/rest/v1/analysis_results?bid_id=eq.${fixture.bidId}&select=*`, { token: ownerToken });
    assertPermissionDenied(explicitWildcard, 'owner_explicit_wildcard');

    // 4. Private column selection: explicit internal column request must fail closed
    const privateRead = await request(`/rest/v1/analysis_results?bid_id=eq.${fixture.bidId}&select=fast_analysis_result_snapshot`, { token: ownerToken });
    assertPermissionDenied(privateRead, 'owner_private_snapshot_read');

    // 5. Cross-tenant isolation: other tenant member receives empty result [] or permission denial
    const cross = await request(`/rest/v1/analysis_results?bid_id=eq.${fixture.bidId}&select=id`, { token: otherToken });
    assertEmptyOrDenied(cross, 'cross_tenant_read');

    // 6. Anonymous request: must be permission denied or return empty result []
    const anonymous = await request(`/rest/v1/analysis_results?bid_id=eq.${fixture.bidId}&select=id`);
    assertEmptyOrDenied(anonymous, 'anonymous_read');

    // 7. Direct authenticated DML rejection tests: verify responses and exact DB state
    const preCount = Number(scalar(`SELECT count(*) FROM public.analysis_results WHERE bid_id = ${fixture.bidId};`));
    assert(preCount === 1, 'initial_result_count_invalid');

    // 7a. Direct POST rejection
    const postRes = await request('/rest/v1/analysis_results', {
      token: ownerToken,
      method: 'POST',
      body: { run_id: Number(fixture.runId), bid_id: Number(fixture.bidId), structured_intelligence: { injected: true } }
    });
    const postIsAuthDenial = isAuthorizationDenial(postRes);
    const postIsEmpty = [200, 204].includes(postRes.status) && (postRes.text === '' || postRes.text === '[]');
    assert(postIsAuthDenial || postIsEmpty, `owner_direct_post: unexpected status HTTP ${postRes.status}`);
    assert(!String(postRes.text || '').includes(SENTINEL), 'owner_direct_post: sentinel leaked');
    const postCount = Number(scalar(`SELECT count(*) FROM public.analysis_results WHERE bid_id = ${fixture.bidId};`));
    assert(postCount === preCount, 'owner_direct_post: unauthorized row created in database');

    // 7b. Direct PATCH rejection
    const patchRes = await request(`/rest/v1/analysis_results?id=eq.${fixture.resultId}`, {
      token: ownerToken,
      method: 'PATCH',
      body: { structured_intelligence: { mutated: true } }
    });
    const patchIsAuthDenial = isAuthorizationDenial(patchRes);
    const patchIsEmpty = [200, 204].includes(patchRes.status) && (patchRes.text === '' || patchRes.text === '[]');
    assert(patchIsAuthDenial || patchIsEmpty, `owner_direct_patch: unexpected status HTTP ${patchRes.status}`);
    assert(!String(patchRes.text || '').includes(SENTINEL), 'owner_direct_patch: sentinel leaked');
    const patchCheck = psql(`SELECT structured_intelligence->>'safe', structured_intelligence->>'mutated', fast_analysis_result_snapshot->>'m028_private_sentinel' FROM public.analysis_results WHERE id = ${fixture.resultId};`, true);
    assert(patchCheck.includes('true||must-not-leak'), 'owner_direct_patch: unauthorized mutation persisted in database');

    // 7c. Direct DELETE rejection
    const delRes = await request(`/rest/v1/analysis_results?id=eq.${fixture.resultId}`, {
      token: ownerToken,
      method: 'DELETE'
    });
    const delIsAuthDenial = isAuthorizationDenial(delRes);
    const delIsEmpty = [200, 204].includes(delRes.status) && (delRes.text === '' || delRes.text === '[]');
    assert(delIsAuthDenial || delIsEmpty, `owner_direct_delete: unexpected status HTTP ${delRes.status}`);
    assert(!String(delRes.text || '').includes(SENTINEL), 'owner_direct_delete: sentinel leaked');
    const postDeleteCount = Number(scalar(`SELECT count(*) FROM public.analysis_results WHERE id = ${fixture.resultId};`));
    assert(postDeleteCount === 1, 'owner_direct_delete: unauthorized deletion occurred in database');

    // 8. Service role retains full raw snapshot access
    const service = psql(`BEGIN READ ONLY; SET LOCAL ROLE service_role; SELECT fast_analysis_result_snapshot->>'m028_private_sentinel' FROM public.analysis_results WHERE run_id = ${fixture.runId}; ROLLBACK;`, true);
    assert(service.includes('must-not-leak'), 'trusted service role lost raw snapshot access');

    console.log('M028_SNAPSHOT_DATA_API_ACCEPTANCE: PASS');
  } catch (err) {
    primaryError = err;
  } finally {
    try {
      await cleanup();
    } catch (cleanupErr) {
      if (primaryError) {
        console.error(`M028 cleanup failure: ${cleanupErr.message}`);
        throw primaryError;
      }
      throw cleanupErr;
    }
    if (primaryError) {
      throw primaryError;
    }
  }
}

if (require.main === module) {
  main().catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
} else {
  module.exports = {
    SENTINEL,
    SEED_PREFIX,
    fail,
    assert,
    isValidUuid,
    isValidPositiveInt,
    sanitizeUuid,
    sanitizePositiveInt,
    parseSqlState,
    isAuthorizationDenial,
    assertPermissionDenied,
    assertEmptyOrDenied,
    buildRecoveryIdentities,
    validateFixtureOwnership,
    buildCleanupQueries,
    parseSeedOutput,
  };
}
