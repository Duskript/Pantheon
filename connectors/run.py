#!/usr/bin/env python3
"""
run.py — Pantheon connector CLI.

Subcommands map to per-source connectors. The first concrete
connector is the YouTube Takeout one; Gmail / RSS / Claude export
will land as v0.5 (per the User-Context-Engine build plan).

Usage:

    python run.py youtube --file watch-history.json
    python run.py youtube --file watch-history.json --user-id konan
    python run.py youtube --file watch-history.json --codex Codex-YouTube
    python run.py youtube --file watch-history.json --since 1970-01-01T00:00:00Z

Exit codes:

    0   One or more items were dropped, OR the run was a no-op
        (everything skipped by the cursor — that's a success state).
    1   A hard failure: file not found, unreadable JSON, or any
        other error that prevented the run from completing. The
        state file's ``errors`` list has the message.
    2   Invalid CLI usage (argparse rejects the args).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

# Make ``lib`` and ``sources`` importable when run as a script.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


from sources.youtube_takeout.connector import (  # noqa: E402
    YouTubeTakeoutConnector,
    CONNECTOR_NAME as YT_NAME,
)


# Configure root logging so the operator (or cron) sees progress.
# Verbose-by-default is a conscious choice for D2 — the file-drop
# flow is rare enough that progress lines help debugging. We can
# quiet this down later if the cron output gets noisy.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger("run")


# ─── argument parsing ──────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argparse parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="run.py",
        description=(
            "Pantheon connector CLI. Run a per-source connector against "
            "its data and drop the result into the Athenaeum inbox."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── youtube (file-drop Takeout connector) ──
    yt = sub.add_parser(
        "youtube",
        aliases=["yt"],
        help="YouTube Takeout connector. Reads watch-history.json, fetches transcripts, drops to inbox.",
    )
    yt.add_argument(
        "--file",
        required=True,
        type=Path,
        metavar="PATH",
        help="Path to watch-history.json from a Google Takeout export.",
    )
    yt.add_argument(
        "--user-id",
        default="konan",
        metavar="ID",
        help="Tenant identifier (default: %(default)s).",
    )
    yt.add_argument(
        "--codex",
        default=None,
        metavar="CODEX",
        help="Target codex for the dropped files (default: Codex-YouTube).",
    )
    yt.add_argument(
        "--since",
        default=None,
        metavar="ISO8601",
        help=(
            "ISO-8601 UTC timestamp; only process watch-history entries "
            "newer than this. Defaults to the state cursor. Use "
            "'1970-01-01T00:00:00Z' to force a full re-process."
        ),
    )
    yt.add_argument(
        "--language",
        default=None,
        metavar="LANG",
        help=(
            "Comma-separated transcript language preference list "
            "(default: en,en-US,en-GB)."
        ),
    )

    return parser


def _parse_since(raw: Optional[str]) -> Optional[datetime]:
    """Parse a ``--since`` value into a UTC datetime, or return None."""
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise SystemExit(f"invalid --since value {raw!r}: {exc}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ─── subcommand handlers ──────────────────────────────────────────


def cmd_youtube(args: argparse.Namespace) -> int:
    """Run the YouTube Takeout connector.

    Returns the process exit code: 0 for success (including
    no-op), 1 for hard failure. The state file is the source of
    truth for "did anything drop"; the function also returns the
    number of dropped items via a JSON summary on stdout.
    """
    file_path: Path = args.file.expanduser()
    if not file_path.is_file():
        # Hard fail — better to error visibly than to write an
        # ambiguous state record.
        print(
            json.dumps({"error": f"watch-history.json not found at {file_path}"}),
            file=sys.stderr,
        )
        return 1

    languages: Optional[Sequence[str]] = None
    if args.language:
        languages = tuple(s.strip() for s in args.language.split(",") if s.strip())

    connector = YouTubeTakeoutConnector(
        file_path=file_path,
        fetch_languages=languages,
    )
    connector.user_id = args.user_id
    if args.codex:
        connector.codex = args.codex

    since = _parse_since(args.since)

    try:
        dropped = connector.run(since=since)
    except Exception as exc:  # noqa: BLE001 — surface anything to stderr
        # ``ConnectorBase.run`` is supposed to catch and record its
        # own errors, so anything reaching this point is a real
        # bug. Log and exit 1.
        logger.exception("unhandled exception in run()")
        print(
            json.dumps({"error": repr(exc)}),
            file=sys.stderr,
        )
        return 1

    # Single-line JSON summary on stdout — easy to parse in a cron
    # wrapper or just read for an at-a-glance count.
    summary = {
        "connector": YT_NAME,
        "user_id": args.user_id,
        "codex": connector.codex,
        "file": str(file_path),
        "dropped": dropped,
    }
    print(json.dumps(summary))
    return 0


# ─── main ─────────────────────────────────────────────────────────


_HANDLERS = {
    "youtube": cmd_youtube,
    "yt": cmd_youtube,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _HANDLERS.get(args.command)
    if handler is None:
        parser.error(f"unknown command: {args.command}")
        return 2
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
