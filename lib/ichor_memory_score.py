"""Importance + Trust scoring for Ichor memory events.

Every ichor_event gets two scores:
- importance (0-100): how notable the information is
- trust (0-100): how reliable the information is

These change over time through access, updates, decay, and contradiction.
"""

import sqlite3
import logging

from lib.ichor_temporal import older_than_sql

logger = logging.getLogger("ichor_memory_score")

# Decay/maturity maintenance is bounded to L3 (long-term memory, 30d+).
# Rationale (measured 2026-09-21): apply_decay() + update_maturity() are
# whole-table UPDATEs, and ichor_tick runs this module every 2 hours, so a
# 1.82M-row table was being rewritten 12x/day. On a 1.82M-row table that is
# ~1.2 GiB of page writes per pass, and because ichor_events_au fired on any
# update it also rewrote every FTS document. The value it computes is
# degenerate anyway (88% of rows converge on a single importance of 49.0075),
# so the churn bought nothing. L1/L2 rows now keep the score their access
# boosts give them; only L3 rows age.
L3_MIN_AGE_DAYS = 30

DECAY_RATE = 0.995       # Daily importance decay factor
IMPORTANCE_ACCESS_BOOST = 3
IMPORTANCE_UPDATE_BOOST = 5
TRUST_CONFIRM_BOOST = 3
TRUST_CONTRADICT_PENALTY = 10

DRAFT_THRESHOLD = 20
CORE_THRESHOLD = 70
PRUNE_IMPORTANCE = 5
PRUNE_TRUST = 20
PRUNE_DAYS = 90


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """Open a connection to the ichor database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Add scoring columns if they don't exist (idempotent).

    Note: 'last_access' uses a separate two-step migration because
    SQLite ALTER TABLE ADD COLUMN does not accept non-constant defaults.
    We add the column as nullable TEXT, then set existing rows.
    """
    existing = [row["name"] for row in conn.execute("PRAGMA table_info(ichor_events)")]
    migrations = [
        ("importance", "REAL DEFAULT 50.0"),
        ("trust", "REAL DEFAULT 50.0"),
        ("maturity", "TEXT DEFAULT 'validated'"),
    ]
    for col, col_type in migrations:
        if col not in existing:
            conn.execute(f"ALTER TABLE ichor_events ADD COLUMN {col} {col_type}")

    # last_access uses a non-constant default, two-step migration
    if "last_access" not in existing:
        conn.execute("ALTER TABLE ichor_events ADD COLUMN last_access TEXT")
        conn.execute("UPDATE ichor_events SET last_access = datetime('now') WHERE last_access IS NULL")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_ichor_events_importance ON ichor_events(importance)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ichor_events_maturity ON ichor_events(maturity)")

    # Phase 3: Direction + peer_god columns
    if "direction" not in existing:
        conn.execute("ALTER TABLE ichor_events ADD COLUMN direction TEXT DEFAULT 'unknown'")
    if "peer_god" not in existing:
        conn.execute("ALTER TABLE ichor_events ADD COLUMN peer_god TEXT DEFAULT ''")

    conn.commit()


def on_access(conn: sqlite3.Connection, event_id: int) -> None:
    """Record access: boost importance, update timestamp."""
    conn.execute(
        "UPDATE ichor_events SET importance = MIN(100, importance + ?), "
        "last_access = datetime('now') WHERE id = ?",
        (IMPORTANCE_ACCESS_BOOST, event_id),
    )
    conn.commit()


def on_update(conn: sqlite3.Connection, event_id: int) -> None:
    """Record update: bigger importance boost."""
    conn.execute(
        "UPDATE ichor_events SET importance = MIN(100, importance + ?), "
        "last_access = datetime('now') WHERE id = ?",
        (IMPORTANCE_UPDATE_BOOST, event_id),
    )
    conn.commit()


def on_confirm(conn: sqlite3.Connection, event_id: int) -> None:
    """Confirm information: boost trust."""
    conn.execute(
        "UPDATE ichor_events SET trust = MIN(100, trust + ?), "
        "last_access = datetime('now') WHERE id = ?",
        (TRUST_CONFIRM_BOOST, event_id),
    )
    conn.commit()


