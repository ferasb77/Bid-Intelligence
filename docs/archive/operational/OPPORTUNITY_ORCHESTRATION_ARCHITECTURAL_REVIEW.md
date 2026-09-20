# Opportunity Orchestration Architectural Review

## Document metadata

| Field | Value |
|---|---|
| Document | `OPPORTUNITY_ORCHESTRATION_ARCHITECTURAL_REVIEW.md` |
| Title | Opportunity Orchestration Architectural Review |
| Authority level | Level 5 — Operational architectural review |
| Version | 1.0.0 |
| Status | Review finding |
| Purpose | Determine the constitutional owner of multi-owner publication admission, resolution-context assembly, and Opportunity Intelligence support binding. |
| Higher authority | [The Bid Intelligence Constitution](../../../MANIFESTO.md), [Repository Governance](../../../GOVERNANCE.md), [Architecture Doctrine](../../architecture/ARCHITECTURE.md), [Canonical Opportunity Publication Architecture](../../../CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md), [Governed Reference Resolution Architecture](../../../GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md), and [Opportunity Intelligence Analyst Specification](../../../OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md) |
| Governed documents | None; this review does not amend architecture. |
| Related documents | [Canonical Opportunity Publication Architectural Review](CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURAL_REVIEW.md) and [Opportunity Intelligence Publication Architectural Review](OPPORTUNITY_INTELLIGENCE_PUBLICATION_ARCHITECTURAL_REVIEW.md) |

## Executive summary

The approved architecture assigns all semantic ownership and owner publication correctly, and Governed Reference Resolution correctly owns deterministic verification. It does not assign complete constitutional responsibility for assembling the bounded, cross-owner input used by Opportunity Intelligence and its owner publication.

Several documents refer to an “orchestrator,” a “governed operation orchestrator,” or an “Opportunity Intelligence orchestration boundary.” Those references establish that assembly must occur outside owner publication and outside resolution. They do not define an authoritative orchestration contract, its admitted inputs, compatibility rules, manifest, identity, validation obligations, or failure behavior. The missing responsibility therefore cannot be supplied safely through implementation sequencing alone.

The required orchestration responsibility has no semantic authority. It does not publish domain objects, own owner snapshots, interpret content, repair references, or decide which facts are true. It assembles an immutable declaration of exact owner publications, validates their eligibility for one bounded operation, constructs the corresponding resolution context, and binds existing Opportunity Intelligence `EvidenceSupport` declarations to exact admitted references.

**Conclusion: C. A new orchestration architecture is constitutionally required.**

## Review scope and authority note

This review examines architecture only. It does not define runtime components, APIs, persistence, services, or implementation sequencing.

The requested file `OPPORTUNITY_INTELLIGENCE_PUBLICATION_ARCHITECTURE.md` is not present in the repository. Opportunity Intelligence owner publication is governed by the publication amendment in [Opportunity Intelligence Analyst Specification](../../../OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md), currently version 1.1.1. This review relies on that ratified specification and does not infer content for the absent standalone filename.

## Validation method

The review traced each required action across the approved authority chain:

1. identify who creates semantic objects;
2. identify who publishes each owner’s immutable snapshot and references;
3. identify who selects compatible publications for one operation;
4. identify who declares the closed snapshot set;
5. identify who maps analyst support declarations to exact governed references;
6. identify who verifies identity, version, digest, authority, and relationship closure; and
7. test whether assigning the missing actions to an existing component would transfer or duplicate authority.

The analysis applies the repository rules of single ownership, evidence before inference, immutable references, deterministic behavior, explicit uncertainty, and fail-closed transitions.

## Existing responsibilities

### Owner domains

Each semantic owner creates and validates its own objects. Canonical Opportunity owns canonical field states, canonical observations, and canonical conflicts. Other existing domains retain ownership of requirements, evaluation entities, submission entities, Contract Hygiene entities, evidence, and provenance.

