"""
CHECK-2D live acceptance (one-off, deliberate, READ-ONLY, zero provider calls):
render the durable Calgary CHECK run as the Proposal Assurance Report.

    python scripts/export_check2d_calgary_report.py <out.pdf> [bid_id=1360] [run_id=37]

Goes through the production path (tenancy.export_check_assurance_report_for_
organization -> check_run_service.get_check_run_result -> DB rows) with every
provider / adjudication / execution entry point and every CHECK / analysis
write path poisoned in-process: any attempt raises and is reported. Prints a
JSON summary (page count, size, semantic digest, status counts, programmatic
content checks). Record model_usage_events before and after running it.
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import check_coverage as cc  # noqa: E402
import check_run_service as csr  # noqa: E402
import config  # noqa: E402
import database as db  # noqa: E402
import full_analysis  # noqa: E402
import pypdf  # noqa: E402
import tenancy  # noqa: E402

HITS: list = []


def _poison(mod, name):
    if not hasattr(mod, name):
        return

    def boom(*a, **k):
        HITS.append(f"{mod.__name__}.{name}")
        raise RuntimeError(f"forbidden call during CHECK-2D export: {mod.__name__}.{name}")
    setattr(mod, name, boom)


for _m, _n in ((cc, "run_check_coverage"), (cc, "plan_check_coverage"), (cc, "_default_model_call"),
               (full_analysis, "_call_model"), (config, "get_anthropic_client"), (config, "execute_messages_create"),
               (csr, "_execute_check_run"), (csr, "start_check_run"), (csr, "mark_check_run_stuck"),
               (db, "start_check_run"), (db, "record_check_run_event"), (db, "finalize_check_run"),
               (db, "create_analysis_run"), (db, "update_analysis_run"), (db, "create_analysis_result")):
    _poison(_m, _n)


def main() -> int:
    out_path = Path(sys.argv[1])
    bid_id = int(sys.argv[2]) if len(sys.argv) > 2 else 1360
    run_id = int(sys.argv[3]) if len(sys.argv) > 3 else 37
    org = db.get_bid(bid_id)["organization_id"]
    out = tenancy.export_check_assurance_report_for_organization(bid_id, org, run_id)
    out_path.write_bytes(out["pdf"])
    reader = pypdf.PdfReader(io.BytesIO(out["pdf"]))
    text = re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in reader.pages))
    checks = {
        "procurement_title": "Design and Delivery Services for Leadership Learning" in text,
        "rfp_id": "26-1603" in text,
        "buyer": "The City of Calgary" in text,
        "run_complete": "CHECK run status: COMPLETE" in text,
        "headings": all(h in text for h in (
            "Assurance Overview", "Evaluation Criteria Overview", "Findings Requiring Attention",
            "Human Review Required", "Not Verifiable from the Submitted Files", "Not Addressed (0)",
            "Addressed Mandatory Requirements", "Outside Proposal-Assurance Scope", "Evidence Appendix",
            "Methodology & Status Definitions")),
        "req46": "REQ-46" in text,
        "b2_evidence": "Multi-party form" in text and "B2 Multi-Party Confirmation Form" in text,
        "appendix_d_evidence": "Pricing form" in text and "Appendix D_Price Form" in text,
        "appendix_e_evidence": "Submission form" in text and "APPENDIX E_" in text,
        "no_overall_score": not re.search(r"overall score|win probability|estimated score|\d+\s*/\s*100",
                                          text, re.I),
        "no_recommendation_section": not re.search(r"recommendations?\b", text, re.I),
    }
    summary = {"out": str(out_path), "filename": out["filename"], "bytes": len(out["pdf"]),
               "pages": len(reader.pages), "digest": out["digest"], "checks": checks, "poisoned_hits": HITS}
    print(json.dumps(summary, indent=1))
    return 0 if all(checks.values()) and not HITS else 1


if __name__ == "__main__":
    raise SystemExit(main())
