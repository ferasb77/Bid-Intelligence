# Legacy XLS Ingestion Report

## Scope and base

- Repository: `ferasb77/Bid-Intelligence`
- Branch: `fix/legacy-xls-ingestion`
- Verified base: `18649f9401caff34c178c3dbad0e65ce51eb49de`
- Production commits:
  - `516008d1fe3a06a3740091ed8d0f6c3df6a877b3` — native XLS ingestion
  - `7595ef2c23a6825f03e91529abb72f91e825bc50` — time-only value integrity
- Scope: ingestion-only native Excel 97–2003 BIFF support

## Parser and dependency

`xlrd>=2.0.2,<3` is the only production dependency added. Legacy `.xls`
workbooks use `xlrd`; existing `.xlsx` workbooks continue to use `openpyxl`.
No pandas, Calamine, LibreOffice, external conversion service, or `.doc`
support was added.

The parser opens workbook bytes with `formatting_info=True`, `on_demand=True`,
and `ragged_rows=True`, then releases workbook resources in `finally`.

## Files changed

- `extractor.py`: native XLS extraction, deterministic value rendering,
  metadata, routing, failure diagnostics, and package admission.
- `app.py`: primary procurement uploader accepts and advertises `.xls`.
- `requirements.txt`: bounded `xlrd` dependency.
- `tests/test_xls_ingestion.py`: focused ingestion and provenance tests.
- `tests/integration/test_procurement_package_ingestion.py`: package contract
  updated from XLS rejection to XLS admission with diagnostics.
- `tests/test_streamlined_workflow.py`: format-support contract updated.
- `tests/fixtures/xls/synthetic_legacy.xls`: non-proprietary BIFF8 fixture.
- `tests/fixtures/xls/MANIFEST.md`: fixture definition and hash.
- `tests/fixtures/xls/generate_synthetic_xls.py`: optional developer-only
  generator; `xlwt` is not needed by tests or production.

## Parser contract

`extract_xls_with_metadata(file_bytes, filename)` returns marked text plus
metadata containing:

- `type: xls`
- `parse_status`
- detected BIFF label
- workbook-order sheet names
- XLSX-compatible `rows_per_sheet` tuples
- sheet visibility
- A1 merged ranges
- `formula_policy: CACHED_VALUES`
- safe warnings

Supported statuses are `PARSED`, `EMPTY_WORKBOOK`,
`UNSUPPORTED_XLS_VARIANT`, `ENCRYPTED`, `CORRUPT`, `PARSER_ERROR`, and
`LIMIT_EXCEEDED`. Encryption is selected only when the parser error explicitly
identifies encryption or password protection.

Output retains the established Stage A marker shape:

```text
[[SOURCE: filename.xls | SHEET: SheetName | ROWS: min-max]]
Row N: ...
```

## Value normalization

- Text preserves Unicode and trims surrounding whitespace.
- Blank cells are omitted.
- Boolean values render as `True` or `False`.
- Known Excel errors render as stable tokens such as `#DIV/0!`.
- Integer-valued numerics omit `.0`; decimals avoid binary-float noise.
- Ordinary percentage formats render human-visible values (`0.25` with `0%`
  becomes `25%`). Complex formats fall back to deterministic raw numerics.
- Date-only cells use workbook datemode and render as ISO dates.
- Time-only cells render as `HH:MM:SS` without an Excel epoch date.
- Combined date/time cells render as local ISO datetimes.
- Elapsed formats such as `[h]:mm` fall back to deterministic raw numeric text
  rather than being represented as calendar values.
- No timezone or currency is inferred.

## Formula and security policy

Only stored formula results exposed by `xlrd` are treated as data. The code
does not calculate formulas, execute VBA/macros or DDE, open links, invoke
Excel or subprocesses, make network calls, or refresh external data. Cached
zero, false, numeric, text, and error values are retained when the workbook
provides them. Formula expressions without useful cached values are omitted.

Malformed or unsupported XLS content produces inert marked text and structured
metadata. Package preflight sends the safe filename-specific diagnostic through
the existing warning channel while retaining the failed file marker; other
package files continue.

## Package and uploader routing

- Direct `.xls`: accepted.
- `.xls` ZIP member: accepted after existing path and hidden-file checks.
- `.doc`: remains unsupported.
- `.xlsb`, `.xlsm`, and `.ods`: remain unsupported.
- `.xlsx`: still routes exclusively to `extract_xlsx_with_metadata()` and
  `openpyxl`.

## Synthetic fixture

