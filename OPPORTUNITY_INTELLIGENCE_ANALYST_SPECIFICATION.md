# Opportunity Intelligence Analyst — Functional Specification

**Specification version:** `opportunity-intelligence-analyst/1.1.1`
**Framework dependency:** Decision Intelligence Phase 1 and Decision Analyst Contract Phase 2
**Status:** Authoritative implementation specification
**Implementation status:** Not implemented

## Summary of amendments

Version 1.1.0 adds one responsibility established by [`OPPORTUNITY_INTELLIGENCE_PUBLICATION_ARCHITECTURAL_REVIEW.md`](docs/archive/operational/OPPORTUNITY_INTELLIGENCE_PUBLICATION_ARCHITECTURAL_REVIEW.md): Opportunity Intelligence publishes the immutable analytical objects it already owns for governed downstream resolution.

The amendment defines publication identity, snapshot, version and digest binding, owner-declared semantic and relationship publication, compatibility, validation, fail-closed behavior, and downstream guarantees. It does not change analytical semantics, computation, evidence or canonical ownership, or any downstream domain.

Version 1.1.1 clarifies the existing publication identity contract by separating semantic publication from operational execution metadata. Operational metadata remains available for audit, replay, diagnostics, and execution traceability, but cannot affect semantic publication identity, publication-snapshot identity, semantic digests, governed-reference identity, canonical ordering, or downstream semantic equality.

## Rationale

The existing contract makes `DecisionAnalysis` an immutable, validated analytical output, but stable IDs alone do not make its owned objects resolvable across domain boundaries. [`GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md`](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md) requires the owning domain to publish exact semantic representations under immutable owner, version, snapshot, digest, and relationship bindings.

Opportunity Intelligence must provide those owner declarations because it owns the analytical meaning. Governed Reference Resolution may verify them but cannot create them. Executive Opportunity Understanding may organize their references but cannot bind or republish their semantics. Publication therefore closes the existing cross-domain boundary without creating another source of truth.

The version 1.1.1 clarification follows the constitutional separation of evidence, computation, inference, and operational process. A governed semantic identity describes what an owner declares, while an execution record describes when and how processing occurred. Allowing process metadata to change semantic identity would make identical governed meaning appear different without an owner-declared semantic change, weakening determinism, immutable ownership, historical resolution, and downstream equality.

## 1. Purpose

The Opportunity Intelligence Analyst describes what an opportunity looks like from the evidence already held by Bid Intelligence. It organizes authoritative facts, calculates reproducible structural measures, identifies evidence-backed patterns and alternative explanations, exposes uncertainty, and raises questions that require management judgment.

It does not answer whether the organization should bid. It has no authority to approve, reject, prioritize, price, qualify, submit, or withdraw an opportunity.

Its governing principle is:

> AI assists reasoning. Humans make decisions.

## 2. Responsibilities

The analyst is responsible for:

1. assembling an opportunity-scoped view of already validated entities;
2. reporting authoritative facts without changing or reclassifying them;
3. computing deterministic structural measures from those facts;
4. identifying evidence-supported patterns, relationships, themes, trade-offs, and possible organizational implications;
5. keeping competing explanations separate;
6. exposing assumptions, limitations, contradictions, missing inputs, and confidence;
7. distinguishing factual observations from AI inference;
8. raising business-judgment questions for management; and
9. returning a valid Phase 2 `DecisionAnalysis` for future moderation.

It solves the problem of turning a large normalized opportunity record into a traceable description of scope, complexity, effort, obligations, and uncertainty without converting that description into a pursuit recommendation.

## 3. Questions the analyst answers

The analyst may answer:

- What is known about the opportunity?
- Which facts define its structure, scope, deadlines, evaluation, submission, commercial obligations, and delivery expectations?
- How large and structurally complex is the known requirement set?
- Which parts of the opportunity appear to drive proposal or delivery effort?
- Which themes recur across requirements, deliverables, clauses, and evaluation criteria?
- Which facts interact or create trade-offs?
- Where do the documents contain ambiguity, contradiction, or incomplete coverage?
- Which interpretations are supported, partially supported, unsupported, or unknown?
- What alternative explanations fit the same evidence?
- What evidence would reduce material uncertainty?
- Which issues require management judgment rather than factual resolution?

## 4. Questions the analyst must never answer

The analyst must never answer or imply:

- Should we bid?
- Is this a go or no-go opportunity?
- Will we win?
- What is the probability of winning?
- Is the buyer likely to prefer us?
- Which competitor will win?
- Are we capable or qualified unless an authoritative human-controlled capability record explicitly establishes that fact in a future version?
- What price should we submit?
- Should management accept a contractual risk?
- Should a requirement be marked compliant?
- Should the proposal be approved or submitted?
- Is a missing clause favorable or safe?
- What an absent document would have said?
- Whether an inferred pattern is legally, commercially, or professionally conclusive?

It does not replace management, legal counsel, commercial advisers, estimators, engineers, compliance specialists, or proposal consultants.

