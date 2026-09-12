# Governed Reference Resolution Architecture

## Document metadata

| Field | Value |
|---|---|
| Document | `GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md` |
| Title | Governed Reference Resolution Architecture |
| Authority Level | Level 3 — Repository Architecture |
| Version | 1.0.0 |
| Status | Proposed |
| Purpose | Govern deterministic, immutable, fail-closed resolution of references between repository domains without transferring authority or duplicating canonical truth. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md), [`AGENT.md`](AGENT.md), [`GOVERNANCE.md`](GOVERNANCE.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md), [`docs/architecture/DOMAIN_MODEL.md`](docs/architecture/DOMAIN_MODEL.md), [`docs/architecture/DESIGN_PRINCIPLES.md`](docs/architecture/DESIGN_PRINCIPLES.md), and [`docs/architecture/DECISION_DOCTRINE.md`](docs/architecture/DECISION_DOCTRINE.md) |
| Governed Documents | Future cross-domain reference contracts, immutable snapshot manifests, deterministic resolvers, resolution validators, compatibility specifications, and consumer contracts |
| Related Documents | [`EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md`](EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md), [`BUYER_DOMAIN_ARCHITECTURE.md`](BUYER_DOMAIN_ARCHITECTURE.md), [`BUYER_EVIDENCE_ARCHITECTURE.md`](BUYER_EVIDENCE_ARCHITECTURE.md), [`BID_WORKSPACE_ARCHITECTURE.md`](BID_WORKSPACE_ARCHITECTURE.md), and [`EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURAL_VALIDATION.md`](EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURAL_VALIDATION.md) |

## 1. Purpose

Bid Intelligence contains multiple immutable governed domains. Each domain owns a different kind of truth: evidence domains own attributable source representations, canonical domains own validated facts, intelligence domains own typed analysis, workspaces own coordination records, and humans own decisions. These domains must reference one another without copying authority, silently changing meaning, or requiring every consumer to understand every owner’s internal representation.

Governed reference resolution defines how one immutable domain obtains the exact, version-bound semantic content of an object owned by another immutable domain.

It solves five repository-wide problems:

1. a stable identifier alone proves identity but does not necessarily provide the semantic value required by a consumer;
2. copying an upstream object into a consumer can create an accidental second source of truth;
3. resolving against mutable current state can change historical meaning;
4. domain-specific lookup rules can produce inconsistent behavior, incomplete provenance, and silent fallbacks;
5. a consumer needs a governed way to distinguish unavailable data from an invalid or stale reference.

Reference resolution is a repository concern because the invariant crosses domain boundaries. An owning domain can define its objects, but it cannot unilaterally define how every other domain binds versions, verifies snapshots, closes evidence relationships, or handles failure. A consuming domain can define what it needs, but it cannot grant itself authority over another domain’s content. The repository requires one common protocol governing the boundary between them.

This architecture does not centralize domain data. It centralizes the rules by which immutable domain-owned data is identified, bound, resolved, verified, and consumed.

Governed reference resolution is not:

- a new canonical domain;
- an evidence store;
- a persistence design;
- a network service or API;
- a search or retrieval engine;
- a projection that creates new meaning;
- an intelligence capability;
- a summarizer, classifier, reconciler, or conflict resolver;
- a mechanism for substituting current data for historical data;
- permission for a consumer to inspect arbitrary owner internals.

## 2. Architectural position

```text
Owning Domain Contract
        ↓ publishes immutable identity and resolvable semantics
Governed Reference
        ↓ bound to exact version and snapshot
Governed Resolution
        ↓ validates identity, ownership, digest, and closure
Read-only Consumer
```

The arrows express governed access, not transfer of authority.

An owning domain remains the single source of truth for each resolved object. Resolution makes that truth available under a verified immutable context. A consumer receives the owner’s semantic content and declared relationships. It does not receive ownership and cannot alter the resolved object by presenting, organizing, or using it.

