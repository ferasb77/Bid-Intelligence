# Understanding Profile Architecture

## Document metadata

| Field | Value |
|---|---|
| Document | `UNDERSTANDING_PROFILE_ARCHITECTURE.md` |
| Title | Understanding Profile Architecture |
| Authority Level | Level 3 — Opportunity Intelligence Presentation Architecture |
| Version | 1.0.0 |
| Status | Proposed |
| Purpose | Define deterministic professional-perspective projections over Executive Opportunity Understanding without creating or changing intelligence. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md), [`AGENT.md`](AGENT.md), [`GOVERNANCE.md`](GOVERNANCE.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), [`docs/architecture/DECISION_DOCTRINE.md`](docs/architecture/DECISION_DOCTRINE.md), and [`EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md`](EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md) |
| Governed Documents | Future Understanding Profile contracts, profile registries, deterministic profile projectors, validators, compatibility adapters, and profile-consuming view specifications |
| Related Documents | [`OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md`](OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md), [`EXECUTIVE_OPPORTUNITY_BRIEF_ARCHITECTURE.md`](EXECUTIVE_OPPORTUNITY_BRIEF_ARCHITECTURE.md), [`BUYER_INTELLIGENCE_ARCHITECTURE.md`](BUYER_INTELLIGENCE_ARCHITECTURE.md), [`BUYER_BRIEF_ARCHITECTURE.md`](BUYER_BRIEF_ARCHITECTURE.md), [`BID_WORKSPACE_ARCHITECTURE.md`](BID_WORKSPACE_ARCHITECTURE.md), [`DECISION_WORKSPACE_ARCHITECTURE.md`](DECISION_WORKSPACE_ARCHITECTURE.md), and [`STAGE_D_ARCHITECTURAL_REVIEW.md`](STAGE_D_ARCHITECTURAL_REVIEW.md) |

## 1. Purpose

An Understanding Profile is a deterministic projection of one immutable Executive Opportunity Understanding for a defined professional perspective.

Profiles exist because people participating in the same pursuit navigate the opportunity through different responsibilities. Executive Leadership needs a rapid whole-opportunity orientation. Bid Management coordinates deadlines, dependencies, and decisions. Commercial and Legal reviewers inspect different governed obligations. Domain specialists need direct access to the work and evidence relevant to their expertise.

These perspectives must not produce different intelligence. Every participant must remain anchored to the same authoritative facts, computed facts, observations, interpretations, alternatives, assumptions, conflicts, unknowns, questions, limitations, and evidence relationships.

Profiles solve a navigation and organization problem. They may place the same governed object in a different section, expose it inline rather than through detail navigation, or order it according to an explicit professional workflow. They do not change what the object means or how much authority it has.

An Understanding Profile is therefore a projection rather than intelligence because it:

- consumes an already validated Executive Opportunity Understanding;
- creates no analytical statement;
- introduces no evidence;
- performs no inference or deterministic domain computation;
- retains upstream object identities and wording;
- changes only placement, visibility mode, grouping, and navigation;
- is reproducible from explicit rules.

Profiles strengthen Opportunity Intelligence by reducing the burden of finding relevant governed material while preserving one shared account of the opportunity.

## 2. Architectural position

```text
Validated Opportunity Intelligence
                ↓
Executive Opportunity Understanding
                ↓
Understanding Profile Projector
                ↓
Profile Projections
                ↓
Briefs, Workspaces, Dashboards, APIs and Other Renderers
```

The projector never reads raw procurement documents and never invokes an analyst or model. It accepts one complete, immutable Executive Opportunity Understanding and one supported profile definition. It returns one immutable projection plus a complete coverage record.

The source understanding remains the sole semantic input for every profile. Profile consumers must not route around it to form role-specific conclusions from raw evidence.

## 3. Authority boundary

Understanding Profiles have **presentation-organization authority only**.

Profiles may:

- reference objects from Executive Opportunity Understanding;
- group objects by governed semantic category;
- assign objects to profile-specific sections;
- change deterministic section and item order;
- choose whether an object is displayed inline or reached through the complete detail register;
- add non-semantic navigation labels from a controlled profile definition;
- expose role-relevant evidence links already present in the understanding;
- preserve a complete, profile-independent route to every object.

Profiles cannot:

- create or modify facts;
- create computations, observations, interpretations, hypotheses, assumptions, unknowns, conflicts, considerations, questions, limitations, recommendations, or decisions;
- paraphrase, summarize, merge, split, or truncate governed statements;
- change evidence support, confidence, support status, scope, precision, conflict state, or authority class;
- resolve competing interpretations or select one side of a conflict;
- hide conflicts, unknowns, assumptions, alternatives, or limitations;
- rank importance or assign priority, urgency, materiality, severity, relevance scores, or composite scores;
- recommend actions or answers;
- infer that an object matters more because it appears earlier or inline;
- create role-specific intelligence;
- mutate Executive Opportunity Understanding.

Profiles own only their definition identity, deterministic projection identity, organization rules, and coverage record. All substantive content remains owned by its upstream domain.

## 4. Canonical profile model

The architecture separates three concepts:

1. **Profile Definition** — a versioned declarative set of permitted semantic selectors and ordering rules.
2. **Profile Projection** — the immutable result of applying one definition to one Executive Opportunity Understanding.
3. **Profile Set** — all required projections generated from the same understanding, including the Complete profile and a cross-profile coverage matrix.

### 4.1 Profile Definition

A Profile Definition contains:

| Field | Meaning |
|---|---|
| `profile_definition_id` | Stable controlled profile identity |
| `profile_version` | Exact semantic version of the definition |
| `profile_kind` | Controlled professional-perspective kind |
| `display_name` | Controlled human-readable label |
| `purpose` | Non-directive description of the navigation need |
| `accepted_understanding_versions` | Explicit supported Executive Opportunity Understanding versions |
| `section_definitions` | Fixed section keys, labels, and ordinals |
| `semantic_selectors` | Controlled rules mapping upstream object classes, semantic types, and scopes to sections |
| `visibility_rules` | Rules selecting `INLINE` or `DETAIL_REFERENCE` presentation mode |
| `ordering_rules` | Deterministic section and item keys |
| `mandatory_uncertainty_sections` | Conflict, unknown, assumption, alternative, question, and limitation sections that cannot be disabled |

Profile definitions contain no source content, free-form filtering expressions, learned weights, audience preferences, or user-specific instructions. Definitions are reviewed architecture artifacts, not runtime prompts.

### 4.2 Profile Projection

A Profile Projection contains:

| Field | Meaning |
|---|---|
| `projection_id` | Stable digest-derived identity |
| `profile_definition_id` | Exact definition used |
| `profile_version` | Exact definition version |
| `understanding_id` | Exact source understanding identity |
| `understanding_contract_version` | Exact source contract version |
| `source_digest` | Digest of the immutable source understanding |
| `sections` | Ordered profile sections containing upstream object references |
| `uncertainty_index` | Mandatory references to all governed uncertainty objects |
| `complete_register_reference` | Profile-independent route to the complete understanding detail register |
| `coverage_map` | One profile disposition for every admitted source object |
| `validation_record` | Reference, completeness, determinism, and policy validation results |

Every section entry is a reference to an existing Executive Opportunity Understanding object. It retains the exact object ID, authority class, semantic type, owner domain, support status, confidence where applicable, evidence-support IDs, and detail pointer.

### 4.3 Profile Set

A Profile Set binds multiple profile projections to one Executive Opportunity Understanding. It contains:

- one mandatory Complete profile;
- zero or more professional-perspective profiles;
- a sorted profile registry snapshot;
- a cross-profile coverage matrix;
- set-level completeness validation;
- the source understanding identity and digest.

Profiles from different source-understanding identities or digests cannot enter the same Profile Set.

