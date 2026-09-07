# Document Metadata

| Field | Value |
|---|---|
| Document | `docs/product/CUSTOMER_WORKFLOW.md` |
| Title | Customer Pursuit Workflow Reference Model |
| Authority Level | Level 3 — Product Doctrine |
| Version | 1.0.0 |
| Status | Ratified |
| Purpose | Define the real pursuit workflow the product supports and the human role at every stage. |
| Higher Authority | [`MANIFESTO.md`](../../MANIFESTO.md), [`AGENT.md`](../../AGENT.md), [`GOVERNANCE.md`](../../GOVERNANCE.md), [`ANTI_GOALS.md`](../../ANTI_GOALS.md) |
| Governed Documents | Workflow design, product navigation, feature placement, hand-offs, and stage-level requirements. |
| Related Documents | [`PRODUCT_VISION.md`](PRODUCT_VISION.md), [`PRODUCT_PRINCIPLES.md`](PRODUCT_PRINCIPLES.md), [`CUSTOMER_PERSONAS.md`](CUSTOMER_PERSONAS.md), [`PRODUCT_ROADMAP.md`](PRODUCT_ROADMAP.md) |

# Customer Pursuit Workflow

This is the reference workflow for feature design:

```text
Receive RFP
  → Opportunity Intelligence
  → Buyer Intelligence
  → Select previous proposal(s)
  → Existing AI tools customize proposal
  → Proposal Compliance Intelligence
  → Executive Review
  → Submission
  → Outcome
  → Organizational Intelligence
```

The stages describe responsibility and information flow. They do not require one rigid sequence when a live pursuit demands iteration.

## 1. Receive RFP

- **Purpose:** Establish a controlled source package and the scope of the opportunity.
- **Primary users:** Bid Manager, Proposal Manager.
- **Questions:** What was received? Is the package complete? Which version is authoritative?
- **Information required:** RFP files, attachments, amendments, receipt context, and source identity.
- **Outputs:** Traceable source package and identified ingestion issues.
- **Bid Intelligence contribution:** Preserves source identity, extracts supported formats, and makes provenance available downstream.
- **Human judgment:** Users confirm package completeness and obtain missing or corrected documents.

## 2. Opportunity Intelligence

- **Purpose:** Understand what the opportunity asks of the firm.
- **Primary users:** Bid Manager, Senior Consultant, CEO / Managing Partner.
- **Questions:** What is required? How is it evaluated? What must be submitted, delivered, and accepted commercially? What conflicts or gaps remain?
- **Information required:** Authoritative procurement package and amendments.
- **Outputs:** Canonical opportunity facts, requirements, criteria, submission rules, dates, commercial clauses, deliverables, conflicts, and structured analysis.
- **Bid Intelligence contribution:** Organizes evidence, computes structural indicators, preserves uncertainty, and prepares management questions.
- **Human judgment:** Leaders interpret strategic significance, seek clarification, assess organizational implications, and decide whether to proceed.

## 3. Buyer Intelligence

- **Purpose:** Understand the buyer through observable evidence.
- **Primary users:** CEO / Managing Partner, Bid Manager, Senior Consultant.
- **Questions:** What is known about the buyer’s context and procurement behavior? Which patterns are documented, and which are only hypotheses?
- **Information required:** Current buyer materials and governed historical evidence.
- **Outputs:** Evidence-linked buyer observations, patterns, alternative interpretations, limitations, and questions.
- **Bid Intelligence contribution:** Separates observed history from inference and makes provenance inspectable.
- **Human judgment:** Professionals judge relevance, relationship context, ethical boundaries, and how much weight historical patterns deserve.

## 4. Select previous proposal(s)

- **Purpose:** Choose relevant organizational experience for the response.
- **Primary users:** Proposal Manager, Bid Manager, Senior Consultant.
- **Questions:** Which prior work is substantively relevant? What can be reused responsibly? What is stale or client-specific?
- **Information required:** Prior proposals, outcomes, delivery evidence, permissions, and current requirements.
- **Outputs:** Human-selected reference material and reuse boundaries.
- **Bid Intelligence contribution:** Retrieves and compares traceable prior material without selecting the final source set.
- **Human judgment:** Users choose relevance, approve reuse, and protect confidentiality.

