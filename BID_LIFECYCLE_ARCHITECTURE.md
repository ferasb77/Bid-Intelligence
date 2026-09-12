# Document Metadata

| Field | Value |
|---|---|
| Document | `BID_LIFECYCLE_ARCHITECTURE.md` |
| Title | Canonical Bid Lifecycle Architecture |
| Authority Level | Level 4 — Architecture Specification |
| Version | 1.0.0 |
| Status | Proposed |
| Purpose | Define the governed lifecycle of one procurement opportunity from receipt through outcome, retrospective, and organizational-learning handoff. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md), [`AGENT.md`](AGENT.md), [`GOVERNANCE.md`](GOVERNANCE.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), [Product Doctrine](docs/product/PRODUCT_VISION.md), [Architecture Doctrine](docs/architecture/ARCHITECTURE.md), [Engineering Doctrine](docs/engineering/CONTRIBUTING.md), [`BID_INTELLIGENCE_BRIEFING_PACK.md`](BID_INTELLIGENCE_BRIEFING_PACK.md), and [`BID_WORKSPACE_ARCHITECTURE.md`](BID_WORKSPACE_ARCHITECTURE.md) |
| Governed Documents | Future lifecycle contracts, capability-participation specifications, milestone policies, transition rules, implementation designs, validation plans, and acceptance reviews. |
| Related Documents | [`CUSTOMER_WORKFLOW.md`](docs/product/CUSTOMER_WORKFLOW.md), [`DOMAIN_MODEL.md`](docs/architecture/DOMAIN_MODEL.md), [`DECISION_DOCTRINE.md`](docs/architecture/DECISION_DOCTRINE.md), [`OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md`](OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md), [`BUYER_INTELLIGENCE_ARCHITECTURE.md`](BUYER_INTELLIGENCE_ARCHITECTURE.md), [`BUYER_EVIDENCE_ACQUISITION_ARCHITECTURE.md`](BUYER_EVIDENCE_ACQUISITION_ARCHITECTURE.md), and [`BUYER_BRIEF_ARCHITECTURE.md`](BUYER_BRIEF_ARCHITECTURE.md) |

# Canonical Bid Lifecycle Architecture

## Purpose

The Bid Lifecycle defines the governed progression of one procurement opportunity from receipt through preparation, human pursuit decisions, proposal work, verification, submission, outcome capture, retrospective, and organizational-learning handoff.

It answers **when** a capability may participate, which governed outputs and human acts establish a milestone, and what information state must remain visible at each transition. Each capability retains authority over **how** it performs its work.

The lifecycle coordinates. It does not acquire evidence, create canonical truth, perform intelligence, generate Briefs, manage collaboration records, write proposals, verify compliance, submit a bid, determine an Outcome, produce learning, or make a decision.

## Architectural position

```text
Procurement Opportunity
          ↓
     Bid Lifecycle
          ↓
 Bid Workspace state and milestones
          ↓
 Governed capability participation
          ↓
 Human deliberation and Human Decisions
          ↓
 Proposal production, review, and submission
          ↓
 Authoritative Outcome and attributed reflection
          ↓
 Organizational Intelligence and Institutional Learning
```

The arrows describe coordination and dependency. They do not transfer ownership. A lifecycle reference never becomes the evidence, analysis, Brief, proposal, submission, Outcome, reflection, or learning record it points to.

The lifecycle is not a workflow engine or mandatory automation sequence. It is a permanent semantic model for stages, milestone evidence, participation, transition authority, and historical reconstruction.

## Relationship to the Bid Workspace

The **Bid Lifecycle** defines the canonical stage and transition semantics for one opportunity. The **Bid Workspace** owns the opportunity-scoped collaboration records through which people coordinate assignments, reviews, readiness declarations, approvals, and Human Decision records.

The Workspace records lifecycle state and transition history under this architecture. The lifecycle does not own the Workspace, execute its actions, assign its members, or infer state from its task counts. Workspace activity supplies a lifecycle transition only through an explicit, validated milestone or human act.

Workspace states may use operational names aligned with lifecycle stages, but the two are not interchangeable. A Workspace can contain preparation work for a later stage while the lifecycle remains in an earlier stage, and a capability may refresh an earlier output during a later stage.

## Lifecycle concepts and ownership

### Lifecycle instance

One lifecycle instance is bound to exactly one Canonical Opportunity identity and one Bid Workspace identity. Its binding never changes. A reissued procurement with a different canonical opportunity identity requires a distinct lifecycle unless a future canonical rule explicitly establishes continuity.

The lifecycle instance owns only stage history, milestone references, transition records, participation records, and closure classification. It owns no substantive source, analytical, collaboration, proposal, submission, Outcome, or learning content.

### Stage

A stage is the dominant coordination context at a point in the pursuit. It declares a purpose, question, expected capabilities, human responsibilities, entry and exit criteria, and permitted transitions. A stage is not proof that its work is complete or that all relevant capabilities have stopped participating.

Only one stage is current for the canonical lifecycle projection. Concurrent capability work is represented by participation records and readiness dimensions, not multiple contradictory current stages.

### Milestone

A milestone is an immutable, attributable event supported by governed references. Examples include an accepted source-scope review, an issued Brief revision, a completed named human review, a Human Decision, a submission receipt, or an authoritative Outcome.

A milestone records what occurred. It does not imply a broader completion state unless a declared transition rule requires and validates it.

### Capability participation

A participation record identifies a capability, supported version, stage purpose, exact inputs and outputs referenced, participation status, human owner where applicable, and failure or partial-completion state. Participation never gives the lifecycle authority to invoke or reproduce the capability's logic.

### Readiness declaration

A readiness declaration is an item-level, owner-attributed description of a condition needed for a milestone or transition. It is not a score or prediction. Readiness belongs to the Bid Workspace collaboration record and is referenced by the lifecycle.

### Human act

Reviews, approvals, decisions, attestations, submission actions, reflections, and closure choices are separate human acts with separate authority. The lifecycle records their occurrence and references their immutable records; it cannot manufacture one from another.

## Lifecycle model

The canonical lifecycle contains fifteen stages. The normal forward path provides a reference sequence. Governed backward, bypass, early-close, and reopen transitions are defined later.

```text
RECEIVED
  → SOURCE_CONTROL
  → OPPORTUNITY_UNDERSTANDING
  → BUYER_UNDERSTANDING
  → KICKOFF_PREPARATION
  → PURSUIT_AUTHORIZATION
  → PROPOSAL_DEVELOPMENT
  → PROPOSAL_VERIFICATION
  → FINAL_REVIEW
  → SUBMISSION_AUTHORIZATION
  → SUBMISSION
  → OUTCOME_CAPTURE
  → PURSUIT_RETROSPECTIVE
  → LEARNING_HANDOFF
  → CLOSED
  → ARCHIVED
```

