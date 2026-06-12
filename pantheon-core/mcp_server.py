#!/usr/bin/env python3
"""Pantheon MCP Server — exposes Athenaeum, messaging, and god systems as MCP tools.

Run modes:
  python3 mcp_server.py          # HTTP mode (StreamableHTTP) on port 8010
  python3 mcp_server.py --stdio  # stdio mode (for Hermes subprocess)

Any MCP client (Hermes, AionUi, Claude Code) can connect and use Pantheon tools.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REAL_HOME = os.path.expanduser("~")
_ATHENAEUM_ROOT = Path(f"{_REAL_HOME}/athenaeum")
_CHROMA_DIR = Path(f"{_REAL_HOME}/.hermes/pantheon/chroma")
_MESSAGES_DIR = Path(f"{_REAL_HOME}/pantheon/gods/messages")
_PANTHEON_DIR = Path(f"{_REAL_HOME}/pantheon")
_HADES_REPORTS = Path(f"{_REAL_HOME}/athenaeum/Codex-Pantheon/reports")
_EMBEDDABLE_EXTS = {".md", ".txt", ".json", ".yaml", ".yml"}

# Load env vars from ~/.hermes/.env and profile-specific .env files
for env_file in [
    Path(f"{_REAL_HOME}/.hermes/.env"),
    Path(f"{_REAL_HOME}/.hermes/profiles/hephaestus/.env"),
    Path(f"{_REAL_HOME}/.hermes/profiles/apollo/.env"),
]:
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").split("\n"):
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, v_line = line.split("=", 1)
                    v_line = v_line.strip().strip("\"'")
                    os.environ.setdefault(k.strip(), v_line)
        except Exception:
            pass

logger = logging.getLogger("pantheon-mcp")

# ---------------------------------------------------------------------------
# Embedding client (reused from Hermes plugin)
# ---------------------------------------------------------------------------


class _Embedder:
    """Thin embedding wrapper — OpenRouter first, Ollama fallback.

    Ollama configuration:
    - Configurable model via ATHENAEUM_EMBED_MODEL env var
      (default: nomic-embed-text:v1.5).
    - ``num_ctx=2048`` to keep memory usage low on this hardware.
    - ``search_document: `` instruction prefix for retrieval-optimized embeddings.
    """

    def __init__(self):
        self._api_key = os.environ.get("ATHENAEUM_EMBED_API_KEY", "") or os.environ.get("OPENROUTER_API_KEY", "")
        self._model = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
        self._timeout = 30.0
        # Ollama model — configurable, defaults to qwen3-embedding:0.6b
        self._ollama_model = os.environ.get("ATHENAEUM_EMBED_MODEL", "nomic-embed-text:v1.5")

    @property
    def use_openrouter(self) -> bool:
        provider = os.environ.get("ATHENAEUM_EMBED_PROVIDER", "").lower()
        if provider == "ollama":
            return False
        return bool(self._api_key)

    def embed(self, text: str) -> List[float]:
        import httpx

        # nomic-embed-text has a ~512-token / ~2000-char limit.
        # Chunk at 1500 chars with overlap to stay safe.
        CHUNK_SIZE = 1500
        CHUNK_OVERLAP = 100
        MAX_CHUNKS = 20

        def _call_api(payload: dict) -> List[float]:
            if self.use_openrouter:
                url = "https://openrouter.ai/api/v1/embeddings"
                headers = {
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                }
            else:
                url = "http://localhost:11434/api/embeddings"
                headers = {"Content-Type": "application/json"}
                # nomic-embed-text supports ~2048 tokens — lower context saves RAM
                payload.setdefault("options", {})["num_ctx"] = 2048
            resp = httpx.post(url, headers=headers, json=payload, timeout=self._timeout)
            resp.raise_for_status()
            if self.use_openrouter:
                return resp.json()["data"][0]["embedding"]
            return resp.json()["embedding"]

        if len(text) <= CHUNK_SIZE:
            if self.use_openrouter:
                return _call_api({"model": self._model, "input": text})
            return _call_api({"model": self._ollama_model, "prompt": "search_document: " + text})

        # Chunk long texts and average
        chunks = []
        start = 0
        while start < len(text) and len(chunks) < MAX_CHUNKS:
            end = min(start + CHUNK_SIZE, len(text))
            if end < len(text):
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
                v = _call_api({"model": self._ollama_model, "prompt": "search_document: " + chunk})
            vectors.append(v)

        if not vectors:
            raise RuntimeError("embedding failed for all chunks")

        dim = len(vectors[0])
        avg = [0.0] * dim
        for v in vectors:
            for i in range(dim):
                avg[i] += v[i]
        return [x / len(vectors) for x in avg]

    def embed_chunks(self, text: str) -> List[List[float]]:
        """Embed text in chunks and return averaged vector."""
        chunk_size = 512
        chunks_n = max(1, len(text) // chunk_size + 1)
        if chunks_n == 1:
            return [self.embed(text)]
        embeddings = []
        texts = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
        for t in texts:
            embeddings.append(self.embed(t))
        # Average all chunk embeddings
        avg = [sum(vals) / len(embeddings) for vals in zip(*embeddings)]
        return [avg]

    def is_available(self) -> bool:
        if self.use_openrouter:
            return True
        try:
            import httpx
            resp = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# ChromaDB helpers
# ---------------------------------------------------------------------------


def _partition_for(codex: str) -> str:
    slug = codex.lower().replace("-", "_").replace(" ", "_")
    return f"pantheon_{slug}"


def _dict_factory(cursor, row):
    """SQLite row factory — returns dicts instead of tuples."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _codex_from_partition(collection_name: str) -> str:
    parts = collection_name.split("_", 2)
    if len(parts) < 3:
        return "Codex-General"
    raw = parts[2]
    words = raw.split("_")
    return "Codex-" + "-".join(w.capitalize() for w in words) if words else "Codex-General"


def _get_chroma_client():
    """Get or create a ChromaDB client."""
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        client.heartbeat()
        return client
    except Exception as exc:
        logger.warning("ChromaDB unavailable: %s", exc)
        return None


def _embed_file_background(file_path: str, content: str, codex_hint: str = "") -> None:
    """Embed a single file into ChromaDB. Non-blocking — failures are logged, not raised."""
    try:
        client = _get_chroma_client()
        if client is None:
            return
        embedder = _Embedder()
        if not embedder.is_available():
            return

        # Determine codex from file path
        rel = Path(file_path).relative_to(_ATHENAEUM_ROOT)
        codex = codex_hint or rel.parts[0]
        col_name = f"pantheon_{codex.lower().replace('-', '_')}"

        # Get or create the collection
        try:
            collection = client.get_collection(col_name)
        except Exception:
            collection = client.create_collection(col_name)

        # Embed and upsert (truncate to ~4K chars for nomic-embed-text context limit)
        embedding = embedder.embed(content[:4000])
        collection.upsert(
            ids=[str(Path(file_path).resolve())],
            embeddings=[embedding],
            documents=[content],
            metadatas=[{"source": file_path, "codex": codex, "filename": Path(file_path).name}],
        )
        logger.info("Embedded: %s → %s", rel, col_name)
    except Exception as exc:
        logger.warning("Background embed failed for %s: %s", file_path, exc)


def _list_codexes() -> List[str]:
    if not _ATHENAEUM_ROOT.is_dir():
        return []
    return sorted(
        d.name for d in _ATHENAEUM_ROOT.iterdir()
        if d.is_dir() and d.name.startswith("Codex-")
    )


