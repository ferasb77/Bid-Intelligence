# Document Metadata

| Field | Value |
|---|---|
| Document | `BID_INTELLIGENCE_BRIEFING_PACK.md` |
| Title | Bid Intelligence Briefing Pack Product Design |
| Authority Level | Level 3 — Product Doctrine |
| Version | 1.0.0 |
| Status | Proposed |
| Purpose | Define the canonical family, lifecycle, and presentation standard for customer-facing Bid Intelligence deliverables. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md), [`AGENT.md`](AGENT.md), [`GOVERNANCE.md`](GOVERNANCE.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), [Product Doctrine](docs/product/PRODUCT_VISION.md), [Architecture Doctrine](docs/architecture/ARCHITECTURE.md), [Engineering Doctrine](docs/engineering/CONTRIBUTING.md) |
| Governed Documents | Designs, specifications, evaluations, and presentation standards for every customer-facing Bid Intelligence briefing document. |
| Related Documents | [`BUYER_INTELLIGENCE_SPECIFICATION.md`](BUYER_INTELLIGENCE_SPECIFICATION.md), [`BUYER_BRIEF_DESIGN.md`](BUYER_BRIEF_DESIGN.md), [`EXECUTIVE_BRIEF_REVIEW_FRAMEWORK.md`](docs/evaluation/EXECUTIVE_BRIEF_REVIEW_FRAMEWORK.md), [`CUSTOMER_WORKFLOW.md`](docs/product/CUSTOMER_WORKFLOW.md) |

# Bid Intelligence Briefing Pack

## Overall philosophy

The Bid Intelligence Briefing Pack is the professional collection through which a consulting firm consumes Decision Preparation across a pursuit. It turns governed evidence and validated intelligence into documents that people can read, circulate, discuss, and revisit.

Customers should not need to understand intelligence engines, analytical modules, or processing stages. They receive a coherent set of briefings, each answering one important question at the moment that question becomes useful.

The pack prepares people to think. It does not make decisions, recommend actions, score opportunities, rank alternatives, prescribe proposal strategy, or replace professional judgment.

## Relationship to repository doctrine

The pack gives customer-facing form to the four pillars established by the [`MANIFESTO.md`](MANIFESTO.md):

- Opportunity Intelligence produces understanding of the opportunity.
- Buyer Intelligence produces understanding of the buyer.
- Proposal Compliance Intelligence produces verification of the completed response.
- Organizational Intelligence produces evidence-linked learning from completed pursuits.

Every volume follows [`PRODUCT_PRINCIPLES.md`](docs/product/PRODUCT_PRINCIPLES.md) and the information transitions in [`DECISION_DOCTRINE.md`](docs/architecture/DECISION_DOCTRINE.md). Facts, computations, observations, interpretations, assumptions, unknowns, questions, and Human Decisions retain distinct authority. A briefing presents validated intelligence; it does not become another analyst.

The pack must never advance an exclusion in [`ANTI_GOALS.md`](ANTI_GOALS.md). In particular, it is not a proposal-writing suite, win-probability product, autonomous bidding engine, or executive decision-maker.

## Purpose of the pack

The pack exists to:

1. establish a shared understanding across executive, bid, proposal, consulting, specialist, commercial, and operational roles;
2. reduce repeated reading, searching, comparison, and reconstruction;
3. bring the right evidence, uncertainty, and questions into each human discussion;
4. preserve continuity from opportunity receipt through outcome and learning;
5. provide durable internal documents that can be reviewed independently of the platform;
6. ensure every intelligence capability is judged by the professional artifact it produces.

The pack is a product family, not one continuously expanding report. Each volume remains bounded so readers can use the document appropriate to their current work.

## Briefing Pack lifecycle

