# Executive Opportunity Understanding Architectural Validation

## Document metadata

| Field | Value |
|---|---|
| Document | `EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURAL_VALIDATION.md` |
| Title | Executive Opportunity Understanding Architectural Validation |
| Authority Level | Level 5 — Architectural Review Record |
| Version | 1.0.0 |
| Status | Complete |
| Purpose | Determine whether the approved Executive Opportunity Understanding architecture is sufficient as the sole canonical upstream contract for governed presentation consumers. |
| Higher Authority | [`EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md`](../../../EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md) |
| Governed Documents | None |
| Related Documents | [`EXECUTIVE_OPPORTUNITY_BRIEF_ARCHITECTURE.md`](../../../EXECUTIVE_OPPORTUNITY_BRIEF_ARCHITECTURE.md), [`STAGE_D_ARCHITECTURAL_REVIEW.md`](STAGE_D_ARCHITECTURAL_REVIEW.md) |

## Executive Summary

The approved architecture is **not sufficient to guarantee that Executive Opportunity Understanding can serve as a self-contained sole upstream contract for every governed presentation consumer** when those consumers are prohibited from accessing an external resolver, an owning domain, or a secondary projection.

The architecture fully defines a deterministic organizational contract: it establishes identity, authority separation, section assignment, ordering, a complete typed detail register, coverage, validation, and consumer boundaries. It also states that the Executive Opportunity Brief and other presentation consumers consume this contract and that the contract can be rendered without Stage D or a model call.

However, the architecture defines substantive entries primarily as references. Exact display labels or values are optional: a governed object reference *may* carry them. Evidence content remains in the owning evidence store. The contract is expressly not a replacement for canonical opportunity data, normalized facts, provenance stores, or Opportunity Intelligence. Several detail-register requirements say that semantic properties remain attached through the upstream object without requiring those properties to be present in the understanding contract itself.

Those choices support a reference-based architecture in which a consumer can resolve governed objects from their owning stores. They do not support the stronger requirement evaluated here: deterministic reconstruction of all presentation content from the serialized Executive Opportunity Understanding alone.

The architecture therefore requires narrowly bounded amendments if Executive Opportunity Understanding is to be the sole, self-sufficient presentation input. No amendment is required if “consume this contract” is intended to include deterministic reference resolution against the immutable authoritative snapshot and owning provenance stores.

## Validation Method

This review examined only `EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md`. It did not inspect implementation, prompts, tests, evaluation artifacts, or runtime behavior.

The architecture was tested against the following proposition:

> Given only one valid serialized Executive Opportunity Understanding, can any governed presentation consumer reproduce all permitted semantic content, evidence relationships, provenance navigation, uncertainty, and ordering deterministically, without consulting Opportunity Intelligence, Stage D, an external resolver, or another projection?

Each architectural guarantee was assessed for:

1. mandatory presence in the canonical contract;
2. sufficient semantic content for presentation;
3. deterministic ordering and identity;
4. evidence and provenance closure;
5. independence from unavailable upstream objects;
6. explicit fail-closed behavior when required content is absent.

The review distinguishes:

- **proven sufficiency** — the architecture explicitly guarantees the capability;
- **architectural omission** — the output contract does not normatively guarantee information required by the stated proposition;
- **intentional external dependency** — the architecture explicitly leaves information with an owning domain or store;
- **implementation issue** — the architecture contains an adequate guarantee and only conformance could be deficient. No implementation was reviewed, so no implementation defect is asserted here.

## Architectural Findings

### Finding 1: The architecture guarantees organization, identity, and coverage

The contract envelope, executive index, detail register, coverage ledger, and validation record provide a strong deterministic organizational boundary. The architecture fixes thirteen executive sections, defines inclusion and ordering rules, requires bijective coverage over admitted objects, preserves authority classes, and fails closed on missing references, incomplete coverage, invalid versions, or semantic flattening.

This is sufficient to determine **which governed objects exist, how they are classified, where they belong, how they are ordered, and whether admitted input coverage is complete**.

Classification: **proven sufficiency**.

### Finding 2: Canonical semantic values are not mandatory contract content

The governed object reference requires identity, class, owner, version, authority, support references, status, confidence, section assignment, ordering, and a detail pointer. It does not require the authoritative value, exact statement text, display label, normalized value, unit, precision, scope, or other semantic payload of the referenced object.

