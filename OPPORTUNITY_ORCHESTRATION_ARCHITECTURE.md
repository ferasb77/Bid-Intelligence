# Opportunity Orchestration Architecture

## Document metadata

| Field | Value |
|---|---|
| Document | `OPPORTUNITY_ORCHESTRATION_ARCHITECTURE.md` |
| Title | Opportunity Orchestration Architecture |
| Authority level | Level 3 — Architecture Doctrine |
| Version | 1.0.0 |
| Status | Approved |
| Purpose | Govern deterministic assembly of an operation-scoped, immutable context from independently published owner artifacts. |
| Higher authority | [The Bid Intelligence Constitution](MANIFESTO.md), [Repository Governance](GOVERNANCE.md), [Product Principles](docs/product/PRODUCT_PRINCIPLES.md), [Architecture Doctrine](docs/architecture/ARCHITECTURE.md), and [Decision Doctrine](docs/architecture/DECISION_DOCTRINE.md) |
| Governed documents | Future Opportunity Orchestration contracts, manifests, validators, and conformance tests |
| Related documents | [Opportunity Orchestration Architectural Review](docs/archive/operational/OPPORTUNITY_ORCHESTRATION_ARCHITECTURAL_REVIEW.md), [Governed Reference Resolution Architecture](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md), [Canonical Opportunity Publication Architecture](CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md), [Opportunity Intelligence Analyst Specification](OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md), [Executive Opportunity Understanding Architecture](EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md), and [Executive Opportunity Brief Architecture](EXECUTIVE_OPPORTUNITY_BRIEF_ARCHITECTURE.md) |

## 1. Purpose

Opportunity Orchestration assembles the exact immutable owner publications required for one governed Opportunity Intelligence operation. It creates a closed execution universe in which every admitted reference, semantic object, relationship, and support declaration can be resolved and validated without search, inference, mutable lookup, or authority transfer.

It answers one organizational question:

> Which exact immutable owner publications and reference bindings constitute the authoritative input for this governed opportunity operation?

Opportunity Orchestration reduces coordination and verification burden. It does not establish what an opportunity means, interpret evidence, or decide what a proposal team should do.

## 2. Authority boundary

Opportunity Orchestration has composition authority only. Composition authority permits it to:

- admit or reject exact owner publications for one declared operation;
- verify that admitted publications satisfy the operation's declared compatibility requirements;
- assemble the bounded `ResolutionContext` from admitted immutable snapshots;
- assemble exact `OpportunitySupportBinding` records from existing analyst support declarations and admitted governed references; and
- declare an immutable orchestration manifest for that operation.

Composition authority is not semantic authority. Admission does not endorse, strengthen, weaken, reinterpret, reconcile, summarize, classify, or rank an owner object. A valid unresolved conflict remains unresolved. An unverified observation remains unverified. A hypothesis remains a hypothesis. An admitted reference retains its exact owner, authority class, contract version, snapshot, digest, and relationships.

Opportunity Orchestration cannot repair an owner publication, create a missing object, substitute a current object, infer equivalence, or expand an operation after its context has been finalized.

## 3. Architectural position

```text
Independent semantic owners
        ↓ own semantics
Independent owner publications
        ↓ publish immutable objects, snapshots, manifests, and references
Opportunity Orchestration
        ↓ admits exact publications and assembles one bounded operation context
Governed Reference Resolution
        ↓ verifies identity, integrity, authority, compatibility, and closure
Opportunity Intelligence
        ↓ produces validated analytical semantics
Opportunity Intelligence Owner Publication
        ↓ publishes immutable analytical objects and outbound relationships
Executive Opportunity Understanding
        ↓ organizes governed analytical objects
Executive Opportunity Brief
        ↓ presents governed understanding
Human judgment
```

Opportunity Orchestration is a boundary between independently published authority and governed execution. It is not an owner domain, publication domain, intelligence layer, resolver, persistence layer, service, API, or presentation layer.

## 4. Responsibilities

Opportunity Orchestration shall:

1. identify the exact governed operation and supported orchestration-contract version;
2. determine the complete set of publication roles required by that operation;
3. receive only immutable, owner-published artifacts;
4. validate each publication envelope, owner identity, contract version, snapshot identity, snapshot digest, object manifest, and declared relationships before admission;
5. validate compatibility across the exact authoritative snapshots represented by those publications;
6. reject missing, duplicate, ambiguous, stale, corrupt, foreign, unsupported, or incompatible publications;
7. freeze the admitted publication and snapshot set in canonical order;
8. assemble one immutable, bounded `ResolutionContext` from that frozen set;
9. map each existing Opportunity Intelligence `EvidenceSupport` declaration to exactly one compatible admitted governed entity reference and its declared evidence references;
10. prove complete one-to-one support-binding coverage without synthesizing relationships;
11. declare the exact operation, admissions, compatibility bindings, context identity, context digest, and support-binding digest in an immutable orchestration manifest;
12. submit the context and bindings to their owning validators; and
13. fail closed before analysis or publication when any required guarantee cannot be established.

## 5. Explicit exclusions

Opportunity Orchestration does not:

- extract, normalize, reconcile, interpret, classify, compute, reason, summarize, rank, score, recommend, or decide;
- create or own semantic values;
- create or own governed semantic objects;
- create, alter, or own governed object references;
- create, alter, or own owner publications;
- create, alter, or own owner snapshots;
- create or own evidence or provenance;
- create or own canonical truth;
- create or own requirements, evaluation entities, submission entities, commercial clauses, deliverables, dates, money, procurement mechanics, or conflicts;
- create or own Opportunity Intelligence analysis or analytical conclusions;
- create or own Executive Opportunity Understanding organization;
- create presentation content or rendered artifacts;
- resolve governed references;
- discover publications through network, search, mutable registry defaults, or “latest” aliases;
- transform unsupported publication versions;
- repair incomplete manifests or relationships;
- infer owner or object identity from prose, filenames, positions, similarity, or source frequency;
- select among conflicting semantic values; or
- persist contexts, publications, analysis, or presentation artifacts.

The boundary owns assembly metadata only. It never acquires the authority of anything it assembles.

## 6. Explicit non-ownership

Opportunity Orchestration owns no semantic object, governed object, owner publication, owner snapshot, governed reference, evidence record, provenance record, canonical fact, analytical output, understanding object, or presentation.

Its only owned artifacts are operation-scoped assembly declarations:

- admission decisions tied to exact publication identities;
- compatibility declarations tied to exact immutable snapshot bindings;
- the bounded resolution-context declaration;
- exact support-binding declarations; and
- the immutable orchestration manifest that binds those declarations together.

These artifacts describe composition. They do not restate owner semantics and cannot become an alternative source of truth.

## 7. Admission policy

### 7.1 Eligible publications

A publication is eligible only when all of the following are true:

- it was emitted by the semantic owner named in its publication contract;
- its owner contract and exact version are explicitly supported for the declared operation;
- its immutable snapshot and object manifest validate under that owner contract;
- its declared authority class is permitted for the publication role;
- its authoritative input snapshot binding is compatible with the operation;
- every required relationship target is either in the same snapshot or named by an exact external governed reference;
- it contributes at least one required object or required relationship target to the declared operation scope; and
- admitting it does not create duplicate identity, competing snapshot binding, or undeclared authority.

Eligibility never depends on recency alone. A newer publication is not automatically preferable, and a mutable “current” record is never eligible in place of an exact immutable publication.

### 7.2 Required publication roles

The operation contract declares its required publication roles before admission. For Opportunity Intelligence v1, those roles correspond only to authoritative input classes already permitted by [Opportunity Intelligence Analyst Specification](OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md), when those classes are present and required by the analysis.

Canonical Opportunity Publication can satisfy only Canonical Opportunity-owned roles. Requirements, evaluation entities, submission entities, Contract Hygiene entities, evidence, provenance, and other permitted inputs must be supplied by their own conformant owner publications. Opportunity Orchestration cannot assign those responsibilities or publish substitutes.

