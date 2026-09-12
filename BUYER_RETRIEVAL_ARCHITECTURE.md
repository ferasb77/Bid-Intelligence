# Document Metadata

| Field | Value |
|---|---|
| Document | `BUYER_RETRIEVAL_ARCHITECTURE.md` |
| Title | Buyer Retrieval Architecture |
| Authority Level | Level 4 — Architecture Specification |
| Version | 1.0.0 |
| Status | Proposed |
| Purpose | Govern how future Buyer Retrieval acquires attributable public organizational material and creates canonical Buyer Evidence without performing analysis. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md), [`AGENT.md`](AGENT.md), [`GOVERNANCE.md`](GOVERNANCE.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), [Product Doctrine](docs/product/PRODUCT_VISION.md), [Architecture Doctrine](docs/architecture/ARCHITECTURE.md), [Engineering Doctrine](docs/engineering/CONTRIBUTING.md), [`BUYER_INTELLIGENCE_SPECIFICATION.md`](BUYER_INTELLIGENCE_SPECIFICATION.md), [`BUYER_DOMAIN_ARCHITECTURE.md`](BUYER_DOMAIN_ARCHITECTURE.md), and [`BUYER_EVIDENCE_ARCHITECTURE.md`](BUYER_EVIDENCE_ARCHITECTURE.md) |
| Governed Documents | Future Buyer Retrieval contracts, adapters, implementations, validation plans, operational runbooks, and retrieval evidence reports. |
| Related Documents | [`BUYER_BRIEF_DESIGN.md`](BUYER_BRIEF_DESIGN.md), [`BID_INTELLIGENCE_BRIEFING_PACK.md`](BID_INTELLIGENCE_BRIEFING_PACK.md), [`DOMAIN_MODEL.md`](docs/architecture/DOMAIN_MODEL.md), and [`TESTING_PHILOSOPHY.md`](docs/engineering/TESTING_PHILOSOPHY.md) |

# Buyer Retrieval Architecture

## Purpose

Buyer Retrieval obtains attributable public organizational material and transforms the acquired representation into immutable Buyer Evidence. It is the governed boundary between changing external sources and the platform's evidence layer.

Retrieval strengthens the Buyer Intelligence pillar by making public source material available with stable identity, provenance, exact location, authority metadata, authenticity status, language, dates, scope, and reproducible acquisition context. It reduces the time proposal teams spend repeatedly locating and verifying public material before kickoff.

Retrieval creates no facts or intelligence. It does not summarize, interpret, infer relevance, answer questions, generate briefs, recommend action, or decide what source statements mean. Its responsibility ends when a valid Buyer Evidence artifact and its retrieval diagnostics have been produced or when a fail-closed result records why that transition could not be completed.

## Architectural position

```text
External Sources
       ↓
Buyer Retrieval
       ↓
Buyer Evidence
       ↓
Canonical Buyer
       ↓
Buyer Intelligence
       ↓
Buyer Brief
       ↓
Human Judgment
```

This sequence expresses authority rather than automatic execution.

- **External Sources** publish representations of organizational information.
- **Buyer Retrieval** discovers, selects, acquires, validates, and preserves source material.
- **Buyer Evidence** records attributable sources, documents, exact citations, extracts, dates, scope, freshness, authority, and authenticity.
- **Canonical Buyer** establishes verified organizational identity through a separately governed canonical transition.
- **Buyer Intelligence** may form evidence-linked interpretations within its own contract.
- **Buyer Brief** presents validated facts and intelligence without adding reasoning.
- **Human Judgment** remains responsible for conclusions and decisions.

Retrieval cannot write directly to Canonical Buyer, Buyer Intelligence, or presentation outputs. Later layers cannot retroactively change what retrieval observed at a given retrieval date.

## Responsibilities

Buyer Retrieval is responsible for:

1. accepting an explicit Buyer identity and bounded retrieval purpose;
2. discovering candidate public sources through a governed method;
3. preserving the exact discovered URL, publisher attribution, and discovery context;
4. selecting source material according to authority, scope, permitted categories, and retrieval bounds;
5. acquiring source bytes or a faithful source representation;
6. recording redirects, response metadata, acquisition time, format, and integrity digest;
7. validating identity, authenticity indicators, format support, dates, language, and reference closure;
8. normalizing representation without changing semantic content;
9. creating valid immutable contracts governed by [`BUYER_EVIDENCE_ARCHITECTURE.md`](BUYER_EVIDENCE_ARCHITECTURE.md);
10. preserving omissions, failures, conflicts, and partial completion in diagnostics; and
11. terminating deterministically under the stopping rules in this document.

