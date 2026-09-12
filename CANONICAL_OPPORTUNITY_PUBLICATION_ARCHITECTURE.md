# Canonical Opportunity Publication Architecture

## Document metadata

| Field | Value |
|---|---|
| Document | `CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md` |
| Title | Canonical Opportunity Publication Architecture |
| Authority level | Level 3 — Canonical Domain Publication Contract |
| Version | 1.2.0 |
| Status | Approved |
| Purpose | Define how Canonical Opportunity exposes the semantic objects it already owns as immutable governed objects for exact downstream resolution. |
| Higher authority | [Bid Intelligence Constitution](MANIFESTO.md), [AI Contributor Instructions](AGENT.md), [Product Anti-Goals](ANTI_GOALS.md), [Architecture Doctrine](docs/architecture/ARCHITECTURE.md), [Decision Information Doctrine](docs/architecture/DECISION_DOCTRINE.md), and [Governed Reference Resolution Architecture](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md) |
| Validated basis | [Canonical Opportunity Publication Architectural Review](CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURAL_REVIEW.md) |
| Governed implementation | Future Canonical Opportunity owner-publication contracts, validators, immutable snapshots, manifests, and governed references |
| Related architecture | [Opportunity Intelligence Analyst Specification](OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md), [Executive Opportunity Understanding Architecture](EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md), and [Executive Opportunity Brief Architecture](EXECUTIVE_OPPORTUNITY_BRIEF_ARCHITECTURE.md) |

## 1. Purpose

Canonical Opportunity Publication makes existing canonical opportunity truth addressable, immutable, verifiable, and resolvable across repository boundaries. It publishes exact canonical semantic objects under their existing Canonical Opportunity ownership.

Publication does not create canonical truth. Canonical Opportunity first establishes what the available authoritative procurement evidence supports, including explicit unresolved and conflicted states. Publication then exposes that exact validated state through the repository-wide governed reference protocol.

This capability strengthens Opportunity Intelligence by reducing the burden of proving which exact canonical state supported an analysis. It preserves sovereign human judgment because publication neither interprets an opportunity nor recommends an action.

## 2. Authority boundary

Canonical Opportunity remains the sole owner of:

- canonical resolved field states;
- canonical observations admitted under its existing contract;
- canonical conflict states created by its own reconciliation authority;
- canonical supersession decisions validated under its existing rules;
- the Canonical Opportunity publication identity;
- the immutable membership and digest of its publication snapshot; and
- owner-declared relationships from its canonical objects to other governed objects.

Publication has authority to represent these owned semantics exactly. It may assign publication metadata required for immutable resolution: owner contract, publication version, semantic object class, snapshot binding, canonical serialization, object digest, snapshot digest, and governed references.

Publication has no authority to alter a value, select a conflicted alternative, strengthen provenance, repair evidence, normalize a new fact, infer a relationship, or change the status established by Canonical Opportunity.

## 3. Architectural position

```text
Authoritative procurement evidence and owning provenance domains
                              ↓
                    Canonical Opportunity
                              ↓
             Canonical Opportunity Publication
                              ↓
             Governed Reference Resolution
                              ↓
     Opportunity Intelligence input orchestration
                              ↓
                  Opportunity Intelligence
```

Canonical Opportunity Publication is part of the Canonical Opportunity owner boundary. It is not a new domain, intelligence layer, persistence layer, service, registry, resolver, or presentation component.

Other owner snapshots may be assembled with a Canonical Opportunity publication snapshot by a separately governed orchestration boundary. This architecture does not create that multi-owner context and does not grant Canonical Opportunity authority over its other members.

## 4. Publication responsibilities

Canonical Opportunity Publication shall:

