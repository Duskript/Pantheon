"""
Phase 3 of ichor-v2 — provenance enforcement (athenaeum write hook).

Tests for `_check_provenance`, `_cold_event_exists`,
`_parse_frontmatter_sources`, and the integration into the
`athenaeum_write` MCP tool.

Gate: warm_entities / reference_knowledge writes cite cold_event sources.
- Missing sources: soft warn (allowed, message non-empty).
- Cited-but-missing cold_event key: hard reject (allowed=False).
- Non-triggering codex: pass-through, no message.
- Non-triggering path: pass-through.

Spec: ~/athenaeum/Codex-Pantheon/plans/ichor-v2-build-blueprint.md §5
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# Make ~/pantheon importable so we can `import mcp_server` against the
# real source. We do NOT spin up the FastMCP server — we import the
# module which exposes the helper functions at module scope.
_PANTHEON = Path.home() / "pantheon"
if str(_PANTHEON) not in sys.path:
    sys.path.insert(0, str(_PANTHEON))
sys.path.insert(0, str(_PANTHEON / "pantheon-core"))


def _import_helpers():
    """Import the helpers fresh, bypassing the FastMCP server start."""
    import mcp_server  # type: ignore
    return {
        "check": mcp_server._check_provenance,
        "exists": mcp_server._cold_event_exists,
        "parse": mcp_server._parse_frontmatter_sources,
        "codexes": mcp_server._PROVENANCE_CODEXES,
        "write": mcp_server.athenaeum_write,
    }


_HELPERS = _import_helpers()


# =============================================================================
# Pure-function tests for _parse_frontmatter_sources
# =============================================================================


class TestParseFrontmatterSources(unittest.TestCase):
    """YAML frontmatter parser — accepts valid frontmatter, rejects garbage."""

    def test_no_frontmatter_returns_empty(self) -> None:
        self.assertEqual(_HELPERS["parse"]("just plain markdown"), [])

    def test_empty_string_returns_empty(self) -> None:
        self.assertEqual(_HELPERS["parse"](""), [])

    def test_non_string_returns_empty(self) -> None:
        # Type-flexible contract: non-string content (e.g. legacy dict callers)
        # should not crash.
        self.assertEqual(_HELPERS["parse"](None), [])  # type: ignore[arg-type]
        self.assertEqual(_HELPERS["parse"](12345), [])  # type: ignore[arg-type]

    def test_simple_sources_list(self) -> None:
        content = "---\nsources: [a, b, c]\n---\nbody"
        self.assertEqual(_HELPERS["parse"](content), ["a", "b", "c"])

    def test_sources_as_yaml_block(self) -> None:
        content = (
            "---\n"
            "title: foo\n"
            "sources:\n"
            "  - k_one\n"
            "  - k_two\n"
            "---\n"
            "body"
        )
        self.assertEqual(_HELPERS["parse"](content), ["k_one", "k_two"])

    def test_missing_sources_key_returns_empty(self) -> None:
        content = "---\ntitle: foo\n---\nbody"
        self.assertEqual(_HELPERS["parse"](content), [])

    def test_sources_not_a_list_returns_empty(self) -> None:
        content = "---\nsources: just_a_string\n---\nbody"
        self.assertEqual(_HELPERS["parse"](content), [])

    def test_unclosed_frontmatter_returns_empty(self) -> None:
        # No closing "---" → bail rather than guess.
        content = "---\nsources: [a, b]\nbody without close"
        self.assertEqual(_HELPERS["parse"](content), [])

    def test_empty_frontmatter_returns_empty(self) -> None:
        content = "---\n---\nbody"
        self.assertEqual(_HELPERS["parse"](content), [])

    def test_sources_filters_none_values(self) -> None:
        content = "---\nsources: [a, null, b]\n---\nbody"
        # YAML loads `null` as None; we drop None entries.
        self.assertEqual(_HELPERS["parse"](content), ["a", "b"])

    def test_malformed_yaml_returns_empty(self) -> None:
        # `: : :` is malformed YAML.
        content = "---\n: : :\n---\nbody"
        self.assertEqual(_HELPERS["parse"](content), [])


# =============================================================================
# Pure-function tests for _cold_event_exists (against temp SQLite DBs)
# =============================================================================


class TestColdEventExists(unittest.TestCase):
    """`_cold_event_exists` reads from ichor.db. We point it at temp DBs."""

    def setUp(self) -> None:
        # tmp_root/.hermes/ichor.db is the layout the function expects:
        # Path(_REAL_HOME) / ".hermes" / "ichor.db"
        self.tmp_root = Path(tempfile.mkdtemp())
        self.tmp_hermes = self.tmp_root / ".hermes"
        self.tmp_hermes.mkdir()
        self.tmp_db = self.tmp_hermes / "ichor.db"
        conn = sqlite3.connect(str(self.tmp_db))
        try:
            conn.execute(
                """
                CREATE TABLE cold_events (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    event_type TEXT,
                    raw_text TEXT
                )
                """
            )
            conn.executemany(
                "INSERT INTO cold_events (name, event_type, raw_text) VALUES (?, ?, ?)",
                [
                    ("existing_key_alpha", "fact", "alpha fact"),
                    ("existing_key_beta", "decision", "beta decision"),
                    ("existing_key_gamma", "digest_entry", "gamma digest"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        # Point mcp_server._REAL_HOME at the temp root.
        import mcp_server
        self._orig_real_home = mcp_server._REAL_HOME
        mcp_server._REAL_HOME = str(self.tmp_root)

    def tearDown(self) -> None:
        import mcp_server
        mcp_server._REAL_HOME = self._orig_real_home
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def test_existing_key_returns_true(self) -> None:
        self.assertTrue(_HELPERS["exists"]("existing_key_alpha"))
        self.assertTrue(_HELPERS["exists"]("existing_key_beta"))
        self.assertTrue(_HELPERS["exists"]("existing_key_gamma"))

    def test_missing_key_returns_false(self) -> None:
        self.assertFalse(_HELPERS["exists"]("nonexistent_xyz"))

    def test_empty_string_returns_false(self) -> None:
        self.assertFalse(_HELPERS["exists"](""))

    def test_non_string_returns_false(self) -> None:
        self.assertFalse(_HELPERS["exists"](None))  # type: ignore[arg-type]
        self.assertFalse(_HELPERS["exists"](12345))  # type: ignore[arg-type]

    def test_db_missing_returns_false(self) -> None:
        # Point at a non-existent home; should not raise.
        import mcp_server
        mcp_server._REAL_HOME = "/nonexistent/path/that/does/not/exist"
        self.assertFalse(_HELPERS["exists"]("anything"))


# =============================================================================
# Pure-function tests for _check_provenance (gate logic)
# =============================================================================


class TestCheckProvenanceGate(unittest.TestCase):
    """The gate logic. Cold-events stubbed via _cold_event_exists patching."""

    def setUp(self) -> None:
        # Build a fake cold-event resolver: {existing_keys} = allowed.
        self.existing = {"k_alpha", "k_beta"}
        self._orig_exists = _HELPERS["exists"]

        # Replace `_cold_event_exists` at module level so the gate
        # function reads from our fake set.
        import mcp_server
        mcp_server._cold_event_exists = lambda key: key in self.existing
        self._mcp_server = mcp_server

    def tearDown(self) -> None:
        self._mcp_server._cold_event_exists = self._orig_exists

    # -- non-triggering paths ----------------------------------------

    def test_empty_codex_normal_path_passes(self) -> None:
        ok, msg = _HELPERS["check"]("", "body", "Codex-General/notes/x.md")
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_unrelated_codex_passes(self) -> None:
        ok, msg = _HELPERS["check"](
            "Codex-Pantheon", "body", "Codex-Pantheon/notes/x.md"
        )
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_path_with_no_warm_or_ref_segments_passes(self) -> None:
        ok, msg = _HELPERS["check"](
            "", "body", "deep/nested/path/file.md"
        )
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    # -- triggered via codex parameter -------------------------------

    def test_warm_entities_codex_no_frontmatter_warns(self) -> None:
        ok, msg = _HELPERS["check"](
            "warm_entities", "plain body no frontmatter", "warm_entities/foo.md"
        )
        self.assertTrue(ok)
        self.assertIn("Provenance warning", msg)

    def test_reference_knowledge_codex_no_frontmatter_warns(self) -> None:
        ok, msg = _HELPERS["check"](
            "reference_knowledge", "plain body", "ref_knowledge/x.md"
        )
        self.assertTrue(ok)
        self.assertIn("Provenance warning", msg)

    def test_warm_entities_with_valid_sources_passes(self) -> None:
        content = "---\nsources: [k_alpha, k_beta]\n---\nbody"
        ok, msg = _HELPERS["check"](
            "warm_entities", content, "warm_entities/foo.md"
        )
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_warm_entities_with_partial_sources_rejects(self) -> None:
        # Sources list is present but contains non-existent keys → hard reject.
        # Gate contract: presence-with-bad-keys rejects (not soft-warns) so
        # authors notice the issue immediately rather than drifting.
        content = "---\nsources: [k_alpha, nonexistent_xyz]\n---\nbody"
        ok, msg = _HELPERS["check"](
            "warm_entities", content, "warm_entities/foo.md"
        )
        self.assertFalse(ok)
        self.assertIn("Provenance rejected", msg)
        self.assertIn("nonexistent_xyz", msg)

    def test_warm_entities_with_only_bad_sources_rejects(self) -> None:
        content = "---\nsources: [ghost1, ghost2]\n---\nbody"
        ok, msg = _HELPERS["check"](
            "warm_entities", content, "warm_entities/foo.md"
        )
        self.assertFalse(ok)
        self.assertIn("Provenance rejected", msg)
        self.assertIn("ghost1", msg)
        self.assertIn("ghost2", msg)

    # -- triggered via path segment ----------------------------------

    def test_warm_entities_path_segment_triggers_gate(self) -> None:
        ok, msg = _HELPERS["check"](
            "", "no frontmatter", "deep/warm_entities/notes/x.md"
        )
        self.assertTrue(ok)
        self.assertIn("Provenance warning", msg)

    def test_reference_knowledge_path_segment_triggers_gate(self) -> None:
        ok, msg = _HELPERS["check"](
            "", "no frontmatter", "reference_knowledge/x.md"
        )
        self.assertTrue(ok)
        self.assertIn("Provenance warning", msg)

    def test_partial_segment_match_does_not_trigger(self) -> None:
        # `warm_entities_v2` is not the same as `warm_entities`. We use
        # exact-segment matching, not substring.
        ok, msg = _HELPERS["check"](
            "", "body", "warm_entities_v2/x.md"
        )
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    # -- case-insensitive matching -----------------------------------

    def test_codex_matching_is_case_insensitive(self) -> None:
        ok, msg = _HELPERS["check"](
            "Warm_Entities", "body", "warm_entities/x.md"
        )
        self.assertTrue(ok)
        self.assertIn("Provenance warning", msg)


# =============================================================================
# Integration tests against athenaeum_write (source-read pattern from Phase 2)
# =============================================================================


class TestAthenaeumWriteIntegration(unittest.TestCase):
    """The provenance gate is wired into athenaeum_write before write_text.

    We check the source rather than booting the MCP server because the
    server runs in a specific environment (matches Phase 2 convention).
    """

    def setUp(self) -> None:
        self.mcp_path = _PANTHEON / "pantheon-core" / "mcp_server.py"
        self.src = self.mcp_path.read_text()

    def test_check_provenance_called_in_athenaeum_write(self) -> None:
        """_check_provenance must be called inside athenaeum_write."""
        self.assertIn("_check_provenance(", self.src)

        # Find athenaeum_write and confirm _check_provenance appears in it.
        idx = self.src.index("def athenaeum_write(")
        # Crude "find next top-level def after athenaeum_write" — we just
        # search for the next "@mcp.tool" decorator which marks the
        # boundary to the next tool.
        next_tool = self.src.find("@mcp.tool(", idx + 1)
        body = self.src[idx:next_tool if next_tool > 0 else idx + 5000]
        self.assertIn("_check_provenance(", body,
                      "_check_provenance must be invoked inside athenaeum_write")

    def test_reject_branch_returns_error_json(self) -> None:
        """On rejection, athenaeum_write returns JSON with 'provenance: rejected'."""
        idx = self.src.index("def athenaeum_write(")
        next_tool = self.src.find("@mcp.tool(", idx + 1)
        body = self.src[idx:next_tool if next_tool > 0 else idx + 5000]
        self.assertIn('"provenance": "rejected"', body,
                      "athenaeum_write must return provenance=rejected on gate failure")
        self.assertIn('"error":', body)

    def test_warm_entities_in_provenance_codexes(self) -> None:
        """Both warm_entities and reference_knowledge are gated."""
        self.assertIn('"warm_entities"', self.src)
        self.assertIn('"reference_knowledge"', self.src)

    def test_provenance_check_runs_before_write_text(self) -> None:
        """Provenance gate must precede the actual write_text call.

        This pins the order so a rejected write never creates the file.
        """
        idx_check = self.src.index("_check_provenance(")
        # find the next write_text after _check_provenance
        idx_write = self.src.index("write_text(", idx_check)
        # sanity: write_text comes after the check
        self.assertLess(idx_check, idx_write)


# =============================================================================
# End-to-end smoke test against a temp athenaeum root
# =============================================================================


class TestEndToEndWithTempAthenaeum(unittest.TestCase):
    """Run the gate against an isolated temp athenaeum + temp ichor.db."""

    def setUp(self) -> None:
        import mcp_server

        self.tmp_root = Path(tempfile.mkdtemp())
        self.tmp_hermes = self.tmp_root / ".hermes"
        self.tmp_hermes.mkdir()
        self.tmp_db = self.tmp_hermes / "ichor.db"

        # Seed the temp ichor.db with one cold_event.
        conn = sqlite3.connect(str(self.tmp_db))
        conn.execute(
            "CREATE TABLE cold_events (id INTEGER PRIMARY KEY, name TEXT, event_type TEXT, raw_text TEXT)"
        )
        conn.execute(
            "INSERT INTO cold_events (name, event_type, raw_text) VALUES (?, ?, ?)",
            ("seeded_event_1", "fact", "a seeded fact"),
        )
        conn.commit()
        conn.close()

        # Point mcp_server at our temp locations.
        self.tmp_athenaeum = self.tmp_root / "athenaeum"
        self.tmp_athenaeum.mkdir()

        self._orig_real_home = mcp_server._REAL_HOME
        self._orig_athenaeum_root = mcp_server._ATHENAEUM_ROOT
        mcp_server._REAL_HOME = str(self.tmp_root)
        mcp_server._ATHENAEUM_ROOT = self.tmp_athenaeum

    def tearDown(self) -> None:
        import mcp_server
        mcp_server._REAL_HOME = self._orig_real_home
        mcp_server._ATHENAEUM_ROOT = self._orig_athenaeum_root
        shutil.rmtree(self.tmp_root, ignore_errors=True)

    def test_warm_write_with_good_source_succeeds(self) -> None:
        result_json = _HELPERS["write"](
            path="warm_entities/foo.md",
            content="---\nsources: [seeded_event_1]\n---\nbody",
            codex="warm_entities",
        )
        result = json.loads(result_json)
        self.assertTrue(result.get("success"), result)
        # File should exist on disk in the temp athenaeum.
        self.assertTrue((self.tmp_athenaeum / "warm_entities" / "foo.md").exists())

    def test_warm_write_with_bad_source_rejected(self) -> None:
        result_json = _HELPERS["write"](
            path="warm_entities/foo.md",
            content="---\nsources: [ghost_unknown]\n---\nbody",
            codex="warm_entities",
        )
        result = json.loads(result_json)
        self.assertIn("error", result)
        self.assertEqual(result.get("provenance"), "rejected")
        self.assertIn("ghost_unknown", result["error"])
        # File should NOT exist on disk after rejection.
        self.assertFalse((self.tmp_athenaeum / "warm_entities" / "foo.md").exists())

    def test_regular_write_unaffected(self) -> None:
        """Non-triggering codex writes are untouched by the gate."""
        result_json = _HELPERS["write"](
            path="Codex-Pantheon/notes/random.md",
            content="plain markdown, no frontmatter",
            codex="Codex-Pantheon",
        )
        result = json.loads(result_json)
        self.assertTrue(result.get("success"), result)
        self.assertNotIn("provenance", result)
        self.assertTrue(
            (self.tmp_athenaeum / "Codex-Pantheon" / "notes" / "random.md").exists()
        )

    def test_warm_write_no_sources_soft_warning_succeeds(self) -> None:
        """Soft enforcement: missing sources warn but allow."""
        result_json = _HELPERS["write"](
            path="warm_entities/foo.md",
            content="no frontmatter here",
            codex="warm_entities",
        )
        result = json.loads(result_json)
        # Should succeed (allowed=True) but include provenance warning.
        self.assertTrue(result.get("success"), result)
        # File should exist on disk.
        self.assertTrue((self.tmp_athenaeum / "warm_entities" / "foo.md").exists())


if __name__ == "__main__":
    unittest.main()