## 3. Authority

### 3.1 Ownership remains with the producing domain

Every resolvable object has exactly one owning domain and one governing owner contract version. The owner defines:

- the object’s identity;
- its semantic type and fields;
- its authority class;
- its validation rules;
- its evidence and provenance relationships;
- its lifecycle and supersession rules;
- which semantic content is safe and necessary to expose to governed consumers.

Resolution cannot change any of these properties.

### 3.2 Resolution has verification authority only

Governed resolution may verify that:

- a reference is well formed;
- the named owner and contract are supported;
- the requested immutable snapshot exists and matches its digest;
- the object exists exactly once in that snapshot;
- the object’s identity, type, version, and digest match the reference;
- required relationships close within the declared resolution context;
- the consumer is receiving the exact owner-declared semantic representation.

Resolution has no authority to create facts, computations, interpretations, assumptions, unknowns, conflicts, recommendations, or decisions.

### 3.3 Consumers never become owners

A consumer may display, organize, compare, navigate, or apply its own authorized operation to a resolved object. It must retain the owner identity, object identity, contract version, snapshot binding, authority class, and evidence relationships required by its consumer contract.

A consumer must not:

- rewrite a resolved value and preserve the original ID;
- promote evidence to canonical fact;
- promote analysis to authoritative fact;
- resolve an upstream conflict;
- assign confidence where the owner does not;
- remove uncertainty from the resolved meaning;
- treat a local cache or rendered copy as a new source of truth;
- silently replace an unavailable historical object with a current version.

### 3.4 Resolution creates no new canonical truth

A successful resolution asserts only that a reference deterministically identified an owner-authored object in a validated immutable context. It does not assert that the real world has not changed, that the corpus is complete, or that the resolved object has greater authority than its owner assigned.

## 4. Core concepts

### 4.1 Governed object

A governed object is an immutable, validated semantic object owned by a repository domain. It may represent evidence, a canonical fact, a computed fact, an analytical statement, an unknown, a conflict, a limitation, a workspace record, a compliance finding, or another explicitly governed class.

### 4.2 Governed reference

A governed reference is an immutable identity claim that names one governed object under one exact owner contract and immutable snapshot.

Every cross-domain reference must identify, directly or through an unambiguous contract-bound namespace:

- owning domain;
- owner contract identity;
- exact supported contract version;
- semantic object class;
- stable object ID;
- immutable snapshot identity;
- immutable snapshot digest;
- object digest when the owner contract defines one;
- relationship role when the meaning of the link depends on that role.

A reference contains no replacement prose and grants no authority. Human-readable labels may accompany a reference for navigation, but labels cannot substitute for resolution or override owner semantics.

### 4.3 Immutable snapshot

An immutable snapshot is the exact validated state against which references resolve. It binds object identities, owner contract versions, semantic content, relationship manifests, and digests.

The snapshot may be represented inside an aggregate or as a separately governed resource. In either case, its content is immutable, its identity is stable, and its digest is reproducible. “Latest,” mutable aliases, current database rows without version binding, and time-dependent lookups are not immutable snapshots.

### 4.4 Resolution context

A resolution context is the closed set of immutable snapshots and owner-contract versions permitted for one deterministic resolution operation. It defines the universe in which references may resolve.

The context must be explicit. It cannot expand through opportunistic search, network discovery, mutable defaults, or consumer guesswork. If a required target is outside the context, resolution fails.

### 4.5 Resolved semantic representation

A resolved semantic representation is the exact, immutable, consumer-accessible meaning exposed by the owning contract for the referenced object. It preserves the owner’s semantic fields, authority class, status, uncertainty, evidence relationships, and provenance navigation required by the declared consumer use.

It is not a consumer-authored summary. It cannot omit a semantic property required to interpret the object correctly. Presentation-safe labels and values must come from owner-declared fields or fixed consumer labels bound to explicit semantic types.

