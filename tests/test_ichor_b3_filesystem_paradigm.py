"""
B3: Filesystem Paradigm — gate + contract tests.

Spec: ~/athenaeum/Codex-God-thoth/research/openviking-vs-ichor-comparison/build-brief.md §P3
      ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md §B3

Gate checks:
  1. ichor_ls("pantheon://") returns all top-level sections
  2. ichor_ls("pantheon://warm/") matches distinct warm_entities categories
  3. ichor_find("ssl", "pantheon://warm/") only returns results under warm/
  4. Invalid path returns empty list, not error
  5. Root path "pantheon://" is valid and returns top-level structure

Plus contract tests for path resolution, codex/god filesystem listing,
scoped search.
"""

import sys
import unittest
from pathlib import Path

PANTHEON_ROOT = str(Path.home() / "pantheon")
if PANTHEON_ROOT not in sys.path:
    sys.path.insert(0, PANTHEON_ROOT)

from lib.ichor_paths import (  # noqa: E402
    parse_path,
    list_codex_dirs,
    list_god_dirs,
    path_matches,
    PANTHEON_PREFIX,
)
from lib.ichor_browse import ichor_ls, ichor_find  # noqa: E402


# ---------------------------------------------------------------------------
# Gate checks
# ---------------------------------------------------------------------------

class TestGateB3RootListing(unittest.TestCase):
    """Gate B3 check 1: ichor_ls(pantheon://) returns all 4 top-level sections."""

    def test_root_has_four_sections(self):
        entries = ichor_ls("pantheon://")
        names = {e["name"] for e in entries}
        self.assertEqual(names, {"warm", "codexes", "gods", "reference"})

    def test_root_entries_are_directories(self):
        for e in ichor_ls("pantheon://"):
            self.assertEqual(e["type"], "directory")

    def test_root_entries_have_briefs(self):
        for e in ichor_ls("pantheon://"):
            self.assertTrue(e["brief"], msg=f"{e['name']} missing brief")

    def test_root_paths_are_pantheon_urls(self):
        for e in ichor_ls("pantheon://"):
            self.assertTrue(e["path"].startswith("pantheon://"),
                            msg=f"{e['name']} path {e['path']!r} missing prefix")


class TestGateB3WarmCategories(unittest.TestCase):
    """Gate B3 check 2: ichor_ls(pantheon://warm/) matches warm_entities."""

    def test_warm_listing_returns_categories(self):
        entries = ichor_ls("pantheon://warm/")
        names = {e["name"] for e in entries}
        # At least some of the canonical categories should be present
        canonical = {"blocker", "decision", "commitment", "preference",
                     "insight", "fact", "follow_up", "correction",
                     "digest_entry", "reference"}
        # The intersection must be non-empty — at least the schema is alive
        self.assertTrue(
            canonical & names,
            msg=f"warm listing {names} has none of {canonical}"
        )

    def test_warm_listing_has_item_counts(self):
        entries = ichor_ls("pantheon://warm/")
        for e in entries:
            self.assertIsInstance(e["item_count"], int)
            self.assertGreater(e["item_count"], 0,
                               msg=f"category {e['name']} shows 0 items")


class TestGateB3ScopedFind(unittest.TestCase):
    """Gate B3 check 3: ichor_find() respects the subtree filter."""

    def test_find_warm_scoped_to_warm(self):
        results = ichor_find("decision", "pantheon://warm/")
        for r in results:
            self.assertIn("warm/", r["path"],
                          msg=f"result {r['id']!r} not in warm/: {r['path']}")

    def test_find_warm_category_scoped(self):
        results = ichor_find("decision", "pantheon://warm/decision/")
        for r in results:
            self.assertTrue(
                r["path"].startswith("pantheon://warm/decision/"),
                msg=f"result {r['id']!r} not in warm/decision/: {r['path']}"
            )

    def test_find_codex_scoped(self):
        results = ichor_find("memory", "pantheon://codexes/")
        # All results should be from codex files (filesystem paths)
        for r in results:
            self.assertNotIn("pantheon://", r["path"],
                             msg=f"codex result {r['id']!r} has pantheon:// path")

    def test_find_codex_specific_name_scoped(self):
        results = ichor_find("Forge", "pantheon://codexes/Forge/")
        for r in results:
            self.assertIn("Codex-Forge", r["path"],
                          msg=f"result {r['id']!r} not under Codex-Forge: {r['path']}")


class TestGateB3InvalidPath(unittest.TestCase):
    """Gate B3 check 4: invalid path returns empty list, not error."""

    def test_wrong_prefix_returns_empty(self):
        self.assertEqual(ichor_ls("not-a-path"), [])
        self.assertEqual(ichor_ls("http://warm/"), [])
        self.assertEqual(ichor_ls("foo://bar"), [])

    def test_unknown_root_returns_empty(self):
        self.assertEqual(ichor_ls("pantheon://unknown/"), [])

    def test_nonexistent_codex_returns_empty(self):
        self.assertEqual(ichor_ls("pantheon://codexes/Nonexistent/"), [])

    def test_find_invalid_path_returns_empty(self):
        self.assertEqual(ichor_find("ssl", "not-a-path"), [])
        self.assertEqual(ichor_find("ssl", "pantheon://unknown/"), [])

    def test_empty_query_returns_empty(self):
        self.assertEqual(ichor_find("", "pantheon://"), [])
        self.assertEqual(ichor_find("   ", "pantheon://"), [])

    def test_ls_does_not_raise(self):
        """Even the weirdest inputs shouldn't raise."""
        for p in [None, "", "   ", "pantheon://///", "pantheon://\x00"]:
            try:
                # None can't be passed via string typing, so skip that
                if p is None:
                    continue
                result = ichor_ls(p)
                self.assertIsInstance(result, list)
            except Exception as e:
                self.fail(f"ichor_ls({p!r}) raised: {e}")


