# Evidence Architecture

## Document metadata

| Field | Value |
|---|---|
| Document | `EVIDENCE_ARCHITECTURE.md` |
| Title | Evidence Architecture |
| Authority level | Level 3 — Repository Architecture |
| Version | 1.0.0 |
| Status | Approved |
| Purpose | Define the domain-neutral constitutional owner, immutable contracts, publication duties, and governed resolution boundaries for attributable evidence and its provenance. |
| Higher authority | [The Bid Intelligence Constitution](MANIFESTO.md), [Repository Governance](GOVERNANCE.md), [Architecture Doctrine](docs/architecture/ARCHITECTURE.md), [Decision Doctrine](docs/architecture/DECISION_DOCTRINE.md), and [Canonical Domain Vocabulary](docs/architecture/DOMAIN_MODEL.md) |
| Governed documents | Future Evidence contracts, Evidence owner-publication specifications, validators, and conformance tests |
| Related documents | [Evidence and Provenance Architectural Review](EVIDENCE_AND_PROVENANCE_ARCHITECTURAL_REVIEW.md), [Governed Reference Resolution Architecture](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md), [Canonical Opportunity Publication Architecture](CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md), [Opportunity Orchestration Architecture](OPPORTUNITY_ORCHESTRATION_ARCHITECTURE.md), [Opportunity Intelligence Analyst Specification](OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md), and [Executive Opportunity Understanding Architecture](EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md) |

## 1. Purpose

Evidence is the repository's authoritative representation of what an attributable source made available. This architecture establishes Evidence as the domain-neutral semantic owner of source identity, source artifacts, exact source occurrences, bounded extracts, and the provenance required to inspect them.

Evidence answers:

> What attributable source material was available, exactly where did it come from, and which immutable occurrence supports a governed downstream object?

Evidence does not decide whether a source claim is true in the world. It preserves source truth: the exact content, identity, version, location, and lineage of what the source communicated. Canonical and analytical owners may rely on that material while retaining responsibility for their own facts and interpretations.

This architecture governs evidence used in procurement, contracts, compliance, due diligence, Buyer Intelligence, and future products. It does not create a runtime service, retrieval system, database design, or product feature.

## 2. Constitutional authority

Repository doctrine places Evidence before Canonical Truth. The Evidence owner therefore has semantic authority over attributable source representations and their provenance. No downstream owner acquires that authority by citing, normalizing, reconciling, analyzing, organizing, or rendering Evidence.

Evidence authority is limited to:

- source and artifact identity;
- exact content or an integrity-bound content representation;
- source-provided and acquisition metadata;
- occurrence and locator identity;
- language and publication or effective version when established;
- authenticity and verification state under the Evidence contract;
- provenance lineage; and
- Evidence-owned relationships among source, artifact, occurrence, and extract objects.

Evidence authority does not include the authority to create canonical facts, intelligence, interpretations, recommendations, classifications, or decisions.

## 3. Architectural position

```text
Attributable Source
        ↓ acquired without reinterpretation
Evidence Owner
        ↓ publishes immutable evidence objects and provenance
Governed Reference Resolution
        ↓ verifies exact owner, version, snapshot, digest, and closure
Canonical and Analytical Owners
        ↓ publish their own governed semantics and relationships
Organizational and Presentation Consumers
```

The arrows express governed access. They do not transfer ownership.

Acquisition may discover and register material, but it does not own meaning outside the Evidence contract. Canonical owners reconcile facts. Analytical owners produce analysis. Orchestration admits publications. Resolution verifies references. Presentation renders resolved content. None may manufacture or repair Evidence.

## 4. Evidence ownership

Evidence is one independent semantic owner boundary. Independence means that its object identities, validation rules, snapshots, and publication lifecycle do not depend on a downstream consumer. It does not require a separate deployment, service, database, or user-facing product.

The Evidence owner owns:

- the stable identities of Evidence objects;
- the semantic fields declared for those objects;
- object and snapshot digests;
- immutable snapshot membership;
- provenance represented by Evidence occurrences and their relationships;
- Evidence-owned relationship declarations;
- historical versions and supersession declarations; and
- publication validation.

The Evidence owner does not own relationships declared by another owner. For example, Canonical Opportunity owns the declaration that a canonical observation is supported by an Evidence object, while Evidence owns the referenced object and its internal provenance.

Possession of a filename, URL, copied quotation, source identifier, or locator does not confer Evidence ownership.

## 5. Evidence object classes

Version 1.0.0 defines four immutable semantic object classes.

### 5.1 Evidence Source

An `EVIDENCE_SOURCE` identifies an attributable origin such as an issuing organization, official publisher, governed system, named counterparty, or other source recognized by the Evidence contract. It contains only identity and source attributes required to distinguish that origin. It does not summarize or assess the source's position.

### 5.2 Evidence Artifact

An `EVIDENCE_ARTIFACT` identifies one immutable version of a content-bearing artifact, including a document, notice, amendment, record, message, dataset release, webpage capture, or equivalent source material. Its content is included directly or bound by a cryptographic digest and governed retrieval location. A mutable URL alone is insufficient identity.

### 5.3 Evidence Occurrence

An `EVIDENCE_OCCURRENCE` identifies the exact acquired or observed occurrence of an artifact. It preserves the source, artifact version, acquisition or observation lineage, exact locator system, language, and relevant verification state. This is the canonical provenance representation in this architecture.

An occurrence may identify a complete artifact or a stable portion of it. Operational acquisition logs may accompany it, but only owner-declared semantic provenance participates in governed identity.

### 5.4 Evidence Extract

An `EVIDENCE_EXTRACT` identifies exact bounded content from one occurrence, with a precise locator and a content digest. It preserves source wording or source data. It may normalize encoding or line endings under a declared deterministic rule, but it may not summarize, paraphrase, interpret, classify, or complete missing content.

An extract is optional when a downstream relationship appropriately targets the whole occurrence or artifact. Creating an extract does not create a new claim.

These classes are exhaustive for version 1.0.0. New classes require a versioned architectural amendment. Domain-specific labels may be represented as typed metadata only when they describe source form or governed scope and do not import downstream semantics.

## 6. Evidence identity

Every Evidence object has a stable, owner-declared identity within the Evidence namespace. Identity must be derived deterministically from immutable semantic identity material appropriate to the class.

Identity must distinguish:

- different attributable sources;
- different artifacts;
- different published or effective versions of an artifact;
- different occurrences where occurrence history matters; and
- different bounded extracts or locators.

Identity must not depend solely on a local filename, directory, mutable URL, database row number, ingestion order, current clock time, execution identifier, processing environment, or consumer-provided alias.

Byte-identical copies may remain separate occurrences while sharing one artifact identity. Semantically different versions must never share an artifact identity. Equivalence, duplication, translation, replacement, and supersession are explicit relationships rather than silent identity collapse.

## 7. Evidence digests

Each Evidence object has a cryptographic object digest over its canonical semantic representation and Evidence-owned semantic relationships. The digest verifies content under the object's declared contract version; it is not an analytical confidence score.

Operational execution metadata is excluded from semantic digests. This includes runtime identifiers, processing environment, transient paths, cache state, diagnostics, and timestamps that record when a process ran rather than when a source event occurred.

Source-provided publication dates, governed acquisition dates, effective dates, occurrence identifiers, locators, content digests, and semantic verification states participate when the relevant object contract declares them semantic.

Changing semantic content or an identity-bearing relationship changes the object digest. Replaying identical semantics in a different execution does not.

## 8. Evidence snapshots

An Evidence publication snapshot is an immutable, version-bound set of Evidence objects and Evidence-owned relationships. The snapshot belongs to the Evidence owner.

Every snapshot declares:

- owner identity;
- owner contract version;
- publication contract version;
- snapshot identity;
- snapshot digest;
- canonical object membership;
- canonical relationship membership; and
- any authoritative upstream acquisition-corpus binding required by the Evidence contract.

A snapshot records exact admitted Evidence. Snapshot existence does not itself assert that a corpus is complete for a business purpose. Completeness is a separately validated property of an acquisition plan or consuming operation.

Snapshot identity and digest are deterministic functions of semantic membership and bindings. Operational execution metadata does not alter them.

## 9. Snapshot membership

Snapshot membership is closed and explicit. Every published reference must target an object listed in the exact snapshot bound by the reference. Objects cannot be discovered through implicit current-state lookup.

Membership rules are:

1. each object identity occurs exactly once;
2. each member's digest matches its canonical semantic representation;
3. every Evidence-owned relationship endpoint is either a member of the same snapshot or an explicitly declared external governed reference;
4. required source, artifact, occurrence, and extract closure is complete;
5. membership and relationships are canonically ordered; and
6. absent objects remain absent and cannot be substituted from another snapshot.

The owner may publish multiple snapshots for different bounded corpora. Snapshot boundaries must be explicit and cannot imply cross-snapshot completeness.

## 10. Provenance representation

Provenance is governed semantic information within the Evidence owner boundary. It is not a separate semantic owner or domain in version 1.0.0.

Provenance is represented through `EVIDENCE_OCCURRENCE` objects and their immutable relationships to sources, artifacts, and extracts. It preserves, where applicable:

- attributable source identity;
- exact artifact identity and version;
- occurrence or acquisition identity;
- language;
- exact page, section, paragraph, cell, record, URL capture, or equivalent locator;
- source-provided publication or effective date;
- governed retrieval or acquisition date;
- authenticity or verification state;
- integrity digest; and
- declared lineage, translation, replacement, or supersession.

Operational logs can provide additional audit detail without becoming semantic provenance. A consumer must not infer provenance from filenames, prose, adjacency, or processing order.

A downstream `PROVENANCE` relationship targets the exact occurrence that provides provenance navigation. An `EVIDENCE_SUPPORT` relationship may target an artifact, occurrence, or extract according to the owning downstream contract. The same occurrence may validly satisfy both roles when it exposes the complete required evidence and provenance; no duplicate provenance object is required.

## 11. Publication responsibilities

Owner publication is a responsibility of the Evidence owner, not a separate semantic domain. The Evidence owner publishes only Evidence semantics it already owns.

Publication must:

- validate every object before admission;
- assign stable object and snapshot identities;
- compute canonical digests;
- publish immutable snapshots and manifests;
- expose resolver-compatible governed references;
- declare Evidence-owned relationships exactly;
- retain historical snapshots required by existing references;
- separate semantic publication from operational audit metadata; and
- fail closed when identity, content, provenance, or relationship closure is incomplete.

Publication must not retrieve material, reconcile source claims, create canonical truth, infer relationships, repair missing locators, or create downstream support declarations.

## 12. Relationship model

Relationships preserve meaning without transferring ownership. Each relationship has an owner, type, source, target, version binding, and any role required by its governing contract.

Evidence-owned relationships include:

- an artifact's attributable source relationship;
- an occurrence's relationship to its exact artifact and source;
- an extract's relationship to its occurrence and artifact;
- explicit translation or equivalent-version relationships;
- explicit replacement or supersession relationships; and
- declared lineage among Evidence objects.

Cross-owner relationships follow [Governed Reference Resolution Architecture](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md). A downstream owner declares its own `EVIDENCE_SUPPORT` or `PROVENANCE` edge and supplies the exact Evidence reference. The Evidence owner validates the target object, not the downstream semantic claim that relies on it.

Conflicting source statements remain separate Evidence objects or extracts. Evidence does not resolve the conflict. Duplicate artifacts remain explicit occurrences and may carry a declared equivalence relationship only when deterministic integrity and version rules prove equivalence.

## 13. Resolution compatibility

