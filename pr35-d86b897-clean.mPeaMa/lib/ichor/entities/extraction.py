"""ER-P1: Backfill extraction for the Entity-Relationship Graph.

Two layers, both $0 (no LLM):
  L0 — Regex extraction (emails, @mentions, URLs, GitHub-style orgs/handles)
  L1 — Levenshtein clustering (group near-duplicate entity names)

Plus a linker that records extraction provenance by fuzzy-matching
entity names against warm_entities.name (the "I found this entity
inside this memory chunk" relationship).

Public API:
  extract_l0(raw_text)        list[dict]   # raw matches
  cluster_l1(entities)        list[dict]   # canonical form
  link_to_warm(entity, ...)   list[int]    # warm_entity IDs
  backfill(conn)              dict         # end-to-end on cold_events
  backfill_stats(conn)        dict         # counts only (read-only)

Schema notes (matches lib.ichor.entities.schema):
  - entity_types.id is TEXT (the slug itself, e.g. 'email')
  - relationship_types.id is TEXT
  - entities.aliases is TEXT (JSON array)
  - extraction_log.method NOT NULL, source_text + source_session_id
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from typing import Any

# ---------- L0 regex patterns ----------

RE_EMAIL = re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b")
RE_MENTION = re.compile(r"(?<![A-Za-z0-9._-])@([A-Za-z][A-Za-z0-9_]{1,30})\b")
RE_URL = re.compile(r"\bhttps?://[^\s<>\"')]+[^\s<>\"'.,)]")
# GitHub orgs/repos: "github.com/anthropics" or "github.com/anthropics/repo"
RE_GITHUB_PATH = re.compile(
    r"\bgithub\.com/([A-Za-z0-9][A-Za-z0-9\-]{0,38})(?:/([A-Za-z0-9._\-]{1,100}))?"
)
# Bare "org/repo" shorthand seen in many cold_events texts
RE_GITHUB_SHORT = re.compile(
    r"(?<![A-Za-z0-9._-])([a-z][a-z0-9\-]{2,30})/([a-z][a-z0-9\-_.]{2,80})(?![A-Za-z0-9._/-])"
)

# Curated org list — only the names we actually expect to see in this corpus.
# Adding to this list is a deliberate curation choice, not auto-discovery.
KNOWN_ORGS = {
    "openai", "anthropic", "anthropics", "google", "deepmind", "meta",
    "nvidia", "microsoft", "apple", "amazon", "huggingface", "nous",
    "hermes", "pantheon", "konan", "theoforge", "relay7",
    "moonshot", "minimax", "alibaba", "tencent", "deepseek", "mistral",
    "github", "gitlab", "n8n", "cf", "cloudflare",
}


def extract_l0(raw_text: str) -> list[dict[str, Any]]:
    """Run all L0 regex extractors. Returns list of {type, value, span}."""
    if not raw_text:
        return []
    out: list[dict[str, Any]] = []
    for m in RE_EMAIL.finditer(raw_text):
        out.append({"type": "email", "value": m.group(0).lower(), "span": (m.start(), m.end())})
    for m in RE_MENTION.finditer(raw_text):
        out.append({"type": "mention", "value": "@" + m.group(1), "span": (m.start(), m.end())})
    for m in RE_URL.finditer(raw_text):
        v = m.group(0).rstrip(".,;:!?)")
        out.append({"type": "url", "value": v, "span": (m.start(), m.start() + len(v))})
    github_spans: list[tuple[int, int]] = []
    for m in RE_GITHUB_PATH.finditer(raw_text):
        org, repo = m.group(1), m.group(2)
        if repo:
            out.append({"type": "github_repo", "value": f"{org}/{repo}", "span": (m.start(), m.end())})
            github_spans.append((m.start(), m.end()))
        else:
            out.append({"type": "github_org", "value": org, "span": (m.start(1), m.end(1))})
            github_spans.append((m.start(1), m.end(1)))
    for m in RE_GITHUB_SHORT.finditer(raw_text):
        s, e = m.start(), m.end()
        if any(g_s <= s < g_e for g_s, g_e in github_spans):
            continue
        org, repo = m.group(1), m.group(2)
        org_l = org.lower()
        if repo and (org_l in KNOWN_ORGS or _looks_like_repo(repo)):
            out.append({"type": "github_repo", "value": f"{org}/{repo}", "span": (s, e)})
        elif org_l in KNOWN_ORGS:
            out.append({"type": "github_org", "value": org, "span": (m.start(1), m.end(1))})
    # Dedupe by (type, value) — keep first span
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for e in out:
        k = (e["type"], e["value"])
        if k not in seen:
            seen.add(k)
            deduped.append(e)
    return deduped


def _looks_like_repo(name: str) -> bool:
    """Heuristic: has digits or hyphen or .py/.md/.ts suffix → looks like a repo name."""
    if any(c.isdigit() for c in name):
        return True
    if "-" in name or "_" in name:
        return True
    return bool(re.search(r"\.(py|md|ts|js|go|rs|sh|json|yaml|yml|toml)$", name))


# ---------- L1 Levenshtein clustering ----------

def _levenshtein(a: str, b: str, max_dist: int = 3) -> int:
    """Bounded Levenshtein. Returns max_dist+1 if distance exceeds max_dist."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > max_dist:
        return max_dist + 1
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        row_min = curr[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + cost,
            )
            if curr[j] < row_min:
                row_min = curr[j]
        if row_min > max_dist:
            return max_dist + 1
        prev = curr
    return prev[lb]