An optional role may be absent only when the governing operation contract explicitly permits absence and represents the absence as governed state. Missing required publication roles fail admission.

### 7.3 Owner and contract compatibility

For each candidate publication, orchestration verifies exact agreement among:

- declared owner domain;
- owner contract identity;
- owner publication contract identity;
- supported semantic object classes;
- exact owner and publication contract versions;
- declared publication role; and
- authority classes of member objects.

An owner alias, similar namespace, matching object ID, or structurally similar payload cannot satisfy an owner or contract mismatch.

### 7.4 Version compatibility

Versions are compatible only when the operation contract explicitly lists the exact combination or a governing architecture authorizes a deterministic, lossless compatibility rule. Orchestration cannot infer semantic-version compatibility or adapt an older contract because its shape appears similar.

Unsupported, mixed, or ambiguous versions fail closed.

### 7.5 Digest compatibility

Orchestration verifies every declared publication digest, snapshot digest, object-manifest digest, object digest, and authoritative input digest required by the owner contracts. It also verifies that duplicated references to the same identity carry identical digest bindings.

A matching ID with a different digest is a collision or stale binding, not an equivalent object. Digest mismatch fails admission.

### 7.6 Snapshot compatibility

Every admitted snapshot must belong to the exact opportunity operation and compatible authoritative input state declared by its owner. Publications derived from different opportunity identities, incompatible source-package states, superseded canonical states, or unrelated analytical runs cannot be combined merely because individual objects resolve.

Where one owner publication declares an upstream snapshot dependency, the exact depended-on snapshot must be admitted or its absence must be explicitly allowed by the governing contract. Snapshot compatibility is transitive only when every intermediate owner declaration and digest binding is present.

## 8. Publication compatibility

Publication compatibility is a declared, verifiable relationship among exact owner publications. It requires:

- a common operation identity or an explicit compatible scope binding;
- supported owner and publication contract versions;
- consistent authoritative-input identities and digests where those publications share an upstream state;
- complete required dependency and relationship targets;
- no duplicate owner/object identity with conflicting snapshot or digest bindings;
- no use of operational timestamps or runtime metadata as semantic compatibility evidence; and
- a canonical compatibility declaration recorded in the orchestration manifest.

Orchestration verifies compatibility claims exposed by owner publications. It cannot author a semantic compatibility transformation. If compatibility requires reinterpretation, migration, or repair, admission fails until the owning architectures define an authorized lossless rule.

## 9. Snapshot admission

Snapshot admission freezes exact owner snapshots into one operation-scoped membership set.

For every admitted snapshot, the orchestration manifest records:

- publication role;
- owner domain and owner contract;
- exact contract and publication versions;
- publication identity and digest;
- snapshot identity and digest;
- authoritative input identity and digest bindings required for compatibility; and
- canonical admission order.

The snapshot remains owned by its publisher. Admission neither copies ownership nor permits mutation. The same owner snapshot may be referenced by multiple operation contexts without becoming an orchestration-owned snapshot.

No snapshot can be added, removed, replaced, or reordered after the context is finalized. Any membership change creates a different orchestration manifest and context identity.

## 10. Compatibility declarations

A compatibility declaration states why exact admitted publications may participate in the same operation. It contains only identity and integrity metadata required to verify composition:

- source and dependent publication roles;
- exact publication and snapshot identities;
- exact owner and contract versions;
- authoritative-input binding identities and digests;
- declared dependency or relationship role; and
- the governing compatibility rule identifier and version.

It contains no copied semantic values and cannot assert equivalence not already established by owner contracts. Compatibility declarations are canonically ordered and immutable.

## 11. ResolutionContext assembly

Opportunity Orchestration assembles the `ResolutionContext` only after admission and compatibility validation succeed.

The context is:

- the closed set of exact admitted owner snapshots;
- bound to one operation identity and one orchestration manifest;
- immutable after construction;
- canonically ordered by owner domain, owner contract, contract version, snapshot identity, and snapshot digest unless a governing owner contract requires a stricter stable order;
- deterministically identified and digested from semantic assembly inputs only; and
- submitted to Governed Reference Resolution for independent validation.