### 4.6 Resolution result

A resolution result records either:

- successful resolution to exactly one validated semantic representation; or
- a controlled failure identifying why resolution could not safely occur.

There is no partially trusted success state. Optional relationships may be absent only when the owner contract explicitly permits absence and exposes that absence as governed state.

## 5. Repository principles

### 5.1 Single ownership

Each semantic object has one owning domain. References may be repeated; authority may not be duplicated. A resolved copy remains a representation of the owner’s object and retains its identity and binding.

### 5.2 Immutable references

Reference identity and binding fields are immutable. A change in owner, object ID, object class, contract version, snapshot, digest, or relationship role creates a different reference.

### 5.3 Immutable snapshots

Resolution occurs only against immutable validated snapshots. Historical references always resolve against their historical snapshots. Mutable current state cannot satisfy a historical reference.

### 5.4 Deterministic lookup

The same governed reference and resolution context produce byte-equivalent semantic results or the same controlled failure. Resolution cannot depend on insertion order, current time, locale, process identity, network timing, model output, heuristic matching, or source frequency.

### 5.5 Exact identity

Resolution uses exact identifiers and declared namespaces. Filename similarity, text similarity, fuzzy locators, inferred aliases, case folding not declared by the owner, and “closest match” behavior are prohibited.

### 5.6 Version binding

Every resolution is bound to an exact supported owner contract version. Consumers declare supported versions and fail on incompatible versions. They do not reinterpret older objects using current semantics.

### 5.7 Digest binding

Snapshot and object digests, where defined, are verified before semantic content is returned. A matching ID with a different digest is a stale or corrupted reference, not a valid substitute.

### 5.8 Semantic completeness

Successful resolution supplies every owner-declared semantic field required by the consuming contract. Identity without necessary meaning is unresolved. A consumer must not infer a missing value from IDs, prose fragments, sibling objects, or presentation context.

### 5.9 Relationship closure

Evidence, provenance, conflict, supersession, dependency, and support relationships required to understand or validate an object must resolve within the declared context or be represented as an explicit governed absence. A dangling required relationship invalidates resolution.

### 5.10 Authority preservation

Resolution preserves semantic type, authority, confidence, support status, uncertainty, conflict state, precision, language, scope, and provenance. It cannot upgrade, downgrade, flatten, or relabel these properties.

### 5.11 Read-only consumption

Resolved semantic representations are immutable. Consumer transformations create separate values under the consumer’s own contract and cannot mutate the owner snapshot or masquerade as owner data.

### 5.12 Fail-closed behavior

Ambiguity, absence, incompatibility, corruption, incomplete closure, or unverifiable binding produces explicit failure. Resolution never repairs, fabricates, coerces, searches for a substitute, or returns an unverified partial object as complete.

### 5.13 Bounded disclosure

Owners expose the semantic content and relationship navigation required by governed consumers. They do not expose credentials, secrets, private transport metadata, internal mutable state, or unrelated records. Bounded disclosure protects security without weakening semantic completeness.

### 5.14 No intelligence in resolution

Resolution performs identity and integrity verification only. It does not summarize, classify, rank, score, infer, reconcile, or choose between conflicting objects.

## 6. Deterministic resolution lifecycle

### 6.1 Reference validation

Validate the reference schema, namespace, object class, owner identity, contract version, snapshot identity, digest formats, and relationship role. Unsupported or malformed values fail before lookup.

### 6.2 Context validation

Validate that the resolution context is immutable, complete for its declared scope, internally version-compatible, and bound to its manifest digest. A context assembled from unrelated snapshots fails.

### 6.3 Owner selection

Select the exact owner registry identified by the reference. No fallback registry, domain alias, or consumer-specific search order is permitted.

### 6.4 Snapshot binding

Locate the exact snapshot identity and verify its digest and owner contract version. Resolution must not substitute a newer, older, or “equivalent” snapshot.

### 6.5 Exact object lookup