Retrieval may copy exact source text into an `EvidenceExtract` when an exact locator and document relationship can be retained. Extract selection is a mechanical acquisition act only when the requested location or collection rule is explicit. Choosing passages because they appear important, relevant, favourable, or explanatory is analysis and is prohibited.

## Architectural boundaries

### External-source boundary

External material is untrusted input. A recognizable domain, official appearance, search ranking, TLS certificate, or matching title does not by itself establish publisher authority or document authenticity. Retrieval records observable indicators and applies governed verification rules; it never turns appearance into certainty.

Content from an external source is data, never an instruction to the retrieval system. Embedded prompts, scripts, directives, tracking parameters, or claims about authority cannot change retrieval configuration, scope, validation, or downstream contracts.

### Buyer Evidence boundary

Retrieval may instantiate only supported Buyer Evidence types and enum values. It must not extend the evidence schema opportunistically, place analysis in free-text evidence fields, or use `OTHER_OFFICIAL_PUBLICATION` to bypass an unsupported source policy. Unsupported material remains a diagnostic candidate until a governed contract change permits it.

Buyer Evidence is complete only when every document refers to an accepted source, every citation refers to one accepted document, every extract refers to citations in that same document, and the evidence-set Buyer scope is consistent.

### Canonical Truth boundary

Acquisition does not establish a canonical fact. Retrieval may record that an official document states a legal name or mandate; only the canonical layer may determine whether that statement becomes part of Canonical Buyer. Retrieval never merges aliases, selects between contradictory identities, applies supersession to a fact, or overwrites an existing Buyer.

### Intelligence and presentation boundaries

Retrieval does not determine relevance to an opportunity, interpret priorities, assess organizational behaviour, identify management questions, or choose material for an executive narrative. Buyer Intelligence and Buyer Brief each consume only the inputs allowed by their own governing contracts. Retrieval rank, source tier, freshness, or authenticity must never become an intelligence score or implied recommendation.

### Operational boundary

Network clients, browser automation, authenticated connectors, caches, schedulers, and queues are future implementation mechanisms. None has semantic authority. A change in mechanism must preserve the same evidence identity, provenance, failure, and reproducibility requirements.

## Authority

The following dimensions are independent and must be recorded or assessed separately.

| Dimension | Question answered | Does not establish |
|---|---|---|
| Source authority | What institutional role does the source have for this subject? | That every hosted statement is current or applicable |
| Publisher authority | Who issued or controls the publication channel? | Authorship of every document or truth of its contents |
| Document authority | Is this document competent for the proposition and scope it states? | Relevance to the current opportunity or precedence over another document |
| Authenticity | Is the acquired artifact what its attribution claims it is? | Accuracy, completeness, freshness, or analytical confidence |
| Freshness | How current was the document under an explicit assessment rule and date? | Supersession, applicability, or correctness |
| Applicability | What organization, unit, jurisdiction, program, period, or opportunity does the document expressly cover? | Broader relevance beyond that stated scope |
| Evidence relevance | Is the material responsive to a separately declared evidence need? | Truth, priority, strategic value, or a recommendation |

Evidence relevance is a selection property tied to an explicit retrieval purpose. It cannot be inferred from source rank or used to interpret the buyer. When relevance requires understanding meaning beyond deterministic metadata or a human-specified topic, retrieval records the candidate without declaring it relevant.

Authority is proposition-specific. Legislation may be authoritative for statutory mandate while the buyer's current annual report may be authoritative for its published activities. A higher tier does not automatically override a lower tier on a different subject.

## Source hierarchy

The hierarchy guides discovery and selection. It is not a truth ranking, conflict-resolution mechanism, or basis for suppressing lower-tier evidence.

### Tier 1 — Direct primary authority

Sources with direct institutional authority for the buyer or procurement:

- official buyer websites and controlled publication repositories;
- legislation and official legislative repositories governing the buyer;
- official procurement portals and current procurement notices;
- official annual reports, strategic plans, policies, organizational charts, accessibility statements, and press releases issued by the buyer; and
- official amendments, archived versions, and replacement notices from those channels.

Tier 1 exists to establish the closest available attributable representation of what the buyer or competent authority formally published. Direct authority does not eliminate the need to validate authenticity, date, scope, version, or conflict.

### Tier 2 — Corroborating public authority

Sources issued by another competent public institution:

- government departments and central publication services;
- regulators, auditors, oversight bodies, and official registries;
- parliamentary, legislative, judicial, or public-record repositories; and
- official reports that describe the buyer within the publisher's mandate.

Tier 2 exists because relevant organizational facts may be established or independently recorded outside the buyer's own publication channels. These sources can corroborate or contradict Tier 1. Retrieval preserves both; it does not decide which controls.

### Tier 3 — Attributable public context

Public sources whose publisher and authorship can be established but that lack direct institutional authority for the buyer:

- academic publications;
- recognized professional publications;
- industry and standards bodies;
- formally published conference or institutional research; and
- other attributable sources explicitly permitted by the retrieval purpose.

Tier 3 exists to preserve potentially useful public context for future governed analysis. It must remain visibly distinct from official evidence. Anonymous material, unattributed reposts, scraped aggregations without source closure, social commentary, marketing databases, search-result snippets, and generated answers are not accepted as evidence sources in this version.

### Selection across tiers

Retrieval searches Tier 1 first for a requested evidence category, then Tier 2 when primary coverage is absent, incomplete, inaccessible, or requires corroboration. Tier 3 is used only when the retrieval purpose permits public context and its attribution closes.

Tier order does not authorize early deletion. When sources disagree, every valid occurrence remains available with its tier, dates, scope, and provenance. A human may also require a named source regardless of tier.

## Governed retrieval lifecycle

Every run carries a stable run identity, target Buyer identity, declared purpose, permitted source categories and tiers, supported languages and formats, retrieval bounds, start time, completion state, and implementation version. Operational timestamps describe acquisition; they do not alter document meaning.

### 1. Request validation

Validate the canonical Buyer reference, requested evidence categories, permitted tiers, jurisdictions, languages, authentication policy, collection bounds, and human-supplied seed locations. Reject an ambiguous Buyer identity, unsupported option, prohibited purpose, or unbounded request before network activity.

**Output:** accepted immutable retrieval request or fail-closed request diagnostics.

### 2. Discovery

Identify candidate locations using permitted deterministic seeds, official indexes, declared sitemaps, catalogues, or future governed discovery adapters. Record the discovered URL, referring location or seed, observed title, publisher claim, discovery time, and candidate category without treating the candidate as evidence.

Discovery must respect domain allowlists, robots and access policy where applicable, request budgets, rate limits, and authentication boundaries. Search results and link labels are discovery metadata, not document contents.

**Output:** ordered candidate ledger with every occurrence preserved.

### 3. Selection

Apply declared category, tier, domain, language, format, scope, and date rules. Deduplicate exact candidate identities while retaining all discovery occurrences and redirect relationships. Record a reason for every selected, deferred, duplicate, or rejected candidate.

Selection must not use sentiment, strategic significance, likely usefulness to a proposal, or inferred buyer intent. If semantic judgment is required, route the candidate for human selection without retrieving beyond the authorized boundary.

**Output:** bounded acquisition plan and selection diagnostics.

### 4. Acquisition

Fetch the selected resource through its permitted adapter. Preserve response bytes when policy allows, final and original URLs, redirect chain, response and content type, declared encoding, retrieval date and time, status, publisher headers when material, and a cryptographic content digest.

Acquisition must impose time, byte, redirect, retry, and request limits. Retries must be bounded and recorded. Authentication credentials must never enter evidence content or logs.

**Output:** immutable acquisition artifact or explicit acquisition failure.

### 5. Validation

Validate transport success, URL identity, publisher attribution, source authority classification, authenticity indicators, supported format, content-type agreement, digest, language, dates, document identity, malware and active-content policy, and declared scope. Validate authenticity independently from authority and freshness.

Validation does not correct source statements. Conflicting or suspicious metadata is preserved in diagnostics and prevents the affected document from being promoted when identity or authenticity cannot be established.

