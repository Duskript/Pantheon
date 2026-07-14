"""
B3: ichor_ls + ichor_find — the browse/retrieve tools for pantheon://.

Spec: ~/athenaeum/Codex-God-thoth/research/openviking-vs-ichor-comparison/build-brief.md §P3a, §P3b
      ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md §B3

`ichor_ls(path)` — list directory entries at a pantheon:// path
`ichor_find(query, path)` — search, scoped to a subtree

Both return empty lists (not errors) for invalid paths, per the
gate's verification: "Invalid path returns empty list, not error".
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.ichor_paths import (
    PANTHEON_PREFIX,
    parse_path,
    list_codex_dirs,
    list_god_dirs,
    list_codex_files,
    path_matches,
)

logger = logging.getLogger("ichor_browse")

_HOME = Path.home()
_ICHOR_DB = _HOME / ".hermes" / "ichor.db"
_ATHENAEUM_ROOT = _HOME / "athenaeum"

# Stop-words for FTS5-style search (kept tiny — we delegate to FTS5
# for real matching, this is only for the path-scoped filter)
_TERMINAL_PUNCT = re.compile(r"[\s\"'`]+")


# ---------------------------------------------------------------------------
# ichor_ls
# ---------------------------------------------------------------------------

def ichor_ls(path: str = PANTHEON_PREFIX) -> List[Dict[str, Any]]:
    """List entries at a pantheon:// path.

    Each entry is a dict with:
      - name: str
      - type: "directory" | "file"
      - brief: str           (L0 summary; "" if not available)
      - path: str            (full pantheon:// path)
      - item_count: int      (for directories, how many items inside)

    Examples:
      ichor_ls("pantheon://")        → [warm, codexes, gods, reference]
      ichor_ls("pantheon://warm/")   → [blockers, commitments, decisions, ...]
      ichor_ls("pantheon://gods/")   → [Apollo, Hephaestus, Iris, ...]
      ichor_ls("invalid://")         → []
    """
    spec = parse_path(path)
    if not spec.get("valid"):
        logger.debug("ichor_ls: invalid path %r: %s",
                     path, spec.get("error", "?"))
        return []

    root = spec.get("root")
    if root is None:
        # Root: list the 4 namespaces
        return [
            {"name": "warm", "type": "directory",
             "brief": "Frequent-access memory entities",
             "path": f"{PANTHEON_PREFIX}warm/",
             "item_count": _count_distinct_categories("warm_entities")},
            {"name": "codexes", "type": "directory",
             "brief": "Athenaeum codex directories",
             "path": f"{PANTHEON_PREFIX}codexes/",
             "item_count": len(list_codex_dirs())},
            {"name": "gods", "type": "directory",
             "brief": "Per-god codex directories",
             "path": f"{PANTHEON_PREFIX}gods/",
             "item_count": len(list_god_dirs())},
            {"name": "reference", "type": "directory",
             "brief": "Reference knowledge base",
             "path": f"{PANTHEON_PREFIX}reference/",
             "item_count": _count_distinct_categories("reference_knowledge")},
        ]

    if root == "warm":
        return _ls_warm(spec.get("category"))
    if root == "codexes":
        return _ls_codex_filesystem(spec.get("name"), spec.get("subpath"))
    if root == "gods":
        return _ls_god_filesystem(spec.get("name"), spec.get("subpath"))
    if root == "reference":
        return _ls_reference(spec.get("category"))

    return []


def _count_distinct_categories(table: str) -> int:
    """Count distinct non-null values in a `category` column, or 0."""
    if not _ICHOR_DB.exists():
        return 0
    try:
        con = sqlite3.connect(_ICHOR_DB)
        try:
            r = con.execute(
                f"SELECT COUNT(DISTINCT category) FROM {table} "
                f"WHERE category IS NOT NULL"
            ).fetchone()
            return r[0] if r else 0
        finally:
            con.close()
    except sqlite3.Error as e:
        logger.debug("_count_distinct_categories(%s) failed: %s", table, e)
        return 0


def _ls_warm(category: Optional[str]) -> List[Dict[str, Any]]:
    """List warm_entities by category."""
    if not _ICHOR_DB.exists():
        return []
    con = sqlite3.connect(_ICHOR_DB)
    try:
        if category is None:
            # List distinct categories
            rows = con.execute(
                "SELECT category, COUNT(*) FROM warm_entities "
                "WHERE category IS NOT NULL "
                "GROUP BY category ORDER BY category"
            ).fetchall()
            return [
                {"name": cat, "type": "directory",
                 "brief": _category_brief(cat),
                 "path": f"{PANTHEON_PREFIX}warm/{cat}/",
                 "item_count": cnt}
                for cat, cnt in rows
                if cat
            ]
        # List entities in the category
        rows = con.execute(
            "SELECT name, brief FROM warm_entities "
            "WHERE category = ? "
            "ORDER BY importance DESC, name ASC",
            (category,),
        ).fetchall()
        return [
            {"name": name, "type": "file",
             "brief": brief or "",
             "path": f"{PANTHEON_PREFIX}warm/{category}/{name}",
             "item_count": 0}
            for name, brief in rows
        ]
    except sqlite3.Error as e:
        logger.warning("warm ls failed: %s", e)
        return []
    finally:
        con.close()


def _ls_codex_filesystem(name: Optional[str], subpath: Optional[str]) -> List[Dict[str, Any]]:
    """List a codex dir or its subpath."""
    if name is None:
        return [
            {"name": p.name[len("Codex-"):] if p.name.startswith("Codex-") else p.name,
             "type": "directory",
             "brief": _codex_brief(p),
             "path": f"{PANTHEON_PREFIX}codexes/{p.name[len('Codex-'):]}/",
             "item_count": _count_files_in_dir(p)}
            for p in list_codex_dirs()
        ]
    # name is "Codex-Forge" etc; list files inside (optionally under subpath)
    codex_path = _ATHENAEUM_ROOT / name
    if not codex_path.is_dir():
        return []
    if subpath:
        base = codex_path / subpath
        if not base.is_dir():
            return []
        return _file_entries(base.rglob("*"))
    return _file_entries(codex_path.rglob("*"))


def _ls_god_filesystem(name: Optional[str], subpath: Optional[str]) -> List[Dict[str, Any]]:
    """List a god codex dir or its subpath."""
    if name is None:
        return [
            {"name": p.name[len("Codex-God-"):] if p.name.startswith("Codex-God-") else p.name,
             "type": "directory",
             "brief": _codex_brief(p),
             "path": f"{PANTHEON_PREFIX}gods/{p.name[len('Codex-God-'):]}/",
             "item_count": _count_files_in_dir(p)}
            for p in list_god_dirs()
        ]
    return _ls_codex_filesystem(name, subpath)  # same logic


def _ls_reference(category: Optional[str]) -> List[Dict[str, Any]]:
    """List reference_knowledge entries (table is currently empty in prod)."""
    if not _ICHOR_DB.exists():
        return []
    con = sqlite3.connect(_ICHOR_DB)
    try:
        if category is None:
            rows = con.execute(
                "SELECT slug, brief FROM reference_knowledge "
                "WHERE slug IS NOT NULL "
                "ORDER BY slug"
            ).fetchall()
            return [
                {"name": slug, "type": "file",
                 "brief": brief or "",
                 "path": f"{PANTHEON_PREFIX}reference/{slug}",
                 "item_count": 0}
                for slug, brief in rows
            ]
        # Specific slug
        row = con.execute(
            "SELECT slug, brief FROM reference_knowledge WHERE slug = ?",
            (category,),
        ).fetchone()
        if not row:
            return []
        return [{"name": row[0], "type": "file",
                 "brief": row[1] or "",
                 "path": f"{PANTHEON_PREFIX}reference/{row[0]}",
                 "item_count": 0}]
    except sqlite3.Error as e:
        logger.debug("reference ls failed: %s", e)
        return []
    finally:
        con.close()


def _file_entries(paths) -> List[Dict[str, Any]]:
    """Convert an iterable of paths to DirEntry dicts (files only)."""
    entries = []
    for p in paths:
        if not p.is_file() or p.name.startswith("."):
            continue
        try:
            rel = p.relative_to(_ATHENAEUM_ROOT)
        except ValueError:
            continue
        # Skip INDEX.md from the listing of files? No — it's useful
        brief = _first_line_brief(p) if p.suffix == ".md" else ""
        entries.append({
            "name": p.name,
            "type": "file",
            "brief": brief,
            "path": str(rel),
            "item_count": 0,
        })
    # INDEX.md first, then alphabetic
    entries.sort(key=lambda e: (0 if e["name"] == "INDEX.md" else 1, e["name"].lower()))
    return entries


def _count_files_in_dir(p: Path) -> int:
    """Count non-hidden files recursively in a directory."""
    if not p.is_dir():
        return 0
    return sum(1 for f in p.rglob("*") if f.is_file() and not f.name.startswith("."))


def _first_line_brief(p: Path) -> str:
    """Pull the first non-heading markdown line as a brief."""
    try:
        text = p.read_text(errors="ignore")
    except Exception:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        return line[:200]
    return ""


def _codex_brief(p: Path) -> str:
    """Get a codex's brief from its INDEX.md or first non-heading line."""
    index = p / "INDEX.md"
    if index.exists():
        text = index.read_text(errors="ignore")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            return line[:200]
    return _first_line_brief(p) if p.is_file() else ""


def _category_brief(cat: str) -> str:
    """Return a fixed brief string for known warm categories."""
    briefs = {
        "decision": "Decisions made and their rationale",
        "blocker": "Active blockers preventing progress",
        "commitment": "Commitments and follow-throughs",
        "preference": "User preferences and conventions",
        "insight": "Captured insights and learnings",
        "fact": "Verified facts about the system",
        "follow_up": "Open follow-up items",
        "correction": "Corrections to prior beliefs",
        "digest_entry": "Shared context digest entries",
        "reference": "Reference material and links",
    }
    return briefs.get(cat, cat)


# ---------------------------------------------------------------------------
# ichor_find
# ---------------------------------------------------------------------------

def ichor_find(
    query: str,
    path: str = PANTHEON_PREFIX,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Search for `query`, scoped to the subtree at `path`.

    Each result is a dict with:
      - id: str
      - brief: str
      - outline: str (may be empty)
      - path: str   (full filesystem or pantheon:// path)
      - score: float (0-1)
      - has_full: bool (true if full content is available)

    Scoping rules:
      - pantheon:// (root)            → all sources
      - pantheon://warm/...           → warm_entities only
      - pantheon://codexes/<name>/... → codex files (subpath filter applied)
      - pantheon://gods/<name>/...    → god codex files
      - pantheon://reference/...      → reference_knowledge only
      - invalid path                  → []
    """
    if not query or not query.strip():
        return []
    spec = parse_path(path)
    if not spec.get("valid"):
        logger.debug("ichor_find: invalid path %r", path)
        return []
    root = spec.get("root")

    results: List[Dict[str, Any]] = []
    if root is None or root == "warm":
        results.extend(_find_warm(query, spec.get("category"), limit))
    if root is None or root == "codexes":
        results.extend(_find_codex(query, spec.get("name"),
                                   spec.get("subpath"), limit))
    if root is None or root == "gods":
        results.extend(_find_god(query, spec.get("name"),
                                 spec.get("subpath"), limit))
    if root is None or root == "reference":
        results.extend(_find_reference(query, spec.get("category"), limit))

    # Sort by score desc, dedupe by id, cap at limit
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for r in sorted(results, key=lambda r: r.get("score", 0), reverse=True):
        rid = r.get("id", "")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        deduped.append(r)
        if len(deduped) >= limit:
            break
    return deduped


def _find_warm(query: str, category: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """FTS5 search on warm_entities.name + warm_entities.brief + raw_text in cold_events."""
    if not _ICHOR_DB.exists():
        return []
    con = sqlite3.connect(_ICHOR_DB)
    try:
        # FTS5 on warm_entities: there's no FTS table, so use LIKE for now.
        # The bigger FTS5 search is in ichor_hybrid. This is a simple scoped
        # name/brief match.
        like_q = f"%{query}%"
        if category is None:
            rows = con.execute(
                "SELECT name, brief, outline, category, importance "
                "FROM warm_entities "
                "WHERE name LIKE ? OR brief LIKE ? "
                "ORDER BY importance DESC LIMIT ?",
                (like_q, like_q, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT name, brief, outline, category, importance "
                "FROM warm_entities "
                "WHERE category = ? AND (name LIKE ? OR brief LIKE ?) "
                "ORDER BY importance DESC LIMIT ?",
                (category, like_q, like_q, limit),
            ).fetchall()
        results = []
        for name, brief, outline, cat, importance in rows:
            score = min(1.0, (importance or 0.0) / 100.0)
            results.append({
                "id": f"warm:{cat}:{name}",
                "brief": brief or "",
                "outline": outline or "",
                "path": f"{PANTHEON_PREFIX}warm/{cat}/{name}",
                "score": round(score, 3),
                "has_full": True,
            })
        return results
    except sqlite3.Error as e:
        logger.debug("warm find failed: %s", e)
        return []
    finally:
        con.close()


def _find_codex(query: str, name: Optional[str], subpath: Optional[str],
                limit: int) -> List[Dict[str, Any]]:
    """Grep codex files for the query string."""
    results = []
    if name is None:
        dirs = list_codex_dirs()
    else:
        codex = _ATHENAEUM_ROOT / name
        dirs = [codex] if codex.is_dir() else []
    for d in dirs:
        for f in d.rglob("*"):
            if not f.is_file() or f.name.startswith("."):
                continue
            if not path_matches(str(f), subpath):
                continue
            try:
                rel = f.relative_to(_ATHENAEUM_ROOT)
            except ValueError:
                continue
            score, has_match = _file_match_score(f, query)
            if score <= 0:
                continue
            results.append({
                "id": f"codex:{f}",
                "brief": _first_line_brief(f) if f.suffix == ".md" else "",
                "outline": "",  # outline is in the file, not pre-extracted
                "path": str(rel),
                "score": round(score, 3),
                "has_full": has_match,
            })
    return results


def _find_god(query: str, name: Optional[str], subpath: Optional[str],
              limit: int) -> List[Dict[str, Any]]:
    """Same as _find_codex but for god codexes."""
    if name is None:
        dirs = list_god_dirs()
    else:
        god = _ATHENAEUM_ROOT / name
        dirs = [god] if god.is_dir() else []
    results = []
    for d in dirs:
        for f in d.rglob("*"):
            if not f.is_file() or f.name.startswith("."):
                continue
            if not path_matches(str(f), subpath):
                continue
            try:
                rel = f.relative_to(_ATHENAEUM_ROOT)
            except ValueError:
                continue
            score, has_match = _file_match_score(f, query)
            if score <= 0:
                continue
            results.append({
                "id": f"god:{f}",
                "brief": _first_line_brief(f) if f.suffix == ".md" else "",
                "outline": "",
                "path": str(rel),
                "score": round(score, 3),
                "has_full": has_match,
            })
    return results


def _find_reference(query: str, category: Optional[str],
                    limit: int) -> List[Dict[str, Any]]:
    """Search reference_knowledge (table is currently empty in prod)."""
    if not _ICHOR_DB.exists():
        return []
    con = sqlite3.connect(_ICHOR_DB)
    try:
        like_q = f"%{query}%"
        if category is None:
            rows = con.execute(
                "SELECT slug, title, brief, outline "
                "FROM reference_knowledge "
                "WHERE slug LIKE ? OR title LIKE ? OR brief LIKE ? "
                "LIMIT ?",
                (like_q, like_q, like_q, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT slug, title, brief, outline FROM reference_knowledge "
                "WHERE slug = ? LIMIT ?",
                (category, limit),
            ).fetchall()
        return [
            {
                "id": f"reference:{slug}",
                "brief": brief or "",
                "outline": outline or "",
                "path": f"{PANTHEON_PREFIX}reference/{slug}",
                "score": 0.5,
                "has_full": True,
            }
            for slug, title, brief, outline in rows
        ]
    except sqlite3.Error as e:
        logger.debug("reference find failed: %s", e)
        return []
    finally:
        con.close()


def _file_match_score(f: Path, query: str) -> tuple:
    """Score a file for query match.

    Returns (score, has_full_text). 0 means no match.
    Score is 1.0 if filename matches, 0.5 if first line matches, 0.3 if
    any line in the file matches.
    """
    if not query or not query.strip():
        return 0.0, False
    q = query.lower()
    if q in f.name.lower():
        return 1.0, True
    try:
        text = f.read_text(errors="ignore")
    except Exception:
        return 0.0, False
    if q in text.lower():
        # Crude: check first line
        first_line = text.split("\n", 1)[0].lower() if text else ""
        if q in first_line:
            return 0.5, True
        return 0.3, True
    return 0.0, False
