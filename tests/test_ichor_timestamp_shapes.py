"""`created_at` holds four timestamp shapes; every comparison must normalise.

Regression suite for the 2026-09-22 mismatch. `ichor_events.created_at` is
written in four different shapes by different writers (SQLite's
`DEFAULT (datetime('now'))`, explicit ISO-Z, aware `isoformat()`, and naive
`strftime`). All four are UTC, but a RAW string comparison against a literal of
another shape is only correct down to the DAY: at offset 10 the separator
differs, ' ' (0x20) vs 'T' (0x54).

Live effect on the eviction gate: the predicate
`created_at < '2026-06-24T13:52:42+00:00'` matched id 164078 at
'2026-06-24 23:51:31' -- a row 89.6 days old, not 90 -- because ' ' < 'T'
decided the comparison. The defect is in the DELETE direction: it evicts rows
that are not yet old enough. The same shape error under-includes in the other
direction (morning-briefing's 14h lookback used a naive-'T' cutoff and silently
dropped space-shaped rows from the overnight inbox).

The fix normalises BOTH sides with SQLite's `datetime()`. These tests pin that
behaviour so the raw comparison cannot come back.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The instant the live defect fired on: a 90-day cutoff of 2026-06-24T13:52:42Z.
CUTOFF_NOW = datetime(2026, 9, 22, 13, 52, 42, tzinfo=timezone.utc)
# Same day as the cutoff, AFTER the cutoff instant -> 89.6 days old -> must survive.
LATE_SPACE = "2026-06-24 23:51:31"
LATE_ISO = "2026-06-24T23:51:31Z"
# Same day as the cutoff, BEFORE the cutoff instant -> 90.5 days old -> evictable.
EARLY_SPACE = "2026-06-24 01:00:00"
EARLY_ISO = "2026-06-24T01:00:00Z"


def _seed(db_path: Path, events: list[dict], *, side_tables: bool = False) -> None:
    """Minimal ichor_events (+ optional tag/evidence tables) for the gates."""
    con = sqlite3.connect(str(db_path))
    con.executescript(
        """
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
        """
    )
    if side_tables:
        # Mirrors the live schema's referential declarations -- which never fire,
        # because sqlite3 opens connections with `foreign_keys=OFF`.
        con.executescript(
            """
            CREATE TABLE ichor_event_tags (
                event_id INTEGER NOT NULL REFERENCES ichor_events(id) ON DELETE CASCADE,
                tag TEXT NOT NULL,
                PRIMARY KEY (event_id, tag)
            );
            CREATE TABLE ichor_observation_sources (
                observation_id INTEGER NOT NULL,
                event_id INTEGER REFERENCES ichor_events(id) ON DELETE SET NULL,
                quote TEXT NOT NULL
            );
            """
        )
    for ev in events:
        cols = ", ".join(ev.keys())
        ph = ", ".join("?" for _ in ev)
        con.execute(f"INSERT INTO ichor_events ({cols}) VALUES ({ph})", list(ev.values()))
    con.commit()
    con.close()


def _row(created_at: str, importance: float = 20.0, subject: str = "stale") -> dict:
    return {
        "session_id": "s1", "event_type": "fact", "subject": subject,
        "raw_text": "x", "created_at": created_at, "importance": importance,
        "god_name": "hermes",
    }


class TestShapeNormalisation(unittest.TestCase):
    """`datetime()` is the normaliser every comparison site now relies on."""

    def test_all_four_stored_shapes_normalise_to_one_instant(self) -> None:
        shapes = [
            "2026-06-24 13:52:42",               # SQLite DEFAULT (datetime('now'))
            "2026-06-24T13:52:42Z",              # explicit ISO-8601 UTC
            "2026-06-24T13:52:42.123456+00:00",  # aware datetime.isoformat()
            "2026-06-24T13:52:42",               # naive strftime
        ]
        con = sqlite3.connect(":memory:")
        normalised = {con.execute("SELECT datetime(?)", (s,)).fetchone()[0] for s in shapes}
        con.close()
        self.assertEqual(normalised, {"2026-06-24 13:52:42"})

    def test_an_explicit_offset_is_converted_to_utc(self) -> None:
        con = sqlite3.connect(":memory:")
        got = con.execute("SELECT datetime(?)", ("2026-06-24T13:52:42+02:00",)).fetchone()[0]
        con.close()
        self.assertEqual(got, "2026-06-24 11:52:42")

    def test_unparseable_timestamp_is_null_and_therefore_never_older(self) -> None:
        """`NULL < x` is not true, so a malformed row can never be evicted.

        Note the comparison yields NULL rather than 0 -- which is exactly why the
        property has to be asserted through a WHERE clause and not by reading the
        expression's value.
        """
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE t (created_at TEXT)")
        con.execute("INSERT INTO t VALUES ('not-a-timestamp')")
        normalised = con.execute("SELECT datetime(created_at) FROM t").fetchone()[0]
        selected = con.execute(
            "SELECT COUNT(*) FROM t WHERE datetime(created_at) < datetime('now')"
        ).fetchone()[0]
        con.close()
        self.assertIsNone(normalised)
        self.assertEqual(selected, 0, "an unparseable timestamp must never be eligible")


class TestEvictionBoundaryRegression(unittest.TestCase):
    """The exact live failure, frozen at the instant it fired."""

    def _candidates(self, created_at: str) -> list[int]:
        from lib.ichor_eviction import run_eviction
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            _seed(db, [_row(created_at)])
            result = run_eviction(str(db), dry_run=True, reference_now=CUTOFF_NOW)
            return result["candidates"]

    def test_space_shaped_row_inside_the_window_survives(self) -> None:
        """id 164078's shape: 89.6 days old, was eligible under the raw compare."""
        self.assertEqual(self._candidates(LATE_SPACE), [],
                         "a row younger than the age cutoff must never be evicted")

    def test_iso_shaped_row_inside_the_window_survives(self) -> None:
        self.assertEqual(self._candidates(LATE_ISO), [])

    def test_rows_past_the_cutoff_are_evicted_in_every_shape(self) -> None:
        self.assertEqual(len(self._candidates(EARLY_SPACE)), 1)
        self.assertEqual(len(self._candidates(EARLY_ISO)), 1)

    def test_shapes_agree_for_the_same_instant(self) -> None:
        """Same instant, two shapes -> identical verdict, which is the contract."""
        self.assertEqual(len(self._candidates(LATE_SPACE)), len(self._candidates(LATE_ISO)))
        self.assertEqual(len(self._candidates(EARLY_SPACE)), len(self._candidates(EARLY_ISO)))

    def test_the_raw_string_comparison_is_what_admitted_it(self) -> None:
        """Pin the defect itself, so this suite fails if SQLite changes semantics.

        The old predicate passed a `datetime.isoformat()` cutoff
        ('2026-06-24T13:52:42+00:00'). Under a raw string compare the space-shaped
        row sorts BEFORE it -- ' ' (0x20) < 'T' (0x54) at offset 10 -- which is
        why an 89.6-day-old row was eligible for a 90-day eviction.
        """
        cutoff_iso = (CUTOFF_NOW - timedelta(days=90)).isoformat()
        con = sqlite3.connect(":memory:")
        raw = con.execute("SELECT ? < ?", (LATE_SPACE, cutoff_iso)).fetchone()[0]
        normalised = con.execute(
            "SELECT datetime(?) < datetime(?)", (LATE_SPACE, cutoff_iso)
        ).fetchone()[0]
        con.close()
        self.assertEqual(raw, 1, "the raw comparison admitted the row (the defect)")
        self.assertEqual(normalised, 0, "the normalised comparison rejects it (the fix)")

    def test_the_shipped_predicate_normalises_the_column(self) -> None:
        from lib.ichor_eviction import eligibility_sql
        sql = eligibility_sql("datetime(?)")
        self.assertIn("datetime(created_at)", sql)
        self.assertNotIn("created_at <", sql,
                         "the raw column must never be compared directly")


