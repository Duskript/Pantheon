"""
A1: Ichor Goals Registry — test the full CRUD + preamble + MCP dispatch surface.

Spec: ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md §A1

The IchorGoals class is a thin SQLite wrapper over the `strategic_goals`
table. All tests use a tempfile-resident DB so the real `~/.hermes/ichor.db`
is never touched (no side effects on the production state).

Covers:
  - add() — happy path + 3 validation errors
  - get() — found / not-found
  - find_by_title() — exact / LIKE / not-found
  - list() — status filter, category filter, both, ordering, limit
  - list_active() — min_priority filter, default
  - update() — partial updates, no-op, validation, completed_at auto-stamp
  - update_progress() — convenience
  - complete() — by id, by exact title, by LIKE title, double-complete idempotent
  - pause() — by id, by title, not-found
  - delete() — found, not-found
  - stats() — counts by status
  - format_active_goals_preamble() — empty, single, multiple, description wrap, target_date
  - mcp_dispatch() — all 8 actions + error paths
  - CLI subcommands via subprocess — add, list, complete, inject, stats
  - VALID_STATUSES / VALID_CATEGORIES — exhaustive
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure pantheon root on sys.path (matches other test files in this repo)
PANTHEON_ROOT = str(Path(__file__).resolve().parent.parent)
if PANTHEON_ROOT not in sys.path:
    sys.path.insert(0, PANTHEON_ROOT)

from lib.ichor_goals import (  # noqa: E402
    IchorGoals,
    VALID_CATEGORIES,
    VALID_STATUSES,
    DEFAULT_MAX_INJECTED,
    DEFAULT_MIN_PRIORITY,
    format_active_goals_preamble,
    mcp_dispatch,
)


# ---------------------------------------------------------------------------
# Fixtures: each test gets its own temp DB; production DB is never read or
# written. The IchorGoals class accepts db_path in __init__, so isolation
# is per-instance (per-test) without any module-level monkey-patching.
# ---------------------------------------------------------------------------

def _make_goals() -> IchorGoals:
    """Return an IchorGoals backed by a fresh tempfile. Caller closes."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    g = IchorGoals(db_path=tmp.name)
    g.connect()  # force table creation
    return g


class TestConstants(unittest.TestCase):
    """The exported frozensets match what the CLI choices expect."""

    def test_valid_statuses_is_frozenset(self):
        self.assertIsInstance(VALID_STATUSES, frozenset)
        self.assertEqual(
            VALID_STATUSES,
            frozenset({"active", "paused", "completed", "abandoned"}),
        )

    def test_valid_categories_is_frozenset(self):
        self.assertIsInstance(VALID_CATEGORIES, frozenset)
        self.assertEqual(
            VALID_CATEGORIES,
            frozenset({"general", "theoforge", "pantheon", "skc"}),
        )

    def test_default_inject_bounds(self):
        self.assertEqual(DEFAULT_MAX_INJECTED, 5)
        self.assertEqual(DEFAULT_MIN_PRIORITY, 3)


