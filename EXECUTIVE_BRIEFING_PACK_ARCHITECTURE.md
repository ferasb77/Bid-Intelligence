# Executive Briefing Pack Architecture

## Document metadata

| Field | Value |
|---|---|
| Document | `EXECUTIVE_BRIEFING_PACK_ARCHITECTURE.md` |
| Title | Executive Briefing Pack Architecture |
| Authority level | Level 3 — Repository Architecture |
| Version | 1.0.0 |
| Status | Approved |
| Purpose | Govern deterministic, fail-closed composition of independently governed brief artifacts into one Executive Briefing Pack. |
| Higher authority | [The Bid Intelligence Constitution](MANIFESTO.md), [Repository Governance](GOVERNANCE.md), [Product Anti-Goals](ANTI_GOALS.md), [Architecture Doctrine](docs/architecture/ARCHITECTURE.md), and [Decision Doctrine](docs/architecture/DECISION_DOCTRINE.md) |
| Governed documents | Future Executive Briefing Pack composition contracts, validators, renderers, and conformance tests |
| Related documents | [Constitutional Completeness Review](docs/archive/operational/CONSTITUTIONAL_COMPLETENESS_REVIEW.md), [Bid Intelligence Briefing Pack Product Design](docs/archive/proposed/BID_INTELLIGENCE_BRIEFING_PACK.md), [Executive Opportunity Brief Architecture](EXECUTIVE_OPPORTUNITY_BRIEF_ARCHITECTURE.md), [Buyer Brief Architecture](BUYER_BRIEF_ARCHITECTURE.md), [Executive Opportunity Understanding Architecture](EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md), [Opportunity Orchestration Architecture](OPPORTUNITY_ORCHESTRATION_ARCHITECTURE.md), and [Governed Reference Resolution Architecture](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md) |

## Summary

The Executive Briefing Pack is an immutable presentation-composition contract. It binds exact, independently validated brief volumes into a deterministic reading sequence and proves that the selected pack edition is complete and internally compatible.

The pack owns composition metadata only. It does not copy, reinterpret, resolve, publish, or acquire the semantic content of any included volume. Each volume retains its identity, revision, authority, evidence cutoff, governed references, resolution bindings, provenance, and validation status.

This architecture closes the single responsibility gap identified by the [Constitutional Completeness Review](docs/archive/operational/CONSTITUTIONAL_COMPLETENESS_REVIEW.md). It introduces no semantic owner, intelligence layer, publication owner, resolver, operation orchestrator, persistence boundary, or runtime service.

## 1. Purpose

The Executive Briefing Pack gives an executive or proposal team one governed collection of briefing volumes for a bounded opportunity. It answers:

> Which validated brief volumes constitute this exact pack revision, in what order, and can they be presented together without changing their meaning or hiding incompleteness?

The pack reduces navigation and distribution effort. It does not improve, summarize, combine, or judge the intelligence inside a volume. It does not answer the questions owned by its member briefs.

## 2. Authority boundary

The Executive Briefing Pack has presentation-composition authority only.

It owns:

- pack composition;
- deterministic volume ordering;
- membership and completeness validation;
- cross-volume navigation;
- pack identity;
- pack revision identity;
- pack digest;
- pack metadata;
- pack revision metadata; and
- the rendering contract for presenting the same pack in supported formats.

It does not own:

- semantic values;
- Evidence or provenance;
- Canonical Truth;
- Opportunity Intelligence or Buyer Intelligence;
- Executive Opportunity Understanding;
- Executive Opportunity Brief or Buyer Brief;
- any owner publication or publication snapshot;
- governed objects or governed references;
- any `ResolutionContext`;
- analysis, interpretation, classification, uncertainty, or confidence;
- decisions, recommendations, scores, rankings, predictions, or strategy.

Pack validation proves composition. It does not revalidate or certify the truth of member content beyond requiring each member's own validation contract to pass.

## 3. Architectural position

