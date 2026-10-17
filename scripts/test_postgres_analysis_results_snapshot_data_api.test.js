/*
 * Local unit tests for Migration 028 acceptance harness logic.
 *
 * Exercises the shared permission-denial validator, strict JSON SQLSTATE parsing,
 * safe error sanitization, strict identifier validation, and recoverable fixture
 * identity cleanup query generation without external network calls or database mutations.
 */
const assert = require('assert');
const harness = require('./test_postgres_analysis_results_snapshot_data_api.js');

let passedCount = 0;
function test(name, fn) {
  try {
    fn();
    passedCount++;
    console.log(`PASS: ${name}`);
  } catch (err) {
    console.error(`FAIL: ${name}`);
    console.error(err);
    process.exitCode = 1;
  }
}

// ── 1. Strict JSON-based SQLSTATE validation tests ──────────────────────────

test('isAuthorizationDenial accepts HTTP 401 Unauthorized and 403 Forbidden', () => {
  assert.strictEqual(harness.isAuthorizationDenial({ status: 401, text: '{"message":"JWT expired"}' }), true);
  assert.strictEqual(harness.isAuthorizationDenial({ status: 403, text: '{"message":"Forbidden"}' }), true);
});

test('isAuthorizationDenial accepts HTTP 400 with valid JSON having exact code "42501"', () => {
  const body = JSON.stringify({ code: '42501', message: 'permission denied for table analysis_results' });
  assert.strictEqual(harness.isAuthorizationDenial({ status: 400, text: body }), true);
  assert.strictEqual(harness.parseSqlState(body), '42501');
});

test('isAuthorizationDenial rejects HTTP 400 with malformed JSON containing "42501"', () => {
  const malformedBodies = [
    '{"code": "42501"',
    '{"code": 42501}',
    'prefix {"code": "42501"} suffix',
    '{"message": "error with code 42501"}',
    'SQLSTATE 42501: permission denied',
  ];
  for (const text of malformedBodies) {
    assert.strictEqual(harness.isAuthorizationDenial({ status: 400, text }), false, `Should reject: ${text}`);
    assert.strictEqual(harness.parseSqlState(text), null);
  }
});

test('isAuthorizationDenial rejects HTTP 400 with valid JSON containing other SQLSTATE codes', () => {
  const otherCodes = ['42601', '42P01', '23505', 'PGRST100', 'PGRST301'];
  for (const code of otherCodes) {
    const text = JSON.stringify({ code, message: 'some error' });
    assert.strictEqual(harness.isAuthorizationDenial({ status: 400, text }), false);
    assert.strictEqual(harness.parseSqlState(text), code);
  }
});

test('isAuthorizationDenial rejects non-JSON gateway and server errors', () => {
  const gatewayBodies = [
    '<html><body>502 Bad Gateway</body></html>',
    '504 Gateway Time-out',
    'Service Unavailable',
    '',
  ];
  for (const text of gatewayBodies) {
    assert.strictEqual(harness.isAuthorizationDenial({ status: 502, text }), false);
    assert.strictEqual(harness.isAuthorizationDenial({ status: 504, text }), false);
    assert.strictEqual(harness.isAuthorizationDenial({ status: 500, text }), false);
    assert.strictEqual(harness.isAuthorizationDenial({ status: 400, text }), false);
    assert.strictEqual(harness.parseSqlState(text), null);
  }
});

test('isAuthorizationDenial rejects HTTP 429 Rate Limit', () => {
  assert.strictEqual(harness.isAuthorizationDenial({ status: 429, text: '{"message":"Too many requests"}' }), false);
});

test('isAuthorizationDenial rejects HTTP 200 OK', () => {
  assert.strictEqual(harness.isAuthorizationDenial({ status: 200, text: '[]' }), false);
});

test('isAuthorizationDenial rejects null, undefined, or missing status', () => {
  assert.strictEqual(harness.isAuthorizationDenial(null), false);
  assert.strictEqual(harness.isAuthorizationDenial(undefined), false);
  assert.strictEqual(harness.isAuthorizationDenial({}), false);
});

// ── 2. Diagnostic security and sentinel redaction tests ─────────────────────

test('assertPermissionDenied passes on valid 401, 403, and 400-42501', () => {
  harness.assertPermissionDenied({ status: 401, text: '{"code":"PGRST301"}' }, 'test_op');
  harness.assertPermissionDenied({ status: 403, text: '{"message":"forbidden"}' }, 'test_op');
  harness.assertPermissionDenied({ status: 400, text: '{"code":"42501"}' }, 'test_op');
});

test('assertPermissionDenied throws on 200 [], 429, 500, and malformed 400', () => {
  assert.throws(() => harness.assertPermissionDenied({ status: 200, text: '[]' }, 'test_op'), /expected authorization denial/);
  assert.throws(() => harness.assertPermissionDenied({ status: 429, text: 'rate limit' }, 'test_op'), /expected authorization denial/);
  assert.throws(() => harness.assertPermissionDenied({ status: 500, text: 'crash' }, 'test_op'), /expected authorization denial/);
  assert.throws(() => harness.assertPermissionDenied({ status: 400, text: '{"code":"42501"' }, 'test_op'), /expected authorization denial/);
});

