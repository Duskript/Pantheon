"""Kronos — log pipeline service for Pantheon.

Driver: service
Writes structured JSONL log entries to Codex-Pantheon/sessions/kronos/.
One file per day, named YYYY-MM-DD.jsonl. Always appends, never overwrites.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields as dataclass_fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class LogEntry:
    timestamp: str        # ISO 8601
    level: str            # "info" | "warn" | "error"
    god: str
    event: str
    detail: Optional[str] = None


class KronosWriter:
    """Appends LogEntry records to daily JSONL files under *log_dir*."""

    def __init__(self, log_dir: str) -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def log(self, entry: LogEntry) -> None:
        """Append *entry* as a JSON line to today's log file."""
        path = self._today_path()
        line = json.dumps(asdict(entry), ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read_today(self) -> list[LogEntry]:
        """Return all entries logged today."""
        return self.read_date(self._today_str())

    def read_date(self, date: str) -> list[LogEntry]:
        """Return all entries for *date* (format: 'YYYY-MM-DD').

        Returns an empty list if no log file exists for that date.
        """
        path = self._log_dir / f"{date}.jsonl"
        if not path.exists():
            return []
        entries: list[LogEntry] = []
        with path.open("r", encoding="utf-8") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    data = json.loads(raw_line)
                    known = {f.name for f in dataclass_fields(LogEntry)}
                    filtered = {k: v for k, v in data.items() if k in known}
                    entries.append(LogEntry(**filtered))
                except (json.JSONDecodeError, TypeError, KeyError):
                    # Skip malformed or structurally invalid lines gracefully
                    continue
        return entries

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _today_str() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _today_path(self) -> Path:
        return self._log_dir / f"{self._today_str()}.jsonl"
