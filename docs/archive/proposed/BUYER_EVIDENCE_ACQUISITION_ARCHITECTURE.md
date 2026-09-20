# Document Metadata

| Field | Value |
|---|---|
| Document | `BUYER_EVIDENCE_ACQUISITION_ARCHITECTURE.md` |
| Title | Buyer Evidence Acquisition Architecture |
| Authority Level | Level 4 — Architecture Specification |
| Version | 1.0.0 |
| Status | Proposed |
| Purpose | Govern how attributable public organizational material is selected, acquired, validated, and closed into a Buyer Evidence corpus. |
| Higher Authority | [`MANIFESTO.md`](../../../MANIFESTO.md), [`AGENT.md`](../../../AGENT.md), [`GOVERNANCE.md`](../../../GOVERNANCE.md), [`ANTI_GOALS.md`](../../../ANTI_GOALS.md), [Product Doctrine](../../product/PRODUCT_VISION.md), [Architecture Doctrine](../../architecture/ARCHITECTURE.md), [Engineering Doctrine](../../engineering/CONTRIBUTING.md), [`BUYER_INTELLIGENCE_SPECIFICATION.md`](BUYER_INTELLIGENCE_SPECIFICATION.md), [`BUYER_DOMAIN_ARCHITECTURE.md`](../../../BUYER_DOMAIN_ARCHITECTURE.md), and [`BUYER_EVIDENCE_ARCHITECTURE.md`](../../../BUYER_EVIDENCE_ARCHITECTURE.md) |
| Governed Documents | Future Buyer Evidence acquisition policies, coverage profiles, acquisition plans, adapters, validation contracts, implementations, runbooks, and acceptance evidence. |
| Related Documents | [`BUYER_RETRIEVAL_ARCHITECTURE.md`](BUYER_RETRIEVAL_ARCHITECTURE.md), [`BUYER_INTELLIGENCE_ARCHITECTURE.md`](../../../BUYER_INTELLIGENCE_ARCHITECTURE.md), [`BUYER_BRIEF_DESIGN.md`](BUYER_BRIEF_DESIGN.md), and [`BID_INTELLIGENCE_BRIEFING_PACK.md`](BID_INTELLIGENCE_BRIEFING_PACK.md) |

# Buyer Evidence Acquisition Architecture

## Purpose

Buyer Evidence Acquisition builds a bounded, attributable public evidence corpus for a known Buyer. It reduces the repeated work of locating, verifying, preserving, and tracing organizational material before proposal kickoff.

Its output is governed Buyer Evidence and a complete acquisition record. It does not establish what a source statement means, decide which competing statement is true, create a Canonical Buyer fact, perform Buyer Intelligence, or produce a Buyer Brief.

Acquisition quality is assessed through declared coverage, provenance closure, reproducibility, and visible gaps. Document count and collected volume are operational measurements only. They are never evidence quality scores.

## Architectural position

