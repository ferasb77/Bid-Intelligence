# Executive Opportunity Understanding Architecture

## Document metadata

| Field | Value |
|---|---|
| Document | `EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURE.md` |
| Title | Executive Opportunity Understanding Architecture |
| Authority Level | Level 3 — Opportunity Intelligence Architecture |
| Version | 1.1.0 |
| Status | Approved |
| Purpose | Define the authority, immutable contract, deterministic organization, validation, failure behavior, versioning, and consumer boundaries for Executive Opportunity Understanding. |
| Higher Authority | [`MANIFESTO.md`](MANIFESTO.md), [`AGENT.md`](AGENT.md), [`GOVERNANCE.md`](GOVERNANCE.md), [`ANTI_GOALS.md`](ANTI_GOALS.md), product doctrine, [`docs/architecture/DECISION_DOCTRINE.md`](docs/architecture/DECISION_DOCTRINE.md), [`GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md`](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md), [`OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md`](OPPORTUNITY_INTELLIGENCE_ANALYST_SPECIFICATION.md), and [`STAGE_D_ARCHITECTURAL_REVIEW.md`](STAGE_D_ARCHITECTURAL_REVIEW.md) |
| Governed Documents | Future Executive Opportunity Understanding contracts, validators, deterministic assemblers, compatibility adapters, and consumer specifications |
| Related Documents | [`DECISION_INTELLIGENCE_ARCHITECTURE_PHASE1.md`](DECISION_INTELLIGENCE_ARCHITECTURE_PHASE1.md), [`DECISION_ANALYST_ARCHITECTURE_PHASE2.md`](DECISION_ANALYST_ARCHITECTURE_PHASE2.md), [`DECISION_WORKSPACE_ARCHITECTURE.md`](DECISION_WORKSPACE_ARCHITECTURE.md), [`EXECUTIVE_OPPORTUNITY_BRIEF_ARCHITECTURE.md`](EXECUTIVE_OPPORTUNITY_BRIEF_ARCHITECTURE.md), [`BID_WORKSPACE_ARCHITECTURE.md`](BID_WORKSPACE_ARCHITECTURE.md), [`BID_INTELLIGENCE_BRIEFING_PACK.md`](BID_INTELLIGENCE_BRIEFING_PACK.md), [`BUYER_INTELLIGENCE_ARCHITECTURE.md`](BUYER_INTELLIGENCE_ARCHITECTURE.md), [`BUYER_BRIEF_ARCHITECTURE.md`](BUYER_BRIEF_ARCHITECTURE.md), and [`EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURAL_VALIDATION.md`](EXECUTIVE_OPPORTUNITY_UNDERSTANDING_ARCHITECTURAL_VALIDATION.md) |

## Summary of amendments

Version 1.1.0 makes the existing reference-based contract an explicit participant in the repository-wide Governed Reference Resolution protocol. It clarifies that:

- Executive Opportunity Understanding owns only its identity, deterministic organization, coverage, and input bindings;
- substantive facts, computations, analysis, evidence, and provenance remain owned by their existing domains;
- the contract's object references resolve under the immutable context identified by its envelope;
- presentation and operational consumers obtain exact semantic values and relationships through Governed Reference Resolution;
- optional copied labels or display values are navigation conveniences and never replace owner-resolved semantics;
- missing, stale, incompatible, or incomplete resolution fails closed.

The amendment adds no semantic store, intelligence, presentation logic, or resolver implementation to Executive Opportunity Understanding.

## Rationale

The original architecture correctly preserved single ownership by organizing upstream objects through stable references. It did not explicitly state the repository protocol by which downstream consumers obtain the exact values and relationships behind those references. [`GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md`](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md) now defines that common protocol.

Binding Executive Opportunity Understanding to that protocol removes the ambiguity without duplicating Canonical Opportunity, Opportunity Intelligence, evidence, or provenance. The understanding remains the sole canonical organizer for its consumers; the owning domains remain the sole authorities for referenced semantic content.

## 1. Purpose

Executive Opportunity Understanding is the governed organization of validated Opportunity Intelligence into the smallest complete mental model an experienced executive needs to understand an opportunity.

It answers:

- What is the opportunity?
- What is the buyer asking for?
- How will the response and resulting work be evaluated?
- What must be submitted, when, and through which pathways?
- What delivery and commercial structure is documented?
- What has been computed from the authoritative record?
- What has an analyst observed or interpreted?
- What remains conflicted, assumed, ambiguous, unavailable, or unknown?
- Which questions require accountable management judgment?