## 5. Governing framework contracts

The implementation must satisfy the existing internal contracts:

- Phase 1 `DecisionStatement`, `EvidenceSupport`, `ReasoningGaps`, `AlternativeHypothesis`, and `HumanDecisionRecord` boundaries;
- Phase 2 `DecisionAnalystMetadata`, `DecisionAnalysis`, `AnalystReasoning`, `AnalystHypothesis`, `AnalystRecommendation`, `AnalystUnknowns`, and `ManagementQuestion` boundaries; and
- Phase 2 registry identity, version, capability, evidence-closure, and output-validation rules.

The analyst metadata must use a stable analyst ID. The initial implementation should declare version `1.0.0`, a domain of opportunity characterization, and only the statement and evidence types it actually emits.

The analyst must not modify either framework contract to accommodate domain-specific shortcuts.

## 6. Allowed inputs

The analyst receives an explicitly bounded, immutable opportunity context. Version 1 may consume only the following entities when they are present in the supplied context and valid under their owning subsystem:

| Input | Permitted use | Authority |
|---|---|---|
| Canonical opportunity | Resolved headline identity and structure | Authoritative for its resolved fields |
| Canonical observations | Typed dates, money, term, and procurement mechanics | Authoritative only according to canonical status and provenance state |
| Requirements | Counts, categories, obligation structure, evidence state, and thematic reasoning | Authoritative source facts after existing normalization |
| Deliverables | Delivery-output structure and obligation measures | Authoritative only when admitted by Contract Hygiene |
| Commercial clauses | Commercial and contractual fact structure | Authoritative only when admitted by Contract Hygiene |
| Canonical dates | Timeline calculations and milestone structure | Authoritative according to canonical resolution and precision |
| Canonical money | Stated-value and commercial-scale calculations | Authoritative according to canonical resolution and currency semantics |
| Procurement mechanics | Opportunity-form and award-mechanic description | Authoritative according to canonical classification status |
| Evaluation criteria | Weighting, hierarchy, thresholds, and evaluation emphasis | Authoritative under the existing evaluation hierarchy |
| Submission requirements | Artifact, channel, format, mandatory-state, and pathway structure | Authoritative under the existing submission projection |
| Conflicts | Identification of unresolved disagreement and affected fields | Authoritative as unresolved conflict records |
| Evidence IDs | Traceable support for statements and entity links | Authoritative references; content remains in the owning provenance store |
| Existing Decision Intelligence statements | Context supplied by the orchestrator | Authority remains defined by each statement category |

The analyst may also receive stable IDs for requirements, clauses, deliverables, observations, canonical facts, conflicts, and evidence. It must reuse those IDs exactly.

### 6.1 Authority precedence

When representations overlap, the implementation must observe this order:

1. authoritative canonical resolution for fields governed by Canonical Opportunity;
2. explicit unresolved canonical or Stage C conflict state;
3. authoritative normalized entity from its owning subsystem;
4. deterministic computed fact derived from the above;
5. AI inference;
6. hypothesis or management consideration.

Lower levels cannot overwrite, resolve, or contradict higher levels. An unresolved authoritative conflict remains unresolved.

### 6.2 Input admission

An entity is admissible only if the existing subsystem would expose it to an authorized downstream consumer. In particular:

- unverified fresh logical clauses remain diagnostic and are not reasoning inputs;
- malformed or unparsed canonical observations cannot become authoritative headline facts;
- unresolved conflicts cannot be converted into selected values;
- evidence links must resolve to declared Phase 2 `evidence_used` entries; and
- source provenance must remain in its original subsystem rather than being copied into analyst output.

## 7. Prohibited inputs

Version 1 must not use:

- internet or web search;
- historical award data;
- supplier, competitor, market, sanctions, corporate, or pricing databases;
- CRM records;
- buyer relationship history;
- organizational memory or undocumented human recollection;
- future Buyer, Competition, Capability, Pricing, Risk, or Organizational Intelligence outputs;
- previous opportunity analyses unless explicitly admitted by a future versioned contract;
- private model training memory;
- facts from unrelated bids or workspaces;
- guessed missing documents, amendments, annexes, clauses, values, dates, or requirements;
- unverified, unparsed, unsupported, or inaccessible evidence;
- user identity, role, or commercial preference as factual evidence;
- free-text citations that do not resolve to stable entity and evidence IDs; or
- any model-generated claim merely because it appears in an earlier narrative output.

If a prohibited or unavailable input would materially affect interpretation, the analyst records the absence as an unknown or limitation. It does not approximate the missing information.

## 8. Processing model

The future implementation has three strictly separated layers.

### 8.1 Deterministic assembly

The orchestrator validates the bounded context, entity IDs, versions, authority states, and evidence links. This step performs no AI reasoning.

### 8.2 Deterministic computation

Pure functions compute reproducible measures from admitted entities. Each computed result becomes a `COMPUTED_FACT`, uses a deterministic-computation source, and links to every contributing entity and evidence reference required by the calculation.

