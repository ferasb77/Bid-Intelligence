# Stage D Synthesis Projection — Implementation Report

## Outcome and scope

Implemented the versioned Stage D projection, provenance sidecar, field-level citations, strict response validation, private checkpoints, and deterministic resume support. The existing authoritative applicator and final submission-document builder remain authoritative. The public extraction return shape remains bid/brief/requirements/documents/outline.

Implementation is ready for code review, **not a claim that full-package Stage D capacity is resolved**. The generic synthetic 559-requirement case fits the existing guard. Both retained real fixtures produce larger prompts under this full-ID, full-excerpt contract. No live LLM extraction or synthesis benchmark was run.

**FULL BRITISH COUNCIL CAPACITY ACCEPTANCE NOT YET PROVEN**

## Branch, base, and commits

- Branch: `fix/stage-d-synthesis-projection`.
- Verified base: `2619499431463efc93f8b4a9404820f5caea27ba`.
- Checked out main, fetched origin, fast-forwarded local main to that exact SHA, verified it, then created the requested branch before editing.
- Production/test/tools commit: `7e42188b508976a600d9eee9db33bf8360e4a94c` — `fix(stage-d): add scalable synthesis projection`.
- This report and the sanitized measurements belong to the subsequent evidence-only commit. Its SHA is reported in the task completion message.
- No PR or merge. Existing untracked design and British Council artifacts were preserved and were not included in either commit.

## Root problem

The original Stage D path serialized normalized records with repeated provenance, including capped requirement excerpts, and asked the model to regenerate seven sections that deterministic code subsequently rebuilt. The full British Council failure artifact records 559 normalized requirements, seven conflicts, and 1,045,967 characters against the unchanged 580,000-character limit. Stage D dispatch did not occur.

The new implementation separates prompt-facing interpretation from authoritative data retention. It does not attempt to reduce requirement count, rewrite obligations, infer source precedence, or repair upstream extraction.

## Files changed

| File | Change |
|---|---|
| `stage_d_projection.py` | Pure projection builder, canonical serialization, stable IDs, field registries, shared evidence context, diagnostics, exact request finalization, strict JSON/field-level citation validation, synthesis-only prompt. |
| `stage_d_checkpoints.py` | Configurable atomic private checkpoint writer, manifest/checksums, source/version validation, preprocessing JSON codec, required-mode resume. |
| `extractor.py` | Routes Stage D through projection/validation, owns one retry loop with SDK retries disabled for D, calls unchanged authority helpers, adds checkpoint hooks around stage boundaries and final assembly checks. Keeps legacy context/prompt for offline comparisons. |
| `scripts/measure_stage_d_projection.py` | Offline measurement tool; required external checkpoint root; no LLM dispatch; synthetic and retained-fixture comparisons. |
| `tests/test_stage_d_projection.py` | 74 deterministic test cases covering projection, citations, boundary dispatch, authority, checkpoint modes, corruption, resume, and frozen/scalability cases. |
| `tests/test_stage_d_completeness.py` | Updates the small-context mock to a valid v1 response and strengthens dispatch/authority assertions. Invalid `{}` output is tested explicitly in the new suite. |
| `STAGE_D_SYNTHESIS_PROJECTION_REPORT.md` | This report. |
| `tests/acceptance/results/stage_d_projection_offline_measurements.json` | Sanitized counts, sizes, digests, and invariant results; no source excerpts, raw facts, or request content. |

An AST comparison against the required base confirmed that the only changed **existing** extractor function bodies are `synthesize_bid_brief` and `extract_procurement_package`. Existing Stage A/B/C functions, requirement semantics, evaluation/submission helpers, and `apply_stage_d_authoritative_sections` are unchanged. New integration helpers contain the extracted final assembly and projection dispatch path.

No database/schema/migration, model, context limit, .xls handling, fuzzy deduplication, clustering, duplicate-document detection, or Bank of Canada expected-behavior changes.

## Implemented projection contract

Public pure functions:

```python
build_stage_d_synthesis_projection(normalized_facts, conflicts)
finalize_stage_d_request(projection, prompt_instructions)
validate_stage_d_response(response, projection)
```

Version: `stage-d-projection/1`.

The builder returns `prompt_context`, `sidecar`, and `diagnostics`. It performs no I/O, API/database operations, clock access, random-ID generation, semantic summarization, or requirement deduplication. Canonical JSON uses UTF-8, sorted keys, compact separators, `ensure_ascii=False`, and `allow_nan=False`.