It exists because exhaustive procurement extraction and executive comprehension are different needs. The governed opportunity record must remain complete, while an executive needs a stable way to construct an accurate mental model without reading facts in source-document order or relying on generated narrative.

Executive Opportunity Understanding reduces the burden of navigating, relating, and checking validated opportunity information. It does not reduce that burden by discarding evidence or hiding uncertainty. It provides an executive index over a complete governed detail register, with explicit coverage for every admitted input.

Executive Opportunity Understanding is not:

- an analyst;
- a source of new intelligence;
- a summary generated from raw documents;
- a recommendation or decision;
- a Bid / No Bid assessment;
- a score, ranking, or prioritization;
- a proposal outline or proposal-writing service;
- an Executive Opportunity Brief;
- a rendering format;
- a replacement for the canonical opportunity, normalized facts, provenance stores, or Opportunity Intelligence;
- a mechanism for resolving conflicts, filling gaps, or converting assumptions into facts.

## 2. Architectural position

```text
Authoritative Opportunity Domains
              ↓
Validated Opportunity Intelligence
              ↓
Executive Opportunity Understanding
              ↓
Presentation and Operational Consumers
```

The authoritative opportunity domains include Canonical Opportunity, normalized requirements, evaluation hierarchy, submission projection, Contract Hygiene, dates, monetary observations, procurement mechanics, conflicts, and their owning provenance stores.

Opportunity Intelligence consumes those domains under its own contract. It produces deterministic computations and typed analytical statements without changing upstream authority.

Executive Opportunity Understanding consumes only validated Opportunity Intelligence and the authoritative references declared by that analysis. It reorganizes those existing objects. It does not inspect raw documents, run extraction, call a model, or create analytical statements.

The understanding envelope and its governed object references identify the immutable resolution context required by [`GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md`](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md). Governed Reference Resolution verifies and exposes the exact owner-declared semantic content behind those references without transferring ownership to the understanding or its consumers.

Presentation and operational consumers receive the same immutable understanding contract and resolve its references through that bound governed context. A consumer may change layout or expose role-specific navigation, but it cannot reinterpret or mutate the contract or the resolved owner objects.

## 3. Authority boundary

Executive Opportunity Understanding has **organizational authority only**.

It may:

- validate that supplied Opportunity Intelligence is supported and compatible;
- resolve references to already authoritative or already validated objects;
- assign an existing object to one or more deterministic executive sections;
- preserve the original semantic class, authority, confidence, support status, and wording of each object;
- create deterministic structural labels, section keys, ordering keys, and coverage dispositions;
- expose relationships already declared by upstream contracts;
- create navigation from an executive index to complete detail and evidence.

It may not:

- create, rewrite, merge, paraphrase, or reinterpret a fact;
- create a computed fact;
- create an observation, inference, hypothesis, assumption, unknown, conflict, limitation, consideration, or management question;
- select among competing interpretations;
- resolve or suppress an authoritative conflict;
- assign confidence to facts;
- change analytical confidence or support status;
- rank findings or assign importance;
- create a recommendation, score, prediction, or human decision;
- own evidence, facts, intelligence, recommendations, or decisions;
- treat presentation order as analytical priority;
- infer relevance from source position, extraction order, frequency, prose length, or model preference.

Every substantive object retains its owning domain and stable upstream identifier. Executive Opportunity Understanding owns only its contract identity, organization profile, section assignments, deterministic ordering, coverage record, validation record, and input snapshot bindings. It references authoritative facts, computations, analytical statements, evidence relationships, and provenance; it does not own or duplicate their semantic values.

Reference resolution has verification authority only. A successful resolution makes the owning domain's exact immutable semantic representation available to a consumer. It does not create canonical truth, create intelligence, change authority, or authorize the understanding to rewrite the resolved object.

## 4. Inputs

Version 1 accepts one validated Opportunity Intelligence `DecisionAnalysis` and the immutable authoritative opportunity snapshot against which that analysis was validated.

The input boundary requires:

- a supported Opportunity Intelligence analyst ID and version;
- a valid `DecisionAnalysis` contract;
- an analysis input digest bound to the supplied authoritative snapshot;
- stable identifiers for every referenced fact, computation, observation, interpretation, hypothesis, assumption, unknown, conflict, question, and limitation;
- closed evidence references under the owning contracts;
- preserved canonical resolution and conflict state;
- supported versions for every upstream contract represented in the snapshot.

