# Fast Analysis — Product Integration Phase 2 Report (Corrected: Progressive UX + Final Acceptance Hardening)

**Addendum (final acceptance hardening pass):** migration 005 has been
applied to the live Supabase project and independently re-verified here via
a read-only query through the app's own configured connection (§10). One
interpretation is stated explicitly: you did not ask for the `fast_analysis.py`
hook flagged in §1 to be reverted, so it has been **kept**, and this
hardening pass builds on top of it. If that's not what you intended, say so
and it can still be reverted to the milestone-only fallback described there.
See §10 for what changed in this pass and the updated recommendation.

This supersedes the earlier Phase 2 report, which covered only the
completed-analysis view (UNDERSTAND-stage enhancement, View Source
expanders, the stuck-run safety net) and was correctly rejected as
incomplete: Phase 2's core objective was a truthful, durable, progressive
experience **while Fast Analysis is still running**, not only a richer
finished report. This report covers that remaining work end to end.

The three previously-accepted components are unchanged and are not
re-described in depth here — see the prior report section 1.1-1.3 for their
original detail. This report focuses on gaps 1-7 from the acceptance review.

---

## 0. Summary answers (required report fields)

| Field | Answer |
|---|---|
| Persisted milestones implemented | **Yes** |
| Where stored | New `analysis_runs.progress` JSONB column (migration 005, **not yet applied**) |
| How Fast Analysis emits them | An additive, optional, default-`None` `on_task_done` callback parameter on `run_fast_analysis_corpus()` — see §2 for exact diff and why |
| Partial intelligence technically available | Only a small set of **early facts** (title, buyer, submission/clarification deadline, procurement mechanic) — read directly off the identity document's own extracted fields, never re-derived or fabricated. Full section content (evaluation, commercial, ambiguities) is **not** exposed early — see §4 for why |
| Earliest trustworthy information shown | Opportunity title + buyer, as soon as the identity-document task completes (in practice: whichever document Fast Analysis routes to `ROUTE_IDENTITY_EVAL_REQ` — usually the master RFP) |
| Active-run refresh/reconnection | Fully DB-backed; verified — see §6 |
| Polling mechanism and interval | Streamlit `st.fragment(run_every=6)` — no WebSockets/Realtime/queue; stops the instant the run is terminal — see §5 |
| Progressive sections supported | Milestone checklist (9 items) + early facts only; full report sections remain locked until COMPLETE — see §4 |
| What remains unavailable until COMPLETE | Evaluation detail, pricing/commercial detail, ambiguities, buyer intelligence, source map, the PDF, and the full UNDERSTAND-stage intelligence section |
| Stuck-run behavior | Unchanged from the prior report — bounded, user-initiated, never automatic |
| View Source behavior | Unchanged from the prior report |
| Migrations added | `migrations/005_analysis_run_progress.sql` — **additive, not applied, not executed automatically** |
| Tests added | 18 new tests in `tests/test_analysis_service.py` (`TestMilestoneProgress`) + 16 new tests in `tests/test_app_analysis_panel.py` (new file) = 34 |
| Full-suite result | **1446 passed, 2 skipped** (2 skips are the same pre-existing, live-API-gated tests as every prior baseline — not new) |
| Fast Analysis V4 behavior changes | **NONE** — verified: all 98 pre-existing `fast_analysis.py`/V2/V3/V4 tests pass byte-identical, unchanged. **Source changes: one additive parameter, flagged transparently in §2 — please read that section before accepting** |
| Deep Verify behavior changes | **NONE** — not touched, not imported into any new code path |

**Recommendation: PHASE 2 NEEDS FURTHER CORRECTION** — not because anything below is broken (regression gates are green and the flow is verified end to end), but because migration 005 has not been applied to the live database yet, exactly like migration 004 went through a separate review-and-apply step before Phase 2 began. Once you've reviewed §2 (the one deliberate, narrow touch to `fast_analysis.py`) and applied migration 005, this becomes **READY FOR PRODUCT INTEGRATION PHASE 3**.