Resolve the object ID and semantic class. Zero matches fail as missing. More than one match fails as an identity collision. A class mismatch fails even if the object ID exists.

### 6.6 Object integrity validation

Verify the object digest when defined, validate its owner contract, and confirm that its identity-bearing fields match the reference. A valid container cannot make an invalid nested object resolvable.

### 6.7 Relationship closure

Resolve every required relationship under the same bounded context. Relationship traversal retains edge role, direction, ordering, and owner identity. Cycles are permitted only when the owning contracts explicitly permit them and the resolver detects them without infinite traversal.

### 6.8 Semantic sufficiency validation

Confirm that all fields required by the declared consumer contract are present and valid. A resolver cannot manufacture a missing label, value, unit, precision, scope, statement, conflict alternative, or provenance link.

### 6.9 Immutable result

Return the exact owner-declared semantic representation with its reference, verified bindings, and relationship navigation. Canonical serialization and ordering follow the owner contract. Resolution metadata must not change object meaning or semantic equality.

## 7. Consumer rights

A governed consumer is guaranteed the following when resolution succeeds.

### 7.1 Exact identity and ownership

The consumer receives the exact object ID, semantic class, owning domain, owner contract, contract version, snapshot identity, and verified digests.

### 7.2 Deterministic semantic values

The consumer receives the exact owner-declared values necessary for its governed operation. This includes normalized and display values where the owner contract distinguishes them. Presentation consumers are not required to recreate values from identifiers or source text.

### 7.3 Authoritative labels and typed properties

The consumer receives explicit semantic field types and owner-declared labels where labels carry meaning. Dates retain kind, precision, and timezone state. Monetary values retain currency and unit. Scoped objects retain scope. Computations retain formula identity, inputs, denominator, unit, and null behavior where applicable. Analytical objects retain statement type, wording, confidence, support status, assumptions, alternatives, gaps, and limitations as defined by their owner.

### 7.4 Authority and uncertainty

The consumer receives the exact authority class, verification state, conflict state, ambiguity, partial precision, and other governed uncertainty. A resolved object cannot appear more certain merely because it is easier to present that way.

### 7.5 Evidence relationships

The consumer can navigate the exact evidence-support relationships declared by the owner. Relationship roles, occurrence identities, and required ordering remain intact.

### 7.6 Provenance navigation

The consumer can reach the governed provenance required to inspect origin, source identity, locator, publication or effective version, language, and applicable supersession history. Access may remain reference-based, but every required reference must close within the resolution context.

### 7.7 Immutable snapshot consistency

All resolved objects used in one governed output come from the declared compatible snapshot set. The consumer is protected from accidental mixing of historical and current state.

### 7.8 Deterministic ordering

Ordered owner collections retain owner-defined order. Unordered collections use canonical ordering defined by the owning contract. Resolution does not introduce presentation priority.

### 7.9 Explicit absence and explicit failure

The consumer can distinguish a valid governed unknown or optional absence from a broken reference, incomplete snapshot, incompatible version, or validation failure.

### 7.10 Portable verification

A consumer can verify the identities, versions, and digests of resolved content without trusting mutable ambient state. This does not require every source document to be copied into every consumer artifact; it requires the declared resolution context to remain available and verifiable.

Consumer rights apply only to content within the consumer’s governed purpose. They do not grant arbitrary access to unrelated owner data.

## 8. Owner responsibilities

An owning domain that permits cross-domain references must:

1. define a stable namespace for its object identities;
2. define exact semantic object classes and immutable validation rules;
3. publish an exact contract version for each supported representation;
4. bind resolvable objects to immutable snapshot identities and reproducible digests;
5. expose every semantic field required to interpret an object correctly;
6. distinguish canonical value, normalized value, display value, and source wording where those meanings differ;
7. expose authority, status, confidence, scope, precision, language, and uncertainty without consumer inference;
8. expose required evidence, provenance, conflict, supersession, dependency, and support relationships with explicit roles;
9. define canonical serialization and ordering;
10. define optional fields and governed absence explicitly;
11. provide deterministic compatibility rules for supported historical versions;
12. retain historical snapshots for as long as governed references to them remain valid;
13. fail validation when identity, semantic content, or relationship closure is incomplete;
14. define a bounded consumer-safe representation that excludes secrets and irrelevant internal state without omitting necessary meaning.

