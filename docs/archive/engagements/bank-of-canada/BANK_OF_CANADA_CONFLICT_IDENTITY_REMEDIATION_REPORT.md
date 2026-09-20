# Bank of Canada RFP 2026-026 — Conflict Identity Remediation Report

**Scope:** dedicated conflict-identity contract and cross-boundary
reconciliation audit, triggered by Executive Opportunity Brief
commissioning failing at "Opportunity Intelligence Support Binding
Derivation" with `CONF-EVAL-1..4` having "no governed reference exists in
any admitted publication" — after the provenance-granularity remediation
had already made Canonical Opportunity Publication and Opportunity
Structure Publication pass legitimately. No Stage A rerun. No LLM calls.
Frozen, authoritative lineage: `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5`
/ `phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031` /
`phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8`.

---

## A. Complete conflict identity map

Reading confirms **three independent conflict-producing systems**, flattened
into one undifferentiated list by `extractor.reconcile_package_facts()`
(the real Stage C entry point):

```python
def reconcile_package_facts(normalized_facts, package_files):
    conflicts = detect_document_conflicts(normalized_facts, package_files)          # (1)
    conflicts.extend(structured_deliverable_conflicts(..., start_index=len(conflicts)+1))    # (1)
    conflicts.extend(structured_commercial_clause_conflicts(..., start_index=len(conflicts)+1))  # (1)
    canonical = resolve_canonical_opportunity(canonical)                             # (2)
    canonical = apply_legacy_conflict_fallback(canonical, conflicts)                 # one-way, text-heuristic
    conflicts.extend(canonical.get("conflicts", []))                                 # (2)
    return conflicts
```

| Boundary/module | Conflict type | Identity producer | Identity shape | Identity inputs | Stable across rebuild? | Consumers |
|---|---|---|---|---|---|---|
| `extractor.detect_document_conflicts` | DATE, EVALUATION, SUBMISSION, MANDATORY, COMMERCIAL, SCOPE review items | single global `conflict_idx = 1` counter, incremented across every family in fixed code order | `CONF-{FAMILY}-{n}` (e.g. `CONF-EVAL-2`) | none — pure sequence position | **NO** — shifts if any earlier-processed family's conflict count changes (see Section C) | `stage_c_conflicts.json`; `opportunity_intelligence.py` (previously, as FUTURE_ENTITY support) |
| `contract_hygiene.structured_deliverable_conflicts` / `structured_commercial_clause_conflicts` | deliverable/clause structural conflicts | `start_index` continues the SAME counter from (1) | `CONF-HYGIENE-{n}` / `CONF-CLAUSE-{n}` | none — pure sequence position | **NO**, same reason | same as above |
| `canonical_opportunity._conflict` (via `resolve_canonical_opportunity`) | opportunity-level FIELD_KINDS: title, client, file_number, contract_term, headline_value, opportunity_type, procurement_model | `_id("conf_", {version, field, sorted(observation_ids), values})` (SHA-256) | `conf_<64-hex>` | schema version + resolved field name + sorted participating observation_ids + incompatible values | **YES** — deterministic, order-invariant, content-sensitive (Section D) | `canonical.get("conflicts")`; **published verbatim** by Canonical Opportunity Publication as governed `CONFLICT`-authority objects (`object_id == conflict_id`) |
| `opportunity_structure.build_opportunity_structure` (inline conflict block, `CONFLICT_FIELDS_BY_FAMILY`) | structural per-record conflicts: `EVALUATION_CRITERION.role`, `EVALUATION_CRITERION.weight`, `SUBMISSION_RULE.*` | `_id("struct_conf_", {version, family, record_id, field, values})` (SHA-256) | `struct_conf_<64-hex>` | schema version + family + record_id + field + values | **YES**, same reason | `structure.get("conflicts")`; **published verbatim** by Opportunity Structure Publication (`object_id == conflict_id`) |
| `opportunity_intelligence.py` (`_record_id("conflicts", item, i)`) | consumer of (1)+(2) merged | returns `item["conflict_id"]` verbatim if present, else its own content hash fallback | passthrough of whichever producer's ID the item already carries | n/a (pure passthrough) | inherits producer's stability | `evidence_used` (FUTURE_ENTITY support), `unresolved_conflict_ids` |
| `opportunity_intelligence_publication.publish_opportunity_intelligence` | consumer of `analysis.unknowns` | requires `binding_map` to exactly cover `analysis.evidence_used`; builds `unknown_relationships` from `missing_evidence + unresolved_conflict_ids + ambiguous_observation_ids` | n/a — resolves by exact `entity_id` string equality against supplied `OpportunitySupportBinding`s | n/a | n/a | `executive_opportunity_understanding.py` (indirectly, via the "unknowns" object) |
| `stage_d_projection.validate_stage_d_response` | consumer only | pointer/support_id/evidence_catalog mechanism | n/a | n/a | n/a | not part of the duplicated-identity population (confirmed in the prior provenance-granularity remediation) |

