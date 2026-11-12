"""Deterministic spreadsheet intelligence for procurement packages.

For every workbook in a bid package: inspect sheets, header rows and formulas,
identify the workbook's purpose (pricing, compliance, schedule, evaluation,
staffing) from cell evidence, and link it to the RFP/addendum text that
references it. Never fills a template and never invents a value: a purpose or
link that cannot be shown from cell/sentence evidence is reported as
"unconfirmed".
"""
from __future__ import annotations

import csv
import io
import re

import procurement_digest as pdg

WORKBOOK_EXT = (".xlsx", ".xlsm", ".xls", ".csv")

PURPOSES = {
    "Pricing / financial schedule": [
        "price", "pricing", "rate", "unit cost", "cost", "amount", "total", "fee", "quotation",
        "boq", "bill of quantities", "currency", "vat", "tax", "lump sum", "hourly"],
    "Compliance / requirements response": [
        "compliance", "comply", "compliant", "requirement", "response", "yes/no", "mandatory",
        "conformity", "clause", "bidder response", "comments"],
    "Schedule / work plan": [
        "schedule", "timeline", "milestone", "week", "month", "start date", "end date",
        "gantt", "duration", "activity", "phase"],
    "Evaluation / scoring": ["score", "scoring", "weight", "evaluation", "points", "criteria"],
    "Staffing / personnel": ["cv", "personnel", "staff", "key expert", "role", "position", "team member"],
}


def is_workbook(name: str) -> bool:
    return (name or "").lower().endswith(WORKBOOK_EXT)


def _col(c: int) -> str:
    s = ""
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def _profile_grid(grid_by_sheet: dict[str, list[list]], formulas_by_sheet: dict[str, list] | None) -> list[dict]:
    sheets = []
    for name, rows in grid_by_sheet.items():
        header_row, headers = None, []
        for r_idx, row in enumerate(rows[:20], 1):
            texts = [(c_idx, str(v).strip()) for c_idx, v in enumerate(row, 1)
                     if isinstance(v, str) and str(v).strip()]
            if len(texts) >= 2:
                header_row = r_idx
                headers = [{"cell": f"{_col(c)}{r_idx}", "text": t[:60]} for c, t in texts[:12]]
                break
        labels = []
        for r_idx, row in enumerate(rows[:200], 1):
            for c_idx, v in enumerate(row, 1):
                if isinstance(v, str) and v.strip():
                    labels.append({"cell": f"{_col(c_idx)}{r_idx}", "text": v.strip()[:80]})
        f = (formulas_by_sheet or {}).get(name)
        sheets.append({
            "name": name,
            "rows": len(rows),
            "header_row": header_row,
            "headers": headers,
            "labels": labels,
            "formula_count": None if f is None else len(f),
            "formula_samples": [] if not f else f[:4],
        })
    return sheets


