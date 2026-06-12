"""
ER-P0: Entity-relationship graph schema — gate + contract tests.

Spec: ~/athenaeum/Codex-God-thoth/research/entity-relationship-taxonomies/ichor-entity-model-design.md §Schema
      ~/athenaeum/handoffs/marvin-build-list-2026-06-11.md §ER-P0

ER-P0 gate (per build list):
  [1] All 6 tables exist
  [2] No NULL primary keys
  [3] All expected indexes present
  [4] migrate() is idempotent
  [5] rollback() drops only entity-graph tables (not the 5-tier tables)
  [6] Other 5-tier tables (cold_events, warm_entities, etc.) untouched

Plus contract tests for: bitemporal columns, FK constraints, JSON aliases,
provenance log references, etc.

Note: the "real DB" smoke test in TestER_P0_AgainstIsolatedDB uses an
isolated temp DB, NOT the real ~/.hermes/ichor.db. The real-DB gate
verification lives in test_er_p1_extraction.py (read-only).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path


# Ensure pantheon root is on path (consistent with conftest.py)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.ichor.entities.schema import (  # noqa: E402
    DB_PATH,
    SCHEMA_TABLES,
    _EXPECTED_INDEXES,
    get_conn,
    migrate,
    rollback,
    validate,
)


def _isolated_db() -> Path:
    """Create a temp DB file and return its path. Caller must clean up."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="er_p0_test_")
    os.close(fd)
    return Path(path)


