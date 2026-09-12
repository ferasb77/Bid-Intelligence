# Opportunity Intelligence Publication Architectural Review

## Document metadata

| Field | Value |
|---|---|
| Document | `OPPORTUNITY_INTELLIGENCE_PUBLICATION_ARCHITECTURAL_REVIEW.md` |
| Title | Opportunity Intelligence Publication Architectural Review |
| Authority Level | Level 5 — Architectural Review Record |
| Version | 1.0.0 |
| Status | Complete |
| Purpose | Determine whether Opportunity Intelligence has an architecturally complete responsibility for publishing its owned analytical objects for governed downstream resolution. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md), [`AGENT.md`](AGENT.md), [`GOVERNANCE.md`](GOVERNANCE.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md), [`docs/architecture/DOMAIN_MODEL.md`](docs/architecture/DOMAIN_MODEL.md), [`docs/architecture/DESIGN_PRINCIPLES.md`](docs/architecture/DESIGN_PRINCIPLES.md), [`docs/architecture/DECISION_DOCTRINE.md`](docs/architecture/DECISION_DOCTRINE.md), [`DECISION_INTELLIGENCE_ARCHITECTURE_PHASE1.md`](DECISION_INTELLIGENCE_ARCHITECTURE_PHASE1.md), [`DECISION_ANALYST_ARCHITECTURE_PHASE2.md`](DECISION_ANALYST_ARCHITECTURE_PHASE2.md), [`OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md`](OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md), [`EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md`](EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md), and [`GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md`](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md) |
| Governed Documents | None. This review records a finding and does not amend architecture. |
| Related Documents | [`EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURAL_VALIDATION.md`](EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURAL_VALIDATION.md) |

## Executive Summary

Opportunity Intelligence has a defined production responsibility and a defined immutable output boundary: it consumes a bounded authoritative opportunity context, produces typed analytical content, and returns one validated Phase 2 `DecisionAnalysis`. The governing documents therefore establish analytical ownership and contract production.

They do not, however, establish publication in the stronger repository-wide sense required by Governed Reference Resolution. The Opportunity Intelligence specification does not require its owned objects to be exposed through an owner-declared semantic representation bound to an immutable snapshot identity, exact owner contract version, reproducible snapshot and object digests, relationship manifests, canonical serialization, historical retention, and deterministic compatibility rules. A valid `DecisionAnalysis` is consequently an immutable analytical aggregate, but the architecture does not state that each cross-domain-resolvable Opportunity Intelligence object is published under the complete owner obligations of the resolution protocol.

This is a genuine architectural omission rather than an incorrect implementation sequence. Executive Opportunity Understanding is required to reference Opportunity Intelligence objects without owning their semantics. Governed Reference Resolution can verify and resolve only owner-published objects. Neither layer has authority to manufacture the missing owner declaration after analysis. Implementation order cannot supply an authority boundary that the owning architecture has not defined.

Publication is a distinct responsibility, but it should remain an owner responsibility of Opportunity Intelligence rather than become a separate semantic domain. It answers: **Which exact, immutable Opportunity Intelligence findings existed for this governed analysis and opportunity snapshot, and how may downstream consumers resolve them without changing their meaning or ownership?** Assigning that responsibility to another domain would duplicate or transfer analytical authority.

The recommendation is for a future explicit architectural amendment to the Opportunity Intelligence governing contract before resolver-based downstream integration proceeds. That amendment need only establish Opportunity Intelligence's owner-publication responsibility under the existing Governed Reference Resolution protocol. This review does not design that amendment or authorize implementation.

## Validation Method

This review examined architecture and doctrine only. Production code, prompts, tests, persistence, schemas, and generated artifacts were excluded.

The review applied four tests:

1. **Production test:** identify what Opportunity Intelligence is required to produce and validate.
2. **Ownership test:** identify which domain owns every analytical semantic class.
3. **Publication test:** compare the Opportunity Intelligence contract with the mandatory owner responsibilities in Governed Reference Resolution.
4. **Consumption test:** trace whether Executive Opportunity Understanding and later presentation consumers can obtain exact semantics without copying authority, private lookup, inference, or fallback.

The documents were interpreted according to the repository authority hierarchy. The narrower Level 3 Governed Reference Resolution architecture governs cross-domain reference publication and resolution. The Opportunity Intelligence specification governs analyst semantics. Their requirements are compatible, but the latter does not yet declare how its objects participate in the former.

## Findings

### 1. Does Opportunity Intelligence currently publish immutable governed objects?

**Not in the complete Governed Reference Resolution sense.**

The existing architecture does require:

- immutable analyst identity, semantic version, domain, and declared capabilities;
- one immutable, validated `DecisionAnalysis` output;
- stable analysis, statement, hypothesis, assumption, limitation, unknown, and question identities where defined by the analyst contracts;
- typed separation of computed facts, inference, hypotheses, assumptions, limitations, unknowns, evidence, and management questions;
- closed evidence references;
- deterministic computation and canonical ordering requirements; and
- preservation of upstream ownership and provenance.