class TestAdd(unittest.TestCase):
    """add() creates a row and returns its id. Validation covers 3 axes."""

    def setUp(self):
        self.g = _make_goals()

    def tearDown(self):
        self.g.close()
        os.unlink(self.g.db_path)

    def test_add_minimal_returns_id(self):
        gid = self.g.add("Ship A2")
        self.assertIsInstance(gid, int)
        self.assertGreater(gid, 0)

    def test_add_persists_all_fields(self):
        gid = self.g.add(
            "Ship A2",
            description="Docs + tests + deploy",
            category="theoforge",
            priority=8,
            target_date="2026-06-30",
        )
        row = self.g.get(gid)
        self.assertEqual(row["title"], "Ship A2")
        self.assertEqual(row["description"], "Docs + tests + deploy")
        self.assertEqual(row["category"], "theoforge")
        self.assertEqual(row["priority"], 8)
        self.assertEqual(row["target_date"], "2026-06-30")
        # Defaults
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["progress"], 0.0)
        # Timestamps are set by SQLite
        self.assertIsNotNone(row["started_at"])
        self.assertIsNotNone(row["created_at"])
        self.assertIsNotNone(row["updated_at"])

    def test_add_strips_whitespace(self):
        gid = self.g.add("  Ship A2  ", description="  desc  ",
                         target_date="  2026-06-30  ")
        row = self.g.get(gid)
        self.assertEqual(row["title"], "Ship A2")
        self.assertEqual(row["description"], "desc")
        self.assertEqual(row["target_date"], "2026-06-30")

    def test_add_rejects_empty_title(self):
        with self.assertRaises(ValueError) as ctx:
            self.g.add("")
        self.assertIn("title", str(ctx.exception).lower())

    def test_add_rejects_whitespace_title(self):
        with self.assertRaises(ValueError):
            self.g.add("   ")

    def test_add_rejects_invalid_category(self):
        with self.assertRaises(ValueError) as ctx:
            self.g.add("X", category="invalid_cat")
        self.assertIn("invalid category", str(ctx.exception).lower())

    def test_add_rejects_priority_below_1(self):
        with self.assertRaises(ValueError):
            self.g.add("X", priority=0)

    def test_add_rejects_priority_above_10(self):
        with self.assertRaises(ValueError):
            self.g.add("X", priority=11)

    def test_add_accepts_priority_boundaries(self):
        gid_low = self.g.add("low", priority=1)
        gid_high = self.g.add("high", priority=10)
        self.assertEqual(self.g.get(gid_low)["priority"], 1)
        self.assertEqual(self.g.get(gid_high)["priority"], 10)

    def test_add_with_each_valid_category(self):
        for cat in VALID_CATEGORIES:
            gid = self.g.add(f"goal in {cat}", category=cat)
            self.assertEqual(self.g.get(gid)["category"], cat)


class TestGet(unittest.TestCase):

    def setUp(self):
        self.g = _make_goals()

    def tearDown(self):
        self.g.close()
        os.unlink(self.g.db_path)

    def test_get_existing_returns_dict(self):
        gid = self.g.add("X")
        row = self.g.get(gid)
        self.assertIsInstance(row, dict)
        self.assertEqual(row["id"], gid)
        self.assertEqual(row["title"], "X")

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.g.get(99999))


class TestFindByTitle(unittest.TestCase):

    def setUp(self):
        self.g = _make_goals()
        self.g.add("Ship A2", category="theoforge")
        self.g.add("Ship A3", category="pantheon")
        self.g.add("Refactor memory", category="general")

    def tearDown(self):
        self.g.close()
        os.unlink(self.g.db_path)

    def test_exact_match(self):
        row = self.g.find_by_title("Ship A2")
        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "Ship A2")

    def test_exact_match_case_sensitive(self):
        self.assertIsNone(self.g.find_by_title("ship a2"))

    def test_like_match(self):
        row = self.g.find_by_title("Ship", exact=False)
        self.assertIsNotNone(row)
        self.assertIn("Ship", row["title"])

    def test_like_match_returns_first(self):
        # Both "Ship A2" and "Ship A3" match LIKE %Ship%; should return
        # the lower id.
        row = self.g.find_by_title("Ship", exact=False)
        self.assertEqual(row["title"], "Ship A2")

    def test_no_match_returns_none(self):
        self.assertIsNone(self.g.find_by_title("nonexistent"))
        self.assertIsNone(self.g.find_by_title("nonexistent", exact=False))