The architecture says a reference *may* carry an exact display label or value already provided by its owning contract. “May” does not guarantee availability. Consequently, the contract does not guarantee that a consumer can render an opportunity title, buyer identity, workstream, deadline, contract term, procurement model, deliverable, clause, observation, interpretation, question, unknown, conflict, or limitation as human-readable content from the understanding alone.

Classification: **architectural omission for sole-contract rendering**. It is not merely an implementation issue because the field is optional at the architectural level.

### Finding 3: The authoritative snapshot is an input but not guaranteed as retrievable output

Version 1 accepts a validated `DecisionAnalysis` and an immutable authoritative opportunity snapshot. The output envelope contains the snapshot digest, while substantive authoritative facts are represented by upstream references. The architecture does not require the immutable snapshot itself, or a complete consumer-accessible semantic representation of it, to be included in the output contract.

The digest proves binding and identity but cannot reconstruct content. The executive index and detail pointers navigate the understanding contract; they do not, by themselves, resolve authoritative domain objects that are absent from it.

Classification: **architectural omission for sole-contract rendering** and **intentional external dependency** under the current reference-based design.

### Finding 4: Evidence relationships are identifiable but not self-contained

The reference contract includes `evidence_support_ids` where an upstream contract permits them. Validation requires evidence references to close against the owning evidence registry. The architecture also states that evidence content remains in the owning evidence store and is referenced rather than copied.

This adequately preserves evidence identity and prevents the understanding layer from becoming an evidence owner. It does not guarantee that a consumer possessing only the understanding can determine the complete relationship shape, source locator, quoted or extracted content, occurrence provenance, or other citation information needed for evidence presentation and drill-down.

Classification: **intentional external dependency**. It becomes an **architectural gap** only under the stronger requirement that no external resolver or owning evidence store may be used.

### Finding 5: Provenance remains outside the canonical output

The architecture identifies provenance stores as authoritative domains and expressly says Executive Opportunity Understanding is not their replacement. It requires preserved references and closed evidence links, but the canonical envelope and governed-reference definition do not guarantee inclusion of complete provenance records or a self-contained route capable of resolving them without another store.

Classification: **intentionally outside the contract**. This is incompatible with self-contained provenance rendering when external resolution is forbidden.

### Finding 6: Computed values and computation semantics depend on upstream objects

The computed-facts section says formula identity, denominator, unit, input references, and null behavior remain attached through the upstream object. These properties are not mandatory fields of the governed object reference. The architecture therefore preserves their authority and identity but does not guarantee their availability to a consumer that cannot resolve the upstream computed-fact object.

Classification: **architectural omission for sole-contract rendering** and **intentional upstream dependency**.

### Finding 7: Executive observations and interpretations are not guaranteed to carry their wording

The authority boundary requires preservation of the original wording of each object, and the detail-register descriptions require reasoning gaps, limitations, confidence, evidence support, and alternatives to remain visible. Yet the canonical reference fields do not require statement wording or complete nested reasoning content. The optional display-value provision is insufficient to make this content mandatory.

This creates a normative ambiguity: preservation is required, but consumer-accessible materialization inside the output contract is not.

Classification: **architectural omission**. If a conforming contract can preserve wording solely by reference, then an external resolver is architecturally required; if the understanding must stand alone, exact wording must be mandatory within its consumer-accessible content.

### Finding 8: Conflict, unknown, assumption, alternative, question, and limitation detail is not fully specified in the canonical reference

The detail-register sections make strong semantic promises: conflicts retain affected fields, observations, scopes, alternatives, and resolution state; unknowns retain type, affected objects, and gap references; competing sets retain all alternatives; and questions and limitations remain explicit. The governed-reference schema does not define mandatory fields for these details.

The architecture therefore guarantees their classification, admission, identity, and coverage, but not a self-contained representation sufficient to render their complete meaning.

Classification: **architectural omission for sole-contract rendering**. This could be satisfied by upstream resolution under the current design, but upstream resolution is excluded by the question under review.

### Finding 9: Section membership does not provide presentation labels or field semantics

The executive index deterministically identifies objects assigned to sections. It does not require stable human-readable labels for individual object types or define how a consumer distinguishes, for example, buyer identity from solicitation title within `OPPORTUNITY_IDENTITY`, or commencement date from submission deadline within `TIMELINE`, unless that information is available from the referenced upstream object.