The immutable authoritative snapshot and analysis binding form the bounded resolution context for the understanding. During construction, every admitted upstream reference must resolve exactly under [`GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md`](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md). Construction cannot search outside that context, substitute current state, or accept identity without the semantic and relationship closure required by this contract.

The assembler must not accept a generic narrative, an unvalidated model response, raw extraction output, a rendered brief, or a mixture of records from different opportunity snapshots.

Version 1 accepts one Opportunity Intelligence analysis because Executive Opportunity Understanding belongs to that pillar. Multiple analysts remain separate in the Decision Workspace. A future version may admit additional opportunity-domain analysts only through an explicit compatibility and authority review; it must never merge analyst boundaries implicitly.

## 5. Canonical immutable contract

The canonical contract version identifier is:

`executive-opportunity-understanding/1.0.0`

The contract is immutable in memory and after serialization. Nested collections, mappings, references, and coverage records are immutable. Construction creates a new value and cannot mutate any upstream object.

### 5.1 Contract envelope

The top-level contract contains:

| Field | Meaning |
|---|---|
| `understanding_id` | Stable identity derived from the contract version, opportunity identity, authoritative snapshot digest, and analysis identity |
| `contract_version` | Exact Executive Opportunity Understanding contract version |
| `opportunity_id` | Stable canonical opportunity identity |
| `context_id` | Governed analysis context identity |
| `authoritative_snapshot_digest` | Digest of the immutable authoritative input snapshot |
| `analysis_id` | Exact Opportunity Intelligence analysis identity |
| `analyst_id` | Exact producing analyst identity |
| `analyst_version` | Exact supported analyst version |
| `analysis_input_digest` | Upstream analysis input digest |
| `organization_profile` | Versioned deterministic executive-section profile |
| `executive_index` | Deterministic section index over referenced governed objects |
| `detail_register` | Complete typed register of every admitted object |
| `coverage_ledger` | One disposition for every eligible upstream object |
| `validation_record` | Contract, reference, coverage, and determinism results |

Execution timestamps may be recorded as operational metadata outside semantic identity. They must not affect ordering, equality, or output meaning.

### 5.2 Governed object reference

Every substantive entry is a reference to one upstream object and contains:

- `object_id` — the exact upstream stable identifier;
- `object_class` — the upstream semantic class;
- `owner_domain` — the subsystem that owns the object;
- `source_contract_version` — the governing upstream version;
- `authority_class` — authoritative fact, deterministic computation, analyst observation, interpretation, hypothesis, assumption, unknown, conflict, management question, or limitation;
- `evidence_support_ids` — exact upstream evidence-support references where the source contract permits them;
- `support_status` — copied unchanged where applicable;
- `confidence` — copied unchanged for reasoning only;
- `section_assignments` — deterministic executive section keys;
- `display_order_key` — deterministic structural ordering key;
- `detail_pointer` — reference to the immutable detail-register entry.

The reference may carry an exact display label or value already provided by its owning contract. It cannot generate replacement prose. Evidence content remains in the owning evidence store and is referenced rather than copied as a new authority-bearing object.

Each governed object reference is interpreted together with the contract envelope. The envelope supplies the immutable context identity and snapshot digest; the reference supplies the owning domain, source contract version, object class, stable object ID, relationship identifiers, and organization metadata. Together they constitute the contract-bound identity required for Governed Reference Resolution. An owner-defined object digest is verified when the owning contract provides one.

An optional exact display label or value is a non-authoritative convenience copied unchanged from the owning contract. It may support navigation or compact rendering, but it cannot satisfy resolution when the consumer requires additional semantic properties, evidence relationships, or provenance. It cannot be rewritten, inferred, or treated as a second canonical value.

### 5.3 Detail register

The detail register contains separate immutable collections for:

1. `authoritative_facts`
2. `computed_facts`
3. `analyst_observations`
4. `validated_interpretations`
5. `competing_interpretation_sets`
6. `assumptions`
7. `unknowns`
8. `conflicts`
9. `management_considerations`
10. `management_questions`
11. `limitations`

These collections must never be flattened into a common narrative list.

The detail register is complete as an organizational register, not as a duplicate semantic store. Its entries identify and classify the admitted owner objects. Consumers obtain the exact semantic fields, typed properties, evidence relationships, and provenance navigation required for their governed operation by resolving those entries through the immutable context bound by the envelope.

