# Document Metadata

| Field | Value |
|---|---|
| Document | `BUYER_EVIDENCE_ARCHITECTURE.md` |
| Title | Canonical Buyer Evidence Architecture |
| Authority Level | Level 4 — Architecture Specification |
| Version | 1.0.0 |
| Status | Implemented |
| Purpose | Define immutable contracts for attributable public organizational evidence consumed by future Buyer Intelligence. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md), [`GOVERNANCE.md`](GOVERNANCE.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md), [`docs/architecture/DOMAIN_MODEL.md`](docs/architecture/DOMAIN_MODEL.md), [`BUYER_INTELLIGENCE_SPECIFICATION.md`](docs/archive/proposed/BUYER_INTELLIGENCE_SPECIFICATION.md), and [`BUYER_DOMAIN_ARCHITECTURE.md`](BUYER_DOMAIN_ARCHITECTURE.md) |
| Governed Documents | [`buyer_evidence.py`](buyer_evidence.py), [`tests/test_buyer_evidence.py`](tests/test_buyer_evidence.py) |
| Related Documents | [`BUYER_BRIEF_DESIGN.md`](docs/archive/proposed/BUYER_BRIEF_DESIGN.md), [`BID_INTELLIGENCE_BRIEFING_PACK.md`](docs/archive/proposed/BID_INTELLIGENCE_BRIEFING_PACK.md) |

# Canonical Buyer Evidence Architecture

## Purpose

The Buyer Evidence domain gives future Buyer Intelligence an immutable, attributable record of public source material. It represents what was published, where it was found, when it was published and retrieved, how it can be located, which buyer or public scope it concerns, and how source authenticity was established.

This phase strengthens the Buyer Intelligence pillar and reduces repeated source verification before proposal kickoff. It does not retrieve evidence or form an understanding of the buyer.

## Authority boundary

Evidence precedes Canonical Truth and intelligence. `BuyerEvidenceSet` describes source material and reference closure; it does not turn publication into a canonical buyer fact. `CanonicalBuyer` may retain stable evidence IDs after a separately governed canonical transition. Future Buyer Intelligence may cite the evidence but cannot mutate it, upgrade its authority, or convert source text into fact without the appropriate validation boundary.

The contracts contain no interpretation, reasoning, summary, question, recommendation, strategy, unknown, assumption, prediction, score, rank, or executive conclusion. Authenticity status concerns confidence that an artifact is what its attribution claims; it is not analytical confidence and says nothing about the truth of a conclusion.

## Contract structure

- `EvidenceSource` identifies the attributable publisher, authority class, base URL, and stated jurisdiction.
- `EvidenceDocument` records a supported public-document category, source reference, title, canonical URL, language, publication and retrieval dates, explicit freshness, applicable scopes, publisher identity, version, and optional content digest.
- `EvidenceCitation` identifies an exact location in one document. Typed locators prevent vague or fuzzy references.
- `EvidenceExtract` preserves exact source text and links it to one or more citations in the same document.
- `EvidenceFreshness` records an explicit status and assessment dates without consulting system time.
- `EvidenceScope` names the organization, unit, jurisdiction, program, or opportunity to which a document explicitly applies.
- `BuyerEvidenceSet` supplies the versioned aggregate and validates identity and reference closure.

All contracts use frozen, slotted dataclasses. Collections are normalized into sorted tuples. IDs and typed references, rather than display order or prose, determine durable relationships.

## Evidence authority and categories

Authority classes distinguish the buyer itself, legislative authorities, government authorities, official procurement authorities, other official publishers, and attributable public sources. Categories enumerate the source families permitted for this version, including organizational websites, reports, plans, legislation, policies, organizational charts, procurement notices, and government publications.

Authority and category are independent. A strategic plan describes a document type; `OFFICIAL_BUYER` identifies who published it. Neither classification grants analytical authority.

## Validation and failure behavior

Construction fails closed for:

- missing or malformed stable IDs;
- unsupported enum values, source categories, authority classes, scope types, locator types, freshness states, or contract versions;
- non-HTTP(S), credential-bearing, fragment-bearing, or malformed URLs;
- malformed language tags, content digests, page ranges, and table-cell locators;
- missing scopes or extract citations;
- non-date values and publication dates after retrieval dates;
- inconsistent freshness dates;
- duplicate source, document, citation, extract, scope, or reference identities;
- documents referencing absent sources;
- citations or extracts referencing absent or different documents;
- extract language differing from document language; and
- organization scopes that contradict the evidence set's Buyer identity.

Failure remains local to construction. The module does not repair, infer, fetch, discard, or silently reinterpret invalid evidence.

## Determinism, copying, and serialization

The contracts use only explicit inputs. They do not read the clock, environment, network, filesystem, or model state. Equivalent collections are sorted by stable identity, so equality and JSON serialization remain identical for identical evidence regardless of input ordering. Dates serialize in ISO 8601 form and enums by stable values. Deep copying cannot create mutable nested state.

## Extension strategy

New source categories or authority classes require contract review because consumers fail closed on unknown enum values. Retrieval, crawling, search, authenticity verification, evidence reconciliation, Buyer Intelligence, Buyer Brief presentation, persistence, and public APIs require separate governed phases. An incompatible meaning or representation requires a new `buyer-evidence/*` version and an explicit compatibility decision.

## Doctrine compliance

The domain preserves source identity, provenance, exact location, authority, uncertainty about authenticity, stable references, immutability, determinism, and fail-closed behavior. It creates no intelligence and leaves interpretation and executive judgment to their governed layers.