**`apply_legacy_conflict_fallback(canonical, legacy_conflicts)`** is a
pre-existing, one-way, keyword-text heuristic (`"clarification deadline"`,
`"submission deadline"`, `"contract term"` substrings only) that can inject
a legacy ordinal `CONF-*` id directly into a resolved field's `conflict_ids`
— **without** adding a matching entry to `canonical["conflicts"]`. This is
architecturally the *same class of defect* as the one being remediated here
(an ungoverned ordinal id appearing somewhere a governed id is expected),
but confirmed **dormant** in the real corpus (Section B) and out of scope —
documented as a remaining limitation (Section Q).

---

## B. Eight-conflict cross-boundary trace

The authoritative Stage C output (`stage_c_conflicts.json`) contains exactly
8 conflicts. Traced individually:

| Stage C conflict ID | Family | Semantic subject | Canonical Opp. identity | Opp. Structure identity | Publication object identity | Same object as Stage C entry? |
|---|---|---|---|---|---|---|
| `CONF-EVAL-1` | EVALUATION_CONFLICT | "Corporate Profile" scoring weight internal discrepancy (5 vs 10 points, same doc) | none | none | none | n/a — never published anywhere |
| `CONF-EVAL-2` | EVALUATION_CONFLICT | "Team Experience" scoring weight internal discrepancy | none | none | none | n/a |
| `CONF-EVAL-3` | EVALUATION_CONFLICT | "Methodology" scoring weight internal discrepancy | none | none | none | n/a |
| `CONF-EVAL-4` | EVALUATION_CONFLICT | "Relevant Experience and References" scoring weight internal discrepancy | none | none | none | n/a |
| `conf_64da8f52...` | CONTRACT_TERM / INITIAL_DURATION | `"3 years"` (free text) vs `{"duration":"3","unit":"years"}` (structured) | **same object**, `resolved.contract_term.conflict_ids == ["conf_64da8f52..."]` | none | `CONFLICT` object, `object_id = conf_64da8f52...` | **YES** — literally the same dict, appended in place |
| `conf_68a3a3a5...` | IDENTITY / BUYER_NAME | `"bank of canada"` / `"bank"` / `"the bank"` | same object | none | same | YES |
| `conf_8c65820f...` | IDENTITY / SOLICITATION_NUMBER | `"2026-026"` / `"rfp 2026-026"` | same object | none | same | YES |
| `conf_a06e6957...` | IDENTITY / OPPORTUNITY_TITLE | full title vs two abbreviated variants | same object | none | same | YES |

