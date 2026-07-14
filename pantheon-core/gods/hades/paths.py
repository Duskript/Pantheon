"""Hades paths and constants.

Single source of truth for filesystem locations. Brittleness fix #2
(2026-06-03): replaced hardcoded `os.path.expanduser("~konan")` with an
env-var override + standard `~` fallback. This means the pipeline now
works on any machine that sets `HADES_HOME`, and on this one without
relying on a hardcoded username.
"""

from __future__ import annotations

import os
from pathlib import Path

# Brittleness fix #2: env-overridable home.
# `HADES_HOME` lets you point the pipeline at a different athenaeum for
# staging, testing, or running on a machine where the user isn't `konan`.
# Default keeps the prior behavior (uses `~` for the real home).
REAL_HOME: str = os.environ.get("HADES_HOME") or os.path.expanduser("~")

ATHENAEUM_ROOT: Path = Path(f"{REAL_HOME}/athenaeum")
CHROMA_DIR: Path = Path(f"{REAL_HOME}/.hermes/pantheon/chroma")
GRAPH_DB: Path = Path(f"{REAL_HOME}/.hermes/pantheon/graph.db")
SUGGEST_FILE: Path = Path(f"{REAL_HOME}/.hermes/pantheon/suggested-codexes.json")
HERMES_INBOX: Path = Path(f"{REAL_HOME}/pantheon/gods/messages/hermes")

# Brittleness fix #4: per-phase resumable state file. Hades writes here
# after each phase completes; on startup, completed phases are skipped.
# The file is best-effort — if it's missing or malformed, the run starts
# from scratch (fail-open, not fail-closed).
HADES_STATE_FILE: Path = Path(f"{REAL_HOME}/.hermes/pantheon/hades-state.json")

# Brittleness fix #5: notif-cron decoupled from main cron. The notif
# at 9:15am checks for this file before declaring "all good" — if it's
# older than 24h, the notif should alert instead of rubber-stamping.
HADES_LAST_SUCCESS: Path = Path(f"{REAL_HOME}/.hermes/pantheon/hades-last-success.json")

INDEX_DESCRIPTION: str = (
    "Content in `{path}` is managed by Demeter and Mnemosyne.\n"
    "Files are auto-detected and embedded into the vector store on change."
)

# Files older than this (in days) are archive candidates if not linked in the graph
STALE_THRESHOLD_DAYS: int = 90

# Codex exclusion list — system codices we don't auto-archive or auto-distill
SYSTEM_CODEXES: set[str] = {"Codex-Pantheon"}

KNOWN_CODEXES: list[str] = [
    "Codex-Forge", "Codex-Pantheon", "Codex-Infrastructure",
    "Codex-SKC", "Codex-Fiction", "Codex-Asclepius", "Codex-General",
]

EMBEDDABLE_EXTS: set[str] = {".md", ".txt", ".json", ".yaml", ".yml"}
DISTILLED_DIR_NAME: str = "distilled"
ARCHIVE_DIR_NAME: str = "archive"
SESSIONS_DIR_NAME: str = "sessions"
