"""Ichor Memory Gap-Closure tests — SPEC phases 2D, 3B, 3D.

Covers:
  * Phase 2D entity resolution: merge near-duplicates into one canonical,
    no-merge below threshold, dry-run leaves a clean corpus untouched,
    alias resolution returns the canonical node.
  * Phase 3B cascade triggers: supersede an entity → relationships expire;
    supersede a claim → evidence expires; re-supersede is a no-op.
  * Phase 3D recall audit trail: one recall_log row per retrieve, query
    truncation to 300 chars, recall_stats reports lanes/latency.

Spec: ~/athenaeum/Codex-God-thoth/research/ichor-mnemos-upgrade-plan/SPEC.md
"""

from __future__ import annotations

import importlib.machinery
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

MODULE_PATH = Path("/home/konan/pantheon/lib/ichor_mcp.py")


def _load_ichor_mcp(home_dir: str):
    """Load lib/ichor_mcp.py with HOME pointed at a temp dir (same pattern
    as tests/test_ichor_mcp.py) so the module uses an isolated ichor.db."""
    os.environ["HOME"] = home_dir
    name = f"ichor_mcp_gap_{Path(home_dir).name}"
    loader = importlib.machinery.SourceFileLoader(name, str(MODULE_PATH))
    return loader.load_module()  # type: ignore[deprecated-call]


def _isolated_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="gap_closure_")
    os.close(fd)
    return Path(path)