class TestEvictionLockstepCleanup(unittest.TestCase):
    """The DELETE must not orphan rows whose FK cascades never fire."""

    def test_apply_removes_tags_and_unlinks_evidence(self) -> None:
        from lib.ichor_eviction import run_eviction
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            _seed(db, [_row(EARLY_SPACE, subject="stale")], side_tables=True)
            con = sqlite3.connect(str(db))
            con.execute("INSERT INTO ichor_event_tags (event_id, tag) VALUES (1, 'old')")
            con.execute("INSERT INTO ichor_event_tags (event_id, tag) VALUES (1, 'junk')")
            con.execute(
                "INSERT INTO ichor_observation_sources (observation_id, event_id, quote)"
                " VALUES (7, 1, 'quoted')"
            )
            con.commit()
            con.close()

            result = run_eviction(str(db), dry_run=False, reference_now=CUTOFF_NOW)
            self.assertEqual(result["archived"], 1)
            self.assertEqual(result["tags_removed"], 2)
            self.assertEqual(result["evidence_unlinked"], 1)

            con = sqlite3.connect(str(db))
            orphans = con.execute(
                "SELECT COUNT(*) FROM ichor_event_tags t "
                "WHERE NOT EXISTS (SELECT 1 FROM ichor_events e WHERE e.id = t.event_id)"
            ).fetchone()[0]
            dangling = con.execute(
                "SELECT COUNT(*) FROM ichor_observation_sources s "
                "WHERE s.event_id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM ichor_events e WHERE e.id = s.event_id)"
            ).fetchone()[0]
            unlinked = con.execute(
                "SELECT COUNT(*) FROM ichor_observation_sources WHERE event_id IS NULL"
            ).fetchone()[0]
            cold = con.execute("SELECT COUNT(*) FROM ichor_cold_storage").fetchone()[0]
            archived_at = con.execute("SELECT archived_at FROM ichor_cold_storage").fetchone()[0]
            con.close()
            self.assertEqual(orphans, 0, "tag rows were orphaned by the delete")
            self.assertEqual(dangling, 0, "evidence still points at a deleted event")
            self.assertEqual(unlinked, 1, "evidence must be unlinked, not deleted")
            self.assertEqual(cold, 1, "the archive is what makes eviction recoverable")
            # archived_at matches the column DEFAULT's shape, so it stays
            # comparable with a plain `datetime(archived_at)`.
            self.assertEqual(archived_at, "2026-09-22 13:52:42")

    def test_apply_on_a_db_without_side_tables_is_safe(self) -> None:
        """A foreign/fresh DB has no tag tables; eviction must still work."""
        from lib.ichor_eviction import run_eviction
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            _seed(db, [_row(EARLY_SPACE)])
            result = run_eviction(str(db), dry_run=False, reference_now=CUTOFF_NOW)
            self.assertEqual(result["archived"], 1)
            self.assertEqual(result["tags_removed"], 0)
            self.assertEqual(result["evidence_unlinked"], 0)


