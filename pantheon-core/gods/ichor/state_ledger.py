"""
State Ledger — renders the current entity graph as a structured prompt preamble.

Used by: LedgerAgent pattern — injects current state into every session's
system prompt so the agent doesn't have to reconstruct state from context.

Spec: ichor-v2-build-blueprint.md §7 (Phase 5).

Four sections rendered per god:
  1. Active Blockers       (event_type='blocker', importance >= 30)
  2. Recent Decisions      (event_type='decision', last 7 days)
  3. Active Commitments    (event_type='commitment', importance >= 20)
  4. Key Relationships     (top warm_entities by importance)

Schema notes (drift from blueprint §7):
  - Spec referenced `ichor_events.content` but the live schema uses
    `ichor_events.raw_text`. This module uses `raw_text`.
  - Spec referenced `graph_entities` but the live schema (lib/ichor/
    schema_v2.py) uses `warm_entities` as the single source of truth for
    validated entities (Rule 43). `warm_entities` carries `importance`
    (0-100 scale, default 50) and is the right input here. It does NOT
    have a `god_name` column, so the relationships section is intentionally
    god-agnostic — top-importance entities shared across all gods. Per-god
    entity scoping is a forward-compatible addition once the entities
    table grows a god_name column (Phase 3+).
  - `importance` is on a 0-100 scale in the live schema (default 50), not
    0.0-1.0 as the blueprint snippet implied. Thresholds are scaled
    accordingly: `> 30` for blockers (~ top 30%), `> 20` for commitments.

Performance:
  - Each render opens one sqlite3 connection.
  - No caching — `build_system_prompt()` callers control memoization.
  - SQLite read-only mode (`mode=ro`) for safety.

Usage:
    from gods.ichor.state_ledger import render_god_ledger
    print(render_god_ledger('hermes'))

    from gods.ichor.state_ledger import render_all_gods_ledger
    print(render_all_gods_ledger())
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────────────────

# Default DB location: ~/.hermes/ichor.db. Override per-call with db_path=...
ICHOR_DB: Path = Path.home() / ".hermes" / "ichor.db"

# Cap preamble at 2000 chars so it stays well under typical LLM context budgets.
MAX_PREAMBLE_CHARS: int = 2000

# Per-section item caps (keeps each section scannable even with high event volume).
MAX_BLOCKERS: int = 5
MAX_DECISIONS: int = 5
MAX_COMMITMENTS: int = 5
MAX_ENTITIES: int = 10

# Importance thresholds — live schema uses 0-100 scale (default 50).
BLOCKER_MIN_IMPORTANCE: float = 30.0       # top ~30% by default
COMMITMENT_MIN_IMPORTANCE: float = 20.0    # top ~50% by default

# Recent decisions window (days).
DECISION_WINDOW_DAYS: int = 7

# Display limits for text fields (per spec).
SUBJECT_MAX: int = 80
TEXT_MAX: int = 200

# Section headers — pinned in spec §7.
HEADER_BLOCKERS = "### ⛔ Active Blockers"
HEADER_DECISIONS = "### ✅ Recent Decisions"
HEADER_COMMITMENTS = "### 📋 Active Commitments"
HEADER_ENTITIES = "### 🔗 Key Relationships"


# ────────────────────────────────────────────────────────────────────────────
# Connection helpers
# ────────────────────────────────────────────────────────────────────────────


def _open_ro(db_path: Path) -> sqlite3.Connection:
    """Open ichor.db in read-only mode.

    Uses URI mode=ro so a missing DB or permission issue fails loudly at
    connect time, not after we've executed queries. Returns a Row-factory
    connection so we can address columns by name.
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _resolve_db(db_path: Optional[str]) -> Path:
    """Resolve the DB path, falling back to the default."""
    return Path(db_path) if db_path else ICHOR_DB


# ────────────────────────────────────────────────────────────────────────────
# Section renderers (one per ledger section)
# ────────────────────────────────────────────────────────────────────────────


def _truncate(text: Optional[str], max_len: int) -> str:
    """Trim text to max_len, ellipsis if cut, with empty-string fallback."""
    if not text:
        return ""
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0]
    return (cut or text[:max_len]).rstrip(",;:.- ") + "…"


def _fetch_blockers(
    conn: sqlite3.Connection, god_name: str, limit: int = MAX_BLOCKERS
) -> List[Tuple[str, str, str]]:
    """Active blockers for this god, highest importance first."""
    try:
        cursor = conn.execute(
            """
            SELECT subject, raw_text, created_at
            FROM ichor_events
            WHERE god_name = ?
              AND event_type = 'blocker'
              AND importance >= ?
            ORDER BY importance DESC, created_at DESC
            LIMIT ?
            """,
            (god_name, BLOCKER_MIN_IMPORTANCE, limit),
        )
        return [(r["subject"], r["raw_text"] or "", r["created_at"] or "")
                for r in cursor.fetchall()]
    except sqlite3.OperationalError as exc:
        logger.warning("blockers query failed for god=%s: %s", god_name, exc)
        return []