1. accept one completely validated canonical opportunity state under one exact supported Canonical Opportunity contract version;
2. preserve the canonical opportunity identity and authoritative input binding;
3. publish every eligible Canonical Opportunity-owned object exactly once;
4. preserve exact stable object IDs already assigned by Canonical Opportunity;
5. expose every semantic field needed to interpret each published object without consumer inference;
6. preserve status, precision, scope, normalization state, conflict state, provenance state, and governed absence — including a governed absence of evidence or provenance relationship closure for an observation whose provenance_status is PARTIAL or UNVERIFIED, published as an explicit empty binding rather than by omitting the observation or withholding the publication;
7. declare exact evidence, provenance, conflict-member, and supersession relationships already present in the canonical state, or their explicit governed absence when the canonical state does not itself establish full closure for an observation Canonical Opportunity has not declared VERIFIED;
8. produce deterministic object digests, snapshot identity, snapshot digest, manifest ordering, and references;
9. validate complete object membership and relationship closure — required unconditionally for every observation Canonical Opportunity declares VERIFIED, and satisfied by an explicit empty binding for one it declares PARTIAL or UNVERIFIED; and
10. emit no publication when identity, semantics, ownership, compatibility, or required closure cannot be proven for any VERIFIED observation. A PARTIAL or UNVERIFIED observation's own inability to achieve evidence or provenance closure is not, by itself, grounds to withhold the entire publication; a missing or unrecognized provenance_status is held to the same requirement as VERIFIED.

Publication is read-only with respect to its canonical input. It cannot mutate the input or make a valid canonical state depend on publication success.

This distinction was added in contract version 1.1.0, in direct response to live commissioning evidence: a real procurement package whose Canonical Opportunity ledger contained observations Canonical Opportunity's own provenance check had already, independently declared PARTIAL was otherwise permanently unpublishable in full under the prior 1.0.0 text, which required identical closure for every sourced observation regardless of its own declared provenance state. The change does not weaken the requirement for any VERIFIED observation, does not alter Canonical Opportunity's existing resolution rule (a PARTIAL or UNVERIFIED observation still cannot resolve an executive field), and does not permit any evidence or provenance relationship to be fabricated — only an already-declared absence to be published honestly instead of blocking publication of every other, fully-grounded observation.

Contract version 1.2.0 adds one additive object class, `CANONICAL_OPPORTUNITY_IDENTITY` (§6.4), in direct response to live commissioning evidence documented in [OPPORTUNITY_IDENTITY_AND_LEGACY_DATES_ARCHITECTURE.md](OPPORTUNITY_IDENTITY_AND_LEGACY_DATES_ARCHITECTURE.md): no publication anywhere exposed a governed object representing the Opportunity itself, so a required Opportunity Intelligence support relationship to its own analysis context could never resolve. The new object introduces no new owner, no new authoritative input, and no new reconciliation — its semantic content restates only facts the canonical state already carries (`opportunity_id`, source schema version, authoritative input digest, document count) and its only relationships declare, as fact, which already-published `CANONICAL_FIELD_STATE` objects constitute it. Every publication produced under 1.1.0 remains a valid subset of what 1.2.0 produces; no existing object, relationship, or validation rule for `CANONICAL_FIELD_STATE`, `CANONICAL_OBSERVATION`, or `CANONICAL_CONFLICT` changed.

## 5. Explicit exclusions

Canonical Opportunity Publication does not own or publish as Canonical Opportunity objects:

- normalized requirements;
- evaluation entities or evaluation hierarchy objects;
- submission entities, artifacts, rules, pathways, or projections;
- Contract Hygiene entities, including admitted deliverables and commercial clauses;
- evidence content, source excerpts, documents, citations, or evidence occurrences;
- provenance content or provenance records;
- Opportunity Intelligence objects;
- computed facts, observations owned by analysts, interpretations, hypotheses, assumptions, unknowns, limitations, management questions, recommendations, or decisions;
- Buyer Intelligence, Proposal Compliance, Bid Workspace, or other domain objects; or
- publication objects belonging to any other domain.

It also does not:

- construct a multi-owner `ResolutionContext`;
- create Opportunity Intelligence `EvidenceSupport` declarations or `OpportunitySupportBindings`;
- resolve governed references;
- retrieve evidence;
- persist snapshots;
- render a brief;
- call AI; or
- expose mutable current state as an immutable historical snapshot.

A relationship from a canonical object to evidence or provenance does not transfer ownership of its target. Canonical Opportunity publishes the relationship identity; the target owner publishes the target object.

## 6. Immutable published object classes

The publication contract exposes only semantic classes already present in Canonical Opportunity. Publication names the representation class; it does not create a new semantic category.

### 6.1 Canonical field state

A `CANONICAL_FIELD_STATE` represents one exact field governed by Canonical Opportunity, such as an identity field, headline milestone, contract term, monetary field, or procurement classification.

Its owner-declared semantic representation includes, where present in the canonical contract:

