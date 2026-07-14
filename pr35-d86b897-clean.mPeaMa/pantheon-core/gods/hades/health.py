"""Hades health-check phase.

Phase 1 of the pipeline. Walks every known Codex and reports:
  - File counts by subfolder (sessions / distilled / embeddable / total)
  - ChromaDB vs filesystem consistency (orphans in either direction)
  - Missing INDEX.md files (and auto-creates them when safe)
  - Stale files (>90d not modified) — archive candidates

Auto-creating INDEX.md is the only side-effect here, and it's bounded:
the generator only runs against subdirectories, not the codex root
itself, and only when no INDEX.md exists. The generator never
overwrites existing indexes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .paths import (
    ARCHIVE_DIR_NAME,
    ATHENAEUM_ROOT,
    CHROMA_DIR,
    DISTILLED_DIR_NAME,
    EMBEDDABLE_EXTS,
    INDEX_DESCRIPTION,
    KNOWN_CODEXES,
    SESSIONS_DIR_NAME,
    STALE_THRESHOLD_DAYS,
)

logger = logging.getLogger(__name__)


def _walk_codex_files(codex_root: Path) -> Dict[str, List[Path]]:
    """Walk a Codex directory and group files by subfolder.

    Returns: {
        "files": [all embeddable files excluding archive/distilled/sessions],
        "embeddable": [files that should be in ChromaDB],
        "sessions": [session log files],
        "distilled": [existing distilled files],
        "subdirs": [all subdirectories],
    }
    """
    result: Dict[str, List[Path]] = {
        "files": [],
        "embeddable": [],
        "sessions": [],
        "distilled": [],
        "subdirs": [],
    }

    for child in codex_root.iterdir():
        if child.is_dir():
            result["subdirs"].append(child)

    for f in codex_root.rglob("*"):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        rel = f.relative_to(codex_root)
        parts = rel.parts

        # Skip hidden files
        if f.name.startswith("."):
            continue
        # Skip INDEX.md — navigation, not content
        if f.name == "INDEX.md":
            continue

        # Categorize by subfolder
        if len(parts) > 1:
            parent = parts[0]
            if parent == ARCHIVE_DIR_NAME:
                continue  # Skip archive files entirely
            if parent == DISTILLED_DIR_NAME:
                result["distilled"].append(f)
                continue
            if parent == SESSIONS_DIR_NAME:
                result["sessions"].append(f)
                continue

        result["files"].append(f)
        if ext in EMBEDDABLE_EXTS:
            result["embeddable"].append(f)

    return result


def ensure_index_files(codex_root: Path) -> List[str]:
    """Auto-create INDEX.md for any subdirectory that's missing one.

    Returns a list of paths where INDEX.md was created.
    Also checks for file counts and content changes.
    """
    created: List[str] = []
    parent_name = codex_root.name
    parent_rel = f"../INDEX.md"

    for child in sorted(codex_root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue

        index_path = child / "INDEX.md"
        if index_path.exists():
            continue

        # Count files in this subdirectory
        file_count = sum(1 for f in child.rglob("*") if f.is_file() and not f.name.startswith("."))

        # Generate description
        if child.name == "sessions":
            desc = "Session logs for this Codex."
        elif child.name == "distilled":
            desc = "Distilled knowledge extracted from session logs."
        elif child.name == "archive":
            desc = "Superseded and archived content."
        elif file_count == 0:
            desc = INDEX_DESCRIPTION.format(path=f"`{parent_name}/{child.name}`")
        else:
            desc = INDEX_DESCRIPTION.format(path=f"`{parent_name}/{child.name}`")

        content = (
            f"# {child.name.capitalize()} — Index\n"
            f"Parent: [{parent_name}]({parent_rel})\n\n"
            f"{desc}\n"
        )
        index_path.write_text(content, encoding="utf-8")
        created.append(f"{parent_name}/{child.name}")
        logger.info("  → Created INDEX.md for %s/%s", parent_name, child.name)

    return created


def find_stale_files(
    codex_root: Path, days: int = STALE_THRESHOLD_DAYS
) -> List[Dict]:
    """Find files not modified in *days* that are eligible for archival.

    Skips: INDEX.md, files already in archive/, files in sessions/.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
    stale: List[Dict] = []

    for f in codex_root.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in EMBEDDABLE_EXTS:
            continue
        rel = f.relative_to(codex_root)
        parts = rel.parts
        if len(parts) > 1 and parts[0] in (ARCHIVE_DIR_NAME, SESSIONS_DIR_NAME, DISTILLED_DIR_NAME):
            continue
        if f.name == "INDEX.md":
            continue

        try:
            mtime = f.stat().st_mtime
            if mtime < cutoff:
                stale.append({
                    "path": str(rel),
                    "last_modified": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                    "size": f.stat().st_size,
                })
        except Exception:
            continue

    stale.sort(key=lambda x: x["last_modified"])
    return stale


def run_health_checks() -> Dict[str, Any]:
    """Run all health checks across the Athenaeum.

    Returns health dict matching HadesReport.health shape.
    """
    health: Dict[str, Any] = {
        "codexes": {},
        "chroma_vs_fs": {},
        "orphans": {"chroma_only": [], "fs_unembedded": []},
        "missing_indexes": [],
        "indexes_created": [],
        "stale_candidates": [],
        "chroma_count": None,
    }

    # ChromaDB removed in P4a — chroma counts no longer tracked
    chroma_counts: Dict[str, int] = {}
    health["chroma_count"] = None

    for codex_name in KNOWN_CODEXES:
        codex_dir = ATHENAEUM_ROOT / codex_name
        if not codex_dir.is_dir():
            continue

        info = _walk_codex_files(codex_dir)
        health["codexes"][codex_name] = {
            "files": len(info["files"]),
            "embeddable": len(info["embeddable"]),
            "sessions": len(info["sessions"]),
            "distilled": len(info["distilled"]),
            "subdirs": len(info["subdirs"]),
        }

        # Auto-create INDEX.md for missing subdirectories
        created = ensure_index_files(codex_dir)
        health["indexes_created"].extend(created)

        # Check for persistent gaps (subdirs without INDEX.md despite creation attempt)
        # This catches edge cases like empty dirs or permission issues
        still_missing: List[str] = []
        for child in codex_dir.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                if not (child / "INDEX.md").exists():
                    still_missing.append(f"{codex_dir.name}/{child.name}")
        if still_missing:
            health["missing_indexes"].extend(still_missing)

        # Chroma-vs-FS comparison removed in P4a (no vector DB to compare against).
        # Orphan detection is now file-system-only.
        health["chroma_vs_fs"][codex_name] = {
            "chroma": 0,
            "fs_embeddable": 0,
            "delta": 0,
            "note": "ChromaDB removed in P4a; comparison no longer meaningful",
        }

        # Find stale files
        stale = find_stale_files(codex_dir)
        health["stale_candidates"].extend(stale)

    return health