```text
Opportunity received and processed
  ↓
Volume 1 — Executive Opportunity Brief
  ↓
Volume 2 — Buyer Brief
  ↓
Human pursuit deliberation and proposal development
  ↓
Volume 3 — Proposal Compliance Brief (future)
  ↓
Executive review and human submission authorization
  ↓
Submission and authoritative outcome
  ↓
Volume 4 — Pursuit Retrospective (future)
  ↓
Volume 5 — Institutional Learning Brief (future)
  ↓
Relevant evidence informs later briefing packs
```

The lifecycle is not an automated workflow. Humans determine when a briefing is ready, which people receive it, what questions need resolution, and what decisions follow. A revised source or proposal may produce a new revision of an existing volume without changing its purpose.

## Current volumes

### Volume 1 — Executive Opportunity Brief

- **Purpose:** Establish a concise, authoritative understanding of what is being requested and prepare the proposal kickoff.
- **Audience:** CEO / Managing Partner, Bid Manager, Proposal Manager, Senior Consultants, SMEs, Commercial Lead.
- **Primary question:** What is being requested?
- **Generated:** After the procurement package has been successfully processed and authoritative opportunity facts are available; regenerated when a material amendment changes that record.
- **Required inputs:** Canonical Opportunity, authoritative procurement evidence, validated Opportunity Intelligence, conflicts, unknowns, and the existing opportunity synthesis.
- **Relationship to other volumes:** Provides the opportunity facts referenced by the Buyer Brief and the future Proposal Compliance Brief. It does not contain buyer analysis.
- **Reading order:** Read first. Within the volume: opportunity at a glance, workstreams, characteristics, timeline, attention areas, preparation ownership, kickoff questions, clarification candidates, known unknowns, limitations.
- **Approximate reading time:** 8–10 minutes, excluding evidence inspection.
- **Expected business value:** Reduces RFP reconstruction, creates a common kickoff baseline, exposes immediate preparation needs, and preserves source uncertainty.
- **Deliberately excludes:** Buyer Intelligence, proposal drafting, compliance judgments, recommendations, Bid / No Bid, scoring, pricing advice, and win probability.

### Volume 2 — Buyer Brief

- **Purpose:** Establish an evidence-linked understanding of the organization issuing the opportunity.
- **Audience:** CEO / Managing Partner, Bid Manager, Proposal Manager, Senior Consultants, SMEs, Commercial Lead.
- **Primary question:** Who is asking?
- **Generated:** After buyer identity is verified and the permitted public evidence set has been collected and validated; refreshed when material public evidence changes.
- **Required inputs:** Canonical buyer and opportunity identity, authoritative procurement evidence, permitted public organizational sources, validated Buyer Intelligence, assumptions, unknowns, and limitations.
- **Relationship to other volumes:** Adds organizational context to Volume 1 without redefining opportunity facts. Later learning volumes may reference it while preserving its original evidence date.
- **Reading order:** Read after Volume 1 and before proposal planning. Within the volume, follow the structure governed by [`BUYER_BRIEF_DESIGN.md`](BUYER_BRIEF_DESIGN.md).
- **Approximate reading time:** About 10 minutes, excluding the Evidence Register.
- **Expected business value:** Gives the team a shared institutional context, distinguishes mandate from current priorities, and surfaces buyer questions that require human knowledge.
- **Deliberately excludes:** Buyer intent, relationship speculation, competitor analysis, proposal strategy, pricing advice, procurement tactics, recommendations, Bid / No Bid, and win probability.

## Future volumes

Future status does not authorize implementation. Each volume requires its own specification, evidence boundaries, validation, customer evaluation, and governance review.

### Volume 3 — Proposal Compliance Brief

