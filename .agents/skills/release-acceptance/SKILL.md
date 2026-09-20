---
name: release-acceptance
description: >-
  Checklist for resuming or re-attempting a real (non-synthetic, budget-
  consuming) acceptance step against a live external provider, in this
  repo's incremental commissioning style. Use this whenever a task says
  "resume commissioning," asks for exactly one real call/run to prove a
  gate, or re-attempts a previously failed acceptance step, instead of
  re-deriving the procedure (repeated across Phase 5's live-telemetry
  commissioning attempts).
---

# Release / Commissioning Acceptance

## Before attempting
- Confirm branch/HEAD match what the task expects
  (`python scripts/agent_context.py`).
- Confirm prior evidence (a telemetry event, a commissioned artifact,
  a prior run's output) still exists exactly as before — don't assume
  a previous session's state; re-check it live.
- Confirm no other run of the same expensive/budget-consuming operation
  is in flight, so results aren't attributed to the wrong attempt.

## Attempting
- Make the **smallest possible** real exercise of the gate under test —
  never the full workflow (no Fast Analysis, no Phoenix, no large
  document) unless the task specifically requires it.
- **No retry loop.** One real attempt. If it fails, record the failure
  honestly (what failed, the exact error) and stop — do not retry hoping
  for a different outcome, and do not fall back to synthetic data and
  declare success.

## After attempting (success or failure)
- Cross-check every field of the result against what was expected,
  preserving `NULL`/absent fields as `NULL` — never backfill a missing
  field with a guess.
- Never delete or overwrite prior genuine evidence (an earlier failure
  event, a previous commissioned artifact) to make a report look cleaner.
- Run whatever reporting/aggregation layer consumes this evidence and
  confirm it reflects the new result correctly alongside prior results.
- Declare PASS only against the task's own explicit acceptance
  criterion — not a softened version of it. A partial success (e.g.
  "everything works except the one real call") is a FAIL on that
  criterion, reported honestly, not a PASS with caveats.
- Skip the full test suite / a new commit if nothing in the working tree
  actually changed — an acceptance attempt is not automatically a code
  change.