### 8.3 Constrained AI reasoning

AI may interpret relationships among admitted source and computed facts. Every output becomes an `AI_INFERENCE` or `HYPOTHESIS`, carries reasoning confidence and support status, and discloses assumptions, alternatives, limitations, and gaps.

Human judgment occurs outside the analyst. Management questions and considerations are handoff objects, not decisions.

## 9. Required deterministic computations

The following measures must be deterministic whenever their required inputs exist. The implementation phase must specify formulas, denominators, null behavior, units, sorting, and rounding before code is accepted.

### 9.1 Requirement structure

- total normalized requirement count;
- count by authoritative category and requirement type;
- mandatory, optional, conditional, and unknown counts where represented;
- mandatory-to-known-requirement and optional-to-known-requirement ratios;
- requirements without verified source evidence;
- requirements affected by unresolved conflicts;
- requirement density by source document, section, page, or worksheet when comparable locator units exist; and
- count of requirements linked to each deliverable or submission artifact.

Ratios must disclose their denominator. Unknown classifications are never forced into mandatory or optional totals.

### 9.2 Evaluation structure

- total stated weights by unit and basis;
- weight by evaluation stage and leaf criterion;
- count of thresholds and pass/fail gates;
- unweighted or partially weighted criteria;
- hierarchy depth and criterion count by level;
- conflicting weight or role observations; and
- percentage of evaluation weight that can be reconciled without mixing incompatible bases.

Weights with different units or bases cannot be summed.

### 9.3 Submission structure

- required, optional, and unknown-mandatory artifact counts;
- artifact counts by format and submission channel;
- number of distinct submission pathways;
- artifacts with unresolved format, channel, or mandatory state;
- number of signatures, certifications, forms, workbooks, and envelopes when explicitly classified; and
- document-completeness coverage against explicitly identified submission requirements.

Document completeness describes identified artifacts and available status. It does not assert portal acceptance or final compliance.

### 9.4 Timeline structure

- calendar days between valid canonical milestones;
- days from the configured analysis reference time to valid future milestones;
- clarification-to-submission interval;
- count of milestones with date, datetime, partial, unknown, malformed, or conflicted state;
- overlapping or identical milestone dates; and
- intervals for explicitly stated delivery periods where compatible endpoints exist.

Calculations use supplied timezone semantics only. They never invent a timezone or convert partial dates into full dates.

### 9.5 Commercial and delivery structure

- count of verified commercial clauses by controlled kind;
- count of verified supplier deliverables by obligation state, frequency, and scope;
- clause and deliverable counts affected by explicit conditions;
- count of explicit monetary observations by semantic kind and currency;
- count of unresolved commercial conflicts;
- count of stated commencement, end, option, or renewal observations; and
- count of explicitly linked canonical observations.

Values in different currencies or semantic kinds remain separate. Absence of a clause is not a favorable commercial fact.

### 9.6 Complexity indicators

Version 1 may compute individual indicators from the measures above, including:

- requirement volume;
- source-document dispersion;
- evaluation hierarchy depth;
- submission artifact volume;
- distinct submission pathways;
- milestone compression;
- conditional-obligation volume;
- deliverable frequency diversity;
- commercial-clause diversity;
- unresolved conflict count;
- unknown mandatory-state count;
- missing-evidence count; and
- cross-entity linkage density.

Version 1 must not produce an opaque aggregate complexity score. Each indicator remains visible with its source measures. Any future composite requires an independently reviewed formula and version.

## 10. Permitted AI reasoning

AI may reason about:

- recurring themes across authoritative entities;
- relationships between requirements, evaluation emphasis, deliverables, submission artifacts, dates, and clauses;
- possible drivers of proposal effort or delivery complexity;
- organizational implications expressed as considerations rather than capability judgments;
- trade-offs created by schedule, submission, commercial, or evidence structure;
- hidden complexity supported by multiple explicit facts;
- material uncertainty and which missing evidence causes it;
- multiple plausible explanations for a measured pattern; and
- business-judgment questions created by the known evidence.

AI must not:

- invent or silently complete evidence;
- change facts, IDs, provenance, classifications, dates, values, conflict status, or authoritative sections;
- calculate measures that are designated deterministic;
- select one side of an unresolved conflict;
- treat correlation as causation;
- infer bidder capability from opportunity requirements;
- infer buyer preference, competitor position, win probability, or recommended pursuit action;
- convert an organizational implication into a factual deficiency;
- give legal, tax, accounting, engineering, medical, or regulatory advice; or
- conceal an assumption inside narrative prose.

## 11. Output contract

The analyst returns one Phase 2 `DecisionAnalysis`. Its `analysis_id`, analyst ID, version, and timezone-aware execution timestamp are stable and explicit.

The output contains:

- admitted `evidence_used` links;
- deterministic `computed_facts`;
- typed `inferences`;
- unranked `hypotheses`;
- no pursuit recommendations;
- explicit assumptions;
- explicit limitations;
- explicit unknowns; and
- explicit management questions.

