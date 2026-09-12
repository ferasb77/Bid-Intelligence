# Bank of Canada RFP 2026-026 — Canonical Opportunity Commissioning Report

**Commissioning run ID:** `canonopp-boc-2026-026-20260912T135357Z-060143`
**Artifact directory:** `evaluation/bank_of_canada_briefing_pack/canonical_opportunity_commissioning/canonopp-boc-2026-026-20260912T135357Z-060143/`

## A. Run metadata

| | |
|---|---|
| Phase 1 (Stage A, frozen) | `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5` |
| Phase 2 (Stage B, frozen) | `phase2-boc-2026-026-stageb-20260912T125051Z-91a22b` |
| Phase 3 (Stage C, frozen) | `phase3-boc-2026-026-stagec-20260912T130007Z-dd391b` |
| Phase 4 (Stage D, frozen, referenced only) | `phase4-boc-2026-026-staged-20260912T131303Z-2cc8af` |
| Stage D narrative diagnostic (frozen, referenced only) | `phase4-narrative-diag-boc-2026-026-20260912T133437Z-2a74e2` |
| Git commit | `7e797830f42d06ff08745648585de0e26557addb` |
| Working tree | dirty (unrelated in-flight docs/opportunity-structure WIP files; none touch Stage A–D or Canonical Opportunity) |
| Production entry points | `canonical_opportunity.build_canonical_opportunity()` (called from `extractor.normalize_package_facts` — Stage B), `canonical_opportunity.resolve_canonical_opportunity()` + `apply_legacy_conflict_fallback()` (called from `extractor.reconcile_package_facts` — Stage C) |
| Runtime | 1.771s |
| LLM calls | **0** |
| API cost | **$0** |

## 1–2. Implementation inspection and constitutional role

`canonical_opportunity.py` was read in full (610 lines) before anything was run. It is entirely deterministic — no `anthropic`/`client.messages`/`get_anthropic_client` reference anywhere in the module.

**Architecture, as actually implemented (not assumed from prior prompts):**

- **`build_canonical_opportunity(doc_facts_list, package_metadata)`** — builds an immutable, order-independent *observation ledger* directly from each document's raw Stage A `typed_observations` array (a Stage A output field entirely separate from `requirements`/`dates`/`evaluation_criteria`/`submission_rules`/`deliverables`/`commercial_clauses`). Every raw observation is validated against a fixed `FAMILIES`/`KINDS_BY_FAMILY` taxonomy; anything with an unrecognized family/kind is fail-closed into `integrity_diagnostics.invalid_observations` and never enters the trusted ledger. Each surviving observation gets a content-addressed `observation_id` (`obs_` + SHA-256 of its identity material) and a separately content-addressed `normalized_identity_id`; identical raw facts re-observed across chunks/documents deduplicate into one logical observation with multiple `extraction_occurrences`, never silently merging genuinely different observations (a hash collision on the same `observation_id` with different identity material is recorded in `integrity_diagnostics.collision_ids`, not silently overwritten). This function runs **inside Stage B**, called at `extractor.py:3240-3241`, with the exact same `doc_facts_list`/`package_metadata` Stage B itself receives — it is not derived from Stage B's deduplicated `requirements`/`dates` arrays.
- **`resolve_canonical_opportunity(canonical)`** — takes the built ledger and computes a separate, non-destructive *resolution view* (`resolved`, `conflicts`) for a fixed set of executive fields: `title`, `client`, `file_number`, `submission_deadline`, `clarification_deadline` (all via `_resolve_simple`/`_resolve_client`), `contract_term` (`_resolve_term`), `headline_value` (`_resolve_money`), `opportunity_type`/`procurement_model` (`_resolve_classifications`). Every resolver only considers `ACTIVE` (non-superseded), `VERIFIED`-provenance, successfully-normalized observations as candidates; if the surviving candidates disagree, a `conflict` record is created and the field is explicitly set to `CONFLICTED`/`None` — never a guessed winner. This runs **inside Stage C**, called at `extractor.py:3297-3300`.
- **`apply_legacy_conflict_fallback(canonical, legacy_conflicts)`** — a narrow, keyword-scoped safety net that additionally nulls `clarification_deadline`/`submission_deadline`/`contract_term` if Stage C's *separate*, older rule-engine conflict detector independently flagged the same topic and canonical resolution hadn't already caught it (also called from Stage C, immediately after `resolve_canonical_opportunity`).
- **`apply_authoritative_values(synthesis, canonical)`** / **`remove_authoritative_values_for_validation(response, canonical)`** — consumed only by Stage D, to force Stage D's `bid`/`brief` scalar fields to the canonical resolved values (or `None` if not `RESOLVED`) and to scrub the model's own copies before citation validation. **Not exercised in this commissioning run** (Stage D was not invoked), documented here only to confirm Canonical Opportunity has no dependency in the other direction.
- **`compact_stage_d_summary(canonical)`** — a prompt-safe projection used only by Stage D's prompt context; likewise not exercised here.

