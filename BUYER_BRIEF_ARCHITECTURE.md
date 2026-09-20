# Document Metadata

| Field | Value |
|---|---|
| Document | `BUYER_BRIEF_ARCHITECTURE.md` |
| Title | Buyer Brief Presentation Architecture |
| Authority Level | Level 5 — Presentation Architecture |
| Version | 1.0.0 |
| Status | Implemented |
| Purpose | Govern the deterministic presentation of validated Buyer Intelligence as Volume 2 of the Bid Intelligence Briefing Pack. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md), [`GOVERNANCE.md`](GOVERNANCE.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), [Architecture Doctrine](docs/architecture/ARCHITECTURE.md), [`BUYER_INTELLIGENCE_SPECIFICATION.md`](docs/archive/proposed/BUYER_INTELLIGENCE_SPECIFICATION.md), [`BUYER_INTELLIGENCE_ARCHITECTURE.md`](BUYER_INTELLIGENCE_ARCHITECTURE.md), [`BUYER_BRIEF_DESIGN.md`](docs/archive/proposed/BUYER_BRIEF_DESIGN.md), and [`BID_INTELLIGENCE_BRIEFING_PACK.md`](docs/archive/proposed/BID_INTELLIGENCE_BRIEFING_PACK.md) |
| Governed Documents | [`buyer_brief.py`](buyer_brief.py) and [`tests/test_buyer_brief.py`](tests/test_buyer_brief.py) |
| Related Documents | [`BUYER_DOMAIN_ARCHITECTURE.md`](BUYER_DOMAIN_ARCHITECTURE.md), [`BUYER_EVIDENCE_ARCHITECTURE.md`](BUYER_EVIDENCE_ARCHITECTURE.md), [`BUYER_RETRIEVAL_ARCHITECTURE.md`](docs/archive/proposed/BUYER_RETRIEVAL_ARCHITECTURE.md), and [`executive_opportunity_brief.py`](executive_opportunity_brief.py) |

# Buyer Brief Presentation Architecture

## Purpose

The Buyer Brief is the professional presentation of one validated Buyer Intelligence analysis. It answers “Who is asking?” for executives and proposal teams before kickoff. It arranges established facts, attributed public statements, validated interpretations, alternatives, uncertainty, questions, evidence, and limitations without adding content or deciding what the team should do.

The brief is Volume 2 of the Bid Intelligence Briefing Pack. It follows the Executive Opportunity Brief, which establishes what is being requested. The two volumes share opportunity context while retaining separate authority: Volume 1 cannot supply buyer interpretation, and Volume 2 cannot redefine opportunity facts.

## Presentation boundary

The generator consumes `GovernedBuyerInputs`, a validated `BuyerIntelligenceAnalysis`, and the Canonical Buyer already present in those inputs. It calls Buyer Intelligence validation before presentation. It then places the same frozen analysis objects into fixed presentation sections. It does not copy conclusions into new analytical types, rewrite statements, change confidence, select among hypotheses, resolve conflicts, or suppress unknowns.

Canonical identity values are projected into a compact factual panel. Evidence metadata is projected into an evidence register. These are deterministic representation changes, not intelligence.

The generator has no retrieval, web, model, prompt, persistence, API, schema, migration, or pipeline behavior.

## Governed section order

The fixed order is:

1. Buyer at a Glance;
2. Mandate and Operating Context;
3. Relevant Organizational Context;
4. Published Priorities in Context;
5. Opportunity-to-Organization Context;
6. Current Procurement Context;
7. Questions for the Proposal Kickoff;
8. Known Unknowns and Assumptions;
9. Evidence Register; and
10. Limitations.

The first nine titles follow [`BUYER_BRIEF_DESIGN.md`](docs/archive/proposed/BUYER_BRIEF_DESIGN.md). The tenth follows the higher-level functional output contract in [`BUYER_INTELLIGENCE_SPECIFICATION.md`](docs/archive/proposed/BUYER_INTELLIGENCE_SPECIFICATION.md), which requires limitations as a distinct final section. Every section appears even when its validated collection is empty.

## Section projection

### Buyer at a Glance

The panel exposes up to six Canonical Buyer identity values and validated identity facts. It contains no interpretation. Construction fails if populated identity content would exceed the design limit instead of dropping an item silently.

### Mandate and Operating Context

This section contains mandate, responsibility, and governance facts. Any deterministic computed facts appear under an explicitly labelled subsection and retain their exact computation name and value.

### Relevant Organizational Context

This section contains organizational function, capability, accessibility, initiative, and relationship facts plus only `RELEVANT_ORGANIZATIONAL_FUNCTION` interpretations. Facts and interpretations remain separate fields and receive different presentation labels.

### Published Priorities in Context

