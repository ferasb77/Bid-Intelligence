# Intelligence Engine Rebuild — Release-Blocking Architectural Constraints

Owner directives of 2026-11-21. Any violation blocks release of the rebuilt
FAST/FULL engine. Each item must be verified and evidenced before a Phoenix
Beta release candidate is proposed.

## C1. Tenant isolation (no cross-tenant intelligence)

1. All source documents, extracted findings, both analysts' outputs, the
   evidence register, reconciliation and adjudication records, verification
   results and reports are scoped to the originating organization
   (`organization_id`) and bid.
2. Analysing one tenant's package never retrieves or uses another tenant's
   documents, findings, analysis history or reports.
3. No global or cross-tenant knowledge base is populated from client
   documents.
4. Isolation is enforced by the existing mechanisms — `tenancy.py`
   (`require_bid_access`, `start_*_analysis_for_organization`, session
   revalidation) and database row scoping — never by prompt wording alone.
   New engine entry points go through these; new tables carry
   `organization_id` and follow the existing isolation pattern.
5. No automatic learning, reusable-memory promotion or self-modifying analysis
   instructions under the current authorization. The engine does not read
   `organizational_memory` or `content_library`. Any future learning needs
   separate approval and must stay inside the tenant's own environment.

## C2. Each package analysed on its own evidence (no RFP-specific behaviour)

1. Each procurement package is interpreted only from its own source documents
   and general-purpose instructions. Findings from earlier packages — even the
   same buyer's — are never evidence for a new one.
2. No buyer-, document-, reference-number-, filename-, hash- or phrase-specific
   rules; no memorized requirements, dates or report text; no evaluation-case
   examples in production prompts; no per-source verification exemptions.
3. Evaluation labels and fixtures live only under `tests/` / evaluation
   tooling and cannot be imported by production modules (checked by a test).
4. Validation includes genuinely unfamiliar RFPs.

## C3. External provider processing (separate authorization, currently OPEN)

1. Sending client documents to a second provider (OpenAI) needs the owner's
   separate authorization after its data-processing, retention and training
   terms are confirmed. Approval of cross-provider processing does not imply
   approval of cross-tenant sharing, and vice versa.
2. Until authorized, the independent-analyst path is not called with client
   data, and no report is labelled as independently verified by two models.
3. Status: **OPEN** — no OpenAI key, model ID or authorization supplied.

## C4. Environment and release

1. Work only on branch `feature/intelligence-engine-rebuild` (from `606c16d`).
   The accepted Beta baseline, WP1/WP2 branches and live data are untouched.
2. No live Beta container switch, live migration or client-data change without
   explicit deployment authorization.
3. A report is never marked verified when a required model pass failed.
