# Buyer Intelligence Domain Architecture

## Document metadata

| Field | Value |
|---|---|
| Document | `BUYER_INTELLIGENCE_DOMAIN_ARCHITECTURE.md` |
| Title | Buyer Intelligence Domain Architecture |
| Authority level | Level 3 — Architectural Domain Definition |
| Version | 1.0.0 |
| Status | Investigation complete — no code changed. Reconciles and extends existing Level 4 documents; introduces no implementation. |
| Purpose | Determine, before implementing a Buyer Intelligence producer, whether the repository has correctly identified Buyer Intelligence's constitutional scope — and design the one part of that scope (contribution to shared procurement memory) no existing document yet covers. |
| Trigger | Commissioning reached Buyer Intelligence and found a validator and a full publication architecture but no producer — only hand-authored evaluation fixtures construct a `BuyerIntelligenceAnalysis` today. |
| Higher authority | [MANIFESTO.md](MANIFESTO.md), [ANTI_GOALS.md](ANTI_GOALS.md), [AGENT.md](AGENT.md), [GOVERNANCE.md](GOVERNANCE.md), [docs/architecture/DECISION_DOCTRINE.md](docs/architecture/DECISION_DOCTRINE.md), [docs/architecture/DOMAIN_MODEL.md](docs/architecture/DOMAIN_MODEL.md) |
| Reconciles | [BUYER_INTELLIGENCE_SPECIFICATION.md](BUYER_INTELLIGENCE_SPECIFICATION.md), [BUYER_INTELLIGENCE_ARCHITECTURE.md](BUYER_INTELLIGENCE_ARCHITECTURE.md), [BUYER_DOMAIN_ARCHITECTURE.md](BUYER_DOMAIN_ARCHITECTURE.md), [BUYER_EVIDENCE_ARCHITECTURE.md](BUYER_EVIDENCE_ARCHITECTURE.md), [BUYER_EVIDENCE_ACQUISITION_ARCHITECTURE.md](BUYER_EVIDENCE_ACQUISITION_ARCHITECTURE.md), [BUYER_RETRIEVAL_ARCHITECTURE.md](BUYER_RETRIEVAL_ARCHITECTURE.md), [BUYER_BRIEF_ARCHITECTURE.md](BUYER_BRIEF_ARCHITECTURE.md) |

---

## Headline finding

The repository has, in six pre-existing Level 4 documents plus `buyer_domain.py`, `buyer_evidence.py`, `buyer_intelligence.py`, and `buyer_brief.py`, **already correctly identified almost all of Buyer Intelligence's constitutional scope** — its purpose, its knowledge families, its evidence-tier discipline, and its presentation boundary are well-formed and consistent with the rest of the constitution. Nothing here needed correcting.

**One part of the scope was never architected at the same rigor: what happens to a buyer observation after the one opportunity it was made for is over.** `BUYER_INTELLIGENCE_SPECIFICATION.md` names this gap itself, twice, as an unimplemented future version ("Version 4 — Institutional Learning," "Version 5 — Cross-Opportunity Organizational Intelligence," lines 320-328) but never resolves it. That resolution — Parts 3 and 4 below — is this document's actual new contribution; everything else confirms and cites what already exists rather than re-deciding it.

---

## Part 1 — What is Buyer Intelligence?

### The test

A knowledge domain belongs to Buyer Intelligence only if answering it requires evidence that exists **outside the procurement package** — from the issuing organization's own, independent, standing public record, not from anything Evidence, Canonical Opportunity, Opportunity Structure, Opportunity Intelligence, or Executive Opportunity Understanding already ingest or could ingest by reading the solicitation more carefully.

Applying it to the five existing domains:

| Domain | What it already answers | Source material |
|---|---|---|
| Evidence | What does the source material say, and exactly where | The procurement package (any document in it) |
| Canonical Opportunity | Who is named as buyer, when, how much, what kind of procurement mechanic | The procurement package's own typed observations |
| Opportunity Structure | What is required, how it is judged, what must be delivered, on what terms, how to submit | The procurement package's requirements/criteria/clauses/deliverables/rules |
| Opportunity Intelligence | What the documented structure implies (volume, ambiguity, conflict, effort drivers) — reasoning that never leaves the four corners of the package | The above, reasoned over |
| Executive Opportunity Understanding | How to review what has already been established about the opportunity | Opportunity Intelligence Publication |