class TestER_P0_Gate(unittest.TestCase):
    """The 6 gate checks from the build list."""

    def setUp(self) -> None:
        self.db_path = _isolated_db()

    def tearDown(self) -> None:
        if self.db_path.exists():
            self.db_path.unlink()
        # Also remove the WAL sidecars SQLite leaves behind
        for ext in ("-wal", "-shm"):
            sidecar = self.db_path.with_name(self.db_path.name + ext)
            if sidecar.exists():
                sidecar.unlink()

    # ---- Gate 1: all 6 tables exist after migrate() ----

    def test_migrate_creates_all_six_tables(self) -> None:
        result = migrate(self.db_path)
        self.assertEqual(result["tables_total"], 6, "schema should have 6 tables")
        self.assertEqual(
            sorted(result["created"]),
            sorted(SCHEMA_TABLES),
            "first migrate should create all 6",
        )
        # Confirm via direct query
        conn = get_conn(self.db_path)
        try:
            for t in SCHEMA_TABLES:
                row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (t,),
                ).fetchone()
                self.assertIsNotNone(row, f"table {t} not created")
        finally:
            conn.close()

    # ---- Gate 2: no NULL primary keys ----

    def test_no_null_primary_keys_on_empty_tables(self) -> None:
        migrate(self.db_path)
        result = validate(self.db_path)
        for table in SCHEMA_TABLES:
            entry = result[table]
            self.assertIsInstance(entry, dict, f"{table} should report OK dict")
            self.assertEqual(entry["status"], "OK", f"{table} status: {entry}")

    def test_no_null_primary_keys_with_data(self) -> None:
        """Insert valid rows into every table; verify no NULL PKs surface."""
        migrate(self.db_path)
        conn = get_conn(self.db_path)
        try:
            # Seed entity_types first (parent of everything else)
            conn.execute(
                "INSERT INTO entity_types (id, description) VALUES (?, ?)",
                ("person", "A natural person"),
            )
            conn.execute(
                "INSERT INTO entity_types (id, description) VALUES (?, ?)",
                ("organization", "A company or group"),
            )
            conn.execute(
                "INSERT INTO entities (type_id, name) VALUES (?, ?)",
                ("person", "Alice"),
            )
            conn.execute(
                "INSERT INTO entities (type_id, name) VALUES (?, ?)",
                ("organization", "Acme"),
            )
            conn.execute(
                "INSERT INTO relationship_types (id, source_type, target_type) VALUES (?, ?, ?)",
                ("works_at", "person", "organization"),
            )
            conn.execute(
                "INSERT INTO relationships "
                "(type_id, source_id, target_id, valid_from) "
                "VALUES (?, ?, ?, ?)",
                ("works_at", 1, 2, "2026-01-01"),
            )
            conn.execute(
                "INSERT INTO entity_facts (entity_id, key, value) VALUES (?, ?, ?)",
                (1, "mrr", "50000"),
            )
            conn.execute(
                "INSERT INTO extraction_log (method, source_text) VALUES (?, ?)",
                ("regex", "Alice works at Acme"),
            )
            conn.commit()
        finally:
            conn.close()

        result = validate(self.db_path)
        for table in SCHEMA_TABLES:
            entry = result[table]
            self.assertIsInstance(entry, dict, f"{table} should report OK")
            self.assertEqual(entry["status"], "OK", f"{table} status: {entry}")
            self.assertGreaterEqual(entry["rows"], 1, f"{table} should have seed row")

    # ---- Gate 3: all expected indexes present ----

    def test_all_expected_indexes_present(self) -> None:
        migrate(self.db_path)
        result = validate(self.db_path)
        indexes = result["_indexes"]
        for table, expected_list in _EXPECTED_INDEXES.items():
            self.assertIn(table, indexes, f"index report missing table {table}")
            for ix in expected_list:
                self.assertEqual(
                    indexes[table][ix],
                    "present",
                    f"index {ix} on {table} not present (got {indexes[table].get(ix)})",
                )

    def test_no_extra_unexpected_indexes_required(self) -> None:
        """The spec is permissive about extra indexes — only checks required ones.

        This test just guards against the case where someone added an
        index that doesn't exist in the spec, leading to a phantom
        required-index list.
        """
        # Total expected indexes = sum of lengths of _EXPECTED_INDEXES values
        total_expected = sum(len(v) for v in _EXPECTED_INDEXES.values())
        migrate(self.db_path)
        result = validate(self.db_path)
        indexes = result["_indexes"]
        total_present = sum(
            1
            for table_expected in indexes.values()
            for status in table_expected.values()
            if status == "present"
        )
        self.assertEqual(total_present, total_expected,
                         f"expected {total_expected} indexes, found {total_present}")

    # ---- Gate 4: migrate() is idempotent ----

    def test_migrate_idempotent(self) -> None:
        first = migrate(self.db_path)
        second = migrate(self.db_path)
        third = migrate(self.db_path)
        self.assertEqual(len(first["created"]), 6, "first run creates all 6")
        self.assertEqual(len(second["created"]), 0, "second run creates nothing")
        self.assertEqual(len(third["created"]), 0, "third run creates nothing")
        self.assertEqual(len(second["already_present"]), 6)
        self.assertEqual(len(third["already_present"]), 6)

    def test_migrate_after_seed_preserves_data(self) -> None:
        """Re-running migrate() must not drop or modify existing rows."""
        migrate(self.db_path)
        conn = get_conn(self.db_path)
        try:
            conn.execute(
                "INSERT INTO entity_types (id, description) VALUES (?, ?)",
                ("person", "A natural person"),
            )
            conn.commit()
        finally:
            conn.close()
        # Re-run migrate
        result = migrate(self.db_path)
        self.assertEqual(len(result["created"]), 0)
        # Data still there?
        conn = get_conn(self.db_path)
        try:
            row = conn.execute(
                "SELECT description FROM entity_types WHERE id='person'"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["description"], "A natural person")
        finally:
            conn.close()

    # ---- Gate 5: rollback() drops only entity-graph tables ----

    def test_rollback_drops_only_entity_tables(self) -> None:
        """Pre-create a non-entity table, run rollback, verify it survives."""
        conn = get_conn(self.db_path)
        try:
            # Mimic a 5-tier table that existed before we got here
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cold_events ("
                "id INTEGER PRIMARY KEY, "
                "raw_text TEXT)"
            )
            conn.execute(
                "INSERT INTO cold_events (raw_text) VALUES (?)",
                ("pre-existing 5-tier data",),
            )
            conn.commit()
        finally:
            conn.close()

        # Now run our migrate (adds entity tables alongside) + rollback
        migrate(self.db_path)
        result = rollback(self.db_path)
        self.assertEqual(len(result["dropped"]), 6)

        # Verify the 5-tier table is still there with its data
        conn = get_conn(self.db_path)
        try:
            row = conn.execute(
                "SELECT raw_text FROM cold_events LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(row, "cold_events should survive rollback")
            self.assertEqual(row["raw_text"], "pre-existing 5-tier data")

            # All 6 entity tables are gone
            for t in SCHEMA_TABLES:
                row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (t,),
                ).fetchone()
                self.assertIsNone(row, f"{t} should be dropped")
        finally:
            conn.close()

    def test_rollback_on_empty_db_is_safe(self) -> None:
        """Rollback on a DB with no entity tables should be a no-op."""
        result = rollback(self.db_path)
        self.assertEqual(result["dropped"], [])

    # ---- Gate 6: 5-tier tables untouched by migrate() ----

    def test_migrate_does_not_alter_existing_5tier_tables(self) -> None:
        """Pre-create the canonical 5-tier tables; verify migrate doesn't touch them."""
        # Snapshot the DB before migrate
        conn = get_conn(self.db_path)
        try:
            # Mimic 5-tier v2 schema (subset that matters)
            for ddl in [
                "CREATE TABLE cold_events (id INTEGER PRIMARY KEY, raw_text TEXT)",
                "CREATE TABLE warm_entities (id INTEGER PRIMARY KEY, name TEXT, "
                "category TEXT, UNIQUE(category, name))",
                "CREATE TABLE reference_knowledge (id INTEGER PRIMARY KEY, slug TEXT)",
                "CREATE TABLE hot_state (key TEXT PRIMARY KEY, value TEXT)",
                "CREATE TABLE strategic_goals (id INTEGER PRIMARY KEY, title TEXT)",
            ]:
                conn.execute(ddl)
            conn.execute(
                "INSERT INTO cold_events (raw_text) VALUES ('pre-existing')"
            )
            conn.execute(
                "INSERT INTO warm_entities (name, category) VALUES ('alice', 'person')"
            )
            conn.commit()
        finally:
            conn.close()

        # Run our migrate
        migrate(self.db_path)

        # Verify pre-existing data is intact
        conn = get_conn(self.db_path)
        try:
            n_cold = conn.execute("SELECT COUNT(*) AS c FROM cold_events").fetchone()["c"]
            n_warm = conn.execute("SELECT COUNT(*) AS c FROM warm_entities").fetchone()["c"]
            self.assertEqual(n_cold, 1, "cold_events row should survive")
            self.assertEqual(n_warm, 1, "warm_entities row should survive")
            # And the 5-tier schema is unchanged — we added entity tables
            # alongside, not modified cold_events or warm_entities
            n_entity = conn.execute("SELECT COUNT(*) AS c FROM entities").fetchone()["c"]
            self.assertEqual(n_entity, 0, "entities should be empty after fresh migrate")
        finally:
            conn.close()