test('assertPermissionDenied detects sentinel leak and redacts sentinel from error message', () => {
  const leakedText = `{"code":"42501","leak":"${harness.SENTINEL}"}`;
  let caughtError = null;
  try {
    harness.assertPermissionDenied({ status: 400, text: leakedText }, 'test_leak_op');
  } catch (err) {
    caughtError = err;
  }
  assert(caughtError, 'Expected assertion failure on sentinel leak');
  assert.strictEqual(caughtError.message.includes('private sentinel leaked in response'), true);
  assert.strictEqual(caughtError.message.includes(harness.SENTINEL), false, 'Error message must NOT contain private sentinel');
});

test('assertEmptyOrDenied permits exact 200 [] and genuine denials', () => {
  harness.assertEmptyOrDenied({ status: 200, text: '[]' }, 'cross_tenant');
  harness.assertEmptyOrDenied({ status: 200, text: '  []  ' }, 'anonymous');
  harness.assertEmptyOrDenied({ status: 401, text: '{"message":"unauthorized"}' }, 'anonymous');
  harness.assertEmptyOrDenied({ status: 403, text: '{"message":"forbidden"}' }, 'anonymous');
  harness.assertEmptyOrDenied({ status: 400, text: '{"code":"42501"}' }, 'anonymous');
});

test('assertEmptyOrDenied rejects non-empty 200, 500, 429, and malformed 400', () => {
  assert.throws(() => harness.assertEmptyOrDenied({ status: 200, text: '[{"id":1}]' }, 'cross_tenant'), /expected empty array/);
  assert.throws(() => harness.assertEmptyOrDenied({ status: 500, text: 'error' }, 'anonymous'), /expected authorization denial or HTTP 200/);
  assert.throws(() => harness.assertEmptyOrDenied({ status: 429, text: 'limit' }, 'anonymous'), /expected authorization denial or HTTP 200/);
  assert.throws(() => harness.assertEmptyOrDenied({ status: 400, text: '{"code":"42501"' }, 'anonymous'), /expected authorization denial or HTTP 200/);
});

test('assertEmptyOrDenied detects sentinel leak and redacts sentinel from error message', () => {
  const leakedText = `[{"private":"${harness.SENTINEL}"}]`;
  let caughtError = null;
  try {
    harness.assertEmptyOrDenied({ status: 200, text: leakedText }, 'anonymous');
  } catch (err) {
    caughtError = err;
  }
  assert(caughtError, 'Expected assertion failure on sentinel leak');
  assert.strictEqual(caughtError.message.includes('private sentinel leaked in response'), true);
  assert.strictEqual(caughtError.message.includes(harness.SENTINEL), false, 'Error message must NOT contain private sentinel');
});

// ── 3. Strict identifier validation tests ───────────────────────────────────

test('isValidUuid accepts valid UUIDs and rejects malformed/injectable values', () => {
  const validUuids = [
    'a1b2c3d4-e5f6-4a1b-8c2d-3e4f5a6b7c8d',
    '00000000-0000-0000-0000-000000000000',
    'A1B2C3D4-E5F6-4A1B-8C2D-3E4F5A6B7C8D',
  ];
  for (const u of validUuids) {
    assert.strictEqual(harness.isValidUuid(u), true, `Should accept valid UUID: ${u}`);
    assert.strictEqual(harness.sanitizeUuid(u), u.trim().toLowerCase());
  }

  const invalidUuids = [
    'not-a-uuid',
    '12345',
    '',
    null,
    undefined,
    "1'; DROP TABLE auth.users; --",
    'a1b2c3d4-e5f6-4a1b-8c2d-3e4f5a6b7c8z', // invalid hex 'z'
    'a1b2c3d4-e5f6-4a1b-8c2d-3e4f5a6b7c8de', // too long
    '{a1b2c3d4-e5f6-4a1b-8c2d-3e4f5a6b7c8d}', // braces
  ];
  for (const inv of invalidUuids) {
    assert.strictEqual(harness.isValidUuid(inv), false, `Should reject invalid UUID: ${inv}`);
    assert.strictEqual(harness.sanitizeUuid(inv), null);
  }
});

test('isValidPositiveInt accepts positive integers and rejects 0, negatives, and injectable values', () => {
  const validInts = [1, 42, 999999, '1', '42', '1000000'];
  for (const v of validInts) {
    assert.strictEqual(harness.isValidPositiveInt(v), true, `Should accept valid positive int: ${v}`);
    assert.strictEqual(harness.sanitizePositiveInt(v), String(v).trim());
  }

  const invalidInts = [
    0,
    '0',
    -1,
    '-1',
    1.5,
    '1.5',
    '',
    'abc',
    null,
    undefined,
    "1 OR 1=1",
    "1; DROP TABLE bids; --",
  ];
  for (const inv of invalidInts) {
    assert.strictEqual(harness.isValidPositiveInt(inv), false, `Should reject invalid int: ${inv}`);
    assert.strictEqual(harness.sanitizePositiveInt(inv), null);
  }
});

// ── 4. Recoverable fixture identity and ownership validation tests ──────────

test('buildRecoveryIdentities creates deterministic, exact identifiers', () => {
  const ids = harness.buildRecoveryIdentities('fixed_nonce_123');
  assert.strictEqual(ids.label.startsWith('m028_'), true);
  assert.strictEqual(ids.label.endsWith('_fixed_nonce_123'), true);
  assert.strictEqual(ids.ownerEmail, `${ids.label}_owner@example.invalid`);
  assert.strictEqual(ids.otherEmail, `${ids.label}_other@example.invalid`);
  assert.strictEqual(ids.ownerOrgSlug, `${ids.label}_owner_org`);
  assert.strictEqual(ids.otherOrgSlug, `${ids.label}_other_org`);
  assert.strictEqual(ids.bidTitle, `${ids.label}_bid`);
});

