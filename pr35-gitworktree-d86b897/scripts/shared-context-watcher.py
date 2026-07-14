#!/usr/bin/env python3
"""
shared-context-watcher.py — Shared Context → Ichor Inotify Watcher (v3)

Replaces the */15 polling cron (`inject-shared-context.py`) with an event-driven
inotify watcher. God-agnostic, memory-layer-owned. Mirrors the demeter-watcher
pattern (`demeter-watcher.service` watches `~/Staging/inbox/`).

Why this exists:
    The shared-context → ichor ingestion was originally a Thoth-god agent cron
    (job `6bdfb04790c5`) supplemented by a system-cron fallback. When the system
    cron started writing first, the Thoth cron's dedup caught everything
    (`0 injected, 875 skipped`) and it has been burning ~1500 LLM tokens every
    15 min to do nothing for 4 days. See ~/athenaeum/Codex-God-marvin/journal/
    2026-06-11-memory-upgrade-d2-cron-teardown.md for the full history.

    This watcher takes both jobs' place. No LLM, no polling, no god dependency.

Architecture:
    systemd user service (shared-context-watcher.service)
        → python3 scripts/shared-context-watcher.py --watch
        → tries watchdog (inotify) with 500ms debounce per path
        → falls back to polling if inotify fails to bind
        → on startup, does a full scan to catch anything that changed while down
        → on each change, reads file, hashes content, writes digest_entry to
          ichor_events (source='shared-context-watcher') if hash is new

Sources watched (matches inject-shared-context.py exactly):
    DIGEST.md                 → category 'digest'
    CONTEXT_*.md              → category 'context:<user_id>'
    athenaeum-writes.md       → category 'athenaeum'
    decisions/<user_id>/*.md  → category 'decisions:<user_id>:<stem>'
    decisions/*.md            → category 'decisions:<stem>'
    active/*.md               → category 'active:<stem>'

Dedup:
    subject = f"shared:{category}:{content_hash(content)[:16]}"
    Skip if subject already exists in ichor_events.event_type='digest_entry'.

CLI:
    shared-context-watcher.py --watch    # daemon (systemd)
    shared-context-watcher.py --scan     # one-shot full scan, exit
    shared-context-watcher.py --status   # quick health (last run, db row count)

Schema written:
    event_type='digest_entry'
    subject='shared:<category>:<content_hash[:16]>'
    raw_text=file_content (truncated to 10K for large files, 2K for decisions/active)
    source='shared-context-watcher'
    god_name='thoth'  (matches existing rows so god attribution is consistent)
    importance=50.0, trust=50.0, maturity='validated'
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sqlite3
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

_HOME = Path(os.path.expanduser("~"))
SHARED_DIR = _HOME / "pantheon" / "shared"
ICHOR_DB = _HOME / ".hermes" / "ichor.db"
LOG_DIR = _HOME / "pantheon" / "logs"
LOG_FILE = LOG_DIR / "shared-context-watcher.log"

SOURCE_LABEL = "shared-context-watcher"
GOD_NAME = "thoth"

# Debounce window per path: editor saves touch files multiple times; wait for
# the dust to settle before reading and hashing.
DEBOUNCE_SECONDS = 0.5

# Polling fallback interval (only used if watchdog can't bind).
POLL_INTERVAL = 5.0

# Source-side file filter — matches inject-shared-context.py source list.
WATCHED_GLOBS = [
    ("digest", lambda d: [(d / "DIGEST.md", None)]),
    ("context", lambda d: [(p, p.stem.replace("CONTEXT_", ""))
                            for p in sorted(d.glob("CONTEXT_*.md"))]),
    ("athenaeum", lambda d: [(d / "athenaeum-writes.md", None)]),
    (
        "decisions",
        lambda d: _iter_decisions(d / "decisions"),
    ),
    (
        "active",
        lambda d: [(p, p.stem)
                    for p in sorted((d / "active").glob("*.md"))]
        if (d / "active").is_dir()
        else [],
    ),
]


def _iter_decisions(dec_dir: Path):
    """Yield (path, category_parts) for every decisions file to index.

    Mirrors inject-shared-context.py: walk <user_id>/<stem>.md AND top-level
    <stem>.md, skip INDEX.md and dotfiles, depth one.
    """
    if not dec_dir.is_dir():
        return []
    out = []
    for entry in sorted(dec_dir.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            for md in sorted(entry.iterdir()):
                if md.suffix == ".md" and md.name != "INDEX.md":
                    out.append((md, (entry.name, md.stem)))
        elif entry.suffix == ".md" and entry.name != "INDEX.md":
            out.append((entry, (entry.stem,)))
    return out


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool = False) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("shared-context-watcher")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [shared-context-watcher] %(levelname)s: %(message)s"
    )
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def _open_db() -> sqlite3.Connection:
    if not ICHOR_DB.exists():
        raise FileNotFoundError(f"Ichor DB not found at {ICHOR_DB}")
    return sqlite3.connect(str(ICHOR_DB), timeout=10.0)


def _load_existing_subjects(cursor: sqlite3.Cursor) -> set:
    """Return the set of all digest_entry subjects currently in the table.

    Same query inject-shared-context.py uses, source-agnostic. Means our
    watcher will skip any subject already written by the old cron (and vice
    versa) — collision-safe by content hash.
    """
    cursor.execute(
        "SELECT subject FROM ichor_events WHERE event_type = 'digest_entry'"
    )
    return {row[0] for row in cursor.fetchall()}


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _truncate_for(category_root: str, content: str) -> str:
    """Truncation matches the old script: 10K for top-level files, 2K for
    decisions/active (they're meant to be small summaries anyway)."""
    if category_root in ("decisions", "active"):
        return content[:2000]
    return content[:10000]


# ---------------------------------------------------------------------------
# Ingestion core
# ---------------------------------------------------------------------------


class SharedContextIngestor:
    """Indexes shared-context files into ichor_events.

    Single responsibility: given a list of (category, path), hash each,
    dedup, write new ones. Used by both --scan and the live inotify loop.
    """

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def _category_for(self, path: Path, parts) -> str:
        """Build the canonical category string for a shared-context file.

        `parts` is the same tuple yielded by the globs in WATCHED_GLOBS:
            - digest, athenaeum: (None,)      (the path is fixed)
            - context:           (uid,)        (e.g. ('konan',))
            - active:            (stem,)       (e.g. ('my-task',))
            - decisions/<u>/<s>: (uid, stem)   (e.g. ('konan', '2026-06-11-...'))
            - decisions/<s>:     (stem,)
        """
        p = parts if isinstance(parts, tuple) else (parts,)
        if not p or p[0] is None:
            # digest / athenaeum: use the root name
            if path.name == "DIGEST.md":
                return "digest"
            if path.name == "athenaeum-writes.md":
                return "athenaeum"
            return path.stem
        if path.name.startswith("CONTEXT_") and path.suffix == ".md":
            return f"context:{p[0]}"
        if path.parent.name == "active":
            return f"active:{p[0]}"
        if path.parent.name == "decisions":
            if len(p) == 2:
                return f"decisions:{p[0]}:{p[1]}"
            return f"decisions:{p[0]}"
        return p[0]

    def collect_files(self) -> list:
        """Return [(category, path, truncate_root)] for every watched file."""
        out = []
        for category_root, globs_fn in WATCHED_GLOBS:
            for path, parts in globs_fn(SHARED_DIR):
                if path.is_file():
                    cat = self._category_for(path, parts)
                    out.append((cat, path, category_root))
        return out

    def run_once(self) -> tuple:
        """One full scan. Returns (injected, skipped, errors)."""
        conn = _open_db()
        cur = conn.cursor()
        existing = _load_existing_subjects(cur)
        injected = 0
        skipped = 0
        errors = 0
        for category, path, truncate_root in self.collect_files():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                self.logger.warning("  read error: %s: %s", path, e)
                errors += 1
                continue
            ch = _content_hash(content)
            subject = f"shared:{category}:{ch}"
            if subject in existing:
                skipped += 1
                continue
            try:
                cur.execute(
                    """INSERT INTO ichor_events
                       (session_id, event_type, subject, predicate, object,
                        raw_text, created_at, god_name,
                        importance, trust, maturity, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "scw-scan",
                        "digest_entry",
                        subject,
                        category,
                        f"Shared context {category}",
                        _truncate_for(truncate_root, content),
                        _now(),
                        GOD_NAME,
                        50.0,
                        50.0,
                        "validated",
                        SOURCE_LABEL,
                    ),
                )
                injected += 1
            except sqlite3.OperationalError as e:
                self.logger.error("  write error: %s: %s", subject, e)
                errors += 1
        conn.commit()
        conn.close()
        return injected, skipped, errors

    def ingest_one(self, path: Path) -> Optional[str]:
        """Ingest a single path (called by the inotify loop). Returns the
        subject written, or None if skipped / errored."""
        if not path.is_file():
            return None
        # Restrict to watched files only. For each candidate match, compute
        # the same canonical category string that `run_once()` uses so that
        # live events and full scans produce identical subjects — that way
        # the content-hash dedup works identically whether the trigger was
        # inotify, polling, or an explicit --scan.
        for category_root, globs_fn in WATCHED_GLOBS:
            for candidate, parts in globs_fn(SHARED_DIR):
                if candidate == path:
                    cat = self._category_for(path, parts)
                    try:
                        content = path.read_text(
                            encoding="utf-8", errors="replace"
                        )
                    except OSError as e:
                        self.logger.warning("read error: %s: %s", path, e)
                        return None
                    ch = _content_hash(content)
                    subject = f"shared:{cat}:{ch}"
                    conn = _open_db()
                    cur = conn.cursor()
                    existing = _load_existing_subjects(cur)
                    if subject in existing:
                        conn.close()
                        self.logger.debug("skip (dup): %s", subject)
                        return None
                    try:
                        cur.execute(
                            """INSERT INTO ichor_events
                               (session_id, event_type, subject, predicate, object,
                                raw_text, created_at, god_name,
                                importance, trust, maturity, source)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                "scw-event",
                                "digest_entry",
                                subject,
                                cat,
                                f"Shared context {cat}",
                                _truncate_for(category_root, content),
                                _now(),
                                GOD_NAME,
                                50.0,
                                50.0,
                                "validated",
                                SOURCE_LABEL,
                            ),
                        )
                        conn.commit()
                        self.logger.info(
                            "ingested: %s (%db)",
                            subject,
                            len(content),
                        )
                        return subject
                    except sqlite3.OperationalError as e:
                        self.logger.error("write error: %s: %s", subject, e)
                        return None
                    finally:
                        conn.close()
        # Not in the watched set — silently ignore (matches old behavior).
        return None


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Watchdog path (event-driven, preferred)
# ---------------------------------------------------------------------------


