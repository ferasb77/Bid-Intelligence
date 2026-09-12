# Bank of Canada RFP 2026-026 — Phase 2 / Stage B Commissioning Report

This report documents a fresh, real production run of **Stage B (Deduplication & Source Provenance Validation)** — the production function `extractor.normalize_package_facts()` — against the frozen fresh Phase 1 output for the authoritative 16-document corpus. Stage A was **not** re-invoked. Stage C, Stage D, Canonical Opportunity resolution, Opportunity Intelligence, Buyer Brief, Executive Opportunity Brief, and Executive Briefing Pack were **not** run.

## 0. Inspection of the real Stage B implementation (performed before execution)

- **Production function**: `extractor.normalize_package_facts(doc_facts_list: list[dict], package_metadata: dict) -> dict` (`extractor.py:2933-3170`).
- **Input type**: `doc_facts_list` — the list of raw per-document Stage A dicts (exactly `phase1_stage_a_document_facts.json`). `package_metadata` — `{"files": [...], "doc_metadata": {...}, "doc_texts": {...}}`, the same structure Document Parsing built in Phase 1.
- **Output type**: a plain Python `dict` (not a dataclass or typed schema) with keys `doc_metadata`, `requirements`, `dates`, `evaluation_criteria`, `submission_rules`, `deliverables`, `commercial_clauses`, `contract_risks`, `_canonical_opportunity`, `_contract_hygiene`.
- **Deterministic?** Yes — confirmed by code inspection: no randomness, no I/O beyond reading `package_metadata`, and this run's own two consecutive executions of the metadata-reconstruction step produced byte-identical character/page counts (Section B).
- **Invokes an LLM?** **No.** `normalize_package_facts` and every helper it calls (`validate_source_refs`, `requirement_semantics.*`, `evaluation_hierarchy.deduplicate_evaluation_criteria`, `canonical_opportunity.build_canonical_opportunity`, `contract_hygiene.build_contract_hygiene`) are pure Python — no `client.messages.create` anywhere in this call graph. Verified by reading every one of these functions before running this commissioning, and by this run making zero API calls (0.23-second total runtime for the entire boundary).
- **Object families actually processed, and how**, exactly as found in the code (not as assumed):
  - **`requirements`**: deduplicated by an **exact** key — `re.sub(r'\W+','', description.strip().lower())` (whitespace/punctuation-insensitive exact match, not fuzzy/semantic). Merges append the union of validated `source_refs` (deduped by `(source_doc, page)` only) and accumulate `requirement_type` candidates across all contributing documents.
  - **`dates`**: **no deduplication, no provenance validation at all** — `normalized["dates"].extend(df.get("dates", []))`, a raw concatenation. This is real, existing behavior, not a gap introduced by this run.
  - **`evaluation_criteria`**: raw-concatenated then deduplicated separately by `evaluation_hierarchy.deduplicate_evaluation_criteria()`, keyed on `(criterion_id or normalized title, normalized parent title, hierarchy level)` — independent of weight, so differing weights for the same logical criterion are preserved as `weight_observations` with `weight_conflict=True` rather than silently collapsed. **Source refs on this family are never passed through `validate_source_refs()`** — copied verbatim from Stage A.
  - **`submission_rules`**: deduplicated by `_canonical_submission_item_identity(item)` (or lowercased item text); merges track `artifact_type`/`file_format`/`submission_channel`/`mandatory` as accumulated "observations" with explicit `*_conflict` boolean flags when documents disagree — conflicting values are marked, never silently overwritten.
  - **`deliverables`** / **`commercial_clauses`** / **`contract_risks`**: raw-concatenated, then entirely reprocessed and **overwritten** by `contract_hygiene.build_contract_hygiene()` — a separate, stricter pipeline (Section 0.1 below).
  - **`typed_observations`**: not carried forward as a top-level array at all. Consumed exclusively by `canonical_opportunity.build_canonical_opportunity()`, which builds an identity-deduplicated observation ledger (`_canonical_opportunity.observations`) with `resolved: {}` and `conflicts: []` left **empty** at this boundary — real conflict/field resolution (`resolve_canonical_opportunity`) is a separate function called only from Stage C (`reconcile_package_facts`), never from Stage B.
