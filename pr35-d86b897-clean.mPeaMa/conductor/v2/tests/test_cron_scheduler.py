"""Tests for the CronScheduler — Phase 2 REWORK #1, Step 2.3 unit.

What we cover here:
  - Rule scanning: only `event_type: schedule.cron` rules with an
    `expression` get scheduled.
  - Edge cases: missing expression (warning), malformed expression
    (error, no crash), non-string expression (error).
  - Real croniter math: the production `0 7 * * 1-5` rule fires at
    7:00am MT on a Monday, and rolls forward to Monday from Saturday.
  - Event payload shape: type, source, subject, payload keys all match
    the spec.
  - Lifecycle: start()/stop() cleanly cancels the background task.

These are unit tests — they do NOT spin up the full ConductorService.
For that, see test_cron_e2e.py (slow, marked with @pytest.mark.slow).

Run: PYTHONPATH=/home/konan/pantheon PANTHEON_ROOT=/home/konan/pantheon \\
     pytest conductor/v2/tests/test_cron_scheduler.py -v
"""

from __future__ import annotations

import asyncio
import logging
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Match the v2 test pattern: insert the tests dir so a bare
# `import fixtures` works, and let fixtures.py add the conductor/ dir
# to sys.path via its own sys.path.insert(0, str(CONDUCTOR_ROOT)).
sys.path.insert(0, str(Path(__file__).parent))
import fixtures as cf  # noqa: E402

from v2 import engine as eng  # noqa: E402
from v2.cron_scheduler import CronScheduler, DEFAULT_TICK_INTERVAL  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_rule(tmp: cf.TmpConductor, name: str, *, when: dict, then: dict | None = None) -> Path:
    """Write a single rule YAML into the tmp rules dir."""
    import yaml

    then = then or {"dispatch_workflow": "noop"}
    body = {"rules": [{"id": name, "when": when, "then": then}]}
    path = tmp.rules_dir / f"{name}.yaml"
    path.write_text(yaml.safe_dump(body, sort_keys=False))
    return path


def _make_mock_engine() -> MagicMock:
    """Return a MagicMock that quacks like ConductorEngine for the
    scheduler's purposes — async handle_event, list_active. We don't
    load real rules/workflows."""
    eng_mock = MagicMock(spec=eng.ConductorEngine)
    eng_mock.handle_event = AsyncMock(
        return_value={"status": "no_action", "rule": "?"}
    )
    eng_mock.list_active = MagicMock(return_value=[])
    return eng_mock


# ---------------------------------------------------------------------------
# 1. Rule scanning
# ---------------------------------------------------------------------------