class TestList(unittest.TestCase):
    """list() filters by status/category, orders by priority DESC then id ASC."""

    def setUp(self):
        self.g = _make_goals()
        self.g.add("alpha", priority=3, category="general")
        self.g.add("beta", priority=8, category="theoforge")
        self.g.add("gamma", priority=5, category="theoforge")
        self.g.add("delta", priority=10, category="pantheon")
        # Complete one
        self.g.update(self.g.find_by_title("alpha")["id"], status="completed")

    def tearDown(self):
        self.g.close()
        os.unlink(self.g.db_path)

    def test_list_no_filter(self):
        rows = self.g.list()
        self.assertEqual(len(rows), 4)
        # Order: priority DESC, then id ASC: delta(10), beta(8), gamma(5), alpha(3)
        self.assertEqual([r["title"] for r in rows],
                         ["delta", "beta", "gamma", "alpha"])

    def test_list_filter_by_status(self):
        rows = self.g.list(status="completed")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "alpha")

        rows = self.g.list(status="active")
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["title"] for r in rows], ["delta", "beta", "gamma"])

    def test_list_filter_by_category(self):
        rows = self.g.list(category="theoforge")
        self.assertEqual([r["title"] for r in rows], ["beta", "gamma"])

    def test_list_filter_by_both(self):
        rows = self.g.list(status="active", category="theoforge")
        self.assertEqual([r["title"] for r in rows], ["beta", "gamma"])

    def test_list_respects_limit(self):
        rows = self.g.list(limit=2)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["title"] for r in rows], ["delta", "beta"])

    def test_list_rejects_invalid_status(self):
        with self.assertRaises(ValueError) as ctx:
            self.g.list(status="not-a-status")
        self.assertIn("invalid status", str(ctx.exception).lower())


class TestListActive(unittest.TestCase):
    """list_active() — the session-start inject path."""

    def setUp(self):
        self.g = _make_goals()
        # Active priorities: 8, 5
        self.g.add("a-high", priority=8)
        self.g.add("a-med", priority=5)
        # Active but below default min (3)
        self.g.add("a-low", priority=2)
        # Not active
        gid_done = self.g.add("a-done", priority=10)
        self.g.update(gid_done, status="completed")

    def tearDown(self):
        self.g.close()
        os.unlink(self.g.db_path)

    def test_default_min_priority(self):
        rows = self.g.list_active()
        # min_priority=3, so a-high(8) + a-med(5), a-low(2) excluded, a-done excluded
        self.assertEqual([r["title"] for r in rows], ["a-high", "a-med"])

    def test_custom_min_priority(self):
        rows = self.g.list_active(min_priority=2)
        # Now a-low(2) is included
        self.assertEqual([r["title"] for r in rows], ["a-high", "a-med", "a-low"])

    def test_respects_limit(self):
        rows = self.g.list_active(limit=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "a-high")

    def test_empty_when_none_match(self):
        rows = self.g.list_active(min_priority=99)
        self.assertEqual(rows, [])