---

## 1. A flag for your review: the one change to `fast_analysis.py`

Every prior phase in this engagement held `fast_analysis.py` at zero diff.
Delivering **real, non-fake, per-task milestones** (your instruction 1: "must
map to actual Fast Analysis execution events... do not fake progress based
on elapsed time") turned out to require observing when each of
`run_fast_analysis_corpus()`'s internal tasks completes — and that function
currently returns one atomic result only at the very end, with no way for a
caller to observe its internal progress.

I added the smallest possible hook to make that observable, rather than
falling back immediately to milestone-only progression. Before you accept
this, please look at it directly — I do not consider "NONE" an honest
answer to "Fast Analysis V4 behavior changes" when there is a real, if
narrow, diff to the file:

```python
def run_fast_analysis_corpus(documents, api_key, max_document_concurrency=2,
                             on_task_done=None) -> FastAnalysisResult:
    ...  # docstring addition only, no change to existing text
```

And, inside the existing `as_completed` dispatch loop, after each task's
data is already merged into `result` exactly as before — two new lines,
once per branch:

```python
if on_task_done is not None:
    on_task_done(kind, payload, task_result)
```

That is the **entire** diff: one new parameter (default `None`) and two
call sites that fire only when a caller opts in. It does not change:

- what is extracted, from which documents, under which schema/prompt
- routing, chunking, batching, or the focused-section logic
- `max_document_concurrency` (still `2`, still enforced — verified by an
  existing Phase 1 test that continues to pass)
- token limits, temperature, or model
- the ambiguity-detection logic or its inputs
- what `run_fast_analysis_corpus()` returns to a caller that doesn't pass
  `on_task_done`

**Verification, not assertion:** all 98 pre-existing tests across
`tests/test_fast_analysis.py`, `test_fast_analysis_v2.py`,
`test_fast_analysis_v3.py`, and `test_fast_analysis_v4.py` — none of which
pass `on_task_done` — pass unchanged. If you'd prefer `fast_analysis.py` to
stay at literally zero diff instead, say so and I will revert this hook and
fall back to milestone-only progression per your own instruction 3's
explicit escape valve: `CORPUS_PREPARED` → (opaque `ANALYZING`, no
sub-milestones) → `AMBIGUITIES_READY` → `REPORT_ASSEMBLED`, with no early
facts and no `OPPORTUNITY_IDENTIFIED`/`DATES_READY`/etc. granularity. I
judged the richer version worth proposing given your own instruction that
milestones "must map to actual... execution events," but this is exactly
the kind of scope boundary you've been precise about throughout this
engagement, so I'm surfacing it rather than deciding it silently.

---

## 2. Milestones: what they are and what real event each maps to

Nine milestones, in `analysis_service.py` as `MILESTONE_*` constants and
canonical order `MILESTONE_ORDER`:

| Milestone | User-facing label | Real event it maps to |
|---|---|---|
| `CORPUS_PREPARED` | "Preparing procurement documents" | All corpus documents downloaded and text-parsed (existing PREPARING→ANALYZING boundary) |
| `OPPORTUNITY_IDENTIFIED` | "Understanding the opportunity" | The identity-document task's `doc_metadata` contains a title or client |
| `DATES_READY` | "Identifying critical dates and requirements" | Same task's `doc_metadata`/`typed_observations` contains a submission or clarification deadline |
| `PROCUREMENT_STRUCTURE_READY` | "Mapping procurement structure" | Same task's `requirements` array is non-empty |
| `QUALIFICATION_READY` | "Reviewing qualification requirements" | Same task's `requirements` array is non-empty |
| `EVALUATION_READY` | "Mapping evaluation criteria" | **Every** evaluation-contributing task (the identity task, the EVAL_ONLY batch, each EVAL_ONLY single document, and each focused `rated_criteria` section job) has completed — counted, not guessed, by mirroring the engine's own deterministic task-list construction (§3) |
| `COMMERCIAL_READY` | "Reviewing commercial terms" | The `ROUTE_COMMERCIAL_ONLY` document's task completes (vacuously reached immediately if the corpus has no such document) |
| `AMBIGUITIES_READY` | "Checking ambiguities and bid risks" | `run_fast_analysis_corpus()` has returned — ambiguity detection runs synchronously, inside that call, before it returns, so this is a real completion event, not a guess |
| `REPORT_ASSEMBLED` | "Preparing your intelligence report" | The PDF has been rendered and uploaded to storage |

**Honesty about granularity:** `OPPORTUNITY_IDENTIFIED`, `DATES_READY`,
`PROCUREMENT_STRUCTURE_READY`, and `QUALIFICATION_READY` all derive from
the *same* task result (the identity document's schema bundles title,
dates, and requirements into one LLM call — see `_IDENTITY_EVAL_REQ_SCHEMA`
in `fast_analysis.py`). They will, in practice, always be marked together
at the same real moment. They're kept as four distinct constants because
they represent four conceptually distinct report sections and match your
requested vocabulary, not because the current V4 architecture can actually
distinguish their completion in time. This is stated plainly rather than
implied otherwise.

**Order is not guaranteed.** Tasks run concurrently (`max_document_concurrency=2`,
unchanged); whichever LLM call returns first fires first. The UI
(`MILESTONE_ORDER`) always displays the fixed canonical order and marks
each item ✅/⏳ by set membership, never by assuming reach-order.

**`EVALUATION_READY`'s task count is computed correctly, not assumed:**
`analysis_service._compute_eval_tasks_total()` mirrors — calls, does not
reimplement — `run_fast_analysis_corpus`'s own public, deterministic
`route_document()`/`find_section()`/`BATCH_GROUP` to count exactly how many
real tasks contribute evaluation data for *this* corpus, before the engine
runs. Verified with dedicated tests, including one where a document is
both EVAL_ONLY-routed *and* contains a focused `rated_criteria` section
(correctly counted as 2 separate tasks, matching the engine's actual
2-loop task construction).

---

## 3. Durable persistence

**Storage:** new `analysis_runs.progress` JSONB column
(`migrations/005_analysis_run_progress.sql`), nullable-by-default
`'{}'::jsonb`. I first checked whether the existing `telemetry` column
could hold this (per your instruction to check before adding schema) and
concluded no: `telemetry`'s own Phase 1 docstring says it is
"non-engineering-facing... never rendered in the client-facing report,"
which is the opposite of this column's purpose (progress *is* meant to be
rendered live). Overloading it would blur an existing, already-tested
contract rather than extend it cleanly.