The context cannot contain mutable aliases, ambient current state, an inferred owner, a provisional snapshot, or a snapshot omitted from the orchestration manifest. The resolver may reject the context but cannot expand, reorder, repair, or select its membership.

A successfully validated context grants bounded read-only resolution. It grants no semantic ownership to orchestration or consumers.

## 12. OpportunitySupportBinding assembly

Opportunity Orchestration assembles a support binding for every `EvidenceSupport` declaration emitted by the validated Opportunity Intelligence input contract.

Each binding must preserve:

- the exact `EvidenceSupport` declaration;
- exactly one admitted governed entity reference matching its declared entity type and stable ID;
- the exact admitted governed evidence references declared by that entity support;
- owner, contract version, snapshot, object, authority, and digest bindings; and
- canonical evidence-reference ordering.

Assembly uses only explicit stable identity and owner-declared relationships. It performs no semantic matching. A support declaration with zero targets, multiple eligible targets, an authority mismatch, an evidence-ID mismatch, incomplete evidence relationships, or a target outside the context fails closed.

Bindings must cover the complete `evidence_used` set exactly once. Extra bindings, duplicate support declarations, duplicate targets where uniqueness is required, omitted support, or evidence relationships not declared by the admitted owners are invalid.

The binding set is immutable and deterministic. Opportunity Intelligence Publication remains responsible for verifying the set against the exact `DecisionAnalysis` and context before publishing analytical objects.

## 13. Immutable orchestration manifest

The orchestration manifest is the authoritative record of one assembly operation. It binds:

- orchestration contract identity and version;
- operation type and stable operation identity;
- canonical admitted-publication records;
- canonical admitted-snapshot records;
- compatibility declarations;
- resolution-context identity and digest;
- canonical support bindings or their complete deterministic digest;
- required and satisfied publication roles;
- explicit governed absences allowed by the operation contract; and
- a reproducible manifest digest.

The manifest contains no copied owner semantic values. It does not become an owner publication or canonical artifact. Its identity and digest exclude runtime timestamps, process IDs, storage paths, execution duration, machine identity, and other operational metadata that does not affect assembly meaning.

Any change to operation scope, publication membership, snapshot binding, version, compatibility declaration, context membership, support binding, or governed absence changes the manifest identity or digest as required by the contract.

## 14. Deterministic orchestration

Given byte-equivalent admitted owner publications and the same orchestration-contract version and operation scope, Opportunity Orchestration produces:

- the identical admission result;
- the identical canonical snapshot membership and ordering;
- the identical compatibility declarations;
- the identical `ResolutionContext` identity, digest, and serialized representation;
- the identical `OpportunitySupportBindings` identity, ordering, and serialized representation; and
- the identical orchestration manifest identity, digest, and serialized representation.

Determinism cannot depend on current time, random values, process identity, thread scheduling, file-system order, locale, network state, mutable lookup, insertion order, or AI output. Operational execution metadata may be recorded separately but cannot affect semantic assembly identity or equality.

## 15. Context lifetime

An orchestration context is immutable, operation-scoped, and disposable after its governed execution completes. It is not canonical truth, an owner publication, a repository-wide registry, or a mutable session that accumulates later material.

Finalization closes membership. Reuse is permitted only for the same exact operation identity, manifest, admitted snapshots, compatibility declarations, and context digest. A new input publication, amended source state, revised owner version, changed binding, or different consumer operation requires a new context.

Disposal of an execution context does not authorize deletion or mutation of owner publications. The orchestration manifest contains the exact identities and digests needed to reproduce the context when the referenced owner snapshots remain governed and available. This architecture defines reproducibility requirements, not persistence mechanisms or retention policy.

## 16. Historical reproducibility

A historical operation is reproducible only from:

- the exact orchestration-contract version;
- the exact immutable orchestration manifest;
- every exact admitted owner publication and snapshot named by that manifest;
- every exact compatibility declaration;
- the exact support declarations; and
- the same deterministic assembly rules.

