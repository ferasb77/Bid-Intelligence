# Current PCI State

Phase:
PCI-A.1 — Durability & Invariant Closure

Architecture decision:
A procurement is modeled as a living, chronological revision sequence
(Revision 0 baseline + additive buyer revisions 1, 2, ...).
Historical revisions remain immutable.
Authoritative current state is derived deterministically by replaying
fact-level changes in buyer chronological order.
Field-level precedence ensures addenda modify only explicitly touched facts;
unrelated facts survive unchanged.
Ambiguous conflicts do not auto-resolve and are flagged as HUMAN_REVIEW_REQUIRED.
Idempotent document hashing prevents duplicate revisions from re-uploads.
Out-of-order uploads are re-ordered by buyer chronology rather than upload time.

Durability & Persistence:
PCI-A.1 closes in-memory gaps with genuine database-backed durability:
- Storage abstraction: `PCIBaseStorage` with `InMemoryPCIStorage` (test/restart simulation) and `PCIDatabaseStorage` (production Supabase).
- Direct rehydration APIs: `load_revision_history(bid_id, org_id)` and `load_current_authoritative_state(bid_id, org_id)`.
- Tenancy enforcement: Verified against persistent storage (`bids.organization_id`), failing closed on cross-org access.
- Optimistic concurrency: `expected_base_revision` checked against persisted DB revision counter, raising `StaleRevisionError` on race conditions.
- Real content identity: Rejects empty/missing document `content_hash` and fact `source_hash` (`ValueError`), prohibiting synthetic hashes.
- Invariant separation: System Procurement Revision (monotonic applied counter) is strictly decoupled from Buyer Chronology (`buyer_chronology_index`).
- Semantic fingerprint isolation: `compute_state_fingerprint` depends strictly on active facts and artifacts, remaining stable across non-semantic revisions (`OUTCOME_NEW_REVISION_NO_SEMANTIC_CHANGE`), while `compute_revision_fingerprint` uniquely tracks graph node identity.

Schema reused/changed:
REUSE_EXISTING_SCHEMA.
No new database migration or DDL was introduced.
Reuses existing migration 010 schema primitives:
- `bids.procurement_revision`
- `bids.procurement_truth_status`
- `documents.content_hash`
- `requirements.lifecycle_status` ('active', 'superseded', 'removed')
- `requirements.retired_at_procurement_revision`
- `procurement_update_reviews` (`document_set_digest`, `buyer_update_type`, `buyer_issued_date`, `status`, `base_procurement_revision`, `resulting_procurement_revision`, `idempotency_key`, `no_canonical_change`)
- `procurement_update_review_documents` (`role`, `document_hash`)
- `procurement_changes` (`review_decision`, `change_type`, `canonical_effect`, `entity_type`, `entity_id`, `previous_value`, `new_value`, `source_document_hash`, `physical_source_ref`)
- `procurement_conflicts` (`unresolved`, `resolved`)

Entry manifest for next phase (maximum 5 files):
1. `procurement_change_intelligence.py` — Core revision manager, durable storage adapters, rehydration, and state replay
2. `tests/test_procurement_change_intelligence.py` — Test fixtures A-J, durability, concurrency, and schema mapping tests
3. `migrations/010_procurement_revision_governance.sql` — Existing revision governance schema and trigger immutability contract
4. `database.py` — Procurement revision governance query methods (`get_procurement_update_reviews`, `get_procurement_update_review_documents`, `get_procurement_changes`)
5. `canonical_procurement.py` — Semantic typing, closed vocabularies, and field-level authority definitions

Durable objects:
- `FactChange`: Bounded fact-level mutation with change_type, before/after values, and verified source hash
- `ArtifactRecord`: Buyer-issued file artifact status tracking (CURRENT / SUPERSEDED)
- `ProcurementChangeSet`: Deterministic change set for a revision with stable semantic fingerprint
- `ProcurementRevision`: Immutable revision node in chronological chain with parent pointer, separating system revision from buyer chronology
- `AuthoritativeProcurementState`: Deterministically derived current state separating active facts, superseded facts, pending conflicts, and active artifacts
- `PCIBaseStorage` / `InMemoryPCIStorage` / `PCIDatabaseStorage`: Durable adapters mapping PCI state to Migration 010 persistence

Key invariants:
- Previous revisions are immutable
- Identical document uploads yield NO_NEW_REVISION (idempotency across process restarts)
- Latest authoritative buyer fact outranks older facts via chronological replay
- Superseded facts remain queryable in history
- Unrelated facts survive unchanged across revisions
- Out-of-order uploads preserve buyer chronology
- Corrections can supersede facts introduced by earlier addenda
- Ambiguous precedence requires human confirmation without auto-resolving
- Semantic fingerprints change only when facts change; revision fingerprints change on every revision
- Tenancy boundaries hold across bid and organization boundaries against persisted storage
- Revision creation is concurrency safe via database-level optimistic locking
- Real document content hashes and fact source hashes are strictly required

Tests:
`tests/test_procurement_change_intelligence.py` (35 passed, 0 failed):
- Fixtures A through J (10 tests)
- Concurrency and optimistic locking (3 tests)
- Invariant verification (4 tests)
- Document classification and chronology extraction (2 tests)
- Migration 010 schema mapping (1 test)
- Durability and process restart rehydration (13 tests)
- Production storage wiring proof: default `PCIDatabaseStorage` (1 test)
- Atomic optimistic database concurrency proof across independent instances (1 test)

Open issues:
None for PCI-A.1. Durability and invariants fully closed.

Next phase:
PCI-B Impact Routing + Incremental Intelligence