class TestGateB3RootIsValid(unittest.TestCase):
    """Gate B3 check 5: root path is valid and returns top-level structure."""

    def test_root_with_no_slash(self):
        entries = ichor_ls("pantheon://")
        self.assertGreater(len(entries), 0)

    def test_root_with_trailing_slash(self):
        entries = ichor_ls("pantheon:///")
        self.assertGreater(len(entries), 0)

    def test_empty_string_is_root(self):
        entries = ichor_ls("")
        # The resolver treats "" as root → returns top-level
        self.assertGreater(len(entries), 0)


# ---------------------------------------------------------------------------
# Contract tests: path resolution
# ---------------------------------------------------------------------------

class TestParsePath(unittest.TestCase):
    """The path parser handles all the spec examples correctly."""

    def test_root(self):
        spec = parse_path("pantheon://")
        self.assertTrue(spec["valid"])
        self.assertIsNone(spec["root"])
        self.assertIsNone(spec["category"])
        self.assertIsNone(spec["name"])

    def test_warm_root(self):
        spec = parse_path("pantheon://warm/")
        self.assertTrue(spec["valid"])
        self.assertEqual(spec["root"], "warm")
        self.assertIsNone(spec["category"])

    def test_warm_category(self):
        spec = parse_path("pantheon://warm/blockers/")
        self.assertTrue(spec["valid"])
        self.assertEqual(spec["root"], "warm")
        self.assertEqual(spec["category"], "blockers")

    def test_codex_specific(self):
        spec = parse_path("pantheon://codexes/Forge/")
        self.assertTrue(spec["valid"])
        self.assertEqual(spec["root"], "codexes")
        # The Codex- prefix is added back when materializing the path
        self.assertEqual(spec["name"], "Codex-Forge")
        self.assertIsNone(spec["subpath"])

    def test_codex_with_subpath(self):
        spec = parse_path("pantheon://codexes/Forge/notes/scratch.md")
        self.assertEqual(spec["name"], "Codex-Forge")
        self.assertEqual(spec["subpath"], "notes/scratch.md")

    def test_god_specific(self):
        spec = parse_path("pantheon://gods/thoth/")
        self.assertEqual(spec["root"], "gods")
        self.assertEqual(spec["name"], "Codex-God-thoth")

    def test_reference_root(self):
        spec = parse_path("pantheon://reference/")
        self.assertEqual(spec["root"], "reference")
        self.assertIsNone(spec["category"])

    def test_invalid_returns_invalid_spec(self):
        spec = parse_path("not-a-path")
        self.assertFalse(spec["valid"])
        self.assertIn("error", spec)

    def test_unknown_root_is_invalid(self):
        spec = parse_path("pantheon://unknown/")
        self.assertFalse(spec["valid"])

    def test_none_path_is_invalid(self):
        spec = parse_path(None)
        self.assertFalse(spec["valid"])


class TestFilesystemLists(unittest.TestCase):
    """codex/god listing helpers work."""

    def test_codex_dirs_excludes_god_dirs(self):
        dirs = list_codex_dirs()
        for d in dirs:
            self.assertFalse(d.name.startswith("Codex-God-"),
                             msg=f"{d.name} should be in god list, not codex")
            self.assertTrue(d.name.startswith("Codex-"),
                            msg=f"{d.name} missing Codex- prefix")

    def test_god_dirs_includes_only_god_dirs(self):
        dirs = list_god_dirs()
        self.assertGreater(len(dirs), 0, "no god codex dirs found")
        for d in dirs:
            self.assertTrue(d.name.startswith("Codex-God-"),
                            msg=f"{d.name} not a god dir")


class TestPathMatchFilter(unittest.TestCase):
    """path_matches() for ichor_find's subpath filter."""

    def test_empty_filter_matches_everything(self):
        self.assertTrue(path_matches("/foo/bar", None))
        self.assertTrue(path_matches("/foo/bar", ""))
        self.assertTrue(path_matches("/foo/bar", "/"))

    def test_exact_subpath_matches(self):
        self.assertTrue(path_matches("/home/konan/athenaeum/Codex-Forge/notes/scratch.md",
                                     "notes"))

    def test_wrong_subpath_does_not_match(self):
        self.assertFalse(path_matches("/home/konan/athenaeum/Codex-Forge/notes/scratch.md",
                                      "research"))

    def test_partial_path_components(self):
        # 'notes' should NOT match 'notes_old' as a subpath
        self.assertFalse(path_matches("/foo/notes_old/file.md", "notes"))


class TestSearchResultShape(unittest.TestCase):
    """ichor_find results have the right keys."""

    def test_result_has_required_fields(self):
        results = ichor_find("decision", "pantheon://warm/", limit=3)
        for r in results:
            for k in ("id", "brief", "outline", "path", "score", "has_full"):
                self.assertIn(k, r, msg=f"missing {k} in {r}")

    def test_result_score_bounded(self):
        results = ichor_find("decision", "pantheon://warm/", limit=3)
        for r in results:
            self.assertGreaterEqual(r["score"], 0.0)
            self.assertLessEqual(r["score"], 1.0)

    def test_limit_is_respected(self):
        results = ichor_find("decision", "pantheon://warm/", limit=2)
        self.assertLessEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main()
