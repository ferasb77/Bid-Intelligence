"""
CHECK-1.1 -- one-off live commissioning step: establish the canonical
Calgary RFP 26-1603 benchmark bid (buyer side) and run exactly ONE bounded
Fast Analysis over the authoritative 13-file buyer package.

Deliberate, not part of any test. Idempotent on the bid: an existing bid
with file_number '26-1603' in the organization is reused (never a second
benchmark bid), documents already attached by name are not re-uploaded,
and a COMPLETE Fast Analysis run whose corpus already covers every buyer
document is reused instead of spending again.

Usage:
    python scripts/commission_check11_calgary_buyer.py <path-to-Calgary-RFP.zip> <organization_id>

Buyer-side ONLY: every document is attached as doc_type 'RFP / Source'.
Bidder-side files are never uploaded into the bid's document pool (they
are persisted separately as submission evidence, migration 021).
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db  # noqa: E402
import tenancy  # noqa: E402

FILE_NUMBER = "26-1603"
BID = {
    "title": "RFP 26-1603 - Design and Delivery Services for Leadership Learning and Development",
    "client": "The City of Calgary",
    "file_number": FILE_NUMBER,
    "stage": "Submitted",
    "sensitivity": "Standard",
    "notes": "CHECK-1.1 canonical CHECK benchmark bid. Buyer side: the complete authoritative RFP 26-1603 "
             "package (RFP with Price V2.5, Proponent Acknowledgements, Appendix D Price Form template, CGC "
             "2026-05-13, Addenda 1-5, four Q&A logs). Bidder side (Phoenix Consulting Canada submission) is "
             "held only as submission evidence (migration 021), never as bid documents.",
}


def main(zip_path: str, organization_id: str) -> None:
    with zipfile.ZipFile(zip_path) as z:
        files = [(os.path.basename(i.filename), z.read(i.filename)) for i in z.infolist() if not i.is_dir()]
    print(f"buyer package: {len(files)} files")

    bids = [b for b in tenancy.list_bids_for_organization(organization_id) if b.get("file_number") == FILE_NUMBER]
    if bids:
        bid_id = int(bids[0]["id"])
        print(f"reusing benchmark bid {bid_id}")
    else:
        bid_id = tenancy.create_bid_for_organization(BID, organization_id)
        print(f"created benchmark bid {bid_id}")

    have = {d["name"] for d in db.get_documents(bid_id)}
    for name, data in files:
        if name in have:
            print(f"  already attached: {name}")
            continue
        _, doc_id = tenancy.upload_document_for_organization(bid_id, organization_id, name, data, doc_type="RFP / Source")
        print(f"  attached doc {doc_id}: {name} ({len(data)} bytes)")

    docs = [d for d in db.get_documents(bid_id) if d.get("doc_type") == "RFP / Source"]
    doc_ids = {d["id"] for d in docs}
    for run in db.list_analysis_runs(bid_id):
        covered = {c.get("document_id") for c in (run.get("corpus_document_ids") or [])}
        if run.get("analysis_mode") == "FAST" and run.get("status") == "COMPLETE" and doc_ids <= covered:
            print(f"reusing COMPLETE Fast Analysis run {run['id']} -- no provider calls")
            return
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY not set")
    run = tenancy.start_fast_analysis_for_organization(bid_id, organization_id, api_key, created_by="check-1.1-commissioning")
    print(f"started Fast Analysis run {run['id']}")
    t0 = time.time()
    for t in threading.enumerate():
        if t.name == f"fast-analysis-run-{run['id']}":
            t.join()
    final = db.get_analysis_run(run["id"])
    print(json.dumps({"run_id": final["id"], "status": final["status"], "failure_reason": final.get("failure_reason"),
                      "wall_s": round(time.time() - t0, 1), "telemetry": final.get("telemetry")}, indent=1, default=str))


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
    except Exception:
        pass
    main(sys.argv[1], sys.argv[2])
