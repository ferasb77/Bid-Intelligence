# Current PCI State

Phase:
PCI-A.2 — Governed Apply & Durable Chronology

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

Durability, Persistence & Governed Apply (PCI-A.2):
PCI-A.2 integrates revision intelligence with governed atomic apply and durable chronology:
1. Transactional Governed Apply:
   - Direct SQL updates to `bids.procurement_revision` from Python are strictly prohibited.
   - All revision state transitions flow through the Migration 010 RPC lifecycle:
     a. `create_procurement_update_review` RPC creates review in status `'analyzing'`.
     b. Changes are staged into `procurement_changes` with `review_decision='pending'`.
     c. Review status transitions to `'ready_for_review'`.
     d. Decisions are recorded via `record_change_review_decision` RPC (`decision='approved'`).
     e. Final apply occurs inside `apply_procurement_update_review` RPC (optimistic concurrency check, conditional revision increment, atomic lock).
   - Any failure before or during apply leaves `bids.procurement_revision` untouched.
2. Real Document Identity (Fail-Closed):
   - Every document must provide a genuine integer `document_id` and non-empty `content_hash`.
   - Fabricated or missing document IDs fail closed (`ValueError`).
3. Multi-Document Buyer Updates:
   - Compound updates spanning multiple physical files (e.g. Addendum letter + Replacement Pricing Form) are supported.
   - Exactly one `primary` document role is enforced per review (`primary`, `replacement`, `supporting`).
4. Two Distinct Sequences:
   - Buyer Update Event: Every legitimate buyer-issued document set creates a durable review record.
   - Canonical Procurement Revision: `bids.procurement_revision` advances only when approved canonical changes exist. Non-semantic notices create durable events with `no_canonical_change=True` without bumping canonical revision.
5. Durable Buyer Chronology:
   - Reconstructed deterministically from persisted document metadata (`extract_chronology_metadata` on primary document name + buyer issued date).
   - Ambiguous documents are flagged with `chronology_unresolved=True`, routing changes to `pending_conflicts` with `REVIEW_STATUS_HUMAN_REVIEW_REQUIRED`. Never falls back to revision numbers.

Schema reused/changed:
REUSE_EXISTING_SCHEMA.
No new database migration or DDL was introduced.
Reuses existing migration 010 schema primitives:
- `bids.procurement_revision`
- `bids.procurement_truth_status`
- `documents.id`, `documents.name`, `documents.content_hash`
- `requirements.lifecycle_status` ('active', 'superseded', 'removed')
- `requirements.retired_at_procurement_revision`
- `procurement_update_reviews` (`document_set_digest`, `buyer_update_type`, `buyer_issued_date`, `status`, `base_procurement_revision`, `resulting_procurement_revision`, `idempotency_key`, `no_canonical_change`)
- `procurement_update_review_documents` (`role`, `document_hash`, `document_id`)
- `procurement_changes` (`review_decision`, `change_type`, `canonical_effect`, `entity_type`, `entity_id`, `previous_value`, `new_value`, `source_document_id`, `source_document_hash`, `physical_source_ref`)
- `procurement_conflicts` (`unresolved`, `resolved`)

Entry manifest for next phase (maximum 5 files):
1. `procurement_change_intelligence.py` — Core revision manager, durable storage adapters, rehydration, state replay, and governed apply
2. `tests/test_procurement_change_intelligence.py` — Test fixtures A-J, durability, concurrency, schema mapping, and PCI-A.2 regression tests
3. `migrations/010_procurement_revision_governance.sql` — Existing revision governance schema and trigger immutability contract
4. `database.py` — Procurement revision governance query methods and RPC wrappers
5. `canonical_procurement.py` — Semantic typing, closed vocabularies, and field-level authority definitions

Durable objects:
- `FactChange`: Bounded fact-level mutation with change_type, before/after values, verified source hash, and `source_document_id`
- `ArtifactRecord`: Buyer-issued file artifact status tracking (CURRENT / SUPERSEDED)
- `ProcurementChangeSet`: Deterministic change set for a revision with stable semantic fingerprint
- `ProcurementRevision`: Immutable revision node in chronological chain with parent pointer, separating system revision from buyer chronology, with `chronology_unresolved` and `no_canonical_change` flags
- `AuthoritativeProcurementState`: Deterministically derived current state separating active facts, superseded facts, pending conflicts, and active artifacts
- `PCIBaseStorage` / `InMemoryPCIStorage` / `PCIDatabaseStorage`: Durable adapters mapping PCI state to Migration 010 persistence and RPC lifecycle

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
- Real document content hashes and integer document IDs are strictly required
- Governed apply is transactional via Migration 010 RPC

Tests:
`tests/test_procurement_change_intelligence.py` (40 passed, 0 failed):
- Fixtures A through J (10 tests)
- Concurrency and optimistic locking (3 tests)
- Invariant verification (4 tests)
- Document classification and chronology extraction (2 tests)
- Migration 010 schema mapping (1 test)
- Durability and process restart rehydration (13 tests)
- Production storage wiring proof: default `PCIDatabaseStorage` (1 test)
- Atomic optimistic database concurrency proof across independent instances (1 test)
- PCI-A.2 Governed Apply & Durable Chronology regression tests (5 tests)

Open issues:
None for PCI-A.2. Governed apply and durable chronology fully closed.

Next phase:
PCI-B Impact Routing + Incremental Intelligence
