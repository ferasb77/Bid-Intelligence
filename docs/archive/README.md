# Archive

This directory holds historical evidence, superseded designs, and
not-yet-implemented proposals moved out of the repository root during the
BI Context & Token Optimization Program, Phase 3. It exists so a fresh
agent's ordinary orientation (`docs/current/`) doesn't have to compete with
~70 historical documents for attention — not to hide or devalue them.

## What lives here

- `operational/` — implementation reports, commissioning reports,
  remediation reports, audits, and similar point-in-time records of
  completed past work.
- `engagements/<name>/` — records specific to one buyer/client engagement
  (e.g. `bank-of-canada/`) rather than generic platform architecture.
- `superseded/<subsystem>/` — an explicit prior version in a version chain
  where a later, current version is verified in code (each such directory
  has its own small `README.md` naming the current version and linking the
  historical ones — never synthesized, never rewritten).
- `proposed/` — designs, specifications, or architecture that explicitly
  self-declare a `Proposed` / `Draft` / not-yet-implemented status. These
  were never built as described; do not treat them as evidence of current
  platform behavior.

## Rules for using this directory

- **Archive material remains valid historical evidence.** Moving a
  document here does not retract, weaken, or invalidate any claim it
  makes about what happened at the time it was written.
- **Archive is not current architecture.** For "how does the system work
  right now," use `docs/current/` and the source code it points to, not a
  document in this directory — even one with "architecture" in its name
  (see `proposed/` above for exactly why that distinction matters here).
- **Access this directory for historical or audit questions**, not for
  ordinary task orientation. `docs/current/NAVIGATION.md` says so
  explicitly.
- **Moving a file preserves its git history** at the new path; `git log
  --follow` recovers the original location and full history.
- **Never treat archived proposal or engagement-specific material as proof
  of current platform behavior without verifying against the live source
  code first.** A proposal may never have been built; an engagement record
  describes what was true for one buyer, at one time, not a platform
  guarantee.
- Contents here are not rewritten, summarized, or "corrected" when moved —
  only the mechanical link paths needed to keep cross-references from
  breaking are ever touched, never the substantive prose.

See `docs/current/DOCUMENT_AUTHORITY_MAP.json` for the deterministic
classification that produced this structure, including exactly which
signal justified each document's placement.