**Output:** accepted source artifact, quarantined artifact, or rejected artifact with reasons.

### 6. Representation normalization

Normalize only representation needed by the Buyer Evidence contract: URL form, language-tag casing, date encoding, enum values, whitespace required for stable exact extraction, and deterministic collection ordering. Retain original values alongside normalized acquisition metadata where semantic fidelity or diagnosis requires them.

Normalization must not paraphrase, translate, summarize, classify subject matter through inference, repair malformed content by guessing, or merge different documents.

**Output:** deterministic evidence candidates with original acquisition linkage.

### 7. Evidence creation

Create `EvidenceSource`, `EvidenceDocument`, `EvidenceFreshness`, `EvidenceScope`, `EvidenceCitation`, and `EvidenceExtract` values under [`BUYER_EVIDENCE_ARCHITECTURE.md`](BUYER_EVIDENCE_ARCHITECTURE.md). Stable IDs derive from governed identity inputs and cannot depend on discovery order, mutable display text, or transient run position.

Only exact requested extracts with exact citations may be created automatically. Whole documents may be preserved without extracts. Absence of an extract does not make an acquired document absent.

**Output:** candidate immutable `BuyerEvidenceSet` plus the complete retrieval diagnostic sidecar.

### 8. Reference closure

Verify that source, document, citation, extract, Buyer, and scope identities close; citations and extracts belong to the same document; supported languages and dates remain consistent; and duplicate identities do not hide distinct occurrences. Recompute deterministic digests and serialization where required.

**Output:** closed evidence set or a scoped validation failure. Invalid material cannot enter the closed set, but its acquisition and failure diagnostics remain preserved.

### 9. Completion

Evaluate the stopping rules and issue a completion state: `COMPLETE`, `PARTIAL`, `FAILED`, or `CANCELLED_BY_HUMAN`. Record coverage against the request, limits reached, unavailable or rejected candidates, unresolved metadata conflicts, and the exact evidence-set identity when one exists.

`COMPLETE` means the governed retrieval request and its bounded coverage conditions were satisfied. It does not mean that all public information was found, the evidence is sufficient for analysis, or the buyer is fully understood.

## Conflict handling

Retrieval records conflicts and never resolves them.

### Sources disagree

Preserve each valid document and occurrence independently. Record the conflicting metadata or source statements, respective authority, authenticity, dates, scopes, and citations. Do not choose a winner, average values, silently prefer Tier 1, or suppress a lower-tier contradiction.

### Documents change

Different content digests or publisher versions create distinct document versions linked by an observed version relationship. Retrieval does not overwrite the earlier artifact or assume that change implies correction.

### Pages disappear

Retain the prior acquisition artifact, digest, original URL, retrieval date, and later unavailability event. A disappearance does not invalidate what was previously retrieved and does not prove withdrawal or supersession.

### Documents are superseded

Record supersession only when an attributable source explicitly identifies the relationship. Preserve both documents and the exact supersession notice. Retrieval does not apply the newer document to canonical facts.

### Languages differ

Preserve each language version as a separate document identity unless the publisher explicitly declares equivalent versions and a governed identity rule links them. Retrieval does not translate or assume semantic equivalence. Conflicting language versions remain visible.

### Publication dates conflict

Preserve the date values and their origins. If a single document identity has incompatible dates that cannot be represented without ambiguity, quarantine it from the closed evidence set and retain the conflict in diagnostics. Retrieval never selects the more plausible date.

## Freshness and historical reproducibility

### Publication date

Publication date is source metadata. Missing, partial, or conflicting dates remain missing, partial, or conflicted under a future compatible contract; retrieval must not derive a publication date from file timestamps, search indexes, or URL patterns.

### Retrieval date

Retrieval date records when the artifact was acquired. It must be explicit and timezone handling must follow the future operational contract. It is not evidence of publication or effective date.

### Freshness

Freshness is an explicit assessment status made under a declared rule and assessment date. It must never depend silently on the current clock. `CURRENT`, `STALE`, `NOT_ASSESSED`, and `NOT_APPLICABLE` describe the assessment record, not document authority or accuracy.

### Refresh policy

A retrieval request declares whether refresh is manual, event-triggered, scheduled, or prohibited. Refresh creates a new run and compares stable locations, publisher versions, response validators, and content digests. It never mutates a prior run.

