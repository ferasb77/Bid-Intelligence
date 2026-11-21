# Skill: forensic-trace

## Purpose
Trace a reported bug, missed RFP requirement, or output discrepancy across the Bid Intelligence pipeline to prove the exact failing layer before any code is modified.

## Hard Rules (STRICTLY READ-ONLY)
- Read `CONSTRAINTS.md` and `SPEC.md` in the repository root first.
- Make **0 file edits**, **0 database writes/migrations**, and **0 external LLM API calls** ($0.00 spend).
- Do NOT propose a refactor, new architecture, or additional pipeline layers.

## Execution Steps
1. Locate the raw source input, run artifacts/logs, validation output (if present), and final rendered output for the run specified in the ticket.
2. If specific missed items are not listed in the ticket, identify the failing/missing items from the run's validation output or by comparing the raw source against the final output.
3. Trace each item through three stages and mark **PRESENT / MANGLED / MISSING**:
   - **Stage A — Ingestion:** Is the exact text intact in the extracted source text?
   - **Stage B — Raw Model Output:** Did the model receive it and extract it into the raw inventory/register?
   - **Stage C — Post-Processing & Report Assembly:** Was it dropped, filtered, or altered during composition/rendering?

## Required Output (Post as Issue Comment and STOP)
1. Compact table: `Item | Stage A (Ingestion) | Stage B (Raw Model) | Stage C (Final Output)`.
2. Exact root-cause layer and specific `file_path -> function_name` responsible.
3. Exact paths of artifacts and code inspected.
4. Confirmation line: `0 files edited, 0 API calls made ($0.00), 0 CONSTRAINTS.md rules violated.`
5. **STOP.** Do not reassign or create sub-issues.
