#!/usr/bin/env python3
"""Ichor Auto-Eviction — move stale events to cold storage.

Events with importance below CUTOFF_IMPORTANCE AND age > CUTOFF_DAYS
are moved from ``ichor_events`` to ``ichor_cold_storage``. The cold
table mirrors the event schema plus an ``archived_at`` column.

Schedule: daily at 02:30, after decay at 02:30 (see
scripts/ichor_overnight_phase4.py, which is what the cron actually runs).

Usage:
    python3 lib/ichor_eviction.py                       # dry-run
    python3 lib/ichor_eviction.py --apply               # apply to live DB
    python3 lib/ichor_eviction.py --db /tmp/test.db --apply
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

# This module is documented as directly runnable (`python3 lib/ichor_eviction.py`),
# in which case sys.path[0] is lib/ and the repo-root package is not importable.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.ichor_temporal import normalize_timestamp, sql_utc  # noqa: E402

# Resolve through the account home, not `$HOME`: a god's gateway session runs
# with HOME set to its profile sandbox, so `Path.home()` silently points at a
# DIFFERENT DB — a shadow `ichor.db` was written in production this way.
from lib.pantheon_path import account_home as _account_home  # noqa: E402

logger = logging.getLogger("ichor_eviction")

DEFAULT_DB = _account_home() / ".hermes" / "ichor.db"
COLD_TABLE = "ichor_cold_storage"

# `ichor_events.importance` is a 0-100 score (schema DEFAULT 50.0, decayed rows
# settle just under the seeded value). The original cutoff here was 0.1 -- a unit
# error, not a tuning choice: it matched 0 of 1,813,406 rows, so this job exited
# 0 and archived nothing for its entire life ('reports success while doing
# nothing'). 10.0 also matches 0 rows on that scale.
#
# 40.0 is the low tail of the measured distribution (live 2026-09-21: min 31.0,
# avg 49.4, max 93.8 over 79,257 rows) and keeps the backlog bounded. Guarded by
# tests/test_ichor_v2_phase4.py::test_eviction_cutoff_is_scale_correct, which
# fails if anyone re-introduces a sub-1.0 constant.
CUTOFF_IMPORTANCE: float = 40.0
CUTOFF_DAYS: int = 90

# Cold storage schema mirrors ichor_events plus archived_at.
COLD_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {COLD_TABLE} (
    id INTEGER PRIMARY KEY,
    session_id TEXT,
    event_type TEXT,
    subject TEXT,
    predicate TEXT,
    object TEXT,
    confidence REAL,
    source TEXT,
    raw_text TEXT,
    created_at TEXT,
    god_name TEXT,
    importance REAL,
    trust REAL,
    maturity TEXT,
    last_access TEXT,
    direction TEXT,
    peer_god TEXT,
    archived_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


def _table_columns(conn: sqlite3.Connection, table: str) -> list[tuple]:
    """(name, type, notnull, dflt_value, pk) rows for `table`, or []."""
    return [
        (row[1], row[2], row[3], row[4], row[5])
        for row in conn.execute(f'PRAGMA table_info("{table}")')
    ]


def _sql_default(dflt: object) -> str:
    """Render a PRAGMA dflt_value as a legal DEFAULT clause.

    SQLite reports an expression default without its parentheses
    (``created_at`` comes back as ``datetime('now')``), and re-emitting that
    verbatim is a syntax error -- ``DEFAULT datetime('now')`` is rejected while
    ``DEFAULT (datetime('now'))`` is not. Literals pass through untouched.
    """
    text = str(dflt)
    if "(" in text and not text.lstrip().startswith(("'", '"')):
        return f"({text})"
    return text


def ensure_cold_table(conn: sqlite3.Connection) -> None:
    """Create -- or migrate -- ichor_cold_storage so it can hold ANY event row.

    The cold table mirrors ``ichor_events`` plus ``archived_at``, and it is
    DERIVED from the live source table rather than from a hand-written DDL.

    Why it must be derived: the previous hardcoded column list matched the
    2026-05 schema and then silently drifted as ``ichor_events`` gained
    ``occurred_start`` / ``occurred_end`` / ``mentioned_at`` / ``valid_from`` /
    ``valid_until`` / ``status`` / ``superseded_by`` / ``content_hash``. Because
    the call is ``CREATE TABLE IF NOT EXISTS``, the stale table simply stayed and
    every archive INSERT raised::

        table ichor_cold_storage has no column named occurred_start

    Nobody had ever seen that error, because the zero-match predicate meant the
    insert path was never reached -- the job returned early on `not rows` and
    exited 0. Two independent silent no-ops stacked on the same job.

    Deriving the definition (plus an ALTER migration for an existing narrower
    table) keeps the copy target in lockstep with the source by construction, so
    the next column added to ``ichor_events`` cannot re-break eviction.
    """
    source_cols = _table_columns(conn, "ichor_events")
    if not source_cols:
        # Nothing to mirror (fresh/foreign DB): keep the documented shape.
        conn.execute(COLD_TABLE_DDL)
        return

    defs: list[str] = []
    pk_cols: list[str] = []
    for name, ctype, notnull, dflt, pk in source_cols:
        definition = f'"{name}"'
        if ctype:
            definition += f" {ctype}"
        if pk and name.lower() == "id":
            definition += " PRIMARY KEY"
        else:
            if pk:
                pk_cols.append(f'"{name}"')
            if notnull:
                definition += " NOT NULL"
            if dflt is not None:
                definition += f" DEFAULT {_sql_default(dflt)}"
        defs.append(definition)
    if pk_cols:
        defs.append("PRIMARY KEY (" + ", ".join(pk_cols) + ")")
    defs.append("archived_at TEXT NOT NULL DEFAULT (datetime('now'))")

    conn.execute(
        f'CREATE TABLE IF NOT EXISTS {COLD_TABLE} (\n    '
        + ",\n    ".join(defs)
        + "\n)"
    )

    existing = {name for name, *_ in _table_columns(conn, COLD_TABLE)}
    for name, ctype, _notnull, _dflt, _pk in source_cols:
        if name in existing:
            continue
        conn.execute(
            f'ALTER TABLE {COLD_TABLE} ADD COLUMN "{name}"{f" {ctype}" if ctype else ""}'
        )


def eligibility_sql(age_bound: str = "datetime(?)") -> str:
    """The canonical eviction eligibility predicate, as an SQL fragment.

    Import this instead of restating it. Both the job (this module) and the
    monitor that grades it (``scripts/ichor-health.py``) MUST ask the same
    question -- a monitor carrying its own copy of a threshold is how
    ``importance < 0.1`` against a 0-100 column stayed green for months.

    ``age_bound`` is the normalised right-hand side: ``datetime(?)`` for the
    job's absolute cutoff, ``datetime('now', '-90 day')`` for the monitor's
    relative one. Both are compared against a normalised ``created_at`` -- see
    ``lib.ichor_temporal.CREATED_AT_SHAPES`` for why the raw column cannot be
    compared to a differently-shaped literal (it evicts rows that are not yet
    old enough).
    """
    return f"importance < ? AND {sql_utc('created_at')} < {age_bound}"


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def run_eviction(
    db_path: str | Path,
    *,
    dry_run: bool = True,
    reference_now: datetime | None = None,
    importance_cutoff: float | None = None,
    age_days: int | None = None,
) -> Dict[str, Any]:
    """Move stale events to cold storage.

    Args:
        db_path: Path to ichor.db.
        dry_run: If True, report candidates but don't move.
        reference_now: Override "now" for deterministic testing.
        importance_cutoff: Override CUTOFF_IMPORTANCE (operability/testing).
        age_days: Override CUTOFF_DAYS (operability/testing).

    Returns:
        Dict with `archived` (count moved), `candidates` (list of ids), and the
        cutoffs actually applied (`importance_cutoff`, `age_days`) so a caller
        can assert what ran instead of assuming the constant.
    """
    path = Path(db_path)
    if not path.exists():
        return {"archived": 0, "candidates": [], "error": "db not found"}

    cutoff_importance = CUTOFF_IMPORTANCE if importance_cutoff is None else float(importance_cutoff)
    cutoff_days = CUTOFF_DAYS if age_days is None else int(age_days)

    now = reference_now or datetime.now(timezone.utc)
    # BOTH sides normalised. `created_at` holds four shapes (see
    # lib/ichor_temporal.CREATED_AT_SHAPES) and the raw column can only be
    # compared to a differently-shaped literal down to the DAY: at offset 10
    # ' ' < 'T', so a space-shaped row on the cutoff day sorted as if it were
    # older. Live 2026-09-22: that admitted id 164078 ('2026-06-24 23:51:31',
    # 89.6 days old) into a 90-day eviction. `datetime()` on both sides makes
    # the comparison exact, and an unparseable created_at yields NULL -- which
    # compares false, so a malformed timestamp can never be evicted.
    cutoff_param = normalize_timestamp(now - timedelta(days=cutoff_days))

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    thresholds = {"importance_cutoff": cutoff_importance, "age_days": cutoff_days}

    try:
        ensure_cold_table(conn)

        cursor = conn.execute(
            f"SELECT * FROM ichor_events WHERE {eligibility_sql('datetime(?)')}",
            (cutoff_importance, cutoff_param),
        )
        rows = cursor.fetchall()
    except sqlite3.OperationalError as exc:
        conn.close()
        return {"archived": 0, "candidates": [], "error": str(exc), **thresholds}

    if not rows:
        conn.close()
        return {"archived": 0, "candidates": [], **thresholds}

    candidate_ids = [row["id"] for row in rows]

    if dry_run:
        conn.close()
        logger.info(
            "Eviction DRY-RUN: %d candidates (not moved)", len(rows)
        )
        return {"archived": 0, "candidates": candidate_ids, **thresholds}

    # Copy to cold storage FIRST -- the archive is what makes this recoverable.
    col_names = list(rows[0].keys())
    col_names = [c for c in col_names if c != "archived_at"]  # exclude if present
    placeholders = ", ".join("?" for _ in col_names)
    col_list = ", ".join(col_names)

    # `archived_at` is written in SQLite's own `datetime('now')` shape so it
    # matches the column DEFAULT and stays comparable with a plain
    # `datetime(archived_at)`.
    archived_at = now.strftime("%Y-%m-%d %H:%M:%S")
    conn.executemany(
        f"INSERT OR IGNORE INTO {COLD_TABLE} ({col_list}, archived_at) "
        f"VALUES ({placeholders}, ?)",
        [tuple(row[col] for col in col_names) + (archived_at,) for row in rows],
    )

    # Lockstep cleanup for the rows about to leave ichor_events.
    #
    # `ichor_event_tags.event_id` declares ON DELETE CASCADE and
    # `ichor_observation_sources.event_id` declares ON DELETE SET NULL, but
    # sqlite3 opens connections with `foreign_keys=OFF` and this module does not
    # change that, so NEITHER fires -- the same trap ichor-retention-prune.py
    # documents. Measured on the live DB for the 462 rows eligible on
    # 2026-09-22: 1,386 tag rows would be orphaned and 69 evidence rows would
    # point at events that no longer exist. Both are done explicitly here.
    #
    # `ichor_events_fts` needs nothing: it is external-content, so its AFTER
    # DELETE trigger keeps the index in sync. `memory_fts` and
    # `event_embeddings` mirror `cold_events` -- a different table with its own
    # id space -- and are untouched by eviction.
    tags_removed = 0
    evidence_unlinked = 0
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _evict_ids (id INTEGER PRIMARY KEY)")
    conn.execute("DELETE FROM _evict_ids")
    conn.executemany("INSERT INTO _evict_ids (id) VALUES (?)", [(rid,) for rid in candidate_ids])
    if _table_exists(conn, "ichor_event_tags"):
        tags_removed = conn.execute(
            "DELETE FROM ichor_event_tags WHERE event_id IN (SELECT id FROM _evict_ids)"
        ).rowcount
    if _table_exists(conn, "ichor_observation_sources"):
        evidence_unlinked = conn.execute(
            "UPDATE ichor_observation_sources SET event_id = NULL "
            "WHERE event_id IN (SELECT id FROM _evict_ids)"
        ).rowcount

    # Delete from main table
    conn.execute("DELETE FROM ichor_events WHERE id IN (SELECT id FROM _evict_ids)")
    conn.commit()

    logger.info(
        "Eviction: %d events archived to %s (%d tags removed, %d evidence rows unlinked)",
        len(rows), COLD_TABLE, tags_removed, evidence_unlinked,
    )
    conn.close()
    return {
        "archived": len(rows),
        "candidates": candidate_ids,
        "tags_removed": tags_removed,
        "evidence_unlinked": evidence_unlinked,
        **thresholds,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Ichor Auto-Eviction")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="Path to ichor.db")
    ap.add_argument("--apply", action="store_true", help="Actually apply (default: dry-run)")
    ap.add_argument("--importance", type=float, default=None,
                    help=f"Importance cutoff on the 0-100 scale (default {CUTOFF_IMPORTANCE})")
    ap.add_argument("--days", type=int, default=None,
                    help=f"Age cutoff in days (default {CUTOFF_DAYS})")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    result = run_eviction(
        args.db,
        dry_run=not args.apply,
        importance_cutoff=args.importance,
        age_days=args.days,
    )
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        return

    # ── report ───────────────────────────────────────────────────────────
    # The mode word is the ONLY tell that separates a run which archived rows
    # from one which merely counted them, so it stays on its own line and is
    # printed verbatim into the cron artifact. When the step actually applied,
    # the lockstep-cleanup counts are reported alongside it: a DELETE that
    # silently orphans tag rows is the same defect class as a job that reports
    # success while doing nothing, and neither one raises an error.
    mode = "ARCHIVED" if args.apply else "DRY-RUN"
    print(
        f"{mode}: {result['archived']} events, "
        f"{len(result.get('candidates', []))} candidates "
        f"(importance < {result.get('importance_cutoff')}, older than {result.get('age_days')}d)"
    )
    if args.apply:
        print(
            f"  lockstep cleanup: {result.get('tags_removed', 0)} tag rows deleted, "
            f"{result.get('evidence_unlinked', 0)} evidence rows unlinked"
        )
    if not args.apply and result.get("candidates"):
        print(f"  Candidate IDs: {result['candidates'][:10]}...")


if __name__ == "__main__":
    main()
