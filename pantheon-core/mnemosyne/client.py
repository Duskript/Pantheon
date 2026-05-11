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
        self._embed_api_key: str = os.environ.get("OPENROUTER_API_KEY", "")
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
        """Obtain an embedding for *text* via OpenRouter."""
        try:
            import httpx  # noqa: PLC0415

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
                f"OpenRouter embedding request failed: {exc}"
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
                results.append(
                    {
                        "content": doc,
                        "source": meta.get("source", ""),
                        "codex": meta.get("codex", name),
                    }
                )

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
            collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[{"source": str(file_path), "codex": codex}],
            )
        except Exception as exc:
            raise MnemosyneUnavailableError(
                f"Upsert into collection '{collection_name}' failed: {exc}"
            ) from exc