None of the five can, even in principle, answer "why does a Bank of Canada RFP for talent and organizational development services plausibly relate to what the Bank of Canada is legislatively responsible for and has publicly said it is trying to do this year?" — because the Bank of Canada Act, the Bank's own strategic plan, and its own annual report are not procurement documents and were never given to any of the five domains above. `BUYER_INTELLIGENCE_SPECIFICATION.md` states this exact distinction directly (lines 21, verbatim): *"Opportunity Intelligence answers, 'What is this opportunity?' Buyer Intelligence answers, 'Who is asking?'"*

### Constitutional purpose (as a knowledge domain, not a feature list)

**Buyer Intelligence is the domain responsible for establishing verified, source-grounded knowledge about the issuing organization as a standing entity — independent of any single procurement — and for connecting that independently-established context to what the current opportunity documents.** Its evidence source is categorically different (the organization's own public record, not the solicitation), and its question is categorically different (who is asking and why does this plausibly fit their mandate, not what is being asked).

This is confirmed, not invented, by `docs/architecture/DOMAIN_MODEL.md`'s existing Buyer entry: *"Architectural ownership: Canonical Truth owns verified identity; Buyer Intelligence owns buyer analysis"* — a deliberate mirror of the same split already ratified for Opportunity (*"Canonical Truth owns its authoritative identity; Opportunity Intelligence owns its analysis"*). Buyer Intelligence is structurally the Opportunity Intelligence of the buyer side, over a disjoint evidence corpus.

---

## Part 2 — Buyer knowledge model

`buyer_intelligence.py`'s `FactKind` enum (11 members, already committed to code) is the load-bearing, already-decided knowledge taxonomy — not something this document should redesign. Testing the user's example families against it and against existing doctrine:

| Family | Belongs? | Evidence |
|---|---|---|
| Organizational mandate | **Yes** — `MANDATE`, `RESPONSIBILITY` | `buyer_intelligence.py:38-39`; legislated, charter-based |
| Strategic priorities | **Yes** — `PUBLISHED_PRIORITY`, `PUBLIC_INITIATIVE` | `buyer_intelligence.py:40,44`; strategic/departmental plans |
| Governance | **Yes** — `GOVERNANCE` | `buyer_intelligence.py:42`; procurement policy, organizational governance structure |
| Accessibility | **Yes** — `ACCESSIBILITY_COMMITMENT` | `buyer_intelligence.py:43`; already exercised by real Bank of Canada ACA content this session |
| Current procurement behavior (this engagement) | **Yes** — `CURRENT_PROCUREMENT_ROLE` | `buyer_intelligence.py:45` |
| Historical procurement patterns | **Yes, bounded** — `VERIFIED_PROCUREMENT_CONTEXT` fact class | `BUYER_INTELLIGENCE_ARCHITECTURE.md` L47-49; "time-bounded and must not be generalized beyond the evidence" (`BUYER_INTELLIGENCE_SPECIFICATION.md:158`) |
| Procurement maturity | **No, as a named family** — collapses into `GOVERNANCE` facts (e.g. "publishes a formal procurement policy") | Naming it "maturity" produces an aggregate judgment, not a fact — exactly the "Win probability engine" pattern `ANTI_GOALS.md:35-37` forbids ("buyer signals... opaque weights... must not present prediction as knowledge") |
| Technology posture | **No, as a named family** — subsumed by `ORGANIZATIONAL_CAPABILITY`/`ORGANIZATIONAL_FUNCTION` when a source states it | No dedicated evidence tier exists for this; inventing one duplicates an existing kind |
| Sustainability | **No, as a named family** — subsumed by `PUBLIC_INITIATIVE` when a source states it | Same reasoning as technology posture — a published sustainability commitment is a `PUBLIC_INITIATIVE`, not a new class |
| Supplier ecosystem | **No** | Explicitly forbidden: *"No private CRM data, relationship notes, personal data enrichment, competitor data"*; *"rank or assess competitors"* (`BUYER_INTELLIGENCE_SPECIFICATION.md:87,64`). A buyer's own publicly-stated relationship (e.g. an annual report naming an existing partner) is `ORGANIZATIONAL_RELATIONSHIP`; reasoning about *my firm's* competitive position from it is not Buyer Intelligence's domain at all |
| Decision style | **No** | Explicitly forbidden: *"speculate about personal relationships, influence, or buyer preference"*; *"infer evaluator preference"* is a named `Unknown`, never a fact (`BUYER_INTELLIGENCE_SPECIFICATION.md:63,210`) |

**Conclusion: the existing 11-member `FactKind` taxonomy is complete and correctly scoped.** Every legitimate example the user raised either already has a home or correctly collapses into one; every rejected example is rejected by evidence already in the constitution, not by this document's judgment call.

---

## Part 3 — Static vs. dynamic knowledge, and a distinction the existing docs miss

### Static (established once, revisited occasionally, never per-opportunity)

- `IDENTITY` — owned one level below Buyer Intelligence, by `CanonicalBuyer` (`buyer_domain.py`), not by Buyer Intelligence itself
- `MANDATE`, `RESPONSIBILITY` — change only via legislative/charter amendment
- `GOVERNANCE` — a standing policy/structure characteristic
- `ORGANIZATIONAL_FUNCTION` — reorganizations are infrequent
- `ACCESSIBILITY_COMMITMENT` — a standing published commitment

### Dynamic — but two different kinds, and only the existing docs cover the first

**3a. Current-snapshot dynamic** (established fully within *one* Buyer Intelligence analysis, already correctly modeled): `PUBLISHED_PRIORITY`, `ORGANIZATIONAL_CAPABILITY`, `PUBLIC_INITIATIVE`, `ORGANIZATIONAL_RELATIONSHIP`, `CURRENT_PROCUREMENT_ROLE`. These can change between engagements, but each Buyer Intelligence analysis captures them as of the evidence it has now — no accumulation across engagements is required to state them.

**3b. Cross-opportunity accumulated dynamic** (the user's own examples — *procurement behavior, clarification behavior, amendment behavior, evaluation tendencies, procurement evolution*): these are **patterns**, not facts, and a pattern is not observable from one opportunity. "This buyer amended RFP 2026-026 once" is a fact one analysis can state (`VERIFIED_PROCUREMENT_CONTEXT`). "This buyer tends to amend RFPs" is a claim about *many* opportunities that no single analysis has evidence for.

**The distinction the existing documents do not draw**: `docs/architecture/DOMAIN_MODEL.md` already assigns pattern-recognition across opportunities to a *different* pillar — *"Organizational Learning ... Architectural ownership: Organizational Intelligence"* (not Buyer Intelligence). This means Buyer Intelligence's job for 3b-type knowledge is **capture, not synthesis**: record each individual, evidence-linked, per-opportunity observation faithfully; never itself claim the pattern. A Buyer Intelligence analysis that concluded "this buyer typically amends solicitations" from evidence about one solicitation would violate `DECISION_DOCTRINE.md`'s prohibited transition — *"an inference being stored or displayed as a fact"* (`docs/architecture/DECISION_DOCTRINE.md:99-113`) — twice over: premature generalization, and reasoning outside its own domain's authority.

This is the load-bearing conclusion for Part 4.

---

## Part 4 — Procurement memory

### Ownership

Per `docs/architecture/DOMAIN_MODEL.md`'s own, already-ratified assignment, Buyer Intelligence is a **contributor** to procurement memory, never its owner or synthesizer. The owner of cross-opportunity pattern synthesis is Organizational Intelligence (MANIFESTO.md Pillar 4: *"Organizational Intelligence — learn from historical bids. Turn RFPs, proposals, outcomes, debriefs, and lessons into durable organizational memory"*). `BUYER_INTELLIGENCE_SPECIFICATION.md` already reserves exactly this handoff as its unimplemented "Version 5" (lines 324-328, quoted in full): *"Support evidence-linked comparison across buyers and opportunities to reveal recurring organizational questions and learning themes. Preserve buyer boundaries, temporal context, confidentiality, and the prohibition on prediction and scoring."*

### What is safe to contribute

An observation is safe for shared procurement memory only if **both** hold:

1. It is a `AUTHORITATIVE_BUYER_FACT` or `PUBLIC_ORGANIZATIONAL_INFORMATION` — never an Interpretation, Hypothesis, Assumption, Unknown, or Management Question (those are reasoning scoped to one tenant's one analysis of one opportunity, not a fact about the buyer).
2. Its source is the **buyer's own public record**, or the **public procurement notice itself** — never anything derived from a tenant's proposal, pricing, competitive positioning, or internal analysis.

Concretely safe: *"the Bank of Canada Act establishes [mandate]"* (public legislation); *"Bank of Canada RFP 2026-026 was amended once, on 2026-08-28"* (a fact about the public notice, not about any bidder). Both are already-public facts about the buyer or about the buyer's own published procurement action — restating them centrally leaks nothing any tenant privately holds.

### What is prohibited

- Supplier proposals, pricing, and any tenant-derived content — **never**, per this document's own mandate.
- Any Interpretation or Hypothesis a tenant's analysis produced — its relevance reasoning is scoped to that tenant's specific opportunity, not a fact about the buyer.
- Any signal, direct or inferable, that a specific tenant is pursuing or has pursued a specific opportunity — this is a cross-tenant confidentiality leak by a different route than pricing, and just as forbidden by the same principle.
- Anything that would require inferring, rather than citing, a public source — an unverifiable "fact" contributed to a shared store is worse than one held privately, because more tenants would act on it.

### Aggregation rules

1. **Buyer-scoped, not tenant-scoped, not opportunity-scoped.** The memory is keyed by `CanonicalBuyer.buyer_id`, exactly mirroring `buyer_domain.py`'s existing identity contract — *"It allows multiple procurements to refer to the same buyer without repeating or reinterpreting organizational identity"* (`BUYER_DOMAIN_ARCHITECTURE.md:19`). The same discipline now extends across tenants, not just across one tenant's procurements.
2. **Deduplicate at the fact, not the analysis.** Many tenants will independently observe the identical public fact (the same mandate, the same amendment). The memory reconciles these into one canonical, evidence-linked record — the same "one governed authority for the present evidence state" pattern Canonical Opportunity already established (`docs/architecture/ARCHITECTURE.md:59`) — rather than storing N duplicate, unreconciled copies.
3. **Accretion, never mutation.** A later-observed fact never overwrites an earlier tenant's contribution; it is added, with its own provenance, exactly as `canonical_opportunity.py`'s supersession discipline already requires for every other governed ledger in this repository.
4. **No scores, ranks, or predictive metrics — ever**, over the accumulated set. The memory remains a growing collection of governed observations. Turning it into a score would be the "Win probability engine" anti-goal (`ANTI_GOALS.md:35-37`) at buyer-memory scale instead of single-opportunity scale — the prohibition is identical regardless of how many opportunities feed it.
5. **Provenance travels with the fact.** A consuming tenant sees the original public citation, not a laundered, unsourced claim — bounded disclosure, not bounded truth.

Pattern synthesis over this ledger ("does this buyer tend to amend, extend, or add clarification rounds?") remains Organizational Intelligence's job, operating on top of the ledger Buyer Intelligence contributes to — a separate, not-yet-built capability, out of scope here.

---

## Part 5 — Data acquisition

The existing `BUYER_RETRIEVAL_ARCHITECTURE.md` three-tier hierarchy and `BUYER_INTELLIGENCE_SPECIFICATION.md`'s source rules are already correctly scoped; this section confirms them against the requested taxonomy rather than replacing them.

| Category | Examples | Acceptable? |
|---|---|---|
| Authoritative | The buyer's own official website, enabling legislation/charter, official annual/strategic/departmental plans, official org charts, official budgets and public accounts, official policy publications; the procurement package itself for identity/context | **Yes** — Tier 1, `BUYER_RETRIEVAL_ARCHITECTURE.md:121-158` |
| Public | Official legislative/regulatory repositories, official government procurement portals and award-disclosure systems not controlled by the buyer but authoritative for the fact asserted | **Yes** — Tier 2 |
| Derived | Attributable secondary public commentary with a clear institutional owner, explicitly distinct from authoritative fact | **Not in Version 1** — Tier 3 is named but excluded until a later, explicitly governed version (`BUYER_EVIDENCE_ACQUISITION_ARCHITECTURE.md:275`, `BUYER_RETRIEVAL_ARCHITECTURE.md:154`) |
| Computed | None substantive — Buyer Intelligence has no deterministic normalization family analogous to Canonical Opportunity's date/money resolution; its `ComputedFact` class is limited to structural counts, never new buyer content | N/A |
| Inferred | Reasoned Interpretation, Hypothesis | **Never a source of fact** — consumes evidence, never produces it |
| Never acceptable at any tier | Search-result snippets, aggregators, marketing databases, anonymous material, personal social media, inferred-contact services, unattributed reposts | **No** — already explicitly excluded, `BUYER_INTELLIGENCE_SPECIFICATION.md:122` |

**Recommendation: Authoritative + Public only for the producer this document is clearing the way for.** This is not a new decision — it is the confirmation that the already-ratified, already-written acquisition doctrine is correctly bounded and needs no revision before implementation begins.

---

## Part 6 — Interaction model

- **Opportunity Intelligence → Buyer Intelligence, one-way, read-only.** Buyer Intelligence consumes Opportunity Intelligence's analysis only for relevance reasoning ("this requirement appears related to the buyer's stated mandate"); it never modifies opportunity facts, never treats an unresolved opportunity conflict as resolved, never duplicates opportunity normalization (`BUYER_INTELLIGENCE_SPECIFICATION.md:85`). Opportunity Intelligence never depends on Buyer Intelligence — consistent with MANIFESTO.md's own pillar ordering (Pillar 1 before Pillar 2).
- **Executive Understanding / Executive Brief — siblings, not a pipeline stage.** Executive Opportunity Understanding organizes `OpportunityIntelligencePublication` content specifically; Buyer Intelligence has its own, parallel presentation path (Buyer Brief, "Volume 2" per `BUYER_BRIEF_ARCHITECTURE.md:127-134`, contrasted directly with Volume 1, the Executive Opportunity Brief). Neither Understanding nor Brief nests the other; both are assembled together only at a higher-level Executive Briefing Pack, not yet built.
- **Clarification Questions — different domain, different addressee.** Clarification Questions are directed at the procurement authority about the *solicitation's* meaning, and belong to Opportunity Intelligence/Opportunity Structure. An organization's mandate cannot be "clarified" through an RFP Q&A channel. Buyer Intelligence's unresolved questions become either a `BuyerManagementQuestion` (needs a human) or remain a permanent `BuyerUnknown` — never a Clarification Question.
- **Amendments — narrow, factual relevance only.** An amendment is Evidence/Canonical Opportunity's domain (`BID_LIFECYCLE_ARCHITECTURE.md`: *"An attributable procurement amendment enters Acquisition and Evidence first... impact is evaluated by the owning canonical and intelligence capabilities"*). Buyer Intelligence may hold "this buyer issued N amendments to this solicitation" as a `VERIFIED_PROCUREMENT_CONTEXT` fact; it never re-derives, evaluates, or acts on an amendment's substantive content.
- **Future Procurement Memory — contributor, not owner**, exactly as designed in Part 4.

---

## Ownership boundaries (summary)

**Owns:** verified organizational identity linkage (via `CanonicalBuyer`), organizational mandate/responsibility/governance/function/priority/initiative/capability/relationship/accessibility facts, current and verified-historical procurement-role facts, bounded relevance interpretation between those facts and the current opportunity, and — going forward — governed, evidence-linked, buyer-scoped contribution to shared procurement memory.

**Never owns:** opportunity extraction or canonical opportunity facts (Canonical Opportunity), procurement structure (Opportunity Structure), opportunity-internal interpretation (Opportunity Intelligence), Clarification Questions, proposal content, compliance or commercial decisions, competitor assessment, win-probability or Bid/No-Bid recommendation, or cross-opportunity pattern synthesis (Organizational Intelligence) — all already correctly excluded by existing documents, reaffirmed here.

## Lifecycle

Buyer identification (via the authoritative opportunity record) → Buyer Evidence acquisition (Authoritative/Public tiers only) → fact establishment (`BuyerFact`, classed and kinded) → bounded interpretation and unknowns → validated `BuyerIntelligenceAnalysis` → Buyer Brief presentation → (future) eligible facts offered to the buyer-scoped procurement memory ledger, where they may later inform Organizational Intelligence's separate, cross-opportunity synthesis.

## Publication implications

A future Buyer Intelligence Publication should mirror the same pattern Canonical Opportunity, Opportunity Structure, and Opportunity Intelligence Publications already establish: immutable governed objects per fact/interpretation/hypothesis/unknown, evidence-derived identity, and resolution through the existing `governed_reference_resolution.py` protocol — no new resolution mechanism required. This document does not design that publication; it confirms the domain it would publish is correctly scoped first.

## Future extensibility

The only forward slot this document opens (beyond what `BUYER_INTELLIGENCE_SPECIFICATION.md` already reserved) is the buyer-scoped procurement memory ledger of Part 4 — a governed, deduplicated, accretion-only fact store, contributed to by every tenant's Buyer Intelligence analyses and consumed only by a future, separately-authorized Organizational Intelligence synthesis capability. No other extension is implied or recommended here.

---

## What was not done

No code, prompt, schema, or test was written or modified. This document does not authorize implementing a Buyer Intelligence producer, a Buyer Evidence acquisition mechanism, or a procurement memory store — it establishes that the domain is correctly scoped (with the one gap above now resolved on paper) so that a future implementation pass has an unambiguous specification to build against.