- **Purpose:** Verify the completed proposal and submission package against the authoritative opportunity.
- **Audience:** Bid Manager, Proposal Manager, Senior Consultants, SMEs, Commercial Lead, executive reviewer.
- **Primary question:** What has the proposal addressed, and what remains unverified or missing?
- **Generated:** When a reviewable proposal exists and again before human submission authorization.
- **Required inputs:** Canonical Opportunity, source requirements, completed proposal, submission package, traceable response relationships, and validated Proposal Compliance Intelligence.
- **Relationship to other volumes:** Uses Volume 1’s opportunity authority and may use Volume 2 for reader context, but buyer interpretation cannot alter compliance findings.
- **Reading order:** After the proposal draft; before executive review and submission authorization.
- **Approximate reading time:** 10–15 minutes for the executive view, with a detailed coverage appendix for working review.
- **Expected business value:** Makes gaps and evidence coverage visible early enough for accountable correction and reduces avoidable submission defects.
- **Deliberately excludes:** Proposal generation, automatic rewriting, competitiveness judgments, winner prediction, submission authorization, and executive recommendations.

### Volume 4 — Pursuit Retrospective

- **Purpose:** Preserve what was known, decided, submitted, and learned after an authoritative outcome or formal close.
- **Audience:** CEO / Managing Partner, Bid Manager, Proposal Manager, Senior Consultants, Commercial Lead.
- **Primary question:** What happened during this pursuit, and what did the participating humans learn?
- **Generated:** After outcome and debrief evidence are available, or after a pursuit is formally closed without submission.
- **Required inputs:** Prior briefing volumes, Human Decision records, submitted proposal identity, authoritative Outcome, Buyer Debrief, and attributed participant reflections.
- **Relationship to other volumes:** Closes the individual pursuit record. It preserves earlier knowledge states rather than judging them with hindsight.
- **Reading order:** After outcome capture; before lessons enter cross-pursuit Organizational Intelligence.
- **Approximate reading time:** 10–15 minutes.
- **Expected business value:** Retains rationale, distinguishes outcome facts from team interpretation, and prevents lessons from disappearing into informal conversation.
- **Deliberately excludes:** Blame, retroactive certainty, causal claims unsupported by evidence, performance rankings, and automated prescriptions for future bids.

### Volume 5 — Institutional Learning Brief

- **Purpose:** Present evidence-linked observations and open questions that recur across completed pursuits.
- **Audience:** Company leadership, Bid Manager, practice leaders, proposal leadership, and organizational-learning owners.
- **Primary question:** What is the organization learning across its pursuits?
- **Generated:** At a human-selected review interval or for a bounded learning question after sufficient comparable evidence exists.
- **Required inputs:** Historical RFPs, proposals, Human Decisions, Outcomes, Buyer Debriefs, Pursuit Retrospectives, and validated Organizational Intelligence.
- **Relationship to other volumes:** Draws from completed packs while retaining opportunity, buyer, time, and evidence boundaries. Its observations may inform questions in later packs but cannot overwrite them.
- **Reading order:** Outside the live-pursuit sequence; consulted when preparing relevant future work or conducting leadership learning reviews.
- **Approximate reading time:** 15 minutes for the core briefing, with evidence appendices available separately.
- **Expected business value:** Makes organizational experience reusable, exposes recurring evidence gaps, and improves future inquiry without reducing history to a prediction.
- **Deliberately excludes:** Win-probability models, causal claims from correlation, buyer or staff rankings, universal playbooks, and automated strategy.

## Volumes not adopted in this design

### Capability Gap Brief

Not adopted as a standalone pack volume. Without a separately governed organizational-capability authority, it could turn missing evidence into an unsupported capability judgment or Bid / No Bid signal. Verified capability questions may appear in kickoff preparation; a future capability must first define its evidence and authority.

### Engagement Readiness Brief

Not adopted within the bid Briefing Pack. Delivery readiness begins after award and belongs to engagement governance unless a future product decision explicitly extends the platform boundary.

### Knowledge Transfer Brief

Not adopted as a separate volume because its intended value is already served by the Pursuit Retrospective and Institutional Learning Brief. A delivery handoff may later use a governed extract, but duplicating a volume would fragment authority.

