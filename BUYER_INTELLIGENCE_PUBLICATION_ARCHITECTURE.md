# Buyer Intelligence Publication Architecture

## Document metadata

| Field | Value |
|---|---|
| Document | `BUYER_INTELLIGENCE_PUBLICATION_ARCHITECTURE.md` |
| Title | Buyer Intelligence Publication Architecture |
| Authority level | Level 3 — Canonical Domain Publication Contract |
| Version | 1.0.0 |
| Status | Proposed — discovered by commissioning, not yet implemented |
| Purpose | Define the publication contracts that make Buyer Evidence, Canonical Buyer, and Buyer Intelligence addressable, immutable, and governed-reference resolvable — mirroring Evidence Publication, Canonical Opportunity Publication, and Opportunity Intelligence Publication exactly wherever the architecture requires identical behavior. |
| Trigger | Commissioning found `buyer_intelligence.py` has a real, commissioned `analyze_buyer` producer but no publication contract, and no such contract can bind its evidence citations without an equally missing Buyer Evidence Publication and Canonical Buyer Publication existing first. |
| Higher authority | [MANIFESTO.md](MANIFESTO.md), [AGENT.md](AGENT.md), [ANTI_GOALS.md](ANTI_GOALS.md), [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md), [docs/architecture/DECISION_DOCTRINE.md](docs/architecture/DECISION_DOCTRINE.md), [GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md) |
| Related architecture | [EVIDENCE_ARCHITECTURE.md](EVIDENCE_ARCHITECTURE.md), [CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md](CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md), [OPPORTUNITY_STRUCTURE_PUBLICATION_ARCHITECTURE.md](OPPORTUNITY_STRUCTURE_PUBLICATION_ARCHITECTURE.md), [BUYER_DOMAIN_ARCHITECTURE.md](BUYER_DOMAIN_ARCHITECTURE.md), [BUYER_EVIDENCE_ARCHITECTURE.md](BUYER_EVIDENCE_ARCHITECTURE.md), [BUYER_INTELLIGENCE_ARCHITECTURE.md](BUYER_INTELLIGENCE_ARCHITECTURE.md) |

---

## 0. Why this is three contracts, not one

Commissioning asked for "Buyer Intelligence Publication." Investigating it the same way Opportunity Intelligence Publication was investigated (which turned out to require Canonical Opportunity Publication and Opportunity Structure Publication to exist first) found the identical shape of dependency on the Buyer side:

- `BuyerFact.evidence_ids` (`buyer_intelligence.py`) cites bare `EvidenceSource`/`EvidenceDocument`/`EvidenceCitation`/`EvidenceExtract` ids from `buyer_evidence.py`. No governed reference to any of them exists, because **Buyer Evidence has never been published** — `buyer_evidence.py` is validators-only, exactly like `evidence.py` was before `evidence_publication.py` existed.
- `CanonicalBuyer.evidence_ids` (`buyer_domain.py`) is a reconciled identity conclusion *derived from* Buyer Evidence — structurally the Buyer-side analog of Canonical Opportunity's resolved field states, not raw evidence itself. It needs its own publication, separate from Buyer Evidence Publication, for the same reason Canonical Opportunity Publication is separate from Evidence Publication: a different authority (`AuthorityClass.CANONICAL_FACT`, not `EVIDENCE`) and a different reconciliation boundary.
- `BuyerIntelligenceAnalysis` (the analyst just commissioned) needs both of the above to exist before *its own* evidence citations can resolve to anything.

This document therefore defines all three, in dependency order, using no mechanism this repository has not already ratified.

---

## Part A — Buyer Evidence Publication

**Owner**: Buyer Evidence (`buyer_evidence.py`), unchanged — publication only exposes what this module already governs, exactly as `evidence_publication.py` does for `evidence.py`.

**Contract**: `OWNER_DOMAIN = "buyer-evidence"`, `OWNER_CONTRACT = "buyer-evidence"`, `PUBLICATION_CONTRACT_VERSION = "1.0.0"`.

**Object classes**: `SOURCE`, `DOCUMENT`, `CITATION`, `EXTRACT` — one per `BuyerEvidenceSet` collection. No new object class; publication names the representation, it does not invent a category (same rule `CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md` §6 states for its own classes).

**Deterministic identity**: each object's `object_id` is the field's own already-stable id (`source_id`/`document_id`/`citation_id`/`extract_id`) — no new identifier scheme, mirroring every publication built this session.

