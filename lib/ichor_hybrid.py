"""Ichor Hybrid Scorer + Memory Trait Contract.

Fuses 4 backends into a unified retrieval interface:

  | Backend  | Source                    | Weight | Signal      |
  |----------|---------------------------|--------|-------------|
  | FTS5     | ~/.hermes/ichor.db        | 0.20   | Keyword     |
  | ChromaDB | ~/.hermes/pantheon/chroma | 0.35   | Semantic    |
  | Graph    | ~/.hermes/pantheon/graph.db| 0.25   | Relationship|
  | Events   | ~/.hermes/ichor.db        | 0.20   | Structured  |

Memory Trait Contract provides four unified tools:
  - ichor_store(namespace, key, content, category) → stores content
  - ichor_retrieve(query, limit, backends) → fused search across backends
  - ichor_forget(namespace, key) → deletes from all backends
  - ichor_health() → checks all backends

Usage:
    from lib.ichor_hybrid import HybridScorer, MemoryTrait
    scorer = HybridScorer()
    results = scorer.retrieve("SSL cert expiry", limit=10)
    health = MemoryTrait().health_check()
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ichor_hybrid")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HOME = Path.home()
_PANTHEON_LIB = _HOME / "pantheon" / "lib"
_ICHOR_DB = _HOME / ".hermes" / "ichor.db"
_CHROMA_DIR = _HOME / ".hermes" / "pantheon" / "chroma"
_GRAPH_DB = _HOME / ".hermes" / "pantheon" / "graph.db"

# Retrieval query log — append-only JSONL for forge weight tuning
_RETRIEVAL_LOG = _HOME / ".hermes" / "pantheon" / "retrieval-log.jsonl"

# Weights for fused scoring
WEIGHTS = {
    "fts5": 0.25,
    "chroma": 0.35,
    "graph": 0.25,
    "events": 0.15,
}

BACKEND_NAMES = {
    "fts5": "🔍 FTS5 (Keyword)",
    "chroma": "🧠 ChromaDB (Semantic)",
    "graph": "🔗 Graph (Relationships)",
    "events": "📋 Events (Structured)",
}


def _ensure_imports() -> None:
    """Ensure ~/pantheon/ is on sys.path."""
    pantheon_root = str(_HOME / "pantheon")
    if pantheon_root not in sys.path:
        sys.path.insert(0, pantheon_root)


# ===================================================================
# Backend Connectors
# ===================================================================


class FTS5Backend:
    """Keyword search over ichor_events via SQLite FTS5."""

    def __init__(self) -> None:
        self._db = None

    def _connect(self):
        if self._db is None:
            _ensure_imports()
            from lib.ichor_db import IchorDB  # type: ignore[import-untyped]
            self._db = IchorDB(db_path=str(_ICHOR_DB))
            self._db.connect()
        return self._db

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """FTS5 full-text search across ichor_events."""
        try:
            db = self._connect()
            events = db.query_fts(query, limit=limit)
            max_score = max((e.get("confidence", 0) for e in events), default=1.0)
            results = []
            for ev in events:
                results.append({
                    "id": f"fts5:{ev['id']}",
                    "score": round(ev.get("confidence", 0.5) / max_score, 3),
                    "backend": "fts5",
                    "type": ev.get("event_type", ""),
                    "title": ev.get("subject", ""),
                    "snippet": (ev.get("raw_text") or "")[:300],
                    "source": ev.get("session_id", ""),
                    "created_at": ev.get("created_at", ""),
                })
            return results
        except Exception as exc:
            logger.debug("FTS5 search failed: %s", exc)
            return []

    def health(self) -> bool:
        try:
            db = self._connect()
            db._conn.execute("SELECT 1 FROM ichor_events LIMIT 1")
            return True
        except Exception:
            return False


class ChromaBackend:
    """Semantic search over Athenaeum via ChromaDB."""

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
            collections = client.list_collections()
            if not collections:
                return []

            # Embed query
            embedder = _Embedder()
            if not embedder.is_available():
                return []

            query_emb = embedder.embed(query[:512])
            if not query_emb:
                return []

            results: List[Dict[str, Any]] = []
            for col in collections:
                try:
                    qr = col.query(
                        query_embeddings=[query_emb],
                        n_results=min(limit, 5),
                    )
                    ids = qr.get("ids", [[]])[0]
                    distances = qr.get("distances", [[]])[0]
                    documents = qr.get("documents", [[]])[0]
                    metadatas = qr.get("metadatas", [[]])[0]

                    for i, doc_id in enumerate(ids):
                        dist = distances[i] if i < len(distances) else 1.0
                        sim = max(0.0, 1.0 - dist)
                        doc = documents[i] if i < len(documents) else ""
                        meta = metadatas[i] if i < len(metadatas) else {}

                        results.append({
                            "id": f"chroma:{doc_id}",
                            "score": round(sim, 3),
                            "backend": "chroma",
                            "type": "document",
                            "title": meta.get("source", doc_id)[:100],
                            "snippet": doc[:300],
                            "source": col.name,
                            "created_at": meta.get("timestamp", ""),
                        })
                except Exception:
                    continue

            # Sort by score, cap
            results.sort(key=lambda x: x["score"], reverse=True)
            norm = max((r["score"] for r in results), default=1.0)
            for r in results:
                r["score"] = round(r["score"] / norm, 3) if norm > 0 else 0

            # ⚡ SYSTEM RULE: distilled documents always rank above raw sessions.
            # A distilled doc is the canonical reference — the god reads this first
            # and only falls back to the raw session if more detail is needed.
            # Boost by +0.3 ensures distilled docs overtake raw session results
            # in the fused ranking without distorting relative relevance.
            for r in results:
                doc_id = r.get("id", "")
                if "--distilled" in doc_id or "distilled/" in doc_id:
                    r["score"] = round(min(r["score"] + 0.3, 1.0), 3)

            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:limit]

        except Exception as exc:
            logger.debug("ChromaDB search failed: %s", exc)
            return []

    def health(self) -> bool:
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
            client.heartbeat()
            return True
        except Exception:
            return False


class GraphBackend:
    """Entity relationship search via graph.db."""

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            import sqlite3
            conn = sqlite3.connect(str(_GRAPH_DB))
            conn.row_factory = sqlite3.Row

            # Search nodes by label matching
            cursor = conn.execute(
                """
                SELECT n.*, COUNT(e.id) AS edge_count
                FROM nodes n
                LEFT JOIN edges e ON e.source_id = n.id OR e.target_id = n.id
                WHERE n.label LIKE ? OR n.id LIKE ?
                GROUP BY n.id
                ORDER BY edge_count DESC
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", limit),
            )
            rows = [dict(r) for r in cursor.fetchall()]

            if not rows:
                # No matching nodes — return empty, don't fall back to general
                conn.close()
                return []

            max_edges = max((r.get("edge_count", 1) for r in rows), default=1)
            results = []
            for r in rows:
                score = min(r.get("edge_count", 1) / max_edges, 1.0)
                results.append({
                    "id": f"graph:{r['id']}",
                    "score": round(score, 3),
                    "backend": "graph",
                    "type": r.get("type", "entity"),
                    "title": r.get("label", r["id"]),
                    "snippet": f"Type: {r.get('type', '?')} | Edges: {r.get('edge_count', 0)} | Codex: {r.get('codex', '')}",
                    "source": r.get("codex", ""),
                    "created_at": r.get("created_at", ""),
                })
            conn.close()
            return results[:limit]

        except Exception as exc:
            logger.debug("Graph search failed: %s", exc)
            return []

    def health(self) -> bool:
        try:
            import sqlite3
            conn = sqlite3.connect(str(_GRAPH_DB))
            conn.execute("SELECT 1 FROM nodes LIMIT 1")
            conn.close()
            return True
        except Exception:
            return False


