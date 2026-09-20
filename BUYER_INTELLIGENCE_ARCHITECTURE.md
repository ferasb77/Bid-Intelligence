# Document Metadata

| Field | Value |
|---|---|
| Document | `BUYER_INTELLIGENCE_ARCHITECTURE.md` |
| Title | Buyer Intelligence v1 Architecture |
| Authority Level | Level 4 — Architecture Specification |
| Version | 1.0.0 |
| Status | Implemented |
| Purpose | Govern the immutable, evidence-closed Buyer Intelligence analysis produced from approved Buyer and opportunity inputs. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md), [`GOVERNANCE.md`](GOVERNANCE.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), [Architecture Doctrine](docs/architecture/ARCHITECTURE.md), [`BUYER_INTELLIGENCE_SPECIFICATION.md`](docs/archive/proposed/BUYER_INTELLIGENCE_SPECIFICATION.md), [`BUYER_DOMAIN_ARCHITECTURE.md`](BUYER_DOMAIN_ARCHITECTURE.md), [`BUYER_EVIDENCE_ARCHITECTURE.md`](BUYER_EVIDENCE_ARCHITECTURE.md), and [`BUYER_RETRIEVAL_ARCHITECTURE.md`](docs/archive/proposed/BUYER_RETRIEVAL_ARCHITECTURE.md) |
| Governed Documents | [`buyer_intelligence.py`](buyer_intelligence.py), [`tests/test_buyer_intelligence.py`](tests/test_buyer_intelligence.py) |
| Related Documents | [`BUYER_BRIEF_DESIGN.md`](docs/archive/proposed/BUYER_BRIEF_DESIGN.md), [`BID_INTELLIGENCE_BRIEFING_PACK.md`](docs/archive/proposed/BID_INTELLIGENCE_BRIEFING_PACK.md), and [`DECISION_DOCTRINE.md`](docs/architecture/DECISION_DOCTRINE.md) |

# Buyer Intelligence v1 Architecture

## Purpose

Buyer Intelligence v1 produces a validated, immutable account of organizational understanding for one Buyer and one opportunity. It helps consulting professionals establish who is asking, which published organizational context is relevant, what evidence supports that view, and where human discussion is still required.

The analysis prepares understanding. It makes no recommendation, procurement decision, prediction, ranking, pricing judgment, proposal strategy, or executive conclusion.

## Architectural position and authority

```text
Canonical Buyer ─────────┐
Buyer Evidence ──────────┤
Canonical Opportunity ──┤
Procurement Evidence ────┼─→ Buyer Intelligence ─→ Buyer Brief ─→ Human Judgment
Opportunity Intelligence ┘       (when referenced)
```

Buyer Intelligence consumes governed inputs and creates a new analysis. It cannot retrieve evidence, mutate Canonical Buyer, alter Buyer Evidence, redefine Canonical Opportunity, overrule Opportunity Intelligence, or render the Buyer Brief.

`GovernedBuyerInputs` carries immutable Buyer and Buyer Evidence values plus stable identity, version, digest, entity, evidence, evaluation-context, source-date, and optional Opportunity Intelligence references for the other authoritative inputs. Digests bind the analysis to the exact governed input state without copying mutable pipeline structures into the analysis.

The analysis references evidence and opportunity entities by stable ID. It does not copy provenance into analytical prose or make free-text citations authoritative.

## Information model

`BuyerIntelligenceAnalysis` requires every substantive collection explicitly, including empty collections. This prevents absent sections from being confused with reviewed sections containing no findings.

### Buyer facts

`BuyerFact` has one of three structural classes:

- `AUTHORITATIVE_BUYER_FACT` for identity, mandate, responsibility, structure, or official responsibility established by a competent source;
- `PUBLIC_ORGANIZATIONAL_INFORMATION` for attributed published statements about functions, plans, priorities, capabilities, governance, accessibility, initiatives, or relationships; and
- `VERIFIED_PROCUREMENT_CONTEXT` for current procurement context needed to understand the buyer's documented role.

Facts carry evidence status and exact evidence IDs. They carry no analytical confidence. Facts cannot occupy a collection for another fact class.

### Deterministic computed facts

`ComputedFact` records the named computation, exact produced value, and input fact IDs. It carries no confidence and cannot introduce an interpretation. Version 1 need not emit a computed fact; the explicit collection preserves the shared analysis shape when a governed deterministic computation exists.

### Reasoned interpretations

`BuyerInterpretation` identifies one permitted organizational-relevance relationship, its supporting and contradicting evidence, relevant Canonical Opportunity entities, visible assumptions, qualitative confidence, and evidence support status. It cannot exist without supporting evidence or opportunity linkage.

Permitted kinds cover opportunity-to-mandate relationships, relevant organizational functions, published-priority context, organizational context, governance context, and current procurement context. They do not encode buyer intent, evaluator preference, hidden motivation, relationship inference, or proposal advice.

### Competing hypotheses

`BuyerHypothesis` preserves a plausible alternative separately from interpretations. It identifies supporting and contradicting evidence, opportunity entities, qualitative confidence, and support status. The aggregate never selects a hypothesis or suppresses an alternative.

### Assumptions

`BuyerAssumption` states the provisional premise, the evidence gap that makes it necessary, and every dependent interpretation. The relationship is reciprocal: each interpretation exposes its assumption IDs. Assumption-dependent interpretations cannot be classified as fully supported.

### Unknowns

`BuyerUnknown` distinguishes missing evidence, unavailable information, ambiguous ownership, conflicting statements, stale information, unknown opportunity relationships, and unsupported questions about buyer intent. Every unknown states why it remains unresolved. It may reference evidence but never uses absence as proof of a negative conclusion.

### Conflicts