These exclusions are product-design choices, not permanent constitutional anti-goals. They may be reconsidered through product and architecture review when a distinct customer question, authoritative input, and human owner are established.

## Reading sequence

### Before proposal writing

Read Volume 1 first to understand the requested work. Read Volume 2 second to understand the issuing organization. Discuss the questions and unknowns from both volumes together, without merging their facts or analytical ownership.

### During proposal development

Return to Volumes 1 and 2 as reference documents. A material procurement amendment creates a revised Volume 1 and may require review of Volume 2 relevance. Neither volume becomes a drafting instruction.

### Before submission

Read Volume 3 against the completed proposal. Executive reviewers may consult Volumes 1 and 2 for context, but only a named human authorizes submission.

### After outcome

Read Volume 4 to preserve the pursuit’s evidence and participant learning. Consult Volume 5 only when cross-pursuit evidence is sufficient and the learning question is explicit.

No reader must consume every volume in one sitting. Each has a bounded question and time of use.

## Document relationships

```text
Executive Opportunity Brief ── authoritative opportunity context ──┐
                                                                  ├─> Proposal Compliance Brief
Buyer Brief ─────────────── public buyer context ──────────────────┘

Opportunity + Buyer + Compliance Briefs
                 + Human Decisions + Outcome + Debrief
                                  ↓
                         Pursuit Retrospective
                                  ↓
                    Institutional Learning Brief
                                  ↓
                 evidence and questions for later packs
```

References cross volume boundaries; authority does not. Volume 2 cannot change an opportunity deadline. Volume 3 cannot treat buyer interpretation as a requirement. Volume 5 cannot rewrite what was known when a Human Decision was made.

## Naming conventions

- The product family is **Bid Intelligence Briefing Pack**.
- A customer-facing document is a **Brief** when it prepares a bounded understanding question.
- Current names are **Executive Opportunity Brief** and **Buyer Brief**. Future names are reserved only after their specifications are approved.
- Volume numbers express the standard reading sequence, not importance, confidence, or product maturity.
- Titles use professional domain language. They do not expose analyst, engine, pipeline, stage, model, or implementation names.
- Every issued document identifies opportunity, volume title, document revision, evidence cutoff date, status, and confidentiality classification.
- File names should remain human-readable and stable: `[Opportunity Reference] — [Volume Name] — [Revision]`.

## Versioning philosophy

The pack, each volume design, and each generated document have separate versions:

- **Pack version** changes when the family, lifecycle, or cross-volume authority changes.
- **Volume-design version** changes when a volume’s purpose, structure, or information hierarchy changes.
- **Document revision** changes when source evidence, analysis, or reviewed presentation changes for one opportunity.

Compatible clarification increments a patch version. An additive compatible section or governed capability increments a minor version. A changed purpose, authority boundary, required reading relationship, or incompatible structure increments a major version.

Document revisions never rewrite earlier issued briefs. Each retains its evidence cutoff and can be compared with its predecessor. A newer revision does not imply that earlier human decisions were defective; it records a later information state.

## Professional presentation philosophy

Every volume should look and read like a briefing prepared by an experienced consulting leader:

- lead with the question and context the audience needs;
- use clear headings, restrained prose, and short evidence-supported statements;
- keep the core reading path within the stated time budget;
- use tables only for genuine comparison or structured reference;
- keep evidence markers unobtrusive and evidence registers complete;
- express dates, currencies, quantities, and uncertainty consistently;
- distinguish information classes through labels and typography, not color alone;
- preserve accessibility across digital and printable forms;
- show unknowns and limitations with the same professional care as known facts;
- omit empty decorative sections unless their absence itself is material;
- avoid AI language, software terminology, internal identifiers, and generated-text mannerisms.

The pack is coherent through shared visual discipline and evidence treatment, not identical templates. Each volume’s structure follows its customer question.

## Acceptance criteria