### Owner publication

Each owner publication responsibility exposes only that owner’s existing semantics through immutable objects, an owner-bound snapshot, object and snapshot digests, owner-declared relationships, and governed references. An owner publication cannot admit another owner’s snapshot or claim cross-domain completeness.

[Canonical Opportunity Publication Architecture](../../../CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md) expressly excludes construction of a multi-owner `ResolutionContext` and creation of Opportunity Intelligence support bindings. It assigns compatible multi-owner context assembly to a “governed operation orchestrator.”

### Opportunity Intelligence

Opportunity Intelligence consumes an explicitly bounded authoritative opportunity context and produces analytical semantics within its own authority. Its specification assigns deterministic input assembly to “the orchestrator,” while analysis retains no authority to publish or repair upstream objects.

### Opportunity Intelligence owner publication

Opportunity Intelligence publishes only its validated analytical objects. It validates that every outbound support relationship maps to an exact admitted upstream reference. It cannot create missing upstream publications, infer bindings from matching identifiers, or expand the authoritative context.

### Governed Reference Resolution

Governed Reference Resolution validates an explicitly supplied `ResolutionContext`, performs exact lookup, checks versions and digests, enforces authority and semantic sufficiency, and validates relationship closure. It creates no semantics and has no authority to select a convenient publication, infer compatibility, discover additional snapshots, or repair an incomplete context.

## Responsibility analysis

### ResolutionContext

The orchestration boundary must own the declaration and deterministic assembly of the operation-scoped `ResolutionContext`. This ownership is limited to the context’s admission decision, exact membership, compatibility declaration, identity, ordering, and integrity metadata.

The orchestrator does not own the semantic objects or snapshots inside the context. Governed Reference Resolution validates the assembled context and all resolution operations against it. The resolver therefore owns verification, while orchestration owns the bounded input declaration presented for verification.

### OpportunitySupportBindings

The Opportunity Intelligence orchestration boundary must own assembly of `OpportunitySupportBindings`. A binding is not new semantic meaning. It records that one existing `EvidenceSupport` declaration maps to one exact reference already admitted to the bounded context.

The orchestrator may establish a binding only through exact owner identity, supported contract version, snapshot binding, object identity, declared authority, and required evidence relationship. It cannot infer equivalence from prose, filenames, ordering, semantic similarity, or current state. Opportunity Intelligence Publication retains responsibility for validating complete one-to-one coverage and rejecting invalid bindings.

### Admitted publication snapshots

Semantic owners own and publish snapshots. Orchestration owns only their admission into one operation. Admission means selecting exact immutable owner publications, proving that their declared versions and authoritative snapshot bindings are mutually compatible, and freezing that selected set. Admission never republishes or transfers ownership of snapshot members.

### Cross-owner publication manifests

Each owner retains ownership of its own publication manifest. Orchestration must not create a replacement cross-owner publication manifest that purports to republish their content.

The missing boundary instead requires an operation-scoped admission manifest: an immutable inventory of the exact owner publication manifests and snapshots admitted to the operation, their roles, versions, digests, compatibility bindings, and canonical order. This assembly manifest asserts composition and closure only. It does not assert or duplicate semantic truth.

## Alternatives considered

### A. Existing architecture is sufficient

This conclusion is not supported. The architecture names orchestration but does not govern it. There is no authoritative definition of context scope, admission authority, cross-owner compatibility, binding completeness, deterministic ordering, orchestration identity, or failure behavior. Implementing those choices directly would allow code to create constitutional policy implicitly.

### B. An existing architecture requires amendment

A narrow amendment is insufficient because none of the existing components can own the complete responsibility without crossing its established boundary:

- amending Canonical Opportunity Publication would give one semantic owner authority over other owners;
- amending Opportunity Intelligence would mix analytical semantics with admission and binding;
- amending Opportunity Intelligence Publication would permit a downstream publisher to manufacture its own authoritative inputs;
- amending Governed Reference Resolution would mix context selection with neutral verification; and
- amending a normalized-entity owner would give that owner authority over unrelated publications.

