"""Ichor Phase 0A claim, evidence, and entity contracts.

Architecture
============
The existing ``cold_events`` table is an immutable activity stream. Claims are
different: they are crystallized beliefs with an explicit lifecycle, temporal
validity, confidence, and trust. This module supplies the typed boundary and a
small transactional SQLite repository used by later extractors, tension gates,
profile compilers, and lifecycle tools.

Data model
==========
``Claim`` stores the belief. ``Evidence`` links it back to source events and
sessions. ``ClaimEntity`` associates it with named entities and optionally
stores the stable semantic vector used by the tension gate. Embeddings are JSON
inside SQLite so the foundation does not depend on sqlite-vec availability.

Operational guarantees
======================
An insertion containing evidence and entities commits atomically. Foreign keys
are enabled for every repository connection. Reads return immutable dataclasses
rather than leaking sqlite rows into callers. This module deliberately contains
no extraction or lifecycle policy; those belong to later master-plan phases.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class Claim:
    """A crystallized fact or hypothesis in the Ichor lifecycle."""

    text: str
    type: str = "fact"
    status: str = "hypothesis"
    zone: Optional[str] = None
    tension_score: Optional[float] = None
    confidence: float = 0.5
    trust_score: Optional[float] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    extracted_by: str = "manual"
    source_session_id: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass(frozen=True)
class Evidence:
    """A source event or session excerpt supporting one claim."""

    source_event_id: Optional[int] = None
    source_session_id: Optional[str] = None
    excerpt: Optional[str] = None


@dataclass(frozen=True)
class ClaimEntity:
    """An entity associated with a claim and its optional semantic vector."""

    entity_name: str
    role: str = "subject"
    embedding: Optional[list[float]] = None


class ClaimStore:
    """Transactional CRUD layer over the Phase 0A claim tables."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def insert_claim(
        self,
        claim: Claim,
        evidence: Iterable[Evidence] = (),
        entities: Iterable[ClaimEntity] = (),
    ) -> int:
        """Insert a claim and all provenance links in one transaction."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ichor_claims (
                    text, type, status, zone, tension_score, confidence,
                    trust_score, valid_from, valid_to, extracted_by,
                    source_session_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), ?, ?, ?)
                """,
                (
                    claim.text, claim.type, claim.status, claim.zone,
                    claim.tension_score, claim.confidence, claim.trust_score,
                    claim.valid_from, claim.valid_to, claim.extracted_by,
                    claim.source_session_id,
                ),
            )
            claim_id = int(cursor.lastrowid)
            for item in evidence:
                self._add_evidence(conn, claim_id, item)
            for item in entities:
                self._add_entity(conn, claim_id, item)
        return claim_id

    def get_claim(self, claim_id: int) -> Optional[Claim]:
        """Return one claim by primary key, or None when absent."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ichor_claims WHERE id = ?", (claim_id,)
            ).fetchone()
        return self._claim_from_row(row) if row else None

    def list_claims_by_entity(self, entity_name: str) -> list[Claim]:
        """List claims linked to an entity, newest claim first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.* FROM ichor_claims AS c
                JOIN ichor_claim_entities AS e ON e.claim_id = c.id
                WHERE e.entity_name = ? ORDER BY c.id DESC
                """,
                (entity_name,),
            ).fetchall()
        return [self._claim_from_row(row) for row in rows]

    def add_evidence(self, claim_id: int, evidence: Evidence) -> None:
        """Attach one evidence record to an existing claim."""
        with self._connect() as conn:
            self._add_evidence(conn, claim_id, evidence)

    def list_evidence(self, claim_id: int) -> list[Evidence]:
        """Return provenance records in insertion order."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source_event_id, source_session_id, excerpt
                FROM ichor_claim_evidence WHERE claim_id = ? ORDER BY id
                """,
                (claim_id,),
            ).fetchall()
        return [Evidence(**dict(row)) for row in rows]

    def add_entity(self, claim_id: int, entity: ClaimEntity) -> None:
        """Attach one entity and optional embedding to an existing claim."""
        with self._connect() as conn:
            self._add_entity(conn, claim_id, entity)

    def list_entities(self, claim_id: int) -> list[ClaimEntity]:
        """Return entity links with embeddings decoded to float lists."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT entity_name, role, embedding FROM ichor_claim_entities
                WHERE claim_id = ? ORDER BY id
                """,
                (claim_id,),
            ).fetchall()
        return [
            ClaimEntity(
                entity_name=row["entity_name"],
                role=row["role"],
                embedding=json.loads(row["embedding"]) if row["embedding"] else None,
            )
            for row in rows
        ]

    @staticmethod
    def _add_evidence(conn: sqlite3.Connection, claim_id: int, evidence: Evidence) -> None:
        conn.execute(
            """
            INSERT INTO ichor_claim_evidence (
                claim_id, source_event_id, source_session_id, excerpt
            ) VALUES (?, ?, ?, ?)
            """,
            (claim_id, evidence.source_event_id, evidence.source_session_id, evidence.excerpt),
        )

    @staticmethod
    def _add_entity(conn: sqlite3.Connection, claim_id: int, entity: ClaimEntity) -> None:
        embedding = json.dumps(entity.embedding) if entity.embedding is not None else None
        conn.execute(
            """
            INSERT INTO ichor_claim_entities (
                claim_id, entity_name, role, embedding
            ) VALUES (?, ?, ?, ?)
            """,
            (claim_id, entity.entity_name, entity.role, embedding),
        )

    @staticmethod
    def _claim_from_row(row: sqlite3.Row) -> Claim:
        return Claim(
            id=row["id"], text=row["text"], type=row["type"], status=row["status"],
            zone=row["zone"], tension_score=row["tension_score"],
            confidence=row["confidence"], trust_score=row["trust_score"],
            valid_from=row["valid_from"], valid_to=row["valid_to"],
            extracted_by=row["extracted_by"],
            source_session_id=row["source_session_id"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