## 5. Canonical profile kinds

Version 1 defines profiles by professional responsibility rather than named individuals, seniority assumptions, or organization-specific job titles.

### 5.1 Complete

`COMPLETE`

The canonical non-selective projection. It exposes every admitted Executive Opportunity Understanding object in the source organization order and preserves all detail-register navigation. It is generated for every Profile Set and serves as the completeness reference.

The Complete profile is not a preferred or ranked view. It is the profile-independent assurance that no object exists only inside a specialized perspective.

### 5.2 Executive Leadership

`EXECUTIVE_LEADERSHIP`

Organizes opportunity identity, requested work, documented evaluation and success structure, timeline, delivery and commercial shape, measured characteristics, analyst findings, complete uncertainty, and management deliberation.

It cannot convert management questions into recommended answers or reduce uncertainty to a decision signal.

### 5.3 Pursuit Coordination

`PURSUIT_COORDINATION`

Serves Bid Managers and equivalent pursuit coordinators. Organizes scope, requirements, evaluation structure, submission pathways, artifacts, milestones, dependencies, conflicts, unknowns, management questions, and coverage navigation.

It does not assign owners, set priorities, certify readiness, or decide whether to pursue.

### 5.4 Response Management

`RESPONSE_MANAGEMENT`

Serves Proposal Managers and equivalent response leads. Organizes evaluation hierarchy, response artifacts, forms, formats, channels, envelopes, evidence requests, deadlines, workstreams, and unresolved submission states.

It does not write proposal content, construct strategy, rank evaluation criteria, or certify compliance.

### 5.5 Commercial Review

`COMMERCIAL_REVIEW`

Organizes verified monetary observations, pricing mechanics, payment provisions, term, options, demand commitments, commercial clauses, conditions, relevant deliverables, commercial unknowns, conflicts, assumptions, and questions.

It does not characterize terms as acceptable, market-standard, favorable, or safe, and does not recommend pricing.

### 5.6 Legal Review

`LEGAL_REVIEW`

Organizes verified contractual clauses, governing terms, liability, indemnity, insurance, confidentiality, intellectual property, termination, dispute, compliance, and associated unknowns and conflicts.

It does not provide legal advice, assign legal severity, infer consequences absent from validated upstream interpretation, or accept contractual terms.

### 5.7 People and Organization

`PEOPLE_AND_ORGANIZATION`

Organizes requirements and deliverables concerning organizational development, leadership, workforce, change, talent, facilitation, personnel qualifications, accessibility, language, and related delivery conditions.

It does not assert bidder capability or interpret buyer organizational intent beyond validated Opportunity Intelligence.

### 5.8 Learning and Development

`LEARNING_AND_DEVELOPMENT`

Organizes learning-program, curriculum, assessment, facilitation, delivery-mode, participant, accessibility, language, evaluation, and qualification objects already present in the understanding.

It does not design learning solutions or infer unstated participant needs.

### 5.9 Delivery Operations

`DELIVERY_OPERATIONS`

Organizes deliverables, frequencies, volumes, locations, timing, resource conditions, security, technology, dependencies, acceptance structures, and operational unknowns.

It does not create a delivery plan, resource estimate, or capability conclusion.

### 5.10 Subject Matter Review

`SUBJECT_MATTER_REVIEW`

A governed domain-specialist profile parameterized by a controlled semantic-domain code. It organizes only objects whose upstream semantic types or scopes match that registered domain, together with all related evidence, conflicts, assumptions, alternatives, unknowns, questions, and limitations.

Free-form domain filters are prohibited. New domain codes require a versioned registry update and validation fixtures. Technical SMEs use this profile when their specialty is represented by a supported code.

## 6. Projection rules

Projection is a pure deterministic transformation.

### 6.1 Admission

The projector first validates the entire Executive Opportunity Understanding. It accepts only a supported contract version with valid identity, digest, detail-register, and coverage-ledger invariants.