**Data model:** plain `dict`/`list` structures (no dataclasses/Pydantic), content-addressed IDs throughout (`_id(prefix, value) = prefix + sha256(canonical_json(value))`), `canonical_json` a deterministic sorted-key JSON serializer used for every digest and for conflict deduplication.

**Constitutional role, verified against the actual code (not assumed):**
- Organizes normalized facts into 9 canonical fields (`title`, `client`, `file_number`, `submission_deadline`, `clarification_deadline`, `contract_term`, `headline_value`, `opportunity_type`, `procurement_model`) — ✅ matches "organize normalized facts into canonical fields."
- Preserves every source-derived observation in an immutable ledger, never deleted by resolution — ✅ (`resolve_canonical_opportunity` deep-copies before touching anything; the only in-place mutation is `_apply_supersession` appending `conflict_ids`/setting `supersession_state`, never removing an observation).
- Resolves fields only via `EXACT_AGREEMENT` (all VERIFIED candidates literally agree) or `RESOLVED_BY_SUPERSESSION` (an explicit, verified, exact-text-matched supersession statement) or, for `contract_term`, `STRUCTURED_COMPONENTS` (distinct non-repeatable term components that don't contradict each other) — ✅ governed deterministic bases only, no heuristic "newer wins."
- Explicitly nulls/withholds fields under genuine conflict (`CONFLICTED`) or missing verified support (`UNVERIFIED`/`MISSING`/`NOT_CLASSIFIED`) — ✅ confirmed for all 3 identity fields on this real corpus (Section E).
- **Does not** invent buyer intent, score attractiveness, recommend bid/no-bid, or generate strategy — confirmed: no such fields or logic exist anywhere in the 610-line module.
- **Does not** resolve Stage C's legacy conflicts without a governed basis — confirmed: `apply_legacy_conflict_fallback` only ever *adds* a null/CONFLICTED state, never resolves one.
- **Does not** infer amendment precedence — confirmed in Section 9 below.
- **Does not** fabricate citations — every `source_refs` entry is a deep-copied, validated (`_validate_ref`) descendant of a real Stage A `source_refs` entry; nothing is synthesized.
- **Does not** import Stage D narrative prose — confirmed: zero references to `executive_summary`/`outline`/`risk_assessments`/`scope_categories` anywhere in `canonical_opportunity.py` (re-confirmed this run; consistent with the prior narrative audit).
- **Does not** reintroduce Stage B rejected objects — confirmed empirically in Section I below (0 hits).

## 3. Input lock

Canonical Opportunity's production dependency path, confirmed by direct code reading (not assumed):

| Consumes | |
|---|---|
| Stage A raw `typed_observations` (per document, via `doc_facts_list`) | ✅ direct input to `build_canonical_opportunity` |
| `package_metadata` (files/doc_metadata/doc_texts) | ✅ direct input, used for `_validate_ref` grounding |
| Stage B normalized `requirements`/`dates`/etc. | ❌ not consumed — canonical's ledger is built independently, in parallel |
| Stage C's legacy rule-engine conflicts | ✅ only as an additional fallback signal (`apply_legacy_conflict_fallback`), never as primary resolution input |
| Stage D result | ❌ not consumed (confirmed in the prior narrative-completeness audit and re-confirmed here) |

Locked to the authoritative artifacts: `doc_facts_list` loaded verbatim from `phase1_stage_a_document_facts.json` (Stage A **not** rerun); `package_metadata` reconstructed via the same deterministic, non-LLM `extract_document_with_metadata()` call Phase 1/Phase 2 already used (not a new extraction); Stage B's persisted `_canonical_opportunity` (built-but-unresolved) and Stage C's persisted `_canonical_opportunity` (resolved) loaded from `stage_b_normalized_result.json` and `stage_c_canonical_opportunity_resolved.json` respectively. No historical `corrected_pipeline` artifacts were touched.

## K. Determinism (verified before any audit content was trusted)

Two independent, zero-LLM, zero-cost in-memory checks, performed without creating a duplicate persisted commissioning run for the build/resolve steps themselves:

**Build determinism** — `build_canonical_opportunity(doc_facts_list, package_metadata)` recomputed fresh vs. the persisted Phase 2 artifact:
```
fresh_input_digest   == persisted_input_digest   -> True
full_object_match                                -> True
```

**Resolve determinism** — the real `reconcile_package_facts()` (which internally calls `resolve_canonical_opportunity` + `apply_legacy_conflict_fallback`) run **twice**, independently, from a deep-copied frozen Stage B artifact, and compared against each other and against the persisted Phase 3 artifact:
```
run1 == run2                    -> True
run1 == persisted Phase 3       -> True
run2 == persisted Phase 3       -> True
run1 conflicts == run2 conflicts == persisted (7 each) -> True
zero_llm_calls: true    zero_stage_a_rerun: true
```

**Conclusion:** the persisted Phase 2/Phase 3 `_canonical_opportunity` artifacts are proven, not merely assumed, to be exact, reproducible products of the real production path from the frozen upstream lineage. Every section below audits this now-verified object.

## 4. Canonical field inventory (actual production schema)

| Field | Type | Family / accepted semantic kinds | Resolution mechanism | Provenance representation | On agreement | On conflict | On absence |
|---|---|---|---|---|---|---|---|
| `title` | string or null | IDENTITY / `OPPORTUNITY_TITLE` | `_resolve_simple` | `observation_ids`, `provenance_status` | `EXACT_AGREEMENT` (all VERIFIED candidates normalize identically) | `CONFLICTED`, value `None`, conflict record created | `MISSING` if zero typed observations of this kind exist at all, `UNVERIFIED` if candidates exist but none reach VERIFIED |
| `client` | string or null | IDENTITY / `BUYER_NAME`, with `ISSUING_AUTHORITY` as a governed fallback | `_resolve_client` → `_resolve_simple` | same | `EXACT_AGREEMENT`, or `ISSUING_AUTHORITY_FALLBACK` if no `BUYER_NAME` observations exist but `ISSUING_AUTHORITY` ones do | `CONFLICTED` | `MISSING`/`UNVERIFIED` |
| `file_number` | string or null | IDENTITY / `SOLICITATION_NUMBER` | `_resolve_simple` | same | `EXACT_AGREEMENT` | `CONFLICTED` | `MISSING`/`UNVERIFIED` |
| `submission_deadline` | `{date, time, timezone, precision}` or null | MILESTONE / `SUBMISSION_DEADLINE`, unscoped only, `DATE`/`DATETIME` precision only | `_resolve_simple` | same | `EXACT_AGREEMENT` or `RESOLVED_BY_SUPERSESSION` | `CONFLICTED` | `MISSING`/`UNVERIFIED` |
| `clarification_deadline` | `{date, time, timezone, precision}` or null | MILESTONE / `CLARIFICATION_DEADLINE`, same constraints | `_resolve_simple` | same | same | same | same |
| `contract_term` | list of `{kind, value, scope}` or `"Not stated"` (formatted) | CONTRACT_TERM / `INITIAL_DURATION`, `COMMENCEMENT_DATE`, `END_DATE`, `EXTENSION_OPTION`, `RENEWAL_OPTION`, `MAXIMUM_TERM`, `TERMINATION_CONDITION`, `TERM_STATEMENT` | `_resolve_term` | per-item `observation_ids` | `STRUCTURED_COMPONENTS` — distinct, non-contradicting term components co-exist (not a single scalar); repeatable kinds (extension/renewal options) may co-occur only if distinctly sequenced; a stated duration must arithmetically agree with explicit start/end dates when all three are present | `CONFLICTED` if the same non-repeatable kind+scope has >1 disagreeing value, or a duration/date arithmetic mismatch | `MISSING`/`UNVERIFIED` |
| `headline_value` | `{amount, currency, tax_basis, guarantee_status, period_basis}` or null | MONETARY / `ESTIMATED_CONTRACT_VALUE`, unscoped only | `_resolve_money` | `observation_ids` | `EXACT_ESTIMATED_VALUE_AGREEMENT` | `CONFLICTED` | `MISSING`/`UNVERIFIED` |
| `opportunity_type` | enum string or null | PROCUREMENT_MECHANIC / RFP·ITT·RFQ·PANEL·STANDING_OFFER, unscoped, VERIFIED only | `_resolve_classifications` | `observation_ids` | `EXPLICIT_MECHANICS` | `PROCUREMENT_MECHANIC_CONTRADICTION` if instrument types collide | `NOT_CLASSIFIED` (with `stage_d_tier2_permitted` signaling whether Stage D's own model may classify) |
| `procurement_model` | enum string or null | PROCUREMENT_MECHANIC / SINGLE·MULTIPLE_SUPPLIER_AWARD·CALL_OFF·PANEL·STANDING_OFFER combinations | `_resolve_classifications` | `observation_ids` | `EXPLICIT_MECHANICS` | `PROCUREMENT_MECHANIC_CONTRADICTION` | `NOT_CLASSIFIED` |

No fields were invented for this table; all 9 come directly from `FIELD_KINDS` plus the 4 additional fields explicitly resolved in `resolve_canonical_opportunity` (`contract_term`, `headline_value`, `opportunity_type`, `procurement_model`).

## 5/D. Complete canonical field audit

| Field | Status | Disposition | Final value | Resolution basis | Provenance | Contributing observations | Competing conflict |
|---|---|---|---|---|---|---|---|
| `title` | CONFLICTED | **UNRESOLVED** | `null` | — | UNVERIFIED | none (all candidates conflicted out) | `conf_cc97…815bc`: 10 observations, values `"rfp 2026-026 - talent, learning and organizational development services"` vs `"talent, learning and organizational development services"` |
| `client` | CONFLICTED | **UNRESOLVED** | `null` | — | UNVERIFIED | none | `conf_90315…5087a`: 13 observations, values `"bank of canada"` / `"bank"` / `"the bank"` |
| `file_number` | CONFLICTED | **UNRESOLVED** | `null` | — | UNVERIFIED | none | `conf_14f51…dd9f8`: 20 observations, values `"2026-026"` / `"rfp 2026-026"` |
| `submission_deadline` | RESOLVED | **ASSERTED** | `{date: "2026-09-30", precision: "DATE"}` | `EXACT_AGREEMENT` | VERIFIED | 1 observation (master RFP, sole source) | none |
| `clarification_deadline` | UNVERIFIED | **UNRESOLVED** | `null` | — | UNVERIFIED | none | none — no conflict, simply no candidate reached VERIFIED provenance |
| `contract_term` | RESOLVED | **ASSERTED** | `[{kind: INITIAL_DURATION, scope: {component: "HR Advisory", period_basis: "WEEKS"}, value: {duration: "12", unit: "weeks"}}]` | `STRUCTURED_COMPONENTS` | VERIFIED | 1 observation (Appendix E Pricing Form, "HR Advisory pricing scenario" sheet) | none |
| `headline_value` | MISSING | **ABSENT** | `null` | — | UNVERIFIED | none | none — zero `ESTIMATED_CONTRACT_VALUE` typed observations exist in the corpus at all |
| `opportunity_type` | NOT_CLASSIFIED | **UNRESOLVED** | `null` | — | UNVERIFIED | none | none |
| `procurement_model` | NOT_CLASSIFIED | **UNRESOLVED** | `null` | — | UNVERIFIED | none | none |

**2 of 9 fields ASSERTED, 6 UNRESOLVED, 1 ABSENT, 0 improperly resolved.** Every competing-value list above is the literal, unedited `incompatible_values` from the real conflict records — no candidate value was silently dropped from the trace.

## 6/E. Trace of all 7 Stage C conflicts into Canonical Opportunity

| Conflict ID | Semantic subject | Category | Canonical field affected | Canonical output | Provenance retained |
|---|---|---|---|---|---|
| `CONF-EVAL-1` | Evaluation weight discrepancy, "Corporate Profile" | **C** — irrelevant, available upstream | none | none | ✅ full record remains in Stage C's own conflict list |
| `CONF-EVAL-2` | Evaluation weight discrepancy, "Team Experience" | **C** | none | none | ✅ |
| `CONF-EVAL-3` | Evaluation weight discrepancy, "Methodology" | **C** | none | none | ✅ |
| `CONF-EVAL-4` | Evaluation weight discrepancy, "Title Relevant Experience And References" | **C** | none | none | ✅ |
| `conf_14f51c2b…dd9f8` | Solicitation/file number | **A** — maps directly | `file_number` | `CONFLICTED` / `null` | ✅ 20 observation IDs, full `source_refs` preserved |
| `conf_90315cf4…5087a` | Buyer/client name | **A** | `client` | `CONFLICTED` / `null` | ✅ 13 observation IDs |
| `conf_cc97deb3…815bc` | Opportunity/document title | **A** | `title` | `CONFLICTED` / `null` | ✅ 10 observation IDs |

**Zero conflicts fall into category D (improperly resolved or lost).** The 4 `EVALUATION_CONFLICT` items are category C by architecture, not by omission: `evaluation_criteria` is a Stage A/B fact family entirely outside Canonical Opportunity's `FAMILIES` set (`IDENTITY`, `MILESTONE`, `CONTRACT_TERM`, `MONETARY`, `PROCUREMENT_MECHANIC`, `DOCUMENT_ROLE`) — they were never eligible to enter the canonical ledger as typed observations in the first place, and remain fully, independently represented in Stage C's own `conflicts` list, unmodified by anything in this boundary.

**Note on the 3 identity fields:** the prior Stage D-era analysis correctly described `title`/`client`/`file_number` as force-nulled — verified here directly at the Canonical Opportunity layer itself (not inferred from Stage D's behavior): all 3 are genuinely `CONFLICTED` at the source, with real, non-trivial disagreement between multiple physically-verified observations (10–20 observations each). Stage D's force-null behavior for these fields is a correct downstream reflection of an already-correct upstream `CONFLICTED` state, not an independent Stage D decision.

## 7/F. Clean-resolution trace: `contract_term` and `submission_deadline`

**`submission_deadline`** — `RESOLVED`, `EXACT_AGREEMENT`, 1 contributing observation:
- `SUBMISSION_DEADLINE`, value `2026-09-30`, source: the master RFP (`RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf`), `provenance_status: VERIFIED`.
- This is the **sole** typed `SUBMISSION_DEADLINE` observation in the entire 16-document, 120-observation ledger that is both unscoped and reaches `DATE`/`DATETIME` precision with verified provenance. `EXACT_AGREEMENT` with a single candidate is the code's genuinely correct behavior (a single VERIFIED observation trivially satisfies "all candidates agree" — there is nothing else to disagree with), not a labeling error: no other competing `SUBMISSION_DEADLINE` observation exists anywhere in the corpus to have disagreed.

**`contract_term`** — `RESOLVED`, `STRUCTURED_COMPONENTS`, 1 contributing observation:
- `INITIAL_DURATION`, original text *"approximately twelve (12) weeks"*, normalized `{duration: "12", unit: "weeks"}`, `scope: {component: "HR Advisory", period_basis: "WEEKS"}`, source: `OriginalRevision/RFP 2026-026 - Appendix E - Pricing Form.xlsx`, sheet `"HR Advisory pricing scenario"`, excerpt *"The engagement will be completed over approximately twelve (12) weeks"*, `provenance_status: VERIFIED`.

**This is where the audit found a genuine defect (Section D below).** The full `CONTRACT_TERM`-family ledger contains **5** observations, not 1:

| Semantic kind | Scope | Provenance | Value | Source |
|---|---|---|---|---|
| `INITIAL_DURATION` | `{component: HR Advisory}` | **VERIFIED** | 12 weeks | Appendix E Pricing Form |
| `INITIAL_DURATION` | none | PARTIAL | 3 years | abstract.pdf |
| `INITIAL_DURATION` | none | PARTIAL | 3 years | master RFP |
| `EXTENSION_OPTION` | none | PARTIAL | 2× 1-year options | master RFP |
| `TERM_STATEMENT` | `{period_basis: FIXED}` | PARTIAL | 2 days | master RFP |

The 3-year initial-term observation is independently stated in **two physically separate documents** (the abstract and the master RFP itself) — genuinely strong real-world corroboration — but both instances have `provenance_status: PARTIAL` (grounded excerpt *or* locator, not both, per `_validate_ref`'s strict VERIFIED bar), so `_resolve_term`'s `VERIFIED`-only candidacy filter correctly excludes them from resolution. This is the code's *governed* resolution rule working exactly as designed — no ambiguous or under-verified fact is ever promoted to an asserted value, which is precisely the "governed canonical resolution vs. unsupported conflict suppression" distinction the user asked this trace to prove. **The defect was not in this filtering rule — filtering to VERIFIED-only candidates is correct and was not touched.**

The defect was in **how the single surviving, correctly-VERIFIED, but narrowly-scoped result gets displayed**: `format_contract_term()`, the function that renders `resolved["contract_term"]` into the human/Stage-D-facing string, silently dropped the `scope` dict for every term kind. Before the fix applied in this commissioning run, the formatted output was the bare string `"Initial term: 12 weeks"` — indistinguishable from an opportunity-wide fact, even though the underlying structured `resolved.value[0].scope` correctly says `{"component": "HR Advisory"}`. Since this exact string is what `apply_authoritative_values()` forces into Stage D's non-model-editable `brief.contract_term` (confirmed: this is the literal value recorded in the accepted Phase 4 commissioning artifact, `phase4-boc-2026-026-staged-20260912T131303Z-2cc8af`), a reader of the executive brief would reasonably — but incorrectly — read "Initial term: 12 weeks" as the whole engagement's term, when it is actually one specific service category's pricing-sheet statement, while the better-corroborated, genuinely opportunity-wide 3-year figure is invisible anywhere downstream.

**Fix applied** (see Section D below): `format_contract_term()` now appends a scope qualifier whenever `item.get("scope")` is non-empty. The corrected, recommissioned output for this exact field is:
```
Initial term: 12 weeks (component: HR Advisory; period_basis: WEEKS)
```
No change was made to `_resolve_term`'s candidacy/conflict logic, to the VERIFIED-only bar, or to any validator — this is a strictly additive labeling correction to the display function.

## 8/G. Master RFP contribution

- **Total observations from the master RFP:** 57 of 120 (47.5%).
- **Pages represented among master-RFP-sourced canonical observations:** 1, 3, 4, 5, 9, 10, 11, 12, 13, 14, 15, 18, 19.
- **Fields the master RFP contributes to:** `submission_deadline` only — and there, it is the **sole source** (the only VERIFIED, unscoped, correctly-precision `SUBMISSION_DEADLINE` observation in the whole corpus).
- **Fields where the master RFP participates in an unresolved conflict:** `title`, `client`, `file_number` (all 3 `A`-category conflicts above include master-RFP-sourced observations among their competing values — confirmed via `conflicts_involving_master_rfp` matching all 3 canonical conflict IDs), and — outside Canonical Opportunity's own scope — all 4 `EVALUATION_CONFLICT` items.
- **Fields the master RFP does *not* contribute to at all:** `contract_term` (its own 3-year/2-day/extension-option observations are all `PARTIAL`, correctly excluded from candidacy — see Section 7), `headline_value`, `opportunity_type`, `procurement_model`, `clarification_deadline`.
- **Implicit master-RFP precedence:** **none found.** Nothing in `canonical_opportunity.py` special-cases the master RFP's filename, role, or document identity in any resolution path — its single-field dominance (`submission_deadline`) is a pure consequence of it being the only document with a verified, correctly-shaped observation for that field, not a governance rule favoring it. Where the master RFP's observations disagree with other documents (title/client/file_number), they are treated as ordinary competing candidates and the field goes `CONFLICTED` like any other disagreement — the master RFP does not win by default.

## 9/H. Amendment/revision precedence safety

Verified by direct code inspection (`inspect.getsource` scan plus manual reading of every resolver): **no filename-based, document-role-based, or "latest/revised document wins" precedence rule exists anywhere in `canonical_opportunity.py`.** The only mechanism through which one observation can ever override another is `_apply_supersession()`, and it requires **all** of:
1. `raw.supersession.basis` to be one of a fixed, explicit set (`EXPLICIT_REVISED_VALUE`, `EXPLICIT_EXTENSION`, `EXPLICIT_REPLACEMENT`, `EXPLICIT_SUPERSEDES_STATEMENT`, `EXPLICIT_OLD_TO_NEW_RELATIONSHIP`) — i.e., Stage A must have explicitly asserted a supersession statement from the source text itself;
2. verified provenance on that supersession statement;
3. an exact normalized-text match between the asserted old value and a real target observation's value, and between the asserted new value and the superseding observation's own value.

On this real corpus, `explicit_supersession_declarations_in_input: 0` (already established in the Phase 3 commissioning), so this mechanism never fired here. Nothing about a document being named "Amendment1" or "REVISED" is read by any resolver — confirmed by the keyword scan (the only hit, `"REVISED"`, is a substring match inside the module's own comments, not executable logic). This audit did **not** add any amendment-precedence mechanism, per instruction.

## 10/I. Provenance integrity

For both asserted fields, the full lineage — canonical field → observation → `source_refs` → source document → physical locator/excerpt — was traced and independently checked against the real, persisted evidence:

- **Asserted canonical field count: 2** (`submission_deadline`, `contract_term`)
- **Asserted fields with valid lineage (real physical locator + non-empty grounded excerpt + VERIFIED provenance): 2 / 2**
- **Asserted fields lacking lineage: 0**
- **Unresolved/null field count: 6** (`title`, `client`, `file_number`, `clarification_deadline`, `opportunity_type`, `procurement_model`)
- **Absent field count: 1** (`headline_value`)
- **Fabricated references: 0**
- **Dangling references: 0**

`submission_deadline` traces to the master RFP with a real page-level locator; `contract_term` traces to Appendix E's "HR Advisory pricing scenario" sheet with a grounded excerpt. No asserted field lacks lineage; the fail-closed rule ("any asserted factual field without valid lineage should fail closed") was not triggered because it did not need to be — every asserted field already had it.

## 11/J. Rejected-record safety

The 2 Stage B `ZERO_VALID_PROVENANCE` rejected records — `After-Sales Services` (family `deliverables`) and `Data Breach Investigation and Cooperation` (family `commercial_clauses`) — were searched for by both family-overlap and literal text-match against every one of the 120 canonical observations.

- **Family overlap with Canonical Opportunity's `FAMILIES` set:** none (`deliverables`/`commercial_clauses` are not `IDENTITY`/`MILESTONE`/`CONTRACT_TERM`/`MONETARY`/`PROCUREMENT_MECHANIC`/`DOCUMENT_ROLE`).
- **Text-identity match against every canonical observation's `original_value`:** 0 hits.

```
REJECTED RECORD RE-ENTRY: 0
```

## 12/J. D1/D2/D3 scope safety

Canonical Opportunity's `FAMILIES` set has no submission-rule or page-limit concept at all. A full scan of the ledger for anything resembling "D1"/"D2"/"D3"/page-limit language found exactly **one** incidental hit: a `DOCUMENT_TITLE`-kind observation with `original_value: "Appendix D1 - Rated criteria response form"` — a document title, not a page-limit constraint, and it does not feed any resolved field (`DOCUMENT_TITLE` is not one of `FIELD_KINDS`'s accepted kinds for `title`, which only accepts `OPPORTUNITY_TITLE`). No canonical field aggregates, averages, or otherwise represents the D1=15pg/D2=12pg/D3=10pg page-limit constraints — they remain exclusively a Stage B/C `submission_rules` concept (`_submission_rule_appendix_scope`). No global page-limit field exists, and none was manufactured for this audit.

## 13/K. Determinism

Covered in full above (Section K, immediately after the input-lock section) — build and resolve both proven digest-stable and byte-identical across two independent in-memory runs plus the originally-persisted artifacts, zero LLM calls.

## 14/L. Validators and anomalies

The pre-existing regression suite (`tests/test_canonical_opportunity.py`) plus 2 new tests added by this audit: **36 passed**. Additionally, every anomaly category the user asked for was checked programmatically against the real object:

| Check | Result |
|---|---|
| Conflicting field asserted despite unresolved conflict | 0 found |
| Unresolved field carrying a selected winner | 0 found |
| Canonical value not among contributing source values | 0 found |
| Fabricated canonical observation | 0 found (all 120 trace to real Stage A typed_observations) |
| Missing provenance on an asserted field | 0 found |
| Duplicate canonical observation identity (`collision_ids`) | 0 — `collision_free: true` |
| Invalid scope | 0 found |
| Dangling conflict ID (conflict references a non-existent observation) | 0 found |
| Dangling observation-conflict reference (observation references a non-existent conflict) | 0 found |
| Rejected fact re-entry | 0 (Section 11) |
| Unsupported external inference | 0 found |
| Canonical identity inconsistency | 0 — collision-free |
| **Invalid typed observations correctly fail-closed (diagnostic only)** | **17** — all `family: DOCUMENT_ROLE` with a `semantic_kind` outside the `ROLES` taxonomy (e.g. `DOCUMENT_TITLE`, `PRICING_FORM` mistakenly tagged under the `DOCUMENT_ROLE` family by Stage A extraction). Correctly retained in `integrity_diagnostics.invalid_observations` for diagnosis and correctly excluded from the trusted ledger — this is the fail-closed gate working as designed, not a canonical_opportunity.py defect. `DOCUMENT_ROLE` is not one of the 9 fields `resolve_canonical_opportunity` produces, so this has zero effect on any canonical field's disposition. Not investigated further as a code defect (it is a Stage A extraction-quality characteristic, out of scope for this boundary's commissioning). |

## Defect found and remediated

**Defect:** `format_contract_term()` in `canonical_opportunity.py` silently dropped the `scope` dict from every rendered term component, so a genuinely single-service-category-scoped `contract_term` value ("12 weeks", scoped to HR Advisory only) was rendered identically to how an opportunity-wide term would be rendered — no visual distinction. This value is not a diagnostic aside; it is forced, unconditionally, into Stage D's non-model-editable `brief.contract_term` by `apply_authoritative_values()`, meaning it reaches the executive-facing output as if it were authoritative and unscoped.

**Constitutional impact:** directly implicates the explicit prohibition on converting "ambiguous or conflicting values into a confident canonical assertion" — here the value is not ambiguous (it is correctly VERIFIED) but its *scope* was being silently discarded, producing a confident-looking assertion broader than what the evidence actually supports. It also risks starving a governed downstream reader of the fact that a much better-corroborated (2-independent-source), genuinely opportunity-wide 3-year figure exists in the ledger but was never surfaced anywhere.

**Root cause:** `format_contract_term()` never referenced `item.get("scope")` in any of its 5 rendering branches.

**Fix:** added `_scope_suffix(item)`, a small deterministic helper appending `" (key: value; ...)"` for any non-empty scope dict, and applied it in all 5 branches. No change to `_resolve_term`'s candidacy filtering, `VERIFIED`-only bar, conflict detection, or any validator.

**Regression tests added** (`tests/test_canonical_opportunity.py`):
- `test_scoped_term_display_retains_scope_qualifier` — a component-scoped `INITIAL_DURATION` now renders `"Initial term: 12 weeks (component: HR Advisory)"`.
- `test_unscoped_term_display_has_no_scope_suffix` — an unscoped term is unaffected, proving the fix is purely additive.

**Validation:**
```
py_compile canonical_opportunity.py tests/test_canonical_opportunity.py  -> COMPILE_OK
git diff --check                                                         -> clean
pytest tests/test_canonical_opportunity.py -q                            -> 36 passed
pytest -q (full repository suite)                                        -> 1187 passed, 2 skipped
```
Canonical Opportunity was then recommissioned from the same frozen Phase 1/2/3 artifacts (no Stage A/B/C rerun) — build and resolve determinism re-verified identical to the pre-fix run (the fix touches only a display-formatting function never consulted by `resolve_canonical_opportunity` itself, so `input_digest`/`resolved`/`conflicts`/`observations` are byte-identical before and after).

## 17/M. Human-readable Canonical Opportunity — what Bid Intelligence currently believes is canonically true

| Field | Disposition | Value |
|---|---|---|
| Title | **UNRESOLVED / NULL** | — (2 competing readings: with vs. without the "RFP 2026-026 -" prefix) |
| Client | **UNRESOLVED / NULL** | — (3 competing readings: "Bank of Canada" / "Bank" / "the Bank") |
| File / solicitation number | **UNRESOLVED / NULL** | — (2 competing readings: "2026-026" / "RFP 2026-026") |
| Submission deadline | **ASSERTED** | 2026-09-30 |
| Clarification deadline | **ABSENT** | no verified typed observation exists |
| Contract term | **ASSERTED** | Initial term: 12 weeks (component: HR Advisory; period_basis: WEEKS) |
| Headline / estimated value | **ABSENT** | no typed observation exists |
| Opportunity type | **ABSENT** | not classified from verified mechanics |
| Procurement model | **ABSENT** | not classified from verified mechanics |

No prose was generated to fill any empty field. Where a field shows a dash, that is its entire canonical representation today — a deliberate, governed null, not an omission from this report.

## Artifact index

- `evaluation/bank_of_canada_briefing_pack/canonical_opportunity_commissioning/canonopp-boc-2026-026-20260912T135357Z-060143/`
  - `run_metadata.json`
  - `build_determinism_check.json`, `resolve_determinism_check.json`
  - `canonical_field_audit.json` (complete, all 9 fields)
  - `seven_conflict_trace.json`
  - `clean_resolution_trace.json`
  - `master_rfp_contribution.json`
  - `amendment_precedence_audit.json`
  - `provenance_integrity.json`
  - `rejected_record_safety.json`
  - `d1_d2_d3_scope_safety.json`
  - `validators_and_anomalies.json`
  - `human_readable_canonical_opportunity.json`
- Code changed: [canonical_opportunity.py](../../canonical_opportunity.py) (`format_contract_term` scope-suffix fix), [tests/test_canonical_opportunity.py](../../tests/test_canonical_opportunity.py) (+2 tests)
- Commissioning script: [scripts/commission_canonical_opportunity_bank_of_canada.py](../../scripts/commission_canonical_opportunity_bank_of_canada.py)

---

## FINAL RESPONSE

- **UPSTREAM INPUT LOCK: PASS**
- **CANONICAL CONSTRUCTION: PASS**
- **CANONICAL PROVENANCE VALIDATION: PASS**
- **CONFLICT PRESERVATION: PASS**
- **CANONICAL OPPORTUNITY COMMISSIONING: PASS**
- **Run ID:** `canonopp-boc-2026-026-20260912T135357Z-060143`
- **Production function:** `canonical_opportunity.build_canonical_opportunity` (Stage B) + `resolve_canonical_opportunity`/`apply_legacy_conflict_fallback` (Stage C)
- **LLM calls / cost:** 0 / $0
- **Number of canonical fields:** 9
- **Asserted field count:** 2 (`submission_deadline`, `contract_term`)
- **Unresolved/null field count:** 6 (`title`, `client`, `file_number`, `clarification_deadline`, `opportunity_type`, `procurement_model`)
- **Absent field count:** 1 (`headline_value`)
- **Asserted fields with valid provenance:** 2 / 2
- **Asserted fields lacking provenance:** 0
- **7 conflict outcomes:** 4 × category C (irrelevant to canonical, fully preserved upstream — the 4 EVALUATION_CONFLICT items); 3 × category A (map directly to `title`/`client`/`file_number`, all correctly `CONFLICTED`/`null`); 0 × category D
- **`contract_term` result:** RESOLVED, `STRUCTURED_COMPONENTS`, "Initial term: 12 weeks (component: HR Advisory; period_basis: WEEKS)" — scope-corrected by this audit's fix
- **`submission_deadline` result:** RESOLVED, `EXACT_AGREEMENT`, 2026-09-30, sole-sourced from the master RFP
- **Master RFP contribution:** 57/120 observations (47.5%); sole contributor to `submission_deadline`; participates in all 3 canonical conflicts; zero implicit precedence
- **Rejected-record re-entry count:** 0
- **D1/D2/D3 handling:** not represented in Canonical Opportunity at all (out of family scope); no global page-limit field exists or was created
- **Defects found/fixed:** 1 found and fixed — `format_contract_term()` silently dropped scope qualifiers, making a single-category-scoped term read as opportunity-wide; fixed additively, no validator weakened
- **Tests added:** 2 (`test_scoped_term_display_retains_scope_qualifier`, `test_unscoped_term_display_has_no_scope_suffix`)
- **Full-suite result:** 1187 passed, 2 skipped
- **Runtime:** 1.771s (commissioning script); 86.02s (full suite)
- **Report path:** [evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_CANONICAL_OPPORTUNITY_COMMISSIONING_REPORT.md](evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_CANONICAL_OPPORTUNITY_COMMISSIONING_REPORT.md)
- **Raw artifact paths:** `evaluation/bank_of_canada_briefing_pack/canonical_opportunity_commissioning/canonopp-boc-2026-026-20260912T135357Z-060143/`

Per instruction, this commissioning stops here. **Opportunity Structure and Opportunity Intelligence have not been started.**
