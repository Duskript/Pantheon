"""Vector similarity search backend for Ichor.

Uses sqlite-vec to store and query 384-dim embeddings in the same SQLite
file as the FTS5 index. Hybrid (FTS5 + vector) becomes a single SQL query.

Schema (added by schema_v2.migrate()):
    CREATE VIRTUAL TABLE event_embeddings USING vec0(
        event_id INTEGER PRIMARY KEY,
        embedding float[384]
    )

The `event_id` is the rowid of the source row in ichor_events (or
cold_events after the 5-tier migration). One vector per event.

Search returns KNN-N by cosine distance. Distance is converted to a
similarity score in [0, 1] via 1 / (1 + distance).

Spike (2026-06-20, 1K vectors, this hardware):
    KNN-10 query latency: 4.3ms
    Storage: 1,626 bytes/vector
    Projected 107K vectors: ~166 MB total, ~30-80ms KNN (not benchmarked)
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import sqlite3
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger("ichor.vector_backend")

_DB_PATH = Path.home() / ".hermes" / "ichor.db"
_EXPECTED_DIM = 384


class EmbeddingProvider(Protocol):
    """Provider-neutral interface for embedding one claim-sized text."""

    def embed_one(self, text: str) -> Optional[List[float]]:
        """Return a stable vector for text, or None when unavailable."""


class _BGEEmbeddingProvider:
    """Adapter around Ichor's existing cached local BGE embedder."""

    @staticmethod
    def embed_one(text: str) -> Optional[List[float]]:
        from lib.ichor.embedder import embed_one

        return embed_one(text)


def _local_feature_embedding(text: str) -> List[float]:
    """Build a deterministic 384-dim lexical vector with feature hashing.

    This dependency-free fallback preserves tension scoring when the optional
    BGE runtime is absent. Word unigrams and adjacent bigrams are hashed into a
    signed fixed-width vector and L2-normalized, giving related claim texts a
    useful lexical similarity signal without pretending to be a neural model.
    """
    words = re.findall(r"[a-z0-9_./:-]+", text.lower())
    features = words + [f"{left}::{right}" for left, right in zip(words, words[1:])]
    vector = [0.0] * _EXPECTED_DIM
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        index = value % _EXPECTED_DIM
        vector[index] += 1.0 if value & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]
    return vector


def get_embedding(
    text: str,
    provider: Optional[EmbeddingProvider] = None,
) -> List[float]:
    """Return a stable vector for claim-length text.

    Callers depend only on ``EmbeddingProvider`` and can substitute an API,
    Ollama adapter, or another local model. When no provider is supplied the
    existing lazily-loaded BGE-small pipeline is preferred, with a deterministic
    384-dimensional lexical fallback when BGE is unavailable. Blank input fails
    loudly because tension scoring cannot safely use an absent semantic signal.
    """
    if not text or not text.strip():
        raise ValueError("embedding text must be non-empty")

    selected = provider or _BGEEmbeddingProvider()
    vector = selected.embed_one(text)
    if not vector and provider is None:
        logger.info("BGE embedder unavailable; using local feature-hash embedding")
        vector = _local_feature_embedding(text)
    if not vector:
        raise RuntimeError("embedding provider returned an empty vector")
    return [float(value) for value in vector]


def _ensure_vec_loaded(conn: sqlite3.Connection) -> None:
    """Load sqlite-vec extension on a connection."""
    conn.enable_load_extension(True)
    try:
        import sqlite_vec
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


class VectorBackend:
    """KNN search over ichor_event_embeddings using sqlite-vec."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._db = None

    def _connect(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = sqlite3.connect(str(self._db_path))
            self._db.row_factory = sqlite3.Row
            _ensure_vec_loaded(self._db)
        return self._db

    def health(self) -> bool:
        try:
            db = self._connect()
            db.execute("SELECT 1 FROM event_embeddings LIMIT 1")
            return True
        except Exception as exc:
            logger.debug("VectorBackend health failed: %s", exc)
            return False

    def upsert(self, event_id: int, vector: List[float]) -> None:
        """Insert or replace a vector for an event_id."""
        if len(vector) != _EXPECTED_DIM:
            raise ValueError(
                f"Vector dim {len(vector)} != expected {_EXPECTED_DIM}"
            )
        db = self._connect()
        packed = struct.pack(f"{_EXPECTED_DIM}f", *vector)
        db.execute(
            "INSERT OR REPLACE INTO event_embeddings(event_id, embedding) VALUES (?, ?)",
            (event_id, packed),
        )
        db.commit()

    def upsert_batch(self, items: List[tuple]) -> None:
        """Bulk insert. items = [(event_id, vector), ...]"""
        if not items:
            return
        db = self._connect()
        rows = [
            (eid, struct.pack(f"{_EXPECTED_DIM}f", *vec))
            for eid, vec in items
            if len(vec) == _EXPECTED_DIM
        ]
        db.executemany(
            "INSERT OR REPLACE INTO event_embeddings(event_id, embedding) VALUES (?, ?)",
            rows,
        )
        db.commit()

    def search(
        self,
        query: str | List[float],
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """KNN search. Returns list of {event_id, distance, score}.

        Accepts either a pre-computed embedding vector (List[float]) or a
        raw query string. When given a string and no embedding service is
        available, returns an empty list rather than crashing — the hybrid
        scorer's backend loop expects a uniform ``(query, limit) -> list``
        contract.

        Phase 4 (ichor-athenaeum-god-aware-retrieval-build-spec-v1.md
        §Phase 4 — Vector Hydration + Safer Ranking) — the caller MUST
        hydrate `event_id` against cold_events before using the hit as a
        final ranked result. An unhydrated vector hit carries no snippet,
        no title, no source path — it cannot rank #1 even if the cosine
        distance is small.

        The hydration layer lives in `lib.ichor.retrieval_hydration`
        and consumes the `event_id` field on each hit returned here.
        The chain is:

            VectorBackend.search()      → {event_id, distance, score}
                ↓
            retrieval_hydration.hydrate_event_ids()  → cold_events row
                ↓
            retrieval_hydration.hydrate_vector_results() → snippet/title
                ↓
            retrieval_hydration.apply_rank_modifiers() → fused_score bump
        """
        if isinstance(query, str):
            # No embedding service wired — return empty gracefully
            return []
        if len(query) != _EXPECTED_DIM:
            raise ValueError(
                f"Query vector dim {len(query)} != expected {_EXPECTED_DIM}"
            )
        db = self._connect()
        packed = struct.pack(f"{_EXPECTED_DIM}f", *query)
        try:
            rows = db.execute(
                """
                SELECT event_id, distance
                FROM event_embeddings
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
                """,
                (packed, limit),
            ).fetchall()
        except Exception as exc:
            logger.debug("VectorBackend search failed: %s", exc)
            return []
        results = []
        for r in rows:
            d = float(r["distance"])
            results.append({
                "event_id": int(r["event_id"]),
                "distance": d,
                "score": 1.0 / (1.0 + d),  # convert distance → similarity
            })
        return results

    def count(self) -> int:
        try:
            db = self._connect()
            return int(
                db.execute("SELECT COUNT(*) FROM event_embeddings").fetchone()[0]
            )
        except Exception:
            return 0