# ---------------------------------------------------------------------------
# MCP server definition
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Pantheon",
    instructions="""Pantheon knowledge and messaging system for the multi-agent AI Pantheon.

Available systems:
- **Athenaeum** — file-based knowledge store with Codex-partitioned semantic search
- **Messaging** — inter-god message delivery via file-based inboxes
- **Ichor Brief** — query-less recall: 'what should I know right now?' — ranked context from conversation memory
- **Ichor Graph** — multi-hop NL graph queries: 'what tools does Hermes use?' — relation inference + entity resolution + path walking
- **Skills** — shared executable skills hub at athenaeum/skills/
- **Hades** — nightly consolidation reports
- **God Roster** — registered god information

All tools are Codex-aware: you can scope searches, reads, and writes to specific
Codices (Codex-Forge, Codex-Pantheon, Codex-Infrastructure, etc.).""",
    host="127.0.0.1",
    port=8010,
    log_level="INFO",
)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: athenaeum_search
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="[FTS5 P4d] Keyword search via SQLite FTS5 over the new 5-tier schema (cold_events + reference_knowledge). Replaced ChromaDB vector search. Returns content, source, codex, and rank score for each result.",
)
def athenaeum_search(
    query: str,
    codexes: Optional[List[str]] = None,
    n_results: int = 5,
) -> str:
    """Search the Athenaeum via FTS5 keyword matching.

    Implementation: P4d reimplementation. Uses the 5-tier schema's memory_fts
    FTS5 virtual table (over cold_events) and the reference_knowledge table.

    Args:
        query: Natural language or keyword search string. FTS5 supports
               prefix wildcards (e.g. "theo*"), boolean AND/OR, phrase quotes.
        codexes: Optional list of Codex names to scope results. Currently filters
                 by checking if the result's god_name (or reference_knowledge
                 source) matches. Most ichor events don't have a codex, so this
                 filter is best-effort.
        n_results: Maximum results to return (1-20). Default: 5.

    Returns:
        JSON string with results: [{content, source, codex, score}]
    """
    import sqlite3
    from pathlib import Path as _P
    db_path = _P.home() / ".hermes" / "ichor.db"

    if not query or not query.strip():
        return json.dumps({"error": "Empty query"}, indent=2)

    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.row_factory = sqlite3.Row
    except Exception as exc:
        return json.dumps({"error": f"Cannot open ichor.db: {exc}"}, indent=2)

    try:
        # Build FTS5 query — split on whitespace, quote each term, AND them
        # (FTS5 treats quoted strings as phrases, and default operator is AND)
        terms = query.split()
        # Sanitize each term: strip FTS5 special chars
        safe_terms = []
        for t in terms:
            t = t.strip('"\'()\\')
            if not t:
                continue
            # Escape double quotes
            t = t.replace('"', '')
            safe_terms.append(f'{t}*')  # prefix match
        if not safe_terms:
            return json.dumps({"error": "No valid search terms"}, indent=2)
        fts_query = " AND ".join(safe_terms)

        # Search cold_events via memory_fts
        limit = max(1, min(n_results, 20))
        rows = conn.execute(
            """SELECT m.rowid AS id, m.content, m.name, m.event_type, m.category,
                      c.importance, c.trust, c.session_id, c.god_name, c.created_at
               FROM memory_fts m
               JOIN cold_events c ON c.id = m.rowid
               WHERE memory_fts MATCH ?
               ORDER BY c.importance DESC, c.created_at DESC
               LIMIT ?""",
            (fts_query, limit)
        ).fetchall()

        results = []
        for r in rows:
            # Filter by codex if requested (best-effort: match against god_name or category)
            if codexes:
                # No reliable codex mapping in cold_events, so this filter is lenient
                pass

            content_preview = (r["content"] or "")[:2000] or "(empty)"
            # Compute a rank score: importance is 0-100, normalize to 0-1
            score = round((r["importance"] or 50.0) / 100.0, 3)

            results.append({
                "content": content_preview,
                "source": r["name"] or f"cold_event:{r['id']}",
                "codex": r["god_name"] or "ichor",
                "event_type": r["event_type"] or "",
                "score": score,
                "created_at": r["created_at"] or "",
            })

        return json.dumps({"results": results, "total": len(results)}, indent=2)

    except sqlite3.OperationalError as exc:
        # Common: FTS5 query syntax error
        return json.dumps({"error": f"FTS5 query failed: {exc}. Try simpler terms."}, indent=2)
    except Exception as exc:
        return json.dumps({"error": f"Search failed: {type(exc).__name__}: {exc}"}, indent=2)
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# Tool: athenaeum_read
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Read a specific file from the Athenaeum by path relative to the Athenaeum root. Returns content with line numbers. Use athenaeum_walk first to find paths.",
)
def athenaeum_read(
    path: str,
) -> str:
    """Read a file from the Athenaeum.

    Args:
        path: Path relative to the Athenaeum root (e.g. "Codex-Forge/INDEX.md"
              or "Codex-Forge/blueprints/plan.md").

    Returns:
        File content with line numbers and path info, or an error message.
    """
    # Security: prevent path traversal
    sanitized = path.lstrip("/").replace("..", "")
    full_path = (_ATHENAEUM_ROOT / sanitized).resolve()

    # Ensure it's still under the Athenaeum
    try:
        full_path.relative_to(_ATHENAEUM_ROOT.resolve())
    except ValueError:
        return json.dumps({"error": "Path must be within the Athenaeum"}, indent=2)

    if not full_path.exists():
        # Suggest similar paths
        parent = full_path.parent
        if parent.is_dir():
            siblings = sorted(
                str(p.relative_to(_ATHENAEUM_ROOT))
                for p in parent.iterdir()
                if p.is_file() and not p.name.startswith(".")
            )
            hint = f"\nAvailable files in {parent.name}: {siblings[:10]}"
            if len(siblings) > 10:
                hint += f" ... and {len(siblings) - 10} more"
        else:
            hint = ""

        return json.dumps({"error": f"File not found: {path}{hint}"}, indent=2)

    if full_path.is_dir():
        return json.dumps({"error": f"Path is a directory, not a file: {path}"}, indent=2)

    try:
        content = full_path.read_text(encoding="utf-8")
        lines = content.split("\n")
        numbered = "\n".join(
            f"{i + 1:4d}|{l}" for i, l in enumerate(lines)
        )
        return json.dumps({
            "path": path,
            "total_lines": len(lines),
            "content": numbered,
        }, indent=2)
    except Exception as exc:
        return json.dumps({"error": f"Failed to read {path}: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: athenaeum_walk
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Navigate the Athenaeum index tree. Reads an INDEX.md to list available files and subdirectories. Start at root (path='INDEX.md') and walk down through Codexes.",
)
def athenaeum_walk(
    path: str = "INDEX.md",
) -> str:
    """Browse the Athenaeum index structure.

    Args:
        path: Path to an INDEX.md, relative to Athenaeum root.
              Use "INDEX.md" for root, "Codex-Forge/INDEX.md" for a Codex, etc.
              Default: "INDEX.md" (root).

    Returns:
        The index file content and a listing of subdirectories and files.
    """
    sanitized = path.lstrip("/").replace("..", "")
    full_path = (_ATHENAEUM_ROOT / sanitized).resolve()

    try:
        full_path.relative_to(_ATHENAEUM_ROOT.resolve())
    except ValueError:
        return json.dumps({"error": "Path must be within the Athenaeum"}, indent=2)

    # Determine which directory to browse
    browse_dir = full_path.parent if full_path.suffix else full_path

    if not browse_dir.is_dir():
        return json.dumps({"error": f"Directory not found: {browse_dir.relative_to(_ATHENAEUM_ROOT)}"}, indent=2)

    # Read INDEX.md if it exists
    index_path = browse_dir / "INDEX.md"
    index_content = ""
    if index_path.exists():
        try:
            index_content = index_path.read_text(encoding="utf-8")[:2000]  # truncate long indexes
        except Exception:
            pass

    # List subdirectories and files
    subdirs = []
    files = []
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
            if child.is_dir():
                subdirs.append({"name": child.name, "path": rel, "last_modified": modified})
            elif child.is_file():
                size_kb = child.stat().st_size / 1024
                files.append({
                    "name": child.name,
                    "path": rel,
                    "size_kb": round(size_kb, 1),
                    "last_modified": modified,
                })
    except Exception as exc:
        return json.dumps({"error": f"Failed to list directory: {exc}"}, indent=2)

    result = {
        "directory": browse_dir.relative_to(_ATHENAEUM_ROOT).as_posix(),
        "index_content": index_content or "(no INDEX.md found)",
        "subdirectories": subdirs,
        "files": files,
    }
    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: athenaeum_write
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Write content to a file in the Athenaeum. Creates parent directories if needed. WARNING: overwrites existing files. Use for contributing structured knowledge or session artifacts.",
)
def athenaeum_write(
    path: str,
    content: str,
    codex: str = "",
) -> str:
    """Write a file to the Athenaeum.

    Args:
        path: Path relative to Athenaeum root (e.g. "Codex-Forge/notes/something.md").
        content: The full content to write. Overwrites if file exists.
        codex: Optional Codex hint for validation (e.g. "Codex-Forge").
               The path's first directory must match this if provided.

    Returns:
        Result message with the full path written.
    """
    sanitized = path.lstrip("/").replace("..", "")
    full_path = (_ATHENAEUM_ROOT / sanitized).resolve()

    try:
        full_path.relative_to(_ATHENAEUM_ROOT.resolve())
    except ValueError:
        return json.dumps({"error": "Path must be within the Athenaeum"}, indent=2)

    # Validate Codex if specified
    if codex:
        first_part = full_path.relative_to(_ATHENAEUM_ROOT).parts[0]
        if first_part != codex:
            return json.dumps({
                "error": f"Path {path} does not start with the specified Codex '{codex}' (got '{first_part}')"
            }, indent=2)

    # Create parent directories
    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return json.dumps({"error": f"Failed to create directories: {exc}"}, indent=2)

    try:
        full_path.write_text(content, encoding="utf-8")
        # ── Auto-embed into ChromaDB ─────────────────────────────────
        if full_path.suffix.lower() in _EMBEDDABLE_EXTS and full_path.name != "INDEX.md":
            try:
                _embed_file_background(str(full_path), content, codex)
            except Exception:
                pass  # never fail a write because embedding is down
        return json.dumps({
            "success": True,
            "path": str(full_path.relative_to(_ATHENAEUM_ROOT)),
            "bytes_written": len(content.encode("utf-8")),
        }, indent=2)
    except Exception as exc:
        return json.dumps({"error": f"Failed to write {path}: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: athenaeum_list_codexes
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="List all available Codexes (knowledge domains) in the Athenaeum with optional file counts.",
)
def athenaeum_list_codexes(
    details: bool = False,
) -> str:
    """List all Codexes in the Athenaeum.

    Args:
        details: If True, include file counts per Codex. Default: False.

    Returns:
        List of Codex names with optional file counts.
    """
    codexes = _list_codexes()
    if not codexes:
        return json.dumps({"error": "No Codexes found in Athenaeum"}, indent=2)

    if not details:
        return json.dumps({"codexes": codexes}, indent=2)

    result = []
    for c in codexes:
        codex_dir = _ATHENAEUM_ROOT / c
        file_count = sum(
            1 for f in codex_dir.rglob("*")
            if f.is_file() and f.suffix.lower() in _EMBEDDABLE_EXTS and f.name != "INDEX.md"
        )
        result.append({"name": c, "file_count": file_count})

    return json.dumps({"codexes": result}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: messaging_send
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Send a message to another god's inbox. Gods check their inboxes at the start of sessions. Messages can be notifications, requests, or alerts.",
)
def messaging_send(
    to: str,
    subject: str,
    body: str,
    priority: str = "normal",
    message_type: str = "notification",
) -> str:
    """Send a message to a god's inbox via the bridge protocol.

    Args:
        to: Recipient god name (lowercase, e.g. "hermes", "hephaestus", "apollo").
        subject: Short subject line for the message.
        body: Message content. Can include markdown.
        priority: "high", "normal", or "low". Default: "normal".
        message_type: "notification", "request", "response", "alert", or "report". Default: "notification".

    Returns:
        Result with message ID and delivery path.
    """
    inbox_dir = _MESSAGES_DIR / to
    try:
        inbox_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return json.dumps({"error": f"Cannot create inbox for '{to}': {exc}"}, indent=2)

    now = datetime.now(timezone.utc)
    msg_id = f"msg_{now.strftime('%Y%m%d_%H%M%S')}_{to[:6]}"

    message = {
        "id": msg_id,
        "from": "pantheon-mcp",
        "to": to,
        "type": message_type,
        "subject": subject,
        "body": body,
        "priority": priority if priority in ("high", "normal", "low") else "normal",
        "timestamp": now.isoformat(),
        "read": False,
        "payload": {},
        "thread_id": None,
    }

    msg_path = inbox_dir / f"{msg_id}.json"
    try:
        msg_path.write_text(json.dumps(message, indent=2) + "\n", encoding="utf-8")
        return json.dumps({
            "success": True,
            "message_id": msg_id,
            "delivered_to": f"gods/messages/{to}/{msg_id}.json",
            "timestamp": now.isoformat(),
        }, indent=2)
    except Exception as exc:
        return json.dumps({"error": f"Failed to write message: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: messaging_check_inbox
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Check a god's inbox for unread messages. Returns all unread messages with their content and metadata.",
)
def messaging_check_inbox(
    god_name: str,
    mark_read: bool = False,
) -> str:
    """Check a god's inbox for new messages.

    Args:
        god_name: The god name to check (e.g. "hephaestus", "hermes", "apollo").
        mark_read: If True, mark returned messages as read. Default: False.

    Returns:
        List of unread messages with their content.
    """
    inbox_dir = _MESSAGES_DIR / god_name
    if not inbox_dir.is_dir():
        return json.dumps({"messages": [], "note": f"No inbox found for '{god_name}'"}, indent=2)

    messages = []
    try:
        for f in sorted(inbox_dir.glob("msg_*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("read", False):
                    continue
                messages.append({
                    "id": data.get("id", f.stem),
                    "from": data.get("from", "unknown"),
                    "type": data.get("type", "notification"),
                    "subject": data.get("subject", ""),
                    "body": data.get("body", ""),
                    "priority": data.get("priority", "normal"),
                    "timestamp": data.get("timestamp", ""),
                })
                if mark_read:
                    data["read"] = True
                    f.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            except (json.JSONDecodeError, Exception):
                continue
    except Exception as exc:
        return json.dumps({"error": f"Failed to check inbox: {exc}"}, indent=2)

    return json.dumps({"messages": messages, "count": len(messages)}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: ichor_brief
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Get a ranked context brief for a Pantheon god — 'what should I know right now?'. Scores events by priority (blockers > commitments > decisions), freshness, confidence, and repetition. No search query needed.",
)
def ichor_brief(
    god_name: str = "",
    limit: int = 10,
    min_score: float = 0.20,
    include_all_gods: bool = False,
    output_json: bool = True,
) -> str:
    """Get a ranked context brief for a Pantheon god — zero-query recall.

    Returns the most relevant events for a god, scored by a weighted formula
    combining priority (event type), freshness (time decay), confidence (Tier A
    extraction), and repetition (occurrence count).

    Args:
        god_name: Filter events for this specific god (e.g. 'hermes', 'hephaestus').
                  Empty string returns events for all gods.
        limit: Maximum number of events to return (default: 10, max: 50).
        min_score: Minimum relevance score threshold 0.0-1.0 (default: 0.20).
                   Higher values filter out lower-confidence events.
        include_all_gods: If True, include events from ALL gods even when
                         god_name is set. Gives cross-god awareness.
        output_json: If True (default), returns structured JSON. If False,
                     returns formatted markdown.

    Returns:
        JSON string with ranked events and metadata, or markdown string.
    """
    try:
        # Import and build the brief
        sys.path.insert(0, str(Path.home() / "pantheon"))
        from lib.ichor_brief import build_brief  # type: ignore[import-untyped]

        result = build_brief(
            god_name=god_name,
            limit=min(limit, 50),
            min_score=min_score,
            include_all_gods=include_all_gods,
            output_format="json" if output_json else "markdown",
        )
        if output_json:
            return json.dumps(result, indent=2, default=str)
        return result
    except Exception as exc:
        return json.dumps({"error": f"ichor_brief failed: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: hades_get_report
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Get the most recent Hades nightly consolidation report. Hades runs daily and produces a report on health, distillation, and archival status of the Athenaeum.",
)
def hades_get_report(
    report_date: str = "",
) -> str:
    """Read the most recent (or specific) Hades consolidation report.

    Args:
        report_date: Optional date string (YYYY-MM-DD) to fetch a specific report.
                     Default: most recent report available.

    Returns:
        The report content as markdown.
    """
    if not _HADES_REPORTS.is_dir():
        return json.dumps({"error": "No Hades reports directory found"}, indent=2)

    if report_date:
        report_path = _HADES_REPORTS / f"hades-{report_date}.md"
        if not report_path.exists():
            return json.dumps({"error": f"No report found for date {report_date}"}, indent=2)
    else:
        # Find most recent
        reports = sorted(_HADES_REPORTS.glob("hades-*.md"), reverse=True)
        if not reports:
            return json.dumps({"error": "No Hades reports found"}, indent=2)
        report_path = reports[0]
        report_date = report_path.stem.replace("hades-", "")

    try:
        content = report_path.read_text(encoding="utf-8")
        return json.dumps({
            "report_date": report_date,
            "report_path": str(report_path.relative_to(_ATHENAEUM_ROOT)),
            "content": content,
        }, indent=2)
    except Exception as exc:
        return json.dumps({"error": f"Failed to read report: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: god_list
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="List all registered gods in the Pantheon. Returns their display name, role, description, capabilities, and status.",
)
def god_list() -> str:
    """List all registered gods from the gods.yaml roster.

    Returns:
        List of gods with their metadata.
    """
    gods_file = _PANTHEON_DIR / "gods" / "gods.yaml"

    if not gods_file.exists():
        return json.dumps({"error": "No gods.yaml roster found"}, indent=2)

    try:
        import yaml
        data = yaml.safe_load(gods_file.read_text(encoding="utf-8"))
        if not data or "gods" not in data:
            return json.dumps({"error": "gods.yaml has no 'gods' key"}, indent=2)

        gods = []
        for gid, info in data["gods"].items():
            gods.append({
                "id": gid,
                "display_name": info.get("display_name", gid),
                "role": info.get("role", ""),
                "description": info.get("description", ""),
                "capabilities": info.get("capabilities", []),
                "status": info.get("status", "unknown"),
            })

        return json.dumps({"gods": gods}, indent=2)
    except Exception as exc:
        return json.dumps({"error": f"Failed to parse gods.yaml: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: ichor_retrieve
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Fused search across all Ichor memory backends (FTS5 keyword + ChromaDB semantic + Graph relationships + structured events). Returns ranked results with fused relevance scores. ⚠️ SYSTEM RULE: When ChromaDB returns both a distilled document and a raw session for the same topic, the distilled document is always ranked higher by design. Use the distilled doc as your primary context — it's the canonical LLM-optimized summary. Only fall back to the raw session if you need more detail than the distilled version provides. Part of the Memory Trait Contract.",
)
def ichor_retrieve(
    query: str,
    limit: int = 10,
    backends: str = "fts5,chroma,graph,events",
    min_score: float = 0.0,
) -> str:
    """Unified retrieval across all Ichor backends — 'what do we know about X?'

    Searches all configured memory backends simultaneously, fuses results
    with a weighted scoring formula, and returns ranked results.

    Args:
        query: Natural language search query.
        limit: Maximum results to return (default: 10, max: 50).
        backends: Comma-separated backend list. Options: fts5, chroma, graph, events.
                  Default: 'fts5,chroma,graph,events' (all backends).
        min_score: Minimum fused score threshold 0.0-1.0 (default: 0.0).

    Returns:
        JSON with ranked results, backends used, and scores.
    """
    try:
        sys.path.insert(0, str(Path.home() / "pantheon"))
        from lib.ichor_hybrid import MemoryTrait  # type: ignore[import-untyped]

        backend_list = [b.strip() for b in backends.split(",") if b.strip()]
        trait = MemoryTrait()
        result = trait.retrieve(
            query=query,
            limit=min(limit, 50),
            backends=backend_list,
            min_score=min_score,
            output_format="json",
        )
        return json.dumps(result, indent=2, default=str)
    except Exception as exc:
        return json.dumps({"error": f"ichor_retrieve failed: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: ichor_store
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="""Store content into Ichor memory — auto-routes to correct backend based on category.

FORGE INSTRUCTIONS (CRITICAL):
When you write a memory, ALSO evaluate whether this content affects the user profile or should be shared across the Pantheon:
  - category='fact|preference|decision|commitment|insight|blocker|follow_up|correction|reference' — standard memory (current)
  - category='user_md_update' — this content changes what we know about the user. Updates USER.md profile. Write a separate ichor_store call with this category when your memory entry represents a new user preference, habit, correction, or identity detail.
  - category='digest_entry' — this content matters for other gods/users to know about. Write a separate ichor_store call with this category when your memory is a decision, deployment change, blocker resolution, or other cross-system signal. Include the session_id so others can pull context.
  - category='entity|relationship' — extract named entities or relationships for the knowledge graph. Write separate ichor_store calls for each entity/relationship found.
  - 'document|note|reference' — full content stored to Athenaeum + auto-embedded to ChromaDB silently in background.

Think of memory writing as a forge: one important realization → multiple outputs (memory entry, profile update, digest notification, entity extraction). The same LLM context that produced the memory should evaluate all four.

Categories routing:
  - fact/preference/decision/commitment/insight/blocker/follow_up/correction/reference/user_md_update → ichor_events (FTS5)
  - entity/relationship → Graph DB
  - digest_entry → Shared context digest (DIGEST.md)
  - document/note → Athenaeum files + ChromaDB embed (background)
""",)
def ichor_store(
    key: str,
    content: str,
    namespace: str = "default",
    category: str = "fact",
    session_id: str = "",
    god_name: str = "",
) -> str:
    """Store content into Ichor memory with automatic backend routing.

    Args:
        key: Unique identifier for the stored item.
        content: Content to store (markdown text).
        namespace: Logical grouping (default: 'default').
        category: Content category for backend routing.
        session_id: Optional source session ID.
        god_name: Optional god name for scoping.

    Returns:
        JSON with store result and backend used.
    """
    try:
        sys.path.insert(0, str(Path.home() / "pantheon"))
        from lib.ichor_hybrid import MemoryTrait

        trait = MemoryTrait()
        result = trait.store(
            namespace=namespace, key=key, content=content,
            category=category, session_id=session_id, god_name=god_name,
        )
        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"error": f"ichor_store failed: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: ichor_forget
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Delete an item from Ichor memory by key (e.g. 'fts5:42', 'graph:node:abc'). Part of the Memory Trait Contract.",
)
def ichor_forget(
    key: str,
) -> str:
    """Delete an item from Ichor memory.

    Args:
        key: '<backend>:<id>' — e.g. 'fts5:42', 'graph:node:abc'.

    Returns:
        JSON confirmation.
    """
    try:
        sys.path.insert(0, str(Path.home() / "pantheon"))
        from lib.ichor_hybrid import MemoryTrait

        trait = MemoryTrait()
        result = trait.forget(key=key)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"error": f"ichor_forget failed: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: ichor_goal (A1, 2026-06-11)
# ═══════════════════════════════════════════════════════════════════════════
# Strategic-goals registry. Distinct from hermes_cli/goals.py (per-turn
# judge). Spec: ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md
# §A1. Backed by `strategic_goals` table in ichor.db (see lib.ichor.schema_v2 (was lib/ichor_schema_v2.py)..

@mcp.tool(
    description="[A1] Strategic-goals registry for Pantheon. Distinct from hermes_cli/goals.py (per-turn judge). Actions: add | list | get | update | complete | pause | inject | stats. `add` creates a goal; `list` filters by status/category; `inject` returns the session-start preamble (markdown) for the system prompt; `complete`/`pause` flip status. See `format_active_goals_preamble()` in lib/ichor_goals.py for the injection format.",
)
def ichor_goal(
    action: str,
    title: str = "",
    goal_id: int = 0,
    description: str = "",
    category: str = "general",
    priority: int = 5,
    status: str = "",
    progress: float = -1.0,
    target_date: str = "",
    limit: int = 5,
    min_priority: int = 3,
) -> str:
    """Manage strategic goals in `ichor.db::strategic_goals`.

    Returns:
        JSON string. For action='inject', also includes a `preamble` field
        with the markdown block to splice into the system prompt.
    """
    try:
        sys.path.insert(0, str(Path.home() / "pantheon"))
        from lib.ichor_goals import mcp_dispatch  # type: ignore[import-untyped]
        return mcp_dispatch(
            action=action, title=title, goal_id=goal_id,
            description=description, category=category, priority=priority,
            status=status, progress=progress, target_date=target_date,
            limit=limit, min_priority=min_priority,
        )
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"ichor_goal failed: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: ichor_health
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Check health of all Ichor memory backends (FTS5, ChromaDB, Graph, Events). Part of the Memory Trait Contract.",
)
def ichor_health() -> str:
    """Check health of all Ichor memory backends.

    Returns:
        JSON with per-backend health and fused status.
    """
    try:
        sys.path.insert(0, str(Path.home() / "pantheon"))
        from lib.ichor_hybrid import MemoryTrait

        trait = MemoryTrait()
        result = trait.health_check()
        return json.dumps(result, indent=2)
    except Exception as exc:
        return json.dumps({"error": f"ichor_health failed: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: ichor_gates
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Test or run the Ichor RALPH 5-gate harness. Supports: state_gate (read-before-write check on a file), logic_gate (syntax validate a file), phase_detect (detect RALPH phase from text), handoff (generate handoff manifest between gods). Returns gate results and intervention details.",
)
def ichor_gates(
    action: str,
    path_or_input: str = "",
    source_god: str = "hermes",
    target_god: str = "hephaestus",
    tier: str = "full",
    verbose: bool = False,
) -> str:
    """Run the Ichor RALPH 5-gate harness.

    Enforces deterministic tool-call gating: State Gate (read-before-write),
    Logic Gate (post-write syntax validation), Intent Injection (context
    pre-fetching), Phase Detection (RALPH phase tracking), and Handoff Gate
    (state verification + signed seal).

    Args:
        action: One of 'state_gate', 'logic_gate', 'phase_detect',
                'handoff', 'pipeline_health'.
        path_or_input: File path (for state/logic gates) or natural language
                       input (for phase detection).
        source_god: Source god name for handoff (default: hermes).
        target_god: Target god name for handoff (default: hephaestus).
        tier: Handoff tier: 'full' (all 6 checks) or 'bronze' (git+mandatory).
        verbose: If True, include detailed gate state in output.

    Returns:
        JSON with gate results, intervention details, and recovery hints.
    """
    try:
        sys.path.insert(0, str(Path.home() / "pantheon"))
        from lib.ichor_gates import (  # type: ignore[import-untyped]
            GatePipeline,
            LogicGate,
            PhaseDetectionGate,
            ReadCache,
            StateGate,
        )

        pipeline = GatePipeline()
        result: dict = {"action": action, "gate": "", "passed": True,
                        "message": "", "details": {}}

        if action == "state_gate":
            if not path_or_input:
                return json.dumps({"error": "path_or_input required for state_gate"})
            cache = ReadCache()
            gate = StateGate(cache)

            # Test without prior read
            r = gate.pre_call("write_file", {"path": path_or_input}, {})
            if r and not r.passed:
                result["gate"] = "state_gate"
                result["passed"] = False
                result["message"] = r.message
                result["details"]["recovery"] = r.recovery_hint
                result["details"]["intervention"] = True
            else:
                result["message"] = "File appears new or was read — write allowed"

            # Show what happens after read
            cache.mark_read(path_or_input)
            r2 = gate.pre_call("write_file", {"path": path_or_input}, {})
            result["details"]["after_read"] = "blocked" if (r2 and not r2.passed) else "allowed"

        elif action == "logic_gate":
            if not path_or_input:
                return json.dumps({"error": "path_or_input required for logic_gate"})
            gate = LogicGate()
            try:
                with open(path_or_input, "r") as f:
                    content = f.read()
            except FileNotFoundError:
                return json.dumps({"error": f"File not found: {path_or_input}"})

            r = gate.post_call("write_file", {"path": path_or_input,
                                "content": content}, None, {})
            if r and not r.passed:
                result["gate"] = "logic_gate"
                result["passed"] = False
                result["message"] = r.message
                result["details"]["issues"] = r.recovery_hint.split("\n")
                result["details"]["intervention"] = r.intervention
            else:
                result["message"] = "File passed syntax validation"
                result["details"]["issues"] = []

        elif action == "phase_detect":
            if not path_or_input:
                return json.dumps({"error": "path_or_input required for phase_detect"})
            gate = PhaseDetectionGate()
            phase = gate.detect_phase(path_or_input)
            result["gate"] = "phase_detection_gate"
            result["message"] = f"Detected phase: {phase.value}"
            result["details"]["phase"] = phase.value
            result["details"]["tools"] = gate.get_allowed_tools() or []
            result["details"]["prompt"] = gate.get_phase_prompt()

        elif action == "handoff":
            manifest = pipeline.generate_handoff_manifest(
                source_god, target_god, tier
            )
            result["gate"] = "handoff_gate"
            result["message"] = (f"Handoff {source_god} → {target_god} "
                                 f"[{manifest.tier.upper()}]")
            result["details"]["source"] = source_god
            result["details"]["target"] = target_god
            result["details"]["tier"] = manifest.tier
            result["details"]["seal"] = manifest.signature
            result["details"]["checks"] = manifest.check_results
            result["details"]["state_size"] = manifest.state_snapshot.get("count", 0)
            all_pass = all(manifest.check_results.values())
            result["passed"] = all_pass
            if verbose:
                result["details"]["state_snapshot"] = manifest.state_snapshot

        elif action == "pipeline_health":
            gates = ["state_gate", "logic_gate", "intent_injection_gate",
                     "phase_detection_gate", "handoff_gate"]
            result["message"] = f"Gate pipeline ready: {len(gates)} gates"
            result["details"]["gates"] = gates
            result["details"]["pipeline_size"] = len(pipeline.gates)

        else:
            return json.dumps({
                "error": f"Unknown action '{action}'. Options: state_gate, "
                         "logic_gate, phase_detect, handoff, pipeline_health"
            })

        return json.dumps(result, indent=2)

    except Exception as exc:
        return json.dumps({"error": f"ichor_gates failed: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: ichor_forge
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Run the Ichor Forge — self-adjusting harness analysis. Analyzes gate intervention logs to detect over-blocking, missing intent keywords, phase detection issues, and recurring failure patterns. Supports: analyze (full report), status (quick summary), adjust (propose changes). The forge is the meta-learning loop — like Dojo for the gates themselves.",
)
def ichor_forge(
    action: str = "status",
    days: int = 7,
    verbose: bool = False,
    god: str = "",
) -> str:
    """Run the Ichor Forge — self-adjusting harness analysis.

    Reads intervention logs from ~/.hermes/ichor/forge/all.jsonl and
    produces analysis: per-gate metrics, failure patterns, model-specific
    issues, missing intent keywords, and suggested adjustments.
    Supports per-god filtering — different gods have different behavior
    patterns and need different tuning.

    Args:
        action: One of 'status' (quick summary), 'analyze' (full report),
                'adjust' (propose changes), 'json' (raw data).
        days: Lookback window in days (default: 7).
        verbose: Include per-gate detail in analyze mode.
        god: Filter by god name (e.g. 'hermes', 'apollo', 'hephaestus').
             Empty string (default) analyzes all gods together.

    Returns:
        JSON with forge findings: total_interventions, overall_block_rate,
        per_gate metrics, detected_patterns, suggested_adjustments.
    """
    try:
        sys.path.insert(0, str(Path.home() / "pantheon"))
        from lib.ichor_forge import (  # type: ignore[import-untyped]
            ForgeAnalyzer,
            ForgeReport,
            ForgeSmith,
        )

        analyzer = ForgeAnalyzer()
        smith = ForgeSmith()
        report = ForgeReport()

        if action == "status":
            findings = analyzer.analyze(days=days, god=god)
            return json.dumps({
                "action": "status",
                "short_status": report.short_status(findings),
                "total_interventions": findings.total_interventions,
                "overall_block_rate": round(findings.overall_block_rate, 3),
                "gates_active": len(findings.gates_seen),
                "patterns_found": len(findings.detected_patterns),
                "adjustments_suggested": len(findings.suggested_adjustments),
            }, indent=2)

        elif action == "analyze":
            findings = analyzer.analyze(days=days, god=god)
            result = {
                "action": "analyze",
                "total_interventions": findings.total_interventions,
                "timespan_days": round(findings.timespan_days, 1),
                "overall_block_rate": round(findings.overall_block_rate, 3),
                "models_seen": findings.models_seen,
                "gates_seen": findings.gates_seen,
                "per_gate": {},
                "detected_patterns": findings.detected_patterns,
                "suggested_adjustments": findings.suggested_adjustments,
            }
            for gate_name, gm in findings.per_gate.items():
                result["per_gate"][gate_name] = {
                    "total": gm.total,
                    "passed": gm.passed,
                    "blocked": gm.blocked,
                    "block_rate": round(gm.block_rate, 3),
                }
                if verbose:
                    result["per_gate"][gate_name]["top_blocks"] = [
                        {"message": m, "count": c}
                        for m, c in gm.top_block_messages.most_common(5)
                    ]
            return json.dumps(result, indent=2)

        elif action == "adjust":
            findings = analyzer.analyze(days=days, god=god)
            adjustments = smith.evaluate(findings)
            return json.dumps({
                "action": "adjust",
                "total_interventions": findings.total_interventions,
                "adjustments": [
                    {
                        "target": a.target,
                        "action": a.action,
                        "item": a.item,
                        "reason": a.reason,
                        "confidence": round(a.confidence, 2),
                    }
                    for a in adjustments
                ],
            }, indent=2)

        elif action == "json":
            import dataclasses
            findings = analyzer.analyze(days=days)
            return json.dumps(
                dataclasses.asdict(findings),
                indent=2, default=str,
            )

        else:
            return json.dumps({
                "error": f"Unknown action '{action}'. "
                         "Options: status, analyze, adjust, json"
            })

    except Exception as exc:
        return json.dumps({"error": f"ichor_forge failed: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: ichor_graph_query
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Multi-hop graph query against the Ichor entity-relationship layer (ER-P3). Resolves `query` to a known entity, then returns its neighborhood subgraph (nodes, edges, stats) using the new 5-tier schema. Replaces the P4b stub — the entity-relationship layer is now live."
)
def ichor_graph_query(
    query: str,
    hops: int = 2,
    max_results: int = 30,
    output_markdown: bool = False,
) -> str:
    """Multi-hop graph query via lib.ichor.entities.traversal.

    Resolves the free-form `query` to a known entity name using
    athenaeum_graph_search, then walks the entity-relationship graph
    via the new 5-tier schema (entities / relationships / warm_entities).
    The entity layer was added in 2026-06-12's Ichor refactor and was
    latent until this tool was wired in.

    Args:
        query: Entity name or free-form phrase. Resolved to the top
            athenaeum_graph_search hit (best-effort fuzzy match).
        hops: Traversal depth (1..7). Clamped to 7. Default 2.
        max_results: Cap on returned nodes/edges in markdown mode.
        output_markdown: If True, render as human-readable text instead
            of JSON.

    Returns:
        JSON or markdown rendering of:
          {nodes: [...], edges: [...], stats: {...}, resolved_from: query}
    """
    # Lazy import — the entities package is heavy (loads 7 submodules)
    # and we don't want to pay the cost on every mcp_server startup.
    try:
        import sqlite3 as _sqlite3
        from lib.ichor.entities import graph_query as _er_graph_query  # type: ignore[import-untyped]
        from lib.ichor.entities.schema import get_conn as _er_get_conn  # type: ignore[import-untyped]
    except Exception as exc:
        return json.dumps({
            "error": "entities_layer_unavailable",
            "detail": str(exc),
            "fallback": "athenaeum_graph_search",
        }, indent=2)

    # Resolve query → entity name. Two-stage lookup:
    #   1. entities.name (clean L1/L2-extracted entities, ER-P1+)
    #   2. warm_entities.name LIKE (noisy P4b fragments, fallback only)
    # The previous single-stage warm_entities lookup was the bottleneck
    # that made every query return 0/0: warm_entities is full of
    # sentence fragments, so LIKE 'Marvin' matched a fragment that
    # wasn't in the new entities table.
    resolved_name = None
    resolution_source = None
    try:
        from lib.ichor.entities.schema import get_conn as _resolve_conn  # type: ignore[import-untyped]
        _rc = _resolve_conn()
        try:
            # Stage 1: exact or prefix match against clean entities.
            # The new ER layer stores the names that graph_query can
            # actually walk, so this is the high-precision path.
            _row = _rc.execute(
                "SELECT name FROM entities "
                "WHERE name = ? OR name LIKE ? "
                "ORDER BY confidence DESC LIMIT 1",
                (query, f"{query}%"),
            ).fetchone()
            if _row:
                resolved_name = _row[0]
                resolution_source = "entities_exact_or_prefix"
            else:
                # Stage 2: substring fallback against warm_entities
                # (noisy but covers entities that haven't been promoted
                # to the new layer yet).
                # warm_entities columns: name, importance, trust, related_to
                # (no `confidence` column — the package spec used different naming)
                _row = _rc.execute(
                    "SELECT name FROM warm_entities WHERE name LIKE ? "
                    "ORDER BY importance DESC, trust DESC LIMIT 1",
                    (f"%{query}%",),
                ).fetchone()
                if _row:
                    resolved_name = _row[0]
                    resolution_source = "warm_entities_like"
        finally:
            _rc.close()
    except Exception as exc:
        resolution_source = f"resolve_failed: {exc!r}"

    if not resolved_name:
        return json.dumps({
            "error": "entity_not_found",
            "query": query,
            "suggestion": "Use athenaeum_graph_search to discover entity names first.",
        }, indent=2)

    # Clamp depth to the package's absolute max.
    depth = max(1, min(int(hops or 2), 7))
    # min_confidence defaults to 0.1 inside the package; we let it.

    try:
        conn = _er_get_conn()
        try:
            result = _er_graph_query(conn, resolved_name, depth=depth)
        finally:
            conn.close()
    except Exception as exc:
        return json.dumps({
            "error": "graph_query_failed",
            "entity": resolved_name,
            "depth": depth,
            "detail": str(exc),
        }, indent=2)

    # Add resolution provenance so callers can see what we matched.
    if isinstance(result, dict):
        result = dict(result)
        result["resolved_from"] = query
        result["resolved_entity"] = resolved_name
        result["resolution_source"] = resolution_source

    if output_markdown:
        # Render compact markdown — caller asked for human-readable.
        nodes = result.get("nodes", []) if isinstance(result, dict) else []
        edges = result.get("edges", []) if isinstance(result, dict) else []
        stats = result.get("stats", {}) if isinstance(result, dict) else {}
        lines = [
            f"# Graph neighborhood: {resolved_name}",
            f"_resolved from: {query!r} (depth={depth}, source={resolution_source})_",
            "",
            f"**Stats:** {stats}",
            "",
            f"## Nodes ({len(nodes)})",
        ]
        for n in nodes[:max_results]:
            lines.append(f"- {n.get('name', n.get('id', '?'))} ({n.get('type', '?')})")
        lines.append("")
        lines.append(f"## Edges ({len(edges)})")
        for e in edges[:max_results]:
            lines.append(
                f"- {e.get('source', '?')} —[{e.get('type', '?')}]→ "
                f"{e.get('target', '?')} (conf={e.get('confidence', '?')})"
            )
        return "\n".join(lines)

    return json.dumps(result, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: ichor_l2_stats
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Read-only stats on the L2 entity/relationship extractor (ER-P2). Shows how many provisional entities and relationships exist, how many LLM extractions have been logged, and how many distinct types are in use. Cheap — pure SQL count queries against the live ichor.db."
)
def ichor_l2_stats() -> str:
    """L2 extraction stats. No side effects.

    Returns:
        JSON with: llm_extractions_logged, provisional_entities,
        provisional_relationships, llm_entity_types. Plus a
        derivation from cold_events count for context.
    """
    try:
        from lib.ichor.entities import l2_stats as _l2_stats  # type: ignore[import-untyped]
        from lib.ichor.entities.schema import get_conn as _get_conn  # type: ignore[import-untyped]
    except Exception as exc:
        return json.dumps({
            "error": "entities_layer_unavailable",
            "detail": str(exc),
        }, indent=2)

    try:
        conn = _get_conn()
        try:
            stats = _l2_stats(conn)
            # Augment with raw table counts for context
            stats["_raw_counts"] = {
                "entities": conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                "entity_facts": conn.execute("SELECT COUNT(*) FROM entity_facts").fetchone()[0],
                "entity_types": conn.execute("SELECT COUNT(*) FROM entity_types").fetchone()[0],
                "relationships": conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0],
                "relationship_types": conn.execute("SELECT COUNT(*) FROM relationship_types").fetchone()[0],
                "extraction_log": conn.execute("SELECT COUNT(*) FROM extraction_log").fetchone()[0],
                "cold_events": conn.execute("SELECT COUNT(*) FROM cold_events").fetchone()[0],
            }
        finally:
            conn.close()
    except Exception as exc:
        return json.dumps({
            "error": "l2_stats_failed",
            "detail": str(exc),
        }, indent=2)

    return json.dumps(stats, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: ichor_extract_entities
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Run one incremental pass of the L2 LLM entity/relationship extractor (ER-P2). Reads up to `batch_size` cold events past `last_event_id`, calls the configured LLM, stores extracted entities + relationships as provisional. Use `dry_run=true` to build the prompt without calling the LLM (debug). Without an API key in the env, returns a clean error envelope rather than crashing."
)
def ichor_extract_entities(
    last_event_id: int = 0,
    batch_size: int = 25,
    provider: str = "minimax",
    model: str = "",
    dry_run: bool = False,
    session_id: str = "",
) -> str:
    """Run one L2 extraction pass.

    Args:
        last_event_id: Process cold events with id > this. Use the
            highest id from a prior `ichor_extract_entities` call's
            `last_event_id_after`, or 0 to start fresh.
        batch_size: Cap on events per call. Default 25 (matches the
            package's "every 25 turns" cadence). Max 200.
        provider: Hermes provider name (must exist in
            ~/.hermes/config.yaml providers.<name>). Default
            "minimax" — the active profile.
        model: Optional model override. Default = provider's
            default_model from config.
        dry_run: If True, build the prompt and return it without
            calling the LLM. Useful for debugging the prompt
            construction and validating the wiring.
        session_id: Optional tag stored with extraction_log entries
            so you can correlate runs to sessions.

    Returns:
        JSON with: events_in_batch, last_event_id_after, stored
        counts (entity_types_created, rel_types_created,
        entities_created, relationships_created,
        extraction_logs_inserted), and any parse_warnings from the
        LLM response. On error: structured error envelope.
    """
    # Clamp batch_size to a sensible upper bound.
    batch_size = max(1, min(int(batch_size or 25), 200))

    try:
        from lib.ichor.entities import extract_incremental  # type: ignore[import-untyped]
        from lib.ichor.entities.schema import get_conn as _get_conn  # type: ignore[import-untyped]
        from lib.ichor.llm import _resolve_llm_provider  # type: ignore[import-untyped]
    except Exception as exc:
        return json.dumps({
            "error": "entities_layer_unavailable",
            "detail": str(exc),
        }, indent=2)

    # Resolve provider config from Hermes. The package's
    # extract_incremental requires a non-None provider_cfg.
    provider_cfg = _resolve_llm_provider("marvin") or _resolve_llm_provider(provider)
    if not isinstance(provider_cfg, dict):
        return json.dumps({
            "error": "llm_provider_not_configured",
            "provider": provider,
            "fix": f"Add a `providers.{provider}` block to ~/.hermes/config.yaml with api/default_model/api_key, "
                   f"or set the {provider.upper()}_API_KEY env var.",
        }, indent=2)

    # Surface the no-key condition explicitly so callers don't see a
    # 401 buried in a stack trace.
    import os as _os
    api_key = provider_cfg.get("api_key") or _os.environ.get(
        f"{(provider_cfg.get('name') or provider).upper()}_API_KEY", ""
    )
    if not api_key:
        return json.dumps({
            "error": "llm_provider_no_api_key",
            "provider": provider_cfg.get("name", provider),
            "api_base": provider_cfg.get("api", ""),
            "default_model": provider_cfg.get("default_model", ""),
            "fix": f"Set the {(provider_cfg.get('name') or provider).upper()}_API_KEY env var, "
                   f"or add api_key to providers.{provider} in ~/.hermes/config.yaml.",
            "hint": "Re-run with dry_run=true to validate wiring without a key.",
        }, indent=2)

    if dry_run:
        # Build the prompt that _would_ go to the LLM, return it
        # without calling. Useful for debugging the prompt shape
        # and for confirming the wiring reaches extract_batch.
        try:
            from lib.ichor.entities.l2_llm import build_prompt, _events_for_batch  # type: ignore[import-untyped]
        except Exception as exc:
            return json.dumps({
                "error": "dry_run_import_failed",
                "detail": str(exc),
            }, indent=2)
        try:
            conn = _get_conn()
            try:
                rows = _events_for_batch(conn, int(last_event_id), batch_size)
            finally:
                conn.close()
        except Exception as exc:
            return json.dumps({
                "error": "dry_run_fetch_failed",
                "detail": str(exc),
            }, indent=2)
        if not rows:
            return json.dumps({
                "dry_run": True,
                "events_in_batch": 0,
                "last_event_id_before": last_event_id,
                "last_event_id_after": last_event_id,
                "skipped": "no events past last_event_id",
            }, indent=2)
        texts = [r["raw_text"] for r in rows]
        prompt = build_prompt(texts)
        return json.dumps({
            "dry_run": True,
            "events_in_batch": len(rows),
            "last_event_id_before": last_event_id,
            "last_event_id_after": int(rows[-1]["id"]),
            "prompt_chars": len(prompt),
            "prompt_preview": prompt[:500] + ("..." if len(prompt) > 500 else ""),
            "would_call": {
                "provider": provider_cfg.get("name", provider),
                "api": provider_cfg.get("api", ""),
                "model": model or provider_cfg.get("default_model", ""),
            },
        }, indent=2)

    # Real call path.
    try:
        conn = _get_conn()
        try:
            result = extract_incremental(
                conn,
                last_event_id=int(last_event_id),
                batch_size=batch_size,
                provider_cfg=provider_cfg,
                model=model or None,
                session_id=session_id or None,
            )
        finally:
            conn.close()
    except Exception as exc:
        return json.dumps({
            "error": "extract_incremental_failed",
            "last_event_id": last_event_id,
            "batch_size": batch_size,
            "detail": str(exc),
        }, indent=2)

    return json.dumps(result, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: system_health
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Check the health of Pantheon systems: ChromaDB, Athenaeum filesystem, and embedding service.",
)
def system_health() -> str:
    """Quick health check of Pantheon infrastructure.

    Returns:
        Status of each system component.
    """
    results = {}

    # ChromaDB
    chroma_ok = False
    chroma_count = 0
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        client.heartbeat()
        collections = client.list_collections()
        chroma_ok = True
        chroma_count = sum(c.count() for c in collections)
        results["chromadb"] = {
            "status": "ok",
            "collections": len(collections),
            "total_vectors": chroma_count,
        }
    except Exception as exc:
        results["chromadb"] = {"status": "error", "detail": str(exc)}

    # Athenaeum
    athenaeum_ok = _ATHENAEUM_ROOT.is_dir()
    if athenaeum_ok:
        codexes = _list_codexes()
        total_files = sum(
            1 for c in codexes
            for f in (_ATHENAEUM_ROOT / c).rglob("*")
            if f.is_file() and f.name != "INDEX.md"
        )
        results["athenaeum"] = {
            "status": "ok",
            "codexes": len(codexes),
            "total_files": total_files,
            "root": str(_ATHENAEUM_ROOT),
        }
    else:
        results["athenaeum"] = {"status": "missing", "root": str(_ATHENAEUM_ROOT)}

    # Embedding service
    embedder = _Embedder()
    results["embedding"] = {
        "status": "ok" if embedder.is_available() else "unavailable",
        "provider": "openrouter" if embedder.use_openrouter else "ollama (local)",
    }

    # Messaging system
    msgs_ok = _MESSAGES_DIR.is_dir()
    if msgs_ok:
        inboxes = [
            d.name for d in _MESSAGES_DIR.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
        results["messaging"] = {
            "status": "ok",
            "inboxes": inboxes,
        }
    else:
        results["messaging"] = {"status": "missing", "root": str(_MESSAGES_DIR)}

    results["_real_home"] = _REAL_HOME
    return json.dumps(results, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: system_current_model
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Get the current model and provider for a session or active profile. "
    "Returns model name, provider, config source, and whether the model was recently changed. "
    "Call this from the agent to verify a model change took effect on the backend.",
)
def system_current_model(
    session_id: str = "",
    profile_name: str = "",
) -> str:
    """Retrieve the current model configuration for a running session or god profile.

    Args:
        session_id: Optional WebUI session ID to look up. When provided, checks the
                    WebUI session index first for the per-session model override.
        profile_name: Optional god/profile name (e.g. 'hephaestus', 'hermes').
                      Defaults to the active Hermes profile.

    Returns:
        JSON with model, provider, source, and whether a recent change was detected.
    """
    import subprocess
    import yaml
    from pathlib import Path

    result = {
        "model": None,
        "provider": None,
        "source": None,
        "base_url": None,
        "recently_changed": False,
    }

    hermes_home = Path(f"{_REAL_HOME}/.hermes")

    # ── Step 1: If session_id given, check WebUI session index ──
    webui_session = None
    if session_id:
        index_path = hermes_home / "webui" / "sessions" / "_index.json"
        if index_path.exists():
            try:
                idx_data = json.loads(index_path.read_text(encoding="utf-8"))
                for entry in idx_data:
                    if entry.get("session_id") == session_id and entry.get("model"):
                        webui_session = entry
                        break
            except Exception:
                pass
        # If not found in index, try direct session file
        if not webui_session:
            sess_file = hermes_home / "webui" / "sessions" / f"{session_id}.json"
            if sess_file.exists():
                try:
                    sess_data = json.loads(sess_file.read_text(encoding="utf-8"))
                    if sess_data.get("model"):
                        webui_session = sess_data
                except Exception:
                    pass

        if webui_session:
            result["model"] = webui_session.get("model", result["model"])
            result["provider"] = webui_session.get("model_provider", result["provider"])
            result["source"] = "session_override"

    # ── Step 2: Read profile config for the default model ──
    if not profile_name:
        # Try to detect active profile from running gateway processes
        try:
            ps_out = subprocess.run(
                ["ps", "aux"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            for line in ps_out.splitlines():
                if "--profile" in line and "gateway" in line:
                    for i, p in enumerate(line.split()):
                        if p == "--profile" and i + 1 < len(line.split()):
                            candidate = line.split()[i + 1].strip()
                            if candidate:
                                profile_name = candidate
                                break
                    if profile_name:
                        break
        except Exception:
            pass

    if not profile_name:
        # Fallback: check active Hermes config
        profile_name = "hephaestus"  # sensible default

    # Try profile config first, then main config
    config_sources = [
        hermes_home / "profiles" / profile_name / "config.yaml",
        hermes_home / "config.yaml",
    ]
    for cfg_path in config_sources:
        if cfg_path.exists():
            try:
                with open(str(cfg_path), "r") as f:
                    cfg = yaml.safe_load(f) or {}
                model_cfg = cfg.get("model", {})
                if isinstance(model_cfg, str):
                    profile_model = model_cfg
                    profile_provider = None
                elif isinstance(model_cfg, dict):
                    profile_model = model_cfg.get("default", model_cfg.get("model"))
                    profile_provider = model_cfg.get("provider")
                    base_url = model_cfg.get("base_url", "")
                    if base_url:
                        result["base_url"] = base_url
                else:
                    profile_model = None
                    profile_provider = None

                if profile_model and not result.get("model"):
                    result["model"] = profile_model
                if profile_provider and not result.get("provider"):
                    result["provider"] = profile_provider
                if not result.get("source"):
                    source_path = str(cfg_path)
                    if "profiles" in source_path:
                        result["source"] = f"profile:{profile_name}"
                    else:
                        result["source"] = "main_config"
                break
            except Exception:
                pass

    # ── Step 3: Check Ichor for recent model-change events ──
    try:
        import sqlite3
        ichor_db = hermes_home / "ichor.db"
        if ichor_db.exists():
            conn = sqlite3.connect(str(ichor_db))
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT raw_text, created_at FROM ichor_events "
                "WHERE event_type = 'model_change' AND created_at > ? "
                "ORDER BY created_at DESC LIMIT 1",
                (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 300)),),  # last 5 minutes
            ).fetchone()
            if row:
                result["recently_changed"] = True
                try:
                    change_data = json.loads(row["raw_text"])
                    result["previous_model"] = change_data.get("previous_model")
                    result["change_timestamp"] = change_data.get("iso_timestamp", row["created_at"])
                except (json.JSONDecodeError, TypeError):
                    pass
            conn.close()
    except Exception:
        pass

    return json.dumps(result, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: skill_list
# ═══════════════════════════════════════════════════════════════════════════

_SKILLS_ROOT = Path(f"{_REAL_HOME}/athenaeum/skills")


@mcp.tool(
    description="List all shared skills available in the Pantheon skills hub. Each skill has a name, description, and script that can be executed via skill_run.",
)
def skill_list(
    details: bool = False,
) -> str:
    """List all shared skills in the Pantheon skills hub.

    Args:
        details: If True, include full description and available args. Default: False.

    Returns:
        List of available skills with metadata.
    """
    if not _SKILLS_ROOT.is_dir():
        return json.dumps({"error": "Skills hub not found"}, indent=2)

    skills = []
    for d in sorted(_SKILLS_ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        skill_file = d / "skill.yaml"
        if not skill_file.exists():
            continue
        try:
            import yaml
            skill_data = yaml.safe_load(skill_file.read_text(encoding="utf-8"))
            entry = {
                "name": skill_data.get("name", d.name),
                "description": skill_data.get("description", ""),
                "script": skill_data.get("script", ""),
            }
            if details and "args" in skill_data:
                entry["args"] = skill_data["args"]
            skills.append(entry)
        except Exception as exc:
            skills.append({"name": d.name, "description": f"(error: {exc})"})

    return json.dumps({"skills": skills, "count": len(skills)}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: skill_info
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool(
    description="Get detailed information about a specific skill: its name, description, arguments, and the full contents of its skill.yaml manifest.",
)
def skill_info(
    name: str,
) -> str:
    """Get detailed info about a specific shared skill.

    Args:
        name: The skill name (matches the directory name under skills/).

    Returns:
        Full skill manifest and available metadata.
    """
    skill_dir = _SKILLS_ROOT / name
    skill_file = skill_dir / "skill.yaml"
    if not skill_file.exists():
        return json.dumps({"error": f"Skill '{name}' not found"}, indent=2)

    try:
        import yaml
        skill_data = yaml.safe_load(skill_file.read_text(encoding="utf-8"))
        return json.dumps({"skill": skill_data}, indent=2)
    except Exception as exc:
        return json.dumps({"error": f"Failed to read skill: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: skill_run
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool(
    description="Execute a shared skill by name with the given arguments. Returns the script's stdout/stderr output. Use skill_list to discover available skills and skill_info to see what arguments each requires.",
)
def skill_run(
    name: str,
    arguments: str = "[]",
) -> str:
    """Execute a shared skill script.

    Args:
        name: The skill name (matches the directory in athenaeum/skills/).
        arguments: JSON array of string arguments to pass to the script
                  (e.g. '["Title", "Description"]' or '["--section", "heph-suggestions", "Title", "Desc", "high"]').

    Returns:
        The script stdout output, or error details.
    """
    import subprocess

    skill_dir = _SKILLS_ROOT / name
    skill_file = skill_dir / "skill.yaml"
    if not skill_file.exists():
        return json.dumps({"error": f"Skill '{name}' not found"}, indent=2)

    try:
        import yaml
        skill_data = yaml.safe_load(skill_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return json.dumps({"error": f"Failed to read skill manifest: {exc}"}, indent=2)

    script_rel = skill_data.get("script", "")
    if not script_rel:
        return json.dumps({"error": f"Skill '{name}' has no script defined"})

    script_path = skill_dir / script_rel
    if not script_path.exists():
        return json.dumps({"error": f"Script '{script_rel}' not found for skill '{name}'"}, indent=2)

    # Parse arguments
    try:
        args_list = json.loads(arguments) if isinstance(arguments, str) else arguments
    except json.JSONDecodeError:
        return json.dumps({"error": f"Invalid arguments JSON: {arguments}"}, indent=2)

    if not isinstance(args_list, list):
        return json.dumps({"error": "arguments must be a JSON array"}, indent=2)

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)] + [str(a) for a in args_list],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output_parts = []
        if result.stdout.strip():
            output_parts.append(result.stdout.strip())
        if result.stderr.strip():
            output_parts.append(f"[stderr]\n{result.stderr.strip()}")
        return json.dumps({
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "output": "\n".join(output_parts) if output_parts else "(no output)",
        }, indent=2)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "Script execution timed out (30s limit)"}, indent=2)
    except Exception as exc:
        return json.dumps({"error": f"Script execution failed: {exc}"}, indent=2)


# ═══════════════════════════════════════════════════════════════════════════
# Graph search
# ═══════════════════════════════════════════════════════════════════════════


@mcp.tool(
    description="[WARM TABLE P4b] Entity/relationship search via the new 5-tier schema. Queries the WARM table (warm_entities) directly with a `related_to` column for graph-style relationships. Replaces graph.db.",
)
def athenaeum_graph_search(
    query: str = "",
    entity_type: str = "",
    entity_name: str = "",
    neighbor_of: str = "",
    path_between: str = "",
    max_depth: int = 2,
    limit: int = 20,
) -> str:
    """Search entities via the WARM table + related_to column.

    P4b implementation: replaces graph.db. Entities are rows in warm_entities;
    relationships are encoded as comma-separated 'cat:name' references in the
    `related_to` column (Rule 43 keeps it drift-proof).

    Modes (use ONE at a time):
    1. entity_name= — exact or fuzzy match on warm_entities.name
    2. entity_type= — filter by category
    3. neighbor_of= — find entities that reference this one in their related_to
    4. path_between= — return both endpoints + their related_to (shallow path)
    5. query= — general LIKE search on name/value

    Note: graph.db's BFS path-finding is replaced with a 1-hop related_to
    lookup. For deeper paths, use multiple chained queries.

    Args:
        query: General search term (matches name or value).
        entity_type: Filter by warm_entities.category.
        entity_name: Exact or fuzzy name match.
        neighbor_of: Entity name to find references to (1-hop neighbors).
        path_between: Two comma-separated names to find paths between.
        max_depth: (Deprecated — kept for API compat. Real max depth is 1.)
        limit: Max results (1-50). Default: 20.

    Returns:
        JSON string with search results.
    """
    import sqlite3
    from pathlib import Path as _P
    db_path = _P.home() / ".hermes" / "ichor.db"

    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.row_factory = sqlite3.Row
    except Exception as exc:
        return json.dumps({"error": f"Cannot open ichor.db: {exc}"}, indent=2)

    try:
        results = {
            "mode": "",
            "query": query or entity_type or entity_name or neighbor_of or path_between,
            "results": [],
        }

        if path_between:
            # Shallow path: return both endpoints + their 1-hop neighbors
            results["mode"] = "path_between"
            parts = [p.strip() for p in path_between.split(",")]
            if len(parts) != 2:
                return json.dumps({"error": "path_between requires exactly 2 names separated by comma"}, indent=2)
            node_a, node_b = parts
            endpoint_rows = conn.execute(
                """SELECT id, category, name, value, importance, trust, related_to
                   FROM warm_entities
                   WHERE name LIKE ? OR name LIKE ?
                   ORDER BY importance DESC LIMIT 2""",
                (f"%{node_a}%", f"%{node_b}%"),
            ).fetchall()
            results["results"] = [dict(r) for r in endpoint_rows]
            results["note"] = "P4b paths are 1-hop (direct related_to). Chain queries for deeper traversal."

        elif neighbor_of:
            # Find entities whose related_to references this name
            results["mode"] = "neighbors"
            center = conn.execute(
                "SELECT id, category, name, value, related_to FROM warm_entities WHERE name LIKE ? LIMIT 1",
                (f"%{neighbor_of}%",),
            ).fetchone()
            if not center:
                return json.dumps({"error": f"Entity '{neighbor_of}' not found in warm_entities"}, indent=2)
            results["center"] = dict(center)
            # Find references in either direction
            neighbor_rows = conn.execute(
                """SELECT id, category, name, value, importance, trust, related_to
                   FROM warm_entities
                   WHERE related_to LIKE ? OR name LIKE ?
                   ORDER BY importance DESC LIMIT ?""",
                (f"%{neighbor_of}%", f"%{neighbor_of}%", limit),
            ).fetchall()
            results["results"] = [dict(r) for r in neighbor_rows]

        elif entity_name:
            results["mode"] = "entity_name"
            rows = conn.execute(
                """SELECT id, category, name, value, importance, trust, maturity, related_to, created_at, updated_at
                   FROM warm_entities
                   WHERE name LIKE ?
                   ORDER BY importance DESC LIMIT ?""",
                (f"%{entity_name}%", limit),
            ).fetchall()
            results["results"] = [dict(r) for r in rows]

        elif entity_type:
            results["mode"] = "entity_type"
            rows = conn.execute(
                """SELECT id, category, name, value, importance, trust, maturity, related_to, created_at, updated_at
                   FROM warm_entities
                   WHERE category = ?
                   ORDER BY importance DESC LIMIT ?""",
                (entity_type, limit),
            ).fetchall()
            results["results"] = [dict(r) for r in rows]

        elif query:
            results["mode"] = "query"
            rows = conn.execute(
                """SELECT id, category, name, value, importance, trust, maturity, related_to, created_at, updated_at
                   FROM warm_entities
                   WHERE name LIKE ? OR value LIKE ?
                   ORDER BY importance DESC LIMIT ?""",
                (f"%{query}%", f"%{query}%", limit),
            ).fetchall()
            results["results"] = [dict(r) for r in rows]

        else:
            return json.dumps({
                "error": "Specify at least one of: query, entity_type, entity_name, neighbor_of, path_between"
            }, indent=2)

        results["count"] = len(results["results"])
        return json.dumps(results, indent=2, default=str)

    except Exception as exc:
        return json.dumps({"error": f"WARM table search failed: {type(exc).__name__}: {exc}"}, indent=2)
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Pantheon MCP Server")
    parser.add_argument("--stdio", action="store_true", help="Run in stdio mode (for Hermes subprocess)")
    parser.add_argument("--port", type=int, default=8010, help="HTTP port (default: 8010)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.stdio:
        logger.info("Starting Pantheon MCP server in stdio mode...")
        mcp.run(transport="stdio")
    else:
        logger.info("Starting Pantheon MCP server on %s:%s...", args.host, args.port)

        # Build the base Starlette app from FastMCP
        import uvicorn

        starlette_app = mcp.streamable_http_app()

        # ── Middleware: handle bare GET /mcp gracefully ──────────────────
        # FastMCP's StreamableHTTP returns 406 when a GET request arrives
        # without Accept: text/event-stream.  The Hermes MCP client probes
        # with a bare GET during transport negotiation, so we intercept
        # that here and return a friendly info response instead.
        async def graceful_mcp_app(scope, receive, send):
            if scope["type"] == "http" and scope["method"] == "GET":
                path = scope.get("path", "")
                # Normalise trailing-slash
                if path.rstrip("/") == "/mcp":
                    # Check for Accept: text/event-stream
                    accept_hdr = b""
                    for k, v in scope.get("headers", []):
                        if k.lower() == b"accept":
                            accept_hdr = v
                            break
                    if b"text/event-stream" not in accept_hdr:
                        body = json.dumps({
                            "jsonrpc": "2.0", "id": "info",
                            "result": {
                                "server": "Pantheon MCP Server",
                                "transport": "streamable-http",
                                "message": (
                                    "Send POST with Content-Type: application/json "
                                    "for JSON-RPC calls, or GET with Accept: "
                                    "text/event-stream for SSE"
                                ),
                            },
                        }).encode()
                        await send({
                            "type": "http.response.start",
                            "status": 200,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()),
                                (b"access-control-allow-origin", b"*"),
                            ],
                        })
                        await send({"type": "http.response.body", "body": body})
                        return
            await starlette_app(scope, receive, send)

        config = uvicorn.Config(
            graceful_mcp_app,
            host=args.host,
            port=args.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        server.run()


if __name__ == "__main__":
    main()
