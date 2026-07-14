"""Hades orchestrator — runs all phases in sequence.

This is the function that the cron at 9am, the `scripts/hades` CLI
shim, and the test suite all call. It coordinates the 6 phases:

  1. Health checks (`run_health_checks`)
  2. Embed backfill (`embed_missing_files` + `_recheck_embedded_counts`)
  3. Distillation (`run_distillation`)
  4. Archive scan (`run_archive`)
  5. Suggestions (`load_suggestions`)
  6. Mailbox delivery (`deliver_to_mailbox`) — also writes the
     last-success sentinel for the notif-cron

Each phase runs inside its own try/except so a downstream failure
doesn't abort the rest of the sweep. Per-phase state is saved after
each phase completes; on the next run, completed phases are skipped
unless `--skip-resume` is passed or the state file is missing.

Brittleness fixes #3 and #4 (2026-06-03):
  - Per-phase timeout: each phase is bounded by `timeout / 3` seconds
    so a hung LLM call can't block the whole sweep. Default timeout
    is 1500s (25 min) → 500s per phase.
  - Per-phase resumable state: written to
    `~/.hermes/pantheon/hades-state.json` after each phase completes.
    Restartable from any point.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from typing import Any, Dict

from . import mailbox
from .embed import _recheck_embedded_counts, embed_missing_files
from .health import run_health_checks
from .distill import run_distillation
from .archive import run_archive
from .models import HadesReport
from .paths import HADES_STATE_FILE, REAL_HOME

logger = logging.getLogger(__name__)


# Phase definitions — name → (callable, description)
# The order here is the run order. Each phase is independently
# catchable; failures append to `report.errors` and the run continues.
PHASES: list = [
    ("health", "Health checks", run_health_checks),
    ("embed", "Embed backfill", embed_missing_files),
    ("distill", "Distillation", run_distillation),
    ("archive", "Archive scan", run_archive),
]


def _alarm_handler(signum: int, frame: Any) -> None:
    """SIGALRM handler — raises TimeoutError to abort the current phase."""
    raise TimeoutError(f"phase exceeded timeout")


def _run_phase_with_timeout(
    phase_name: str,
    phase_fn,
    report: HadesReport,
    per_phase_timeout: int,
) -> bool:
    """Run a single phase under a SIGALRM-based timeout.

    Returns True if the phase completed (within timeout), False if it
    timed out or errored. On error, appends to `report.errors`.
    """
    # Only set the alarm on platforms that support signal.SIGALRM
    # (POSIX). On Windows this is a no-op — the timeout will be
    # advisory only. The cron at 9am runs on Linux, so this matters
    # there.
    have_alarm = hasattr(signal, "SIGALRM")
    if have_alarm:
        old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(per_phase_timeout)

    try:
        if phase_name == "embed":
            # Embed is special: it also calls _recheck_embedded_counts
            # against the report after the embed pass.
            embed_result = phase_fn()
            report.embed = embed_result
            if embed_result.get("skipped") == -1:
                logger.warning("  → Embedder not available — skipping embed backfill")
            else:
                newly = embed_result.get("embedded", 0)
                before = embed_result.get("total_before", 0)
                after = embed_result.get("total_after", 0)
                rem = embed_result.get("remaining", 0)
                failed = embed_result.get("failed", 0)
                logger.info("  → %d files embedded (total: %d → %d vectors, %d remaining, %d failed)",
                            newly, before, after, rem, failed)
                # Brittleness follow-up: per-file embed failures (Ollama
                # timeouts, dim mismatches) are caught INSIDE _embed_file
                # and surfaced as result["failed"], not as exceptions.
                # Without this, the orchestrator's "clean run" check
                # (which keys off report.errors) would clear the resumable
                # state and the 9:15am notif would rubber-stamp success
                # while 30 embeds silently failed. Promote to report.errors
                # so the sentinel file + state-cleanup check both see it.
                if failed > 0:
                    report.errors.append(
                        f"embed phase: {failed} files failed to embed "
                        f"(see /home/konan/pantheon/logs/hades.log for per-file errors)"
                    )
            _recheck_embedded_counts(report)
            logger.info("  → Report counts refreshed with accurate embed numbers")
        else:
            result = phase_fn()
            if phase_name == "health":
                report.health = result
                logger.info("  → %d codexes checked", len(result.get("codexes", {})))
            elif phase_name == "distill":
                report.distillation = result
                logger.info("  → %d sessions → %d distilled files",
                            result.get("sessions_processed", 0),
                            result.get("distilled_files_written", 0))
            elif phase_name == "archive":
                report.archive = result
                logger.info("  → %d archive candidates found", len(result.get("candidates", [])))
        return True
    except TimeoutError as exc:
        report.errors.append(f"{phase_name} phase timed out after {per_phase_timeout}s: {exc}")
        logger.exception("Hades %s phase timed out", phase_name)
        return False
    except Exception as exc:
        # Catch network timeouts (httpx.ReadTimeout, httpcore.ReadTimeout,
        # requests.exceptions.Timeout) as well as general exceptions.
        # The SIGALRM-based timeout catches most cases; this catches
        # per-request timeouts that fire from inside the embed loop.
        report.errors.append(f"{phase_name} phase failed: {exc}")
        logger.exception("Hades %s phase error", phase_name)
        return False
    finally:
        if have_alarm:
            signal.alarm(0)  # Cancel the alarm
            signal.signal(signal.SIGALRM, old_handler)  # type: ignore[name-defined]


def run_hades(skip_resume: bool = False, timeout: int = 1500) -> HadesReport:
    """Run the complete Hades consolidation pipeline.

    Args:
        skip_resume: If True, ignore the per-phase state file and
            run all phases from scratch. Default False.
        timeout: Hard timeout in seconds for the whole run. Per-phase
            timeout is `timeout // 3`. Default 1500 (25 min).

    Returns:
        A HadesReport with all findings.
    """
    report = HadesReport()
    start = time.time()
    per_phase_timeout = max(60, timeout // 3)

    # Load resumable state unless told to skip
    state: Dict[str, Any] = {} if skip_resume else mailbox.load_state()
    if skip_resume:
        logger.info("Hades: --skip-resume set, ignoring per-phase state")
    elif state:
        logger.info("Hades: resuming from state: %s", ", ".join(sorted(state.keys())))
    else:
        logger.info("Hades: no resumable state, running all phases")

    try:
        # Run the 4 data-collection phases
        for phase_name, phase_desc, phase_fn in PHASES:
            if phase_name in state:
                logger.info("Hades: %s (skipping — completed at %s)", phase_desc, state[phase_name])
                # Re-run anyway but don't write state again — this is
                # the "skip" behavior. If you want a fresh run, use
                # --skip-resume.
                continue

            logger.info("Hades: %s...", phase_desc)
            ok = _run_phase_with_timeout(phase_name, phase_fn, report, per_phase_timeout)
            if ok:
                mailbox.save_state(phase_name)
            else:
                # Don't save state for failed phases so the next run
                # retries. But keep going — the report can still
                # capture whatever did succeed.
                logger.warning("Hades: %s did not complete cleanly — will retry next run", phase_desc)

        # Phase 5: Suggestions (always run — file is small + atomic)
        logger.info("Hades: Loading suggestions...")
        try:
            suggestions = mailbox.load_suggestions()
            report.suggestions = suggestions
            if suggestions:
                logger.info("  → %d pending Codex suggestions", len(suggestions))
        except Exception as exc:
            report.errors.append(f"Suggestions load failed: {exc}")
            logger.exception("Hades suggestions error")

        # Phase 6: Mailbox delivery
        logger.info("Hades: Delivering report to Hermes mailbox...")
        try:
            msg_path = mailbox.deliver_to_mailbox(report)
            if msg_path:
                logger.info("  → Delivered: %s", msg_path)
        except Exception as exc:
            report.errors.append(f"Mailbox delivery failed: {exc}")
            logger.exception("Hades mailbox delivery error")

        # If we got here without errors, the full run succeeded —
        # clear the resumable state so the next run starts fresh.
        if not report.errors:
            mailbox.clear_state()
            logger.info("Hades: full run clean, resumable state cleared")
        else:
            logger.warning("Hades: %d errors, resumable state preserved for next run", len(report.errors))

        elapsed = time.time() - start
        logger.info("Hades complete in %.2fs", elapsed)

        # Phase 7: Write heartbeat for the Fates watchdog
        try:
            _hades_scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
            if _hades_scripts not in sys.path:
                sys.path.insert(0, _hades_scripts)
            from heartbeat import beat  # type: ignore  # noqa: F811
            beat("hades")
            logger.info("  → Heartbeat written")
        except Exception as exc:
            logger.warning("  → Heartbeat write failed (non-fatal): %s", exc)

    except Exception as exc:
        report.errors.append(f"Hades run failed: {exc}")
        logger.exception("Hades run failed")

    return report
