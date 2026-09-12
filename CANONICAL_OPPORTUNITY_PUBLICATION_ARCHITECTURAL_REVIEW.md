# Canonical Opportunity Publication Architectural Review

## Document metadata

| Field | Value |
|---|---|
| Document | `CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURAL_REVIEW.md` |
| Status | Architectural review only |
| Scope | Governed publication of authoritative opportunity objects for downstream resolution |
| Higher authority | [Bid Intelligence Constitution](MANIFESTO.md), [Architecture Doctrine](docs/architecture/ARCHITECTURE.md), [Decision Information Doctrine](docs/architecture/DECISION_DOCTRINE.md), [Opportunity Intelligence Analyst Specification](OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md), [Governed Reference Resolution Architecture](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md), and [Executive Opportunity Understanding Architecture](EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md) |
| Repository changes authorized | This review document only |

## Executive conclusion

The Bank of Canada production blocker is a genuine architectural omission followed by an implementation-sequencing consequence. It is not a defect in Governed Reference Resolution, Opportunity Intelligence owner publication, or Executive Opportunity Understanding.

[Governed Reference Resolution Architecture](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md) establishes the uniform repository protocol and states that an existing domain participating in cross-domain resolution must declare how its stable references bind to immutable snapshots and which owner-authored semantic representation satisfies consumer rights. [Opportunity Intelligence Analyst Specification](OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md) correctly requires upstream requirements, facts, observations, conflicts, evidence, and provenance to remain owned and published by their existing domains. The repository does not contain `CANONICAL_OPPORTUNITY_ARCHITECTURE.md`, and no other approved Canonical Opportunity contract supplies the required owner-publication declaration.

The current Canonical Opportunity implementation creates deterministic mappings with stable IDs, normalized values, resolution states, conflicts, source references, and a schema version. It does not define or emit governed semantic objects, owner-contract versions compatible with the resolution protocol, immutable owner snapshots, object digests, relationship manifests, or resolver-compatible references. Test fixtures construct these items manually, but test construction is not a production owner contract.

**Conclusion: C. A new Canonical Opportunity Publication architecture is constitutionally required.**

This conclusion means a publication contract within the existing Canonical Opportunity owner boundary. It does not authorize a new semantic domain, publication service, canonical store, resolver, or intelligence layer. The publication contract must expose Canonical Opportunity's existing owned meaning without copying or redefining it.

The Canonical Opportunity publication contract is necessary but not sufficient to close every binding used by Opportunity Intelligence. Requirements, evaluation criteria, submission requirements, Contract Hygiene entities, Stage C conflicts, and provenance may have different existing owners. Each owner represented in an Opportunity Intelligence input must have an equivalent owner-publication declaration. Canonical Opportunity must not absorb those objects merely to make one context convenient.

## Review scope and validation method

The review compared:

1. constitutional rules for Canonical Truth, evidence before inference, single ownership, and fail-closed transitions;
2. the object, snapshot, context, relationship, and consumer guarantees in Governed Reference Resolution;
3. the upstream binding and owner-publication requirements in Opportunity Intelligence;
4. the organizational-consumer requirements in Executive Opportunity Understanding;
5. current production behavior in `canonical_opportunity.py`, `opportunity_intelligence_publication.py`, and `governed_reference_resolution.py`; and
6. production call-site availability outside tests.

The named standalone `OPPORTUNITY_INTELLIGENCE_PUBLICATION_ARCHITECTURE` is not present. Its relevant authority is section 11.1 of [Opportunity Intelligence Analyst Specification](OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md). The named `CANONICAL_OPPORTUNITY_ARCHITECTURE.md` is also not present. Its absence prevents the review from inferring owner-publication semantics from an approved Canonical Opportunity contract.

No implementation, tests, prompts, schemas, persistence, pipeline, or existing architecture documents were changed during this review.

## Current production blocker

The current flow reaches a valid `DecisionAnalysis`. Opportunity Intelligence Publication then requires:

- one immutable authoritative `ResolutionContext`;
- one exact governed entity reference for every distinct `EvidenceSupport` admitted by the analysis;
- exact governed evidence references matching every evidence ID in each support value;
- complete, deterministic `OpportunitySupportBinding` coverage; and
- relationship closure across all referenced immutable owner snapshots.

Production currently supplies none of these authoritative upstream publication products. `canonical_opportunity.py` returns a dictionary contract identified as `canonical-opportunity/1`. It has stable observation, normalized-identity, conflict, document, and evidence-related fields, but those fields are not published as objects under the immutable reference protocol. No production module converts the Canonical Opportunity output into a governed owner snapshot. No production call site assembles all required upstream snapshots and support bindings before invoking Opportunity Intelligence Publication.

The resolver cannot fill this gap. It verifies objects and relationships already declared by owners. Allowing it to construct canonical values, assign owner identities, select evidence links, or create snapshots would give verification infrastructure semantic and canonical authority expressly denied by its architecture.