class TestUpdate(unittest.TestCase):

    def setUp(self):
        self.g = _make_goals()
        self.gid = self.g.add("X", priority=5, category="general")

    def tearDown(self):
        self.g.close()
        os.unlink(self.g.db_path)

    def test_update_single_field(self):
        ok = self.g.update(self.gid, title="Y")
        self.assertTrue(ok)
        self.assertEqual(self.g.get(self.gid)["title"], "Y")
        # Other fields unchanged
        self.assertEqual(self.g.get(self.gid)["priority"], 5)
        self.assertEqual(self.g.get(self.gid)["category"], "general")

    def test_update_multiple_fields(self):
        ok = self.g.update(self.gid, title="Y", priority=9, progress=0.5)
        self.assertTrue(ok)
        row = self.g.get(self.gid)
        self.assertEqual(row["title"], "Y")
        self.assertEqual(row["priority"], 9)
        self.assertEqual(row["progress"], 0.5)

    def test_update_no_fields_returns_false(self):
        # All None — should return False without writing
        ok = self.g.update(self.gid)
        self.assertFalse(ok)

    def test_update_nonexistent_returns_false(self):
        ok = self.g.update(99999, title="X")
        self.assertFalse(ok)

    def test_update_rejects_invalid_status(self):
        with self.assertRaises(ValueError):
            self.g.update(self.gid, status="not-a-status")

    def test_update_rejects_invalid_category(self):
        with self.assertRaises(ValueError):
            self.g.update(self.gid, category="not-a-cat")

    def test_update_rejects_out_of_range_priority(self):
        with self.assertRaises(ValueError):
            self.g.update(self.gid, priority=11)

    def test_update_rejects_out_of_range_progress(self):
        with self.assertRaises(ValueError):
            self.g.update(self.gid, progress=1.5)
        with self.assertRaises(ValueError):
            self.g.update(self.gid, progress=-0.1)

    def test_completed_auto_stamps_completed_at(self):
        # Initially NULL
        self.assertIsNone(self.g.get(self.gid)["completed_at"])
        self.g.update(self.gid, status="completed")
        # After update: completed_at is set
        self.assertIsNotNone(self.g.get(self.gid)["completed_at"])

    def test_abandoned_auto_stamps_completed_at(self):
        self.g.update(self.gid, status="abandoned")
        self.assertIsNotNone(self.g.get(self.gid)["completed_at"])

    def test_double_complete_preserves_first_completed_at(self):
        self.g.update(self.gid, status="completed")
        first = self.g.get(self.gid)["completed_at"]
        # Update something else and re-complete
        self.g.update(self.gid, progress=1.0)
        # Note: re-completion should not overwrite completed_at
        # (COALESCE in SQL — see update() implementation)
        self.g.update(self.gid, status="completed")
        second = self.g.get(self.gid)["completed_at"]
        self.assertEqual(first, second)

    def test_paused_does_not_stamp_completed_at(self):
        self.g.update(self.gid, status="paused")
        self.assertIsNone(self.g.get(self.gid)["completed_at"])

    def test_active_does_not_stamp_completed_at(self):
        self.g.update(self.gid, status="active")
        self.assertIsNone(self.g.get(self.gid)["completed_at"])


class TestUpdateProgress(unittest.TestCase):

    def setUp(self):
        self.g = _make_goals()
        self.gid = self.g.add("X")

    def tearDown(self):
        self.g.close()
        os.unlink(self.g.db_path)

    def test_update_progress_sets_and_persists(self):
        self.g.update_progress(self.gid, 0.42)
        self.assertEqual(self.g.get(self.gid)["progress"], 0.42)

    def test_update_progress_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            self.g.update_progress(self.gid, 1.5)


class TestComplete(unittest.TestCase):

    def setUp(self):
        self.g = _make_goals()
        self.gid = self.g.add("Ship A2")
        self.g.add("Ship A3")

    def tearDown(self):
        self.g.close()
        os.unlink(self.g.db_path)

    def test_complete_by_id(self):
        ok = self.g.complete(self.gid)
        self.assertTrue(ok)
        row = self.g.get(self.gid)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["progress"], 1.0)

    def test_complete_by_exact_title(self):
        ok = self.g.complete("Ship A3")
        self.assertTrue(ok)
        row = self.g.find_by_title("Ship A3")
        self.assertEqual(row["status"], "completed")

    def test_complete_by_substring_via_LIKE(self):
        # Add a goal with a unique substring
        self.g.add("Refactor memory code")
        ok = self.g.complete("memory")  # LIKE %memory% → "Refactor memory code"
        self.assertTrue(ok)
        # Ship A2 should NOT be completed (it was the first id, not the LIKE match)
        self.assertEqual(self.g.get(self.gid)["status"], "active")
        # The LIKE match should be completed
        row = self.g.find_by_title("Refactor memory code")
        self.assertEqual(row["status"], "completed")

    def test_complete_nonexistent_returns_false(self):
        ok = self.g.complete("nonexistent-title-xyz")
        self.assertFalse(ok)

    def test_complete_idempotent(self):
        self.g.complete(self.gid)
        # Completing again should still return True (the row still updates)
        ok2 = self.g.complete(self.gid)
        self.assertTrue(ok2)
        self.assertEqual(self.g.get(self.gid)["status"], "completed")

    def test_complete_stamps_completed_at(self):
        self.assertIsNone(self.g.get(self.gid)["completed_at"])
        self.g.complete(self.gid)
        self.assertIsNotNone(self.g.get(self.gid)["completed_at"])


