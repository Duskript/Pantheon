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
from typing import Any, List, Optional

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REAL_HOME = "/home/konan"
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
    """Thin embedding wrapper — OpenRouter first, Ollama fallback."""

    def __init__(self):
        self._api_key = os.environ.get("OPENROUTER_API_KEY", "")
        self._model = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
        self._timeout = 30.0

    @property
    def use_openrouter(self) -> bool:
        return bool(self._api_key)

    def embed(self, text: str) -> List[float]:
        import httpx

        if self.use_openrouter:
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
- **Hades** — nightly consolidation reports
- **God Roster** — registered god information

All tools are Codex-aware: you can scope searches, reads, and writes to specific
Codices (Codex-Forge, Codex-Pantheon, Codex-Infrastructure, etc.).
""",
    host="127.0.0.1",
    port=8010,
    log_level="INFO",
)


# ═══════════════════════════════════════════════════════════════════════════
# Tool: athenaeum_search
# ═══════════════════════════════════════════════════════════════════════════

@mcp.tool(
    description="Semantic search across the Athenaeum. Finds relevant content by meaning, not keywords. Returns content, source, and Codex for each result.",
)
def athenaeum_search(
    query: str,
    codexes: Optional[List[str]] = None,
    n_results: int = 5,
) -> str:
    """Search the Athenaeum using semantic vector search via ChromaDB.

    Args:
        query: Natural language query to search for.
        codexes: Optional list of Codexes to restrict search to (e.g. ["Codex-Forge", "Codex-Pantheon"]).
                Default: search all available Codexes.
        n_results: Maximum number of results to return (1-20). Default: 5.

    Returns:
        JSON string with results: [{content, source, codex, score}]
    """
    client = _get_chroma_client()
    if client is None:
        return json.dumps({"error": "ChromaDB is not available"}, indent=2)

    embedder = _Embedder()
    if not embedder.is_available():
        return json.dumps({"error": "No embedding service available (neither OpenRouter nor Ollama)"}, indent=2)

    # Determine which Codexes to search
    all_codexes = _list_codexes()
    if codexes:
        targets = [c for c in codexes if c in all_codexes]
    else:
        targets = all_codexes

    if not targets:
        return json.dumps({"error": "No Codexes found in Athenaeum"}, indent=2)

    # Determine dimension from first embed call
    try:
        query_embedding = embedder.embed(query[:512])  # Keep query short
    except Exception as exc:
        return json.dumps({"error": f"Embedding failed: {exc}"}, indent=2)

    results = []
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

                # Convert distance to similarity score (0-1 range)
                score = max(0.0, 1.0 - dist) if dist else 0.0

                # Truncate content for display
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

    # Sort by score descending, cap at requested n_results
    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:n_results]

    if not results:
        return json.dumps({"results": [], "note": f"No matches found for query in {len(targets)} Codexes"}, indent=2)

    return json.dumps({"results": results, "total": len(results)}, indent=2)


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
        # Run as StreamableHTTP server using FastMCP's built-in runner
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