- exact field key;
- resolution status;
- exact normalized value or explicit absence;
- contributing canonical observation IDs;
- affecting canonical conflict IDs;
- resolution basis;
- resolving authority or verified supersession basis; and
- any precision, scope, units, currency, date, time, or classification state needed to interpret the value correctly.

`RESOLVED`, `CONFLICTED`, `UNVERIFIED`, `MISSING`, `NOT_CLASSIFIED`, and other supported owner states remain distinct. Publication cannot convert an unresolved state into a value-bearing state.

### 6.2 Canonical observation

A `CANONICAL_OBSERVATION` represents one existing canonical observation. Its semantic representation preserves all meaning-bearing fields declared by Canonical Opportunity, including:

- observation ID and normalized identity ID;
- family and semantic kind;
- original and normalized value;
- normalization state;
- source state;
- document role where Canonical Opportunity governs that role;
- scope;
- provenance status;
- supersession state;
- related conflict IDs; and
- explicit absence for optional canonical properties.

Source excerpts, locators, and occurrence content remain in evidence or provenance owners. The observation links to them through governed relationships rather than republishing their content.

### 6.3 Canonical conflict

A `CANONICAL_CONFLICT` represents one conflict owned by Canonical Opportunity. Its semantic representation preserves:

- conflict ID;
- conflict state;
- affected canonical field or semantic kind;
- exact incompatible values or alternatives as declared by Canonical Opportunity;
- affected canonical observation IDs;
- resolution basis and resolver identity when the conflict is resolved under an authorized canonical rule; and
- explicit unresolved state when no authorized resolution exists.

Publication cannot merge alternatives, select a winner, infer equivalence, or resolve a conflict through ordering.

### 6.4 Opportunity identity

A `CANONICAL_OPPORTUNITY_IDENTITY` represents the Opportunity itself — the single governed anchor other publications' required support relationships resolve against when they need to declare "this concerns THIS opportunity," as distinct from any one of its individual resolved fields. Exactly one exists per publication. Its owner-declared semantic representation is limited to facts the canonical state already carries verbatim:

- the opportunity ID;
- the Canonical Opportunity schema version;
- the authoritative input digest; and
- the document count.

Its only relationships are `DEPENDENCY` ("contains-field-state") to every `CANONICAL_FIELD_STATE` object published alongside it — declaring, as fact, which already-published field states constitute the opportunity's identity. It never restates, reinterprets, or duplicates a field state's own value, status, or provenance; a consumer needing a specific field's value still resolves the `CANONICAL_FIELD_STATE` object directly. Its object ID is deterministic over `(opportunity_id, authoritative_input_digest)` alone, so the identical real input always yields the identical identity, independent of which or how many fields resolved.

### 6.5 Snapshot envelope

The publication envelope binds the published objects to one canonical opportunity identity, one exact Canonical Opportunity contract version, one exact authoritative input digest, one publication version, one immutable snapshot identity, and one immutable snapshot digest.

The envelope is publication metadata. It does not become another semantic opportunity object and does not duplicate the canonical field states contained in the snapshot.

## 7. Semantic field ownership

Every published semantic field must be an exact owner-declared property of the validated Canonical Opportunity input. Publication may encode a property into the domain-neutral governed semantic value types required by Governed Reference Resolution, but the conversion must be lossless and deterministic.

Publication may not:

- derive a display summary from several fields;
- replace typed values with prose;
- omit a status or qualifier required to interpret a value;
- add confidence to a canonical fact;
- interpret provenance strength;
- infer scope from nearby objects;
- convert a missing value into an empty string, zero, false, or placeholder; or
- include operational metadata as canonical meaning.

Execution timestamps, runtime identifiers, processing environment, performance measurements, storage locations, transport metadata, and diagnostics are operational metadata. They may remain independently available for audit but must not affect semantic object identity, object digests, snapshot identity, snapshot digest, governed references, ordering, or downstream semantic equality.

## 8. Object identity and digests

### 8.1 Object identity

Each published object reuses the exact stable Canonical Opportunity object identity assigned under the source contract. Publication cannot generate a replacement semantic identity from display text, collection position, filename, current time, or runtime state.

Canonical field states whose source contract identifies fields by stable field key use an owner-versioned deterministic object identity derived from the canonical opportunity identity and exact field key. This is an identity binding for an existing canonical field, not a new fact identity.

An object reference binds:

- Canonical Opportunity owner domain;
- Canonical Opportunity owner contract;
- exact publication contract version;
- semantic object class;
- stable object ID;
- immutable snapshot identity;
- immutable snapshot digest; and
- object digest.