The Briefing Pack design is realized only when:

1. every volume answers one bounded professional question;
2. every current volume maps to a constitutional intelligence pillar and customer-workflow moment;
3. facts, computation, interpretation, assumptions, alternatives, unknowns, questions, and Human Decisions retain distinct authority;
4. every material fact and interpretation remains traceable to evidence;
5. uncertainty, conflict, freshness, and source limitations remain visible;
6. presentation introduces no reasoning absent from validated intelligence;
7. volumes preserve one another’s domain authority and never silently merge conclusions;
8. each core document fits its declared reading time in representative real opportunities;
9. intended users can circulate each document internally without substantial editing;
10. no volume contains recommendations, Bid / No Bid advice, win probability, opportunity scoring, competitor ranking, proposal strategy, pricing advice, or executive conclusions;
11. human ownership is explicit wherever deliberation, authorization, reflection, or learning requires judgment;
12. revisions are identifiable, comparable, and tied to an evidence cutoff;
13. a reader can move from current opportunity understanding to later learning without losing provenance or temporal context;
14. role-based evaluation demonstrates reduced reading and reconstruction effort;
15. the pack remains useful when any optional future volume is absent.

Each volume must pass its own customer review framework. Technical validation alone cannot establish professional usefulness.

## Success metrics

Success is measured through human use, with dimensions retained separately rather than combined into a score:

- time required to reach an accurate working understanding;
- source-searching still required after reading;
- executive readability and internal distributability;
- reduction in repeated explanation during kickoff and review;
- trust in evidence traceability;
- ability to identify material unknowns and assumptions;
- quality of the human discussion enabled;
- reuse of prior evidence and learning in later relevant pursuits;
- preservation of role-specific disagreement and judgment;
- frequency and severity of material corrections after circulation.

The pack is not successful because it contains more volumes, generates more text, or receives a high aggregate score. It is successful when experienced professionals understand the opportunity and buyer more quickly, verify their work more reliably, retain organizational learning, and remain clearly responsible for what they decide.

## Rationale for major design decisions

### Organize around documents, not modules

Professional teams circulate briefs, not software architecture. Document language keeps the product centered on customer work while internal capabilities remain governed behind the presentation boundary.

### Use a pack rather than one master report

One report would grow across the pursuit, mix authority, and overwhelm time-constrained readers. Bounded volumes preserve purpose, timing, ownership, and selective circulation.

### Make Volumes 1 and 2 companions

Opportunity and buyer understanding are both needed before writing, but they rely on different evidence and answer different questions. Sequential companion documents preserve that distinction.

### Place compliance after proposal development

Compliance requires a completed response to compare. Moving it earlier would confuse requirements with response coverage; combining it with generation would allow authorship to certify itself.

### Separate individual retrospective from institutional learning

A Pursuit Retrospective preserves one pursuit and attributed human reflection. An Institutional Learning Brief compares across pursuits. Combining them would encourage premature generalization.

### Avoid a mandatory linear workflow

Real pursuits iterate when amendments, clarification, or new evidence arrives. The lifecycle supplies a reference sequence while allowing human-controlled revision and return.

### Keep evidence appendices attached to each volume

A central evidence pool alone would make individual briefs difficult to verify and circulate. Volume-level registers preserve local closure while stable references prevent unnecessary duplication of source content.

### Keep Human Decisions outside analytical volumes

Briefs prepare and record context; authorized people decide. Human Decisions may be referenced in retrospective learning, but no analytical volume presents them as system conclusions.

### Reject automatic cross-volume synthesis

Combining facts and findings into one “answer” would erase analyst boundaries and create implicit prioritization. Cross-references give readers continuity without transferring authority.

### Require usefulness evaluation for every volume

Customers experience the artifact, not the internal capability. Every volume must demonstrate reduced cognitive effort, professional readability, evidence trust, and discussion value with real users before production readiness is claimed.
