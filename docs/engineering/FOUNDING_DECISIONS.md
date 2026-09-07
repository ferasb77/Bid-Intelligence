# Document Metadata

| Field | Value |
|---|---|
| Document | `docs/engineering/FOUNDING_DECISIONS.md` |
| Title | Founding Product and Architecture Decisions |
| Authority Level | Level 5 — Engineering Doctrine |
| Version | 1.0.0 |
| Status | Ratified Historical Record |
| Purpose | Preserve the identity-defining decisions on which Bid Intelligence was founded. |
| Higher Authority | Constitutional layer: [`MANIFESTO.md`](../../MANIFESTO.md), [`AGENT.md`](../../AGENT.md), [`GOVERNANCE.md`](../../GOVERNANCE.md), [`ANTI_GOALS.md`](../../ANTI_GOALS.md). All documents in [`docs/product/`](../product/PRODUCT_VISION.md) and [`docs/architecture/`](../architecture/ARCHITECTURE.md). |
| Governed Documents | Future decision records that interpret or propose changes to these founding choices. |
| Related Documents | [`CONTRIBUTING.md`](CONTRIBUTING.md), [`REPOSITORY_STANDARDS.md`](REPOSITORY_STANDARDS.md), [`DECISION_DOCTRINE.md`](../architecture/DECISION_DOCTRINE.md) |

# Founding Decisions

This is a record of identity, not a chronological change log. These decisions remain subordinate to their higher-authority doctrine. Changing one requires explicit product and architectural review and may require a constitutional amendment.

## FD-01 — Decision Preparation rather than AI automation

- **Decision:** Build a Decision Preparation Platform that improves the evidence available to accountable professionals.
- **Why:** Pursuit decisions combine evidence, context, responsibility, and judgment. Automating the answer would weaken accountability and disguise uncertainty.
- **Alternatives considered:** Autonomous pursuit orchestration; automated executive recommendations; a general AI assistant for bidding.
- **Long-term implications:** Every capability must identify what it prepares, what authority it has, and where the human decision begins.

## FD-02 — Proposal writing remains outside the competitive focus

- **Decision:** Support the workflow before and after writing while relying on experienced authors and existing general-purpose tools for proposal generation.
- **Why:** Writing capability is abundant. Reliable opportunity understanding, compliance, and organizational learning remain underserved.
- **Alternatives considered:** End-to-end proposal generation; template-first authoring; competing directly with general-purpose language tools.
- **Long-term implications:** Generated prose cannot become the product’s measure of value or displace investment in evidence and verification.

## FD-03 — Four intelligence pillars define the product

- **Decision:** Organize the product around Opportunity Intelligence, Buyer Intelligence, Proposal Compliance Intelligence, and Organizational Intelligence.
- **Why:** These are the connected problems that surround professional proposal writing and compound across pursuits.
- **Alternatives considered:** One undifferentiated bid workflow; a compliance-only product; a broad procurement suite.
- **Long-term implications:** Every feature identifies its pillar, and cross-pillar reuse preserves separate authority and responsibility.

## FD-04 — Human judgment remains sovereign

- **Decision:** Humans make Bid / No Bid, strategic, commercial, pricing, commitment, and submission decisions.
- **Why:** Those decisions carry organizational accountability that software does not possess.
- **Alternatives considered:** Automated gates; algorithmic pursuit approval; system-triggered commitments.
- **Long-term implications:** The system may prepare evidence, questions, and transparent advice but must record the final choice as a Human Decision.

## FD-05 — Evidence before inference

- **Decision:** Require meaningful reasoning to remain traceable to authoritative evidence and keep facts distinct from interpretation.
- **Why:** Fluent unsupported conclusions are unsafe in consequential professional work.
- **Alternatives considered:** Narrative summaries without provenance; model confidence as a substitute for evidence; post-hoc citations.
- **Long-term implications:** Stable evidence identity, provenance closure, typed statements, explicit uncertainty, and fail-closed validation are architectural requirements.

