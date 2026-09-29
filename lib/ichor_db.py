"""Ichor Memory Engine — Database Layer.

Manages the SQLite-backed events database with FTS5 full-text search.
All event storage, retrieval, and search operations for the Pantheon system.
"""

import os
import re
import hashlib
import sqlite3
import threading
from typing import Any, Optional


# Canonical event types. Kept in sync with TYPE_META in ichor_brief.py.
# Single source of truth here; ichor_brief.py imports from this module.
def content_hash(raw_text: str | None) -> str:
    """Stable hash of an event's content key (normalized raw_text).

    Single source of truth for the write-path dedupe guard: `insert_event`
    stores it, and `ichor_tier_a._find_duplicate_id` looks it up to refuse
    re-storing identical content. Measured 2026-09-21 before this existed:
    88% of surviving ichor memory was byte-identical duplication, with one
    prompt fragment stored 19,108 times, because the extractor runs on every
    turn and stored the same text again each time.
    """
    return hashlib.sha256(
        (raw_text or "").strip().encode("utf-8", "replace")
    ).hexdigest()


VALID_EVENT_TYPES: frozenset[str] = frozenset({
    "blocker",
    "commitment",
    "decision",
    "follow_up",
    "correction",
    "insight",
    "fact",
    "preference",
    "reference",
    "user_md_update",
})


# ── Tiered-context generation (B1, per marvin-memory-upgrade-handoff-2026-06-10) ──
# Heuristics for deriving L0 (brief) and L1 (outline) from raw text. The rules
# are intentionally simple — first-sentence / first-N-chars. The Tier A path
# (B2) will refine this with an optional LLM upgrade if the heuristic is too
# lossy. See gate-b1-from-schema-to-tiered in the handoff doc.

_BRIEF_MAX = 100   # L0 ceiling
_OUTLINE_MAX = 500  # L1 ceiling

# Sentence-boundary splitter: ., !, ? followed by whitespace + uppercase or end.
# Won't catch every edge case (Mr., e.g., etc.) but is good enough for the
# heuristic; full sentence-tokenization is overkill at L0.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9'\"])")