Although Phase 2 supports advisory recommendations generally, Opportunity Intelligence version 1 must declare no `RECOMMENDATION` capability and must return an empty recommendations collection. Management considerations belong in inference or moderator-ready consideration structures and cannot contain directives.

### 11.1 Owner publication for governed resolution

After a `DecisionAnalysis` passes its complete owner validation, Opportunity Intelligence publishes its owned analytical objects as one immutable publication snapshot conforming to [`GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md`](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md). Publication is part of the Opportunity Intelligence owner boundary. It is not a separate domain, service, analysis, projection, or persistence authority.

Publication does not create or alter semantic content. It makes the exact validated content already owned by Opportunity Intelligence resolvable by other governed domains.

#### Publication identity and binding

Each publication has:

- the owner domain `OPPORTUNITY_INTELLIGENCE`;
- the exact Opportunity Intelligence owner-contract identity and version;
- the stable `analysis_id`;
- the immutable authoritative input-snapshot identity and digest against which the analysis was validated;
- a deterministic publication-snapshot identity;
- a reproducible publication-snapshot digest;
- a closed, canonically ordered object manifest;
- a reproducible object digest for every published object; and
- the exact versions of owner contracts needed to interpret published objects and their relationships.

The publication-snapshot identity is derived deterministically from the owner-contract version, `analysis_id`, authoritative input-snapshot identity and digest, and publication object-manifest digest. The snapshot digest covers the canonical semantic publication and excludes operational metadata that has no effect on meaning. Any change to semantic content, object membership, relationship membership, owner version, or authoritative input binding creates a different digest and, where the identity inputs change, a different publication-snapshot identity.

The published snapshot is immutable. It cannot mean “latest,” depend on mutable current state, or be rebound to another authoritative input snapshot. Historical references remain bound to the exact historical publication and authoritative input snapshots.

#### Semantic publication and operational execution metadata

Semantic publication consists only of owner-declared analytical meaning and the governed bindings required to identify, interpret, order, validate, and resolve that meaning. It includes published object membership, semantic fields, authority and reasoning properties, uncertainty, assumptions, alternatives, limitations, relationship membership, owner-contract version, authoritative input-snapshot binding, and the canonical ordering required by this specification.

Operational execution metadata describes the process that produced or handled an analysis without changing what the validated analysis means. It includes execution timestamps, execution identifiers, runtime and processing-environment metadata, performance measurements, transport or storage locations, and execution diagnostics. Such metadata is not an owner-declared analytical fact merely because it is recorded beside a `DecisionAnalysis` or publication record.

Operational execution metadata MUST NOT participate in:

- semantic publication identity;
- publication-snapshot identity;
- semantic publication or object digests;
- governed-reference identity;
- canonical semantic ordering; or
- downstream semantic equality.

In particular, the timezone-aware execution timestamp required by the `DecisionAnalysis` output contract remains operational metadata. For the same validated semantic analysis, owner-contract version, authoritative input-snapshot binding, published object set, relationships, and canonical semantic values, changing only the execution timestamp or other operational metadata produces the identical semantic publication identity, publication-snapshot identity, semantic digests, governed references, ordering, and downstream semantic equality.

Operational metadata may remain separately attributable to the immutable execution or publication record for audit, deterministic replay verification, diagnostics, and operational traceability. Its storage and audit identity are independent of semantic publication identity. Excluding it from semantic identity does not permit mutation of an existing audit record, loss of execution history, or substitution of one execution record for another.

#### Published objects

Opportunity Intelligence publishes only the analytical objects it owns and that are present in the validated `DecisionAnalysis`:

- deterministic computed facts;
- typed analytical observations and inferences;
- hypotheses and their complete unranked alternatives;
- explicit assumptions;
- explicit unknowns and evidence gaps;
- explicit limitations;
- management considerations; and
- unanswered management questions.

For each object, Opportunity Intelligence publishes the exact owner-declared semantic representation required to interpret it without consumer inference. The representation retains all applicable existing fields, including stable identity, semantic type, exact wording or value, computation metadata, authority class, reasoning state, confidence, support status, scope, units, assumptions, alternatives, gaps, limitations, and governed absence. Publication introduces no replacement wording, summary, classification, score, or display-specific variant.

Version 1 publishes no recommendations or human decisions because the Opportunity Intelligence contract does not authorize them.

#### Published relationships

The publication manifest exposes the exact existing relationships required to understand and validate each published object, with explicit role, direction, identity, owner, contract version, snapshot binding, and canonical order where order is meaningful. These include, as applicable:

- contributing authoritative entity and fact references;
- evidence-support references;
- supporting and contradicting evidence;
- computation inputs;
- assumption dependencies;
- alternative-hypothesis membership;
- unknown, evidence-gap, and limitation relationships;
- affected entity references; and
- the governed basis for management considerations and questions.

