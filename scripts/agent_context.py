"""
scripts/agent_context.py

Deterministic current-state snapshot for a fresh agent starting work on
this repo. Makes NO model/API calls. Prints a compact summary (target
~1-2 KB, never full diffs/logs/file inventories/document contents) and
exits 0. Safe to run repeatedly; read-only.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _git(*args) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception as exc:
        return f"<git call failed: {exc}>"


def _highest_migration() -> str:
    migrations = sorted((ROOT / "migrations").glob("*.sql"))
    return migrations[-1].name if migrations else "<none found>"


def main() -> int:
    branch = _git("branch", "--show-current")
    head = _git("rev-parse", "HEAD")
    head_short = _git("rev-parse", "--short", "HEAD")

    status_lines = _git("status", "--porcelain").splitlines()
    tracked_changes = [l for l in status_lines if not l.startswith("??")]
    untracked = [l[3:] for l in status_lines if l.startswith("??")]

    log = _git("log", "--oneline", "-5")

    print("=" * 60)
    print("BID INTELLIGENCE -- AGENT CONTEXT SNAPSHOT (read-only, no model calls)")
    print("=" * 60)
    print(f"Repository:   Bid-Intelligence")
    print(f"Branch:       {branch}")
    print(f"HEAD:         {head}  ({head_short})")
    print()
    print(f"Working tree: {'CLEAN' if not status_lines else f'{len(tracked_changes)} tracked change(s), {len(untracked)} untracked file(s)'}")
    if tracked_changes:
        print("  Tracked changes:")
        for l in tracked_changes[:10]:
            print(f"    {l}")
        if len(tracked_changes) > 10:
            print(f"    ... and {len(tracked_changes) - 10} more")
    if untracked:
        print(f"  Untracked files: {len(untracked)}")
        for name in untracked[:5]:
            print(f"    {name}")
        if len(untracked) > 5:
            print(f"    ... and {len(untracked) - 5} more")
    print()
    print("Last 5 commits:")
    for line in log.splitlines():
        print(f"  {line}")
    print()
    print(f"Highest migration file in repo: {_highest_migration()}")
    print("  (a migration FILE existing here does not mean it is applied to any")
    print("   live database -- see docs/current/SYSTEM_STATE.md)")
    print()
    print("Development-freeze status: see docs/current/SYSTEM_STATE.md")
    print("  ('Current development freeze' section)")
    print()
    print("Key entry points:")
    print("  fast_analysis.py, analysis_service.py   -- Fast Analysis engine")
    print("  pages/stage_build.py, section_analyzer.py -- BUILD / Section Analyzer")
    print("  analyst.py                               -- CHECK / proposal alignment")
    print("  tenancy.py, database.py                  -- auth boundary / persistence")
    print()
    print("Test command: python -m pytest -q   (targeted file first; full suite once")
    print("  after a substantive change -- see docs/current/CHANGE_VERIFICATION.md)")
    print()
    print("Read next: docs/current/SYSTEM_STATE.md, docs/current/NAVIGATION.md")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