The projector cannot rehabilitate an invalid understanding. An invalid source fails before any profile is emitted.

### 6.2 Semantic selection

Profile selectors may inspect only controlled fields already present in the understanding:

- authority class;
- governed object class;
- governed semantic type;
- governed scope;
- existing section assignment;
- existing relationship identifiers;
- canonical resolution status;
- conflict or unknown relationship;
- source contract version.

Selectors cannot inspect prose for keywords, measure statement length, count repeated mentions as relevance, infer meaning from filenames, or use an embedding, model, learned classifier, or hidden score.

### 6.3 Reorganization

One source object may appear in multiple profile sections when explicit rules assign it to each section. Every occurrence references the same object ID and detail pointer. Reorganization never creates a copied fact with a new identity.

### 6.4 Visibility modes

Each source object receives one profile-specific visibility mode:

- `INLINE` — referenced directly in a profile section;
- `DETAIL_REFERENCE` — available through the profile's complete-register navigation and coverage map;
- `NOT_APPLICABLE_TO_PROFILE_SECTION` — has no specialized inline section under this definition but remains available through the complete register.

No visibility mode removes an object from the source understanding or complete access path.

### 6.5 Uncertainty propagation

Every profile includes an `uncertainty_index` containing references to all source:

- unresolved conflicts;
- unknowns;
- assumptions;
- competing interpretations;
- evidence gaps;
- limitations;
- unanswered management questions.

When an inline fact, finding, or computation is affected by one of these objects, the profile must include the relationship beside the reference. A profile cannot show a value without its governing conflict, assumption, or limitation.

### 6.6 Ordering

Profile order uses:

1. fixed section ordinal;
2. controlled semantic-type ordinal;
3. governed scope key;
4. source understanding order where that order is itself authoritative;
5. stable upstream object ID as the final tie-breaker.

Ordering expresses workflow and navigation. It never means importance, urgency, risk, quality, or recommended action.

### 6.7 Prohibited projection behavior

Projection must never:

- invent an object or relationship;
- summarize or paraphrase content;
- truncate a collection;
- drop an item to satisfy a page, token, or context limit;
- select a preferred hypothesis;
- convert uncertainty into a resolved value;
- exclude an item because it appears irrelevant according to a model or user preference;
- change an upstream identifier;
- alter evidence ownership or authority;
- turn required proof into evidence of bidder possession;
- use profile order as a recommendation.

## 7. Coverage guarantees

Coverage is enforced at source, projection, and set level.

### 7.1 Source completeness

The Executive Opportunity Understanding coverage ledger remains authoritative for which upstream Opportunity Intelligence objects were admitted. Profiles cannot expand or contract that source set.

### 7.2 Per-profile coverage

Every profile coverage map contains exactly one disposition for every object in the understanding detail register. Therefore every professional profile retains a navigable path to every governed object, even when the object is not inline in a specialized section.

No object can disappear from a profile's governed access path.

### 7.3 Set-union equality

For a Profile Set:

```text
union(profile.covered_object_ids for profile in profile_set)
    == executive_opportunity_understanding.detail_object_ids
```

Set-union equality is necessary but not sufficient. The Complete profile must independently cover the entire source set, and every specialized profile must retain a complete-register reference.

### 7.4 No profile-exclusive intelligence

An object referenced inline by any specialized profile must already exist in Executive Opportunity Understanding and the Complete profile. It must be reachable from every other profile through that profile's complete-register reference and coverage map.

Nothing may appear only in one profile. Profiles can differ in inline organization, but never in the governed information available to their consumers.

### 7.5 Coverage matrix

The cross-profile coverage matrix contains one row per source object and one column per profile. Each cell records the visibility mode and section assignments for that profile.

Validation requires:

- every source object has a row;
- every registered profile has a column;
- the Complete column contains no `NOT_APPLICABLE_TO_PROFILE_SECTION` disposition;
- every specialized profile has exactly one visibility disposition per source object;
- no profile references an object absent from the source understanding;
- every uncertainty object appears in every profile's uncertainty index;
- duplicate inline appearances retain one source identity.

