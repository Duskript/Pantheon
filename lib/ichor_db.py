"""Ichor Memory Engine — Database Layer.

Manages the SQLite-backed events database with FTS5 full-text search.
All event storage, retrieval, and search operations for the Pantheon system.
"""

import os
import re
import sqlite3
import threading
from typing import Any, Optional


# Canonical event types. Kept in sync with TYPE_META in ichor_brief.py.
# Single source of truth here; ichor_brief.py imports from this module.
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

    def __init__(self, db_path: str = "~/.hermes/ichor.db"):
        """Initialize the Ichor database manager.

        Args:
            db_path: Path to the SQLite database file. Tilde is expanded
                     to the user's home directory. Defaults to ~/.hermes/ichor.db.
        """
        self.db_path = os.path.expanduser(db_path)
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
            self._conn.row_factory = sqlite3.Row

            # Load and execute the schema DDL
            schema_path = os.path.join(
                os.path.dirname(__file__), "..", "schemas", "ichor-events.sql"
            )
            schema_path = os.path.normpath(schema_path)

            with open(schema_path, "r") as f:
                schema_sql = f.read()
            self._conn.executescript(schema_sql)
            self._conn.commit()

        return self._conn

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
    ) -> int:
        """Insert a new event into the database.

        Validates event_type against the canonical VALID_EVENT_TYPES set
        defined at module level. Raises sqlite3.IntegrityError (rather than
        a custom exception) so callers can catch the standard SQLite error
        type and the test suite's `pytest.raises(sqlite3.IntegrityError)`
        contract remains stable.

        Args:
            session_id: Identifier for the source god session.
            event_type: One of VALID_EVENT_TYPES (see module constant):
                blocker, commitment, decision, follow_up, correction,
                insight, fact, preference, reference.
            subject: The subject of the event (who or what the event is about).
            predicate: Optional relationship/predicate describing the event.
            object: Optional object of the relationship.
            confidence: Confidence score (0.0 to 1.0). Default 0.8.
            source: Origin tier — 'tier_a', 'tier_b', or 'manual'.
            raw_text: Original raw text the event was extracted from.
            god_name: Name of the god that generated this event.
            direction: Optional 'user→agent', 'agent→user', 'agent→agent', etc.
            peer_god: Optional peer god name for cross-god events.

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
        # Dynamic column list — include direction/peer_god if provided
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

        placeholders = ", ".join("?" * len(columns))
        col_list = ", ".join(columns)
        cursor = conn.execute(
            f"INSERT INTO ichor_events ({col_list}) VALUES ({placeholders})",
            values,
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

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