An owner must not expose:

- mutable internal objects as immutable snapshots;
- credentials, tokens, private transport headers, or secret configuration;
- unvalidated draft state as authoritative content;
- consumer-specific conclusions presented as owner facts;
- generated labels that change semantic meaning;
- unsupported inferred relationships;
- current values substituted for historical values;
- opaque blobs that force consumers to parse owner internals or infer field meaning;
- lossy summaries in place of the governed object;
- unrestricted domain internals unrelated to the declared consumer purpose.

Owners may evolve independently, but a version change cannot silently alter the meaning of an existing reference.

## 9. Consumer responsibilities

A governed consumer must:

- declare the owner contracts, major versions, object classes, and semantic fields it supports;
- resolve all required references before producing a validated output;
- retain reference identity and authority in derived contracts;
- use exact typed properties rather than keyword inference or fuzzy matching;
- preserve conflicts, unknowns, alternatives, assumptions, limitations, and precision;
- keep local presentation labels distinct from owner semantic values;
- treat caches as immutable copies bound to the same snapshot and digest;
- fail when required semantic content or relationship closure is unavailable;
- avoid persisting or exporting sensitive resolution metadata;
- never treat resolution success as a management decision or analytical conclusion.

A consumer may collapse, paginate, filter, or reorganize content only under its own governing contract. Such presentation operations cannot change the underlying resolved set or imply analytical ranking.

## 10. Failure behavior

Governed resolution fails closed. A failure identifies the reference, expected owner, expected version, expected snapshot, affected relationship role, and a controlled reason without exposing sensitive data.

### 10.1 Missing reference

If no object matches the exact owner, class, and ID in the bound snapshot, resolution fails as `REFERENCE_NOT_FOUND`. The resolver does not search similar IDs, filenames, labels, or other snapshots.

### 10.2 Ambiguous reference

If more than one object matches an identity that must be unique, resolution fails as `REFERENCE_COLLISION`. It does not select by order, recency, or apparent similarity.

### 10.3 Stale reference

If identity matches but a required snapshot or object digest differs, resolution fails as `DIGEST_MISMATCH`. A newer value cannot satisfy the stale reference.

### 10.4 Incompatible version

If the owner contract version is unsupported or incompatible with the consumer, resolution fails as `UNSUPPORTED_CONTRACT_VERSION`. Conversion is allowed only through an explicit deterministic compatibility contract that preserves all required meaning and records non-representable content. Lossy conversion fails.

### 10.5 Missing semantic value

If the object exists but lacks a semantic field required by the consumer contract, resolution fails as `REQUIRED_SEMANTIC_CONTENT_MISSING`. The resolver cannot derive the value from labels, IDs, related objects, or source prose.

### 10.6 Broken provenance or evidence relationship

If a required evidence or provenance target is absent, mismatched, invalid, or outside the resolution context, resolution fails as `REFERENCE_CLOSURE_FAILED`. The primary object does not become valid merely because its own scalar fields are present.

### 10.7 Incomplete snapshot

If the snapshot manifest omits required members, versions, relationship targets, or digests, resolution fails as `SNAPSHOT_INCOMPLETE`. A partial snapshot cannot be presented as a complete resolution context.

### 10.8 Ownership or type mismatch

If the target exists under another owner or semantic class, resolution fails as `OWNERSHIP_OR_TYPE_MISMATCH`. Resolution cannot reinterpret it into the requested class.

### 10.9 Invalid governed object