def _cleanup_db(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        p = db_path.with_name(db_path.name + suffix)
        if p.exists():
            p.unlink()


def _insert_entity(conn: sqlite3.Connection, type_id: str, name: str) -> int:
    cur = conn.execute(
        "INSERT INTO entities (type_id, name) VALUES (?, ?)", (type_id, name)
    )
    return int(cur.lastrowid)


class TestEntityResolve(unittest.TestCase):
    """Phase 2D — dedup pass."""

    def setUp(self) -> None:
        self.db_path = _isolated_db()
        from lib.ichor.entities.schema import migrate

        migrate(self.db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row

    def tearDown(self) -> None:
        self.conn.close()
        _cleanup_db(self.db_path)

    def test_merge_tallon_variants_into_one_canonical(self) -> None:
        from lib.ichor.entities import entity_resolve

        tallon = _insert_entity(self.conn, "person", "Tallon")
        k_tallon = _insert_entity(self.conn, "person", "K. Tallon")
        konan_tallon = _insert_entity(self.conn, "person", "konan tallon")
        acme = _insert_entity(self.conn, "organization", "Acme")
        # Relationship from a loser + a fact on another loser.
        self.conn.execute(
            "INSERT INTO relationships (type_id, source_id, target_id, valid_from) "
            "VALUES ('works_at', ?, ?, datetime('now'))",
            (k_tallon, acme),
        )
        self.conn.execute(
            "INSERT INTO entity_facts (entity_id, key, value) VALUES (?, 'mrr', '50000')",
            (konan_tallon,),
        )
        self.conn.commit()

        report = entity_resolve.run(dry_run=False, threshold=0.85, db_path=self.db_path)

        self.assertEqual(report["merges"], 2, report)
        self.assertGreaterEqual(report["candidates"], 2, report)
        canonical = min(tallon, k_tallon, konan_tallon)
        self.assertEqual(canonical, tallon)

        # Losers marked merged → canonical.
        for loser in (k_tallon, konan_tallon):
            row = self.conn.execute(
                "SELECT status, merged_into FROM entities WHERE id = ?", (loser,)
            ).fetchone()
            self.assertEqual(row["status"], "merged")
            self.assertEqual(row["merged_into"], canonical)

        # Canonical still active.
        row = self.conn.execute(
            "SELECT status FROM entities WHERE id = ?", (canonical,)
        ).fetchone()
        self.assertEqual(row["status"], "active")

        # Relationship re-pointed to canonical.
        rel = self.conn.execute(
            "SELECT source_id, target_id FROM relationships WHERE type_id = 'works_at'"
        ).fetchone()
        self.assertEqual(rel["source_id"], canonical)
        self.assertEqual(rel["target_id"], acme)

        # Fact re-pointed to canonical.
        fact = self.conn.execute("SELECT entity_id FROM entity_facts WHERE key = 'mrr'").fetchone()
        self.assertEqual(fact["entity_id"], canonical)

        # Alias rows exist for every cluster variant.
        aliases = {
            r["alias"]
            for r in self.conn.execute(
                "SELECT alias FROM entity_aliases WHERE canonical_entity_id = ?",
                (canonical,),
            )
        }
        self.assertIn("Tallon", aliases)
        self.assertIn("K. Tallon", aliases)
        self.assertIn("konan tallon", aliases)

        # Any alias resolves to the same canonical node.
        self.assertEqual(entity_resolve.resolve("Tallon", db_path=self.db_path), canonical)
        self.assertEqual(entity_resolve.resolve("K. Tallon", db_path=self.db_path), canonical)
        self.assertEqual(entity_resolve.resolve("konan tallon", db_path=self.db_path), canonical)
        self.assertIsNone(entity_resolve.resolve("No Such Person", db_path=self.db_path))

    def test_no_merge_below_threshold_jr_suffix(self) -> None:
        from lib.ichor.entities import entity_resolve

        _insert_entity(self.conn, "person", "John Smith")
        _insert_entity(self.conn, "person", "John Smith Jr")
        self.conn.commit()

        report = entity_resolve.run(dry_run=True, threshold=0.85, db_path=self.db_path)
        self.assertEqual(report["merges"], 0, report)
        self.assertEqual(report["candidates"], 0, report)

        # Different single-letter initials also stay separate.
        _insert_entity(self.conn, "person", "A. Smith")
        _insert_entity(self.conn, "person", "B. Smith")
        self.conn.commit()
        report2 = entity_resolve.run(dry_run=True, threshold=0.85, db_path=self.db_path)
        self.assertEqual(report2["merges"], 0, report2)

    def test_dry_run_zero_merges_on_clean_corpus(self) -> None:
        from lib.ichor.entities import entity_resolve

        for name in ("Acme", "Globex", "Initech"):
            _insert_entity(self.conn, "organization", name)
        self.conn.commit()

        report = entity_resolve.run(dry_run=True, threshold=0.85, db_path=self.db_path)
        self.assertEqual(report["candidates"], 0, report)
        self.assertEqual(report["merges"], 0, report)

        # Dry-run changed nothing: all still active.
        statuses = {
            r["name"]: r["status"]
            for r in self.conn.execute("SELECT name, status FROM entities")
        }
        self.assertEqual(
            statuses, {"Acme": "active", "Globex": "active", "Initech": "active"}
        )

    def test_normalize_and_similarity_units(self) -> None:
        from lib.ichor.entities import entity_resolve

        self.assertEqual(entity_resolve.normalize("K. Tallon"), "k tallon")
        self.assertEqual(entity_resolve.normalize("Konan  TALLON!"), "konan tallon")
        self.assertGreaterEqual(entity_resolve.similarity("Tallon", "K. Tallon"), 0.85)
        self.assertGreaterEqual(entity_resolve.similarity("Tallon", "konan tallon"), 0.85)
        self.assertLess(entity_resolve.similarity("John Smith", "John Smith Jr"), 0.85)


class TestCascadeTriggers(unittest.TestCase):
    """Phase 3B — SQL cascade triggers."""

    def setUp(self) -> None:
        self.db_path = _isolated_db()
        from lib.ichor.entities.schema import migrate

        migrate(self.db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row

    def tearDown(self) -> None:
        self.conn.close()
        _cleanup_db(self.db_path)

    def test_entity_supersede_expires_relations_idempotently(self) -> None:
        a = _insert_entity(self.conn, "person", "Alpha")
        b = _insert_entity(self.conn, "person", "Beta")
        c = _insert_entity(self.conn, "person", "Gamma")
        self.conn.execute(
            "INSERT INTO relationships (type_id, source_id, target_id, valid_from) "
            "VALUES ('works_at', ?, ?, datetime('now'))",
            (a, b),
        )
        # A relationship NOT touching the superseded entity must survive.
        self.conn.execute(
            "INSERT INTO relationships (type_id, source_id, target_id, valid_from) "
            "VALUES ('works_at', ?, ?, datetime('now'))",
            (b, c),
        )
        self.conn.commit()

        # Supersede Alpha → its open relation expires instantly (trigger).
        self.conn.execute("UPDATE entities SET merged_into = ? WHERE id = ?", (c, a))
        self.conn.commit()

        rel_a = self.conn.execute(
            "SELECT valid_to FROM relationships WHERE source_id = ? AND target_id = ?",
            (a, b),
        ).fetchone()
        rel_bc = self.conn.execute(
            "SELECT valid_to FROM relationships WHERE source_id = ? AND target_id = ?",
            (b, c),
        ).fetchone()
        self.assertIsNotNone(rel_a["valid_to"], "relation touching superseded entity must expire")
        self.assertIsNone(rel_bc["valid_to"], "unrelated relation must stay valid")

        expired_at = rel_a["valid_to"]

        # Re-supersede to the SAME canonical → trigger WHEN guard → no-op.
        self.conn.execute("UPDATE entities SET merged_into = ? WHERE id = ?", (c, a))
        self.conn.commit()
        rel_a = self.conn.execute(
            "SELECT valid_to FROM relationships WHERE source_id = ? AND target_id = ?",
            (a, b),
        ).fetchone()
        self.assertEqual(rel_a["valid_to"], expired_at, "re-supersede must be a no-op")

        # Re-supersede to a DIFFERENT canonical → fires, but valid_to guard → no-op.
        self.conn.execute("UPDATE entities SET merged_into = ? WHERE id = ?", (b, a))
        self.conn.commit()
        rel_a = self.conn.execute(
            "SELECT valid_to FROM relationships WHERE source_id = ? AND target_id = ?",
            (a, b),
        ).fetchone()
        self.assertEqual(rel_a["valid_to"], expired_at, "re-supersede must be idempotent")

    def test_claim_supersede_expires_evidence_idempotently(self) -> None:
        import lib.ichor.schema_v2 as schema_v2

        schema_v2.DB_PATH = self.db_path
        try:
            # migrate() backfills from ichor_events; create an empty source table.
            conn = schema_v2.get_conn()
            conn.execute(
                "CREATE TABLE IF NOT EXISTS ichor_events ("
                "id INTEGER PRIMARY KEY, event_type TEXT, subject TEXT, object TEXT, "
                "raw_text TEXT, category TEXT, confidence REAL, importance REAL, "
                "trust REAL, maturity TEXT, direction TEXT, peer_god TEXT, "
                "god_name TEXT, session_id TEXT, created_at TEXT)"
            )
            conn.commit()
            conn.close()
            schema_v2.migrate()

            conn = schema_v2.get_conn()
            cur = conn.execute(
                "INSERT INTO ichor_claims (text, status) VALUES ('claim one', 'validated')"
            )
            claim1 = int(cur.lastrowid)
            cur = conn.execute(
                "INSERT INTO ichor_claims (text, status) VALUES ('claim two', 'validated')"
            )
            claim2 = int(cur.lastrowid)
            cur = conn.execute(
                "INSERT INTO ichor_claims (text, status) VALUES ('claim three', 'validated')"
            )
            claim3 = int(cur.lastrowid)
            for ev in (10, 11):
                conn.execute(
                    "INSERT INTO ichor_claim_evidence "
                    "(claim_id, source_event_id, source_session_id, excerpt) "
                    "VALUES (?, ?, 's1', 'e')",
                    (claim1, ev),
                )
            conn.commit()

            # Supersede claim1 → its evidence expires instantly (trigger).
            conn.execute(
                "UPDATE ichor_claims SET superseded_by = ? WHERE id = ?", (claim2, claim1)
            )
            conn.commit()
            rows = conn.execute(
                "SELECT valid_until FROM ichor_claim_evidence WHERE claim_id = ?",
                (claim1,),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            for r in rows:
                self.assertIsNotNone(r["valid_until"], "evidence of superseded claim must expire")
            expired_at = rows[0]["valid_until"]

            # Re-supersede (same value) → WHEN guard → no-op.
            conn.execute(
                "UPDATE ichor_claims SET superseded_by = ? WHERE id = ?", (claim2, claim1)
            )
            conn.commit()
            rows = conn.execute(
                "SELECT valid_until FROM ichor_claim_evidence WHERE claim_id = ?",
                (claim1,),
            ).fetchall()
            for r in rows:
                self.assertEqual(r["valid_until"], expired_at, "re-supersede must be a no-op")

            # Re-supersede (different value) → valid_until guard → no-op.
            conn.execute(
                "UPDATE ichor_claims SET superseded_by = ? WHERE id = ?", (claim3, claim1)
            )
            conn.commit()
            rows = conn.execute(
                "SELECT valid_until FROM ichor_claim_evidence WHERE claim_id = ?",
                (claim1,),
            ).fetchall()
            for r in rows:
                self.assertEqual(r["valid_until"], expired_at, "re-supersede must be idempotent")
            conn.close()
        finally:
            schema_v2.DB_PATH = Path.home() / ".hermes" / "ichor.db"


def _wait_for_recall_rows(db_path: Path, expected: int, timeout: float = 3.0) -> list[tuple]:
    """Poll the async recall_log writer until `expected` rows exist."""
    deadline = time.time() + timeout
    rows: list[tuple] = []
    while time.time() < deadline:
        try:
            conn = sqlite3.connect(str(db_path))
            try:
                cur = conn.execute(
                    "SELECT id, query_text, god_name, lanes_used, per_lane_latency_ms, "
                    "total_ms, top_result_ids, top_result_scores, retrieved_at "
                    "FROM recall_log ORDER BY id"
                )
                rows = cur.fetchall()
            finally:
                conn.close()
        except Exception:
            rows = []
        if len(rows) >= expected:
            return rows
        time.sleep(0.05)
    return rows


class TestRecallAuditTrail(unittest.TestCase):
    """Phase 3D — recall_log + ichor_recall_stats."""

    def setUp(self) -> None:
        self.td = tempfile.TemporaryDirectory(dir="/home/konan")
        self.home = self.td.name
        self.mod = _load_ichor_mcp(self.home)
        self.db_path = Path(self.home) / ".hermes" / "ichor.db"

    def tearDown(self) -> None:
        self.td.cleanup()

    def test_recall_log_row_written_per_retrieve(self) -> None:
        mod = self.mod
        store = json.loads(mod.ichor_store(
            namespace="test",
            key="gap.retrieve",
            content="tallon works at acme and prefers relay seven",
            category="fact",
            session_id="sess-1",
            god_name="hermes",
        ))
        self.assertTrue(store["stored"])

        out = json.loads(mod.ichor_retrieve("tallon acme", limit=5, active_god="thoth"))
        self.assertIn("results", out)

        rows = _wait_for_recall_rows(self.db_path, 1)
        self.assertGreaterEqual(len(rows), 1, "one recall_log row expected per retrieve")
        q_text, god, lanes, per_lane, total_ms, top_ids, top_scores = rows[0][1:8]
        self.assertEqual(q_text, "tallon acme")
        self.assertEqual(god, "thoth")
        self.assertIsInstance(json.loads(lanes), list)
        self.assertIsInstance(json.loads(per_lane), dict)
        self.assertGreaterEqual(float(total_ms), 0.0)
        self.assertEqual(len(json.loads(top_ids)), len(out["results"]))
        self.assertEqual(len(json.loads(top_scores)), len(out["results"]))

    def test_recall_log_truncates_query_to_300_chars(self) -> None:
        mod = self.mod
        long_query = "x" * 500
        json.loads(mod.ichor_retrieve(long_query, limit=5))
        rows = _wait_for_recall_rows(self.db_path, 1)
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(len(rows[0][1]), 300, "query text must be truncated to 300 chars")
        self.assertEqual(rows[0][1], "x" * 300)

    def test_recall_stats_shows_lanes_and_latency(self) -> None:
        mod = self.mod
        for i, (key, content, query) in enumerate([
            ("gap.k1", "tallon founded relay seven in 2026", "tallon relay"),
            ("gap.k2", "konan tallon maintains the pantheon codebase", "pantheon konan"),
        ]):
            json.loads(mod.ichor_store(
                namespace="test", key=key, content=content, category="fact",
                session_id=f"sess-{i}", god_name="hermes",
            ))
            json.loads(mod.ichor_retrieve(query, limit=5, active_god="hermes"))

        rows = _wait_for_recall_rows(self.db_path, 2)
        self.assertGreaterEqual(len(rows), 2, "two retrieves → two recall_log rows")

        stats = json.loads(mod.ichor_recall_stats(recent=10))
        self.assertIn("avg_total_ms", stats)
        self.assertIn("p95_total_ms", stats)
        self.assertGreaterEqual(stats["avg_total_ms"], 0.0)
        self.assertGreaterEqual(stats["p95_total_ms"], 0.0)
        self.assertIsNotNone(stats["slowest_lane"], "per-lane breakdown expected")
        self.assertIn("lane", stats["slowest_lane"])
        self.assertIn("per_lane_avg_ms", stats)
        self.assertEqual(stats["zero_hit_rate_pct"], 0.0, "both queries hit results")
        self.assertGreaterEqual(len(stats["top_retrieved_events"]), 1)
        self.assertGreaterEqual(stats["top_retrieved_events"][0]["count"], 1)

    def test_entity_resolve_mcp_tool_dry_run(self) -> None:
        mod = self.mod
        out = json.loads(mod.ichor_entity_resolve())  # dry-run by default
        self.assertTrue(out["dry_run"])
        self.assertIn("candidates", out)
        self.assertIn("merges", out)
        self.assertEqual(out["candidates"], 0)
        self.assertEqual(out["merges"], 0)


if __name__ == "__main__":
    unittest.main()