```text
Governed Opportunity Domains                    Governed Buyer Domains
             ↓                                             ↓
Executive Opportunity Understanding                 Buyer Intelligence
             ↓                                             ↓
Executive Opportunity Brief                         Buyer Brief
             └───────────────┬─────────────────────────────┘
                             ↓
              Executive Briefing Pack Composition
                             ↓
                  Format-specific Rendering
                 Markdown / DOCX / PDF / Screen
```

The two volume paths retain separate authority. Their convergence is artifact composition, not semantic merger.

Opportunity Orchestration remains upstream and operation-scoped. Governed Reference Resolution remains the protocol used within governed consumers. Neither participates in pack assembly merely because a member volume preserves references or resolution bindings.

## 4. Inputs

The pack accepts only immutable brief artifacts that:

1. conform to an explicitly supported volume contract and version;
2. have passed their owner presentation validation;
3. expose stable volume identity and revision identity;
4. expose deterministic content or a deterministic content digest;
5. identify their opportunity and, where applicable, buyer scope through governed identity rather than labels;
6. declare their evidence cutoff or governed absence of one;
7. retain all governed references, provenance navigation, and resolution-context bindings required by their own contract; and
8. expose the metadata necessary for pack compatibility and rendering without requiring the pack to inspect upstream semantic domains.

Version 1.0.0 supports the current two-volume executive edition:

1. Volume 1 — one validated Executive Opportunity Brief governed by [Executive Opportunity Brief Architecture](EXECUTIVE_OPPORTUNITY_BRIEF_ARCHITECTURE.md) v2.x;
2. Volume 2 — one validated Buyer Brief governed by [Buyer Brief Architecture](BUYER_BRIEF_ARCHITECTURE.md) v1.x.

Future volumes require a versioned pack-contract amendment or a separately declared pack edition. A future volume cannot enter merely because a renderer can concatenate it.

Inputs are brief artifacts, not raw analyses, understandings, publications, snapshots, contexts, normalized facts, Stage D output, source files, or renderer output.

## 5. Composition responsibilities

Composition must:

- admit exactly the volume classes required by the selected pack contract;
- reject duplicate or undeclared memberships;
- preserve every admitted volume unchanged;
- place volumes in the contract-defined order;
- validate opportunity, buyer, revision, and evidence-cutoff compatibility;
- validate pack completeness;
- create deterministic cross-volume navigation using presentation-local navigation identifiers;
- retain each volume's complete validation and traceability metadata;
- compute pack and pack-revision identity from canonical composition material;
- expose a rendering-independent pack contract; and
- fail closed when compatibility, identity, completeness, or deterministic reproduction cannot be proven.

Composition may add only fixed pack-level elements: cover metadata, table of contents, volume boundaries, navigation entries, pack validation state, and format-independent distribution metadata authorized by this contract.

Composition cannot edit a volume, select content from it, collapse its coverage, add semantic transitions, reconcile differences, or create a cross-volume conclusion.

## 6. Identity preservation

Every member volume retains exactly its own:

- volume type and contract version;
- artifact identity;
- revision identity;
- semantic and presentation digests supplied by its contract;
- opportunity and buyer bindings;
- evidence cutoff;
- governed reference identities;
- owner, publication, object, and snapshot identities;
- resolution-context bindings;
- authority, confidence, uncertainty, and provenance; and
- internal ordering and coverage state.

The pack stores or binds these values without rewriting them. A pack-local volume number or navigation anchor is a presentation locator only. It cannot replace a volume identity or governed reference.

If byte embedding is used, the embedded bytes must match the member's declared artifact digest. If a member is referenced rather than embedded, the reference must be immutable and digest-bound. Mutable paths and URLs do not establish membership.

## 7. Pack identity and revision

### 7.1 Pack identity

Pack identity identifies the enduring governed collection for one exact opportunity scope and one pack contract family. It is derived deterministically from:

- pack contract name and major version;
- governed opportunity identity;
- governed buyer identity or an explicit governed absence permitted by the pack contract; and
- pack edition identity.

Pack identity excludes execution time, output filename, storage location, renderer, file format, pagination, generation host, runtime environment, and operator.

### 7.2 Pack revision identity

Pack revision identity identifies one immutable composition of the pack. It is derived from:

- pack identity;
- exact pack contract version;
- canonical ordered membership manifest;
- each member's exact contract version, artifact identity, revision identity, and digest;
- compatibility declarations required by this architecture;
- evidence-cutoff manifest;
- cross-volume navigation manifest; and
- deterministic pack metadata that affects governed presentation meaning.

Any membership, member revision, member digest, compatibility declaration, governed cutoff, order, or meaning-bearing pack metadata change creates a new pack revision identity. Re-rendering the same revision does not.

### 7.3 Pack digest

The pack digest is a cryptographic digest of the canonical rendering-independent pack revision representation. It proves the composition manifest and pack metadata. It does not replace or recalculate member digests.

Operational metadata such as build timestamp, render duration, file path, application version, or conversion diagnostics remains available for audit but cannot influence pack identity, revision identity, digest, equality, or ordering.

## 8. Revision compatibility

Member revisions are compatible only when their owner-declared scope bindings establish that they concern the same governed opportunity and applicable buyer. Display titles, solicitation text, filenames, adjacent generation times, or user selection do not prove compatibility.

Compatibility rules are deterministic:

- the Executive Opportunity Brief must bind the pack's exact opportunity identity;
- the Buyer Brief must bind the same opportunity identity for context and the buyer identity declared for that opportunity;
- each volume contract and version must be explicitly supported by the pack contract;
- each member revision must validate independently;
- no member may be superseded within the pack by a second revision of the same volume slot;
- cross-volume identifiers must agree exactly where the contracts declare the same governed identity; and
- a known identity disagreement is incompatible and cannot be presented as a warning-only pack.

The pack does not choose a newest, best, or apparently matching revision. Selection occurs before composition under accountable external workflow. The pack only validates the supplied exact revisions.

## 9. Evidence cutoff compatibility

Each member's evidence cutoff remains owned and defined by that member contract. The pack preserves a manifest of all member cutoffs.

Equal cutoffs are not required because opportunity and buyer corpora may be acquired and validated on different schedules. Different cutoffs are compatible only when:

- every cutoff is explicit and valid under its member contract;
- the pack exposes the differences without harmonizing them;
- no member claims reliance on another volume state later than the referenced member revision;
- any owner-declared dependency between volumes binds an exact compatible revision; and
- the selected pack contract permits independent cutoffs for those volume classes.

An absent cutoff is compatible only when the member contract explicitly governs that absence and the pack contract permits it. The pack cannot invent a common cutoff, promote the latest date to a pack-wide evidence date, or imply simultaneous knowledge.

The pack may expose a fixed label such as “Volume evidence cutoffs” followed by exact member values. That is presentation metadata, not a new evidence assertion.

## 10. Cross-volume reference preservation

A member volume may contain governed references or presentation links to another governed artifact. Composition preserves those references exactly.

The pack may create local navigation from one included volume boundary to another, but such navigation:

- identifies only a location in this pack revision;
- records the target member's exact artifact and revision identity;
- does not replace a governed reference;
- does not alter relationship kind, direction, role, owner, version, snapshot, or digest;
- does not imply a semantic relationship absent from the member contracts; and
- fails if the referenced included member identity does not match exactly.

The pack does not resolve governed references. A member that requires resolved semantics must already be valid under its own bound context before admission. Pack assembly cannot extend, merge, rebuild, or substitute `ResolutionContext` values.

External references remain external and unchanged. The pack must not claim complete navigation for a reference whose required target is unavailable.

## 11. Pack membership and completeness

The membership manifest is an immutable canonically ordered list containing, for each volume:

- volume slot;
- volume class;
- volume contract and version;
- artifact identity;
- revision identity;
- artifact digest;
- governed opportunity and buyer bindings required for compatibility;
- evidence cutoff state; and
- validation-state identity or digest required by the member contract.

Pack completeness means only that:

1. every required slot for the selected pack contract and edition is occupied exactly once;
2. no unsupported or duplicate member is present;
3. every member validates independently;
4. all required compatibility checks pass;
5. all required cross-volume navigation closes;
6. the membership and cutoff manifests are complete; and
7. every admitted member can be reproduced or verified from its exact identity and digest.

Pack completeness does not assert that Evidence is complete, intelligence is exhaustive, unknowns are resolved, or management is ready to decide. Member limitations, conflicts, unknowns, and coverage states remain visible.

A partial collection may be retained operationally, but it cannot be identified, rendered, or distributed as a complete Executive Briefing Pack under this contract.

## 12. Deterministic ordering

The pack contract defines volume order. Version 1.0.0 orders:

1. Executive Opportunity Brief;
2. Buyer Brief.

Required front matter precedes the volumes in a fixed order: pack identity metadata, revision metadata, volume evidence cutoffs, validation state, and table of contents. Optional cosmetic renderer elements do not enter the semantic composition order.

The pack preserves internal member ordering exactly. It does not reorder sections or content across volumes by importance, confidence, date, page fit, length, or inferred relevance.

Set-like metadata uses explicit canonical sort keys ending in stable identity. Identical validated inputs and the same pack contract produce identical membership, navigation, canonical serialization, revision identity, and pack digest.

## 13. Rendering independence

The Executive Briefing Pack contract is a rendering-independent immutable composition. Markdown, DOCX, PDF, HTML, screen views, and future formats are renderings of that composition. They are not constitutional artifacts and do not own the pack.

A renderer may control typography, page geometry, headers, footers, page numbers, bookmarks, accessible navigation, and equivalent format mechanics. It may not:

- change membership or volume order;
- edit or summarize member content;
- suppress member coverage, limitations, conflicts, unknowns, or provenance paths;
- replace identities or references with presentation aliases alone;
- create new semantic cross-volume statements;
- treat pagination or layout as importance; or
- report a partial render as a complete pack.

Each rendering binds the exact pack revision identity and pack digest and declares its renderer and format version separately. Format-specific operational metadata does not alter pack identity.

Equivalent rendering means preservation of composition, member content, identity, navigation, ordering, and completeness, not necessarily byte equivalence across different formats. Repeated rendering under the same deterministic format contract must reproduce the same semantic presentation; container metadata that is unavoidably operational remains outside semantic equality.

## 14. Validation

Composition validation must establish:

- supported pack contract, edition, and version;
- structurally valid pack, revision, and member identities;
- exact required membership;
- unique volume slots, identities, revisions, and membership entries;
- member contract and version support;
- successful independent validation of every member;
- exact member digest verification;
- opportunity and buyer identity compatibility;
- evidence-cutoff compatibility and complete disclosure;
- immutable preservation of member metadata and governed references;
- complete cross-volume navigation closure;
- canonical ordering and serialization;
- reproducible pack identity, revision identity, and digest;
- absence of semantic content owned by the pack; and
- absence of recommendations, rankings, scores, predictions, strategies, or decisions created by composition.

Validation cannot repair a member, invoke an analyst, query Canonical Truth, retrieve Evidence, resolve a governed reference, rebuild a context, choose a revision, or infer compatibility from prose.

## 15. Fail-closed behaviour

Pack construction fails closed for:

- a missing required volume;
- an extra or unsupported volume;
- duplicate volume class, slot, identity, or revision;
- unsupported member or pack contract version;
- invalid or mutable member artifact;
- member digest mismatch;
- opportunity or buyer identity mismatch;
- missing, malformed, incompatible, or undisclosed evidence cutoff;
- incompatible member revisions;
- broken cross-volume navigation;
- absent member validation proof required by its contract;
- inability to preserve a member's references, provenance, coverage, or identity;
- non-deterministic membership or ordering;
- pack identity, revision identity, or digest mismatch;
- semantic content created or altered by composition; or
- inability to produce a complete rendering without omission.