Reproduction must yield the same context, bindings, ordering, identities, and digests. It cannot substitute newer snapshots, reconstruct missing references from current state, or reinterpret an old contract under a new version.

If any required historical publication, snapshot, manifest, version, digest, relationship, or support declaration is unavailable or invalid, reproduction fails explicitly. Historical reproducibility never permits silent repair.

## 17. Validation

Before a context or binding set is released to Opportunity Intelligence or Opportunity Intelligence Publication, orchestration validates:

1. supported orchestration contract and operation type;
2. unique stable operation identity;
3. complete required publication roles;
4. exact owner and publication identities;
5. exact supported contract versions;
6. publication, manifest, snapshot, and object digest integrity;
7. authoritative-input snapshot compatibility;
8. unique snapshot and object identities within the declared namespaces;
9. canonical admission and snapshot ordering;
10. complete internal and required external relationship targets;
11. context membership equality with the orchestration manifest;
12. context identity and digest reproducibility;
13. exact authority classes for admitted references;
14. complete, unique `EvidenceSupport` coverage;
15. exact entity and evidence-reference binding;
16. support-binding identity, ordering, and digest reproducibility;
17. absence of copied semantics or transferred authority;
18. exclusion of operational metadata from semantic assembly identity; and
19. successful independent validation by each relevant owner publication contract and Governed Reference Resolution.

Validation is structural and deterministic. It cannot use AI, semantic similarity, source frequency, heuristic confidence, or consumer preference.

## 18. Fail-closed behaviour

Opportunity Orchestration emits no usable context, support-binding set, or successful orchestration manifest when it encounters:

- a missing required owner publication or snapshot;
- duplicate or ambiguous owner, publication, snapshot, object, or support identity;
- unsupported owner, contract, publication, or orchestration version;
- publication, object, snapshot, context, binding, or manifest digest mismatch;
- incompatible authoritative input snapshots;
- stale, mutable, provisional, or substituted state;
- an undeclared or foreign publication role;
- incomplete snapshot membership or relationship closure;
- missing, extra, duplicate, ambiguous, or mismatched support bindings;
- an evidence or provenance target outside the bounded context;
- a conflict or uncertainty state weakened through composition;
- non-deterministic ordering or identity;
- copied semantic content or attempted authority transfer; or
- inability to reproduce the declared assembly exactly.

Failure never permits partial context presented as complete, best-effort binding, omitted owner publications, fallback lookup, inferred identity, fuzzy matching, current-state substitution, silent version coercion, repaired relationships, or publication by orchestration.

A failure identifies the affected operation and stable failure class without changing any valid owner publication. Owners remain authoritative for their own valid artifacts.

## 19. Compatibility with existing architecture

### 19.1 Canonical Opportunity Publication

Canonical Opportunity Publication continues to publish only canonical field states, canonical observations, and canonical conflicts. Opportunity Orchestration may admit that immutable owner publication and its exact external relationships. It does not ask Canonical Opportunity to create a multi-owner context or support bindings.

### 19.2 Future owner publications

Future publications remain inside their semantic owner boundaries. They become eligible only through approved owner contracts and explicit operation-version compatibility. This architecture does not create publication responsibilities for any domain or pre-authorize unsupported semantics.

### 19.3 Governed Reference Resolution

Opportunity Orchestration declares and assembles the closed context. Governed Reference Resolution independently validates the context and performs exact deterministic resolution. Orchestration never resolves; the resolver never selects or expands operation membership.

### 19.4 Opportunity Intelligence

Opportunity Intelligence receives only the bounded, validated authoritative context permitted by its specification. Orchestration performs deterministic admission and binding, while Opportunity Intelligence retains sole ownership of its analytical semantics.

### 19.5 Opportunity Intelligence Owner Publication

Opportunity Intelligence Owner Publication receives the validated analysis, the exact authoritative `ResolutionContext`, and the complete deterministic `OpportunitySupportBindings`. It validates and publishes analytical relationships. It does not construct or repair its own authoritative inputs.

### 19.6 Executive Opportunity Understanding

