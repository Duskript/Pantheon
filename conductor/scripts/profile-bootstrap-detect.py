#!/usr/bin/env python3
"""
profile-bootstrap-detect.py — Conductor v2 Step 4.4, Brief 1 of 3.

Detect canonical skills (under ~/.hermes/skills/) that lack a per-profile
SKILL.md under any of the 7 target god profiles
(apollo, cachyos, hephaestus, iris, marvin, rheta, thoth).

DETECTION ONLY. This script never writes to the per-profile trees. Brief 2
of Step 4.4 will create the symlinks; this script just reports.

Output:
  - default: tab-separated lines "<god>\t<cat>/<skill>" on stdout
  - --json : [{"god": "...", "category": "...", "skill_name": "..."}, ...]

Exit codes:
  - 0 always on successful run (idempotent; "needs work" is a normal state)
  - 1 only on script error (filesystem, parse, argparse, etc.)

Filtering rules:
  - skip canonical paths that contain a ".archive/" component
    (archived skills are not discoverable; Brief 1 does not touch them)
  - skip (profile, category, skill_name) tuples present in
    shared/active/conductor-step-4.3-no-canon.txt
    (intentional per-profile-only skills — no canonical twin by design)
  - scan only the 7 god profiles listed in TARGET_PROFILES (below),
    not every directory under ~/.hermes/profiles/
    (caduceus, hermes, master-coder, mercer, theoforge are out of scope
    for Step 4.4; they were excluded in Step 4.3 by Hermes ratifying
    the 7-god scope)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable

# --- constants (pinned from the brief) -------------------------------------

CANONICAL_ROOT = Path(os.path.expanduser("~/.hermes/skills"))
PROFILES_ROOT = Path(os.path.expanduser("~/.hermes/profiles"))
NO_CANON_REPORT = Path(
    os.path.expanduser("~/pantheon/shared/active/conductor-step-4.3-no-canon.txt")
)

# 7 god profiles in scope (Apollo, CachyOS, Hephaestus, Iris, Marvin,
# Rheta, Thoth). Hermes, Caduceus, Mercer, MasterCoder, TheoForge are
# observed in ~/.hermes/profiles/ but out of scope for Step 4.4.
TARGET_PROFILES = ("apollo", "cachyos", "hephaestus", "iris", "marvin", "rheta", "thoth")

# SKILL.md is the discoverable sentinel; the brief pins it.
SKILL_FILENAME = "SKILL.md"

# Skip canonical paths that contain any of these components
# (archived/non-discoverable). The brief: ".archive/ subdirs are out of scope".
SKIP_PATH_COMPONENTS = (".archive",)


# --- helpers ---------------------------------------------------------------

def log_err(msg: str) -> None:
    """Stderr informational logging. Stdout is reserved for the report."""
    print(msg, file=sys.stderr)


def parse_no_canon(path: Path) -> set[tuple[str, str, str]]:
    """Parse the NO-CANON report and return a set of (profile, cat, skill).

    The file format is:
        # comment lines start with '#'
        profile|category|skill_name|per_profile_path|mtime|size_bytes
    Blank lines and comments are skipped. We extract the first three
    pipe-separated fields and build a set for O(1) lookup.
    """
    skip: set[tuple[str, str, str]] = set()
    if not path.is_file():
        log_err(f"[warn] NO-CANON report not found: {path} (filter disabled)")
        return skip
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
    """Yield (category, skill_name, skill_md_path) for every discoverable
    canonical SKILL.md under `root`.

    A discoverable skill lives at:
        <root>/<category>/<skill_name>/SKILL.md
    (depth 3 from <root>). Paths that contain a SKIP_PATH_COMPONENTS
    component (e.g. ".archive") are excluded.
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
                # Canonical must be a regular file (not a symlink) — we
                # only detect drift of real skills. Symlinked canonical
                # entries are out of scope for Step 4.4.
                yield category_dir.name, skill_dir.name, skill_md