def cluster_l1(
    entities: list[dict[str, Any]],
    distance_threshold: int = 2,
) -> list[dict[str, Any]]:
    """Cluster near-duplicate entities by name (case-insensitive Levenshtein).

    Input: list of {type, value, span, source_event_id}
    Output: list of {type, canonical_value, aliases, count, sources}
    """
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in entities:
        by_type[e["type"]].append(e)

    clusters: list[dict[str, Any]] = []
    for ent_type, items in by_type.items():
        n = len(items)
        parent: list[int] = list(range(n))

        def find(x: int) -> int:
            root = x
            while parent[root] != root:
                root = parent[root]
            cur = x
            while parent[cur] != root:
                nxt = parent[cur]
                parent[cur] = root
                cur = nxt
            return root

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        names = [it["value"].lower() for it in items]
        lengths = [len(name) for name in names]
        for i in range(n):
            ni, li = names[i], lengths[i]
            for j in range(i + 1, n):
                if abs(li - lengths[j]) > distance_threshold:
                    continue
                d = _levenshtein(ni, names[j], max_dist=distance_threshold)
                if d <= distance_threshold:
                    union(i, j)

        groups: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            groups[find(i)].append(i)

        for idxs in groups.values():
            members = [items[i] for i in idxs]
            canonical = max(members, key=lambda m: (len(m["value"]), m["value"]))["value"]
            aliases = sorted({m["value"] for m in members})
            sources = sorted({m["source_event_id"] for m in members if m.get("source_event_id") is not None})
            clusters.append({
                "type": ent_type,
                "canonical_value": canonical,
                "aliases": aliases,
                "count": len(members),
                "sources": sources,
            })
    return clusters


# ---------- Linker to warm_entities ----------

def link_to_warm(
    cluster: dict[str, Any],
    warm_names: list[tuple[int, str]],
    distance_threshold: int = 3,
) -> list[int]:
    """Find warm_entity IDs whose name is within Levenshtein distance
    of the cluster's canonical_value or any alias. Returns sorted list
    of warm IDs (deduped, threshold-filtered)."""
    candidates = [cluster["canonical_value"]] + cluster.get("aliases", [])
    candidates_l = [c.lower() for c in candidates]
    matches: set[int] = set()
    for warm_id, warm_name in warm_names:
        wn_l = warm_name.lower()
        wn_len = len(wn_l)
        for c_l in candidates_l:
            if abs(wn_len - len(c_l)) > distance_threshold:
                continue
            d = _levenshtein(wn_l, c_l, max_dist=distance_threshold)
            if d <= distance_threshold:
                matches.add(warm_id)
                break
    return sorted(matches)


# ---------- End-to-end backfill ----------

