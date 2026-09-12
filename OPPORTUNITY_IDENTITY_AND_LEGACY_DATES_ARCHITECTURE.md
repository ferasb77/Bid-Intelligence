# Opportunity Identity and Legacy Dates Architecture

## Document metadata

| Field | Value |
|---|---|
| Document | `OPPORTUNITY_IDENTITY_AND_LEGACY_DATES_ARCHITECTURE.md` |
| Title | Opportunity Identity and Legacy Dates Architecture |
| Authority level | Level 3 — Architectural Ownership Investigation |
| Version | 1.0.0 |
| Status | Investigation complete — no code changed. Recommendations only. |
| Purpose | Determine, from repository evidence, whether Stage A's legacy `dates` section and the ungoverned `context_id` "root" reference used by Opportunity Intelligence are genuinely missing constitutional owners, or legacy representations that should disappear. |
| Trigger | Live commissioning of the real Bank of Canada corpus: `analyze_opportunity()` produced 13 `evidence_used` entities (12 from `dates`, 1 root `CANONICAL_FACT`) that no admitted publication (Evidence, Canonical Opportunity, Opportunity Structure) could resolve a governed reference for. |
| Higher authority | [MANIFESTO.md](MANIFESTO.md), [ANTI_GOALS.md](ANTI_GOALS.md), [AGENT.md](AGENT.md), [GOVERNANCE.md](GOVERNANCE.md), [docs/architecture/DECISION_DOCTRINE.md](docs/architecture/DECISION_DOCTRINE.md), [GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md](GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md) |
| Related architecture | [CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md](CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md), [OPPORTUNITY_STRUCTURE_PUBLICATION_ARCHITECTURE.md](OPPORTUNITY_STRUCTURE_PUBLICATION_ARCHITECTURE.md), [OPPORTUNITY_ORCHESTRATION_ARCHITECTURE.md](OPPORTUNITY_ORCHESTRATION_ARCHITECTURE.md) |

---

## 1. Repository evidence

### 1.1 Part 1 — Legacy `dates`: what it is, how it is (not) reconciled

Stage A's prompt schema (`extractor.py:135-137`) defines `dates` as a second, independent extraction path for calendar facts, alongside `typed_observations`' governed `MILESTONE` family:

```python
"dates": [
    {"milestone": "Milestone name", "date": "YYYY-MM-DD", "source_doc": "<filename>"}
],
```

**Reconciliation discipline, by pipeline stage:**

| Stage | What happens to `dates` |
|---|---|
| Stage A, within one document's chunks | `aggregate_stage_a_facts` (`extractor.py:2498-2514`) deduplicates by exact `(milestone.lower(), date)` tuple — the only real dedup `dates` ever receives. |
| Stage B, across documents in the package | `normalize_package_facts` (`extractor.py:3013`): `normalized["dates"].extend(df.get("dates", []))` — **raw concatenation, zero cross-document dedup, no `validate_source_refs` call** (unlike `requirements`, deduped by `desc_key` a few lines above and passed through `validate_source_refs`). |
| Stage C | `detect_document_conflicts` (`extractor.py:1493-1576`) reads `dates` only to *flag* a `DATE_CONFLICT`; it never rewrites, merges, or resolves the underlying list. There is no `dates` equivalent of `reconcile_package_facts`'s call to `resolve_canonical_opportunity`. |
| Stage D | `build_stage_d_context` (`extractor.py:3906`) passes the raw, undeduped, package-wide list straight into the LLM synthesis context. A separate, later display-layer function, `apply_stage_d_authoritative_sections` (`extractor.py:4053-4078`), does its own light `(milestone, date, source_doc)` dedup for a legacy `brief.key_dates` field — a presentation cleanup, not a Stage B/C data contract. |

**No test exercises cross-document reconciliation of `dates`.** `tests/test_stage_a_extraction_reliability.py` tests only single-document chunk aggregation and recovery; `tests/test_stage_c_refinement.py` tests only conflict *flagging*. No test supplies two documents with an overlapping milestone/date pair and asserts `normalized["dates"]` collapses them — because Stage B's `.extend()` never does.

**The one real downstream consumer**, `opportunity_intelligence.py`, combines the two independent extraction paths without correcting for overlap (`opportunity_intelligence.py:197-210`):

