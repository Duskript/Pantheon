"""Tests for Phase 4: Decay + Eviction + Forge."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _seed_test_db(
    db_path: Path,
    events: list[dict],
    extra_columns: tuple[tuple[str, str], ...] = (),
) -> None:
    """Create a minimal ichor_events table and insert seed rows.

    ``extra_columns`` models schema drift: the live ``ichor_events`` is wider
    than the shape the eviction module's cold-storage DDL assumed.
    """
    con = sqlite3.connect(str(db_path))
    con.executescript("""
        CREATE TABLE ichor_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            event_type TEXT,
            subject TEXT,
            predicate TEXT,
            object TEXT,
            confidence REAL DEFAULT 0.8,
            source TEXT,
            raw_text TEXT,
            created_at TEXT,
            god_name TEXT,
            importance REAL DEFAULT 50.0,
            trust REAL DEFAULT 50.0,
            maturity TEXT DEFAULT 'draft',
            last_access TEXT,
            direction TEXT,
            peer_god TEXT
        );
    """)
    for col in extra_columns:
        name, ctype = col[0], col[1]
        default = f" DEFAULT {col[2]}" if len(col) > 2 else ""
        con.execute(f'ALTER TABLE ichor_events ADD COLUMN "{name}" {ctype}{default}')
    for ev in events:
        cols = ", ".join(ev.keys())
        ph = ", ".join("?" for _ in ev)
        con.execute(f"INSERT INTO ichor_events ({cols}) VALUES ({ph})", list(ev.values()))
    con.commit()
    con.close()


class TestDecay(unittest.TestCase):

    def test_decay_lowers_importance_in_l3(self) -> None:
        """Only L3 (30d+) rows decay; this row is firmly in L3."""
        from lib.ichor_decay import run_decay
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            old = (now - timedelta(days=103)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "fact",
                 "subject": "test", "raw_text": "x",
                 "created_at": old, "importance": 100.0,
                 "god_name": "hermes"},
            ])
            result = run_decay(str(db), dry_run=True, reference_now=now)
            self.assertEqual(result["decayed"], 1)
            self.assertEqual(result["skipped"], 0)
            s = result["sample"][0]
            self.assertLess(s["new_importance"], s["old_importance"])
            self.assertGreater(s["new_importance"], 0)

    def test_decay_leaves_l1_l2_untouched(self) -> None:
        """A 10-day-old row is L2 (medium-term): its score must NOT age.

        This is the 2026-09-21 bound. Before it, the sweep was a whole-table
        UPDATE that rewrote 1.82M rows (and their FTS documents) 12x/day.
        """
        from lib.ichor_decay import run_decay
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            l2 = (now - timedelta(days=10)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "fact",
                 "subject": "test", "raw_text": "x",
                 "created_at": l2, "importance": 100.0,
                 "god_name": "hermes"},
            ])
            result = run_decay(str(db), dry_run=False, reference_now=now)
            self.assertEqual(result["decayed"], 0)
            self.assertEqual(result["skipped"], 1)
            con = sqlite3.connect(str(db))
            imp = con.execute("SELECT importance FROM ichor_events WHERE id=1").fetchone()[0]
            con.close()
            self.assertEqual(imp, 100.0, "L1/L2 importance must survive the decay sweep")

    def test_decay_skips_recent_events(self) -> None:
        from lib.ichor_decay import run_decay
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            recent = (now - timedelta(minutes=30)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "fact",
                 "subject": "test", "raw_text": "x",
                 "created_at": recent, "importance": 100.0,
                 "god_name": "hermes"},
            ])
            result = run_decay(str(db), dry_run=True, reference_now=now)
            self.assertEqual(result["decayed"], 0)
            self.assertGreater(result["skipped"], 0)

    def test_decay_apply_writes(self) -> None:
        from lib.ichor_decay import run_decay
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            old = (now - timedelta(days=30)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "fact",
                 "subject": "test", "raw_text": "x",
                 "created_at": old, "importance": 100.0,
                 "god_name": "hermes"},
            ])
            result = run_decay(str(db), dry_run=False, reference_now=now)
            self.assertEqual(result["decayed"], 1)
            # Verify it persisted
            con = sqlite3.connect(str(db))
            imp = con.execute("SELECT importance FROM ichor_events WHERE id=1").fetchone()[0]
            con.close()
            self.assertLess(imp, 100.0)
            self.assertGreater(imp, 0.0)


class TestEviction(unittest.TestCase):

    def test_eviction_candidates_found(self) -> None:
        from lib.ichor_eviction import run_eviction
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            very_old = (now - timedelta(days=120)).isoformat()
            # Low tail of the real 0-100 importance scale. The old 0.01 here
            # was off-scale, which is why this suite stayed green while the live
            # predicate (`importance < 0.1`) matched 0 of 1,813,406 rows.
            very_low = 20.0
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "fact",
                 "subject": "stale", "raw_text": "x",
                 "created_at": very_old, "importance": very_low,
                 "god_name": "hermes"},
            ])
            result = run_eviction(str(db), dry_run=True, reference_now=now)
            self.assertEqual(len(result.get("candidates", [])), 1)

    def test_eviction_skips_recent(self) -> None:
        from lib.ichor_eviction import run_eviction
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            recent = (now - timedelta(days=5)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "fact",
                 "subject": "fresh", "raw_text": "x",
                 "created_at": recent, "importance": 20.0,
                 "god_name": "hermes"},
            ])
            result = run_eviction(str(db), dry_run=True, reference_now=now)
            self.assertEqual(len(result.get("candidates", [])), 0)

    def test_eviction_apply(self) -> None:
        from lib.ichor_eviction import run_eviction
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            very_old = (now - timedelta(days=120)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "fact",
                 "subject": "stale", "raw_text": "x",
                 "created_at": very_old, "importance": 20.0,
                 "god_name": "hermes"},
            ])
            result = run_eviction(str(db), dry_run=False, reference_now=now)
            self.assertEqual(result["archived"], 1)
            # Verify moved to cold storage and removed from main
            con = sqlite3.connect(str(db))
            main_count = con.execute("SELECT COUNT(*) FROM ichor_events").fetchone()[0]
            cold_count = con.execute("SELECT COUNT(*) FROM ichor_cold_storage").fetchone()[0]
            con.close()
            self.assertEqual(main_count, 0)
            self.assertEqual(cold_count, 1)


class TestForge(unittest.TestCase):

    def test_forge_finds_cross_session_pattern(self) -> None:
        from scripts.ichor_overnight_phase4 import run_forge_step
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            recent = (now - timedelta(hours=6)).isoformat()
            _seed_test_db(db, [
                {"session_id": "sess-a", "event_type": "fact",
                 "subject": "hermes:nginx-config", "raw_text": "nginx ssl setup",
                 "created_at": recent, "importance": 80.0,
                 "god_name": "hermes"},
                {"session_id": "sess-b", "event_type": "insight",
                 "subject": "hermes:nginx-config", "raw_text": "renewed certs",
                 "created_at": recent, "importance": 70.0,
                 "god_name": "hephaestus"},
                {"session_id": "sess-a", "event_type": "follow_up",
                 "subject": "hermes:other-topic", "raw_text": "something else",
                 "created_at": recent, "importance": 50.0,
                 "god_name": "hermes"},
            ])
            result = run_forge_step(str(db), dry_run=True, reference_now=now)
            self.assertGreaterEqual(result["patterns_found"], 1)
            topics = [p["topic"] for p in result.get("patterns", [])]
            self.assertIn("nginx-config", topics)

    def test_forge_requires_two_sessions(self) -> None:
        from scripts.ichor_overnight_phase4 import run_forge_step
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            recent = (now - timedelta(hours=2)).isoformat()
            _seed_test_db(db, [
                {"session_id": "sess-a", "event_type": "fact",
                 "subject": "hermes:single-topic", "raw_text": "only one session",
                 "created_at": recent, "importance": 80.0,
                 "god_name": "hermes"},
                {"session_id": "sess-a", "event_type": "follow_up",
                 "subject": "hermes:single-topic", "raw_text": "same session again",
                 "created_at": recent, "importance": 70.0,
                 "god_name": "hermes"},
            ])
            result = run_forge_step(str(db), dry_run=True, reference_now=now)
            # No cross-session pattern — same session doesn't count
            self.assertEqual(result["patterns_found"], 0)


if __name__ == "__main__":
    unittest.main()


class TestScoreMaintenanceBound(unittest.TestCase):
    """apply_decay()/update_maturity() are whole-table UPDATEs, so they are
    bounded to L3 (30d+). ichor_tick runs this module every 2 hours; without
    the bound a 1.82M-row table was rewritten 12x/day to compute a degenerate
    value (88% of rows converge on importance 49.0075)."""

    def _seed(self, db):
        con = sqlite3.connect(str(db))
        con.execute("""
            CREATE TABLE ichor_events (
                id INTEGER PRIMARY KEY, session_id TEXT, event_type TEXT,
                subject TEXT, raw_text TEXT, created_at TEXT,
                importance REAL DEFAULT 50.0, trust REAL DEFAULT 50.0,
                maturity TEXT DEFAULT 'validated', last_access TEXT
            );
        """)
        now = datetime.now(timezone.utc)
        l3 = (now - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
        l2 = (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        con.execute("INSERT INTO ichor_events (id, session_id, event_type, subject,"
                    " raw_text, created_at, importance, maturity) VALUES"
                    " (1,'s1','fact','l3','x',?,100.0,'validated')", (l3,))
        con.execute("INSERT INTO ichor_events (id, session_id, event_type, subject,"
                    " raw_text, created_at, importance, maturity) VALUES"
                    " (2,'s1','fact','l2','x',?,100.0,'validated')", (l2,))
        con.commit()
        return con

    def test_apply_decay_touches_only_l3(self) -> None:
        from lib import ichor_memory_score as score
        with tempfile.TemporaryDirectory() as td:
            con = self._seed(Path(td) / "t.db")
            score.apply_decay(con)
            l3 = con.execute("SELECT importance FROM ichor_events WHERE id=1").fetchone()[0]
            l2 = con.execute("SELECT importance FROM ichor_events WHERE id=2").fetchone()[0]
            con.close()
            self.assertLess(l3, 100.0, "L3 row must decay")
            self.assertEqual(l2, 100.0, "L2 row must keep its score")

    def test_update_maturity_touches_only_l3(self) -> None:
        from lib import ichor_memory_score as score
        with tempfile.TemporaryDirectory() as td:
            con = self._seed(Path(td) / "t.db")
            con.execute("UPDATE ichor_events SET maturity='draft', importance=95.0")
            con.commit()
            score.update_maturity(con)
            l3 = con.execute("SELECT maturity FROM ichor_events WHERE id=1").fetchone()[0]
            l2 = con.execute("SELECT maturity FROM ichor_events WHERE id=2").fetchone()[0]
            con.close()
            self.assertEqual(l3, "core", "L3 row must be reclassified")
            self.assertEqual(l2, "draft", "L2 row must keep its maturity")


class TestEvictionScaleContract(unittest.TestCase):
    """The eviction defect was a unit mismatch, not a tuning choice.

    `importance` is a 0-100 score; the job asked for `< 0.1`. It exited 0 and
    archived nothing for its entire life, and nothing alerted because a
    zero-match predicate is indistinguishable from a healthy idle job. These
    tests assert the *relationship* between the cutoff and the scale it is
    compared against, so the bug cannot come back silently.
    """

    def test_eviction_cutoff_is_scale_correct(self) -> None:
        from lib.ichor_eviction import CUTOFF_IMPORTANCE

        # A sub-1.0 cutoff against a 0-100 column matches nothing, ever.
        self.assertGreater(
            CUTOFF_IMPORTANCE, 1.0,
            "CUTOFF_IMPORTANCE must live on ichor_events.importance's 0-100 scale",
        )
        # And it must sit below the seeded default, or freshly-written rows
        # would be evictable the moment they age out.
        self.assertLess(CUTOFF_IMPORTANCE, 50.0)

    def test_seeded_default_row_is_never_evicted(self) -> None:
        from lib.ichor_eviction import run_eviction

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            very_old = (now - timedelta(days=400)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "fact",
                 "subject": "seed-default", "raw_text": "x",
                 "created_at": very_old, "importance": 50.0,  # schema DEFAULT
                 "god_name": "hermes"},
            ])
            result = run_eviction(str(db), dry_run=True, reference_now=now)
            self.assertEqual(
                len(result.get("candidates", [])), 0,
                "a row at the seeded default must survive, however old",
            )

    def test_result_reports_the_cutoffs_it_applied(self) -> None:
        from lib.ichor_eviction import CUTOFF_DAYS, CUTOFF_IMPORTANCE, run_eviction

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            _seed_test_db(db, [])
            result = run_eviction(str(db), dry_run=True)
            self.assertEqual(result["importance_cutoff"], CUTOFF_IMPORTANCE)
            self.assertEqual(result["age_days"], CUTOFF_DAYS)

    def test_health_monitor_reads_the_shipped_cutoff(self) -> None:
        """The monitor must grade the job against the job's own constant.

        A second copy of a threshold is how this survived: the monitor's own
        "correct" value (10.0) was a third opinion that neither the job nor the
        scale agreed with.
        """
        import importlib.util
        import os

        from lib.ichor_eviction import CUTOFF_DAYS, CUTOFF_IMPORTANCE

        script = Path(__file__).resolve().parent.parent / "scripts" / "ichor-health.py"
        spec = importlib.util.spec_from_file_location("ichor_health_monitor", script)
        module = importlib.util.module_from_spec(spec)
        saved_home = os.environ.get("HOME")
        try:
            spec.loader.exec_module(module)
            cutoff, age_days, source = module._configured_eviction_cutoff()
        finally:
            if saved_home is not None:
                os.environ["HOME"] = saved_home
        self.assertEqual(cutoff, CUTOFF_IMPORTANCE)
        self.assertEqual(age_days, CUTOFF_DAYS)
        self.assertEqual(source, "lib/ichor_eviction.py",
                         "monitor fell back instead of reading the shipped constant")


class TestColdStorageSchema(unittest.TestCase):
    """Eviction had a second, independent silent no-op stacked under the first.

    The cutoff never matched a row, so nobody ever found out that the archive
    INSERT could not execute: `ichor_cold_storage` was created from a hardcoded
    2026-05 DDL and had drifted behind `ichor_events`, raising
    `table ichor_cold_storage has no column named occurred_start`. Fixing the
    threshold alone would have turned the no-op into a nightly crash. These
    tests pin the derived-schema behaviour that makes both work.
    """

    def test_archive_survives_extra_event_columns(self) -> None:
        from lib.ichor_eviction import run_eviction

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            very_old = (now - timedelta(days=400)).isoformat()
            _seed_test_db(
                db,
                [{"session_id": "s1", "event_type": "fact",
                  "subject": "stale", "raw_text": "x",
                  "created_at": very_old, "importance": 20.0,
                  "god_name": "hermes",
                  "occurred_start": "2026-01-01T00:00:00Z",
                  "content_hash": "abc123"}],
                extra_columns=(("occurred_start", "TEXT"), ("content_hash", "TEXT")),
            )
            result = run_eviction(str(db), dry_run=False, reference_now=now)
            self.assertEqual(result["archived"], 1)

            con = sqlite3.connect(str(db))
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM ichor_cold_storage").fetchone()
            con.close()
            self.assertEqual(row["subject"], "stale")
            self.assertEqual(row["occurred_start"], "2026-01-01T00:00:00Z")
            self.assertEqual(row["content_hash"], "abc123")
            self.assertIsNotNone(row["archived_at"])

    def test_existing_narrow_cold_table_is_migrated(self) -> None:
        """A pre-existing legacy cold table must be ALTERed, not crash."""
        from lib.ichor_eviction import run_eviction

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            very_old = (now - timedelta(days=400)).isoformat()
            _seed_test_db(
                db,
                [{"session_id": "s1", "event_type": "fact",
                  "subject": "stale", "raw_text": "x",
                  "created_at": very_old, "importance": 20.0,
                  "god_name": "hermes", "content_hash": "abc123"}],
                extra_columns=(("content_hash", "TEXT"),),
            )
            con = sqlite3.connect(str(db))
            con.execute(
                "CREATE TABLE ichor_cold_storage ("
                " id INTEGER PRIMARY KEY, session_id TEXT, subject TEXT,"
                " importance REAL, archived_at TEXT)"
            )
            con.commit()
            con.close()

            result = run_eviction(str(db), dry_run=False, reference_now=now)
            self.assertEqual(result["archived"], 1)
            con = sqlite3.connect(str(db))
            cols = {r[1] for r in con.execute("PRAGMA table_info(ichor_cold_storage)")}
            n = con.execute("SELECT COUNT(*) FROM ichor_cold_storage").fetchone()[0]
            con.close()
            self.assertIn("content_hash", cols, "legacy cold table was not migrated")
            self.assertEqual(n, 1)

    def test_expression_default_does_not_break_the_derived_ddl(self) -> None:
        """`created_at TEXT DEFAULT (datetime('now'))` is the live shape.

        PRAGMA reports the default as `datetime('now')` without parentheses, and
        re-emitting that verbatim is a syntax error, so the derived CREATE has to
        re-parenthesise expression defaults. Caught live on 2026-09-21: the
        archive refused with `near "(": syntax error`.
        """
        from lib.ichor_eviction import ensure_cold_table, run_eviction

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            very_old = (now - timedelta(days=400)).isoformat()
            _seed_test_db(
                db,
                [{"session_id": "s1", "event_type": "fact",
                  "subject": "stale", "raw_text": "x",
                  "created_at": very_old, "importance": 20.0,
                  "god_name": "hermes"}],
                extra_columns=(("mentioned_at", "TEXT", "(datetime('now'))"),),
            )
            con = sqlite3.connect(str(db))
            ensure_cold_table(con)  # must not raise
            con.close()
            result = run_eviction(str(db), dry_run=False, reference_now=now)
            self.assertEqual(result["archived"], 1)
