# Current PCI State

Phase:
PCI-B2A.1 — Context Identity & Fail-Closed Binding Closure

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

Impact Routing & Intelligence Dependency Model (PCI-B1 & PCI-B1.1):
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

Revision-Aware Specialist Context & Identity Closure (PCI-B2A & PCI-B2A.1):
1. Context Lineage & Fingerprint Identity:
   - `RevisionSpecialistContext` carries explicit lineage: `impact_plan_fingerprint` and `base_package_digest`.
   - Context fingerprint (`compute_specialist_context_fingerprint`) reflects the complete semantic state:
     - Mutated canonical objects, additive `RevisionFact` items, relevant `FactChange` items.
     - `stale_prior_findings` content, `retained_prior_findings` content.
     - `permitted_canonical_ids`, `impact_plan_fingerprint`, and `base_package_digest`.
   - Sensitive to modified finding content (severity, text, detail, citations).
   - Order-invariant across lists and dictionary keys; strips execution noise (timestamps, database IDs, latencies).
2. Domain-Bound Prior Findings & Stale IDs:
   - Prior findings passed into context building are strictly domain-bounded via `produced_by`, `specialist_id`, `domain`, and finding ID prefix.
   - A specialist (e.g. `EVALUATION_INTELLIGENCE`) receives ONLY its own prior findings (`retained_prior_findings` and `stale_prior_findings`). Findings from other specialists (e.g. Commercial, Schedule) are strictly excluded even if present in the caller pool.
   - Stale finding IDs (`stale_prior_finding_ids`) are similarly domain-bounded.
3. Stale Finding Content Payload:
   - `RevisionSpecialistContext` provides the complete finding payload in `stale_prior_findings` alongside the compact index `stale_prior_finding_ids`.
   - Allows delta reanalysis specialists to reason over previous finding details for precise RETAIN, SUPERSEDE, REMOVE, or REPLACE decisions.
4. Fail-Closed Canonical Binding:
   - `_match_canonical_object` enforces a strict 5-level precedence hierarchy:
     Level 1: Explicit `canonical_id` field.
     Level 2: Explicit `canonical_ids` list/tuple/set.
     Level 3: Exact canonical identity (`id`, `key`, `criteria_id`, `deliverable_id`, etc.).
     Level 4: Exact semantic match against unique entity titles, scope headings, requirement texts, or `before_value`.
     Level 5: Unresolved fallback.
   - When more than one candidate matches Level 4 (e.g. multiple evaluation criteria with identical key tokens), binding fails closed:
     `AMBIGUOUS_CANONICAL_BINDING: candidate canonical IDs: ['CRIT-1', 'CRIT-2']`.
   - Context becomes `is_executable = False` with explicit diagnostic explanation in `blocking_reason`.
   - Unambiguous matches bind deterministically with strong binding type (`EXISTING_CANONICAL`).

Schema reused/changed:
REUSE_EXISTING_SCHEMA.
No new database migration or DDL was introduced.
Reuses existing migration 010 schema primitives.

