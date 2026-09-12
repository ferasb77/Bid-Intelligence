# Document Metadata

| Field | Value |
|---|---|
| Document | `BUYER_DOMAIN_ARCHITECTURE.md` |
| Title | Canonical Buyer Domain Architecture |
| Authority Level | Level 4 — Architecture Specification |
| Version | 1.0.0 |
| Status | Implemented |
| Purpose | Define the immutable canonical identity contract for an organization that issues opportunities. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md), [`GOVERNANCE.md`](GOVERNANCE.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md), [`docs/architecture/DOMAIN_MODEL.md`](docs/architecture/DOMAIN_MODEL.md), and [`BUYER_INTELLIGENCE_SPECIFICATION.md`](BUYER_INTELLIGENCE_SPECIFICATION.md) |
| Governed Documents | [`buyer_domain.py`](buyer_domain.py), [`tests/test_buyer_domain.py`](tests/test_buyer_domain.py) |
| Related Documents | [`BUYER_BRIEF_DESIGN.md`](BUYER_BRIEF_DESIGN.md), [`BID_INTELLIGENCE_BRIEFING_PACK.md`](BID_INTELLIGENCE_BRIEFING_PACK.md) |

# Canonical Buyer Domain Architecture

## Purpose

The canonical Buyer gives the platform one stable, evidence-linked identity for an organization that issues opportunities. It allows multiple procurements to refer to the same buyer without repeating or reinterpreting organizational identity.

This phase strengthens the Buyer Intelligence pillar by establishing its canonical input. It reduces the proposal team's burden of repeatedly establishing who issued an opportunity. It does not implement Buyer Intelligence.

## Authority and boundaries

Canonical Truth owns Buyer identity. The contract records attributable facts and stable references to the evidence that supports the record. It does not acquire authority over the source material and does not reconcile conflicting source observations.

Buyer Intelligence may later consume a canonical Buyer but cannot mutate it. The Buyer Brief may later present Buyer identity but cannot add facts or interpretations. Persistence, replay, retrieval, prompts, public-source ingestion, and pipeline integration remain outside this module.

The contract cannot represent mission interpretation, strategic priorities, procurement behaviour, historical awards, risk, relationship analysis, organizational assessment, proposal strategy, analyst findings, management questions, unknowns, assumptions, recommendations, or decisions. Those concepts require separately governed evidence or intelligence contracts.

## Contract

`CanonicalBuyer` contains:

- a stable Buyer ID, legal name, country, jurisdiction, government level, organization type, and evidence references;
- optional common name, sector, parent identity, public mandate, official website, and primary procurement authority;
- ordered identifiers, aliases, language codes, public contact references, and attributable organizational notes;
- the explicit contract version `canonical-buyer/1`.

Nested values are immutable typed records. Collections become sorted tuples during construction. Equivalent inputs therefore compare equally and serialize identically regardless of input collection order.

`evidence_ids` identify existing evidence; the contract does not copy provenance or create evidence. Organizational notes require their own evidence references because free-standing prose without attribution would weaken the fact boundary.

## Validation and failure behavior

Construction fails closed when:

- required identity or evidence is absent;
- stable IDs contain unsupported characters;
- a parent references the Buyer itself;
- country and jurisdiction disagree;
- an ISO 3166-2 style subdivision does not belong to the jurisdiction country;
- an enum or nested value has the wrong type;
- aliases duplicate one another or repeat the legal or common name;
- identifiers, contacts, notes, evidence references, or languages contain duplicates;
- language tags fall outside the supported simple BCP 47 form;
- an official website is not an absolute HTTP(S) URL or contains credentials, a query, or a fragment;
- the contract version is unsupported.

Website normalization lowercases the scheme and IDNA host, removes default ports and trailing slashes, and preserves meaningful paths. It neither fetches the URL nor infers an official site. Language normalization changes representation only; it does not infer language capability.

## Determinism and serialization

`to_dict()` returns JSON-compatible primitives. `to_json()` uses stable keys and compact deterministic encoding. No timestamp, environment value, network state, model output, or collection insertion order affects equality or serialization.

## Extension strategy

Compatible identity fields may be introduced only through an explicit contract review. A change in meaning or an incompatible shape requires a new `canonical-buyer/*` version and an adapter or migration decision. Future evidence collection, reconciliation, Buyer Intelligence, and Buyer Brief work must remain separate modules that reference this identity rather than expanding it into an intelligence object.

## Doctrine compliance

The module preserves evidence before inference, canonical authority, stable identity, immutable transitions, deterministic behavior, and fail-closed validation. It supplies no score, prediction, recommendation, procurement strategy, or executive decision. Human judgment remains outside the contract.