`ARCHIVED` is a retention state after the active lifecycle and is not counted as substantive pursuit work. Opportunity and Buyer preparation may overlap when their independent entry conditions are satisfied. A human No Bid, withdrawal, cancellation, or discontinued proposal may transition to `CLOSED` from an earlier stage with an explicit decision or authoritative event and a recorded retrospective disposition.

## Stage responsibilities

### 1. `RECEIVED`

- **Purpose:** establish that an identifiable procurement opportunity or invitation has entered the firm's controlled consideration.
- **Question:** What was received, from whom, when, and under which provisional opportunity identity?
- **Required governed inputs:** source occurrence or human intake record, receipt context, and provisional or canonical opportunity identity.
- **Capabilities expected:** controlled intake and safe document ingestion may participate; no intelligence is required.
- **Briefing Pack volumes:** none.
- **Human responsibilities:** Bid Manager confirms intake ownership, source custody, and whether the material belongs to one opportunity.
- **Required reviews:** receipt and identity review.
- **Required approvals:** none unless organizational intake policy requires one.
- **Entry criteria:** an attributable receipt event exists.
- **Exit criteria:** one opportunity scope and controlled source-package boundary are declared, or intake is rejected explicitly.
- **Permitted transitions:** `SOURCE_CONTROL` or `CLOSED` for duplicate, out-of-scope, cancelled, or human-declined intake.
- **Blocked conditions:** missing source occurrence, irreconcilable opportunity identity, unsafe material without controlled handling, or no accountable intake owner.
- **Information consumed:** received source occurrence and intake context.
- **Information produced:** lifecycle identity proposal, initial Workspace binding, intake review, and source-scope declaration; no facts or intelligence.

### 2. `SOURCE_CONTROL`

- **Purpose:** establish a controlled, version-aware authoritative procurement package.
- **Question:** Which issued materials constitute the present source package, and what is missing, conflicting, unsafe, or superseded?
- **Required governed inputs:** declared opportunity scope, acquired files or source locations, amendments, notices, and receipt history.
- **Capabilities expected:** procurement acquisition, ingestion, provenance preservation, format validation, and package completeness review.
- **Briefing Pack volumes:** none.
- **Human responsibilities:** Bid Manager confirms package scope, obtains missing material, and accepts explicit partial coverage where necessary.
- **Required reviews:** source inventory, provenance, amendment, language, and package-boundary review.
- **Required approvals:** human acceptance of the authoritative package scope or explicit partial state.
- **Entry criteria:** `RECEIVED` exited with a valid opportunity and controlled source boundary.
- **Exit criteria:** a validated authoritative package identity exists, every expected item has a disposition, and unresolved gaps remain explicit.
- **Permitted transitions:** `OPPORTUNITY_UNDERSTANDING`, back to `RECEIVED` for identity correction, or `CLOSED`.
- **Blocked conditions:** no authoritative package can close, required provenance is missing, active conflicts prevent safe package identity, or unsupported material contains the only required source.
- **Information consumed:** acquisition artifacts, source occurrences, and human package declarations.
- **Information produced:** authoritative package reference, package manifest, acquisition diagnostics, and explicit coverage state; no opportunity conclusions.

### 3. `OPPORTUNITY_UNDERSTANDING`

- **Purpose:** establish a validated understanding of what the opportunity requests.
- **Question:** What is required, evaluated, submitted, delivered, dated, and commercially stated, and what remains unresolved?
- **Required governed inputs:** authoritative procurement package and supported Canonical Opportunity inputs.
- **Capabilities expected:** Canonical Opportunity reconciliation and Opportunity Intelligence. Buyer Intelligence may begin only after its own Buyer identity and evidence inputs exist.
- **Briefing Pack volumes:** Volume 1, Executive Opportunity Brief, is expected before exit.
- **Human responsibilities:** Bid Manager, Proposal Manager, consultants, SMEs, and Commercial Lead review the relevant facts, unknowns, conflicts, and questions.
- **Required reviews:** canonical integrity review, Opportunity Intelligence validation, and human Volume 1 review.
- **Required approvals:** human acknowledgement of the current opportunity understanding and unresolved conditions for kickoff use.
- **Entry criteria:** a validated authoritative package reference exists.
- **Exit criteria:** supported Canonical Opportunity and Opportunity Intelligence references exist; current Volume 1 is issued and reviewed or explicitly unavailable; blocking defects have dispositions.
- **Permitted transitions:** `BUYER_UNDERSTANDING`, `KICKOFF_PREPARATION` under an explicit Buyer-evidence exception, back to `SOURCE_CONTROL`, or `CLOSED`.
- **Blocked conditions:** canonical identity failure, unresolved reference closure, invalid intelligence, missing critical package material without human disposition, or unreviewed Volume 1 when required.
- **Information consumed:** evidence and canonical opportunity records.
- **Information produced:** references to canonical truth, validated analysis, Volume 1, reviews, and readiness declarations; the lifecycle itself produces none of their content.

### 4. `BUYER_UNDERSTANDING`

- **Purpose:** establish attributable organizational context for the Buyer without altering opportunity authority.
- **Question:** Who is asking, what do authoritative public sources establish, and what remains unknown or interpretive?
- **Required governed inputs:** Canonical Buyer identity, Buyer Evidence acquisition result, current opportunity identity, and relevant validated opportunity references.
- **Capabilities expected:** Buyer Evidence Acquisition, Canonical Buyer validation, Buyer Intelligence, and Buyer Brief presentation. Opportunity Intelligence may refresh independently if procurement evidence changes.
- **Briefing Pack volumes:** Volume 2, Buyer Brief, is expected before exit; Volume 1 remains separately authoritative.
- **Human responsibilities:** CEO or Managing Partner, Bid Manager, Proposal Manager, consultants, SMEs, and Commercial Lead review Buyer facts, interpretations, assumptions, alternatives, unknowns, and limitations.
- **Required reviews:** evidence coverage and provenance review, Buyer Intelligence validation, and human Volume 2 review.
- **Required approvals:** human acceptance of complete or explicitly partial Buyer context for kickoff use.
- **Entry criteria:** Canonical Buyer identity and an eligible acquisition request exist; this work may start during `OPPORTUNITY_UNDERSTANDING` when those conditions are already met.
- **Exit criteria:** Buyer Evidence has an explicit completion state; valid Buyer analysis and Volume 2 references exist or an authorized partial/unavailable disposition is recorded; review is complete for current revisions.
- **Permitted transitions:** `KICKOFF_PREPARATION`, back to `SOURCE_CONTROL` or `OPPORTUNITY_UNDERSTANDING` when identity changes, or `CLOSED`.
- **Blocked conditions:** Buyer identity cannot close, evidence references fail, unsupported source classes enter analysis, or required human review is absent.
- **Information consumed:** attributable public evidence, canonical Buyer, and opportunity references.
- **Information produced:** references to acquisition coverage, Canonical Buyer, Buyer Intelligence, Volume 2, reviews, and gaps; no new Buyer claim is produced by the lifecycle.

### 5. `KICKOFF_PREPARATION`