`BuyerConflict` preserves at least two distinct evidence positions. Conflict objects do not select a winner or alter upstream evidence. Any reasoning marked conflicting requires an explicit conflict in the analysis.

### Management questions

`BuyerManagementQuestion` remains unanswered, ends as a question, and references evidence, an unknown, or a conflict that caused it. Deterministic validation rejects recognizable recommendation, pricing, prediction, Bid / No Bid, evaluator-preference, and proposal-strategy language.

### Limitations

`BuyerLimitation` records source coverage, time, language, availability, or analytical constraints. Limitations are explicit analysis records rather than presentation footnotes.

## Evidence traceability

The evidence closure is validated in two stages:

1. `evidence_used` must resolve to the supplied Buyer Evidence set or the authoritative procurement evidence index.
2. Every fact, interpretation, hypothesis, unknown, conflict, and evidence-linked management question must reference an ID declared in `evidence_used`.

Analytical conclusions require exact citable evidence: a Buyer Evidence citation, Buyer Evidence extract, or authoritative procurement evidence ID. Source and document identities alone may appear in the evidence register but cannot support a conclusion without a locator. Canonical Buyer evidence IDs must resolve within the supplied Buyer Evidence set.

Version 1 rejects attributable secondary public sources even though the general evidence domain can represent them. The active specification permits official organizational, legislative, regulatory, government, procurement, accountability, and registry sources only.

Fact authority is proposition-specific. Organizational facts require verified organizational documents. Except for buyer identity, procurement evidence cannot establish authoritative Buyer facts. Current procurement context requires authoritative procurement evidence or a verified procurement notice. A valid reference therefore cannot be reused outside the subject its source class is competent to establish.

Stale evidence remains available. A fact relying on stale evidence must be visibly `PARTIALLY_SUPPORTED`; it cannot be presented as fully supported.

## Confidence

Confidence is qualitative and applies only to `BuyerInterpretation` and `BuyerHypothesis`. Its values are `LOW`, `MODERATE`, `HIGH`, and `UNKNOWN`.

Confidence describes the strength, specificity, freshness, agreement, and scope of evidence supporting reasoning. It is not a probability, numerical score, rank, prediction, or substitute for evidence support status. Facts and computations have no confidence field. A confidence label cannot hide contradicting evidence, make an unsupported statement acceptable, or make an assumption-dependent interpretation established.

`SupportStatus` remains a separate evidence condition: `SUPPORTED`, `PARTIALLY_SUPPORTED`, `CONFLICTING`, `INSUFFICIENT_EVIDENCE`, or `MISSING_EVIDENCE`.
Interpretations and hypotheses accept only the first three states. Insufficient or missing evidence cannot validate a conclusion and must be represented in the Unknowns collection.

## Validation and failure behavior

Construction and aggregate validation fail closed for:

- missing, malformed, duplicate, or cross-section identities;
- unsupported Buyer, Buyer Evidence, Canonical Opportunity, Opportunity Intelligence, or analyst versions;
- mismatched Buyer, opportunity, evaluation-context, or input-digest identity;
- unresolved, undeclared, or non-citable evidence references;
- Canonical Buyer evidence outside the supplied Buyer Evidence set;
- secondary sources outside Version 1 policy;
- wrong fact classes or unsupported fact and interpretation kinds;
- evidence confidence states on facts that imply conflict or missing evidence;
- stale facts presented as fully supported;
- unknown fact or Canonical Opportunity entity references;
- unsupported or missing evidence for reasoning;
- hidden, missing, one-way, or fully-supported assumptions;
- hidden conflicts or unknowns required by reasoning status;
- conflicts without two distinct evidence positions;
- unknowns without an unresolved reason;
- management questions without an evidence or uncertainty cause;
- management questions stated as answers; and
- recognizable recommendation, prediction, ranking, pricing, strategy, or evaluator-preference language.

Validation never repairs a conclusion, mutates an input, resolves a conflict, supplies missing evidence, or removes a valid unrelated record.

## Determinism and immutability

Every contract is a frozen, slotted dataclass. Nested collections become sorted tuples and duplicate stable identities fail. Serialization uses sorted JSON keys, stable enum values, and ISO dates. Input digests use the complete Canonical Buyer and Buyer Evidence serialization plus the declared opportunity, procurement-package, evaluation-context, source-date, and Opportunity Intelligence references.

No current time, environment state, model state, network result, collection insertion order, or presentation choice affects the analysis. Deep copies preserve semantic equality and cannot introduce mutable nested state.

## Separation from adjacent layers

- **Retrieval** discovers and acquires external material. This module performs no retrieval, crawling, search, URL access, or authenticity verification.
- **Buyer Evidence** owns attributable source representations. This module references its stable IDs and does not modify its content or status.
- **Canonical Buyer** owns organizational identity. This module consumes it and cannot add or correct canonical fields.
- **Opportunity Intelligence** owns opportunity analysis. This module may retain its validated identity and version but cannot rewrite its outputs.
- **Buyer Brief** owns professional presentation. This module has no layout, rendering, executive-summary, or document-generation behavior.
- **Human Judgment** owns interpretation of business context and every decision. This module has no recommendation or decision contract.

## Extension strategy

Later versions may add procurement-history analysis, new governed source classes, or additional interpretation kinds only through updates to the functional specification and an explicit compatibility review. Retrieval, presentation, persistence, pipeline integration, AI execution, and public APIs remain separate phases. New capability must not be smuggled into free text or an unrestricted enum.

## Doctrine compliance

The implementation preserves evidence before inference, typed epistemic boundaries, canonical authority, stable identity, complete traceability, explicit assumptions and unknowns, competing hypotheses, immutable transitions, deterministic behavior, scoped failure, and sovereign human judgment. It advances none of the repository anti-goals and modifies no governing doctrine.
