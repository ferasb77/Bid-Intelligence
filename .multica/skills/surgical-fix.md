# Skill: surgical-fix

## Purpose
Apply a minimal, bounded fix to a proven root-cause layer without scope creep, hardcoding, or unnecessary API spend.

## Hard Rules
- Read `CONSTRAINTS.md` and `SPEC.md` in the repository root before editing.
- Touch **ONLY** the file(s) and scope explicitly authorized in the ticket.
- **Max 2 attempts.** If verification fails twice, STOP immediately, mark the issue `BLOCKED`, and post the exact error.
- Prefer `$0.00` verification (in-memory re-composition, existing run artifacts, and `pytest`) unless the ticket explicitly authorizes a live API run under the `CONSTRAINTS.md` USD cap.
- Never hardcode client names or RFP-specific terms. Never add scoring, proposal generation, or unapproved dependencies. Never mutate protected runs (including Bid 1522) or commit to `main`.

## Required Output (Post as Issue Comment and STOP)
1. `git diff --stat` and the exact diff (leave uncommitted for Red-Teamer review unless explicitly instructed otherwise).
2. Root cause and exact change made (3–5 bullets max).
3. Verification results (before vs. after on real run data + test suite pass count) and exact API dollar spend.
4. Any edge cases or trade-offs the human owner should review.
5. Confirmation line: `[API spend], 0 CONSTRAINTS.md rules violated. Stopping for Constraint Red-Teamer review.`
