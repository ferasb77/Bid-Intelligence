# Evidence and Provenance Architectural Review

## Document metadata

| Field | Value |
|---|---|
| Document | `EVIDENCE_AND_PROVENANCE_ARCHITECTURAL_REVIEW.md` |
| Title | Evidence and Provenance Architectural Review |
| Authority level | Level 5 — Operational architectural review |
| Version | 1.0.0 |
| Status | Review finding |
| Purpose | Determine the constitutional ownership and publication requirements of Evidence and Provenance in the governed opportunity pipeline. |
| Higher authority | [The Bid Intelligence Constitution](MANIFESTO.md), [Repository Governance](GOVERNANCE.md), [Architecture Doctrine](docs/architecture/ARCHITECTURE.md), [Decision Doctrine](docs/architecture/DECISION_DOCTRINE.md), and [Canonical Domain Vocabulary](docs/architecture/DOMAIN_MODEL.md) |
| Governed documents | None; this review does not amend architecture. |
| Related documents | [Canonical Opportunity Publication Architecture](CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md), [Governed Reference Resolution Architecture](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md), [Opportunity Orchestration Architecture](OPPORTUNITY_ORCHESTRATION_ARCHITECTURE.md), [Opportunity Intelligence Analyst Specification](OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md), and [Opportunity Orchestration Architectural Review](OPPORTUNITY_ORCHESTRATION_ARCHITECTURAL_REVIEW.md) |

## Executive summary

The repository already places Evidence before Canonical Truth and assigns Evidence semantic ownership to the Evidence layer. Evidence is therefore an independent semantic owner in the architectural sense: it owns the meaning and validity of attributable source representations. It is not owned by Canonical Opportunity, Opportunity Intelligence, Opportunity Orchestration, or Governed Reference Resolution.

Provenance is not constitutionally established as a second independent semantic domain. It is the governed origin, occurrence, and location information retained by the source or Evidence subsystem. The existing architecture explicitly permits provenance to be exposed either through a distinct owner-published provenance object or through an Evidence-owner object that combines evidence and occurrence provenance. Creating a separate Provenance domain is neither required nor currently authorized.

Canonical Opportunity owns its canonical observations, field states, conflicts, and the relationship declarations from those objects. It owns neither the evidence targets nor their provenance content. It may retain source identifiers and publish exact relationships, but those references do not transfer Evidence authority.

Cross-domain governed resolution requires Evidence-layer objects to become immutable, versioned, owner-published objects bound to exact snapshots and digests. Provenance must also be resolvable as owner-declared semantic content, but it does not necessarily require a separate owner or separate snapshot. The same Evidence-layer object may satisfy both `EVIDENCE_SUPPORT` and `PROVENANCE` relationships when its contract exposes complete evidence and occurrence provenance.

The constitutional owner exists, but the repository lacks a general Evidence and Provenance architecture for authoritative procurement material. Existing doctrine does not define the stable namespaces, semantic object classes, complete provenance representation, snapshot boundaries, publication identity, versioning, relationship rules, or historical retention required by Governed Reference Resolution. Buyer Evidence is a separate, buyer-specific contract and cannot silently become the owner of procurement evidence.

**Conclusion: C. A new constitutional architecture is required.**

The required architecture should govern the already-existing Evidence layer. It need not create a new domain, a separate Provenance owner, or a standalone publication domain.

## Review scope and authority note

This is an architectural review only. It defines no production component, schema, API, persistence mechanism, migration, service, or implementation plan.

The requested `CANONICAL_OPPORTUNITY_ARCHITECTURE.md` is not present in the repository. Canonical Opportunity authority was therefore evaluated through [Architecture Doctrine](docs/architecture/ARCHITECTURE.md), [Decision Doctrine](docs/architecture/DECISION_DOCTRINE.md), [Canonical Domain Vocabulary](docs/architecture/DOMAIN_MODEL.md), the approved [Canonical Opportunity Publication Architecture](CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md), and the inspected production contracts. This review does not invent content for the absent document.

## Current production blocker

The corrected Bank of Canada boundary run produces a valid Canonical Opportunity with canonical observations, field states, conflicts, and an authoritative input digest. Canonical Opportunity Publication then fails closed with:

```text
MISSING_RELATIONSHIP_BINDING
observation bindings must exactly cover canonical observations
```

This failure is constitutionally correct. Canonical Opportunity Publication requires each sourced canonical observation to declare exact governed evidence and provenance targets. The production pipeline currently supplies source-reference and occurrence data inside Canonical Opportunity, but no owner-published Evidence snapshot exposes those targets as resolver-compatible objects and references.