Opportunity Intelligence Publication cannot fill the gap either. It owns analytical objects and their outbound relationships. Publishing canonical or normalized source entities as Opportunity Intelligence objects would promote or duplicate upstream authority. Accepting caller-invented bindings without owner publication would weaken exact identity, digest, and provenance guarantees.

Executive Opportunity Understanding also cannot fill the gap. It owns organization and coverage only. It must consume resolvable published analytical references and cannot reconstruct upstream semantic objects or publication metadata.

## Constitutional analysis

### Canonical Truth

[Architecture Doctrine](docs/architecture/ARCHITECTURE.md) assigns Canonical Truth the authoritative account of what available evidence supports. Publication must therefore originate at the owner boundary. A presentation, analyst, resolver, or orchestration layer cannot author canonical semantic representations on Canonical Opportunity's behalf.

Publishing an exact immutable representation does not create new truth. It makes existing canonical truth addressable and verifiable across domain boundaries. The published representation must retain resolution state, conflict state, precision, scope, contributing observations, source relationships, and governed absence. It cannot flatten conflicts or expose a resolved value where the owner declares none.

### Evidence before inference

Canonical publication must retain links to evidence and provenance objects under their actual owners. Canonical Opportunity may declare relationships to those objects but cannot republish evidence content as canonical content. Required evidence and provenance edges must close within the bounded context or publication must fail.

### Single ownership

Each semantic owner publishes its own objects. Canonical Opportunity publishes only canonical facts, canonical observations and conflict states that its governing contract assigns to it. Requirements, evaluation entities, submission entities, Contract Hygiene entities, and provenance remain with their existing owners unless an approved higher-authority contract already assigns them to Canonical Opportunity.

Creating a new publication *domain* would violate single ownership. Creating an owner-publication contract inside Canonical Opportunity does not: it is the same owner exposing the same meaning under immutable bindings.

### Determinism and immutability

Stable IDs in mutable mappings are insufficient for cross-domain resolution. The owner contract must distinguish semantic identity from operational metadata and define canonical serialization, object membership, object digests, snapshot identity, snapshot digest, relationship order, version compatibility, and historical immutability.

### Fail-closed behavior

The Bank of Canada halt is constitutionally correct. Until owner snapshots and relationships exist, constructing them heuristically from names, record shapes, or current state would be silent repair. The missing transition must remain unavailable rather than producing an apparently governed Briefing Pack.

## Ownership analysis

### Governed opportunity objects

The domain that owns an opportunity semantic object must create its governed publication representation:

| Object family | Publication owner |
|---|---|
| Canonical resolved fields, canonical observations, and canonical conflicts | Canonical Opportunity |
| Normalized requirements | Existing requirements or normalization owner |
| Evaluation criteria and hierarchy | Existing evaluation owner |
| Submission artifacts, rules, and pathways | Existing submission owner |
| Admitted deliverables and commercial clauses | Contract Hygiene or the existing admitted-fact owner |
| Stage C conflicts not owned by Canonical Opportunity | Existing reconciliation/conflict owner |
| Evidence occurrences and provenance | Existing evidence or provenance owner |
| Computed facts, analytical statements, hypotheses, assumptions, unknowns, questions, and limitations | Opportunity Intelligence |

Canonical Opportunity must not become an umbrella publisher for every opportunity-related object. Doing so would alter ownership rather than expose it.

### Immutable snapshots

Each semantic owner owns creation and validation of its own immutable snapshot because only that owner can declare complete object membership and semantic meaning. The shared resolver supplies domain-neutral snapshot primitives and verifies them; it does not own snapshot content.

For Canonical Opportunity, its owner-publication contract must govern its snapshot. Other opportunity domains require their own compatible publication declarations or an already-approved aggregate contract that explicitly preserves each object's original owner.

### ResolutionContext creation

A `ResolutionContext` is a closed integration product over already-published owner snapshots. Its assembly belongs to the governed orchestration boundary initiating the cross-domain operation. For Opportunity Intelligence publication, that is the deterministic Opportunity Intelligence input/publication orchestration described by its specification.

The orchestrator may select only declared compatible snapshots for the exact opportunity and analysis input. It does not own their objects and cannot manufacture missing snapshots, references, relationships, or compatibility. Governed Reference Resolution validates the resulting context identity, digest, versions, ownership, and closure.

The current architecture describes the context and refers to an orchestrator, but it does not fully specify the production assembly contract for a multi-owner opportunity snapshot set. That is a narrow secondary architectural gap. It must be defined at the integration boundary without becoming a new semantic authority.

### OpportunitySupportBindings

An `OpportunitySupportBinding` links one Opportunity Intelligence `EvidenceSupport` declaration to exact upstream owner references. Responsibility is split without splitting authority:

- upstream owners publish the references available for binding;
- Opportunity Intelligence owns the analytical support declaration and its outbound relationship meaning;
- the deterministic Opportunity Intelligence orchestration boundary matches the already-declared support identity to the exact admitted owner reference under the same authoritative input snapshot set; and
- Opportunity Intelligence Publication validates complete one-to-one coverage and publishes the resulting analytical relationships.