**Shape:**
```json
{
  "milestones": [{"milestone": "CORPUS_PREPARED", "reached_at": "<ISO 8601 UTC>"}, ...],
  "early_facts": {"title": "...", "buyer": "...", "submission_deadline": "...", ...}
}
```

**Not migration 004.** Migration 004 (already live) is untouched. Migration
005 is additive only, adds one column to one table, changes no RLS, and —
per your instruction — is **not applied and not executed automatically**.
Apply it the same way you applied 004: review, then run manually via the
Supabase SQL editor.

**Never only in thread memory.** `analysis_service._ProgressTracker`
persists via `db.update_analysis_run(run_id, {"progress": ...})` on every
new milestone reached and every new early fact learned — a page refresh, a
different browser tab, or a reconnect all read the same row a manual
`SELECT` would. A bug inside the tracker is caught and swallowed
(`on_task_done` never raises) so a milestone-mapping mistake can, at worst,
cost one missed UI update — never fail the underlying analysis run.

---

## 4. Early trustworthy intelligence — and what I deliberately did NOT expose

**Exposed, and why it's safe:** `title`, `buyer`, `file_number`,
`submission_deadline`, `clarification_deadline`, `procurement_mechanic`.
Every one of these is read **directly** off the identity task's own
`doc_metadata` / `typed_observations` fields — the model's literal
extracted values for an already-completed task, exactly as they'll appear
in the final report. Nothing is inferred, reformatted, or guessed, and a
field is only ever set once (never overwritten by a later, possibly-empty
value) — see `_ProgressTracker.set_early_facts()`.