The prompt contains a flat requirement list, metadata facts, every current occurrence in dates/evaluation_criteria/submission_rules/deliverables/commercial_clauses/contract_risks, shared evidence_context, detected_conflicts, and context_integrity.

Each requirement preserves original present fields: req_id, category, requirement_type, description, rfso_ref, weight, evidence, qual_status, and evidence_status. It adds requirement_id, evidence_refs, and provenance_status. Description and required proof are never shortened. Missing optional fields remain absent; explicit null category is preserved. No category, type, qualification, PASS, or readiness is inferred.

Requirement source_refs move to the sidecar/shared evidence context. Every original requirement occurrence maps through a source JSON Pointer; even identical duplicate occurrences remain separate. Original req_id is preserved but is not the unique citation identity.

Identifiers:

- Requirements: `R-<full SHA-256>-<occurrence>`.
- Evidence: `E-<full SHA-256>`.
- Facts: `F-<full SHA-256>-<occurrence>`.
- Conflicts: `C-<full SHA-256>-<occurrence>`.

Record identity includes the section and authoritative content. Source-ref ordering is canonicalized only for identity. Original values, duplicates, and order remain intact in the sidecar snapshot. Reordering distinct requirements preserves the ID multiset. An identical duplicate's occurrence suffix identifies its position among identical payload occurrences; it is not a new upstream persistent business identifier. Content changes can change IDs. A digest collision between unequal identity payloads fails hard.

Explicit registries cover actual normalized metadata, evaluation hierarchy/observations, submission observations/conflicts, and the other fact sections. Unknown substantive fields fail with `UNCLASSIFIED_PROJECTION_FIELD`. Historical `_semantic_candidates`, `_specific_types`, and `_raw_evaluation_criteria` are sidecar-only if present. Arbitrary original provenance extension fields remain preserved in evidence originals.

## Sidecar and inline evidence

The self-contained sidecar embeds the exact normalized-facts/conflicts snapshot. It indexes requirement/fact/conflict source pointers and evidence records. Evidence originals preserve source_doc, page, sheet, section, full excerpt, verification, row/cell/range data, and other original validated provenance fields. Every evidence record retains all owner IDs and source occurrence pointers.

Only identical evidence payloads are interned. Multiple owners can reference one evidence record. Source-document-only facts yield document-pointer evidence with unknown verification; filename presence never establishes verification. Conflict sources preserve both alternative texts and original doc/ref/text records. Nothing is inferred to resolve a conflict.

Every exposed evidence ID has inline interpretation context:

- `ALREADY_INLINE`: the complete excerpt is an exact substring of an owning substantive field. The evidence entry points to that owner/field rather than duplicating the excerpt.
- `FULL`: the complete normalized excerpt appears once in shared evidence_context, without the previous 500-character cap.
- `UNAVAILABLE`: no excerpt is available; no quotation or missing locator is fabricated.

Available locators and existing verification state remain inline. Null locators and redundant non-requirement provenance-status strings are omitted from the compact representation; their authoritative originals remain in the sidecar. Full preservation means preservation of the supplied normalized evidence, not reconstruction of content already lost upstream.

## Response and citation behavior

The internal model response is `{synthesis, citations}`. Synthesis contains existing bid fields, executive_summary, opportunity_type, contract_term, procurement_model, scope_categories, and outline. It does not include the seven deterministic sections or legacy source_citations.

Field-level citations use this shape:

```json
{
  "output_pointer": "/brief/executive_summary",
  "supports": [
    {
      "entity_id": "R-<full digest>-1",
      "field_pointer": "/description",
      "evidence_refs": ["E-<full digest>"]
    }
  ]
}
```

The digest placeholders above are explanatory; actual responses must use exact supplied IDs. List outputs such as scope_categories are cited by item pointer. Suggested outline titles use `{section_index, kind: "proposal", supports: [entity IDs]}`. Proposal titles receive a deterministic “Suggested proposal structure.” note. Factual notes need their own citation; evaluation weights cannot establish word limits. With the current registry, word_limit remains null unless an explicit supported word_limit field is added through a future registry revision.

No character spans or character-level grounding engine were implemented.