**Relationship model**: unlike `evidence.py` (which carries its own first-class `EvidenceRelationship` graph inside `EvidenceSnapshot`'s manifest), `BuyerEvidenceSet` expresses cross-references only as plain foreign-key fields, already validated by its own `__post_init__` (`document.source_id`, `citation.document_id`, `extract.document_id`, `extract.citation_ids`). Publication derives `PROVENANCE` relationships from these fields directly — the same technique `canonical_opportunity_publication.py` and `opportunity_structure_publication.py` already use to turn foreign keys into governed relationships, applied here because Buyer Evidence's simpler, flat shape does not warrant importing `evidence.py`'s richer (and here unnecessary) relationship-object machinery.

**Governed references**: one per published object, produced by the existing `reference_to(snapshot, object_class, object_id)` — no new resolution mechanism.

**Constitutional boundaries**: publishes exactly what `buyer_evidence.py` already states and nothing more — no interpretation, no authenticity re-assessment, no acquisition. `EvidenceAuthority`/`AuthenticityStatus`/`FreshnessStatus` are preserved as semantic fields, never converted into governed judgments.

**Replay compatibility**: deterministic given an identical `BuyerEvidenceSet` — no randomness, no clock dependency beyond the dates the evidence itself already carries.

**Versioning**: `1.0.0`, independent of Evidence's, Canonical Opportunity's, and Opportunity Structure's own version numbers, per `GOVERNANCE.md`'s existing per-contract versioning discipline.

---

## Part B — Canonical Buyer Publication

**Owner**: Buyer Domain (`buyer_domain.py`), unchanged.

**Contract**: `OWNER_DOMAIN = "canonical-buyer"`, `OWNER_CONTRACT = "canonical-buyer"`, `PUBLICATION_CONTRACT_VERSION = "1.0.0"`.

**Object classes**: a single `CANONICAL_BUYER_IDENTITY` class — one object per `CanonicalBuyer`. `CanonicalBuyer` is already a single, already-reconciled identity record (unlike Canonical Opportunity's six-family observation ledger), so there is exactly one object to publish, not several field-state objects — the correct minimum, not an arbitrary simplification.

**Deterministic identity**: `object_id` = `buyer.buyer_id` itself — already a stable, already-governed identifier; no hash needs deriving.

**Relationship model**: `EVIDENCE_SUPPORT` relationships from the identity object to every one of `buyer.evidence_ids`, resolved against Buyer Evidence Publication's own references (Part A) — the same binding pattern `canonical_observation_binding.py` and `opportunity_structure_binding.py` already established: a real, fail-closed binder that refuses to invent a reference for an evidence id Buyer Evidence Publication cannot actually resolve.

**Constitutional boundaries**: publishes exactly `CanonicalBuyer`'s own fields (legal name, jurisdiction, government level, organization type, identifiers, aliases, contacts, notes) — no interpretation, no mandate analysis (that remains Buyer Intelligence's, Part C).

**Replay compatibility / Versioning**: same discipline as Part A, `1.0.0`, independent version.

---

## Part C — Buyer Intelligence Publication (the boundary originally requested)

**Owner**: Buyer Intelligence (`buyer_intelligence.py`), unchanged — the analyst's authority does not move.

**Contract**: `OWNER_DOMAIN = "buyer-intelligence"`, `OWNER_CONTRACT = "buyer-intelligence-analyst"`, `PUBLICATION_CONTRACT_VERSION = "1.0.0"` — named exactly like `opportunity_intelligence_publication.py`'s own contract, for the same reason: this publishes an *analyst's* conclusions, not a ledger.

**Object classes**, one per statement family already defined in `buyer_intelligence.py` (no new class invented): `BUYER_FACT`, `COMPUTED_FACT`, `INTERPRETATION`, `HYPOTHESIS`, `ASSUMPTION`, `UNKNOWN`, `CONFLICT`, `MANAGEMENT_QUESTION`, `LIMITATION`, plus one `ANALYSIS` root object mirroring `opportunity_intelligence_publication.py`'s own "analysis" root pattern exactly (a single object whose relationships enumerate everything the analysis contains, via `RelationshipKind.DEPENDENCY` "contains").

**Deterministic identity**: every statement already carries a stable id (`fact_id`, `interpretation_id`, `hypothesis_id`, …) — reused verbatim, no new scheme. The root `ANALYSIS` object's id is `analysis.analysis_id`, itself already deterministic (`analyze_buyer`'s `_id("bi-analysis-", …)`).

**Governed references and relationship model**: every `BuyerFact.evidence_ids` entry must resolve against **either** Buyer Evidence Publication (Part A) **or** Canonical Buyer Publication (Part B) — never invented. This mirrors `canonical_observation_binding.py`'s exact discipline: a binder that independently verifies each citation resolves to a real governed reference before a `BuyerIntelligencePublication` can be produced, refusing (not guessing) when it cannot. Statement-to-statement relationships (an `INTERPRETATION`'s `assumption_ids`, a `MANAGEMENT_QUESTION`'s `unknown_ids`) are internal `SELF` references, exactly as `opportunity_intelligence_publication.py` already resolves its own internal statement graph.

**Constitutional boundaries**: publishes `BuyerIntelligenceAnalysis` exactly as `analyze_buyer` produced it — no re-interpretation, no new confidence, no new fact. Identical to every publication module built this session: publication is read-only over its source.

**Replay compatibility**: deterministic given the identical `BuyerIntelligenceAnalysis` plus the identical Buyer Evidence/Canonical Buyer publications it binds against.

**Versioning**: `1.0.0`.

---

## Dependency order this implies

Buyer Evidence Acquisition (done) → **Buyer Evidence Publication (Part A, new)** → Canonical Buyer construction (done) → **Canonical Buyer Publication (Part B, new)** → Buyer Intelligence Analysis (done) → **Buyer Intelligence Publication (Part C, new, the boundary originally requested)** → Buyer Brief (already production-ready, currently blocked upstream exactly as `executive_opportunity_brief.py` was before Opportunity Intelligence Publication existed).

No architecture here modifies Procurement Intelligence, extends any schema to support it, or touches `MANIFESTO.md` — all three parts are additive, Buyer-domain-only contracts, exactly as scoped.