- **Purpose:** assemble the governed materials, participants, questions, and open conditions needed for human kickoff deliberation.
- **Question:** Does the team have an explicit, reviewable basis for a productive kickoff, and which matters remain open?
- **Required governed inputs:** current Volume 1 and Volume 2 references or explicit exceptions, associated analyses, readiness declarations, open Unknowns and Conflicts, team roles, and kickoff agenda ownership.
- **Capabilities expected:** Bid Workspace collaboration and Briefing Pack presentation. Intelligence capabilities supply existing outputs or separately governed revisions; the lifecycle performs no synthesis.
- **Briefing Pack volumes:** current Volumes 1 and 2, independently identified and reviewed.
- **Human responsibilities:** Bid Manager organizes participants and review; leaders and specialists identify discussion needs and accept visible limitations.
- **Required reviews:** briefing currency, audience, unresolved matters, management questions, and role coverage.
- **Required approvals:** accountable human kickoff-readiness attestation.
- **Entry criteria:** opportunity understanding exists and Buyer understanding is reviewed or explicitly dispositioned.
- **Exit criteria:** exact briefing revisions, participants, open conditions, and questions are recorded; kickoff-readiness is attested; the kickoff occurrence is recorded if held.
- **Permitted transitions:** `PURSUIT_AUTHORIZATION`, backward to either understanding stage, or `CLOSED`.
- **Blocked conditions:** stale or mismatched briefing references, missing accountable participants, hidden critical unknowns, or no readiness attestation.
- **Information consumed:** briefing volumes, validated analyses, collaboration records, and readiness dimensions.
- **Information produced:** kickoff review, readiness attestation, agenda and action references, and kickoff occurrence; no merged executive conclusion.

### 6. `PURSUIT_AUTHORIZATION`

- **Purpose:** record the accountable human choice about whether and under what conditions the firm will proceed with proposal work.
- **Question:** What has an authorized human decided about pursuing this opportunity?
- **Required governed inputs:** exact information references considered, briefing reviews, acknowledged uncertainty, resource and commercial human input where required, and declared decision authority.
- **Capabilities expected:** Bid Workspace decision recording only. Intelligence may be consulted by reference but does not participate as decision-maker.
- **Briefing Pack volumes:** current reviewed Volumes 1 and 2 are expected unless the decision record explains their absence.
- **Human responsibilities:** authorized CEO, Managing Partner, or delegated owner makes and owns the decision; Bid Manager preserves the record and conditions.
- **Required reviews:** organization-defined pursuit, capability, capacity, commercial, ethical, and conflict reviews where applicable.
- **Required approvals:** the Human Decision itself and any separately required conditional approvals.
- **Entry criteria:** sufficient information is available for the human to decide, or the human explicitly decides to defer or decline under uncertainty.
- **Exit criteria:** immutable `PROCEED`, `PROCEED_WITH_CONDITIONS`, `DEFER`, or `DO_NOT_PROCEED` Human Decision record exists with owner, rationale, time, scope, and exact references.
- **Permitted transitions:** `PROPOSAL_DEVELOPMENT` for authorized pursuit, backward for `DEFER`, or `CLOSED` for `DO_NOT_PROCEED`.
- **Blocked conditions:** absent decision authority, missing rationale or exact information state, unresolved required approvals, or an attempted system-generated choice.
- **Information consumed:** governed references and attributed human review inputs.
- **Information produced:** Human Decision and related transition reference; no recommendation or automated decision.

### 7. `PROPOSAL_DEVELOPMENT`

- **Purpose:** coordinate creation of the proposal in separately governed production tools and human work practices.
- **Question:** Is a traceable, reviewable proposal being produced against the current opportunity authority?
- **Required governed inputs:** authorized pursuit decision, current opportunity and Buyer references, selected prior material under human control, assignments, and production baseline.
- **Capabilities expected:** proposal production and optional future Proposal Intelligence under separate contracts. Knowledge reuse may support human selection. Bid Intelligence itself does not own proposal writing.
- **Briefing Pack volumes:** Volumes 1 and 2 remain reference material; no new mandatory volume.
- **Human responsibilities:** Proposal Manager controls structure and versions; contributors author content; SMEs validate claims; Commercial Lead owns commercial inputs.
- **Required reviews:** section, evidence, factual, specialist, commercial, privacy, confidentiality, and editorial reviews as declared by the team.
- **Required approvals:** human approval of proposal baselines or sections where organizational policy requires it.
- **Entry criteria:** pursuit is authorized and a proposal-production owner and baseline identity exist.
- **Exit criteria:** one reviewable proposal revision is explicitly identified, required contributor work has dispositions, and unresolved production issues remain visible.
- **Permitted transitions:** `PROPOSAL_VERIFICATION`, backward to preparation or authorization when material conditions change, or `CLOSED` after withdrawal.
- **Blocked conditions:** no authorized pursuit, no controlled proposal revision, unsupported claims without disposition, or changed opportunity authority not incorporated or acknowledged.
- **Information consumed:** canonical opportunity, briefing references, human decisions, and human-selected organizational material.
- **Information produced:** proposal revision and production records owned outside the lifecycle; lifecycle stores references and participation state only.

### 8. `PROPOSAL_VERIFICATION`

- **Purpose:** compare a reviewable proposal and intended submission package with authoritative opportunity requirements.
- **Question:** What is covered, missing, conflicting, or unverifiable in the current proposal and package?
- **Required governed inputs:** exact proposal revision, intended submission-package identity, Canonical Opportunity, authoritative requirements, and permitted proposal evidence.
- **Capabilities expected:** future Proposal Compliance Intelligence. Proposal production may respond through a new revision but cannot certify itself.
- **Briefing Pack volumes:** future Volume 3, Proposal Compliance Brief, is expected when that volume is governed and available.
- **Human responsibilities:** Bid Manager and Proposal Manager coordinate correction; contributors and SMEs address findings; humans decide dispositions.
- **Required reviews:** item-level compliance, mandatory requirements, submission mechanics, evidence, commercial consistency, and source-amendment incorporation.
- **Required approvals:** human acceptance of remaining compliance gaps or exceptions under declared authority.
- **Entry criteria:** a reviewable proposal and submission-package baseline exist.
- **Exit criteria:** validated compliance output is bound to exact proposal and authority revisions; required human review and gap dispositions are recorded.
- **Permitted transitions:** `FINAL_REVIEW`, backward to `PROPOSAL_DEVELOPMENT`, or `CLOSED` after withdrawal.
- **Blocked conditions:** mismatched proposal revision, unavailable authoritative requirements, self-certification, unresolved mandatory gaps without disposition, or invalid compliance output.
- **Information consumed:** proposal, package, canonical requirements, and evidence.
- **Information produced:** compliance findings and future Volume 3 owned by their capabilities; lifecycle records references only.

### 9. `FINAL_REVIEW`

