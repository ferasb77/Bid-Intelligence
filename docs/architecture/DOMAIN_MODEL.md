# Document Metadata

| Field | Value |
|---|---|
| Document | `docs/architecture/DOMAIN_MODEL.md` |
| Title | Canonical Domain Vocabulary |
| Authority Level | Level 4 — Architecture Doctrine |
| Version | 1.0.0 |
| Status | Ratified |
| Purpose | Establish stable meanings, relationships, and ownership for core Bid Intelligence concepts. |
| Higher Authority | [`MANIFESTO.md`](../../MANIFESTO.md), [`AGENT.md`](../../AGENT.md), [`GOVERNANCE.md`](../../GOVERNANCE.md), [`ANTI_GOALS.md`](../../ANTI_GOALS.md), [`PRODUCT_VISION.md`](../product/PRODUCT_VISION.md), [`PRODUCT_PRINCIPLES.md`](../product/PRODUCT_PRINCIPLES.md), [`CUSTOMER_WORKFLOW.md`](../product/CUSTOMER_WORKFLOW.md), [`CUSTOMER_PERSONAS.md`](../product/CUSTOMER_PERSONAS.md), [`COMPETITIVE_POSITIONING.md`](../product/COMPETITIVE_POSITIONING.md), [`PRODUCT_ROADMAP.md`](../product/PRODUCT_ROADMAP.md) |
| Governed Documents | Domain contracts, schemas, specifications, interfaces, user language, and analytical outputs. |
| Related Documents | [`ARCHITECTURE.md`](ARCHITECTURE.md), [`DECISION_DOCTRINE.md`](DECISION_DOCTRINE.md), [`DESIGN_PRINCIPLES.md`](DESIGN_PRINCIPLES.md) |

# Canonical Domain Vocabulary

Terms in this document describe enduring concepts, not storage or interface shapes. Architectural ownership names the layer responsible for a concept’s meaning and validity.

## Procurement and organizational concepts

### Opportunity

- **Meaning:** A bounded invitation or possibility for the firm to provide professional services.
- **Purpose:** The primary unit around which current-pursuit evidence is organized.
- **Relationships:** Issued by a Buyer; contains Requirements, Evaluation Criteria, Commercial Clauses, Deliverables, and submission obligations; may lead to a Proposal, Human Decision, and Outcome.
- **Architectural ownership:** Canonical Truth owns its authoritative identity; Opportunity Intelligence owns its analysis.

### Buyer

- **Meaning:** The organization seeking or purchasing the services.
- **Purpose:** Anchor current and historical evidence about the issuing organization.
- **Relationships:** Issues Opportunities, evaluates Proposals, produces Outcomes, and may provide Buyer Debriefs.
- **Architectural ownership:** Canonical Truth owns verified identity; Buyer Intelligence owns buyer analysis.

### Requirement

- **Meaning:** A traceable statement of something the buyer requires, requests, constrains, or expects.
- **Purpose:** Establish obligations and response scope without collapsing distinct occurrences.
- **Relationships:** Supported by Evidence; may relate to Evaluation Criteria, Deliverables, Proposal Responses, Compliance, and Coverage.
- **Architectural ownership:** Opportunity Intelligence domain authority, grounded in Canonical Truth.

### Evaluation Criterion

- **Meaning:** A documented basis, weight, threshold, gate, or hierarchy used to assess a response.
- **Purpose:** Preserve how the buyer says evaluation will occur.
- **Relationships:** May reference Requirements and Proposal Responses; informs Compliance but does not predict success.
- **Architectural ownership:** Opportunity Intelligence domain authority.

### Commercial Clause

- **Meaning:** A sourced contractual or commercial provision relevant to the opportunity.
- **Purpose:** Expose authoritative terms for professional review without inventing legal interpretation.
- **Relationships:** Supported by Evidence; may concern money, term, liability, insurance, intellectual property, payment, or other obligations.
- **Architectural ownership:** Canonical Truth owns the fact; qualified humans own legal and commercial judgment.

### Deliverable

- **Meaning:** A documented output, service result, artifact, or recurring obligation expected from delivery.
- **Purpose:** Make the buyer’s requested outputs traceable and distinguish them from interpreted risk.
- **Relationships:** May satisfy Requirements, shape a Proposal Response, and later support delivery or Outcome learning.
- **Architectural ownership:** Opportunity Intelligence domain authority.

### Proposal

- **Meaning:** The firm’s complete response to an Opportunity.
- **Purpose:** Represent what the firm intends to submit and, if awarded, may be expected to honor.
- **Relationships:** Contains Proposal Responses; is checked through Compliance; may be submitted, evaluated, and linked to an Outcome.
- **Architectural ownership:** Human authors own its claims; Proposal Compliance Intelligence owns verification against the Opportunity.

### Proposal Response

- **Meaning:** A bounded part of a Proposal that addresses one or more Requirements or Evaluation Criteria.
- **Purpose:** Provide the unit of traceable proposal coverage.
- **Relationships:** Belongs to a Proposal; links to Requirements, Evaluation Criteria, and supporting Evidence.
- **Architectural ownership:** Human authors own content; Proposal Compliance Intelligence owns coverage assessment.

### Outcome

- **Meaning:** The authoritative result of a pursuit, including issued decision, supplied scores, and known commercial result.
- **Purpose:** Close the factual pursuit record and enable later learning.
- **Relationships:** Follows an Opportunity and Proposal; may include a Buyer Debrief; contributes to Organizational Learning.
- **Architectural ownership:** Canonical Truth owns outcome facts; Organizational Intelligence owns longitudinal analysis.

