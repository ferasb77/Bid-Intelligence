# Synthetic legacy XLS fixture

`synthetic_legacy.xls` is a generated, non-proprietary BIFF8 workbook used to
test legacy spreadsheet ingestion. Normal tests read the committed binary and
do not require `xlwt`.

- Generator: `generate_synthetic_xls.py` (developer-only; requires `xlwt`)
- Sheets, in order: `Main Data`, `Hidden Guidance`, `Very Hidden`, `Empty Sheet`
- Coverage: merged heading, blank-row gap, Unicode, integer, decimal, boolean
  false, numeric zero, ordinary percentages, leap-day date, datetime,
  time-only values, elapsed duration, formula without a cached result,
  hidden/very-hidden sheets, and an empty sheet.
- SHA-256: `55672271c1a62b7c69bd9844426dc088f797416cc2e7135c9c3cdec75c1fa6e1`