class EventsBackend:
    """Structured event search over ichor_events (by type/confidence)."""

    def __init__(self) -> None:
        self._db = None

    def _connect(self):
        if self._db is None:
            _ensure_imports()
            from lib.ichor_db import IchorDB
            self._db = IchorDB(db_path=str(_ICHOR_DB))
            self._db.connect()
        return self._db

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search by matching query against subject or raw_text, ranked by confidence."""
        try:
            db = self._connect()
            conn = db._conn

            # Get recent high-confidence events that match the query terms
            cursor = conn.execute(
                """
                SELECT * FROM ichor_events
                WHERE (subject LIKE ? OR raw_text LIKE ?)
                ORDER BY confidence DESC, created_at DESC
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", limit),
            )
            rows = [dict(r) for r in cursor.fetchall()]

            max_conf = max((r.get("confidence", 0.5) for r in rows), default=1.0)
            results = []
            for r in rows:
                results.append({
                    "id": f"events:{r['id']}",
                    "score": round(r.get("confidence", 0.5) / max_conf, 3),
                    "backend": "events",
                    "type": r.get("event_type", ""),
                    "title": r.get("subject", ""),
                    "snippet": (r.get("raw_text") or "")[:300],
                    "source": r.get("session_id", ""),
                    "created_at": r.get("created_at", ""),
                })
            return results
        except Exception as exc:
            logger.debug("Events search failed: %s", exc)
            return []

    def health(self) -> bool:
        try:
            db = self._connect()
            db._conn.execute("SELECT 1 FROM ichor_events LIMIT 1")
            return True
        except Exception:
            return False