def on_contradict(conn: sqlite3.Connection, event_id: int) -> None:
    """Contradict information: penalize trust."""
    conn.execute(
        "UPDATE ichor_events SET trust = MAX(0, trust - ?), "
        "last_access = datetime('now') WHERE id = ?",
        (TRUST_CONTRADICT_PENALTY, event_id),
    )
    conn.commit()


def apply_decay(conn: sqlite3.Connection) -> int:
    """Apply daily decay to all events. Returns count of events affected."""
    cursor = conn.execute(
        "UPDATE ichor_events SET importance = MAX(0, importance * ?) "
        "WHERE importance > 0 "
        # Normalised both sides: `created_at` holds four shapes and the
        # raw column only compares correctly to a same-shaped literal down
        # to the DAY (see lib/ichor_temporal.CREATED_AT_SHAPES). This gate
        # decides which rows get REWRITTEN, so an off-by-a-day here is a
        # silent write to the wrong rows.
        f"AND {older_than_sql('created_at', days=L3_MIN_AGE_DAYS)}",
        (DECAY_RATE,),
    )
    conn.commit()
    return cursor.rowcount


def update_maturity(conn: sqlite3.Connection) -> None:
    """Recalculate maturity tier for all events based on importance score."""
    conn.execute(
        f"""UPDATE ichor_events SET maturity = CASE
            WHEN importance < ? THEN 'draft'
            WHEN importance >= ? THEN 'core'
            ELSE 'validated'
        END
        WHERE {older_than_sql('created_at', days=L3_MIN_AGE_DAYS)}""",
        (DRAFT_THRESHOLD, CORE_THRESHOLD),
    )
    conn.commit()


def prune_candidates(conn: sqlite3.Connection) -> list:
    """Find events eligible for pruning.

    Returns list of (id, subject, importance, trust, age_days) for review.
    """
    candidates = conn.execute(
        """SELECT id, subject, importance, trust,
            julianday('now') - julianday(created_at) AS age_days
        FROM ichor_events
        WHERE importance < ? AND trust < ?
        AND julianday('now') - julianday(created_at) > ?
        ORDER BY importance ASC, trust ASC
        LIMIT 50""",
        (PRUNE_IMPORTANCE, PRUNE_TRUST, PRUNE_DAYS),
    ).fetchall()
    return [dict(r) for r in candidates]


def prune_execute(conn: sqlite3.Connection, dry_run: bool = True) -> int:
    """Delete eligible events, or dry-run to show what would be deleted.

    Returns count of events that would be / were deleted.
    """
    candidates = conn.execute(
        """SELECT id FROM ichor_events
        WHERE importance < ? AND trust < ?
        AND julianday('now') - julianday(created_at) > ?
        ORDER BY importance ASC
        LIMIT 100""",
        (PRUNE_IMPORTANCE, PRUNE_TRUST, PRUNE_DAYS),
    ).fetchall()

    if not candidates:
        return 0

    ids = [r["id"] for r in candidates]

    if dry_run:
        logger.info("Prune dry-run: %d events eligible for deletion", len(ids))
        return len(ids)

    placeholders = ",".join("?" * len(ids))
    # Clean the dependants BEFORE the delete. Both FKs declare cascading
    # behaviour (ichor_event_tags ON DELETE CASCADE, observation_sources
    # event_id ON DELETE SET NULL) but every live connection runs
    # foreign_keys=0, so SQLite never enforces them: deleting events alone
    # leaves orphaned tags and dangling provenance pointers. Measured
    # 2026-09-21: this function running every 2 hours had produced 121,997
    # dangling observation_sources.event_id values and orphaned tag rows.
    conn.execute(
        f"UPDATE ichor_observation_sources SET event_id = NULL "
        f"WHERE event_id IN ({placeholders})", ids)
    conn.execute(
        f"DELETE FROM ichor_event_tags WHERE event_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM ichor_events WHERE id IN ({placeholders})", ids)
    conn.commit()
    logger.info("Pruned %d low-importance events (provenance + tags cleaned)",
                len(ids))
    return len(ids)