## 5. Existing AI tools customize proposal

- **Purpose:** Draft and adapt the proposal using the firm’s chosen working methods.
- **Primary users:** Proposal Manager / Proposal Writer, Senior Consultant, Subject Matter Expert.
- **Questions:** How should the response articulate the firm’s approach and evidence?
- **Information required:** Current requirements, selected prior material, firm methods, case evidence, and author instructions.
- **Outputs:** Proposal draft.
- **Bid Intelligence contribution:** Supplies authoritative context and traceability to the surrounding workflow.
- **Human judgment:** Authors control claims, voice, methods, evidence, confidentiality, and final wording. Bid Intelligence does not seek to replace the writing tool.

## 6. Proposal Compliance Intelligence

- **Purpose:** Verify the completed draft against the buyer’s request.
- **Primary users:** Bid Manager, Proposal Manager, Senior Consultant.
- **Questions:** Is every requirement addressed? Is supporting evidence present? Are evaluation, commercial, and submission obligations covered? What remains missing or ambiguous?
- **Information required:** Authoritative opportunity record, proposal draft, and submission package.
- **Outputs:** Traceable coverage findings, gaps, conflicts, and verification status.
- **Bid Intelligence contribution:** Compares the response to authoritative requirements without predicting whether it will win.
- **Human judgment:** Users decide how to correct gaps, accept residual risk, and allocate review effort.

## 7. Executive Review

- **Purpose:** Make accountable pursuit and release judgments.
- **Primary users:** CEO / Managing Partner, Bid Manager, Commercial / Finance.
- **Questions:** Should the firm commit? Are the approach, obligations, economics, risk, and submission state acceptable?
- **Information required:** Prepared decision workspace, proposal, compliance findings, commercial review, resource view, and unresolved questions.
- **Outputs:** Human decisions, conditions, approvals, or rejection with accountable rationale.
- **Bid Intelligence contribution:** Presents validated facts, findings, alternatives, unknowns, and questions without choosing an outcome.
- **Human judgment:** Executives own every decision and its consequences.

## 8. Submission

- **Purpose:** Release the correct, complete package through the required channel and retain evidence of submission.
- **Primary users:** Bid Manager, Proposal Manager.
- **Questions:** Are files final, correctly named, authorized, and submitted before the deadline?
- **Information required:** Approved package, submission rules, deadline, channel, and release authority.
- **Outputs:** Submitted package, receipt, and submission record.
- **Bid Intelligence contribution:** Supports deterministic checks and control records.
- **Human judgment:** An authorized person releases the submission and handles exceptions.

## 9. Outcome

- **Purpose:** Record what happened without rewriting the earlier decision record.
- **Primary users:** Bid Manager, CEO / Managing Partner, Commercial / Finance.
- **Questions:** What was the official result? What feedback and scores were provided? What is fact versus interpretation?
- **Information required:** Award notice, evaluator feedback, debrief, commercial result, and internal record.
- **Outputs:** Authoritative outcome record and open learning questions.
- **Bid Intelligence contribution:** Links the outcome to the source opportunity, proposal, and decisions.
- **Human judgment:** Leaders interpret performance, relationships, and follow-up actions.

## 10. Organizational Intelligence

- **Purpose:** Convert experience into durable learning for later pursuits.
- **Primary users:** CEO / Managing Partner, Bid Manager, Senior Consultant, Proposal Manager.
- **Questions:** What recurring observations are supported? Which lessons can be reused? What remains uncertain across the portfolio?
- **Information required:** Historical RFPs, proposals, decisions, outcomes, and buyer debriefs.
- **Outputs:** Evidence-linked organizational observations, hypotheses, lessons, and questions.
- **Bid Intelligence contribution:** Preserves longitudinal relationships and exposes patterns without presenting correlation as causation or predicting winners.
- **Human judgment:** Leaders decide which lessons alter practice and when historical context is relevant.

Feature proposals should identify their workflow stage, input authority, output, hand-off, and responsible human persona. Persona responsibilities are defined in [`CUSTOMER_PERSONAS.md`](CUSTOMER_PERSONAS.md).