def _fetch_decisions(
    conn: sqlite3.Connection,
    god_name: str,
    limit: int = MAX_DECISIONS,
    reference_now: str | None = None,
) -> List[Tuple[str, str, str]]:
    """Recent decisions (last 7 days) for this god, newest first.

    Args:
        conn: Read-only SQLite connection.
        god_name: God identifier.
        limit: Max decisions to return.
        reference_now: Optional ISO-8601 timestamp to use as the
            reference point for the 7-day window. When None, uses
            SQLite's ``datetime('now')``. Tests can inject a fixed
            timestamp to keep the window stable.
    """
    try:
        if reference_now is None:
            cursor = conn.execute(
                f"""
                SELECT subject, raw_text, created_at
                FROM ichor_events
                WHERE god_name = ?
                  AND event_type = 'decision'
                  AND created_at >= datetime('now', '-{DECISION_WINDOW_DAYS} days')
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (god_name, limit),
            )
        else:
            cursor = conn.execute(
                f"""
                SELECT subject, raw_text, created_at
                FROM ichor_events
                WHERE god_name = ?
                  AND event_type = 'decision'
                  AND created_at >= datetime(?, '-{DECISION_WINDOW_DAYS} days')
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (god_name, reference_now, limit),
            )
        return [(r["subject"], r["raw_text"] or "", r["created_at"] or "")
                for r in cursor.fetchall()]
    except sqlite3.OperationalError as exc:
        logger.warning("decisions query failed for god=%s: %s", god_name, exc)
        return []