Upstream evidence, provenance, requirements, deliverables, clauses, canonical facts, observations, conflicts, dates, monetary values, procurement mechanics, evaluation criteria, and submission requirements remain owned and published by their existing domains. Opportunity Intelligence publishes only exact governed references to them. It does not copy their semantic content into an Opportunity Intelligence-owned object or claim their authority.

Every required outbound relationship must close within the immutable bounded resolution context formed by the Opportunity Intelligence publication snapshot and the exact compatible upstream snapshots against which the analysis was validated. Publication cannot add a relationship that was not present in the validated analysis or its admitted input bindings.

#### Explicit publication exclusions

Opportunity Intelligence does not publish:

- upstream authoritative or canonical objects as Opportunity Intelligence-owned objects;
- copied provenance or evidence content as a new source of truth;
- raw extraction, normalization, reconciliation, Stage D, prompt, or model-provider state;
- diagnostic or rejected inputs that were not admitted to the validated analysis;
- mutable internal state, credentials, transport metadata, or unrelated domain records;
- presentation sections, executive organization, rendered narratives, or consumer-specific labels;
- inferred relationships, repaired references, fallback values, or current-state substitutions; or
- recommendations, rankings, scores, predictions, procurement strategy, or human decisions.

#### Downstream guarantees

When Governed Reference Resolution successfully resolves an Opportunity Intelligence publication reference, the consumer is guaranteed:

- exact object identity, ownership, semantic class, contract version, snapshot identity, and verified digests;
- the complete owner-declared semantic representation required by the consumer contract;
- unchanged authority, reasoning state, confidence, support status, uncertainty, assumptions, alternatives, gaps, and limitations;
- exact evidence, provenance-navigation, support, dependency, and affected-entity relationships required by the object;
- deterministic owner ordering and canonical serialization;
- consistency with the exact authoritative input snapshot used by the analysis; and
- a clear distinction between governed absence and resolution failure.

Successful resolution grants read-only semantic access. It does not transfer ownership, promote analysis to canonical fact, authorize a consumer to alter the object, or answer a management question.

#### Publication validation and fail-closed behavior

Opportunity Intelligence emits no publication snapshot unless:

- the complete `DecisionAnalysis` validates under the exact owner-contract version;
- every published object has a unique stable identity and supported semantic class;
- the analysis and publication bind to the same authoritative input snapshot and digest;
- canonical serialization reproduces every snapshot and object digest;
- the object manifest is complete and deterministically ordered;
- every owner-declared required semantic field is present;
- every required relationship is typed, directionally explicit, and closed in the bounded resolution context;
- all referenced owner contracts and exact versions are supported;
- authority, uncertainty, confidence, support status, assumptions, alternatives, and limitations remain unchanged; and
- the publication contains no excluded object, copied authority, inferred relationship, or consumer-authored meaning.

Missing or duplicate identities, unsupported versions, owner mismatch, snapshot or object digest mismatch, incomplete manifests, missing semantic content, broken relationship closure, incompatible snapshot sets, or nondeterministic serialization fail publication. Opportunity Intelligence does not drop the affected object, repair the reference, search another snapshot, substitute current state, or emit a partially trusted publication.

#### Publication compatibility

Every governed reference names the exact Opportunity Intelligence owner-contract version and publication snapshot that define its meaning. Consumers declare supported versions and fail on incompatible versions.

A compatibility transformation is permitted only when an explicit deterministic contract preserves stable owner and object identities, all required semantic content, authority, uncertainty, evidence and provenance relationships, snapshot and digest traceability, and canonical ordering. It must identify source and target versions and fail when required meaning cannot be represented. It cannot rerun analysis, recompute a fact, reinterpret prose, add or remove an alternative, repair evidence, or substitute a newer publication.

Historical publication snapshots remain immutable and resolvable for as long as governed references to them remain valid.

## 12. Required report sections

Every section is structured data backed by typed statements. Display headings do not create additional facts.

### 12.1 Executive Overview

A concise description of the opportunity’s known structure, major measured characteristics, material uncertainty, and principal management considerations. It contains no decision, pursuit direction, win claim, or unsupported superlative.

### 12.2 Opportunity Characteristics

Authoritative and computed facts describing opportunity type, procurement mechanics, scope structure, value where resolved, term where resolved, requirement composition, and evaluation form.

### 12.3 Complexity Assessment

Individual deterministic complexity indicators and evidence-backed interpretations of their possible significance. No opaque score and no automatic “simple” or “complex” label without a versioned rule.

### 12.4 Capability Considerations

Opportunity demands that may require management to inspect organizational capability. The analyst describes demanded capabilities; it does not determine whether the bidder possesses them.

### 12.5 Commercial Considerations

Verified commercial facts, obligation patterns, monetary structures, conditions, and unresolved commercial uncertainty. It does not characterize a term as acceptable, market-standard, or legally safe.

### 12.6 Compliance Considerations

Mandatory, conditional, evidence, submission, and unresolved-state structure. It does not change compliance status or certify eligibility.

