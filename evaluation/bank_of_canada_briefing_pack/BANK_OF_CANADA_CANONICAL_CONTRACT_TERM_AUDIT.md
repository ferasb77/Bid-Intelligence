# Bank of Canada RFP 2026-026 — Canonical Contract-Term Candidacy and Scope Audit

**Audit run ID:** `canonopp-boc-2026-026-20260912T142551Z-34a031`
**Regenerated Stage B (canonical sub-object only):** `phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031`
**Prior Canonical Opportunity commissioning run (superseded for `contract_term`/`procurement_model` only):** `canonopp-boc-2026-026-20260912T135357Z-060143`
**Authoritative lineage (unchanged):** Phase 1 `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5` · Stage B `phase2-boc-2026-026-stageb-20260912T125051Z-91a22b` (all families except `_canonical_opportunity` remain this exact artifact — verified byte-identical below)
**LLM calls: 0. Stage A: not rerun. API cost: $0.**

---

## 1. Semantic contract of `contract_term`

Traced through the actual implementation, not inferred from the field name:

- **`resolved["contract_term"]["value"]` is a `list`, not a scalar** (`_resolve_term`'s return: `"value": sorted(values, key=canonical_json)` where `values = [{"kind": ..., "value": ..., "scope": ...}, ...]`). No other canonical field (`title`, `client`, `submission_deadline`, `headline_value`) returns a list — this one is structurally distinct by design.
- **Candidate grouping is explicitly scope-aware**: `groups` keys on `(semantic_kind, canonical_json(normalized_value), canonical_json(scope))`; `by_kind` (used for conflict detection) keys on `(kind, scope)`. Two observations with the *same* `kind` but *different* `scope` are placed in separate buckets and **never compared against each other** for agreement or conflict.
- **`format_contract_term()` iterates every item in the list independently**, joining rendered parts with `"; "` — the formatter is already built to display multiple, distinct term components side by side.
- **Stage D's `apply_authoritative_values()`** calls `format_contract_term(term)` once and assigns the whole formatted string to `brief["contract_term"]` — it does not further interpret or select among items.
- **Opportunity Structure / Opportunity Intelligence / Buyer Brief / Executive Opportunity Brief / Executive Briefing Pack**: none of these modules reference `contract_term`, `format_contract_term`, or `_canonical_opportunity` at all (confirmed by direct grep of `opportunity_structure.py`, `opportunity_structure_binding.py`, `opportunity_structure_publication.py`, `opportunity_intelligence.py`, `executive_opportunity_brief.py`, `executive_briefing_pack.py` — zero hits beyond one doc-comment). `opportunity_structure.py`'s own docstring confirms its `stage_facts` input is the Stage B/C `normalized_facts` mapping, not Canonical Opportunity's resolved view.

**Conclusion: interpretation D is what the code actually implements** — `contract_term` is a canonical *family* capable of holding multiple, independently-resolved, scope-tagged duration components (an opportunity-wide initial term, a service-category-scoped engagement duration, extension options, etc.), not a single scalar forced to pick one winner. Interpretation A (a single opportunity-wide scalar) and interpretation C (only scoped values) are both narrower than what the schema, resolver, and formatter actually support. This was confirmed empirically, not just from code reading: fixing the defect below (Section 5) produces exactly this — an opportunity-wide item and a scoped item coexisting without conflict (new regression test `test_scoped_and_unscoped_contract_terms_coexist_without_conflict`).

## 2. Complete `contract_term` candidate inventory

All 5 `CONTRACT_TERM`-family observations in the ledger — the entire pool, not a sample:

| Observation ID | Source doc | Original text | Semantic kind | Scope | Parsed value | Stage B validation (before fix) | Canonical candidacy (before) | Provenance (after fix) | Candidacy (after) | Rejection reason (before) |
|---|---|---|---|---|---|---|---|---|---|---|
| `obs_2282cb0…3139a` | Appendix E Pricing Form.xlsx, sheet "HR Advisory pricing scenario" | "approximately twelve (12) weeks" | INITIAL_DURATION | `{component: HR Advisory, period_basis: WEEKS}` | `{duration:12, unit:weeks}` | VERIFIED | admitted | VERIFIED | admitted | — |
| `obs_95004a6…3e34b4` | abstract.pdf, p.1, "Details" | "Duration: 3 years" | INITIAL_DURATION | `{}` (unscoped) | `"3 years"` (bare string — see Section 4) | **PARTIAL** | excluded | **VERIFIED** | admitted | grounding failed: missing space after colon in raw text (`"Duration:3 years"`) |
| `obs_a769a7b…e13622` | Master RFP, p.14, §4.2 | "The term of each agreement will be for a period of three (3) years, with the option to extend for up to two (2) additional one-year terms, if required." | INITIAL_DURATION | `{}` (unscoped) | `{duration:3, unit:years}` | **PARTIAL** | excluded | **VERIFIED** | admitted | zero-length segment: `section: "4.2"` requested against a page-only marker with no section tag |
| `obs_e8a6ffe…dd925b5` | Master RFP, p.14, §4.2 (same excerpt) | "option to extend for up to two (2) additional one-year terms, if required" | EXTENSION_OPTION | `{}` | `{duration:1, option_count:2, optional:1, unit:years}` | **PARTIAL** | excluded | **VERIFIED** | admitted | same section-locator gap + hyphenated line-wrap ("one-\nyear") broke exact-substring grounding |
| `obs_fa5b0a7…572aa78` | Master RFP, p.3, §1.2 RFP timetable | "Rectification period Two (2) days" | TERM_STATEMENT | `{period_basis: FIXED}` | `{duration:2, unit:DAYS}` | **PARTIAL** | excluded | **VERIFIED** | admitted | section-locator gap (same class of defect, different page/section) |

**Every rejection before the fix traces to the same two root causes (Section 5), not five independent problems.** All 5 observations are now admitted candidates; none required inventing a locator or excerpt that wasn't already present.

## 3. The 3-year term, traced

Two documents state an opportunity-wide (unscoped) `INITIAL_DURATION` of "3 years":

- **abstract.pdf**, page 1, section "Details": raw text `"Purchase Type\nDuration:3 years\nOption: 2 years"`. Stage A's excerpt: `"Duration: 3 years"`. Parsed to the *bare string* `"3 years"` (Stage A's raw typed_observation for this document did not populate structured `duration`/`unit` fields, so `_normalized_value()` fell back to `_text(value)`).
- **The master RFP**, page 14, section "4.2": raw text `"...The term of each agreement will be for a period of three (3) years, with the option to extend for up to two (2) additional one-\nyear terms, if required."`. Parsed to the *structured dict* `{duration: "3", unit: "years"}` (this document's Stage A extraction did populate `duration`/`unit`).

**Do these genuinely corroborate each other, or only share the digit 3?** Established from the structured facts, not the surface text:
- Both are typed as the same `semantic_kind` (`INITIAL_DURATION`) with the same `scope` (`{}`, unscoped) — Stage A itself classified them as the same *kind* of fact.
- Both literally state "3 years" as the duration figure.
- **But their `normalized_value` representations are not the same shape** — one is `"3 years"` (string), the other `{"duration": "3", "unit": "years"}` (dict) — a real, unresolved normalization inconsistency inherited from Stage A's extraction (this document's raw fact never carried `duration`/`unit` fields), not something this audit's fix touches (per instruction, Stage A extraction wording was not changed).
- **The master RFP is explicit that "3 years" is the *initial* term, with a separately-stated, distinct extension mechanism** ("...for a period of three (3) years, **with the option to extend for** up to two (2) additional one-year terms"). abstract.pdf's phrasing is terser and less explicit — `"Duration:3 years / Option: 2 years"` does not, on its own words, confirm whether "Option: 2 years" means the same "2×1-year extension options" structure, or a single 2-year option, or something else. **This is a real, unresolved textual ambiguity, not manufactured for this audit** — the two documents corroborate the *headline initial-term figure* ("3 years") but do not, from their literal text alone, provably corroborate the *same extension structure*.