#### Authoritative facts

References to resolved canonical values and admissible entities from their owning opportunity domains. Conflicted, ambiguous, unverified, malformed, or unparsed values cannot appear as resolved authoritative facts.

#### Computed facts

References to deterministic computations already produced and validated by Opportunity Intelligence. The understanding contract does not recompute them. Formula identity, denominator, unit, input references, and null behavior remain attached through the upstream object.

#### Analyst observations

Evidence-backed descriptive findings emitted by Opportunity Intelligence that do not add a causal or predictive conclusion. Their original statement type and evidence support remain visible.

#### Validated interpretations

Typed Opportunity Intelligence inferences admitted by the analyst contract. Each retains its evidence support, confidence, support status, reasoning gaps, and limitations. The understanding layer cannot rewrite an interpretation into a fact.

#### Competing interpretation sets

Each set identifies the upstream subject and contains every declared alternative hypothesis. Alternatives remain separate and unranked. A set cannot declare a preferred interpretation unless an upstream authoritative process has already eliminated alternatives and changed the source contract accordingly.

#### Assumptions

Explicit assumptions copied from the validated analysis. Assumptions cannot appear inside fact wording, section labels, or unstated display logic.

#### Unknowns

Explicit missing evidence, unresolved information, unavailable information, ambiguity, partial precision, and other unknown states supplied upstream. Each retains its type, affected objects, and evidence-gap references.

#### Conflicts

Every unresolved authoritative conflict referenced by the analysis. The contract retains affected fields, observations, scopes, alternatives, and resolution state. It cannot display one incompatible value as resolved elsewhere in the same understanding.

#### Management considerations

Neutral, non-directive matters already raised by Opportunity Intelligence for human deliberation. They must not contain pursuit direction, commercial acceptance, hidden ranking, or implied management decisions.

#### Management questions

Questions already emitted under the Opportunity Intelligence contract. The understanding layer cannot answer them, rewrite them into directives, or infer a response.

#### Limitations

Input, scope, temporal, evidence, validation, and method limitations. Limitations remain explicit even when a renderer uses a compact presentation.

### 5.4 Coverage ledger

The coverage ledger proves that executive organization did not silently omit eligible upstream content.

It contains exactly one record for every eligible upstream object:

| Field | Meaning |
|---|---|
| `object_id` | Exact upstream object identity |
| `object_class` | Upstream semantic class |
| `disposition` | `EXECUTIVE_INDEX_AND_DETAIL`, `DETAIL_ONLY`, or `INELIGIBLE` |
| `rule_id` | Versioned deterministic rule that produced the disposition |
| `section_keys` | Every executive section containing the reference |
| `detail_pointer` | Exact detail-register destination when admitted |
| `ineligibility_reason` | Controlled reason required only for `INELIGIBLE` |

`DETAIL_ONLY` is not omission. It means the object remains in the complete governed detail register and is reachable from coverage and section navigation, but is not repeated in the compact executive index under the versioned organization profile.

`INELIGIBLE` is permitted only when the upstream contract itself forbids downstream admission, such as invalid provenance, unsupported version, diagnostic-only material, or an entity outside the supplied opportunity scope. The object and controlled reason remain recorded in validation diagnostics. Unsupported or corrupt inputs fail construction rather than becoming `INELIGIBLE` by convenience.

The ledger must satisfy a bijection between eligible upstream IDs and admitted detail-register IDs. Duplicate references may point to one stable object, but meaningful source occurrences remain preserved by the owning provenance contract.

## 6. Executive organization

Executive organization follows the questions required to form an opportunity mental model. It does not follow document order, extraction order, model output order, or prompt structure.

Version 1 defines these section keys in this fixed order:

1. `OPPORTUNITY_IDENTITY`
2. `REQUESTED_WORK`
3. `EVALUATION_AND_SUCCESS_STRUCTURE`
4. `RESPONSE_AND_SUBMISSION_STRUCTURE`
5. `TIMELINE`
6. `DELIVERY_STRUCTURE`
7. `COMMERCIAL_AND_CONTRACT_STRUCTURE`
8. `MEASURED_CHARACTERISTICS`
9. `ANALYST_FINDINGS`
10. `ASSUMPTIONS_AND_ALTERNATIVES`
11. `CONFLICTS_UNKNOWNS_AND_EVIDENCE_GAPS`
12. `MANAGEMENT_DELIBERATION`
13. `LIMITATIONS_AND_COVERAGE`