Canonical Opportunity Publication cannot manufacture the missing targets because doing so would make Canonical Opportunity the apparent owner of source content and occurrence provenance. Opportunity Orchestration cannot manufacture them because orchestration owns composition only. Governed Reference Resolution cannot manufacture them because resolution owns verification only.

The blocker occurs before orchestration. Opportunity Orchestration is therefore not the remaining owner gap.

## Constitutional ownership analysis

### Evidence

[Architecture Doctrine](docs/architecture/ARCHITECTURE.md) defines Evidence as an attributable representation supplied by a source and requires it to retain identity, provenance, location, and relevant status. Evidence precedes Canonical Truth. Canonical Truth describes what available Evidence supports; it does not own the underlying representation merely because it reconciles facts derived from it.

[Canonical Domain Vocabulary](docs/architecture/DOMAIN_MODEL.md) makes the assignment explicit: Evidence is architecturally owned by the Evidence layer. It supports Source Facts, Observations, Requirements, and analytical conclusions while retaining provenance.

Evidence is therefore an independent semantic owner because it has meaning and validation rules that remain authoritative across consumers:

- source identity;
- source occurrence identity;
- exact content or content binding;
- locator and document identity;
- language and applicable version;
- authority and verification state;
- retrieval or acquisition lineage where governed;
- provenance; and
- relationships to source documents and supported objects.

“Independent semantic owner” does not imply an independent runtime service, database, product pillar, or user-facing domain. It means that no downstream domain may rewrite or claim authority over Evidence semantics.

### Provenance

Provenance answers where an evidence representation came from, which occurrence was used, how it was located, and which source identity and version govern it. Those properties are semantic because changing them can change traceability, authority, historical meaning, or relationship closure.

The repository does not assign Provenance to a separate architectural domain. Instead:

- Architecture Doctrine requires Evidence itself to retain provenance and location;
- Decision Doctrine requires source, occurrence, and location to remain identifiable;
- Opportunity Intelligence refers to an authoritative provenance store and prohibits copied provenance;
- Canonical Opportunity Publication requires provenance navigation while excluding provenance content from Canonical ownership; and
- Governed Reference Resolution requires owners to expose exact provenance relationships and complete navigation.

These statements place provenance responsibility in the source or Evidence subsystem that records the attributable occurrence. Provenance is therefore owner-governed semantic content, but not necessarily an independent semantic owner separate from Evidence.

### Source documents, evidence, and provenance

The concepts must remain distinct even when one owner contract represents them together:

- a source document is an attributable artifact or source container;
- an evidence object is a governed representation or extract used to support another object;
- provenance identifies the evidence occurrence, source identity, locator, version, and lineage required to inspect its origin; and
- an evidence relationship records that one governed object relies on an exact evidence target.

Combining these concepts in one immutable Evidence-owner object is permitted only when the object preserves every required identity and semantic distinction. Physical combination does not collapse their meanings.

## Semantic ownership analysis

### Is Evidence an independent semantic owner?

Yes. The Evidence layer owns Evidence semantics and validity. Canonical Opportunity, normalized-entity owners, intelligence analysts, and presentation consumers may reference Evidence but cannot acquire its authority.

### Is Provenance an independent semantic owner?

Not under the current doctrine. Provenance is governed semantic content owned by the subsystem that owns the source representation or occurrence. A future architecture may define a separate provenance owner only if an independently meaningful lifecycle or cross-source responsibility requires it. No such constitutional necessity is established here.

### Are Evidence and Provenance merely relationships?

No. `EVIDENCE_SUPPORT` and `PROVENANCE` are relationships, but their targets must expose resolvable meaning. A relationship records an edge; it cannot replace the target’s source identity, content binding, locator, occurrence, version, authority, or validation state.

Evidence and provenance semantics therefore cannot exist only as untyped relationship labels. They require owner-declared immutable representation somewhere in the admitted snapshot set.

### Does Canonical Opportunity own Evidence?

No. Canonical Opportunity owns its authoritative account of what Evidence supports. It does not own source documents, excerpts, citations, occurrences, locators, acquisition lineage, or Evidence authority.

### What does Canonical Opportunity own in the relationship?

Canonical Opportunity owns the declaration that a canonical object is supported by or traceable through exact upstream targets. In publication terms, it owns the source side, relationship kind, role, direction, and canonical ordering of that edge because those are properties of its canonical object.

The target reference retains the Evidence owner, owner contract, version, snapshot, object identity, and digest. The relationship never transfers target ownership.