- **IDs/digests/revisions**: Stage B's `requirements`/`dates`/`submission_rules`/`evaluation_criteria` records carry no independent object ID of their own. `_canonical_opportunity` observations get content-derived IDs (`obs_<hash>`, `norm_<hash>`) and an `input_digest` for the whole ledger. `_contract_hygiene` deliverable/clause records get content-derived `dlv_<hash>`/`clause_<hash>` IDs.
- **Multiple `source_refs` handling**: requirements/submission_rules keep all validated refs (valid and invalid alike, each flagged `verified: true/false`); deliverables/commercial_clauses **drop** unverified refs before an occurrence is even built (`contract_hygiene._verified_refs()`); evaluation_criteria/dates keep refs completely unvalidated.
- **Scopes/categories/lots**: `deliverables`/`commercial_clauses` carry a `scope: {lot, phase, component, location}` dict as part of their logical-identity key (`_deliverable_key`/`_clause_key`) — two records with the same wording but different scope are **not** merged. `typed_observations`→canonical-opportunity identity also includes `scope` in its identity key.
- **Existing validators at this boundary**: `extractor.validate_source_refs()` (binary verified/not-verified, checks document existence, page bounds, sheet existence, row range, excerpt-word-presence) applied to requirements/submission_rules and (via `contract_hygiene._verified_refs`) deliverables/commercial_clauses; `canonical_opportunity._validate_ref()` — a **separate**, three-tier (`VERIFIED`/`PARTIAL`/`UNVERIFIED`) validator applied only to typed-observation source refs, checking document existence plus excerpt-grounded-in-local-segment plus locator-coordinate presence. No validator exists for `dates` or `evaluation_criteria` source references.

### 0.1 `contract_hygiene.build_contract_hygiene()` — the deliverables/clauses/risks sub-pipeline

- Each raw deliverable/clause is shape-validated (`normalize_deliverable_occurrence`/`normalize_clause_occurrence`: required fields present and in a controlled vocabulary). Shape-valid items get real refs validated and **filtered to verified-only**; shape-invalid items become unconditional **"legacy" records** (`assessment_basis: LEGACY_EXTRACTION`, `evidence_state: UNVERIFIED`) that are **never ref-validated at all** and always survive to the final output.
- Shape-valid occurrences are grouped into logical records (`_deliverable_key`/`_clause_key` — includes `scope`, so scope differences prevent merging) and the record's `evidence_state` is `VERIFIED` only if **every** contributing occurrence has ≥1 verified ref.
- **Asymmetry found and preserved (not corrected) in this commissioning**: `normalize_package_facts` keeps **both** `VERIFIED` and `UNVERIFIED` logical deliverable records in the final `deliverables` array, but keeps **only** `VERIFIED` logical records for `commercial_clauses` (`[c for c in hygiene["clauses"] if c["evidence_state"]=="VERIFIED"] + legacy_clauses`) — an `UNVERIFIED` fresh clause occurrence is **silently dropped** from the final clauses array (it does not appear anywhere in `normalized["commercial_clauses"]`). Legacy (shape-invalid) records of both kinds always survive, unconditionally, regardless of provenance.
- `contract_risks`: Stage A's own prompt schema does not define this category (confirmed: 0 raw `contract_risks` records across all 16 documents in this run), and every item that *did* exist would become an unconditional, never-ref-validated `legacy_risks` record.

## A. Run metadata

