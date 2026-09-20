# Change Verification

The repeatable workflow rules that used to be retyped into every task
prompt (Phase 1 audit finding: none of this was structurally encoded
anywhere — `py_compile`/`git diff --check` appeared only in prose
*describing* past runs, never enforced by CI, a hook, or a Makefile; none
exist in this repo). This file is that durable home. Reference it; don't
copy it into a task prompt.

## Before work

- Verify current branch and HEAD: `git branch --show-current`,
  `git rev-parse HEAD` (or `python scripts/agent_context.py`).
- `git status --short` — read it before touching anything.
- If uncommitted or untracked work exists that isn't yours, leave it alone.
  Never `reset`/`clean`/`checkout --` over it without being told to.

## After code changes

- `python -m py_compile <every touched .py file>` — cheap, always do this.
- `git diff --check` — catches trailing whitespace/conflict markers, not a
  style opinion.
- Run the **targeted** test file(s) for what you touched.
- Run the **full suite once** after a substantive change.

### On running the full suite twice

Phase 1 found "run full suite twice" was never a repo rule — it appeared
only because individual task prompts asked for it, case by case, usually
for acceptance-grade commissioning work where flaky-vs-real failure needed
to be ruled out.

**Default: run the full suite once.** Run it a second time only when:
- the task is an acceptance/commissioning deliverable that explicitly
  needs to demonstrate determinism, or
- the first run showed something inconsistent (a flake, an ordering-
  sensitive failure) worth confirming before trusting either result.

Don't spend a second full run's tokens as habit. If a task's own
instructions ask for two runs, follow the task.

## Database / migration discipline

- Never rewrite an already-numbered migration file, applied or not.
- A migration file existing in `migrations/` is **not** the same as it
  being applied to any live database — always distinguish "written" from
  "applied" explicitly, in code comments and in any report.
- Do not apply a migration to any database (dev, staging, or otherwise)
  without the task explicitly authorizing it. When authorized, prefer the
  repo's established manual/dashboard-apply convention (every migration
  file 001–013 documents this) unless told otherwise.

## Deployment

- Never merge `main` unless explicitly instructed for that specific task.
- Never deploy production unless explicitly instructed for that specific
  task. A prior approval does not carry forward to a later task.

## Acceptance reporting

- State only what you verified, and how. Mark inferred/estimated claims as
  such.
- If something is genuinely unknown or unmeasurable with available tools,
  say so plainly (e.g. "PER-CALL TOKEN ATTRIBUTION UNAVAILABLE") rather
  than approximating it into a false precision.
- Never declare PASS on a claim you didn't actually check.
