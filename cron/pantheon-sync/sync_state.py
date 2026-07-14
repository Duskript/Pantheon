"""
SyncState — tracks sync progress per connection.

Tracks: last_sync, cursor, records_today, daily budget, and date-reset logic.
Thread-safe enough for single-threaded cron use.
"""

import json
import os
from datetime import date, datetime
from typing import Any, Dict, Optional


class SyncState:
    """Per-connection sync state with daily budget reset.

    Persisted to a JSON file so state survives between cron ticks.
    """

    def __init__(self, state_file: Optional[str] = None):
        self.state_file = state_file or os.path.expanduser(
            "~/.hermes/cron/pantheon-sync/sync_state.json"
        )
        self.states: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self):
        """Load state from disk if it exists."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file) as f:
                    self.states = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.states = {}

    def _save(self):
        """Persist state to disk atomically via temp file."""
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        tmp = self.state_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.states, f, indent=2, default=str)
        os.replace(tmp, self.state_file)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, connection_id: str) -> dict:
        """Get state for a connection, seeding defaults on first access."""
        if connection_id not in self.states:
            self.states[connection_id] = {
                "last_sync": None,
                "cursor": None,
                "records_today": 0,
                "daily_budget": 1000,
                "last_reset_date": str(date.today()),
            }
        return self.states[connection_id]

    def record_sync(
        self,
        connection_id: str,
        records_synced: int = 0,
        cursor: Any = None,
    ):
        """Record a completed sync tick for *connection_id*."""
        state = self.get(connection_id)
        state["last_sync"] = datetime.now().isoformat()
        state["records_today"] += records_synced
        if cursor is not None:
            state["cursor"] = cursor
        self._save()

    def record_error(self, connection_id: str, error: str):
        """Log an error against a connection without updating last_sync."""
        # errors are logged to scan.log by the scheduler; this is a
        # convenience if callers want state-level error tracking later.
        state = self.get(connection_id)
        state.setdefault("last_error", None)
        state["last_error"] = error
        state["last_error_at"] = datetime.now().isoformat()
        self._save()

    # ------------------------------------------------------------------
    # Daily budget
    # ------------------------------------------------------------------

    def reset_daily_if_needed(self, connection_id: str):
        """Zero out *records_today* if the date has rolled over."""
        state = self.get(connection_id)
        today = str(date.today())
        if state.get("last_reset_date") != today:
            state["records_today"] = 0
            state["last_reset_date"] = today
            self._save()

    def set_daily_budget(self, connection_id: str, budget: int):
        """Override the daily budget for a connection (from connections.json)."""
        state = self.get(connection_id)
        state["daily_budget"] = budget
        self._save()

    def is_over_budget(self, connection_id: str) -> bool:
        """True when today's records have hit the daily cap."""
        state = self.get(connection_id)
        return state["records_today"] >= state.get("daily_budget", 1000)

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def is_due(
        self, connection_id: str, min_interval_minutes: int = 20
    ) -> bool:
        """Has enough wall-clock time elapsed since the last sync?"""
        state = self.get(connection_id)
        last = state["last_sync"]
        if last is None:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
            elapsed_min = (datetime.now() - last_dt).total_seconds() / 60.0
            return elapsed_min >= min_interval_minutes
        except (ValueError, TypeError, OSError):
            return True  # corrupt timestamp → sync now to repair state
