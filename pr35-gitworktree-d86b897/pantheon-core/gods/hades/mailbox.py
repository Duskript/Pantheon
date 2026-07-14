"""Hades mailbox + suggestions phase.

Phase 5 of the pipeline. Two responsibilities:
  1. `load_suggestions` — drains the pending-codex suggestions queue.
     The queue lives at `~/.hermes/pantheon/suggested-codexes.json`.
     Hades reads + clears the file atomically; if the file is missing
     or malformed, returns an empty list (fail-open).
  2. `deliver_to_mailbox` — writes the HadesReport as a JSON message
     into Hermes' inbox (`~/pantheon/gods/messages/hermes/`). The
     message follows the standard pantheon-bridge envelope shape:
     `id / from / to / type / subject / body / payload / timestamp / read`.

The mailbox delivery is also where the cron-notif decoupled fix (#5)
gets its input: after a successful delivery we write a sentinel file
at `~/.hermes/pantheon/hades-last-success.json` so the 9:15am
Hades-Notif cron can verify the main job actually completed.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import HadesReport
from .paths import (
    HADES_LAST_SUCCESS,
    HADES_STATE_FILE,
    HERMES_INBOX,
    SUGGEST_FILE,
    REAL_HOME,
)

logger = logging.getLogger(__name__)


def _seq_id() -> str:
    """Generate a unique message ID based on timestamp."""
    return datetime.now(timezone.utc).strftime("msg_%Y%m%d_%H%M%S_%f")[:26]


def load_suggestions() -> List[Dict]:
    """Load and clear the pending Codex suggestions queue."""
    if SUGGEST_FILE.exists():
        try:
            suggestions: List[Dict] = json.loads(SUGGEST_FILE.read_text())
            SUGGEST_FILE.write_text("[]")
            return suggestions
        except (json.JSONDecodeError, Exception):
            return []
    return []


def _write_last_success(report: HadesReport) -> None:
    """Brittleness fix #5: write a sentinel the notif-cron reads.

    The Hades-Notif cron at 9:15am was previously decoupled from the
    main Hades job. If the main job died at step 1, the notif still
    ran and rubber-stamped "all good" based on stale state. This
    sentinel file fixes that — the notif should refuse to declare
    success if this file is missing or older than 24h.
    """
    try:
        HADES_LAST_SUCCESS.parent.mkdir(parents=True, exist_ok=True)
        HADES_LAST_SUCCESS.write_text(json.dumps({
            "timestamp": report.timestamp,
            "errors": len(report.errors),
            "distilled": report.distillation.get("distilled_files_written", 0),
            "embedded": report.embed.get("embedded", 0),
            "archive_candidates": len(report.archive.get("candidates", [])),
        }, indent=2), encoding="utf-8")
        logger.info("  → Last-success sentinel written: %s", HADES_LAST_SUCCESS)
    except Exception as exc:
        logger.warning("  → Failed to write last-success sentinel (non-fatal): %s", exc)


def deliver_to_mailbox(report: HadesReport) -> Optional[str]:
    """Send the Hades report as a JSON message to Hermes' inbox.

    Returns the message file path if delivered, None on failure.
    Also writes the last-success sentinel for the notif-cron to read.
    """
    try:
        HERMES_INBOX.mkdir(parents=True, exist_ok=True)

        msg_id = _seq_id()
        markdown = report.to_markdown()
        health = report.health or {}
        dist = report.distillation or {}
        arch = report.archive or {}

        # Build a concise summary for the body
        summary_parts: List[str] = []
        if health.get("indexes_created"):
            summary_parts.append(f"📄 Auto-created {len(health['indexes_created'])} INDEX.md files")
        orphans_fs = health.get("orphans", {}).get("fs_unembedded", [])
        if orphans_fs:
            summary_parts.append(f"⚠️ {len(orphans_fs)} files not embedded in ChromaDB")
        if dist.get("distilled_files_written", 0) > 0:
            summary_parts.append(f"🔄 Distilled {dist['distilled_files_written']} files")
        if arch.get("candidates"):
            summary_parts.append(f"🗄️ {len(arch['candidates'])} archive candidates found")
        if report.errors:
            summary_parts.append(f"❌ {len(report.errors)} errors during run")

        summary = " • ".join(summary_parts) if summary_parts else "No issues detected."

        message = {
            "id": msg_id,
            "from": "hephaestus",
            "to": "hermes",
            "type": "report",
            "subject": f"Hades Nightly Report — {report.timestamp[:10]}",
            "body": f"Hades consolidation pipeline ran at {report.timestamp[:19]}.\n\n{summary}\n\n---\n\nFull report:\n{markdown}",
            "priority": "normal",
            "timestamp": report.timestamp,
            "read": False,
            "payload": {
                "report_type": "hades_nightly",
                "date": report.timestamp[:10],
                "indexes_created": len(health.get("indexes_created", [])),
                "files_unembedded": len(orphans_fs),
                "distilled_written": dist.get("distilled_files_written", 0),
                "archive_candidates": len(arch.get("candidates", [])),
                "errors": len(report.errors),
            },
            "thread_id": None,
        }

        msg_path = HERMES_INBOX / f"{msg_id}.json"
        msg_path.write_text(json.dumps(message, indent=2, default=str), encoding="utf-8")
        logger.info("  → Report delivered to Hermes mailbox: %s", msg_path.name)

        # Write the sentinel the notif-cron depends on
        _write_last_success(report)

        return str(msg_path)

    except Exception as exc:
        logger.exception("Failed to deliver report to Hermes mailbox: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Per-phase resumable state (Brittleness fix #4)
# ---------------------------------------------------------------------------


def load_state() -> Dict[str, Any]:
    """Read the per-phase resumable state.

    Returns a dict of `phase_name: timestamp_iso`. Missing or malformed
    file returns an empty dict (fail-open — the caller treats an empty
    state as "all phases need to run").
    """
    if not HADES_STATE_FILE.exists():
        return {}
    try:
        return json.loads(HADES_STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(phase: str) -> None:
    """Mark a phase as completed in the state file.

    Called after each phase succeeds. The state file is best-effort —
    if writes fail, the next run will just re-run everything (no harm
    done; the phases are mostly idempotent).
    """
    try:
        state = load_state()
        state[phase] = datetime.now(timezone.utc).isoformat()
        HADES_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        HADES_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("  → Failed to write phase state for %s (non-fatal): %s", phase, exc)


def clear_state() -> None:
    """Clear the per-phase state. Called at the start of a full run."""
    try:
        if HADES_STATE_FILE.exists():
            HADES_STATE_FILE.unlink()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CLI entry point + main orchestrator
# ---------------------------------------------------------------------------


def main() -> None:
    """Run Hades and print the report to stdout.

    Brittleness fix #6 (2026-06-03): the --archive help text now says
    "List stale files eligible for archival (does NOT move)" so users
    don't expect the scanner to actually move files.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Hades — Athenaeum consolidation pipeline")
    parser.add_argument("--health", action="store_true", help="Run health checks only")
    parser.add_argument("--embed", action="store_true", help="Run embed backfill only")
    parser.add_argument("--distill", action="store_true", help="Run distillation only")
    parser.add_argument(
        "--archive", action="store_true",
        help="List stale files eligible for archival (does NOT move; reports candidates for review)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--save", metavar="PATH", help="Save report to file")
    parser.add_argument(
        "--skip-resume", action="store_true",
        help="Ignore per-phase state file and run all phases from scratch",
    )
    parser.add_argument(
        "--timeout", type=int, default=1500, metavar="SECONDS",
        help="Hard timeout in seconds for the full run (default 1500 = 25 min). Per-phase is 1/3 of this.",
    )

    args = parser.parse_args()

    # Set up logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    if args.embed:
        from .embed import embed_missing_files, _recheck_embedded_counts
        report = HadesReport()
        embed_result = embed_missing_files()
        _recheck_embedded_counts(report)
        if embed_result.get("skipped") == -1:
            print("Embedder not available — skipping")
        else:
            print(f"Embedded: {embed_result.get('embedded', 0)} files "
                  f"(total: {embed_result.get('total_before', 0)} → {embed_result.get('total_after', 0)} vectors)")
        from .health import run_health_checks
        report.health = run_health_checks()
        _recheck_embedded_counts(report)
        report.suggestions = load_suggestions()
    elif args.health:
        from .health import run_health_checks
        from .embed import _recheck_embedded_counts
        report = HadesReport()
        report.health = run_health_checks()
        _recheck_embedded_counts(report)
        report.suggestions = load_suggestions()
    elif args.distill:
        from .distill import run_distillation
        report = HadesReport()
        report.distillation = run_distillation()
    elif args.archive:
        from .archive import run_archive
        report = HadesReport()
        report.archive = run_archive()
    else:
        from .orchestrator import run_hades as _run_hades
        report = _run_hades(skip_resume=args.skip_resume, timeout=args.timeout)

    # Record heartbeat after any mode runs
    try:
        _hades_scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
        if _hades_scripts not in sys.path:
            sys.path.insert(0, _hades_scripts)
        from heartbeat import beat  # noqa: F811
        beat("hades")
    except Exception:
        pass

    if args.json:
        output = json.dumps(report.to_dict(), indent=2)
    else:
        output = report.to_markdown()

    print(output)

    if args.save:
        Path(args.save).write_text(output, encoding="utf-8")
        logger.info("Report saved to %s", args.save)


if __name__ == "__main__":
    main()