test('validateFixtureOwnership fails closed on missing, invalid, or mismatched fixture identities', () => {
  const base = harness.buildRecoveryIdentities('valid_nonce_456');

  // Valid base fixture passes
  harness.validateFixtureOwnership(base);

  // Null/non-object fixture
  assert.throws(() => harness.validateFixtureOwnership(null), /cleanup_blocked_missing_fixture_object/);
  assert.throws(() => harness.validateFixtureOwnership('string'), /cleanup_blocked_missing_fixture_object/);
  assert.throws(() => harness.buildCleanupQueries(null), /cleanup_blocked_missing_fixture_object/);

  // Missing or malformed label
  assert.throws(() => harness.validateFixtureOwnership({ ...base, label: undefined }), /cleanup_blocked_invalid_fixture_label/);
  assert.throws(() => harness.validateFixtureOwnership({ ...base, label: 'short' }), /cleanup_blocked_invalid_fixture_label/);
  assert.throws(() => harness.validateFixtureOwnership({ ...base, label: 12345 }), /cleanup_blocked_invalid_fixture_label/);
  assert.throws(() => harness.validateFixtureOwnership({ ...base, label: 'm028_invalid!chars' }), /cleanup_blocked_invalid_fixture_label/);

  // Mismatched ownerEmail
  assert.throws(() => harness.validateFixtureOwnership({ ...base, ownerEmail: 'admin@prod.com' }), /cleanup_blocked_ambiguous_owner_email/);
  assert.throws(() => harness.validateFixtureOwnership({ ...base, ownerEmail: `${base.label}_wrong@example.invalid` }), /cleanup_blocked_ambiguous_owner_email/);

  // Mismatched otherEmail
  assert.throws(() => harness.validateFixtureOwnership({ ...base, otherEmail: 'other@prod.com' }), /cleanup_blocked_ambiguous_other_email/);

  // Ambiguous user emails (identical or foreign)
  assert.throws(() => harness.validateFixtureOwnership({ ...base, otherEmail: base.ownerEmail }), /cleanup_blocked_ambiguous_other_email/);

  // Mismatched ownerOrgSlug
  assert.throws(() => harness.validateFixtureOwnership({ ...base, ownerOrgSlug: 'york_university' }), /cleanup_blocked_ambiguous_owner_slug/);

  // Mismatched otherOrgSlug
  assert.throws(() => harness.validateFixtureOwnership({ ...base, otherOrgSlug: 'foreign_org' }), /cleanup_blocked_ambiguous_other_slug/);

  // Ambiguous org slugs (identical or foreign)
  assert.throws(() => harness.validateFixtureOwnership({ ...base, otherOrgSlug: base.ownerOrgSlug }), /cleanup_blocked_ambiguous_other_slug/);

  // Mismatched bidTitle
  assert.throws(() => harness.validateFixtureOwnership({ ...base, bidTitle: 'York University P27-070' }), /cleanup_blocked_ambiguous_bid_title/);

  // Confirm buildCleanupQueries fails closed when validation fails
  assert.throws(() => harness.buildCleanupQueries({ ...base, bidTitle: 'York University P27-070' }), /cleanup_blocked_ambiguous_bid_title/);
});

// ── 5. Behavioral relational simulation helpers ──────────────────────────────

function createMockDatabase(f) {
  return {
    organizations: [
      { id: 'bench-org-uuid', slug: 'york_university' },
      { id: 'unrelated-org-uuid', slug: 'unrelated_corp' },
      { id: 'fixture-owner-org-uuid', slug: f.ownerOrgSlug },
      { id: 'fixture-other-org-uuid', slug: f.otherOrgSlug },
    ],
    bids: [
      { id: 1522, organization_id: 'bench-org-uuid', title: 'York University P27-070' },
      { id: 9001, organization_id: 'unrelated-org-uuid', title: 'Unrelated RFP' },
      { id: 8888, organization_id: 'fixture-owner-org-uuid', title: f.bidTitle },
    ],
    authUsers: [
      { id: 'bench-user-uuid', email: 'admin@york.example.ca' },
      { id: 'unrelated-user-uuid', email: 'user@unrelated.example.com' },
      { id: 'fixture-owner-user-uuid', email: f.ownerEmail },
      { id: 'fixture-other-user-uuid', email: f.otherEmail },
    ],
    analysisRuns: [
      { id: 5001, bid_id: 1522, engine_version: 'fast-analysis-v4' },
      { id: 5002, bid_id: 9001, engine_version: 'full-analysis-v1' },
      { id: 8889, bid_id: 8888, engine_version: f.label },
    ],
    analysisResults: [
      { id: 6001, bid_id: 1522, run_id: 5001, structured_intelligence: { safe: true, engine: 'v4' } },
      { id: 6002, bid_id: 9001, run_id: 5002, structured_intelligence: { safe: true, engine: 'v1' } },
      { id: 8890, bid_id: 8888, run_id: 8889, structured_intelligence: { safe: true, fixture_label: f.label } },
    ],
  };
}