Failure is explicit and identifies the affected volume slot and controlled reason. It cannot trigger fallback to an earlier brief, legacy Stage D content, current mutable state, similarly named artifact, evaluation output, or manual repair.

A valid member remains valid when pack construction fails. Pack failure neither mutates nor invalidates its members.

## 16. Compatibility analysis

### Executive Opportunity Brief

The pack admits one already-valid Executive Opportunity Brief and preserves its presentation identity, understanding binding, executive-index order, coverage, references, and provenance visibility. It neither accesses Executive Opportunity Understanding directly nor resolves the brief's references.

### Buyer Brief

The pack admits one already-valid Buyer Brief and preserves its Buyer Intelligence, Canonical Buyer, Evidence register, opportunity-context binding, cutoff, ordering, and limitations according to [Buyer Brief Architecture](BUYER_BRIEF_ARCHITECTURE.md). It does not allow buyer interpretation to alter opportunity content or opportunity content to alter buyer analysis.

### Executive Opportunity Understanding

Executive Opportunity Understanding remains the organizational source consumed by the Executive Opportunity Brief. The pack does not consume, reorganize, duplicate, or acquire authority over it. Its identity and coverage remain visible through the admitted brief's bindings.

### Opportunity Orchestration

Opportunity Orchestration assembles owner publications, a bounded `ResolutionContext`, and support bindings for a governed operation. Pack composition consumes none of those orchestration inputs directly and does not extend the operation boundary. Any orchestration identity retained by a member remains opaque and unchanged.

### Governed Reference Resolution

Governed Reference Resolution verifies owner-declared semantic references. Pack composition performs no resolution. It preserves member reference and context identities so authorized navigation remains possible under the member contracts. A pack cannot cure a resolution failure or admit a member that failed its own closure requirements.

### Authority conclusion

There is no overlap. Member briefs own their separate presentation responsibilities. The pack owns only their deterministic composition. Renderers own format mechanics. Upstream domains retain all semantic authority. Humans retain all decisions.

## 17. Acceptance criteria

This architecture is satisfied only when:

1. a pack accepts only immutable, independently validated, supported brief artifacts;
2. the selected pack edition's required membership is exact and complete;
3. every member retains its identity, revision, digest, authority, ordering, evidence cutoff, references, provenance, coverage, and limitations unchanged;
4. opportunity and buyer bindings prove compatibility without filename or prose inference;
5. differing evidence cutoffs remain explicit and are accepted only under deterministic compatibility rules;
6. cross-volume navigation preserves governed references and never creates semantic relationships;
7. identical inputs produce identical membership, order, canonical representation, pack identity, revision identity, and digest;
8. operational execution and rendering metadata cannot affect semantic composition identity;
9. Markdown, DOCX, PDF, and other formats render the same pack contract without becoming constitutional artifacts;
10. missing, duplicate, incompatible, stale, altered, unsupported, or incomplete content fails closed;
11. pack failure does not mutate or invalidate a valid member;
12. the pack performs no retrieval, resolution, analysis, understanding, publication, orchestration, semantic creation, summarization, ranking, recommendation, or decision; and
13. a complete pack never conceals that one of its members contains conflicts, unknowns, assumptions, alternatives, evidence gaps, or limitations.

## Architectural definition

The Executive Briefing Pack is the deterministic, immutable, fail-closed composition of independently governed presentation artifacts for one exact opportunity scope.

It preserves rather than merges. It orders rather than ranks. It validates membership rather than semantic truth. It provides navigation rather than resolution. It binds exact revisions rather than selecting them. Its renderings make the same pack usable in different formats without changing the constitutional artifact or any member's authority.
