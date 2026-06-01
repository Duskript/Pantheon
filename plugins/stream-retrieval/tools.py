"""Stream retrieval tool implementations.

All 6 tools return JSON strings. Empty results return '[]' or '{}'.
Never crash on missing data — every path handles FileNotFoundError,
empty directories, and malformed data gracefully.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("stream_retrieval_plugin")

# ── Data paths ──────────────────────────────────────────────────────────────

ATHENAEUM = Path.home() / "athenaeum"
CODEX_STREAM = ATHENAEUM / "Codex-Stream"
RAW_DIR = CODEX_STREAM / "raw"
ENTITIES_DIR = CODEX_STREAM / "entities"
HOTNESS_PATH = CODEX_STREAM / "hotness.json"
COOCCURRENCE_PATH = CODEX_STREAM / "cooccurrence.jsonl"

# Ichor graph database (may not exist)
ICHOR_GRAPH = Path.home() / ".hermes" / "ichor" / "graph.db"


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _find_chunks(query: str | None = None, source: str | None = None,
                 max_results: int = 10) -> list[dict]:
    """Search raw chunks by content (grep) and optional source filter."""
    results = []
    search_root = RAW_DIR / source if source else RAW_DIR

    if not search_root.exists():
        return []

    # Walk all .md files
    for md_file in search_root.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        # If query provided, check if file contains it (case-insensitive)
        if query and query.lower() not in content.lower():
            continue

        # Extract frontmatter for metadata
        metadata = _parse_frontmatter(content)
        body = _strip_frontmatter(content)

        # Determine source from path: raw/{source}/{date}/{chunk_id}.md
        parts = md_file.relative_to(RAW_DIR).parts
        detected_source = parts[0] if len(parts) > 0 else "unknown"
        date_str = parts[1] if len(parts) > 1 else ""

        results.append({
            "path": str(md_file.relative_to(ATHENAEUM)),
            "chunk_id": md_file.stem,
            "source": metadata.get("source", detected_source),
            "provider": metadata.get("provider", ""),
            "date": date_str,
            "title": metadata.get("title", md_file.stem),
            "snippet": body[:300].strip(),
            "size_chars": len(content),
        })

    # Sort by date descending, limit
    results.sort(key=lambda r: r["date"], reverse=True)
    return results[:max_results]


def _parse_frontmatter(content: str) -> dict[str, str]:
    """Extract YAML-style frontmatter (--- ... ---)."""
    if not content.startswith("---"):
        return {}
    try:
        end = content.index("---", 3)
        fm = content[3:end]
        meta = {}
        for line in fm.strip().split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        return meta
    except (ValueError, IndexError):
        return {}


def _strip_frontmatter(content: str) -> str:
    """Remove frontmatter block."""
    if not content.startswith("---"):
        return content
    try:
        end = content.index("---", 3)
        return content[end + 3:].strip()
    except (ValueError, IndexError):
        return content


def _load_hotness() -> dict:
    """Load hotness.json, returning empty dict on any error."""
    try:
        if HOTNESS_PATH.exists():
            return json.loads(HOTNESS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("Failed to load hotness.json: %s", e)
    return {"entities": []}


def _load_cooccurrence(entity_name: str) -> list[str]:
    """Load co-occurring entities from JSONL file."""
    if not COOCCURRENCE_PATH.exists():
        return []
    entities = set()
    try:
        for line in COOCCURRENCE_PATH.read_text(encoding="utf-8").strip().split("\n"):
            if not line:
                continue
            record = json.loads(line)
            ents = record.get("entities", [])
            if entity_name in ents:
                entities.update(e for e in ents if e != entity_name)
    except Exception as e:
        logger.debug("Cooccurrence load error: %s", e)
    return sorted(entities)[:20]


def _query_ichor(entity_name: str) -> list[dict]:
    """Query Ichor graph for entity neighbors."""
    if not ICHOR_GRAPH.exists():
        return []

    try:
        db = sqlite3.connect(str(ICHOR_GRAPH))
        db.row_factory = sqlite3.Row
        cur = db.execute("""
            SELECT DISTINCT e2.name, e2.type, r.type as rel_type
            FROM entities e1
            JOIN relationships r ON r.source_id = e1.id
            JOIN entities e2 ON r.target_id = e2.id
            WHERE e1.name = ?
            UNION
            SELECT DISTINCT e2.name, e2.type, r.type as rel_type
            FROM entities e1
            JOIN relationships r ON r.target_id = e1.id
            JOIN entities e2 ON r.source_id = e2.id
            WHERE e1.name = ?
        """, (entity_name, entity_name))
        rows = [{"entity": r["name"], "type": r["type"], "relationship": r["rel_type"]} for r in cur.fetchall()]
        db.close()
        return rows
    except Exception as e:
        logger.debug("Ichor query error: %s", e)
        return []


# ══════════════════════════════════════════════════════════════════════════════
# Tool 1: stream_search
# ══════════════════════════════════════════════════════════════════════════════


def stream_search(query: str = "", max_results: int = 10, source: str = "") -> str:
    """Search ingested content chunks by keyword. Returns ranked JSON array."""
    results = _find_chunks(
        query=query.strip() if query else None,
        source=source.strip() if source else None,
        max_results=max(max_results, 100),
    )
    logger.info("stream_search('%s') → %d results", query[:50], len(results))
    return json.dumps(results, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════════
# Tool 2: stream_filter
# ══════════════════════════════════════════════════════════════════════════════


def stream_filter(source: str = "", date_from: str = "", date_to: str = "",
                  max_results: int = 20) -> str:
    """Filter chunks by source provider and/or date range."""
    results = _find_chunks(
        source=source.strip() if source else None,
        max_results=max(max_results, 200),
    )

    # Date filtering
    if date_from or date_to:
        filtered = []
        for r in results:
            date_str = r.get("date", "")
            if date_str:
                try:
                    chunk_date = datetime.strptime(date_str, "%Y-%m-%d")
                    if date_from:
                        from_d = datetime.strptime(date_from, "%Y-%m-%d")
                        if chunk_date < from_d:
                            continue
                    if date_to:
                        to_d = datetime.strptime(date_to, "%Y-%m-%d")
                        if chunk_date > to_d:
                            continue
                except ValueError:
                    pass
            filtered.append(r)
        results = filtered

    logger.info("stream_filter(source=%s, from=%s, to=%s) → %d results",
                source, date_from, date_to, len(results))
    return json.dumps(results[:max_results], ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════════
# Tool 3: stream_entity
# ══════════════════════════════════════════════════════════════════════════════


def stream_entity(entity_name: str = "") -> str:
    """Look up all chunks mentioning an entity, plus co-occurring entities."""
    if not entity_name:
        return json.dumps({"error": "entity_name required"}, ensure_ascii=False)

    # Find chunks mentioning the entity
    chunks = _find_chunks(query=entity_name, max_results=50)
    cooccurring = _load_cooccurrence(entity_name)

    # Check hotness
    hotness = _load_hotness()
    mentions = 0
    for e in hotness.get("entities", []):
        if e.get("name", "").lower() == entity_name.lower():
            mentions = e.get("mentions", 0)
            break

    result = {
        "entity": entity_name,
        "mentions": mentions,
        "chunks": chunks,
        "cooccurring_entities": cooccurring,
    }
    logger.info("stream_entity('%s') → %d chunks, %d co-occurring",
                entity_name, len(chunks), len(cooccurring))
    return json.dumps(result, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════════
# Tool 4: stream_trending
# ══════════════════════════════════════════════════════════════════════════════


def stream_trending(min_mentions: int = 3, max_results: int = 20) -> str:
    """Return top trending entities by mention count."""
    hotness = _load_hotness()
    entities = hotness.get("entities", [])

    # Filter by min_mentions and sort by mentions descending
    filtered = [e for e in entities if e.get("mentions", 0) >= min_mentions]
    filtered.sort(key=lambda e: e.get("mentions", 0), reverse=True)

    results = filtered[:max_results]
    logger.info("stream_trending(min=%d) → %d entities", min_mentions, len(results))
    return json.dumps(results, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════════
# Tool 5: stream_connections
# ══════════════════════════════════════════════════════════════════════════════


def stream_connections(entity_name: str = "") -> str:
    """Find entity neighbors in the Ichor knowledge graph."""
    if not entity_name:
        return json.dumps({"error": "entity_name required"}, ensure_ascii=False)

    # Try Ichor graph first, fall back to cooccurrence JSONL
    connections = _query_ichor(entity_name)

    if not connections:
        # Fallback: cooccurrence data
        cooccurring = _load_cooccurrence(entity_name)
        connections = [{"entity": e, "type": "unknown", "relationship": "co-occurs"} for e in cooccurring]

    result = {
        "entity": entity_name,
        "connections": connections,
        "source": "ichor_graph" if ICHOR_GRAPH.exists() else "cooccurrence_jsonl",
    }
    logger.info("stream_connections('%s') → %d connections", entity_name, len(connections))
    return json.dumps(result, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════════
# Tool 6: stream_fetch_chunks
# ══════════════════════════════════════════════════════════════════════════════


def stream_fetch_chunks(chunk_ids: list[str] | None = None) -> str:
    """Fetch full content of specific chunks by path or ID."""
    if not chunk_ids:
        return json.dumps({"error": "chunk_ids required (list of paths)"}, ensure_ascii=False)

    results = []
    for chunk_ref in chunk_ids[:20]:
        # Try as relative path from athenaeum root
        path = ATHENAEUM / chunk_ref
        if not path.exists():
            # Try as filename within raw/
            matches = list(RAW_DIR.rglob(f"{chunk_ref}.md")) + list(RAW_DIR.rglob(f"{chunk_ref}"))
            if matches:
                path = matches[0]
            else:
                results.append({"chunk_ref": chunk_ref, "error": "not found"})
                continue

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            results.append({
                "path": str(path.relative_to(ATHENAEUM)),
                "content": content[:5000],  # cap per chunk
                "size_chars": len(content),
                "truncated": len(content) > 5000,
            })
        except Exception as e:
            results.append({"chunk_ref": chunk_ref, "error": str(e)})

    logger.info("stream_fetch_chunks: %d/%d fetched", sum(1 for r in results if "content" in r), len(chunk_ids))
    return json.dumps(results, ensure_ascii=False)