Executive Opportunity Understanding organizes published Opportunity Intelligence objects and preserves their bound context and reference identities. It receives no orchestration authority and cannot alter upstream context membership.

### 19.7 Executive Opportunity Brief

The Executive Opportunity Brief remains a deterministic presentation adapter over Executive Opportunity Understanding. It neither accesses orchestration directly nor reconstructs owner publications, contexts, or support bindings.

## 20. Authority and ownership consistency

| Responsibility | Constitutional owner |
|---|---|
| Create semantic values | Each existing semantic owner |
| Publish owner-governed objects and snapshots | Each existing semantic owner |
| Admit exact owner publications for one opportunity operation | Opportunity Orchestration |
| Declare cross-publication compatibility for that operation | Opportunity Orchestration, using only owner-declared identities and approved compatibility rules |
| Assemble bounded `ResolutionContext` membership | Opportunity Orchestration |
| Assemble exact `OpportunitySupportBindings` | Opportunity Orchestration |
| Verify governed references and relationship closure | Governed Reference Resolution |
| Create and own opportunity analysis | Opportunity Intelligence |
| Publish analytical objects | Opportunity Intelligence |
| Organize analytical understanding | Executive Opportunity Understanding |
| Render the executive brief | Executive Opportunity Brief |
| Exercise pursuit judgment | Authorized humans |

No row transfers semantic authority to another row.

## 21. Acceptance criteria

Opportunity Orchestration is conformant only when:

1. it accepts only immutable validated owner publications permitted by the exact operation contract;
2. every required publication role is present or represented by an explicitly authorized governed absence;
3. owner identity, contract version, publication identity, snapshot identity, authority, and every required digest validate exactly;
4. admitted publications bind to one compatible opportunity and authoritative input state;
5. snapshots remain owned by their publishers and are never mutated or republished;
6. the context contains exactly the snapshots declared by the orchestration manifest;
7. the context is immutable, bounded, deterministic, operation-scoped, and independently valid under Governed Reference Resolution;
8. every Opportunity Intelligence support declaration maps to exactly one admitted governed entity reference and its exact declared evidence references;
9. support bindings provide complete one-to-one coverage with no inferred, extra, duplicate, or omitted relationships;
10. identical admitted publications and operation scope produce identical context, bindings, and orchestration manifest;
11. context and manifest identity exclude operational execution metadata;
12. historical reproduction uses exact immutable owner artifacts and never substitutes current state;
13. orchestration owns only admission, assembly, compatibility declarations, support bindings, and its operation-scoped manifest;
14. orchestration creates no semantic object, publication, snapshot, reference, evidence, provenance, analysis, understanding, presentation, recommendation, or decision;
15. unresolved conflicts, uncertainty, authority, provenance, and evidence relationships survive assembly unchanged;
16. missing, stale, incompatible, ambiguous, corrupt, incomplete, or non-deterministic input fails closed; and
17. Canonical Opportunity Publication, other owner publications, Governed Reference Resolution, Opportunity Intelligence, Opportunity Intelligence Publication, Executive Opportunity Understanding, and Executive Opportunity Brief retain their existing authority without overlap.

## 22. Rationale

Independent owner publication is necessary for single semantic ownership. Governed Reference Resolution is necessary for neutral identity and integrity verification. Neither responsibility can decide which complete set of independent publications constitutes one Opportunity Intelligence execution without crossing its boundary.

Opportunity Orchestration supplies that missing composition contract. By owning only admission and immutable assembly, it lets multiple owner publications participate in one bounded operation while preserving their identities, authority, evidence, provenance, conflicts, uncertainty, and historical bindings. Its fail-closed rules prevent convenience wiring from becoming an undeclared source of truth.

This architecture implements the conclusion of [Opportunity Orchestration Architectural Review](docs/archive/operational/OPPORTUNITY_ORCHESTRATION_ARCHITECTURAL_REVIEW.md): a distinct orchestration architecture is constitutionally required, while a new semantic domain, owner publication, resolver, intelligence layer, or runtime service is not.
