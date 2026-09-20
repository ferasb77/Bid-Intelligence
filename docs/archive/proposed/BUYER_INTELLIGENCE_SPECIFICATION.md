# Document Metadata

| Field | Value |
|---|---|
| Document | `BUYER_INTELLIGENCE_SPECIFICATION.md` |
| Title | Buyer Intelligence v1 Functional Specification |
| Authority Level | Level 4 — Functional Specification |
| Version | 1.0.0 |
| Status | Proposed |
| Purpose | Define the first Buyer Intelligence capability and the future Buyer Intelligence Brief without prescribing implementation. |
| Higher Authority | [`MANIFESTO.md`](../../../MANIFESTO.md), [`AGENT.md`](../../../AGENT.md), [`GOVERNANCE.md`](../../../GOVERNANCE.md), [`ANTI_GOALS.md`](../../../ANTI_GOALS.md), [Product Doctrine](../../product/PRODUCT_VISION.md), [Architecture Doctrine](../../architecture/ARCHITECTURE.md), [Engineering Doctrine](../../engineering/CONTRIBUTING.md) |
| Governed Documents | Future Buyer Intelligence architecture, contracts, designs, implementation plans, validation, and evaluation criteria. |
| Related Documents | [`PRODUCT_VISION.md`](../../product/PRODUCT_VISION.md), [`CUSTOMER_WORKFLOW.md`](../../product/CUSTOMER_WORKFLOW.md), [`DOMAIN_MODEL.md`](../../architecture/DOMAIN_MODEL.md), [`DECISION_DOCTRINE.md`](../../architecture/DECISION_DOCTRINE.md), [`PRODUCT_ROADMAP.md`](../../product/PRODUCT_ROADMAP.md) |

# Buyer Intelligence v1

## Purpose

Buyer Intelligence helps a consulting firm understand the organization issuing an opportunity. It prepares the proposal team with traceable organizational context before proposal writing begins.

Opportunity Intelligence answers, **“What is this opportunity?”** Buyer Intelligence answers, **“Who is asking?”** Neither answers whether the firm should bid, how it should compete, what it should charge, or whether it will win.

Buyer Intelligence is a preparation capability. It is not prediction, recommendation, procurement strategy, or sales intelligence.

## Product outcome

Version 1 should let an experienced professional establish:

- the buyer’s verified identity and organizational form;
- its public mandate and stated responsibilities;
- the business functions visibly connected to the procurement;
- organizational priorities that authoritative public sources state;
- the department or organizational unit that issued or owns the procurement, when evidenced;
- public context needed to understand the opportunity;
- how the documented opportunity may relate to stated organizational objectives;
- what remains unknown, ambiguous, assumed, or interpretive.

The capability succeeds when a proposal team can begin a better-informed kickoff without mistaking public information or analyst interpretation for buyer intent.

## Responsibilities

Buyer Intelligence is responsible for:

1. identifying the buyer represented in the authoritative opportunity record;
2. organizing permitted public evidence about that buyer;
3. establishing source-supported buyer facts;
4. separating current organizational facts from historical procurement facts;
5. producing bounded interpretations about relevance to the opportunity;
6. exposing assumptions, competing hypotheses, limitations, and unknowns;
7. raising unanswered management questions where human judgment is required;
8. preserving evidence identity, provenance, publication context, and access context;
9. returning a validated Buyer Intelligence analysis suitable for presentation in the Decision Workspace and a Buyer Intelligence Brief.

It does not own opportunity extraction, canonical opportunity facts, proposal content, compliance, commercial decisions, or organizational learning across the firm’s own bids.

## Boundaries

Buyer Intelligence must not:

- predict a contract award or estimate win probability;
- recommend Bid / No Bid or any executive decision;
- infer corruption, impropriety, favoritism, or undisclosed relationships;
- speculate about personal relationships, influence, or buyer preference;
- rank or assess competitors;
- recommend pricing, commercial terms, negotiation, or risk acceptance;
- recommend proposal themes, messaging, positioning, or pursuit strategy;
- convert a public statement into proof of actual internal behavior;
- treat procurement history as a causal predictor of a current outcome;
- infer an issuing department when the evidence identifies only the organization;
- infer current priorities from stale publications without an explicit limitation;
- replace executive, consultant, legal, commercial, or relationship judgment.