### 8.2 Object digest

The object digest is a lowercase SHA-256 digest over the canonical serialization of:

- owner domain and owner contract;
- publication contract version;
- semantic object class and stable object ID;
- authority class;
- complete owner-declared semantic fields; and
- complete ordered relationship manifest.

Operational metadata is excluded. Any change to semantic content, authority, relationship membership, relationship role, or relationship target binding changes the object digest.

## 9. Snapshot identity and digest

### 9.1 Snapshot identity

Snapshot identity is derived deterministically from:

- Canonical Opportunity owner and publication contract version;
- canonical opportunity identity;
- authoritative canonical input digest; and
- canonical publication object-manifest digest.

The same exact canonical semantics and authoritative input binding produce the same snapshot identity. Operational execution differences do not change it.

### 9.2 Snapshot digest

The snapshot digest covers:

- owner domain and owner contract;
- publication contract version;
- snapshot identity;
- canonical opportunity identity and authoritative input binding;
- complete ordered object membership; and
- every member object digest.

Any semantic, membership, version, ownership, relationship, or authoritative input change produces a different digest. A matching snapshot identity with a different digest is invalid.

### 9.3 Immutable membership

Snapshot membership is closed at publication. Every eligible Canonical Opportunity-owned field state, observation, and conflict appears exactly once. No foreign-domain object appears as a snapshot member.

A relationship target may belong to another snapshot in a compatible bounded resolution context. That target remains outside Canonical Opportunity snapshot membership.

Published snapshots are immutable. “Latest,” mutable aliases, database rows without version binding, and runtime reconstruction against current state cannot satisfy a historical reference.

## 10. Canonical ordering and serialization

Canonical serialization is UTF-8 JSON with deterministic object keys, explicit enum values, explicit nulls where the owner contract distinguishes absence, and no dependence on insertion order, locale, process identity, runtime time, or storage order.

Ordering is deterministic:

1. object membership by semantic object class and stable object ID;
2. semantic fields by owner-declared field name;
3. relationships by source identity, relationship kind, role, ordinal, and target identity;
4. collection values by the order declared meaningful by Canonical Opportunity, or by a documented stable identity key when source order has no semantic meaning; and
5. conflict members and supersession targets by stable identity unless the Canonical Opportunity contract declares semantic order.

Publication must preserve source-contract order when that order carries meaning. It cannot reorder by perceived importance, frequency, confidence, source filename, or presentation preference.

## 11. Governed reference production

Publication emits one immutable governed reference for every snapshot member. References conform exactly to [Governed Reference Resolution Architecture](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md).

Reference production occurs only after complete snapshot validation. A reference cannot name a provisional snapshot digest, unresolved placeholder, mutable alias, or object omitted from the final manifest.

References grant read-only semantic access. They do not transfer canonical ownership, grant permission to alter a value, or establish that the available corpus is complete.

## 12. Relationships

Relationships are owner-declared edges. Their kind, role, direction, ordinal, source, target owner, target contract version, target snapshot, and target object digest are immutable and included in integrity validation.

### 12.1 Evidence relationships

A canonical object that relies on source evidence declares an `EVIDENCE_SUPPORT` relationship to the exact evidence object published by the evidence owner. The relationship does not copy excerpts, documents, citations, or locators into Canonical Opportunity ownership.

Every required evidence target must resolve with evidence authority in the bounded context used by the consumer. A missing target, wrong authority, unsupported version, or digest mismatch fails relationship closure.

### 12.2 Provenance relationships

A canonical observation declares a `PROVENANCE` relationship to every owner-published provenance object required to trace the observation to its source occurrence and locator. Canonical Opportunity preserves the relationship but does not own the occurrence, locator, extraction record, or source content.

If the existing evidence owner combines evidence and occurrence provenance in one governed object, the reference retains that owner contract. Publication does not create a parallel provenance representation.

### 12.3 Conflict relationships

A canonical conflict declares `CONFLICT_MEMBER` relationships to every affected canonical observation. A canonical field state affected by the conflict declares the exact relationship needed to retain the unresolved state and navigate to the conflict.

Conflict relationships are complete and bidirectional only when Canonical Opportunity already declares both directions. Publication cannot infer a reverse edge.

### 12.4 Supersession relationships