Canonical Opportunity cannot own all `OpportunitySupportBindings` because many bindings target entities and evidence outside Canonical Opportunity. Governed Reference Resolution cannot own them because matching an analytical support declaration to a target is relationship declaration, not resolution. Executive Opportunity Understanding cannot own them because it is downstream and organizational only.

## Compatibility analysis

### Opportunity Intelligence

The recommended publication contract supplies the immutable upstream references already required by Opportunity Intelligence Analyst Specification. It does not change analysis, evidence admission, authority precedence, or analytical semantics.

### Opportunity Intelligence Publication

Opportunity Intelligence Publication already fails closed unless bindings exactly cover `analysis.evidence_used` and all referenced objects resolve. Canonical owner publication would satisfy an expected input boundary without changing Opportunity Intelligence ownership or publication behavior.

### Governed Reference Resolution

The recommendation conforms to the existing protocol. Owner contracts declare semantic objects and snapshots; the resolver remains domain-neutral and verifies exact identity, version, digest, authority, semantic sufficiency, and relationship closure.

### Executive Opportunity Understanding

Executive Opportunity Understanding would continue to organize published Opportunity Intelligence objects. Its bounded context could include compatible upstream owner snapshots for relationship and provenance navigation. It would neither own nor duplicate their semantic values.

### Canonical Opportunity

Publication must expose existing canonical meaning without changing `canonical-opportunity/1` semantics by implication. Compatibility between the current canonical contract and its first resolver-participating publication version must be explicit. Historical canonical states cannot be represented by mutable current state or recomputation during resolution.

## Is a separate architectural layer required?

No new runtime or semantic layer is justified. The enduring flow remains:

```text
Evidence owners publish evidence snapshots
                     ↓
Canonical Opportunity creates canonical truth
                     ↓
Canonical Opportunity publishes its owned immutable snapshot
                     ↓
Governed orchestration binds compatible owner snapshots
                     ↓
Opportunity Intelligence analyzes the bounded input
                     ↓
Opportunity Intelligence publishes its owned analysis
                     ↓
Governed Reference Resolution verifies references
                     ↓
Executive Opportunity Understanding organizes them
```

“Canonical Opportunity Publication” is an owner-bound responsibility, not a box with independent authority. A separately named architecture document is required because no approved Canonical Opportunity architecture currently declares that responsibility. Its constitutionally valid scope is the publication contract of Canonical Opportunity itself.

## Architectural recommendation

Create an authoritative Canonical Opportunity Publication architecture that remains inside the Canonical Opportunity owner boundary and defines only:

- published canonical object classes and exact semantic fields;
- owner namespace and contract version;
- stable object identity and canonical ordering;
- object and snapshot identity and digest rules;
- immutable snapshot membership;
- evidence, provenance, conflict-member, and supersession relationship roles;
- governed reference production;
- compatibility with the current canonical schema;
- historical resolution guarantees;
- validation and fail-closed behavior; and
- explicit exclusions preventing ownership of other opportunity domains.

Do not create a generic publication service or let Canonical Opportunity publish every object consumed by Opportunity Intelligence.

In parallel architectural sequencing, identify every non-canonical owner represented by Opportunity Intelligence `evidence_used`. Amend only those existing owner contracts that do not yet declare resolver-compatible publication. Then clarify the existing Opportunity Intelligence orchestration responsibility for assembling one compatible authoritative context and exact support bindings from those owner publications.

These steps close the constitutional gap before implementation. Implementation sequencing should then proceed owner publications first, governed context assembly second, Opportunity Intelligence publication third, and downstream understanding and presentation last.

## Minimum constitutional changes required

1. Establish the missing Canonical Opportunity governing publication contract within its existing owner boundary.
2. Declare which Canonical Opportunity objects, fields, conflicts, observations, relationships, versions, identities, and digests are resolvable.
3. Explicitly exclude normalized entities, evidence, provenance, and conflicts owned by other domains.
4. Add resolver-participation declarations to any other existing opportunity owner contracts whose objects appear in Opportunity Intelligence evidence support.
5. Clarify, in the existing Opportunity Intelligence input/publication orchestration authority, how compatible owner snapshots form the exact authoritative `ResolutionContext` and how exact support bindings are assembled without semantic inference.

No amendment to Governed Reference Resolution is required. No change to Executive Opportunity Understanding is required. No additional semantic authority is required.

## Final determination

The blocker is not merely incorrect implementation order because the production artifacts cannot be implemented safely from the current approved owner contracts. The repository-wide protocol is sufficient as a protocol, but Canonical Opportunity has not declared how it participates, and several other authoritative opportunity owners may have the same gap.

It must be a narrow owner-publication architecture for Canonical Opportunity, accompanied by only the minimum owner declarations and orchestration clarification needed to close all upstream relationships. It must not become a new domain, duplicate canonical truth, absorb other owners, or move semantic creation into Governed Reference Resolution.

**C. A new Canonical Opportunity Publication architecture is constitutionally required.**
