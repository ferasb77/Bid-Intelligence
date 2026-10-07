"""BI-VALUE-2.4 live York recommissioning (disposable bid only; never mutates Bid 1522).

Modes:
  run    -> create disposable bid, run governed research once (real provider), print JSON
  reuse  -> (new process) re-run same bid/fingerprint, expect REUSED_COMPLETE with 0 calls
  clean  -> delete the disposable bid via tenant-safe cleanup
Usage: python scripts/commission_bi_value_2_4_york.py run|reuse|clean <state.json>
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import buyer_research as br  # noqa: E402
import buyer_source_authority as bsa  # noqa: E402
import database as db  # noqa: E402
import tenancy  # noqa: E402

BUYER = "York University"
SOL = "P27-070"
ANCHOR = "Executive education leadership training"
BENCH_BID = 1522
FORBIDDEN = ("york.ac.uk", "york.edu", "yorkregion.com")


def _bench_snapshot() -> tuple[str, str]:
    sb = db.get_client()
    row = sb.table("bids").select("*").eq("id", BENCH_BID).execute().data[0]
    docs = sb.table("documents").select("id").eq("bid_id", BENCH_BID).execute().data
    reqs = sb.table("requirements").select("id").eq("bid_id", BENCH_BID).execute().data
    blob = json.dumps(
        {"bid": row, "docs": sorted(d["id"] for d in docs), "reqs": sorted(r["id"] for r in reqs)},
        sort_keys=True, default=str,
    )
    return row["organization_id"], hashlib.sha256(blob.encode()).hexdigest()


def main() -> int:
    mode, state_path = sys.argv[1], Path(sys.argv[2])
    org_id, snap = _bench_snapshot()
    out: dict = {"mode": mode, "policy": bsa.SOURCE_AUTHORITY_POLICY_VERSION, "bench_snapshot": snap}

    if mode == "run":
        bid_id = tenancy.create_bid_for_organization(
            {"title": "BI-VALUE-2.4 disposable York commissioning", "client": BUYER, "file_number": SOL},
            org_id,
        )
        state_path.write_text(json.dumps({"bid_id": bid_id, "org_id": org_id, "bench": snap}))
        out["bid_id"] = bid_id
    else:
        st = json.loads(state_path.read_text())
        bid_id = st["bid_id"]
        out["bid_id"] = bid_id

    if mode in ("run", "reuse"):
        calls = {"search": 0, "fetch": 0, "urls": []}
        if mode == "reuse":
            import buyer_research_provider as brp

            def _s(q):  # any provider call in reuse mode is a failure
                calls["search"] += 1
                return brp.anthropic_search(q)

            def _f(u):
                calls["fetch"] += 1
                return brp.anthropic_fetch(u)
        else:
            import buyer_research_provider as brp

            def _s(q):
                calls["search"] += 1
                return brp.anthropic_search(q)

            def _f(u):
                calls["fetch"] += 1
                calls["urls"].append(u)
                return brp.anthropic_fetch(u)

        res = br.run_governed_buyer_research(
            BUYER, bid_id=bid_id, organization_id=org_id, solicitation_number=SOL,
            context_anchors=ANCHOR, jurisdiction_country="CA", jurisdiction_subdivision="CA-ON",
            search_fn=_s, fetch_fn=_f,
        )
        urls = sorted({s.source_url for s in res.signals})
        out.update(
            status=res.status.value, searches=res.searches_executed, pages=res.pages_accepted,
            signals=len(res.signals), verified_domain=res.verified_buyer_domain, run_id=res.run_id,
            reused=res.cached_reuse, provider_search_calls=calls["search"],
            provider_fetch_calls=calls["fetch"], source_urls=urls,
            forbidden_hits=[u for u in urls if any(f in u for f in FORBIDDEN)],
            off_domain=[u for u in urls if not (res.verified_buyer_domain and (
                u.split("/")[2] == res.verified_buyer_domain or u.split("/")[2].endswith("." + res.verified_buyer_domain)
                or bsa.classify_government_domain(u, "CA")))],
        )

    if mode == "clean":
        out["delete"] = tenancy.delete_bid_for_organization(bid_id, org_id)

    org2, snap2 = _bench_snapshot()
    out["bench_unchanged"] = snap2 == snap
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