- File: `tests/fixtures/xls/synthetic_legacy.xls`
- SHA-256: `55672271c1a62b7c69bd9844426dc088f797416cc2e7135c9c3cdec75c1fa6e1`
- Format: BIFF8
- Sheets: visible, hidden, very-hidden, and empty sheets in workbook order
- Coverage: merged heading, physical blank-row gap, Unicode, integer, decimal,
  boolean false, numeric zero, percentages, leap-day date, datetime, `h:mm`
  and `h:mm:ss` time-only values, `[h]:mm` elapsed duration, and a formula
  without a cached result
- Additional deterministic cases: known Excel error mapping, fake XLS bytes,
  truncated OLE bytes, direct upload, ZIP admission, and package continuation

Normal tests do not require `xlwt`.

## Provenance validation

The synthetic fixture passes both existing provenance paths using an `.xls`
source marker:

- `validate_source_refs()`: verified
- canonical source verification: `VERIFIED`

No extension-specific downstream workaround was introduced. Sheet names,
physical row numbers, marked text, `package_metadata.doc_metadata`, Stage A
source references, canonical verification, and Stage D evidence remain on the
existing generic workbook contract.

## Deterministic tests

Focused command:

```text
python -m pytest tests/test_xls_ingestion.py tests/integration/test_procurement_package_ingestion.py tests/test_stage_a_extraction_reliability.py tests/test_canonical_opportunity.py tests/test_streamlined_workflow.py -q
```

Result: **105 passed, 0 failed**.

Full repository command:

```text
python -m pytest -q
```

Result: **576 passed, 1 skipped, 19 subtests passed, 0 failures**. The run
reported 118 existing Supabase deprecation warnings. These are local results;
no GitHub CI result is claimed.

### Final time-only correction validation

Focused command:

```text
python -m pytest tests/test_xls_ingestion.py tests/integration/test_procurement_package_ingestion.py tests/test_streamlined_workflow.py -q
```

Result: **47 passed, 0 failed**.

The corrected fixture proves:

- date-only: `2028-02-29`
- datetime: `2028-02-29T13:45:30`
- `h:mm`: `13:45:00`
- `h:mm:ss`: `13:45:30`
- Excel 1900 and 1904 date modes do not introduce phantom epoch dates for
  time-only values
- no timezone is added
- `[h]:mm` elapsed value `1.5` remains `1.5`, without a calendar date

Final full-suite result: **580 passed, 1 skipped, 19 subtests passed, 0
failures** with 118 existing Supabase deprecation warnings.

## British Council XLS preprocessing

Known local fixture:
`annex_2a_procurement_specific_questionnaire_ratio_analysis_1.xls`

- Size: 49,152 bytes
- SHA-256: `fa0a7cb3f96dba015f0d442b0b12190d55691a7836663ee6bc16ed89a6656ead`
- Parse status: `PARSED`
- Format: BIFF8 / OLE Compound
- Sheets: one visible sheet, `Ratio Analysis`
- Physical dimensions: 44 rows × 6 columns
- Populated physical rows: 22, all retained with original row numbers
- Merged ranges: five
- Marked extraction: 1,121 characters, one Stage A chunk
- Formula policy: cached values
- Parser warnings: none
- Legacy source validation: verified
- Canonical source validation: `VERIFIED`

The proprietary workbook remains local, unchanged, and untracked.

## One-workbook Stage A contract smoke

The optional smoke used only the British Council `.xls` workbook and the
unchanged `claude-haiku-4-5-20251001` model.

- JSON result: parsed successfully
- Extraction diagnostic: `VERIFIED_ADEQUATE`
- Recovery attempts: 0
- Requirements: 13
- Evaluation criteria: 3
- Submission rules: 1
- Typed observations: 2
- Source references: 19
- Verified source references: 19/19
- References retaining `Ratio Analysis`: 19/19

These counts are contract evidence, not hard-coded semantic expectations. The
full British Council package was not run.

## Known limitations and adjacent debt

- Cached formula values may be stale because the application does not
  recalculate workbooks.
- Complex custom Excel visual formats fall back to raw deterministic values.
- Encrypted workbooks are not decrypted; users must provide an unlocked or
  exported copy.
- Duplicate ZIP basenames can still create filename-based provenance ambiguity.
  This predates XLS support and remains a separate package-ingestion track.
- ZIP expansion and compression-ratio limits remain a separate security track.
- No arbitrary procurement-specific byte or character limit was introduced.

**NO MIGRATION 004**

**FULL BRITISH COUNCIL ACCEPTANCE NOT CLAIMED**

**XLSX EXTRACTION BEHAVIOR NOT REDESIGNED**
