"""Live Stage D compatibility only. Never invokes A/B/C or writes raw data to Git."""
import argparse
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import extractor
from config import get_api_key
from stage_d_checkpoints import checkpoint_run
from stage_d_projection import canonical_json, digest, strict_json


def run_smoke(fixture, checkpoint_root):
    paths = {"normalized": ROOT / "tests/acceptance/results" / f"{fixture}_normalized_facts.json",
             "conflicts": ROOT / "tests/acceptance/results" / f"{fixture}_conflicts.json"}
    normalized = json.loads(paths["normalized"].read_text(encoding="utf-8"))
    conflicts = json.loads(paths["conflicts"].read_text(encoding="utf-8"))
    key = get_api_key()
    if not key:
        raise RuntimeError("No configured Anthropic API key; no dispatch occurred")
    events = []
    factory = extractor.get_anthropic_client

    def track(client):
        def create(**kwargs):
            event = {"attempt": len(events) + 1, "api_dispatch_occurred": True,
                     "model": kwargs["model"], "prompt_chars": len(kwargs["messages"][0]["content"][0]["text"]) + len(canonical_json(kwargs["output_config"])),
                     "structured_outputs": True, "output_config_digest": digest(kwargs["output_config"]),
                     "stop_reason": None, "response_json_parsed": False}
            events.append(event)
            print(f"{fixture}: Stage D dispatch {event['attempt']} ({event['prompt_chars']} chars)", file=sys.stderr, flush=True)
            response = client.messages.create(**kwargs)
            event["stop_reason"] = response.stop_reason
            event["returned_model"] = response.model
            try:
                strict_json("".join(b.text for b in response.content if b.type == "text"))
                event["response_json_parsed"] = True
            except RuntimeError:
                pass
            return response
        return SimpleNamespace(messages=SimpleNamespace(create=create),
                               with_options=lambda **options: track(client.with_options(**options)))

    with checkpoint_run(mode="required", root=checkpoint_root) as store:
        store.write("stage-b/normalized-facts.json", normalized)
        store.write("stage-c/conflicts.json", conflicts)
        summary = {"kind": "STAGE_D_CONTRACT_COMPATIBILITY_SMOKE", "fixture": fixture,
                   "input_files": {k: str(v.relative_to(ROOT)).replace("\\", "/") for k, v in paths.items()},
                   "input_digest": digest({"normalized_facts": normalized, "conflicts": conflicts}),
                   "requirement_count": len(normalized.get("requirements", [])), "conflicts_count": len(conflicts),
                   "model": "claude-haiku-4-5-20251001", "checkpoint_mode": "required", "checkpoint_run_id": store.root.name,
                   "runtime_versions": store.manifest["versions"],
                   "stage_a_calls": 0, "stage_b_calls": 0, "stage_c_calls": 0,
                   "authoritative_reapplication_passed": False, "final_assembly_passed": False,
                   "semantic_review": "PENDING", "error_code": None}
        start = time.perf_counter()
        try:
            with patch("extractor.get_anthropic_client", side_effect=lambda **kw: track(factory(**kw))), \
                 patch("extractor.extract_document_facts", side_effect=AssertionError("Stage A forbidden")) as stage_a, \
                 patch("extractor.normalize_package_facts", side_effect=AssertionError("Stage B forbidden")) as stage_b, \
                 patch("extractor.reconcile_package_facts", side_effect=AssertionError("Stage C forbidden")) as stage_c:
                synthesis = extractor.synthesize_bid_brief(normalized, conflicts, key)
                summary["authoritative_reapplication_passed"] = True
                final = extractor._assemble_procurement_result(synthesis, normalized, conflicts)
                store.write("stage-d/final-result.json", final)
                summary["final_assembly_passed"] = True
                summary.update(stage_a_calls=stage_a.call_count, stage_b_calls=stage_b.call_count, stage_c_calls=stage_c.call_count)
        except Exception as exc:
            # Never persist API exception text, headers, or credentials.
            summary["error_code"] = getattr(exc, "code", type(exc).__name__)
        summary["stage_d_duration_sec"] = round(time.perf_counter() - start, 3)
        for event in events:
            path = store.root / f"stage-d/attempt-{event['attempt']:02d}/validation.json"
            validation = strict_json(path.read_text(encoding="utf-8")) if path.exists() else {}
            event["citation_validation_passed"] = validation.get("status") == "VALIDATED"
            event["validation_failure_code"] = validation.get("code")
        summary.update(attempt_count=len(events), api_dispatch_occurred=bool(events), attempts=events,
                       result="PASS" if summary["final_assembly_passed"] else "FAIL")
        store.write("contract-smoke.json", summary)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", choices=("bc_ir67tvet42026_attempt2", "boc_2026_026"), required=True)
    parser.add_argument("--checkpoint-root", required=True)
    args = parser.parse_args()
    summary = run_smoke(args.fixture, args.checkpoint_root)
    print(json.dumps(summary, indent=2))
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