### 6.1 Opportunity identity

Resolved buyer, title, solicitation identity, opportunity type, procurement mechanics, and contract-term facts. Any unresolved headline field appears in the conflict or unknown collection and must not be replaced by a selected value.

### 6.2 Requested work

Authoritative scope, service categories, workstreams, deliverables, and stated delivery expectations. It describes demanded capabilities without asserting that the bidder possesses them.

### 6.3 Evaluation and success structure

Authoritative gates, criteria, hierarchy, weights, thresholds, stages, and compatible deterministic measures. “Success” means the documented evaluation structure; it does not mean predicted award success.

### 6.4 Response and submission structure

Required artifacts, forms, evidence, certifications, formats, channels, envelopes, signatures, and unresolved submission states. Required proof is not proof of bidder possession or completion.

### 6.5 Timeline

Valid resolved milestones and deterministic intervals. Partial dates remain partial, malformed dates remain inadmissible as headline dates, and conflicting dates remain conflicts. No timezone or precision may be invented.

### 6.6 Delivery structure

Verified deliverables, frequencies, conditions, dependencies, acceptance structures, and documented demand patterns. No operational capability judgment is permitted.

### 6.7 Commercial and contract structure

Verified commercial clauses, monetary observations, term observations, procurement mechanics, and bounded clause interpretations already validated upstream. It does not characterize terms as acceptable, safe, standard, or favorable.

### 6.8 Measured characteristics

Deterministic computed facts from Opportunity Intelligence, including their units, denominators, formulas, and contributing evidence. No composite score or qualitative ranking is introduced.

### 6.9 Analyst findings

Validated observations and interpretations grouped by their original semantic type. Facts and computations are not repeated here as analyst conclusions.

### 6.10 Assumptions and alternatives

Explicit assumptions and complete competing-interpretation sets. Alternatives remain unranked and no preferred narrative is produced.

### 6.11 Conflicts, unknowns, and evidence gaps

Separate subsections preserve authoritative conflicts, missing evidence, unavailable information, ambiguity, and partial knowledge. They cannot be compressed into a generic caveat.

### 6.12 Management deliberation

Neutral considerations and unanswered management questions. This section cannot contain decisions, recommended answers, approval states, or action rankings.

### 6.13 Limitations and coverage

Analysis limitations, source-scope limitations, contract-version information, coverage totals, detail-register navigation, and evidence-traceability entry points.

## 7. Deterministic inclusion and ordering

The same authoritative snapshot, validated analysis, contract version, and organization profile must produce byte-equivalent semantic output after canonical serialization.

### 7.1 Inclusion rules

Inclusion depends only on:

- upstream contract validity;
- opportunity and context identity;
- authority class;
- governed semantic type;
- canonical resolution status;
- evidence and reference closure;
- versioned section-assignment rules.

Inclusion must never depend on:

- an LLM or model preference;
- narrative fluency;
- hidden relevance or importance ranking;
- an aggregate score;
- source frequency;
- document position;
- extraction or prompt order;
- response length;
- token limits or context-window pressure;
- arbitrary collection slicing;
- a renderer’s available page count.

Every eligible object enters the detail register. The executive index contains objects selected by explicit semantic rules, never by estimated importance. For example, resolved headline identity enters `OPPORTUNITY_IDENTITY`; all unresolved conflicts enter `CONFLICTS_UNKNOWNS_AND_EVIDENCE_GAPS`; all management questions enter `MANAGEMENT_DELIBERATION`; and all limitations enter `LIMITATIONS_AND_COVERAGE`.

### 7.2 Ordering rules

Ordering uses:

1. fixed section ordinal from the organization profile;
2. controlled semantic-type ordinal within the section;
3. governed scope key;
4. stable upstream object ID.

Dates may additionally use normalized temporal value only when full precision and compatibility are established. Evaluation criteria may use authoritative hierarchy position. Submission artifacts may use authoritative envelope or pathway position. These domain-specific keys must be explicit and versioned; missing values fall back to stable ID rather than guessed order.

Display order communicates structure, not priority.

### 7.3 No summarization or truncation

The assembler does not summarize prose, shorten evidence, merge semantically similar statements, or truncate collections. Compactness comes from references, non-duplication, deterministic organization, and separation between the executive index and complete detail register.