### 12.7 Delivery Considerations

Deliverable volume, frequency, scope, acceptance structure, dependencies, and schedule relationships. It does not assert operational capability.

### 12.8 Proposal Effort

Deterministic workload indicators and alternative explanations for apparent effort. It does not estimate hours or staffing unless a future authoritative effort model supplies those values.

### 12.9 Unknowns

Explicit missing or unavailable facts, unresolved conflicts, ambiguous observations, partial dates, unknown mandatory states, and other bounded uncertainty.

### 12.10 Evidence Gaps

Missing evidence or documents whose absence limits a stated conclusion. Each gap identifies the affected statements and entities.

### 12.11 Clarification Questions

Factual ambiguities that could be submitted to the contracting authority. Questions must trace to an ambiguity, conflict, or missing source element. They are distinct from management questions.

### 12.12 Management Considerations

Neutral descriptions of trade-offs or issues requiring organizational judgment. They cannot contain `bid`, `do not bid`, `go`, `no-go`, approval, rejection, or equivalent direction.

### 12.13 Confidence

Reasoning confidence by significant inference and hypothesis, including the factors limiting confidence. Facts do not receive confidence labels.

### 12.14 Alternative Interpretations

Competing explanations for significant patterns. Alternatives remain separate and unranked unless deterministic evidence excludes one.

### 12.15 Limitations

Input, validation, scope, temporal, and method limitations affecting the analysis as a whole.

## 13. Evidence and citation rules

Every significant conclusion must reference typed Phase 1 or Phase 2 objects and stable existing IDs.

Allowed support includes:

- Decision Intelligence statement IDs;
- canonical fact or observation IDs;
- requirement IDs;
- verified commercial-clause IDs;
- verified deliverable IDs;
- conflict IDs; and
- evidence IDs already owned by the provenance layer.

Free-text citations, filenames embedded in prose, fabricated page references, and narrative descriptions of support do not satisfy the contract.

The analysis-level `evidence_used` collection is closed: every evidence link used by a computed fact, inference, or hypothesis must appear in it. An ID is referenced, not rewritten. The source excerpt, locator, verification state, and ownership remain in the authoritative provenance store.

## 14. Confidence interpretation

Confidence applies only to reasoning.

| Confidence | Meaning |
|---|---|
| `HIGH` | The admitted evidence directly and consistently supports the inference, material alternatives have been considered, and no known gap is likely to reverse it. |
| `MODERATE` | The inference has meaningful support, but one or more assumptions, alternatives, conflicts, or coverage limitations could materially change it. |
| `LOW` | The inference is plausible but rests on limited, indirect, incomplete, or materially conflicted evidence. |
| `UNKNOWN` | Available evidence is insufficient to assess the inference’s reliability. |

Confidence is not probability, source authority, legal certainty, compliance status, or a quality score. It must not be averaged across unrelated statements. Overall analysis confidence summarizes the coverage of reasoning only and cannot upgrade any individual inference.

Support status and confidence remain distinct. `SUPPORTED` describes the relationship between admitted evidence and reasoning; `HIGH` describes the assessed reliability of that reasoning. A statement can be supported but still have moderate confidence because the available package is incomplete.

## 15. Alternative interpretations

Every significant inference must either:

1. carry at least one material alternative hypothesis; or
2. state a deterministic reason why no material alternative was identified.

For an apparent high-proposal-effort pattern, separate hypotheses may include:

- genuinely broad scope;
- poor source-document organization;
- multiple submission pathways;
- missing annexes;
- uncertain amendment coverage; or
- duplication across documents.

The analyst must not merge these into one explanation, silently select a preferred explanation, or assign a rank. Supporting and contradicting evidence remains distinct for each hypothesis.

An alternative is removed only when a deterministic contradiction or an authoritative fact makes it impossible. Mere lower confidence does not remove it.

## 16. Assumption disclosure

Every assumption is a separate, stable `AnalystAssumption`. Assumptions must never be implied through phrasing.

Each inference and hypothesis should identify the assumptions on which it depends. Examples include comparability of document sections, completeness of the supplied package, or consistent use of terminology. These examples are not default assumptions and must not be inserted unless the reasoning actually depends on them.

If an assumption cannot be supported, it remains an assumption and reduces confidence. It cannot be promoted to a source or computed fact.

## 17. Uncertainty representation

Uncertainty must be represented through explicit typed fields rather than softened narrative language.

Required uncertainty families include:

- missing evidence;
- missing documents;
- missing or unknown amendments;
- unavailable annexes;
- ambiguous wording;
- contradictory requirements;
- unresolved canonical or Stage C conflicts;
- incomplete pricing or currency context;
- partial, malformed, or unknown dates;
- unknown submission mandatory state;
- unsupported entity linkage;
- incomplete evaluation weighting; and
- validation or method limitations.

Each material unknown identifies the conclusions it limits. If the uncertainty prevents a conclusion, the analyst emits `UNKNOWN` rather than a weak affirmative conclusion.