function simulateResidueAudit(db, f) {
  const ownerOrgIds = new Set(db.organizations.filter(o => o.slug === f.ownerOrgSlug).map(o => o.id));
  const otherOrgIds = new Set(db.organizations.filter(o => o.slug === f.otherOrgSlug).map(o => o.id));
  const allFixtureOrgIds = new Set([...ownerOrgIds, ...otherOrgIds]);

  const matchingBids = db.bids.filter(b => b.title === f.bidTitle && ownerOrgIds.has(b.organization_id));

  // Independent marker lookups without joining to parent bid
  const matchingRuns = db.analysisRuns.filter(r => r.engine_version === f.label);
  const matchingResults = db.analysisResults.filter(res => res.structured_intelligence?.fixture_label === f.label);

  const matchingOrgs = db.organizations.filter(o => allFixtureOrgIds.has(o.id));
  const matchingUsers = db.authUsers.filter(u => u.email === f.ownerEmail || u.email === f.otherEmail);

  return (
    matchingBids.length +
    matchingRuns.length +
    matchingResults.length +
    matchingOrgs.length +
    matchingUsers.length
  );
}

function simulateDatabaseCleanup(db, f) {
  const ownerOrgIds = new Set(db.organizations.filter(o => o.slug === f.ownerOrgSlug).map(o => o.id));

  // 1. DELETE FROM public.bids WHERE title = '${safeBidTitle}' AND organization_id IN (SELECT id FROM public.organizations WHERE slug = '${safeOwnerSlug}');
  const bidsToDelete = db.bids.filter(b => b.title === f.bidTitle && ownerOrgIds.has(b.organization_id));
  const deletedBidIds = new Set(bidsToDelete.map(b => b.id));

  const updatedBids = db.bids.filter(b => !deletedBidIds.has(b.id));
  const updatedRuns = db.analysisRuns.filter(r => !deletedBidIds.has(r.bid_id));
  const updatedResults = db.analysisResults.filter(res => !deletedBidIds.has(res.bid_id));

  // 2. DELETE FROM public.organizations WHERE slug = '${safeOwnerSlug}' OR slug = '${safeOtherSlug}';
  const updatedOrgs = db.organizations.filter(o => o.slug !== f.ownerOrgSlug && o.slug !== f.otherOrgSlug);

  // 3. DELETE FROM auth.users WHERE email = '${safeOwnerEmail}' OR email = '${safeOtherEmail}';
  const updatedUsers = db.authUsers.filter(u => u.email !== f.ownerEmail && u.email !== f.otherEmail);

  return {
    organizations: updatedOrgs,
    bids: updatedBids,
    authUsers: updatedUsers,
    analysisRuns: updatedRuns,
    analysisResults: updatedResults,
  };
}

// ── 6. Adversarial cleanup & independent residue audit behavioral tests ─────

test('cleanup and residue audit with correct returned IDs safely clears fixture and preserves benchmark', () => {
  const ids = harness.buildRecoveryIdentities('correct_ids_test');
  const fixture = {
    ...ids,
    bidId: 8888,
    runId: 8889,
    resultId: 8890,
    ownerOrg: 'fixture-owner-org-uuid',
    otherOrg: 'fixture-other-org-uuid',
    ownerUser: 'fixture-owner-user-uuid',
    otherUser: 'fixture-other-user-uuid',
  };

  const queries = harness.buildCleanupQueries(fixture);
  // Verify returned IDs are NOT in SQL
  assert.strictEqual(queries.dbSql.includes('8888'), false);
  assert.strictEqual(queries.dbSql.includes('fixture-owner-org-uuid'), false);
  assert.strictEqual(queries.authSql.includes('fixture-owner-user-uuid'), false);
  assert.strictEqual(queries.residueSql.includes('8888'), false);
  // Diagnostic contains recorded IDs
  assert.strictEqual(queries.diagnostic.recordedBidId, '8888');

  const initialDb = createMockDatabase(fixture);
  assert.strictEqual(simulateResidueAudit(initialDb, fixture), 7);

  const cleanedDb = simulateDatabaseCleanup(initialDb, fixture);
  assert.strictEqual(simulateResidueAudit(cleanedDb, fixture), 0);

  // Canonical benchmark intact
  assert(cleanedDb.bids.some(b => b.id === 1522 && b.title === 'York University P27-070'));
  assert(cleanedDb.organizations.some(o => o.slug === 'york_university'));
  assert(cleanedDb.authUsers.some(u => u.email === 'admin@york.example.ca'));
  assert(cleanedDb.analysisRuns.some(r => r.id === 5001 && r.bid_id === 1522));
  assert(cleanedDb.analysisResults.some(res => res.id === 6001 && res.bid_id === 1522));
});

test('cleanup and residue audit with missing IDs (response loss) safely clears fixture', () => {
  const ids = harness.buildRecoveryIdentities('missing_ids_test');
  const fixture = {
    ...ids,
    bidId: null,
    runId: null,
    resultId: null,
    ownerOrg: null,
    otherOrg: null,
    ownerUser: null,
    otherUser: null,
  };

  const queries = harness.buildCleanupQueries(fixture);
  assert.strictEqual(queries.dbSql.includes('null'), false);
  assert.strictEqual(queries.authSql.includes('null'), false);
  assert.strictEqual(queries.residueSql.includes('null'), false);

  const initialDb = createMockDatabase(fixture);
  assert.strictEqual(simulateResidueAudit(initialDb, fixture), 7);

  const cleanedDb = simulateDatabaseCleanup(initialDb, fixture);
  assert.strictEqual(simulateResidueAudit(cleanedDb, fixture), 0);
  assert(cleanedDb.bids.some(b => b.id === 1522));
});

