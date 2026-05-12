"""Demeter — Athenaeum file watcher and ingestion daemon.

Monitors ~/Staging/inbox/ for new files and processes them through
the ingestion pipeline. Also provides the background orchestration
for scheduled ingestion tasks.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, List, Optional

from .ingest import IngestResult, ingest_file, load_rules

logger = logging.getLogger(__name__)

_REAL_HOME = os.path.expanduser("~")

_DEFAULT_INBOX = os.environ.get(
    "ATHENAEUM_INBOX",
    f"{_REAL_HOME}/Staging/inbox",
)


class DemeterWatcher:
    """Watch ~/Staging/inbox/ for new files and auto-ingest.

    Uses watchdog if available, otherwise falls back to polling.
    """

    def __init__(
        self,
        inbox_path: Optional[str] = None,
        poll_interval: float = 5.0,
        on_ingest: Optional[Callable[[List[IngestResult]], None]] = None,
    ):
        self._inbox = Path(inbox_path or _DEFAULT_INBOX)
        self._poll_interval = poll_interval
        self._on_ingest = on_ingest
        self._rules = load_rules()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._known_files: set = set()

        # Ensure inbox exists
        self._inbox.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        """Start the watcher in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("DemeterWatcher already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="demeter-watcher")
        self._thread.start()
        logger.info("DemeterWatcher started on %s", self._inbox)

    def stop(self) -> None:
        """Stop the watcher."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10.0)
            self._thread = None
        logger.info("DemeterWatcher stopped")

    def _run(self) -> None:
        """Main loop — try watchdog, fall back to polling."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class _Handler(FileSystemEventHandler):
                def __init__(self, watcher: "DemeterWatcher"):
                    self.watcher = watcher

                def on_created(self, event):
                    if not event.is_directory:
                        self.watcher._process_file(Path(event.src_path))

                def on_modified(self, event):
                    if not event.is_directory:
                        self.watcher._process_file(Path(event.src_path))

            observer = Observer()
            observer.schedule(_Handler(self), str(self._inbox), recursive=False)
            observer.start()
            logger.info("DemeterWatcher using watchdog (event-driven)")

            while not self._stop_event.is_set():
                time.sleep(1)

            observer.stop()
            observer.join()

        except ImportError:
            logger.info("watchdog not installed — falling back to polling")
            self._poll_loop()

    def _poll_loop(self) -> None:
        """Polling fallback when watchdog is not available."""
        while not self._stop_event.is_set():
            self._scan_inbox()
            time.sleep(self._poll_interval)

    def _scan_inbox(self) -> None:
        """Check inbox for new files."""
        if not self._inbox.is_dir():
            return

        for child in self._inbox.iterdir():
            if child.is_file() and child.name.startswith("."):
                continue  # skip hidden files
            self._process_file(child)

    def _process_file(self, path: Path) -> None:
        """Process a single file from the inbox."""
        if not path.is_file():
            return

        resolved = str(path.resolve())
        if resolved in self._known_files:
            return  # already seen
        self._known_files.add(resolved)

        # Brief delay to ensure file is fully written
        time.sleep(0.5)

        logger.info("Inbox file detected: %s", path.name)
        result = ingest_file(resolved, rules=self._rules)

        if result.success:
            logger.info(
                "Ingested %s → %s [%s]",
                path.name,
                result.destination,
                result.codex,
            )
            if result.suggested_codex:
                logger.info("  → Suggested new Codex: %s", result.suggested_codex)

            # Move processed file to a 'processed' subfolder
            processed_dir = self._inbox / "processed"
            processed_dir.mkdir(exist_ok=True)
            try:
                dest = processed_dir / path.name
                path.rename(dest)
            except Exception:
                pass

            if self._on_ingest:
                self._on_ingest([result])
        else:
            logger.warning("Failed to ingest %s: %s", path.name, result.error)

    def scan_now(self) -> List[IngestResult]:
        """Force a scan of the inbox. Returns results."""
        results: List[IngestResult] = []
        if not self._inbox.is_dir():
            return results

        for child in sorted(self._inbox.iterdir()):
            if child.is_file() and not child.name.startswith("."):
                result = ingest_file(str(child), rules=self._rules)
                results.append(result)
                if result.success:
                    processed_dir = self._inbox / "processed"
                    processed_dir.mkdir(exist_ok=True)
                    try:
                        dest = processed_dir / child.name
                        child.rename(dest)
                    except Exception:
                        pass

        return results