The absence of public evidence must produce an Unknown, not a negative inference.

## Inputs

Version 1 consumes:

- the validated Canonical Opportunity identity and relevant canonical observations;
- the authoritative procurement package and its source references;
- the validated Opportunity Intelligence analysis when cross-reference is useful;
- captured evidence from permitted public sources;
- explicit evaluation context, including buyer identity, opportunity identity, source date, and supported contract versions.

Opportunity Intelligence remains authoritative for the opportunity. Buyer Intelligence may link to opportunity facts but cannot modify them, reinterpret unresolved opportunity conflicts as resolved, or duplicate opportunity normalization.

No private CRM data, relationship notes, personal data enrichment, competitor data, or unverified sales intelligence belongs in Version 1.

## Authoritative sources

Source authority depends on what a source is competent to establish.

### Opportunity authority

The issued procurement package, amendments, procurement notice, and official clarification responses establish the buyer identity and procurement context within their stated scope. They do not establish the buyer’s unstated motives.

### Organizational authority

Primary organizational sources may establish mandate, governance, structure, functions, plans, and published priorities. Examples include:

- the buyer’s official website;
- enabling legislation, regulation, charter, or other official constituting instrument;
- official annual reports, corporate plans, strategic plans, and departmental plans;
- official organizational charts, leadership directories, and departmental pages;
- official budgets, public accounts, performance reports, and accessibility plans;
- official policy, program, service, research, and public consultation publications.

### Procurement-history authority

Verified procurement history must come from attributable official notices, award records, contract disclosures, amendments, or buyer publications. It remains a record of prior procurements. It does not prove preference, future behavior, incumbent advantage, or the likely result of the present opportunity.

## Permitted public sources

Version 1 permits only publicly accessible, attributable sources with a clear institutional owner:

- official buyer-controlled domains and publications;
- official legislative and regulatory repositories;
- official government procurement portals and award-disclosure systems;
- official public-sector budget, audit, accountability, and performance repositories;
- official public registries when they are authoritative for the fact asserted.

Search results, snippets, generated summaries, aggregators, marketing databases, anonymous material, personal social media, inferred contact databases, and unattributed reposts are not evidence. News, commentary, and other secondary sources are outside Version 1. A later version may admit a governed secondary-source class, but it must remain explicitly distinct from authoritative buyer facts.

Public availability does not remove obligations concerning privacy, licensing, retention, or ethical use.

## Evidence doctrine

Every retained evidence occurrence must include:

- a stable evidence identifier;
- source owner and source type;
- document or page title;
- canonical location or publication identity;
- publication date when stated;
- retrieval date for changeable public material;
- exact locator and bounded supporting excerpt where available;
- language;
- applicable organizational scope;
- verification and freshness status;
- relationship to the buyer and opportunity.

The system must preserve distinct evidence occurrences even when they support the same fact. A current official source may supersede an older statement only through an explicit, verified relationship. Source disappearance after capture does not erase the retained occurrence, but it must affect availability and freshness status.

## Information classes

Buyer Intelligence keeps these classes structurally distinct:

### Authoritative buyer facts

Facts directly supported by sources competent to establish buyer identity, mandate, structure, or official responsibility. They carry no confidence score.

### Public organizational information

Attributed public statements about plans, priorities, functions, programs, or operating context. They remain statements made by the organization, not proof of execution, commitment, or internal preference.

### Verified procurement history

Past notices, awards, amendments, and disclosures with verified identity and provenance. History is time-bounded and must not be generalized beyond the evidence.

### Reasoned interpretation

Transparent analysis of relationships among buyer facts, public organizational information, procurement history, and current opportunity facts. It is attributed to Buyer Intelligence, carries confidence, and exposes its supporting and contradicting evidence.

### Explicit assumptions

Provisional premises required for an interpretation. An assumption is never presented as buyer fact and cannot silently supply missing evidence.

### Explicit unknowns