def _run_watchdog(ingestor: SharedContextIngestor, logger: logging.Logger):
    """Try inotify via watchdog. Raises ImportError if not available."""
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    # Per-path debounce: collect writes, fire after DEBOUNCE_SECONDS of quiet.
    pending: dict = defaultdict(list)
    lock = threading.Lock()
    timer: dict = {}  # path -> Timer

    def fire(path: Path):
        with lock:
            pending.pop(path, None)
            timer.pop(path, None)
        try:
            ingestor.ingest_one(path)
        except Exception as e:  # noqa: BLE001 — best-effort daemon
            logger.exception("ingest_one failed for %s: %s", path, e)

    def schedule(path: Path):
        with lock:
            pending[path] = pending.get(path, 0) + 1
            old = timer.pop(path, None)
            if old:
                old.cancel()
            t = threading.Timer(DEBOUNCE_SECONDS, fire, args=(path,))
            t.daemon = True
            timer[path] = t
            t.start()

    class _Handler(FileSystemEventHandler):
        def on_created(self, event):
            if not event.is_directory:
                schedule(Path(event.src_path))

        def on_modified(self, event):
            if not event.is_directory:
                schedule(Path(event.src_path))

        def on_moved(self, event):
            # Editor save = write-temp + rename. Treat dest as a fresh create.
            if not event.is_directory:
                schedule(Path(event.dest_path))

    observer = Observer()
    observer.schedule(_Handler(), str(SHARED_DIR), recursive=True)
    observer.start()
    logger.info("watchdog observer started on %s (recursive)", SHARED_DIR)
    return observer