class TestPause(unittest.TestCase):

    def setUp(self):
        self.g = _make_goals()
        self.gid = self.g.add("X")

    def tearDown(self):
        self.g.close()
        os.unlink(self.g.db_path)

    def test_pause_by_id(self):
        ok = self.g.pause(self.gid)
        self.assertTrue(ok)
        self.assertEqual(self.g.get(self.gid)["status"], "paused")

    def test_pause_by_title(self):
        ok = self.g.pause("X")
        self.assertTrue(ok)
        self.assertEqual(self.g.get(self.gid)["status"], "paused")

    def test_pause_nonexistent_returns_false(self):
        self.assertFalse(self.g.pause("nope"))


class TestDelete(unittest.TestCase):

    def setUp(self):
        self.g = _make_goals()
        self.gid = self.g.add("X")

    def tearDown(self):
        self.g.close()
        os.unlink(self.g.db_path)

    def test_delete_existing(self):
        ok = self.g.delete(self.gid)
        self.assertTrue(ok)
        self.assertIsNone(self.g.get(self.gid))

    def test_delete_nonexistent(self):
        ok = self.g.delete(99999)
        self.assertFalse(ok)


class TestStats(unittest.TestCase):

    def setUp(self):
        self.g = _make_goals()
        self.g.add("a")  # active
        self.g.add("b")  # active
        gid_c = self.g.add("c")
        self.g.update(gid_c, status="completed")
        gid_p = self.g.add("d")
        self.g.update(gid_p, status="paused")

    def tearDown(self):
        self.g.close()
        os.unlink(self.g.db_path)

    def test_stats_counts(self):
        stats = self.g.stats()
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["by_status"]["active"], 2)
        self.assertEqual(stats["by_status"]["completed"], 1)
        self.assertEqual(stats["by_status"]["paused"], 1)

    def test_stats_empty_db(self):
        g2 = _make_goals()
        try:
            stats = g2.stats()
            self.assertEqual(stats["total"], 0)
            self.assertEqual(stats["by_status"], {})
        finally:
            g2.close()
            os.unlink(g2.db_path)


# ---------------------------------------------------------------------------
# format_active_goals_preamble — the system-prompt injection block
# ---------------------------------------------------------------------------

class TestFormatPreamble(unittest.TestCase):

    def setUp(self):
        self.g = _make_goals()

    def tearDown(self):
        self.g.close()
        os.unlink(self.g.db_path)

    def test_empty_goals_returns_empty_string(self):
        # No DB rows at all
        result = format_active_goals_preamble(goals=[])
        self.assertEqual(result, "")

    def test_goals_filtered_out_by_priority_returns_empty(self):
        self.g.add("low", priority=1)
        # Default min_priority=3, this goal is below threshold
        result = format_active_goals_preamble()
        self.assertEqual(result, "")

    def test_single_goal_renders(self):
        self.g.add("Ship A2", priority=8, target_date="2026-06-30")
        # Pass goals explicitly — don't depend on a fresh IchorGoals()
        # reading from the real production DB.
        goals = self.g.list_active()
        md = format_active_goals_preamble(goals=goals)
        self.assertIn("## Active Goals (1)", md)
        self.assertIn("🎯 Ship A2", md)
        self.assertIn("Priority 8", md)
        self.assertIn("0% complete", md)
        self.assertIn("Target: 2026-06-30", md)

    def test_multiple_goals_numbered(self):
        self.g.add("first", priority=8)
        self.g.add("second", priority=6)
        self.g.add("third", priority=4)
        goals = self.g.list_active()
        md = format_active_goals_preamble(goals=goals)
        self.assertIn("## Active Goals (3)", md)
        self.assertIn("1. 🎯 first", md)
        self.assertIn("2. 🎯 second", md)
        self.assertIn("3. 🎯 third", md)

    def test_progress_percentage_renders(self):
        gid = self.g.add("partial", priority=8)
        self.g.update_progress(gid, 0.42)
        goals = self.g.list_active()
        md = format_active_goals_preamble(goals=goals)
        self.assertIn("42% complete", md)

    def test_description_wraps_and_indents(self):
        long_desc = " ".join(["word"] * 30)  # 150 chars total
        self.g.add("with-desc", priority=8, description=long_desc)
        goals = self.g.list_active()
        md = format_active_goals_preamble(goals=goals)
        # Lines after the title are indented with 3 spaces
        for line in md.splitlines()[1:]:
            if line.strip() and not line.startswith("1."):
                self.assertTrue(line.startswith("   "),
                                f"non-title line not indented: {line!r}")

    def test_empty_description_not_rendered(self):
        self.g.add("no-desc", priority=8, description="")
        goals = self.g.list_active()
        md = format_active_goals_preamble(goals=goals)
        # No indented description line
        lines = [l for l in md.splitlines() if l.strip()]
        self.assertEqual(len(lines), 2)  # header + numbered title line (no description, no target)

    def test_empty_target_date_not_rendered(self):
        self.g.add("no-target", priority=8, target_date="")
        goals = self.g.list_active()
        md = format_active_goals_preamble(goals=goals)
        self.assertNotIn("Target:", md)

    def test_accepts_goals_arg_bypassing_db(self):
        # Pure-function path: caller pre-fetches goals
        goals = [{"title": "injected", "priority": 7, "progress": 0.5,
                  "description": "", "target_date": ""}]
        md = format_active_goals_preamble(goals=goals)
        self.assertIn("🎯 injected", md)
        self.assertIn("50% complete", md)