test('cleanup and residue audit with malformed IDs drops injections and safely clears fixture', () => {
  const ids = harness.buildRecoveryIdentities('malformed_ids_test');
  const fixture = {
    ...ids,
    bidId: "1 OR 1=1",
    runId: "bad-run",
    resultId: "bad-res",
    ownerOrg: "'; DROP TABLE organizations; --",
    otherOrg: "bad-uuid",
    ownerUser: "attacker-user'; DROP TABLE auth.users; --",
    otherUser: "invalid",
  };

  const queries = harness.buildCleanupQueries(fixture);
  assert.strictEqual(queries.dbSql.includes('DROP'), false);
  assert.strictEqual(queries.dbSql.includes('OR 1=1'), false);
  assert.strictEqual(queries.authSql.includes('DROP'), false);
  assert.strictEqual(queries.residueSql.includes('DROP'), false);

  const initialDb = createMockDatabase(fixture);
  assert.strictEqual(simulateResidueAudit(initialDb, fixture), 7);

  const cleanedDb = simulateDatabaseCleanup(initialDb, fixture);
  assert.strictEqual(simulateResidueAudit(cleanedDb, fixture), 0);
  assert(cleanedDb.bids.some(b => b.id === 1522));
});

test('adversarial: valid but unrelated bid ID (canonical benchmark 1522) cannot delete benchmark and cannot cause false-zero residue', () => {
  const ids = harness.buildRecoveryIdentities('unrelated_bid_test');
  const fixture = {
    ...ids,
    bidId: 1522, // Canonical benchmark ID
    runId: 9999,
    resultId: 9998,
    ownerOrg: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    otherOrg: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    ownerUser: '11111111-1111-4111-8111-111111111111',
    otherUser: '22222222-2222-4222-8222-222222222222',
  };

  const queries = harness.buildCleanupQueries(fixture);
  // Unrelated ID must NOT appear in SQL
  assert.strictEqual(queries.dbSql.includes('1522'), false);
  assert.strictEqual(queries.residueSql.includes('1522'), false);

  const initialDb = createMockDatabase(fixture);

  // PROVE 2A: The genuine synthetic fixture remains discoverable by the independent residue audit
  const preResidue = simulateResidueAudit(initialDb, fixture);
  assert.strictEqual(preResidue, 7, 'Genuine fixture must be discovered before cleanup despite wrong bidId');

  // Perform cleanup
  const cleanedDb = simulateDatabaseCleanup(initialDb, fixture);

  // PROVE 1: No unrelated record can be selected for deletion
  const benchmarkBid = cleanedDb.bids.find(b => b.id === 1522);
  assert(benchmarkBid, 'Benchmark bid 1522 must NEVER be deleted');
  assert.strictEqual(benchmarkBid.title, 'York University P27-070');
  assert.strictEqual(cleanedDb.bids.some(b => b.id === 9001), true, 'Unrelated tenant bid must remain');

  // PROVE 2B: The genuine synthetic fixture was safely removed by exact-identity cleanup, and residue returns 0
  const postResidue = simulateResidueAudit(cleanedDb, fixture);
  assert.strictEqual(postResidue, 0, 'Residue must be exactly 0 after genuine fixture removal');
  assert.strictEqual(cleanedDb.bids.some(b => b.title === ids.bidTitle), false, 'Genuine synthetic bid must be gone');
});

test('adversarial: valid but unrelated organization UUID cannot delete benchmark org and cannot cause false-zero residue', () => {
  const ids = harness.buildRecoveryIdentities('unrelated_org_test');
  const fixture = {
    ...ids,
    ownerOrg: 'bench-org-uuid', // Canonical benchmark organization UUID
  };

  const queries = harness.buildCleanupQueries(fixture);
  assert.strictEqual(queries.dbSql.includes('bench-org-uuid'), false);
  assert.strictEqual(queries.residueSql.includes('bench-org-uuid'), false);

  const initialDb = createMockDatabase(fixture);

  // PROVE 2A: Genuine fixture discovered before cleanup
  assert.strictEqual(simulateResidueAudit(initialDb, fixture), 7);

  // Cleanup
  const cleanedDb = simulateDatabaseCleanup(initialDb, fixture);

  // PROVE 1: Benchmark org is not deleted
  assert(cleanedDb.organizations.some(o => o.id === 'bench-org-uuid' && o.slug === 'york_university'));
  assert(cleanedDb.organizations.some(o => o.slug === 'unrelated_corp'));

  // PROVE 2B: Genuine fixture removed, residue is 0
  assert.strictEqual(simulateResidueAudit(cleanedDb, fixture), 0);
  assert.strictEqual(cleanedDb.organizations.some(o => o.slug === ids.ownerOrgSlug), false);
});

test('adversarial: valid but unrelated Auth UUID cannot delete benchmark user and cannot cause false-zero residue', () => {
  const ids = harness.buildRecoveryIdentities('unrelated_user_test');
  const fixture = {
    ...ids,
    ownerUser: 'bench-user-uuid', // Benchmark user UUID
  };

  const queries = harness.buildCleanupQueries(fixture);
  assert.strictEqual(queries.authSql.includes('bench-user-uuid'), false);
  assert.strictEqual(queries.residueSql.includes('bench-user-uuid'), false);

  const initialDb = createMockDatabase(fixture);

  // PROVE 2A: Genuine fixture discovered
  assert.strictEqual(simulateResidueAudit(initialDb, fixture), 7);

  // Cleanup
  const cleanedDb = simulateDatabaseCleanup(initialDb, fixture);

  // PROVE 1: Benchmark user is not deleted
  assert(cleanedDb.authUsers.some(u => u.id === 'bench-user-uuid' && u.email === 'admin@york.example.ca'));
  assert(cleanedDb.authUsers.some(u => u.email === 'user@unrelated.example.com'));

  // PROVE 2B: Genuine fixture removed, residue is 0
  assert.strictEqual(simulateResidueAudit(cleanedDb, fixture), 0);
  assert.strictEqual(cleanedDb.authUsers.some(u => u.email === ids.ownerEmail), false);
});

