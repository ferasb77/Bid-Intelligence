# Stage D Architectural Review

## Document metadata

| Field | Value |
|---|---|
| Document | `STAGE_D_ARCHITECTURAL_REVIEW.md` |
| Title | Stage D Architectural Review |
| Authority level | Level 5 — Architectural Review Record |
| Version | 1.0.0 |
| Status | Review only; no architecture decision or implementation authorization |
| Purpose | Assess whether Stage D combines responsibilities that should be separated for governed executive understanding at enterprise scale. |
| Higher authority | `MANIFESTO.md`, `AGENT.md`, `GOVERNANCE.md`, `ANTI_GOALS.md`, product doctrine, Decision Intelligence doctrine, Opportunity Intelligence doctrine, Executive Opportunity Brief architecture, Buyer Intelligence doctrine, Buyer Brief architecture, and Bid Intelligence Briefing Pack doctrine |
| Governed documents | None |
| Related documents | `STAGE_D_SYNTHESIS_COMPLETENESS_REPORT.md`, `STAGE_D_SYNTHESIS_PROJECTION_REPORT.md`, `OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md`, `EXECUTIVE_OPPORTUNITY_BRIEF_ARCHITECTURE.md`, `DECISION_WORKSPACE_ARCHITECTURE.md`, `BID_INTELLIGENCE_BRIEFING_PACK.md` |

## Executive finding

Stage D currently owns too many responsibilities with different authority, scaling characteristics, and failure modes.

Its name suggests one synthesis stage, but its production boundary presently includes deterministic evidence projection, provider-request construction, model-authored executive narrative, constrained classification, proposal-outline construction, citation validation, conflict protection, canonical authority reapplication, and final structured brief assembly. Those responsibilities do not form one coherent architectural unit.

Stage D does **not** currently render the Executive Opportunity Brief, DOCX, or PDF. Rendering occurs downstream. It nevertheless shapes presentation by returning brief fields and a proposal outline, so it mixes intelligence-facing narrative construction with presentation-oriented structure.

The corrected Bank of Canada run demonstrates the consequence. Evidence acquisition, extraction, normalization, reconciliation, and Opportunity Intelligence all completed over a substantially richer corpus. The Stage D projection included all 413 requirements and remained below its guard. The pipeline still could not produce an accepted brief because model-generated citation structures repeatedly failed deterministic validation. A presentation deliverable therefore became unavailable even though the governed opportunity understanding already existed.

The recommended direction is to make **Executive Opportunity Understanding** a first-class, immutable contract within the Opportunity Intelligence pillar. It should organize authoritative facts, deterministic computations, typed interpretations, assumptions, alternatives, conflicts, unknowns, limitations, and management questions without generating a recommendation or choosing among competing evidence. Narrative and rendering should become downstream, replaceable presentation transformations with no analytical authority.

This is an architectural recommendation only. It does not authorize changes to Stage D, prompts, contracts, code, persistence, replay, or public APIs.

## 1. Responsibilities Stage D currently owns

### 1.1 Deterministic evidence projection

Stage D builds a compact synthesis projection from normalized facts and conflicts. This work includes:

- preserving every normalized requirement;
- assigning prompt-local aliases to requirements, facts, evidence, clauses, and canonical observations;
- interning shared source references and proof text;
- retaining full authoritative inputs and provenance in a sidecar;
- separating prompt-visible material from diagnostic-only material;
- measuring request size and enforcing the fixed guard;
- recording completeness, bijection, provenance, and digest diagnostics.

This responsibility is deterministic infrastructure. It performs no executive reasoning and should not depend on the success of narrative generation.

### 1.2 Provider contract construction and dispatch

Stage D constructs the provider request and structured-output schema, dispatches the model call, and owns the bounded two-attempt retry policy. It therefore combines projection with an external execution boundary.

This responsibility has operational failure modes—provider errors, incomplete responses, schema rejection, and retry exhaustion—that are different from evidence-integrity failures.

### 1.3 Executive narrative construction

The model is asked to generate fields including:

- executive summary;
- opportunity type;
- contract term;
- procurement model;
- scope categories;
- selected bid metadata and notes.

Even under strict citations, these fields combine several semantic classes. Exact dates and identifiers are authoritative facts. Opportunity and procurement classifications are controlled interpretations. Executive summary and notes are narrative expressions. Treating them as one model response makes one validation defect capable of blocking all of them.

### 1.4 Proposal-outline and presentation shaping