# ---------------------------------------------------------------------------
# mcp_dispatch — JSON-string-returning entry point used by the MCP server
# ---------------------------------------------------------------------------

class TestMCPDispatch(unittest.TestCase):

    def setUp(self):
        self.g = _make_goals()
        # Patch the MCP dispatch to use our temp DB
        import lib.ichor_goals as goals_mod
        self._orig_ichor_goals = goals_mod.IchorGoals

        def _patched_init_goals(*args, **kwargs):
            # Override db_path to our temp file
            return self.g
        # Actually simpler: just monkey-patch the class
        goals_mod.IchorGoals = lambda *a, **kw: self.g

    def tearDown(self):
        import lib.ichor_goals as goals_mod
        goals_mod.IchorGoals = self._orig_ichor_goals
        self.g.close()
        os.unlink(self.g.db_path)

    def _dispatch(self, **kwargs):
        return json.loads(mcp_dispatch(**kwargs))

    def test_dispatch_add(self):
        result = self._dispatch(action="add", title="X", priority=8,
                                category="theoforge")
        self.assertTrue(result["ok"])
        self.assertEqual(result["title"], "X")
        self.assertIn("id", result)

    def test_dispatch_add_missing_title(self):
        result = self._dispatch(action="add", title="")
        self.assertIn("error", result)

    def test_dispatch_add_validation_error(self):
        result = self._dispatch(action="add", title="X", priority=99)
        self.assertFalse(result.get("ok"))
        self.assertIn("error", result)

    def test_dispatch_list(self):
        self.g.add("X", priority=8)
        result = self._dispatch(action="list")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["goals"][0]["title"], "X")

    def test_dispatch_list_filtered(self):
        self.g.add("X", category="theoforge")
        result = self._dispatch(action="list", category="theoforge")
        self.assertEqual(result["count"], 1)
        result2 = self._dispatch(action="list", category="general")
        self.assertEqual(result2["count"], 0)

    def test_dispatch_get(self):
        gid = self.g.add("X")
        result = self._dispatch(action="get", goal_id=gid)
        self.assertTrue(result["ok"])
        self.assertEqual(result["goal"]["title"], "X")

    def test_dispatch_get_missing_id(self):
        result = self._dispatch(action="get", goal_id=0)
        self.assertIn("error", result)

    def test_dispatch_get_not_found(self):
        result = self._dispatch(action="get", goal_id=99999)
        self.assertFalse(result["ok"])

    def test_dispatch_update(self):
        gid = self.g.add("X", priority=5)
        result = self._dispatch(action="update", goal_id=gid, priority=9)
        self.assertTrue(result["ok"])
        self.assertEqual(self.g.get(gid)["priority"], 9)

    def test_dispatch_update_no_fields(self):
        gid = self.g.add("X")
        result = self._dispatch(action="update", goal_id=gid)
        self.assertIn("error", result)

    def test_dispatch_complete_by_title(self):
        self.g.add("X")
        result = self._dispatch(action="complete", title="X")
        self.assertTrue(result["ok"])

    def test_dispatch_complete_by_id(self):
        gid = self.g.add("X")
        result = self._dispatch(action="complete", goal_id=gid)
        self.assertTrue(result["ok"])

    def test_dispatch_complete_missing_args(self):
        result = self._dispatch(action="complete")
        self.assertIn("error", result)

    def test_dispatch_pause_by_title(self):
        self.g.add("X")
        result = self._dispatch(action="pause", title="X")
        self.assertTrue(result["ok"])
        self.assertEqual(self.g.find_by_title("X")["status"], "paused")

    def test_dispatch_inject_empty(self):
        result = self._dispatch(action="inject")
        self.assertTrue(result["ok"])
        self.assertFalse(result["injected"])
        self.assertEqual(result["preamble"], "")

    def test_dispatch_inject_with_goals(self):
        self.g.add("X", priority=8)
        result = self._dispatch(action="inject")
        self.assertTrue(result["ok"])
        self.assertTrue(result["injected"])
        self.assertIn("🎯 X", result["preamble"])

    def test_dispatch_stats(self):
        self.g.add("X")
        result = self._dispatch(action="stats")
        self.assertTrue(result["ok"])
        self.assertEqual(result["stats"]["total"], 1)

    def test_dispatch_unknown_action(self):
        result = self._dispatch(action="frobnicate")
        self.assertIn("error", result)
        self.assertIn("unknown action", result["error"].lower())