Missing, unavailable, ambiguous, stale, conflicted, or unsupported information. Unknowns remain visible in analysis, presentation, and review.

## Reasoning doctrine

Version 1 may reason only about organizational relevance that follows transparently from documented sources. Permitted reasoning includes:

- relating an opportunity’s documented scope to a buyer’s stated mandate or published priority;
- identifying which documented business functions appear relevant;
- noting that multiple organizational units or objectives may be implicated;
- identifying alignment, tension, ambiguity, or missing context between public statements and the opportunity;
- offering multiple plausible interpretations when the evidence does not support one conclusion;
- raising management questions about what context matters to the firm.

Permitted language remains bounded: “the published plan identifies,” “the opportunity appears related to,” or “the available evidence does not establish.” It must not become “the buyer wants,” “the evaluator will prefer,” or “this will improve the chance of winning.”

Every interpretation must link to existing evidence and relevant canonical opportunity entities. No free-text citation may replace typed references. Contradictory evidence must remain visible. Reasoning cannot resolve source conflicts or repair unsupported facts.

## Assumptions

Assumptions are used only when necessary to state the boundary of an interpretation. Each assumption must:

- have a stable identity;
- state what is being provisionally accepted;
- identify the interpretation that depends on it;
- explain why evidence does not establish it;
- remain visible beside the resulting interpretation;
- be removable without changing authoritative facts.

An interpretation that depends materially on an assumption cannot be described as established.

## Unknowns

Unknowns are grouped as:

- missing buyer evidence;
- unavailable or inaccessible public information;
- ambiguous organizational ownership;
- conflicting public statements;
- stale information;
- unknown relationship between an organizational objective and the procurement;
- unsupported questions about buyer intent, evaluator preference, or internal decision-making.

Where a question cannot be answered within Version 1’s permitted evidence, the output states that limit. It does not widen the source boundary automatically.

## Confidence

Confidence applies only to Reasoned Interpretation and Hypotheses. It never applies to authoritative buyer facts, public-source facts, procurement-history facts, or deterministic computations.

Confidence reflects the strength, specificity, freshness, agreement, and scope of supporting evidence. It is not a probability, score, rank, or prediction. A confidence label must not soften a conflict or make a weakly evidenced claim acceptable. Unsupported interpretation is rejected regardless of confidence.

## Future Buyer Intelligence Brief

An excellent Buyer Intelligence Brief should contain the following sections in deterministic order.

### 1. Buyer at a Glance

Verified identity, organizational form, jurisdiction, public mandate, and the buyer’s role in the opportunity. This section contains facts only.

### 2. Public Mandate and Responsibilities

The buyer’s formally stated purpose and responsibilities, with source dates and evidence links. Statutory mandate is distinguished from organizational messaging.

### 3. Relevant Organizational Functions

Departments, functions, programs, or accountable units visibly connected to the procurement. Unknown ownership remains explicit.

### 4. Stated Organizational Priorities

Current published priorities relevant to the opportunity. Each item states who published it, when, and its applicable scope. The section does not infer evaluator preference.

### 5. Opportunity-to-Organization Context

Evidence-linked interpretations of how the opportunity appears to support stated mandate, functions, or objectives. Facts and interpretation are visually and structurally distinct. Alternative interpretations remain visible.

### 6. Public Procurement Context

For Version 1, only current-procurement context needed to understand the buyer’s role. Later versions may add verified history under an explicit versioned section.

### 7. Management Questions

Unanswered questions requiring human organizational judgment, such as which buyer context is material to kickoff discussion. Questions do not contain recommended answers or proposal strategy.

### 8. Known Unknowns and Assumptions

Professional-language presentation of missing evidence, ambiguity, staleness, conflict, unavailable information, and explicit assumptions. Technical identifiers may appear in an evidence appendix.

### 9. Evidence Register

The authoritative evidence used, organized by source class with stable references, dates, locators, freshness, and verification status.

### 10. Limitations

Source coverage, time boundaries, language coverage, unavailable information, and analytical constraints.

The brief contains no competitor ranking, pricing advice, pursuit recommendation, proposal strategy, Bid / No Bid view, win probability, or executive conclusion.

## Output structure