The responsibility spans multiple independent owners and serves a governed operation rather than any one semantic domain.

### C. A new orchestration architecture is required

This conclusion matches the existing references to a separate governed orchestration boundary and closes their undefined constitutional responsibility. “New architecture” here means a governing contract for composition. It does not imply a new semantic domain, publication owner, intelligence layer, or runtime service.

## Constitutional ownership model

| Question | Finding |
|---|---|
| Who owns orchestration? | A separately governed opportunity-operation orchestration boundary. |
| Does orchestration possess semantic authority? | No. It cannot establish facts, analysis, evidence meaning, conflicts, or decisions. |
| Does orchestration own publication? | No. Each semantic owner publishes its own objects and manifest. |
| Does orchestration own governed semantic objects? | No. It may own only operation-scoped assembly identity and integrity metadata. |
| Does orchestration own snapshots? | No. It admits exact immutable snapshots owned by their publishers. |
| Does orchestration own the ResolutionContext? | It owns the bounded membership declaration and deterministic assembly; Governed Reference Resolution owns validation and resolution behavior. |
| Does orchestration own support bindings? | It owns exact assembly of bindings for the operation; the analyst defines support declarations and Opportunity Intelligence Publication validates publication coverage. |
| Does orchestration assemble immutable owner publications? | Yes, without copying, altering, repairing, or republishing them. |

## Required constitutional coverage

A future governing architecture is required to assign, without adding semantic authority:

- the opportunity-operation scope and identity;
- the exact eligible owner publication classes and versions;
- immutable admission of owner snapshots and manifests;
- authoritative snapshot compatibility rules;
- deterministic context identity, membership, ordering, and digest binding;
- exact `EvidenceSupport` to governed-reference binding;
- complete binding and relationship-closure requirements;
- separation between operation assembly metadata and semantic identity;
- historical and replay binding to exact snapshots;
- deterministic validation responsibilities shared with owner publishers and the resolver; and
- fail-closed behavior for missing, duplicate, stale, incompatible, ambiguous, corrupt, or incomplete inputs.

These are missing architectural guarantees, not implementation instructions.

## Compatibility analysis

The finding preserves existing authority boundaries:

- **Canonical Truth:** Canonical Opportunity and other authoritative domains remain sole owners of their facts and conflicts.
- **Evidence before inference:** only exact admitted evidence and authoritative references may support analysis.
- **Owner publication:** every owner continues to publish only its own semantics and relationships.
- **Opportunity Intelligence:** analysis consumes a validated context and does not acquire input-admission authority.
- **Opportunity Intelligence Publication:** analytical publication continues to validate bindings and outbound closure without manufacturing them.
- **Governed Reference Resolution:** resolution remains a neutral verifier and never chooses context membership.
- **Determinism:** operation membership and bindings become explicit, immutable, versioned, and reproducible.
- **Fail-closed behavior:** absence of any required owner publication, compatible snapshot, exact binding, or relationship target prevents the governed transition.

No authority is duplicated. Orchestration answers only: “Which exact immutable owner publications and reference bindings constitute the authoritative input for this governed opportunity operation?” It does not answer what those objects mean or what management should decide.

## Recommendation

Create a dedicated constitutional architecture for governed opportunity-operation orchestration before production assembly is implemented. Its scope should be limited to immutable multi-owner admission, compatibility declaration, bounded `ResolutionContext` assembly, exact support binding, and assembly validation. It must explicitly exclude semantic ownership, owner publication, governed semantic-object creation, intelligence, resolution, repair, presentation, persistence policy, and human decisions.

This review does not authorize that architecture or any implementation. It records the missing responsibility so it can be governed before code supplies policy implicitly.

## Conclusion

**C. A new orchestration architecture is constitutionally required.**
