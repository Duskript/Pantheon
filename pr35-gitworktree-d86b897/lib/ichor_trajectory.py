"""
B4: ichor_trajectory — replay a past retrieval query.

Spec: ~/athenaeum/Codex-God-thoth/research/openviking-vs-ichor-comparison/build-brief.md §P4b
      ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md §B4

`ichor_trajectory(session_id)` reads the most recent retrieval-log
entry for the session and returns a Trajectory dict with the
spec's shape:

  {
    "query": str,
    "path": str,
    "steps": [
      {pass: 1, action: "brief_scan", candidates: int, selected: int, ...},
      {pass: 2, action: "outline_filter", ...},
      {pass: 3, action: "full_loaded", ...}
    ],
    "results": [str, ...]
  }

Backward-compat: log entries written before B4 don't have a `passes`
field. We synthesize a flat trajectory from `result_ids` and
`backends_used` so the API stays uniform.

`render_trajectory(traj)` produces the spec's display format:

  🔍 "deploy failure" at pantheon://
    Step 1: Brief scan → 12 candidates, 4 selected
      warm/blockers/  score 0.85 ← selected
      warm/decisions/ score 0.42 ← pruned
    Step 2: Outline filter → 2 selected
      ...
    Step 3: Full loaded → 2 items
      ✓ blocker:deploy-fail-2026-06-09
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ichor_trajectory")

_HOME = Path.home()
_RETRIEVAL_LOG = _HOME / ".hermes" / "pantheon" / "retrieval-log.jsonl"


# ---------------------------------------------------------------------------
# Reading the log
# ---------------------------------------------------------------------------

def _read_log_entries(session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read retrieval-log entries, newest first.

    Filters by session_id if provided (uses 'session_id' field on each
    entry; log entries written by HybridScorer don't currently include
    session_id, so if no filter matches, we return ALL entries sorted
    by timestamp desc).
    """
    if not _RETRIEVAL_LOG.exists():
        return []
    try:
        entries = []
        with open(_RETRIEVAL_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.warning("could not read retrieval log: %s", e)
        return []

    # Filter by session_id if present
    if session_id is not None:
        filtered = [e for e in entries if e.get("session_id") == session_id]
        # If no exact match, fall back to all entries (most callers want
        # "the most recent query", not "queries from a specific session"
        # since HybridScorer doesn't always set session_id).
        if not filtered:
            entries = entries
        else:
            entries = filtered

    # Newest first
    entries.sort(key=lambda e: e.get("timestamp", 0), reverse=True)
    return entries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ichor_trajectory(
    session_id: Optional[str] = None,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the trajectory for a past query.

    Args:
        session_id: Optional filter. If provided, returns the most recent
            entry for that session. If None, returns the most recent
            entry overall.
        query: Optional filter by exact query string. If provided, returns
            the most recent entry whose query matches exactly.

    Returns:
        Trajectory dict. Empty if no log entries exist.
    """
    entries = _read_log_entries(session_id=session_id)
    if query is not None:
        entries = [e for e in entries if e.get("query") == query]

    if not entries:
        return {
            "query": "",
            "path": "",
            "steps": [],
            "results": [],
            "source_entry": None,
        }

    entry = entries[0]
    return _entry_to_trajectory(entry)


def _entry_to_trajectory(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a retrieval-log entry to a Trajectory dict.

    If the entry has a 'passes' field (B4-extended log), use it directly.
    Otherwise synthesize a flat trajectory from result_ids + backends_used
    for backward compat with pre-B4 entries.
    """
    passes = entry.get("passes")
    steps: List[Dict[str, Any]] = []
    if passes:
        # Forward the recorded passes as-is
        steps = list(passes)
    else:
        # Synthesize a single-step trajectory from legacy fields
        backends = entry.get("backends_used", [])
        backend = backends[0] if backends else "unknown"
        steps = [{
            "pass": 1,
            "action": f"backend_search ({backend})",
            "candidates": entry.get("result_count", 0),
            "selected": entry.get("result_count", 0),
            "latency_ms": None,
            "result_ids": entry.get("result_ids", []),
        }]

    return {
        "query": entry.get("query", ""),
        "path": entry.get("path", ""),
        "steps": steps,
        "results": entry.get("result_ids", []),
        "weights": entry.get("weights", {}),
        "mode": entry.get("mode", "legacy"),
        "outcome": entry.get("outcome", "pending"),
        "source_entry": entry,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_trajectory(traj: Dict[str, Any]) -> str:
    """Format a Trajectory for display. Matches the spec's example output."""
    lines: List[str] = []
    query = traj.get("query", "")
    path = traj.get("path", "pantheon://")
    lines.append(f'🔍 "{query}" at {path}')

    steps = traj.get("steps", [])
    for step in steps:
        pass_num = step.get("pass", "?")
        action = step.get("action", "?")
        candidates = step.get("candidates", 0)
        selected = step.get("selected", 0)
        lines.append(f"  Step {pass_num}: {action} → {candidates} candidates, "
                     f"{selected} selected")

        # Pass 1 directories
        dirs_considered = step.get("directories_considered", [])
        dirs_selected = step.get("directories_selected", [])
        dirs_pruned = step.get("directories_pruned", [])
        if dirs_considered:
            for d in dirs_considered:
                name = d.get("name", "?")
                score = d.get("score", 0.0)
                marker = ""
                if any(s.get("name") == name for s in dirs_selected):
                    marker = " ← selected"
                elif any(p.get("name") == name for p in dirs_pruned):
                    marker = " ← pruned"
                lines.append(f"    {name:30s}  score {score:.2f}{marker}")

        # Pass 2 pruned
        pruned = step.get("pruned", [])
        if pruned:
            for p in pruned:
                lines.append(f"    {p}")

        # Pass 3 loaded
        loaded = step.get("loaded", [])
        if loaded:
            for item in loaded:
                lines.append(f"    ✓ {item}")

    results = traj.get("results", [])
    if results:
        lines.append(f"  Results: {', '.join(results[:5])}"
                     + ("..." if len(results) > 5 else ""))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton for the MCP-tool style import
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    q = sys.argv[2] if len(sys.argv) > 2 else None
    traj = ichor_trajectory(sid, q)
    print(render_trajectory(traj))