class TestMonitorPredicateMatchesJob(unittest.TestCase):
    """The monitor must grade the job with the job's own predicate."""

    def _monitor_module(self):
        script = ROOT / "scripts" / "ichor-health.py"
        spec = importlib.util.spec_from_file_location("ichor_health_monitor_shapes", script)
        module = importlib.util.module_from_spec(spec)
        saved_home = os.environ.get("HOME")
        try:
            spec.loader.exec_module(module)
        finally:
            if saved_home is not None:
                os.environ["HOME"] = saved_home
        return module

    def test_monitor_predicate_is_the_shipped_one(self) -> None:
        from lib.ichor_eviction import eligibility_sql
        module = self._monitor_module()
        self.assertEqual(
            module._eviction_predicate_sql("datetime('now', ?)"),
            eligibility_sql("datetime('now', ?)"),
            "the monitor restated the predicate instead of importing it",
        )

    def test_monitor_predicate_normalises_created_at(self) -> None:
        module = self._monitor_module()
        sql = module._eviction_predicate_sql("datetime('now', ?)")
        self.assertIn("datetime(created_at)", sql)
        self.assertNotIn("created_at <", sql)


class TestOrchestratorStepGating(unittest.TestCase):
    """`--apply-step` is what lets eviction apply while decay stays gated."""

    def _run(self, td: str, *args: str) -> tuple[subprocess.CompletedProcess, dict, Path]:
        db = Path(td) / "test.db"
        result_json = Path(td) / "result.json"
        _seed(db, [_row(EARLY_SPACE, importance=20.0)])
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "ichor_overnight_phase4.py"),
             "--db", str(db), "--result-json", str(result_json), *args],
            cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
        )
        payload = json.loads(result_json.read_text()) if result_json.exists() else {}
        return proc, payload, db

    def test_apply_step_evict_applies_only_eviction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proc, payload, db = self._run(td, "--apply-step", "evict")
            self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
            self.assertEqual(
                payload["steps"],
                {"decay": "dry-run", "eviction": "APPLIED", "forge": "dry-run"},
            )
            self.assertFalse(payload["dry_run"])
            self.assertEqual(payload["applied_steps"], ["evict"])
            self.assertIn("eviction=APPLIED", proc.stdout)
            self.assertIn("decay=dry-run", proc.stdout)
            con = sqlite3.connect(str(db))
            cold = con.execute("SELECT COUNT(*) FROM ichor_cold_storage").fetchone()[0]
            live = con.execute("SELECT COUNT(*) FROM ichor_events").fetchone()[0]
            con.close()
            self.assertEqual((cold, live), (1, 0), "eviction did not apply")

    def test_decay_is_not_applied_by_the_wired_command(self) -> None:
        """The approved wiring must not rewrite importance (not recoverable)."""
        with tempfile.TemporaryDirectory() as td:
            proc, payload, db = self._run(td, "--apply-step", "evict")
            self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
            con = sqlite3.connect(str(db))
            importance = con.execute("SELECT importance FROM ichor_cold_storage").fetchone()[0]
            con.close()
            self.assertEqual(importance, 20.0, "decay rewrote importance while gated")

    def test_no_args_is_still_a_full_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proc, payload, db = self._run(td)
            self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["applied_steps"], [])
            self.assertIn("Phase 4 DRY-RUN complete", proc.stdout)
            con = sqlite3.connect(str(db))
            live = con.execute("SELECT COUNT(*) FROM ichor_events").fetchone()[0]
            con.close()
            self.assertEqual(live, 1, "a bare invocation must not mutate anything")

    def test_evict_only_apply_still_works(self) -> None:
        """The literal command A named keeps its original meaning."""
        with tempfile.TemporaryDirectory() as td:
            proc, payload, db = self._run(td, "--evict-only", "--apply")
            self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
            self.assertEqual(payload["steps"], {"eviction": "APPLIED"})
            con = sqlite3.connect(str(db))
            cold = con.execute("SELECT COUNT(*) FROM ichor_cold_storage").fetchone()[0]
            con.close()
            self.assertEqual(cold, 1)


if __name__ == "__main__":
    unittest.main()