Refresh priority may use observable conditions such as a declared review date, expired validity period, changed digest, known procurement amendment, or human request. It may not use inferred strategic importance.

### Version history and supersession

Every distinct acquired representation remains addressable by stable identity, content digest, retrieval date, and lineage. Explicit supersession adds a relationship; it never deletes history. Corrected metadata is a new validated record linked to the earlier record.

### Caching

Caches are transport optimizations. A cache hit must identify the stored artifact, acquisition date, validation state, and digest. Cache state cannot change semantic identity or masquerade as a new retrieval. Expired or unverifiable cache entries cannot satisfy a request requiring fresh acquisition.

### Historical preservation

The system must be able to reconstruct which source representation supported an evidence set at its evidence cutoff. Historical evidence remains immutable even when a URL changes, a document is superseded, or a later run rejects the current source.

## Stopping rules

Retrieval is bounded because exhaustive collection is neither provable nor necessary.

### Required bounds

Every request defines:

- target Buyer identity and retrieval purpose;
- required and optional evidence categories;
- permitted source tiers, jurisdictions, languages, domains, and formats;
- maximum candidates, documents, bytes, requests, redirects, retries, and elapsed duration;
- per-host rate limits;
- minimum coverage conditions; and
- the human override authority.

No default may mean unlimited.

### Minimum completeness

Minimum completeness is satisfied when every required category has either at least one closed evidence document from an allowed source or an explicit terminal reason such as unavailable, inaccessible, unsupported, or not found within bounds. A terminal reason makes the run reproducible; it does not turn missing evidence into coverage.

### Source saturation

Saturation may stop discovery when a declared number of consecutive permitted discovery steps yields no new document identity for any unmet category and all Tier 1 seeds have reached a terminal state. Saturation is an operational stopping condition, not proof that no additional evidence exists.

### Duplicate detection

Exact duplicate content is detected by cryptographic digest. Location identity uses normalized URL and publisher identifiers. Similar titles, near-duplicate prose, or matching filenames are insufficient for semantic deduplication. Duplicate occurrences and redirect paths remain in diagnostics even when one content artifact is retained.

### Bounded completion

Retrieval stops when minimum completeness is met, saturation is reached, a declared resource bound is reached, all candidates reach terminal states, or a human cancels the run. Reaching a bound produces `PARTIAL` unless all required coverage conditions were already satisfied.

### Human override

An authorized human may add or exclude a named source, reduce bounds, cancel a run, or accept partial completion. The override, actor, time, scope, and reason are recorded. A human override cannot reclassify invalid evidence as valid, erase failures, or authorize retrieval for a prohibited analytical purpose.

## Validation philosophy

Validation protects identity and provenance rather than judging content. It occurs at each transition and is repeated at reference closure.

The future validation contract must test:

- stable run, Buyer, source, document, citation, extract, and scope identities;
- allowed schemes, domains, redirects, authentication modes, categories, formats, and languages;
- exact original and final URLs without credential leakage;
- publisher attribution and authority classification evidence;
- authenticity status and the indicators supporting it;
- publication, retrieval, assessment, and validity date syntax and consistency;
- content-type and format agreement;
- content digests and byte-level integrity;
- exact, non-fuzzy locators;
- document-version and supersession links;
- collection uniqueness with occurrence preservation;
- source-to-document-to-citation-to-extract reference closure;
- Buyer and evidence-scope consistency;
- deterministic output for identical acquisition inputs; and
- rejection of prohibited interpretive fields and unsupported contract versions.

Passing technical validation establishes that the artifact is well-formed and attributable. It does not establish that a source statement is true, sufficient, relevant to a decision, or suitable for an interpretation.

## Fail-closed behavior