Buyer Intelligence should eventually return a validated, immutable Decision Analysis compatible with the shared Decision Intelligence contracts. Its substantive collections are:

- evidence used;
- buyer facts;
- public organizational facts;
- verified procurement-history facts, when supported by the version;
- deterministic computed facts, if any;
- interpretations;
- competing hypotheses;
- assumptions;
- unknowns;
- management questions;
- limitations.

Version 1 returns no recommendations. The presentation brief is derived from this validated output and introduces no new reasoning.

## Validation

Validation fails closed when:

- buyer or opportunity identity is missing or inconsistent;
- an evidence reference cannot be resolved;
- a source class is not permitted by the active version;
- provenance, source ownership, locator, or required date context is absent;
- an organizational fact exceeds what its source can establish;
- an interpretation lacks supporting evidence or links to an unknown entity;
- an interpretation is emitted as a fact;
- confidence is attached to a fact or computation;
- an assumption is hidden or used as evidence;
- a conflict or material unknown is omitted or silently resolved;
- stale information is presented as current without qualification;
- unsupported analyst or contract versions are supplied;
- output contains a prediction, competitor ranking, pricing advice, procurement strategy, proposal strategy, Bid / No Bid recommendation, or executive decision;
- authoritative inputs are mutated;
- presentation introduces reasoning absent from the validated analysis.

Validation does not repair, rewrite, or remove invalid conclusions automatically. Valid unrelated evidence remains available while the affected output fails or remains unresolved.

## Staged roadmap

### Version 1 — Organization Understanding

Establish verified buyer identity, mandate, responsibilities, relevant functions, published priorities, opportunity alignment interpretations, unknowns, and management questions using primary official sources. No procurement-history analysis beyond current-opportunity context.

### Version 2 — Procurement Context

Add verified understanding of the buyer’s procurement framework, public policies, governance, standard processes, and accountable procurement functions. Describe published rules and structures without turning them into tactical proposal advice.

### Version 3 — Historical Procurement Behaviour

Add verified, time-bounded procurement notices, amendments, awards, and disclosures. Expose observable patterns and alternative explanations without inferring preference, incumbent advantage, or future outcomes.

### Version 4 — Institutional Learning

Connect buyer evidence with the consulting firm’s governed records of past opportunities, proposals, decisions, outcomes, and debriefs. Keep public buyer facts separate from the firm’s internal experience and interpretation.

### Version 5 — Cross-Opportunity Organizational Intelligence

Support evidence-linked comparison across buyers and opportunities to reveal recurring organizational questions and learning themes. Preserve buyer boundaries, temporal context, confidentiality, and the prohibition on prediction and scoring.

Each version requires its own evidence permissions, contracts, validation, evaluation, and compatibility decision. A later version must not reinterpret earlier records silently.

## Acceptance criteria

Buyer Intelligence v1 is ready for implementation acceptance only when the future capability can demonstrate that:

1. it consumes the Canonical Opportunity without changing it;
2. it uses only permitted, attributable public sources;
3. every retained fact and interpretation closes against existing evidence identifiers;
4. authoritative buyer facts, public organizational information, procurement history, interpretation, assumptions, and unknowns remain distinct;
5. current and stale statements cannot be confused;
6. contradictory sources remain visible and unresolved unless an explicit authority rule applies;
7. confidence appears only on reasoning;
8. unsupported buyer intent, relationship, preference, corruption, and causal claims are rejected;
9. outputs contain no award prediction, win probability, competitor ranking, pricing or commercial advice, proposal strategy, Bid / No Bid recommendation, or executive decision;
10. unknowns and alternative interpretations survive analysis and presentation;
11. identical authoritative inputs and versions produce identical deterministic facts, identities, and ordering;
12. the Buyer Intelligence Brief preserves the validated analysis and adds no reasoning;
13. an experienced Bid Manager can identify who the buyer is, what it publicly exists to do, which functions and priorities are relevant, what evidence supports that context, and what remains unknown;
14. human reviewers retain responsibility for relevance, relationship context, pursuit choices, and action.

The acceptance decision is human and evidence-based. No aggregate score or model output confers production readiness.