Coverage is a structural property. It is not a score and does not measure usefulness, quality, priority, or compliance.

## 8. Determinism and identity

Identical source understanding, profile definition, registry version, and projector contract produce identical semantic output.

`projection_id` is derived from:

- projector contract version;
- profile definition ID and version;
- source understanding ID and digest;
- controlled parameter values, if the profile permits them.

It does not depend on:

- current user identity;
- timestamps;
- process state;
- input collection insertion order;
- model output;
- clicks or navigation history;
- document length;
- page or token limits;
- display viewport;
- mutable preferences.

Canonical serialization fixes map-key ordering, section order, reference order, null representation, enum representation, and duplicate rejection. Operational rendering metadata remains outside semantic equality.

Profiles use no AI preference, summarization, ranking, importance score, relevance score, or probabilistic selection.

## 9. Validation and failure behavior

Profile construction fails closed when:

- the source understanding is invalid or unsupported;
- the profile definition or registry version is unsupported;
- a selector refers to an unknown semantic type, scope, section, or authority class;
- a source object has no profile disposition;
- a reference does not resolve exactly once;
- an object appears that is absent from the source understanding;
- source and projection digests disagree;
- an uncertainty object is missing from the profile uncertainty index;
- a conflicted object is shown without its conflict relationship;
- an assumption or limitation relationship is suppressed;
- the Complete profile does not cover every object;
- set-union equality fails;
- a profile-exclusive object is detected;
- ordering is nondeterministic;
- prohibited summary, recommendation, ranking, scoring, or decision content is present.

The projector never responds by dropping the failing item, selecting a default interpretation, weakening validation, or returning a projection labelled complete.

A profile failure does not mutate or invalidate Executive Opportunity Understanding. Other already validated profile projections remain valid if their identity and source digest still match. A Profile Set claiming completeness is not emitted until every profile required by that set validates.

Missing domain content is represented by the source understanding's unknowns and limitations. It is not filled by the profile.

## 10. Versioning and compatibility

The following versions are independent:

- profile architecture version;
- profile-definition version;
- profile-registry version;
- projector contract version;
- accepted Executive Opportunity Understanding version.

Semantic versioning applies:

- **PATCH** clarifies labels or validation without changing semantic selection or meaning;
- **MINOR** adds a compatible profile, section, controlled semantic selector, or optional metadata field;
- **MAJOR** changes authority, required fields, visibility semantics, coverage rules, or the meaning of an existing selector.

Consumers declare supported major versions and reject incompatible inputs. Historical profile projections remain bound to their original source digest and profile definition.

A compatibility adapter must be deterministic, declare source and target versions, preserve all references and coverage, and fail if conversion would suppress content or alter meaning. An adapter cannot rerun Opportunity Intelligence or create a new understanding.

Adding a profile never changes Executive Opportunity Understanding. It adds a new projection definition over the existing contract.

## 11. Consumer relationships and extension strategy

### 11.1 Proposal Compliance

Proposal Compliance may use a profile for navigation, but compliance authority continues to compare proposal responses with authoritative requirements and submission rules. A profile cannot become evidence of compliance or replace the source requirement.

### 11.2 Bid Workspace

The Bid Workspace may let a user switch profiles while retaining one source-understanding identity. It must make the active profile visible and provide access to the Complete profile. Switching views cannot create or discard semantic state.

### 11.3 Executive dashboards

Dashboards may render the Executive Leadership profile, expose detail, and link evidence. Widgets cannot compute hidden scores or omit mandatory uncertainty.

### 11.4 Mobile briefings

Mobile views may paginate or collapse profile sections, but every item remains available through deterministic navigation. Screen constraints cannot change profile coverage.

### 11.5 API consumers

APIs expose versioned Profile Projections and paginated detail references. Pagination is transport behavior and must preserve complete retrieval, stable order, source identity, and coverage totals.