Deterministic templates are allowed, but a template cannot select the correct label or value without deterministic semantic fields.

Classification: **architectural omission for independent presentation**. Structural section keys are sufficient for navigation but not for complete human-readable reconstruction.

### Finding 10: Rendering without Stage D is guaranteed; rendering without all upstream stores is not

Acceptance criterion 11 explicitly requires that the contract can be rendered without Stage D or a model call. The consumer section says the Executive Opportunity Brief presents the understanding contract. Neither statement explicitly requires rendering from the understanding contract **alone**.

Elsewhere, the architecture requires reference resolution and retains evidence and provenance in owning stores. Read together, the current architecture supports deterministic rendering without Stage D while still relying on governed upstream reference resolution.

Classification: **proven sufficiency for Stage D independence**; **no guarantee of resolver independence**.

## Proven Sufficiencies

The approved architecture explicitly and adequately guarantees:

- one immutable, versioned organizational contract;
- deterministic identity and canonical equality semantics;
- fixed executive section taxonomy and section ordering;
- deterministic inclusion and ordering independent of model preference or document position;
- separation of authoritative facts, computed facts, observations, interpretations, alternatives, assumptions, unknowns, conflicts, considerations, questions, and limitations;
- complete admitted-object registration and bijective coverage;
- stable upstream object identities and owning-domain attribution;
- preservation of authority, confidence, support status, and conflict state;
- rejection of recommendations, scores, rankings, predictions, and decisions;
- fail-closed validation of identity, version, reference closure, coverage, and semantic boundaries;
- rendering without Stage D or a model call;
- consumer independence from presentation format;
- immutable historical contracts and explicit compatibility adapters;
- continued separation of Opportunity Intelligence and Buyer Intelligence.

These guarantees make Executive Opportunity Understanding a valid canonical **organizational and navigation contract**.

## Identified Gaps

The architecture does not explicitly guarantee that the serialized contract alone provides:

| Presentation requirement | Current architectural guarantee | Gap classification |
|---|---|---|
| Opportunity title | Section assignment and upstream reference | Architectural omission for self-contained presentation |
| Buyer identity | Section assignment and upstream reference | Architectural omission for self-contained presentation |
| Solicitation identity | Section assignment and upstream reference | Architectural omission for self-contained presentation |
| Workstreams and authoritative scope wording | Requested-work references | Architectural omission; upstream dependency |
| Timeline values, labels, precision, and timezone state | Timeline references and validity rules | Architectural omission; upstream dependency |
| Contract term | Opportunity-identity/commercial references | Architectural omission; upstream dependency |
| Procurement model and mechanics | Opportunity-identity/commercial references | Architectural omission; upstream dependency |
| Deliverable titles, descriptions, conditions, and dependencies | Delivery-structure references | Architectural omission; upstream dependency |
| Executive observation and interpretation wording | Preservation rule plus optional display value | Architectural omission due optional materialization |
| Computed values, units, formulas, and denominators | Retained through upstream object | Intentional upstream dependency; gap under sole-contract requirement |
| Complete assumptions and competing hypotheses | Typed collections and upstream references | Architectural omission for self-contained meaning |
| Complete unknown and conflict semantics | Typed collections and upstream references | Architectural omission for self-contained meaning |
| Management-question text | Typed identity and optional display value | Architectural omission for self-contained presentation |
| Limitation text and scope | Typed identity and optional display value | Architectural omission for self-contained presentation |
| Complete evidence relationship structure | Evidence-support IDs where permitted | Intentional evidence-store dependency |
| Source content and locators | Owning evidence store | Intentionally outside the contract |
| Complete provenance | Owning provenance stores | Intentionally outside the contract |
| Human-readable stable field labels | Structural section and semantic class | Architectural omission for independent presentation |
| Deterministic access to referenced upstream content | Reference closure during construction | No consumer-access guarantee without a resolver |

The table identifies architectural guarantees only. It makes no claim about any implementation.

## Required Architectural Amendments

Architectural amendments are required **only if** Executive Opportunity Understanding must be the sole self-contained semantic input and downstream consumers may not resolve owning-domain objects.

The minimum missing guarantees are:

1. **Mandatory consumer-accessible semantic content.** Every admitted reference must expose, within the canonical contract, the exact upstream label, value, statement, and governed semantic properties necessary to present that object without recomputation, interpretation, or external lookup.