Every externally resolvable Evidence reference must preserve the metadata required by the governed resolution protocol:

- Evidence owner identity;
- exact object identity and semantic class;
- owner contract version;
- publication contract version;
- exact snapshot identity and digest;
- exact object digest; and
- authority class permitted by the Evidence contract.

Evidence publications expose exact semantic values, typed properties, Evidence-owned relationships, and provenance navigation required by authorized consumers. Consumers receive read-only resolved content, never Evidence ownership.

Resolution must reject missing objects, owner mismatch, class mismatch, version mismatch, digest mismatch, stale or incompatible context, incomplete provenance, and incomplete relationship closure. There is no fallback lookup, current-state substitution, fuzzy locator matching, or consumer-side repair.

## 14. Historical compatibility

Historical references retain their original meaning. The Evidence owner must preserve resolvable historical snapshots for the retention period required by governing repository policy and existing immutable contracts.

A corrected artifact, new acquisition, changed verification state, improved locator, or later source version creates a new object version or snapshot as required by the relevant identity rule. It does not mutate a published snapshot.

Supersession is explicit and directional. A successor does not erase its predecessor, rewrite historical provenance, or cause old references to resolve to current content. Unsupported legacy Evidence representations may be replayed only through a versioned compatibility contract that preserves their original identity and uncertainty; they must never be silently upgraded.

## 15. Deterministic serialization

Canonical serialization must be fully specified by the implementing Evidence contract and must include:

- UTF-8 encoding;
- normalized Unicode and line endings under one declared rule;
- explicit nullability;
- stable field names and enum values;
- canonical ordering of objects, relationships, locators, and collections;
- deterministic date and time representations without invented time zones;
- canonical numeric representation; and
- exclusion of operational metadata from semantic serialization.

Unordered maps, local paths, runtime object representations, locale-dependent formatting, filesystem iteration order, and current timestamps cannot affect semantic serialization.

Identical semantic Evidence produces byte-identical canonical serialization, identical digests, identical identities, and identical governed references.

## 16. Validation

Construction and publication fail closed unless all applicable rules pass.

Validation must establish:

- supported owner, object, publication, and contract versions;
- unique and structurally valid identities;
- required semantic fields for each object class;
- valid source-to-artifact-to-occurrence-to-extract closure;
- exact, non-fuzzy locators appropriate to the artifact type;
- valid language and date representations where present;
- valid URLs where URLs are semantic, without treating URL reachability as identity proof;
- content and integrity digest correctness;
- canonical ordering and serialization;
- immutable snapshot membership;
- object and snapshot digest correctness;
- relationship ownership and endpoint validity;
- explicit handling of duplicates, translations, replacements, and supersession;
- complete provenance for every externally supportable object; and
- absence of prohibited analytical or decision content.

Authenticity state must be explicit. Unverified material may be retained when the Evidence contract permits it, but its state must remain visible and downstream owners must not receive it as verified. Missing metadata must remain missing; validators cannot invent or infer it.

## 17. Fail-closed behaviour

Evidence construction, publication, admission, or resolution must fail closed for:

- missing or ambiguous source identity;
- malformed or duplicate object identity;
- absent required content or content digest;
- inconsistent artifact versions;
- unsupported semantic class, language, locator, or version;
- invalid or incomplete provenance;
- unresolved relationship endpoints;
- duplicate snapshot membership;
- object or snapshot digest mismatch;
- owner or authority mismatch;
- stale or incompatible resolution context;
- missing historical snapshot;
- implicit current-state substitution;
- attempted semantic repair or fuzzy matching; or
- prohibited canonical, analytical, interpretive, presentation, or decision content.

Failure is explicit and typed. Rejection does not delete the acquisition record or operational diagnostics, but rejected material cannot enter a governed Evidence snapshot.

## 18. Explicit exclusions

Evidence does not own or produce:

- Canonical Truth or canonical field states;
- normalized requirements, evaluation, submission, or Contract Hygiene entities;
- Opportunity Intelligence or Buyer Intelligence;
- Executive Opportunity Understanding;
- analysis, interpretation, classification, assumptions, alternatives, limitations, or management questions;
- conflict resolution or authoritative supersession decisions outside source-artifact lineage;
- presentation, narrative, rendering, scoring, ranking, recommendation, or prediction;
- procurement, commercial, legal, compliance, or business decisions; or
- publications, snapshots, objects, or identities owned by another domain.

Evidence may record a source's own words containing any of these concepts. Recording source content does not adopt that content as an Evidence-layer conclusion.

## 19. Compatibility with repository domains

### 19.1 Canonical Opportunity and its publication

Canonical Opportunity may consume resolved Evidence and publish canonical observations, field states, and conflicts. Its publication declares outgoing support and provenance relationships to exact Evidence references. Evidence remains the target owner; Canonical Opportunity remains the owner of canonical truth and of its outgoing declarations.

### 19.2 Opportunity Orchestration

Opportunity Orchestration may admit a compatible Evidence snapshot alongside other immutable owner publications and assemble a bounded resolution context. It owns no Evidence object, Evidence snapshot, provenance, or support relationship. Admission cannot cure an invalid Evidence publication.

### 19.3 Opportunity Intelligence and publication

Opportunity Intelligence may resolve Evidence through governed support bindings and may publish analytical objects with exact outgoing Evidence relationships. It cannot copy Evidence into analytical ownership, replace provenance, or reinterpret an Evidence object's authority state.

### 19.4 Executive Opportunity Understanding

Executive Opportunity Understanding organizes published analytical and governed references. It does not ingest raw Evidence as a substitute for owner publication, duplicate Evidence values, or create provenance. Presentation consumers navigate Evidence through its bound resolution context.

### 19.5 Buyer and future domains

Buyer Evidence contracts may specialize permitted categories, acquisition scope, and completeness for public organizational material while conforming to this repository-wide owner boundary. They cannot redefine general Evidence identity or transfer Evidence authority to Buyer Intelligence.

Contract, compliance, due-diligence, proposal, and future domains consume the same protocol. Domain-specific use does not require a new general Evidence owner.

## 20. Acceptance criteria

This architecture is satisfied only when:

1. Evidence has one explicit domain-neutral semantic owner boundary.
2. Source, artifact, occurrence, and extract semantics remain distinct and immutable.
3. Provenance is completely represented and resolvable within the Evidence owner boundary without creating a separate Provenance domain.
4. Every published object and snapshot has deterministic identity, canonical serialization, and verified digests.
5. Snapshot membership and Evidence-owned relationships are closed, immutable, and canonically ordered.
6. Governed references bind exact owner, object, version, snapshot, and digest identities.
7. Historical references never resolve against substituted current state.
8. Missing, malformed, ambiguous, stale, or incomplete Evidence fails closed without repair or inference.
9. Operational execution metadata remains auditable without influencing semantic identity or equality.
10. Canonical, analytical, organizational, orchestration, resolution, and presentation owners retain their existing authority boundaries.
11. Evidence contains no downstream facts, intelligence, interpretation, ranking, recommendation, or decision.
12. The architecture operates consistently across procurement, contracts, compliance, due diligence, Buyer Intelligence, and future governed products.

## Summary of architecture

This architecture formalizes the repository's existing Evidence layer as the independent owner of attributable source representations. It introduces no second Provenance owner: occurrence objects and Evidence-owned relationships preserve provenance inside the same constitutional boundary. Evidence owner publication exposes immutable, versioned, snapshot-bound objects for governed resolution while leaving canonical facts, analysis, organization, orchestration, and presentation with their established owners.

The result closes the ownership and publication gap identified in the [Evidence and Provenance Architectural Review](EVIDENCE_AND_PROVENANCE_ARCHITECTURAL_REVIEW.md) without creating a new semantic authority or duplicating canonical truth.