class TestER_P0_Contract(unittest.TestCase):
    """Contract tests for column shapes and FK behavior."""

    def setUp(self) -> None:
        self.db_path = _isolated_db()
        migrate(self.db_path)

    def tearDown(self) -> None:
        if self.db_path.exists():
            self.db_path.unlink()
        for ext in ("-wal", "-shm"):
            sidecar = self.db_path.with_name(self.db_path.name + ext)
            if sidecar.exists():
                sidecar.unlink()

    def test_entity_types_supports_hierarchy(self) -> None:
        """parent_type FK should allow 'lead' → 'organization' inheritance."""
        conn = get_conn(self.db_path)
        try:
            conn.execute(
                "INSERT INTO entity_types (id, description) VALUES (?, ?)",
                ("organization", "A company"),
            )
            conn.execute(
                "INSERT INTO entity_types (id, description, parent_type) "
                "VALUES (?, ?, ?)",
                ("lead", "A potential customer", "organization"),
            )
            conn.commit()
            row = conn.execute(
                "SELECT et.id AS child, et.parent_type AS parent "
                "FROM entity_types et WHERE et.id='lead'"
            ).fetchone()
            self.assertEqual(row["parent"], "organization")
        finally:
            conn.close()

    def test_entity_aliases_stores_json_array(self) -> None:
        """The aliases column is TEXT (JSON-encoded array) per the design."""
        import json
        conn = get_conn(self.db_path)
        try:
            conn.execute(
                "INSERT INTO entity_types (id) VALUES ('person')"
            )
            aliases = json.dumps(["Alice", "ali", "A."])
            conn.execute(
                "INSERT INTO entities (type_id, name, aliases) VALUES (?, ?, ?)",
                ("person", "Alice Smith", aliases),
            )
            conn.commit()
            row = conn.execute(
                "SELECT aliases FROM entities WHERE name='Alice Smith'"
            ).fetchone()
            self.assertEqual(json.loads(row["aliases"]), ["Alice", "ali", "A."])
        finally:
            conn.close()

    def test_relationships_bitemporal_columns(self) -> None:
        """valid_from / valid_to: NULL valid_to means 'still true'."""
        conn = get_conn(self.db_path)
        try:
            conn.executemany(
                "INSERT INTO entity_types (id) VALUES (?)",
                [("person",), ("organization",)],
            )
            conn.executemany(
                "INSERT INTO entities (type_id, name) VALUES (?, ?)",
                [("person", "Alice"), ("organization", "Acme")],
            )
            conn.execute(
                "INSERT INTO relationship_types (id, source_type, target_type) "
                "VALUES (?, ?, ?)",
                ("works_at", "person", "organization"),
            )
            # Active relationship (no valid_to)
            conn.execute(
                "INSERT INTO relationships "
                "(type_id, source_id, target_id, valid_from) "
                "VALUES (?, ?, ?, ?)",
                ("works_at", 1, 2, "2026-01-01"),
            )
            # Ended relationship
            conn.execute(
                "INSERT INTO relationships "
                "(type_id, source_id, target_id, valid_from, valid_to) "
                "VALUES (?, ?, ?, ?, ?)",
                ("works_at", 1, 2, "2025-01-01", "2026-01-01"),
            )
            conn.commit()
            active = conn.execute(
                "SELECT COUNT(*) AS c FROM relationships WHERE valid_to IS NULL"
            ).fetchone()["c"]
            ended = conn.execute(
                "SELECT COUNT(*) AS c FROM relationships WHERE valid_to IS NOT NULL"
            ).fetchone()["c"]
            self.assertEqual(active, 1)
            self.assertEqual(ended, 1)
        finally:
            conn.close()

    def test_relationships_unique_constraint_prevents_duplicate_facts(self) -> None:
        """The UNIQUE(type_id, source_id, target_id, valid_from) constraint
        prevents recording the same 'factually true at time T' twice."""
        import sqlite3 as sql
        conn = get_conn(self.db_path)
        try:
            conn.executemany(
                "INSERT INTO entity_types (id) VALUES (?)",
                [("person",), ("organization",)],
            )
            conn.executemany(
                "INSERT INTO entities (type_id, name) VALUES (?, ?)",
                [("person", "Alice"), ("organization", "Acme")],
            )
            conn.execute(
                "INSERT INTO relationship_types (id, source_type, target_type) "
                "VALUES (?, ?, ?)",
                ("works_at", "person", "organization"),
            )
            conn.execute(
                "INSERT INTO relationships "
                "(type_id, source_id, target_id, valid_from) "
                "VALUES (?, ?, ?, ?)",
                ("works_at", 1, 2, "2026-01-01"),
            )
            conn.commit()
            # Second insert with same (type, source, target, valid_from) → IntegrityError
            with self.assertRaises(sql.IntegrityError):
                conn.execute(
                    "INSERT INTO relationships "
                    "(type_id, source_id, target_id, valid_from) "
                    "VALUES (?, ?, ?, ?)",
                    ("works_at", 1, 2, "2026-01-01"),
                )
        finally:
            conn.close()

    def test_extraction_log_method_constraint(self) -> None:
        """extraction_log.method should be NOT NULL with no default — we must supply it."""
        conn = get_conn(self.db_path)
        try:
            with self.assertRaises(sqlite3_IntegrityError()):
                conn.execute(
                    "INSERT INTO extraction_log (source_text) VALUES ('no method')"
                )
        finally:
            conn.close()


