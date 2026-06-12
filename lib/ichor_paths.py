"""
B3: pantheon:// path resolution.

Spec: ~/athenaeum/Codex-God-thoth/research/openviking-vs-ichor-comparison/build-brief.md §P3c
      ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md §B3

The `pantheon://` namespace exposes Ichor and the Athenaeum as a
browsable, scoped filesystem. This module is the *pure* resolver —
it parses paths and returns a structured description of what to
list or search. I/O is in ichor_browse.py (sibling module).

Path schema (top-level roots):
  pantheon://                  → all roots: warm, codexes, gods, reference
  pantheon://warm/             → distinct categories in warm_entities
  pantheon://warm/<category>/  → entities in that category
  pantheon://codexes/          → Codex-* dirs under ~/athenaeum/
  pantheon://codexes/<name>/   → files in a codex dir
  pantheon://gods/             → Codex-God-* dirs
  pantheon://gods/<name>/      → files in a god's codex
  pantheon://reference/        → categories in reference_knowledge
  pantheon://reference/<slug>/ → reference_knowledge entries

The "warm" root maps directly to the warm_entities table added in B1.
The "codexes" and "gods" roots are filesystem-backed (~/athenaeum/).
The "reference" root maps to reference_knowledge (currently empty in
production; schema is in place).

Invalid paths return an empty path-spec dict so callers can degrade
gracefully (per gate: "Invalid path returns empty list, not error").
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

PANTHEON_PREFIX = "pantheon://"

# Top-level roots (the things you can list at pantheon://)
ROOTS = ("warm", "codexes", "gods", "reference")

# God directories use the "Codex-God-" prefix on the filesystem but
# are exposed without the prefix on the namespace (e.g. "pantheon://gods/thoth/"
# → ~/athenaeum/Codex-God-thoth/).
_GOD_DIR_PREFIX = "Codex-God-"
_ATHENAEUM_ROOT = Path.home() / "athenaeum"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _strip_prefix(path: str) -> str:
    """Strip 'pantheon://' and any leading slashes, return '' for root."""
    if not path:
        return ""
    s = path.strip()
    if s.startswith(PANTHEON_PREFIX):
        s = s[len(PANTHEON_PREFIX):]
    s = s.strip("/")
    return s


def parse_path(path: Optional[str]) -> Dict[str, Any]:
    """Parse a pantheon:// path into a path-spec dict.

    Returns a dict with these keys:
      - root: str | None      — 'warm' / 'codexes' / 'gods' / 'reference' / None (root)
      - category: str | None  — for warm + reference: the category/slug
      - name: str | None      — for codexes + gods: the bare directory name
      - subpath: str | None   — any remaining subpath (e.g. subdirectory inside a codex)
      - raw: str              — the input, for error reporting
      - valid: bool           — False for malformed paths

    Examples:
      'pantheon://'                  → {root: None, valid: True}
      'pantheon://warm/'             → {root: 'warm', category: None}
      'pantheon://warm/blockers/'    → {root: 'warm', category: 'blocker'}
      'pantheon://codexes/'          → {root: 'codexes', name: None}
      'pantheon://codexes/Forge/'    → {root: 'codexes', name: 'Codex-Forge'}
      'pantheon://gods/thoth/'       → {root: 'gods', name: 'Codex-God-thoth'}
      'pantheon://reference/'        → {root: 'reference', category: None}
      ''                             → {root: None, valid: True}  (root alias)
      'panty://warm/'                → {valid: False, raw: ...}    (wrong prefix)
    """
    if path is None:
        return {"valid": False, "raw": str(path), "error": "path is None"}

    stripped = _strip_prefix(path)
    if not stripped:
        return {"root": None, "category": None, "name": None,
                "subpath": None, "raw": path, "valid": True}

    parts = stripped.split("/")
    head = parts[0].lower() if parts else ""

    if head not in ROOTS:
        # Unknown root — return invalid
        return {"valid": False, "raw": path, "error": f"unknown root: {head!r}"}

    spec: Dict[str, Any] = {"root": head, "valid": True, "raw": path}

    if head == "warm":
        spec["category"] = parts[1] if len(parts) > 1 and parts[1] else None
    elif head == "reference":
        spec["category"] = parts[1] if len(parts) > 1 and parts[1] else None
    elif head == "codexes":
        spec["name"] = ("Codex-" + parts[1]) if len(parts) > 1 and parts[1] else None
        spec["subpath"] = "/".join(parts[2:]) if len(parts) > 2 else None
    elif head == "gods":
        spec["name"] = (_GOD_DIR_PREFIX + parts[1]) if len(parts) > 1 and parts[1] else None
        spec["subpath"] = "/".join(parts[2:]) if len(parts) > 2 else None

    return spec


# ---------------------------------------------------------------------------
# Filesystem resolution (codexes + gods roots)
# ---------------------------------------------------------------------------

def list_codex_dirs() -> List[Path]:
    """Return all Codex-* directories under ~/athenaeum/.

    Excludes Codex-God-* (those are gods) and any directory that
    doesn't start with 'Codex-' to avoid confusing non-codex dirs
    like 'handoffs' or 'research'.
    """
    if not _ATHENAEUM_ROOT.exists():
        return []
    return sorted([
        p for p in _ATHENAEUM_ROOT.iterdir()
        if p.is_dir()
        and p.name.startswith("Codex-")
        and not p.name.startswith(_GOD_DIR_PREFIX)
    ])


def list_god_dirs() -> List[Path]:
    """Return all Codex-God-* directories under ~/athenaeum/."""
    if not _ATHENAEUM_ROOT.exists():
        return []
    return sorted([
        p for p in _ATHENAEUM_ROOT.iterdir()
        if p.is_dir() and p.name.startswith(_GOD_DIR_PREFIX)
    ])


def list_codex_files(codex_name: str) -> List[Path]:
    """List files inside a codex dir, relative paths returned absolute.

    Skips hidden files, INDEX.md is sorted to the top, then alphabetic.
    """
    codex_path = _ATHENAEUM_ROOT / codex_name
    if not codex_path.is_dir():
        return []
    files = [p for p in codex_path.rglob("*") if p.is_file()
             and not p.name.startswith(".")]
    # INDEX.md first, then alphabetic
    files.sort(key=lambda p: (0 if p.name == "INDEX.md" else 1, str(p).lower()))
    return files


# ---------------------------------------------------------------------------
# Path matching (for ichor_find's subtree filter)
# ---------------------------------------------------------------------------

def path_matches(path: str, subpath_filter: Optional[str]) -> bool:
    """Check if a filesystem path is under the given subpath.

    subpath_filter uses '/' as separator (filesystem style, not
    pantheon://). If filter is None/empty, everything matches.
    """
    if not subpath_filter:
        return True
    # Normalize: leading/trailing slashes don't matter
    norm = subpath_filter.strip("/")
    if not norm:
        return True
    return "/" + norm + "/" in "/" + path.strip("/") + "/"


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Quick CLI for debugging
    import sys
    if len(sys.argv) > 1:
        print(parse_path(sys.argv[1]))
    else:
        # Demo
        for p in [
            "pantheon://",
            "pantheon://warm/",
            "pantheon://warm/blockers/",
            "pantheon://codexes/Forge/",
            "pantheon://codexes/Forge/notes.md",
            "pantheon://gods/thoth/research/",
            "pantheon://reference/",
            "not-a-path",
            "",
        ]:
            print(f"  {p!r:55s} → {parse_path(p)}")
        print()
        print(f"  codex dirs: {len(list_codex_dirs())}")
        print(f"  god dirs:   {len(list_god_dirs())}")