This section contains published-priority facts and only `PUBLISHED_PRIORITY_CONTEXT` interpretations. Published statements and interpretations remain visibly distinct. Confidence appears only on the interpretations.

### Opportunity-to-Organization Context

This section contains every remaining validated interpretation and every competing hypothesis. Supporting and contradicting evidence, confidence, and visible assumptions remain attached. No hypothesis is selected.

### Current Procurement Context

This section contains verified current-procurement facts only. Interpretations cannot enter it.

### Questions for the Proposal Kickoff

This section reuses the exact validated management questions. It never answers or reformulates them.

### Known Unknowns and Assumptions

Unknowns, conflicts, and assumptions remain separate typed collections. The renderer shows why each unknown is unresolved, retains each conflict subject and opposing evidence, and shows assumption statements with their evidence gaps. Internal assumption IDs do not appear in the executive body.

### Evidence Register

Every ID in `analysis.evidence_used` receives one consecutive marker in deterministic ID order. Buyer Evidence entries reuse their source, document, citation, and extract objects and expose available owner, authority, title, dates, language, freshness, authenticity, URL, and exact locator. Current procurement references remain stable references to their authoritative package; the generator does not invent missing document metadata.

### Limitations

The exact validated limitation statements appear last. An empty collection remains visible and is described only as having no recorded limitations.

## Evidence preservation

The brief does not duplicate evidence content. `EvidenceRegisterEntry` retains references to the existing immutable source, document, citation, and extract values. Evidence markers are local presentation aliases; stable evidence IDs remain visible in the register and retain authority.

Every Canonical Buyer evidence ID displayed in the identity panel must already be declared in `analysis.evidence_used`. Missing marker closure fails before rendering. Facts and interpretations retain their original evidence tuples unchanged.

## Confidence and information classes

Confidence is rendered only beside `BuyerInterpretation` and `BuyerHypothesis`. Facts, computed facts, unknowns, assumptions, conflicts, and questions receive no confidence. The generator reads the validated confidence value and never calculates, upgrades, downgrades, or removes it.

Each section accepts its governed typed class. Facts cannot move into interpretation fields, interpretations cannot enter procurement facts, and assumptions and unknowns cannot become factual prose.

## Determinism and identity

`BuyerBrief` and every presentation type are frozen, slotted dataclasses. The brief ID is the SHA-256 identity of the brief contract version, complete validated analysis, Canonical Buyer, and evidence cutoff. Identical inputs therefore produce equal brief objects, identical IDs, identical serialization, and identical Markdown.

Section ordering is an immutable constant. Evidence markers follow the already deterministic evidence order. Serialization uses stable enum values, ISO dates, sorted JSON keys, and immutable collection order. The generator does not read the clock or environment.

## Validation and failure behavior

Construction fails closed when:

- Buyer Intelligence validation fails;
- Buyer, opportunity, evaluation-context, input-digest, version, evidence, assumption, conflict, unknown, or entity closure fails upstream;
- the Buyer Brief version or fixed section order differs;
- a required section argument is absent;
- evidence register markers or IDs are duplicated or nonconsecutive;
- displayed Canonical Buyer evidence is absent from `evidence_used`;
- Buyer at a Glance exceeds six entries; or
- a non-date evidence cutoff is supplied.

The renderer accepts only a valid `BuyerBrief`. It cannot repair invalid analysis, infer missing content, or retrieve absent metadata. Empty-state language describes the empty validated collection and does not claim that information does not exist in reality.

## Relationship to the Executive Opportunity Brief

The Executive Opportunity Brief and Buyer Brief are sequential companions:

| Volume 1 — Executive Opportunity Brief | Volume 2 — Buyer Brief |
|---|---|
| What is being requested? | Who is asking? |
| Canonical Opportunity and Opportunity Intelligence authority | Canonical Buyer, Buyer Evidence, and Buyer Intelligence authority |
| Scope, workstreams, requirements, milestones, and opportunity preparation | Identity, mandate, organizational context, published priorities, procurement role, and buyer-context questions |
| Cannot infer buyer intent | Cannot redefine opportunity facts |

The Buyer Brief retains opportunity identity only to bind the analysis. It does not repeat Volume 1’s opportunity narrative, requirements, scoring, commercial structure, or preparation plan.

## Evaluation artifact

Generated Markdown is an evaluation artifact outside the production contract. It is not committed with the generator. An artifact records its evidence cutoff and may expose explicit gaps when the repository lacks governed public organizational evidence. Evaluation cannot authorize the generator to fill those gaps from general knowledge.

## Doctrine compliance

The presentation preserves evidence before inference, canonical authority, analyst ownership, immutable inputs, explicit uncertainty, alternatives, limitations, deterministic behavior, and sovereign human judgment. It contains no recommendation, score, ranking, prediction, procurement strategy, proposal strategy, pricing advice, Bid / No Bid view, or executive conclusion.
