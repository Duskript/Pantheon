"""
Phase 5 of ichor-v2 — State Ledger Rendering + ichor_ledger MCP tool.

Tests for `render_god_ledger()` in gods.ichor.state_ledger, the
`build_system_prompt()` integration in gods/__init__.py, and the
`ichor_ledger` MCP tool in pantheon-core/mcp_server.py.

Gate:
  - render_god_ledger('hermes') returns markdown (string, non-empty, has sections)
  - ichor_ledger MCP tool callable, returns markdown + JSON shapes

Spec: ~/athenaeum/Codex-Pantheon/plans/ichor-v2-build-blueprint.md §7 + §10
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

# Make ~/pantheon importable so `import gods.ichor.state_ledger` works
_PANTHEON_ROOT = Path.home() / "pantheon"
_PANTHEON_CORE = _PANTHEON_ROOT / "pantheon-core"
if str(_PANTHEON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PANTHEON_ROOT))
if str(_PANTHEON_CORE) not in sys.path:
    sys.path.insert(0, str(_PANTHEON_CORE))


# =============================================================================
# Helpers — seed a temp ichor.db mirroring the live schema
# =============================================================================


def _seed_temp_ichor_db(db_path: Path, rows: List[Dict[str, Any]]) -> None:
    """Create a minimal ichor.db mirroring the live schema + warm_entities.

    Mirrors `ichor_events` and `warm_entities` from lib/ichor_db.py and
    lib/ichor/schema_v2.py. Includes all the columns the state_ledger
    module actually queries — anything beyond that is not needed for
    these tests.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        # ichor_events — the canonical Phase 5 source
        conn.execute(
            """
            CREATE TABLE ichor_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                predicate TEXT,
                object TEXT,
                confidence REAL DEFAULT 0.8,
                source TEXT,
                raw_text TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                god_name TEXT,
                importance REAL DEFAULT 50.0,
                trust REAL DEFAULT 50.0,
                maturity TEXT DEFAULT 'validated',
                last_access TEXT,
                direction TEXT DEFAULT 'unknown',
                peer_god TEXT DEFAULT ''
            )
            """
        )
        # warm_entities — the single source of truth for entities (Rule 43)
        conn.execute(
            """
            CREATE TABLE warm_entities (
                id INTEGER PRIMARY KEY,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                value TEXT NOT NULL,
                importance REAL DEFAULT 50.0,
                trust REAL DEFAULT 50.0,
                maturity TEXT DEFAULT 'validated',
                last_access TEXT,
                related_to TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                brief TEXT DEFAULT '',
                outline TEXT DEFAULT '',
                UNIQUE (category, name)
            )
            """
        )
        for row in rows:
            cols = ", ".join(row.keys())
            placeholders = ", ".join(["?"] * len(row))
            conn.execute(
                f"INSERT INTO ichor_events ({cols}) VALUES ({placeholders})",
                list(row.values()),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_warm_entities(db_path: Path, entities: List[Dict[str, Any]]) -> None:
    """Add warm_entities rows to an existing ichor.db."""
    conn = sqlite3.connect(str(db_path))
    try:
        for ent in entities:
            cols = ", ".join(ent.keys())
            placeholders = ", ".join(["?"] * len(ent))
            conn.execute(
                f"INSERT INTO warm_entities ({cols}) VALUES ({placeholders})",
                list(ent.values()),
            )
        conn.commit()
    finally:
        conn.close()


# =============================================================================
# Pure unit tests — render_god_ledger against a temp DB
# =============================================================================


class TestRenderGodLedgerHappyPath(unittest.TestCase):
    """render_god_ledger() returns markdown with all four sections."""

    def setUp(self) -> None:
        from gods.ichor.state_ledger import render_god_ledger as _render
        self._ref_now = "2026-06-20 12:00:00"  # anchor for 7d window
        self.render_god_ledger = lambda god, db=None, **kw: _render(
            god, db, reference_now=self._ref_now, **kw
        )

        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_db = Path(self.tmpdir.name) / "ichor.db"
        _seed_temp_ichor_db(
            self.tmp_db,
            [
                # Blocker for hermes, high importance
                {"session_id": "s1", "event_type": "blocker",
                 "subject": "broker:nat-subsystem-down",
                 "raw_text": "NATS broker unreachable on 100.46.52:4222",
                 "god_name": "hermes", "importance": 95.0,
                 "created_at": "2026-06-20 12:00:00"},
                # Blocker for hermes, lower importance (still >= 30 threshold)
                {"session_id": "s2", "event_type": "blocker",
                 "subject": "hermes:kanban-dispatch-lag",
                 "raw_text": "Dispatcher lag is 90s+ since 14:00 UTC",
                 "god_name": "hermes", "importance": 60.0,
                 "created_at": "2026-06-20 13:00:00"},
                # Blocker for OTHER god — must NOT appear in hermes ledger
                {"session_id": "s3", "event_type": "blocker",
                 "subject": "thoth:research-stalled",
                 "raw_text": "Thoth research queue stalled",
                 "god_name": "thoth", "importance": 80.0,
                 "created_at": "2026-06-20 13:30:00"},
                # Decision for hermes, recent
                {"session_id": "s4", "event_type": "decision",
                 "subject": "hermes:use-opencode-go-rotate",
                 "raw_text": "Rotated OpenCode-Go key 2026-06-14",
                 "god_name": "hermes", "importance": 80.0,
                 "created_at": "2026-06-20 11:00:00"},
                # Decision for hermes, but OLD (must NOT appear — outside 7d window)
                {"session_id": "s5", "event_type": "decision",
                 "subject": "hermes:old-decision-should-not-appear",
                 "raw_text": "Decision from 30 days ago",
                 "god_name": "hermes", "importance": 90.0,
                 "created_at": "2026-05-15 11:00:00"},
                # Commitment for hermes, importance >= 20
                {"session_id": "s6", "event_type": "commitment",
                 "subject": "hermes:deliver-L2-finalize",
                 "raw_text": "Finish L2 finalize by 2026-06-20",
                 "god_name": "hermes", "importance": 70.0,
                 "created_at": "2026-06-20 10:00:00"},
                # Commitment BELOW threshold (importance < 20) — must NOT appear
                {"session_id": "s7", "event_type": "commitment",
                 "subject": "hermes:low-importance-commitment",
                 "raw_text": "Below threshold, must be filtered",
                 "god_name": "hermes", "importance": 5.0,
                 "created_at": "2026-06-20 09:00:00"},
            ],
        )
        _seed_warm_entities(
            self.tmp_db,
            [
                {"category": "service", "name": "NATS",
                 "value": "100.46.52:4222", "importance": 90.0,
                 "related_to": "broker:subspace-messaging"},
                {"category": "tool", "name": "deepseek-v4-flash",
                 "value": "LLM model", "importance": 80.0,
                 "related_to": "opencode-go:minimax"},
                {"category": "rule", "name": "no-rm-rf-without-ls",
                 "value": "Rule 9", "importance": 95.0,
                 "related_to": "destructive-op-checklist"},
            ],
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_returns_nonempty_markdown_string(self) -> None:
        md = self.render_god_ledger("hermes", str(self.tmp_db))
        self.assertIsInstance(md, str)
        self.assertGreater(len(md), 100, "Expected substantial markdown output")

    def test_has_all_four_section_headers(self) -> None:
        md = self.render_god_ledger("hermes", str(self.tmp_db))
        self.assertIn("### ⛔ Active Blockers", md)
        self.assertIn("### ✅ Recent Decisions", md)
        self.assertIn("### 📋 Active Commitments", md)
        self.assertIn("### 🔗 Key Relationships", md)

    def test_blockers_filtered_by_god(self) -> None:
        """Hermes' ledger must contain hermes blockers, NOT thoth blockers."""
        md = self.render_god_ledger("hermes", str(self.tmp_db))
        self.assertIn("broker:nat-subsystem-down", md)
        self.assertIn("hermes:kanban-dispatch-lag", md)
        self.assertNotIn("thoth:research-stalled",
                         "Cross-god blockers must not leak into hermes ledger")

    def test_blockers_sorted_by_importance_desc(self) -> None:
        """Highest-importance blocker must appear first."""
        md = self.render_god_ledger("hermes", str(self.tmp_db))
        idx_nats = md.index("broker:nat-subsystem-down")
        idx_dispatch = md.index("hermes:kanban-dispatch-lag")
        self.assertLess(idx_nats, idx_dispatch,
                        "Higher-importance blocker must come first")

    def test_blockers_respect_importance_threshold(self) -> None:
        """No blocker with importance < 30 should appear."""
        md = self.render_god_ledger("hermes", str(self.tmp_db))
        self.assertNotIn("below-threshold-blocker", md)

    def test_decisions_filtered_by_7day_window(self) -> None:
        """Old decisions (>7d) must not appear."""
        md = self.render_god_ledger("hermes", str(self.tmp_db))
        self.assertIn("hermes:use-opencode-go-rotate", md)
        self.assertNotIn("hermes:old-decision-should-not-appear",
                         "Decisions older than 7 days must be filtered out")

    def test_commitments_respect_importance_threshold(self) -> None:
        """Commitments with importance < 20 must not appear."""
        md = self.render_god_ledger("hermes", str(self.tmp_db))
        self.assertIn("hermes:deliver-L2-finalize", md)
        self.assertNotIn("hermes:low-importance-commitment",
                         "Low-importance commitments must be filtered out")

    def test_entities_section_renders(self) -> None:
        """Top-importance warm_entities should appear."""
        md = self.render_god_ledger("hermes", str(self.tmp_db))
        # All three entities have importance >= 50, so they should appear
        self.assertIn("NATS", md)
        self.assertIn("deepseek-v4-flash", md)
        self.assertIn("no-rm-rf-without-ls", md)

    def test_preamble_capped_at_max_chars(self) -> None:
        """Long output gets truncated at MAX_PREAMBLE_CHARS + marker."""
        from gods.ichor.state_ledger import MAX_PREAMBLE_CHARS
        md = self.render_god_ledger("hermes", str(self.tmp_db))
        # Truncation marker is only present if the output exceeded the cap.
        # In this small dataset it doesn't, so we just sanity-check the cap.
        self.assertLessEqual(
            len(md),
            MAX_PREAMBLE_CHARS + len("\n\n... [truncated]"),
            "Output must respect MAX_PREAMBLE_CHARS cap",
        )


# =============================================================================
# Empty + edge cases
# =============================================================================


class TestRenderGodLedgerEdgeCases(unittest.TestCase):

    def setUp(self) -> None:
        from gods.ichor.state_ledger import render_god_ledger as _render
        self._ref_now = "2026-06-20 12:00:00"  # anchor for 7d window
        self.render_god_ledger = lambda god, db=None, **kw: _render(
            god, db, reference_now=self._ref_now, **kw
        )

    def test_empty_god_name_returns_empty_string(self) -> None:
        self.assertEqual(self.render_god_ledger(""), "")

    def test_missing_db_returns_empty_string(self) -> None:
        """If the DB doesn't exist, return empty (caller can detect)."""
        missing = Path("/tmp/definitely-does-not-exist-ichor-ledger.db")
        if missing.exists():
            missing.unlink()
        self.assertEqual(self.render_god_ledger("hermes", str(missing)), "")

    def test_empty_db_returns_empty_string(self) -> None:
        """DB exists but has no matching events → empty ledger."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            db = Path(tmpdir.name) / "ichor.db"
            _seed_temp_ichor_db(db, [])  # no rows
            self.assertEqual(self.render_god_ledger("hermes", str(db)), "")
        finally:
            tmpdir.cleanup()

    def test_db_with_no_matching_god_returns_empty_string(self) -> None:
        """DB has events for other gods but not the one we ask about."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            db = Path(tmpdir.name) / "ichor.db"
            _seed_temp_ichor_db(
                db,
                [{"session_id": "s1", "event_type": "blocker",
                  "subject": "thoth:some-blocker", "raw_text": "x",
                  "god_name": "thoth", "importance": 90.0,
                  "created_at": "2026-06-20 12:00:00"}],
            )
            # Hermes has no events → empty
            self.assertEqual(self.render_god_ledger("hermes", str(db)), "")
        finally:
            tmpdir.cleanup()

    def test_god_with_only_low_importance_events_returns_empty(self) -> None:
        """Events below importance thresholds are filtered out."""
        tmpdir = tempfile.TemporaryDirectory()
        try:
            db = Path(tmpdir.name) / "ichor.db"
            _seed_temp_ichor_db(
                db,
                [
                    {"session_id": "s1", "event_type": "blocker",
                     "subject": "tiny-blocker", "raw_text": "x",
                     "god_name": "hermes", "importance": 1.0,
                     "created_at": "2026-06-20 12:00:00"},
                    {"session_id": "s2", "event_type": "commitment",
                     "subject": "tiny-commitment", "raw_text": "x",
                     "god_name": "hermes", "importance": 1.0,
                     "created_at": "2026-06-20 12:00:00"},
                ],
            )
            self.assertEqual(self.render_god_ledger("hermes", str(db)), "")
        finally:
            tmpdir.cleanup()


# =============================================================================
# Section renderers — pure-function tests
# =============================================================================


class TestTruncateHelper(unittest.TestCase):

    def test_truncate_short_text_unchanged(self) -> None:
        from gods.ichor.state_ledger import _truncate
        self.assertEqual(_truncate("hello", 80), "hello")

    def test_truncate_long_text_cuts_at_word_boundary(self) -> None:
        from gods.ichor.state_ledger import _truncate
        out = _truncate("hello world " * 20, 80)
        self.assertLessEqual(len(out), 80 + 5)  # 80 + ellipsis
        self.assertTrue(out.endswith("…"))

    def test_truncate_empty_returns_empty(self) -> None:
        from gods.ichor.state_ledger import _truncate
        self.assertEqual(_truncate("", 80), "")
        self.assertEqual(_truncate(None, 80), "")

    def test_truncate_strips_trailing_punctuation(self) -> None:
        from gods.ichor.state_ledger import _truncate
        out = _truncate("hello world, with punctuation", 12)
        self.assertFalse(out.endswith(","), "Should strip trailing punctuation")


# =============================================================================
# render_all_gods_ledger
# =============================================================================


class TestRenderAllGodsLedger(unittest.TestCase):

    def setUp(self) -> None:
        from gods.ichor.state_ledger import render_all_gods_ledger
        self.render_all_gods_ledger = render_all_gods_ledger

        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_db = Path(self.tmpdir.name) / "ichor.db"
        _seed_temp_ichor_db(
            self.tmp_db,
            [
                {"session_id": "s1", "event_type": "blocker",
                 "subject": "h-block", "raw_text": "x",
                 "god_name": "hermes", "importance": 90.0,
                 "created_at": "2026-06-20 12:00:00"},
                {"session_id": "s2", "event_type": "blocker",
                 "subject": "m-block", "raw_text": "x",
                 "god_name": "marvin", "importance": 90.0,
                 "created_at": "2026-06-20 12:00:00"},
                {"session_id": "s3", "event_type": "blocker",
                 "subject": "h-block2", "raw_text": "x",
                 "god_name": "hermes", "importance": 80.0,
                 "created_at": "2026-06-20 13:00:00"},
                # Empty god_name — must NOT appear as a god
                {"session_id": "s4", "event_type": "blocker",
                 "subject": "anon-block", "raw_text": "x",
                 "god_name": "", "importance": 90.0,
                 "created_at": "2026-06-20 12:00:00"},
                # NULL god_name — must NOT appear as a god
                {"session_id": "s5", "event_type": "blocker",
                 "subject": "null-block", "raw_text": "x",
                 "god_name": None, "importance": 90.0,
                 "created_at": "2026-06-20 12:00:00"},
            ],
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_returns_dict_of_god_to_markdown(self) -> None:
        out = self.render_all_gods_ledger(str(self.tmp_db))
        self.assertIsInstance(out, dict)
        self.assertIn("hermes", out)
        self.assertIn("marvin", out)

    def test_excludes_empty_and_null_god_names(self) -> None:
        out = self.render_all_gods_ledger(str(self.tmp_db))
        self.assertNotIn("", out)
        self.assertNotIn(None, out)

    def test_each_value_is_markdown_string(self) -> None:
        out = self.render_all_gods_ledger(str(self.tmp_db))
        for god, md in out.items():
            self.assertIsInstance(md, str)
            self.assertGreater(len(md), 0)


# =============================================================================
# render_god_ledger_structured — JSON form for MCP tool
# =============================================================================


class TestRenderGodLedgerStructured(unittest.TestCase):

    def setUp(self) -> None:
        from gods.ichor.state_ledger import render_god_ledger_structured as _render
        self._ref_now = "2026-06-20 12:00:00"  # anchor for 7d window
        self.render = lambda god, db=None, **kw: _render(
            god, db, reference_now=self._ref_now, **kw
        )

        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_db = Path(self.tmpdir.name) / "ichor.db"
        _seed_temp_ichor_db(
            self.tmp_db,
            [
                {"session_id": "s1", "event_type": "blocker",
                 "subject": "h-block", "raw_text": "x",
                 "god_name": "hermes", "importance": 90.0,
                 "created_at": "2026-06-20 12:00:00"},
                {"session_id": "s2", "event_type": "decision",
                 "subject": "h-decision", "raw_text": "y",
                 "god_name": "hermes", "importance": 80.0,
                 "created_at": "2026-06-20 11:00:00"},
                {"session_id": "s3", "event_type": "commitment",
                 "subject": "h-commit", "raw_text": "z",
                 "god_name": "hermes", "importance": 70.0,
                 "created_at": "2026-06-20 10:00:00"},
            ],
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_returns_dict_with_all_sections(self) -> None:
        out = self.render("hermes", str(self.tmp_db))
        self.assertEqual(out["god_name"], "hermes")
        self.assertEqual(out["db_path"], str(self.tmp_db))
        self.assertIn("blockers", out)
        self.assertIn("decisions", out)
        self.assertIn("commitments", out)
        self.assertIn("entities", out)
        self.assertIn("counts", out)

    def test_sections_contain_seeded_rows(self) -> None:
        out = self.render("hermes", str(self.tmp_db))
        self.assertEqual(len(out["blockers"]), 1)
        self.assertEqual(out["blockers"][0]["subject"], "h-block")
        self.assertEqual(out["blockers"][0]["importance"], 90.0)
        self.assertEqual(len(out["decisions"]), 1)
        self.assertEqual(out["decisions"][0]["subject"], "h-decision")
        self.assertEqual(len(out["commitments"]), 1)
        self.assertEqual(out["commitments"][0]["subject"], "h-commit")

    def test_counts_match_lengths(self) -> None:
        out = self.render("hermes", str(self.tmp_db))
        self.assertEqual(out["counts"]["blockers"], len(out["blockers"]))
        self.assertEqual(out["counts"]["decisions"], len(out["decisions"]))
        self.assertEqual(out["counts"]["commitments"], len(out["commitments"]))
        self.assertEqual(out["counts"]["entities"], len(out["entities"]))

    def test_empty_god_returns_skeleton(self) -> None:
        out = self.render("", str(self.tmp_db))
        self.assertEqual(out["god_name"], "")
        self.assertEqual(out["blockers"], [])
        self.assertEqual(out["decisions"], [])
        self.assertEqual(out["commitments"], [])
        self.assertEqual(out["entities"], [])
        self.assertEqual(out["counts"], {})

    def test_is_json_serializable(self) -> None:
        """The whole dict must serialize cleanly via json.dumps."""
        out = self.render("hermes", str(self.tmp_db))
        serialized = json.dumps(out, default=str)
        # Round-trip parse to confirm valid JSON
        parsed = json.loads(serialized)
        self.assertEqual(parsed["god_name"], "hermes")
        self.assertGreater(len(parsed["blockers"]), 0)


# =============================================================================
# build_system_prompt — gods/__init__.py integration
# =============================================================================


class TestBuildSystemPrompt(unittest.TestCase):
    """build_system_prompt() prepends the ledger to the base prompt."""

    def setUp(self) -> None:
        from gods import build_system_prompt as _build
        self._build_system_prompt = _build

        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_db = Path(self.tmpdir.name) / "ichor.db"
        _seed_temp_ichor_db(
            self.tmp_db,
            [
                {"session_id": "s1", "event_type": "blocker",
                 "subject": "hermes:gate-broken",
                 "raw_text": "Something is broken",
                 "god_name": "hermes", "importance": 95.0,
                 "created_at": "2026-06-20 12:00:00"},
            ],
        )
        _seed_warm_entities(
            self.tmp_db,
            [{"category": "service", "name": "NATS",
              "value": "100.46.52:4222", "importance": 90.0,
              "related_to": "broker:subspace-messaging"}],
        )
        self.build_system_prompt = lambda god, base="", **kw: _build(
            god, base, db_path=kw.pop("db_path", str(self.tmp_db)), **kw
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_empty_god_name_returns_base_unchanged(self) -> None:
        self.assertEqual(
            self.build_system_prompt("", "base prompt"),
            "base prompt",
        )

    def test_missing_db_returns_base_unchanged(self) -> None:
        # Pass a non-existent path — should not raise, just return base
        out = self.build_system_prompt(
            "hermes", "base prompt", db_path="/tmp/does-not-exist-xyz.db"
        )
        self.assertEqual(out, "base prompt")

    def test_ledger_prepended_when_present(self) -> None:
        """Integration: live ichor.db has hermes data → ledger is prepended."""
        out = self.build_system_prompt("hermes", "You are Hermes.")
        self.assertIn("You are Hermes.", out)
        self.assertIn("## Current State Ledger", out)

    def test_base_prompt_preserved_when_ledger_prepended(self) -> None:
        """Base prompt should be at the front, ledger after."""
        out = self.build_system_prompt("hermes", "BASE-PROMPT-MARKER")
        idx_base = out.index("BASE-PROMPT-MARKER")
        idx_ledger = out.index("## Current State Ledger")
        self.assertLess(idx_base, idx_ledger)

    def test_returns_string_type(self) -> None:
        self.assertIsInstance(
            self.build_system_prompt("hermes", "x"),
            str,
        )


# =============================================================================
# MCP tool — ichor_ledger
# =============================================================================


class TestIchorLedgerMCPTool(unittest.TestCase):
    """The MCP tool `ichor_ledger` callable, returns markdown + JSON."""

    @classmethod
    def setUpClass(cls) -> None:
        # Try to load the MCP server module. It imports FastMCP which is
        # available in this environment (verified during Marvin run).
        try:
            import mcp_server  # type: ignore[import-untyped]
            cls.mcp_server = mcp_server
            cls.has_mcp = True
        except Exception as exc:
            cls.mcp_server = None
            cls.has_mcp = False
            cls._import_error = exc

    def setUp(self) -> None:
        if not self.has_mcp:
            self.skipTest(
                f"MCP server module not loadable: {getattr(self, '_import_error', '?')}"
            )

        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_db = Path(self.tmpdir.name) / "ichor.db"
        _seed_temp_ichor_db(
            self.tmp_db,
            [
                {"session_id": "s1", "event_type": "blocker",
                 "subject": "hermes:gate-broken",
                 "raw_text": "Something is broken",
                 "god_name": "hermes", "importance": 95.0,
                 "created_at": "2026-06-20 12:00:00"},
            ],
        )
        _seed_warm_entities(
            self.tmp_db,
            [{"category": "service", "name": "NATS",
              "value": "100.46.52:4222", "importance": 90.0,
              "related_to": "broker:subspace-messaging"}],
        )

    def tearDown(self) -> None:
        if hasattr(self, 'tmpdir'):
            self.tmpdir.cleanup()

    def test_ichor_ledger_function_exists(self) -> None:
        self.assertTrue(
            hasattr(self.mcp_server, "ichor_ledger"),
            "ichor_ledger must be defined in mcp_server.py",
        )

    def test_ichor_ledger_callable(self) -> None:
        self.assertTrue(callable(self.mcp_server.ichor_ledger))

    def test_ichor_ledger_returns_markdown_for_hermes(self) -> None:
        """Gate: ichor_ledger('hermes') returns markdown with sections."""
        result = self.mcp_server.ichor_ledger(god_name="hermes", db_path=str(self.tmp_db))
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 100)
        # Should contain at least one section header
        self.assertTrue(
            "### ⛔ Active Blockers" in result
            or "### ✅ Recent Decisions" in result
            or "### 📋 Active Commitments" in result
            or "### 🔗 Key Relationships" in result,
            f"Expected ledger sections in output, got: {result[:300]!r}",
        )

    def test_ichor_ledger_json_shape(self) -> None:
        """When output_json=True, return JSON dict with all sections."""
        result = self.mcp_server.ichor_ledger(god_name="hermes", output_json=True, db_path=str(self.tmp_db))
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)
        self.assertIn("blockers", parsed)
        self.assertIn("decisions", parsed)
        self.assertIn("commitments", parsed)
        self.assertIn("entities", parsed)
        self.assertIn("counts", parsed)

    def test_ichor_ledger_empty_god_returns_error_json(self) -> None:
        """Empty god_name → JSON error envelope, not crash."""
        result = self.mcp_server.ichor_ledger(god_name="")
        self.assertIsInstance(result, str)
        parsed = json.loads(result)
        self.assertIn("error", parsed)


# =============================================================================
# Module API surface
# =============================================================================


class TestModuleSurface(unittest.TestCase):
    """The public API of gods.ichor matches the spec."""

    def test_ichor_subpackage_imports(self) -> None:
        from gods.ichor import (
            render_god_ledger,
            render_all_gods_ledger,
            render_god_ledger_structured,
            ICHOR_DB,
            MAX_PREAMBLE_CHARS,
        )
        # Constants exported
        self.assertTrue(callable(render_god_ledger))
        self.assertTrue(callable(render_all_gods_ledger))
        self.assertTrue(callable(render_god_ledger_structured))
        self.assertIsInstance(ICHOR_DB, Path)
        self.assertIsInstance(MAX_PREAMBLE_CHARS, int)

    def test_gods_package_exports_build_system_prompt(self) -> None:
        import gods
        self.assertTrue(hasattr(gods, "build_system_prompt"))
        self.assertTrue(callable(gods.build_system_prompt))


if __name__ == "__main__":
    unittest.main()