If the target fails its owner contract, resolution fails as `OWNER_CONTRACT_INVALID`. Upstream validation history does not excuse invalid replayed or imported content.

### 10.10 Unavailable resolution context

If the exact immutable context cannot be accessed or verified, resolution fails as `RESOLUTION_CONTEXT_UNAVAILABLE`. Operational unavailability must not be reported as a governed unknown about the opportunity or buyer.

No failure mode permits silent omission, placeholder facts, default values, guessed labels, fallback to Stage D narrative, or substitution from another domain.

## 11. Compatibility and historical integrity

### 11.1 Exact version support

Owners and consumers declare supported contract versions. The exact version named by a reference governs its meaning. Compatibility is explicit and deterministic.

### 11.2 Compatibility transformations

A compatibility transformation may change representation but cannot create or discard semantic meaning. It must:

- identify source and target versions;
- preserve stable owner and object identities;
- preserve authority, conflict state, uncertainty, evidence, and provenance relationships;
- preserve snapshot and digest traceability;
- identify every field that cannot be represented;
- fail when required meaning would be lost.

It cannot rerun extraction, reconciliation, analysis, or model synthesis.

### 11.3 Historical resolution

Historical references resolve against historical immutable snapshots. Re-rendering an older brief, replaying an analysis, or reviewing an earlier decision must reproduce the semantic content available at that governed point, not today’s current state.

### 11.4 Snapshot sets

A governed output may require snapshots from several owners. The resolution context binds the exact compatible set and its manifest. Compatibility between snapshots must be validated through explicit opportunity, buyer, proposal, workspace, or lifecycle identity relationships. Shared timestamps or filenames do not prove compatibility.

## 12. Uniform application across domains

This architecture applies one protocol to every governed domain. Domain contracts define their semantics; they do not receive special resolution rules.

### 12.1 Canonical Opportunity

Canonical Opportunity owns resolved opportunity facts and explicit conflict states. References resolve exact canonical fields, normalized values, precision, scopes, contributing observations, and provenance under a bound snapshot. Consumers cannot select a conflicting alternative or infer a missing headline value.

### 12.2 Opportunity Intelligence

Opportunity Intelligence owns its computed facts, observations, interpretations, hypotheses, assumptions, unknowns, limitations, and management questions. Resolution preserves exact wording, computation metadata, evidence support, confidence, support status, alternatives, and gaps. It does not turn analysis into canonical truth.

### 12.3 Executive Opportunity Understanding

Executive Opportunity Understanding owns deterministic organization and coverage. Its references to canonical and analytical objects resolve through the same owner-bound mechanism as every other domain. Resolution provides semantic access without transferring fact or intelligence ownership to the understanding or its presentation consumers. This architecture does not amend the Executive Opportunity Understanding contract.

### 12.4 Buyer Domain

Canonical Buyer owns verified buyer identity and canonical organizational facts. Buyer references resolve exact scoped values and supporting evidence under immutable buyer snapshots. Opportunity context cannot silently modify Buyer identity.

### 12.5 Buyer Evidence

Buyer Evidence owns attributable public source records, documents, extracts, citations, authority metadata, language, publication and retrieval dates, and authenticity state. Resolution preserves source identity and occurrence provenance. It does not promote evidence into a buyer fact or interpretation.

### 12.6 Buyer Intelligence

Buyer Intelligence owns its bounded evidence-backed analysis. References resolve typed buyer statements, confidence, assumptions, alternatives, unknowns, limitations, and supporting Buyer Evidence relationships. Resolution does not merge Buyer and Opportunity Intelligence or infer a relationship between them.

### 12.7 Proposal Compliance

Proposal Compliance owns compliance observations and findings. It references authoritative requirements, submission rules, proposal locations, and evidence under exact compatible snapshots. Resolution cannot convert completeness into award likelihood or certify a proposal through presentation alone.

### 12.8 Bid Workspace