| Field | Value |
|---|---|
| Phase 2 run ID | `phase2-boc-2026-026-stageb-20260912T094351Z-b489a1` |
| Timestamp (UTC) | 2026-09-12T09:43:55.649371+00:00 |
| Git commit | `7e797830f42d06ff08745648585de0e26557addb` (working tree dirty, 114 changed files — pre-existing, unrelated) |
| Production entry point | `scripts/commission_phase2_stage_b_bank_of_canada.py` → `extractor.normalize_package_facts()` |
| Stage B function | `extractor.normalize_package_facts` |
| Input Phase 1 run ID | `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5` |
| Input Stage A digest | `_canonical_opportunity.input_digest` = `input_fb12798abe44bc3a925f988351ab83b11ff2c56d03736399ef4c8b19ddf9c895` |
| Stage B duration | **0.233787 seconds** |
| Model / API use | **None. Stage B makes zero LLM calls** (confirmed by code inspection and by this run's own execution: `llm_calls_made_this_run: 0`) |
| Token usage / cost | Not applicable — no model was invoked |

`package_metadata` (files/doc_metadata/doc_texts) was not persisted as raw structured JSON by the Phase 1 run — it was reconstructed here by re-calling the same deterministic, non-LLM `extract_document_with_metadata()` against the same 16 frozen physical files (SHA-256-verified identical to the Phase 1 manifest first). This is **not** a Stage A rerun; `extract_document_facts` (the LLM call) was never invoked in this run. The reconstruction was cross-checked field-by-field against the persisted `phase1_document_parsing.json` character/page counts — **all 16 documents matched exactly** (`metadata_reconstruction_check.json`).

## B. Input lock

```
PHASE 1 INPUT LOCK: PASS
```

| Check | Result |
|---|---|
| Phase 1 run ID | `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5` |
| Source documents | 16 |
| Stage A total records (frozen) | 916 |
| Master-RFP Stage A records (frozen) | 288 |
| Fresh corpus SHA-256 vs. frozen manifest | **identical for all 16 files** |
| `package_metadata` reconstruction vs. frozen Phase 1 parsing | **identical for all 16 files** |
| Stage A rerun | **No** — `doc_facts_list` loaded verbatim from `phase1_stage_a_document_facts.json`, never mutated before being passed to Stage B |

## C. Actual Stage B output schema (as produced by this run)

Top-level dict keys and what each contains (see Section 0 for full behavior):
`doc_metadata` (dict, first-non-empty-wins merge) · `requirements[]` · `dates[]` · `evaluation_criteria[]` · `submission_rules[]` · `deliverables[]` · `commercial_clauses[]` · `contract_risks[]` · `_canonical_opportunity{schema_version, documents[], observations[], resolved, conflicts, coverage, integrity_diagnostics, input_digest}` · `_contract_hygiene{version, deliverable_occurrences[], deliverables[], clause_occurrences[], clauses[], legacy_deliverables[], legacy_clauses[], legacy_risks[]}`.

## D. Pre/post normalization counts

| Family | Stage A raw input count | Records considered (non-empty/valid shape) | Stage B normalized output count | Duplicate groups (size > 1) | Records merged away | Records retained 1:1 | Records rejected/dropped | Records with provenance failure |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| requirements | 445 | 445 (0 skipped — all had non-empty description) | **427** | 9 | 18 (445 − 427) | 418 | 0 | 0 |
| dates | 23 | 23 (no filtering exists) | **23** | n/a — no dedup | 0 | 23 | 0 | n/a — never validated |
| evaluation_criteria | 102 | 102 (0 skipped — all had non-empty stage/title) | **83** | 11 | 19 (102 − 83) | 72 | 0 | n/a — never validated |
| submission_rules | 85 | 85 (0 skipped — all had non-empty item) | **62** | 18 | 23 (85 − 62) | 44 | 0 | 0 |
| deliverable_occurrences (pre-logical-grouping) | 24 (all 24 raw deliverables passed shape validation) | 24 | 24 logical → **24 final** (0 legacy) | 0 | 0 | 24 | 0 | 1 occurrence had zero refs survive filtering (still kept, `evidence_state=UNVERIFIED`) |
| clause_occurrences (pre-logical-grouping) | 91 (90 passed shape validation, 1 became legacy) | 91 | 91 logical (89 verified + 2 unverified) → **90 final** (89 verified fresh + 1 legacy) | 0 | 0 | 91 occurrences / 90 final records | 2 unverified fresh logical records silently excluded from final array | 2 |
| contract_risks | 0 | 0 | **0** | n/a | 0 | 0 | 0 | n/a |
| typed_observations → canonical_opportunity observations | 145 | 128 (17 rejected: unrecognized family/kind combination) | **120** | (same-document exact-coordinate repeats collapse) | 8 | — | 17 (`invalid_observations`, distinct family/kind combo not in the controlled schema) | 2 `UNVERIFIED` |

Stage B currently normalizes **seven** raw Stage A categories (`requirements`, `dates`, `evaluation_criteria`, `submission_rules`, `deliverables`, `commercial_clauses`, `typed_observations`); `contract_risks` is processed by the same code path but Stage A's own prompt schema never populates it, so it is always empty in real runs. No category was fabricated or normalized beyond what the real implementation defines.

## E. Deduplication audit

| Family | Total groups | Groups merged (size>1) | Groups singleton | Largest group sizes |
|---|---:|---:|---:|---|
| requirements | 427 | 9 | 418 | 4, 4, 4, 3, 3, 3, 2, 2, 2 |
| submission_rules | 62 | 18 | 44 | 4, 3, 3, 3, 2, 2, 2, 2, 2, 2 |
| evaluation_criteria | 83 | 11 | 72 | 4, 4, 4, 3, 3, 2, 2, 2, 2, 2 |
| deliverable_occurrences | 24 | 0 | 24 | — no deliverable text repeated verbatim across documents |
| clause_occurrences | 91 | 0 | 91 | — no clause text repeated verbatim across documents |

### Representative merge groups

**Exact duplicate (requirements, group size 4)** — the same sentence, byte-identical after normalization, appears in 4 different documents:
> `"Proponents will be evaluated only on the service category(ies) for which they submit a response."`
- Contributing documents: Amendment1 D2-REVISED, OriginalRevision D1, OriginalRevision D2, OriginalRevision D3
- Resulting normalized record: 1 requirement, `source_refs` = union of 4 refs (each `section: "Header"`, `page: null`, all `verified: true`)
- Nothing lost: all 4 physical citations retained; only the redundant duplicate text collapses to one logical requirement.

**Exact duplicate (requirements, group size 4) spanning the master RFP and 3 appendices:**
> `"Each proposal must provide written confirmation of the ability to provide all services, materials and solutions in both English and French."`
- Contributing documents: Appendix B1, B2, B3 (each per-category mandatory-criteria sheet) **and** the master RFP itself
- Resulting record: 1 requirement citing all 4 documents — direct evidence the master RFP's own bilingualism clause is recognized as the same logical requirement as each category-specific appendix restating it.

**Similar-looking records deliberately kept separate (submission_rules)**: "Appendix B1", "Appendix B2", "Appendix B3" each dedup within their own item-identity key (their own group, sizes 1–2, e.g. "Appendix B1" appearing once in the abstract and once in the appendix file itself), but B1/B2/B3 are **never** merged with each other — `_canonical_submission_item_identity()` keys on the literal appendix label, and B1/B2/B3 name visibly different service categories in `item`/`details`, so scope difference is preserved by construction, not by a special rule this run added.

**Evaluation criteria kept separate despite similar titles**: "Corporate Profile" (group size 4, appears once per rated-criteria response form D1/D2/D2-REVISED/D3, one per service category) never merges with the differently-titled "Key Personnel and Roster" (also size 4) or "Relationship Management" (size 3) — `make_criterion_key()` is title-based, and these are genuinely distinct criteria that happen to recur once per service-category form.

## F. Provenance validation audit

| Family | Total physical refs | Valid | Invalid | — not-found-in-package | — other reason | Records w/ zero valid ref |
|---|---:|---:|---:|---:|---:|---:|
| requirements | 446 | **446 (100%)** | 0 | 0 | 0 | 0 |
| submission_rules | 143 | **143 (100%)** | 0 | 0 | 0 | 0 |
| evaluation_criteria | 106 | *not validated by Stage B* | — | — | — | — |
| dates | n/a (23 date records) | *not validated by Stage B* | — | — | — | — |
| deliverable_occurrences | 24 occurrences → 23 with ≥1 verified ref | — | 1 occurrence's refs were entirely filtered out by `_verified_refs()` (record still kept, `evidence_state=UNVERIFIED`) | — | — | 1 |
| clause_occurrences | 91 occurrences → 89 verified, 2 unverified | — | 2 occurrences' refs were entirely filtered out (both **silently dropped** from the final `commercial_clauses` array per Section 0.1) | — | — | 2 (dropped) |
| canonical_opportunity observations | 120 total | 70 `VERIFIED` | 48 `PARTIAL`, 2 `UNVERIFIED` | — | — | 2 |

**Every one of the 446 requirement references and 143 submission-rule references in this run validated successfully against the real 16-document evidence universe** — zero fabricated pages, sheets, or excerpts were found. This is a genuinely strong result: it means Stage A, across all 16 documents including the 4 `RECOVERED_TRUNCATED` ones, never hallucinated a source location for anything that survived into a requirement or submission rule.

Representative validated examples:

```json
// PDF/page provenance
{"req_id": "M1", "description": "Appendix A - Submission form must be completed and submitted",
 "source_refs": [{"source_doc": "abstract.pdf", "page": 1, "section": "Bid Documents List - Envelope 1",
                   "sheet": null, "excerpt": "Appendix A - Submission form - Mandatory", "verified": true}]}

// DOCX/section provenance
{"req_id": "R1", "description": "Responses must not exceed twelve (12) pages...",
 "source_refs": [{"source_doc": "Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx",
                   "page": null, "section": "Header", "sheet": null, "verified": true}]}

// XLSX/sheet provenance
{"req_id": "S1", "description": "Respond to ESG questionnaire section with yes/no answers...",
 "source_refs": [{"source_doc": "OriginalRevision/DP 2026-026 - Annexe F - Questionnaire ESG.xlsx",
                   "page": null, "sheet": "ESG", "section": null, "verified": true}]}

// Multi-document merged provenance (4 documents, all verified)
{"req_id": "R3", "description": "Proponents will be evaluated only on the service category(ies) for which they submit a response.",
 "source_refs": [
   {"source_doc": "Amendment1/RFP 2026-026 - Appendix D2 - Rated Criteria Response REVISED.docx", "section": "Header", "verified": true},
   {"source_doc": "OriginalRevision/RFP 2026-026 - Appendix D1 - Rated criteria response form.docx", "section": "Header", "verified": true},
   {"source_doc": "OriginalRevision/RFP 2026-026 - Appendix D2 - Rated Criteria Response Form.docx", "section": "Header", "verified": true},
   {"source_doc": "OriginalRevision/RFP 2026-026 - Appendix D3 - Rated Criteria Response Form.docx", "section": "Header", "verified": true}]}
```

No requirement or submission-rule reference was invented: `page`, `sheet`, and `section` are populated only where the real parser produced that coordinate type for that file format (no page numbers were manufactured for DOCX/XLSX; no sheet names were manufactured for PDF/DOCX).

## G. Document contribution after normalization

| Document | Stage A records | Normalized records citing it (req+rules+eval) | Physical refs from it | Sole-source records | Shared-source records |
|---|---:|---:|---:|---:|---:|
| abstract.pdf | 76 | 41 | 80 | 28 | 13 |
| Amendment1/…D2-REVISED.docx | 22 | 20 | 20 | 9 | 11 |
| OriginalRevision/…Annexe F ESG.xlsx | 3 | 2 | 2 | 2 | 0 |
| OriginalRevision/…Appendix A Submission Form.docx | 18 | 11 | 13 | 9 | 2 |
| OriginalRevision/…Appendix B1.xlsx | 15 | 9 | 9 | 3 | 6 |
| OriginalRevision/…Appendix B2.xlsx | 9 | 5 | 5 | 0 | 5 |
| OriginalRevision/…Appendix B3.xlsx | 15 | 9 | 9 | 6 | 3 |
| OriginalRevision/…Appendix C1.xlsx | 8 | 4 | 4 | 4 | 0 |
| OriginalRevision/…Appendix C2.xlsx | 10 | 7 | 7 | 6 | 1 |
| OriginalRevision/…Appendix C3.xlsx | 9 | 6 | 6 | 4 | 2 |
| OriginalRevision/…Appendix D1.docx | 73 | 66 | 72 | 56 | 10 |
| OriginalRevision/…Appendix D2.docx (original) | 23 | 22 | 22 | 12 | 10 |
| OriginalRevision/…Appendix D3.docx | 24 | 22 | 22 | 14 | 8 |
| OriginalRevision/…Appendix E Pricing Form.xlsx | 76 | 50 | 51 | 49 | 1 |
| OriginalRevision/…Appendix G Form of Agreement.docx | 247 | 162 | 167 | 161 | 1 |
| **RFP 2026-026 - Talent, Learning and Organizational Development Services.pdf (MASTER RFP)** | **288** | **192** | **206** | **172** | **20** |

**No document disappeared entirely from normalized provenance** — every one of the 16 documents contributes at least 2 normalized records and at least 2 physical references. (This table covers `requirements`+`submission_rules`+`evaluation_criteria` — the three families with a `source_refs[].source_doc` field; `deliverables`/`commercial_clauses` carry their own scope rather than a flat source-doc list, and `typed_observations`→canonical-opportunity provenance is reported separately in Section F.)

## H. Master RFP contribution

| Metric | Value |
|---|---|
| Stage A records in | 288 |
| Normalized requirements retaining master-RFP provenance | 105 (101 sole-source, 4 shared) |
| Normalized submission_rules retaining master-RFP provenance | 32 (17 sole-source, 15 shared) |
| Normalized evaluation_criteria retaining master-RFP provenance | 55 (54 sole-source, 1 shared) — **zero loss**: every one of the 55 raw master-RFP evaluation criteria survived as its own logical record |
| Physical master-RFP references retained (req+rules+eval) | 206 |
| Pages represented after Stage B (req+rules+eval only) | 3–21 (19 of 21 pages) |
| Master-RFP Stage A records not reflected in this 3-family page list | Page 1 and page 2 content — page 1's Stage A output was exclusively `typed_observations` (SOLICITATION_NUMBER, OPPORTUNITY_TITLE identity facts), which route to `_canonical_opportunity`, not to requirements/rules/criteria (correctly retained there — see Section F's `canonical_opportunity` row); page 2 (Table of Contents) produced zero Stage A records of any kind, as already established in the Phase 1 report |