A renderer may collapse detail interactively or move it to an appendix, but the contract remains complete and the renderer must expose coverage and access to that detail.

## 8. Validation

Construction fails unless all of the following hold:

- top-level and nested contract fields match the supported schema exactly;
- the Opportunity Intelligence analyst ID and version are supported;
- the `DecisionAnalysis` is valid under its owning contract;
- opportunity ID, context ID, snapshot digest, and analysis input digest agree;
- all object IDs are unique within their owning namespace;
- every substantive reference resolves to exactly one upstream object;
- every evidence reference closes against the owning evidence registry;
- authoritative facts reflect valid canonical resolution states;
- reasoning confidence appears only on reasoning objects;
- assumptions, alternatives, unknowns, conflicts, questions, and limitations remain in their proper collections;
- every unresolved conflict referenced by the analysis is present;
- no competing interpretation is missing from its declared set;
- no prohibited recommendation, decision, score, ranking, or unsupported capability assertion exists;
- every eligible upstream object has exactly one coverage-ledger disposition;
- the coverage ledger and detail register are bijective over admitted objects;
- section assignments comply with the exact organization profile;
- canonical ordering and stable identity reproduce deterministically.
- every admitted governed object reference resolves under the exact immutable context bound by the envelope;
- every resolved object supplies the semantic fields and relationship closure required by this contract without consumer inference.

Validation must operate at the understanding boundary even when upstream validation already occurred. Replay, imports, and future consumers may enter without traversing the newest upstream path.

## 9. Failure behavior

Executive Opportunity Understanding fails closed.

No contract is emitted when:

- an input contract or version is unsupported;
- identity or digest bindings disagree;
- a reference is missing, ambiguous, or owned by another entity;
- eligible content lacks a coverage disposition;
- a collection is incomplete;
- a conflict has been flattened or a competing interpretation suppressed;
- a fact has acquired analytical confidence;
- an interpretation has been presented as authoritative fact;
- ordering or identity is nondeterministic;
- prohibited recommendation, scoring, ranking, prediction, or decision content is present.
- a governed reference is missing, stale, ambiguous, owned by a different domain, bound to an incompatible version or digest, or incomplete for required semantic or provenance closure.

Missing real-world information is not a construction failure when it is validly represented as an upstream unknown, evidence gap, conflict, or limitation. Missing required contract structure or reference closure is a construction failure.

Failure records must identify the contract version, input identities, validation code, and affected object IDs without inventing a replacement value. The assembler must never repair prose, drop an object, choose an alternative, infer a missing relationship, or fall back to an unvalidated narrative.

A failure in Executive Opportunity Understanding does not mutate or invalidate authoritative evidence or the validated Opportunity Intelligence analysis. Those upstream records retain their own status and authority.

## 10. Identity and equality

`understanding_id` is derived deterministically from:

- exact Executive Opportunity Understanding contract version;
- organization-profile version;
- opportunity ID;
- authoritative snapshot digest;
- analysis ID;
- analysis input digest.

It does not depend on timestamps, process IDs, random values, collection insertion order, rendering format, or display pagination.

Two contracts are semantically equal when their canonical serialized content is equal after excluding explicitly non-semantic operational metadata. Different authoritative snapshots or analyses must produce different identities even if their rendered text happens to look the same.

## 11. Versioning and compatibility

The contract and organization profile are versioned independently:

- `contract_version` governs fields, semantic meaning, authority, validation, and reference rules;
- `organization_profile` governs section taxonomy, assignment rules, and deterministic ordering.

Semantic versioning applies:

- **PATCH** clarifies validation or representation without changing meaning or accepted object classes;
- **MINOR** adds optional compatible fields, sections, or governed object types while preserving existing meaning;
- **MAJOR** changes authority, required fields, semantic meaning, inclusion rules, or compatibility expectations.

Consumers must declare supported major versions and reject unknown incompatible versions. They must not guess at missing fields or reinterpret an older object under newer semantics.

Compatibility is provided through explicit, deterministic adapters. An adapter:

- declares source and target versions;
- preserves all supported semantic content and stable upstream references;
- records every non-representable field;
- fails if conversion would lose meaning, conflict state, alternatives, unknowns, or evidence closure;
- never reruns analysis or creates new intelligence.

Historical contracts remain immutable. Re-rendering an older understanding uses its original supported contract or a validated adapter; it does not silently rebuild meaning from current rules.

