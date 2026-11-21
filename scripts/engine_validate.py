"""Validation scoring for engine runs against human-written source-truth checklists.

    python scripts/engine_validate.py CHECKLIST.json RUN_LABEL [--existing FILE ...]

Evaluation only: production code never imports this script or any checklist
(tests/test_engine_constraints.py). Client checklists live in the git-ignored
.engine_runs/validation/ folder.

Checklist format:
{"case": "...", "items": [{"id": "C-01", "kind": "ELIGIBILITY|OMISSION|INTERPRETATION|CONTRADICTION",
  "source": "doc p.N clause", "expect": "what a correct report states",
  "all": ["regex", ...],            # all must match one report item (case-insensitive)
  "fast": true,                     # must appear in FAST (else FULL suffices)
  "forbid": ["regex", ...]}]}       # a report item matching these is a misinterpretation

For CONTRADICTION items the `all` patterns must match the conflicts /
open-issues content (an unflagged contradiction does not count).
Existing-engine reports (plain text) are scored on three-line windows; the comparison is reported with evidence lines.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _items(rep: dict) -> list[str]:
    out = []
    for k, v in rep.get("identity") or []:
        out.append(f"{k}: {v}")
    out += list(rep.get("summary") or [])
    for sec in rep.get("sections") or []:
        for g in sec.get("groups") or [{"title": "", "items": sec.get("items") or []}]:
            for it in g.get("items") or []:
                prev = " ".join(p.get("statement", "") for p in it.get("previous") or [])
                out.append(f"[{sec['title']}] {it['text']} {' '.join(it.get('labels') or [])} {prev}")
        for p in sec.get("analysis") or []:
            out.append(f"[analysis] {p['heading']}: {p['analysis']}")
    return out


def _open_issue_texts(res: dict) -> list[str]:
    by = {e["entry_id"]: e for e in res["register"]["entries"]}
    out = []
    for c in res.get("conflicts", {}).get("conflicts") or []:
        out.append(" ".join([c.get("issue") or "", c.get("clarification_question") or ""] +
                            [by[i]["statement"] for i in c.get("entry_ids") or [] if i in by]))
    return out


def _match(texts: list[str], pats: list[str]) -> str | None:
    for t in texts:
        if all(re.search(p, t, re.I | re.S) for p in pats):
            return t
    return None


def score(checklist: dict, res: dict | None, existing: list[str]) -> dict:
    fast = _items(res["composed"]["fast"]) if res else []
    full = _items(res["composed"]["full"]) if res else []
    issues = _open_issue_texts(res) if res else []
    # existing reports are plain text: scored on windows of three consecutive lines
    ex_lines = [ln.strip() for t in existing for ln in t.splitlines() if ln.strip()]
    ex_units = [" ".join(ex_lines[i:i + 3]) for i in range(len(ex_lines))]
    rows = []
    for it in checklist["items"]:
        pats, forbid = it.get("all") or [], it.get("forbid") or []
        if it["kind"] == "CONTRADICTION":
            hit_eng = _match(issues, pats)
            hit_fast = hit_eng if hit_eng and _match([x for x in fast if "conflict" in x.lower()], pats[:1]) else None
        else:
            hit_fast = _match(fast, pats)
            hit_eng = hit_fast or _match(full, pats)
        wrong = [t for t in fast + full if forbid and any(re.search(p, t, re.I) for p in forbid)]
        ex_pats = pats + ([r"conflict|inconsisten|discrepan|differ|contradict"] if it["kind"] == "CONTRADICTION" else [])
        ex_hit = bool(_match(ex_units, ex_pats))
        ex_wrong = [t for t in ex_units if forbid and any(re.search(p, t, re.I) for p in forbid)]
        ok = bool(hit_eng) and (bool(hit_fast) or not it.get("fast")) and not wrong
        rows.append({"id": it["id"], "kind": it["kind"], "source": it.get("source"), "expect": it.get("expect"),
                     "engine": "PASS" if ok else ("WRONG" if wrong else ("FULL_ONLY" if hit_eng else "MISSING")),
                     "engine_fast": bool(hit_fast), "engine_evidence": (hit_fast or hit_eng or "")[:300],
                     "engine_wrong": [w[:200] for w in wrong][:2],
                     "existing": ("WRONG" if ex_wrong else "PRESENT" if ex_hit else "ABSENT") if existing else "N/A",
                     "existing_evidence": ((ex_wrong[0] if ex_wrong else _match(ex_units, ex_pats)) or "")[:300]})
    n = len(rows)
    return {"case": checklist.get("case"), "items": n,
            "engine_pass": sum(r["engine"] == "PASS" for r in rows),
            "existing_present": sum(r["existing"] == "PRESENT" for r in rows) if existing else None,
            "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("checklist")
    ap.add_argument("run_label")
    ap.add_argument("--existing", nargs="*", default=[])
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    cl = json.load(open(a.checklist, encoding="utf-8"))
    path = os.path.join(ROOT, ".engine_runs", a.run_label, "result.json")
    res = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
    if res and res.get("record", {}).get("status") != "COMPLETE":
        print(f"run {a.run_label} is {res['record'].get('status')}: not scored")
        return 1
    existing = [open(f, encoding="utf-8", errors="replace").read() for f in a.existing]
    out = score(cl, res, existing)
    for r in out["rows"]:
        print(f"{r['id']:6} {r['kind'][:13]:13} engine={r['engine']:9} existing={r['existing']:7} {r['expect'][:70]}")
    print(f"engine {out['engine_pass']}/{out['items']}" +
          (f" | existing {out['existing_present']}/{out['items']}" if existing else ""))
    with open(a.out or os.path.join(ROOT, ".engine_runs", a.run_label, "validation.json"), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