### Does Canonical Opportunity own only references to Evidence?

Canonical Opportunity owns its canonical semantics and its exact outgoing evidence and provenance relationship declarations. It carries governed references to external targets. Describing this as “only references” is correct regarding Evidence content and authority, but it must not obscure that the relationship declaration itself is part of the canonical object’s governed meaning.

## Publication analysis

### Evidence objects

Evidence must possess immutable governed objects when it is referenced across owner boundaries. Governed Reference Resolution cannot resolve a filename, raw dictionary, locator string, or evidence ID alone. Successful resolution requires an exact owner contract, supported version, object class, stable object identity, immutable snapshot, object and snapshot digests, semantic fields, authority, and relationship closure.

The Evidence-layer owner publication must expose the complete consumer-safe semantic representation required to identify and inspect the attributable material. It cannot expose only an opaque content blob or force Canonical Opportunity to parse owner internals.

### Provenance objects

Provenance must be resolvable through immutable governed representation, but a distinct Provenance object is conditional rather than universal.

Two constitutionally valid representations are already contemplated:

1. **Combined Evidence object:** one Evidence-owner object exposes evidence identity and the complete occurrence provenance required by consumers. Canonical Opportunity may point both `EVIDENCE_SUPPORT` and `PROVENANCE` relationships to that same exact governed object under different roles.
2. **Distinct Provenance object class:** the same Evidence or source owner publishes separately addressable evidence and provenance objects when occurrences, locators, document versions, or lineage require independent identity and navigation.

Both preserve one owner boundary. Neither requires a separate Provenance domain. The governing Evidence architecture must choose and validate the representation appropriate to each declared object class; consumers and orchestration may not choose opportunistically.

### Publication ownership

Evidence publication belongs inside the existing Evidence owner boundary, following the repository-wide owner-publication pattern. Publication makes existing Evidence semantics addressable; it does not create a publication domain or transfer Evidence authority.

If provenance is published as a distinct object class, it remains within its established source or Evidence owner unless a future ratified architecture assigns another owner. If provenance is combined with Evidence, no parallel provenance publication should be created.

### Why current architecture is insufficient for implementation

[Governed Reference Resolution Architecture](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md) supplies uniform owner obligations, but it intentionally does not define domain semantics. A conforming Evidence owner must still declare:

- stable namespaces for documents, occurrences, evidence extracts, citations, and provenance records as applicable;
- exact semantic object classes;
- identity and equality boundaries;
- content, locator, language, authority, authenticity, and version semantics;
- provenance representation and navigation;
- source-document and occurrence relationships;
- required and optional relationship closure;
- canonical serialization and ordering;
- immutable snapshot membership and authoritative input binding;
- publication and object digests;
- historical compatibility and retention requirements;
- bounded disclosure; and
- fail-closed validation.

Neither the general domain vocabulary nor the resolver may invent these owner-specific rules.

## Relationship analysis

### Evidence support

An `EVIDENCE_SUPPORT` edge means that a governed source object relies on an exact Evidence-layer target. The source owner declares the edge. The Evidence owner declares the target. Opportunity Orchestration admits both snapshots. Governed Reference Resolution verifies both identities, authority, digests, and closure.

No component may derive an evidence target from matching text, filename, page number, array position, or an unqualified evidence ID.

### Provenance navigation

A `PROVENANCE` edge must lead to the exact owner-published representation required to reach source identity, occurrence, locator, applicable version, and lineage. Its target may be the same object used by `EVIDENCE_SUPPORT` or a distinct object declared by the same owning contract.

Canonical Opportunity Publication cannot convert its internal `source_refs` or `extraction_occurrences` into external owner objects. Those values may support a future lossless transition only under an approved Evidence owner contract that establishes identity, ownership, and validation.

### Relationship ownership matrix

| Element | Constitutional owner |
|---|---|
| Source representation and Evidence semantics | Evidence layer |
| Evidence occurrence and provenance semantics | Source or Evidence subsystem that governs the occurrence |
| Canonical observation and canonical state | Canonical Opportunity |
| Canonical object’s outgoing evidence/provenance edge | Canonical Opportunity |
| Evidence/provenance target object | Its source or Evidence owner |
| Owner publication and snapshot | The same semantic owner |
| Cross-owner snapshot admission | Opportunity Orchestration |
| Reference and relationship verification | Governed Reference Resolution |
| Analytical use of admitted support | Opportunity Intelligence |

## Compatibility analysis

### Canonical Opportunity

Canonical Opportunity remains authoritative for reconciled opportunity state. It may preserve source references and occurrence diagnostics as inputs and traceability data, but it cannot become the Evidence owner merely by consuming those values.