Entry manifest for next phase (maximum 5 files):
1. `procurement_change_intelligence.py` — Revision impact plan, domain router, finding dependency resolver, revision specialist context
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
- `RevisionImpactPlan`: Deterministic routing and finding staleness contract for PCI-B2 incremental execution, including unique `revision_id` event identity
- `DomainRoutingReason` / `ChangeRoutingDecision`: Explainable deterministic routing decisions
- `RevisionSpecialistContext`: Authoritative revision-aware specialist reanalysis contract providing mutated canonical objects, additive `RevisionFact` items, permitted citation IDs, carry-forward retained findings, stale finding payload, lineage digests, and change bindings
- `ChangeBinding`: Precise linkage between a `FactChange` and its target canonical entity (`EXISTING_CANONICAL`, `REVISION_FACT`, or `UNRESOLVED`)
- `RevisionFact`: Structured representation of an additive buyer update not bound to any baseline canonical entity

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
- Routing consumes ONLY applied authoritative changes; unapplied updates (`review_status != "applied"`, e.g. `ready_for_review`, `analyzing`, `failed`) do not mutate canonical truth and return zero canonical impact (`UNAPPLIED_BUYER_UPDATE_CANONICAL_UNTOUCHED`)
- Raw `ProcurementChangeSet` requires explicit `applied=True` to route, defaulting to fail-closed
- Domain routing uses the closed vocabulary of 6 existing specialist domains and accepts legacy PCI-A vocabulary (`DEADLINE`, `WEIGHT`, `COMMERCIAL`, `SCOPE`, `ARTIFACT`, etc.)
- Prefix matching normalizes dot, colon, hyphen, and underscore delimiters identically
- Finding dependencies bridge canonical prefixes (`CRIT-...`, `SCOPE-...`, `OBL-...`) to FactChange entities without manual metadata injection
- Staleness is strictly dependency-based; new revisions do not stale unrelated findings
- Replaced artifacts invalidate only findings citing that artifact
- Findings with insufficient dependency metadata fail safely to UNRESOLVED (never silently RETAINED)
- Zero-impact administrative updates affect 0 domains, do not register changed keys, and stale 0 findings
- Revision impact plans are 100% deterministic and idempotent with stable event identity (`revision_id`)
- Ambiguous integer revision numbers matching multiple revisions fail closed via manager
- Base `CanonicalPackage` is strictly immutable: building revision specialist context produces zero side effects and preserves `package_digest` byte-for-byte
- Unapplied revisions or unresolved chronology fail closed with `PCIContextNotEligibleError`
- Requesting context for a specialist domain not affected by the revision impact plan fails closed with `PCIContextNotEligibleError`
- Additive requirements or clauses generate stable `REV-FACT-...` IDs and are appended to `permitted_canonical_ids`
- Removed canonical objects are excluded from active canonical objects and revoked from `permitted_canonical_ids`
- Unresolved bindings set `is_executable=False` and report clear `blocking_reason` diagnostics
- When multiple candidate canonical objects match, binding fails closed with `AMBIGUOUS_CANONICAL_BINDING` and candidate IDs
- Specialists receive only prior findings and stale finding IDs belonging to their own domain (`produced_by`)
- `RevisionSpecialistContext` carries complete `stale_prior_findings` payloads for downstream delta reconciliation
- Revision specialist context fingerprints (`context_fingerprint`) are 100% deterministic, order-invariant, and sensitive to revision facts, canonical objects, permitted citation IDs, stale/retained findings, `impact_plan_fingerprint`, and `base_package_digest`
- Pure application-layer routing and context formulation with zero external model calls and zero database migrations

Tests:
`tests/test_procurement_change_intelligence.py` (90 passed, 0 failed):
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
- PCI-B1.1 Applied-State & Compatibility tests (10 tests: Tests A through J covering applied gating, chronology gating, unapplied impact plan, raw changeset fail-closed, vocabulary compatibility, prefix normalization, canonical-id bridge, zero-impact key filtering, stable event identity, ambiguous revision number fail-closed)
- PCI-B2A Revision-Aware Specialist Context tests (14 tests: Test Scenarios A through J covering weight overlay, deadline overlay, commercial obligation overlay, scope overlay, additive revision fact, removed requirement exclusion, replacement pricing form provenance, unapplied revision fail-closed, unresolved binding blocking execution, unaffected domain bounding fail-closed, base package immutability, deterministic context fingerprinting, prior findings filtering, manager end-to-end integration)
- PCI-B2A.1 Context Identity & Binding Closure tests (6 tests: lineage fields and stale findings payload, real finding shape and domain-bound filtering, fingerprint sensitivity to finding content, fingerprint order-invariance, fail-closed ambiguous canonical binding, deterministic unique strong binding)

Open issues:
None for PCI-B2A.1. Context identity and fail-closed binding invariants are fully verified and closed.

Entry Manifest for PCI-B2B:
- `procurement_change_intelligence.py`: `RevisionSpecialistContext`, `build_revision_specialist_context`, `ProcurementRevisionManager.get_revision_specialist_context`
- `full_analysis.py`: `SPECIALIST_IDS`, `build_specialist_input`, `SpecialistResult`, `validate_findings`
- `full_analysis_service.py`: `execute_specialist_run`, reanalysis orchestration, persistence adapter

Next phase:
PCI-B2B — Incremental Specialist Execution + Delta Reconciliation
