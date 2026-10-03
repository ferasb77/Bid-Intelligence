# Current PCI State

Phase:
PCI-B1 — Impact Routing & Intelligence Dependency Model

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

Durability, Persistence & Governed Apply (PCI-A.2 & PCI-A.2.1):
1. Transactional Governed Apply:
   - Direct SQL updates to `bids.procurement_revision` from Python are strictly prohibited.
   - All revision state transitions flow through the Migration 010 RPC lifecycle:
     a. `create_procurement_update_review` RPC creates review in status `'analyzing'`.
     b. Changes are staged into `procurement_changes` with `review_decision='pending'`.
     c. Review status transitions to `'ready_for_review'`.
     d. Decisions are recorded via `record_change_review_decision` RPC (`decision='approved'` only for approved changes).
     e. Final apply occurs inside `apply_procurement_update_review` RPC (optimistic concurrency check, conditional revision increment, atomic lock).
   - Any failure before or during apply leaves `bids.procurement_revision` untouched.
2. Human-Review Gate & Zero Auto-Approval:
   - Changes with `HUMAN_REVIEW_REQUIRED`, `PENDING`, `REJECTED`, or `CHANGE_CONFLICTS_WITH`, and revisions with `chronology_unresolved=True`, are NEVER auto-approved.
   - Governed Apply Gate is All-or-Nothing: If any material change remains unapproved or chronology is unresolved, `apply_procurement_update_review` is NOT called. The review remains in `'ready_for_review'`, `bids.procurement_revision` does not advance, and canonical truth is untouched (no partial apply).
   - Unapplied reviews and pending conflicts survive manager restart and rehydration from storage across instances.
3. Exact Source Provenance (Fail-Closed):
   - Every `FactChange` must provide a genuine integer `source_document_id` matching an input document in the revision.
   - `source_hash` must match the content hash of that specific document.
   - Missing, non-integer, or mismatched document IDs fail closed (`ValueError`). No fallback to primary document ID.

Impact Routing & Intelligence Dependency Model (PCI-B1):
1. Strict Authority Boundary:
   - Consumes ONLY applied, approved canonical changes.
   - Unapplied reviews, pending changes, rejected changes, `CHANGE_CONFLICTS_WITH`, and revisions with `chronology_unresolved=True` are strictly excluded from specialist invalidation.
   - Existing UNDERSTAND specialist intelligence remains valid on the last applied revision until new canonical truth is applied.
2. Closed Specialist Domain Vocabulary:
   - Reuses existing 6 Full Analysis specialist domains:
     `PROCUREMENT_STRUCTURE`, `REQUIREMENTS_COMPLIANCE`, `EVALUATION_INTELLIGENCE`, `SCOPE_DELIVERABLES`, `COMMERCIAL_CONTRACTUAL`, `SCHEDULE_SUBMISSION`.
3. Deterministic Domain Router:
   - Pure deterministic table `DOMAIN_ROUTING_RULES` mapping changes to affected domains with compact reasons (`DomainRoutingReason`: `domain`, `rule`).
   - Bounded cross-domain rules:
     - Evaluation threshold -> `EVALUATION_INTELLIGENCE` + `REQUIREMENTS_COMPLIANCE`
     - Staffing / personnel credentials -> `REQUIREMENTS_COMPLIANCE` + `SCOPE_DELIVERABLES`
     - Pricing structure -> `COMMERCIAL_CONTRACTUAL` + `REQUIREMENTS_COMPLIANCE`
     - Pricing artifact replacement -> `COMMERCIAL_CONTRACTUAL` + `REQUIREMENTS_COMPLIANCE` + `SCHEDULE_SUBMISSION`
     - Scope delivery restriction -> `SCOPE_DELIVERABLES` + `COMMERCIAL_CONTRACTUAL`
   - Zero-Impact Administrative Updates:
     - Buyer contact typo, administrative notice, document metadata, or `CHANGE_UNCHANGED` route to 0 domains and stale 0 findings.
4. Finding Dependency & Staleness Model:
   - Closed PCI finding statuses: `RETAINED`, `STALE`, `UNRESOLVED`.
   - Derives dependencies from existing finding fields: `canonical_ids`, `dependencies`, `artifact_ids`, `source_refs`.
   - Staleness is strictly dependency-based: new revisions do not invalidate unrelated findings.
   - A finding is `STALE` if any dependency matches an authoritative changed entity, fact_type, canonical_id, or replaced artifact.
   - A finding is `RETAINED` if its dependencies are unaffected.
   - A finding is `UNRESOLVED` if dependency metadata is insufficient (empty citations and dependencies) — never silently retained.