**Corrected framing, superseding the earlier, less precise investigation
summary:** `CONF-EVAL-1..4` are **not** the same conflicts as Opportunity
Structure's own 4 `EVALUATION_CRITERION` conflicts. Rebuilding Opportunity
Structure from the identical frozen lineage shows its 4 real conflicts are
all `field: "role"` (values `"Award Criterion"` / `"Structural Container"` /
`"Unknown"` — a classification ambiguity), never `field: "weight"`. The
`CONF-EVAL-N` scoring-weight discrepancies and Opportunity Structure's
`role`-classification conflicts are two **semantically unrelated**
populations that merely share a family label and, coincidentally, a count
of 4 each. No crosswalk between them exists or should exist.

---

## C. `CONF-EVAL-1..4` stability analysis

Read directly from `extractor.detect_document_conflicts` (lines ~1522–2213)
and `reconcile_package_facts` — confirmed by direct code reading and by
regression tests (`tests/test_conflict_identity_remediation.py`, Section D):

- **Ordinal, not content-derived.** `conflict_idx = 1` is a single counter
  incremented across DATE → EVALUATION → SUBMISSION → MANDATORY →
  COMMERCIAL → SCOPE → HYGIENE → CLAUSE, in fixed code order, regardless of
  content.
- **Not stable if an unrelated, earlier-processed conflict is inserted.**
  `test_conf_eval_ordinal_id_shifts_when_an_earlier_family_conflict_is_inserted`
  proves this directly: the identical evaluation-weight discrepancy is
  `CONF-EVAL-1` alone, and `CONF-EVAL-2` once one unrelated `CONF-DATE-1`
  conflict is detected first in the same run.