A canonical observation with an authorized, verified supersession declares a `SUPERSESSION` relationship to every exact superseded canonical observation. The semantic representation retains the supersession basis and state already established by Canonical Opportunity.

Unverified, ambiguous, partial, or inferred amendment relationships cannot be published as verified supersession. Publication cannot use document dates, filenames, extraction order, or source frequency as a replacement supersession rule.

### 12.5 Relationship closure

Internal relationships must close within the Canonical Opportunity snapshot. External evidence and provenance relationships must close within the exact compatible owner snapshots admitted to the consumer's bounded resolution context.

Publication may create its owner snapshot before a multi-owner context is assembled, but it cannot claim complete cross-domain resolvability until every required external target is present and verified in that context.

## 13. Historical compatibility

Every reference names the exact Canonical Opportunity publication contract version and immutable snapshot that define its meaning. Historical references resolve only against their historical snapshots.

Compatibility with the existing `canonical-opportunity/1` contract must be explicit and lossless. A publication adapter may expose an existing validated canonical state only when it preserves:

- stable canonical identities;
- every required semantic field and explicit absence;
- status, normalization, provenance, conflict, precision, and scope;
- complete object membership;
- evidence, provenance, conflict, and supersession relationships; and
- authoritative input and digest traceability.

The adapter fails when existing data cannot provide required identity, meaning, or relationship closure. It cannot rerun extraction or reconciliation, select a newer canonical state, repair missing provenance, or reinterpret an older schema.

A future publication version may define a deterministic compatibility transformation. The transformation must name source and target versions, preserve ownership and meaning, reproduce digests, and fail whenever lossless representation is impossible.

## 14. Resolver compatibility

Canonical Opportunity Publication conforms to the shared protocol rather than creating domain-specific lookup behavior.

Successful resolution guarantees the consumer:

- exact Canonical Opportunity ownership;
- exact object class and stable identity;
- exact publication and snapshot versions;
- verified object and snapshot digests;
- complete owner-declared semantic fields required by the consumer;
- unchanged authority, status, precision, scope, normalization, uncertainty, and conflict state;
- exact relationship identities and navigation; and
- deterministic results for the same reference and bounded context.

The resolver verifies these guarantees. It does not create the published object, snapshot, semantics, relationship, or compatibility rule.

## 15. Validation

Publication validates before emitting a snapshot or reference:

1. the source is one validated, supported Canonical Opportunity state;
2. the canonical opportunity identity and authoritative input digest are present and consistent;
3. every published member belongs to Canonical Opportunity;
4. every eligible owned object appears exactly once;
5. no excluded or foreign-domain object is included;
6. each object has a supported semantic class and exact stable ID;
7. every required semantic field is present with its exact type and explicit absence;
8. resolved and unresolved states obey the source Canonical Opportunity contract;
9. object and snapshot serialization, identities, and digests reproduce exactly;
10. internal relationships close within the snapshot;
11. relationship kinds, roles, ordinals, targets, owners, versions, and digests are exact;
12. required evidence and provenance relationships are declared without copied target content;
13. conflict membership and verified supersession are complete;
14. canonical ordering is reproducible;
15. operational metadata is excluded from semantic identity; and
16. publication did not mutate its source.

Validation records may describe success or controlled failure for audit. They are operational records and do not become canonical semantic objects merely because publication produced them.

## 16. Fail-closed behaviour

Publication emits no snapshot or governed reference when any required invariant fails, including:

- missing, duplicate, unstable, or mismatched identities;
- unsupported Canonical Opportunity or publication versions;
- missing canonical opportunity or authoritative input binding;
- semantic fields that are missing, malformed, lossy, or inconsistent with canonical status;
- foreign-domain objects presented as Canonical Opportunity members;
- object or snapshot digest mismatch;
- nondeterministic ordering or serialization;
- incomplete snapshot membership;
- missing internal relationship targets;
- incomplete evidence, provenance, conflict, or supersession relationships;
- unverified supersession presented as authoritative;
- mutable or current-state substitution;
- incompatible historical state; or
- source mutation.

Failure does not permit omission of the invalid object from an otherwise complete snapshot, generation of placeholder objects, inferred references, fuzzy matching, downgraded relationship requirements, direct current-state lookup, or publication under another owner.

Canonical Opportunity remains valid under its own contract when publication fails. The cross-domain transition requiring governed publication stops and exposes the controlled failure.

