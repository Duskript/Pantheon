"""Pantheon Athenaeum memory provider for Hermes Agent.

Provides persistent, Codex-partitioned memory via an embedded ChromaDB vector
store (Mnemosyne) backed by files in the Athenaeum filesystem (~/athenaeum/).

Architecture:
  Athenaeum (~/athenaeum/) — canonical, human-readable markdown knowledge store.
    ├── INDEX.md — root navigation, lists every Codex
    ├── Codex-*/ — domain-partitioned folders with subfolder indexes
    │   ├── INDEX.md — Codex-level index
    │   ├── subfolder/files — actual content
    │   ├── distilled/ — Hades-consolidated canonical knowledge
    │   └── archive/ — archived/superseded content (unindexed)
    └── handoffs/ — cross-session continuity notes

  Mnemosyne — embedded ChromaDB (PersistentClient) storing semantic embeddings
    of Athenaeum content. Codex-scoped by collection. Rebuilt if corrupted.

  Vault — real-time session logging to the Athenaeum. Each turn is written
    immediately to avoid data loss.

Lifecycle:
  initialize() — connect to ChromaDB, set up paths, warm embeddings
  prefetch() — semantic recall before each turn (background thread)
  sync_turn() — write user+assistant turn to vault immediately
  system_prompt_block() — Athenaeum navigation instructions
  on_session_end() — end-of-session metadata write
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_ATHENAEUM_ROOT = "/home/konan/athenaeum"
_DEFAULT_CHROMA_DIR = "/home/konan/.hermes/pantheon/chroma"
_DEFAULT_VAULT_CODEX = "Codex-Forge"  # where Hermes sessions log by default
_DEFAULT_EMBED_MODEL = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
_DEFAULT_OLLAMA_HOST = "http://localhost:11434"
_DEFAULT_EMBED_TIMEOUT = 30.0
_DEFAULT_OPENROUTER_HOST = "https://openrouter.ai"
_DEFAULT_PREFETCH_RESULTS = 5
_DEFAULT_VAULT_SESSIONS_DIR = "sessions"

# File extensions to consider for embedding
_EMBEDDABLE_EXTS = {".md", ".txt", ".json", ".yaml", ".yml"}

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _default_config() -> dict:
    return {
        "athenaeum_root": _DEFAULT_ATHENAEUM_ROOT,
        "chroma_dir": _DEFAULT_CHROMA_DIR,
        "vault_codex": _DEFAULT_VAULT_CODEX,
        "embed_model": _DEFAULT_EMBED_MODEL,
        "ollama_host": _DEFAULT_OLLAMA_HOST,
        "embed_timeout": _DEFAULT_EMBED_TIMEOUT,
        "prefetch_results": _DEFAULT_PREFETCH_RESULTS,
        "vault_sessions_dir": _DEFAULT_VAULT_SESSIONS_DIR,
    }


def _load_config(hermes_home: str) -> dict:
    config = _default_config()
    config_path = Path(hermes_home) / "pantheon.json"
    if config_path.exists():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                config.update({k: v for k, v in raw.items() if v is not None})
        except Exception:
            logger.debug("Failed to parse %s", config_path, exc_info=True)

    # Expand paths — use defaults directly if expansion fails
    for key in ("athenaeum_root", "chroma_dir"):
        raw = config.get(key, "")
        if raw:
            try:
                p = Path(raw)
                if "~" in raw:
                    # Manual ~ expansion using konan's actual home
                    p = Path("/home/konan") / raw.lstrip("~/")
                config[key] = str(p.resolve())
            except Exception:
                pass

    return config


def _save_config(values: dict, hermes_home: str) -> None:
    config_path = Path(hermes_home) / "pantheon.json"
    existing = {}
    if config_path.exists():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                existing = raw
        except Exception:
            existing = {}
    existing.update(values)
    config_path.write_text(
        json.dumps(existing, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Codex helpers
# ---------------------------------------------------------------------------


def _partition_for(codex: str) -> str:
    """Return the ChromaDB collection name for a Codex tag.

    Examples:
        _partition_for("Codex-SKC")   → "pantheon_codex_skc"
        _partition_for("Codex-Forge") → "pantheon_codex_forge"
    """
    slug = codex.lower().replace("-", "_").replace(" ", "_")
    return f"pantheon_{slug}"


def _codex_from_partition(collection_name: str) -> str:
    """Reverse of _partition_for."""
    # "pantheon_codex_skc" → "Codex-SKC"
    parts = collection_name.split("_", 2)
    if len(parts) < 3:
        return "Codex-General"
    raw = parts[2]  # "skc"
    words = raw.split("_")
    return "Codex-" + "-".join(w.capitalize() for w in words) if words else "Codex-General"


def _list_codexes(athenaeum_root: Path) -> List[str]:
    """Return list of Codex names found in the Athenaeum."""
    if not athenaeum_root.is_dir():
        return []
    return sorted(
        d.name for d in athenaeum_root.iterdir()
        if d.is_dir() and d.name.startswith("Codex-")
    )


# ---------------------------------------------------------------------------
# Embedding client
# ---------------------------------------------------------------------------


class _OllamaEmbedder:
    """Generate embeddings via Ollama's nomic-embed-text model."""

    def __init__(self, host: str, model: str, timeout: float):
        self._host = host.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._chunk_size = 512  # chars per chunk for long documents

    def embed(self, text: str) -> List[float]:
        """Return embedding vector for *text*."""
        import httpx  # noqa: PLC0415

        url = f"{self._host}/api/embeddings"
        response = httpx.post(
            url,
            json={"model": self._model, "prompt": text},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()["embedding"]

    def embed_chunks(self, text: str) -> List[Tuple[List[float], int]]:
        """Embed *text* in chunks. Returns [(embedding, char_offset), ...]."""
        chunks = []
        for i in range(0, len(text), self._chunk_size):
            chunk = text[i : i + self._chunk_size]
            chunks.append((self.embed(chunk), i))
        return chunks

    def is_available(self) -> bool:
        """Quick reachability check."""
        import httpx  # noqa: PLC0415

        try:
            resp = httpx.get(f"{self._host}/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Athenaeum file scanner
# ---------------------------------------------------------------------------


def _walk_athenaeum_files(root: Path) -> List[Tuple[str, str, str]]:
    """Yield (relative_path, full_path, codex_name) for all embeddable files.

    Skips /archive/ paths and /distilled/ paths at any depth (those are
    managed separately).
    """
    results = []
    for codex_dir in root.iterdir():
        if not codex_dir.is_dir() or not codex_dir.name.startswith("Codex-"):
            continue
        codex = codex_dir.name
        for file_path in codex_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in _EMBEDDABLE_EXTS:
                continue
            # Skip archive, distilled, handoffs
            rel = file_path.relative_to(root)
            parts = rel.parts
            if "archive" in parts or "distilled" in parts:
                continue
            # Skip INDEX.md — index is navigation, not semantic content
            if file_path.name == "INDEX.md":
                continue
            results.append((str(rel), str(file_path), codex))
    return results


# ---------------------------------------------------------------------------
# Vault writer
# ---------------------------------------------------------------------------


class _VaultWriter:
    """Real-time session turn writer to the Athenaeum.

    Writes each turn immediately. A crash loses at most one turn.
    """

    def __init__(self, vault_dir: Path, god_name: str = "Hephaestus"):
        self._vault_dir = vault_dir
        self._god_name = god_name
        self._session_file: Optional[Path] = None
        self._session_id: str = ""

    def ensure_session(self, session_id: str) -> Path:
        """Create or return the session file path."""
        if self._session_file and self._session_id == session_id:
            return self._session_file

        self._vault_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%dT%H-%M-%SZ")
        filename = f"{timestamp}--{session_id[:8]}.md"
        path = self._vault_dir / filename

        if not path.exists():
            header = (
                f"---\nsanctuary: Hermes Workflow\ngod: {self._god_name}\n"
                f"timestamp: {now.isoformat()}\nsession_id: {session_id}\n---\n\n"
            )
            path.write_text(header, encoding="utf-8")

        self._session_file = path
        self._session_id = session_id
        return path

    def write_turn(self, session_id: str, role: str, content: str) -> None:
        """Write a single turn immediately."""
        path = self.ensure_session(session_id)
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        line = f"\n[{role}] ({timestamp}):\n{content}\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)

    def close_session(self) -> None:
        """Finalize the session file."""
        if self._session_file:
            now = datetime.now(timezone.utc)
            with self._session_file.open("a", encoding="utf-8") as f:
                f.write(f"\n--- session ended: {now.isoformat()} ---\n")
            self._session_file = None
            self._session_id = ""


# ---------------------------------------------------------------------------
# The Pantheon Memory Provider
# ---------------------------------------------------------------------------


class PantheonMemoryProvider(MemoryProvider):
    """Hermes memory provider backed by the Pantheon Athenaeum + Mnemosyne."""

    def __init__(self):
        self._config = _default_config()
        self._athenaeum_root: Optional[Path] = None
        self._chroma: Any = None  # chromadb.PersistentClient
        self._embedder: Optional[_OpenRouterEmbedder] = None
        self._vault: Optional[_VaultWriter] = None
        self._hermes_home = ""
        self._session_id = ""
        self._prefetch_result = ""
        self._prefetch_lock = threading.Lock()
        self._prefetch_thread: Optional[threading.Thread] = None
        self._initialized = False
        self._chroma_available = False

    # -- Provider identity ------------------------------------------------

    @property
    def name(self) -> str:
        return "pantheon"

    # -- Availability check -----------------------------------------------

    def is_available(self) -> bool:
        """Check that the Athenaeum exists and required packages are installed."""
        athenaeum = Path(_DEFAULT_ATHENAEUM_ROOT).expanduser().resolve()
        if not athenaeum.is_dir():
            return False
        try:
            import chromadb  # noqa: PLC0415, F401
            import httpx  # noqa: PLC0415, F401

            return True
        except ImportError:
            return False

    # -- Config schema for `hermes memory setup` --------------------------

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "athenaeum_root",
                "description": "Path to the Athenaeum directory",
                "default": _DEFAULT_ATHENAEUM_ROOT,
                "required": False,
            },
            {
                "key": "chroma_dir",
                "description": "Path for embedded ChromaDB data",
                "default": _DEFAULT_CHROMA_DIR,
                "required": False,
            },
            {
                "key": "vault_codex",
                "description": "Default Codex for session vault logging",
                "default": _DEFAULT_VAULT_CODEX,
                "required": False,
            },
            {
                "key": "embed_model",
                "description": "Ollama model for embeddings",
                "default": _DEFAULT_EMBED_MODEL,
                "required": False,
            },
            {
                "key": "ollama_host",
                "description": "Ollama server URL",
                "default": _DEFAULT_OLLAMA_HOST,
                "required": False,
            },
        ]

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        _save_config(values, hermes_home)

    # -- Session lifecycle ------------------------------------------------

    def initialize(self, session_id: str, **kwargs) -> None:
        """Initialize plugin for a session.

        Sets up the Athenaeum path, connects to ChromaDB, prepares the
        vault writer, and performs an initial content scan.
        """
        from hermes_constants import get_hermes_home  # noqa: PLC0415

        self._hermes_home = kwargs.get("hermes_home") or str(get_hermes_home())
        self._session_id = session_id
        self._config = _load_config(self._hermes_home)

        # Expand and resolve paths
        self._athenaeum_root = Path(self._config["athenaeum_root"])
        chroma_dir = Path(self._config["chroma_dir"])

        # Ensure directories exist
        self._athenaeum_root.mkdir(parents=True, exist_ok=True)
        chroma_dir.mkdir(parents=True, exist_ok=True)

        # Set up embedder — tries OpenRouter first, falls back to local Ollama
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self._embedder = _OpenRouterEmbedder(
            host=self._config.get("openrouter_host", _DEFAULT_OPENROUTER_HOST),
            model=self._config.get("embed_model", _DEFAULT_EMBED_MODEL),
            timeout=self._config.get("embed_timeout", _DEFAULT_EMBED_TIMEOUT),
            api_key=api_key or self._config.get("openrouter_api_key", ""),
        )

        # Set up ChromaDB — embedded, no Docker needed
        try:
            import chromadb  # noqa: PLC0415

            self._chroma = chromadb.PersistentClient(path=str(chroma_dir))
            self._chroma.heartbeat()
            self._chroma_available = True
        except Exception as exc:
            logger.warning("ChromaDB initialization failed: %s", exc)
            self._chroma_available = False

        # Set up vault writer
        vault_codex = self._config.get("vault_codex", _DEFAULT_VAULT_CODEX)
        vault_dir = self._athenaeum_root / vault_codex / "sessions"
        vault_dir.mkdir(parents=True, exist_ok=True)
        self._vault = _VaultWriter(vault_dir)

        # Warm up: ensure collections exist for all Codexes
        if self._chroma_available:
            self._ensure_codex_collections()

        self._initialized = True

    def shutdown(self) -> None:
        """Clean shutdown — flush vault, close ChromaDB."""
        if self._vault:
            self._vault.close_session()
        self._chroma = None
        self._embedder = None
        self._initialized = False

    # -- ChromaDB management ----------------------------------------------

    def _ensure_codex_collections(self) -> None:
        """Create ChromaDB collections for each Codex in the Athenaeum."""
        if not self._chroma or not self._athenaeum_root:
            return
        for codex in _list_codexes(self._athenaeum_root):
            col_name = _partition_for(codex)
            try:
                self._chroma.get_or_create_collection(col_name)
            except Exception as exc:
                logger.debug("Could not create collection %s: %s", col_name, exc)

    def _get_collection(self, codex: str) -> Any:
        """Get or create a ChromaDB collection for *codex*."""
        if not self._chroma:
            return None
        try:
            return self._chroma.get_or_create_collection(_partition_for(codex))
        except Exception as exc:
            logger.warning("Failed to get collection for %s: %s", codex, exc)
            return None

    def _scoped_collections(self, scope: Optional[List[str]] = None) -> List[str]:
        """Return collection names in scope."""
        if not self._chroma:
            return []
        try:
            all_cols = [c.name for c in self._chroma.list_collections()]
        except Exception:
            return []

        if scope is None or scope == "all":
            return all_cols

        wanted = {_partition_for(c) for c in scope}
        return [name for name in all_cols if name in wanted]

    # -- Embedding operations ----------------------------------------------

    def embed_file(self, file_path: str, codex: str) -> bool:
        """Embed a single file into its Codex partition. Returns True on success."""
        if not self._chroma or not self._embedder:
            return False

        collection = self._get_collection(codex)
        if collection is None:
            return False

        path = Path(file_path)
        if not path.exists():
            logger.warning("File not found: %s", file_path)
            return False

        try:
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                return False

            embedding = self._embedder.embed(content)
            doc_id = str(path.resolve())
            collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[{
                    "source": str(path),
                    "codex": codex,
                    "filename": path.name,
                }],
            )
            return True
        except Exception as exc:
            logger.warning("Failed to embed %s: %s", file_path, exc)
            return False

    def embed_athenaeum(self) -> Tuple[int, int]:
        """Walk the Athenaeum and embed all unembedded files.

        Returns (total_files, successfully_embedded).
        """
        if not self._athenaeum_root or not self._chroma or not self._embedder:
            return (0, 0)

        files = _walk_athenaeum_files(self._athenaeum_root)
        embedded = 0

        for rel_path, full_path, codex in files:
            if self.embed_file(full_path, codex):
                embedded += 1

        return (len(files), embedded)

    # -- Semantic search (Mnemosyne query) ---------------------------------

    def query(
        self, text: str, n_results: int = 5,
        scope: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Semantic search across scoped Codex partitions.

        Returns list of dicts with keys: content, source, codex, filename.
        """
        if not self._chroma or not self._embedder:
            return []

        try:
            embedding = self._embedder.embed(text)
        except Exception as exc:
            logger.warning("Embedding failed for query: %s", exc)
            return []

        collection_names = self._scoped_collections(scope)
        results: List[Dict[str, Any]] = []

        for name in collection_names:
            try:
                collection = self._chroma.get_collection(name)
                count = collection.count()
                raw = collection.query(
                    query_embeddings=[embedding],
                    n_results=min(n_results, count or n_results),
                    include=["documents", "metadatas"],
                )
            except Exception as exc:
                logger.debug("Query against %s failed: %s", name, exc)
                continue

            documents = raw.get("documents", [[]])[0]
            metadatas = raw.get("metadatas", [[]])[0]
            for doc, meta in zip(documents, metadatas):
                results.append({
                    "content": (doc or "")[:500],  # truncate for token budget
                    "source": meta.get("source", ""),
                    "codex": meta.get("codex", _codex_from_partition(name)),
                    "filename": meta.get("filename", ""),
                })

        return results[:n_results]

    def remove_stale(self, file_path: str) -> bool:
        """Remove a file's embedding from ChromaDB. Used when files are archived."""
        if not self._chroma:
            return False
        doc_id = str(Path(file_path).resolve())
        try:
            for collection in self._chroma.list_collections():
                try:
                    c = self._chroma.get_collection(collection.name)
                    c.delete(ids=[doc_id])
                except Exception:
                    continue
            return True
        except Exception:
            return False

    # -- MemoryProvider interface: system prompt block ---------------------

    def system_prompt_block(self) -> str:
        """Return Athenaeum navigation instructions for the system prompt."""
        if not self._athenaeum_root or not self._athenaeum_root.is_dir():
            return ""

        codexes = _list_codexes(self._athenaeum_root)
        codex_list = "\n".join(f"  - {c}" for c in codexes)

        vault_codex = self._config.get("vault_codex", _DEFAULT_VAULT_CODEX)

        return f"""<pantheon-context>
You have access to the Pantheon Athenaeum — a persistent, Codex-partitioned knowledge store at {self._athenaeum_root}.

Available Codices:
{codex_list}

Navigation:
  - Use athenaeum_walk to browse the index tree (always start at root INDEX.md)
  - Use athenaeum_read to read a specific file
  - Use athenaeum_search for semantic search across all content
  - Use athenaeum_embed to manually trigger re-embedding of a file

Current conversations are auto-logged to {vault_codex}/sessions/ and become searchable.
</pantheon-context>"""

    # -- MemoryProvider interface: prefetch --------------------------------

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """Start a background prefetch thread for the next turn."""
        # Cancel any running prefetch
        if self._prefetch_thread and self._prefetch_thread.is_alive():
            pass  # Let it finish — we'll use newest result

        def _do_prefetch():
            try:
                result = self._prefetch_sync(query)
                with self._prefetch_lock:
                    self._prefetch_result = result
            except Exception:
                pass

        self._prefetch_thread = threading.Thread(target=_do_prefetch, daemon=True)
        self._prefetch_thread.start()

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Return the most recent prefetched context, or run synchronously."""
        with self._prefetch_lock:
            if self._prefetch_result:
                result = self._prefetch_result
                self._prefetch_result = ""
                return result
        # Fallback: run sync
        return self._prefetch_sync(query)

    def _prefetch_sync(self, query: str) -> str:
        """Run a synchronous prefetch — search Mnemosyne for relevant context."""
        if not self._chroma_available or not self._embedder:
            return ""

        # Use the query text to find relevant content
        results = self.query(query, n_results=self._config.get("prefetch_results", 5))
        if not results:
            return ""

        lines = []
        for r in results:
            source = r.get("source", "")
            codex = r.get("codex", "")
            content = r.get("content", "")
            if content:
                lines.append(f"  [{codex}] {content[:300]}")
                if source:
                    lines[-1] += f" (source: {source})"

        if not lines:
            return ""

        return (
            "<pantheon-recall>\n"
            "Relevant context from previous sessions:\n"
            + "\n".join(lines) +
            "\n</pantheon-recall>"
        )

    # -- MemoryProvider interface: vault logging ---------------------------

    def sync_turn(
        self, user_content: str, assistant_content: str, *,
        session_id: str = "",
    ) -> None:
        """Write user and assistant turns to the vault immediately."""
        if not self._vault:
            return
        sid = session_id or self._session_id
        if not sid:
            return
        try:
            if user_content:
                self._vault.write_turn(sid, "User", user_content)
            if assistant_content:
                self._vault.write_turn(sid, "Assistant", assistant_content)
        except Exception as exc:
            logger.warning("Vault write failed: %s", exc)

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """Called when the session ends — close vault file."""
        if self._vault:
            self._vault.close_session()

    def on_session_switch(
        self, new_session_id: str, *,
        parent_session_id: str = "",
        reset: bool = False,
        **kwargs,
    ) -> None:
        """Handle session switch — finalize old vault, start new."""
        if self._vault:
            self._vault.close_session()
        self._session_id = new_session_id

        # Re-initialize vault for new session
        if self._athenaeum_root:
            vault_codex = self._config.get("vault_codex", _DEFAULT_VAULT_CODEX)
            vault_dir = self._athenaeum_root / vault_codex / "sessions"
            vault_dir.mkdir(parents=True, exist_ok=True)
            self._vault = _VaultWriter(vault_dir)

    # -- Provider tools ----------------------------------------------------

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return tool schemas for interacting with the Athenaeum."""
        return [
            {
                "name": "athenaeum_search",
                "description": "Semantic search across the Athenaeum. Finds relevant content by meaning, not keywords. Returns content, source, and Codex for each result.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for — natural language query",
                        },
                        "codexes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional. Restrict search to specific Codices (e.g. ['Codex-Forge', 'Codex-Pantheon']). Default: all",
                        },
                        "n_results": {
                            "type": "integer",
                            "description": "Max results (1-20)",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "athenaeum_read",
                "description": "Read a specific file from the Athenaeum by path relative to the Athenaeum root. Use athenaeum_walk first to find the path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path relative to the Athenaeum root (e.g. 'Codex-Forge/INDEX.md' or 'Codex-Forge/blueprints/plan.md')",
                        },
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "athenaeum_walk",
                "description": "Navigate the Athenaeum index tree. Reads an INDEX.md to find available files and subfolders. Always start at 'INDEX.md' (root) and walk down.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to an INDEX.md, relative to Athenaeum root. Use 'INDEX.md' for root, 'Codex-Forge/INDEX.md' for a Codex, etc.",
                            "default": "INDEX.md",
                        },
                    },
                    "required": [],
                },
            },
            {
                "name": "athenaeum_embed",
                "description": "Trigger re-embedding of a file into Mnemosyne. Useful after creating or modifying a file. Files are auto-detected on change, but this does an immediate manual embed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path relative to Athenaeum root (e.g. 'Codex-Forge/sessions/session-1.md')",
                        },
                    },
                    "required": ["path"],
                },
            },
        ]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        """Handle tool calls for Athenaeum operations."""
        handlers = {
            "athenaeum_search": self._tool_search,
            "athenaeum_read": self._tool_read,
            "athenaeum_walk": self._tool_walk,
            "athenaeum_embed": self._tool_embed,
        }
        handler = handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        try:
            result = handler(args)
            return json.dumps(result, default=str)
        except Exception as exc:
            logger.exception("Tool %s failed", tool_name)
            return json.dumps({"error": str(exc)})

    def _tool_search(self, args: dict) -> dict:
        query = args.get("query", "")
        codexes = args.get("codexes", None)
        n_results = min(int(args.get("n_results", 5)), 20)
        results = self.query(query, n_results=n_results, scope=codexes)
        return {"results": results, "count": len(results)}

    def _tool_read(self, args: dict) -> dict:
        rel_path = args.get("path", "")
        if not rel_path:
            return {"error": "path is required"}
        full_path = self._athenaeum_root / rel_path
        if not full_path.exists():
            return {"error": f"File not found: {rel_path}"}
        if not full_path.is_file():
            return {"error": f"Not a file: {rel_path}"}
        try:
            content = full_path.read_text(encoding="utf-8")
            return {
                "content": content,
                "path": rel_path,
                "size": len(content),
            }
        except Exception as exc:
            return {"error": str(exc)}

    def _tool_walk(self, args: dict) -> dict:
        rel_path = args.get("path", "INDEX.md")
        full_path = self._athenaeum_root / rel_path
        if not full_path.exists():
            return {
                "error": f"INDEX.md not found: {rel_path}",
                "available_codexes": _list_codexes(self._athenaeum_root),
            }
        if not full_path.is_file():
            return {"error": f"Not a file: {rel_path}"}
        try:
            content = full_path.read_text(encoding="utf-8")
            # Also list sibling files/subdirs for easy navigation
            parent = full_path.parent
            entries = []
            for child in sorted(parent.iterdir()):
                if child.is_dir():
                    entries.append({
                        "name": child.name,
                        "type": "directory",
                        "has_index": (child / "INDEX.md").exists(),
                    })
                elif child.is_file() and child.suffix.lower() in _EMBEDDABLE_EXTS:
                    entries.append({
                        "name": child.name,
                        "type": "file",
                        "size": child.stat().st_size,
                    })
            return {
                "content": content,
                "path": rel_path,
                "parent": str(parent.relative_to(self._athenaeum_root)) if parent != self._athenaeum_root else "/",
                "entries": entries,
            }
        except Exception as exc:
            return {"error": str(exc)}

    def _tool_embed(self, args: dict) -> dict:
        rel_path = args.get("path", "")
        if not rel_path:
            return {"error": "path is required"}
        full_path = self._athenaeum_root / rel_path
        if not full_path.exists():
            return {"error": f"File not found: {rel_path}"}

        # Determine Codex from path
        parts = Path(rel_path).parts
        codex = parts[0] if parts and parts[0].startswith("Codex-") else "Codex-General"

        success = self.embed_file(str(full_path), codex)
        return {
            "success": success,
            "path": rel_path,
            "codex": codex,
        }


# ---------------------------------------------------------------------------
# Plugin registration (called by Hermes plugin loader)
# ---------------------------------------------------------------------------


def register(ctx):
    """Register the Pantheon memory provider with Hermes."""
    ctx.register_memory_provider(PantheonMemoryProvider())