### 11.6 Future AI assistants

A future assistant may consume a validated profile as bounded context. The profile does not authorize the assistant to create facts, suppress uncertainty, answer management questions, or make recommendations. Any reasoning remains governed by a separate analyst or assistant contract and cannot write back into the profile or Executive Opportunity Understanding.

### 11.7 New professional perspectives

New profiles are added through the registry. Each proposal must state:

- the professional navigation problem;
- why an existing profile is insufficient;
- exact semantic selectors;
- uncertainty propagation;
- deterministic ordering;
- coverage proof;
- compatibility impact;
- tests for prohibited authority expansion.

Profiles must not proliferate merely to change labels or create personalized intelligence.

## 12. Doctrine compliance

### Evidence before inference

Profiles reference governed understanding objects and their existing evidence relationships. They cannot create post-hoc citations or treat role relevance as evidence.

### Human judgment

Profiles organize information for deliberation. They do not answer management questions, direct action, select strategy, recommend Bid / No Bid, accept commercial terms, or authorize submission.

### Determinism

Admission, selection, grouping, visibility, ordering, identity, and coverage use explicit versioned rules. Identical inputs produce identical projections.

### Immutable contracts

Executive Opportunity Understanding remains unchanged. Each profile is a new immutable value bound to an exact source identity and digest.

### Separation of concerns

Opportunity domains own facts. Opportunity Intelligence owns analysis. Executive Opportunity Understanding owns governed executive organization. Profiles own perspective-specific navigation. Briefs, dashboards, workspaces, and APIs own presentation. Humans own decisions.

### Fail-closed validation

Invalid source contracts, unsupported selectors, missing references, incomplete uncertainty, coverage gaps, and prohibited conclusions prevent projection. The projector does not silently recover by deleting information.

### Transparency

Every profile exposes its definition, source understanding, organization rules, coverage map, uncertainty index, and complete-register navigation. A professional can inspect why an object appears inline and verify that non-inline objects remain available.

## 13. Acceptance criteria for future implementation

A future implementation conforms only if it proves that:

1. identical inputs and profile definitions produce identical semantic output and projection IDs;
2. source Executive Opportunity Understanding is never mutated;
3. every projection references only source-understanding objects;
4. no profile creates intelligence, evidence, summaries, recommendations, rankings, scores, or decisions;
5. every source object receives exactly one visibility disposition in every profile;
6. every profile retains access to the complete detail register;
7. the Complete profile covers every source object inline or by direct detail reference;
8. the union of profile-covered IDs equals the source detail-register IDs;
9. no object is exclusive to one professional profile;
10. every conflict, unknown, assumption, alternative, evidence gap, limitation, and management question appears in every profile uncertainty index;
11. conflicted or qualified objects retain their governing uncertainty relationships;
12. filtering uses only controlled semantic fields and never prose, AI, or hidden scores;
13. ordering is deterministic and cannot be interpreted as priority;
14. unsupported source or profile versions fail closed;
15. missing references, duplicate identities, digest mismatches, and coverage gaps fail closed;
16. role-specific views can change without changing Executive Opportunity Understanding;
17. rendering and transport constraints never change semantic coverage;
18. future assistants cannot mutate profiles or inherit decision authority from them.

## 14. Architecture definition

Understanding Profiles are deterministic, immutable professional-perspective projections over one Executive Opportunity Understanding.

They change navigation, grouping, inline placement, and order. They do not change intelligence, evidence, authority, uncertainty, or meaning.

Every Profile Set includes a Complete profile, every profile retains access to the complete governed detail register, and every uncertainty object remains visible. The profile union equals the source understanding, and no object can exist exclusively inside one professional perspective.

This architecture allows Executive Leadership, pursuit teams, commercial and legal reviewers, domain specialists, operations, future compliance capabilities, workspaces, dashboards, mobile views, APIs, and governed assistants to use the same opportunity understanding without creating different versions of reality.