## 17. Compatibility with downstream architecture

### 17.1 Governed Reference Resolution

Canonical Opportunity supplies owner-declared objects, immutable snapshot membership, exact references, digests, and relationships. Governed Reference Resolution remains a domain-neutral verifier and transfers no authority.

### 17.2 Opportunity Intelligence

Opportunity Intelligence receives exact references to canonical field states, observations, and conflicts through a bounded authoritative context. It may compute or reason only within its existing authority. It cannot modify canonical states or treat an unresolved conflict as resolved.

This publication does not supply normalized requirements, evaluation entities, submission entities, Contract Hygiene entities, or non-canonical conflicts. Their owners must publish them independently when Opportunity Intelligence requires governed resolution.

### 17.3 Opportunity Intelligence Publication

Opportunity Intelligence Publication may bind its existing `EvidenceSupport` declarations to Canonical Opportunity references supplied through the governed input context. It continues to publish only Opportunity Intelligence-owned analytical objects. Canonical semantic content remains upstream and is referenced rather than copied.

Canonical Opportunity Publication does not create `OpportunitySupportBindings`. The governed Opportunity Intelligence orchestration boundary assembles exact bindings from admitted owner references, and Opportunity Intelligence Publication validates and exposes its outbound analytical relationships.

### 17.4 Executive Opportunity Understanding

Executive Opportunity Understanding continues to own deterministic organization and coverage. It organizes published analytical objects and may navigate their exact upstream canonical relationships through the bound multi-owner resolution context. It does not duplicate canonical values.

### 17.5 Executive Opportunity Brief

The Executive Opportunity Brief remains a pure deterministic presentation adapter. It displays owner-resolved semantic values and relationships through Executive Opportunity Understanding's bounded context. It cannot inspect Canonical Opportunity directly or reconstruct canonical values.

## 18. Ownership consistency

This architecture adds addressability without adding authority:

| Responsibility | Owner |
|---|---|
| Create and reconcile canonical truth | Canonical Opportunity |
| Publish Canonical Opportunity-owned objects | Canonical Opportunity |
| Publish evidence and provenance content | Their existing evidence and provenance owners |
| Publish normalized requirements, evaluation, submission, and Contract Hygiene objects | Their existing semantic owners |
| Assemble a compatible multi-owner context | Governed operation orchestrator |
| Verify references and relationship closure | Governed Reference Resolution |
| Create and publish opportunity analysis | Opportunity Intelligence |
| Organize governed analytical objects | Executive Opportunity Understanding |
| Render the executive brief | Executive Opportunity Brief |
| Make pursuit and commercial decisions | Authorized humans |

No row transfers or duplicates another row's authority.

## 19. Acceptance criteria

Canonical Opportunity Publication is conformant only when:

1. it is implemented inside the Canonical Opportunity owner boundary;
2. it publishes only resolved field states, observations, and conflicts owned by Canonical Opportunity;
3. every eligible owned object appears exactly once in one immutable snapshot;
4. exact source identities and canonical semantic fields are preserved without summary or inference;
5. conflict, absence, precision, scope, provenance, normalization, and supersession states remain explicit;
6. evidence and provenance remain externally owned and reachable through exact governed relationships;
7. object identity, object digests, snapshot identity, snapshot digest, membership, and ordering are deterministic;
8. operational metadata does not affect semantic identity or equality;
9. every emitted reference resolves to exactly one owner object under a compatible bounded context;
10. required internal and external relationships close without fallback or repair;
11. historical references reproduce their exact historical meaning;
12. no other opportunity, evidence, analytical, workspace, or presentation domain acquires Canonical Opportunity authority;
13. no foreign-domain object is republished as Canonical Opportunity content;
14. unsupported, incomplete, stale, ambiguous, or corrupted publication fails closed;
15. identical validated canonical inputs produce byte-equivalent canonical publication artifacts; and
16. publication failure cannot mutate or invalidate the source Canonical Opportunity state.

## 20. Architectural confirmation

This architecture closes the omission identified by [Canonical Opportunity Publication Architectural Review](CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURAL_REVIEW.md).

It introduces no new semantic authority, domain, runtime service, persistence mechanism, API, schema, prompt, retrieval capability, intelligence, presentation logic, recommendation, or decision. It does not redesign Canonical Opportunity. It defines only how Canonical Opportunity publishes the immutable semantic objects it already owns for governed downstream resolution.