- **Not stable under reordering** of the same family's own candidate list
  (Python dict iteration order over `eval_by_identity`, itself determined
  by Stage B's own emission order) — not independently re-tested here since
  it follows directly from the same mechanism.
- **Not derived from semantic content at all.**
  `test_conf_eval_ordinal_id_is_not_derived_from_semantic_content` proves
  two entirely unrelated evaluation-weight discrepancies (different
  criterion, different point values) receive the **identical** id
  (`CONF-EVAL-1`) whenever each happens to be first in its own,
  independent run.
- **Intended only for display / human clarification requests.** Every
  `detect_document_conflicts` entry carries `topic`, `reason`, `assessment`,
  `recommended_action` — prose fields with no counterpart in the governed
  object schema — consistent with a "flag for review" mechanism, never a
  durable identity.

**Conclusion: `CONF-EVAL-N` (and its `CONF-DATE/SUB/MAND/COMM/SCOPE/HYGIENE/CLAUSE`
siblings) must never be treated as a durable, citable identity by any
downstream module.**

---

## D. Hashed-ID analysis

**`canonical_opportunity._conflict(field, observations, values)`:**

```python
cid = _id("conf_", {
    "version": SCHEMA_VERSION,
    "field": "/resolved/" + field,
    "observations": sorted(o["observation_id"] for o in observations),
    "values": values,
})
```

Confirmed via direct unit tests
(`test_governed_conflict_id_is_deterministic_across_identical_rebuilds`,
`test_governed_conflict_id_is_invariant_to_observation_order`,
`test_governed_conflict_id_differs_for_different_field`,
`test_governed_conflict_id_differs_for_different_values`,
`test_governed_conflict_id_differs_for_different_participating_observations`):
deterministic, invariant to observation ordering (`sorted(...)` in the
preimage), and sensitive to field/values/participating-observation-set
changes. **`scope` is not an explicit hash input** — it is carried
correctly only because different scopes always correspond to different
participating `observation_id` sets in real production data (the resolvers
group observations by scope before ever calling `_conflict`); this is a
documented, non-fabricating property, not a defect, since it never actually
allows two differently-scoped conflicts to collide (that would require two
different scopes producing the identical observation-id set, which cannot
happen — an observation belongs to exactly one scope).

**`opportunity_structure.py`'s inline conflict block** (`_id("struct_conf_",
{version, family, record_id, field, values})`) is structurally identical in
kind (deterministic, content-derived) and was not touched.

**No volatile fields** (list index, generated record IDs not already part
of stable content, wall-clock time) enter either hash.

---

## E. Object-ID vs governed-conflict-ID semantics

Both `canonical_opportunity_publication.py` (line ~574) and
`opportunity_structure_publication.py` (line ~462) publish their conflict
objects with `object_id = conflict["conflict_id"]` **verbatim** — no
re-derivation, no re-hashing, no separate identity layer. Object identity
and governed conflict identity are the **same value** for both boundaries;
no conflation defect exists there. This is correct and was left unchanged.

The actual defect was never a conflation of object-ID vs conflict-ID within
a single boundary — it was that `opportunity_intelligence.py` and
`opportunity_intelligence_publication.py` treated **an entity with no
publication path at all** (`CONF-EVAL-N`) as if it necessarily had one,
because both populations arrive through the same flat `conflicts` list with
no discriminating field beyond the `conflict_id` string's own format.

---

## F. Support-binding failure root cause

Exact trace for `CONF-EVAL-1`:

1. **Originating Stage C conflict:** `detect_document_conflicts`'s internal
   evaluation-weight-discrepancy branch, id `CONF-EVAL-1`.
2. **Downstream object that references it:** `opportunity_intelligence.py`'s
   `analyze()` (before this fix) added `links[("conflicts", 0)] =
   EvidenceSupport(FUTURE_ENTITY, "CONF-EVAL-1", ())`, making it part of
   `analysis.evidence_used`; `unresolved_conflict_ids` also listed it.
3. **ID stored on that object:** `CONF-EVAL-1` (the raw Stage C string,
   verbatim — `_record_id`'s `("conflict_id",)` lookup for section
   `"conflicts"` returns it unchanged).
4. **Support binder lookup key:** the commissioning script's own support
   resolution loop (and, deeper, `publish_opportunity_intelligence`'s
   `binding_map`) looked for a `GovernedObjectReference` whose `object_id ==
   "CONF-EVAL-1"` among Evidence Publication, Canonical Opportunity
   Publication, and Opportunity Structure Publication's admitted references.
5. **Available publication objects:** none — Canonical Opportunity
   Publication only publishes the 4 `conf_<hash>` conflicts (Section B);
   nothing anywhere publishes `detect_document_conflicts`'s ordinal output.
6. **Why lookup fails:** the entity genuinely, structurally has no governed
   representation — not a wrong ID, not a stale artifact, not a
   serialization loss.
7. **Semantic match otherwise exact:** yes — the *conflict as a real-world
   fact* (differing evaluation weights) is genuine and correctly detected;
   the failure is purely about a governed-identity contract that this
   entity was never designed to satisfy.

**Classification: independently-generated identity with no crosswalk, by
architectural design of the two producing systems — not a wrong ID, not a
missing parent reference, not stale data, not a serialization bug.** No
string heuristics, fuzzy matching, or Bank-of-Canada-specific handling was
used to reach or fix this diagnosis.

---

## G. Chosen identity contract

Neither pure MODEL A, B, nor C describes the architecture actually found.
The real, evidence-backed contract is a **two-population model**:

> **Governed conflicts** (`canonical_opportunity._conflict`'s FIELD_KINDS
> conflicts; `opportunity_structure.py`'s structural
> `CONFLICT_FIELDS_BY_FAMILY` conflicts) use **MODEL B**: one deterministic,
> content-derived hash identity, minted once by the producing boundary and
> referenced **verbatim** — never re-derived, never re-hashed — by every
> downstream consumer, including as the published `object_id`.
>
> **Stage B/C's own cross-document reconciliation advisory findings**
> (`CONF-DATE/EVAL/SUB/MAND/COMM/SCOPE/HYGIENE/CLAUSE`) are **not** governed
> conflicts. They carry only a Stage-C-local, non-durable ordinal *display*
> label, are never published as governed objects, and must never be cited
> by any downstream module's support/reference-binding machinery as if they
> required resolution to one.

This is the model the architecture's own closed `FIELD_KINDS`/
`CONFLICT_FIELDS_BY_FAMILY` sets already, deliberately implement for
governed conflicts (confirmed: `canonical_opportunity.py`'s `FAMILIES` /
`FIELD_KINDS` never include `EVALUATION_CRITERION` or any Stage-B
structural section at all — a closed, intentional set of six opportunity-
level executive-fact families). The defect was never in the governed half;
it was `opportunity_intelligence.py` failing to distinguish the two
populations before citing them uniformly. **The fix was chosen to match
the already-existing architectural boundary, not to expand it** — no new
publication responsibility was invented for the advisory population, and
neither `FIELD_KINDS` nor `CONFLICT_FIELDS_BY_FAMILY` was touched.

---

## H. Backward compatibility

- `CONF-*` ordinal ids are **not** a public API, not stored in any
  database, not user-facing outside `stage_c_conflicts.json` and (now, as
  before) `unresolved_conflict_ids`'s plain string content — they remain
  fully present there, unchanged, satisfying full backward compatibility
  for anything reading that field.
- Nothing was renamed, migrated, or aliased. `apply_legacy_conflict_fallback`
  (a pre-existing consumer of the SAME ordinal ids) was not touched.
- `AnalystUnknowns.unresolved_conflict_ids`'s **schema** is unchanged (still
  `tuple[str, ...]`); only which of those strings additionally receive a
  `FUTURE_ENTITY` evidence_used citation changed.

No migration was needed because no identity format changed — only which
downstream field is permitted to reference an already-existing, unchanged
identity.

---

## I. Crosswalk

Persisted, reproducible artifact:
`evaluation/bank_of_canada_briefing_pack/conflict_identity_remediation/conflict_identity_crosswalk.json`
(built by `scripts/build_conflict_identity_crosswalk_bank_of_canada.py`).
8 total conflicts: 4 `GOVERNED` (each with `governed_conflict_id` ==
`canonical_opportunity_publication_object_id`, its real, immutable
`conf_<hash>`), 4 `ADVISORY` (`governed_conflict_id: null`,
`citable_as_future_entity_evidence_used: false`, `legacy_display_only:
true`). The artifact also separately lists Opportunity Structure's own 4
`role`-family conflicts, explicitly labeled unrelated to `CONF-EVAL-N`
(Section B).

This artifact is diagnostic/audit tooling for this remediation, not a new
permanent production component — the production fix requires no runtime
crosswalk lookup (Section G's contract is enforced by set-membership
against `canonical.get("conflicts")`, computed directly from already-loaded
data, not from this file).

---

## J. Tests

**20 new tests** in `tests/test_conflict_identity_remediation.py` (all
pass), covering:

- **Section A** (opportunity_intelligence.py): only governed conflicts
  become citable `FUTURE_ENTITY` support; `unresolved_conflict_ids` still
  lists governed **and** advisory conflicts (zero loss); `total_conflicts`
  still counts both; `validate_opportunity_analysis` still passes for
  advisory-only and mixed populations (its "never resolve or omit a
  conflict" invariant is checked against `unresolved_conflict_ids`, which
  is untouched).
- **Section B** (opportunity_intelligence_publication.py): a `FUTURE_ENTITY`
  conflict absent from `evidence_used` (the new, correct shape) publishes
  with an honest, disclosed absence of a relationship instead of failing;
  a governed `FUTURE_ENTITY` conflict **with** a supplied binding still
  gets a real relationship; an **ambiguous** conflict reference (two
  distinct governed targets claiming the same id) still fails closed
  unconditionally — the leniency covers only a *missing* target, never an
  ambiguous one; `missing_evidence` (REQUIREMENT) and
  `ambiguous_observation_ids` (OBSERVATION) with no binding still fail
  closed exactly as before — the leniency does not leak beyond
  `unresolved_conflict_ids`.
- **Section C** (`canonical_opportunity._conflict`): deterministic across
  identical rebuilds; invariant to observation order; differs for
  different field / values / participating observations; id format is
  always `conf_<64-hex>`.
- **Section D** (`extractor.detect_document_conflicts`): the identical
  semantic evaluation conflict gets a **different** ordinal id purely
  because an unrelated, earlier-processed conflict shifted the counter;
  two **unrelated** evaluation conflicts can get the **identical** ordinal
  id; ordinal ids never collide in format with either governed prefix
  (`conf_` / `struct_conf_`).

## K. Full suite result

```
py_compile canonical_opportunity.py opportunity_structure.py
           opportunity_structure_publication.py opportunity_intelligence.py
           opportunity_intelligence_publication.py extractor.py
           contract_hygiene.py executive_opportunity_understanding.py
           executive_opportunity_brief.py
           tests/test_conflict_identity_remediation.py            -> COMPILE_OK