### Canonical Opportunity Publication

Canonical Opportunity Publication already defines the correct relationship boundary: it publishes canonical objects and exact external relationships while excluding evidence excerpts, documents, citations, occurrences, and provenance records. A conformant Evidence publication would satisfy its required targets without changing Canonical ownership.

### Opportunity Orchestration

Opportunity Orchestration admits the exact Evidence and Canonical Opportunity owner publications into one bounded context. It does not create their references, derive observation bindings, or repair closure. Once owner publications exist, orchestration may assemble exact support bindings using their declared identities and relationships.

### Governed Reference Resolution

The resolver already defines domain-neutral identity, snapshot, digest, authority, semantic sufficiency, and closure validation. It requires an Evidence owner contract but must not define Evidence or Provenance semantics itself.

### Opportunity Intelligence

Opportunity Intelligence continues to use admitted evidence and canonical entities without copying provenance or promoting evidence into analytical truth. Its `evidence_used` declarations remain references to upstream authority.

### Buyer Evidence

[Canonical Buyer Evidence Architecture](BUYER_EVIDENCE_ARCHITECTURE.md) defines attributable public organizational evidence for Buyer Intelligence. Its scope, categories, authenticity rules, buyer identity, and acquisition context are specific to that pillar. It demonstrates that Evidence can be an immutable owner contract, but it cannot silently govern procurement-package evidence used by Canonical Opportunity.

Reusing its general design principles is possible only through an explicit architecture. Reusing its semantic ownership directly would conflate buyer evidence with opportunity source evidence.

## Options considered

### A. Existing architecture is sufficient

The existing architecture establishes the Evidence layer as owner and correctly excludes Evidence from downstream ownership. That is sufficient to reject fabrication and authority transfer. It is not sufficient to implement resolver-compatible procurement Evidence publication because the required owner contract, semantic classes, identity rules, snapshot boundaries, and provenance representation remain undefined.

Treating the generic resolver protocol as the missing Evidence contract would force implementation to make domain decisions that architecture has not authorized.

### B. Existing architecture requires amendment

A narrow amendment to Canonical Opportunity Publication would be incorrect because that architecture explicitly and correctly excludes Evidence and Provenance content. Amending Opportunity Orchestration or Governed Reference Resolution would likewise give composition or verification components semantic authority.

Expanding Buyer Evidence would cross its buyer-specific purpose. Expanding the canonical domain vocabulary into a complete publication contract would overload a repository-wide vocabulary document with one source subsystem’s identity, versioning, and snapshot rules.

No existing architecture has a sufficiently aligned declared purpose to absorb the missing guarantees through a narrow amendment.

### C. A new constitutional architecture is required

A dedicated Evidence and Provenance architecture is required to govern the already-recognized Evidence layer for authoritative opportunity material. This is a new architecture document, not necessarily a new semantic domain.

Its minimum constitutional purpose would be to define:

- what constitutes governed source Evidence for an opportunity;
- which source or Evidence subsystem owns each object class;
- whether occurrence provenance is combined with Evidence or independently addressable within that owner contract;
- exact identities, versions, semantics, relationships, snapshots, publication guarantees, and historical behavior; and
- fail-closed admission and publication boundaries.

Owner publication should be defined as a responsibility of that Evidence owner, not as a separate publication authority. A separate Provenance domain should not be introduced unless the architecture later proves an independently governed lifecycle that cannot remain inside the source or Evidence owner.

## Architectural recommendation

Create one general Evidence and Provenance architecture for authoritative opportunity source material before implementing production evidence publication or canonical observation bindings.

The architecture should formalize the Evidence layer already established by repository doctrine and preserve Provenance within the source or Evidence owner boundary by default. It should permit distinct provenance object classes only when independent occurrence identity and navigation require them, while explicitly prohibiting duplicate provenance ownership.

The architecture must leave these existing boundaries unchanged:

- Evidence owns attributable source semantics;
- Canonical Opportunity owns canonical truth and outgoing relationship declarations;
- owner publication exposes only owner-governed objects;
- Opportunity Orchestration assembles exact immutable publications;
- Governed Reference Resolution verifies references and closure;
- Opportunity Intelligence owns analysis; and
- humans retain decision authority.

Until that architecture exists, the current `MISSING_RELATIONSHIP_BINDING` failure is the required fail-closed outcome. Implementing evidence or provenance objects directly from current dictionaries would create an undeclared owner contract and must not proceed.

**C. A new constitutional architecture is required.**