test('adversarial: valid but unrelated run and result IDs cannot affect benchmark runs or cause false-zero residue', () => {
  const ids = harness.buildRecoveryIdentities('unrelated_run_test');
  const fixture = {
    ...ids,
    runId: 5001,    // Benchmark run ID
    resultId: 6001, // Benchmark result ID
  };

  const queries = harness.buildCleanupQueries(fixture);
  assert.strictEqual(queries.dbSql.includes('5001'), false);
  assert.strictEqual(queries.residueSql.includes('5001'), false);

  const initialDb = createMockDatabase(fixture);
  assert.strictEqual(simulateResidueAudit(initialDb, fixture), 7);

  const cleanedDb = simulateDatabaseCleanup(initialDb, fixture);

  // PROVE 1: Benchmark runs and results intact
  assert(cleanedDb.analysisRuns.some(r => r.id === 5001));
  assert(cleanedDb.analysisResults.some(res => res.id === 6001));

  // PROVE 2B: Genuine fixture removed, residue is 0
  assert.strictEqual(simulateResidueAudit(cleanedDb, fixture), 0);
});

test('partial-success response loss (users/orgs created, bid lost) is fully cleaned up', () => {
  const ids = harness.buildRecoveryIdentities('partial_loss_test');
  const fixture = {
    ...ids,
    bidId: null,
    runId: null,
    resultId: null,
    ownerOrg: 'fixture-owner-org-uuid',
    otherOrg: 'fixture-other-org-uuid',
    ownerUser: 'fixture-owner-user-uuid',
    otherUser: 'fixture-other-user-uuid',
  };

  const initialDb = createMockDatabase(fixture);
  assert.strictEqual(simulateResidueAudit(initialDb, fixture), 7);

  const cleanedDb = simulateDatabaseCleanup(initialDb, fixture);
  assert.strictEqual(simulateResidueAudit(cleanedDb, fixture), 0);
  assert.strictEqual(cleanedDb.organizations.some(o => o.slug === ids.ownerOrgSlug), false);
  assert.strictEqual(cleanedDb.authUsers.some(u => u.email === ids.ownerEmail), false);
});

test('repeated cleanup is idempotent and deterministic', () => {
  const ids = harness.buildRecoveryIdentities('repeat_clean_test');
  const fixture = {
    ...ids,
    bidId: 42,
    ownerOrg: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    otherOrg: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    ownerUser: '11111111-1111-4111-8111-111111111111',
    otherUser: '22222222-2222-4222-8222-222222222222',
    runId: 84,
  };

  const first = harness.buildCleanupQueries(fixture);
  const second = harness.buildCleanupQueries(fixture);

  assert.strictEqual(first.dbSql, second.dbSql);
  assert.strictEqual(first.authSql, second.authSql);
  assert.strictEqual(first.residueSql, second.residueSql);

  const initialDb = createMockDatabase(fixture);
  const firstClean = simulateDatabaseCleanup(initialDb, fixture);
  assert.strictEqual(simulateResidueAudit(firstClean, fixture), 0);

  const secondClean = simulateDatabaseCleanup(firstClean, fixture);
  assert.strictEqual(simulateResidueAudit(secondClean, fixture), 0);
});

// ── 7. Broken-cascade negative tests & marker isolation ─────────────────────

test('broken-cascade negative test A: fixture bid deleted, but fixture run and result remain, producing nonzero residue', () => {
  const ids = harness.buildRecoveryIdentities('broken_cascade_a');
  const fixture = { ...ids };

  const db = createMockDatabase(fixture);
  // Simulate incomplete cascade: bid, orgs, and users were deleted, but run and result remained orphaned
  db.bids = db.bids.filter(b => b.title !== fixture.bidTitle);
  db.organizations = db.organizations.filter(o => o.slug !== fixture.ownerOrgSlug && o.slug !== fixture.otherOrgSlug);
  db.authUsers = db.authUsers.filter(u => u.email !== fixture.ownerEmail && u.email !== fixture.otherEmail);

  // Confirm parent bid is completely absent
  assert.strictEqual(db.bids.some(b => b.title === fixture.bidTitle), false, 'Parent bid must be deleted');
  // Confirm orphaned run and result still carry exact fixture marker
  assert.strictEqual(db.analysisRuns.some(r => r.engine_version === fixture.label), true, 'Orphaned run must exist');
  assert.strictEqual(db.analysisResults.some(res => res.structured_intelligence?.fixture_label === fixture.label), true, 'Orphaned result must exist');

  // Independent residue audit MUST discover orphaned run and result without depending on parent bid
  const residue = simulateResidueAudit(db, fixture);
  assert.strictEqual(residue, 2, 'Orphaned run and result must both be detected, producing nonzero residue (2)');
  assert(residue > 0, 'Residue must be strictly greater than 0');
});