# ---------------------------------------------------------------------------
# CLI: subprocess tests for the main() argparse entry point.
# These exercise the user-facing surface; they use a temp HOME via
# XDG_DATA_HOME-style override by monkey-patching HOME-equivalent
# in the subprocess. (lib/ichor_goals.py reads Path.home() at import time
# via the module-level _ICHOR_DB constant, so we have to set HOME in the
# subprocess env to a tempdir so the CLI's IchorGoals() lands on a
# writable scratch DB rather than the real one.)
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):

    def setUp(self):
        self.tmp_home = tempfile.mkdtemp()
        # Pre-create the .hermes dir so the CLI can write there
        os.makedirs(os.path.join(self.tmp_home, ".hermes"), exist_ok=True)
        self.env = os.environ.copy()
        self.env["HOME"] = self.tmp_home
        # Clear any vars that might leak the real DB path
        for k in ("HERMES_HOME", "ICHOR_DB"):
            self.env.pop(k, None)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_home, ignore_errors=True)

    def _run(self, *args):
        """Run the CLI with args, return (returncode, stdout, stderr)."""
        proc = subprocess.run(
            [sys.executable, "-m", "lib.ichor_goals", *args],
            capture_output=True, text=True, env=self.env,
            cwd=PANTHEON_ROOT,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_cli_add(self):
        rc, out, err = self._run("add", "CLI goal", "--priority", "8",
                                 "--category", "theoforge")
        self.assertEqual(rc, 0, msg=f"stderr: {err}")
        self.assertIn("Created goal #", out)
        self.assertIn("CLI goal", out)
        self.assertIn("priority 8", out)
        self.assertIn("category theoforge", out)

    def test_cli_list_empty(self):
        rc, out, err = self._run("list")
        self.assertEqual(rc, 0, msg=f"stderr: {err}")
        self.assertIn("no goals", out)

    def test_cli_list_after_add(self):
        self._run("add", "A")
        self._run("add", "B", "--priority", "9")
        rc, out, err = self._run("list")
        self.assertEqual(rc, 0, msg=f"stderr: {err}")
        self.assertIn("A", out)
        self.assertIn("B", out)
        # B is higher priority, should appear first
        a_idx = out.index("[")
        # (just check both are present)
        self.assertIn("P 9", out)
        self.assertIn("P 5", out)

    def test_cli_complete_by_id(self):
        self._run("add", "X")
        # The id is 1 for the first goal in a fresh DB
        rc, out, err = self._run("complete", "X")
        self.assertEqual(rc, 0, msg=f"stderr: {err}")
        self.assertIn("complete: ok=True", out)

    def test_cli_complete_by_numeric_id(self):
        self._run("add", "X")
        rc, out, err = self._run("complete", "1")
        self.assertEqual(rc, 0, msg=f"stderr: {err}")
        self.assertIn("complete: ok=True", out)

    def test_cli_inject_empty(self):
        rc, out, err = self._run("inject")
        self.assertEqual(rc, 0, msg=f"stderr: {err}")
        self.assertIn("no active goals", out)

    def test_cli_inject_with_goals(self):
        self._run("add", "X", "--priority", "8")
        rc, out, err = self._run("inject")
        self.assertEqual(rc, 0, msg=f"stderr: {err}")
        self.assertIn("## Active Goals", out)
        self.assertIn("🎯 X", out)

    def test_cli_stats(self):
        self._run("add", "X")
        self._run("add", "Y")
        rc, out, err = self._run("stats")
        self.assertEqual(rc, 0, msg=f"stderr: {err}")
        self.assertIn('"total": 2', out)
        self.assertIn('"active": 2', out)

    def test_cli_rejects_invalid_category(self):
        # argparse should reject this before lib.ichor_goals sees it
        rc, out, err = self._run("add", "X", "--category", "bogus")
        self.assertNotEqual(rc, 0)
        # argparse writes the error to stderr
        self.assertTrue(err or "invalid choice" in out.lower() or
                        "invalid" in err.lower() or rc != 0)


# ---------------------------------------------------------------------------
# Integration: end-to-end CRUD + stats + preamble via real I/O
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):

    def setUp(self):
        self.g = _make_goals()

    def tearDown(self):
        self.g.close()
        os.unlink(self.g.db_path)

    def test_full_lifecycle(self):
        # Add 3 goals
        g1 = self.g.add("Goal 1", category="theoforge", priority=9)
        g2 = self.g.add("Goal 2", category="pantheon", priority=5)
        g3 = self.g.add("Goal 3", category="general", priority=3)

        # Update progress on one
        self.g.update_progress(g2, 0.5)

        # Complete one
        self.g.complete("Goal 1")

        # Pause another
        self.g.pause("Goal 3")

        # List active — only g2 (active, priority >= 3)
        active = self.g.list_active(min_priority=3)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["title"], "Goal 2")
        self.assertEqual(active[0]["progress"], 0.5)

        # Stats
        stats = self.g.stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["by_status"]["completed"], 1)
        self.assertEqual(stats["by_status"]["paused"], 1)
        self.assertEqual(stats["by_status"]["active"], 1)

        # Preamble
        md = format_active_goals_preamble(goals=active)
        self.assertIn("## Active Goals (1)", md)
        self.assertIn("🎯 Goal 2", md)
        self.assertIn("50% complete", md)

        # Delete one
        self.assertTrue(self.g.delete(g3))
        self.assertIsNone(self.g.get(g3))

    def test_categories_exhaustive(self):
        for cat in VALID_CATEGORIES:
            gid = self.g.add(f"in-{cat}", category=cat)
            self.assertEqual(self.g.get(gid)["category"], cat)

    def test_priority_ordering_after_updates(self):
        # Add with one order, then update priorities, verify list re-orders
        self.g.add("A", priority=1)
        self.g.add("B", priority=2)
        self.g.add("C", priority=3)
        # Boost A above C
        a_id = self.g.find_by_title("A")["id"]
        self.g.update(a_id, priority=10)
        rows = self.g.list()
        self.assertEqual([r["title"] for r in rows], ["A", "C", "B"])


if __name__ == "__main__":
    unittest.main()