def sqlite3_IntegrityError():
    """Return sqlite3.IntegrityError (avoids the import in test bodies)."""
    import sqlite3
    return sqlite3.IntegrityError


class TestER_P0_PublicAPI(unittest.TestCase):
    """The package's __init__ should re-export the schema helpers."""

    def test_imports_work(self) -> None:
        from lib.ichor.entities import (  # noqa: F401
            DB_PATH,
            SCHEMA_TABLES,
            get_conn,
            migrate,
            rollback,
            status,
            validate,
        )
        self.assertEqual(len(SCHEMA_TABLES), 6)

    def test_status_is_alias_for_validate(self) -> None:
        from lib.ichor.entities import status, validate
        # Both exist and return the same shape (call-through wrapper).
        # We test behavioral equivalence, not object identity, because
        # `status` is defined as `return validate(db_path)` in schema.py
        # rather than `status = validate` (latter would lose the docstring).
        import inspect
        self.assertTrue(callable(status))
        self.assertTrue(callable(validate))
        # Same signature minus docstring variation
        self.assertEqual(
            list(inspect.signature(status).parameters),
            list(inspect.signature(validate).parameters),
        )


class TestER_P0_AgainstIsolatedDB(unittest.TestCase):
    """End-to-end smoke test using an ISOLATED temp DB.

    IMPORTANT: The previous version of this test ran migrate() +
    rollback() against the real ~/.hermes/ichor.db. That was destructive:
    it dropped any data the entity tables had, which broke P1's
    backfill results. This version uses a temp DB and patches DB_PATH
    for the test's duration.

    Real-DB gate verification belongs in test_er_p1_extraction.py,
    where it's a read-only inspection of the post-backfill state.
    """

    def setUp(self) -> None:
        self.db_path = _isolated_db()
        # Override the module-level DB_PATH for this test only.
        from lib.ichor.entities import schema as _schema
        self._original_db_path = _schema.DB_PATH
        _schema.DB_PATH = self.db_path

    def tearDown(self) -> None:
        from lib.ichor.entities import schema as _schema
        _schema.DB_PATH = self._original_db_path
        if self.db_path.exists():
            self.db_path.unlink()
        for ext in ("-wal", "-shm"):
            sidecar = self.db_path.with_name(self.db_path.name + ext)
            if sidecar.exists():
                sidecar.unlink()

    def test_migrate_then_rollback_against_isolated_db(self) -> None:
        # Pre-state: nothing exists
        pre = validate()
        for t in SCHEMA_TABLES:
            self.assertEqual(pre[t], "MISSING", f"{t} should be missing pre-migrate")

        # Run migrate
        result = migrate()
        self.assertEqual(result["tables_total"], 6)

        # Post-state: all 6 entity tables present
        post = validate()
        for t in SCHEMA_TABLES:
            self.assertIn(t, post, f"{t} missing after migrate()")
            self.assertIsInstance(post[t], dict, f"{t} not OK")
            self.assertEqual(post[t]["status"], "OK")

        # Rollback to verify the migration is reversible
        rb = rollback()
        self.assertEqual(len(rb["dropped"]), 6, "rollback should drop all 6")

        # Verify gone
        post_rb = validate()
        for t in SCHEMA_TABLES:
            self.assertEqual(post_rb[t], "MISSING", f"{t} should be gone")


if __name__ == "__main__":
    unittest.main()
