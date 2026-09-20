# Bid Intelligence — Phase 8 Production Readiness, Security & Tenancy Audit

**Audit date:** 2026-09-15 (UTC)
**Scope:** Audit only. No application code, schema, migrations, Supabase policies, auth settings, environment variables, storage buckets, or deployment configuration were modified. No migration 006 created. No RLS enabled on any table. No users created. No live LLM calls made.
**Baseline audited:** commit `f6a6d25d9d906a44c378ff465afbedfb54cfe158`, tag `bid-intelligence-generalized-v2`, engine `fast-analysis-v4`, regression baseline `1529 passed, 2 skipped`.
**Verification method:** live re-query of the actual Supabase project (`whonalbdpbubaqhpzrnw`, confirmed by name/URL match against this app's `.env`) via direct `pg_catalog`/`pg_policies` SQL and Supabase's own security advisor, cross-checked against every migration file and `supabase_schema.sql` in this repo — not inferred from repo comments alone, several of which are now stale (see §3).

---

## 1. Executive Assessment

Bid Intelligence today is a **single-tenant, unauthenticated, service-role-only application**. There is no login, no session identity, no user table, and no organization/tenant model anywhere in the code or the live database. The application's one Supabase client (`database.py:get_client()`) always connects with the **service-role key**, for every operation, for every table — this is what makes the product work correctly today (it needs no RLS to function), and it is also precisely why the product cannot safely become multi-user without new work first.

The live database is in better shape than the repo's own SQL files suggest: 13 of 16 application tables actually have RLS **enabled** on the live project (with zero policies, i.e. fail-closed to any non-service-role caller) — a live, undocumented improvement over `supabase_schema.sql`'s own comment ("RLS: disable for now"). But **3 tables — `bid_briefs`, `bid_decisions`, `firm_profiles` — have RLS disabled today**, confirmed independently by both a direct SQL query and Supabase's own advisor (ERROR-level finding). As long as only the service-role key is ever used, this is not exploitable. It becomes exploitable the moment any anon/publishable key is introduced into a browser-facing surface — which is exactly what a Supabase-Auth-based production migration would naturally introduce, unless these 3 tables are fixed first.

There is no data-corruption or destructive-operation emergency here — the single-user internal deployment this was built for is coherent and matches its own architecture. The gap is entirely about what's missing before a second, mutually-untrusted user or organization is let in.

## 2. Current Security Architecture

Answered directly, from code and live schema — not inferred:

| Question | Answer |
|---|---|
| User authentication? | **No.** No login flow, no password check, no OAuth, no session-cookie identity anywhere in `app.py` or any `pages/*.py`. `requirements.txt` includes no auth library. |
| Session identity? | **No.** Streamlit's `st.session_state` holds UI state (an optionally-pasted Anthropic API key, in-progress extraction data) — never a user identifier. |
| Application user table? | **No.** No `users` table in the schema. Supabase's own `auth.users` table exists (Supabase Auth is provisioned by default on every project) but is confirmed **empty** (`select count(*) from auth.users` → `0`, live-verified) — nobody has ever signed up; the feature is present but entirely unused. |
| Organization/tenant model? | **No.** No `organizations` or `organization_members` table; no `org_id`/`tenant_id` column anywhere in the schema. |
| Bid ownership? | **No real ownership.** `bids` has no `owner_id`/`created_by` foreign key to a user. `analysis_runs.created_by` exists as a free-text column, but the one call site that populates it (`pages/stage_understand.py:260`) hardcodes the literal string `"app-ui"` regardless of who is using the app — it carries no real identity today. |
| Row-level authorization in application code? | **No.** Every `database.py` read/write function filters only by `bid_id` (or a row `id`); none checks a caller's identity or organization. |
| Row-level authorization in Supabase (RLS)? | **Partial and inconsistent** — see §3. 13 tables RLS-enabled-no-policy (fail-closed to anything but service-role); 3 tables RLS-disabled (open to any key with API access, though none but the service-role key is used today). |
| Does the app operate primarily via the service-role key? | **Yes — exclusively.** `database.py:get_client()` is the only place a Supabase client is created anywhere in the codebase (verified by repo-wide grep), and it always resolves `SUPABASE_SERVICE_KEY` (Streamlit secrets first, then `.env`). There is no anon-key code path at all. |
| Which operations bypass RLS? | **All of them.** Because the only client the app ever constructs is service-role, every single read and write in the application — regardless of which table's RLS setting — bypasses RLS unconditionally. RLS's current enabled/disabled state is, today, cosmetic to the running application; it only starts to matter the moment a non-service-role key is used anywhere (e.g. a future browser-side Supabase client, or a leaked service key limited by RLS instead — which would not help, since a leaked service key bypasses RLS by definition). |

**Streamlit-specific architectural note:** Bid Intelligence is a server-rendered Streamlit app, not a single-page app shipping JS to the browser. The service-role key lives only in server-side Python process memory (`.env`/Streamlit secrets) and is never transmitted to client code — this is *why* today's service-role-everywhere design isn't already a live secret-exposure incident, but it is also why the entire product currently has no concept of "this browser tab belongs to user X."

## 3. Table-by-Table RLS Audit (live-verified)

Source: `select relname, relrowsecurity from pg_class ...` executed directly against project `whonalbdpbubaqhpzrnw`, cross-checked against `select * from pg_policies where schemaname='public'` (returned **zero rows** — no policy exists on any table, anywhere), and independently confirmed by Supabase's own `get_advisors(type=security)` linter.

| Table | RLS enabled (live) | Policies | Anon/authenticated access | Service-role bypass | Risk if a non-service-role key is ever used client-side |
|---|---|---|---|---|---|
| `bids` | **YES** | 0 | None (fail-closed) | Yes | None today (fail-closed) |
| `requirements` | YES | 0 | None (fail-closed) | Yes | None today |
| `tasks` | YES | 0 | None (fail-closed) | Yes | None today |
| `documents` | YES | 0 | None (fail-closed) | Yes | None today |
| `document_versions` | YES | 0 | None (fail-closed) | Yes | None today |
| `outline_sections` | YES | 0 | None (fail-closed) | Yes | None today |
| `content_library` | YES | 0 | None (fail-closed) | Yes | None today |
| `coaches` | YES | 0 | None (fail-closed) | Yes | None today |
| `clarifications` | YES | 0 | None (fail-closed) | Yes | None today |
| `debriefs` | YES | 0 | None (fail-closed) | Yes | None today |
| `deliverables` | YES | 0 | None (fail-closed) | Yes | None today |
| `analysis_runs` | YES | 0 | None (fail-closed) | Yes | None today |
| `analysis_results` | YES | 0 | None (fail-closed) | Yes | None today |
| **`bid_briefs`** | **NO** | 0 | **Full read/write for any key with PostgREST access** | Yes | **All buyers' AI-generated executive summaries, evaluation breakdowns, commercial structure, and contract risk data readable/writable by anyone holding any Supabase key for this project** |
| **`bid_decisions`** | **NO** | 0 | **Full read/write for any key with PostgREST access** | Yes | **All bid pursuit decisions (GO/NO-GO, AI confidence, red flags, human override reasoning) readable/writable by anyone holding any key** |
| **`firm_profiles`** | **NO** | 0 | **Full read/write for any key with PostgREST access** | Yes | Lower sensitivity (this firm's own capability profile, not buyer/tenant data) but still unrestricted |

The 13 fail-closed tables are, today, functionally safer than `supabase_schema.sql`'s own header comment claims ("RLS: disable for now") — that comment is stale and should not be trusted as documentation of the live state, exactly as flagged by the audit instructions. Migration 002's comment ("Disable RLS for new tables (consistent with existing schema design)") is what actually reflects the 3 exposed tables' live state; the other 11 originally-disabled tables were re-enabled at some point outside of any migration file in this repo (no corresponding migration exists for re-enabling `bids`, `requirements`, etc. — this was evidently done directly via the Supabase dashboard, and the repo's own migration history does not reflect it).

**Storage (`storage.objects`):** RLS **enabled**, 0 policies (fail-closed) — live-confirmed. Bucket `bid-documents`: `public = false` (live-confirmed), no `file_size_limit`, no `allowed_mime_types` configured at the bucket level.

## 4. Service-Role Key Audit

Repo-wide grep for `create_client`, `SUPABASE_SERVICE_KEY`, `SUPABASE_ANON_KEY`, `SUPABASE_KEY` confirms exactly **one** call site in the entire codebase: `database.py:get_client()`. No other file — including `embeddings.py`, any `pages/*.py`, `analysis_service.py`, `fast_analysis.py`, or any script — constructs its own Supabase client; everything routes through this single function.

| Usage | Classification |
|---|---|
| `database.py:get_client()` — every application read/write (bids, documents, requirements, analysis runs/results, storage upload/download/signed-URL, all of it) | `REQUIRED_SERVER_PRIVILEGE` today, because RLS has no policies to authorize a lesser key — but this is a direct consequence of §3's gap, not an independent architectural need. Once real RLS policies exist (§16), the large majority of this usage becomes `TEMPORARY_ARCHITECTURAL_SHORTCUT`: ordinary reads/writes scoped to a user's own organization should run under a per-user/anon+JWT client instead. |
| `analysis_service.py`'s background thread (`_execute_fast_analysis_run`) writing run status/results | `REQUIRED_SERVER_PRIVILEGE` — this is genuine server-side background work with no browser session attached; it should keep using a privileged credential regardless of the auth model chosen. |
| PDF/report generation and `regenerate_report()` reading persisted snapshots | `REQUIRED_SERVER_PRIVILEGE` for the same reason — server-side batch work. |

**Does it ever reach browser/client code?** No. Confirmed both architecturally (Streamlit is server-rendered; there is no bundled JS reading `.env`/`st.secrets`) and by inspection — the key is read once per `get_client()` call, used directly in server-side Python, and never placed into anything returned to the browser (no `st.write(key)`, no JS interpolation found).

**Classification: `CRITICAL_EXPOSURE`?** None found. The key's blast radius today is "whoever has server-side code execution or `.env`/Streamlit-secrets read access" — which for a single-operator internal tool is the same trust boundary as the operator's own machine/deployment account. This changes materially the moment a second, less-trusted party gets any form of access to the running app or its environment.

## 5. Secret Management

**Method:** ran the repo's own `scripts/audit_secrets.py` (regex-based scan across all 750 git-tracked files for Anthropic keys, Supabase JWTs, GitHub tokens, private-key headers, and hardcoded key-assignment patterns), then independently checked `.env`, `.env.example`, `.gitignore`, `.streamlit/`, and git history for `.env`.

| Item | Classification | Detail |
|---|---|---|
| `scripts/audit_secrets.py` run across all 750 tracked files | **PASS** — 0 secret patterns matched | Confirms no Anthropic key, Supabase JWT, GitHub token, or private-key block is committed anywhere in tracked history as of `HEAD`. |
| `.env` (real `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID`, `ANTHROPIC_CUSTOM_HEADERS`) | `LOCAL_SECRET_NOT_COMMITTED` | Listed in `.gitignore` (`.env` and `.env.*`); confirmed via `git log --all -- .env` — **never** committed, at any point in this repository's history. |
| `.env.example` | `SAFE_REFERENCE` | Contains only placeholder values (`sk-ant-paste-your-key-here`, `your-project-id`, etc.), no real secret material. |
| `.streamlit/secrets.toml` | Not present locally | Listed in `.gitignore` proactively; Streamlit Cloud deployments normally configure this directly in the platform dashboard rather than as a local file — consistent with not finding one here. |
| `scripts/audit_secrets.py`'s own regex patterns | `SAFE_REFERENCE` | The patterns themselves look like secrets to a naive scanner but are just regex literals, not real key material. |
| `tests/fixtures/xls/synthetic_legacy.xls` and other test fixtures | `TEST_VALUE` | No credential material found in any fixture scanned. |
| Generated reports/PDFs (root-level, untracked) | Not scanned by content (binary/PDF), but none reference credentials by design (they are Fast Analysis output, not config dumps). |

**No secret values are reproduced in this report.** Where a real value exists (`.env`), it is referenced only by variable name.

**One adjacent, non-secret finding surfaced by the same audit sweep:** `scripts/audit_secrets.py`'s own "raw procurement file" check (unrelated to secrets, but run in the same pass) shows **385 files under `evaluation/`** are git-tracked, including real Bank of Canada procurement documents (`.docx`/`.xlsx`/`.pdf`) — even though `.gitignore` lists `evaluation/`. This is a classic gitignore gap: these files were committed *before* the ignore rule was added, so the rule doesn't retroactively untrack them (`output/` and `tmp/` are correctly untracked — 0 files each, confirming the rule works going forward). The GitHub remote (`ferasb77/Bid-Intelligence`) is confirmed **private** (`gh repo view` → `isPrivate: true`), which meaningfully bounds this finding's severity; it is a real-document data-hygiene issue worth a deliberate `git rm --cached` cleanup, not a public-exposure incident. Not classified as a secret; noted here because it surfaced in the same sweep the instructions requested.

## 6. Tenancy Model

**Current state: none.** There is no `User → Organization → Bid` relationship, nor any equivalent, anywhere in the schema or code. Every table's only ownership-adjacent column is `bid_id` (a plain foreign key to `bids`, with `on delete cascade`) — `bids` itself has no owner/organization column. `firm_profiles` is a **single global row** (`get_firm_profile()` does `.limit(1)`, with no `bid_id` or org scoping at all) — by design, there is currently exactly one bidding firm's profile, shared across every bid.

**What would be required for isolation** (access isolation only, per the instruction's explicit "not a CRM" scope):

- A new `organizations` table and `organization_members` join table (user ↔ organization, minimally with a role).
- One new nullable-then-required FK: `bids.organization_id`.
- Everything else — `documents`, `requirements`, `tasks`, `outline_sections`, `deliverables`, `content_library` (bid-scoped rows), `clarifications`, `debriefs`, `bid_briefs`, `bid_decisions`, `analysis_runs`, `analysis_results` — already inherits isolation transitively through its existing `bid_id` FK, once RLS policies exist that join back to `bids.organization_id` (§16). No second `organization_id` column is needed on these tables; inheriting via the `bid_id` join is sufficient and avoids duplicating the tenant key everywhere.
- `firm_profiles` needs a decision, not just a column: if multiple firms will one day use this product, it needs an `organization_id` and to stop being a `.limit(1)` singleton; if this remains one operator's internal tool serving multiple *buyer* organizations' bids (not multiple *bidding* firms), it can stay global. This audit does not assume which — it is a product decision, not a security one, and is flagged rather than resolved here.
- `content_library` items with `bid_id IS NULL` (the reusable/global library items — see `get_library_items()`'s `.or_(f"bid_id.eq.{bid_id},bid_id.is.null")`) are, by current design, meant to be visible across all bids. Under a real tenant model this becomes "visible across all bids in the *same organization*," not globally — a real behavior change to get right in the RLS design, not just a mechanical policy add.

## 7. Analysis-Run Ownership

- `created_by` on `analysis_runs` is a nullable free-text column. The only call site that sets it (`pages/stage_understand.py:260`, via `analysis_service.start_fast_analysis(bid_id, api_key, created_by="app-ui")`) hardcodes the literal string `"app-ui"` — it does not reference any real user identity today, because none exists.
- Any caller who knows (or guesses) a `bid_id`/`run_id` can retrieve any run's results — `database.py`'s `get_analysis_run(run_id)`, `get_analysis_result(run_id)`, and `list_analysis_runs(bid_id)` all filter only by the id argument, with no ownership predicate. This is consistent with, not a defect distinct from, the "no tenancy exists" finding in §6.
- Result ownership is **not currently inherited from the bid** in any enforced way — it's inherited only informally, through the `bid_id` foreign key existing in the data, with nothing checking it against a caller's identity.
- Report paths (`upload_analysis_report`) use `{bid_id}/analysis_reports/{run_id}.pdf` — a predictable-but-private path (bucket is non-public; retrieval requires a signed URL or the service-role key — see §8/§9), not protected by any authorization check beyond that.

**Minimum production-safe ownership model:** `created_by` should become a real (nullable-until-auth-exists) FK to `auth.users(id)`, populated from the actual authenticated session rather than a constant. Run/result *access* should be authorized by "does the caller's identity belong to the organization that owns this run's `bid_id`" (inherited via §6/§16), not by a separate per-run ACL — a run does not need independent ownership finer-grained than its bid.

## 8. Document / Storage Security

- **Provider/bucket:** Supabase Storage, bucket `bid-documents`, confirmed live as `public = false` — private by default, correct choice.
- **Public vs. signed URL usage:** `database.py` provides both `download_file()` (server-side download via the service-role client — bypasses any bucket policy by definition) and `get_signed_url(storage_path, expires_in=3600)` (a genuine time-limited signed URL, 1-hour default). Both exist; which one any given UI code path actually uses was not re-derived path-by-path in this audit (out of scope for an audit-only pass) but the *building block* for correct signed-URL-based sharing already exists.
- **Path naming:** `f"{bid_id}/{uuid4().hex}{ext}"` for source documents, `f"{bid_id}/analysis_reports/{run_id}.pdf"` for reports. Neither embeds or trusts the original filename in the storage path — the filename is stored only as `documents.name`, a data field, not a path component. This is a solid, deliberate anti-path-traversal design; no path-traversal risk found.
- **Guessability:** A source-document path is `{bid_id}/{random UUID4 hex}{ext}` — the `bid_id` prefix is trivially guessable (sequential integers) but the UUID4 component is not; an attacker who could enumerate storage objects would need either the exact UUID or the service-role key/RLS bypass regardless. A report path (`{bid_id}/analysis_reports/{run_id}.pdf`) is **fully guessable**: `bid_id` and `run_id` are both small sequential integers with no random component, so anyone who could reach the bucket directly (again, requires the service-role key or a future misconfigured anon policy) could enumerate every report for every bid by simply iterating small integers.
- **Deletion behavior:** `delete_document(doc_id)` deletes only the `documents` table row — it does **not** delete the underlying Storage object. This is an orphaned-file risk (storage cost creep and undeleted data lingering past a user's expectation of deletion), not currently an access-control risk, but worth listing as a real gap.
- **Overwrite behavior:** `save_upload()`'s Storage call passes `upsert: "true"` — a re-upload to the same generated path would overwrite silently, but since each upload generates a fresh UUID-based path, this only matters for the explicit "version update" flow, which deliberately archives the prior version's metadata into `document_versions` first (see database.py:227-247) before overwriting — correct, deliberate behavior, not a defect.
- **MIME/file validation:** None server-side. `st.file_uploader(type=[...])` is a client-side UI filter only; `save_upload()` hardcodes `content-type: application/octet-stream` on every upload regardless of actual file type, and never re-validates the file's real content against its extension. A malformed or mislabeled file would only be caught later, if at all, during extraction (`extractor.py`), not at upload time.
- **Maximum upload handling:** No explicit application-level size cap found (no `max_upload_size` override in `.streamlit/config.toml`; Streamlit's platform default of 200MB/file applies implicitly). No aggregate-corpus size cap.
- **Guessing another user's storage paths:** Not currently meaningful to ask "could User A guess User B's path" because there is no User A/User B distinction yet (§2) — everyone today has the same (server-side, service-role) access to everything. This becomes the live question the moment tenancy is introduced (§6/§16), and the report-path guessability finding above is exactly the kind of thing that must be fixed (signed URLs, not raw sequential paths) before that happens.

## 9. Report Security

- **Where reports live:** Same bucket/convention as source documents — `bid-documents/{bid_id}/analysis_reports/{run_id}.pdf` — see §8.
- **Public paths?** No — the bucket is private; a direct unauthenticated fetch of the object URL fails without a signed URL or privileged key.
- **URL expiry:** `get_signed_url()`'s default is 1 hour (`expires_in=3600`), a sound default where used.
- **Does report access check bid/user authorization?** No — see §7. Today "authorization" is entirely "do you have the service-role key," because nothing else exists yet.
- **Old regenerated reports:** `upload_analysis_report()` uses `upsert: "true"` at a path keyed by `run_id`, so each run's own report is overwritten in place on regeneration (not accumulated) — no stale-old-report accumulation for a single run. Prior *runs'* reports (different `run_id`, e.g. runs 6/7/8 for Calgary) remain independently accessible, which is intentional (preserves holdout history) rather than a defect.
- **Cross-tenant risk assessment:** None currently possible in the narrow sense (no tenants exist), but the underlying mechanism — predictable, non-signed-by-default storage paths, no per-caller authorization check — is exactly the mechanism that would leak reports across organizations the day tenancy is added, unless report retrieval is required to go through `get_signed_url()` plus an authorization check, not a raw path.

## 10. Background Execution Resilience

Current mechanism, confirmed by reading `analysis_service.py` (whose own module docstring already documents this candidly): an **in-process daemon thread**, started per Fast Analysis run (`threading.Thread(..., daemon=True)`), inside the same long-lived Python process Streamlit keeps per app instance.

| Scenario | Effect | Category |
|---|---|---|
| Streamlit process restarts (e.g. code redeploy) while a run is in-flight | The thread dies with the process. The `analysis_runs` row is left stranded in a non-terminal status (QUEUED/PREPARING/ANALYZING/ASSEMBLING) with no thread left to finish it. No data corruption — nothing partial is ever written as COMPLETE (the thread function only ever writes FAILED-with-detail or a fully-formed COMPLETE result). | `DATA SAFETY`: preserved. `JOB RESILIENCE`: absent — the run itself never finishes; a human or the stuck-run safety net must intervene. |
| Deployment restart / instance scale-down | Same as above — identical failure mode, since Streamlit Cloud (the intended target) keeps one process per instance. | Same. |
| Process crash | Same as above. | Same. |
| Multiple app instances | Each instance has its own in-memory thread; there is no shared thread registry across instances. The **DB-level** partial unique index (`idx_analysis_runs_one_active`) is what actually prevents two instances from creating two concurrent runs for the same bid+mode — this is correctly implemented as a database-level guard precisely because in-memory guards can't span instances (see §11). | `JOB RESILIENCE` gap remains (no instance can resume another instance's dead thread), but `DATA SAFETY`/`CONCURRENCY SAFETY` for run creation is sound. |
| Two users start jobs simultaneously (same bid) | Handled correctly — see §11. | N/A |

**UX recovery:** `is_run_stuck()` / `mark_run_failed_as_stuck()` provide a bounded, user-initiated (never automatic) way to un-stick a stranded run after `STUCK_RUN_THRESHOLD_SECONDS`, after which the normal Retry path creates a genuinely new run. This is honestly documented in the code itself as **not equivalent to durable job execution** — it is a UX safety net for a known failure mode, not a fix for the underlying lack of a real queue.

**When does a real worker/queue become necessary?** Not for continued single-user/internal use — the current mechanism is adequate there; a stuck run is rare and self-service-recoverable. It becomes necessary at the point multiple concurrent users across organizations are running expensive, minutes-long analyses regularly enough that (a) stranded runs from ordinary redeploys become a routine support burden rather than a rare event, or (b) horizontal scaling to more than one app instance is needed for load, since only a real queue (not in-process threads) can hand a run's execution to whichever instance is free. This audit does not implement one (§23/instruction 10).

## 11. Concurrency / Duplicate Safety

- **Partial unique index:** `idx_analysis_runs_one_active` on `(bid_id, analysis_mode) where status not in ('COMPLETE','FAILED')` — live-confirmed present in migration 004 and exercised in code (`create_analysis_run` catches the resulting insert failure and returns `None`; `start_fast_analysis` treats that as the authoritative signal, with the pre-check being only a fast/friendly first pass — the DB constraint is correctly documented and used as the real atomic guard, not the pre-check). This is sound, race-safe design for its one job.
- **Multiple browser tabs / multiple users / multiple app instances, all trying to start the same bid's analysis:** Correctly serialized by the above — verified by direct code reading, not just the docstring's claim.
- **Retries:** The `mark_run_failed_as_stuck` → Retry path deliberately creates a **new** run rather than resuming the old one, explicitly to avoid two threads racing to write the same `run_id`'s result (documented and correct).
- **Report generation:** `upload_analysis_report`'s `upsert: "true"` at a `run_id`-keyed path means two concurrent regenerations of the *same* run's report would race harmlessly to overwrite the same content (idempotent, not a correctness risk).
- **Bid updates / document uploads:** No equivalent row-level locking or optimistic-concurrency check exists for ordinary bid/document edits (e.g. two tabs editing the same bid's notes) — Postgres's own last-write-wins semantics apply, same as before Fast Analysis existed. Not a new Phase 8 finding; a pre-existing, low-severity characteristic of the original CRUD design, worth naming since the instructions ask for it explicitly.
- **Race conditions unit tests may not expose:** The one genuine cross-instance race (simultaneous run creation) is covered by a real DB constraint, not just application logic, so it is resilient even to scenarios unit tests can't simulate (true concurrent processes). No other genuine multi-instance race was found in this audit's scope; ordinary CRUD races exist but are pre-existing and low-impact for a single-operator tool.

## 12. Database Mutation Audit

Every mutation in the application flows through exactly one module, `database.py` — confirmed by a repo-wide grep for `.table(...).update(`, `.upsert(`, and `.delete(` outside of it, which returns only two matches, both in test/acceptance helper scripts (`tests/test_database.py`, `tests/acceptance/process_frozen_pipeline.py`), never in `app.py` or `pages/*.py`. This is a real architectural strength worth naming, not just a list of risks.

- **`update_bid()`:** already fixed (visible directly in its own docstring/comment) for the historical defect the instructions reference — it now does an explicit *presence*-based partial update (`{k: data[k] for k in keys if k in data}`), so an omitted key is left untouched and only an explicitly-included key (even `None`) is written, matching the Edit-Bid form's intended clear-to-NULL semantics. No further action needed here; confirmed correct, not merely trusted.
- **`upsert_document()`:** uses the opposite filter — `if data.get(k) is not None` — meaning a caller currently **cannot** clear a document field to NULL through this path (an included key with value `None` is silently dropped, not written). This is an inconsistency with `update_bid()`'s semantics, not a security risk; flagged as a minor data-integrity note for future cleanup, not a Phase 8 remediation item.
- **Broad `.update()` calls / accidental nulling:** Every other `update()` call site in `database.py` builds its payload from an explicit allowlist of keys (`keys = [...]` then a dict comprehension), never a full-object dump. No accidental-nulling pattern found elsewhere.
- **Missing ownership predicates:** Every `delete_*`/`update_*` function in `database.py` scopes by a single row `id` (and `create_analysis_run`/queries by `bid_id`) with **no** ownership or tenant predicate — but this is a direct, consistent consequence of §6 (no tenancy model exists to predicate against) rather than an inconsistency within the mutation layer itself. Once §6/§16 exist, every one of these functions needs either an added `organization_id`/authorization check, or (more simply) to keep using the service-role key exclusively for server-side mutation while all *browser-facing* reads move to a properly-RLS'd, per-user client — see §17.
- **Delete without tenant scope:** `delete_bid`, `delete_document`, `delete_requirement`, `delete_task`, `delete_section`, `delete_deliverable`, `delete_library_item`, `delete_coach`, `delete_clarification` — none check tenant/ownership, consistent with the above; none of them are individually a *new* defect, they are the expected shape of a pre-tenancy CRUD layer.
- **Upsert collisions:** `upsert_requirement`'s three-tier fallback (`keys_with_integrity` → `keys_with_qual` → `keys_basic`, catching schema-mismatch errors between each) is a defensive-but-slightly-fragile pattern — it infers *which* columns exist by parsing exception text for substrings like `"column"`/`"schema"`/`"pgrst"` rather than checking the schema directly. It has not caused an observed defect in this engagement and is out of scope to change during an audit-only phase, but is worth naming as a fragility, not a security risk.
- **`delete_document` does not delete the underlying Storage object** — see §8; an orphaned-data hygiene gap, not an access-control one.

## 13. File Upload Safety

| Aspect | Finding | Classification |
|---|---|---|
| Allowed extensions | Client-side `st.file_uploader(type=[...])` allowlist only (varies by call site: `pdf/docx/xlsx/xls/csv/txt/zip` in one place, `pdf/docx/xlsx/doc` or `.../pptx/txt/png/jpg` in others) | `PRODUCT LIMITATION` (inconsistent allowlists across upload sites) and a mild `SECURITY RISK` (client-side-only filtering is trivially bypassable by anyone who can drive the Streamlit protocol directly rather than through the rendered widget) |
| MIME validation | None server-side; `save_upload()` hardcodes `content-type: application/octet-stream` on every upload | `SECURITY RISK` (low severity today, absent any code path that trusts the stored content-type for execution — Streamlit/PDF/Office parsers all sniff/parse content themselves rather than trusting a header) |
| Filename sanitization | Original filename is never used to build a filesystem/storage path (see §8) — only stored as a data field | Not a risk — deliberately avoided |
| Path traversal | None found — storage path is always `{bid_id}/{uuid4().hex}{ext}`, never derived from user input | Not a risk |
| Duplicate filenames | Handled naturally — each upload gets a fresh UUID-based storage path; `documents.name` can duplicate freely with no collision | `PRODUCT LIMITATION` only (a user could be confused by two documents named identically), not a risk |
| Very large files | No application-level cap; relies entirely on Streamlit's platform default (200MB/file) | `PRODUCT LIMITATION` bordering on `SECURITY RISK` (unbounded-cost/resource-exhaustion surface once multi-user, absent a per-organization quota) |
| Malformed PDFs | Not validated at upload time; failure (if any) surfaces later during extraction, with extraction's own existing error handling — out of this audit's scope to re-verify | `PRODUCT LIMITATION` |
| Excel ingestion | Same — validated at parse time (`extractor.py`/`XLS_INGESTION_REPORT.md` covers this from a prior phase), not upload time | `PRODUCT LIMITATION` |
| Unsupported formats | The `.zip` option in one upload widget (`app.py:236`) is notable — a zip could contain anything, including nested archives or path-traversal-crafted entries if ever extracted server-side. Whether/how this app extracts uploaded zips was not traced in this audit-only pass; flagged for a follow-up look given zip-extraction is a classic path-traversal ("zip slip") vector if handled naively. | Flagged, not yet classified — needs its own follow-up read of the zip-handling code path before a severity can be assigned responsibly. |

## 14. Authentication Options

Given the existing architecture (Streamlit server-rendered app, Supabase already the system of record, Supabase Auth already provisioned-but-unused):

| Option | Simplicity | Streamlit fit | Org membership | Future enterprise SSO | RLS integration |
|---|---|---|---|---|---|
| **A. Supabase Auth** | High — no new infrastructure; it's already provisioned on the exact project this app uses (`auth.users` exists, empty) | Good — Streamlit has mature community patterns (`st.session_state` + Supabase's Python client `auth.sign_in_with_password`/magic-link) for holding a session across reruns | Needs `organization_members` built on top either way (Supabase Auth doesn't ship org membership itself) | Supabase Auth supports SAML/OIDC on paid tiers — a real, if not-immediate, upgrade path | Native — Supabase RLS policies read `auth.uid()` directly; this is the intended pairing |
| B. External IdP (e.g. Auth0/Okta/Entra) issuing a JWT Supabase RLS trusts | Medium-high setup cost (new vendor, new config, JWT-claim wiring into Supabase's custom-JWT support) | Same Streamlit session-handling pattern as A, plus an extra redirect/callback flow to build | Same — still need `organization_members` | Best-in-class if enterprise SSO is a near-term, not speculative, requirement | Supported (Supabase can validate third-party JWTs) but strictly more moving parts than A for the same RLS outcome |
| C. Another architecture (custom session/password table) | Lowest infra dependency, highest *build* cost (password hashing, reset flows, session management — all now this team's problem to secure correctly) | N/A — reinvents what A already provides | Custom, same either way | Weak — no SSO story without significant extra work | Would require hand-rolled RLS policies against a custom identity claim, more fragile than A |

**Recommendation: Option A, Supabase Auth**, specifically because it requires zero new vendor relationship, the identity provider and the data store are already the same project, and it is the natural, lowest-friction on-ramp to `auth.uid()`-based RLS policies (§16) — which is the actual goal, not authentication for its own sake. Enterprise SSO (Option B's strength) can be revisited later as a Supabase Auth *upgrade* rather than a different foundation, if/when a real enterprise customer requires it. This is a recommendation only; not implemented.

## 15. Recommended Minimum Tenancy Model

Smallest production-safe model, derived from the actual existing schema (not a generic template):

```
organizations
    id (pk)
    name

organization_members
    organization_id (fk -> organizations)
    user_id (fk -> auth.users)
    role            -- e.g. 'member' | 'admin'; only as much as access control needs, not an HR system
    primary key (organization_id, user_id)

bids
    ... existing columns, unchanged ...
    organization_id  (fk -> organizations, nullable during migration, not-null once backfilled)
```

Every other table needs **no new tenant column** — `documents`, `requirements`, `tasks`, `outline_sections`, `deliverables`, `content_library` (bid-scoped rows), `clarifications`, `debriefs`, `bid_briefs`, `bid_decisions`, `analysis_runs`, `analysis_results` all already carry `bid_id`, and access is derived by joining back to `bids.organization_id` in the RLS policy itself (§16), not by duplicating `organization_id` onto twelve more tables. `content_library`'s bid-`NULL` global rows need one policy decision (organization-visible vs. truly global — see §6), and `firm_profiles` needs the product decision named in §6 before it gets an `organization_id` or stays global.

This is deliberately **not**: a CRM account model, a sales pipeline, a granular permissions framework, or per-field ACLs. One role distinction (`member`/`admin`) is enough to separate "can this org see/edit its own bids" from "can this org manage its own membership" — nothing finer is justified by anything in this codebase today.

## 16. RLS Remediation Design (conceptual — no SQL executed)

Conceptual policy shape, to be written as real SQL in a future, separately-reviewed migration:

- **`bids`** — direct organization check:
  `USING (organization_id IN (SELECT organization_id FROM organization_members WHERE user_id = auth.uid()))`
- **`documents`, `requirements`, `tasks`, `outline_sections`, `deliverables`, `clarifications`, `debriefs`, `bid_briefs`, `bid_decisions`, `analysis_runs`, `analysis_results`** — inherit via the `bid_id` FK:
  `USING (bid_id IN (SELECT id FROM bids WHERE organization_id IN (SELECT organization_id FROM organization_members WHERE user_id = auth.uid())))`
  (or equivalently, a `bid_id IN (...)` subquery against an RLS-filtered `bids` — Postgres lets a policy reference another RLS-protected table transparently.)
- **`document_versions`** — inherits one hop further, via `document_id → documents.bid_id`.
- **`content_library`** — two cases: bid-scoped rows inherit via `bid_id` as above; `bid_id IS NULL` (global) rows need an explicit decision (§6) — either visible to every authenticated org member (`USING (bid_id IS NULL OR ...)`), or given their own `organization_id` if "global" should really mean "global within my org."
- **`coaches`** — currently has no `bid_id` at all (a firm-wide roster, not bid-scoped) — needs the same product decision as `firm_profiles`: genuinely global, or firm/org-scoped.
- **`firm_profiles`** — per §6/§15, pending a product decision; if it becomes org-scoped, same direct-`organization_id` pattern as `bids`.
- **Server-only tables/paths:** `analysis_runs`/`analysis_results` writes (run creation, status transitions, result persistence) should remain service-role-only regardless of the read policy above — the background thread has no `auth.uid()` to act as, and shouldn't need one; only the *read* side needs a user-facing RLS policy for a future browser-direct read path (if one is ever built) to work safely without the service-role key.
- **`organizations`/`organization_members`** themselves need their own minimal policies (a user can read organizations they belong to; only an `admin` role can modify membership) — not detailed further here since no such tables exist yet to police.

No production SQL is included as an appendix here by design — the instructions permit but do not require it, and writing real policy SQL before the underlying `organizations`/`organization_members` tables and Supabase Auth integration exist would be premature and untestable.

## 17. Admin / Service Separation

| Operation | Should run as |
|---|---|
| Ordinary bid/document/requirement CRUD, reading analysis results, downloading a report | User-level, once §14/§16 exist — should use a per-request client scoped to the authenticated user's JWT, relying on RLS, not the service-role key |
| Starting/executing a Fast Analysis run (the background thread) | Privileged server operation — no browser session is attached to a background thread; continues to need a privileged credential regardless of the auth model chosen (§4) |
| Report PDF assembly / `regenerate_report()` | Privileged server operation — same reasoning |
| Admin maintenance (e.g. marking a stuck run failed, firm-profile edits if kept global) | Should require the `admin` organization role (§15), not blanket service-role access from every browser session |

Today, **all** of the left column runs as service-role, because no alternative client exists (§4). The remediation is not "stop using service-role" wholesale — background/report work genuinely needs it — it's "introduce a second, RLS-respecting client for the operations a browser session should be allowed to do for itself," and stop routing ordinary reads through the privileged path once that exists.

## 18. Audit Logging

**Current state:** No dedicated audit-log table. Two things function as partial, incidental audit trails today:
- `bid_decisions` is effectively append-only in practice (`save_bid_decision` only ever inserts; `get_bid_decision` reads the most recent by `id desc`) — so pursuit-decision history is naturally preserved, even though this wasn't its explicit design intent.
- `document_versions` preserves prior versions on re-upload (§8), giving a real, if narrow, history of document changes.

Neither `bids`, `analysis_runs` status transitions, nor deletions of any kind are logged anywhere beyond Postgres's own `updated_at`/`created_at` timestamps (and several tables, e.g. `requirements`, `tasks`, don't even have `updated_at`).

**Recommended minimum production audit trail** (a single lightweight table, not event sourcing):

```
audit_log
    id, occurred_at, organization_id, user_id, bid_id (nullable),
    event_type,   -- 'bid_created' | 'document_uploaded' | 'document_deleted' |
                  -- 'analysis_started' | 'analysis_completed' | 'analysis_failed' |
                  -- 'report_generated' | 'bid_decision_recorded'
    detail jsonb  -- small, event-specific context (e.g. run_id, document name)
```

One insert per event, from server-side code only (never client-writable), covering exactly the event list the instructions name and nothing more elaborate.

## 19. Observability

**Current visibility:**
- **Failed analysis runs:** Reasonably good — every failure is persisted with `failure_reason` and structured `failure_detail` on the `analysis_runs` row itself (confirmed in `_execute_fast_analysis_run`'s exception handling), visible to whoever queries the table. No push/alerting layer on top of it.
- **LLM errors / token usage / latency:** Captured per-run in `analysis_runs.telemetry` (wall time, call counts, recovery/retry counts, input/output tokens — confirmed in the telemetry-building code read in this and prior phases) — durable and detailed, but again purely pull-based (someone has to query it); nothing surfaces it proactively.
- **Report failures:** Caught the same way as any other in-run exception (part of the same try/except in `_execute_fast_analysis_run`), so a report-assembly failure becomes a FAILED run with detail — not a silent gap, but not distinguished from an extraction failure either.
- **Database errors:** Not centrally logged — individual `database.py` functions mostly let exceptions propagate (a few swallow them deliberately, e.g. `save_firm_profile`'s bare `except: pass`, which is a legitimate "non-fatal, best-effort" choice for that one field but means a real DB outage there would be silently invisible).
- **Worker crashes:** Only detectable indirectly, via `is_run_stuck()`'s elapsed-time heuristic (§10) — there is no direct crash signal, only its downstream symptom.

**Minimum production monitoring requirement:** structured error logging (even just Python's `logging` to stdout, which Streamlit Cloud and most container platforms already capture) for every caught exception that currently gets silently swallowed or only written to a DB row nobody is watching; and one external alert (even a simple periodic query + webhook) on "any `analysis_runs` row stuck past `STUCK_RUN_THRESHOLD_SECONDS`" — turning the existing self-service safety net (§10) into something an operator is proactively told about, not just something a user might notice and click. No dashard is proposed, per instruction 19.

## 20. Deployment Readiness

- **Deployment target assumption:** Streamlit Community Cloud or an equivalent single-long-lived-process host (the architecture explicitly depends on this — see §10's module docstring reasoning). A serverless/per-request execution model (e.g. plain AWS Lambda per request) would break the in-process background thread entirely.
- **Environment configuration:** `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ANTHROPIC_API_KEY` (+ optional workspace/header vars), optional `VOYAGE_API_KEY` — via Streamlit secrets in production, `.env` locally. No secrets manager integration (e.g. AWS Secrets Manager, Vault) — acceptable for the current scale, worth revisiting only if compliance requirements demand it later.
- **Startup behavior:** `database.py:init_db()` is a documented no-op — schema is applied manually via the Supabase SQL editor, not on app boot. No automatic migration-on-start.
- **Migration strategy:** Fully manual, by explicit convention stated in every migration file's own header ("NOT auto-applied by any code path... apply manually... after separate review"). This is a deliberate, conservative choice, consistent throughout this entire engagement's own discipline — and it is also why the live RLS state has quietly drifted from what the repo's SQL files describe (§3): manual dashboard changes aren't required to leave a matching file behind, and at least one (re-enabling RLS on 11 tables) didn't.
- **Health checks:** None found — no `/healthz`-equivalent endpoint or Streamlit-level health signal beyond the platform's own process-liveness check.
- **Persistence assumptions:** Correctly stateless at the process level — all durable state lives in Supabase (DB + Storage), not on local disk, except the documented local-file fallback in `save_upload()` if Storage upload fails (a fallback that would silently create ephemeral, non-durable, non-multi-instance-visible files on whatever container happens to handle that one request — worth noting as a real gap for multi-instance deployments, though it only triggers if Storage itself is down).
- **Process restart behavior:** Covered in depth in §10.

**Blockers for `production single-tenant/internal`:** None that are blocking — this describes the current, working deployment shape reasonably well. The only genuinely open item even for continued internal-only use is the 3 RLS-disabled tables (§3), which cost nothing to fix and should be closed regardless of any multi-tenant timeline, plus the local-fallback-on-storage-failure gap above if this ever runs on more than one instance.

**Blockers for `production multi-tenant/external`:** Authentication (§2/§14), tenancy (§6/§15), real RLS policies (§16), service-role minimization for user-facing paths (§17), signed-URL-only report/document access (§8/§9), and a durable job mechanism if concurrent multi-org load is expected (§10) are all required before this is safe to open to mutually-untrusted external users.

## 21. Prioritized Risk Register

| # | Finding | Risk | Classification |
|---|---|---|---|
| 1 | `bid_briefs`, `bid_decisions`, `firm_profiles` have RLS disabled with zero policies | If any anon/publishable Supabase key is ever introduced to a client-facing surface (a near-certain step of any Supabase-Auth migration if done carelessly), any holder of that key gets full unauthenticated read/write on all buyers' AI-generated intelligence summaries and pursuit decisions | **CRITICAL** (conditional — not exploitable today because no non-service-role key is ever used, but this is precisely the landmine a future auth migration would step on if §3 isn't fixed first) |
| 2 | No authentication, no tenancy, no per-user/org authorization anywhere | The application cannot safely serve more than one mutually-untrusted party today; anyone with server/environment access sees everything | **HIGH** (blocking for any multi-tenant plan; not itself an active incident for the current single-operator deployment) |
| 3 | Report/document storage paths are predictable, unsigned by default, and access-unchecked beyond the service-role boundary | Once tenancy exists, this exact mechanism becomes a direct cross-tenant report/document leak if retrieval isn't required to go through `get_signed_url()` + an authorization check | **HIGH** (same conditional nature as #1 — a landmine for the *next* change, not an active exposure today) |
| 4 | Shared, server-configured Anthropic API key used for every visitor's LLM calls with no per-user attribution or quota | Once multi-user, any authenticated (or, until then, any) user can drive unbounded LLM spend against one shared credential | **HIGH** (cost/abuse risk, not a data-confidentiality one) |
| 5 | No durable job queue — background analysis threads die with the process | Runs stranded on redeploy/crash/scale-down; self-service-recoverable today, becomes an operational burden at real multi-user concurrency | **MEDIUM** |
| 6 | `delete_document()` never removes the underlying Storage object | Storage cost creep; data a user believes deleted persists in the bucket | **MEDIUM** |
| 7 | No server-side MIME/file-size validation on uploads; inconsistent client-side extension allowlists across upload widgets | Low exploitability today (no code path trusts the stored content-type for execution) but unbounded-size uploads are a real resource-exhaustion surface once multi-user | **MEDIUM** |
| 8 | 385 real procurement files under `evaluation/` are git-tracked despite `.gitignore` now listing that path | Real (if currently private-repo-bounded) buyer document material sitting in version-control history rather than being treated as regenerable evidence | **MEDIUM** |
| 9 | `.zip` accepted as an upload type in one widget; zip-extraction handling not traced in this audit | Unclassified pending a dedicated follow-up read — zip handling is a classic path-traversal vector if naive | **MEDIUM** (provisional, pending follow-up) |
| 10 | Live RLS/table state has silently drifted from what migration files and `supabase_schema.sql` document | Anyone relying on the repo's own SQL files as documentation (as this very audit was initially asked to do) would materially misjudge the live security posture in both directions (worse on 3 tables' documentation, better on 11) | **LOW** (a documentation-integrity risk, not a direct access-control one — but it is exactly what caused the instructions to explicitly demand live re-verification rather than trusting old notes) |
| 11 | No dedicated audit-log table; only incidental partial history via `bid_decisions` inserts and `document_versions` | Limited forensic ability if something does go wrong later | **LOW** |
| 12 | No centralized error logging/alerting; several exceptions silently swallowed (e.g. `save_firm_profile`) | Operational blind spots, not a security exposure | **LOW** |
| 13 | `upsert_document()`'s None-filtering is inconsistent with `update_bid()`'s explicit-None-clears semantics | Minor data-integrity/product inconsistency | **LOW** |

Nothing in this register was inflated to CRITICAL without a concrete mechanism by which it becomes exploitable; #1 and #3 are marked CRITICAL/HIGH specifically because they are landmines for the *next* natural step (adding auth), not because anything is exploitable in the product as it runs today.

## 22. Remediation Roadmap

| Order | Package | Depends on | Risk addressed | Complexity | DB migration required? | Live Supabase policy/config change required? |
|---|---|---|---|---|---|---|
| 1 | **Close the 3 open RLS tables** (`bid_briefs`, `bid_decisions`, `firm_profiles`) — enable RLS; since no non-service-role client exists yet, this is a zero-behavior-change safety close, not a feature | None | Risk #1 | Trivial | No (RLS enable is a live policy change, not a schema migration) | **Yes** — this alone is worth doing immediately, independent of everything else below |
| 2 | **Identity/auth** — adopt Supabase Auth (§14) | Package 1 conceptually unrelated but should land first regardless | Risk #2 | Medium (mostly Streamlit session-handling plumbing; the identity provider itself is already provisioned) | No new table needed for auth itself (`auth.users` exists) | Auth provider configuration (email/password or magic-link setup) in the Supabase dashboard |
| 3 | **Organization tenancy** (§15) — `organizations`, `organization_members`, `bids.organization_id` | Package 2 (needs `auth.uid()` to reference) | Risk #2 | Medium | **Yes** — new tables + one new column | No |
| 4 | **RLS policy authoring** (§16) across all tenant-scoped tables | Package 3 | Risks #2, #3 (the report/document leak vector closes once reads are authorization-checked) | Medium-high (careful, table-by-table policy review; this is where a mistake would be most consequential) | No (policies, not schema) | **Yes** |
| 5 | **Storage/report authorization** — require `get_signed_url()` + an authorization check for all report/document retrieval; stop relying on path obscurity | Package 4 | Risk #3 | Low-medium | No | Possibly (storage bucket policies, if moving beyond service-role-only retrieval) |
| 6 | **Service-role minimization** — introduce a per-user RLS-respecting client for browser-facing reads/writes; keep service-role for genuinely server-only work (§17) | Package 4 | Risk #2 (defense in depth) | Medium (touches most of `database.py`'s call sites) | No | No |
| 7 | **Per-user LLM key/quota** instead of one shared server-configured Anthropic key for every visitor | Package 2 (needs identity to attribute usage to) | Risk #4 | Low-medium | Maybe (a usage/quota table) | No |
| 8 | **Durable job execution** (real queue) | Genuinely independent of 1-7 — can happen anytime, but only becomes *necessary* once real multi-org concurrent load exists | Risk #5 | High (new infra dependency) | Possibly | No |
| 9 | **Storage cleanup on delete, upload validation hardening, audit log, observability/alerting** | Mostly independent, can be done incrementally alongside any of the above | Risks #6, #7, #9, #11, #12 | Low-medium each | Small (audit_log table) for one of them | No |
| — | **`evaluation/` git-history cleanup** (Risk #8) | Independent, purely a repo-hygiene task | Risk #8 | Low (a `git rm --cached` + communicate to any collaborators, or a history rewrite if the team decides that's warranted) | N/A | N/A |

Packages 1-7 map directly onto the instructions' own suggested sequence (identity → tenancy → RLS → storage/report auth → service-role minimization → durable jobs → observability), confirmed rather than assumed correct by this audit — the one addition is package 1 (close the 3 open tables) placed *before* identity/auth, since it is free, has zero dependencies, and directly defuses the biggest landmine (#1) before any auth work could accidentally trigger it.

---

*This report is an audit only. No remediation from §22 has been implemented. No code, schema, migration, Supabase policy, auth setting, environment variable, storage bucket, or deployment configuration was changed in the course of producing it.*