Historical reference resolution uses the exact immutable snapshot and owner contract versions bound to the historical understanding. Current owner state cannot satisfy a historical reference unless an explicit lossless compatibility contract proves equivalent meaning under the repository-wide protocol.

## 12. Relationship to consumers

Executive Opportunity Understanding is a shared semantic input. It is not itself a brief, dashboard, workspace, compliance judgment, API response, or role-specific view.

### 12.1 Executive Opportunity Brief

The Executive Opportunity Brief presents the understanding contract in a concise document structure. It may use deterministic text templates and layout rules. It cannot add analysis, suppress governed uncertainty, or become the sole store of evidence.

The brief obtains authoritative labels, values, typed properties, analytical wording, evidence relationships, and provenance navigation by resolving understanding references through the bound governed context. It does not consult Opportunity Intelligence or authoritative domains through private lookup rules, and it does not infer missing semantic content from identifiers or display order.

### 12.2 Executive dashboard

A dashboard may provide navigation, filters, expansion, and evidence drill-down. Filtering changes what is visible at a moment; it does not change the underlying contract or imply ranking.

### 12.3 Decision Workspace and Bid Workspace

Workspaces may place Executive Opportunity Understanding beside Buyer Intelligence and other validated analyses. They preserve analyst and domain boundaries. They do not merge Opportunity and Buyer statements into a new conclusion.

### 12.4 Proposal Compliance Intelligence

Proposal Compliance may consume authoritative opportunity references exposed through the understanding contract for navigation or context, but compliance findings must continue to trace to the authoritative requirement and submission domains. Executive Opportunity Understanding cannot become substitute evidence or certify compliance.

### 12.5 Future APIs

APIs expose a versioned representation of the immutable contract, including coverage and reference identifiers. Pagination or transport limits must not change semantic completeness. A consumer must be able to retrieve the entire detail register and coverage ledger.

Where an API or export permits resolution, it must preserve the same immutable context, owner versions, identity, digest, semantic sufficiency, and relationship-closure guarantees. Transport does not create a separate source of truth.

### 12.6 Role-specific views

CEO, Bid Manager, Proposal Manager, SME, Commercial Lead, and other role-specific views may change labels, layout, expansion defaults, and navigation. They cannot apply hidden prioritization, remove unresolved matters from the underlying accessible contract, or create role-specific facts.

### 12.7 Buyer Brief and Bid Intelligence Briefing Pack

Buyer Intelligence retains its separate evidence and reasoning authority. Buyer Brief consumes Buyer Intelligence under its own contract. The Bid Intelligence Briefing Pack may present the Executive Opportunity Brief and Buyer Brief together, but joining them is a presentation operation. Executive Opportunity Understanding does not absorb Buyer Intelligence or infer relationships between the two pillars.

## 13. Security and trust properties

The contract treats all source-derived content as data. Source text cannot alter organization rules, validation, section assignment, or consumer behavior.

The architecture requires:

- immutable inputs and outputs;
- strict schema and enum validation;
- canonical serialization;
- bounded reference resolution;
- rejection of duplicate keys and duplicate identities;
- no evaluation of embedded instructions;
- explicit separation of semantic data from rendering markup;
- provenance links that do not expose credentials or private transport metadata;
- deterministic digests suitable for replay and audit.
- governed reference resolution bound to exact owner contracts, immutable snapshots, and verified digests;
- fail-closed handling when consumer-required semantic content or relationship closure is unavailable.

## 14. Doctrine compliance

### Evidence before inference

Authoritative facts remain in their owning domains. Deterministic computations and Opportunity Intelligence reasoning retain separate types and references. Executive organization cannot convert one authority class into another.

### Human judgment

The contract exposes management considerations and unanswered questions without making a decision. Bid / No Bid, strategy, pricing, commercial acceptance, resource commitment, and submission authorization remain human responsibilities.

### Determinism

Inclusion, section assignment, ordering, identity, equality, and coverage use explicit versioned rules. No model preference, hidden score, token limit, or narrative choice affects the semantic output.

### Fail-closed validation

Invalid contracts, unsupported versions, missing references, incomplete coverage, suppressed alternatives, flattened conflicts, and prohibited conclusions prevent construction. No partial understanding is presented as complete.

### Separation of concerns