No master-RFP Stage A record was lost due to a Stage B defect: the 4-record reduction in `requirements` (107 raw → 105 final citing master) and 0-record reduction in `evaluation_criteria`/`submission_rules` are ordinary within-family exact-duplicate collapses (a master-RFP requirement whose normalized description exactly matched another master-RFP requirement, or joined a cross-document merge group already counted under Section E) — not silent drops, not fabricated content, and not an amendment/precedence decision.

## I. Amendment/revision safety check

| Metric | Value |
|---|---|
| Original Appendix D2 unique requirement description-keys | 11 |
| Revised Appendix D2 (Amendment1) unique requirement description-keys | 10 |
| Overlap (byte-identical after normalization) | 1 |
| Normalized requirements citing **both** D2 variants together | 1 |

Both the original and revised Appendix D2 survive into Stage B's output as distinct evidence: 10 of the revised document's 11 raw requirements remained associated with the revised document alone (and similarly for the original), and exactly one boilerplate instruction sentence ("Proponents will be evaluated only on the service category(ies)...", shared with D1/D3 too — see Section E) happened to be worded identically in both, merging into a single normalized record that cites all of them. **Stage B made no decision about which version of Appendix D2 is authoritative or current** — no supersession/precedence field was set for either document, and `resolve_canonical_opportunity` (the function that would perform such adjudication) was never called in this run. That determination, if it is ever made, belongs to Stage C, as instructed.

