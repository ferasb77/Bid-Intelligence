# Document Metadata

| Field | Value |
|---|---|
| Document | `docs/architecture/ARCHITECTURE.md` |
| Title | Bid Intelligence Architecture Doctrine |
| Authority Level | Level 4 — Architecture Doctrine |
| Version | 1.0.0 |
| Status | Ratified |
| Purpose | Define the enduring conceptual layers, information flow, and authority boundaries of Bid Intelligence. |
| Higher Authority | [`MANIFESTO.md`](../../MANIFESTO.md), [`AGENT.md`](../../AGENT.md), [`GOVERNANCE.md`](../../GOVERNANCE.md), [`ANTI_GOALS.md`](../../ANTI_GOALS.md), [`PRODUCT_VISION.md`](../product/PRODUCT_VISION.md), [`PRODUCT_PRINCIPLES.md`](../product/PRODUCT_PRINCIPLES.md), [`CUSTOMER_WORKFLOW.md`](../product/CUSTOMER_WORKFLOW.md), [`CUSTOMER_PERSONAS.md`](../product/CUSTOMER_PERSONAS.md), [`COMPETITIVE_POSITIONING.md`](../product/COMPETITIVE_POSITIONING.md), [`PRODUCT_ROADMAP.md`](../product/PRODUCT_ROADMAP.md) |
| Governed Documents | Domain architecture, component design, data contracts, interface specifications, and implementation architecture. |
| Related Documents | [`DOMAIN_MODEL.md`](DOMAIN_MODEL.md), [`DECISION_DOCTRINE.md`](DECISION_DOCTRINE.md), [`DESIGN_PRINCIPLES.md`](DESIGN_PRINCIPLES.md) |

# Architecture Doctrine

Bid Intelligence is an evidence-governed Decision Preparation Platform. Its architecture preserves the distinction between what exists in the world, what sources say, what the platform can establish, what analysts infer, and what humans decide.

Its enduring flow is:

```text
Reality
  ↓
Evidence
  ↓
Canonical Truth
  ↓
Opportunity Intelligence
  ↓
Buyer Intelligence
  ↓
Proposal Compliance Intelligence
  ↓
Organizational Intelligence
  ↓
Decision Workspace
  ↓
Human Judgment
```

The flow expresses authority, not necessarily elapsed time. Intelligence pillars may operate in parallel or revisit earlier evidence, but no later layer may silently rewrite an earlier layer.

## Reality

Reality is the opportunity, buyer, organization, proposal, submission, and outcome as they actually exist. The platform never possesses reality directly. It encounters representations of reality through evidence.

This distinction prevents the system from treating its own record as complete merely because that record is internally consistent.

## Evidence

Evidence is a traceable representation supplied by a source: a document passage, structured record, issued amendment, proposal section, outcome notice, debrief, or other attributable material.

Evidence retains identity, provenance, location, and relevant status. Transformation may improve access to evidence, but it must not sever the path back to the source. Absence of evidence is not evidence of absence.

## Canonical Truth

Canonical Truth is the platform’s authoritative account of what the available evidence supports. It reconciles equivalent observations, preserves disagreement, and distinguishes resolved facts from conflicts and unknowns.

Canonical does not mean infallible or complete. It means that downstream work has one governed authority for the present evidence state. New evidence may revise that authority through an explicit, traceable transition.

## Intelligence pillars

The four intelligence pillars consume authoritative evidence and canonical facts for different purposes.

### Opportunity Intelligence

Organizes what the opportunity requires: requirements, evaluation, submission, dates, commercial terms, deliverables, dependencies, conflicts, and structural characteristics. It answers, “What does this opportunity look like?” It does not decide whether to pursue it.

### Buyer Intelligence

Organizes what evidence shows about the buyer and its observable behavior. It preserves the boundary between recorded history and interpretation. Patterns may create hypotheses or questions; they do not establish intent or predict an outcome.

### Proposal Compliance Intelligence

Compares a completed proposal and submission package with authoritative opportunity requirements. It establishes coverage and gaps. It does not equate completeness with quality, competitiveness, or probable success.

### Organizational Intelligence

Connects historical RFPs, proposals, decisions, outcomes, and buyer debriefs so that learning can compound. It exposes recurring observations and alternative explanations without converting correlation into causation.

The pillars may share evidence but retain separate analytical responsibilities. One pillar must not acquire another’s authority through convenience.

## Decision Workspace

The Decision Workspace is a presentation boundary. It arranges validated facts, computations, findings, assumptions, unknowns, hypotheses, limitations, and management questions while preserving their analyst and authority boundaries.

It performs no synthesis, scoring, ranking, prioritization, recommendation, or decision. Its purpose is to make the state of knowledge inspectable for human deliberation.

## Human Judgment

Human Judgment is the final layer because accountability cannot be delegated to information processing. Executives and experienced professionals interpret context, accept obligations, choose strategy, commit resources, and authorize action.

The architecture succeeds when it improves the quality and traceability of that judgment without claiming the authority to replace it.

## AI is not an architectural layer

AI is one possible mechanism inside a bounded capability. It may help extract, organize, compare, link evidence, recognize patterns, or produce transparent reasoning. The same architectural duties apply whether a capability uses AI, deterministic rules, or human input.

Making AI a layer would give a technique implied authority over information. Instead, each output is governed by its semantic type, evidence, validation, and owner. A source fact remains a source fact; an inference remains an inference, regardless of how it was produced.

## Boundaries

- Evidence acquisition cannot confer canonical authority by itself.
- Canonical reconciliation cannot erase source disagreement.
- Computation cannot become interpretation through presentation.
- Intelligence analysis cannot mutate authoritative inputs or resolve conflicts outside its mandate.
- One analyst cannot silently merge or overrule another analyst’s finding.
- Presentation cannot introduce new reasoning.
- Recommendations cannot acquire executive authority.
- Human decisions cannot be rewritten as system conclusions.

These boundaries are elaborated in [`DECISION_DOCTRINE.md`](DECISION_DOCTRINE.md) and named consistently in [`DOMAIN_MODEL.md`](DOMAIN_MODEL.md).

## Fail closed

When identity, provenance, authority, compatibility, or validation cannot be established, the affected transition stops. The platform exposes the failure or uncertainty rather than inventing a value, silently repairing meaning, dropping inconvenient evidence, or continuing with an apparently complete result.

Fail-closed behavior is scoped. Invalid material should not corrupt valid authoritative material, and a conflict in one field should not suppress an unrelated field. The architecture preserves as much verified evidence as it can without pretending the invalid portion is safe.

## Evidence preservation

Evidence must remain available through every derived layer that relies on it. Derived objects link to stable evidence or authoritative entity identities rather than copying unattributed prose. Deduplication may identify equivalence but must preserve every meaningful occurrence and its provenance. Diagnostic sidecars may carry detail omitted from a bounded presentation, but omission from presentation must never mean deletion from the authoritative record.

This architecture remains valid as implementations change because its subject is authority: what each layer may know, transform, present, and decide.