class TestCronSchedulerScanning(unittest.TestCase):
    """The scheduler's scanner must pick up only the right rules."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.rules = eng.RuleEngine(self.tmp.rules_dir)
        self.engine = _make_mock_engine()
        self.scheduler = CronScheduler(
            engine=self.engine,
            rules=self.rules,
            tick_interval=1.0,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_scanner_finds_single_schedule_cron_rule(self):
        _write_rule(
            self.tmp, "r1",
            when={"event_type": "schedule.cron", "expression": "* * * * *"},
        )
        # Reload rules from disk (RuleEngine reads at __init__).
        self.rules = eng.RuleEngine(self.tmp.rules_dir)
        self.scheduler.rules = self.rules
        sched = self.scheduler._scan_rules()
        self.assertEqual(len(sched), 1)
        nxt, rule_id, expr = sched[0]
        self.assertEqual(rule_id, "r1")
        self.assertEqual(expr, "* * * * *")
        # Next fire must be in the future (croniter returns a datetime
        # strictly > now). The croniter-returned datetime is timezone-
        # aware (UTC), so compare against the same.
        now = datetime.now(timezone.utc)
        self.assertGreater(nxt, now, f"next fire {nxt} not after now {now}")

    def test_scanner_skips_non_cron_rules(self):
        _write_rule(
            self.tmp, "webhook-rule",
            when={"event_type": "webhook", "subject": "foo"},
            then={"dispatch_god": "hermes", "message": "hi"},
        )
        self.rules = eng.RuleEngine(self.tmp.rules_dir)
        self.scheduler.rules = self.rules
        sched = self.scheduler._scan_rules()
        self.assertEqual(sched, [])

    def test_scanner_warns_on_missing_expression(self):
        _write_rule(
            self.tmp, "broken",
            when={"event_type": "schedule.cron"},  # no expression
        )
        self.rules = eng.RuleEngine(self.tmp.rules_dir)
        self.scheduler.rules = self.rules
        with self.assertLogs("conductor.v2.cron_scheduler", level=logging.WARNING) as cm:
            sched = self.scheduler._scan_rules()
        self.assertEqual(sched, [])
        self.assertTrue(
            any("missing 'expression'" in m for m in cm.output),
            f"expected missing-expression warning, got: {cm.output}",
        )

    def test_scanner_errors_on_malformed_expression(self):
        _write_rule(
            self.tmp, "bad-expr",
            when={"event_type": "schedule.cron", "expression": "this is not cron"},
        )
        self.rules = eng.RuleEngine(self.tmp.rules_dir)
        self.scheduler.rules = self.rules
        with self.assertLogs("conductor.v2.cron_scheduler", level=logging.ERROR) as cm:
            sched = self.scheduler._scan_rules()
        # The scheduler MUST NOT crash. The bad rule is just skipped.
        self.assertEqual(sched, [])
        self.assertTrue(
            any("malformed expression" in m for m in cm.output),
            f"expected malformed-expression error, got: {cm.output}",
        )

    def test_scanner_errors_on_non_string_expression(self):
        _write_rule(
            self.tmp, "weird-expr",
            when={"event_type": "schedule.cron", "expression": 42},  # int, not str
        )
        self.rules = eng.RuleEngine(self.tmp.rules_dir)
        self.scheduler.rules = self.rules
        with self.assertLogs("conductor.v2.cron_scheduler", level=logging.ERROR) as cm:
            sched = self.scheduler._scan_rules()
        self.assertEqual(sched, [])
        self.assertTrue(
            any("must be a string" in m for m in cm.output),
            f"expected type error, got: {cm.output}",
        )

    def test_scanner_finds_multiple_cron_rules_sorted_by_next_fire(self):
        # "* * * * *" and "*/5 * * * *" — both fire within a minute.
        # Sort order: whichever croniter computes as earlier first.
        _write_rule(
            self.tmp, "every-minute",
            when={"event_type": "schedule.cron", "expression": "* * * * *"},
        )
        _write_rule(
            self.tmp, "every-5",
            when={"event_type": "schedule.cron", "expression": "*/5 * * * *"},
        )
        self.rules = eng.RuleEngine(self.tmp.rules_dir)
        self.scheduler.rules = self.rules
        sched = self.scheduler._scan_rules()
        self.assertEqual(len(sched), 2)
        # Sorted ascending by next_fire_time.
        self.assertLessEqual(sched[0][0], sched[1][0])


# ---------------------------------------------------------------------------
# 2. croniter math — the real production rule
# ---------------------------------------------------------------------------

class TestCronExpressionMath(unittest.TestCase):
    """Direct croniter tests for the production rule shape `0 7 * * 1-5`.

    This is what the daily-morning-briefing rule uses. We assert it
    behaves as a human operator would expect:
      - Monday 6:59 AM MT → fires at 7:00 AM MT same day
      - Saturday 6:59 AM MT → rolls forward to Monday 7:00 AM MT
    """

    def test_monday_pre_7am_fires_at_7am_same_day(self):
        from croniter import croniter
        from zoneinfo import ZoneInfo

        mt = ZoneInfo("America/Denver")
        # Pick a Monday at 6:59 AM MT — the production rule must
        # fire at 7:00 AM MT on the same Monday.
        mon_659 = datetime(2026, 6, 15, 6, 59, 0, tzinfo=mt)
        nxt = croniter("0 7 * * 1-5", mon_659).get_next(datetime)
        nxt_mt = nxt.astimezone(mt)
        self.assertEqual(nxt_mt.year, 2026)
        self.assertEqual(nxt_mt.month, 6)
        self.assertEqual(nxt_mt.day, 15, "should fire same day, not next day")
        self.assertEqual(nxt_mt.hour, 7)
        self.assertEqual(nxt_mt.minute, 0)

    def test_saturday_pre_7am_rolls_forward_to_monday(self):
        from croniter import croniter
        from zoneinfo import ZoneInfo

        mt = ZoneInfo("America/Denver")
        # 2026-06-20 is a Saturday (verifiable: June 15 2026 is Monday,
        # so +5 days = Saturday). At 6:59 AM MT the rule must skip
        # Sunday and Monday's window and land on Monday 7:00 AM MT.
        sat_659 = datetime(2026, 6, 20, 6, 59, 0, tzinfo=mt)
        nxt = croniter("0 7 * * 1-5", sat_659).get_next(datetime)
        nxt_mt = nxt.astimezone(mt)
        # 2026-06-22 is the Monday after the 2026-06-20 Saturday.
        self.assertEqual(nxt_mt.year, 2026)
        self.assertEqual(nxt_mt.month, 6)
        self.assertEqual(nxt_mt.day, 22, "should roll forward to Monday")
        self.assertEqual(nxt_mt.hour, 7)
        self.assertEqual(nxt_mt.minute, 0)
        # And it must be a Monday: weekday() == 0 in Python.
        self.assertEqual(nxt_mt.weekday(), 0)


# ---------------------------------------------------------------------------
# 3. Event payload shape
# ---------------------------------------------------------------------------

class TestCronEventShape(unittest.TestCase):
    """The Event the scheduler hands to engine.handle_event must match
    the spec (engine.py:151)."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.rules = eng.RuleEngine(self.tmp.rules_dir)
        self.engine = _make_mock_engine()
        self.scheduler = CronScheduler(
            engine=self.engine, rules=self.rules, tick_interval=1.0,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_make_event_has_required_fields(self):
        from datetime import datetime as _dt, timezone as _tz
        now = _dt(2026, 6, 15, 13, 0, 0, tzinfo=_tz.utc)  # 7am MT
        ev = self.scheduler._make_event("daily-morning-briefing", "0 7 * * 1-5", now)
        self.assertEqual(ev.type, "schedule.cron")
        self.assertEqual(ev.source, "cron")
        self.assertIsNone(ev.target)
        self.assertEqual(ev.subject, "daily-morning-briefing")
        self.assertTrue(ev.is_external, "schedule.cron events are external")
        # Payload
        self.assertEqual(ev.payload["rule_id"], "daily-morning-briefing")
        self.assertEqual(ev.payload["expression"], "0 7 * * 1-5")
        self.assertIn("fired_at", ev.payload)
        # fired_at should be ISO-8601 with Z suffix
        self.assertTrue(ev.payload["fired_at"].endswith("Z"))


# ---------------------------------------------------------------------------
# 4. Lifecycle: start/stop
# ---------------------------------------------------------------------------

class TestCronSchedulerLifecycle(unittest.TestCase):
    """Start the loop in a real event loop, wait one tick, then stop."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        # A rule that fires every minute. To keep the test fast we
        # compute the real next-fire time via croniter and wait until
        # just past it. This way the test always finishes in <= ~70s
        # regardless of when the test starts within a minute.
        _write_rule(
            self.tmp, "tick-test",
            when={"event_type": "schedule.cron", "expression": "* * * * *"},
        )
        self.rules = eng.RuleEngine(self.tmp.rules_dir)
        self.engine = _make_mock_engine()
        self.stop_event = asyncio.Event()
        self.scheduler = CronScheduler(
            engine=self.engine, rules=self.rules,
            tick_interval=0.1, stop_event=self.stop_event,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_runs_loop_and_fires_one_event_then_stops(self):
        from croniter import croniter
        from datetime import datetime as _dt, timezone as _tz

        async def go():
            self.scheduler.start()
            # Compute the actual next fire time for "* * * * *" so we
            # know exactly when to stop waiting. Worst case: ~60s
            # from now, but typically 0-30s.
            now = _dt.now(_tz.utc)
            nxt = croniter("* * * * *", now).get_next(_dt)
            # Wait until we're at least 1.5s past the next fire time
            # so the scheduler has had two ticks to emit it.
            deadline = (nxt - now).total_seconds() + 1.5
            # Cap the wait at 70s so the test can't hang on edge cases.
            deadline = min(deadline, 70.0)
            await asyncio.sleep(deadline)
            # Now stop.
            self.stop_event.set()
            await self.scheduler.stop()
            return self.scheduler.fired_count

        count = asyncio.run(go())
        self.assertGreaterEqual(count, 1, "expected at least one cron fire")
        # The engine should have been called the same number of times.
        self.assertEqual(self.engine.handle_event.await_count, count)
        # Each handle_event call got a schedule.cron event.
        for call in self.engine.handle_event.call_args_list:
            ev = call.args[0]
            self.assertEqual(ev.type, "schedule.cron")
            self.assertEqual(ev.source, "cron")
            self.assertEqual(ev.subject, "tick-test")

    def test_start_is_idempotent(self):
        async def go():
            t1 = self.scheduler.start()
            t2 = self.scheduler.start()
            self.assertIs(t1, t2, "second start() should return same task")
            self.stop_event.set()
            await self.scheduler.stop()

        asyncio.run(go())

    def test_stop_cancels_task(self):
        async def go():
            self.scheduler.start()
            await asyncio.sleep(0.05)  # let it tick at least once
            self.stop_event.set()
            await self.scheduler.stop()
            # Task should be None after stop.
            self.assertIsNone(self.scheduler._task)

        asyncio.run(go())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