# ===================================================================
# Embedder (inline, avoids circular deps)
# ===================================================================


class _Embedder:
    """Thin embedding wrapper — OpenRouter first, Ollama fallback.

    Ollama configuration:
    - ``num_ctx=8192`` to use qwen3-embedding's full native context.
    - Configurable model via ATHENAEUM_EMBED_MODEL env var
      (default: qwen3-embedding:0.6b).
    - Instruction prefix for retrieval-optimized embeddings.
    """

    _EMBED_COUNT = 0

    def __init__(self):
        import os
        self._api_key = os.environ.get("ATHENAEUM_EMBED_API_KEY", "") or os.environ.get("OPENROUTER_API_KEY", "")
        self._model = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
        self._timeout = 30.0
        # Ollama model — configurable, defaults to qwen3-embedding:0.6b
        self._ollama_model = os.environ.get("ATHENAEUM_EMBED_MODEL", "qwen3-embedding:0.6b")

    @property
    def use_openrouter(self) -> bool:
        provider = os.environ.get("ATHENAEUM_EMBED_PROVIDER", "").lower()
        if provider == "ollama":
            return False
        return bool(self._api_key)

    def embed(self, text: str, prefix: str = "search_document: ") -> Optional[List[float]]:
        """Embed text via Ollama with retrieval-optimized instruction prefix.

        The ``prefix`` (default ``search_document: ``) improves retrieval quality
        for qwen3-embedding models. Set to ``search_query: `` for query-side
        embeddings, or empty string to disable.
        """
        import httpx

        # qwen3-embedding supports up to 8192 tokens natively.
        # Chunk at 1500 chars (~375 tok) with overlap for safety.
        CHUNK_SIZE = 1500
        CHUNK_OVERLAP = 100
        MAX_CHUNKS = 20

        def _call_api(payload: dict) -> Optional[List[float]]:
            try:
                if self.use_openrouter:
                    url = "https://openrouter.ai/api/v1/embeddings"
                    headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
                else:
                    url = "http://localhost:11434/api/embeddings"
                    headers = {"Content-Type": "application/json"}
                    # qwen3-embedding's full native context
                    payload.setdefault("options", {})["num_ctx"] = 8192

                resp = httpx.post(url, headers=headers, json=payload, timeout=self._timeout)
                resp.raise_for_status()
                if self.use_openrouter:
                    return resp.json()["data"][0]["embedding"]
                return resp.json()["embedding"]
            except Exception:
                return None

        if len(text) <= CHUNK_SIZE:
            # Short enough to embed directly
            if self.use_openrouter:
                return _call_api({"model": self._model, "input": text})
            return _call_api({"model": self._ollama_model, "prompt": prefix + text})

        # Chunk long texts and average embeddings
        chunks = []
        start = 0
        while start < len(text) and len(chunks) < MAX_CHUNKS:
            end = min(start + CHUNK_SIZE, len(text))
            # Try to break at a sentence boundary
            if end < len(text):
                # Look for sentence end within overlap region
                cut = text.rfind(". ", start + CHUNK_SIZE - 200, end)
                if cut > start + CHUNK_SIZE // 2:
                    end = cut + 1
            chunks.append(text[start:end])
            start = end - CHUNK_OVERLAP if end < len(text) else end

        vectors = []
        for chunk in chunks:
            if self.use_openrouter:
                v = _call_api({"model": self._model, "input": chunk})
            else:
                v = _call_api({"model": self._ollama_model, "prompt": prefix + chunk})
            if v:
                vectors.append(v)

        if not vectors:
            return None

        # Average all chunk embeddings
        dim = len(vectors[0])
        avg = [0.0] * dim
        for v in vectors:
            for i in range(dim):
                avg[i] += v[i]
        return [x / len(vectors) for x in avg]

    def is_available(self) -> bool:
        if self.use_openrouter:
            return True
        try:
            import httpx
            resp = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        # Ollama might be wedged — try restarting once before giving up
        try:
            import subprocess, time
            logger = logging.getLogger("ichor_hybrid")
            logger.warning("Ollama not responding — attempting restart...")
            subprocess.run(["systemctl", "--user", "restart", "ollama"], timeout=30, capture_output=True)
            time.sleep(5)
            import httpx
            for attempt in range(6):
                try:
                    resp = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
                    if resp.status_code == 200:
                        logger.info("Ollama restarted successfully")
                        return True
                except Exception:
                    pass
                time.sleep(3)
            logger.warning("Ollama restart failed: still not responding")
        except Exception as e:
            logger = logging.getLogger("ichor_hybrid")
            logger.warning("Ollama restart attempt failed: %s", e)
        return False


