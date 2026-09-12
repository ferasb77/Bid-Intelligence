# Document Metadata

| Field | Value |
|---|---|
| Document | `EXECUTIVE_OPPORTUNITY_BRIEF_ARCHITECTURE.md` |
| Title | Executive Opportunity Brief Architecture |
| Authority Level | Level 4 — Presentation Contract |
| Version | 2.0.0 |
| Status | Approved |
| Purpose | Define the deterministic customer-facing presentation of Executive Opportunity Understanding used to prepare senior consulting leaders for proposal kickoff. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md), [`AGENT.md`](AGENT.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), [`EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md`](EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md), [`OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md`](OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md), and [`GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md`](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md) |
| Governed Documents | `executive_opportunity_brief.py`, `tests/test_executive_opportunity_brief.py`, and evaluation artifacts derived from this contract |
| Related Documents | [`DECISION_WORKSPACE_ARCHITECTURE.md`](DECISION_WORKSPACE_ARCHITECTURE.md), [`BID_INTELLIGENCE_BRIEFING_PACK.md`](BID_INTELLIGENCE_BRIEFING_PACK.md) |

# Executive Opportunity Brief Architecture

## Summary of amendment

Version 2.0.0 aligns the Executive Opportunity Brief with the authoritative Executive Opportunity Understanding architecture. The brief now consumes one validated immutable `ExecutiveOpportunityUnderstanding` and presents its governed organization. It no longer consumes normalized facts, Stage D synthesis, or `DecisionAnalysis` directly.

The amendment removes semantic classification, interpretation, terminology translation, controlled semantic vocabularies, analytical identity creation, semantic identity derivation, reasoning, and intelligence ownership from the brief. Opportunity domains continue to own facts and provenance, Opportunity Intelligence owns analysis, Opportunity Intelligence Publication owns immutable analytical publication, Governed Reference Resolution verifies owner-declared meaning and relationship closure, and Executive Opportunity Understanding owns organization and coverage.

The brief retains only deterministic presentation ordering, formatting, navigation, coverage visibility, traceability, provenance visibility, and fail-closed rendering.

## Constitutional rationale

The repository requires authority to survive transformation and presentation layers to avoid creating or changing meaning. Executive Opportunity Understanding is the higher-authority organizational contract. It already supplies the deterministic executive index, complete detail register, coverage ledger, immutable reference bindings, and governed resolution context required by presentation consumers.

Allowing the brief to inspect upstream facts or analysis independently would create a second organizational path and could produce classifications, labels, identities, omissions, or ordering that diverge from the governed understanding. Version 2.0.0 removes that duplicate authority. The brief reduces reading and navigation effort through presentation while preserving evidence before inference and sovereign human judgment.

## Purpose

The Executive Opportunity Brief is a deterministic presentation adapter over Executive Opportunity Understanding. It prepares senior consulting leaders for proposal kickoff by rendering the governed executive organization in a concise, navigable form.

The brief does not decide whether to pursue an opportunity, advise a team how to win, or create a new account of what the opportunity means.

## Architectural position

```text
Opportunity Intelligence Owner Publication
                    ↓
Governed Reference Resolution
                    ↓
Executive Opportunity Understanding
                    ↓
Executive Opportunity Brief
                    ↓
Document or screen rendering
```

The brief consumes only Executive Opportunity Understanding. It uses the exact immutable reference and resolution-context bindings declared by that contract. It cannot consult Opportunity Intelligence, normalized facts, Stage D, canonical domains, evidence stores, or another resolver through a private lookup path.

## Authority boundary

The Executive Opportunity Brief has presentation authority only.

It owns no semantic meaning, intelligence, interpretation, classification, analytical identity, or analytical authority.

It may:

- render the Executive Opportunity Understanding section order;
- apply deterministic headings, typography, spacing, pagination, tables, lists, and navigation;
- resolve an understanding reference through its exact governed resolution context;
- display exact owner-declared semantic values and typed properties returned by Governed Reference Resolution;
- display owner identity, authority, confidence, uncertainty, evidence relationships, provenance navigation, and immutable reference bindings;
- expose the executive index, complete detail register, and coverage ledger; and
- create a presentation-format identity that identifies a rendering of an exact understanding under an exact renderer version.

It may not:

- analyze, classify, infer, interpret, summarize, reconcile, repair, or translate semantic content;
- create a fact, computation, observation, hypothesis, assumption, unknown, conflict, limitation, consideration, question, recommendation, or decision;
- create analytical, publication, canonical, evidence, provenance, or semantic identities;
- derive semantic identity from rendered wording, source fields, requirements, layout, or pagination;
- own or duplicate semantic values, evidence, provenance, intelligence, classifications, or interpretations;
- change authority, confidence, support state, uncertainty, precision, scope, language, or relationship identity;
- suppress a conflict, unknown, assumption, alternative, limitation, detail entry, or coverage record;
- reconstruct evidence or provenance from identifiers or prose;
- use controlled terminology to create a semantic label not already present in the resolved owner object or the understanding’s fixed organizational metadata; or
- access raw or mutable current state as a fallback.

Fixed headings and other presentational labels identify layout regions only. They do not classify source content or create semantic meaning.

## Input contract

Version 2.0.0 requires one validated immutable `ExecutiveOpportunityUnderstanding` whose contract version is supported by the adapter.

Before rendering, the adapter verifies:

- the understanding identity and contract version;
- the organization-profile version;
- the bound resolution-context identity and digest;
- the publication and snapshot bindings carried by the understanding;
- the exact governed object references in the detail register;
- the executive-index and coverage-ledger integrity already required by the understanding contract; and
- successful governed resolution for every semantic value or relationship the selected presentation format displays.