Opportunity domains own facts. Opportunity Intelligence owns its validated analysis. Executive Opportunity Understanding owns organization and coverage. Briefs and workspaces own presentation. Renderers own format. Humans own decisions.

Governed Reference Resolution verifies access across those boundaries. It owns none of the resolved content and performs no reasoning, classification, summarization, or presentation.

### Immutable contracts

The understanding is a new immutable value bound to exact input identities and versions. It cannot mutate upstream evidence or be silently reinterpreted by a downstream consumer.

### No black-box summary

The executive index is backed by a complete detail register and coverage ledger. Every item remains inspectable. Compact presentation cannot hide the existence of assumptions, alternatives, conflicts, unknowns, or limitations.

## 15. Extension strategy

Future extensions may add:

- additional deterministic executive organization profiles;
- new Opportunity Intelligence object types;
- richer evidence navigation;
- role-specific presentation metadata;
- comparison between versioned opportunity snapshots;
- temporal change records;
- bounded relationships to Proposal Compliance outputs.

Each extension must preserve upstream ownership, evidence closure, deterministic coverage, human authority, and compatibility. Adding another analyst, introducing generated summaries, combining Buyer and Opportunity reasoning, or assigning importance would require separate architecture review and cannot enter as a minor convenience.

## 16. Acceptance criteria for future implementation

A future implementation is conformant only if it demonstrates that:

1. identical governed inputs produce identical semantic output and identity;
2. inputs are not mutated;
3. every eligible upstream object appears exactly once in the coverage ledger and exactly once in its owning detail collection;
4. executive-index inclusion follows only declared semantic rules;
5. every reference resolves to the correct owning object and evidence;
6. authoritative facts, computations, observations, interpretations, alternatives, assumptions, unknowns, conflicts, questions, considerations, and limitations remain separate;
7. unresolved conflicts and competing interpretations are never selected or flattened;
8. unsupported analyst or contract versions fail closed;
9. missing references, duplicates, digest mismatches, and incomplete coverage fail closed;
10. no recommendation, score, ranking, prediction, procurement strategy, bidder capability claim, or human decision can enter the contract;
11. the contract can be rendered without Stage D or any model call;
12. a rendering failure does not alter the valid understanding;
13. the complete detail register remains accessible when a consumer presents a compact executive index;
14. legacy contracts are read only through explicit supported versions or validated adapters;
15. Opportunity and Buyer Intelligence remain separate through Briefing Pack assembly.
16. every admitted reference resolves through the exact governed context bound by the understanding envelope;
17. downstream consumers receive all owner-declared semantic fields and relationship navigation required by their contract without copying ownership or inferring missing values;
18. stale, missing, ambiguous, incompatible, or incomplete reference resolution fails closed.

## 17. Architecture definition

Executive Opportunity Understanding is defined as a first-class, immutable organizational contract within the Opportunity Intelligence pillar.

It creates no intelligence and owns no authoritative content. It turns validated Opportunity Intelligence into a deterministic executive mental model by preserving semantic classes, assigning governed sections, maintaining a complete detail register, and proving coverage for every admitted object.

Briefs, dashboards, workspaces, compliance experiences, APIs, and role-specific views consume this contract. They do not define it. Rendering remains purely presentational, and human judgment remains sovereign.

## 18. Governed Reference Resolution compatibility

This architecture is compatible with [`GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md`](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md).

- **Ownership is unchanged.** Canonical Opportunity and other authoritative opportunity domains own facts and provenance. Opportunity Intelligence owns computations and analytical statements. Executive Opportunity Understanding owns organization and coverage only.
- **References remain immutable.** Each reference retains its owner, source contract version, semantic class, stable object identity, evidence relationships, and envelope-bound snapshot context.
- **Resolution is deterministic and read only.** The exact reference and immutable context produce the same owner-declared semantic result or the same controlled failure.
- **Consumers receive governed meaning.** Presentation and operational consumers receive the exact labels, values, typed properties, uncertainty, evidence relationships, and provenance navigation required by their supported contracts.
- **Canonical truth is not duplicated.** Resolved semantic representations retain their owner identity and authority. Optional display values do not become new canonical objects.
- **Failure remains closed.** Missing identity, incompatible versions, digest mismatch, incomplete snapshots, missing semantic content, or broken relationship closure prevents the affected transition.

This amendment changes architecture documentation only. It changes no production code, prompts, tests, schemas, persistence, APIs, pipelines, evaluation artifacts, or implementation behavior.
