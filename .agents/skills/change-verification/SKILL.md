---
name: change-verification
description: >-
  The standard before/after-work checklist for changes to this repository:
  branch/HEAD verification, py_compile, git diff --check, test scope,
  migration/deployment discipline. Use this whenever starting or finishing
  a code change, instead of re-deriving the checklist from a task prompt.
---

# Change Verification

Full detail lives in
[`docs/current/CHANGE_VERIFICATION.md`](../../../docs/current/CHANGE_VERIFICATION.md)
— this file is the short, progressive-disclosure entry point; read the
linked runbook only if a step below isn't enough.

## Before work
- `git branch --show-current`, `git rev-parse HEAD`, `git status --short`
  (or `python scripts/agent_context.py`).
- Leave any pre-existing uncommitted/untracked work alone.

## After code changes
- `python -m py_compile <touched .py files>`.
- `git diff --check`.
- Run the targeted test file(s) first, then the full suite **once**.
  Twice only for acceptance/commissioning work that needs determinism
  proof, or to confirm a suspected flake — see the runbook for the full
  reasoning.

## Database / deployment
- Never rewrite an applied-or-not migration file.
- A migration file existing is not the same as it being applied to a live
  database — check explicitly.
- Never merge `main` or deploy production without the current task
  explicitly authorizing it.

## Reporting
- State only what you verified. Mark estimates as estimates. Say
  "unavailable" rather than approximate when something can't be measured.