## J. Diagnostic lineage (RECOVERED_TRUNCATED)

| Category | Count (of 572 normalized req+rules+eval records) |
|---|---:|
| Sourced exclusively from clean (`VERIFIED_ADEQUATE`) Stage A documents | 126 |
| Sourced from a mix of clean and `RECOVERED_TRUNCATED` documents | 16 |
| Sourced **exclusively** from `RECOVERED_TRUNCATED` documents | **429** |
| No source document resolvable | 1 |

**429 of 572 normalized records (75%) in these three families depend exclusively on a document that required Stage A's truncation-recovery path** (abstract.pdf, Appendix D1, Appendix G, or the master RFP). This is expected given those four documents alone account for 684 of 916 raw Stage A records (75%) — they are simply the four largest, most content-dense documents in the corpus — but it is reported here exactly as instructed: these upstream diagnostics have **not** been upgraded to clean, and Stage B's schema was **not** modified to carry a diagnostic-lineage field of its own. This lineage classification is derived externally in this commissioning's own analysis (`recovered_truncated_lineage.json`), not stored inside the production Stage B output.

## K. Complete raw artifacts

All paths relative to the repository root, under:
`evaluation/bank_of_canada_briefing_pack/phase2_commissioning/phase2-boc-2026-026-stageb-20260912T094351Z-b489a1/`