def _first_sentence(text: str) -> str:
    """Return the first non-empty sentence, stripped of surrounding whitespace."""
    text = text.strip()
    if not text:
        return ""
    parts = _SENTENCE_SPLIT.split(text, maxsplit=1)
    return parts[0].strip()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True when ``table`` already has ``column`` (SQLite PRAGMA)."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return False
    return any(str(row[1]) == column for row in rows)


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Add a column to an existing table only when it is absent.

    SQLite cannot reliably express ``ALTER TABLE ... ADD COLUMN IF NOT
    EXISTS``, so migrations do the check in Python.
    """
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def auto_generate_tiers(raw_text: str) -> tuple[str, str]:
    """Generate brief (L0) and outline (L1) from raw text heuristically.

    Heuristic rules (per build-brief.md Phase 1 / P1b):
      - brief = first non-empty sentence, capped at 100 chars
      - outline = first 500 chars of cleaned text
      - If raw_text < 100 chars: brief = raw_text, outline = raw_text
      - If raw_text < 500 chars: brief = first 50%, outline = raw_text
      - If raw_text is None or empty: returns ("(no content)", "(no content)")
        so brief/outline are never NULL/empty in the DB.

    Returns:
        (brief, outline) — both strings, never empty if input was provided
        (None, "" or whitespace all return the placeholder).
    """
    if raw_text is None or not raw_text:
        return ("(no content)", "(no content)")
    text = raw_text.strip()
    if not text:
        return ("(no content)", "(no content)")

    n = len(text)
    if n < _BRIEF_MAX:
        # Short content: both tiers carry the same text (no summarization possible).
        return (text, text)

    first = _first_sentence(text)
    # Brief: first sentence, capped
    if len(first) > _BRIEF_MAX:
        # Cut at word boundary, then add ellipsis
        cut = first[:_BRIEF_MAX].rsplit(" ", 1)[0]
        brief = (cut or first[:_BRIEF_MAX]).rstrip(",;:.- ") + "…"
    else:
        brief = first

    # Outline: first 500 chars of cleaned text
    outline = text[:_OUTLINE_MAX]
    if len(text) > _OUTLINE_MAX:
        # Cut at word boundary
        cut = outline.rsplit(" ", 1)[0]
        outline = (cut or outline).rstrip(",;:.- ") + "…"

    return (brief, outline)


# ── lock-wait policy for the shared Ichor connection ───────────────────
# Batch maintenance scripts in the fleet all set PRAGMA busy_timeout=600000
# (~/.hermes/scripts/ichor-retention-prune.py, ichor-dedupe.py,
# ichor-reconcile.py, ichor-importance-reseed.py). The hindsight maintenance
# path was the outlier: it reached the database through this class with only
# sqlite3's 5s default, so when a sibling job held the write lock — a 12 GiB
# WAL truncate, a retention prune, a gateway checkpoint — the run aborted with
# `sqlite3.OperationalError: database is locked`. Observed live 2026-09-21 at
# 09:51 and 10:07 in ichor_hindsight_maintenance.py, which alerts on any
# non-zero exit and so paged a failure that a longer wait would have absorbed.
#
# The timeout is OPT-IN and defaults to None (sqlite3's own 5s) because this
# class is ALSO the live gateway's connection: blocking a chat turn for ten
# minutes is worse than a fast, visible failure. Batch callers pass it
# explicitly; live callers keep today's behaviour.
MAINTENANCE_BUSY_TIMEOUT_MS: int = 600_000


class IchorDB:
    """Manages the Ichor events database connection and operations.

    Provides CRUD operations for ichor_events and FTS5 full-text search,
    with automatic schema initialization on first connect.
    """

    def auto_generate_tiers(self, raw_text: str) -> tuple[str, str]:
        """Instance-method wrapper around the module-level auto_generate_tiers.

        Provided so the spec's Gate B1 check (`db.auto_generate_tiers(...)`)
        works as written. Logic is identical — the module function is the
        single source of truth and the instance method just delegates.
        """
        return auto_generate_tiers(raw_text)

    # ── busy_timeout_ms: why the constructor carries a lock-wait knob ──────
    # Mechanism: sqlite3.connect() starts with a 5s busy timeout, and SQLite
    # raises `database is locked` the moment that expires. A batch job and a
    # live writer share one file, so the batch job's success depends on how
    # long it is willing to wait for a lock it does not control.
    # Symptom (measured): ichor_hindsight_maintenance.py exited 1 twice on
    # 2026-09-21 (09:51 and 10:07) with `sqlite3.OperationalError: database is
    # locked` raised from ichor_temporal_backfill.py, while the WAL stood at
    # 12 GiB and a sibling job was checkpointing it.
    # Reproduce by hand: hold a write lock in one shell and run the job in
    # another —
    #     python3 -c "import sqlite3,time; c=sqlite3.connect('/home/konan/.hermes/ichor.db'); c.execute('BEGIN IMMEDIATE'); time.sleep(30)"
    #     python3 scripts/ichor_temporal_backfill.py --db-path ~/.hermes/ichor.db --apply
    # With the 5s default the second command dies; with the batch value below
    # it simply waits and succeeds.
    def __init__(
        self,
        db_path: str = "~/.hermes/ichor.db",
        *,
        busy_timeout_ms: int | None = None,
    ):
        """Initialize the Ichor database manager.

        Args:
            db_path: Path to the SQLite database file. Tilde is expanded
                     to the user's home directory. Defaults to ~/.hermes/ichor.db.
            busy_timeout_ms: How long a writer blocked on the file lock waits
                     before raising (PRAGMA busy_timeout). None leaves sqlite3's
                     5s default in place, which is what live gateway callers
                     want; batch jobs pass MAINTENANCE_BUSY_TIMEOUT_MS so a lock
                     held by a sibling maintenance job is waited out rather than
                     aborting the run.
        """
        self.db_path = os.path.expanduser(db_path)
        self.busy_timeout_ms = busy_timeout_ms
        self._conn: Optional[sqlite3.Connection] = None
        # RLock: the gateway calls this from worker threads (token-juice,
        # context-compressor, ichor nudge). check_same_thread=False in
        # connect() lets the connection be touched from any thread; this
        # lock serialises access so SQLite's own thread-safety rules hold.
        self._lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        """Open (or create) the database and ensure the schema exists.

        Returns:
            The active sqlite3.Connection object.

        Raises:
            sqlite3.Error: If the database cannot be opened or schema creation fails.
        """
        # Double-checked locking: fast path for the common case, lock for init.
        if self._conn is not None:
            return self._conn
        with self._lock:
            if self._conn is not None:
                return self._conn

            # Ensure parent directory exists
            db_dir = os.path.dirname(self.db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

            # check_same_thread=False lets the gateway call this from
            # worker threads (token-juice, context-compressor, ichor
            # nudge). The RLock above serialises all access so SQLite's
            # own thread semantics remain safe.
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            # ── PRAGMA busy_timeout: the batch lock-wait policy ────────────
            # Mechanism: this pragma sets how many milliseconds SQLite retries a
            # blocked write before raising `database is locked`. It must be
            # applied to the connection BEFORE the first statement, because a
            # connection that has already hit the lock keeps the old policy.
            # Default here is unchanged: with busy_timeout_ms unset we execute
            # nothing and the connection keeps sqlite3's own 5s timeout, so live
            # gateway callers behave exactly as they did before this branch
            # existed. Only batch callers opt in, by passing
            # MAINTENANCE_BUSY_TIMEOUT_MS.
            # Symptom (measured 2026-09-21): two hindsight runs aborted at 09:51
            # and 10:07 with `sqlite3.OperationalError: database is locked`
            # while a sibling job checkpointed a 12 GiB WAL; both would have
            # completed had the wait been longer than 5s.
            # Reproduce by hand: open a write lock in one shell and run the
            # backfill in another —
            #     python3 -c "import sqlite3,time; c=sqlite3.connect('/home/konan/.hermes/ichor.db'); c.execute('BEGIN IMMEDIATE'); time.sleep(30)"
            #     python3 scripts/ichor_temporal_backfill.py --db-path ~/.hermes/ichor.db --apply
            if self.busy_timeout_ms is not None:
                self._conn.execute(
                    f"PRAGMA busy_timeout={int(self.busy_timeout_ms)};"
                )
            self._conn.row_factory = sqlite3.Row

            # Load and execute the schema DDL
            schema_path = os.path.join(
                os.path.dirname(__file__), "..", "schemas", "ichor-events.sql"
            )
            schema_path = os.path.normpath(schema_path)

            with open(schema_path, "r") as f:
                schema_sql = f.read()
            self._conn.executescript(schema_sql)
            # Additive Python migrations (ALTER TABLE etc.) — idempotent.
            self._run_schema_migrations(self._conn)
            self._conn.commit()

        return self._conn

    def _run_schema_migrations(self, conn: sqlite3.Connection) -> None:
        """Apply additive, migration-safe schema upgrades (idempotent).

        SQLite cannot reliably express ``ALTER TABLE ... ADD COLUMN IF NOT
        EXISTS``, so event temporal columns land here after the base schema
        executescripts. Indexes on those columns are created here too (they
        would fail inside executescript because the columns do not exist
        yet at that point).

        Called from ``connect()`` on every open — safe to run repeatedly.
        """
        # Event temporal columns (Phase 1 of the hindsight spec).
        _add_column_if_missing(conn, "ichor_events", "occurred_start", "occurred_start TEXT")
        _add_column_if_missing(conn, "ichor_events", "occurred_end", "occurred_end TEXT")
        _add_column_if_missing(conn, "ichor_events", "mentioned_at", "mentioned_at TEXT")
        _add_column_if_missing(conn, "ichor_events", "valid_from", "valid_from TEXT")
        _add_column_if_missing(conn, "ichor_events", "valid_until", "valid_until TEXT")
        _add_column_if_missing(conn, "ichor_events", "status", "status TEXT DEFAULT 'active'")
        _add_column_if_missing(
            conn, "ichor_events", "superseded_by",
            "superseded_by INTEGER REFERENCES ichor_events(id)",
        )
        # Content-hash column: lets the write path refuse duplicate content
        # instead of re-storing the same fragment every turn (2026-09-21).
        _add_column_if_missing(
            conn, "ichor_events", "content_hash", "content_hash TEXT",
        )

        # Indexes on the migrated columns.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ichor_events_valid_until ON ichor_events(valid_until)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ichor_events_status ON ichor_events(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ichor_events_mentioned_at ON ichor_events(mentioned_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ichor_events_occurred_range "
            "ON ichor_events(occurred_start, occurred_end)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ichor_events_content_hash "
            "ON ichor_events(content_hash)"
        )

    def insert_event(
        self,
        session_id: str,
        event_type: str,
        subject: str,
        predicate: Optional[str] = None,
        object: Optional[str] = None,
        confidence: float = 0.8,
        source: Optional[str] = None,
        raw_text: Optional[str] = None,
        god_name: Optional[str] = None,
        direction: Optional[str] = None,
        peer_god: Optional[str] = None,
        tags: Optional[list[str]] = None,
        occurred_start: Optional[str] = None,
        occurred_end: Optional[str] = None,
        mentioned_at: Optional[str] = None,
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
        status: str = "active",
        superseded_by: Optional[int] = None,
    ) -> int:
        """Insert a new event into the database.

        Validates event_type against the canonical VALID_EVENT_TYPES set
        defined at module level. Raises sqlite3.IntegrityError (rather than
        a custom exception) so callers can catch the standard SQLite error
        type and the test suite's `pytest.raises(sqlite3.IntegrityError)`
        contract remains stable.

        Hindsight memory upgrade (Phase 1/2): optional temporal fields and
        tags are persisted additively. When ``tags`` is omitted, safe
        ``god:<name>`` / ``session:<id>`` tags are inferred. ``mentioned_at``
        defaults to the row's creation time. ``user:<id>`` tags are never
        inferred — they require a trusted caller.

        Args:
            session_id: Identifier for the source god session.
            event_type: One of VALID_EVENT_TYPES (see module constant):
                blocker, commitment, decision, follow_up, correction,
                insight, fact, preference, reference, user_md_update.
            subject: The subject of the event (who or what the event is about).
            predicate: Optional relationship/predicate describing the event.
            object: Optional object of the relationship.
            confidence: Confidence score (0.0 to 1.0). Default 0.8.
            source: Origin tier — 'tier_a', 'tier_b', or 'manual'.
            raw_text: Original raw text the event was extracted from.
            god_name: Name of the god that generated this event.
            direction: Optional 'user→agent', 'agent→user', 'agent→agent', etc.
            peer_god: Optional peer god name for cross-god events.
            tags: Optional explicit tags (``scope:value`` form).
            occurred_start: Optional ISO timestamp when the event occurred (start).
            occurred_end: Optional ISO timestamp when the event occurred (end).
            mentioned_at: Optional ISO timestamp when the event was mentioned;
                defaults to the row's created_at when absent.
            valid_from: Optional ISO timestamp the event becomes valid.
            valid_until: Optional ISO timestamp the event expires.
            status: Row lifecycle status, default 'active'.
            superseded_by: Optional id of the event that supersedes this one.

        Returns:
            The row ID of the newly inserted event.

        Raises:
            sqlite3.IntegrityError: If event_type is not in VALID_EVENT_TYPES.
            sqlite3.Error: If the insert fails.
        """
        if event_type not in VALID_EVENT_TYPES:
            raise sqlite3.IntegrityError(
                f"Invalid event_type '{event_type}'. "
                f"Must be one of: {sorted(VALID_EVENT_TYPES)}"
            )
        conn = self.connect()
        # Dynamic column list — include optional fields if provided
        columns = [
            "session_id", "event_type", "subject", "predicate", "object",
            "confidence", "source", "raw_text", "god_name",
        ]
        values = [
            session_id, event_type, subject, predicate, object,
            confidence, source, raw_text, god_name,
        ]
        if direction is not None:
            columns.append("direction")
            values.append(direction)
        if peer_god is not None:
            columns.append("peer_god")
            values.append(peer_god)
        # Hindsight temporal + lifecycle fields (additive).
        if occurred_start is not None:
            columns.append("occurred_start")
            values.append(occurred_start)
        if occurred_end is not None:
            columns.append("occurred_end")
            values.append(occurred_end)
        if mentioned_at is not None:
            columns.append("mentioned_at")
            values.append(mentioned_at)
        if valid_from is not None:
            columns.append("valid_from")
            values.append(valid_from)
        if valid_until is not None:
            columns.append("valid_until")
            values.append(valid_until)
        if status is not None:
            columns.append("status")
            values.append(status)
        if superseded_by is not None:
            columns.append("superseded_by")
            values.append(superseded_by)
        # Always populate the content hash so the dedupe guard has an index to
        # hit regardless of which caller performed the insert.
        columns.append("content_hash")
        values.append(content_hash(raw_text))

        placeholders = ", ".join("?" * len(columns))
        col_list = ", ".join(columns)
        cursor = conn.execute(
            f"INSERT INTO ichor_events ({col_list}) VALUES ({placeholders})",
            values,
        )
        event_id = int(cursor.lastrowid)  # type: ignore[arg-type]

        # mentioned_at defaults to the row's creation time.
        if mentioned_at is None:
            row = conn.execute(
                "SELECT created_at FROM ichor_events WHERE id = ?", (event_id,)
            ).fetchone()
            created_at = row["created_at"] if row is not None else None
            if created_at:
                conn.execute(
                    "UPDATE ichor_events SET mentioned_at = ? WHERE id = ? AND mentioned_at IS NULL",
                    (created_at, event_id),
                )

        # Tags: explicit when supplied, otherwise infer safe god/session tags.
        if tags:
            final_tags = list(tags)
        else:
            from lib.ichor_tags import infer_event_tags
            final_tags = infer_event_tags(god_name=god_name, session_id=session_id)
        if final_tags:
            from lib.ichor_tags import attach_event_tags
            attach_event_tags(conn, event_id, final_tags)

        conn.commit()
        return event_id

    def query_fts(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Full-text search across events using FTS5.

        Performs a search on subject, predicate, object, and raw_text fields.

        Args:
            query: FTS5 search query string (supports FTS5 syntax like phrase matching).
            limit: Maximum number of results to return. Default 10.

        Returns:
            List of event dictionaries matching the search query.
        """
        conn = self.connect()
        cursor = conn.execute(
            """
            SELECT e.*
            FROM ichor_events e
            JOIN ichor_events_fts fts ON e.id = fts.rowid
            WHERE ichor_events_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_event_tags(self, event_id: int) -> list[str]:
        """Return normalized tags for one event (ordered by tag)."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT tag FROM ichor_event_tags WHERE event_id = ? ORDER BY tag",
            (int(event_id),),
        ).fetchall()
        return [str(r["tag"]) for r in rows]

    def fetch_event_tags(self, event_ids: list[int]) -> dict[int, list[str]]:
        """Return a mapping event_id → sorted tags for many events (one query)."""
        if not event_ids:
            return {}
        conn = self.connect()
        unique = list(dict.fromkeys(int(e) for e in event_ids))
        placeholders = ", ".join("?" * len(unique))
        rows = conn.execute(
            f"SELECT event_id, tag FROM ichor_event_tags "
            f"WHERE event_id IN ({placeholders}) ORDER BY tag",
            unique,
        ).fetchall()
        out: dict[int, list[str]] = {eid: [] for eid in unique}
        for row in rows:
            out[int(row["event_id"])].append(str(row["tag"]))
        return out

    def query_by_session(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieve all events for a given session.

        Args:
            session_id: The session identifier to look up.

        Returns:
            List of event dictionaries for the specified session,
            ordered by creation time.
        """
        conn = self.connect()
        cursor = conn.execute(
            """
            SELECT * FROM ichor_events
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def query_by_type(self, event_type: str, limit: int = 50) -> list[dict[str, Any]]:
        """Filter events by type.

        Args:
            event_type: One of 'decision', 'commitment', 'preference', 'fact', 'correction'.
            limit: Maximum number of results to return. Default 50.

        Returns:
            List of event dictionaries matching the type.
        """
        conn = self.connect()
        cursor = conn.execute(
            """
            SELECT * FROM ichor_events
            WHERE event_type = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (event_type, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get the most recent events.

        Args:
            limit: Maximum number of results to return. Default 20.

        Returns:
            List of the most recent event dictionaries.
        """
        conn = self.connect()
        cursor = conn.execute(
            """
            SELECT * FROM ichor_events
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def count(self) -> int:
        """Return the total number of events in the database.

        Returns:
            Total event count.
        """
        conn = self.connect()
        cursor = conn.execute("SELECT COUNT(*) AS cnt FROM ichor_events")
        row = cursor.fetchone()
        return row["cnt"] if row else 0

    def close(self) -> None:
        """Close the database connection if it is open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
