#!/usr/bin/env python3
"""Pantheon System Index — persistent, queryable index of the entire Pantheon.

Indexes all system components into an FTS5 SQLite database so gods can ask
"where is X" or "how does Y work" without grepping around.

Data sources indexed:
  - Filesystem layout (.py / .md / .yaml under ~/pantheon/, ~/athenaeum/)
  - MCP tools (parsed from @mcp.tool decorators in mcp_server.py)
  - Skills (walked from all profile skill directories + shared skills)
  - Cron jobs (parsed from cron manifest + runtime queries)
  - Gods (SOUL.md files, codex directories)
  - Workflows (pipeline docs, READMEs)
  - Pipelines (Hades, Dreamweaver, Subconscious, etc.)

Database location: ~/.hermes/pantheon/system-index.db
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("pantheon-index")

# ── Paths ──────────────────────────────────────────────────────────────

_REAL_HOME = os.path.expanduser("~konan")
_HOME = os.path.expanduser("~")

INDEX_DB_PATH = Path(f"{_REAL_HOME}/.hermes/pantheon/system-index.db")

PANTHEON_DIR = Path(f"{_REAL_HOME}/pantheon")
ATHENAEUM_DIR = Path(f"{_REAL_HOME}/athenaeum")
HERMES_DIR = Path(f"{_REAL_HOME}/.hermes")
PROFILES_DIR = HERMES_DIR / "profiles"
MCP_SERVER_PATH = PANTHEON_DIR / "pantheon-core" / "mcp_server.py"
CRON_MANIFEST = PANTHEON_DIR / "scripts" / "pantheon-cron-manifest.json"
GODS_DIR = PANTHEON_DIR / "gods"
SHARED_SKILLS_DIR = PANTHEON_DIR / "god-packages" / "shared-skills"
PANTHEON_CORE = PANTHEON_DIR / "pantheon-core"
SCRIPTS_DIR = PANTHEON_DIR / "scripts"
LIB_DIR = PANTHEON_DIR / "lib"

EMBEDDABLE_EXTS = {".py", ".md", ".yaml", ".yml", ".json", ".toml", ".cfg", ".conf", ".txt"}

# ── Schema ─────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS index_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT NOT NULL,       -- 'file', 'tool', 'skill', 'cron', 'god', 'workflow', 'pipeline'
    name        TEXT NOT NULL,
    path        TEXT,
    description TEXT,
    tags        TEXT,                -- JSON array of tags
    metadata    TEXT,                -- JSON blob with category-specific fields
    confidence  REAL DEFAULT 1.0,
    indexed_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS index_fts USING fts5(
    name, description, tags, metadata,
    content='index_entries',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE INDEX IF NOT EXISTS idx_entries_category ON index_entries(category);
CREATE INDEX IF NOT EXISTS idx_entries_name ON index_entries(name);

-- FTS5 virtual table (external-content: term index must be rebuilt after population)
CREATE VIRTUAL TABLE IF NOT EXISTS index_fts USING fts5(
    name, description, tags, metadata,
    content='index_entries',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS index_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


# ── Database ───────────────────────────────────────────────────────────


def _get_db() -> sqlite3.Connection:
    """Open (or create) the index database."""
    INDEX_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(INDEX_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Ensure all tables exist."""
    # Execute each statement separately (virtual table can't be in a batch)
    for stmt in SCHEMA_SQL.split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError as e:
                # "already exists" is fine for triggers
                if "already exists" not in str(e):
                    logger.warning("Schema statement warning: %s", e)
    conn.commit()


def _clear_index(conn: sqlite3.Connection) -> None:
    """Clear all indexed entries (but keep meta)."""
    conn.execute("DELETE FROM index_entries")
    conn.execute("DELETE FROM index_fts")
    conn.commit()


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()


def _get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM index_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


# ── Helpers ────────────────────────────────────────────────────────────


