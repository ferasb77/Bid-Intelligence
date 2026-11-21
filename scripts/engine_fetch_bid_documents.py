"""Read-only retrieval of one bid's source documents for local engine validation.

PREPARED, NOT EXECUTED. Running it against live Phoenix storage requires the
owner's explicit authorization for that specific bid (e.g. 2B OPCO). It:

  * requires --authorized-by "<who/when>" (recorded in the manifest),
  * loads the Supabase credentials from the env file given with --env-file
    into this process only (values are never printed or written),
  * performs only two read operations: database.get_documents(bid_id) and
    database.download_file(storage_path) for "RFP / Source" documents,
  * refuses any write: every mutating database helper is replaced by a
    function that raises before the run starts,
  * writes the files and a manifest (names, sizes, sha256; no content) to the
    git-ignored .engine_runs/inputs/<label>/.

    python scripts/engine_fetch_bid_documents.py --bid-id N --label NAME \
        --env-file PATH/TO/.env --authorized-by "owner, YYYY-MM-DD"

The fetched documents may then be analysed with Anthropic only:
    python scripts/engine_run.py --label NAME .engine_runs/inputs/NAME/*
(OpenAI refuses client documents unless separately authorized.)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
READS = {"get_documents", "download_file"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bid-id", type=int, required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--authorized-by", required=True)
    a = ap.parse_args()

    from dotenv import dotenv_values
    vals = dotenv_values(a.env_file)
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        if not vals.get(k):
            print(f"{k} missing in the env file")
            return 2
        os.environ[k] = vals[k]

    import database as db
    for name in dir(db):        # fail closed on anything that could write
        if name.startswith(("create_", "update_", "upsert_", "delete_", "insert_", "upload_", "save_", "set_",
                            "mark_", "claim_", "record_")) and callable(getattr(db, name)):
            setattr(db, name, lambda *x, _n=name, **k: (_ for _ in ()).throw(RuntimeError(f"write blocked: {_n}")))

    out = os.path.join(ROOT, ".engine_runs", "inputs", a.label)
    os.makedirs(out, exist_ok=True)
    docs = [d for d in db.get_documents(a.bid_id) if d.get("doc_type") == "RFP / Source"]
    manifest = {"bid_id": a.bid_id, "authorized_by": a.authorized_by, "operations": sorted(READS),
                "fetched_at": datetime.now(timezone.utc).isoformat(), "documents": []}
    for d in docs:
        data = db.download_file(d["storage_path"])
        if not data:
            manifest["documents"].append({"name": d["name"], "status": "NOT_DOWNLOADED"})
            continue
        safe = os.path.basename(d["name"])
        with open(os.path.join(out, safe), "wb") as fh:
            fh.write(data)
        manifest["documents"].append({"name": safe, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                                      "uploaded_at": str(d.get("created_at") or "")})
    with open(os.path.join(out, "_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    print(f"{len(manifest['documents'])} document(s) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