These requirements make `DecisionAnalysis` a governed analytical output. They establish production and validation, and they permit future moderation to consume complete analyses.

They do not establish the full publication boundary required for repository-wide resolution. The Opportunity Intelligence architecture does not explicitly declare:

- a stable owner namespace covering every resolvable analytical object class;
- an owner-authored, consumer-safe semantic representation for each class;
- an immutable Opportunity Intelligence snapshot identity and manifest;
- reproducible snapshot and object digests;
- exact reference binding to the analysis and authoritative input snapshot;
- complete relationship roles and closure rules for evidence, assumptions, alternatives, gaps, and provenance;
- canonical serialization of the published snapshot and its objects;
- historical snapshot retention; or
- compatibility rules for resolving supported historical owner-contract versions.

Returning an immutable aggregate is therefore not equivalent to publishing resolver-compatible owner objects.

### 2. Is publication already implied elsewhere?

**Yes, but implication is insufficient for a governed authority transition.**

The Decision Analyst lifecycle says that an analyst publishes immutable identity and returns an immutable `DecisionAnalysis`. The Opportunity Intelligence specification requires stable IDs, closed evidence, and future consumption. Executive Opportunity Understanding requires stable references to all admitted analytical objects and a bounded resolution context. Governed Reference Resolution expressly states that Opportunity Intelligence owns its computed facts, observations, interpretations, hypotheses, assumptions, unknowns, limitations, and management questions.

Together, these documents make cross-domain publication necessary. They do not make its contract complete. Governed Reference Resolution also states that when an existing domain participates in cross-domain resolution, a governing contract must declare how its stable references bind to immutable snapshots and which owner-authored semantic representation satisfies consumer rights. That declaration is absent from the Opportunity Intelligence architecture.

### 3. Is publication an implementation concern or an architectural concern?

**It is an architectural concern.**

Publication determines:

- which domain owns the published meaning;
- which objects are stable and externally referenceable;
- what semantic fields a governed consumer is entitled to receive;
- which version and immutable snapshot govern historical meaning;
- which evidence and provenance relationships must close;
- how compatibility affects meaning; and
- when downstream use must fail closed.

Those are authority and contract decisions. Storage, indexing, serialization mechanics, or resolver calls may later implement them, but implementation cannot decide them without silently creating architecture.

### 4. Is publication a distinct repository responsibility?

**Yes.** Production, publication, resolution, organization, and presentation are separate responsibilities:

| Responsibility | Governing owner | Architectural function |
|---|---|---|
| Produce analysis | Opportunity Intelligence | Create and validate typed analytical objects from admitted authoritative inputs. |
| Publish owned analysis | Opportunity Intelligence | Declare which immutable analytical objects and relationships are resolvable under an exact owner contract and snapshot. |
| Resolve references | Governed Reference Resolution | Verify identity, version, digest, authority, semantic sufficiency, and relationship closure. |
| Organize understanding | Executive Opportunity Understanding | Assign existing governed objects to deterministic executive structures and prove coverage. |
| Present | Briefs, profiles, dashboards, and workspaces | Render resolved governed meaning without creating or changing it. |

Publication is distinct because a produced object can be internally valid without yet being addressable under a cross-domain immutable snapshot. Resolution cannot bridge that distinction on the owner's behalf.

Publication does not warrant a separate intelligence or canonical domain. It is the outward-facing contract duty of the domain that already owns the analytical objects. The generic cross-domain verification mechanism remains governed by Governed Reference Resolution.

### 5. What organizational question would publication answer?

Publication would answer:

> Which exact, immutable Opportunity Intelligence findings existed for this governed analysis and opportunity snapshot, and how may an authorized downstream consumer resolve them without changing their meaning or ownership?

This is an information-governance question. It does not answer what the opportunity means for a management decision, what should be emphasized, or what action should be taken.

### 6. Would publication violate existing authority boundaries?

**No, provided publication remains declaration rather than transformation.**

Opportunity Intelligence already owns its computations and typed analysis. Publishing those exact objects under immutable bindings would make existing ownership inspectable; it would not enlarge analytical authority. Canonical Opportunity would continue to own authoritative facts and conflict states. Evidence and provenance would remain in their owning stores. Executive Opportunity Understanding would continue to own organization and coverage only. Governed Reference Resolution would continue to have verification authority only. Presentation consumers would remain read-only.

Publication would violate the architecture if it copied canonical facts as Opportunity Intelligence-owned truth, rewrote evidence, resolved upstream conflicts, generated consumer-specific variants, or allowed a publication record to become an alternative analytical source. None of those acts is required by the identified responsibility.

### 7. Would publication preserve the governing principles?

