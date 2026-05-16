"""
Tests for the Mnemosyne client.

All ChromaDB and httpx calls are mocked — no real services are required.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: build a minimal chromadb stub so the module can be imported
# without the real package being installed.
# ---------------------------------------------------------------------------

def _make_chromadb_stub() -> ModuleType:
    """Return a fake `chromadb` module with enough surface area for the client."""
    chroma = ModuleType("chromadb")
    errors = ModuleType("chromadb.errors")

    class ChromaError(Exception):
        pass

    errors.ChromaError = ChromaError
    chroma.errors = errors

    # Default HttpClient factory — tests override this per-case.
    chroma.HttpClient = MagicMock()

    sys.modules.setdefault("chromadb", chroma)
    sys.modules.setdefault("chromadb.errors", errors)
    return chroma


_chromadb_stub = _make_chromadb_stub()

# Import after the stub is injected.
from mnemosyne.client import MnemosyneClient, partition_for, score_memory_importance  # noqa: E402
from mnemosyne.exceptions import MnemosyneUnavailableError  # noqa: E402


# ---------------------------------------------------------------------------
# partition_for
# ---------------------------------------------------------------------------

class TestPartitionFor:
    def test_standard_codex_skc(self) -> None:
        assert partition_for("Codex-SKC") == "pantheon_codex_skc"

    def test_standard_codex_forge(self) -> None:
        assert partition_for("Codex-Forge") == "pantheon_codex_forge"

    def test_returns_string(self) -> None:
        result = partition_for("Codex-X")
        assert isinstance(result, str)

    def test_prefixed_with_pantheon(self) -> None:
        result = partition_for("Codex-SKC")
        assert result.startswith("pantheon_")


# ---------------------------------------------------------------------------
# MnemosyneClient construction
# ---------------------------------------------------------------------------

class TestClientConstruction:
    def test_scope_all_does_not_connect(self) -> None:
        """Constructing with scope='all' must NOT contact ChromaDB."""
        mock_http = MagicMock()
        with patch.object(_chromadb_stub, "HttpClient", return_value=mock_http):
            client = MnemosyneClient(scope="all")
        mock_http.heartbeat.assert_not_called()

    def test_scope_list_does_not_connect(self) -> None:
        mock_http = MagicMock()
        with patch.object(_chromadb_stub, "HttpClient", return_value=mock_http):
            client = MnemosyneClient(scope=["Codex-SKC"])
        mock_http.heartbeat.assert_not_called()

    def test_invalid_scope_string_raises(self) -> None:
        with pytest.raises(ValueError):
            MnemosyneClient(scope="Codex-SKC")  # bare string that isn't "all"

    def test_scope_stored(self) -> None:
        client = MnemosyneClient(scope=["Codex-SKC", "Codex-Forge"])
        assert client.scope == ["Codex-SKC", "Codex-Forge"]


# ---------------------------------------------------------------------------
# query — happy path
# ---------------------------------------------------------------------------

class TestQuery:
    def _make_mock_client(self, collection_name: str, docs: list[str], metas: list[dict]):
        """Return a mock ChromaDB HttpClient configured with one collection."""
        collection = MagicMock()
        collection.name = collection_name
        collection.count.return_value = len(docs)
        collection.query.return_value = {
            "documents": [docs],
            "metadatas": [metas],
        }

        mock_client = MagicMock()
        mock_client.heartbeat.return_value = True
        mock_client.list_collections.return_value = [collection]
        mock_client.get_collection.return_value = collection
        return mock_client

    def _patch_embedding(self, embedding: list[float]):
        """Patch _get_embedding to return a fixed vector."""
        return patch.object(MnemosyneClient, "_get_embedding", return_value=embedding)

    def test_returns_list_of_dicts(self) -> None:
        mock_chroma = self._make_mock_client(
            "pantheon_codex_skc",
            ["Hello Pantheon"],
            [{"source": "/athenaeum/hello.md", "codex": "Codex-SKC"}],
        )
        with patch.object(_chromadb_stub, "HttpClient", return_value=mock_chroma):
            with self._patch_embedding([0.1, 0.2, 0.3]):
                client = MnemosyneClient(scope="all")
                results = client.query("hello", n_results=5)

        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0]["content"] == "Hello Pantheon"
        assert results[0]["source"] == "/athenaeum/hello.md"
        assert results[0]["codex"] == "Codex-SKC"

    def test_result_keys_present(self) -> None:
        mock_chroma = self._make_mock_client(
            "pantheon_codex_forge",
            ["Forge doc"],
            [{"source": "/athenaeum/forge.md", "codex": "Codex-Forge"}],
        )
        with patch.object(_chromadb_stub, "HttpClient", return_value=mock_chroma):
            with self._patch_embedding([0.0]):
                client = MnemosyneClient(scope="all")
                results = client.query("forge")

        for item in results:
            assert "content" in item
            assert "source" in item
            assert "codex" in item

    def test_scoped_query_uses_only_scoped_collections(self) -> None:
        """When scope=['Codex-SKC'], only the pantheon_codex_skc collection is queried."""
        skc_collection = MagicMock()
        skc_collection.name = "pantheon_codex_skc"
        skc_collection.count.return_value = 1
        skc_collection.query.return_value = {
            "documents": [["SKC result"]],
            "metadatas": [[{"source": "/s", "codex": "Codex-SKC"}]],
        }

        other_collection = MagicMock()
        other_collection.name = "pantheon_codex_forge"

        mock_chroma = MagicMock()
        mock_chroma.heartbeat.return_value = True
        mock_chroma.list_collections.return_value = [skc_collection, other_collection]
        mock_chroma.get_collection.return_value = skc_collection

        with patch.object(_chromadb_stub, "HttpClient", return_value=mock_chroma):
            with self._patch_embedding([0.0]):
                client = MnemosyneClient(scope=["Codex-SKC"])
                results = client.query("search")

        skc_collection.query.assert_called_once()
        other_collection.query.assert_not_called()
        assert results[0]["codex"] == "Codex-SKC"


# ---------------------------------------------------------------------------
# Unavailability handling
# ---------------------------------------------------------------------------

class TestUnavailability:
    def test_chromadb_connection_error_raises_mnemosyne_unavailable(self) -> None:
        mock_chroma = MagicMock()
        mock_chroma.heartbeat.side_effect = Exception("connection refused")

        with patch.object(_chromadb_stub, "HttpClient", return_value=mock_chroma):
            client = MnemosyneClient(scope="all")
            with pytest.raises(MnemosyneUnavailableError):
                client.query("anything")

    def test_chromadb_query_error_raises_mnemosyne_unavailable(self) -> None:
        collection = MagicMock()
        collection.name = "pantheon_codex_skc"
        collection.count.return_value = 1
        collection.query.side_effect = Exception("chroma internal error")

        mock_chroma = MagicMock()
        mock_chroma.heartbeat.return_value = True
        mock_chroma.list_collections.return_value = [collection]
        mock_chroma.get_collection.return_value = collection

        with patch.object(_chromadb_stub, "HttpClient", return_value=mock_chroma):
            with patch.object(MnemosyneClient, "_get_embedding", return_value=[0.0]):
                client = MnemosyneClient(scope="all")
                with pytest.raises(MnemosyneUnavailableError):
                    client.query("fail")

    def test_ollama_unavailable_raises_mnemosyne_unavailable(self) -> None:
        """Embedding failure (Ollama down) also surfaces as MnemosyneUnavailableError."""
        mock_chroma = MagicMock()
        mock_chroma.heartbeat.return_value = True
        mock_chroma.list_collections.return_value = []

        httpx_stub = ModuleType("httpx")

        class ConnectError(Exception):
            pass

        httpx_stub.ConnectError = ConnectError
        httpx_stub.post = MagicMock(side_effect=ConnectError("ollama down"))

        with patch.dict(sys.modules, {"httpx": httpx_stub}):
            with patch.object(_chromadb_stub, "HttpClient", return_value=mock_chroma):
                client = MnemosyneClient(scope="all")
                with pytest.raises(MnemosyneUnavailableError):
                    client.query("embed this")


# ---------------------------------------------------------------------------
# Mem0-style priority scoring
# ---------------------------------------------------------------------------

class TestPriorityScoring:
    def test_high_priority_operational_memory_scores_higher(self) -> None:
        high = score_memory_importance(
            "- **Priority:** HIGH\nHard rule: never commit secrets or API keys."
        )
        low = score_memory_importance("A casual note about lunch.")
        assert high > low
        assert 0.0 <= low <= 1.0
        assert 0.0 <= high <= 1.0

    def test_query_returns_priority_score_when_metadata_has_it(self) -> None:
        collection = MagicMock()
        collection.name = "pantheon_codex_skc"
        collection.count.return_value = 1
        collection.query.return_value = {
            "documents": [["Important doc"]],
            "metadatas": [[{"source": "/s", "codex": "Codex-SKC", "priority_score": 0.88}]],
        }
        mock_chroma = MagicMock()
        mock_chroma.heartbeat.return_value = True
        mock_chroma.list_collections.return_value = [collection]
        mock_chroma.get_collection.return_value = collection
        with patch.object(_chromadb_stub, "HttpClient", return_value=mock_chroma):
            with patch.object(MnemosyneClient, "_get_embedding", return_value=[0.0]):
                client = MnemosyneClient(scope="all")
                results = client.query("important")

        assert results[0]["priority_score"] == 0.88

    def test_embed_file_stores_priority_score_metadata(self, tmp_path) -> None:
        file_path = tmp_path / "memory.md"
        file_path.write_text("- **Priority:** HIGH\nDecision: Pantheon should avoid credential leaks.", encoding="utf-8")

        collection = MagicMock()
        mock_chroma = MagicMock()
        mock_chroma.heartbeat.return_value = True
        mock_chroma.get_or_create_collection.return_value = collection

        with patch.object(_chromadb_stub, "HttpClient", return_value=mock_chroma):
            with patch.object(MnemosyneClient, "_get_embedding", return_value=[0.1]):
                client = MnemosyneClient(scope="all")
                client.embed_file(str(file_path), "Codex-Pantheon")

        metadata = collection.upsert.call_args.kwargs["metadatas"][0]
        assert metadata["source"] == str(file_path)
        assert metadata["codex"] == "Codex-Pantheon"
        assert metadata["priority_score"] > 0.5