# ===================================================================
# Fusion Engine
# ===================================================================


def _normalize_scores(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize scores within each backend group to 0-1."""
    if not results:
        return results

    # Group by backend, find max per group
    max_per_backend: Dict[str, float] = {}
    for r in results:
        b = r.get("backend", "unknown")
        max_per_backend[b] = max(max_per_backend.get(b, 0), r.get("score", 0))

    # Normalize within each group
    for r in results:
        b_max = max_per_backend.get(r.get("backend", "unknown"), 1.0)
        if b_max > 0:
            r["score"] = round(r["score"] / b_max, 3)

    return results


def _compute_fused_score(result: Dict[str, Any]) -> float:
    """Compute fused score from backend-specific score + weight."""
    backend = result.get("backend", "unknown")
    weight = WEIGHTS.get(backend, 0.0)
    score = result.get("score", 0.0)
    return round(score * weight, 3)


# ===================================================================
# HybridScorer
# ===================================================================


class HybridScorer:
    """Fused search across all 4 backends. Gracefully degrades if a backend is down."""

    def __init__(self) -> None:
        self._fts5 = FTS5Backend()
        self._chroma = ChromaBackend()
        self._graph = GraphBackend()
        self._events = EventsBackend()
        self._backends = {
            "fts5": self._fts5,
            "chroma": self._chroma,
            "graph": self._graph,
            "events": self._events,
        }

    def retrieve(
        self,
        query: str,
        limit: int = 10,
        backends: Optional[List[str]] = None,
        min_score: float = 0.0,
    ) -> Dict[str, Any]:
        """Fused search across selected backends.

        Args:
            query: Search query.
            limit: Max results to return.
            backends: Which backends to query (default: all 4).
            min_score: Minimum fused score threshold.

        Returns:
            Dict with 'results' (sorted list), 'backends_used', 'total'.
        """
        if backends is None:
            backends = ["fts5", "chroma", "graph", "events"]

        all_results: List[Dict[str, Any]] = []
        backends_used: List[str] = []
        backend_errors: Dict[str, str] = {}

        for name in backends:
            be = self._backends.get(name)
            if be is None:
                continue
            try:
                batch = be.search(query, limit=limit)
                if batch:
                    backends_used.append(name)
                    all_results.extend(batch)
            except Exception as exc:
                backend_errors[name] = str(exc)
                logger.debug("Backend '%s' failed: %s", name, exc)

        if not all_results:
            return {
                "results": [],
                "query": query,
                "backends_used": backends_used,
                "backend_errors": backend_errors,
                "total": 0,
            }

        # Normalize scores within each backend
        all_results = _normalize_scores(all_results)

        # Compute fused scores
        for r in all_results:
            r["fused_score"] = _compute_fused_score(r)

        # Deduplicate by title + snippet similarity
        seen_titles: set = set()
        deduped: List[Dict[str, Any]] = []
        for r in sorted(all_results, key=lambda x: x["fused_score"], reverse=True):
            key = (r.get("title", "").lower()[:50], r.get("snippet", "").lower()[:80])
            if key not in seen_titles:
                seen_titles.add(key)
                deduped.append(r)

        # Sort by fused score, cap
        deduped = sorted(deduped, key=lambda x: x["fused_score"], reverse=True)

        if min_score > 0:
            deduped = [r for r in deduped if r["fused_score"] >= min_score]

        top = deduped[:limit]

        # ── Log query for forge weight tuning ────────────────────────
        try:
            entry = {
                "timestamp": time.time(),
                "query": query[:200],
                "weights": dict(WEIGHTS),
                "result_count": len(top),
                "result_ids": [r.get("id", "")[:80] for r in top[:10]],
                "backends_used": backends_used,
            }
            _RETRIEVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(_RETRIEVAL_LOG, "a") as _f:
                _f.write(json.dumps(entry) + "\n")
        except Exception:
            pass  # Non-fatal — don't break retrieval for logging

        return {
            "results": top,
            "query": query,
            "backends_used": backends_used,
            "backend_errors": backend_errors,
            "total": len(top),
            "weights": WEIGHTS,
        }

    def health_check(self) -> Dict[str, Any]:
        """Check health of all backends."""
        health: Dict[str, Any] = {}
        all_healthy = True
        for name, be in self._backends.items():
            try:
                ok = be.health()
                health[name] = {
                    "healthy": ok,
                    "label": BACKEND_NAMES.get(name, name),
                    "weight": WEIGHTS.get(name, 0),
                }
                if not ok:
                    all_healthy = False
            except Exception as exc:
                health[name] = {"healthy": False, "error": str(exc)}
                all_healthy = False

        return {
            "healthy": all_healthy,
            "backends": health,
            "total_backends": len(self._backends),
            "healthy_count": sum(1 for v in health.values() if v.get("healthy")),
        }


# ===================================================================
# Memory Trait Contract
# ===================================================================


def _background_embed(
    file_path: str, content: str, namespace: str, session_id: str = ""
) -> None:
    """Fire-and-forget: embed a single document to ChromaDB silently.

    Runs in a daemon thread — never blocks the caller.
    Only embeds the current document, not a full re-embed.
    """
    try:
        import httpx
        from pathlib import Path

        embed_url = os.environ.get(
            "ATHENAEUM_EMBED_URL",
            "http://localhost:11434/api/embeddings",
        )
        embed_model = os.environ.get(
            "ATHENAEUM_EMBED_MODEL",
            "nomic-embed-text",
        )

        # Embed via Ollama
        resp = httpx.post(
            embed_url,
            json={"model": embed_model, "prompt": content[:64000]},
            timeout=60,
        )
        resp.raise_for_status()
        embedding = resp.json()["embedding"]

        # Write to ChromaDB
        import chromadb  # noqa: PLC0415

        client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        col_name = f"pantheon_{namespace.lower().replace('-', '_')}"
        try:
            col = client.get_collection(col_name)
        except Exception:
            col = client.create_collection(col_name)

        col.upsert(
            ids=[file_path],
            embeddings=[embedding],
            documents=[content],
            metadatas=[{
                "source": file_path,
                "codex": namespace,
                "filename": Path(file_path).name,
                "session_id": session_id,
            }],
        )
    except Exception as exc:
        logger.debug("Background embed failed (non-fatal): %s", exc)


def _regenerate_context(
    source_god: str = "",
    timestamp: str = "",
    user_id: str | None = None,
) -> None:
    """Regenerate CONTEXT_{user_id}.md from DIGEST.md for prompt injection.

    Budget-aware: uses 3% of model context window for the summary.
    Fires on every digest_entry write — replaces the old 15-min cron.
    """
    try:
        user = user_id or os.environ.get("HERMES_USER_ID", "konan")
        digest_path = _HOME / "pantheon" / "shared" / "DIGEST.md"
        context_path = _HOME / "pantheon" / "shared" / f"CONTEXT_{user}.md"

        if not digest_path.exists():
            logger.debug("CONTEXT: no DIGEST.md yet")
            return

        # Parse recent digest entries (### timestamp — title format)
        text = digest_path.read_text(encoding="utf-8")
        entries = re.findall(
            r"### (\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC) — (.+?)\n"
            r"- \*\*Source:\*\* (.+?)(?: \|.*)?\n"
            r"- (.+?)(?=\n### |\n---|\Z)",
            text,
            re.DOTALL,
        )

        if not entries:
            context_path.write_text("## Recent Decisions\n\n_No recent decisions._\n")
            return

        # Sort by timestamp descending, take last 48h
        now = datetime.now(timezone.utc)
        fresh = []
        for ts, title, source, body in entries:
            try:
                entry_time = datetime.strptime(ts, "%Y-%m-%d %H:%M UTC")
                entry_time = entry_time.replace(tzinfo=timezone.utc)
                if (now - entry_time).days < 2:  # Last 48h
                    clean_body = body.strip().replace("\n", " ")
                    fresh.append((ts, title, source.strip(), clean_body))
            except ValueError:
                continue

        if not fresh:
            context_path.write_text("## Recent Decisions\n\n_No decisions in last 48h._\n")
            return

        # Budget: 3% of model context window (default 128k → ~3,800 tokens)
        budget_chars = int(128000 * 0.03 * 4)  # ~15,360 chars
        lines = ["## Recent Decisions\n"]
        used = len("".join(lines))

        for ts, title, source, body in fresh:
            est = len(body) // 4 + 40
            if used + est > budget_chars:
                break
            lines.append(f"- **{title}** — {body} _({source}, {ts[:10]})_\n")
            used += est

        context_path.write_text("".join(lines))
        logger.debug(
            "CONTEXT regenerated: %d entries, %d chars → %s",
            len(lines) - 1, used, context_path.name,
        )
    except Exception as exc:
        logger.debug("CONTEXT regeneration failed (non-fatal): %s", exc)


class MemoryTrait:
    """Unified memory interface — routes operations to the correct backend.

    Implements the OpenHuman-inspired contract:
        store(namespace, key, content, category, session_id)
        retrieve(query, limit, opts)
        forget(key)
        health_check()
    """

    def __init__(self) -> None:
        self._scorer = HybridScorer()

    def store(
        self,
        namespace: str = "default",
        key: str = "",
        content: str = "",
        category: str = "fact",
        session_id: str = "",
        god_name: str = "",
    ) -> Dict[str, Any]:
        """Store content, routing to the correct backend by category.

        Categories:
            - 'fact', 'preference', 'decision', 'commitment' → ichor_events (FTS5)
            - 'document', 'note', 'reference' → ChromaDB (via Athenaeum write)
            - 'entity', 'relationship' → Graph DB

        Args:
            namespace: Logical grouping (e.g. 'hermes', 'hephaestus').
            key: Unique identifier for the stored item.
            content: The content to store.
            category: Content category (determines backend routing).
            session_id: Source session ID.
            god_name: Name of the god storing.

        Returns:
            Dict with 'stored', 'backend', 'id'.
        """
        _ensure_imports()

        # Route by category
        if category in ("fact", "preference", "decision", "commitment", "insight", "blocker", "follow_up", "correction", "reference", "user_md_update"):
            # → ichor_events (FTS5)
            # 'user_md_update' is a forge output — agent-evaluated user profile updates
            from lib.ichor_db import IchorDB  # type: ignore[import-untyped]
            db = IchorDB(db_path=str(_ICHOR_DB))
            db.connect()
            event_id = db.insert_event(
                session_id=session_id or key,
                event_type=category,
                subject=key or content[:60],
                predicate=category,
                object=content,
                confidence=0.9 if category != "user_md_update" else 0.95,
                source="forge" if category == "user_md_update" else "manual",
                raw_text=content,
                god_name=god_name or namespace,
            )
            db.close()
            return {"stored": True, "backend": "fts5", "id": f"fts5:{event_id}", "namespace": namespace}

        elif category in ("entity", "relationship"):
            # → Graph DB
            import sqlite3
            conn = sqlite3.connect(str(_GRAPH_DB))
            now = datetime.now(timezone.utc).isoformat()
            node_id = key or f"manual:{namespace}:{hash(content) % 10**8}"
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO nodes (id, type, codex, label, metadata, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (node_id, category, namespace, key or content[:60], json.dumps({"source": "ichor_store"}), now, now),
                )
                conn.commit()
            except Exception as exc:
                logger.debug("Graph store failed: %s", exc)
            conn.close()
            return {"stored": True, "backend": "graph", "id": f"graph:{node_id}", "namespace": namespace}

        elif category == "digest_entry":
            # → Append to shared digest (forge output)
            digest_path = _HOME / "pantheon" / "shared" / "DIGEST.md"
            digest_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            safe_god = god_name or namespace or "unknown"
            entry = (
                f"\n### {timestamp} — {key}\n"
                f"- **Source:** {safe_god}"
                f"{f' | Session: `{session_id}`' if session_id else ''}\n"
                f"- {content}\n"
            )
            with open(digest_path, "a", encoding="utf-8") as f:
                f.write(entry)

            # Also regenerate CONTEXT_{user_id}.md for prompt injection
            _regenerate_context(safe_god, timestamp)

            return {"stored": True, "backend": "digest", "id": f"digest:{timestamp}", "namespace": namespace}

        else:
            # → Write to Athenaeum + background embed
            athenaeum_path = _ensure_imports()
            notes_dir = _HOME / "athenaeum" / "Codex-Pantheon" / "ichor-notes"
            notes_dir.mkdir(parents=True, exist_ok=True)
            note_path = notes_dir / f"{namespace}--{key.replace('/', '--')}.md"
            note_path.write_text(
                f"---\nnamespace: {namespace}\nkey: {key}\ncategory: {category}\n"
                f"stored_at: {datetime.now(timezone.utc).isoformat()}\n"
                f"session_id: {session_id}\n---\n\n{content}\n",
                encoding="utf-8",
            )
            # Fire-and-forget: embed this single document silently in background
            import threading
            threading.Thread(
                target=_background_embed,
                args=(str(note_path), content, namespace, session_id),
                daemon=True,
            ).start()
            return {"stored": True, "backend": "athenaeum", "id": str(note_path.relative_to(_HOME)), "namespace": namespace}

    def retrieve(
        self,
        query: str,
        limit: int = 10,
        backends: Optional[List[str]] = None,
        min_score: float = 0.0,
        output_format: str = "json",
    ) -> Any:
        """Unified retrieval across all backends (delegates to HybridScorer).

        Args:
            query: Search query.
            limit: Max results.
            backends: Which backends to search (default: all).
            min_score: Minimum fused score.
            output_format: 'json' or 'markdown'.

        Returns:
            JSON dict or formatted markdown string.
        """
        result = self._scorer.retrieve(
            query=query,
            limit=limit,
            backends=backends,
            min_score=min_score,
        )

        if output_format == "json":
            return result

        # Markdown
        if not result["results"]:
            return f"🔍 No results for `{query}` across any backend."

        lines = [f"## 🔍 Hybrid Search: `{query}`", ""]

        for r in result["results"]:
            backend_name = BACKEND_NAMES.get(r.get("backend", ""), r.get("backend", ""))
            fused = r.get("fused_score", r.get("score", 0))
            icon_map = {"blocker": "🚧", "commitment": "📋", "decision": "🎯",
                        "follow_up": "🔁", "insight": "💡", "document": "📄",
                        "entity": "🔗", "correction": "🔧", "fact": "📌"}
            icon = icon_map.get(r.get("type", ""), "•")
            lines.append(f"**{r.get('title', '?')}** {icon}")
            lines.append(f"  `{backend_name}` · fused: {fused:.2f} · type: {r.get('type', '?')}")
            if r.get("snippet"):
                lines.append(f"  > {r['snippet']}")
            lines.append("")

        lines.append(f"---")
        lines.append(f"_Backends: {', '.join(result['backends_used'])} · {result['total']} results_")
        return "\n".join(lines)

    def forget(self, key: str) -> Dict[str, Any]:
        """Delete from all backends by key prefix (e.g. 'fts5:42', 'graph:node:...')."""
        deleted = []
        prefix, _, rest = key.partition(":")

        if prefix == "fts5" and rest:
            try:
                _ensure_imports()
                from lib.ichor_db import IchorDB
                db = IchorDB(db_path=str(_ICHOR_DB))
                db.connect()
                db._conn.execute("DELETE FROM ichor_events WHERE id = ?", (int(rest),))
                db._conn.commit()
                db.close()
                deleted.append("fts5")
            except Exception as exc:
                logger.debug("forget fts5 failed: %s", exc)

        elif prefix == "graph" and rest:
            try:
                import sqlite3
                conn = sqlite3.connect(str(_GRAPH_DB))
                conn.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (rest, rest))
                conn.execute("DELETE FROM nodes WHERE id = ?", (rest,))
                conn.commit()
                conn.close()
                deleted.append("graph")
            except Exception as exc:
                logger.debug("forget graph failed: %s", exc)

        elif prefix == "chroma" and rest:
            logger.debug("ChromaDB forget not yet implemented for single documents")

        return {"forgotten": True, "key": key, "deleted_from": deleted}

    def health_check(self) -> Dict[str, Any]:
        """Health check for all backends."""
        return self._scorer.health_check()


# ===================================================================
# Quick summary formatter (for CLI/AI consumption)
# ===================================================================


def format_health_summary(health: Dict[str, Any]) -> str:
    """Format health check as a scannable string."""
    lines = [f"## 🏥 Ichor Memory Health"]
    lines.append(f"_{health['healthy_count']}/{health['total_backends']} backends healthy_\n")

    for name, info in health.get("backends", {}).items():
        status = "✅" if info.get("healthy") else "❌"
        label = info.get("label", name)
        weight = info.get("weight", 0)
        err = f" — {info.get('error', '')}" if info.get("error") else ""
        lines.append(f"{status} **{label}** (weight: {weight:.0%}){err}")

    return "\n".join(lines)


# ===================================================================
# CLI entry point
# ===================================================================


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Ichor Hybrid Scorer + Memory Trait Contract"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Retrieve
    p_ret = sub.add_parser("retrieve", help="Fused search across backends")
    p_ret.add_argument("query", help="Search query")
    p_ret.add_argument("--limit", "-l", type=int, default=10)
    p_ret.add_argument("--backends", "-b", nargs="+",
                       choices=["fts5", "chroma", "graph", "events"],
                       default=["fts5", "chroma", "graph", "events"])
    p_ret.add_argument("--min-score", "-m", type=float, default=0.0)
    p_ret.add_argument("--markdown", "-d", action="store_true", help="Output markdown instead of JSON")

    # Store
    p_st = sub.add_parser("store", help="Store content")
    p_st.add_argument("--key", "-k", required=True)
    p_st.add_argument("--content", "-c", required=True)
    p_st.add_argument("--namespace", "-n", default="default")
    p_st.add_argument("--category", "-t", default="fact",
                      choices=["fact", "preference", "decision", "commitment",
                               "insight", "blocker", "follow_up", "document", "entity"])
    p_st.add_argument("--session-id", "-s", default="")
    p_st.add_argument("--god-name", "-g", default="")

    # Health
    sub.add_parser("health", help="Check backend health")

    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    trait = MemoryTrait()

    if args.command == "retrieve":
        result = trait.retrieve(
            query=args.query,
            limit=args.limit,
            backends=args.backends,
            min_score=args.min_score,
            output_format="markdown" if args.markdown else "json",
        )
        if args.markdown:
            print(result)
        else:
            print(json.dumps(result, indent=2, default=str))

    elif args.command == "store":
        result = trait.store(
            namespace=args.namespace,
            key=args.key,
            content=args.content,
            category=args.category,
            session_id=args.session_id,
            god_name=args.god_name,
        )
        print(json.dumps(result, indent=2))

    elif args.command == "health":
        health = trait.health_check()
        print(json.dumps(health, indent=2))
        print()
        print(format_health_summary(health))


if __name__ == "__main__":
    main()
