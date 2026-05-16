"""
Mnemosyne client — semantic search over the Athenaeum via ChromaDB.

Connection is lazy: ChromaDB is not contacted until the first operation.
All ChromaError exceptions are caught and re-raised as MnemosyneUnavailableError
so callers can handle an offline vector store gracefully.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .exceptions import MnemosyneUnavailableError

_COLLECTION_PREFIX = "pantheon"

_HIGH_IMPORTANCE_TERMS = (
    "preference", "prefers", "correction", "remember", "decision",
    "critical", "security", "credential", "secret", "api key", "auth",
    "production", "deploy", "architecture", "hard rule", "never",
)
_MEDIUM_IMPORTANCE_TERMS = (
    "project", "workflow", "config", "setup", "bug", "fix", "test",
    "integration", "cron", "service", "gateway", "memory",
)


def score_memory_importance(text: str, metadata: dict[str, Any] | None = None) -> float:
    """Return a Mem0-style priority score for Athenaeum vector metadata.

    The score is deterministic and dependency-free. It gives retrieval/reranking
    layers a stable signal without requiring Mem0 itself. Values are normalized
    to ``0.0``–``1.0`` where higher means the document is more likely to contain
    durable facts, decisions, preferences, or operational hazards.
    """
    metadata = metadata or {}
    lowered = text.lower()
    score = 0.30

    priority = str(metadata.get("priority", "")).lower()
    if "high" in priority:
        score += 0.30
    elif "medium" in priority:
        score += 0.15
    elif "low" in priority:
        score -= 0.05

    if "priority:** high" in lowered or "priority: high" in lowered:
        score += 0.30
    elif "priority:** medium" in lowered or "priority: medium" in lowered:
        score += 0.15
    elif "priority:** low" in lowered or "priority: low" in lowered:
        score -= 0.05

    high_hits = sum(1 for term in _HIGH_IMPORTANCE_TERMS if term in lowered)
    medium_hits = sum(1 for term in _MEDIUM_IMPORTANCE_TERMS if term in lowered)
    score += min(high_hits, 4) * 0.08
    score += min(medium_hits, 4) * 0.035

    if text.startswith("#") or "\n## " in text:
        score += 0.05
    if len(text) > 2000:
        score += 0.05

    return round(max(0.0, min(1.0, score)), 3)


def partition_for(codex: str) -> str:
    """Return the ChromaDB collection name for a given Codex partition tag.

    Examples:
        partition_for("Codex-SKC")   -> "pantheon_codex_skc"
        partition_for("Codex-Forge") -> "pantheon_codex_forge"
    """
    slug = codex.lower().replace("-", "_").replace(" ", "_")
    return f"{_COLLECTION_PREFIX}_{slug}"


class MnemosyneClient:
    """Client for Mnemosyne — the Athenaeum semantic-search interface.

    Parameters
    ----------
    scope:
        ``"all"`` to search across every partition, or a list of Codex
        partition tags (e.g. ``["Codex-SKC", "Codex-Forge"]``) to restrict
        queries to those collections only.
    """

    def __init__(self, scope: str | list[str] = "all") -> None:
        if isinstance(scope, str) and scope != "all":
            raise ValueError(
                "scope must be the string 'all' or a list of Codex partition names."
            )
        self.scope = scope
        self._host: str = os.environ.get("CHROMA_HOST", "localhost")
        self._port: int = int(os.environ.get("CHROMA_PORT", "8000"))
        self._embed_model: str = os.environ.get(
            "ATHENAEUM_EMBED_MODEL",
            "nvidia/llama-nemotron-embed-vl-1b-v2:free",
        )
        self._embed_url: str = os.environ.get(
            "ATHENAEUM_EMBED_URL",
            "https://openrouter.ai/api/v1/embeddings",
        )
        self._embed_api_key: str = (
            os.environ.get("ATHENAEUM_EMBED_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or ""
        )
        # Lazy — initialised on first use.
        self._client: Any = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> Any:
        """Return (and cache) a chromadb.HttpClient, raising MnemosyneUnavailableError on failure."""
        if self._client is not None:
            return self._client
        try:
            import chromadb  # noqa: PLC0415
            import chromadb.errors  # noqa: PLC0415

            client = chromadb.HttpClient(host=self._host, port=self._port)
            # Trigger an actual network call so we discover failure early.
            client.heartbeat()
            self._client = client
            return self._client
        except Exception as exc:  # covers chromadb.errors.ChromaError + connection errors
            raise MnemosyneUnavailableError(
                f"ChromaDB unreachable at {self._host}:{self._port}: {exc}"
            ) from exc

    def _get_embedding(self, text: str) -> list[float]:
        """Obtain an embedding for *text* via the configured embedder."""
        try:
            import httpx  # noqa: PLC0415

            provider = os.environ.get("ATHENAEUM_EMBED_PROVIDER", "").lower()

            if provider == "ollama":
                # Ollama uses /api/embeddings with {model, prompt} format
                response = httpx.post(
                    self._embed_url,
                    json={"model": self._embed_model, "prompt": text},
                    timeout=30.0,
                )
                response.raise_for_status()
                return response.json()["embedding"]
            else:
                # OpenAI-compatible format (OpenRouter, Jina, Voyage, etc.)
                response = httpx.post(
                    self._embed_url,
                    headers={
                        "Authorization": f"Bearer {self._embed_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": self._embed_model, "input": text},
                    timeout=30.0,
                )
                response.raise_for_status()
                return response.json()["data"][0]["embedding"]

        except Exception as exc:
            raise MnemosyneUnavailableError(
                f"Embedding request failed: {exc}"
            ) from exc

    def _scoped_collections(self) -> list[str]:
        """Return collection names that are in scope."""
        client = self._connect()
        try:
            all_collections = [c.name for c in client.list_collections()]
        except Exception as exc:
            raise MnemosyneUnavailableError(
                f"Failed to list ChromaDB collections: {exc}"
            ) from exc

        if self.scope == "all":
            return all_collections

        wanted = {partition_for(codex) for codex in self.scope}
        return [name for name in all_collections if name in wanted]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(self, text: str, n_results: int = 5) -> list[dict]:
        """Semantic search within scoped partitions.

        Returns a list of dicts with keys ``content``, ``source``, and ``codex``.
        """
        client = self._connect()
        embedding = self._get_embedding(text)
        collection_names = self._scoped_collections()

        results: list[dict] = []
        for name in collection_names:
            try:
                collection = client.get_collection(name)
                raw = collection.query(
                    query_embeddings=[embedding],
                    n_results=min(n_results, collection.count() or n_results),
                    include=["documents", "metadatas"],
                )
            except Exception as exc:
                raise MnemosyneUnavailableError(
                    f"Query against collection '{name}' failed: {exc}"
                ) from exc

            documents = raw.get("documents", [[]])[0]
            metadatas = raw.get("metadatas", [[]])[0]
            for doc, meta in zip(documents, metadatas):
                item = {
                    "content": doc,
                    "source": meta.get("source", ""),
                    "codex": meta.get("codex", name),
                }
                if "priority_score" in meta:
                    item["priority_score"] = meta.get("priority_score")
                results.append(item)

        # Sort by relevance order (ChromaDB returns nearest-first per collection).
        return results[:n_results]

    def embed_file(self, path: str, codex: str) -> None:
        """Embed the contents of *path* into the ChromaDB collection for *codex*.

        The file is read as UTF-8 text.  Existing documents with the same
        ``source`` path are replaced (upserted) so re-running is idempotent.
        """
        client = self._connect()
        collection_name = partition_for(codex)

        try:
            collection = client.get_or_create_collection(collection_name)
        except Exception as exc:
            raise MnemosyneUnavailableError(
                f"Could not get/create collection '{collection_name}': {exc}"
            ) from exc

        file_path = Path(path)
        content = file_path.read_text(encoding="utf-8")
        embedding = self._get_embedding(content)
        doc_id = str(file_path.resolve())

        try:
            metadata = {
                "source": str(file_path),
                "codex": codex,
                "priority_score": score_memory_importance(content, {"codex": codex}),
            }
            collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[metadata],
            )
        except Exception as exc:
            raise MnemosyneUnavailableError(
                f"Upsert into collection '{collection_name}' failed: {exc}"
            ) from exc