Bid Workspace owns collaboration structure, assignments, review records, approvals, and Human Decision references under its own authority rules. References to evidence, canonical truth, intelligence, briefs, proposals, and compliance retain their original owners. Workspace status cannot mutate resolved source content.

### 12.9 Future governed domains

A future domain participates by declaring its namespace, owner contract, immutable snapshots, digests, semantic representations, relationship roles, compatibility rules, and consumer requirements. It may not create a private lookup convention that weakens repository-wide identity, closure, or failure rules.

## 13. Evidence and provenance closure

Evidence and provenance are relationships between governed objects, not decorative links.

A resolvable evidence path preserves:

```text
Consumer Object
    ↓ governed relationship role
Owner Semantic Object
    ↓ evidence support
Evidence Occurrence or Extract
    ↓ source locator
Evidence Document
    ↓ source identity and acquisition record
Attributable Source
```

Each step retains its owner, semantic type, stable ID, snapshot, version, and applicable digest. A consumer may stop traversal when its governed purpose does not require deeper content, but it cannot claim complete traceability when a required edge is unresolved.

Multiple evidence occurrences remain distinct when their occurrence identity or locator matters. Deduplication may reuse one stable object identity but cannot erase meaningful provenance. Supersession is an explicit relationship, never a replacement inferred from recency.

Access restrictions do not permit fabrication. If a consumer is not authorized to view required evidence content, the system reports governed unavailability or denies the operation according to the applicable contract; it does not return unsupported semantic content as verified.

## 14. Determinism and canonical serialization

Reference, snapshot, context, and result contracts require canonical serialization.

Semantic identity must not depend on:

- process IDs;
- memory addresses;
- execution timestamps unless time is itself an owner-declared fact;
- map insertion order;
- filesystem traversal order;
- database default ordering;
- locale-specific formatting;
- mutable URLs;
- network response order;
- model output;
- presentation pagination or layout.

Ordered semantic collections retain owner-defined order. Set-like collections use explicit canonical sort keys ending in stable object identity. Identical references and contexts produce identical result digests.

Operational resolution timestamps, cache hits, transport locations, and performance measurements remain outside semantic equality.

## 15. Security and privacy boundaries

Governed resolution follows least disclosure.

- Source-derived content is treated as data and cannot alter resolution rules.
- References cannot contain executable lookup instructions.
- Resolver selection is controlled by owner identity, not source-provided URLs or code.
- Credentials, access tokens, private headers, temporary signed URLs, and local secret paths never enter semantic contracts or digests.
- Failure records reveal enough identity for audit without exposing protected source content.
- Consumer authorization may restrict access, but authorization cannot alter semantic meaning or cause a different object to satisfy the same reference.
- Cached content retains the same immutable binding and protection as its owner source.

Security filtering must fail if it would remove semantic content required for the declared consumer operation. It cannot silently return a misleading partial object.

## 16. Human judgment boundary

Reference resolution prepares people and governed systems to inspect the same verified information. It does not decide what the information means for a pursuit.

Resolution cannot:

- recommend Bid / No Bid;
- rank facts, findings, suppliers, competitors, or actions;
- assign commercial acceptability;
- choose a strategy or price;
- approve a submission;
- infer bidder capability;
- answer a management question;
- convert a Human Decision into canonical evidence.

Presentation order, successful resolution, evidence volume, and provenance completeness are not scores or recommendations.

## 17. Relationship to domain contracts

This architecture defines the common boundary. It does not amend existing domain semantics.

An existing domain remains valid under its approved contract. When that domain later participates in cross-domain resolution, a governing contract must declare how its stable references bind to immutable snapshots and which owner-authored semantic representation satisfies consumer rights. That declaration conforms to this architecture; it does not transfer ownership to the resolver.

Domain-specific rules remain appropriate for semantic validation. Examples include date precision, monetary currency, evidence authenticity, conflict supersession, analyst support status, and compliance state. The repository resolution protocol verifies and preserves those rules but does not redefine them.

