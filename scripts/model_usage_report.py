"""
scripts/model_usage_report.py

Compact, deterministic CLI over the model_usage_events table (Phase 4, BI
Context & Token Optimization Program). Makes NO model/provider calls --
pure reporting over already-persisted telemetry. Default output is a
short summary; individual events are never dumped unless --detail is
explicitly passed.

Usage:
    python scripts/model_usage_report.py --run-id 42
    python scripts/model_usage_report.py --bid-id 1083
    python scripts/model_usage_report.py --workflow fast_analysis
    python scripts/model_usage_report.py --workflow fast_analysis --since 2026-09-01
    python scripts/model_usage_report.py --workflow section_analyzer --detail
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_telemetry as mt


def _fmt(n) -> str:
    return f"{n:,}" if n is not None else "n/a"


def _print_summary(title: str, summary: dict) -> None:
    print(title.upper())
    print(f"Calls: {_fmt(summary['calls'])}  (failures: {_fmt(summary['failures'])}, "
         f"retries: {_fmt(summary['retries'])})")
    print(f"Input tokens:  {_fmt(summary['input_tokens'])}")
    print(f"Output tokens: {_fmt(summary['output_tokens'])}")
    print(f"Cache read:    {_fmt(summary['cache_creation_tokens'])} write / "
         f"{_fmt(summary['cache_read_tokens'])} read")
    if summary.get("reasoning_tokens") is not None:
        print(f"Reasoning tokens: {_fmt(summary['reasoning_tokens'])}")
    if summary.get("latency_ms") is not None:
        print(f"Total latency: {_fmt(summary['latency_ms'])} ms")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Compact model-usage telemetry report.")
    parser.add_argument("--run-id", type=int, help="analysis_run_id (Fast Analysis)")
    parser.add_argument("--bid-id", type=int, help="bid_id -- totals broken down by workflow")
    parser.add_argument("--workflow", type=str, help="e.g. fast_analysis, deep_verify, "
                        "section_analyzer, analyst, content_library")
    parser.add_argument("--since", type=str, help="YYYY-MM-DD")
    parser.add_argument("--until", type=str, help="YYYY-MM-DD")
    parser.add_argument("--detail", action="store_true",
                       help="Also list individual events (bounded, never a full dump by default)")
    args = parser.parse_args()

    if not any([args.run_id, args.bid_id, args.workflow, args.since]):
        parser.error("pass at least one of --run-id / --bid-id / --workflow / --since")

    if args.run_id:
        summary = mt.summarize_for_run(args.run_id)
        _print_summary(f"Analysis run {args.run_id}", summary)

    elif args.bid_id:
        by_workflow = mt.summarize_for_bid(args.bid_id)
        if not by_workflow:
            print(f"No usage events recorded for bid {args.bid_id}.")
        for workflow, summary in by_workflow.items():
            _print_summary(f"Bid {args.bid_id} -- {workflow}", summary)

    elif args.workflow:
        summary = mt.summarize_for_workflow(args.workflow, since=args.since, until=args.until)
        _print_summary(args.workflow, summary)
        top_ops = mt.top_operations_for_workflow(args.workflow, since=args.since, until=args.until)
        if top_ops:
            print("TOP OPERATIONS")
            for op, op_summary in top_ops:
                total = (op_summary["input_tokens"] or 0) + (op_summary["output_tokens"] or 0)
                print(f"  {op:35s} calls={_fmt(op_summary['calls']):>6s}  "
                     f"tokens={_fmt(total):>10s}  retries={_fmt(op_summary['retries'])}")
            print()

    elif args.since:
        by_key = mt.summarize_for_period(args.since, until=args.until)
        if not by_key:
            print("No usage events in this period.")
        for key, summary in by_key.items():
            _print_summary(key, summary)

    if args.detail:
        import database as db
        events = db.get_model_usage_events(
            bid_id=args.bid_id, analysis_run_id=args.run_id, workflow=args.workflow,
            since=args.since, until=args.until, limit=200)
        print(f"EVENTS ({len(events)}, max 200)")
        for e in events:
            print(f"  [{e.get('created_at')}] {e.get('workflow')}/{e.get('operation')} "
                 f"status={e.get('status')} in={_fmt(e.get('input_tokens'))} "
                 f"out={_fmt(e.get('output_tokens'))} retry={e.get('retry_number')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
