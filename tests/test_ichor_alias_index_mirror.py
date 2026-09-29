#!/usr/bin/env python3
"""Alias index mirror — shadow guard, conflict handling, prune + audit.

The mirror copies `entities.aliases` JSON into `entity_aliases` (the table
`resolve()` consults first). Loose aliases are noisy: "Pantheon MCP" lists
`pantheon`, "thoth profile" lists `thoth`. Indexing those made
`resolve('pantheon')` return a 1-edge stub instead of the 1,494-edge hub —
152 of the 417 alias rows pruned on 2026-09-19 pointed at zero-edge anchors.

Shadow rule pinned here: an alias is NOT indexed when another active entity is
literally named it AND is strictly denser (more live edges) than the target.
Aliases pointing at the stronger facet (`Cybermage` -> Konan, `Tallon` -> the
person hub) survive.

Hermetic: temp DB per test.

Run with the hermes venv (no pytest there):
    ~/.hermes/hermes-agent/.venv/bin/python3 tests/test_ichor_alias_index_mirror.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path("/home/konan/pantheon/scripts/ichor_alias_index_mirror.py")
_spec = importlib.util.spec_from_file_location("ichor_alias_index_mirror", SCRIPT)
mirror_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mirror_mod)


def _make_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="alias_mirror_test_")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT, type_id TEXT, "
        "status TEXT, aliases TEXT, summary TEXT)"
    )
    conn.execute(
        "CREATE TABLE entity_aliases (id INTEGER PRIMARY KEY, "
        "canonical_entity_id INTEGER, alias TEXT)"
    )
    conn.execute(
        "CREATE TABLE relationships (id INTEGER PRIMARY KEY, source_id INTEGER, "
        "target_id INTEGER, valid_to TEXT)"
    )
    conn.commit()
    conn.close()
    return Path(path)


class AliasMirrorTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _make_db()
        self.conn = mirror_mod._connect(self.db)

    def tearDown(self) -> None:
        self.conn.close()
        if self.db.exists():
            self.db.unlink()

    def add_entity(self, eid: int, name: str, aliases: list[str], edges: int = 0) -> None:
        self.conn.execute(
            "INSERT INTO entities (id, name, type_id, status, aliases, summary) "
            "VALUES (?, ?, 'concept', 'active', ?, '')",
            (eid, name, json.dumps(aliases)),
        )
        for i in range(edges):
            self.conn.execute(
                "INSERT INTO relationships (source_id, target_id, valid_to) VALUES (?, ?, NULL)",
                (eid, 900000 + eid * 100 + i),
            )
        self.conn.commit()

    def aliases(self) -> dict[str, int]:
        return {
            r["alias"].lower(): int(r["canonical_entity_id"])
            for r in self.conn.execute("SELECT canonical_entity_id, alias FROM entity_aliases")
        }


class TestShadowGuard(AliasMirrorTestBase):
    def test_alias_matching_a_denser_entity_name_is_skipped(self):
        # 'Pantheon MCP' (0 edges) claims the alias 'Pantheon'; the real hub is
        # the entity literally named Pantheon (5 edges).
        self.add_entity(1, "Pantheon MCP", ["Pantheon"], edges=0)
        self.add_entity(2, "Pantheon", [], edges=5)
        report = mirror_mod.mirror(self.conn, limit=None, apply=True)
        self.assertEqual(report["shadow_skipped"], 1)
        self.assertNotIn("pantheon", self.aliases(), "weak facet captured a stronger entity's name")
        self.assertEqual(report["inserted"], 0)

    def test_alias_matching_a_weaker_entity_name_is_indexed(self):
        # 'Konan' (10 edges) carries alias 'Cybermage'; a stray 0-edge
        # 'Cybermage' concept row exists. The alias must still be indexed.
        self.add_entity(10, "Konan", ["Cybermage"], edges=10)
        self.add_entity(11, "Cybermage", [], edges=0)
        report = mirror_mod.mirror(self.conn, limit=None, apply=True)
        self.assertEqual(report["inserted"], 1)
        self.assertEqual(self.aliases()["cybermage"], 10)

    def test_own_name_is_never_indexed_as_its_own_alias(self):
        self.add_entity(20, "Thoth", ["Thoth", "thoth"], edges=3)
        report = mirror_mod.mirror(self.conn, limit=None, apply=True)
        self.assertEqual(report["inserted"], 0)
        self.assertEqual(report["aliases_considered"], 0)


class TestConflictHandling(AliasMirrorTestBase):
    def test_alias_already_held_by_another_entity_is_skipped(self):
        self.add_entity(30, "Alpha", ["Shared"], edges=1)
        self.conn.execute(
            "INSERT INTO entity_aliases (canonical_entity_id, alias) VALUES (31, 'Shared')"
        )
        self.add_entity(32, "Beta", ["Shared"], edges=9)
        report = mirror_mod.mirror(self.conn, limit=None, apply=True)
        # Both claimants (Alpha id 30 and Beta id 32) defer to the incumbent.
        self.assertEqual(report["conflicts_skipped"], 2)
        self.assertEqual(report["inserted"], 0)
        self.assertEqual(self.aliases()["shared"], 31, "incumbent mapping must win")

    def test_second_run_is_idempotent(self):
        self.add_entity(40, "Gamma", ["G", "gam"], edges=2)
        first = mirror_mod.mirror(self.conn, limit=None, apply=True)
        second = mirror_mod.mirror(self.conn, limit=None, apply=True)
        self.assertEqual(first["inserted"], 2)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["already_present"], 2)

    def test_dry_run_writes_nothing(self):
        self.add_entity(50, "Delta", ["D"], edges=1)
        report = mirror_mod.mirror(self.conn, limit=None, apply=False)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["inserted"], 1)
        self.assertEqual(self.aliases(), {}, "dry run wrote to the index")


class TestPruneShadowing(AliasMirrorTestBase):
    def test_prune_removes_violating_rows_and_audits(self):
        self.add_entity(60, "Pantheon MCP", [], edges=0)
        self.add_entity(61, "Pantheon", [], edges=7)
        self.conn.execute(
            "INSERT INTO entity_aliases (canonical_entity_id, alias) VALUES (60, 'Pantheon')"
        )
        self.conn.commit()
        audit = self.db.parent / (self.db.stem + "-audit.jsonl")

        dry = mirror_mod.prune_shadowing(self.conn, apply=False)
        self.assertEqual(dry["removed"], 1)
        self.assertEqual(self.aliases().get("pantheon"), 60, "dry run deleted a row")

        real = mirror_mod.prune_shadowing(self.conn, apply=True, audit=audit)
        self.assertEqual(real["removed"], 1)
        self.assertNotIn("pantheon", self.aliases())
        lines = [json.loads(l) for l in audit.read_text().splitlines()]
        self.assertEqual(lines[0]["alias"], "Pantheon")
        self.assertEqual(lines[0]["denser_named_entity"], 61)
        audit.unlink()

    def test_prune_keeps_alias_pointing_at_the_stronger_facet(self):
        self.add_entity(70, "Konan", [], edges=12)
        self.add_entity(71, "Cybermage", [], edges=0)
        self.conn.execute(
            "INSERT INTO entity_aliases (canonical_entity_id, alias) VALUES (70, 'Cybermage')"
        )
        self.conn.commit()
        report = mirror_mod.prune_shadowing(self.conn, apply=True)
        self.assertEqual(report["removed"], 0)
        self.assertEqual(self.aliases()["cybermage"], 70)


if __name__ == "__main__":
    unittest.main(verbosity=2)
