"""Contract tests for Ichor Master Plan Phase 0A.

These tests pin the public claim/evidence/entity schema and exercise the real
SQLite-backed CRUD surface. They intentionally use a fresh database so the
migration contract is verified without relying on live Pantheon state.

Acceptance criteria covered:
- all three Phase 0A tables and required claim columns exist;
- applying the schema twice is safe;
- claims, evidence links, entities, and embeddings round-trip;
- entity-based claim lookup returns only associated claims.
"""

import sqlite3
from pathlib import Path

from lib.ichor import schema_v2
from lib.ichor.contracts import Claim, ClaimEntity, ClaimStore, Evidence


def _connect_schema_db(db_path: Path) -> sqlite3.Connection:
    """Open an isolated DB with the same sqlite-vec extension as production.

    ``SCHEMA_SQL`` includes the optional vec0 virtual table. Loading the
    extension here keeps the test faithful to the production migration instead
    of deleting unrelated schema statements merely to exercise Phase 0A.
    """
    import sqlite_vec

    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _make_store(tmp_path: Path) -> ClaimStore:
    """Create a fully migrated isolated store for one test."""
    db_path = tmp_path / "ichor.db"
    conn = _connect_schema_db(db_path)
    conn.executescript(schema_v2.SCHEMA_SQL)
    conn.close()
    return ClaimStore(db_path)


def test_schema_is_idempotent_and_contains_phase_0a_tables(tmp_path: Path) -> None:
    """The full migration may run repeatedly without losing claim schema."""
    db_path = tmp_path / "ichor.db"
    conn = _connect_schema_db(db_path)
    conn.executescript(schema_v2.SCHEMA_SQL)
    conn.executescript(schema_v2.SCHEMA_SQL)

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    claim_columns = {
        row[1] for row in conn.execute("PRAGMA table_info('ichor_claims')")
    }
    conn.close()

    assert {"ichor_claims", "ichor_claim_evidence", "ichor_claim_entities"} <= tables
    assert {
        "id", "text", "type", "status", "zone", "tension_score",
        "confidence", "trust_score", "valid_from", "valid_to",
        "extracted_by", "source_session_id", "created_at", "updated_at",
    } <= claim_columns


def test_insert_and_read_claim_with_evidence_and_entity(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    claim_id = store.insert_claim(
        Claim(
            text="Pantheon uses SQLite for Ichor memory.",
            type="fact",
            extracted_by="structural",
            source_session_id="session-123",
            confidence=0.85,
        ),
        evidence=[Evidence(source_event_id=42, source_session_id="session-123")],
        entities=[ClaimEntity(entity_name="Ichor", role="subject", embedding=[0.1, 0.2])],
    )

    stored = store.get_claim(claim_id)
    assert stored is not None
    assert stored.text == "Pantheon uses SQLite for Ichor memory."
    assert stored.status == "hypothesis"
    assert stored.confidence == 0.85
    assert store.list_evidence(claim_id) == [
        Evidence(source_event_id=42, source_session_id="session-123", excerpt=None)
    ]

    claims = store.list_claims_by_entity("Ichor")
    assert [claim.id for claim in claims] == [claim_id]
    assert store.list_claims_by_entity("Unknown") == []


def test_claim_entity_embedding_round_trips_as_floats(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    claim_id = store.insert_claim(Claim(text="A claim"))
    store.add_entity(
        claim_id,
        ClaimEntity(entity_name="Pantheon", role="context", embedding=[1.0, 0.5]),
    )

    entities = store.list_entities(claim_id)
    assert entities == [
        ClaimEntity(entity_name="Pantheon", role="context", embedding=[1.0, 0.5])
    ]