## 18. Clarification questions and management questions

A clarification question seeks an authoritative factual answer from the procurement authority. It must arise from source ambiguity, contradiction, or missing procurement information.

A management question asks the organization to exercise business judgment. Examples include selecting acceptable trade-offs, choosing how much internal validation to perform, or deciding which uncertainty merits escalation. It does not ask management to establish a source fact that the buyer must clarify.

Management questions must:

- have stable IDs;
- identify related analysis IDs;
- explain the judgment boundary neutrally;
- avoid implied recommendations; and
- remain unanswered in analyst output.

## 19. Observation, inference, consideration, and decision

| Layer | Definition | Authority |
|---|---|---|
| Observation | An admitted authoritative or normalized fact with existing provenance | Owned by the source subsystem |
| Computed fact | A reproducible transformation of admitted facts | Deterministic; cannot exceed its inputs |
| Inference | A transparent, evidence-linked interpretation with confidence and alternatives | Advisory reasoning |
| Management consideration | A neutral trade-off or issue requiring business judgment | Advisory framing |
| Recommendation | A proposed action under Phase 2 | Not emitted by Opportunity Intelligence v1 |
| Decision | An accountable human choice with rationale and decision maker | Human authority only |

No layer may masquerade as another. In particular, persuasive wording cannot turn an inference into a fact or a consideration into a decision.

## 20. Validation and failure behavior

The implementation must fail validation rather than return a partial apparently valid analysis when:

- analyst identity or version is wrong;
- output exceeds declared statement or evidence capabilities;
- a conclusion contains an unknown entity or evidence ID;
- a link falls outside `evidence_used`;
- a computed fact is placed in an inference collection or vice versa;
- confidence is attached to a source fact;
- a recommendation or decision is emitted;
- a management consideration contains pursuit direction;
- an unresolved conflict is presented as resolved;
- an assumption is embedded without structured disclosure;
- significant reasoning omits alternatives without a deterministic explanation;
- IDs collide within the analysis;
- execution time lacks timezone information; or
- input or output is mutated during analysis.

Validation should report stable machine-readable failure codes. It must not repair unsupported conclusions by inventing support.

## 21. Determinism requirements

For identical admitted input and the same analyst contract version:

- entity admission and exclusion are identical;
- computed facts and their IDs are identical;
- formulas, rounding, null behavior, and ordering are identical;
- evidence-link ordering is canonical;
- output section ordering is stable;
- aliases, if an implementation uses them internally, are prompt-local and reversible; and
- AI reasoning may vary only inside the validated reasoning fields.

AI variability must never change source facts, computed facts, authority state, conflict state, evidence identity, or human decisions.

## 22. Integration architecture

### Decision Intelligence Architecture

Opportunity Intelligence uses Phase 1 statement classification, evidence linkage, assumptions, alternatives, limitations, gaps, and human-decision separation.

### Decision Analyst Contract

It implements the Phase 2 analyst protocol, registers stable metadata, consumes `AnalystContext`, and returns a validated `DecisionAnalysis`.

### Future Moderator

A moderator may compare the complete analysis with other analyst outputs. Opportunity Intelligence does not produce agreement or disagreement groups itself and cannot resolve disagreements between analysts.

### Future Buyer Intelligence

Buyer Intelligence may later add verified buyer history and behavior. Opportunity Intelligence v1 cannot anticipate or simulate that output.

### Future Competition Intelligence

Competition Intelligence may later add verified competitor and award evidence. Opportunity Intelligence v1 cannot infer competitive position.

### Future Organizational Intelligence

Organizational Intelligence may later compare opportunity demands with verified internal capability and history. Opportunity Intelligence v1 describes demands only.

### Governed downstream resolution

The governed flow is:

```text
Opportunity Intelligence
        ↓ owns and validates analysis
Owner Publication
        ↓ binds exact semantics, relationships, version, snapshot, and digests
Governed Reference Resolution
        ↓ verifies identity, authority, integrity, and closure
Executive Opportunity Understanding
        ↓ organizes resolved governed references
Presentation Consumers
```

Owner Publication is a responsibility of Opportunity Intelligence, not an intervening domain. Governed Reference Resolution performs verification only. Executive Opportunity Understanding performs organization only. Presentation consumers perform rendering only.

### Compatibility analysis

This amendment is compatible with the existing repository architecture:

- **Analytical semantics are unchanged.** The same validated `DecisionAnalysis` objects and meaning are published without new reasoning or computation.
- **Canonical ownership is unchanged.** Canonical Opportunity and other authoritative domains remain the sole owners of authoritative facts and conflicts.
- **Evidence ownership is unchanged.** Opportunity Intelligence publishes evidence relationships, while evidence and provenance remain in their owning domains.
- **Resolution authority is unchanged.** Governed Reference Resolution verifies owner declarations and creates no semantic content.
- **Executive organization is unchanged.** Executive Opportunity Understanding receives resolvable references and continues to own only organization and coverage.
- **Presentation authority is unchanged.** Downstream consumers render resolved meaning and receive no analytical or canonical ownership.
- **Existing immutable analyses retain their meaning.** Version 1.0.0 analyses are not silently reinterpreted as publications. Cross-domain resolution requires an exact supported publication binding or an explicit lossless compatibility contract.
- **Operational auditability is preserved without semantic drift.** Execution metadata remains independently attributable for audit, replay, diagnostics, and operational traceability, while semantic identity remains stable across executions that produce the same governed meaning.