| Condition | Required behavior |
|---|---|
| Unavailable source | Record URL, attempt metadata, status, and terminal reason; do not invent content or substitute an unnamed source. |
| Malformed document | Preserve safely when policy permits, quarantine it, record format and validation failures, and exclude it from the closed evidence set. |
| Authentication failure | Stop the affected acquisition, redact credentials, record the failure class, and do not bypass access controls. |
| Broken link or redirect | Preserve the original location and redirect observations; accept a destination only if it independently passes scope and source policy. |
| Unsupported format | Preserve metadata and digest when safe, record the unsupported format, and create no extracts or fabricated text representation. |
| Duplicate identity | Stop the affected closure when one identity maps to incompatible artifacts; preserve each occurrence and require a deterministic identity correction. |
| Conflicting metadata | Preserve all observed values and their origins; quarantine the affected identity when a required field cannot be represented unambiguously. |
| Unsupported language | Preserve document-level acquisition metadata when permitted, create no unsupported extracts, and mark required language coverage unmet. |
| Network interruption | Apply only bounded recorded retries; retain completed artifacts and report the run as partial or failed. |
| Partial retrieval | Emit only valid closed evidence, retain all failures and unmet coverage, and label the run `PARTIAL`; never present it as complete. |
| Authenticity not established | Use the supported provisional or unverified status when the evidence contract and request permit it; otherwise quarantine the artifact. Never upgrade authenticity from appearance. |
| Active or unsafe content | Do not execute it; quarantine or process through a separately approved safe adapter. |
| Reference-closure failure | Reject the affected evidence set or scoped artifact and preserve diagnostics; never create dangling references. |

Failures are scoped. One unavailable document does not erase independently valid evidence, while valid evidence does not conceal the failed portion of the request.

## Security and access principles

Future retrieval implementations must:

- treat all external content as untrusted;
- prevent server-side request forgery through governed schemes, address ranges, redirects, and destination validation;
- enforce response-size, decompression, archive-depth, recursion, timeout, and rate limits;
- never execute source scripts, macros, embedded objects, or instructions;
- isolate parsing of hostile or malformed formats;
- keep credentials out of URLs, evidence artifacts, diagnostics, and logs;
- respect authorization, terms, robots policy, licensing, and privacy constraints applicable to the source;
- collect public organizational information rather than unnecessary personal data; and
- preserve a reviewable acquisition record without storing prohibited secrets.

These requirements protect the evidence boundary. They do not authorize any particular network tool or access method.

## Out of scope

Buyer Retrieval does not:

- implement Buyer Intelligence or any other analyst;
- summarize, paraphrase, translate, or interpret documents;
- interpret priorities or assess the organization;
- infer buyer intent, evaluator preference, relationships, or procurement behaviour;
- recommend proposal strategy, pricing, pursuit action, or Bid / No Bid;
- generate assumptions, unknowns, hypotheses, management questions, scores, rankings, predictions, or executive conclusions;
- produce the Buyer Brief or any other briefing volume;
- modify Canonical Buyer or resolve canonical conflicts;
- use AI reasoning;
- establish general web search, crawling, monitoring, or persistence in this phase; or
- make external access available through an API in this phase.

## Extension roadmap

Each version requires its own implementation design, threat review, contract validation, evidence, and production-readiness decision. Later stages are not authorized by this document alone.

### Version 1 — Deterministic human-directed acquisition

Accept a canonical Buyer reference and explicit human-supplied source locations. Acquire supported public documents within strict bounds, validate them, and create closed Buyer Evidence. No open-ended discovery, scheduling, AI, or authenticated repository access.

### Version 2 — Governed official-source discovery

Add allowlisted official indexes, sitemaps, catalogues, and narrow search adapters. Candidate discovery remains bounded and recorded. Source hierarchy, attribution, duplicate detection, and human review gates become executable policy.

### Version 3 — Governed authenticated sources

Add approved organizational or government repositories where access is authorized. Introduce credential isolation, permission-aware provenance, access-expiry behavior, and circulation constraints without embedding credentials in evidence.

### Version 4 — Scheduled refresh and version comparison

Add human-configured refresh schedules, conditional acquisition, digest comparison, explicit freshness rules, and immutable version lineage. Scheduling never changes the original evidence cutoff or silently replaces evidence.

### Version 5 — Bounded evidence monitoring

Monitor approved source sets for attributable changes and create reviewable change events. Monitoring does not infer significance, alter canonical truth, or trigger intelligence automatically. Humans govern which changes enter a new evidence set and whether later layers run.

## Acceptance criteria

A future Buyer Retrieval implementation conforms only when it demonstrates that:

1. every run has an explicit Buyer, purpose, scope, supported contract version, and finite bounds;
2. source, publisher, document, authenticity, freshness, applicability, and relevance remain separate dimensions;
3. every accepted artifact retains original location, final location, publisher attribution, retrieval date, format, and integrity identity;
4. every Buyer Evidence reference closes under `buyer-evidence/1` or an explicitly supported successor;
5. identical validated acquisition inputs produce deterministically equivalent evidence output;
6. discovery order, search rank, retries, cache state, and collection order do not change semantic identity;
7. all meaningful occurrences, failures, redirects, versions, and explicit supersession relationships remain inspectable;
8. conflicting sources and metadata remain unresolved and visible;
9. changed, removed, or superseded documents do not overwrite historical evidence;
10. unsupported, malformed, unauthenticated, or unclosed material cannot enter a closed evidence set;
11. partial completion is explicit and cannot be mistaken for complete coverage;
12. stopping conditions are finite, deterministic, and recorded;
13. human overrides are attributable and cannot bypass evidence validity;
14. external content cannot alter retrieval instructions or execute active content;
15. credentials and prohibited personal or secret information do not enter evidence artifacts;
16. retrieval creates no canonical fact, interpretation, inference, summary, recommendation, score, ranking, prediction, question, or brief;
17. no retrieval path writes directly to Canonical Buyer, Buyer Intelligence, Buyer Brief, or Human Decision records;
18. tests cover reference closure, provenance, version history, conflicts, failures, interruption, caching, limits, and replay of historical retrieval results; and
19. operational evidence accurately distinguishes local deterministic tests from live external validation.

## Rationale for major design decisions

### Put retrieval before Buyer Evidence

External material is not evidence merely because it was reachable. The retrieval boundary records acquisition and validates attribution before constructing the governed evidence contract.

### Keep retrieval below Canonical Truth

Allowing retrieval to create facts would combine acquisition with reconciliation. Separate layers ensure that a retrieved statement remains a source statement until canonical rules establish what the available evidence supports.

### Separate authority dimensions

A source can be official yet stale, authentic yet inapplicable, or relevant yet not authoritative. One combined quality score would hide these distinctions and create false precision.

### Use tiers for collection order only

Primary sources usually provide the closest institutional record, so they deserve early attention. Treating tier as automatic truth would suppress valid contradictions and confuse authority with correctness.

### Preserve bytes, metadata, and digests

Web content changes. Reproducibility requires the exact acquired representation and enough metadata to establish when, where, and how it was obtained. A URL alone cannot reproduce historical evidence.

### Make normalization representational

Normalization improves stable identity and contract compatibility. Paraphrase, translation, semantic repair, and relevance judgments would change meaning and therefore belong outside retrieval.

### Require exact citations

Exact locators let reviewers inspect source support and prevent vague attribution. Fuzzy matching may assist discovery in a future governed tool, but it cannot become an authoritative citation.

### Preserve conflicts without resolving them

Retrieval lacks authority to reconcile competing statements. Keeping each occurrence allows Canonical Truth or later analysis to apply its own transparent rules without losing provenance.

### Make freshness explicit

Silent dependence on the current date makes replay nondeterministic. An assessment status, rule, and date make freshness reviewable and preserve what was known at an evidence cutoff.

### Bound every run

The public web has no provable end. Explicit coverage requirements, saturation rules, and resource limits prevent uncontrolled collection while making incompleteness visible.

### Keep caches operational

Cache availability is transient. Treating a cache hit as new evidence would falsify retrieval history and make identical requests depend on hidden state.

### Retain partial valid evidence

Fail-closed behavior should protect the affected transition without discarding unrelated valid material. A partial result is useful when its omissions and failures remain explicit.

### Require human control over expansion

Humans may identify a necessary source or stop collection, but cannot waive identity and provenance invariants. This preserves accountable scope without weakening evidence authority.

## Doctrine compliance

This architecture preserves evidence before inference, stable identity, provenance, immutable history, deterministic transitions, explicit uncertainty, scoped fail-closed behavior, layer isolation, and sovereign human judgment. It advances no proposal-writing, generic procurement, autonomous bidding, prediction, executive-decision, or black-box anti-goal.

The document defines future behavior only. It introduces no retrieval implementation, network access, crawler, search, AI, persistence, API, schema, migration, Buyer Intelligence, Buyer Evidence modification, Canonical Buyer modification, or Buyer Brief generation.
