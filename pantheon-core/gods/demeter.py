"""Demeter — file watcher and cron scheduler for Pantheon.

Driver: script

Phase 1 scope:
  - DemeterScheduler: register and run scheduled jobs (cron / "nightly" / "hourly")
  - DemeterWatcher: stub that raises NotImplementedError until watchdog is wired up

Cron schedule strings:
  - "nightly"  — once per day at 02:00 UTC
  - "hourly"   — once per hour at :00
  - cron expr  — standard 5-field cron ("0 2 * * *")
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ScheduledJob:
    name: str
    schedule: str          # "nightly", "hourly", or "M H D m W" cron expr
    target: str            # god name to dispatch to
    payload: dict[str, Any] = field(default_factory=dict)
    last_run: Optional[str] = None  # ISO 8601 of last execution


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class DemeterScheduler:
    """Simple cron-style scheduler for background Pantheon jobs."""

    # Canonical aliases
    _ALIAS_MAP: dict[str, str] = {
        "nightly": "0 2 * * *",
        "hourly": "0 * * * *",
    }

    def __init__(self) -> None:
        self._jobs: list[ScheduledJob] = []

    def register(self, job: ScheduledJob) -> None:
        """Add *job* to the scheduler."""
        self._jobs.append(job)

    def run_pending(self, now: Optional[datetime] = None) -> list[str]:
        """Check all registered jobs and run any that are due.

        Returns the names of jobs that were executed this call.

        *now* is exposed for testing; defaults to ``datetime.now(UTC)``.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        ran: list[str] = []
        for job in self._jobs:
            if self._is_due(job, now):
                job.last_run = now.isoformat()
                ran.append(job.name)
        return ran

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_schedule(self, schedule: str) -> str:
        return self._ALIAS_MAP.get(schedule, schedule)

    def _is_due(self, job: ScheduledJob, now: datetime) -> bool:
        """Return True if *job* should run at *now*.

        A job is due when the current minute matches the cron expression
        AND it has not already run during this minute.
        """
        expr = self._resolve_schedule(job.schedule)
        if not _cron_matches(expr, now):
            return False
        if job.last_run is None:
            return True
        last = datetime.fromisoformat(job.last_run)
        # Already ran this minute?
        same_minute = (
            last.year == now.year
            and last.month == now.month
            and last.day == now.day
            and last.hour == now.hour
            and last.minute == now.minute
        )
        return not same_minute


# ---------------------------------------------------------------------------
# Watcher stub
# ---------------------------------------------------------------------------


class DemeterWatcher:
    """inotify-based file watcher — Phase 1 stub.

    Full implementation requires the ``watchdog`` library (watchdog>=4.0.0).
    Will be wired up once the dependency is installed in the environment.
    """

    def watch(self, path: str, on_change: Callable[[str], None]) -> None:  # noqa: ARG002
        raise NotImplementedError(
            "inotify watcher requires watchdog — Phase 1 pending"
        )


# ---------------------------------------------------------------------------
# Cron expression helpers
# ---------------------------------------------------------------------------


def _cron_field_matches(field_str: str, value: int) -> bool:
    """Return True if *value* satisfies the single cron *field_str*."""
    if field_str == "*":
        return True
    # Step syntax: */N
    step_match = re.fullmatch(r"\*/(\d+)", field_str)
    if step_match:
        step = int(step_match.group(1))
        return value % step == 0
    # Range syntax: N-M
    range_match = re.fullmatch(r"(\d+)-(\d+)", field_str)
    if range_match:
        lo, hi = int(range_match.group(1)), int(range_match.group(2))
        return lo <= value <= hi
    # List syntax: N,M,...
    if "," in field_str:
        return value in {int(p) for p in field_str.split(",")}
    # Plain integer
    try:
        return value == int(field_str)
    except ValueError:
        return False


def _cron_matches(expr: str, dt: datetime) -> bool:
    """Return True if *dt* matches the 5-field cron expression *expr*.

    Fields: minute  hour  day-of-month  month  day-of-week
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression (expected 5 fields): {expr!r}")
    m_field, h_field, dom_field, mon_field, dow_field = parts
    return (
        _cron_field_matches(m_field, dt.minute)
        and _cron_field_matches(h_field, dt.hour)
        and _cron_field_matches(dom_field, dt.day)
        and _cron_field_matches(mon_field, dt.month)
        and _cron_field_matches(dow_field, dt.weekday())  # 0=Monday per Python
    )
