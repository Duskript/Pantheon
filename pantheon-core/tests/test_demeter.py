"""Tests for gods/demeter.py — DemeterScheduler and DemeterWatcher."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gods.demeter import DemeterScheduler, DemeterWatcher, ScheduledJob


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job(
    name: str = "test-job",
    schedule: str = "* * * * *",  # matches every minute
    target: str = "hades",
    payload: dict | None = None,
) -> ScheduledJob:
    return ScheduledJob(
        name=name,
        schedule=schedule,
        target=target,
        payload=payload or {},
    )


def _now() -> datetime:
    return datetime(2026, 4, 19, 2, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# DemeterScheduler.register()
# ---------------------------------------------------------------------------


class TestRegister:
    def test_register_adds_job(self):
        sched = DemeterScheduler()
        job = _job()
        sched.register(job)
        assert job in sched._jobs

    def test_register_multiple_jobs(self):
        sched = DemeterScheduler()
        jobs = [_job(name=f"job-{i}") for i in range(4)]
        for j in jobs:
            sched.register(j)
        assert len(sched._jobs) == 4

    def test_empty_on_init(self):
        sched = DemeterScheduler()
        assert sched._jobs == []


# ---------------------------------------------------------------------------
# DemeterScheduler.run_pending()
# ---------------------------------------------------------------------------


class TestRunPending:
    def test_returns_empty_when_no_jobs(self):
        sched = DemeterScheduler()
        assert sched.run_pending(now=_now()) == []

    def test_runs_matching_job(self):
        sched = DemeterScheduler()
        sched.register(_job(name="always", schedule="* * * * *"))
        ran = sched.run_pending(now=_now())
        assert ran == ["always"]

    def test_does_not_run_non_matching_job(self):
        sched = DemeterScheduler()
        # schedule: minute=30, but _now() is at minute=0
        sched.register(_job(name="half-hour", schedule="30 * * * *"))
        ran = sched.run_pending(now=_now())
        assert ran == []

    def test_updates_last_run(self):
        sched = DemeterScheduler()
        job = _job(schedule="* * * * *")
        sched.register(job)
        now = _now()
        sched.run_pending(now=now)
        assert job.last_run == now.isoformat()

    def test_does_not_rerun_same_minute(self):
        sched = DemeterScheduler()
        job = _job(schedule="* * * * *")
        sched.register(job)
        now = _now()
        sched.run_pending(now=now)
        # Second call at exact same minute — should not run again
        ran = sched.run_pending(now=now)
        assert ran == []

    def test_reruns_on_next_minute(self):
        sched = DemeterScheduler()
        job = _job(schedule="* * * * *")
        sched.register(job)
        t1 = _now()
        sched.run_pending(now=t1)
        t2 = datetime(2026, 4, 19, 2, 1, 0, tzinfo=timezone.utc)
        ran = sched.run_pending(now=t2)
        assert "test-job" in ran

    def test_runs_multiple_due_jobs(self):
        sched = DemeterScheduler()
        sched.register(_job(name="job-a", schedule="* * * * *"))
        sched.register(_job(name="job-b", schedule="* * * * *"))
        ran = sched.run_pending(now=_now())
        assert set(ran) == {"job-a", "job-b"}

    def test_partial_run_only_due_jobs(self):
        sched = DemeterScheduler()
        sched.register(_job(name="always", schedule="* * * * *"))
        sched.register(_job(name="never-now", schedule="59 23 * * *"))
        ran = sched.run_pending(now=_now())
        assert ran == ["always"]

    # Alias tests

    def test_nightly_alias_matches_0200(self):
        sched = DemeterScheduler()
        sched.register(_job(name="nightly-job", schedule="nightly"))
        # _now() is 02:00 UTC — nightly maps to "0 2 * * *"
        ran = sched.run_pending(now=_now())
        assert "nightly-job" in ran

    def test_nightly_alias_does_not_match_0300(self):
        sched = DemeterScheduler()
        sched.register(_job(name="nightly-job", schedule="nightly"))
        t = datetime(2026, 4, 19, 3, 0, 0, tzinfo=timezone.utc)
        ran = sched.run_pending(now=t)
        assert ran == []

    def test_hourly_alias_matches_top_of_hour(self):
        sched = DemeterScheduler()
        sched.register(_job(name="hourly-job", schedule="hourly"))
        ran = sched.run_pending(now=_now())
        assert "hourly-job" in ran

    def test_hourly_alias_does_not_match_mid_hour(self):
        sched = DemeterScheduler()
        sched.register(_job(name="hourly-job", schedule="hourly"))
        t = datetime(2026, 4, 19, 2, 15, 0, tzinfo=timezone.utc)
        ran = sched.run_pending(now=t)
        assert ran == []


# ---------------------------------------------------------------------------
# DemeterWatcher
# ---------------------------------------------------------------------------


class TestDemeterWatcher:
    def test_watch_raises_not_implemented(self):
        watcher = DemeterWatcher()
        with pytest.raises(NotImplementedError, match="watchdog"):
            watcher.watch("/some/path", lambda p: None)

    def test_watch_message_mentions_phase(self):
        watcher = DemeterWatcher()
        with pytest.raises(NotImplementedError) as exc_info:
            watcher.watch("/some/path", lambda p: None)
        assert "Phase 1" in str(exc_info.value)
