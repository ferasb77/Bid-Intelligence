"""Re-attempt Stage D only, from an already-completed live Stage A-C result.

Not a fixture or replay of a whole pipeline run: normalized_facts/conflicts
here are the real output of an immediately-preceding live Stage A-D
commissioning attempt for the corrected Bank of Canada corpus, saved to disk
by scripts/commission_bank_of_canada.py. Stage D is stochastic (temperature
is not pinned), so re-invoking synthesize_bid_brief with the same authoritative
inputs is a legitimate way to determine whether a Stage D failure is a
one-off sampling event or a reproducible defect, without re-paying Stage A's
cost.
"""
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--input-dir", required=True, type=Path,
                     help="Directory containing stage-c-normalized-facts.json and stage-c-conflicts.json")
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--attempts", type=int, default=1)
args = parser.parse_args()

OUT = args.output.resolve()
if OUT == ROOT or ROOT in OUT.parents:
    raise ValueError("Commissioning artifacts must remain outside the repository")
OUT.mkdir(parents=True, exist_ok=True)

from config import get_api_key
from extractor import synthesize_bid_brief
from stage_d_projection import ProjectionValidationError

normalized = json.loads((args.input_dir / "stage-c-normalized-facts.json").read_text(encoding="utf-8"))
conflicts = json.loads((args.input_dir / "stage-c-conflicts.json").read_text(encoding="utf-8"))
key = get_api_key()
if not key:
    raise RuntimeError("ANTHROPIC_API_KEY is unavailable")

for i in range(1, args.attempts + 1):
    os.environ["CHECKPOINT_MODE"] = "required"
    os.environ["CHECKPOINT_ROOT"] = str(OUT / f"checkpoints-{i:02d}")
    t0 = time.monotonic()
    try:
        synthesis = synthesize_bid_brief(normalized, conflicts, key)
        elapsed = time.monotonic() - t0
        (OUT / f"stage-d-synthesis-{i:02d}.json").write_text(
            json.dumps(synthesis, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"attempt": i, "status": "PASS", "elapsed_seconds": round(elapsed, 3)}), flush=True)
    except ProjectionValidationError as exc:
        elapsed = time.monotonic() - t0
        print(json.dumps({"attempt": i, "status": "FAIL", "elapsed_seconds": round(elapsed, 3),
                          "code": exc.code, "message": str(exc)}), flush=True)