def detect_drift(
    profiles: tuple[str, ...] = TARGET_PROFILES,
    no_canon: set[tuple[str, str, str]] | None = None,
    *,
    canonical_root: Path = CANONICAL_ROOT,
    profiles_root: Path = PROFILES_ROOT,
) -> list[dict[str, str]]:
    """Return a list of {god, category, skill_name} dicts that need symlinks.

    For each canonical (cat, skill), for each god in `profiles`, check
    whether the per-profile SKILL.md exists. Status:
      - missing                       -> needs symlink (output)
      - exists, regular file          -> drift (logged to stderr; NOT
                                         in output, since the path is
                                         PRESENT at the expected
                                         location — Brief 1's output
                                         is "what's missing?")
      - exists, symlink (any target)  -> correct state, skip
      - (profile, cat, skill) in no_canon set -> skip (intentional
                                         per-profile-only)

    We do NOT validate that symlinks resolve to the current canonical.
    The brief's scope is "is the per-profile path present" — not "is it
    correct". A broken/stale symlink is detectable by Brief 2's
    create-symlink pass (it will overwrite stale symlinks with `ln -sf`).
    Out of scope for detection.
    """
    if no_canon is None:
        no_canon = set()

    findings: list[dict[str, str]] = []
    for cat, skill, _skill_path in iter_canonical_skill_files(canonical_root):
        for god in profiles:
            if (god, cat, skill) in no_canon:
                # Intentional per-profile-only (per Step 4.3 NO-CANON report)
                continue
            per_profile = profiles_root / god / "skills" / cat / skill / SKILL_FILENAME
            if per_profile.is_symlink() or per_profile.is_file():
                # Per-profile path exists. The path is PRESENT at the
                # expected location; this canonical skill is NOT flagged
                # as "needs symlink" for this god. If it's a regular file
                # rather than a symlink, that's drift (a manual edit
                # landed a real file); we log it but don't include in
                # output (Brief 2 may want to re-symlink, but Brief 1's
                # output shape is "what's missing?").
                #
                # Fix (Brief 1.5, 2026-06-15): `is_file()` follows
                # symlinks and returns True for a valid symlink pointing
                # to a regular file. We must ALSO check `not is_symlink()`
                # before logging drift, otherwise every correct symlink
                # is misclassified as drift. Hardlinks (ln, not ln -s) are
                # a third case: `is_file()` returns True AND `is_symlink()`
                # returns False — those are NOT drift either, they're
                # functionally equivalent to symlinks. So both must be
                # excluded to log only genuine drift (regular file landed
                # by a manual edit, not by a hardlink).
                if per_profile.is_file() and not per_profile.is_symlink():
                    # Belt-and-suspenders: even with the symlink check,
                    # also verify inode != canonical inode to skip hardlinks.
                    try:
                        if per_profile.stat().st_ino == per_profile.resolve().stat().st_ino:
                            # Same file as the resolved target (hardlink case)
                            # — not drift, just a hardlink pointing at canon.
                            continue
                    except (OSError, FileNotFoundError):
                        pass  # broken symlink etc. — fall through to drift log
                    log_err(
                        f"[drift] {god}\t{cat}/{skill} — per-profile is a "
                        f"regular file, not a symlink"
                    )
                # else: symlink (or hardlink resolved as same file), correct state, silent
                continue
            # Missing entirely — Brief 2 will create the symlink
            findings.append({"god": god, "category": cat, "skill_name": skill})
    return findings


# --- CLI -------------------------------------------------------------------

def render_text(findings: list[dict[str, str]]) -> str:
    """Tab-separated output, one finding per line: '<god>\t<cat>/<skill>'."""
    return "\n".join(f"{f['god']}\t{f['category']}/{f['skill_name']}" for f in findings)


def render_json(findings: list[dict[str, str]]) -> str:
    """JSON array (compact, one object per finding)."""
    return json.dumps(findings, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="profile-bootstrap-detect",
        description=(
            "Detect canonical skills missing a per-profile SKILL.md "
            "(Conductor v2 Step 4.4, Brief 1 of 3). Detection only — "
            "this script never writes to per-profile trees."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit JSON array of {god, category, skill_name} objects (default: text)",
    )
    parser.add_argument(
        "--canonical-root",
        type=Path,
        default=CANONICAL_ROOT,
        help=(
            f"canonical skills root (default: {CANONICAL_ROOT}). "
            f"Used for tests; production should leave this unset."
        ),
    )
    parser.add_argument(
        "--profiles-root",
        type=Path,
        default=PROFILES_ROOT,
        help=(
            f"per-profile skills root (default: {PROFILES_ROOT}). "
            f"Used for tests; production should leave this unset."
        ),
    )
    parser.add_argument(
        "--no-canon-report",
        type=Path,
        default=NO_CANON_REPORT,
        help=(
            f"NO-CANON report path (default: {NO_CANON_REPORT}). "
            f"Used for tests; production should leave this unset."
        ),
    )
    args = parser.parse_args(argv)

    try:
        # CLI overrides flow through to detect_drift (and the iter helper).
        # A bad --canonical-root surfaces as FileNotFoundError in
        # iter_canonical_skill_files, caught below for exit code 1.
        no_canon = parse_no_canon(args.no_canon_report)
        log_err(f"[info] no_canon filter loaded: {len(no_canon)} tuples")
        findings = detect_drift(
            TARGET_PROFILES,
            no_canon,
            canonical_root=args.canonical_root,
            profiles_root=args.profiles_root,
        )
        log_err(f"[info] findings: {len(findings)}")
    except (FileNotFoundError, OSError) as e:
        log_err(f"[error] {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        log_err(f"[error] unexpected: {e!r}")
        return 1

    if args.json:
        print(render_json(findings))
    else:
        if findings:
            print(render_text(findings))
        # else: no findings, emit nothing on stdout (empty output is
        # the idempotent no-op state the brief expects)
    return 0


if __name__ == "__main__":
    sys.exit(main())