```text
External Organizations and Official Public Authorities
                         ↓
              Buyer Evidence Acquisition
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

The arrows express authority transitions. Material reachable on the public web is an acquisition candidate, not Buyer Evidence. A candidate becomes Buyer Evidence only after its identity, attribution, acquisition history, authenticity state, metadata, scope, and references satisfy the evidence contract.

Acquisition sits below Canonical Truth. It may preserve exact source statements and source metadata. It cannot promote them to facts or resolve disagreement. Canonical Buyer remains responsible for governed organizational identity, Buyer Intelligence for bounded interpretation, Buyer Brief for presentation, and humans for judgment.

### Relationship to Buyer Retrieval

Buyer Evidence Acquisition is the governing corpus-building capability. [`BUYER_RETRIEVAL_ARCHITECTURE.md`](BUYER_RETRIEVAL_ARCHITECTURE.md) provides the detailed transport and retrieval architecture for external-resource access, redirects, caching, hostile content, resource limits, and reproducible acquisition runs.

Acquisition may also accept a human-supplied artifact whose source identity is preserved; retrieval is therefore one acquisition mechanism rather than the definition of corpus completeness. Both documents apply. This document governs coverage policy, acquisition priority, corpus completion, and the handoff into Buyer Evidence. The retrieval architecture governs the narrower mechanics of obtaining an external representation. Neither document authorizes implementation.

## Responsibilities

Buyer Evidence Acquisition is responsible for:

1. accepting an explicit Canonical Buyer identity or a governed provisional identity resolution request;
2. declaring the acquisition purpose, evidence cutoff, applicable Buyer Intelligence version, and finite operating bounds;
3. translating the purpose into a versioned coverage profile of required, conditional, and optional evidence needs;
4. discovering or accepting candidate sources only through permitted methods;
5. establishing candidate publisher identity, source category, institutional authority, jurisdiction, and organizational scope;
6. planning collection in a deterministic authority-first order;
7. acquiring exact source representations while preserving location, time, format, bytes or equivalent content identity, and transport diagnostics;
8. verifying authenticity indicators without judging the truth of source statements;
9. preserving document versions and explicit supersession relationships;
10. registering sources, documents, citations, and extracts under the Buyer Evidence contract;
11. proving reference closure and retaining rejected or unavailable candidates in a diagnostic sidecar;
12. assessing corpus coverage against the declared profile; and
13. stopping with an explicit completion state and immutable acquisition manifest.

Acquisition may reject or quarantine material. It may not repair a source by guessing, replace a missing source with remembered knowledge, or treat a plausible document as authentic without evidence.

## Boundaries

### Evidence, not facts

Acquisition records what an attributable source published. It does not state that a mandate is legally controlling, a priority remains operationally active, an organizational chart reflects informal influence, or a policy applies to the current opportunity. Those are later canonical or analytical questions.

### Mechanical extraction only

An exact extract may be registered when its selection is governed by an explicit locator, human instruction, deterministic structural rule, or declared coverage request. Acquisition cannot choose a passage because it appears strategically important, summarize a long document, paraphrase text, translate meaning, or generate a conclusion.

### Authority classification is proposition-specific

Authority describes what an institution is competent to publish. It does not declare every statement accurate or universally applicable. Enabling legislation may be authoritative for statutory mandate; an annual report may be authoritative for what the organization reported for that period; an official procurement notice may be authoritative for the stated procurement context. Source tier never resolves a substantive conflict automatically.

### No downstream writes

Acquisition cannot write directly to Canonical Buyer, Canonical Opportunity, Buyer Intelligence, Buyer Brief, Decision Workspace, persistence records for those layers, or Human Decision records. It hands off a closed evidence set and its acquisition record through an explicit validated boundary.

### No analytical output

Acquisition produces no interpretation, assumption, hypothesis, unknown about organizational meaning, management question, recommendation, score, rank, prediction, procurement strategy, proposal strategy, pricing advice, or executive conclusion. Acquisition gaps are operational evidence-coverage states; Buyer Intelligence decides how a validated gap is represented in its own contract.

### External content is untrusted

Source content is data. Embedded instructions, scripts, prompts, macros, redirects, metadata claims, or page text cannot change acquisition policy, permitted domains, bounds, validation rules, or downstream authority.

## Governed acquisition records

A future implementation should preserve separate immutable records for:

- **Acquisition request:** Buyer identity, purpose, evidence cutoff, requested languages and jurisdictions, coverage profile version, permitted source policy, limits, and human owner.
- **Coverage profile:** each evidence need, its applicability rule, priority, accepted source classes, minimum closure condition, and terminal gap reasons.
- **Candidate record:** discovered or supplied location, discovery mechanism, claimed publisher, proposed category, observed scope, and disposition.
- **Acquisition plan:** selected candidates, deterministic order, expected document identities, permitted adapters, bounds, and reasons for inclusion.
- **Acquisition event:** original and final locations, redirects, access time, response status, content type, size, digest, and failure details.
- **Authenticity record:** observed indicators, verification method, resulting authenticity status, reviewer when required, and unresolved conflicts.
- **Version relationship:** distinct document identities and attributable claims of amendment, replacement, correction, or supersession.
- **Evidence registration:** proposed `EvidenceSource`, `EvidenceDocument`, `EvidenceCitation`, `EvidenceExtract`, freshness, language, dates, and scope.
- **Coverage ledger:** the disposition of every required, conditional, and optional evidence need.
- **Diagnostic sidecar:** rejected material, inaccessible candidates, duplicate occurrences, metadata conflicts, unsupported formats or languages, and all bounded attempts.
- **Completion manifest:** run identity, contract versions, accepted evidence-set identity and digest, completion state, limits reached, coverage ledger, and human overrides.

Operational records never become source evidence merely because they describe an acquisition. They establish how the corpus was built and why a candidate was accepted, rejected, or absent.

## Governed lifecycle

Every lifecycle transition produces a new immutable record or an explicit scoped failure. Later success never erases an earlier attempt.

### 1. Initiation and request validation

Accept a Buyer identity, acquisition purpose, opportunity context when applicable, evidence cutoff, coverage-profile version, allowed sources, languages, formats, jurisdictions, access modes, and finite resource limits. Reject missing identity, unsupported versions, prohibited purposes, unlimited requests, and requests that seek private, speculative, or strategic intelligence.

**Output:** accepted acquisition request or request-level failure.

### 2. Coverage-profile selection

Select the profile appropriate to the active Buyer Intelligence version, organization type, jurisdiction, and current opportunity. Classify every evidence need as `REQUIRED`, `CONDITIONAL`, or `OPTIONAL`. Evaluate conditional applicability from declared facts or human input, never from inferred importance.

**Output:** frozen coverage profile with an initial `UNASSESSED` ledger entry for every need.

### 3. Candidate source discovery

Discover candidates from human-supplied locations, official organizational indexes, constituting authorities, official government catalogues, procurement portals, and other methods permitted by the active roadmap stage. Record every query, index, seed, returned location, discovery time, and source claim needed for reproducibility.

Discovery identifies candidates. Search rank, snippets, filenames, and domain appearance cannot establish authority, authenticity, document identity, or relevance.

**Output:** bounded candidate inventory and discovery diagnostics.

### 4. Authority and scope validation

Verify the institutional owner, permitted source category, authority class, jurisdiction, Buyer relationship, and proposed coverage need. A source must be competent to provide the claimed kind of material. A third-party repost does not become an official source because it reproduces official-looking text.

Conflicting ownership, scope, or category claims remain explicit. Candidates that cannot meet the active source policy are rejected or retained only as diagnostics.

**Output:** admissible candidate set with authority and scope records.

### 5. Acquisition planning

Create a deterministic plan ordered by coverage priority, authority class, specificity, expected currency, and stable source identity. Declare candidate limits, document and byte limits, per-host limits, supported adapters, redirect policy, retries, and expected stopping conditions before access begins.

Planning may avoid redundant transport when a byte-identical validated artifact is already available, but the new occurrence and its provenance remain recorded.

**Output:** immutable acquisition plan.

### 6. Document acquisition

Obtain the selected exact representation through a permitted retrieval adapter or controlled human-supplied-artifact path. Preserve the original location, final location, redirect chain, access method, retrieval date and time, response metadata, declared and detected format, raw artifact or approved immutable representation, size, and cryptographic digest.

Do not execute active content, follow unapproved redirects, bypass access controls, or silently substitute a different document after failure.

**Output:** acquisition artifact or explicit attempt failure.

### 7. Authenticity, identity, and version verification

Assess whether the acquired representation is attributable to the claimed publisher using declared indicators such as official hosting, publisher identifiers, signatures, publication catalogues, internal document metadata, and corroborating official references. Authenticity remains separate from freshness, relevance, truth, and analytical confidence.

Assign a stable document identity. Preserve distinct versions. Record supersession only when an attributable source explicitly states the relationship. Matching titles or newer dates do not prove replacement.

**Output:** verified, provisional, unverified, conflicted, or quarantined artifact with version lineage.

### 8. Evidence registration

Map accepted material into the immutable Buyer Evidence contracts. Preserve source identity, category, authority, title, canonical location, language, publication date when stated, retrieval date, freshness assessment, scope, publisher identifiers, version, digest, exact citations, and bounded verbatim extracts.

Normalization is representational only. It may normalize URL form, language-tag casing, date encoding, enum vocabulary, and deterministic ordering. It cannot paraphrase, summarize, infer missing metadata, translate, or repair source meaning.

**Output:** candidate Buyer Evidence records plus complete acquisition diagnostics.

### 9. Reference closure

Verify that every document refers to an accepted source, every citation to one accepted document, every extract to citations in that document, every organizational scope to the target Buyer, and every identity is unique and version-compatible. Recompute content and aggregate digests where the governing contract requires them.

Dangling, conflicting, duplicate, or cross-document references fail the affected closure. Independently valid records may proceed in a partial corpus when the coverage ledger records the exclusion.

**Output:** closed Buyer Evidence set or scoped closure failures.

### 10. Corpus completeness assessment

Evaluate the closed evidence set against each coverage need. Record accepted document and citation identities, temporal and language coverage, rejected or unavailable candidates, and one explicit coverage status. Completeness assessment observes acquisition results; it does not judge whether later analysis can reach a conclusion.

**Output:** completed coverage ledger and corpus-level completion proposal.

### 11. Completion and handoff

Apply the stopping rules and issue `COMPLETE`, `PARTIAL`, `FAILED`, or `CANCELLED_BY_HUMAN`. Seal the completion manifest, closed evidence-set identity and digest when available, diagnostics identity, evidence cutoff, contract versions, and all human overrides.

Handoff exposes Buyer Evidence to the next governed layer. It does not trigger Canonical Buyer reconciliation, Buyer Intelligence, or Buyer Brief generation automatically.

**Output:** reproducible acquisition result ready for explicit downstream acceptance.

## Completeness philosophy

A complete corpus is complete **against one declared coverage profile at one evidence cutoff**. It is not a claim that the public record is exhaustive, that every page was found, that the organization is fully understood, or that Buyer Intelligence can answer every question.

Completeness has no aggregate percentage or score. Each evidence need retains an independent status:

- `SATISFIED`: at least one admissible, closed evidence item meets the need's stated source, scope, language, and temporal conditions.
- `GAP_NOT_FOUND`: bounded discovery completed without an admissible item.
- `GAP_UNAVAILABLE`: an identified source could not be accessed under permitted conditions.
- `GAP_REJECTED`: candidate material existed but failed authority, authenticity, format, metadata, or reference validation.
- `GAP_UNSUPPORTED`: the active acquisition version could not safely process the material or language.
- `CONFLICTED`: required identity or metadata conflict prevents safe closure for the need.
- `NOT_APPLICABLE`: the profile's explicit applicability rule was evaluated and recorded as false.
- `DEFERRED_BY_HUMAN`: an authorized human deferred an optional or conditional need with attributable rationale.

Only `SATISFIED` and valid `NOT_APPLICABLE` dispositions close a required need for `COMPLETE`. A terminal gap makes incompleteness reproducible; it never counts as evidence coverage. Human acceptance of a partial corpus does not rename it complete.

### Baseline evidence needs

The following needs should be evaluated for every Buyer. Applicability, rather than a universal document checklist, controls what must be acquired:

| Evidence need | Intended source proposition | Default priority |
|---|---|---|
| Organizational identity | Legal or officially used name, organizational form, jurisdiction, official location | Required |
| Constituting authority and mandate | Statutory, charter, regulatory, or formally published purpose and responsibilities | Required |
| Current strategic direction | Current strategic, corporate, departmental, or business plan when publicly issued | Required, or explicit gap |
| Current accountability reporting | Most recent annual, performance, accountability, or equivalent public report | Required, or explicit gap |
| Governance and organizational structure | Governing body, parent relationship, official organization chart, departments, or responsibility pages | Required at the level publicly available |
| Accessibility obligations and commitments | Applicable legislation, accessibility plan, statement, or policy | Conditional on jurisdiction and organization |
| Current procurement identity and role | Official notice and issued procurement material identifying the Buyer and current opportunity | Required for opportunity-bound acquisition |
| Procurement governance | Public procurement policy, delegation, supplier, ethics, or contracting framework | Conditional on the active Buyer Intelligence version and public availability |
| Relevant public functions and initiatives | Official function, program, service, policy, or initiative material connected to the declared acquisition topic | Opportunity-dependent |
| Enabling legislation and regulation | Constituting or governing instruments not already satisfying mandate coverage | Conditional on organization type and jurisdiction |

The coverage profile may distinguish language variants, reporting periods, organizational units, or jurisdictions where those distinctions are material and declared. One generic website page cannot silently satisfy multiple needs unless its exact cited content and authority meet each need independently.

### Temporal completeness

Current-state needs declare an evidence cutoff and freshness rule. Historical documents may remain valid evidence for historical statements but cannot satisfy a current-plan need merely because no newer material was found. Missing publication dates remain missing. File timestamps, search indexes, and URL patterns cannot supply them.

### Language completeness

The request declares required languages based on the Buyer, jurisdiction, source policy, and intended audience. Parallel language versions remain separate evidence occurrences unless the publisher explicitly identifies their relationship. Acquisition never assumes translation equivalence.

### Scope completeness

Organization-wide evidence does not automatically establish department-level context. Department material does not automatically establish an organization-wide position. Coverage records the exact organizational and opportunity scope obtained.

## Acquisition priorities

Priority controls collection order, not truth or later analytical importance.

### Priority 1 — Identity and constituting authority

Seek official organizational identity, constituting instruments, mandate, jurisdiction, and the current procurement source first. These records anchor Buyer and scope identity for every later document. If identity cannot be closed, acquisition fails before collecting a broad corpus.

### Priority 2 — Current authoritative organizational record

Seek the current official strategy or plan, most recent accountability report, governance and structure material, and applicable accessibility material. Prefer direct publisher locations and explicit publication identities.

### Priority 3 — Opportunity-dependent organizational context

Seek official department, function, program, policy, initiative, and procurement-governance material tied to the declared coverage needs. The tie must come from the request, canonical opportunity entities, deterministic metadata, or human instruction. Acquisition does not infer strategic relevance from document prose.

### Priority 4 — Official corroboration and version closure

Seek official catalogues, legislative repositories, government publications, archived publisher versions, and explicit amendment or supersession notices needed to verify identity, fill a required gap, or close a version relationship.

### Optional material

Collect older reports, additional official releases, broader program material, and contextual publications only when the coverage profile names their use. Interesting material is not sufficient reason to expand the corpus.

Secondary commentary, search snippets, aggregators, marketing databases, inferred-contact services, anonymous material, and personal social media remain outside Buyer Intelligence v1. A later source class requires an explicit specification and cannot be introduced through acquisition convenience.

## Validation before Buyer Evidence

Validation occurs at every lifecycle transition and is repeated before reference closure. It verifies representation, identity, attribution, and provenance. It does not validate an interpretation or certify the substantive truth of a published claim.

An accepted evidence item must pass all applicable checks:

1. **Request validity:** supported contract versions, explicit Buyer, lawful purpose, finite bounds, declared evidence cutoff, and permitted access method.
2. **Source admissibility:** identifiable institutional owner, permitted source category and authority class, approved scheme and domain policy, and attributable Buyer or jurisdiction relationship.
3. **Artifact integrity:** bounded size, supported format, content-type agreement, cryptographic digest, safe handling, and no executed active content.
4. **Document identity:** stable unique identity, publisher document identifier when available, version distinction, original and canonical locations, and no incompatible artifact collision.
5. **Metadata integrity:** title, publisher, language, retrieval date, publication date when stated, freshness record, authenticity status, and scope are syntactically and relationally consistent.
6. **Authenticity:** the assigned status is supported by recorded indicators; appearance, logo, filename, or search rank alone cannot produce `VERIFIED`.
7. **Citation precision:** exact non-fuzzy locator belonging to the accepted document; extracts are bounded verbatim source text and retain their citation identities.
8. **Reference closure:** all source, document, citation, extract, Buyer, opportunity, scope, and version references resolve under supported contracts.
9. **Occurrence preservation:** exact duplicates may share content identity, but distinct locations, retrievals, versions, and source occurrences remain inspectable.
10. **Boundary enforcement:** no interpretation, summary, inferred metadata, assumption, question, recommendation, score, ranking, prediction, or decision enters Buyer Evidence.

Validation cannot silently coerce an invalid date, upgrade authenticity, choose among conflicting metadata, invent a canonical URL, construct a missing locator, or repair a broken reference. The affected material is rejected or quarantined, and the diagnostic record survives.

## Conflict and version handling

- Preserve valid conflicting source occurrences independently.
- Preserve original and normalized metadata values when needed to diagnose a conflict.
- Quarantine an identity when required metadata cannot be represented unambiguously.
- Create distinct document versions for distinct acquired representations.
- Record amendment, correction, or supersession only from an attributable explicit statement.
- Never use publication date, retrieval order, source tier, filename, or rule order as automatic conflict resolution.
- Never overwrite an earlier artifact when a page changes or disappears.
- Treat absence, removal, or inaccessibility as an acquisition event, not proof that a source statement was withdrawn.

Conflict resolution belongs to the canonical layer under its own proposition-specific authority rules. Acquisition preserves the material required for that work.

## Stopping rules

Every acquisition request is finite. No default may mean unlimited discovery, documents, bytes, hosts, redirects, retries, or elapsed time.

Acquisition stops when the first applicable condition occurs:

1. every required and applicable conditional need is `SATISFIED` or validly `NOT_APPLICABLE`, and any explicitly requested optional work is complete;
2. every planned candidate has reached an accepted or terminal disposition;
3. the declared source-saturation rule is met after all priority-one seeds and required official indexes reach a terminal state;
4. a request, document, byte, host, retry, redirect, rate, or elapsed-time bound is reached;
5. reference closure cannot produce any valid evidence set;
6. the Buyer identity or permitted acquisition purpose becomes invalid; or
7. an authorized human cancels the run.

Completion state follows deterministically:

- `COMPLETE` only when all required and applicable conditional needs close.
- `PARTIAL` when at least one valid evidence item closes but one or more required needs remain a gap, conflict, or unsupported state, or a bound ends the run.
- `FAILED` when no valid evidence set can close or a request-level invariant fails.
- `CANCELLED_BY_HUMAN` when an authorized cancellation occurs; valid work completed before cancellation remains preserved but is not relabeled complete.

Source saturation and human acceptance are stopping conditions, not proof of completeness. Optional candidates do not keep a run open once the declared profile and plan are satisfied.

## Missing evidence

Every unmet need records:

- coverage-need identity and category;
- required, conditional, or optional status;
- candidates considered and discovery paths attempted;
- each terminal disposition and validation failure;
- limits or policy boundaries that prevented further work;
- language, jurisdiction, scope, and temporal gaps;
- whether a human deferred or cancelled work; and
- the final coverage status at the evidence cutoff.

The system reports “not found within declared bounds,” “unavailable,” “rejected,” or another precise state. It never reports that a document does not exist unless an authoritative source explicitly establishes that fact. It never fills the gap with generalized organizational knowledge.

## Fail-closed behavior

| Condition | Required behavior |
|---|---|
| Buyer identity cannot be closed | Stop corpus construction; retain candidates and identity diagnostics; create no Buyer-scoped evidence set. |
| Source owner or authority cannot be established | Reject or retain as unverified only when the active evidence contract and request permit it; never upgrade by appearance. |
| Canonical or original URL is unavailable | Record the missing location and reject closure when the contract requires it; never invent a URL. |
| Publication date is absent | Preserve it as absent when permitted; do not infer it from file metadata, search results, or URL structure. |
| Required metadata conflicts | Preserve every observed value and origin; quarantine the affected identity until a governed representation is possible. |
| Source is inaccessible | Record attempt metadata and terminal reason; do not substitute an unnamed mirror or remembered content. |
| Unsupported format or language | Preserve safe acquisition metadata and digest when permitted; create no fabricated extract; mark the need unmet. |
| Malformed or unsafe content | Isolate or quarantine it under approved handling; never execute embedded content. |
| Duplicate content | Preserve every occurrence and provenance; use digest equality only for byte-level equivalence. |
| Document changes or disappears | Preserve prior versions and later observations; never rewrite historical acquisition state. |
| Citation cannot close | Exclude the affected citation or artifact from closed evidence and retain the failure in diagnostics. |
| Resource bound is reached | Stop predictably and report `PARTIAL` unless completion conditions were already met. |
| Network or adapter failure | Apply only declared bounded retries; preserve successful independent artifacts and explicit failures. |
| Partial corpus accepted by a human | Record actor, time, reason, and scope; retain `PARTIAL` as the completion state. |

Failures are scoped. Invalid material cannot acquire authority, while one failed candidate cannot erase unrelated evidence that closed successfully.

## Reproducibility and traceability

A reviewer must be able to determine:

- which Buyer and coverage profile governed the run;
- which sources and discovery paths were considered;
- why each candidate was selected, rejected, deferred, or unavailable;
- what exact representation was acquired, from where, and when;
- which digest and version identify it;
- which validation rules and contract versions applied;
- how every evidence citation closes to a document and source;
- which required needs were satisfied and which remained gaps; and
- why and under whose authority acquisition stopped.

Re-running the same request may observe a changed external world. Reproducibility therefore means reconstructing the original acquisition state and producing deterministically equivalent records from the same captured representations and declared inputs. It does not mean pretending a mutable public source will always return the same bytes.

## Human authority

An authorized human may:

- supply a named public source or artifact;
- declare an opportunity-dependent coverage need;
- exclude a candidate for a recorded legal, ethical, licensing, privacy, or relevance reason;
- reduce bounds or cancel a run;
- request a new run after a gap or change; and
- accept a partial corpus for downstream consideration.

A human override cannot invent evidence, waive reference closure, convert prohibited sources into authoritative sources, conceal a gap, reclassify invalid material as valid, or permit acquisition to create intelligence. Downstream consumers remain responsible for whether their own minimum evidence conditions are met.

## Security, legal, and ethical constraints

Future implementations must treat external material as hostile input and enforce governed schemes, hosts, address ranges, redirects, response sizes, decompression limits, archive depth, parser isolation, timeouts, and rate limits. They must not execute scripts, macros, embedded objects, or instructions.

Credentials remain outside evidence, URLs, diagnostics, and logs. Acquisition respects authorization, access terms, robots policy where applicable, licensing, copyright, privacy, retention, and circulation restrictions. Public availability is not blanket permission to collect personal data. Personal biographies, inferred contacts, relationship data, and unnecessary personal information are excluded from Buyer Intelligence v1 acquisition.

Security controls protect the evidence boundary but do not grant source authority or analytical meaning.

## Roadmap

Each stage requires a separate implementation design, threat review, contract review, deterministic tests, and production-readiness decision. This document does not authorize any stage to operate.

### Stage 1 — Manual governed acquisition

Humans identify official sources and provide source locations or artifacts. The system validates the request, records provenance, verifies supported metadata and authenticity indicators, registers Buyer Evidence, closes references, and produces a coverage ledger. No open-web discovery, AI, scheduling, or automatic refresh.

### Stage 2 — Guided acquisition planning

Add reusable versioned coverage profiles, official-source checklists, deterministic candidate queues, and human review gates. The system identifies unfilled evidence needs and organizes acquisition work without searching independently or inferring relevance.

### Stage 3 — Semi-automated official-source acquisition

Add approved adapters for named official sites, catalogues, procurement portals, legislative repositories, and human-selected resources. Acquisition remains bounded, human-directed, and fully recorded. No general crawler or semantic source selection.

### Stage 4 — Governed public-web acquisition

Add allowlisted discovery mechanisms, sitemaps, official search endpoints, redirect controls, hostile-content isolation, rate limits, and deterministic source-saturation rules. Candidate ranking affects work order only and never evidence authority or downstream meaning.

### Stage 5 — Governed refresh and monitoring

Add human-configured refresh policies, scheduled re-acquisition, conditional requests, digest comparison, availability events, immutable version lineage, and reviewable change notifications. A detected change creates a new acquisition result. It never mutates prior evidence, triggers intelligence automatically, or declares analytical significance.

## Acceptance criteria

A future Buyer Evidence Acquisition capability conforms to this architecture only when it demonstrates that:

1. every run names one Buyer, purpose, evidence cutoff, coverage profile, supported versions, human owner, and finite bounds;
2. every evidence need is independently classified, prioritized, and assigned a final coverage status;
3. `COMPLETE` is possible only when all required and applicable conditional needs close, without aggregate scoring;
4. missing, rejected, inaccessible, unsupported, conflicted, and not-applicable states remain distinct and inspectable;
5. source authority, authenticity, freshness, scope, relevance, and completeness remain separate dimensions;
6. collection order prefers authoritative identity and current organizational records without treating order or source tier as conflict resolution;
7. every accepted artifact retains publisher attribution, original and canonical location, retrieval context, language, dates as stated, format, content identity, and scope;
8. no URL, publisher, date, mandate, priority, structure, version, locator, or metadata value is invented or silently repaired;
9. every source, document, citation, extract, Buyer, opportunity, scope, and version reference closes under a supported contract;
10. exact duplicates preserve every meaningful occurrence and provenance;
11. conflicts, amendments, supersession, changed pages, disappeared pages, and language variants preserve immutable history;
12. invalid, malformed, unsafe, unsupported, or unclosed material cannot enter the closed Buyer Evidence set;
13. partial valid evidence remains available while every omitted or failed portion remains explicit;
14. stopping conditions are finite, deterministic, recorded, and cannot be confused with proof that all public information was found;
15. identical captured representations and declared inputs produce deterministically equivalent evidence records, ordering, coverage, and completion state;
16. diagnostics and the completion manifest can reproduce why every item entered or failed to enter the corpus;
17. human overrides are attributable and cannot bypass evidence validity or relabel partial coverage as complete;
18. external content cannot alter acquisition instructions, execute active content, or leak credentials;
19. acquisition produces no fact, canonical resolution, interpretation, summary, assumption, hypothesis, management question, recommendation, score, rank, prediction, strategy, brief, or Human Decision;
20. no path writes directly to Canonical Buyer, Buyer Intelligence, Buyer Brief, Decision Workspace, or Human Decision records;
21. downstream processing occurs only through explicit acceptance of a closed evidence set and never as an automatic side effect of acquisition;
22. historical acquisition results remain replayable at their original evidence cutoff; and
23. validation evidence distinguishes deterministic local tests from live external acquisition checks.

## Rationale

### Govern corpus construction separately from transport

Retrieval explains how a resource is obtained safely. Acquisition also decides which evidence needs exist, what order to pursue them in, when coverage is sufficient, and how a corpus closes. Keeping the concepts separate allows manual and future automated mechanisms to obey one evidence policy.

### Define completeness against a profile

The public record has no provable end. A declared, versioned coverage profile makes completion reviewable without claiming omniscience. Item-level statuses preserve the exact gaps hidden by a percentage or composite score.

### Acquire identity and authority first

Later documents are useful only when their publisher, Buyer relationship, and scope can be established. Closing identity early prevents a large collection of unattributable material from appearing complete.

### Use priorities only for work order

Authority-first collection reduces effort and improves provenance, but source order cannot decide truth. Conflicts remain available for the canonical layer rather than disappearing through acquisition policy.

### Preserve rejected material in diagnostics

Excluding invalid material from Buyer Evidence protects authority. Preserving its attempt and failure record explains corpus gaps, prevents repeated blind work, and supports review without granting the material evidentiary status.

### Separate acquisition gaps from analytical unknowns

An acquisition gap states what the collection process did not close. Buyer Intelligence determines whether that gap prevents a fact or interpretation and expresses any analytical Unknown under its own contract. This prevents operations from becoming intelligence.

### Stop deterministically

Bounded completion protects resources and makes partial results honest. Continuing until the system “knows enough” would require analytical judgment that acquisition does not possess.

### Preserve exact representations and immutable history

Public sources change. Bytes or equivalent captured content, digests, dates, locations, and version lineage allow later reviewers to reconstruct what supported an evidence set at its cutoff without rewriting history.

### Keep humans accountable for scope

People may know that a particular department page or statute matters. They can direct acquisition and accept partial coverage, while contract validation prevents convenience from manufacturing evidence.

## Doctrine compliance

This architecture strengthens Buyer Intelligence by establishing a trustworthy evidence entrance. It reduces locating, verification, provenance, and corpus-coverage effort while preserving evidence before inference, canonical authority, immutable transitions, explicit gaps, deterministic processing, scoped fail-closed behavior, and sovereign human judgment.

It introduces no implementation, retrieval, crawling, search, web access, AI, prompt, schema, persistence, API, migration, pipeline integration, Canonical Buyer mutation, Buyer Intelligence execution, Buyer Brief generation, recommendation, scoring, ranking, prediction, or decision. Repository doctrine remains unchanged.