Validation rejects unknown IDs, missing/hidden field pointers, non-scalar support fields, wrong-owner evidence, uncited substantive fields, missing/extra response keys, duplicate JSON keys, non-finite values, markdown-wrapped/trailing/partial JSON, and non-completed model responses. It verifies projection integrity before accepting output. There is no permissive truncated-JSON recovery for Stage D.

Structured bid identity/deadline values require exact matching metadata support. Contract term requires exact commercial details with the permitted term topic; otherwise it remains unknown. Packages with any Stage C conflicts cannot produce selected bid deadlines or contract terms in this conservative v1 validator. Conflicts are still attached unchanged to final document_conflicts. No conflict-resolution semantics were added to Stage C.

Operational defaults remain deterministic: owner/value_cad null, sensitivity Standard, outline owner null/status Not Started. Model-written bidder capability/status fields are outside the permitted schema; original requirement qual_status/evidence_status remain unchanged. Required proof is not treated as supplied proof.

**Citation validation establishes traceability and typed/exact-value checks, not semantic entailment.** Arbitrary prose could still misstate a cited fact, imply bidder possession, or imply conflict resolution. The prompt prohibits those behaviors, but this branch does not claim a deterministic semantic proof or a live-model quality acceptance result. The supplied simplified citation contract explicitly defers that stronger grounding problem.

The validated ledger is saved in validation checkpoints when checkpointing is enabled. Legacy brief.source_citations strings are rebuilt from valid source locators for compatibility; they are not a replacement for the complete ledger.

## Authoritative reapplication

Accepted synthesis is passed to the unchanged `apply_stage_d_authoritative_sections` with original normalized inputs. Its seven outputs are compared to the same applicator called with empty synthesis and those same authoritative inputs:

1. qualification_gates
2. evaluation_breakdown
3. submission_requirements
4. key_dates
5. commercial_structure
6. contract_risks
7. deliverables_summary

Final assembly verifies original requirements and conflicts are unchanged and documents equal the existing submission builder's result. Input mutation or authoritative mismatch fails explicitly. An authority failure is not retried through the model.

These checks preserve existing applicator deduplication/filtering behavior; they do not redefine it. The final requirements register retains every normalized occurrence even when the executive summary is selective.

## Diagnostics and bounded retry

Diagnostics measure the exact candidate text: fixed instructions, separator, and canonical context. They include character/UTF-8 byte counts, section sizes with an explicit structural remainder, requirement/category/fact/conflict counts, evidence counts and inline text size, sidecar sizes, provenance availability counts, requirement size statistics, input/projection/sidecar/prompt digests, guard/headroom, and dispatch_allowed.

Token count is null and measurement method UNAVAILABLE. No chars-to-tokens estimate is presented as fact.

The 580,000-character guard and `claude-haiku-4-5-20251001` with 8,000 output tokens remain unchanged. Exactly 580,000 characters dispatches; 580,001 blocks before client dispatch. Diagnostics/request/projection/sidecar are checkpointed before attempts in enabled modes, including overflow evidence.

One loop owns a maximum of two Stage D attempts total across model/API/response-validation failures. Stage D disables the SDK's internal retries through `with_options(max_retries=0)`; Stage A client behavior is unchanged. Retry reuses the same factual projection, adds only a concise error-code correction, and rechecks the exact request size. No Stage A replay, automatic truncation, or partial Bid Brief acceptance occurs.

## Checkpoint modes and artifacts

Environment configuration:

| Mode | Behavior |
|---|---|
| `CHECKPOINT_MODE=off` | Default. No filesystem writes or mandatory root/version lookup. Existing deployments remain operational. |
| `CHECKPOINT_MODE=best_effort` | Attempts writes, records/logs failures by artifact/error type, continues normal runtime if storage fails. |
| `CHECKPOINT_MODE=required` | A failed checkpoint blocks the next expensive stage/API call. |

`CHECKPOINT_ROOT` must be outside the repository and any other Git checkout. The new offline measurement tool and resume entry point explicitly use required mode. No DB storage or migration was added. Legacy ad hoc benchmark scripts were not run or rewritten; use the new required-mode entry points for this branch's evidence/replay workflow.

Bundles live at `<root>/stage-d/<ordered-source-manifest-digest>/<run-id>/`. Atomic writes use same-directory temporary files, flush/fsync, replacement, and a checksummed manifest written last. An interrupted artifact/manifest update cannot be silently accepted as a verified checkpoint.

Recorded boundaries:

- manifest with ordered source hashes, code/prompt/projection/model versions, artifact checksums and write errors;
- preprocessing inputs, with a JSON-only typed codec for integer dictionary keys, tuples, and row sets;
- each Stage A document and completed ordered document-facts list;
- Stage B normalized facts and Stage C conflicts;
- Stage D projection, sidecar, diagnostics, exact candidate request;
- each attempt's request/diagnostics, raw response text/stop reason, validation result;
- accepted Stage D synthesis and final assembled result.

No supplied API key, authorization headers, raw transport exception strings, or SDK credential objects are serialized. Raw checkpoint procurement content was written only under the private external root used for these measurements:

`C:/Users/feras/.codex/checkpoints/bid-intelligence-stage-d`

The committed measurement JSON contains only sanitized statistics/invariant results/digests. Existing source fixtures were not overwritten or added to Git.

In off mode, the sidecar/ledger exist only during the call; there is no durable new narrative audit ledger after it returns. In enabled modes they are retained in the private bundle. Filesystem persistence is limited to the configured host/storage lifetime; this branch adds neither cloud-durable storage nor a cleanup scheduler.

## Resume behavior

Entry points in `stage_d_checkpoints.py`:

```python
load_verified_checkpoint(run_directory, package_files)
resume_procurement_checkpoint(
    run_directory, package_files, api_key, checkpoint_root=external_root
)
```

Actual ordered source filenames and file bytes are required to validate source hashes. The loader checks manifest format, all manifested artifact checksums, upstream code fingerprint, Stage A prompt fingerprint, and model. Git SHA is recorded. A changed commit may reuse upstream work only if the upstream code/prompt fingerprints match; this permits a Stage D-only revision without falsely invalidating expensive Stage A work. Changed projection/D prompt/D code is reported, and D artifacts are always rebuilt rather than reused.

If B and C exist, replay runs D and final assembly without calling A, B, or C. If B is missing, verified completed Stage A facts can feed B. If Stage A is partial, only missing document results are extracted from verified preprocessing. Missing/stale/corrupt inputs fail explicitly. Replays use a new required bundle and record their origin manifest digest.

Offline serialization bundles are marked normalized-only because source file bytes are not available in that workflow; they are not falsely advertised as verified source-package resume checkpoints.

## Offline size measurements

Measured after the implementation commit using the committed tool, with no LLM dispatch. Old prompt measurement uses the original instructions, original pretty serializer/context builder, and its capped requirement excerpts. New measurement uses the exact new instructions and full-excerpt projection. These are actual request formats, not an assumption that the two provenance payload policies are identical.

| Case | Requirements | Old chars | New chars | Reduction chars | Reduction % | Guard headroom |
|---|---:|---:|---:|---:|---:|---:|
| Generic synthetic shared schedules — **not BC acceptance** | 559 | 1,634,675 | 508,709 | 1,125,966 | 68.880% | 71,291 |
| Frozen Bank of Canada | 98 | 166,444 | 189,160 | -22,716 | -13.648% | 390,840 |
| Retained BC attempt2 — **not full package** | 41 | 63,609 | 70,816 | -7,207 | -11.330% | 509,184 |

Negative reduction means the prompt grew. Full SHA-256 entity/evidence references and complete excerpts have substantial overhead on sparsely shared evidence. The synthetic case uses four realistic-length common schedule excerpts across 559 individual obligations; it demonstrates exact interning and mechanical capacity, not a prediction for the full BC evidence distribution.

All three comparisons preserve every normalized requirement and source-ref occurrence:

| Case | Source-ref occurrences preserved | Evidence IDs | Seven authoritative sections | Requirements/documents/conflicts |
|---|---:|---:|---|---|
| Synthetic | 2,236 / 2,236 | 4 | Unchanged | Unchanged |
| Bank of Canada | 115 / 115 | 135 | Unchanged | Unchanged |
| BC attempt2 | 42 / 42 | 45 | Unchanged | Unchanged |

Evidence IDs also represent document-only and conflict-source records, so their count is not necessarily lower than source-ref occurrences. The benchmark invariant checks use explicitly unknown interpretation to exercise deterministic validation/assembly; they are not generated prose or live semantic acceptance evidence.

Reproduce offline measurements:

```powershell
python scripts/measure_stage_d_projection.py --checkpoint-root C:\private\bid-checkpoints
```

