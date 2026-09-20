# Buyer Intelligence Fact Ownership Architecture

## Document metadata

| Field | Value |
|---|---|
| Document | `BUYER_INTELLIGENCE_FACT_OWNERSHIP_ARCHITECTURE.md` |
| Title | Buyer Intelligence Fact Ownership Architecture |
| Authority level | Level 3 — Architectural Ownership Investigation |
| Version | 1.0.0 |
| Status | Investigation complete — no code, schema, or publication changed. |
| Purpose | Determine, from repository evidence alone, whether an Intelligence layer may republish a Canonical layer's own already-established facts as its own new facts, using the real collision `analyze_buyer`'s identity facts caused in `BuyerAtAGlance` as the triggering case. |
| Trigger | Real commissioning: `build_buyer_brief` combined `_identity_items(buyer)` (from `CanonicalBuyer`) with `analysis.buyer_facts` filtered to `FactKind.IDENTITY` (from `analyze_buyer`) and exceeded `BuyerAtAGlance`'s six-item cap — 5 + 4 = 9. |
| Higher authority | [MANIFESTO.md](MANIFESTO.md), [docs/architecture/DECISION_DOCTRINE.md](docs/architecture/DECISION_DOCTRINE.md), [docs/architecture/DOMAIN_MODEL.md](docs/architecture/DOMAIN_MODEL.md), [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md), [BUYER_INTELLIGENCE_SPECIFICATION.md](docs/archive/proposed/BUYER_INTELLIGENCE_SPECIFICATION.md) |
| Related architecture | [BUYER_DOMAIN_ARCHITECTURE.md](BUYER_DOMAIN_ARCHITECTURE.md), [BUYER_INTELLIGENCE_ARCHITECTURE.md](BUYER_INTELLIGENCE_ARCHITECTURE.md), [CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md](CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md), [OPPORTUNITY_STRUCTURE_PUBLICATION_ARCHITECTURE.md](OPPORTUNITY_STRUCTURE_PUBLICATION_ARCHITECTURE.md) |

---

## 1. Constitutional purpose of Canonical Buyer

`docs/architecture/DOMAIN_MODEL.md`'s Buyer entry states it directly: *"Architectural ownership: Canonical Truth owns verified identity; Buyer Intelligence owns buyer analysis."* `BUYER_DOMAIN_ARCHITECTURE.md` states the same boundary from the inside: *"The canonical Buyer gives the platform one stable, evidence-linked identity for an organization that issues opportunities"* — and explicitly excludes everything else: *"The contract cannot represent mission interpretation, strategic priorities, procurement behaviour, historical awards, risk, relationship analysis, organizational assessment... recommendations, or decisions."*

Canonical Buyer's purpose is narrow and exclusive: **one governed, evidence-linked identity record per organization** (legal name, jurisdiction, government level, organization type) — nothing about what that identity *means*.

## 2. Constitutional purpose of Buyer Intelligence

`MANIFESTO.md` Pillar 2: *"Buyer Intelligence — understand the buyer. Organize observable buyer evidence and distinguish documented patterns from interpretation."* `BUYER_INTELLIGENCE_SPECIFICATION.md`: *"Opportunity Intelligence answers, 'What is this opportunity?' Buyer Intelligence answers, 'Who is asking?'"* — but note this is asked and answered **given** an identity Canonical Buyer already established, not by re-establishing that identity.

Buyer Intelligence's purpose is to organize and interpret evidence *about* an already-identified buyer — mandate, priorities, capability, governance, procurement role — never to re-derive the identity itself.

## 3. Comparison with existing precedent

### Canonical Opportunity vs. Opportunity Intelligence

Read directly from `opportunity_intelligence.py`: every reference to Canonical Opportunity content is an `EvidenceSupport(SupportedEntityType.OBSERVATION, observation_id, ...)` — a **citation** of an existing observation, used only to support a genuinely new computed value (`total_requirements`, `evaluation_hierarchy_depth`, milestone interval arithmetic). At no point does `opportunity_intelligence.py` construct a new statement that merely restates `resolved.title`, `resolved.client`, or `resolved.submission_deadline` — the resolved executive fields Canonical Opportunity Publication already owns. Opportunity Intelligence does not even touch the `resolved` dict; it consumes only the raw `observations` list, and only as citations, never as content to reissue as its own.

### Evidence vs. Canonical Opportunity

This boundary looks superficially similar but is different in kind, and the difference matters for this investigation. Canonical Opportunity does not "restate" Evidence's raw text — it performs genuine **normalization**: a raw excerpt becomes a typed, structured observation (a date string becomes a validated ISO date; free text becomes a controlled `semantic_kind`). Evidence itself asserts no typed claim to be duplicated; it presents source material. Normalizing raw material into a first typed claim is legitimate, original work by the layer that does it — not a restatement of an already-established fact.

### Opportunity Structure vs. Opportunity Intelligence

The same citation-only pattern repeats. `opportunity_intelligence.py`'s `_entity_type`/`_record_id` machinery builds `EvidenceSupport` references to `REQUIREMENT`/`DELIVERABLE`/`COMMERCIAL_CLAUSE` records to support aggregate counts (`total_requirements`, `mandatory_requirements`) — it never re-asserts a specific requirement's own text or classification as a new Opportunity Intelligence fact.

### What this establishes

Three independent existing boundaries in this repository draw the identical line: **an Intelligence layer cites what a Canonical layer already established; it does not reissue the same claim as its own new object.** The one case that looks like an exception — Evidence into Canonical Opportunity — is not an exception at all, because Evidence makes no prior typed claim to duplicate.