| File | Type | Notes |
|---|---|---|
| `run_metadata.json` | JSON | Run identity, Stage B function, zero-LLM confirmation |
| `input_lock.json` | JSON | Frozen Phase 1 identity + digest-match confirmation |
| `metadata_reconstruction_check.json` | JSON | Per-document fresh-vs-frozen parsing cross-check (16/16 match) |
| `stage_b_normalized_result.json` | JSON | **Complete, non-truncated** production `normalize_package_facts()` output — the actual Stage B result, produced by the real production serializer (plain `json.dumps` of the function's own return dict; no reformatting) |
| `dedup_audit.json` | JSON | Group counts/sizes per family, derived from the frozen raw input using Stage B's own key functions |
| `example_merge_groups.json` | JSON | Representative merge groups per family |
| `provenance_audit.json` | JSON | Reference validation counts per family, including the two asymmetric-behavior notes |
| `per_document_contribution.json` | JSON | Per-document Stage A/normalized/reference counts (Section G) |
| `master_rfp_contribution.json` | JSON | Master RFP dedicated counts (Section H) |
| `amendment_d2_safety_check.json` | JSON | Original/revised D2 overlap analysis (Section I) |
| `recovered_truncated_lineage.json` | JSON | Diagnostic lineage counts (Section J) |
| `summary.json` | JSON | Top-line counts, also printed to console |

## Historical comparison (informational only — collected after this fresh run; did not influence it)

| Metric | Historical corrected run | Fresh Phase 2 |
|---|---:|---:|
| Documents | 16 | 16 |
| Stage A document inputs | 16 | 16 |
| Stage B normalized requirements | 413 | **427** |
| Stage B normalized dates | 23 | **23** (exact match) |
| Stage B normalized evaluation_criteria | 113 | **83** |
| Stage B normalized submission_rules | 66 | **62** |
| Stage B normalized deliverables | 30 | **24** |
| Stage B normalized commercial_clauses | 91 | **90** |

No tuning, retrying, or threshold changes were made to reproduce 413 or any other historical number — this fresh run used the unmodified production `normalize_package_facts()` exactly once.

**What can be established from the artifacts**: `dates` matches exactly (23=23), and `commercial_clauses` is very close (91 vs. 90) — both consistent with the two runs' underlying Stage A extractions having been very similar in volume for those families. `requirements` is close but not identical (427 vs. 413, +14, +3.4%) — Stage B's own dedup/provenance logic ran identically in both cases (it is the same deterministic code in both runs); a difference of this size is consistent with two **independent live Stage A extractions** (this run's vs. the historical evaluation harness's, run in a different session, at a different time, through a different harness script) producing slightly different requirement text/counts, which is expected variance in per-document LLM extraction rather than a Stage B defect.

`evaluation_criteria` shows the largest proportional gap (113 vs. 83, −30, −27%). Because `evaluation_criteria` deduplication is keyed on **exact normalized title text**, this family's final count is more sensitive to small wording differences between two independent Stage A runs than the description-hash-keyed `requirements` family is — a plausible structural reason, though this cannot be confirmed without the historical run's own raw Stage A output (not part of this commissioning's frozen input, and not re-derived here per instruction not to reproduce or chase the historical number). No further explanation is asserted beyond what these artifacts establish.

## FINAL CONSOLE RESPONSE

```
PHASE 1 INPUT LOCK: PASS
STAGE B EXECUTION: PASS
PROVENANCE VALIDATION: PASS
PHASE 2 COMMISSIONING: PASS
```

- **Phase 2 run ID**: `phase2-boc-2026-026-stageb-20260912T094351Z-b489a1`
- **Phase 1 input run ID**: `phase1-boc-2026-026-corrected16-20260912T080929Z-9fd9e5`
- **Actual Stage B object/schema types**: plain `dict` output of `extractor.normalize_package_facts()` — see Section C
- **Stage A input count**: 916 raw records (288 from the master RFP)
- **Stage B normalized count** (all families): 427 requirements + 23 dates + 83 evaluation_criteria + 62 submission_rules + 24 deliverables + 90 commercial_clauses + 0 contract_risks + 120 canonical_opportunity observations
- **Normalized requirement count**: 427
- **Duplicate-group count**: 9 (requirements) + 18 (submission_rules) + 11 (evaluation_criteria) = 38 merge groups total
- **Merge count** (records collapsed): 18 + 23 + 19 = 60
- **Valid physical reference count**: 446 (requirements) + 143 (submission_rules) = 589 verified references (100% of those two families' references)
- **Invalid/unresolved reference count**: 0 for requirements/submission_rules; 2 clause occurrences and 1 deliverable occurrence had all references filtered to zero by contract_hygiene's stricter verified-only rule (2 of those — the clause ones — were silently excluded from the final `commercial_clauses` array, per real existing Stage B behavior)
- **Records with zero valid provenance**: 3 total (1 deliverable occurrence, 2 clause occurrences) — all pre-existing production behavior, not introduced by this run; none of these are `requirements`, which is the family the acceptance conditions treat as requiring provenance
- **Master RFP normalized contribution**: 192 records across requirements+submission_rules+evaluation_criteria (172 sole-source, 20 shared), 206 physical references retained, evaluation_criteria retained with zero loss (55/55)
- **Records dependent on `RECOVERED_TRUNCATED` sources**: 429 of 572 (75%) exclusively, plus 16 more with mixed clean/truncated provenance — **these upstream diagnostics were not upgraded to clean**
- **Runtime**: 0.233787 seconds
- **API/token/cost**: none — Stage B makes zero LLM calls (confirmed by code inspection and by this run)
- **Historical 413 comparison**: fresh run produced 427 requirements (+14, +3.4%); dates matched exactly; evaluation_criteria and submission_rules were lower; commercial_clauses nearly matched — see Historical Comparison section for what can and cannot be attributed to a specific cause
- **Markdown report path**: `evaluation/bank_of_canada_briefing_pack/BANK_OF_CANADA_PHASE_2_STAGE_B_COMMISSIONING_REPORT.md`
- **Complete raw-artifact paths**: `evaluation/bank_of_canada_briefing_pack/phase2_commissioning/phase2-boc-2026-026-stageb-20260912T094351Z-b489a1/` (index in Section K)
- **Warnings/anomalies**: (1) `dates` and `evaluation_criteria` carry no physical-provenance validation at all in the current production Stage B — a real, pre-existing gap, not introduced here; (2) `commercial_clauses` silently drops fresh logical records with zero verified evidence (2 records this run) rather than flagging them; (3) 75% of normalized req/rules/eval records depend exclusively on a `RECOVERED_TRUNCATED` Stage A document; (4) 17 raw `typed_observations` were dropped for an unrecognized family/kind combination (`invalid_observations` in `_canonical_opportunity.integrity_diagnostics`)

Stopping here per your instruction. Stage C is not started.