# ---------------------------------------------------------------------------
# Polling fallback
# ---------------------------------------------------------------------------


def _run_polling(ingestor: SharedContextIngestor, logger: logging.Logger):
    """Fallback: stat-mtime based polling, like the old cron."""
    logger.info("polling fallback started (interval=%.1fs)", POLL_INTERVAL)
    last_mtime: dict = {}
    while True:
        for _, path, _ in ingestor.collect_files():
            try:
                mt = path.stat().st_mtime
            except OSError:
                continue
            if last_mtime.get(path) != mt:
                last_mtime[path] = mt
                try:
                    ingestor.ingest_one(path)
                except Exception as e:  # noqa: BLE001
                    logger.exception("poll ingest failed for %s: %s", path, e)
        time.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--watch", action="store_true",
                      help="Run as daemon (event-driven, systemd).")
    mode.add_argument("--scan", action="store_true",
                      help="One-shot full scan, then exit.")
    mode.add_argument("--status", action="store_true",
                      help="Print health info, then exit.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logger = _setup_logging(args.verbose)
    ingestor = SharedContextIngestor(logger)

    if args.scan:
        logger.info("one-shot scan starting")
        inj, skip, err = ingestor.run_once()
        logger.info("scan complete: %d injected, %d skipped, %d errors",
                    inj, skip, err)
        return 0 if err == 0 else 1

    if args.status:
        # Quick health: total digest_entry rows + last 3 ingested by us.
        conn = _open_db()
        cur = conn.cursor()
        total = cur.execute(
            "SELECT COUNT(*) FROM ichor_events WHERE event_type='digest_entry'"
        ).fetchone()[0]
        ours = cur.execute(
            "SELECT COUNT(*) FROM ichor_events "
            "WHERE event_type='digest_entry' AND source=?",
            (SOURCE_LABEL,),
        ).fetchone()[0]
        recent = cur.execute(
            "SELECT id, created_at, subject FROM ichor_events "
            "WHERE event_type='digest_entry' AND source=? "
            "ORDER BY id DESC LIMIT 3",
            (SOURCE_LABEL,),
        ).fetchall()
        conn.close()
        print(f"total digest_entry rows: {total}")
        print(f"written by shared-context-watcher: {ours}")
        print("recent watcher writes:")
        for row in recent:
            print(f"  id={row[0]} {row[1]} {row[2]}")
        return 0

    # --watch
    logger.info("=" * 60)
    logger.info("shared-context-watcher starting")
    logger.info("  SHARED: %s", SHARED_DIR)
    logger.info("  DB:     %s", ICHOR_DB)
    logger.info("  LOG:    %s", LOG_FILE)

    # Always do an initial full scan to catch anything that changed while down.
    logger.info("running initial full scan...")
    inj, skip, err = ingestor.run_once()
    logger.info("initial scan: %d injected, %d skipped, %d errors",
                inj, skip, err)

    # Try watchdog, fall back to polling.
    observer = None
    try:
        observer = _run_watchdog(ingestor, logger)
    except ImportError:
        logger.warning("watchdog not available — using polling fallback")
        _run_polling(ingestor, logger)
        return 0

    # Keep the main thread alive (watchdog runs on its own observer thread).
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("shutting down...")
        if observer:
            observer.stop()
            observer.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