Measured against this line, `analyze_buyer`'s two categories of `BuyerFact` fall on opposite sides of it:
- The four `FactKind.IDENTITY` facts (legal name, organization type, government level, jurisdiction) **restate** fields `CanonicalBuyer` already, exclusively owns — the same pattern Opportunity Intelligence never exhibits toward Canonical Opportunity's resolved fields.
- The evidence-extract-sourced facts (verbatim quotes from `VERIFIED` Buyer Evidence documents) are **normalization of raw material Buyer Evidence itself asserts no typed claim over** — structurally identical to Evidence-into-Canonical-Opportunity, and not implicated by this finding.

The collision in `BuyerAtAGlance` was caused entirely by the first category.

## 4–5. Which approach — and which doctrine supports it

**Option B — reference canonical facts, publish only analysis-derived facts — is the correct architecture**, supported by every governing document with no exception found:

- `docs/architecture/DOMAIN_MODEL.md`: *"Canonical Truth owns verified identity; Buyer Intelligence owns buyer analysis"* — Option A has Buyer Intelligence re-asserting identity, exactly the ownership DOMAIN_MODEL.md already assigns elsewhere.
- `docs/architecture/DECISION_DOCTRINE.md`'s evidence ladder assumes each fact has exactly one authoritative rung; the same content re-appearing as an independently-governed object at a second rung is precisely the ambiguity the ladder exists to prevent.
- `docs/architecture/ARCHITECTURE.md`'s own stated purpose for a canonical layer — *"downstream work has one governed authority for the present evidence state"* — is violated the moment a second, independently-published authority exists for the same fact.
- `BUYER_INTELLIGENCE_SPECIFICATION.md` never lists "restate the buyer's identity" among Buyer Intelligence's responsibilities; its Product Outcome and Responsibilities lists are entirely about mandate, functions, priorities, procurement role — never identity itself, which is presupposed as already established.
- Opportunity Intelligence precedent (§3): zero instances of restatement across the entire existing, already-commissioned analyst.

No document, and no existing precedent, supports Option A.

## 6. Replay determinism, duplicate ownership, duplicate publication, identity drift

- **Duplicate ownership: confirmed.** `CanonicalBuyer.organization_type` and a `BuyerFact` stating the same organization type are two independently governed assertions of identical content, under two different publications (`canonical-buyer` and `buyer-intelligence-analyst`). Exactly one governed authority per fact is the rule every other boundary in this repository already enforces.
- **Duplicate publication: confirmed.** The real commissioning run produced this literally: Canonical Buyer Publication's one identity object and Buyer Intelligence Publication's four `BUYER_FACT` objects each separately assert the same four field values, as four additional, separately-digested, separately-referenceable governed objects that did not need to exist.
- **Identity drift: a real, latent risk.** If `CanonicalBuyer` is ever re-acquired and its `organization_type` corrected, Canonical Buyer Publication reflects the correction immediately. Any already-published `BuyerIntelligencePublication` built against the prior snapshot keeps its own, now-stale, independently-governed restatement — with no supersession mechanism linking the two, because none was designed for a fact that was never supposed to have two homes.
- **Replay instability:** a single analysis, replayed against an unchanged `CanonicalBuyer`, remains deterministic — no instability there. The instability is downstream: every time `CanonicalBuyer` is legitimately re-acquired or corrected, every consumer that cited the *restated* fact (rather than the canonical one) needs its own new supersession path that would not need to exist if identity had only ever been referenced.

## 7. Downstream consumers

Yes, each becomes simpler if canonical facts remain canonical:

- **Buyer Brief**: `BuyerAtAGlance` could source identity from `CanonicalBuyer` alone, unambiguously, with no deduplication logic and no risk of the six-item collision recurring as evidence accumulates. This is the section that just failed.
- **Procurement Intelligence** (design deferred, per the prior architecture review): its cross-domain synthesis would reason over Buyer Intelligence facts that are all substantively new — no need to first filter out identity noise before relating buyer facts to opportunity structure.
- **Organizational Intelligence / future Organizational Memory** (per `BUYER_INTELLIGENCE_DOMAIN_ARCHITECTURE.md` §Part 4): the memory contribution rule already restricts eligible facts to `AUTHORITATIVE_BUYER_FACT`/`PUBLIC_ORGANIZATIONAL_INFORMATION`. If identity facts remain inside that pool, a memory-contribution process must additionally guard against re-contributing content `CanonicalBuyer` already provides once, canonically, per buyer — a distinction Option B removes by construction rather than by added filtering logic.

## 8. Recommendation

**Option B.** `analyze_buyer` should not construct `FactKind.IDENTITY` facts that restate `CanonicalBuyer`'s own fields. Wherever Buyer Intelligence needs to establish provenance back to the buyer's identity (for example, as support for a computed fact), it should hold a governed reference to Canonical Buyer Publication's identity object directly — the same citation-only relationship Opportunity Intelligence already holds toward Canonical Opportunity and Opportunity Structure. Every other fact category `analyze_buyer` already produces — verbatim, `VERIFIED`-evidence-sourced `BuyerFact`s — is unaffected by this finding and should continue exactly as built, since that path is normalization of raw material, not restatement of an already-canonical claim, and is the direct structural analog of Evidence becoming a Canonical Opportunity observation.

This is a recommendation only. No code, schema, or publication contract has been changed in producing it.