5. Deterministic Impact Plan Contract:
   - `RevisionImpactPlan` dataclass provides the contract consumed by PCI-B2.
   - Stable SHA-256 fingerprint based strictly on semantic inputs (change_set_fingerprint, state_fingerprint, affected_domains, finding_impacts).
   - Excludes timestamps, DB row IDs, execution time, and ordering noise.
   - 100% idempotent with zero provider/model calls.

Schema reused/changed:
REUSE_EXISTING_SCHEMA.
No new database migration or DDL was introduced.
Reuses existing migration 010 schema primitives.

Entry manifest for next phase (maximum 5 files):
1. `procurement_change_intelligence.py` — Revision impact plan, domain router, finding dependency resolver
2. `full_analysis.py` — Specialist runner, specialist inputs, finding validator, reconciliation
3. `full_analysis_service.py` — Durable execution service & DB persistence
4. `tests/test_procurement_change_intelligence.py` — Impact routing tests & fixtures A-J
5. `canonical_procurement.py` — Canonical procurement intelligence definitions

Durable objects:
- `FactChange`: Bounded fact-level mutation with change_type, review_status, before/after values, verified source hash, and required integer `source_document_id`
- `ArtifactRecord`: Buyer-issued file artifact status tracking (CURRENT / SUPERSEDED)
- `ProcurementChangeSet`: Deterministic change set for a revision with stable semantic fingerprint
- `ProcurementRevision`: Immutable revision node in chronological chain with parent pointer, separating system revision from buyer chronology, with `chronology_unresolved` and `no_canonical_change` flags
- `AuthoritativeProcurementState`: Deterministically derived current state separating active facts, superseded facts, pending conflicts, and active artifacts
- `PCIBaseStorage` / `InMemoryPCIStorage` / `PCIDatabaseStorage`: Durable adapters mapping PCI state to Migration 010 persistence, RPC lifecycle, and human review gating
- `RevisionImpactPlan`: Deterministic routing and finding staleness contract for PCI-B2 incremental execution
- `DomainRoutingReason` / `ChangeRoutingDecision`: Explainable deterministic routing decisions

Key invariants:
- Previous revisions are immutable
- Identical document uploads yield NO_NEW_REVISION (idempotency across process restarts)
- Latest authoritative buyer fact outranks older facts via chronological replay
- Superseded facts remain queryable in history
- Unrelated facts survive unchanged across revisions
- Out-of-order uploads preserve buyer chronology
- Corrections can supersede facts introduced by earlier addenda
- Ambiguous precedence requires human confirmation without auto-resolving
- Human review is strictly gated: pending, rejected, or conflicting changes are never auto-approved
- Apply is all-or-nothing: unapproved changes or unresolved chronology block canonical revision advance
- Exact source provenance: every fact change must trace to a verified document ID and matching hash
- Routing consumes ONLY applied authoritative changes; unapplied updates do not invalidate canonical intelligence
- Domain routing uses the closed vocabulary of 6 existing specialist domains
- Staleness is strictly dependency-based; new revisions do not stale unrelated findings
- Replaced artifacts invalidate only findings citing that artifact
- Findings with insufficient dependency metadata fail safely to UNRESOLVED (never silently RETAINED)
- Zero-impact administrative updates affect 0 domains and stale 0 findings
- Revision impact plans are 100% deterministic and idempotent
- Pure application-layer routing with zero external model calls and zero database migrations

Tests:
`tests/test_procurement_change_intelligence.py` (60 passed, 0 failed):
- Fixtures A through J (10 tests)
- Concurrency and optimistic locking (3 tests)
- Invariant verification (4 tests)
- Document classification and chronology extraction (2 tests)
- Migration 010 schema mapping (1 test)
- Durability and process restart rehydration (13 tests)
- Production storage wiring proof: default `PCIDatabaseStorage` (1 test)
- Atomic optimistic database concurrency proof across independent instances (1 test)
- PCI-A.2 Governed Apply & Durable Chronology regression tests (5 tests)
- PCI-A.2.1 Human-Review Gate & Source Provenance tests (6 tests)
- PCI-B1 Impact Routing & Intelligence Dependency tests (14 tests: Fixtures A-J, domain vocabulary parity, zero-impact administrative, idempotency, manager integration)

Open issues:
None for PCI-B1. Impact routing and finding dependency model fully closed.

Next phase:
PCI-B2 — Incremental Specialist Execution + Delta Reconciliation