The amendment satisfies the finding in [`OPPORTUNITY_INTELLIGENCE_PUBLICATION_ARCHITECTURAL_REVIEW.md`](docs/archive/operational/OPPORTUNITY_INTELLIGENCE_PUBLICATION_ARCHITECTURAL_REVIEW.md) by assigning the missing owner-publication responsibility to Opportunity Intelligence and supplying the identity, semantic, snapshot, version, digest, relationship, compatibility, validation, and fail-closed guarantees required by [`GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md`](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md).

## 23. Version roadmap

### Version 1 — Opportunity evidence

Current specification. Uses only the authoritative opportunity package and existing Decision Intelligence context. Produces deterministic characteristics, constrained inference, unknowns, alternatives, and management questions. No recommendations.

### Version 2 — Buyer history

May consume a separately validated Buyer Intelligence contract containing verified buyer history. It must preserve source identity and distinguish historical observation from inference.

### Version 3 — Competition intelligence

May consume validated competitive and award evidence through a versioned Competition Intelligence contract. It must not infer unavailable competitors or win probability by default.

### Version 4 — Historical organizational knowledge

May consume approved internal capability, delivery, proposal, and outcome records through Organizational Intelligence. Human-controlled verification and temporal relevance will require separate rules.

### Version 5 — Market intelligence

May consume governed external market evidence with source recency, licensing, identity resolution, and retrieval provenance. Web search and external APIs remain outside all earlier versions.

Each future version requires an explicit input-contract change, compatibility review, validation suite, and production approval. Roadmap entries do not authorize implementation in version 1.

## 24. Implementation acceptance criteria

A future implementation is conformant only if it proves:

1. no changes to Stage A–D or authoritative procurement models;
2. deterministic calculations with exact fixtures and edge cases;
3. no internet, external database, CRM, or cross-opportunity input;
4. complete evidence closure for every conclusion;
5. no copied or free-text provenance;
6. no confidence on source or computed facts;
7. no recommendation, Bid/No-Bid, or human decision output;
8. unresolved conflicts remain unresolved;
9. partial dates and incompatible monetary units are not combined;
10. competing hypotheses remain separate and unranked;
11. assumptions and uncertainty are structurally explicit;
12. management questions remain questions;
13. output validates through the Phase 2 registry;
14. identical inputs produce identical computed facts and ordering;
15. malicious or irrelevant document instructions cannot extend allowed inputs or outputs;
16. existing public API, persistence, replay, checkpoint, proposal, and UI behavior remains unchanged;
17. the full existing regression suite remains unchanged and passing;
18. every cross-domain-resolvable Opportunity Intelligence object is published under the exact owner contract, immutable publication snapshot, authoritative input-snapshot binding, and reproducible digests;
19. the published semantic representation and required relationship manifest are complete, immutable, canonically ordered, and sufficient for governed downstream resolution without inference;
20. publication never transfers or duplicates canonical, evidence, provenance, understanding, resolution, presentation, or human-decision authority;
21. historical and incompatible publication versions fail or transform only through an explicit deterministic lossless compatibility contract; and
22. publication fails closed for missing, duplicate, stale, incompatible, incomplete, corrupt, or unresolved content; and
23. changing only execution timestamps, execution identifiers, runtime metadata, processing environment, execution diagnostics, or other non-semantic operational metadata leaves semantic publication identity, publication-snapshot identity, semantic digests, governed references, canonical ordering, and downstream semantic equality unchanged while preserving independently attributable operational audit records.

## 25. Explicit exclusions

Version 1 does not implement:

- Bid/No-Bid analysis;
- pursuit recommendations;
- Buyer Intelligence;
- Competition Intelligence;
- Capability or Organizational Intelligence;
- Pricing or market intelligence;
- legal or commercial advice;
- web search or external APIs;
- historical award retrieval;
- CRM integration;
- prompts or model calls;
- extraction, normalization, reconciliation, or synthesis changes;
- persistence, migrations, UI, replay, checkpoint, or proposal changes; or
- analyst moderation.

This document fixes the functional boundary for a future Opportunity Intelligence Analyst. It introduces no runtime behavior.

Versions 1.1.0 and 1.1.1 amend this architecture specification only. Version 1.1.1 resolves the validated publication identity conflict by making operational execution metadata constitutionally non-semantic while preserving its independent auditability. No production code, prompts, tests, schemas, APIs, persistence, pipelines, evaluation artifacts, or other architecture documents were modified.