pytest tests/test_conflict_identity_remediation.py
       tests/test_opportunity_intelligence.py
       tests/test_opportunity_intelligence_publication.py
       tests/test_canonical_opportunity.py
       tests/test_canonical_opportunity_publication.py
       tests/test_opportunity_structure.py
       tests/test_opportunity_structure_publication.py
       tests/test_evidence_grounding.py
       tests/test_canonical_observation_binding.py
       tests/test_opportunity_structure_binding.py
       tests/test_executive_opportunity_understanding.py
       tests/test_executive_opportunity_brief.py
       tests/test_stage_d_projection.py                           -> 333 passed, 1 skipped

git diff --check                                                   -> exit 0 (line-ending
                                                                        warnings only)

pytest (full repository suite)                                     -> 1242 passed, 2 skipped,
                                                                        19 subtests passed
```

---

## L. Refreshed deterministic artifacts

No Stage A rerun. No new Stage B/C run IDs — `canonical_opportunity.py`
and `opportunity_structure.py` were **not modified** by this remediation
(only `opportunity_intelligence.py` and
`opportunity_intelligence_publication.py`), so Canonical Opportunity's and
Opportunity Structure's own byte-identical output from the same frozen
`phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8` facts is
unchanged. Opportunity Intelligence's analysis is computed fresh,
deterministically, in-process on every commissioning run (never persisted
as its own standalone Stage between runs in this pipeline) — no separate
"Opportunity Intelligence run ID" exists to refresh. What changed is the
**result** of re-running the existing, unmodified
`scripts/commission_executive_opportunity_brief_bank_of_canada.py`.

---

## M. Canonical Opportunity Publication: **PASS**

134 objects, within run `eob-boc-2026-026-20260912T173422Z-783064`. Unaffected
by this remediation (module untouched); re-confirmed passing.

## N. Opportunity Structure Publication: **PASS**

696 objects, same run. Unaffected by this remediation (module untouched);
re-confirmed passing.

## O. Executive Opportunity Understanding result: **PASS**

`coverage_records: 33`, `detail_references: 33`, `index_sections: 13`.
Every conflict remains visible: the "unknowns" object's own semantic field
`unresolved_conflict_ids` lists all 8 raw ids (`CONF-EVAL-1..4` and the 4
`conf_<hash>` ids) verbatim; its 464 `RELATED`/`affected-entity`
relationships include a real, resolved target for each of the 4 governed
conflicts (confirmed by direct inspection of
`opportunity_intelligence_publication.json`) and correctly omit one for
each of the 4 advisory conflicts — an honest disclosed absence, not a
silent drop, since the raw id remains in the semantic field regardless.

**Pre-existing, unrelated gap discovered while verifying this (not caused
by, and not fixed by, this remediation):** `DetailRegister.conflicts`
(the `executive_opportunity_understanding.py` field with
`AuthorityClass.CONFLICT`) is **always empty** — `_RULES` (the mapping from
Opportunity Intelligence Publication's own object classes to
`DetailRegister` collection names) has no entry that routes anything to
collection `"conflicts"`; the "unknowns" object (which does carry the real
conflict relationships) routes to collection `"unknowns"` instead. This is
dead, unreachable code for the `conflicts` field specifically, present
before this remediation and unrelated to conflict identity — the conflicts
are correctly represented, just under `detail_register.unknowns` rather
than `detail_register.conflicts`. Documented as a remaining limitation
(Section Q), not fixed here (out of scope: a `DetailRegister`
routing/`_RULES` change, not a conflict-identity change).

## P. EOB recommission result: **PASS**

`sections: 13`, `coverage_ledger: 33`, `detail_register: 33`,
`markdown_chars: 16,053,217`. Determinism confirmed:
`determinism_check.json` shows two independent
`build_executive_opportunity_brief()` calls within the same run producing
`identical: true` and the same `brief_id`
(`executive-brief-629c785ebbb8417871fc99fea4b371ec83ad0f83bb5a1cc03db7addb419b81f6`).

**EOB run ID:** `eob-boc-2026-026-20260912T173422Z-783064`

---

## Q. Remaining architectural limitations

1. **`DetailRegister.conflicts` is permanently unpopulated** (Section O) —
   pre-existing, unrelated to conflict identity, discovered only because
   this remediation is the first successful end-to-end run to reach this
   code path. Conflicts remain fully visible via `detail_register.unknowns`
   instead; no information is lost, but the dedicated `conflicts` field is
   dead code.
2. **`apply_legacy_conflict_fallback`'s text-keyword field matching**
   (`clarification_deadline` / `submission_deadline` / `contract_term`
   only) can, if it ever fires, inject a raw ordinal `CONF-*` id directly
   into a resolved field's `conflict_ids` without a matching entry in
   `canonical["conflicts"]` — the same class of defect remediated here, in
   a different, currently-dormant code path. Confirmed inactive in this
   corpus (Section B); not fixed, since fixing dormant code with no
   observed failure risks scope creep the user's process explicitly warns
   against ("do not blindly refactor").
3. **`canonical_opportunity.py`'s `_source_segment`** stops at the first
   marker satisfying `_locator_matches` rather than searching exhaustively
   (documented in the prior provenance-granularity remediation report,
   Section E/G) — unrelated to conflict identity, restated here only for
   completeness since both remediations touch neighboring code.

---

## R. Artifact index

**Code changed:**
- `opportunity_intelligence.py` — conflict linking restricted to governed
  conflicts (membership in `canonical.get("conflicts")`); `evidence_used`
  no longer cites advisory ordinal conflicts; `unresolved_conflict_ids`,
  `total_conflicts`, `validate_opportunity_analysis` all unchanged.
- `opportunity_intelligence_publication.py` — `publish_opportunity_intelligence`'s
  `unknown_relationships` construction: a `FUTURE_ENTITY`-sourced
  `unresolved_conflict_ids` entry with zero candidates now publishes with
  an honest, omitted relationship instead of failing; ambiguity (>1
  candidate) still fails unconditionally; `missing_evidence` /
  `ambiguous_observation_ids` still fail closed on zero candidates exactly
  as before.

**Tests added:**
- `tests/test_conflict_identity_remediation.py` — 20 new tests.

**Diagnostics (new, persisted, reproducible):**
- `scripts/build_conflict_identity_crosswalk_bank_of_canada.py`
- `evaluation/bank_of_canada_briefing_pack/conflict_identity_remediation/conflict_identity_crosswalk.json`

**Commissioning run artifact:**
- `evaluation/bank_of_canada_briefing_pack/executive_opportunity_brief_commissioning/eob-boc-2026-026-20260912T173422Z-783064/` — full PASS through Executive Opportunity Brief, including `boundaries.json`, `opportunity_intelligence_analysis.json`, `opportunity_intelligence_publication.json`, `executive_opportunity_understanding.json`, `executive_opportunity_brief.json`, `executive_opportunity_brief.md`, `determinism_check.json`.

---

## FINAL RESPONSE

- **CONFLICT IDENTITY REMEDIATION: PASS**
- **Root cause:** `extractor.reconcile_package_facts()` flattens two
  structurally unrelated conflict populations — governed, hash-identified
  FIELD_KINDS/structural conflicts (published, resolvable) and Stage-C-local
  ordinal advisory review items (never published, never resolvable) — into
  one list with no discriminating field. `opportunity_intelligence.py` cited
  both uniformly as governed-reference-requiring `FUTURE_ENTITY` support.
- **Identity model before:** undifferentiated — every conflict in the
  merged list treated as if it must resolve to a governed reference.
- **Identity model after:** two-population model (Section G) — governed
  conflicts (Model B, unchanged) remain citable support requiring
  resolution; Stage-C-local advisory conflicts are display-only, counted
  and fully visible in `unresolved_conflict_ids`, never cited as support
  requiring a governed reference.
- **`CONF-EVAL-N` role after remediation:** permanently advisory/display-
  only — confirmed unstable under insertion and content-independent
  (Section C); never treated as a durable identity anywhere.
- **Governed conflict ID format:** `conf_<sha256-hex>`
  (`canonical_opportunity.py`) / `struct_conf_<sha256-hex>`
  (`opportunity_structure.py`), both deterministic, order-invariant,
  content-sensitive (Section D).
- **Number of current governed conflicts:** 4 (title, client, file_number,
  contract_term) out of 8 total Stage C conflicts.
- **Conflicts successfully cross-boundary mapped:** 4/4 governed conflicts
  (100%) — each traced from Stage C through Canonical Opportunity
  Publication to the Opportunity Intelligence "unknowns" relationship
  graph, identity unchanged end to end.
- **Orphan conflict references:** 0 after remediation (the 4 advisory
  conflicts are no longer cited as if they had a governed target; they
  remain visible as plain identifiers, not orphaned references).
- **Ambiguous conflict mappings:** 0 in the real corpus; the ambiguity
  fail-path is exercised and proven by
  `test_ambiguous_future_entity_conflict_still_fails_even_though_conflict_ids_are_lenient`.
- **Files changed:** `opportunity_intelligence.py`,
  `opportunity_intelligence_publication.py`.
- **Tests added:** 20
  (`tests/test_conflict_identity_remediation.py`).
- **Full suite result:** 1242 passed, 2 skipped, 0 failed (full
  repository); 333 passed, 1 skipped (targeted suites); `git diff --check`
  clean.
- **Refreshed Stage C run ID:** none required —
  `phase3-boc-2026-026-stagec-refresh-20260912T144353Z-3194c8` unchanged.
- **Refreshed Canonical Opportunity run ID:** none required — module
  untouched.
- **Refreshed Opportunity Structure run ID:** none required — module
  untouched.
- **Refreshed Opportunity Intelligence run ID:** not applicable — computed
  fresh, in-process, deterministically on every commissioning run; not a
  separately persisted Stage.
- **Canonical Opportunity Publication: PASS** (134 objects)
- **Opportunity Structure Publication: PASS** (696 objects)
- **EOU: PASS** (33 coverage records, 13 index sections)
- **EOB recommission: PASS** (13 sections, deterministic,
  `identical: true` across two independent builds)
- **EOB run ID:** `eob-boc-2026-026-20260912T173422Z-783064`
- **Remaining warnings:** 3, listed in Section Q — none block acceptance,
  none are conflict-identity defects.
- **Report path:** `BANK_OF_CANADA_CONFLICT_IDENTITY_REMEDIATION_REPORT.md`
- **Raw artifact paths:** listed in full in Section R.

**Per the standing instruction: STOPPING here. Executive Briefing Pack is
NOT built, even though EOB passed.** Explicit authorization to proceed to
pack composition must come from the user after reviewing this remediation
and the provenance-granularity remediation together.