def _relative_path(abs_path: Path, root: Optional[Path] = None) -> str:
    """Get a human-readable relative path."""
    root = root or Path(_REAL_HOME)
    try:
        return str(abs_path.relative_to(root))
    except ValueError:
        return str(abs_path)


def _tags_from_path(path: Path) -> List[str]:
    """Infer tags from file extension and parent directories."""
    tags = []
    ext = path.suffix.lower()
    if ext:
        tags.append(ext.lstrip("."))
    # Parent dir tags
    for parent in path.parents:
        p = parent.name
        if p and not p.startswith("."):
            tags.append(p)
    return tags


def _insert(
    conn: sqlite3.Connection,
    category: str,
    name: str,
    path: Optional[str] = None,
    description: str = "",
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    confidence: float = 1.0,
) -> None:
    """Insert a single index entry."""
    conn.execute(
        """INSERT INTO index_entries (category, name, path, description, tags, metadata, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            category,
            name,
            path,
            description,
            json.dumps(tags or []),
            json.dumps(metadata or {}),
            confidence,
        ),
    )


# ── Indexers ───────────────────────────────────────────────────────────


def _index_files(conn: sqlite3.Connection) -> int:
    """Walk key Pantheon directories and index all code/config files."""
    count = 0
    scanned_dirs = [
        (PANTHEON_CORE, "pantheon-core"),
        (SCRIPTS_DIR, "scripts"),
        (LIB_DIR, "lib"),
        (GODS_DIR, "gods"),
        (SHARED_SKILLS_DIR, "shared-skills"),
        (ATHENAEUM_DIR, "athenaeum"),
    ]

    for base_dir, category_prefix in scanned_dirs:
        if not base_dir.exists():
            continue
        for path in base_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in EMBEDDABLE_EXTS:
                # Skip hidden dirs, venvs, node_modules, __pycache__
                parts = path.relative_to(base_dir).parts
                if any(p.startswith(".") or p in ("__pycache__", "node_modules", "venv")
                       for p in parts):
                    continue

                rel = _relative_path(path)
                tags = _tags_from_path(path)
                # Determine subcategory
                subcat = f"file:{category_prefix}"
                # Add a short description from first line if .py or .md
                description = ""
                try:
                    first_line = path.read_text(encoding="utf-8", errors="replace")[:200].strip()
                    if first_line.startswith("#!"):
                        first_line = ""
                    # Extract docstring quote or markdown heading
                    m = re.search(r'"""(.+?)"""', first_line)
                    if m:
                        description = m.group(1).strip()[:150]
                    elif first_line.startswith("# "):
                        description = first_line[2:150].strip()
                except Exception:
                    pass

                _insert(
                    conn,
                    subcat,
                    path.name,
                    rel,
                    description=description,
                    tags=tags,
                    metadata={"size": path.stat().st_size, "modified": datetime.fromtimestamp(
                        path.stat().st_mtime, tz=timezone.utc).isoformat()},
                    confidence=0.9,
                )
                count += 1

    return count


def _index_mcp_tools(conn: sqlite3.Connection) -> int:
    """Parse @mcp.tool decorators from mcp_server.py."""
    count = 0
    if not MCP_SERVER_PATH.exists():
        logger.warning("MCP server not found at %s", MCP_SERVER_PATH)
        return 0

    try:
        source = MCP_SERVER_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Cannot read MCP server: %s", e)
        return 0

    # Match @mcp.tool(description="...") blocks followed by def tool_name
    pattern = re.compile(
        r'@mcp\.tool\(\s*description="(.+?)"\s*\)\s*\n\s*def\s+(\w+)\s*\(',
        re.DOTALL,
    )
    for match in pattern.finditer(source):
        description = match.group(1).strip()
        tool_name = match.group(2).strip()

        # Extract parameter list
        # Find the function signature up to the colon
        sig_start = match.end()
        sig_end = source.find(":", sig_start)
        if sig_end == -1:
            sig_end = sig_start + 100
        sig = source[sig_start:sig_end].strip()

        _insert(
            conn,
            "tool",
            tool_name,
            str(MCP_SERVER_PATH),
            description=description[:300],
            tags=["mcp", "tool"],
            metadata={"signature": sig, "source": str(MCP_SERVER_PATH)},
            confidence=1.0,
        )
        count += 1

    return count


def _index_skills(conn: sqlite3.Connection) -> int:
    """Walk all skill directories across Hermes profiles and shared skills."""
    count = 0
    skill_dirs = []

    # Shared skills
    if SHARED_SKILLS_DIR.exists():
        for d in SHARED_SKILLS_DIR.iterdir():
            if d.is_dir():
                skill_dirs.append((d, "shared", SHARED_SKILLS_DIR))

    # Profile skills
    if PROFILES_DIR.exists():
        for profile_dir in PROFILES_DIR.iterdir():
            if not profile_dir.is_dir():
                continue
            skills_dir = profile_dir / "skills"
            if skills_dir.exists():
                for category_dir in skills_dir.iterdir():
                    if category_dir.is_dir():
                        for skill_dir in category_dir.iterdir():
                            if skill_dir.is_dir():
                                skill_dirs.append((skill_dir, profile_dir.name, skills_dir))

    for skill_dir, source, base in skill_dirs:
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        try:
            content = skill_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        # Parse YAML frontmatter for name/description
        name = skill_dir.name
        description = ""
        version = ""
        yaml_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if yaml_match:
            front = yaml_match.group(1)
            n = re.search(r"^name:\s*(.+)", front, re.MULTILINE)
            if n:
                name = n.group(1).strip()
            d = re.search(r"^description:\s*(.+)", front, re.MULTILINE)
            if d:
                description = d.group(1).strip()
            v = re.search(r"^version:\s*(.+)", front, re.MULTILINE)
            if v:
                version = v.group(1).strip()

        # Fallback: first heading or first line
        if not description:
            heading = re.search(r"^#\s+(.+)", content, re.MULTILINE)
            if heading:
                description = heading.group(1).strip()[:200]

        rel = _relative_path(skill_dir, base)
        tags = ["skill", source]

        _insert(
            conn,
            "skill",
            name,
            rel,
            description=description[:300],
            tags=tags,
            metadata={"source_profile": source, "version": version, "path": str(skill_dir)},
            confidence=0.95,
        )
        count += 1

    return count


def _index_crons(conn: sqlite3.Connection) -> int:
    """Index cron jobs from the manifest file."""
    count = 0

    # Try cron manifest first
    if CRON_MANIFEST.exists():
        try:
            raw = json.loads(CRON_MANIFEST.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                job_list = raw.get("hermes_cron_jobs", raw.get("jobs", []))
            elif isinstance(raw, list):
                job_list = raw
            else:
                job_list = []
            for job in job_list:
                name = job.get("name", job.get("id", "unknown"))
                schedule = job.get("schedule", "")
                prompt = job.get("prompt", job.get("description", job.get("prompt_preview", "")))
                skill = job.get("skill", "")
                script = job.get("script", "")
                _insert(
                    conn, "cron", name, "",
                    description=str(prompt)[:300],
                    tags=["cron", schedule],
                    metadata={
                        "schedule": schedule,
                        "skill": skill,
                        "script": script,
                        "enabled": job.get("enabled", True),
                    },
                    confidence=0.9,
                )
                count += 1
        except Exception as e:
            logger.warning("Failed to parse cron manifest: %s", e)

    return count


def _index_gods(conn: sqlite3.Connection) -> int:
    """Index known gods from gods directory and SOUL files."""
    count = 0
    known_gods = {
        "thoth": {"codex": "Codex-God-thoth", "domain": "research, knowledge, library"},
        "hermes": {"codex": "Codex-God-hermes", "domain": "messenger, orchestration, delivery"},
        "hephaestus": {"codex": "Codex-God-hephaestus", "domain": "builder, code, infrastructure"},
        "apollo": {"codex": "Codex-God-apollo", "domain": "creativity, content, music"},
        "caduceus": {"codex": "Codex-God-caduceus", "domain": "health, healing, Asclepius"},
        "hestia": {"codex": "", "domain": "health checks, hearth, monitoring"},
        "hades": {"codex": "Codex-Pantheon", "domain": "consolidation, archive, night audits"},
        "konan": {"codex": "Codex-User", "domain": "user profile, personal context"},
        "aion": {"codex": "Codex-Pantheon", "domain": "goals, strategic direction"},
        "marvin": {"codex": "", "domain": "cron, background tasks, watchers"},
    }

    for god_name, info in known_gods.items():
        # Check for SOUL.md files
        soul_paths = []
        for profile_dir in PROFILES_DIR.iterdir() if PROFILES_DIR.exists() else []:
            if not profile_dir.is_dir():
                continue
            soul = profile_dir / "SOUL.md"
            if soul.exists():
                soul_paths.append(str(soul))

        _insert(
            conn,
            "god",
            god_name,
            "",
            description=f"{god_name.title()} — {info['domain']}",
            tags=["god", info["codex"].lower().replace("codex-", "") if info["codex"] else ""],
            metadata={
                "domain": info["domain"],
                "codex": info["codex"],
                "soul_files": soul_paths,
            },
            confidence=0.95,
        )
        count += 1

    return count


def _index_workflows(conn: sqlite3.Connection) -> int:
    """Index known Pantheon workflows/pipelines."""
    workflows = [
        {
            "name": "Hades Nightly Consolidation",
            "description": "Athenaeum consolidation pipeline: health checks, distillation, archive scan, mailbox delivery. Runs daily at midnight.",
            "tags": ["pipeline", "nightly", "consolidation"],
        },
        {
            "name": "Dreamweaver Dream Cycle",
            "description": "Knowledge graph maturation: merge entities, enrich edges, decay confidence, infer transitive relationships. Runs daily at 07:15.",
            "tags": ["pipeline", "daily", "graph"],
        },
        {
            "name": "Ichor Subconscious Engine",
            "description": "Every-15-min tick that queries Ichor events, clusters by topic, builds situation reports, and delivers to god inboxes.",
            "tags": ["pipeline", "recurring", "awareness"],
        },
        {
            "name": "Athenaeum Entity Extraction",
            "description": "LLM-powered extraction of entities and relationships from Athenaeum markdown files into the knowledge graph. Called by Hades.",
            "tags": ["pipeline", "extraction", "llm"],
        },
        {
            "name": "Dawn Patrol Intelligence Briefing",
            "description": "Daily intelligence brief: scans Pantheon reports, recent errors, cron delivery status, and notable patterns from the past 24h.",
            "tags": ["pipeline", "daily", "intelligence"],
        },
        {
            "name": "Thoth Daily Feed Digest",
            "description": "Monitors configured RSS/Atom feeds, extracts abstract/summary, and delivers a consolidated digest.",
            "tags": ["pipeline", "daily", "monitoring"],
        },
        {
            "name": "Ichor Forge Analysis",
            "description": "Nightly harness analysis: scores agent-harness interactions, detects code-quality drift, produces logic-gate reports.",
            "tags": ["pipeline", "nightly", "quality"],
        },
        {
            "name": "Morning Briefing",
            "description": "Energetic morning summary for Konan: outstanding tasks, recent cron results, system health highlights.",
            "tags": ["pipeline", "daily", "briefing"],
        },
        {
            "name": "Career-Ops Job Scan",
            "description": "Daily scan of job boards and company career pages for IT/Systems roles matching Konan's preferences.",
            "tags": ["pipeline", "daily", "job-search"],
        },
    ]

    for wf in workflows:
        _insert(
            conn,
            "workflow",
            wf["name"],
            "",
            description=wf["description"],
            tags=wf["tags"],
            metadata={"source": "pantheon_index"},
            confidence=0.9,
        )

    return len(workflows)


# ── Public API ─────────────────────────────────────────────────────────


def refresh_index() -> Dict[str, Any]:
    """Full index refresh. Walks all sources and rebuilds the database."""
    conn = _get_db()
    try:
        _clear_index(conn)
        results = {}

        logger.info("Pantheon Index: indexing files...")
        results["files"] = _index_files(conn)

        logger.info("Pantheon Index: indexing MCP tools...")
        results["tools"] = _index_mcp_tools(conn)

        logger.info("Pantheon Index: indexing skills...")
        results["skills"] = _index_skills(conn)

        logger.info("Pantheon Index: indexing cron jobs...")
        results["crons"] = _index_crons(conn)

        logger.info("Pantheon Index: indexing gods...")
        results["gods"] = _index_gods(conn)

        logger.info("Pantheon Index: indexing workflows...")
        results["workflows"] = _index_workflows(conn)

        total = sum(results.values())
        # External-content FTS5 table: rebuild the term index from index_entries
        # (DELETE FROM index_fts in _clear_index wipes the term index; without a
        # rebuild, every MATCH query returns zero results and search() silently
        # degrades to the LIKE fallback.)
        conn.execute("INSERT INTO index_fts(index_fts) VALUES('rebuild')")
        _set_meta(conn, "last_indexed", datetime.now(timezone.utc).isoformat())
        _set_meta(conn, "total_entries", str(total))

        conn.commit()
        logger.info("Pantheon Index: refresh complete — %d entries across %d categories",
                    total, len(results))

        return {
            "status": "ok",
            "total_entries": total,
            "breakdown": results,
            "last_indexed": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.exception("Pantheon Index refresh failed")
        conn.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        conn.close()


def search(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Full-text search across all indexed Pantheon components."""
    conn = _get_db()
    try:
        # Escape FTS5 special characters
        safe_query = query.replace("'", "''")
        # Use LIKE for prefix matching too
        results = conn.execute(
            """SELECT e.id, e.category, e.name, e.path, e.description, e.tags, e.confidence
               FROM index_entries e
               JOIN index_fts f ON e.id = f.rowid
               WHERE index_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (safe_query, limit),
        ).fetchall()

        # Fallback: LIKE search if FTS5 returns nothing
        if not results:
            like_q = f"%{query}%"
            results = conn.execute(
                """SELECT e.id, e.category, e.name, e.path, e.description, e.tags, e.confidence
                   FROM index_entries e
                   WHERE e.name LIKE ? OR e.description LIKE ?
                   ORDER BY e.confidence DESC
                   LIMIT ?""",
                (like_q, like_q, limit),
            ).fetchall()

        return [
            {
                "id": r["id"],
                "category": r["category"],
                "name": r["name"],
                "path": r["path"],
                "description": r["description"],
                "tags": json.loads(r["tags"]) if r["tags"] else [],
                "confidence": r["confidence"],
            }
            for r in results
        ]
    finally:
        conn.close()


def locate(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Find 'where is X' — returns exact file paths, tool registrations, skill locations."""
    conn = _get_db()
    try:
        # Exact match first, then prefix, then fuzzy
        results = conn.execute(
            """SELECT e.id, e.category, e.name, e.path, e.description, e.confidence
               FROM index_entries e
               WHERE e.name = ? OR e.name LIKE ? OR e.path LIKE ?
               ORDER BY
                   CASE
                       WHEN e.name = ? THEN 0
                       WHEN e.name LIKE ? THEN 1
                       ELSE 2
                   END,
                   e.confidence DESC
               LIMIT ?""",
            (query, f"{query}%", f"%{query}%", query, f"{query}%", limit),
        ).fetchall()

        return [
            {
                "id": r["id"],
                "category": r["category"],
                "name": r["name"],
                "path": r["path"],
                "description": r["description"],
                "confidence": r["confidence"],
            }
            for r in results
        ]
    finally:
        conn.close()


def list_by_category(category: str) -> List[Dict[str, Any]]:
    """List all entries in a category.

    Categories: tool, skill, cron, god, workflow, file:*, god, pipeline.
    """
    conn = _get_db()
    try:
        if category == "all":
            results = conn.execute(
                "SELECT category, COUNT(*) as cnt FROM index_entries GROUP BY category ORDER BY cnt DESC"
            ).fetchall()
            return [{"category": r["category"], "count": r["cnt"]} for r in results]
        elif category == "file":
            results = conn.execute(
                "SELECT name, path, description, category FROM index_entries WHERE category LIKE 'file:%' ORDER BY name LIMIT 200"
            ).fetchall()
        else:
            results = conn.execute(
                "SELECT name, path, description, confidence FROM index_entries WHERE category = ? ORDER BY name",
                (category,),
            ).fetchall()

        return [dict(r) for r in results]
    finally:
        conn.close()


def status() -> Dict[str, Any]:
    """Get index status: freshness, counts per category."""
    conn = _get_db()
    try:
        last_indexed = _get_meta(conn, "last_indexed") or "never"
        total = int(_get_meta(conn, "total_entries") or 0)

        counts = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM index_entries GROUP BY category ORDER BY cnt DESC"
        ).fetchall()

        return {
            "db_path": str(INDEX_DB_PATH),
            "db_size_bytes": INDEX_DB_PATH.stat().st_size if INDEX_DB_PATH.exists() else 0,
            "last_indexed": last_indexed,
            "total_entries": total,
            "breakdown": {r["category"]: r["cnt"] for r in counts},
        }
    finally:
        conn.close()


# ── CLI ────────────────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Pantheon System Index")
    parser.add_argument("action", nargs="?", default="status",
                        choices=["refresh", "search", "locate", "list", "status"],
                        help="Action to perform")
    parser.add_argument("query", nargs="?", default="", help="Search/locate query")
    parser.add_argument("--category", "-c", default="", help="Category filter for list")
    parser.add_argument("--limit", "-l", type=int, default=20, help="Result limit")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.action == "refresh":
        result = refresh_index()
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"Index refreshed: {result.get('total_entries', 0)} entries")
            for cat, cnt in result.get("breakdown", {}).items():
                print(f"  {cat}: {cnt}")

    elif args.action == "search":
        if not args.query:
            print("Error: query required for search")
            sys.exit(1)
        results = search(args.query, args.limit)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"Search results for '{args.query}':")
            for r in results:
                print(f"  [{r['category']}] {r['name']} — {r['description'][:80]}")

    elif args.action == "locate":
        if not args.query:
            print("Error: query required for locate")
            sys.exit(1)
        results = locate(args.query, args.limit)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"Location results for '{args.query}':")
            for r in results:
                print(f"  [{r['category']}] {r['name']}  ({r['path']})")

    elif args.action == "list":
        cat = args.category or "all"
        results = list_by_category(cat)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"Category '{cat}': {len(results)} entries")
            for r in results[:30]:
                print(f"  {r.get('name', r.get('category', '?'))}")

    elif args.action == "status":
        s = status()
        if args.json:
            print(json.dumps(s, indent=2))
        else:
            print(f"Pantheon System Index")
            print(f"  DB:   {s['db_path']} ({s['db_size_bytes']:,} bytes)")
            print(f"  Last: {s['last_indexed']}")
            print(f"  Total: {s['total_entries']} entries")
            for cat, cnt in s.get("breakdown", {}).items():
                print(f"    {cat}: {cnt}")


if __name__ == "__main__":
    main()