test('broken-cascade negative test B: fixture bid and run deleted, but fixture result remains, producing nonzero residue', () => {
  const ids = harness.buildRecoveryIdentities('broken_cascade_b');
  const fixture = { ...ids };

  const db = createMockDatabase(fixture);
  // Simulate incomplete cascade: bid, run, orgs, and users were deleted, but result remained orphaned
  db.bids = db.bids.filter(b => b.title !== fixture.bidTitle);
  db.analysisRuns = db.analysisRuns.filter(r => r.engine_version !== fixture.label);
  db.organizations = db.organizations.filter(o => o.slug !== fixture.ownerOrgSlug && o.slug !== fixture.otherOrgSlug);
  db.authUsers = db.authUsers.filter(u => u.email !== fixture.ownerEmail && u.email !== fixture.otherEmail);

  // Confirm parent bid and parent run are completely absent
  assert.strictEqual(db.bids.some(b => b.title === fixture.bidTitle), false, 'Parent bid must be deleted');
  assert.strictEqual(db.analysisRuns.some(r => r.engine_version === fixture.label), false, 'Parent run must be deleted');
  // Confirm orphaned result still carries exact fixture marker
  assert.strictEqual(db.analysisResults.some(res => res.structured_intelligence?.fixture_label === fixture.label), true, 'Orphaned result must exist');

  // Independent residue audit MUST discover orphaned result without depending on parent run or bid
  const residue = simulateResidueAudit(db, fixture);
  assert.strictEqual(residue, 1, 'Orphaned result must be detected, producing nonzero residue (1)');
  assert(residue > 0, 'Residue must be strictly greater than 0');
});

test('unrelated runs and results carrying different markers remain untouched and are never counted as fixture residue', () => {
  const ids = harness.buildRecoveryIdentities('unrelated_marker_isolation');
  const fixture = { ...ids };

  const db = createMockDatabase(fixture);
  // Before cleanup, residue finds exactly the 7 fixture rows, NOT unrelated rows
  assert.strictEqual(simulateResidueAudit(db, fixture), 7);

  // Clean the database
  const cleanedDb = simulateDatabaseCleanup(db, fixture);

  // Verify benchmark and unrelated runs/results carrying different markers are intact
  const benchmarkRun = cleanedDb.analysisRuns.find(r => r.id === 5001);
  const unrelatedRun = cleanedDb.analysisRuns.find(r => r.id === 5002);
  const benchmarkRes = cleanedDb.analysisResults.find(res => res.id === 6001);
  const unrelatedRes = cleanedDb.analysisResults.find(res => res.id === 6002);

  assert(benchmarkRun && benchmarkRun.engine_version === 'fast-analysis-v4', 'Benchmark run must remain intact');
  assert(unrelatedRun && unrelatedRun.engine_version === 'full-analysis-v1', 'Unrelated run must remain intact');
  assert(benchmarkRes && benchmarkRes.structured_intelligence.engine === 'v4', 'Benchmark result must remain intact');
  assert(unrelatedRes && unrelatedRes.structured_intelligence.engine === 'v1', 'Unrelated result must remain intact');

  // Residue audit must NEVER match unrelated markers
  const postResidue = simulateResidueAudit(cleanedDb, fixture);
  assert.strictEqual(postResidue, 0, 'Post-cleanup residue must be 0; unrelated markers must never match');
});

test('residueSql independently queries runs and results without joining to parent bid', () => {
  const ids = harness.buildRecoveryIdentities('sql_structure_check');
  const queries = harness.buildCleanupQueries(ids);

  // Must independently select analysis_runs by exact engine_version marker
  assert(
    queries.residueSql.includes(`SELECT 1 FROM public.analysis_runs WHERE engine_version = '${ids.label}'`),
    'Residue query must independently locate analysis_runs by exact engine_version marker'
  );

  // Must independently select analysis_results by exact structured_intelligence fixture_label marker
  assert(
    queries.residueSql.includes(`SELECT 1 FROM public.analysis_results WHERE structured_intelligence->>'fixture_label' = '${ids.label}'`),
    'Residue query must independently locate analysis_results by exact JSON fixture_label marker'
  );

  // Must NOT join analysis_runs or analysis_results to public.bids
  assert.strictEqual(
    queries.residueSql.includes('JOIN public.bids'),
    false,
    'Residue query must NOT join runs or results to public.bids'
  );
});

// ── 8. Seed output parsing and deterministic machine-readable format tests ────

test('parseSeedOutput successfully parses real-world psql output with DO command tag', () => {
  const psqlOut = 'DO\nM028_FIXTURE_SEED:8888|550e8400-e29b-41d4-a716-446655440000|6ba7b810-9dad-11d1-80b4-00c04fd430c8|8889|8890\n';
  const parsed = harness.parseSeedOutput(psqlOut);
  assert.deepStrictEqual(parsed, {
    bidId: '8888',
    ownerOrg: '550e8400-e29b-41d4-a716-446655440000',
    otherOrg: '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
    runId: '8889',
    resultId: '8890'
  });
});

test('parseSeedOutput handles extra whitespace, transaction tags, and notices', () => {
  const trailingSpaces = '  ';
  const sample = `
  BEGIN
  NOTICE:  table created
  DO
    M028_FIXTURE_SEED:  123 | 550e8400-e29b-41d4-a716-446655440000 | 6ba7b810-9dad-11d1-80b4-00c04fd430c8 | 456 | 789${trailingSpaces}
  COMMIT
  `;
  const parsed = harness.parseSeedOutput(sample);
  assert.deepStrictEqual(parsed, {
    bidId: '123',
    ownerOrg: '550e8400-e29b-41d4-a716-446655440000',
    otherOrg: '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
    runId: '456',
    resultId: '789'
  });
});

