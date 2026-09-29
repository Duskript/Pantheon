#!/usr/bin/env python3
"""Hermes Dojo Skill Crystallization — candidate scanner (standalone).

Finds recent COMPLEX COMPLETED TASKS and proposes them as candidates for the
agent to evaluate for crystallization into reusable skills.

Design note (2026-09-19 rewrite): the previous version imported a package
(`hermes_dojo.scripts.skill_crystallization`) that does not exist — the package
dir is `hermes-dojo` (dash), which is not importable — so it printed
"Using fallback mode" and `sys.exit(0)` doing nothing. A later variant queried
ichor_events for non-existent `key`/`content` columns and crashed. Both caused
the agent to improvise junk skills.

Source of truth: the Hermes session store (`~/.hermes/state.db`). A "complex
completed task" is a recent session that used many tools. This is a far better
signal than the ichor_events stream, which in this deployment is 100%
regex-derived (source='tier_a') and therefore noisy.

This script only PROPOSES candidates. It never creates skills — that is the
agent's job via `skill_manage`.

Usage:
    python3 skill_crystallization.py [--days N] [--min-tools N] [--limit N] [--json] [--log]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

STATE_DB = os.environ.get("HERMES_STATE_DB", "/home/konan/.hermes/state.db")
DOJO_LOG = os.environ.get("DOJO_CRYSTALLIZATION_LOG", "/home/konan/.hermes/dojo/crystallizations.jsonl")

# Cron runs are machine-driven, not human tasks worth crystallizing.
EXCLUDE_SOURCES = ("cron",)


def find_candidates(days: int, min_tools: int, limit: int) -> list[dict]:
    if not os.path.isfile(STATE_DB):
        return []
    con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=20)
    con.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in EXCLUDE_SOURCES)
        rows = con.execute(
            f"""
            SELECT id, source, title, message_count, tool_call_count,
                   CAST(last_activity_at AS INTEGER) AS last_activity_at
            FROM sessions
            WHERE last_activity_at > strftime('%s','now', ?)
              AND tool_call_count >= ?
              AND source NOT IN ({placeholders})
            ORDER BY tool_call_count DESC
            LIMIT ?
            """,
            (f"-{int(days)} day", int(min_tools), *EXCLUDE_SOURCES, int(limit)),
        ).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        title = (r["title"] or "").strip() or "(untitled session)"
        out.append({
            "id": r["id"],
            "source": r["source"],
            "title": title,
            "message_count": r["message_count"],
            "tool_call_count": r["tool_call_count"],
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Hermes Dojo crystallization candidate scanner")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--min-tools", type=int, default=15)
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--log", action="store_true", help="append a run summary to the crystallization log")
    args = ap.parse_args()

    candidates = find_candidates(args.days, args.min_tools, args.limit)

    if args.json:
        print(json.dumps({"count": len(candidates), "candidates": candidates}, indent=2))
    elif not candidates:
        print(f"CANDIDATES: 0 (no sessions with >= {args.min_tools} tool calls in the last {args.days}d)")
    else:
        print(f"CANDIDATES: {len(candidates)}")
        for c in candidates:
            print(
                f"CANDIDATE {c['id']}: {c['title']} "
                f"({c['source']}, {c['tool_call_count']} tool calls, {c['message_count']} messages)"
            )

    if args.log:
        try:
            os.makedirs(os.path.dirname(DOJO_LOG), exist_ok=True)
            with open(DOJO_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "kind": "scan",
                    "days": args.days,
                    "min_tools": args.min_tools,
                    "count": len(candidates),
                    "candidate_ids": [c["id"] for c in candidates],
                }) + "\n")
        except OSError as exc:
            print(f"WARN: could not write crystallization log: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
