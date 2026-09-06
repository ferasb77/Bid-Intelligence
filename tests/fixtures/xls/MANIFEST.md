# Synthetic legacy XLS fixture

`synthetic_legacy.xls` is a generated, non-proprietary BIFF8 workbook used to
test legacy spreadsheet ingestion. Normal tests read the committed binary and
do not require `xlwt`.

- Generator: `generate_synthetic_xls.py` (developer-only; requires `xlwt`)
- Sheets, in order: `Main Data`, `Hidden Guidance`, `Very Hidden`, `Empty Sheet`
- Coverage: merged heading, blank-row gap, Unicode, integer, decimal, boolean
  false, numeric zero, ordinary percentages, leap-day date, datetime, formula
  without a cached result, hidden/very-hidden sheets, and an empty sheet.
- SHA-256: `c0b4f6b74241ceab73377135cd6f70e5c75d503e7ae26f5ca06b8e08e6e46ccd`
