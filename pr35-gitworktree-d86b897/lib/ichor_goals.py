"""Ichor Goals Registry — Strategic goals tracked across sessions (Track A / A1).

This is a NEW, parallel goals system. It is intentionally distinct from
`hermes_cli/goals.py` (the per-turn judge). Spec:
    ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md §A1

Design principles:
- One SQLite table (`strategic_goals`) in `ichor.db`
- `cold_events.goal_id` is a nullable FK linking events to the goal they
  advance (added in the A1 migration — see `lib.ichor.schema_v2` (was `lib/ichor_schema_v2.py`))
- `IchorGoals` class is the canonical Python entry point — same shape as
  `IchorDB` for consistency
- `format_active_goals_preamble()` produces the markdown block for system
  prompt injection at session start
- Exposed as MCP tool `ichor_goal` (see `pantheon-core/mcp_server.py`)

Usage (Python):
    from lib.ichor_goals import IchorGoals, format_active_goals_preamble
    g = IchorGoals()
    gid = g.add("Ship A2", category="theoforge", priority=8, target_date="2026-06-30")
    g.update_progress(gid, 0.4)
    goals = g.list_active(limit=5, min_priority=3)
    md = format_active_goals_preamble(goals)  # for system prompt injection

Usage (CLI):
    python3 ~/pantheon/lib/ichor_goals.py add "Ship A2" --priority 8 --category theoforge
    python3 ~/pantheon/lib/ichor_goals.py list
    python3 ~/pantheon/lib/ichor_goals.py complete "Ship A2"
    python3 ~/pantheon/lib/ichor_goals.py inject --max 5 --min-priority 3   # for session-start
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ichor_goals")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HOME = Path.home()
_ICHOR_DB = _HOME / ".hermes" / "ichor.db"

VALID_STATUSES = frozenset({"active", "paused", "completed", "abandoned"})
VALID_CATEGORIES = frozenset({"general", "theoforge", "pantheon", "skc"})

# Defaults — can be overridden by caller
DEFAULT_MAX_INJECTED = 5
DEFAULT_MIN_PRIORITY = 3


# ---------------------------------------------------------------------------
# Goal CRUD
# ---------------------------------------------------------------------------


class IchorGoals:
    """CRUD for the `strategic_goals` table in `ichor.db`.

    Mirrors the pattern of `lib.ichor_db.IchorDB`: connect-on-first-use,
    WAL mode, Row factory. Uses the same `ichor.db` connection that
    `cold_events` and `ichor_events` live in — strategic_goals is one
    of the tables in the 5-tier schema (added in A1).
    """

    def __init__(self, db_path: str = str(_ICHOR_DB)):
        self.db_path = os.path.expanduser(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row
        # Ensure the table exists (idempotent — schema v2 also creates it)
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS strategic_goals (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                category TEXT DEFAULT 'general',
                priority INTEGER DEFAULT 5,
                status TEXT DEFAULT 'active',
                progress REAL DEFAULT 0.0,
                target_date TEXT DEFAULT '',
                started_at TEXT DEFAULT (datetime('now')),
                completed_at TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
        """)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --- Create / Read / Update / Delete ---

    def add(
        self,
        title: str,
        description: str = "",
        category: str = "general",
        priority: int = 5,
        target_date: str = "",
    ) -> int:
        """Create a new strategic goal. Returns the new row id.

        Args:
            title: Required. Short, human-readable goal title.
            description: Optional. Longer description / acceptance criteria.
            category: One of VALID_CATEGORIES. Default 'general'.
            priority: 1-10. Default 5. 1=lowest, 10=highest.
            target_date: Optional ISO date string (YYYY-MM-DD).

        Raises:
            ValueError: if title is empty or category is invalid.
        """
        if not title or not title.strip():
            raise ValueError("title is required and must be non-empty")
        if category not in VALID_CATEGORIES:
            raise ValueError(
                f"invalid category '{category}'. Must be one of: {sorted(VALID_CATEGORIES)}"
            )
        if not (1 <= priority <= 10):
            raise ValueError(f"priority must be 1-10, got {priority}")
        conn = self.connect()
        cur = conn.execute(
            """
            INSERT INTO strategic_goals
                (title, description, category, priority, target_date)
            VALUES (?, ?, ?, ?, ?)
            """,
            (title.strip(), description.strip(), category, priority, target_date.strip()),
        )
        conn.commit()
        return int(cur.lastrowid)  # type: ignore[return-value]

    def get(self, goal_id: int) -> Optional[Dict[str, Any]]:
        """Return the goal row as a dict, or None if not found."""
        conn = self.connect()
        row = conn.execute(
            "SELECT * FROM strategic_goals WHERE id = ?", (goal_id,)
        ).fetchone()
        return dict(row) if row else None

    def find_by_title(self, title: str, exact: bool = True) -> Optional[Dict[str, Any]]:
        """Return the first goal whose title matches. `exact=True` does an
        exact-match query; `exact=False` does a LIKE %title% search.
        """
        conn = self.connect()
        if exact:
            row = conn.execute(
                "SELECT * FROM strategic_goals WHERE title = ? ORDER BY id LIMIT 1",
                (title,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM strategic_goals WHERE title LIKE ? ORDER BY id LIMIT 1",
                (f"%{title}%",),
            ).fetchone()
        return dict(row) if row else None

    def list(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List goals, optionally filtered by status / category. Ordered by
        priority DESC (highest first), then id ASC.
        """
        if status is not None and status not in VALID_STATUSES:
            raise ValueError(
                f"invalid status '{status}'. Must be one of: {sorted(VALID_STATUSES)}"
            )
        conn = self.connect()
        clauses = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if category:
            clauses.append("category = ?")
            params.append(category)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT * FROM strategic_goals{where} "
            "ORDER BY priority DESC, id ASC LIMIT ?"
        )
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def list_active(
        self, limit: int = DEFAULT_MAX_INJECTED, min_priority: int = DEFAULT_MIN_PRIORITY
    ) -> List[Dict[str, Any]]:
        """Return active goals (status='active') with priority >= min_priority,
        ordered by priority DESC. Used by `format_active_goals_preamble()`.
        """
        conn = self.connect()
        rows = conn.execute(
            """
            SELECT * FROM strategic_goals
            WHERE status = 'active' AND priority >= ?
            ORDER BY priority DESC, id ASC
            LIMIT ?
            """,
            (min_priority, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def update(
        self,
        goal_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        priority: Optional[int] = None,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        target_date: Optional[str] = None,
    ) -> bool:
        """Update fields on a goal. Returns True if a row was changed.

        Any field passed as None is left unchanged. If status is set to
        'completed' or 'abandoned' and `completed_at` isn't already set,
        it is auto-stamped.
        """
        if status is not None and status not in VALID_STATUSES:
            raise ValueError(
                f"invalid status '{status}'. Must be one of: {sorted(VALID_STATUSES)}"
            )
        if category is not None and category not in VALID_CATEGORIES:
            raise ValueError(
                f"invalid category '{category}'. Must be one of: {sorted(VALID_CATEGORIES)}"
            )
        if priority is not None and not (1 <= priority <= 10):
            raise ValueError(f"priority must be 1-10, got {priority}")
        if progress is not None and not (0.0 <= progress <= 1.0):
            raise ValueError(f"progress must be 0.0-1.0, got {progress}")

        fields: List[str] = []
        params: List[Any] = []
        for col, val in [
            ("title", title), ("description", description), ("category", category),
            ("priority", priority), ("status", status), ("progress", progress),
            ("target_date", target_date),
        ]:
            if val is not None:
                fields.append(f"{col} = ?")
                params.append(val)
        if not fields:
            return False
        # Auto-stamp completed_at when transitioning to completed
        if status in ("completed", "abandoned"):
            fields.append("completed_at = COALESCE(completed_at, datetime('now'))")
        fields.append("updated_at = datetime('now')")
        params.append(goal_id)
        conn = self.connect()
        cur = conn.execute(
            f"UPDATE strategic_goals SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()
        return cur.rowcount > 0

    def update_progress(self, goal_id: int, progress: float) -> bool:
        """Convenience: set progress (0.0-1.0) and stamp updated_at."""
        return self.update(goal_id, progress=progress)

    def complete(self, title_or_id: Any) -> bool:
        """Mark a goal complete. Accepts either an int (id) or a str (title)."""
        if isinstance(title_or_id, int):
            return self.update(title_or_id, status="completed", progress=1.0)
        # Find by title (exact match first, then LIKE fallback)
        goal = self.find_by_title(str(title_or_id), exact=True)
        if not goal:
            goal = self.find_by_title(str(title_or_id), exact=False)
        if not goal:
            return False
        return self.update(goal["id"], status="completed", progress=1.0)

    def pause(self, title_or_id: Any) -> bool:
        """Mark a goal paused."""
        if isinstance(title_or_id, int):
            return self.update(title_or_id, status="paused")
        goal = self.find_by_title(str(title_or_id), exact=True)
        if not goal:
            return False
        return self.update(goal["id"], status="paused")

    def delete(self, goal_id: int) -> bool:
        """Hard-delete a goal. Prefer `complete()` or `update(status='abandoned')`."""
        conn = self.connect()
        cur = conn.execute("DELETE FROM strategic_goals WHERE id = ?", (goal_id,))
        conn.commit()
        return cur.rowcount > 0

    def stats(self) -> Dict[str, Any]:
        """Counts by status. Used by health checks / dashboards."""
        conn = self.connect()
        rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM strategic_goals GROUP BY status"
        ).fetchall()
        out: Dict[str, Any] = {"by_status": {r["status"]: r["cnt"] for r in rows},
                               "total": sum(r["cnt"] for r in rows)}
        return out


# ---------------------------------------------------------------------------
# Preamble formatting (system-prompt injection)
# ---------------------------------------------------------------------------


def format_active_goals_preamble(
    goals: Optional[List[Dict[str, Any]]] = None,
    max_injected: int = DEFAULT_MAX_INJECTED,
    min_priority: int = DEFAULT_MIN_PRIORITY,
) -> str:
    """Build the markdown block injected into the system prompt at session start.

    Spec format:
        ## Active Goals (N)
        1. 🎯 {title} — Priority {p}, {progress*100}% complete
           {description}
           {if target_date} Target: {date}

    If no active goals, returns an empty string (don't pollute the prompt
    with an empty section).
    """
    if goals is None:
        goals = IchorGoals().list_active(limit=max_injected, min_priority=min_priority)
    if not goals:
        return ""
    lines = [f"## Active Goals ({len(goals)})"]
    for i, g in enumerate(goals, start=1):
        title = g.get("title", "?")
        priority = g.get("priority", "?")
        progress = float(g.get("progress", 0.0))
        pct = int(round(progress * 100))
        desc = (g.get("description") or "").strip()
        target = (g.get("target_date") or "").strip()
        lines.append(
            f"{i}. 🎯 {title} — Priority {priority}, {pct}% complete"
        )
        if desc:
            # Indent description and wrap at ~95 chars
            for chunk in _wrap(desc, 95):
                lines.append(f"   {chunk}")
        if target:
            lines.append(f"   Target: {target}")
    return "\n".join(lines) + "\n"


def _wrap(text: str, width: int) -> List[str]:
    """Cheap text wrapper — splits on whitespace, joins back into lines."""
    words = text.split()
    if not words:
        return []
    out: List[str] = []
    cur = ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur = f"{cur} {w}"
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------------------
# MCP tool entry point (used by pantheon-core/mcp_server.py)
# ---------------------------------------------------------------------------


def mcp_dispatch(
    action: str,
    title: str = "",
    goal_id: int = 0,
    description: str = "",
    category: str = "general",
    priority: int = 5,
    status: str = "",
    progress: float = -1.0,
    target_date: str = "",
    limit: int = DEFAULT_MAX_INJECTED,
    min_priority: int = DEFAULT_MIN_PRIORITY,
) -> str:
    """Dispatch an MCP ichor_goal call. Returns JSON.

    Actions: add | list | get | update | complete | pause | inject | stats.
    """
    g = IchorGoals()
    try:
        if action == "add":
            if not title:
                return json.dumps({"error": "title is required for action=add"})
            gid = g.add(
                title=title, description=description, category=category,
                priority=priority, target_date=target_date,
            )
            return json.dumps({"ok": True, "id": gid, "title": title,
                               "category": category, "priority": priority})
        elif action == "list":
            goals = g.list(
                status=status or None,
                category=category or None,
                limit=limit,
            )
            return json.dumps({"ok": True, "count": len(goals), "goals": goals},
                              indent=2, default=str)
        elif action == "get":
            if not goal_id:
                return json.dumps({"error": "goal_id required for action=get"})
            goal = g.get(goal_id)
            if not goal:
                return json.dumps({"ok": False, "error": f"goal {goal_id} not found"})
            return json.dumps({"ok": True, "goal": goal}, indent=2, default=str)
        elif action == "update":
            if not goal_id:
                return json.dumps({"error": "goal_id required for action=update"})
            kwargs: Dict[str, Any] = {}
            if title: kwargs["title"] = title
            if description: kwargs["description"] = description
            if category and category != "general": kwargs["category"] = category
            if priority != 5: kwargs["priority"] = priority
            if status: kwargs["status"] = status
            if progress >= 0.0: kwargs["progress"] = progress
            if target_date: kwargs["target_date"] = target_date
            if not kwargs:
                return json.dumps({"error": "no fields to update"})
            ok = g.update(goal_id, **kwargs)
            return json.dumps({"ok": ok, "goal_id": goal_id, "updated_fields": list(kwargs.keys())})
        elif action == "complete":
            if not (title or goal_id):
                return json.dumps({"error": "title or goal_id required for action=complete"})
            ok = g.complete(goal_id if goal_id else title)
            return json.dumps({"ok": ok, "completed": title or goal_id})
        elif action == "pause":
            if not (title or goal_id):
                return json.dumps({"error": "title or goal_id required for action=pause"})
            ok = g.pause(goal_id if goal_id else title)
            return json.dumps({"ok": ok, "paused": title or goal_id})
        elif action == "inject":
            md = format_active_goals_preamble(
                max_injected=limit, min_priority=min_priority,
            )
            return json.dumps({
                "ok": True,
                "preamble": md,
                "injected": bool(md),
                "max_injected": limit,
                "min_priority": min_priority,
            })
        elif action == "stats":
            return json.dumps({"ok": True, "stats": g.stats()}, indent=2)
        else:
            return json.dumps({
                "error": f"unknown action '{action}'. "
                         f"Valid: add | list | get | update | complete | pause | inject | stats"
            })
    except (ValueError, sqlite3.Error) as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ichor Goals Registry — strategic goals (Track A / A1)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Create a new goal")
    p_add.add_argument("title", help="Goal title (required)")
    p_add.add_argument("--description", "-d", default="")
    p_add.add_argument("--category", "-c", default="general",
                       choices=sorted(VALID_CATEGORIES))
    p_add.add_argument("--priority", "-p", type=int, default=5,
                       help="1 (low) to 10 (high)")
    p_add.add_argument("--target-date", "-t", default="",
                       help="ISO date YYYY-MM-DD (optional)")

    # list
    p_list = sub.add_parser("list", help="List goals")
    p_list.add_argument("--status", "-s", default="", choices=sorted(VALID_STATUSES) + [""])
    p_list.add_argument("--category", "-c", default="", choices=sorted(VALID_CATEGORIES) + [""])
    p_list.add_argument("--limit", "-l", type=int, default=50)

    # complete
    p_done = sub.add_parser("complete", help="Mark a goal complete (by title or id)")
    p_done.add_argument("identifier", help="Title (exact) or numeric id")

    # inject
    p_inj = sub.add_parser("inject", help="Print session-start goals preamble")
    p_inj.add_argument("--max", type=int, default=DEFAULT_MAX_INJECTED)
    p_inj.add_argument("--min-priority", type=int, default=DEFAULT_MIN_PRIORITY)

    # stats
    sub.add_parser("stats", help="Show goal counts by status")

    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    g = IchorGoals()

    if args.command == "add":
        gid = g.add(
            title=args.title, description=args.description,
            category=args.category, priority=args.priority,
            target_date=args.target_date,
        )
        print(f"Created goal #{gid}: {args.title} "
              f"(priority {args.priority}, category {args.category})")
    elif args.command == "list":
        goals = g.list(
            status=args.status or None,
            category=args.category or None,
            limit=args.limit,
        )
        if not goals:
            print("(no goals match filter)")
            return
        for r in goals:
            target = f" → target {r['target_date']}" if r.get("target_date") else ""
            print(f"#{r['id']:>3} [{r['status']:>9}] P{r['priority']:>2} "
                  f"({r['category']:>10}) {int(round(float(r['progress'])*100)):>3}% "
                  f"{r['title']}{target}")
    elif args.command == "complete":
        try:
            ident = int(args.identifier)
            ok = g.complete(ident)
        except ValueError:
            ok = g.complete(args.identifier)
        print(f"complete: ok={ok}")
    elif args.command == "inject":
        md = format_active_goals_preamble(
            max_injected=args.max, min_priority=args.min_priority,
        )
        if md:
            print(md)
        else:
            print(f"(no active goals with priority >= {args.min_priority})")
    elif args.command == "stats":
        print(json.dumps(g.stats(), indent=2))


if __name__ == "__main__":
    main()