**Deliberately NOT exposed: "procurement/category structure"** (named
service categories/lots), one of your own candidate fields. Investigating
`scripts/fast_analysis_report_adapter.py` (the module that derives this for
the final report) surfaced a real risk: `build_fast_report_content()`
falls back to **static placeholder content** (tagged
`FACT_ORIGINS: "SAFETY_NET_FALLBACK"`) whenever a field is genuinely
missing — correct, rare-case behavior for a FINAL, fully-populated report,
but unsafe to invoke on a deliberately partial, still-in-progress result,
where most fields are *expected* to be missing and the fallback would fire
constantly — showing placeholder text as if it were real early
intelligence. That would violate your own instruction 3 ("do not expose...
unvalidated intermediate output"). So this candidate is rejected, stated
explicitly, exactly as instruction 3 anticipated might be necessary.

**Full sections (evaluation, commercial, ambiguities, buyer intelligence,
source map) stay locked until COMPLETE.** This is the "progressive section
availability" instruction's own explicit fallback: *"If the engine
currently produces only atomic final structured output, do not fabricate
section readiness... milestone progression is still mandatory; early facts
may be shown only where genuinely available; full sections may remain
locked until completion."* `run_fast_analysis_corpus()` does produce
per-task partial data internally (which is how milestones/early-facts work
at all), but exposing full, stable section content earlier would mean
either (a) re-deriving it through the same fallback-laden adapter
prematurely (rejected above), or (b) duplicating that adapter's
non-trivial formatting logic a second time in the integration layer,
against a moving, still-updating input — a correctness risk for no
Phase-2-authorized benefit, since Phase 1 already established that reports
render from a stable, complete result. I judged the honest, bounded answer
to be: real milestones (progress is real), a few genuinely-safe early
facts (also real), full sections locked until they're actually final.

---

## 5. Active-run UX and polling

`app.py`'s Fast Analysis panel, for a non-terminal run, now shows (instead
of a bare status line):

- The existing status label (unchanged wording)
- A 9-item milestone checklist (✅ reached / ⏳ pending), fixed canonical
  order, plain user-facing language only — no route/task names (verified by
  a dedicated test scanning `MILESTONE_UI_LABEL` for forbidden substrings
  like `ROUTE_`, `focused_`, `batch`)
- A "What we know so far" box once any early fact exists
- The existing stuck-run affordance (unchanged)

**Polling mechanism:** `st.fragment(run_every=ANALYSIS_POLL_INTERVAL_SECONDS)`
(`ANALYSIS_POLL_INTERVAL_SECONDS = 6`) — Streamlit's own built-in
fragment-autorefresh (stable since 1.33; this repo runs 1.61.1). Only the
fragment re-runs every 6 seconds, not the whole page. No WebSockets, no
Supabase Realtime, no queue platform, no new dependency. At ~6s intervals
across a typical 2-4 minute run, that's roughly 20-40 lightweight reads per
active viewer per run — not a meaningful load concern.

**Stops at terminal, verified:** each tick re-fetches the run fresh from
the database; the instant it's no longer non-terminal, the fragment issues
one full-page `st.rerun()` and is not entered again — the page falls
through to the existing COMPLETE/FAILED branches. Tested directly
(`test_triggers_a_full_rerun_once_the_run_becomes_complete` /
`..._becomes_failed`).

**Testability note:** an `@st.fragment`-decorated function's body does not
execute outside a real Streamlit script-run context (confirmed directly —
calling it in a bare-mode test silently no-ops). The actual rendering logic
is therefore factored into a plain function, `_render_active_run_progress()`,
which the fragment wrapper (`_poll_active_analysis()`) just calls; every
test exercises the plain function directly.