Stage D also emits an ordered outline containing titles, notes, word limits, status, and ownership placeholders. The validator resets ordering and section numbering and prohibits invented operational state.

This is not document rendering, but it is presentation and proposal-structure shaping. Proposal-outline construction is also outside the core purpose of an Executive Opportunity Brief, whose role is to help professionals understand an opportunity before proposal writing begins.

### 1.5 Interpretation of contract clauses

Stage D emits constrained risk-assessment states and deterministic interpretation codes for verified commercial clauses. Application code converts those codes into approved neutral wording. This is a bounded analytical responsibility, distinct from executive summary writing and distinct from authoritative clause extraction.

### 1.6 Response validation

Stage D validates:

- exact output shape;
- supported classifications;
- citation closure;
- evidence ownership;
- scalar field pointers;
- exact-value support;
- conflict handling;
- clause identity and kind;
- prohibited bidder capability and operational values;
- complete citation of non-empty output fields.

This validation is necessary and doctrinally correct. Its current placement means that any invalid narrative support can prevent deterministic authoritative sections from reaching downstream presentation.

### 1.7 Authoritative reapplication and final assembly

After model validation, application code deterministically rebuilds seven authoritative sections from normalized inputs:

- qualification gates;
- evaluation breakdown;
- submission requirements;
- key dates;
- commercial structure;
- contract risks;
- deliverables summary.

Canonical values are then reapplied, final assembly invariants are checked, and the accepted result is returned.

This step is an authority-preserving assembly boundary. It is conceptually different from model synthesis and should remain available even when optional narrative construction fails.

## 2. Responsibilities that naturally belong together

### 2.1 Projection, identity mapping, sidecar preservation, and capacity diagnostics

These responsibilities form one coherent deterministic module. They all answer the same question: **How is a complete governed opportunity record represented safely for a bounded downstream consumer?**

The module should own:

- immutable source snapshots;
- stable source identities and prompt-local aliases;
- complete occurrence and provenance preservation;
- prompt-visible admission rules;
- sidecar construction;
- deterministic serialization;
- size accounting and guard enforcement;
- replay-safe validation of projection integrity.

The projection is a transport representation, not intelligence and not a brief.

### 2.2 Narrative contract, narrative response validation, and provider execution

If model-authored narrative remains in the system, its request schema, invocation policy, and response validator belong together as one optional component. The component should accept a governed understanding contract and return only the narrative fields it is authorized to express.

Its failure must be explicit. It must not weaken citation integrity, repair unsupported claims, or mutate upstream facts. It should not own deterministic authoritative sections or the existence of the Executive Opportunity Brief.

### 2.3 Authoritative view assembly and authority verification

Deterministic assembly of authoritative facts, computed facts, conflicts, and typed analytical outputs belongs together. This module should verify that every reference closes against its owning evidence domain and that no downstream value changes upstream meaning.

It should produce a presentation-ready view model without selecting a decision, ranking a finding, or resolving an unknown.

### 2.4 Rendering and export

Markdown, HTML, DOCX, and PDF rendering naturally belong together as presentation adapters over the same immutable view model. Layout, pagination, typography, headings, tables, labels, and navigation are rendering concerns. They must not create or reinterpret facts.

## 3. Responsibilities that should become separate modules

The following module boundaries are recommended for a future governed architecture review.

### 3.1 Opportunity Evidence Projection

**Purpose:** Provide complete, compact, consumer-specific representations of governed opportunity evidence.

**Authority:** None to interpret. It may transform representation while preserving identity, meaning, occurrence count, provenance, conflicts, and authoritative sidecar content.

**Inputs:** Canonical Opportunity, normalized requirements, evaluation hierarchy, submission projection, Contract Hygiene entities, conflicts, and provenance.

**Outputs:** Immutable projection plus authoritative sidecar, integrity diagnostics, and coverage measurements.

**Failure behavior:** Fail closed on omission, identity collision, unresolved references, unsupported versions, or capacity overflow.

This module generalizes the strongest part of current Stage D without coupling it to a model or a brief.

### 3.2 Executive Opportunity Understanding

**Purpose:** Provide the smallest complete executive mental model of the opportunity while preserving access to the exhaustive governed record.

**Authority:** A governed view within Opportunity Intelligence. It is not another analyst and does not acquire authority over canonical facts.

**Inputs:** Authoritative opportunity entities and validated `DecisionAnalysis` outputs from Opportunity Intelligence.

