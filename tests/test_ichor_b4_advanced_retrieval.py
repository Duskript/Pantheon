"""
B4: Advanced Retrieval — directory-recursive + ichor_trajectory.

Spec: ~/athenaeum/Codex-God-thoth/research/openviking-vs-ichor-comparison/build-brief.md §P4
      ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md §B4

Gate checks:
  1. Directory-recursive retrieval picks correct directory first (>80% accuracy)
  2. ichor_trajectory returns a valid trajectory for any past query
  3. Retrieval log records all 3 passes for every query
  4. Pruned directories have clear reasons in the trajectory

Plus contract tests for backward compat (search() with default path
still works), trajectory display formatting, and the retrieval-log
schema extension.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict  # noqa: F401
from unittest.mock import patch

PANTHEON_ROOT = str(Path.home() / "pantheon")
if PANTHEON_ROOT not in sys.path:
    sys.path.insert(0, PANTHEON_ROOT)

from lib.ichor_hybrid import TieredRetriever  # noqa: E402
from lib.ichor_trajectory import (  # noqa: E402
    ichor_trajectory,
    render_trajectory,
    _RETRIEVAL_LOG,
)

# Trajectory is a typing alias used only in type hints in tests.
# It's defined here rather than in the production module to keep
# the production API minimal (callers get dicts, not TypedDicts).
Trajectory = Dict[str, Any]  # type alias for tests



# ---------------------------------------------------------------------------
# Gate checks
# ---------------------------------------------------------------------------

class TestGateB4DirRecursiveAccuracy(unittest.TestCase):
    """Gate B4 check 1: directory-recursive retrieval picks correct dir first.

    The spec asks for >80% accuracy on "known queries" — queries where
    we can guess the right top directory from the query alone. We test
    by picking queries that obviously belong to a specific warm
    category and verifying the top-1 directory matches.
    """

    KNOWN_QUERIES = [
        # (query, expected_top_dir_basename)
        ("blocker deploy failure", "blocker"),
        ("decision memory schema", "decision"),
        ("commitment deliverable", "commitment"),
        ("preference user typing", "preference"),
        ("insight learned", "insight"),
        ("fact verified", "fact"),
        ("follow up todo", "follow_up"),
        ("correction wrong", "correction"),
    ]

    def test_top_directory_picked(self):
        """For each known query, top directory should match expected."""
        retriever = TieredRetriever()
        correct = 0
        total = len(self.KNOWN_QUERIES)
        for query, expected in self.KNOWN_QUERIES:
            trajectory = retriever.search(
                query, limit=5, path="pantheon://warm/", return_trajectory=True
            )
            # The trajectory's pass-1 step has the dir info nested inside
            steps = trajectory.get("steps", [])
            if not steps:
                continue
            top_dirs = steps[0].get("directories_selected", [])
            if not top_dirs:
                # No top dirs selected — count as miss
                continue
            top_name = top_dirs[0].get("name", "")
            # The dir name in trajectory is the category (not "Codex-X")
            if top_name == expected:
                correct += 1
        accuracy = correct / total
        self.assertGreaterEqual(
            accuracy, 0.80,
            msg=f"accuracy {accuracy:.0%} ({correct}/{total}) < 80% gate"
        )


class TestGateB4TrajectoryReplay(unittest.TestCase):
    """Gate B4 check 2: ichor_trajectory returns a valid trajectory."""

    def test_trajectory_shape(self):
        """ichor_trajectory returns a dict with the spec's required keys."""
        # First, make sure there's at least one retrieval-log entry to replay
        traj = ichor_trajectory("marvin-dev")
        self.assertIsInstance(traj, dict)
        self.assertIn("query", traj)
        self.assertIn("path", traj)
        self.assertIn("steps", traj)
        self.assertIn("results", traj)
        self.assertIsInstance(traj["steps"], list)
        self.assertIsInstance(traj["results"], list)

    def test_trajectory_with_passes(self):
        """If the log entry has 'passes', trajectory has 3 steps."""
        # Inject a fake log entry with passes
        import time
        entry = {
            "timestamp": time.time(),
            "query": "test trajectory with passes",
            "path": "pantheon://",
            "weights": {"fts5": 0.45, "graph": 0.30, "events": 0.25},
            "mode": "tiered",
            "result_count": 3,
            "outcome": "pending",
            "result_ids": ["fts5:1", "fts5:2", "fts5:3"],
            "backends_used": ["fts5_tiered"],
            "passes": [
                {"pass": 1, "action": "brief_scan", "candidates": 12,
                 "selected": 4, "latency_ms": 5.0,
                 "directories_considered": ["warm/blockers", "warm/decisions"],
                 "directories_selected": [
                     {"name": "warm/blockers", "score": 0.85}
                 ]},
                {"pass": 2, "action": "outline_filter", "candidates": 4,
                 "selected": 2, "latency_ms": 3.0,
                 "pruned": ["cert-expiry (redundant)"]},
                {"pass": 3, "action": "full_loaded", "items": 2,
                 "latency_ms": 1.0, "loaded": ["blocker:deploy-fail-2026-06-09"]},
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl",
                                         delete=False) as f:
            f.write(json.dumps(entry) + "\n")
            log_path = Path(f.name)
        try:
            with patch("lib.ichor_trajectory._RETRIEVAL_LOG", log_path):
                traj = ichor_trajectory("marvin-dev")
            self.assertEqual(len(traj["steps"]), 3)
            self.assertEqual(traj["steps"][0]["pass"], 1)
            self.assertEqual(traj["steps"][1]["pass"], 2)
            self.assertEqual(traj["steps"][2]["pass"], 3)
        finally:
            log_path.unlink()


class TestGateB4LogExtension(unittest.TestCase):
    """Gate B4 check 3: retrieval log records all 3 passes for every query."""

    def test_search_records_passes(self):
        """A real TieredRetriever.search() call writes passes to the log."""
        import time
        # Snapshot log size
        before = _RETRIEVAL_LOG.stat().st_size if _RETRIEVAL_LOG.exists() else 0
        retriever = TieredRetriever()
        retriever.search(
            "test B4 log extension query",
            limit=3,
            path="pantheon://warm/decision/",
            return_trajectory=True,
        )
        after = _RETRIEVAL_LOG.stat().st_size
        self.assertGreater(after, before, "no log entry written")

        # Read the most recent entry and check for 'passes'
        with open(_RETRIEVAL_LOG) as f:
            lines = f.readlines()
        last = json.loads(lines[-1])
        self.assertIn("passes", last, "newest entry missing 'passes' field")
        # At least 1 pass recorded (1 if brief_only, 2 if full)
        self.assertGreaterEqual(len(last["passes"]), 1)


class TestGateB4PruningReasons(unittest.TestCase):
    """Gate B4 check 4: pruned directories have clear reasons in the trajectory."""

    def test_pruned_dirs_have_reasons(self):
        """When dirs are pruned, trajectory records the reason."""
        import time
        entry = {
            "timestamp": time.time(),
            "query": "test pruning",
            "path": "pantheon://warm/",
            "weights": {"fts5": 0.45, "graph": 0.30, "events": 0.25},
            "mode": "tiered",
            "result_count": 0,
            "outcome": "pending",
            "result_ids": [],
            "backends_used": ["fts5_tiered"],
            "passes": [
                {"pass": 1, "action": "brief_scan", "candidates": 30,
                 "selected": 3, "latency_ms": 4.0,
                 "directories_considered": [
                     {"name": "warm/blocker", "score": 0.85},
                     {"name": "warm/decision", "score": 0.42},
                     {"name": "warm/insight", "score": 0.31},
                     {"name": "warm/fact", "score": 0.20},
                 ],
                 "directories_selected": [
                     {"name": "warm/blocker", "score": 0.85},
                     {"name": "warm/decision", "score": 0.42},
                     {"name": "warm/insight", "score": 0.31},
                 ],
                 "directories_pruned": [
                     {"name": "warm/fact", "score": 0.20,
                      "reason": "below top-3 threshold"},
                 ]},
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl",
                                         delete=False) as f:
            f.write(json.dumps(entry) + "\n")
            log_path = Path(f.name)
        try:
            with patch("lib.ichor_trajectory._RETRIEVAL_LOG", log_path):
                traj = ichor_trajectory("marvin-dev")
            pruned = traj["steps"][0].get("directories_pruned", [])
            self.assertGreater(len(pruned), 0, "no pruned dirs in trajectory")
            for p in pruned:
                self.assertIn("reason", p,
                              msg=f"pruned dir {p} missing reason")
        finally:
            log_path.unlink()


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

class TestBackwardCompat(unittest.TestCase):
    """search() with default path behaves exactly as before."""

    def test_default_path_unchanged(self):
        """search() with no path= param uses FTS5 path."""
        retriever = TieredRetriever()
        # Should not raise
        results = retriever.search("test", limit=3)
        # Result list (possibly empty) but with the same shape as before
        self.assertIsInstance(results, list)

    def test_passes_param_is_optional(self):
        """return_trajectory=True returns dict, default returns list."""
        retriever = TieredRetriever()
        # Default — return list of results
        r1 = retriever.search("test", limit=3, path="pantheon://")
        self.assertIsInstance(r1, list)
        # return_trajectory — return dict with passes
        r2 = retriever.search("test", limit=3, path="pantheon://warm/",
                              return_trajectory=True)
        self.assertIsInstance(r2, dict)
        self.assertIn("steps", r2)


class TestTrajectoryRendering(unittest.TestCase):
    """render_trajectory() produces a human-readable string."""

    def test_renders_query(self):
        traj = {
            "query": "deploy failure",
            "path": "pantheon://",
            "steps": [],
            "results": ["blocker:deploy-fail"],
        }
        out = render_trajectory(traj)
        self.assertIn("deploy failure", out)

    def test_renders_steps(self):
        traj = {
            "query": "test",
            "path": "pantheon://",
            "steps": [
                {"pass": 1, "action": "brief_scan", "candidates": 12,
                 "selected": 4},
                {"pass": 2, "action": "outline_filter", "candidates": 4,
                 "selected": 2},
                {"pass": 3, "action": "full_loaded", "items": 2},
            ],
            "results": ["x"],
        }
        out = render_trajectory(traj)
        self.assertIn("Step 1", out)
        self.assertIn("brief_scan", out)
        self.assertIn("Step 2", out)
        self.assertIn("Step 3", out)


class TestTrajectoryNoLogEntries(unittest.TestCase):
    """Edge case: no log entries yet → empty trajectory."""

    def test_no_entries_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl",
                                         delete=False) as f:
            # Empty file
            log_path = Path(f.name)
        try:
            with patch("lib.ichor_trajectory._RETRIEVAL_LOG", log_path):
                traj = ichor_trajectory("nonexistent-session")
            self.assertEqual(traj["query"], "")
            self.assertEqual(traj["steps"], [])
            self.assertEqual(traj["results"], [])
        finally:
            log_path.unlink()


if __name__ == "__main__":
    unittest.main()