## 18. Validation requirements

A governed resolution is valid only when:

1. the reference schema is exact and supported;
2. owner, namespace, object class, and object ID are unambiguous;
3. owner contract and version are supported;
4. snapshot identity and digest match;
5. object identity and digest match where applicable;
6. the object validates under its owner contract;
7. every required semantic field for the consumer is present;
8. evidence, provenance, dependency, conflict, supersession, and support relationships required by the consumer close;
9. every resolved relationship retains its declared role and direction;
10. snapshot-set compatibility is proven;
11. authority, uncertainty, confidence, precision, scope, and language remain unchanged;
12. canonical ordering and serialization reproduce deterministically;
13. no prohibited inference, repair, fallback, or mutable lookup occurred;
14. the result exposes no secret or unrelated owner state;
15. successful resolution is distinguishable from governed absence and operational failure.

Validation must occur at the resolution boundary even if the owner validated the object earlier. Replay, imports, caches, compatibility transformations, and future consumers may otherwise bypass the newest owner path.

## 19. Acceptance criteria

This architecture is satisfied only when a future governed resolution capability demonstrates that:

1. identical references and resolution contexts produce byte-equivalent semantic results or the same controlled failure;
2. no resolution mutates an owner snapshot, reference, relationship, or consumer input;
3. exact owner, type, version, snapshot, and digest binding is enforced;
4. zero matches, duplicate matches, stale digests, and incompatible versions fail closed;
5. all consumer-required semantic values and typed properties are available without inference;
6. every required evidence and provenance relationship closes within the bounded context;
7. historical references never resolve against mutable current state;
8. consumers cannot acquire or alter owner authority;
9. facts, computations, interpretations, assumptions, conflicts, unknowns, and decisions retain their separate authority classes;
10. compatibility transformations are explicit, deterministic, and lossless for required meaning;
11. bounded disclosure excludes secrets without producing misleading partial semantics;
12. resolution performs no reasoning, classification, summarization, reconciliation, ranking, scoring, recommendation, or decision;
13. domain contracts use the same resolution rules without private fallback conventions;
14. operational unavailability is not represented as a real-world unknown;
15. consumer outputs retain enough identity and binding information for audit and replay.

## 20. Doctrine compliance

### Canonical Truth

Canonical domains remain the sole owners of validated facts. Resolution provides exact read-only access and never creates, reconciles, or updates canonical truth.

### Evidence before inference

Evidence relationships remain attributable and traceable. Intelligence resolves its evidence; resolution never converts evidence into inference or inference into fact.

### Separation of concerns

Owners define and validate semantic objects. Resolution verifies identity, binding, and closure. Consumers perform only their authorized operation. Presentation controls layout. Humans make decisions.

### Human judgment

Resolution exposes governed information without ranking it, interpreting it, or deciding what management should do.

### Immutable contracts

References, snapshots, contexts, resolved semantic representations, and results are immutable and versioned. Derived consumer values cannot mutate their sources.

### Determinism

Exact identifiers, versions, digests, bounded contexts, canonical ordering, and canonical serialization determine every result. Heuristics and mutable ambient state are excluded.

### Fail-closed validation

Missing, stale, ambiguous, incompatible, incomplete, corrupt, or unauthorized resolution cannot become partial success. The system reports the controlled failure and creates no substitute meaning.

## 21. Architectural definition

Governed reference resolution is the repository-wide protocol by which a read-only consumer obtains the exact semantic meaning of an immutable object owned by another domain.

It preserves one source of truth by resolving rather than re-owning. It preserves history through exact snapshot, version, and digest binding. It preserves evidence before inference through relationship closure and authority retention. It preserves deterministic behavior through bounded exact lookup and canonical serialization. It preserves trust by failing closed whenever identity, meaning, provenance, or compatibility cannot be proven.

Resolution connects governed domains. It does not merge them.