**Outputs:** An immutable, typed contract containing separate collections for:

- authoritative facts;
- deterministic computed facts;
- evidence-backed analyst findings;
- assumptions;
- conflicts;
- unknowns and evidence gaps;
- alternative interpretations;
- management considerations and questions;
- limitations;
- coverage and traceability links to the complete evidence register.

The contract should organize rather than summarize away. It may apply deterministic inclusion and grouping rules based on semantic type, authority, and executive section. It must not use hidden relevance scores, AI ranking, or narrative preference to decide what deserves attention.

### 3.3 Executive Narrative Adapter

**Purpose:** Express an already governed Executive Opportunity Understanding in readable prose when prose is needed.

**Authority:** Presentation only. It cannot add facts, interpretations, assumptions, priorities, recommendations, or decisions.

**Permitted implementation:** Deterministic sentence templates over typed fields, or human-authored wording attached to governed statement IDs. This review does not recommend adding AI summarization.

**Outputs:** Narrative fragments whose source statement IDs remain explicit.

**Failure behavior:** A narrative failure omits or flags the affected prose fragment; it does not invalidate the underlying understanding or authoritative sections.

The term “narrative” should not imply analytical authority. If that ambiguity cannot be controlled, the narrower name **Executive Brief Text Adapter** would be preferable.

### 3.4 Executive Brief View Assembly

**Purpose:** Convert Executive Opportunity Understanding and optional narrative fragments into a deterministic presentation model.

**Authority:** None to reason. It preserves the ordering, labels, grouping, and evidence links defined by the brief contract.

This module should own section composition, compact tables, drill-down references, appendix links, and explicit empty or unavailable states. It should not decide which competing hypothesis is correct.

### 3.5 Brief Renderers

**Purpose:** Render the same view model to Markdown, HTML, DOCX, PDF, or user-interface components.

**Authority:** None. Renderers may paginate, style, wrap, and create navigation. They may not alter content, confidence, scope, conflict state, or evidence relationships.

### 3.6 Optional proposal-structure component

The current proposal outline does not naturally belong in executive opportunity understanding or brief rendering. If the product retains proposal-structure support, it should be an explicitly invoked downstream capability with its own contract and doctrinal review. It should not determine whether an opportunity can be understood or whether an Executive Opportunity Brief can render.

## 4. Should Executive Understanding become a first-class intelligence layer?

Yes, with a precise boundary: **Executive Opportunity Understanding should become a first-class governed contract inside the Opportunity Intelligence pillar, not a new autonomous analyst.**

Opportunity Intelligence already establishes facts, deterministic computations, evidence-backed observations, bounded inferences, hypotheses, unknowns, alternatives, limitations, and management questions. Executive Understanding should select no winner among those objects and should add no new inference. Its value is to provide a stable executive-scale organization of that validated analysis.

Making the contract first-class would solve three current problems.

First, it would give downstream briefs a stable semantic input independent of a particular model response. Second, it would let validation occur at the level of typed statements and evidence closure before prose exists. Third, it would let the product distinguish successful understanding from successful rendering or optional narrative expression.

The contract must remain immutable and versioned. It must retain links to the exhaustive evidence register and expose coverage so that a compact executive view cannot be mistaken for the complete procurement record.

Executive Understanding must never contain:

- Bid / No Bid direction;
- win probability;
- hidden prioritization;
- composite scoring;
- chosen alternatives where evidence remains conflicted;
- bidder capability claims without a future authoritative capability source;
- commercial acceptance;
- invented management decisions.

## 5. Should brief rendering become purely presentational?

Yes.

Brief rendering should consume a validated, immutable view model and perform only deterministic presentation operations. It should never call a model, inspect raw procurement text to form a new conclusion, infer importance, resolve conflicts, merge analyst findings, or change evidence wording.

Pure rendering supports multiple channels without semantic drift. The Markdown brief, web view, DOCX, and PDF can differ in layout while remaining provably equivalent in content and references.

The renderer should be allowed to:

- apply headings and typography;
- paginate and wrap content;
- render tables, labels, and status markers;
- create links from statements to evidence;
- collapse or expand detail in interactive views;
- move exhaustive registers to appendices while preserving coverage and navigation;
- state that a section is empty, unavailable, conflicted, or incomplete.

It should not be allowed to paraphrase, summarize, rank, suppress, or reinterpret content.

## 6. Enterprise-scale procurement support