def _fetch_commitments(
    conn: sqlite3.Connection, god_name: str, limit: int = MAX_COMMITMENTS
) -> List[Tuple[str, str, str]]:
    """Active commitments for this god, newest first."""
    try:
        cursor = conn.execute(
            """
            SELECT subject, raw_text, created_at
            FROM ichor_events
            WHERE god_name = ?
              AND event_type = 'commitment'
              AND importance >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (god_name, COMMITMENT_MIN_IMPORTANCE, limit),
        )
        return [(r["subject"], r["raw_text"] or "", r["created_at"] or "")
                for r in cursor.fetchall()]
    except sqlite3.OperationalError as exc:
        logger.warning("commitments query failed for god=%s: %s", god_name, exc)
        return []


def _fetch_key_entities(
    conn: sqlite3.Connection, _god_name: str, limit: int = MAX_ENTITIES
) -> List[Tuple[str, str]]:
    """Top-importance warm_entities.

    Note: warm_entities is intentionally god-agnostic (no god_name column).
    See module docstring for why this section shows shared top entities
    rather than god-filtered ones. Phase 3+ will add god_name scoping
    once the entities table grows the column.
    """
    try:
        cursor = conn.execute(
            """
            SELECT name, related_to
            FROM warm_entities
            WHERE importance >= 0
              AND (related_to IS NOT NULL AND related_to != '')
            ORDER BY importance DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [(r["name"], r["related_to"]) for r in cursor.fetchall()]
    except sqlite3.OperationalError as exc:
        logger.warning("entities query failed: %s", exc)
        return []


def _render_section_blockers(rows: List[Tuple[str, str, str]]) -> str:
    """Format the blockers section as markdown."""
    lines = [HEADER_BLOCKERS]
    for subject, raw_text, ts in rows:
        subj = _truncate(subject, SUBJECT_MAX)
        body = _truncate(raw_text, TEXT_MAX)
        ts_short = (ts or "")[:16]
        if body:
            lines.append(f"- **{subj}** — {body} ({ts_short})")
        else:
            lines.append(f"- **{subj}** ({ts_short})")
    return "\n".join(lines)


def _render_section_decisions(rows: List[Tuple[str, str, str]]) -> str:
    """Format the decisions section as markdown."""
    lines = [HEADER_DECISIONS]
    for subject, raw_text, ts in rows:
        subj = _truncate(subject, SUBJECT_MAX)
        body = _truncate(raw_text, TEXT_MAX)
        ts_short = (ts or "")[:16]
        if body:
            lines.append(f"- **{subj}** — {body} ({ts_short})")
        else:
            lines.append(f"- **{subj}** ({ts_short})")
    return "\n".join(lines)


def _render_section_commitments(rows: List[Tuple[str, str, str]]) -> str:
    """Format the commitments section as markdown."""
    lines = [HEADER_COMMITMENTS]
    for subject, raw_text, ts in rows:
        subj = _truncate(subject, SUBJECT_MAX)
        body = _truncate(raw_text, TEXT_MAX)
        ts_short = (ts or "")[:16]
        if body:
            lines.append(f"- **{subj}** — {body} ({ts_short})")
        else:
            lines.append(f"- **{subj}** ({ts_short})")
    return "\n".join(lines)


def _render_section_entities(rows: List[Tuple[str, str]]) -> str:
    """Format the key relationships section as markdown.

    Schema has no relationship_type column on warm_entities — the related_to
    field is a comma-separated string. We render it verbatim. Phase 3+ will
    add explicit relationship typing via the `entities` + `relationships`
    tables (ER-P3 graph layer).
    """
    lines = [HEADER_ENTITIES]
    for name, related in rows:
        nm = _truncate(name, SUBJECT_MAX)
        rel = _truncate(related, TEXT_MAX)
        lines.append(f"- **{nm}** → {rel}")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
# Main renderers
# ────────────────────────────────────────────────────────────────────────────


def render_god_ledger(
    god_name: str,
    db_path: Optional[str] = None,
    reference_now: Optional[str] = None,
) -> str:
    """Render a god's current state as a markdown preamble.

    Sections (only included when they have rows):
      1. Active Blockers       (importance >= 30, top 5 by importance)
      2. Recent Decisions      (last 7 days, top 5 by recency)
      3. Active Commitments    (importance >= 20, top 5 by recency)
      4. Key Relationships     (top 10 warm_entities by importance)

    The returned string is capped at MAX_PREAMBLE_CHARS (2000) and
    suffixed with "\\\\n\\\\n... [truncated]" if cut. Returns an empty string
    if the DB is missing or the god has no entries anywhere (and no
    top entities exist either).

    Args:
        god_name: God identifier (e.g. 'hermes', 'hephaestus', 'marvin').
        db_path: Optional explicit path to ichor.db. Defaults to
                 ``~/.hermes/ichor.db``.
        reference_now: Optional ISO-8601 timestamp to use as the
            reference point for the 7-day decisions window. When None,
            uses SQLite's ``datetime('now')``. Tests can inject a fixed
            timestamp to keep the window stable.

    Returns:
        A markdown string with the populated sections, or "" if nothing to show.
    """
    if not god_name:
        return ""

    db = _resolve_db(db_path)
    if not db.exists():
        logger.debug("ichor.db not found at %s — empty ledger", db)
        return ""

    try:
        conn = _open_ro(db)
    except sqlite3.OperationalError as exc:
        logger.warning("could not open ichor.db at %s: %s", db, exc)
        return ""

    sections: List[str] = []
    try:
        blockers = _fetch_blockers(conn, god_name)
        if blockers:
            sections.append(_render_section_blockers(blockers))

        decisions = _fetch_decisions(conn, god_name, reference_now=reference_now)
        if decisions:
            sections.append(_render_section_decisions(decisions))

        commitments = _fetch_commitments(conn, god_name)
        if commitments:
            sections.append(_render_section_commitments(commitments))

        entities = _fetch_key_entities(conn, god_name)
        if entities:
            sections.append(_render_section_entities(entities))
    finally:
        conn.close()

    if not sections:
        return ""

    preamble = "\n\n".join(sections)
    if len(preamble) > MAX_PREAMBLE_CHARS:
        preamble = preamble[:MAX_PREAMBLE_CHARS] + "\n\n... [truncated]"
    return preamble


def render_all_gods_ledger(
    db_path: Optional[str] = None,
) -> Dict[str, str]:
    """Render ledgers for every god that has any ichor_events.

    Used by the system-prompt builder when the active god is unknown
    (e.g. dispatcher, conductor). Iterates over the distinct god_name
    set in ichor_events and renders each one. Returns an empty dict
    if the DB is missing or no events exist.

    Args:
        db_path: Optional explicit path to ichor.db.

    Returns:
        Dict mapping god_name → markdown ledger string.
    """
    db = _resolve_db(db_path)
    if not db.exists():
        return {}

    try:
        conn = _open_ro(db)
    except sqlite3.OperationalError as exc:
        logger.warning("could not open ichor.db at %s: %s", db, exc)
        return {}

    try:
        cursor = conn.execute(
            """
            SELECT DISTINCT god_name
            FROM ichor_events
            WHERE god_name IS NOT NULL AND god_name != ''
            ORDER BY god_name
            """
        )
        gods = [row["god_name"] for row in cursor.fetchall()]
    finally:
        conn.close()

    return {god: render_god_ledger(god, str(db)) for god in gods}


# ────────────────────────────────────────────────────────────────────────────
# JSON form for MCP tool / programmatic consumers
# ────────────────────────────────────────────────────────────────────────────


def render_god_ledger_structured(
    god_name: str,
    db_path: Optional[str] = None,
    reference_now: Optional[str] = None,
) -> Dict[str, Any]:
    """Render a god's state as a structured dict (not markdown).

    Returns:
        {
          "god_name": str,
          "db_path": str,
          "blockers":     [{"subject", "raw_text", "created_at", "importance"}],
          "decisions":    [{"subject", "raw_text", "created_at"}],
          "commitments":  [{"subject", "raw_text", "created_at", "importance"}],
          "entities":     [{"name", "related_to", "importance"}],
          "counts":       {"blockers": N, "decisions": N, "commitments": N, "entities": N},
        }
    """
    if not god_name:
        return {"god_name": "", "blockers": [], "decisions": [],
                "commitments": [], "entities": [], "counts": {}}

    db = _resolve_db(db_path)
    out: Dict[str, Any] = {
        "god_name": god_name,
        "db_path": str(db),
        "blockers": [],
        "decisions": [],
        "commitments": [],
        "entities": [],
        "counts": {},
    }
    if not db.exists():
        return out

    try:
        conn = _open_ro(db)
    except sqlite3.OperationalError:
        return out

    try:
        # Blockers — include importance for ranking visibility
        try:
            cursor = conn.execute(
                """
                SELECT subject, raw_text, created_at, importance
                FROM ichor_events
                WHERE god_name = ? AND event_type = 'blocker'
                  AND importance >= ?
                ORDER BY importance DESC, created_at DESC
                LIMIT ?
                """,
                (god_name, BLOCKER_MIN_IMPORTANCE, MAX_BLOCKERS),
            )
            out["blockers"] = [dict(r) for r in cursor.fetchall()]
        except sqlite3.OperationalError:
            pass

        # Decisions
        try:
            if reference_now is None:
                cursor = conn.execute(
                    f"""
                    SELECT subject, raw_text, created_at
                    FROM ichor_events
                    WHERE god_name = ? AND event_type = 'decision'
                      AND created_at >= datetime('now', '-{DECISION_WINDOW_DAYS} days')
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (god_name, MAX_DECISIONS),
                )
            else:
                cursor = conn.execute(
                    f"""
                    SELECT subject, raw_text, created_at
                    FROM ichor_events
                    WHERE god_name = ? AND event_type = 'decision'
                      AND created_at >= datetime(?, '-{DECISION_WINDOW_DAYS} days')
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (god_name, reference_now, MAX_DECISIONS),
                )
            out["decisions"] = [dict(r) for r in cursor.fetchall()]
        except sqlite3.OperationalError:
            pass

        # Commitments
        try:
            cursor = conn.execute(
                """
                SELECT subject, raw_text, created_at, importance
                FROM ichor_events
                WHERE god_name = ? AND event_type = 'commitment'
                  AND importance >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (god_name, COMMITMENT_MIN_IMPORTANCE, MAX_COMMITMENTS),
            )
            out["commitments"] = [dict(r) for r in cursor.fetchall()]
        except sqlite3.OperationalError:
            pass

        # Entities
        try:
            cursor = conn.execute(
                """
                SELECT name, related_to, importance
                FROM warm_entities
                WHERE importance >= 0
                  AND (related_to IS NOT NULL AND related_to != '')
                ORDER BY importance DESC
                LIMIT ?
                """,
                (MAX_ENTITIES,),
            )
            out["entities"] = [dict(r) for r in cursor.fetchall()]
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()

    out["counts"] = {
        "blockers": len(out["blockers"]),
        "decisions": len(out["decisions"]),
        "commitments": len(out["commitments"]),
        "entities": len(out["entities"]),
    }
    return out


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point.

    Usage:
        python3 -m gods.ichor.state_ledger --god hermes
        python3 -m gods.ichor.state_ledger --god hermes --json
        python3 -m gods.ichor.state_ledger --all
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Render a god's Ichor state ledger as markdown."
    )
    parser.add_argument(
        "--god", "-g", default="",
        help="God name to render the ledger for (e.g. 'hermes').",
    )
    parser.add_argument(
        "--db", default="",
        help="Path to ichor.db (default: ~/.hermes/ichor.db).",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Render ledgers for all gods that have events.",
    )
    parser.add_argument(
        "--json", "-j", action="store_true",
        help="Output structured JSON instead of markdown.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    db_path = args.db or None

    if args.all:
        if args.json:
            ledgers = render_all_gods_ledger(db_path)
            print(json.dumps({g: render_god_ledger_structured(g, db_path)
                              for g in ledgers}, indent=2, default=str))
        else:
            ledgers = render_all_gods_ledger(db_path)
            for god, ledger in ledgers.items():
                print(f"\n=== {god} ===\n")
                print(ledger)
        return

    if not args.god:
        parser.error("--god NAME is required (or use --all)")

    if args.json:
        print(json.dumps(
            render_god_ledger_structured(args.god, db_path),
            indent=2,
            default=str,
        ))
    else:
        print(render_god_ledger(args.god, db_path))


if __name__ == "__main__":
    main()