### Buyer Debrief

- **Meaning:** Feedback attributable to the buyer after an Outcome.
- **Purpose:** Preserve direct buyer evidence separately from the firm’s interpretation.
- **Relationships:** Linked to the Buyer, Opportunity, Proposal, and Outcome; may support later Observations and Hypotheses.
- **Architectural ownership:** Canonical Truth owns sourced content; Organizational Intelligence owns cross-pursuit analysis.

### Organizational Learning

- **Meaning:** Evidence-linked knowledge developed across multiple pursuits and outcomes.
- **Purpose:** Make experience reusable without turning historical correlation into deterministic prediction.
- **Relationships:** Draws from historical RFPs, Proposals, Human Decisions, Outcomes, and Buyer Debriefs.
- **Architectural ownership:** Organizational Intelligence.

## Epistemic concepts

### Evidence

- **Meaning:** A traceable representation of Reality from an attributable source.
- **Purpose:** Ground facts, computations, and reasoning in inspectable material.
- **Relationships:** Supports Source Facts, Observations, Requirements, and analytical conclusions; retains provenance.
- **Architectural ownership:** Evidence layer.

### Source Fact

- **Meaning:** A proposition directly supported by authoritative Evidence without analytical interpretation.
- **Purpose:** State what a source establishes while preserving its authority and provenance.
- **Relationships:** May be reconciled into Canonical Truth and used by Computed Facts or Inferences.
- **Architectural ownership:** Evidence and Canonical Truth layers.

### Computed Fact

- **Meaning:** A deterministic result produced from identified authoritative inputs.
- **Purpose:** Make counts, intervals, coverage measures, and other reproducible derivations available without calling them interpretation.
- **Relationships:** Depends on Source Facts or canonical entities; may support an Inference.
- **Architectural ownership:** The bounded deterministic capability that defines the computation.

### Observation

- **Meaning:** A typed, evidence-linked record of something found or measured without asserting a broader explanation.
- **Purpose:** Preserve granular occurrences and enable comparison while avoiding premature conclusions.
- **Relationships:** May support Canonical Truth, Computed Facts, Inferences, and Organizational Learning.
- **Architectural ownership:** The intelligence domain that defines the observation, with evidence authority retained upstream.

### Inference

- **Meaning:** A transparent interpretation drawn from identified facts or observations.
- **Purpose:** Help humans examine relationships and implications without presenting them as source truth.
- **Relationships:** Links to Evidence and facts; declares confidence, assumptions, limitations, alternatives, and unknowns as applicable.
- **Architectural ownership:** A named analyst or bounded reasoning capability.

### Assumption

- **Meaning:** A proposition accepted provisionally so reasoning can proceed.
- **Purpose:** Expose a dependency that evidence has not established.
- **Relationships:** Belongs to an Inference, Hypothesis, plan, or Human Decision; may later be confirmed or rejected.
- **Architectural ownership:** The reasoning or human process that relies on it.

### Unknown

- **Meaning:** Information that is missing, unavailable, ambiguous, conflicted, or not established.
- **Purpose:** Prevent absence of knowledge from being disguised as certainty.
- **Relationships:** May block validation, qualify Inferences, create Management Questions, or remain open after a Human Decision.
- **Architectural ownership:** The layer that discovers it; no downstream layer may erase it silently.

### Hypothesis

- **Meaning:** A possible explanation presented for examination rather than acceptance.
- **Purpose:** Preserve competing interpretations and make uncertainty discussable.
- **Relationships:** Identifies supporting and contradicting Evidence, confidence, assumptions, and limitations; may prompt a Management Question.
- **Architectural ownership:** A named analyst or human author.

## Compliance and decision concepts

### Compliance

- **Meaning:** The state of conformity between a Proposal or submission package and an authoritative requirement.
- **Purpose:** Establish whether requested content or mechanics have been addressed.
- **Relationships:** Evaluated through Coverage across Requirements, Evaluation Criteria, commercial obligations, evidence, and submission rules.
- **Architectural ownership:** Proposal Compliance Intelligence.

### Coverage

- **Meaning:** A traceable relationship showing whether and where a governed item is addressed.
- **Purpose:** Make completeness inspectable at the individual-item level.
- **Relationships:** Links Requirements or criteria to Proposal Responses and supporting Evidence; contributes to Compliance.
- **Architectural ownership:** The domain performing the comparison. Coverage is not quality, competitiveness, or predicted success.

### Decision Workspace

- **Meaning:** A deterministic presentation of validated analyses for human deliberation.
- **Purpose:** Arrange what is known, computed, inferred, assumed, unknown, and questioned without creating new analysis.
- **Relationships:** Receives analyst outputs; preserves analyst boundaries; precedes Human Judgment.
- **Architectural ownership:** Presentation layer.

### Management Question

- **Meaning:** An unanswered question requiring organizational or executive judgment.
- **Purpose:** Direct human attention to a decision dependency without prescribing an answer.
- **Relationships:** May arise from an Unknown, Inference, Hypothesis, conflict, or limitation; appears in the Decision Workspace.
- **Architectural ownership:** Analysts may raise it; humans own its disposition.

### Human Decision

- **Meaning:** An accountable choice made by an authorized person.
- **Purpose:** Record commitment, rationale, conditions, and ownership without attributing the choice to the system.
- **Relationships:** Follows Human Deliberation; may consider evidence, analyses, recommendations, and unknowns; later contributes to Organizational Learning.
- **Architectural ownership:** The named human decision-maker.

Facts describe supported reality. Reasoning interprets facts. Decisions commit people and resources. These categories may reference one another, but they never inherit one another’s authority.
