"""
scripts/apply_document_moves.py

Phase 3 execution step: physically moves only HIGH_CONFIDENCE_HISTORICAL /
HIGH_CONFIDENCE_PROPOSED / HIGH_CONFIDENCE_SUPERSEDED root documents (per
docs/current/DOCUMENT_AUTHORITY_MAP.json) into the target docs/archive/
structure, using `git mv` so history is preserved, and rewrites ONLY the
mechanical path component of every affected markdown link so nothing 404s
-- never touching surrounding prose (instruction: "Do NOT rewrite
historical prose merely because a filename/path changes").

Does not move HIGH_CONFIDENCE_CURRENT or NEEDS_REVIEW documents. Safe to
inspect with --dry-run before applying.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "docs" / "current" / "DOCUMENT_AUTHORITY_MAP.json"

_MOVABLE = {"HIGH_CONFIDENCE_HISTORICAL", "HIGH_CONFIDENCE_PROPOSED", "HIGH_CONFIDENCE_SUPERSEDED"}

_LINK_RE = re.compile(r"(\]\()([A-Za-z0-9_.\-]+\.md)(\))")


def _load_plan() -> dict:
    """path (root filename) -> new relative path under docs/archive/...,
    for every document classified as movable with a concrete destination."""
    data = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    plan = {}
    for d in data["documents"]:
        if d["classification"] in _MOVABLE and d["proposed_destination"]:
            dest_dir = d["proposed_destination"].rstrip("/")
            plan[d["path"]] = f"{dest_dir}/{d['path']}"
    return plan


def _new_location(filename: str, plan: dict) -> str:
    """Where this file will live after the move, as a repo-relative path
    (root filename unchanged if it isn't moving)."""
    return plan.get(filename, filename)


def _rewrite_links_in_text(text: str, source_new_location: str, plan: dict) -> str:
    """Rewrites every `](TARGET.md)` link in `text` (whose file will live
    at `source_new_location` after this run) to the correct relative path
    to TARGET's own new-or-unchanged location. Only the path component
    inside `](...)` is touched -- link text and all surrounding prose are
    left byte-for-byte unchanged."""
    source_dir = Path(source_new_location).parent  # "." for a root file

    def _replace(m: re.Match) -> str:
        prefix, target, suffix = m.group(1), m.group(2), m.group(3)
        target_new_location = _new_location(target, plan)
        # Compute a relative path from source_dir to target_new_location,
        # using POSIX separators for markdown portability.
        import os
        rel = os.path.relpath(target_new_location, start=str(source_dir))
        rel = rel.replace("\\", "/")
        return f"{prefix}{rel}{suffix}"

    return _LINK_RE.sub(_replace, text)


def build_actions(plan: dict) -> list[tuple[str, str]]:
    """[(old_repo_relative_path, new_repo_relative_path), ...] for every
    file actually being moved."""
    return [(old, new) for old, new in plan.items()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                       help="Print the move+relink plan without touching anything.")
    args = parser.parse_args()

    plan = _load_plan()
    actions = build_actions(plan)
    print(f"Files to move: {len(actions)}")

    # Every root .md file's link-rewrite is computed against ITS OWN final
    # location (moved or not) -- so a currently-CURRENT file that links to
    # a file that's moving also gets its link fixed, even though the
    # current file itself doesn't move.
    all_root_md = sorted(ROOT.glob("*.md"))

    if args.dry_run:
        for old, new in actions:
            print(f"  git mv {old} -> {new}")
        return 0

    # 1) Rewrite link targets in every root .md file's CURRENT content,
    #    computed against each file's post-move location, and write the
    #    result to a staging dict -- BEFORE any git mv, so every read sees
    #    the original file at its original path.
    rewritten = {}
    for f in all_root_md:
        text = f.read_text(encoding="utf-8", errors="ignore")
        new_location = _new_location(f.name, plan)
        new_text = _rewrite_links_in_text(text, new_location, plan)
        if new_text != text:
            rewritten[f.name] = new_text

    # 2) Write rewritten content back (still at the OLD path -- git mv
    #    preserves content, so editing first then moving keeps history
    #    clean: `git mv` alone, then a content-only diff on the new path).
    for name, new_text in rewritten.items():
        (ROOT / name).write_text(new_text, encoding="utf-8")
    print(f"Rewrote links in {len(rewritten)} file(s) (in place, pre-move)")

    # 3) git mv each file to its destination.
    for old, new in actions:
        dest = ROOT / new
        dest.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(["git", "mv", old, new], cwd=ROOT,
                               capture_output=True, text=True)
        if result.returncode != 0:
            print(f"FAILED: git mv {old} -> {new}\n{result.stderr}", file=sys.stderr)
            return 1
    print(f"Moved {len(actions)} file(s) via git mv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
