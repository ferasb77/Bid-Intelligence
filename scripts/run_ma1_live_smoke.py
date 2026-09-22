"""
One bounded, deliberate MA-1 Full Analysis commissioning smoke run.

Runs exactly six specialist provider calls plus one reconciliation call
against ONE already-COMPLETE Fast Analysis run's durable canonical
snapshot. Makes NO extraction calls and writes nothing to the database.

    python scripts/run_ma1_live_smoke.py <analysis_run_id> [out.json]

Deliberately NOT part of any automated test: the automated MA-1 suite is
fully deterministic and mocks every model call.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analysis_service as svc          # noqa: E402
import config                            # noqa: E402
import full_analysis as fa               # noqa: E402


def main() -> int:
    run_id = int(sys.argv[1]) if len(sys.argv) > 1 else 19
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    api_key = config.get_api_key()
    if not api_key:
        print("no API key configured; aborting before any spend")
        return 2

    t0 = time.monotonic()
    result = svc.run_full_analysis_for_run(run_id, api_key)
    elapsed = time.monotonic() - t0

    print(f"run_id={run_id} bid_id={result.bid_id} version={result.analysis_version}")
    print(f"canonical digest      : {result.canonical_snapshot_digest[:16]}")
    print(f"completeness          : {result.completeness_status}")
    print(f"total elapsed         : {elapsed:.1f}s (orchestrated {result.wall_seconds:.1f}s)")
    print(f"total provider calls  : {result.usage['total_calls']}")
    print(f"tokens in/out         : {result.usage['input_tokens']}/{result.usage['output_tokens']}")
    print("")
    for spec in result.specialist_results:
        print(f"  {spec['specialist_id']:<26} {spec['status']:<9} "
              f"{spec['duration_seconds']:>6.1f}s  findings={len(spec['findings']):<3} "
              f"rejected={len(spec['rejected_findings']):<3} "
              f"in/out={spec['usage'].get('input_tokens')}/{spec['usage'].get('output_tokens')} "
              f"confidence={spec['confidence']}")
    rec = result.reconciliation
    print("")
    print(f"  RECONCILIATION             {rec['status']:<9} {rec['duration_seconds']:>6.1f}s  "
          f"risks={len(rec['cross_domain_risks'])} contradictions={len(rec['contradictions'])} "
          f"merged={len(rec['reconciled_findings'])} duplicates={len(rec['duplicate_findings'])} "
          f"orphan_reqs={len(rec['orphaned_requirements'])} "
          f"incomplete_domains={len(rec['incomplete_domains'])}")

    if out_path:
        out_path.write_text(json.dumps(result.as_dict(), indent=1, default=str), encoding="utf-8")
        print(f"\nwrote {out_path}")
    return 0 if result.completeness_status != fa.COMPLETENESS_FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
