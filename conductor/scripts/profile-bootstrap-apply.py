#!/usr/bin/env python3
"""
profile-bootstrap-apply.py — Conductor v2 Step 4.4, Brief 2 of 3.

Apply per-profile symlinks for canonical skills flagged by Brief 1's
detector (`profile-bootstrap-detect.py`). Reads the live filesystem
(Brief 1 is a black box — this script does NOT import it; it duplicates
the small scan-and-filter so Brief 1 remains untouched per the brief).

Behavior:
  - For each canonical (cat, skill) under ~/.hermes/skills/ and each god
    in TARGET_PROFILES, ensure ~/.hermes/profiles/<god>/skills/<cat>/<skill>/SKILL.md
    is a symlink to the canonical target.
  - Missing entries: create the symlink.
  - Regular-file drift: back up to --backup-dir first, then `ln -sf`.
  - Existing symlinks pointing to the correct target: skip (idempotent).
  - Existing symlinks pointing to a stale/wrong target: overwrite with `ln -sf`.
  - Entries in the NO-CANON report: skip (intentional per-profile-only).

CLI:
  --dry-run         (default) print plan + summary, no writes
  --apply           opt-in mutator; required to actually touch the filesystem
  --god <name>      restrict to one profile (repeatable)
  --limit <int>     cap number of symlinks created
  --json            emit machine-readable plan + summary
  --backup-dir <p>  where drift files are copied before overwrite
                    default: ~/.hermes/profiles/_bootstrap-backups/<timestamp>/

Exit codes:
  0  success or partial success (failed count > 0 still = 0, per brief)
  1  script-broken only: parse error, NO-CANON missing AND filter
     relied on it, canonical root missing, etc., AND nothing was written

Stdout (text mode): per-entry log lines + final summary block
Stderr: informational + drift log (mirrors Brief 1's stderr shape)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

# --- constants (mirror Brief 1, do not import) -----------------------------

CANONICAL_ROOT = Path(os.path.expanduser("~/.hermes/skills"))
PROFILES_ROOT = Path(os.path.expanduser("~/.hermes/profiles"))
NO_CANON_REPORT = Path(
    os.path.expanduser("~/pantheon/shared/active/conductor-step-4.3-no-canon.txt")
)
TARGET_PROFILES = (
    "apollo", "cachyos", "hephaestus", "iris", "marvin", "rheta", "thoth",
)
SKILL_FILENAME = "SKILL.md"
SKIP_PATH_COMPONENTS = (".archive",)
DEFAULT_BACKUP_ROOT = PROFILES_ROOT / "_bootstrap-backups"


# --- helpers ---------------------------------------------------------------

def log_err(msg: str) -> None:
    """Stderr informational. Stdout is reserved for the report + summary."""
    print(msg, file=sys.stderr)


def parse_no_canon(path: Path) -> set[tuple[str, str, str]]:
    """Parse the NO-CANON report. Mirrors Brief 1's parser exactly.

    Format: '#' comment lines + blank lines are skipped; data lines are
    'profile|category|skill_name|per_profile_path|mtime|size_bytes'.
    Returns the set of (profile, cat, skill) tuples to exclude.
    """
    skip: set[tuple[str, str, str]] = set()
    if not path.is_file():
        # Unlike Brief 1 (which warns and disables the filter), the applier
        # is mutating — operating without a NO-CANON filter would clobber
        # intentional per-profile files. We require the report to exist.
        raise FileNotFoundError(
            f"NO-CANON report not found: {path} (required for safe apply)"
        )
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) < 3:
                log_err(f"[warn] NO-CANON malformed line (skipped): {line!r}")
                continue
            profile, cat, skill = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if profile and cat and skill:
                skip.add((profile, cat, skill))
    return skip


def iter_canonical_skill_files(root: Path) -> Iterable[tuple[str, str, Path]]:
    """Yield (cat, skill_name, skill_md_path) for every discoverable canonical
    SKILL.md under `root`. Mirrors Brief 1's iter helper exactly.
    """
    if not root.is_dir():
        raise FileNotFoundError(f"canonical skills root missing: {root}")
    for category_dir in sorted(root.iterdir()):
        if not category_dir.is_dir():
            continue
        if any(part in SKIP_PATH_COMPONENTS for part in category_dir.parts):
            continue
        for skill_dir in sorted(category_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            if any(part in SKIP_PATH_COMPONENTS for part in skill_dir.parts):
                continue
            skill_md = skill_dir / SKILL_FILENAME
            if skill_md.is_file() and not skill_md.is_symlink():
                yield category_dir.name, skill_dir.name, skill_md


# --- core ------------------------------------------------------------------

def build_plan(
    profiles: tuple[str, ...],
    no_canon: set[tuple[str, str, str]],
    *,
    canonical_root: Path,
    profiles_root: Path,
) -> tuple[list[dict], list[dict]]:
    """Scan the filesystem and split findings into (todo, drift) lists.

    todo:  entries that need a symlink created (currently missing)
    drift: entries that exist as a regular file (need backup + ln -sf)
           Returned separately so the CLI can report the drift count
           on stderr (mirroring Brief 1) and process both the same way
           in the apply pass.
    """
    todo: list[dict] = []
    drift: list[dict] = []
    for cat, skill, skill_path in iter_canonical_skill_files(canonical_root):
        for god in profiles:
            if (god, cat, skill) in no_canon:
                continue
            per_profile = profiles_root / god / "skills" / cat / skill / SKILL_FILENAME
            if per_profile.is_symlink():
                # Already a symlink. If target matches, skip in plan (handled
                # by applier as 'skipped: already correct'). If target is
                # wrong, the applier overwrites. We track as a 'todo' so
                # the applier visits it (and decides skip vs overwrite).
                existing_target = os.readlink(per_profile)
                matches = (
                    Path(existing_target).resolve() == skill_path.resolve()
                )
                todo.append({
                    "god": god, "category": cat, "skill_name": skill,
                    "canonical": str(skill_path),
                    "per_profile": str(per_profile),
                    "current_state": "symlink_correct" if matches else "symlink_stale",
                    "existing_target": existing_target,
                })
            elif per_profile.is_file():
                drift.append({
                    "god": god, "category": cat, "skill_name": skill,
                    "canonical": str(skill_path),
                    "per_profile": str(per_profile),
                    "current_state": "drift_regular_file",
                })
            else:
                # Missing entirely
                todo.append({
                    "god": god, "category": cat, "skill_name": skill,
                    "canonical": str(skill_path),
                    "per_profile": str(per_profile),
                    "current_state": "missing",
                })
    return todo, drift


def backup_drift_file(
    per_profile: Path, backup_root: Path, *, apply_mode: bool
) -> str:
    """Copy a drift regular file to backup_root preserving relative layout.

    Returns the backup path. In dry-run, no copy is performed; the path
    is reported as 'planned' so the operator can see what would happen.
    """
    # per_profile = .../profiles/<god>/skills/<cat>/<skill>/SKILL.md
    # backup mirrors the per-profile layout under backup_root, so
    # an operator can `cp -r <backup_root>/<god> ~/.hermes/profiles/`
    # to restore if needed.
    parts = per_profile.parts
    try:
        idx = parts.index("profiles")
        tail = Path(*parts[idx + 1 :])  # <god>/skills/<cat>/<skill>/SKILL.md
        backup_path = backup_root / tail
    except ValueError:
        backup_path = backup_root / per_profile.name

    if apply_mode:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(per_profile, backup_path)
    return str(backup_path)


def apply_one(
    entry: dict, backup_root: Path | None, *, apply_mode: bool
) -> tuple[str, str | None]:
    """Apply (or plan) a single symlink operation.

    Returns (status, backup_path_or_none) where status is one of:
      - 'created'    : missing path, ln -sf ran (or planned)
      - 'overwritten': drift or stale symlink, ln -sf ran (or planned)
      - 'skipped'    : already a correct symlink
      - 'failed'     : sanity check or ln -sf failed
    """
    canonical = Path(entry["canonical"])
    per_profile = Path(entry["per_profile"])

    # Sanity: canonical must exist and be a regular file (not a symlink)
    if not canonical.is_file() or canonical.is_symlink():
        return "failed", None  # caller logs the reason

    backup_path: str | None = None

    if entry["current_state"] == "symlink_correct":
        return "skipped", None

    if entry["current_state"] == "drift_regular_file" and backup_root is not None:
        try:
            backup_path = backup_drift_file(
                per_profile, backup_root, apply_mode=apply_mode
            )
        except OSError:
            return "failed", None

    if apply_mode:
        # Ensure parent dir exists. mkdir -p is idempotent.
        try:
            per_profile.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return "failed", backup_path
        # ln -sf <canonical> <per_profile>
        rc = subprocess.run(
            ["ln", "-sf", str(canonical), str(per_profile)],
            check=False,
        ).returncode
        if rc != 0:
            return "failed", backup_path

    # Post-verify (apply mode only — in dry-run we trust the plan)
    if apply_mode:
        if not per_profile.is_symlink():
            return "failed", backup_path
        if Path(os.readlink(per_profile)).resolve() != canonical.resolve():
            return "failed", backup_path

    if entry["current_state"] in ("drift_regular_file", "symlink_stale"):
        return "overwritten", backup_path
    return "created", backup_path


# --- CLI -------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="profile-bootstrap-apply",
        description=(
            "Apply per-profile symlinks for canonical skills "
            "(Conductor v2 Step 4.4, Brief 2 of 3). "
            "Default mode is --dry-run; --apply is required to mutate."
        ),
    )
    parser.add_argument(
        "--dry-run", dest="dry_run", action="store_true", default=True,
        help="print plan + summary, do NOT write (default)",
    )
    parser.add_argument(
        "--apply", dest="dry_run", action="store_false",
        help="actually create symlinks (overrides --dry-run)",
    )
    parser.add_argument(
        "--god", dest="gods", action="append", default=None,
        help="restrict to one profile (repeatable: --god apollo --god thoth)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="cap number of symlinks created (for staged rollout)",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable output",
    )
    parser.add_argument(
        "--backup-dir", type=Path, default=None,
        help=(
            "where to back up drift files before overwrite "
            f"(default: {DEFAULT_BACKUP_ROOT}/<timestamp>/)"
        ),
    )
    parser.add_argument(
        "--canonical-root", type=Path, default=CANONICAL_ROOT,
        help=f"canonical skills root (default: {CANONICAL_ROOT})",
    )
    parser.add_argument(
        "--profiles-root", type=Path, default=PROFILES_ROOT,
        help=f"per-profile skills root (default: {PROFILES_ROOT})",
    )
    parser.add_argument(
        "--no-canon-report", type=Path, default=NO_CANON_REPORT,
        help=f"NO-CANON report path (default: {NO_CANON_REPORT})",
    )
    args = parser.parse_args(argv)

    apply_mode = not args.dry_run

    # Resolve god filter
    if args.gods:
        unknown = [g for g in args.gods if g not in TARGET_PROFILES]
        if unknown:
            log_err(f"[error] unknown --god value(s): {unknown} "
                    f"(allowed: {list(TARGET_PROFILES)})")
            return 1
        profiles: tuple[str, ...] = tuple(args.gods)
    else:
        profiles = TARGET_PROFILES

    # Resolve backup dir (only needed in apply mode, but plan it always)
    if args.backup_dir is not None:
        backup_root = args.backup_dir
    else:
        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_root = DEFAULT_BACKUP_ROOT / ts

    # Detect + plan
    try:
        no_canon = parse_no_canon(args.no_canon_report)
    except FileNotFoundError as e:
        log_err(f"[error] {e}")
        return 1
    log_err(f"[info] no_canon filter loaded: {len(no_canon)} tuples")

    try:
        todo, drift = build_plan(
            profiles, no_canon,
            canonical_root=args.canonical_root,
            profiles_root=args.profiles_root,
        )
    except (FileNotFoundError, OSError) as e:
        log_err(f"[error] {e}")
        return 1

    # Mirror Brief 1's stderr shape: log drift per-entry
    for d in drift:
        log_err(
            f"[drift] {d['god']}\t{d['category']}/{d['skill_name']} — "
            f"per-profile is a regular file, not a symlink"
        )

    # Combine: apply drift first (backup is the safety net), then missing.
    # For brevity, treat both as a single ordered work list. Drift goes
    # first so the backup happens before any symlink overwrites the file.
    work = drift + [t for t in todo if t["current_state"] != "symlink_correct"]
    skipped = [t for t in todo if t["current_state"] == "symlink_correct"]

    log_err(
        f"[info] plan: {len(drift)} drift, "
        f"{len([t for t in todo if t['current_state'] == 'missing'])} missing, "
        f"{len(skipped)} already correct, "
        f"apply_mode={apply_mode}, "
        f"backup_root={backup_root}"
    )

    if args.limit is not None:
        work = work[: args.limit]
        log_err(f"[info] --limit {args.limit}: capped work list to {len(work)}")

    # Apply (or plan)
    results: list[dict] = []
    succeeded = 0
    overwritten = 0
    skipped_count = 0
    failed = 0

    for entry in work:
        status, backup_path = apply_one(
            entry, backup_root if apply_mode else None,  # no backup in dry-run
            apply_mode=apply_mode,
        )
        results.append({
            "god": entry["god"],
            "category": entry["category"],
            "skill_name": entry["skill_name"],
            "per_profile": entry["per_profile"],
            "canonical": entry["canonical"],
            "status": status,
            "backup_path": backup_path,
        })
        if status == "created":
            succeeded += 1
        elif status == "overwritten":
            succeeded += 1
            overwritten += 1
        elif status == "skipped":
            skipped_count += 1
        else:
            failed += 1

    # Add the pre-existing-symlink skips to the results for full accounting
    for entry in skipped:
        results.append({
            "god": entry["god"],
            "category": entry["category"],
            "skill_name": entry["skill_name"],
            "per_profile": entry["per_profile"],
            "canonical": entry["canonical"],
            "status": "skipped",
            "backup_path": None,
        })
    skipped_count += len(skipped)

    summary = {
        "apply_mode": apply_mode,
        "backup_root": str(backup_root),
        "attempted": len(work),
        "succeeded": succeeded,
        "overwritten": overwritten,
        "created": succeeded - overwritten,
        "skipped": skipped_count,
        "failed": failed,
        "drift_total": len(drift),
        "missing_total": len(todo) - len(skipped),
        "no_canon_filtered": len(no_canon),
    }

    if args.json:
        print(json.dumps({"results": results, "summary": summary},
                         separators=(",", ":")))
    else:
        # Text mode: per-entry log on stdout
        for r in results:
            line = (
                f"{r['status']:11s} {r['god']:11s} "
                f"{r['category']}/{r['skill_name']}"
            )
            if r["backup_path"]:
                line += f"  (backup: {r['backup_path']})"
            print(line)
        print()
        print("summary:")
        for k in ("attempted", "succeeded", "overwritten", "created",
                 "skipped", "failed", "drift_total", "missing_total",
                 "no_canon_filtered"):
            print(f"  {k}: {summary[k]}")
        print(f"  apply_mode: {apply_mode}")
        print(f"  backup_root: {backup_root}")

    # Exit code per brief: "0 if failed == 0 (success or partial success
    # is still 0 — we report partial via the summary)". So individual
    # ln -sf failures don't fail the run; the operator reads the summary
    # and decides what to do. Exit 1 is reserved for script-broken cases
    # (parse error, missing NO-CANON, missing canonical root) — those
    # are returned early above.
    return 0


if __name__ == "__main__":
    sys.exit(main())
