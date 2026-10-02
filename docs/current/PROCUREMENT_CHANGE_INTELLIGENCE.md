# Current PCI State

Phase:
PCI-A — Revision Foundation + Deterministic Change Model

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

Schema reused/changed:
REUSE_EXISTING_SCHEMA.
No new database migration or DDL was introduced.
Reuses existing migration 010 schema primitives:
- `bids.procurement_revision`
- `bids.procurement_truth_status`
- `documents.content_hash`
- `requirements.lifecycle_status` ('active', 'superseded', 'removed')
- `requirements.retired_at_procurement_revision`
- `procurement_update_reviews` (`document_set_digest`, `buyer_update_type`, `buyer_issued_date`, `status`)
- `procurement_update_review_documents` (`role`, `document_hash`)
- `procurement_changes` (`review_decision`, `change_type`, `entity_type`, `entity_id`, `before_value`, `new_value`, `source_document_hash`)
- `procurement_conflicts` (`unresolved`, `resolved`)

Files:
1. `procurement_change_intelligence.py` — Core PCI-A engine (pure, deterministic revision manager, replay, change taxonomy, fingerprints)
2. `tests/test_procurement_change_intelligence.py` — Deterministic test suite covering fixtures A-J, invariants, concurrency, and schema mapping
3. `migrations/010_procurement_revision_governance.sql` — Existing revision governance schema and trigger immutability contract
4. `canonical_procurement.py` — Semantic typing, closed vocabularies, and field-level authority definitions
5. `document_provenance.py` — Document relationship classification and package completeness

Durable objects:
- `FactChange`: Bounded fact-level mutation with change_type (ADDS, SUPERSEDES, REPLACES, CORRECTS, CLARIFIES, NARROWS, EXPANDS, CONFLICTS_WITH, REMOVES, UNCHANGED), before/after values, and source provenance
- `ArtifactRecord`: Buyer-issued file artifact status tracking (CURRENT / SUPERSEDED)
- `ProcurementChangeSet`: Deterministic change set for a revision with stable semantic fingerprint
- `ProcurementRevision`: Immutable revision node in chronological chain with parent pointer
- `AuthoritativeProcurementState`: Deterministically derived current state separating active facts, superseded facts, pending conflicts, and active artifacts

Key invariants:
- Previous revisions are immutable
- Identical document uploads yield NO_NEW_REVISION (idempotency)
- Latest authoritative buyer fact outranks older facts
- Superseded facts remain queryable in history
- Unrelated facts survive unchanged across revisions
- Out-of-order uploads preserve buyer chronology
- Corrections can supersede facts introduced by earlier addenda
- Ambiguous precedence requires human confirmation without auto-resolving
- Semantic fingerprints change only when facts change
- Tenancy boundaries hold across bid and organization boundaries
- Revision creation is concurrency safe via optimistic locking

Tests:
`tests/test_procurement_change_intelligence.py` (18 passed, 0 failed):
- Fixtures A through J
- Concurrency and optimistic locking
- Invariant verification
- Multi-threaded race condition safety
- Migration 010 column mapping compatibility

Open issues:
None for PCI-A. Ready for PCI-B.

Next phase:
PCI-B Impact Routing + Incremental Intelligence
