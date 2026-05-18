"""Athenaeum API — codex tree browsing, file reading, semantic search.

Wraps the Athenaeum filesystem + ChromaDB into endpoints the Web UI can call.
Direct filesystem access (no MCP dependency)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

_REAL_HOME = os.path.expanduser("~konan")
_ATHENAEUM_ROOT = Path(f"{_REAL_HOME}/athenaeum")
_CHROMA_DIR = Path(f"{_REAL_HOME}/.hermes/pantheon/chroma")
_EMBEDDABLE_EXTS = {".md", ".txt", ".json", ".yaml", ".yml"}


# ── Codex Listing ──────────────────────────────────────────────────────────

def list_codexes(details: bool = False) -> dict:
    """List all Codex directories in the Athenaeum."""
    if not _ATHENAEUM_ROOT.is_dir():
        return {"codexes": [], "error": "Athenaeum not found"}

    codexes = sorted(
        d.name for d in _ATHENAEUM_ROOT.iterdir()
        if d.is_dir() and d.name.startswith("Codex-")
    )

    if not details:
        return {"codexes": codexes}

    result = []
    for c in codexes:
        codex_dir = _ATHENAEUM_ROOT / c
        file_count = sum(
            1 for f in codex_dir.rglob("*")
            if f.is_file() and f.suffix.lower() in _EMBEDDABLE_EXTS and f.name != "INDEX.md"
        )
        result.append({"name": c, "file_count": file_count})

    return {"codexes": result, "total": len(result)}


# ── Walk (browse directory) ────────────────────────────────────────────────

def walk(path: str = "INDEX.md") -> dict:
    """Walk an INDEX.md to list files and subdirectories."""
    sanitized = path.lstrip("/").replace("..", "")
    full_path = (_ATHENAEUM_ROOT / sanitized).resolve()

    try:
        full_path.relative_to(_ATHENAEUM_ROOT.resolve())
    except ValueError:
        return {"error": "Path must be within the Athenaeum"}

    browse_dir = full_path.parent if full_path.suffix else full_path

    if not browse_dir.is_dir():
        try:
            rel = browse_dir.relative_to(_ATHENAEUM_ROOT)
        except ValueError:
            rel = browse_dir.name
        return {"error": f"Directory not found: {rel}"}

    # Read INDEX.md if it exists
    index_path = browse_dir / "INDEX.md"
    index_content = ""
    if index_path.exists():
        try:
            index_content = index_path.read_text(encoding="utf-8")[:3000]
        except Exception:
            pass

    # List children
    subdirs: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    try:
        for child in sorted(browse_dir.iterdir()):
            if child.name.startswith("."):
                continue
            try:
                rel = child.relative_to(_ATHENAEUM_ROOT).as_posix()
            except ValueError:
                continue
            modified = datetime.fromtimestamp(
                child.stat().st_mtime, tz=timezone.utc
            ).isoformat()[:10]
            size_kb = child.stat().st_size / 1024

            if child.is_dir():
                subdirs.append({
                    "name": child.name,
                    "path": rel,
                    "last_modified": modified,
                })
            elif child.is_file():
                files.append({
                    "name": child.name,
                    "path": rel,
                    "size_kb": round(size_kb, 1),
                    "last_modified": modified,
                })
    except Exception as exc:
        return {"error": f"Failed to list directory: {exc}"}

    try:
        dir_rel = browse_dir.relative_to(_ATHENAEUM_ROOT).as_posix()
    except ValueError:
        dir_rel = browse_dir.name

    return {
        "directory": dir_rel,
        "index_content": index_content or "(no INDEX.md found)",
        "subdirectories": subdirs,
        "files": files,
    }


# ── Read ───────────────────────────────────────────────────────────────────

def read(path: str) -> dict:
    """Read a file from the Athenaeum, return content with metadata."""
    sanitized = path.lstrip("/").replace("..", "")
    full_path = (_ATHENAEUM_ROOT / sanitized).resolve()

    try:
        full_path.relative_to(_ATHENAEUM_ROOT.resolve())
    except ValueError:
        return {"error": "Path must be within the Athenaeum"}

    if not full_path.exists():
        return {"error": f"File not found: {path}"}

    if full_path.is_dir():
        return {"error": f"Path is a directory: {path}"}

    try:
        content = full_path.read_text(encoding="utf-8")
        lines = content.split("\n")
        return {
            "path": path,
            "total_lines": len(lines),
            "content": content,
            "size_kb": round(full_path.stat().st_size / 1024, 1),
            "last_modified": datetime.fromtimestamp(
                full_path.stat().st_mtime, tz=timezone.utc
            ).isoformat()[:10],
        }
    except Exception as exc:
        return {"error": f"Failed to read {path}: {exc}"}


# ── Semantic Search ────────────────────────────────────────────────────────

class _Embedder:
    """Thin embedding wrapper — OpenRouter first, Ollama fallback."""

    def __init__(self):
        self._api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self._model = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
        self._timeout = 30.0

    @property
    def is_available(self) -> bool:
        return bool(self._api_key) or self._ollama_available()

    def _ollama_available(self) -> bool:
        try:
            import httpx
            resp = httpx.get("http://localhost:11434/api/tags", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def embed(self, text: str) -> list[float]:
        import httpx

        if self._api_key:
            resp = httpx.post(
                "https://openrouter.ai/api/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self._model, "input": text},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        else:
            resp = httpx.post(
                "http://localhost:11434/api/embeddings",
                json={"model": "nomic-embed-text", "prompt": text},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return resp.json()["embedding"]


def _get_chroma_client():
    """Get a ChromaDB PersistentClient."""
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        client.heartbeat()
        return client
    except Exception as exc:
        logger.warning("ChromaDB unavailable: %s", exc)
        return None


def _partition_for(codex: str) -> str:
    slug = codex.lower().replace("-", "_").replace(" ", "_")
    return f"pantheon_{slug}"


def _codex_from_partition(collection_name: str) -> str:
    parts = collection_name.split("_", 2)
    if len(parts) < 3:
        return "Codex-General"
    raw = parts[2]
    words = raw.split("_")
    return "Codex-" + "-".join(w.capitalize() for w in words) if words else "Codex-General"


def search(query: str, codexes: Optional[list[str]] = None, n_results: int = 5) -> dict:
    """Semantic vector search via ChromaDB."""
    client = _get_chroma_client()
    if client is None:
        return {"error": "ChromaDB is not available"}

    embedder = _Embedder()
    if not embedder.is_available:
        return {"error": "No embedding service available"}

    all_codexes = sorted(
        d.name for d in _ATHENAEUM_ROOT.iterdir()
        if d.is_dir() and d.name.startswith("Codex-")
    )

    targets = [c for c in codexes if c in all_codexes] if codexes else all_codexes

    if not targets:
        return {"error": "No Codexes found in Athenaeum"}

    try:
        query_embedding = embedder.embed(query[:512])
    except Exception as exc:
        return {"error": f"Embedding failed: {exc}"}

    results: list[dict[str, Any]] = []
    for codex_name in targets:
        collection_name = _partition_for(codex_name)
        try:
            collection = client.get_collection(collection_name)
            qresults = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(n_results, 20),
            )
            ids = qresults.get("ids", [[]])[0]
            metadatas = qresults.get("metadatas", [[]])[0]
            distances = qresults.get("distances", [[]])[0]
            documents = qresults.get("documents", [[]])[0]

            for idx_id, doc_id in enumerate(ids):
                meta = metadatas[idx_id] if idx_id < len(metadatas) else {}
                dist = distances[idx_id] if idx_id < len(distances) else 0.0
                doc = documents[idx_id] if idx_id < len(documents) else ""

                score = max(0.0, 1.0 - dist) if dist else 0.0
                content_preview = doc[:2000] if doc else "(empty)"

                results.append({
                    "content": content_preview,
                    "source": meta.get("source", doc_id),
                    "codex": codex_name,
                    "score": round(score, 3),
                })
        except Exception as exc:
            logger.debug("ChromaDB query failed for %s: %s", collection_name, exc)
            continue

    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:n_results]

    return {
        "results": results,
        "total": len(results),
        "codexes_searched": len(targets),
    }


# ── Graph Search ───────────────────────────────────────────────────────────

def graph_search(query: str, mode: str = "hybrid", limit: int = 10) -> dict:
    """Search the Knowledge Graph via SQLite."""
    graph_db = Path(f"{_REAL_HOME}/.hermes/pantheon/graph.db")
    if not graph_db.exists():
        return {"error": "Graph DB not found", "results": []}

    try:
        import sqlite3
        conn = sqlite3.connect(str(graph_db))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        q = f"%{query}%"
        if mode == "nodes":
            cursor.execute(
                "SELECT id, label, name, summary, properties FROM nodes WHERE name LIKE ? OR summary LIKE ? LIMIT ?",
                (q, q, limit)
            )
        elif mode == "edges":
            cursor.execute(
                """SELECT e.id, e.type, e.source_id, e.target_id, e.properties,
                          n1.name as source_name, n1.label as source_label,
                          n2.name as target_name, n2.label as target_label
                   FROM edges e
                   JOIN nodes n1 ON e.source_id = n1.id
                   JOIN nodes n2 ON e.target_id = n2.id
                   WHERE e.type LIKE ? OR n1.name LIKE ? OR n2.name LIKE ?
                   LIMIT ?""",
                (q, q, q, limit)
            )
        else:  # hybrid
            cursor.execute(
                """SELECT id, label, name, summary, 'node' as result_type FROM nodes
                   WHERE name LIKE ? OR summary LIKE ?
                   UNION ALL
                   SELECT e.id, e.type as label, e.type as name,
                          printf('%s → %s', n1.name, n2.name) as summary,
                          'edge' as result_type
                   FROM edges e
                   JOIN nodes n1 ON e.source_id = n1.id
                   JOIN nodes n2 ON e.target_id = n2.id
                   WHERE e.type LIKE ? OR n1.name LIKE ? OR n2.name LIKE ?
                   LIMIT ?""",
                (q, q, q, q, q, limit)
            )

        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return {"results": rows, "total": len(rows)}
    except Exception as exc:
        return {"error": f"Graph search failed: {exc}", "results": []}