Supply `--normalized <retained-normalized-json> --conflicts <retained-conflicts-json>` to measure another pair. It still performs no LLM calls and does not re-extract Stage A.

## British Council checkpoint recovery and acceptance

The original `bc_submission_artifact_projection_live_failure.json` supplies the 559-requirement/seven-conflict failure counts. The inspected original replay script retains output statistics rather than the full B/C facts. Searches of project paths and the available private checkpoint root found no original 559-requirement BC normalized/conflict pair. Newly generated synthetic bundles are explicitly labeled synthetic and are not recovery of that run.

The retained attempt2 facts have 41 requirements and zero conflicts. They were used only as an additional small-fixture measurement, never as full-package proof. No Stage A rerun was performed to replace the missing checkpoint.

**FULL BRITISH COUNCIL CAPACITY ACCEPTANCE NOT YET PROVEN**

## Test and regression evidence

All counts below are actual **local** test runs. No GitHub CI claim is made.

| Run | Result |
|---|---|
| Verified pre-change full baseline | 439 passed, 1 skipped, 0 failed; 19 subtests passed; 61.93 seconds |
| Final focused suites | 452 passed, 0 failed; 19 subtests passed; 8.54 seconds |
| Final entire suite | 513 passed, 1 skipped, 0 failed; 19 subtests passed; 66.68 seconds |

The skipped test is live AI. The existing suite emitted 118 pre-existing client deprecation warnings; baseline had the same warning count. Existing database smoke tests remain part of the full suite; no database code/schema was changed. The 74 new cases are in test_stage_d_projection.py. The retained 41-requirement fixture is locally available but untracked; its new optional regression test skips when that fixture is unavailable in another checkout.

Final focused command:

```text
python -m pytest -q tests/test_stage_d_projection.py tests/test_stage_d_completeness.py tests/test_stage_a_extraction_reliability.py tests/test_stage_b_requirement_dedup_integrity.py tests/test_stage_c_refinement.py tests/test_requirement_semantic_separation.py tests/test_evaluation_hierarchy_integrity.py tests/test_submission_artifact_projection.py tests/test_submission_document_provenance.py
```

Full command: `python -m pytest -q`.

The focused cases cover all requested A–Z behaviors, including duplicate occurrences, stable ID multisets, evidence ownership/full trailing negation, unknown/malformed fields, unchanged evaluation/submission data, conflicts, citation rejection, unchanged requirement capability status, all seven authoritative sections, exact guard boundaries, Unicode accounting, all three checkpoint modes, failure before the next Stage A document, checksum/source/version failures, partial Stage A resume, D-only replay with zero A/B/C calls, single shared retry budget, and post-authority failure without a model retry.

Frozen Bank of Canada projection/validation/authority regression passed on its 98-requirement retained normalized facts and three conflicts. All seven authoritative sections and final requirement/document/conflict values match existing helpers. Existing frozen expected behavior was not retuned. Its accepted blind extraction was not rerun.

`git diff --check` passed. Existing extractor function-body AST comparison passed as described above. No test was weakened to accept invalid v1 responses.

## Known limitations and remaining tracks

1. Full real BC capacity acceptance remains unproven until its actual B/C inputs are recovered or a separately authorized new extraction produces them.
2. This exact v1 contract increases prompt size on the two retained real fixtures. It is not a universal prompt reduction guarantee. Oversized projections continue to fail before dispatch with complete evidence saved in required mode.
3. Field-level citations do not establish semantic truth of free prose. Live-model compliance, executive-summary quality, and resistance to falsely asserting possession/resolution are not claimed proven by deterministic tests.
4. Current normalized inputs can already lack provenance or contain upstream extraction limitations. Projection preserves those limitations rather than manufacturing evidence or changing A/B/C behavior.
5. Checkpoint off mode has no durable sidecar/ledger. Enabled filesystem checkpoints do not guarantee survival of ephemeral-host redeployment; operators choose the private storage root.
6. Version 1 conservatively avoids scalar deadlines/terms in conflicted packages and keeps unsupported word limits unknown. It does not create new semantic date/term/word-limit extraction logic.

Future fallback tracks remain separate: evidence compaction beyond exact sharing, alternative identity representation, duplicate-document handling, upstream granularity/deduplication, or broader synthesis architecture. None was implemented here; no model/guard increase, map-reduce, hierarchy retuning, or .xls remediation was used to improve these figures.

READY FOR FINAL REVIEW