## FD-06 — Adopt the Moneyball principle

- **Decision:** Prefer observable evidence and cumulative learning to intuition, hidden scoring, and isolated prediction.
- **Why:** Measurable observations can improve professional inquiry without pretending to replace expertise.
- **Alternatives considered:** Opaque pursuit scores; win probabilities; causal claims from historical correlation.
- **Long-term implications:** Individual indicators remain inspectable, correlation is never causation, and historical data supports learning rather than deterministic forecasts.

## FD-07 — Optimize for Capability Development and Boutique Consulting Firms

- **Decision:** Design for firms selling expertise in leadership, learning, HR, organizational development, executive education, and related boutique consulting work.
- **Why:** Their pursuits require professional judgment, credible evidence, and complex coordination but often lack fit-for-purpose decision infrastructure.
- **Alternatives considered:** A generic procurement platform; enterprise sourcing administration; universal proposal software.
- **Long-term implications:** Relevance to this customer workflow takes precedence over broad category coverage.

## FD-08 — Separate Buyer Intelligence from Opportunity Intelligence

- **Decision:** Treat the current opportunity and the buyer’s broader observable context as separate intelligence domains.
- **Why:** Procurement documents can establish opportunity facts but cannot, by themselves, establish buyer history, preference, or intent.
- **Alternatives considered:** Inferring buyer behavior from a single RFP; merging all context into one opportunity summary.
- **Long-term implications:** Buyer claims require their own evidence, provenance, uncertainty, and analytical boundaries. Opportunity processing does not silently become buyer analysis.

## FD-09 — Separate Proposal Compliance from proposal generation

- **Decision:** Verify completed proposal responses against authoritative requirements without owning their authorship.
- **Why:** Independent verification protects traceability and avoids allowing the same generative act to certify itself.
- **Alternatives considered:** Compliance inferred during drafting; auto-generated responses treated as automatically complete.
- **Long-term implications:** Coverage remains item-level and evidence-linked; completeness is never equated with competitiveness or success.

## FD-10 — Organizational Intelligence is the long-term advantage

- **Decision:** Preserve RFPs, proposals, Human Decisions, Outcomes, and Buyer Debriefs as connected organizational learning evidence.
- **Why:** A firm’s accumulated experience is more durable and distinctive than any individual model or generated proposal.
- **Alternatives considered:** Treating each pursuit as an isolated transaction; retaining only documents without decisions or outcomes; prediction-first analytics.
- **Long-term implications:** Information models preserve temporal context and stable relationships so learning can compound without rewriting history.

## FD-11 — The Decision Workspace is the human interaction boundary

- **Decision:** Present validated analyses in a deterministic workspace that performs no reasoning, ranking, prioritization, scoring, recommendation, or decision.
- **Why:** Human deliberation needs organized information without a presentation layer quietly becoming another analyst.
- **Alternatives considered:** A single synthesized verdict; ranked findings; executive dashboards centered on composite scores.
- **Long-term implications:** Analyst boundaries, alternatives, assumptions, unknowns, questions, and limitations remain visible. Presentation never acquires analytical authority.

## FD-12 — Decision Intelligence prepares rather than recommends

- **Decision:** Establish typed contracts for facts, computations, observations, inferences, hypotheses, unknowns, management questions, recommendations where explicitly permitted, and Human Decisions.
- **Why:** A shared semantic discipline prevents analysis from drifting into unexplained advice or executive authority.
- **Alternatives considered:** Unstructured analyst prose; every analyst returning recommendations; treating confidence as a decision score.
- **Long-term implications:** Analysts declare capabilities, consumers validate versions and references, and a recommendation—when allowed—remains advice rather than authority. The first Opportunity Intelligence Analyst intentionally emits none.

## Using this record

Future decision records may refine implementation and bounded architecture while preserving these choices. If a proposal would reverse a founding decision, it must state that fact directly and follow the authority and amendment process in [`GOVERNANCE.md`](../../GOVERNANCE.md). Founding identity must never change through accumulated local exceptions.