- **Purpose:** coordinate accountable final human review of the exact proposal and intended submission package.
- **Question:** Have the required people reviewed the current material and recorded their conditions without the system deciding acceptability?
- **Required governed inputs:** exact proposal and package revisions, compliance findings, commercial and specialist reviews, current amendments, open conditions, and required approver roster.
- **Capabilities expected:** Bid Workspace review coordination; approved compliance, commercial, legal, security, privacy, accessibility, or proposal-analysis capabilities may supply independent outputs.
- **Briefing Pack volumes:** Volumes 1 and 2 remain available; Volume 3 is expected when governed.
- **Human responsibilities:** named reviewers inspect their scope; Bid Manager preserves version binding and unresolved conditions; executives retain final judgment.
- **Required reviews:** all declared final review scopes with dissent and conditions preserved separately.
- **Required approvals:** review acceptance where required, distinct from submission authorization.
- **Entry criteria:** proposal verification has a valid current result or explicit governed exception.
- **Exit criteria:** all required reviews have attributable outcomes against exact revisions; changes requested are resolved by a new revision or explicitly dispositioned.
- **Permitted transitions:** `SUBMISSION_AUTHORIZATION`, backward to development or verification, or `CLOSED`.
- **Blocked conditions:** stale approvals, unresolved requested changes, missing reviewer authority, hidden dissent, or revision mismatch.
- **Information consumed:** proposal, package, compliance, intelligence, briefing, and human review records.
- **Information produced:** final review and readiness references; no system acceptance conclusion.

### 10. `SUBMISSION_AUTHORIZATION`

- **Purpose:** record the accountable human authorization to release one exact submission package.
- **Question:** Has an authorized person approved this exact package for submission under explicit conditions?
- **Required governed inputs:** submission-ready attestation, exact package digest or revision, final review records, deadline and channel facts, open warnings, and authority declaration.
- **Capabilities expected:** submission-control checks may participate deterministically; no intelligence capability makes the authorization.
- **Briefing Pack volumes:** current relevant volumes available for context; no new volume required.
- **Human responsibilities:** authorized approver makes the release decision; Bid Manager confirms package identity and preserves the record.
- **Required reviews:** package identity, signatures, file rules, channel, deadline, approval conditions, and final authority checks.
- **Required approvals:** immutable human submission-authorization decision.
- **Entry criteria:** required final reviews exist and the current package has a human submission-ready attestation.
- **Exit criteria:** authorization names the exact package, channel, scope, conditions, approver, and time; or refusal/deferment is recorded.
- **Permitted transitions:** `SUBMISSION`, backward to final review or development, or `CLOSED`.
- **Blocked conditions:** no authorized approver, package mismatch, expired or revoked approval, absent readiness attestation, or system-inferred authorization.
- **Information consumed:** package, review, readiness, deadline, and channel references.
- **Information produced:** Human Decision and transition reference only.

### 11. `SUBMISSION`

- **Purpose:** record whether the authorized package was released through the required channel and preserve authoritative receipt evidence.
- **Question:** What exact package was submitted, by whom, when, through which channel, and what receipt exists?
- **Required governed inputs:** valid submission authorization, exact authorized package, authoritative channel and deadline, and human submitter identity.
- **Capabilities expected:** separately governed submission-control operations may assist; the lifecycle does not transmit files.
- **Briefing Pack volumes:** none newly required.
- **Human responsibilities:** authorized submitter performs release, handles exceptions, verifies receipt, and records discrepancies.
- **Required reviews:** package-to-authorization identity and receipt verification.
- **Required approvals:** no new approval beyond valid submission authorization unless an exception requires one.
- **Entry criteria:** exact package is authorized and the submission action is still permitted.
- **Exit criteria:** authoritative receipt or human-verified submission record exists, or failed/non-submission is recorded explicitly.
- **Permitted transitions:** `OUTCOME_CAPTURE`, backward for a permitted corrected resubmission, or `CLOSED` when submission did not occur and no further attempt is permitted.
- **Blocked conditions:** missing authorization, package mismatch, unavailable channel, deadline conflict, failed transmission without receipt, or inability to verify status.
- **Information consumed:** authorization, package, submission facts, and human action.
- **Information produced:** submission and receipt records owned by submission control; lifecycle records their identities and milestone.

### 12. `OUTCOME_CAPTURE`

- **Purpose:** preserve the authoritative procurement result and feedback without rewriting the pursuit's earlier information state.
- **Question:** What outcome has an attributable authority communicated, and what remains unavailable?
- **Required governed inputs:** submission record or explicit non-submission closure context, official notice, buyer communication, debrief, scores, or other governed Outcome evidence when available.
- **Capabilities expected:** Outcome acquisition and canonical Outcome recording. Organizational Intelligence may not treat the result as causal explanation.
- **Briefing Pack volumes:** no current required volume.
- **Human responsibilities:** Bid Manager obtains and verifies result material; executives and participants distinguish fact from reaction.
- **Required reviews:** outcome identity, attribution, relationship to the opportunity and submission, and completeness of received feedback.
- **Required approvals:** human confirmation of the recorded Outcome scope; none for unavailable information.
- **Entry criteria:** submission stage ended or the procurement ended authoritatively without submission.
- **Exit criteria:** authoritative Outcome exists, or an explicit `OUTCOME_UNAVAILABLE`/`NOT_APPLICABLE` disposition records bounded attempts and responsible owner.
- **Permitted transitions:** `PURSUIT_RETROSPECTIVE`, backward if corrected official outcome evidence arrives, or `CLOSED` with explicit retrospective disposition.
- **Blocked conditions:** unattributed result, buyer/opportunity mismatch, inferred award status, or unofficial commentary presented as authoritative Outcome.
- **Information consumed:** official outcome evidence and submission history.
- **Information produced:** governed Outcome and evidence references outside the lifecycle; no causal explanation.

### 13. `PURSUIT_RETROSPECTIVE`

- **Purpose:** preserve what was known, decided, produced, submitted, observed, and learned by identified participants for this pursuit.
- **Question:** What attributable observations and reflections should remain with this pursuit record?
- **Required governed inputs:** prior lifecycle history, exact Briefs, Human Decisions, proposal and submission identities, Outcome disposition, and attributed participant reflections.
- **Capabilities expected:** future retrospective presentation and bounded Organizational Intelligence support. The lifecycle does not synthesize lessons.
- **Briefing Pack volumes:** future Volume 4, Pursuit Retrospective, is expected when governed and applicable.
- **Human responsibilities:** participants contribute reflections; accountable reviewer distinguishes Outcome facts, observations, interpretations, and proposed lessons.
- **Required reviews:** attribution, temporal fidelity, confidentiality, hindsight boundaries, and separation of fact from reflection.
- **Required approvals:** human approval for internal circulation and learning handoff where required.
- **Entry criteria:** Outcome capture has a valid disposition, including explicit unavailability.
- **Exit criteria:** retrospective is issued or explicitly declined/deferred by an authorized human; open learning questions and evidence limits remain visible.
- **Permitted transitions:** `LEARNING_HANDOFF`, backward to `OUTCOME_CAPTURE` for new evidence, or `CLOSED` with a recorded no-retrospective reason.
- **Blocked conditions:** unattributed reflection, hindsight presented as prior knowledge, unsupported causal claims, confidentiality breach, or no responsible reviewer.
- **Information consumed:** immutable pursuit record, Outcome, and human reflections.
- **Information produced:** future Volume 4 and attributed reflection records owned outside the lifecycle; lifecycle records references.

