# Bid Intelligence — Gemini CLI Instructions

Short on purpose. Full product-philosophy doctrine lives in
`MANIFESTO.md` / `GOVERNANCE.md` / `ANTI_GOALS.md` / `AGENT.md` — read
those only when a task actually needs that depth, not by default.

## Start every task

1. `python scripts/agent_context.py` — branch, HEAD, working-tree status,
   migration state, entry points. Read-only, no model calls.
2. `docs/current/SYSTEM_STATE.md` — what the system currently is.
3. `docs/current/NAVIGATION.md` — where to look for the subsystem the task
   touches, before any broad repo exploration.

## Standing rules

- Root `*_REPORT.md` / `*_AUDIT.md` / `*_COMMISSIONING_REPORT.md` files
  are historical operational records, not current architecture. See
  `docs/current/ROOT_DOC_INVENTORY.json` (deterministic classification).
  Read one only when the task specifically needs historical evidence.
- Keep evidence, canonical procurement truth (`requirements`, governed
  once a bid is `governed`), and AI-derived intelligence strictly
  separate. Never invent a requirement or silently repair a procurement
  fact.
- A migration file in `migrations/` is not the same as it being applied
  to a live database. Check explicitly.
- Never merge `main` or deploy production unless the current task
  explicitly authorizes it.
- Use `docs/current/CHANGE_VERIFICATION.md` for the standard before/after
  checklist rather than re-deriving it.

## Scope note

This file targets the Gemini CLI's project-context convention
specifically (verified locally installed). It does not assume or
configure anything Antigravity-IDE-specific — Antigravity's own exact
context-loading behavior was not independently verified when this file
was written.