---

## 6. Refresh / navigation / reconnection — verified

Flow: start → active → refresh browser (or navigate away and back) →
return to bid → same run resumes, showing current progress; no duplicate
run is created.

This was already structurally true from Phase 1 (`get_latest_analysis_run`
re-queries the database on every page load; nothing about run identity
lives in `st.session_state`) — Phase 2 adds the progress-checklist content
on top of the same mechanism, so a refresh mid-run now also shows current
milestone state, not just "still running." Explicitly tested:
`test_refresh_does_not_create_duplicate_run_and_returns_same_active_run`
simulates three sequential "page loads" against an active run and confirms
`create_analysis_run` is never called; the DB-native
`idx_analysis_runs_one_active` partial unique index (from migration 004,
unchanged) remains the actual, atomic guard — the application layer is
confirmed to honor it, not to replace it.

---

## 7. Progressive section availability — final answer

As stated in §4: milestone progression (mandatory, delivered) + early facts
where genuinely available (title/buyer/dates/mechanic, delivered) + full
sections locked until COMPLETE (the documented, deliberate limitation).
"Opportunity Snapshot — Available" in your example is realized as the
"What we know so far" box; "Evaluation — Still analyzing" / "Commercial —
Still analyzing" are realized as the corresponding checklist rows staying
⏳ until their milestone fires, with no content shown for them until then.

---

## 8. Regression gates run

| Gate | Result |
|---|---|
| `py_compile` (`fast_analysis.py`, `analysis_service.py`, `database.py`, `app.py`, both new/changed test files) | Clean |
| `git diff --check` | Clean |
| `fast_analysis.py`/V2/V3/V4 engine tests (98 tests, none passing `on_task_done`) | All pass, unchanged — proves zero behavior change |
| `tests/test_analysis_service.py` (33 Phase-1/stuck-run tests + 18 new `TestMilestoneProgress` tests = 51) | All pass |
| `tests/test_app_analysis_panel.py` (new, 16 tests) | All pass |
| `tests/test_fast_analysis_app_adapter.py` (15, unchanged) | All pass |
| Full repository suite (`pytest -q`) | **1446 passed, 2 skipped** (same 2 pre-existing live-API skips as the prior baseline) |
| Manual end-to-end render: `app._render_fast_analysis_panel()` called directly against a synthetic non-terminal run with real milestone/early-fact data (mocked DB, mocked Streamlit) | Executes without exception |
| Manual end-to-end render: `pages.stage_understand.page_understand()` against a real, populated `OpportunityIntelligence` contract (unchanged from the prior report — re-confirmed unaffected) | Executes without exception |

No live LLM calls were made anywhere in this phase.

---

## 9. Files changed / added this correction

- [fast_analysis.py](fast_analysis.py) — **flagged in §1**: one additive `on_task_done` parameter + two observational call sites. Zero behavior change (verified).
- [analysis_service.py](analysis_service.py) — milestone constants, `_compute_eval_tasks_total`/`_compute_commercial_tasks_total`, `_ProgressTracker`, wiring into `_execute_fast_analysis_run`.
- [database.py](database.py) — `progress` added to `update_analysis_run`'s updatable-field whitelist.
- [app.py](app.py) — `_should_poll`, `_render_milestone_checklist`, `_render_active_run_progress`, `_poll_active_analysis` (the `st.fragment`), `_render_fast_analysis_panel` updated to delegate the non-terminal case.
- [migrations/005_analysis_run_progress.sql](migrations/005_analysis_run_progress.sql) — new, additive, **not applied**.
- [tests/test_analysis_service.py](tests/test_analysis_service.py) — new `TestMilestoneProgress` (18 tests).
- [tests/test_app_analysis_panel.py](tests/test_app_analysis_panel.py) — new file (16 tests).

---

## 10. Final acceptance hardening pass

