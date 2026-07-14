"""Hades archive phase.

Phase 4 of the pipeline. Scans the filesystem for files that meet
**archive criteria** and reports them. Does NOT move files.

Archive criteria (both must be true):
  - File is older than `STALE_THRESHOLD_DAYS` (default 90)
  - File is not registered as a node in the entity graph (graph.db)

The 3-tier archive model from the Phase 3 spec (asphodel/elysium/tartarus)
is **not implemented** here. The spec envisioned Charon as the only code
that moves files between those tiers; the spec's Charon was never built.
See `Codex-Pantheon/architecture/hades-pipeline.md` §"4-god model
status" for the full explanation of why we kept the scanner but skipped
the tiers.

The `candidates` list this returns is for human review. The morning
briefing shows the count; the report markdown lists the first 10 with
"and N more" if there are more. No file ever moves without explicit
human action — this is a deliberate safety choice to prevent data
loss from an automated policy misfire.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .paths import (
    ARCHIVE_DIR_NAME,
    ATHENAEUM_ROOT,
    DISTILLED_DIR_NAME,
    EMBEDDABLE_EXTS,
    GRAPH_DB,
    KNOWN_CODEXES,
    SESSIONS_DIR_NAME,
    STALE_THRESHOLD_DAYS,
    SYSTEM_CODEXES,
)

logger = logging.getLogger(__name__)


def run_archive() -> Dict[str, Any]:
    """Archive stale files that are not linked in the entity graph.

    A file is a candidate if:
    - Not modified in STALE_THRESHOLD_DAYS
    - Not registered as a node in the graph (or has no edges)
    - Not already in archive/ or distilled/

    Currently: reports candidates only, does NOT auto-archive.
    (Auto-archival requires explicit opt-in to avoid data loss.)
    """
    result: Dict[str, Any] = {
        "files_archived": 0,
        "candidates": [],
        "errors": [],
    }

    cutoff = datetime.now(timezone.utc).timestamp() - (STALE_THRESHOLD_DAYS * 86400)

    # Check if graph is available to consult
    graph_available = GRAPH_DB.exists()

    for codex_name in KNOWN_CODEXES:
        codex_dir = ATHENAEUM_ROOT / codex_name
        if not codex_dir.is_dir() or codex_name in SYSTEM_CODEXES:
            continue

        for f in codex_dir.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in EMBEDDABLE_EXTS:
                continue
            rel = f.relative_to(ATHENAEUM_ROOT)
            parts = rel.parts
            if len(parts) > 1 and parts[1] in (ARCHIVE_DIR_NAME, DISTILLED_DIR_NAME, SESSIONS_DIR_NAME):
                continue
            if f.name == "INDEX.md":
                continue

            try:
                mtime = f.stat().st_mtime
            except Exception:
                continue

            is_stale = mtime < cutoff

            # If graph is available, check if the file is linked
            is_linked = False
            if graph_available:
                try:
                    conn = sqlite3.connect(str(GRAPH_DB))
                    c = conn.execute(
                        "SELECT id FROM nodes WHERE id = ?",
                        (f"file:{str(rel)}",),
                    )
                    if c.fetchone():
                        is_linked = True
                    conn.close()
                except Exception:
                    pass

            if is_stale and not is_linked:
                result["candidates"].append({
                    "path": str(rel),
                    "codex": codex_name,
                    "last_modified": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                    "size": f.stat().st_size,
                })

    # Sort by last_modified (oldest first)
    result["candidates"].sort(key=lambda x: x["last_modified"])

    return result
