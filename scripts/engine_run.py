"""Run the intelligence engine on local files (development and validation).

    python scripts/engine_run.py --label NAME [--synthetic] [--independent openai|none] FILE [FILE ...]

Files are extracted with the application's extractor (PDF/DOCX/XLSX/...);
.txt files may carry [[SOURCE: name | PAGE: n]] markers. Outputs go to
.engine_runs/<label>/ (git-ignored): result.json, fast.pdf, full.pdf,
record.json. Credentials come from this worktree's git-ignored .env and are
never printed. The OpenAI analyst refuses client documents unless the owner's
authorization is configured; without it the run is SINGLE_ANALYST.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--synthetic", action="store_true", help="the files are synthetic, not client documents")
    ap.add_argument("--independent", default="openai", choices=["openai", "none"])
    ap.add_argument("--effort", default="high")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=True)
    os.environ.setdefault("ENGINE_COST_LEDGER", os.path.join(ROOT, ".engine_runs", "cost_ledger.jsonl"))

    from extractor import extract_document_with_metadata
    from engine import pipeline
    from engine.package import build_package
    from engine.providers import AnthropicAnalyst, OpenAIAnalyst, UsageLedger
    from engine.render import render

    docs = []
    for f in a.files:
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
    pkg = build_package(docs, data_class="SYNTHETIC" if a.synthetic else "CLIENT")
    key = os.getenv("ENGINE_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    roles = pipeline.EngineRoles(
        primary=AnthropicAnalyst("claude-opus-5-5", effort=a.effort, api_key=key, name="claude-primary"),
        independent=OpenAIAnalyst(name="openai-independent") if a.independent == "openai" else None,
        adjudicator=AnthropicAnalyst("claude-opus-5-5", effort=a.effort, api_key=key, name="claude-adjudicator"))
    out = os.path.join(ROOT, ".engine_runs", a.label)
    os.makedirs(out, exist_ok=True)

    def progress(*x):
        print(time.strftime("%H:%M:%S"), *x, flush=True)

    r = pipeline.run(pkg, roles, ledger=UsageLedger(a.label), progress=progress)
    with open(os.path.join(out, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(r.to_dict(), fh, indent=1, default=str)
    with open(os.path.join(out, "record.json"), "w", encoding="utf-8") as fh:
        json.dump(r.record, fh, indent=1, default=str)
    if r.record.get("status") == "COMPLETE":
        for kind in ("fast", "full"):
            with open(os.path.join(out, f"{kind}.pdf"), "wb") as fh:
                fh.write(render(r.composed[kind]))
    print(json.dumps({k: r.record.get(k) for k in ("status", "verification", "limitations", "seconds", "usage")},
                     indent=1, default=str))
    print("register:", (r.register or {}).get("stats"))
    return 0 if r.record.get("status") == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