2. **Complete typed detail preservation.** Computed-fact metadata, observation and interpretation wording, reasoning gaps, complete alternatives, assumptions, unknown details, conflict details, questions, limitations, deliverable properties, dates, commercial facts, and other admitted semantics must be present losslessly or be reachable through a resource that is normatively part of the contract itself.

3. **Deterministic field semantics.** Presentation consumers must be able to identify the precise governed meaning of each value, including buyer, title, solicitation reference, date kind, term, procurement mechanic, workstream, deliverable, criterion, and submission object, without keyword inference or consumer-owned classification.

4. **Consumer-level evidence closure.** The contract must guarantee enough evidence-relationship and provenance information for presentation and traceability, or explicitly include a contract-bound immutable evidence/provenance resource. An ID whose target is unavailable to the consumer is not sufficient closure under the sole-contract requirement.

5. **Fail-closed completeness for presentation semantics.** Validation must reject an understanding that claims an admitted object or executive-index entry but omits the semantic content required to present it under the supported contract version.

6. **Explicit independence statement.** The architecture must state whether a conforming presentation consumer can render from the serialized understanding alone. If external resolution remains part of the intended model, it must instead state that Executive Opportunity Understanding is the sole semantic organizer but not the sole data-bearing artifact.

These are missing guarantees, not a proposed schema or implementation design.

If the intended architecture remains reference-based, no amendment to materialize all values is necessary. In that case, the evaluated premise must change: presentation consumers require deterministic, read-only access to the exact immutable snapshot and owning stores referenced by the understanding.

## Impact on Downstream Consumers

### Executive Opportunity Brief

The brief can use the executive index to determine section membership and order. It cannot reliably render the existing opportunity identity, workstreams, timelines, commercial structure, deliverables, findings, unknowns, questions, and evidence links from references alone unless exact semantic values are carried or resolved. Any consumer logic that searches IDs, infers labels, reconstructs summaries, or consults Opportunity Intelligence would exceed a pure presentation boundary.

### Dashboards and role-specific views

Dashboards can navigate IDs, authority classes, coverage, and sections. Human-readable cards, tables, filters, date displays, and evidence drill-down require the referenced semantic values and relationship metadata. Without contract-contained content or resolution, different consumers could implement inconsistent lookup and labeling behavior.

### Decision Workspace and Bid Workspace

The contract adequately preserves high-level domain and authority boundaries. Complete side-by-side presentation still requires the exact content of each referenced object. Workspace independence therefore depends on access to owning stores under the current architecture.

### Proposal Compliance

The architecture correctly prevents Executive Opportunity Understanding from becoming substitute evidence. Compliance may use understanding references for navigation, but it must continue tracing to authoritative requirement and submission domains. This is an intentional boundary and means the understanding cannot be a self-contained sole input for compliance evidence.

### APIs and exported artifacts

The API section guarantees retrieval of the complete detail register and coverage ledger, not retrieval of all referenced upstream semantic content. An exported understanding can therefore be complete as an organizational record while remaining insufficient as a portable presentation dataset.

### Historical rendering

Versioned adapters protect semantic compatibility, but historical re-rendering also requires continued availability of referenced upstream content. Identity digests prove which snapshot was used; they do not reproduce that snapshot.

## Recommendation

The approved architecture should be regarded as sufficient for a canonical, immutable **organization-and-coverage layer over governed upstream records**. It is not sufficient as a self-contained sole data-bearing contract for all presentation consumers under a prohibition on external resolution.

The key architectural ambiguity should be resolved before requiring pure presentation consumers to depend on Executive Opportunity Understanding alone:

- If “sole canonical upstream contract” means the sole organizer and authority boundary, while deterministic resolution of contract-bound owning records is permitted, the architecture is already coherent and requires no amendment for that model.
- If it means one serialized object from which every governed presentation value, relationship, and provenance path can be reconstructed without any other resource, the six guarantees listed above require architectural amendment.

Under the exact validation premise in this review—no Opportunity Intelligence, Stage D, external resolver, or secondary projection—the recommendation is **ARCHITECTURAL AMENDMENT REQUIRED**. The amendment should add only the minimum normative guarantees for consumer-accessible semantic completeness and evidence closure. It must preserve the existing authority model: owning domains remain authoritative, Executive Opportunity Understanding remains organizational, presentation remains non-analytical, and human judgment remains sovereign.