test('parseSeedOutput rejects malformed delimiters and field counts', () => {
  const cases = [
    'M028_FIXTURE_SEED:123,550e8400-e29b-41d4-a716-446655440000,6ba7b810-9dad-11d1-80b4-00c04fd430c8,456,789', // comma instead of pipe
    'M028_FIXTURE_SEED:123|550e8400-e29b-41d4-a716-446655440000|6ba7b810-9dad-11d1-80b4-00c04fd430c8|456', // only 4 fields
    'M028_FIXTURE_SEED:123|550e8400-e29b-41d4-a716-446655440000|6ba7b810-9dad-11d1-80b4-00c04fd430c8|456|789|extra', // 6 fields
    'M028_FIXTURE_SEED:', // empty payload
  ];
  for (const raw of cases) {
    assert.throws(
      () => harness.parseSeedOutput(raw),
      err => err.message.includes('fixture_seed_format_invalid'),
      `Should reject: ${raw}`
    );
  }
});

test('parseSeedOutput strictly validates identifier types and fails closed on invalid fields', () => {
  // Invalid bidId
  assert.throws(
    () => harness.parseSeedOutput('M028_FIXTURE_SEED:0|550e8400-e29b-41d4-a716-446655440000|6ba7b810-9dad-11d1-80b4-00c04fd430c8|456|789'),
    err => err.message.includes('fixture_seed_bid_id_invalid')
  );
  assert.throws(
    () => harness.parseSeedOutput('M028_FIXTURE_SEED:-1|550e8400-e29b-41d4-a716-446655440000|6ba7b810-9dad-11d1-80b4-00c04fd430c8|456|789'),
    err => err.message.includes('fixture_seed_bid_id_invalid')
  );
  assert.throws(
    () => harness.parseSeedOutput('M028_FIXTURE_SEED:abc|550e8400-e29b-41d4-a716-446655440000|6ba7b810-9dad-11d1-80b4-00c04fd430c8|456|789'),
    err => err.message.includes('fixture_seed_bid_id_invalid')
  );

  // Invalid ownerOrg
  assert.throws(
    () => harness.parseSeedOutput('M028_FIXTURE_SEED:123|not-a-uuid|6ba7b810-9dad-11d1-80b4-00c04fd430c8|456|789'),
    err => err.message.includes('fixture_seed_owner_org_invalid')
  );

  // Invalid otherOrg
  assert.throws(
    () => harness.parseSeedOutput('M028_FIXTURE_SEED:123|550e8400-e29b-41d4-a716-446655440000|malformed-uuid|456|789'),
    err => err.message.includes('fixture_seed_other_org_invalid')
  );

  // Invalid runId
  assert.throws(
    () => harness.parseSeedOutput('M028_FIXTURE_SEED:123|550e8400-e29b-41d4-a716-446655440000|6ba7b810-9dad-11d1-80b4-00c04fd430c8|0|789'),
    err => err.message.includes('fixture_seed_run_id_invalid')
  );

  // Invalid resultId
  assert.throws(
    () => harness.parseSeedOutput('M028_FIXTURE_SEED:123|550e8400-e29b-41d4-a716-446655440000|6ba7b810-9dad-11d1-80b4-00c04fd430c8|456|foo'),
    err => err.message.includes('fixture_seed_result_id_invalid')
  );
});

test('parseSeedOutput rejects empty, non-string, or failed psql output', () => {
  const missingCases = [
    null,
    undefined,
    12345,
    '',
    '   ',
    'DO\n',
    'ERROR:  relation "public.organizations" does not exist\nROLLBACK',
    'FATAL:  password authentication failed for user "postgres"',
  ];
  for (const raw of missingCases) {
    assert.throws(
      () => harness.parseSeedOutput(raw),
      err => err.message.includes('fixture_seed_output_missing'),
      `Should fail with fixture_seed_output_missing: ${raw}`
    );
  }
});

test('parseSeedOutput rejects ambiguous output with multiple seed lines', () => {
  const ambiguous = `
  M028_FIXTURE_SEED:123|550e8400-e29b-41d4-a716-446655440000|6ba7b810-9dad-11d1-80b4-00c04fd430c8|456|789
  M028_FIXTURE_SEED:999|550e8400-e29b-41d4-a716-446655440000|6ba7b810-9dad-11d1-80b4-00c04fd430c8|888|777
  `;
  assert.throws(
    () => harness.parseSeedOutput(ambiguous),
    err => err.message.includes('fixture_seed_format_invalid'),
    'Should reject ambiguous multiple seed lines'
  );
});

test('partial seed failure preserves safe cleanup and zero-residue recovery via pre-recorded identities', () => {
  const recovery = harness.buildRecoveryIdentities('partial_seed_test');
  const fixture = { ...recovery }; // No bidId, ownerOrg, otherOrg, runId, or resultId populated!

  const db = createMockDatabase(fixture);
  // Before cleanup, residue finds the seeded synthetic records by exact slugs/emails/markers
  assert.strictEqual(simulateResidueAudit(db, fixture), 7);

  // Even without returned IDs from seed(), cleanup successfully and safely purges the fixture
  const cleanedDb = simulateDatabaseCleanup(db, fixture);
  assert.strictEqual(simulateResidueAudit(cleanedDb, fixture), 0);
});

console.log(`\nALL ${passedCount} HARNESS UNIT TESTS PASSED.`);
