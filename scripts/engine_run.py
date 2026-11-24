"""Run the intelligence engine on local files (development and validation).

    python scripts/engine_run.py --label NAME --mode FAST|FULL [--forecast] [--synthetic]
                                 [--independent openai|none] FILE [FILE ...]

--forecast prints the pre-flight (worst-case cost per stage against the
mode's cap and allotments) and exits: no API key is read and no model call is
made. Without it, the run uses the application's default roles for the mode
(Haiku extraction; FAST: Sonnet writer; FULL: Opus at ENGINE_SYNTHESIS_EFFORT),
refuses to start when the pre-flight fails, and checkpoints every answer in
.engine_runs/<label>/checkpoints/ so a re-run with the same label resumes,
and a FULL run labelled like an earlier FAST run reuses its extraction.

Files are extracted with the application's extractor (PDF/DOCX/XLSX/...);
.txt files may carry [[SOURCE: name | PAGE: n]] markers. Outputs go to
.engine_runs/<label>/ (git-ignored): result.json, record.json and fast.pdf
(+ full.pdf for FULL). Credentials come from this worktree's git-ignored .env
and are never printed. The OpenAI analyst refuses client documents unless the
owner's authorization is configured; without it the run is SINGLE_ANALYST.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load_package(files: list[str], synthetic: bool):
    from extractor import extract_document_with_metadata
    from engine.package import build_package
    docs = []
    for f in files:
        data = open(f, "rb").read()
        name = os.path.basename(f)
        if f.lower().endswith(".txt") and b"[[SOURCE:" in data[:200]:
            import re
            text = data.decode("utf-8")
            m = re.search(r"\[\[SOURCE:\s*([^|\]]+?)\s*[|\]]", text)
            docs.append({"name": m.group(1) if m else name, "text": text, "meta": {}})
        else:
            text, meta = extract_document_with_metadata(data, name)
            docs.append({"name": name, "text": text, "meta": meta})
    return build_package(docs, data_class="SYNTHETIC" if synthetic else "CLIENT")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--mode", required=True, choices=["FAST", "FULL"])
    ap.add_argument("--forecast", action="store_true", help="pre-flight only: $0, no model call")
    ap.add_argument("--synthetic", action="store_true", help="the files are synthetic, not client documents")
    ap.add_argument("--independent", default="openai", choices=["openai", "none"])
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=True)
    os.environ.setdefault("ENGINE_COST_LEDGER", os.path.join(ROOT, ".engine_runs", "cost_ledger.jsonl"))

    from engine import budget, pipeline
    from engine.checkpoints import DirStore
    from engine.render import render

    pkg = load_package(a.files, a.synthetic)
    roles = pipeline.default_roles(anthropic_key=None if a.forecast else
                                   (os.getenv("ENGINE_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")),
                                   independent=None if a.independent == "none" else "openai", mode=a.mode)
    route = getattr(roles.primary, "route", None)
    extract_model = (route("extract:x") if route else roles.primary).model
    pf = budget.preflight(pkg, a.mode, extract_model=extract_model, synthesis_model=roles.adjudicator.model,
                          writer_model=(roles.writer or roles.adjudicator).model)
    print(json.dumps(pf, indent=1, default=str))
    if a.forecast:
        return 0 if pf["ok"] else 1
    if not pf["ok"]:
        print("pre-flight refused the run; nothing was sent", file=sys.stderr)
        return 2

    out = os.path.join(ROOT, ".engine_runs", a.label)
    os.makedirs(out, exist_ok=True)

    def progress(*x):
        print(time.strftime("%H:%M:%S"), *x, flush=True)

    r = pipeline.run(pkg, roles, mode=a.mode, ledger=pipeline.new_ledger(a.mode, a.label), progress=progress,
                     store=DirStore(os.path.join(out, "checkpoints")), preflight=pf)
    with open(os.path.join(out, f"result_{a.mode.lower()}.json"), "w", encoding="utf-8") as fh:
        json.dump(r.to_dict(), fh, indent=1, default=str)
    with open(os.path.join(out, f"record_{a.mode.lower()}.json"), "w", encoding="utf-8") as fh:
        json.dump(r.record, fh, indent=1, default=str)
    if r.record.get("status") == "COMPLETE":
        for kind in ("fast", "full"):
            if r.composed.get(kind):
                with open(os.path.join(out, f"{kind}.pdf"), "wb") as fh:
                    fh.write(render(r.composed[kind]))
    print(json.dumps({k: r.record.get(k) for k in ("status", "verification", "limitations", "seconds", "usage")},
                     indent=1, default=str))
    print("register:", (r.register or {}).get("stats"))
    return 0 if r.record.get("status") == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
