"""Phase 4 narrative-completeness diagnostic: ONE instrumented Stage D API
call against the exact same frozen Stage B/Stage C inputs already used by
the authoritative Phase 4 commissioning run
(phase4-boc-2026-026-staged-20260912T131303Z-2cc8af). Stage A/B/C are NOT
rerun. Purpose is diagnosis only: capture the raw model response, stop
reason, and token usage via the existing production checkpoint mechanism
(stage_d_checkpoints.checkpoint_run), so the RAW MODEL RESPONSE -> PARSED
STAGE D RESPONSE -> POST-VALIDATION RESPONSE -> FINAL REBUILT STAGE D
RESULT chain can be directly compared for the five narrative fields
(executive_summary, notes, scope_categories, outline, risk_assessments).
"""
import copy
import json
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHASE2_RUN_ID = "phase2-boc-2026-026-stageb-20260912T125051Z-91a22b"
PHASE3_RUN_ID = "phase3-boc-2026-026-stagec-20260912T130007Z-dd391b"
PHASE2_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase2_commissioning" / PHASE2_RUN_ID
PHASE3_DIR = ROOT / "evaluation/bank_of_canada_briefing_pack/phase3_commissioning" / PHASE3_RUN_ID

DIAG_RUN_ID = f"phase4-narrative-diag-boc-2026-026-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
OUT = ROOT / "evaluation/bank_of_canada_briefing_pack/phase4_commissioning" / DIAG_RUN_ID
OUT.mkdir(parents=True, exist_ok=False)

CHECKPOINT_ROOT = Path(r"C:\Users\feras\AppData\Local\Temp\claude\C--Users-feras-Documents-Projects-Bid-Intelligence\51d7311b-766b-4ce6-af00-2c2abdf5f03e\scratchpad\stage_d_narrative_diagnostic") / DIAG_RUN_ID


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
                             encoding="utf-8")


from config import get_api_key
import stage_d_checkpoints as cp
from extractor import synthesize_bid_brief, StageDContextTooLargeError
from stage_d_projection import ProjectionValidationError

normalized_facts = json.loads((PHASE2_DIR / "stage_b_normalized_result.json").read_text(encoding="utf-8"))
conflicts = json.loads((PHASE3_DIR / "stage_c_conflicts.json").read_text(encoding="utf-8"))
canonical_resolved = json.loads((PHASE3_DIR / "stage_c_canonical_opportunity_resolved.json").read_text(encoding="utf-8"))
assert normalized_facts["_canonical_opportunity"]["documents"] == canonical_resolved["documents"]
assert {o["observation_id"] for o in normalized_facts["_canonical_opportunity"]["observations"]} == \
       {o["observation_id"] for o in canonical_resolved["observations"]}
normalized_facts["_canonical_opportunity"] = canonical_resolved
pristine_rejections = copy.deepcopy(normalized_facts.get("_provenance_rejections", []))

key = get_api_key()
if not key:
    raise RuntimeError("ANTHROPIC_API_KEY is unavailable")

t0 = time.monotonic()
status = "PASS"
error_detail = None
with cp.checkpoint_run(mode="required", root=CHECKPOINT_ROOT) as store:
    try:
        result = synthesize_bid_brief(normalized_facts, conflicts, key)
    except (ProjectionValidationError, StageDContextTooLargeError) as exc:
        status = "FAIL"
        error_detail = {"type": type(exc).__name__, "code": getattr(exc, "code", None), "message": str(exc)}
        result = None
    checkpoint_root = str(store.root)
    manifest = copy.deepcopy(store.manifest)
elapsed = round(time.monotonic() - t0, 3)

save("run_metadata.json", {
    "diagnostic_run_id": DIAG_RUN_ID, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "input_phase2_run_id": PHASE2_RUN_ID, "input_phase3_run_id": PHASE3_RUN_ID,
    "authoritative_phase4_run_id": "phase4-boc-2026-026-staged-20260912T131303Z-2cc8af",
    "purpose": "narrative-completeness diagnosis only, single instrumented Stage D API call",
    "checkpoint_root": checkpoint_root, "elapsed_seconds": elapsed, "status": status, "error": error_detail,
    "provenance_rejections_untouched": normalized_facts.get("_provenance_rejections", []) == pristine_rejections,
})
save("checkpoint_manifest.json", manifest)
print(f"STAGE D DIAGNOSTIC EXECUTION: {status}. Elapsed: {elapsed}s. Checkpoint root: {checkpoint_root}")
if status == "FAIL":
    print(json.dumps(error_detail, indent=2))
    sys.exit(1)

# ── Reassemble the raw -> parsed -> validated -> final chain ────────────────
store_root = Path(checkpoint_root)
attempt_dirs = sorted(p for p in store_root.glob("stage-d/attempt-*") if p.is_dir())
attempts = []
for attempt_dir in attempt_dirs:
    entry = {"attempt": attempt_dir.name}
    for name in ("response.json", "validation.json", "assembly-validation.json", "provider-error.json"):
        path = attempt_dir / name
        if path.exists():
            entry[name] = json.loads(path.read_text(encoding="utf-8"))
    attempts.append(entry)
save("attempts_raw_and_validation.json", attempts)

final_result = json.loads((store_root / "stage-d/synthesis-result.json").read_text(encoding="utf-8"))
save("final_synthesis_result.json", final_result)

NARRATIVE_FIELDS = ["brief.executive_summary", "bid.notes", "brief.scope_categories", "outline", "risk_assessments"]

def get_path(d, dotted):
    cur = d
    for part in dotted.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur

# Raw model response text -> parsed JSON (last successful attempt)
last_ok_attempt = next((a for a in reversed(attempts) if "response.json" in a
                        and a.get("validation.json", {}).get("status") == "VALIDATED"), attempts[-1])
raw_text = last_ok_attempt.get("response.json", {}).get("text")
raw_parsed = json.loads(raw_text) if raw_text else None
raw_synthesis = (raw_parsed or {}).get("synthesis", {})

post_validation = last_ok_attempt.get("validation.json", {}).get("synthesis", {})

field_trace = {}
for field in NARRATIVE_FIELDS:
    field_trace[field] = {
        "raw_model_response": get_path(raw_synthesis, field),
        "post_validation_response": get_path(post_validation, field),
        "final_rebuilt_result": get_path(final_result, field) if field != "risk_assessments"
                                  else "DROPPED_AT_REBUILD (see contract_risks[*].assessment; by design, not a defect)",
    }
save("narrative_field_trace.json", field_trace)

print(json.dumps({
    "attempts": len(attempts),
    "last_attempt_response_stop_reason": last_ok_attempt.get("response.json", {}).get("stop_reason"),
    "last_attempt_input_tokens": last_ok_attempt.get("response.json", {}).get("input_tokens"),
    "last_attempt_output_tokens": last_ok_attempt.get("response.json", {}).get("output_tokens"),
}, indent=2))
print(json.dumps(field_trace, indent=2)[:4000])
print(f"PHASE 4 NARRATIVE DIAGNOSTIC: {status}. Dumps at: {OUT.relative_to(ROOT)}")
print(f"Checkpoint artifacts at: {checkpoint_root}")