The proposed separation improves enterprise-scale behavior because each layer scales according to its actual responsibility.

### 6.1 Complete evidence no longer competes with executive readability

The evidence corpus can remain exhaustive in its authoritative store and sidecar. Executive Understanding can reference that corpus through stable IDs, coverage measures, and drill-down links. The customer receives a usable mental model without treating omission from the first page as deletion from the governed record.

### 6.2 Narrative failure no longer blocks deterministic understanding

The Bank of Canada run showed that a valid 413-requirement projection and a valid Opportunity Intelligence analysis could be held hostage by an invalid narrative citation. Separate contracts would allow authoritative facts, computations, unknowns, conflicts, and management questions to render even when optional narrative text is unavailable.

Failing closed would remain mandatory at the affected boundary. The system would report that narrative is unavailable rather than accepting unsupported prose, while still preserving valid upstream understanding.

### 6.3 Capacity becomes independently measurable

Projection size, analytical object count, executive-view size, and rendering size could be measured separately. Capacity limits would identify the actual constrained component instead of describing the entire output path as “Stage D.”

### 6.4 Different consumers can use the same authority-bearing contract

An executive brief, detailed bid-manager view, kickoff pack, and evidence browser can consume the same Executive Opportunity Understanding without each recreating intelligence. Differences remain presentational and role-specific, not semantic.

### 6.5 Replay and audit become clearer

Each artifact would declare its input digest, contract version, and derivation. Replaying a projection would not imply rerunning analysis. Re-rendering a brief would not imply creating new intelligence. A failed narrative attempt would remain an operational record rather than contaminating the authoritative opportunity state.

## 7. Alignment with repository doctrine

### Human judgment remains sovereign

The proposed separation prepares executives to deliberate. It does not recommend a pursuit decision, rank findings, score the opportunity, or replace accountable professional judgment.

### Evidence remains prior to inference

Authoritative evidence and canonical facts remain owned by their existing domains. Opportunity Intelligence may produce typed reasoning under its existing contract. Executive Understanding organizes those outputs without changing their authority. Narrative and rendering cannot create new claims.

### Presentation performs no reasoning

The recommendation directly implements the founding decision that the Decision Workspace is the human interaction boundary and that presentation cannot become another analyst. Brief renderers become deterministic consumers of validated contracts.

### Facts, computations, interpretations, assumptions, conflicts, and unknowns remain separate

Executive Understanding should preserve these as separate typed collections. A polished narrative cannot flatten them into one confident account.

### Failure remains explicit and local

Projection failure blocks projection. Analytical validation failure blocks the affected analysis. Narrative validation failure blocks narrative. Rendering failure blocks the requested format. No layer silently repairs, truncates, or reclassifies another layer’s output.

### Opportunity and Buyer Intelligence remain separate

Executive Opportunity Understanding remains within Opportunity Intelligence. Buyer Understanding remains governed by Buyer Intelligence and its own evidence domain. The Bid Intelligence Briefing Pack may present both perspectives together, but neither layer merges their facts or reasoning.

### Proposal generation remains outside the competitive center

Separating proposal-outline construction from Stage D prevents proposal structure from becoming a prerequisite for opportunity understanding. It preserves the product’s focus on decision preparation rather than generated writing.

## Architectural conclusion

The Stage D label now conceals several layers with incompatible authority. The deterministic projection and strict validators are durable assets, but they should not define whether executives can receive a governed opportunity understanding. Opportunity Intelligence already supplies the correct analytical foundation.

The preferred future direction is:

```text
Authoritative Opportunity Domains
            ↓
Opportunity Evidence Projection
            ↓
Opportunity Intelligence Analysis
            ↓
Executive Opportunity Understanding
            ↓
Executive Brief View Assembly
            ↓
Deterministic Brief Renderers
```

An optional, non-AI Executive Brief Text Adapter may sit between understanding and view assembly when deterministic prose is useful. Buyer Intelligence and Buyer Brief retain their parallel governed path and join the Executive Opportunity Brief only at the Briefing Pack presentation boundary.

This separation would let Bid Intelligence help experienced professionals construct an accurate mental model quickly while keeping the complete evidence record, uncertainty, alternatives, and human authority intact.

## Review disposition

The architectural concern is substantiated. Stage D should be considered a candidate for decomposition through a future formal architecture decision and compatibility plan. This review makes no implementation change and grants no authority to alter existing Stage D behavior.