| Principle | Architectural effect of owner publication |
|---|---|
| Canonical Truth | Canonical facts remain owned by canonical domains and are referenced rather than re-owned by Opportunity Intelligence. |
| Evidence before inference | Published analytical objects retain exact support relationships, assumptions, alternatives, gaps, and provenance closure. |
| Determinism | Exact identity, contract version, snapshot, digest, ordering, and canonical serialization bind the published meaning. |
| Immutable ownership | Opportunity Intelligence publishes only objects it owns; consumers receive read-only semantics and never ownership. |
| Governed Reference Resolution | The owner supplies the declarations and immutable objects that the repository resolver is authorized to verify. |
| Human judgment | Publication exposes analysis and uncertainty without ranking, recommendation, or decision authority. |
| Fail-closed validation | Missing identity, semantic content, compatibility, digest, or relationship closure prevents governed consumption. |

## Existing Responsibilities

The approved Opportunity Intelligence architecture already assigns the following responsibilities:

1. Assemble an opportunity-scoped view of admitted, validated authoritative entities.
2. Preserve canonical precedence and unresolved conflict state.
3. Compute reproducible structural measures.
4. Produce typed analytical observations, inferences, hypotheses, assumptions, limitations, unknowns, evidence gaps, and management questions.
5. Keep facts, computation, reasoning, alternatives, recommendations, and decisions structurally separate.
6. Reuse stable upstream evidence and entity IDs without copying provenance.
7. Close every analytical evidence link within the analysis-level `evidence_used` collection.
8. Validate analyst identity, capability, evidence closure, category separation, uncertainty, and prohibited outputs.
9. Return one immutable, versioned `DecisionAnalysis` with stable identity and deterministic computed content and ordering.
10. Preserve human judgment by excluding pursuit recommendations and decisions.

These responsibilities establish the semantic content that Opportunity Intelligence owns. They do not define the complete cross-domain publication of that content.

## Missing Responsibilities

One responsibility is missing: **owner publication of Opportunity Intelligence analytical objects for governed cross-domain resolution**.

It is required because Executive Opportunity Understanding must organize references to Opportunity Intelligence-owned semantics, and presentation consumers must obtain those semantics through Governed Reference Resolution. Stable IDs alone do not give the resolver an immutable owner snapshot, exact versions and digests, a semantic representation, or complete relationship closure.

Existing neighboring domains cannot own this responsibility:

- **Canonical Opportunity** cannot publish analytical objects as its own because that would promote inference into canonical truth.
- **Evidence and provenance domains** cannot own analytical meaning because evidence supports analysis but is not analysis.
- **Governed Reference Resolution** cannot create the objects it verifies; it has verification authority only.
- **Executive Opportunity Understanding** cannot bind or author upstream analytical semantics because it has organizational authority only.
- **Briefs, profiles, dashboards, and workspaces** cannot publish upstream meaning because presentation and coordination consumers do not own intelligence.
- **A separate publication domain** would introduce an unnecessary second owner or a transformation boundary between Opportunity Intelligence and its own objects.

The missing responsibility belongs with Opportunity Intelligence as the producing and owning domain. This conclusion identifies responsibility only; it does not define a new contract, object model, lifecycle, or implementation.

## Constitutional Analysis

The omission leaves a gap between two otherwise compatible constitutional requirements:

1. intelligence must remain typed, attributable, immutable, and distinct from canonical fact; and
2. downstream consumers must resolve exact owner-authored meaning without copying authority or reconstructing semantics.

Without an explicit owner-publication boundary, one of four prohibited outcomes becomes likely: a consumer accesses Opportunity Intelligence through a private lookup; Executive Opportunity Understanding copies semantic values and becomes a second source of truth; the resolver infers bindings the owner never declared; or downstream rendering fails because identity exists without resolvable meaning.

An explicit Opportunity Intelligence publication responsibility would close this constitutional gap by making the existing analytical authority safely composable. It would connect evidence-governed analysis to read-only downstream use while preserving the repository's separation among fact, inference, organization, presentation, and human decision.

No conflict exists among the reviewed authorities. The documents agree that Opportunity Intelligence owns analytical meaning, Executive Opportunity Understanding owns organization, Governed Reference Resolution owns verification, and presentations own rendering. The omission concerns the unassigned transition from owned analytical output to resolver-addressable immutable publication.

## Recommendation

Record a future architectural amendment in the governing Opportunity Intelligence contract that explicitly assigns owner publication of its cross-domain-resolvable analytical objects in conformance with [`GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md`](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md).

The amendment is required before Executive Opportunity Understanding or another governed downstream consumer can rely solely on repository-wide resolution of Opportunity Intelligence semantics. It should close only the publication responsibility identified here. It should not create a new semantic domain, transfer ownership, duplicate canonical truth, alter analytical content, add presentation behavior, or authorize implementation by itself.

Until that governing declaration exists, the correct architectural conclusion is:

- Opportunity Intelligence can validly produce an immutable `DecisionAnalysis`;
- that output is not yet architecturally complete as a Governed Reference Resolution publication;
- Executive Opportunity Understanding cannot supply the missing owner declaration;
- Governed Reference Resolution cannot infer or manufacture it; and
- resolver-dependent downstream integration should remain blocked rather than use a private adapter or ownership workaround.

This review makes no architectural amendment and proposes no implementation.