### 14. `LEARNING_HANDOFF`

- **Purpose:** make eligible pursuit records available to governed cross-opportunity learning without claiming that learning is complete.
- **Question:** Which evidence, decisions, outcomes, and attributed reflections are authorized and ready for later organizational inquiry?
- **Required governed inputs:** closed or closing pursuit record, Outcome disposition, retrospective disposition, sharing and confidentiality rules, and stable reference identities.
- **Capabilities expected:** future Organizational Intelligence, Institutional Learning, and Volume 5 may accept the handoff under their own contracts. They are not executed by the lifecycle.
- **Briefing Pack volumes:** Volume 4 when available; future Volume 5 belongs to cross-opportunity learning and is not required to close one lifecycle.
- **Human responsibilities:** authorized learning owner approves eligible material, restrictions, and unanswered learning questions.
- **Required reviews:** identity closure, temporal context, confidentiality, permissions, provenance, and fact-versus-reflection boundaries.
- **Required approvals:** explicit human learning-handoff authorization or recorded decision not to hand off.
- **Entry criteria:** retrospective has a disposition and eligible records have stable identities.
- **Exit criteria:** immutable handoff manifest or no-handoff decision exists; recipient capability acceptance remains separate.
- **Permitted transitions:** `CLOSED`, backward for corrected restrictions or records, or remain pending without implying completion.
- **Blocked conditions:** missing permission, unresolved confidentiality, identity mismatch, mutable history, or an attempt to derive institutional conclusions during handoff.
- **Information consumed:** governed pursuit references and human authorization.
- **Information produced:** handoff manifest only; no Organizational Intelligence or Institutional Learning.

### 15. `CLOSED`

- **Purpose:** end active pursuit coordination while preserving the complete historical information state.
- **Question:** Why has active work ended, what remains unresolved, and what records are retained?
- **Required governed inputs:** closure reason, responsible human or authoritative cancellation event, final lifecycle history, outstanding-item disposition, and learning-handoff disposition.
- **Capabilities expected:** none required. Future learning may continue from immutable references outside the active lifecycle.
- **Briefing Pack volumes:** no new volume required.
- **Human responsibilities:** Workspace owner confirms closure reason, retained access, unresolved matters, and responsible record custodians.
- **Required reviews:** closure completeness, retention, confidentiality, and open-condition review.
- **Required approvals:** human closure approval unless authoritative procurement cancellation establishes the event and policy permits deterministic recording.
- **Entry criteria:** any stage may close when a valid human decision or authoritative event ends active pursuit work.
- **Exit criteria:** closure record is complete; archival may occur under separate retention policy.
- **Permitted transitions:** `ARCHIVED` or governed reopen to the appropriate prior stage.
- **Blocked conditions:** inferred cancellation, inferred withdrawal, missing closure authority, erased open matters, or absent reason.
- **Information consumed:** full lifecycle and Workspace references.
- **Information produced:** immutable closure transition and unresolved-item disposition; no learning conclusion.

### Retention state: `ARCHIVED`

Archival changes active availability under a future retention policy. It preserves the closed lifecycle, Workspace, referenced revisions, decisions, Outcome disposition, and handoff history. Reopening an archive creates an attributed transition and never deletes the prior closure.

## Capability participation summary

| Stage | Primary participating capabilities | Explicitly absent from the stage's authority |
|---|---|---|
| `RECEIVED` | Controlled intake and safe ingestion | Opportunity or Buyer Intelligence, Brief generation, proposal work |
| `SOURCE_CONTROL` | Acquisition, ingestion, package provenance | Intelligence, Buyer analysis, proposal production |
| `OPPORTUNITY_UNDERSTANDING` | Canonical Opportunity, Opportunity Intelligence, Volume 1 | Buyer conclusions, proposal compliance, pursuit decision-making |
| `BUYER_UNDERSTANDING` | Buyer Evidence Acquisition, Canonical Buyer, Buyer Intelligence, Volume 2 | Opportunity mutation, proposal strategy, decision-making |
| `KICKOFF_PREPARATION` | Bid Workspace and Briefing Pack references | New synthesis, merged intelligence, automated readiness |
| `PURSUIT_AUTHORIZATION` | Human Decision recording | System recommendation or autonomous Bid / No Bid |
| `PROPOSAL_DEVELOPMENT` | Human proposal production, approved optional proposal tools | Workspace authorship, self-certifying compliance |
| `PROPOSAL_VERIFICATION` | Proposal Compliance and future Volume 3 | Proposal generation, winner prediction, automatic correction |
| `FINAL_REVIEW` | Human review plus approved specialist outputs | Automated acceptance or submission authorization |
| `SUBMISSION_AUTHORIZATION` | Human Decision and deterministic package controls | Intelligence-based authorization or system commitment |
| `SUBMISSION` | Human/operational submission control | Lifecycle file transmission or inferred receipt |
| `OUTCOME_CAPTURE` | Outcome evidence acquisition and canonical Outcome | Causal learning, retroactive scoring of decisions |
| `PURSUIT_RETROSPECTIVE` | Attributed human reflection and future Volume 4 | Hindsight rewriting, unattributed lessons |
| `LEARNING_HANDOFF` | Controlled handoff to future learning capabilities | Cross-opportunity analysis performed by lifecycle |
| `CLOSED` / `ARCHIVED` | Retention and governed access | New conclusions or silent history changes |

Capability absence means the lifecycle stage grants no authority to that capability. A prior capability may refresh its own output during a later stage when new governed input requires it. The lifecycle records the new participation and applies invalidation rules; it does not absorb the capability's logic.

## Human participation

Humans remain responsible for:

- confirming receipt and source-package scope;
- accepting explicit evidence and package gaps;
- reviewing Opportunity and Buyer understanding;
- declaring kickoff readiness and conducting kickoff;
- making Bid / No Bid and conditional pursuit decisions;
- selecting prior material and authoring the proposal;
- reviewing claims, method, delivery, commercial terms, legal matters, privacy, security, accessibility, and compliance within their authority;
- accepting or correcting proposal and compliance gaps;
- authorizing and performing submission;
- verifying Outcome evidence;
- contributing attributed reflections; and
- authorizing learning handoff, closure, archival, and reopen.

The lifecycle may require a human act and record its reference. It cannot perform the act, infer consent from silence, infer approval from task completion, or assign authority because a person participated earlier.

## Decision philosophy

Human judgment is sovereign. The lifecycle identifies decision points and the conditions under which their records can support transitions. It never creates a decision or preferred answer.

Every lifecycle-relevant Human Decision preserves:

- decision identity and type;
- named owner and declared authority scope;
- exact choice and effective scope;
- rationale and conditions;
- decision and recording times;
- evidence, canonical, intelligence, Brief, proposal, compliance, review, and readiness references considered;
- explicit uncertainty and alternatives acknowledged where applicable; and
- correction, revocation, expiry, or supersession relationships.

A decision cannot change the evidence or analysis it considered. A later stage, Outcome, or lesson cannot rewrite the original rationale. Decision correction creates a new linked record.

Required decisions include pursuit authorization when proposal work will proceed, submission authorization before release, and closure or reopen where no authoritative external event alone establishes the state. Other approvals remain distinct unless they explicitly satisfy a governed Human Decision contract.

## Readiness philosophy

Readiness is descriptive, multidimensional, version-bound, and owned by accountable humans. It is never scored, ranked, predicted, averaged, or converted into a Bid / No Bid recommendation.

Each transition declares required readiness dimensions. Each dimension records applicability, owner, governed references, current descriptive state, open conditions, and attestation. Examples include package scope, canonical availability, intelligence validation, human review, Brief currency, clarification status, specialist review, proposal baseline, compliance disposition, package verification, approval, receipt, Outcome coverage, retrospective disposition, and learning permissions.

The lifecycle never equates:

- source-package disposition with exhaustive source completeness;
- validated intelligence with human acceptance;
- generated Brief with reviewed Brief;
- task completion with stage readiness;
- acknowledged Unknown with resolved Unknown;
- review completion with approval;
- compliance coverage with proposal quality or likely success;
- submission-ready with submission-authorized;
- upload attempt with submission;
- silence with approval or decision;
- Outcome absence with loss; or
- retrospective completion with institutional learning.

A human may attest readiness with open conditions only when those conditions, authority, rationale, and affected stage are explicit. The state remains `ready with recorded conditions`; the conditions do not disappear.

## Milestone model

Canonical milestones should include, where applicable:

- `OPPORTUNITY_REGISTERED`
- `SOURCE_SCOPE_ACCEPTED`
- `CANONICAL_OPPORTUNITY_AVAILABLE`
- `OPPORTUNITY_INTELLIGENCE_VALIDATED`
- `VOLUME_1_REVIEWED`
- `BUYER_IDENTITY_CLOSED`
- `BUYER_EVIDENCE_DISPOSITIONED`
- `BUYER_INTELLIGENCE_VALIDATED`
- `VOLUME_2_REVIEWED`
- `KICKOFF_READINESS_ATTESTED`
- `KICKOFF_HELD`
- `PURSUIT_DECISION_RECORDED`
- `PROPOSAL_BASELINE_IDENTIFIED`
- `COMPLIANCE_REVIEW_RECORDED`
- `FINAL_REVIEW_RECORDED`
- `SUBMISSION_READINESS_ATTESTED`
- `SUBMISSION_AUTHORIZED`
- `SUBMISSION_RECEIPT_RECORDED`
- `OUTCOME_RECORDED` or explicit `OUTCOME_UNAVAILABLE`
- `RETROSPECTIVE_DISPOSITIONED`
- `LEARNING_HANDOFF_DISPOSITIONED`
- `LIFECYCLE_CLOSED`

Milestones carry stable identity, occurrence time, source actor or event authority, supporting references, and supported contract version. The vocabulary is not a checklist that automatically advances stages. Transition rules identify which subset applies to the opportunity and why.

## Transition philosophy

### Forward transitions

A forward transition requires explicit source stage, target stage, actor or authoritative event, reason, applicable readiness declarations, required milestone references, and transition time. The transition appends history and never rewrites the source stage.

The normal sequence is the default coordination path, not a mandate to perform irrelevant work. A bypass requires an explicit not-applicable or human exception record and may not bypass evidence identity, human decision, or submission authorization boundaries.

### Backward transitions

A backward transition reopens the earliest stage whose governed output or review is materially affected. It records the trigger and invalidates only dependent readiness, review, or approval references. Historical states and acts remain available.

Examples:

- a missing attachment returns to `SOURCE_CONTROL`;
- a changed requirement returns to `OPPORTUNITY_UNDERSTANDING`;
- new public organizational evidence returns to `BUYER_UNDERSTANDING` for a new evidence cutoff and analysis revision;
- a changed proposal returns to `PROPOSAL_DEVELOPMENT` and later requires compliance and review against the new revision;
- a changed package after authorization returns to `FINAL_REVIEW` or `SUBMISSION_AUTHORIZATION` under policy.

### Amendments

An attributable procurement amendment enters Acquisition and Evidence first. The lifecycle does not parse or judge it. Once the authoritative package records the amendment, impact is evaluated by the owning canonical and intelligence capabilities.

The amendment event records which references become stale or require review. It never silently changes a deadline, Requirement, Brief, proposal, approval, or decision. Unaffected validated records remain available.

### Additional Buyer evidence

New Buyer material creates a new acquisition result and evidence cutoff. Canonical Buyer and Buyer Intelligence determine whether their own revisions change. The lifecycle can require renewed Buyer Brief review without altering the prior Brief or kickoff record.

### Late clarifications

An official clarification response enters through controlled acquisition and evidence. It may trigger source, opportunity, proposal, compliance, final-review, or authorization re-entry according to validated impact. A tracked internal question or submitted clarification request does not itself change canonical truth.

### Proposal revision

Every material revision has a distinct identity. Compliance, reviews, readiness, and authorization remain bound to the revision they considered. A new revision does not inherit them automatically. The lifecycle returns to the earliest required review stage.

### Reopened opportunities

Reopen appends a transition from `CLOSED` or `ARCHIVED` to the earliest applicable stage. It requires an authoritative reactivation event or authorized human decision, a reason, current identity validation, and an assessment of which references remain usable. Prior closure and history remain immutable.

### Cancelled procurements

Cancellation requires attributable buyer or procurement-authority evidence. The lifecycle records that event and transitions to `OUTCOME_CAPTURE`, `PURSUIT_RETROSPECTIVE`, or `CLOSED` as applicable. It does not infer cancellation from a disappeared page, missed date, or inactivity.

### Withdrawn bids and No Bid decisions

Withdrawal and No Bid are Human Decisions. They identify owner, authority, rationale, time, scope, and considered information. They may close the active path from any pre-submission stage, with retrospective and learning dispositions recorded separately.

### Corrected submission

A corrected or replacement submission requires authoritative permission, a new package identity, renewed review and authorization as applicable, and a distinct submission record. The earlier submission is never overwritten.

### Outcomes and learning

A corrected Outcome creates a new authoritative record and returns the lifecycle to `OUTCOME_CAPTURE` or retrospective review. It does not change earlier decisions. New cross-opportunity learning remains owned by Organizational Intelligence and does not reopen the original lifecycle unless a human initiates a separate governed action.

## Fail-closed behavior

The lifecycle must never infer:

- receipt from a file merely existing;
- package completeness from successful parsing;
- canonical availability from extracted text;
- intelligence completion from a model or function returning output;
- Brief issuance from analysis availability;
- human review from document access;
- kickoff readiness from generated briefing volumes;
- kickoff occurrence from calendar time;
- pursuit authorization from proposal activity;
- proposal completion from task counts or filenames;
- compliance from a review request;
- approval from silence or role membership;
- submission readiness from compliance coverage;
- authorization from readiness;
- submission from upload, email, or portal attempt without governed evidence;
- Outcome from dates, rumours, absence, or unofficial commentary;
- retrospective from an Outcome record;
- learning from a retrospective or data handoff; or
- closure from inactivity.

Invalid identity, version, reference, transition, actor authority, milestone evidence, or readiness state blocks the affected transition. The lifecycle retains the valid current stage and explicit failure. It never coerces a state, fabricates a milestone, or discards unrelated valid history.

## Boundaries

The Bid Lifecycle must never:

- retrieve, acquire, parse, or register evidence;
- reconcile or modify Canonical Opportunity, Canonical Buyer, Outcome, or any canonical truth;
- perform Opportunity, Buyer, Proposal, Compliance, Commercial, Risk, Pricing, Negotiation, Organizational, or Institutional Learning intelligence;
- compute analytical indicators, confidence, scores, rankings, priorities, or predictions;
- generate, revise, assemble, or approve Briefing Pack content;
- create or manage collaboration tasks, discussions, or notes outside the Bid Workspace contract;
- write, rewrite, evaluate, or certify proposal content;
- transmit a submission or manufacture a receipt;
- recommend pursuit, Bid / No Bid, pricing, commercial acceptance, negotiation, proposal strategy, or submission;
- infer an approval, decision, readiness state, Outcome, lesson, or human intent;
- merge analyst outputs, resolve their conflicts, or suppress their uncertainty;
- trigger a downstream capability merely because a stage was entered; or
- replace human authority or judgment.

## Validation

A future lifecycle contract must reject:

- missing, duplicate, mutable, or reused lifecycle identity;
- binding to zero or more than one Canonical Opportunity or Bid Workspace;
- unsupported lifecycle, Workspace, capability, evidence, canonical, analyst, Brief, proposal, compliance, submission, Outcome, or learning version;
- unresolved or digest-mismatched references;
- a stage transition without valid source state, target state, actor or event authority, reason, time, and applicable milestone evidence;
- skipped required stages without an explicit permitted bypass and disposition;
- milestone names unsupported in the active lifecycle version;
- milestone occurrence without attributable evidence;
- readiness inferred from counts, time, model output, or state labels;
- review, approval, Human Decision, submission, Outcome, reflection, or learning inferred from another record type;
- new proposal or Brief revisions inheriting stale review or approval;
- hidden Unknowns, Conflicts, dissent, conditions, partial results, exceptions, or failed participation;
- a capability participating outside its supported purpose or contract;
- lifecycle-authored evidence, intelligence, Brief content, proposal prose, recommendation, decision, Outcome, or learning; and
- mutation or deletion of historical transitions and references.

Validation is scoped. A Buyer evidence failure may block Buyer readiness without erasing a valid Canonical Opportunity. A failed later transition leaves the lifecycle at its last valid stage with the exact block visible.

## Determinism and historical reconstruction

Given identical immutable lifecycle records, governed references, versions, applicability rules, and human acts, the canonical lifecycle projection and ordering are identical. Current time, database order, UI state, task sorting, cache state, and model behavior cannot silently change semantic state.

Operational time is recorded on events. Time may establish that a deadline or approval expiry has passed only under a declared deterministic rule and authoritative time input. It cannot imply the human response to that condition.

Append-only stage, milestone, participation, readiness-reference, decision-reference, and transition history must reconstruct what was available at every pursuit decision, proposal baseline, review, authorization, submission, Outcome, retrospective, handoff, closure, and reopen.

## Extension model

Future capabilities integrate through versioned participation declarations and immutable output references. Adding a capability does not add a lifecycle stage automatically. A new stage is justified only when it represents a durable human coordination question, distinct authority transition, and reusable milestone boundary.

Every extension declares:

1. capability identity, pillar, and owner;
2. stages in which it may participate and the purpose of participation;
3. stages in which it has no authority;
4. required governed inputs and immutable outputs;
5. supported contract versions, identities, revisions, digests, and evidence cutoffs;
6. human reviewer and decision responsibilities;
7. optional readiness dimensions and milestones;
8. invalidation and backward-transition triggers;
9. failure, partial, unavailable, replay, and historical behavior; and
10. confirmation that the lifecycle does not execute or reproduce its logic.

### Commercial Intelligence

A future governed capability may present evidence-linked commercial interpretation separately from canonical money and clause facts. It cannot accept commercial exposure or recommend pricing. The lifecycle may require human commercial review at authorization stages without interpreting the output.

### Risk Intelligence

A future risk capability requires explicit evidence, interpretation, legal, organizational-tolerance, and human-authority boundaries. The lifecycle may reference its validated output and review status. It cannot assign severity, materiality, or acceptance itself.

### Pricing Intelligence

Any future pricing capability must preserve human commercial authority and avoid hidden optimization or autonomous price decisions. Its existence does not alter pursuit or submission authorization requirements.

### Negotiation Intelligence

A future capability may organize governed facts, alternatives, assumptions, and questions for human negotiation preparation. It cannot make commitments, contact the Buyer, accept terms, or transition the lifecycle autonomously.

### Proposal Intelligence and Proposal Compliance

These remain separate capabilities. Proposal Intelligence may analyze a proposal only under an approved contract. Proposal Compliance verifies item-level coverage. Neither writes the proposal, predicts success, authorizes submission, or inherits authority from lifecycle placement.

### Organizational Intelligence and Institutional Learning

These capabilities consume eligible immutable pursuit records after explicit handoff. They preserve temporal context and distinguish observations, hypotheses, attributed human lessons, and unknowns. The lifecycle never marks institutional learning complete because learning is ongoing and cross-opportunity.

### Knowledge reuse

Knowledge reuse supports human discovery and selection of governed prior material. It may participate during preparation and proposal development under confidentiality and relevance controls. The lifecycle records selected references without choosing them or treating prior success as causal evidence.

Optional capabilities are behaviorally absent when unavailable. Their absence is an explicit readiness or participation state, not permission for the lifecycle to simulate them.

## Acceptance criteria

The canonical Bid Lifecycle architecture is satisfied only when a future implementation demonstrates that:

1. each lifecycle has a stable identity bound to exactly one Canonical Opportunity and one Bid Workspace;
2. lifecycle stages coordinate participation without owning capability logic or substantive outputs;
3. every stage declares purpose, question, governed inputs, expected and absent capabilities, briefing expectations, human responsibilities, reviews, approvals, entry, exit, transitions, blocks, consumed information, and produced references;
4. stage entry never implies stage exit, completion, readiness, review, approval, decision, submission, Outcome, or learning;
5. milestones are immutable, attributable, versioned, evidence-supported events rather than inferred labels;
6. capability participation records exact input and output identities, versions, revisions, digests, and failure state;
7. Opportunity Intelligence, Buyer Intelligence, Briefing Pack, Bid Workspace, proposal production, compliance, submission, Outcome, and learning retain independent authority;
8. the lifecycle retrieves no evidence, modifies no canonical truth, performs no intelligence, generates no Brief, writes no proposal, submits no package, records no invented Outcome, and produces no learning;
9. the lifecycle emits no recommendation, score, rank, priority, win probability, pricing advice, strategy, or decision;
10. every required review, approval, attestation, decision, submission, reflection, and handoff remains an attributable human or authoritative external act;
11. Bid / No Bid, pursuit conditions, commercial acceptance, submission authorization, withdrawal, and reopen remain Human Decisions where applicable;
12. readiness is multidimensional, descriptive, condition-visible, and bound to exact references;
13. no aggregate readiness measure or hidden rule determines lifecycle progression;
14. forward, backward, bypass, early-close, and reopen transitions are explicit, validated, and append-only;
15. amendments and official clarifications enter Evidence before affecting canonical records, intelligence, Briefs, proposals, reviews, or approvals;
16. revised evidence, analyses, Briefs, proposals, and packages never inherit stale review, readiness, approval, or decision status automatically;
17. cancelled procurements, withdrawals, failed submissions, unavailable Outcomes, declined retrospectives, and declined learning handoffs remain distinct explicit states;
18. closure and archival preserve all unresolved matters, prior stages, milestones, decisions, and exact information states;
19. invalid transitions fail closed at the affected boundary without destroying unrelated valid history;
20. identical immutable records and declared rules produce deterministic lifecycle projection and ordering;
21. historical reconstruction shows what was known, reviewed, decided, authorized, submitted, observed, and handed off at each material event;
22. future capabilities integrate through bounded versioned participation contracts without changing lifecycle fundamentals;
23. institutional learning remains an ongoing external capability, so the lifecycle records handoff rather than claiming learning completion;
24. accountable humans retain every judgment, acceptance, commitment, authorization, reflection, and closure choice; and
25. deterministic contract tests, replay tests, transition tests, failure tests, and human acceptance evidence are reported separately and accurately.

## Rationale for major architectural decisions

### Separate lifecycle coordination from capability execution

The lifecycle answers when governed work participates. Capabilities answer how evidence is acquired, truth is reconciled, intelligence is produced, briefs are rendered, proposals are written, compliance is checked, and learning is formed. Combining them would create an implicit master engine with authority it does not possess.

### Use stages for dominant context and participation for concurrency

Real pursuits overlap. Buyer evidence may be acquired while Opportunity Intelligence is reviewed, and an amendment may arrive during proposal work. One canonical stage keeps history intelligible; participation records preserve legitimate concurrent work without inventing contradictory current states.

### Treat milestones as evidenced events

Labels such as “complete,” “approved,” and “submitted” are unsafe when derived from task state or elapsed time. Immutable milestone references establish exactly what occurred and what authority supports it.

### Separate readiness, review, approval, decision, and transition

These concepts answer different questions. Collapsing them would let a completed review become an approval, readiness become authorization, or a stage change become a Human Decision. Separate records preserve accountability.

### Keep Opportunity and Buyer understanding distinct

They answer different questions, use different evidence, and have different analytical authority. They may overlap operationally, but neither can substitute for the other or silently merge into one briefing conclusion.

### Place pursuit authorization before proposal development

Proposal work commits human capacity. An accountable human decision should govern that commitment. The system supplies context and records the decision without recommending it.

### Keep proposal production and compliance independent

A proposal must exist before its coverage can be verified. Separate authorship and verification prevent production from certifying itself and preserve the distinction between completion, quality, and probable success.

### Separate final review from submission authorization

Review establishes what named people inspected and concluded. Authorization commits the organization to release one exact package. Treating review completion as authorization would erase executive accountability.

### Require receipt evidence for submission

An upload attempt or sent message does not prove successful submission. Exact package identity, channel, actor, time, and receipt preserve the operational fact without inference.

### Preserve Outcome as evidence, not retrospective explanation

An official result establishes what occurred within its scope. It does not prove why it occurred or validate earlier assumptions. Retrospective interpretation remains separate and attributed.

### Use learning handoff instead of “learning complete”

Institutional learning is cross-opportunity and ongoing. A single lifecycle can establish that its records are eligible and authorized for learning, but cannot declare the organization has finished learning from them.

### Allow backward transitions without rewriting history

Amendments, clarifications, additional evidence, and proposal revisions are normal. Append-only re-entry supports iteration while preserving what humans knew and approved at each earlier point.

### Permit early closure with explicit authority

No Bid, withdrawal, cancellation, and failed submission are legitimate lifecycle outcomes. Forcing every opportunity through proposal, submission, and learning stages would fabricate work. Explicit closure preserves the real path and its reason.

### Integrate future capability through participation contracts

Stable participation rules allow new intelligence and learning capabilities to appear where relevant without expanding lifecycle authority or requiring a new stage for every module.

## Foundational architecture assessment

This document completes the permanent high-level lifecycle model and connects the existing product doctrine, domain vocabulary, intelligence capabilities, Briefing Pack, and Bid Workspace across one pursuit.

The broader architectural foundation is **not yet complete enough to implement the Bid Workspace and Bid Lifecycle as production authority-bearing components**. One fundamental architecture remains required: a **Human Authority and Decision Record Architecture**.

The Constitution and current documents establish that humans own decisions, and the Workspace and lifecycle define what decision and approval references must preserve. They do not yet define the canonical source of human identity, organizational role, delegated authority, authority scope, effective period, revocation, separation of duties, or verification required to prove that an actor could make a particular decision or approval.

Without that architecture, an implementation could record a well-formed decision while being unable to establish that its named owner possessed the asserted authority. The missing document should govern identity and authority references, delegation, approval versus decision semantics, effective and revoked authority, attribution, auditability, and fail-closed verification. It should not choose decisions or become a generic identity product.

This gap does not invalidate the lifecycle architecture and does not block unrelated evidence, canonical-domain, analyst, or presentation work already governed independently. It should be resolved before production implementation of lifecycle transitions, Workspace approvals, pursuit authorization, submission authorization, or other authority-dependent behavior.

## Doctrine compliance

The Bid Lifecycle strengthens continuity across all four intelligence pillars by reducing coordination, transition, review, and historical-reconstruction effort around one opportunity. It preserves evidence before inference, canonical authority, analyst separation, immutable information states, explicit uncertainty, deterministic coordination, scoped failure, and sovereign human judgment.

The lifecycle owns no intelligence. It coordinates references to governed capabilities and records when attributable milestones and human acts occur.

This document introduces no implementation, user interface, API, workflow engine, persistence, database, schema, migration, prompt, AI behavior, retrieval, code, product change, recommendation, score, ranking, prediction, or decision. Repository doctrine remains unchanged.
