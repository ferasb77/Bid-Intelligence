"""Re-compose and re-render FAST/FULL PDFs of a saved engine run with the
current composition/rendering code. Deterministic: no model calls; the
register, conflicts, analysis and verification status are taken from the run.

    python scripts/engine_rerender.py RUN_LABEL [RUN_LABEL ...]
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    from engine import reports
    from engine.render import render
    for label in sys.argv[1:]:
        d = os.path.join(ROOT, ".engine_runs", label)
        r = json.load(open(os.path.join(d, "result.json"), encoding="utf-8"))
        rec = r["record"]
        if rec.get("status") != "COMPLETE":
            print(label, "not COMPLETE; skipped")
            continue
        comp = reports.compose(r["register"]["entries"], an=r["analysis"], conflicts=r["conflicts"],
                               readability=r["package"]["readability"],
                               run_meta={"verification": rec.get("verification")}, research=None)
        if not comp["ledger"]["complete"]:
            print(label, "ledger violations after recomposition:", comp["ledger"]["violations"])
            continue
        old = r["composed"]["fast"].get("verification")
        for k in ("fast", "full"):
            comp[k]["verification"] = old
            with open(os.path.join(d, f"{k}.pdf"), "wb") as fh:
                fh.write(render(comp[k]))
        r["composed"] = comp
        with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as fh:
            json.dump(r, fh, indent=1, default=str)
        print(label, "re-rendered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
