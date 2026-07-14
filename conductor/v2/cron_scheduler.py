"""Conductor v2 cron scheduler — emits schedule.cron events on cron timers.

Phase 2 REWORK #1, Step 2.1. Wires a third background task into
`ConductorService.start()` alongside the file-watcher. The scheduler:

  1. Scans `rules._rules` for `when.event_type == "schedule.cron"` AND
     `when.expression` (5-field cron string).
  2. Maintains a sorted list of (next_fire_time, rule_id, expression) tuples.
  3. Every `tick_interval` seconds, fires any rule whose `next_fire_time`
     is <= now by emitting an `Event(type="schedule.cron", ...)` and calling
     `engine.handle_event(event)`. Then recomputes the next fire time.
  4. On stop, cancels the task cleanly via the parent stop_event.

Uses `croniter` (already in the venv; 6.0.0 at time of writing). Falls back
to a clear error log if a rule has a malformed expression — does NOT crash
the daemon.

Out of scope for this pass: the `condition:` clause on rules
(e.g. `condition: pending_deploys > 0` on `friday-deploy-reminder`).
The `_match_condition` engine helper supports simple `key == value` checks
but does not evaluate arithmetic expressions; if a rule's condition
doesn't evaluate, the rule simply won't match the fired event. That
limitation is tracked separately.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from croniter import croniter

if TYPE_CHECKING:
    from .engine import ConductorEngine, Event, RuleEngine


LOG = logging.getLogger("conductor.v2.cron_scheduler")


# Default tick — matches the spec ("every 30s, check the list"). Override
# in tests via the constructor to run fast (1s for E2E).
DEFAULT_TICK_INTERVAL = 30.0


class CronScheduler:
    """Background asyncio task that fires cron-scheduled events.

    Parameters
    ----------
    engine
        The ConductorEngine to call `handle_event()` on. Must be already
        constructed (the scheduler doesn't own its lifecycle).
    rules
        The RuleEngine whose rules we scan for `event_type: schedule.cron`.
        Passed in as a reference — the scheduler does NOT mutate it. On
        each fire we re-scan the live rule list, so adding a new rule at
        runtime would be picked up on the next tick (not just at init).
    tick_interval
        Seconds between ticks. 30s for prod, 1s for tests. Default 30s.
    stop_event
        An asyncio.Event shared with the service's other background tasks.
        Setting it causes the loop to exit cleanly on the next tick.
    """

    def __init__(
        self,
        engine: "ConductorEngine",
        rules: "RuleEngine",
        *,
        tick_interval: float = DEFAULT_TICK_INTERVAL,
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        self.engine = engine
        self.rules = rules
        self.tick_interval = tick_interval
        # If no stop_event passed, the run() loop will create one for
        # internal use. In production the service passes its own event
        # so all background tasks die together.
        self._external_stop_event = stop_event
        self._internal_stop_event: Optional[asyncio.Event] = None
        self._task: Optional[asyncio.Task] = None
        # Internal book-keeping (mostly for tests):
        #   - fired_count: how many events we've emitted total
        #   - last_fires: per-rule_id list of the most recent N fire times
        #   - last_event: the most recent Event we constructed (for assertions)
        self.fired_count: int = 0
        self.last_fires: dict[str, list[str]] = {}
        self.last_event: Optional["Event"] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> asyncio.Task:
        """Spawn the background task. Idempotent — calling twice returns
        the same task."""
        if self._task and not self._task.done():
            return self._task
        self._task = asyncio.create_task(self.run(), name="conductor.cron-scheduler")
        return self._task

    async def stop(self) -> None:
        """Cancel the background task and wait for it to die."""
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None

    # ------------------------------------------------------------------
    # Schedule management
    # ------------------------------------------------------------------

    def _scan_rules(self) -> list[tuple[datetime, str, str]]:
        """Return the sorted list of (next_fire_time, rule_id, expression)
        for every rule with `event_type: schedule.cron` AND an `expression`.

        Rules without an expression are skipped with a warning (they're
        malformed for cron — they need a fire trigger we don't have).
        Rules with a malformed expression are skipped with an error and
        do NOT crash the scheduler.
        """
        now = datetime.now(timezone.utc)
        out: list[tuple[datetime, str, str]] = []
        for rule in self.rules._rules:
            when = rule.when or {}
            if when.get("event_type") != "schedule.cron":
                continue
            expr = when.get("expression")
            if not expr:
                LOG.warning(
                    f"cron rule {rule.id!r}: missing 'expression' — skipping "
                    f"(event_type is schedule.cron but no cron string)"
                )
                continue
            if not isinstance(expr, str):
                LOG.error(
                    f"cron rule {rule.id!r}: 'expression' must be a string, "
                    f"got {type(expr).__name__} — skipping"
                )
                continue
            try:
                itr = croniter(expr, now)
                nxt = itr.get_next(datetime)
            except (ValueError, KeyError) as e:
                # croniter raises ValueError for bad fields, KeyError for
                # unknown aliases (e.g. "@reboot" which has no next time).
                LOG.error(
                    f"cron rule {rule.id!r}: malformed expression {expr!r} "
                    f"({e}) — skipping"
                )
                continue
            except Exception as e:
                # Catch-all so a bug in croniter or an unsupported
                # expression type doesn't take the daemon down.
                LOG.error(
                    f"cron rule {rule.id!r}: unexpected error parsing "
                    f"{expr!r} ({type(e).__name__}: {e}) — skipping"
                )
                continue
            out.append((nxt, rule.id, expr))
        # Sort by next_fire_time so the earliest is at the head. Ties
        # broken by rule_id for determinism in tests.
        out.sort(key=lambda t: (t[0], t[1]))
        return out

    def _make_event(self, rule_id: str, expression: str, fired_at: datetime) -> "Event":
        """Build the schedule.cron Event that gets handed to handle_event."""
        # Local import to avoid a circular dependency at module load —
        # engine imports nothing from us, so this is fine.
        from .engine import Event
        return Event(
            type="schedule.cron",
            source="cron",
            target=None,
            subject=rule_id,
            payload={
                "rule_id": rule_id,
                "expression": expression,
                "fired_at": fired_at.isoformat().replace("+00:00", "Z"),
            },
            is_external=True,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main scheduler loop. Runs until the stop_event is set or the
        task is cancelled.

        Why we cache `next_fire` per rule (NOT just rescan-and-check
        every tick):

          croniter("...", now).get_next() always returns the *next*
          fire boundary strictly after `now`. If our tick interval
          is shorter than the cron period (e.g. tick=0.1s, rule=
          "* * * * *"), the scheduler can MISS a fire: it scans
          at T-1s, sees the next fire is T+0s in the future, sleeps,
          wakes at T+0.1s, re-scans — and now the scanner computes
          the next fire as T+60s, never firing T+0s.

          To avoid that, we keep a per-rule `next_fire` in a dict.
          We only rescan the rule LIST (for new/removed rules); for
          rules we already know about we re-anchor the next fire
          relative to the just-fired time, not the current wall
          clock, so we always fire every boundary.

        Lifecycle per tick:
          1. Snapshot the rule list (current rules + their expressions).
          2. For any rule in our cache that was REMOVED from the
             snapshot, drop it from the cache.
          3. For any NEW rule in the snapshot (or on first run),
             compute its first next_fire and add it to the cache.
          4. For each cached (rule_id, next_fire, expression):
               - If next_fire > now: skip (not due yet)
               - Else: build the Event, await engine.handle_event,
                 then re-anchor next_fire = croniter(expr, next_fire).get_next().
                 This catches up if multiple ticks were missed.
          5. Sleep `tick_interval` (or until stop_event is set).
        """
        # Bind the stop event for the lifetime of this task.
        if self._external_stop_event is not None:
            stop_event = self._external_stop_event
        else:
            self._internal_stop_event = asyncio.Event()
            stop_event = self._internal_stop_event

        # Per-rule cache: rule_id -> {expression, next_fire}. We use a
        # small dict; the iteration order doesn't matter because we
        # sort by next_fire before firing.
        cache: dict[str, dict[str, Any]] = {}

        LOG.info(
            f"cron scheduler starting: tick_interval={self.tick_interval}s, "
            f"rules_scanned={len(self.rules._rules)}"
        )
        try:
            while not stop_event.is_set():
                now = datetime.now(timezone.utc)
                # Step 1: snapshot the live rule list.
                live_expressions: dict[str, str] = {}
                for rule in self.rules._rules:
                    when = rule.when or {}
                    if when.get("event_type") != "schedule.cron":
                        continue
                    expr = when.get("expression")
                    if not isinstance(expr, str):
                        # The scanner logs the warning/error already;
                        # we just skip silently here.
                        continue
                    try:
                        croniter(expr, now)  # validate
                    except Exception:
                        continue
                    live_expressions[rule.id] = expr

                # Step 2: drop rules that disappeared from the snapshot.
                for stale_id in [k for k in cache if k not in live_expressions]:
                    LOG.info(f"cron: dropping removed rule {stale_id!r}")
                    cache.pop(stale_id, None)

                # Step 3: add new rules with their first next_fire.
                for rid, expr in live_expressions.items():
                    if rid in cache:
                        # Update the expression if it changed on disk
                        # (e.g. operator edited the cron string).
                        if cache[rid]["expression"] != expr:
                            LOG.info(
                                f"cron: rule {rid!r} expression changed "
                                f"{cache[rid]['expression']!r} -> {expr!r}, "
                                f"re-anchoring"
                            )
                            cache[rid] = {
                                "expression": expr,
                                "next_fire": croniter(expr, now).get_next(datetime),
                            }
                        continue
                    try:
                        first = croniter(expr, now).get_next(datetime)
                    except Exception as e:
                        LOG.error(
                            f"cron: rule {rid!r} expression {expr!r} "
                            f"failed at init ({e}) — skipping"
                        )
                        continue
                    cache[rid] = {"expression": expr, "next_fire": first}
                    LOG.info(
                        f"cron: scheduled rule {rid!r} expr={expr!r} "
                        f"first_fire={first.isoformat()}"
                    )

                # Step 4: fire any rules whose next_fire is due.
                # Sort by next_fire so the earliest fires first (and
                # logs are deterministic).
                due = sorted(
                    ((rid, c["next_fire"], c["expression"]) for rid, c in cache.items()),
                    key=lambda t: t[1],
                )
                for rule_id, nxt, expression in due:
                    if nxt > now:
                        continue
                    # Re-fetch now for the fired_at timestamp so the
                    # payload reflects the moment we actually emitted,
                    # not the start of the tick.
                    fired_at = datetime.now(timezone.utc)
                    event = self._make_event(rule_id, expression, fired_at)
                    LOG.info(
                        f"cron fired: rule_id={rule_id} expression={expression} "
                        f"fired_at={event.payload['fired_at']} "
                        f"scheduled_for={nxt.isoformat()}"
                    )
                    try:
                        result = await self.engine.handle_event(event)
                    except Exception as e:
                        LOG.error(
                            f"cron: handle_event failed for rule {rule_id!r}: "
                            f"{type(e).__name__}: {e}"
                        )
                        # Still advance next_fire so we don't keep
                        # retrying the same missed boundary on every
                        # tick (which would spin a tight loop on a
                        # broken handler).
                        nxt = croniter(expression, nxt).get_next(datetime)
                        cache[rule_id]["next_fire"] = nxt
                        continue
                    # Advance the next_fire ANCHORED to the boundary
                    # we just fired — not to now — so we don't lose
                    # any missed boundaries during a slow tick.
                    nxt = croniter(expression, nxt).get_next(datetime)
                    cache[rule_id]["next_fire"] = nxt
                    # Bookkeeping
                    self.fired_count += 1
                    self.last_fires.setdefault(rule_id, []).append(
                        event.payload["fired_at"]
                    )
                    if len(self.last_fires[rule_id]) > 16:
                        self.last_fires[rule_id] = self.last_fires[rule_id][-16:]
                    self.last_event = event
                    LOG.info(
                        f"cron dispatch result: rule_id={rule_id} result={result}"
                    )

                # Step 5: sleep until the next tick or stop.
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self.tick_interval
                    )
                    break  # stop_event set during sleep
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            LOG.info("cron scheduler cancelled")
            raise
        except Exception as e:
            LOG.error(
                f"cron scheduler crashed: {type(e).__name__}: {e}",
                exc_info=True,
            )
            raise
        finally:
            LOG.info("cron scheduler stopped")

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def reset_counters(self) -> None:
        """Zero out fired_count / last_fires / last_event. Tests use this
        between assertions so they don't see events from earlier in the
        run."""
        self.fired_count = 0
        self.last_fires = {}
        self.last_event = None


__all__ = ["CronScheduler", "DEFAULT_TICK_INTERVAL"]