Triggered by: "Migration 005 has been reviewed, applied successfully...
Proceed with the Phase 2 final acceptance hardening only."

**Live verification (read-only, non-destructive):** queried
`analysis_runs.progress` through the app's own `database.get_client()` (the
same connection the running app uses) — `select id,status,progress from
analysis_runs limit 3` succeeded (0 rows, since no Fast Analysis run has
ever been started in the live app yet — expected, not an error). This
confirms the column exists and is queryable exactly as migration 005
defines it, independent of your own verification. No row was created,
modified, or deleted — I deliberately did not create a throwaway
`analysis_runs` row for a real bid to test a full write round-trip, since
that would show up as a fake in-progress analysis against one of your real
bids; the write path itself remains covered by the mocked test suite
below, and will get its first real-data exercise on an actual Fast
Analysis run.

**Gap closed:** `_ProgressTracker`'s docstring promised "a bug in this
tracker must never fail the underlying analysis," but that promise was
only actually enforced *inside* `on_task_done` and `_persist()` — not
around the tracker's own `mark()` / `set_early_facts()` logic when called
directly (as `_execute_fast_analysis_run` does for `CORPUS_PREPARED`,
`AMBIGUITIES_READY`, `REPORT_ASSEMBLED`), and not around **constructing**
the tracker itself. Hardened:

- `mark()` and `set_early_facts()` are now each wrapped end-to-end (not
  just their `_persist()` call), so any bug anywhere in either method's own
  logic is swallowed at the source, regardless of which caller invoked it.
- A new `_NullProgressTracker` (every method a no-op) is the fallback if
  `_ProgressTracker(...)`'s own constructor raises — `_execute_fast_analysis_run`
  now wraps construction in its own `try/except`, so even a bug in
  `_compute_eval_tasks_total`/`_compute_commercial_tasks_total` at
  construction time degrades to "zero progress reporting for this run,"
  never a FAILED run.

**6 new tests** (`TestProgressTrackerHardening` in
`tests/test_analysis_service.py`): `mark()` survives a broken `_persist`;
`mark()` survives its own corrupted internal state; `set_early_facts()`
survives a broken `_persist`; every `_NullProgressTracker` method is a safe
no-op; a fully-broken `_ProgressTracker` constructor still lets a run reach
COMPLETE with the real analysis result fully persisted; a mid-run engine
failure leaves already-persisted progress (`CORPUS_PREPARED`) intact rather
than wiping it, and still correctly ends in FAILED.

**Regression, run again in full:** `py_compile` clean, `git diff --check`
clean, `tests/test_analysis_service.py` now 57/57 (51 + 6 new), full
repository suite **1452 passed, 2 skipped** (same 2 pre-existing skips as
every prior baseline in this engagement — no new failures, no new skips).

**The `fast_analysis.py` question from §1:** not explicitly answered in
your message authorizing this pass. Since you did not ask for a revert, I
have treated the hook as accepted and hardened the system built on top of
it. It remains a one-line-parameter, two-call-site, default-`None`,
behavior-verified-unchanged addition — described in full in §1 — and is
still reversible on request if this reading is wrong.

---

## Recommendation

**READY FOR PRODUCT INTEGRATION PHASE 3.**

Both items from the prior recommendation are now resolved: migration 005
is live and independently re-verified (§10), and the one remaining
robustness gap in the progress-tracking layer (construction-time and
direct-call defensiveness) has been closed and tested. Every previously
accepted component (UNDERSTAND-stage placement, View Source expanders, the
stuck-run safety net) is unchanged. Fast Analysis V4 behavior remains
verified unchanged (98/98 engine tests, byte-identical). Deep Verify is
untouched.

The one open item is not a defect but a decision that's still yours: the
`fast_analysis.py` hook in §1. Everything in this report is built assuming
you're comfortable with it; say the word and it reverts cleanly to the
milestone-only fallback with no other changes needed.

Then STOP. Do not begin Phase 3.