**Confirmed with two independent documents supporting the same initial-duration figure, but with genuinely different structural precision and an unconfirmed extension-structure equivalence.** This is reported as a real, evidence-grounded finding — not "corroborating merely because both contain the number 3."

## 4. The 12-week HR Advisory term, traced

- **Source:** Appendix E (Pricing Form.xlsx), sheet "HR Advisory pricing scenario". Excerpt: *"The engagement will be completed over approximately twelve (12) weeks."*
- **Structured observation:** `INITIAL_DURATION`, `{duration: "12", unit: "weeks"}`, `scope: {component: "HR Advisory", period_basis: "WEEKS"}`.
- **Why it entered candidacy:** its locator is a `sheet` name, and Appendix E's own markers *do* publish sheet-level granularity (confirmed: this observation was already `VERIFIED` before this audit's fix — the section/sheet-asymmetry defect only ever affected PDF documents whose markers are page-only, not this XLSX).
- **Why it "won" before the fix:** it was, before the fix, the *only* `VERIFIED` `CONTRACT_TERM` observation in the whole ledger — not because it out-competed the 3-year figure on the merits, but because the 3-year observations were wrongly excluded from candidacy entirely (Section 5).
- **Does the resolver understand it is scoped to HR Advisory specifically?** Yes — `resolved["contract_term"]["value"][0]["scope"]` correctly carries `{"component": "HR Advisory", ...}`, and (post the prior audit's formatting fix) `format_contract_term()` renders it as *"Initial term: 12 weeks (component: HR Advisory; period_basis: WEEKS)"*, not as an unscoped fact.

**Is a 12-week HR-Advisory-scoped engagement semantically the same canonical fact as an opportunity-wide 3-year agreement term? No.** One describes a specific service category's pricing-scenario assumption; the other describes the legal term of the framework agreement itself. They must not, and — confirmed by the new regression test `test_scoped_and_unscoped_contract_terms_coexist_without_conflict` — **do not**, compete for the same canonical slot. The resolver's `(kind, scope)` grouping already keeps them structurally separate.

## 5. Root cause of the provenance exclusion

Two independent, narrowly-scoped defects in `canonical_opportunity.py`, both **Case B — valid upstream provenance rejected by an inconsistent/stricter-than-necessary Canonical Opportunity check**, confirmed by direct diagnostic replay against the real corpus (not inferred):

**Defect 1 — section/sheet-matching asymmetry (`_locator_matches`).** A ref that specifies `section` (or `sheet`) was rejected outright whenever the candidate marker simply didn't publish that locator dimension at all — which is true for *every* page-granularity-only PDF marker in this corpus. This meant citing a real, correct section number (`"4.2"`) was **strictly worse** than omitting it, because omitting `section` skips the check entirely while specifying it (correctly!) triggers a guaranteed mismatch against a marker that was never going to carry that field. Verified directly: `_source_segment()` returned a zero-length segment for both the master-RFP and abstract.pdf refs, before grounding was even attempted.

**Defect 2 — grounding whitespace brittleness (`_validate_ref`'s `grounded` check).** Even bypassing Defect 1, the plain `_norm()` comparison (`\s+` → single space) does not tolerate two common PDF-extraction artifacts: a hyphenated line-wrap (`"one-\nyear"` → normalizes to `"one- year"`, not `"one-year"`) and a missing space after label punctuation (`"Duration:3 years"` vs. the excerpt's `"Duration: 3 years"`). Both are incidental formatting reflow, not different words — confirmed by direct reproduction against the real extracted text.

Neither defect is a genuine provenance gap: the excerpts are real, faithful quotations of the source text at the cited location. Both were **Case B**, and both were fixed at the root.

**Fix 1** (`_locator_matches`): only enforce `section`/`sheet` equality when the *parsed marker* itself publishes that field — a marker that never carries that dimension can neither corroborate nor refute a more precise citation.
```python
for key in ("sheet", "section"):
    if ref.get(key) is not None and parsed.get(key) is not None and _norm(parsed.get(key)) != _norm(ref[key]):
        return False
```
**Fix 2** (`_validate_ref`): a new, narrowly-scoped `_grounding_norm()` helper (strips *all* whitespace, used **only** for the excerpt-in-segment substring check) replaces `_norm()` in exactly one line. Every other comparison in the module (`_locator_matches`'s own section/sheet check, conflict-value comparisons, scope-key comparisons) continues to use the original word-boundary-preserving `_norm()`, unchanged.

Both fixes are strictly *admission-widening*, never *admission-narrowing* — they cannot cause a previously-VERIFIED observation to become un-verified, and they do not relax the requirement that the excerpt's actual words be present in the source.

## 6. Candidate-admission consistency matrix

| Canonical field | Candidate validation | Required locator | Failure behavior | Consistent with evidence contract? |
|---|---|---|---|---|
| `title` / `client` / `file_number` | `_resolve_simple`: `provenance_status == "VERIFIED"` | any of page/sheet/section/row/cell via `_validate_ref` | excluded from candidacy, field `CONFLICTED` or `UNVERIFIED`/`MISSING` | ✅ now consistent — same `_validate_ref` used everywhere, same fix applies uniformly |
| `submission_deadline` / `clarification_deadline` | `_resolve_simple` + unscoped-only + `DATE`/`DATETIME` precision filter | same | excluded, field `CONFLICTED`/`UNVERIFIED`/`MISSING` | ✅ |
| `contract_term` | `_resolve_term`: `provenance_status == "VERIFIED"` + not `UNPARSED`/`EMPTY` | same | excluded, field `CONFLICTED`/`UNVERIFIED`/`MISSING` | ✅ — this is the field where the defect was discovered, not because its rule was different, but because its real candidates happened to be page-only-PDF-sourced with section citations and hyphenation/punctuation artifacts |
| `headline_value` | `_resolve_money`: `provenance_status == "VERIFIED"` + unscoped + currency present | same | excluded | ✅ |
| `opportunity_type` / `procurement_model` | `_resolve_classifications`: `provenance_status == "VERIFIED"` + unscoped | same | excluded | ✅ — confirmed this field was *also* silently under-resolved by the exact same defect (Section 9) |

**There was no per-field validator asymmetry** — `_validate_ref`/`_locator_matches` are shared, single implementations used identically by every resolver. The asymmetry was **per-document-type** (PDF page-only markers vs. XLSX sheet-tagged markers), which happened to bite `contract_term` and `procurement_model` hardest simply because their strongest evidence in this corpus came from PDF pages with section-level citations. No field had a "stricter selector shape" of its own.

## 7. Scope safety

Directly tested (new regression test): an unscoped opportunity-wide `INITIAL_DURATION` and a `{component: "HR Advisory"}`-scoped `INITIAL_DURATION` were built into a ledger together and resolved. **Result: both appear as separate items in `resolved.contract_term.value`, with their distinct scopes intact, and zero conflict is raised.** A scoped duration cannot and did not replace or merge with an opportunity-wide term. No fuzzy/NLP matching was introduced — the existing structured `scope` dict (already populated by Stage A extraction, already read by `_resolve_term`'s `(kind, scope)` grouping key) is what keeps them apart; nothing new was invented to achieve this.

## 8. What the 3-year source text actually says

- **Master RFP, §4.2 "Contract term":** *"The term of each agreement will be for a period of three (3) years, with the option to extend for up to two (2) additional one-year terms, if required."* — explicitly the **initial agreement term**, with extensions named as a **separate, additional** mechanism (not included in the 3 years).
- **abstract.pdf, "Details":** *"Duration:3 years / Option: 2 years"* — a terse structured-data label pair. "Duration" most plausibly means the same initial-term concept, but the document does not itself state whether "3 years" is inclusive or exclusive of the "Option: 2 years" figure, nor whether that option is 1×2-year or 2×1-year.

These are **not stated identically** and this audit does not assert they are. The canonical ledger keeps them as two distinct observations for exactly this reason.

## 9. Correct canonical outcome — decided from the implementation contract and the evidence, not commercial judgment

**Outcome B: `contract_term` resolves to `CONFLICTED` / `null`.**

Reasoning, applying the resolver's own governed rules (not an external judgment call): once both 3-year observations are correctly admitted as `VERIFIED` candidates (Section 5's fix), `_resolve_term`'s existing, untouched conflict rule fires — `by_kind[(INITIAL_DURATION, {})]` now contains **two** distinct `normalized_value` representations (`"3 years"` vs. `{duration:"3", unit:"years"}`). The resolver's rule is: any non-repeatable `(kind, scope)` bucket with more than one distinct normalized value is a conflict, full stop — it does not attempt to infer that two differently-shaped values might mean the same thing. That inference (treating a bare string and a structured dict as "the same" duration) would require exactly the kind of unsupported semantic-equivalence judgment Section 3 warned against, and is not something this audit implemented, per the explicit instruction not to add external procurement knowledge or fuzzy matching.

This also correctly reflects the genuine textual ambiguity found in Section 8 (does "3 years" already include the extension option or not) — the system is not being overly conservative for no reason; there is a real, unresolved question in the source material that a human reviewer, not an automated resolver, should settle.

**Outcome A** (clean `3 years`) was rejected because it would require silently asserting that two structurally different observations are equivalent. **Outcome C** (12 weeks HR Advisory as "the" answer) was rejected because it never was, and is not now, an opportunity-wide fact, and — now that the true opportunity-wide evidence is correctly admitted — it is self-evidently not the only or the primary contract-term evidence in the corpus. **Outcome D** (the schema can't represent multiple duration types) was rejected because it demonstrably already does (Section 1/7): the 12-week HR-Advisory term coexists cleanly alongside the (now-conflicted) opportunity-wide bucket; it is only the *opportunity-wide* bucket, specifically, that is genuinely disputed.

## 10. Code changes (smallest root cause)

`canonical_opportunity.py`:
1. `_locator_matches()` — section/sheet equality now enforced only when the marker itself publishes that field (Defect 1 fix).
2. New `_grounding_norm()` helper, used in exactly one place (`_validate_ref`'s `grounded` check) — whitespace-insensitive excerpt comparison, tolerating PDF line-wrap hyphenation and punctuation-spacing reflow without weakening the requirement that the excerpt's actual words appear in the source (Defect 2 fix).

No change to `_resolve_term`'s conflict-detection logic, the `VERIFIED`-only candidacy bar, `_normalized_value()`'s shape derivation, any other resolver, or any validator's pass/fail semantics. No amendment-precedence logic was added. No Stage A extraction wording was touched.

## 11. Regression tests added (`tests/test_canonical_opportunity.py`, 7 new)

1. `test_section_citation_against_a_page_only_marker_still_verifies` — Defect 1 fix: a page-only marker no longer blocks a well-grounded, section-cited excerpt.
2. `test_section_mismatch_against_a_real_section_marker_still_rejected` — proves the fix is narrow: a marker that *does* publish a genuinely different section still fails to ground.
3. `test_hyphenated_line_wrap_excerpt_still_grounds` — Defect 2 fix, hyphenation artifact.
4. `test_missing_space_after_punctuation_still_grounds` — Defect 2 fix, punctuation-spacing artifact.
5. `test_genuinely_absent_excerpt_still_fails_to_ground` — guards against over-loosening: unrelated text still fails to ground.
6. `test_scoped_and_unscoped_contract_terms_coexist_without_conflict` — Section 7's scope-safety guarantee, locked in as a regression.
7. `test_same_scope_contract_term_shape_mismatch_conflicts` — locks in Section 9's governed outcome: two verified, same-scope, differently-shaped observations conflict rather than silently corroborate.

Plus the 2 tests already added by the prior audit (`format_contract_term` scope-suffix rendering) remain in place and passing.

**Validation:**
```
py_compile canonical_opportunity.py tests/test_canonical_opportunity.py  -> COMPILE_OK
git diff --check                                                         -> clean
pytest tests/test_canonical_opportunity.py -q                            -> 43 passed
pytest -q (full repository suite)                                        -> 1194 passed, 2 skipped
```

## 12. Before / after canonical output

Stage B's `_canonical_opportunity` sub-object was regenerated deterministically (zero LLM, same frozen Phase 1 Stage A facts) since observation-level `provenance_status` is computed once at build time and cannot be refreshed by re-resolving a stale, pre-fix Stage B artifact. **Every other Stage B family (`requirements`, `dates`, `evaluation_criteria`, `submission_rules`, `deliverables`, `commercial_clauses`, `contract_risks`, `_contract_hygiene`, `_provenance_rejections`) was verified byte-identical before vs. after** (`stage_b_ripple_check.json`: `all_other_families_unchanged: true`) — this regeneration touched nothing outside `_canonical_opportunity`.

| Metric | Before | After |
|---|---:|---:|
| `contract_term` candidate count | 5 | 5 |
| Opportunity-wide (unscoped) VERIFIED candidates | 0 | **3** |
| Scoped VERIFIED candidates | 1 | 2 |
| Rejected (non-VERIFIED) candidates | 4 | **0** |
| Canonical `contract_term` | `RESOLVED`, "Initial term: 12 weeks (component: HR Advisory; period_basis: WEEKS)" | **`CONFLICTED`, "Not stated"** |
| Provenance-valid asserted fields | 2/2 (`submission_deadline`, `contract_term`) | 2/2 (`submission_deadline`, `procurement_model`) |
| Conflicted canonical fields | `title`, `client`, `file_number` (3) | `title`, `client`, `file_number`, `contract_term` (4) |
| `procurement_model` | `NOT_CLASSIFIED` | **`RESOLVED`, "Multi-vendor Call-off"** (same root-cause fix; see below) |
| Rejected-record re-entry | 0 | 0 |
| Determinism (rebuilt twice, zero LLM) | — | identical both times, matches persisted artifact |

**An additional, unplanned but fully evidence-supported effect of the same fix:** `procurement_model` — previously `NOT_CLASSIFIED` — now resolves to `"Multi-vendor Call-off"`, `EXPLICIT_MECHANICS`, from 2 newly-admitted `VERIFIED` observations: an unscoped `MULTIPLE_SUPPLIER_AWARD` ("a maximum of five (5) proponents for [Category 1]; three (3) proponents for [HR Advisory]; and seven (7) proponents for [Facilitation]...") and an unscoped `CALL_OFF` ("...on an as-required basis"). Both were previously excluded from candidacy by the identical page-only-marker section-citation defect. This is not a side effect requiring separate justification — it is the same root cause, correctly fixed once, correctly benefiting every resolver that shares `_validate_ref`.

`title`/`client`/`file_number` remain `CONFLICTED` exactly as before (same 3 fields; more of the real, genuinely-competing evidence is now counted within each conflict — 13→15 observations for `client`, 20→22 for `file_number`, 10→11 for `title` — none flipped to a false resolution).

## 13. Downstream safety check

Opportunity Structure has not been started, and its implementation (`opportunity_structure.py`) does not currently consume `contract_term`, `format_contract_term`, or `_canonical_opportunity` in any form — its `stage_facts` input is the Stage B/C `normalized_facts` mapping directly (confirmed by its own docstring and by an exhaustive grep across `opportunity_structure.py`, `opportunity_structure_binding.py`, and `opportunity_structure_publication.py`: zero references beyond one doc-comment). **There is therefore no current downstream consumer to check for scope-flattening** — the field simply is not read yet. This is recorded here, not as a blocker, but as an explicit note for whoever implements that consumption in the future: they must consume the structured `resolved["contract_term"]["value"]` list (which now correctly preserves per-item `scope`) rather than only the formatted display string, if they need to distinguish opportunity-wide from service-scoped terms programmatically.

## Artifact index

- `evaluation/bank_of_canada_briefing_pack/canonical_opportunity_commissioning/canonopp-boc-2026-026-20260912T142551Z-34a031/`
  - `run_metadata.json`, `stage_b_ripple_check.json`
  - `contract_term_observation_provenance_before_after.json`
  - `contract_term_candidate_inventory.json` (full before/after, all 5 observations)
  - `resolve_determinism_after_fix.json`
  - `before_after_summary.json`
  - `canonical_field_audit_after_fix.json` (all 9 fields, post-fix)
  - `provenance_summary_after_fix.json`
  - `rejected_record_safety_after_fix.json`
- Regenerated Stage B artifact (canonical sub-object only, all other families verified identical): `evaluation/bank_of_canada_briefing_pack/phase2_commissioning/phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031/stage_b_normalized_result.json`
- Code changed: [canonical_opportunity.py](../../canonical_opportunity.py) (`_locator_matches`, `_grounding_norm`, `_validate_ref`), [tests/test_canonical_opportunity.py](../../tests/test_canonical_opportunity.py) (+7 tests)
- Audit script: [scripts/audit_canonical_contract_term_bank_of_canada.py](../../scripts/audit_canonical_contract_term_bank_of_canada.py)

---

## FINAL RESPONSE

- **CANONICAL CONTRACT-TERM AUDIT: PASS**
- **Semantic meaning of `contract_term`:** interpretation D — a canonical family holding multiple, independently-resolved, scope-tagged duration components; not a single opportunity-wide scalar
- **All candidate values:** 5 total — 1 scoped (12 weeks, HR Advisory), 4 unscoped/opportunity-wide (3-year initial term ×2 differently-shaped sources, 1 extension-option, 1 rectification-period statement)
- **3-year source count:** 2 independent documents (abstract.pdf, master RFP), genuinely corroborating the headline figure but with different structural shape and an unconfirmed extension-structure equivalence
- **12-week source count:** 1 (Appendix E Pricing Form, HR Advisory pricing scenario sheet)
- **Why the 3-year observations were previously excluded:** two combined validator defects — (1) `_locator_matches` rejected a correctly-cited `section` locator whenever the source marker simply didn't publish section-level granularity (true for all page-only PDF markers here); (2) `_validate_ref`'s grounding check used a whitespace-collapsing (not whitespace-insensitive) normalizer, failing on a hyphenated PDF line-wrap and a missing space after label punctuation
- **Exclusion validity:** **defective (Case B)** — both are confirmed, narrowly-scoped production defects, now fixed at root; not genuinely invalid provenance
- **Are 12-week and 3-year values semantically comparable?** No — different scope (service-category engagement vs. opportunity-wide agreement term); confirmed they do not and must not compete for the same canonical slot
- **Correct canonical outcome:** Outcome B — `contract_term = CONFLICTED / null`, because the two now-correctly-admitted opportunity-wide observations disagree in structured shape and no governed basis exists to assume equivalence
- **Root cause:** `_locator_matches` section/sheet-matching asymmetry + `_validate_ref` grounding-whitespace brittleness, both in `canonical_opportunity.py`
- **Files changed:** [canonical_opportunity.py](canonical_opportunity.py), [tests/test_canonical_opportunity.py](tests/test_canonical_opportunity.py)
- **Tests added:** 7
- **Full-suite result:** 1194 passed, 2 skipped
- **New canonical run ID:** `canonopp-boc-2026-026-20260912T142551Z-34a031` (regenerated Stage B canonical sub-object: `phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031`; all 8 non-canonical Stage B families verified byte-identical)
- **Before/after `contract_term`:** `RESOLVED` "Initial term: 12 weeks (component: HR Advisory)" → `CONFLICTED` / "Not stated"
- **Asserted-field provenance status:** 2/2 valid both before and after (composition shifted from `{submission_deadline, contract_term}` to `{submission_deadline, procurement_model}` — both fully evidence-grounded)
- **Downstream scope behavior:** not yet consumed by Opportunity Structure or any other downstream layer (confirmed by code inspection) — no blocker exists today, but the structured, scope-tagged object must be what any future consumer reads, not a flattened string
- **Recommendation: AUTHORIZE OPPORTUNITY STRUCTURE**
- **Report path:** [evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_CANONICAL_CONTRACT_TERM_AUDIT.md](evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_CANONICAL_CONTRACT_TERM_AUDIT.md)
- **Raw artifact paths:** `evaluation/bank_of_canada_briefing_pack/canonical_opportunity_commissioning/canonopp-boc-2026-026-20260912T142551Z-34a031/`; regenerated Stage B: `evaluation/bank_of_canada_briefing_pack/phase2_commissioning/phase2-boc-2026-026-stageb-canonterm-fix-20260912T142551Z-34a031/`

Per instruction, this audit stops here. **Opportunity Structure has not been started.**