```python
milestones = []
partial_dates = 0
for item in observations:                       # canonical, governed MILESTONE family
    if item.get("family") != "MILESTONE":
        continue
    ...
    milestones.append((str(item.get("semantic_kind") or "MILESTONE"), parsed))
for item in records["dates"]:                    # raw, ungoverned, undeduped dates section
    ...
    milestones.append((str(item.get("milestone") or "MILESTONE"), parsed))
milestones = sorted(set(milestones), key=lambda pair: (pair[1], pair[0]))
```

`set(milestones)` only removes exact `(label, date)` duplicates. A canonical label (`"SUBMISSION_DEADLINE"`) never string-matches a free-text `dates` label (`"Closing Date"`), so the same real-world date is not deduplicated across the two sources. This directly inflates `"milestone_completeness": {"observed": ...}` (`opportunity_intelligence.py:252`), which sums the two counts with no overlap correction. **This is a real, evidenced double-counting defect in already-shipped code**, exposed by this investigation, not by the commissioning failure itself.

### 1.2 Real production evidence — every `dates` entry from the live Bank of Canada corpus, compared against the real canonical ledger

| # | Legacy `dates` entry | Canonical MILESTONE / CONTRACT_TERM equivalent | Equivalent? | Evidence | Recommendation |
|---|---|---|---|---|---|
| 1 | `Publication`, `2026-08-27`, abstract.pdf | `PUBLICATION_DATE` `2026-08-27` (PARTIAL) | YES | Same date, same source document, same real fact | Retire — already governed |
| 2 | `Bid Intent Deadline`, `2026-09-28`, abstract.pdf | `INTENT_TO_BID_DEADLINE` `2026-09-28` (PARTIAL) | YES | Same date, same document | Retire — already governed |
| 3 | `Question Acceptance Deadline`, `2026-09-10`, abstract.pdf | `CLARIFICATION_DEADLINE` `2026-09-10` (PARTIAL) | YES | Same date, same document | Retire — already governed |
| 4 | `Closing Date`, `2026-09-30`, abstract.pdf | `SUBMISSION_DEADLINE` `2026-09-30` (PARTIAL) | YES | Same date; a synonym label for the same canonical fact as #7 | Retire — already governed |
| 5 | `Amendment No. 1`, `2026-08-28`, abstract.pdf | `AMENDMENT_DATE` `2026-08-28` (PARTIAL) | YES | Same date, same document | Retire — already governed |
| 6 | `Publication Date`, `2026-08-27`, abstract.pdf | `PUBLICATION_DATE` `2026-08-27` (second PARTIAL observation) | YES | Second free-text label for the same fact as #1; Stage A itself extracted this pair twice under `typed_observations` too | Retire — already governed |
| 7 | `Submission Deadline`, `2026-09-30`, abstract.pdf | `SUBMISSION_DEADLINE` `2026-09-30` (PARTIAL) | YES | Same canonical observation as #4 (two raw labels, one governed fact) | Retire — already governed |
| 8 | `Amendment No. 1 Published`, `2026-09-01`, abstract.pdf | `AMENDMENT_DATE` `2026-09-01` (PARTIAL) | YES | Same date, same document | Retire — already governed |
| 9 | `Amendment No. 1 Publication`, `2026-09-01`, abstract.pdf | `AMENDMENT_DATE` `2026-09-01` (second observation, VERIFIED) | YES | Second free-text label for the same fact as #8 | Retire — already governed |
| 10 | `Agreement Commencement Date`, `None`, Appendix G | *(none — no CONTRACT_TERM `COMMENCEMENT_DATE` observation exists for Appendix G)* | NO | Zero canonical observations of any family correspond to this entry; confirmed by full CONTRACT_TERM family scan (3 observations total, none from Appendix G, none semantically COMMENCEMENT_DATE) | Genuinely orphaned — see §5 |
| 11 | `Agreement Termination Date`, `None`, Appendix G | *(none)* | NO | Same as #10 | Genuinely orphaned — see §5 |
| 12 | `Renewal Notice Period`, `None`, Appendix G | *(none)* | NO | Same as #10 | Genuinely orphaned — see §5 |