def _classify(sheets: list[dict]) -> tuple[str | None, list[dict]]:
    scores: dict[str, list[dict]] = {}
    for sh in sheets:
        cand = [{"cell": None, "text": sh["name"], "sheet": sh["name"]}] + \
               [dict(l, sheet=sh["name"]) for l in sh["labels"]]
        for lab in cand:
            low = lab["text"].lower()
            for purpose, kws in PURPOSES.items():
                hit = next((k for k in kws if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", low)), None)
                if hit:
                    scores.setdefault(purpose, []).append(dict(lab, keyword=hit))
    ranked = sorted(scores.items(), key=lambda kv: len({e["keyword"] for e in kv[1]}), reverse=True)
    if not ranked or len({e["keyword"] for e in ranked[0][1]}) < 2:
        return None, (ranked[0][1][:3] if ranked else [])
    # a clear winner needs more distinct evidence than the runner-up
    if len(ranked) > 1 and len({e["keyword"] for e in ranked[1][1]}) == len({e["keyword"] for e in ranked[0][1]}):
        return None, ranked[0][1][:3] + ranked[1][1][:2]
    return ranked[0][0], ranked[0][1][:4]


def profile_workbook(name: str, data: bytes) -> dict:
    """{"name", "sheets", "purpose", "purpose_status", "evidence", "error"}"""
    low = (name or "").lower()
    grid, formulas, error = {}, None, None
    try:
        if low.endswith((".xlsx", ".xlsm")):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=False, read_only=False)
            formulas = {}
            for ws in wb.worksheets:
                rows, fl = [], []
                for r_idx, row in enumerate(ws.iter_rows(max_row=min(ws.max_row or 0, 2000)), 1):
                    vals = []
                    for c_idx, cell in enumerate(row, 1):
                        v = cell.value
                        if isinstance(v, str) and v.startswith("="):
                            fl.append({"cell": f"{_col(c_idx)}{r_idx}", "formula": v[:80]})
                            vals.append(None)
                        else:
                            vals.append(v)
                    rows.append(vals)
                grid[ws.title] = rows
                formulas[ws.title] = fl
        elif low.endswith(".csv"):
            text = data.decode("utf-8-sig", errors="ignore")
            grid["CSV"] = [list(r) for r in csv.reader(io.StringIO(text))][:2000]
        elif low.endswith(".xls"):
            import xlrd
            book = xlrd.open_workbook(file_contents=data)
            for sh in book.sheets():
                grid[sh.name] = [sh.row_values(r) for r in range(min(sh.nrows, 2000))]
    except Exception as exc:  # unreadable workbook: report, never guess
        error = f"{type(exc).__name__}"
    sheets = _profile_grid(grid, formulas)
    purpose, evidence = _classify(sheets) if sheets else (None, [])
    return {
        "name": name,
        "sheets": [{k: v for k, v in s.items() if k != "labels"} for s in sheets],
        "purpose": purpose,
        "purpose_status": "identified" if purpose else "unconfirmed",
        "evidence": evidence,
        "error": error,
    }


def _stem_tokens(name: str) -> list[str]:
    stem = re.sub(r"\.[a-z0-9]+$", "", (name or "").lower())
    return [t for t in re.split(r"[^a-z0-9]+", stem) if len(t) > 2 and not t.isdigit()]


_SHEET_WORDS = re.compile(r"\b(excel|spreadsheet|workbook|xlsx|xls|template|schedule|form|annex|appendix|attachment)\b", re.I)


def find_references(workbook: dict, documents: list[tuple[str, str]]) -> list[dict]:
    """Sentences in the OTHER package documents that reference this workbook.
    status "linked" when the sentence names the file (or its distinctive
    words); "unconfirmed" when only a generic spreadsheet/template mention of
    the same purpose exists."""
    name = workbook["name"]
    others = [(n, t) for n, t in documents or [] if n != name]
    toks = _stem_tokens(name)
    out = []
    purpose_kws = PURPOSES.get(workbook.get("purpose") or "", [])
    for s in pdg.located_sentences(others):
        low = s["text"].lower()
        if name.lower() in low or (len(toks) >= 2 and sum(t in low for t in toks) >= max(2, int(len(toks) * 0.7))):
            out.append(dict(s, status="linked"))
        elif _SHEET_WORDS.search(low) and re.search(r"\b(excel|spreadsheet|workbook|xlsx?)\b", low) and \
                any(k in low for k in purpose_kws):
            out.append(dict(s, status="unconfirmed"))
    out.sort(key=lambda r: r["status"] != "linked")
    return out[:3]


def analyse_package(files: list[tuple[str, bytes]], documents: list[tuple[str, str]]) -> list[dict]:
    """Profile every workbook in `files` and attach its references."""
    res = []
    for name, data in files or []:
        if not is_workbook(name):
            continue
        wb = profile_workbook(name, data)
        wb["references"] = find_references(wb, documents)
        res.append(wb)
    return res