def backfill(conn: sqlite3.Connection, max_events: int | None = None) -> dict[str, Any]:
    """Run L0+L1+linker against cold_events.raw_text. Writes to entity tables.

    Idempotent: re-running is a no-op for entities that already have
    an extraction_log row with method='regex+cluster'.
    """
    conn.row_factory = sqlite3.Row

    # 1) Pull cold_events with content
    sql = "SELECT id, raw_text FROM cold_events WHERE raw_text IS NOT NULL AND raw_text != ''"
    if max_events is not None:
        sql += f" LIMIT {int(max_events)}"
    rows = conn.execute(sql).fetchall()

    # 2) L0 extraction
    raw_entities: list[dict[str, Any]] = []
    for r in rows:
        for hit in extract_l0(r["raw_text"] or ""):
            hit["source_event_id"] = r["id"]
            hit["source_text"] = (r["raw_text"] or "")[:500]  # truncated for log
            raw_entities.append(hit)

    # 3) L1 clustering
    clusters = cluster_l1(raw_entities)

    # 4) Get all warm_entities for linker (real schema: category, name, value, ...)
    warm_rows = conn.execute("SELECT id, name FROM warm_entities").fetchall()
    warm_names = [(r["id"], r["name"]) for r in warm_rows]

    # 5a) entity_types: ensure each cluster's type exists.
    # Schema: id TEXT PK (the slug itself), description, parent_type, extractable, icon, created_at
    type_id_cache: dict[str, str] = {}
    for t in {c["type"] for c in clusters}:
        existing = conn.execute("SELECT id FROM entity_types WHERE id = ?", (t,)).fetchone()
        if existing:
            type_id_cache[t] = existing["id"]
        else:
            conn.execute(
                """INSERT INTO entity_types (id, description, parent_type, extractable, icon, created_at)
                   VALUES (?, ?, NULL, 1, '📄', datetime('now'))""",
                (t, f"Auto-created by ER-P1 backfill for L0 type '{t}'"),
            )
            type_id_cache[t] = t

    # 5b) entities: pre-fetch existing (name, type_id) → id to avoid dupes
    entity_lookup: dict[tuple[str, str], int] = {}
    for row in conn.execute("SELECT id, name, type_id FROM entities").fetchall():
        entity_lookup[(row["name"], row["type_id"])] = row["id"]

    inserted_entities = 0
    updated_entities = 0
    inserted_warm_links = 0
    inserted_logs = 0
    skipped_duplicate_logs = 0

    for cluster in clusters:
        canon = cluster["canonical_value"]
        type_id = type_id_cache[cluster["type"]]
        key = (canon, type_id)
        if key in entity_lookup:
            entity_id = entity_lookup[key]
        else:
            cur = conn.execute(
                """INSERT INTO entities
                   (type_id, name, aliases, summary, confidence, status, created_at, updated_at)
                   VALUES (?, ?, ?, '', 1.0, 'active', datetime('now'), datetime('now'))""",
                (type_id, canon, json.dumps(cluster["aliases"], separators=(",", ":"))),
            )
            entity_id = int(cur.lastrowid) if cur.lastrowid is not None else 0
            entity_lookup[key] = entity_id
            inserted_entities += 1

        # Linker: find warm IDs (stored in entity_facts as provenance)
        warm_ids = link_to_warm(cluster, warm_names)
        if warm_ids:
            # Check existing — store as a single fact with JSON list of warm IDs
            existing = conn.execute(
                "SELECT 1 FROM entity_facts WHERE entity_id = ? AND key = 'linked_warm_ids' LIMIT 1",
                (entity_id,),
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO entity_facts (entity_id, key, value, type, confidence, created_at)
                       VALUES (?, 'linked_warm_ids', ?, 'string', 1.0, datetime('now'))""",
                    (entity_id, json.dumps([str(w) for w in warm_ids], separators=(",", ":"))),
                )
                inserted_warm_links += len(warm_ids)

        # entity_facts: occurrence count
        existing = conn.execute(
            "SELECT 1 FROM entity_facts WHERE entity_id = ? AND key = 'occurrence_count' LIMIT 1",
            (entity_id,),
        ).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO entity_facts (entity_id, key, value, type, confidence, created_at)
                   VALUES (?, 'occurrence_count', ?, 'number', 1.0, datetime('now'))""",
                (entity_id, str(cluster["count"])),
            )
            updated_entities += 1

        # entity_facts: source events list
        if cluster["sources"]:
            existing = conn.execute(
                "SELECT 1 FROM entity_facts WHERE entity_id = ? AND key = 'source_event_ids' LIMIT 1",
                (entity_id,),
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO entity_facts (entity_id, key, value, type, confidence, created_at)
                       VALUES (?, 'source_event_ids', ?, 'string', 1.0, datetime('now'))""",
                    (entity_id, json.dumps([str(s) for s in cluster["sources"]], separators=(",", ":"))),
                )

        # extraction_log: one per (entity, method); dedupe so re-runs are no-ops
        existing_log = conn.execute(
            "SELECT 1 FROM extraction_log WHERE entity_id = ? AND method = 'regex+cluster' LIMIT 1",
            (entity_id,),
        ).fetchone()
        if not existing_log:
            conn.execute(
                """INSERT INTO extraction_log
                   (entity_id, relationship_id, fact_id, method, source_text, source_session_id, confidence, created_at)
                   VALUES (?, NULL, NULL, 'regex+cluster', ?, NULL, 1.0, datetime('now'))""",
                (entity_id, f"L1 cluster from {cluster['count']} raw matches across {len(cluster['sources'])} events"),
            )
            inserted_logs += 1
        else:
            skipped_duplicate_logs += 1

    conn.commit()

    return {
        "events_scanned": len(rows),
        "raw_entities_extracted": len(raw_entities),
        "clusters_after_l1": len(clusters),
        "entities_inserted": inserted_entities,
        "entities_updated": updated_entities,
        "warm_links_added": inserted_warm_links,
        "extraction_logs_inserted": inserted_logs,
        "skipped_duplicate_logs": skipped_duplicate_logs,
    }


def backfill_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Read-only stats for the entity graph. Safe to call repeatedly."""
    out: dict[str, Any] = {}
    for table in ("entity_types", "entities", "relationship_types", "relationships", "entity_facts", "extraction_log"):
        out[f"{table}_count"] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    out["distinct_entity_types_used"] = conn.execute(
        "SELECT COUNT(DISTINCT type_id) FROM entities"
    ).fetchone()[0]
    out["entities_with_warm_link"] = conn.execute(
        "SELECT COUNT(DISTINCT entity_id) FROM entity_facts WHERE key = 'linked_warm_ids'"
    ).fetchone()[0]
    out["total_warm_links"] = conn.execute(
        "SELECT COALESCE(SUM(json_array_length(value)), 0) FROM entity_facts WHERE key = 'linked_warm_ids'"
    ).fetchone()[0]
    return out