**9 of 12 real entries are exact semantic duplicates of an already-governed canonical fact.** Only 3 (all from the Form of Agreement, all with `date: None`) carry information not captured anywhere else — and that information is itself incomplete (a milestone *label* with no date value, because Stage A could not, or did not, produce a value that would pass `typed_observations`' stricter `_valid_iso_date` validation).

**Which downstream modules still consume `dates`?** Confirmed by full-repository grep: only `extractor.py` (writer) and `opportunity_intelligence.py` (the sole analytical reader). `stage_d_projection.py:132` only declares a field allowlist, performing no computation. `decision_workspace.py`, `executive_opportunity_understanding.py`, `executive_opportunity_brief.py`, `buyer_intelligence.py`, `buyer_brief.py`, `buyer_domain.py`, `canonical_opportunity_publication.py`, and `opportunity_intelligence_publication.py` do not read `dates` at all.

**Is `dates` now redundant?** For 9 of 12 real entries, yes — fully redundant with already-governed Canonical Opportunity MILESTONE observations. For 3 of 12, no — but the residual value is a bare milestone label with no verified date, which is marginal and, per the constitutional identity discipline restored earlier this session, should never have been treated as a *governed fact* in its own right (an unparseable/absent date is exactly the `UNPARSED`/`EMPTY` normalization state `canonical_opportunity.py` already has a first-class representation for — `dates` does not need to exist in parallel to express it).

### 1.3 Part 2 — Does a governed "Opportunity" identity object exist under any name?

**No.** Confirmed by exhaustive search across every layer that could plausibly hold it:

- **Evidence** (`evidence.py`, full file): exactly four object classes — `EVIDENCE_SOURCE`, `EVIDENCE_ARTIFACT`, `EVIDENCE_OCCURRENCE`, `EVIDENCE_EXTRACT`. Each is narrower than the opportunity: publisher, document, locator, excerpt. `EvidenceSnapshot.acquisition_corpus_id` is the closest candidate, but it is a syntax-validated string field (`_identifier`), not its own object class — it cannot be the target of a `GovernedObjectReference`.
- **`procurement_evidence_adapter.py`** (full file): `adapt_procurement_corpus` builds one `EvidenceSource`, N `EvidenceArtifact`s, and per-artifact occurrences/extracts. `corpus_id` from the manifest is threaded through only as `acquisition_corpus_id`, never as a referenceable object.
- **Canonical Opportunity** (`canonical_opportunity.py`, `canonical_opportunity_publication.py`): publishes `CANONICAL_FIELD_STATE` (one object *per resolved field* — title, client, submission_deadline, …), `CANONICAL_OBSERVATION`, and `CANONICAL_CONFLICT`. No object represents the opportunity as one whole; the ledger is a bag of per-field resolutions.
- **Opportunity Structure** (`opportunity_structure_publication.py`, built this session): publishes `REQUIREMENT`/`EVALUATION_CRITERION`/`COMMERCIAL_CLAUSE`/`DELIVERABLE`/`SUBMISSION_RULE` and `STRUCTURE_CONFLICT` — deliberately excludes any opportunity-level identity per its own architecture (§3: *"Never owns: ... any interpretation ... about what the structure means"*).
- **Opportunity Intelligence** (`opportunity_intelligence.py:140-142`): builds a required root reference from a bare caller-supplied string:
  ```python
  root = EvidenceSupport(SupportedEntityType.CANONICAL_FACT, context.analyst_context.context_id)
  ```
  `AnalystContext.context_id` (`decision_intelligence.py:207-215`) is validated only for "non-empty trimmed string" — never resolved against any registered object.
- **Opportunity Orchestration** (`opportunity_orchestration.py`): `scope_id`, used throughout `admit_owner_publication`/`orchestrate_opportunity_intelligence`, is validated the identical way — a bare identifier all admitted publications must agree on, never a governed object.
- **Buyer domain, for contrast**: `buyer_domain.py` *does* define `CanonicalBuyer` — a governed identity object for the buyer organization. **This is a real asymmetry already present in the repository**: the buyer has a canonical identity record; the opportunity does not.
- Repository-wide search for a bare `class *Opportunity*` identity object (excluding Publication/Manifest/Error/Contract/Orchestration/Context/Analyst/Binding classes, all of which exist) returns nothing.

### 1.4 Why Opportunity Intelligence needs an Opportunity identity object

`opportunity_intelligence.py`'s own analyst contract *requires* a root evidence-support entity — every computed fact not specifically tied to a requirement links back to `root` (`opportunity_intelligence.py:126-128, 248`). This is a structurally necessary anchor: without it, package-level facts (`total_conflicts`, `procurement_model`, `opportunity_type`, and 15 others) would have no support entity at all, violating `decision_intelligence.py`'s own requirement that every `DecisionStatement` carry `evidence_support`. The analyst was built assuming *something* would eventually publish a resolvable object for that anchor — but nothing ever has, because no such object exists (§1.3).

### 1.5 Constitutional documents — what they say and where they are silent

`MANIFESTO.md` (Pillar 1) is the only passage in the five governing documents that defines "the opportunity" at all, and it defines it as *subject matter*, never as an identity:

> "**Opportunity Intelligence — understand the opportunity.** Establish requirements, evaluation structure, submission mechanics, dates, commercial facts, deliverables, dependencies, ambiguity, and conflict from authoritative source material."

None of `MANIFESTO.md`, `ANTI_GOALS.md`, `GOVERNANCE.md`, or `AGENT.md` uses the terms "governed reference," "identity object," or discusses resolution mechanics — this is a Level-1/Level-2 silence, not a Level-1/Level-2 answer either way.

`GOVERNED_REFERENCE_RESOLUTION_ARCHITECTURE.md` (Level 3, and directly on point) is explicit, and is already violated by the current design:

> §5.9 Relationship closure: *"Evidence, provenance, conflict, supersession, dependency, and support relationships required to understand or validate an object must resolve within the declared context or be represented as an explicit governed absence. A dangling required relationship invalidates resolution."*

`opportunity_intelligence.py`'s root `SUPPORT` relationship is exactly a *"required relationship"* with no way to resolve and no explicit governed-absence representation — the commissioning failure is this rule being enforced correctly, not a defect in the resolution protocol.

---

## 2. Constitutional reasoning

### 2.1 Legacy `dates`: missing owner, or legacy representation that should disappear?

**Legacy representation that should disappear**, not a missing owner. The evidence in §1.1–1.2 shows `dates` was never a reconciled, governed fact source to begin with — Stage B performs no dedup, no `source_refs` validation, and no cross-document resolution; the one real consumer treats it as an informal supplement whose overlap with the governed MILESTONE family it does not correct for. Declaring `dates` a "genuinely missing constitutional owner" would mean building reconciliation, provenance validation, and publication machinery for a structure that is 75% (9/12) exact duplication of a domain that already does all of that correctly (`canonical_opportunity.py`'s MILESTONE family). That would violate the same "duplicate responsibility" discipline this repository's architecture reviews have already applied elsewhere (e.g. `OPPORTUNITY_STRUCTURE_PUBLICATION_ARCHITECTURE.md` §2's precedent argument against splitting one reconciliation into several redundant owners).

The 3 orphaned entries (§1.2, rows 10–12) do carry residual information, but the correct constitutional home for that information is the family that already owns "commercial/contractual date facts" — Canonical Opportunity's `MILESTONE`/`CONTRACT_TERM` families — not a parallel, permanently-ungoverned structure kept alive only to hold three undated labels.

### 2.2 Opportunity root: missing owner, or something that should disappear?

**Genuinely missing owner.** Unlike `dates`, this is not a redundant duplicate of existing governed content — no object anywhere represents "the opportunity as a whole" (§1.3), yet the architecture's own resolution protocol *requires* one for a relationship `opportunity_intelligence.py` already, correctly, declares as necessary (§1.4, §1.5). This cannot "disappear" the way `dates` can: removing the root reference would mean removing the evidentiary anchor for every opportunity-level computed fact, contradicting `DECISION_DOCTRINE.md`'s requirement that computation retain identifiable provenance (*"Its provenance and stable identity remain available"*, quoted in the DECISION_DOCTRINE ladder for Source Facts, and structurally required again at the Computed Fact level by `decision_intelligence.py`'s `EvidenceSupport` contract).

---

## 3. Ownership analysis

### 3.1 Should `dates` have an owner at all?

No new owner. The recommendation (see §5) is to fold the 3 non-redundant entries' *kind* of information (an attributable milestone label without a confirmed date) into Canonical Opportunity's existing `MILESTONE` family, by relaxing `typed_observations`' validation to accept an `UNKNOWN`/absent date the same way it already accepts `UNKNOWN` precision — not by giving `dates` its own reconciliation and publication contract.

### 3.2 Opportunity root: Option A (extend an existing owner) vs. Option B (dedicated new owner)

**Recommendation: Option A — extend Canonical Opportunity Publication with a single new object class representing the opportunity's own identity record.** Reasoning:

1. **No new body of facts to reconcile.** A "genuinely missing constitutional owner" (per this session's earlier Opportunity Structure investigation) is warranted when a *distinct class of facts* has no reconciliation home — Requirement, Evaluation Criterion, Commercial Clause, Deliverable, Submission Rule all needed genuinely new reconciliation logic. An "Opportunity identity" is not a new class of fact; it is a **reference point** that ties already-reconciled facts together. Building a whole new owner domain for a reference point, with its own ledger, its own reconciliation pass, and its own publication contract, would be architecturally redundant machinery for something that requires none.
2. **Direct precedent already exists in this repository.** `buyer_domain.py`'s `CanonicalBuyer` is owned by the Buyer domain itself — the domain that already establishes the buyer's core facts also publishes the buyer's canonical identity record. There is no separate "Buyer Identity" owner. The same pattern applied to the Opportunity means Canonical Opportunity — the domain that already resolves `title`, `client`, `file_number`, `submission_deadline`, `clarification_deadline`, `contract_term`, `headline_value`, `opportunity_type`, and `procurement_model` (`canonical_opportunity.py:26-32`, `FIELD_KINDS`) — is the domain that already establishes exactly the facts that constitute an opportunity's identity.
3. **`docs/architecture/ARCHITECTURE.md`'s own definition of Canonical Opportunity already fits.** As quoted in `CANONICAL_OPPORTUNITY_PUBLICATION_ARCHITECTURE.md` §5: *"Canonical does not mean infallible or complete. It means that downstream work has one governed authority for the present evidence state"* — for exactly the who/when/how-much/what-kind-of-procurement facts an "opportunity identity" would need to reference.
4. **No authority boundary would move.** Adding one more object class to an existing, already-approved publication contract is a strictly smaller, more reversible change than authorizing a new domain, new `OWNER_DOMAIN`/`OWNER_CONTRACT` pair, and a new Level-3 architecture document — consistent with `GOVERNANCE.md`'s discipline against unnecessary constitutional surface area.

**Why not Option B:** A dedicated owner would need to answer "what does this owner reconcile that Canonical Opportunity doesn't already reconcile?" — and the honest answer, from the evidence in §1.3, is nothing. Every fact an Opportunity-identity object would need already has a governed owner; the only missing piece is a single addressable object that other publications' relationships can point to.

---

## 4. Migration analysis

### 4.1 Legacy `dates` — dependency and migration surface

| Aspect | Finding |
|---|---|
| Writers | `extractor.py` only (Stage A prompt schema, chunk aggregation, package concatenation, Stage D context passthrough, legacy brief dedup) |
| Readers | `opportunity_intelligence.py` only (milestone list construction, `milestone_completeness` metric, evidence-link section list); `stage_d_projection.py` only as a field-allowlist schema entry (no computation) |
| Publications | None currently own `dates`; none would need to change if `dates` disappears, since none reference it |
| Governed references | None exist for `dates` today (that is the current failure) — retiring it removes 12 of the 13 unresolved `evidence_used` entities without creating any new ones |
| Tests | No test asserts cross-document `dates` reconciliation (§1.1) — none would break from retiring the cross-document raw-concatenation behavior. Single-document Stage A aggregation tests (`tests/test_stage_a_extraction_reliability.py`) exercise the extraction step itself, which is a separate, unaffected concern from whether the resulting list survives into Stage B/C as an independently governed structure. |
| Replay implication | None — `dates` records receive `_record_id`'s deterministic hash fallback (no `date_id`/`milestone_id` field is ever populated in real production data); no replay-sensitive identity currently depends on `dates` surviving. |
| Compatibility implication | Retiring `dates` as an independent governed source requires a code change only in `opportunity_intelligence.py` (remove `"dates"` from its section list and stop double-summing `milestone_completeness`) — no publication contract changes, no schema-version bump on any existing publication. Recommended as future work, not performed here. |

### 4.2 Opportunity root — dependency and migration surface

| Aspect | Finding |
|---|---|
| Dependent modules | `opportunity_intelligence.py` (constructs the root `EvidenceSupport`); `decision_intelligence.py` (`AnalystContext.context_id` carries it); `opportunity_intelligence_publication.py` (requires a resolvable `OpportunitySupportBinding` for it); `opportunity_orchestration.py` (`scope_id` — a parallel, not identical, bare-identifier pattern that the same fix would not automatically resolve, and should be reviewed separately once an Opportunity identity object exists) |
| Publications affected by adding the object | Canonical Opportunity Publication only, under Option A — one new object class (e.g. `CANONICAL_OPPORTUNITY_IDENTITY` or similar), additive to the existing `CANONICAL_FIELD_STATE`/`CANONICAL_OBSERVATION`/`CANONICAL_CONFLICT` classes. `PUBLICATION_CONTRACT_VERSION` would need a version bump (mirroring the `1.0.0` → `1.1.0` precedent already set this session for the PARTIAL/UNVERIFIED accommodation) |
| Governed references | Zero currently resolve for the root entity; adding the object would need its `object_id` to equal whatever `context_id` callers of `analyze_opportunity` supply — this requires either (a) callers choosing `context_id` to match the new object's deterministic identity, or (b) `opportunity_intelligence.py` itself deriving `context_id` from the admitted Canonical Opportunity Publication automatically. Both are implementation decisions, not made here. |
| Replay implication | The new object's identity must be derived deterministically from the same `input_digest`/`opportunity_id` Canonical Opportunity Publication already uses, so that repeated real runs of the same corpus produce the same identity — consistent with every other identity in this architecture. |
| Compatibility implication | Additive only — no existing Canonical Opportunity Publication object, relationship, or validation rule needs to change; `opportunity_structure_publication.py`, `evidence_publication.py`, and their tests are unaffected. `opportunity_intelligence.py`'s root-construction line and `opportunity_orchestration.py`'s `scope_id` handling would need a coordinated follow-up once the new object exists, to actually bind to it — flagged as required future work, not performed here. |

---

## 5. Recommendation

1. **Retire `dates` as an independently governed structure.** It is not a missing owner; it is a legacy, unreconciled duplicate of Canonical Opportunity's own `MILESTONE` family for 9 of 12 real entries, and an under-specified fragment (label without a valid date) for the remaining 3. Recommended migration: extend `typed_observations`' `MILESTONE` family to accept an explicit "date unknown/unconfirmed" state (mirroring the `UNKNOWN` precision value the schema already supports) so the 3 currently-orphaned Appendix-G milestones can be captured as governed, provenance-validated `MILESTONE` observations instead of ungoverned `dates` entries. Once done, `dates` can be removed from `opportunity_intelligence.py`'s section list entirely, eliminating the double-counting defect identified in §1.1 as a side effect.
2. **Do not build a dedicated "Opportunity identity" owner.** Extend Canonical Opportunity Publication (Option A, §3.2) with one additive object class representing the opportunity's own identity record, referencing its own already-published `CANONICAL_FIELD_STATE` objects. This requires a publication-contract version bump, following the same pattern already used this session for the PARTIAL/UNVERIFIED evidence-closure accommodation.
3. Neither recommendation has been implemented. Both require a follow-up implementation pass, explicitly authorized by the user, following the same investigate → report → implement-minimally → validate → recommission discipline used throughout this engagement.

---

## 6. Implementation implications (recorded as recommendations only — not implemented)

- **For `dates`:** a Stage A/B schema change (relaxing `MILESTONE` date validation) is a change to an already-shipped extraction contract and prompt — larger in blast radius than anything touched so far this session (Stage A prompt changes affect every future extraction run, not just a downstream reconciliation module) and should not be undertaken without explicit authorization and its own validation cycle against real documents.
- **For the Opportunity root:** the new Canonical Opportunity Publication object class, its identity derivation, and the coordinated update to `opportunity_intelligence.py`'s root-construction call site are all mechanical once authorized, but touch three previously-untouched call sites (`opportunity_intelligence.py`, `opportunity_orchestration.py`'s `scope_id` handling, and any script that calls `analyze_opportunity` with a hand-chosen `context_id`) and should be scoped and validated as their own implementation pass, not folded silently into an unrelated change.
- Commissioning remains stopped at the Opportunity Intelligence Support Binding boundary pending a decision on these two recommendations.