The adapter accepts no separate `DecisionAnalysis`, normalized-fact mapping, Stage D synthesis, conflict list, requirement list, evidence collection, or semantic override.

## Deterministic presentation

The brief preserves the fixed section order supplied by the Executive Opportunity Understanding organization profile. Within each section it preserves the understanding’s deterministic reference order. It does not reorder by perceived relevance, materiality, confidence, frequency, prose length, or available page space.

For identical Executive Opportunity Understanding content, identical governed resolution context, adapter version, and output format, the rendered result is byte-equivalent where the format supports canonical bytes and semantically equivalent where container metadata is necessarily operational.

A brief presentation identity, when required, binds only the exact understanding identity and digest, adapter version, and presentation-format version. It identifies a rendering artifact. It is not a semantic, analytical, publication, evidence, or canonical identity and cannot change the meaning or identity of the understanding or any resolved object.

## Sections and rendering

The adapter renders the Executive Opportunity Understanding executive index in its governed order:

1. Opportunity Identity
2. Requested Work
3. Evaluation and Success Structure
4. Response and Submission Structure
5. Timeline
6. Delivery Structure
7. Commercial and Contract Structure
8. Measured Characteristics
9. Analyst Findings
10. Assumptions and Alternatives
11. Conflicts, Unknowns, and Evidence Gaps
12. Management Deliberation
13. Limitations and Coverage

For each indexed reference, the adapter resolves and displays only the semantic fields authorized by the supported owner and consumer contracts. The complete detail register remains available through deterministic detail or appendix presentation. Empty sections use a fixed presentation-state label and never imply that evidence is absent unless the understanding or resolved owner object declares that absence.

The adapter does not translate terminology, generate representative engagements, derive success characteristics, create preparation ownership, rewrite management questions, or turn conflicts into new clarification objects. Such content appears only when it already exists as governed content referenced by the understanding.

## Coverage, traceability, and provenance

Every detail-register entry retains a presentation path. Every coverage-ledger disposition remains visible or navigable. Compact rendering may move detail to an appendix, collapse it interactively, or paginate it, but it cannot remove the entry from the complete brief artifact or claim completeness without a working path to it.

Displayed content retains its exact governed reference, owner domain, owner contract version, publication snapshot, object digest, authority class, and relationship identity. Evidence and provenance remain owned upstream and are reached only through governed relationship navigation. The brief may display provenance supplied by resolution; it cannot recreate, shorten into a substitute citation, or claim ownership of it.

## Failure behaviour

Rendering fails closed when:

- the input is not a supported Executive Opportunity Understanding;
- understanding validation fails;
- a contract, organization profile, owner, or resolver version is unsupported;
- the bound resolution context is missing, stale, incompatible, or has a digest mismatch;
- a required object or semantic field does not resolve exactly;
- evidence or provenance relationship closure required by the presentation fails;
- the executive index and coverage ledger disagree;
- deterministic ordering cannot be reproduced; or
- complete presentation coverage cannot be demonstrated.

Failure never permits direct access to Opportunity Intelligence, normalized facts, Stage D, current state, guessed labels, placeholder facts, semantic omission, or partial success presented as a complete brief.

## Prohibited output

The brief contains no newly authored recommendation, Bid / No Bid direction, win probability, ranking, score, SWOT analysis, pricing advice, proposal strategy, semantic interpretation, unsupported engagement example, or human decision. It never answers a management question.

## Compatibility analysis

This amendment is compatible with the governing architecture:

- **Executive Opportunity Understanding:** the brief consumes its immutable executive index, detail register, coverage ledger, identities, and resolution-context bindings without reorganizing them.
- **Opportunity Intelligence Publication:** published analytical identity, ownership, semantic fields, relationships, snapshot binding, and digests remain unchanged and are never reconstructed by the brief.
- **Governed Reference Resolution:** every displayed semantic value and relationship is obtained through exact bounded resolution; the brief performs no fallback lookup or consumer-side inference.
- **Canonical Truth and provenance:** facts, evidence, and provenance remain in their owning domains. Presentation neither duplicates nor mutates them.
- **Human judgment:** the brief presents governed understanding and unanswered questions without recommendation or decision authority.

The former conflict is resolved: no remaining responsibility in this architecture requires the Executive Opportunity Brief to consume upstream analytical or authoritative inputs directly, organize intelligence, create semantic classifications or interpretations, or derive semantic identity.

## Acceptance criteria

The architecture is satisfied only when:

1. the brief accepts only a validated supported Executive Opportunity Understanding;
2. every displayed semantic value is obtained through Governed Reference Resolution using the understanding’s exact context binding;
3. presentation order follows the understanding’s executive index and detail register exactly;
4. every coverage-ledger entry remains visible or navigable;
5. references, owner identity, authority, confidence, uncertainty, relationships, evidence, and provenance remain unchanged;
6. no semantic value, analytical identity, publication identity, canonical identity, evidence identity, classification, interpretation, or intelligence is created or owned by the brief;
7. identical governed inputs and presentation versions produce deterministic output;
8. missing, stale, incompatible, incomplete, or unresolved content fails closed;
9. compact layout never becomes semantic omission; and
10. rendering contains no recommendation, ranking, score, prediction, procurement strategy, or human decision.

## Amendment confirmation

Version 2.0.0 changes this architecture document only. No production code, tests, prompts, schemas, APIs, persistence, pipelines, evaluation artifacts, or other architecture documents were modified.
