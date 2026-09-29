#!/usr/bin/env python3
"""Ichor Fix D — Option A: priority-scoped semantic summary backfill.

Fills `entities.summary` for the small set of entities that per-turn relational
recall (T3) can actually surface, using the LLM:

  * the T3-visible neighbourhood of Konan's person root — the exact node set
    `graph_query_by_id(anchor, depth=2)` returns, resolved through
    `entity_resolve` so aliases ("Cybermage") land on the canonical id;
  * the top-N hubs by **live** edge degree — the nodes T3 fans out to most.

Why priority-scoped (Option A) rather than full-corpus (Option B): 14,093
active entities have no summary, but the reported symptom is a *hollow rendered
hit* in the graph tier. Only entities reachable from the person graph or
surfaced as hubs can be rendered at all — 190 of them, not 14k.

Why this is not the "poisoned field" case that Fix D's read-time descriptor
avoided: `_neighborhood_descriptor()` writes *derived structural* text and was
deliberately kept out of `summary`. These are real semantic summaries produced
from evidence (typed relations + FTS-matched event text) — the same artifact a
semantic backfill would produce — so `summary` is the correct destination.

Safety
------
* dry-run by default; `--apply` writes
* ``UPDATE ... WHERE status='active' AND (summary IS NULL OR TRIM(summary)='')``
  — an existing summary is never overwritten
* every write is appended to an audit JSONL (id, old, new, evidence digest,
  model, tokens); ``--rollback <audit.jsonl>`` reverts exactly those rows and
  only when the current value still matches what we wrote
* one provenance row per entity in `extraction_log`
  (method=``FIXD_BACKFILL_METHOD``)
* a checkpoint row in `ichor_settings` records ids applied + token spend

Usage
-----
    PY=/home/konan/.hermes/hermes-agent/.venv/bin/python3
    $PY scripts/ichor_fix_d_priority_backfill.py                     # plan only
    $PY scripts/ichor_fix_d_priority_backfill.py --apply \
        --audit /home/konan/athenaeum/Codex-God-hermes/reports/fixd-audit-$(date +%F).jsonl
    $PY scripts/ichor_fix_d_priority_backfill.py --rollback <audit.jsonl> --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

REPO_ROOT = Path("/home/konan/pantheon")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ICHOR_DB = Path("/home/konan/.hermes/ichor.db")
HERMES_ENV = Path("/home/konan/.hermes/.env")
HERMES_CONFIG = Path("/home/konan/.hermes/config.yaml")

ANCHOR_NAME = "konan"
T3_DEPTH = 2
HUB_COUNT = 300
DEFAULT_LIMIT = 250
DEFAULT_BATCH = 8
MIN_CONFIDENCE = 0.3
REL_EVIDENCE_LIMIT = 8
EVENT_EVIDENCE_LIMIT = 4
EVENT_SNIPPET_CHARS = 220
SUMMARY_MAX_CHARS = 200
PREVIEW_LIMIT = 60
DEFAULT_PROVIDER = "opencode-go"
DEFAULT_MODEL = "deepseek-v4.1-flash"

FIXD_BACKFILL_METHOD = "fix_d_priority_summary_backfill"
# opencode-go rejects routeless requests with HTTP 400 MissingSessionID; a stable
# per-process id keeps one run's calls on the same routing shard (and traceable).
OPENCODE_SESSION_ID = f"ichor-fixd-{uuid.uuid4().hex[:12]}"
CHECKPOINT_KEY = "fix_d_priority_summary_backfill_001"
LIVE_REL_FILTER = "r.provisional = 0 AND r.confidence >= ? AND r.valid_to IS NULL"

PROMPT_TEMPLATE = """You are filling in one-line summaries for nodes of a personal
knowledge graph so that a per-turn memory retriever can render them usefully.

For each entity below you get: id, name, type, aliases, its typed relationships
(direction, relation, the entity on the other end, confidence), and verbatim
event snippets that mention it.

Write exactly ONE sentence per entity, max {max_chars} characters, shaped like:

  <name> is a <type> — <what it is or does, taken from the event snippets when
  they say so>; <at most two or three of the strongest relations>.

Hard rules:
- Use ONLY the supplied evidence. Never invent dates, numbers, titles, vendors,
  roles, or outcomes that are not in the evidence.
- Never enumerate every relation you were given. Pick the two or three with the
  highest confidence that best explain the entity. Prefer relations whose other
  end is a named project/person/organization over generic tools.
- Skip noise relations whose other end is the entity itself, one of its
  aliases, or the placeholder name "user".
- No markdown, no bullet points, no surrounding quotes, no leading
  "This entity is".
- Third person, present tense.
- If the evidence is thin, describe structure instead: e.g.
  "Pantheon is an organization — related to konan and to Hermes."

Output ONLY valid JSON, no prose:
{{"summaries": [{{"id": 123, "summary": "...", "confidence": 0.8}}]}}

Entities:
{payload}

JSON:"""


# ---------------------------------------------------------------------------
# environment / provider plumbing
# ---------------------------------------------------------------------------

def load_env_file(path: Path = HERMES_ENV) -> int:
    """Load KEY=VALUE lines from the Hermes env file into os.environ.

    Existing environment variables win — this only fills gaps, so a shell that
    already exports the key behaves identically. Returns the number of keys
    newly set.
    """
    if not path.exists():
        return 0
    added = 0
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ and value:
            os.environ[key] = value
            added += 1
    return added


def _provider_config(provider_name: str) -> dict[str, Any]:
    """Return the provider block from ~/.hermes/config.yaml."""
    import yaml

    data = yaml.safe_load(HERMES_CONFIG.read_text())
    providers = (data or {}).get("providers", {}) or {}
    cfg = providers.get(provider_name)
    if not cfg:
        raise SystemExit(f"provider {provider_name!r} not found in {HERMES_CONFIG}")
    return dict(cfg)


def call_llm_with_usage(
    prompt: str,
    provider_cfg: dict[str, Any],
    *,
    model: Optional[str] = None,
    timeout: float = 150.0,
) -> tuple[str, dict[str, int]]:
    """POST a chat completion, returning (content, usage).

    Mirrors ``lib.ichor.llm._call_llm`` (same endpoint shape, same
    thinking-disabled flag and User-Agent header that Cloudflare requires) but
    also returns token usage so the backfill can report real spend instead of
    an estimate, and sends the ``x-opencode-session`` routing header that
    opencode-go requires (without it: HTTP 400 MissingSessionID).
    """
    api_base = str(provider_cfg.get("api", "")).rstrip("/")
    if not api_base:
        raise RuntimeError("provider has no api base URL")
    model_name = model or provider_cfg.get("default_model", "")
    if not model_name:
        raise RuntimeError("no model specified for provider")
    provider_name = str(provider_cfg.get("name", "")).upper().replace("-", "_")
    api_key = provider_cfg.get("api_key", "") or os.environ.get(f"{provider_name}_API_KEY", "")

    body = json.dumps({
        "model": model_name,
        "messages": [
            {"role": "system",
             "content": "You are a careful analyst. Output ONLY valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 6000,
        "thinking": {"type": "disabled"},
        "temperature": 0.2,
    }).encode("utf-8")

    req = urllib.request.Request(f"{api_base}/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "pantheon-ichor/1.0 (fix_d_priority_backfill)")
    if "opencode.ai" in api_base:
        req.add_header("x-opencode-session", OPENCODE_SESSION_ID)
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:  # pragma: no cover - network path
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"HTTP {exc.code} from {api_base}: {detail}") from exc

    choices = payload.get("choices") or []
    content = ""
    if choices:
        content = (choices[0].get("message") or {}).get("content") or ""
    usage = payload.get("usage") or {}
    return content, {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
    }


# ---------------------------------------------------------------------------
# graph scope
# ---------------------------------------------------------------------------

def _fallback_anchor_id(conn: sqlite3.Connection, name: str) -> Optional[int]:
    """Indexed name lookup, used when `resolve()` cannot run (DB write-locked).

    `entity_resolve.resolve()` calls `migrate()` on every invocation, which
    takes a write lock — on the live 5.5 GB DB with the gateway writing, that
    can legitimately fail. The anchor is the one resolution this backfill
    needs, so degrade to indexed lookups instead of aborting the run.
    """
    row = conn.execute(
        "SELECT id FROM entities WHERE LOWER(name) = LOWER(?) "
        "ORDER BY (status = 'active') DESC, id LIMIT 1",
        (name,),
    ).fetchone()
    if row is None:
        return None
    entity_id = int(row["id"])
    for _ in range(3):  # follow merge chains
        current = conn.execute("SELECT merged_into FROM entities WHERE id = ?",
                               (entity_id,)).fetchone()
        if current is None or not current["merged_into"]:
            break
        entity_id = int(current["merged_into"])
    return entity_id


def resolve_anchor_id(conn: sqlite3.Connection, name: str = ANCHOR_NAME,
                      db_path: Path = ICHOR_DB) -> int:
    """Canonical id for the anchor person (consults entity_aliases first)."""
    from lib.ichor.entities.entity_resolve import resolve

    entity_id: Optional[int] = None
    try:
        result = resolve(name, db_path=str(db_path))
        entity_id = result.get("id") if isinstance(result, dict) else result
    except sqlite3.Error:
        entity_id = None
    if entity_id is None:
        entity_id = _fallback_anchor_id(conn, name)
    if entity_id is None:
        raise SystemExit(f"could not resolve anchor {name!r} to an entity id")
    return int(entity_id)


def live_degree(conn: sqlite3.Connection) -> dict[int, int]:
    """Undirected live-edge degree per entity id."""
    degree: dict[int, int] = {}
    for column in ("source_id", "target_id"):
        rows = conn.execute(
            f"SELECT {column} AS nid, COUNT(*) AS c FROM relationships r "
            f"WHERE {LIVE_REL_FILTER} GROUP BY {column}",
            (MIN_CONFIDENCE,),
        ).fetchall()
        for row in rows:
            degree[row["nid"]] = degree.get(row["nid"], 0) + row["c"]
    return degree


def t3_visible_ids(conn: sqlite3.Connection, anchor_id: int, depth: int = T3_DEPTH) -> set[int]:
    """Node ids the live T3 tier would return for the anchor (same call shape)."""
    from lib.ichor.entities.traversal import graph_query_by_id

    result = graph_query_by_id(
        conn, anchor_id, depth=depth, min_confidence=MIN_CONFIDENCE,
        max_nodes=100, max_edges=200, fanout=50, timeout_ms=2000,
    )
    return {int(node["id"]) for node in result.get("nodes", [])}


def select_targets(
    conn: sqlite3.Connection,
    *,
    anchor_name: str = ANCHOR_NAME,
    depth: int = T3_DEPTH,
    hubs: int = HUB_COUNT,
    limit: int = DEFAULT_LIMIT,
    include_t3: bool = True,
    db_path: Path = ICHOR_DB,
    scope: str = "priority",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pick the target set.

    ``scope="priority"`` (Option A, default): T3-visible empties ∪ top-`hubs`
    empties — the nodes the per-turn retriever can actually render.

    ``scope="all"`` (Option B): every active entity with an empty summary,
    ranked by live edge degree so the most-referenced nodes get summaries first.
    Same evidence, same prompt, same write guard — only the candidate set widens.
    """
    anchor_id = resolve_anchor_id(conn, anchor_name, db_path)
    degree = live_degree(conn)

    if scope == "all":
        rows = conn.execute(
            "SELECT id, name, type_id FROM entities "
            "WHERE status='active' AND (summary IS NULL OR TRIM(summary) = '')"
        ).fetchall()
        targets: list[dict[str, Any]] = []
        skipped_nameless = 0
        for row in rows:
            name = (row["name"] or "").strip()
            if not name:
                skipped_nameless += 1
                continue
            targets.append({
                "id": int(row["id"]),
                "name": name,
                "type_id": row["type_id"],
                "degree": degree.get(int(row["id"]), 0),
                "in_t3": False,
            })
        targets.sort(key=lambda t: (-t["degree"], t["id"]))
        selection = targets[:limit]
        stats = {
            "scope": "all",
            "anchor_id": anchor_id,
            "degree_entities": len(degree),
            "empty_in_scope": len(targets),
            "selected": len(selection),
            "skipped_nameless": skipped_nameless,
            "truncated": max(0, len(targets) - len(selection)),
        }
        return selection, stats

    visible = t3_visible_ids(conn, anchor_id, depth) if include_t3 else set()

    ranked = sorted(degree.items(), key=lambda kv: (-kv[1], kv[0]))
    hub_ids = {eid for eid, _ in ranked[:hubs]}

    candidates = sorted(visible | hub_ids)
    if not candidates:
        return [], {"anchor_id": anchor_id, "degree_entities": len(degree),
                    "t3_visible": len(visible), "hub_candidates": len(hub_ids)}

    marks = ",".join("?" * len(candidates))
    rows = conn.execute(
        f"SELECT id, name, type_id, summary FROM entities "
        f"WHERE id IN ({marks}) AND status='active' "
        f"AND (summary IS NULL OR TRIM(summary) = '') "
        f"ORDER BY id",
        tuple(candidates),
    ).fetchall()

    targets: list[dict[str, Any]] = []
    skipped_nameless = 0
    for row in rows:
        name = (row["name"] or "").strip()
        if not name:
            skipped_nameless += 1
            continue
        targets.append({
            "id": int(row["id"]),
            "name": name,
            "type_id": row["type_id"],
            "degree": degree.get(int(row["id"]), 0),
            "in_t3": int(row["id"]) in visible,
        })

    # Hubs first (higher fanout), then T3-visible, then degree — deterministic.
    targets.sort(key=lambda t: (not t["in_t3"], -t["degree"], t["id"]))
    selection = targets[:limit]
    stats = {
        "scope": "priority",
        "anchor_id": anchor_id,
        "degree_entities": len(degree),
        "t3_visible": len(visible),
        "hub_candidates": len(hub_ids),
        "empty_in_scope": len(targets),
        "selected": len(selection),
        "skipped_nameless": skipped_nameless,
        "truncated": max(0, len(targets) - len(selection)),
    }
    return selection, stats


# ---------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------

def _relation_evidence(conn: sqlite3.Connection, entity_id: int) -> list[dict[str, Any]]:
    """Live typed relations touching entity_id, outgoing and incoming."""
    rows: list[dict[str, Any]] = []
    for direction, key in (("->", "source_id"), ("<-", "target_id")):
        other = "target_id" if direction == "->" else "source_id"
        rows.extend(dict(r) | {"direction": direction} for r in conn.execute(
            f"SELECT r.type_id, r.confidence, e.id AS other_id, e.name AS other_name, "
            f"       e.type_id AS other_type "
            f"FROM relationships r JOIN entities e ON e.id = r.{other} "
            f"WHERE r.{key} = ? AND {LIVE_REL_FILTER} "
            f"ORDER BY r.confidence DESC LIMIT ?",
            (entity_id, MIN_CONFIDENCE, REL_EVIDENCE_LIMIT),
        ).fetchall())
    rows.sort(key=lambda r: -float(r.get("confidence") or 0.0))
    return rows[:REL_EVIDENCE_LIMIT]


def _event_evidence(
    conn: sqlite3.Connection,
    name: str,
    *,
    limit: int = EVENT_EVIDENCE_LIMIT,
    order: str = "recent",
) -> list[dict[str, Any]]:
    """Verbatim event snippets mentioning `name`, from the FTS5 index.

    Degrades to [] when the index is absent (fresh/temp DBs) — grounding is
    additive, never a hard requirement.
    """
    if len(name) < 3:
        return []
    phrase = '"{}"'.format(name.replace('"', '""'))
    rank_clause = "ORDER BY rank" if order == "rank" else "ORDER BY m.rowid DESC"
    try:
        rows = conn.execute(
            f"SELECT m.rowid AS id, m.content, m.category, m.event_type, c.created_at "
            f"FROM memory_fts m LEFT JOIN cold_events c ON c.id = m.rowid "
            f"WHERE memory_fts MATCH ? {rank_clause} LIMIT ?",
            (phrase, limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for row in rows:
        text = re.sub(r"\s+", " ", (row["content"] or "")).strip()
        if not text:
            continue
        out.append({
            "event_id": int(row["id"]),
            "category": row["category"],
            "event_type": row["event_type"],
            "created_at": row["created_at"],
            "text": text[:EVENT_SNIPPET_CHARS],
        })
    return out


def _type_descriptions(conn: sqlite3.Connection) -> tuple[dict[str, str], dict[str, str]]:
    entity_types = {r["id"]: (r["description"] or "") for r in
                    conn.execute("SELECT id, description FROM entity_types")}
    relation_types = {r["id"]: (r["description"] or "") for r in
                      conn.execute("SELECT id, description FROM relationship_types")}
    return entity_types, relation_types


def build_evidence(conn: sqlite3.Connection, target: dict[str, Any]) -> dict[str, Any]:
    """Everything the LLM is allowed to use for one entity."""
    aliases: list[str] = []
    row = conn.execute("SELECT aliases FROM entities WHERE id = ?", (target["id"],)).fetchone()
    if row and row["aliases"]:
        try:
            parsed = json.loads(row["aliases"])
            if isinstance(parsed, list):
                aliases = [str(a) for a in parsed][:8]
        except (TypeError, ValueError):
            aliases = []
    return {
        "id": target["id"],
        "name": target["name"],
        "type": target["type_id"],
        "aliases": aliases,
        "degree": target["degree"],
        "relations": _relation_evidence(conn, target["id"]),
        "events": _event_evidence(conn, target["name"]),
    }


def evidence_digest(evidence: dict[str, Any]) -> str:
    """Stable hash of the evidence actually used — audit + reproducibility."""
    canonical = json.dumps(evidence, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def build_prompt(
    batch: list[dict[str, Any]],
    entity_types: dict[str, str],
    relation_types: dict[str, str],
) -> str:
    """Render the batch prompt."""
    lines: list[str] = []
    for item in batch:
        lines.append(f"- id: {item['id']}")
        lines.append(f"  name: {item['name']}")
        type_desc = entity_types.get(item["type"] or "", "")
        lines.append(f"  type: {item['type']}" + (f" ({type_desc})" if type_desc else ""))
        if item["aliases"]:
            lines.append(f"  aliases: {', '.join(item['aliases'])}")
        if item["relations"]:
            lines.append("  relations:")
            for rel in item["relations"]:
                desc = relation_types.get(rel["type_id"], "")
                suffix = f" [{desc}]" if desc else ""
                lines.append(
                    f"    {rel['direction']} {rel['type_id']}{suffix} "
                    f"{rel['other_name']} ({rel['other_type']}, conf {rel['confidence']:.2f})"
                )
        else:
            lines.append("  relations: (none recorded)")
        if item["events"]:
            lines.append("  event snippets mentioning it:")
            for ev in item["events"]:
                lines.append(f"    [{ev['event_type']}|{ev['category']}|{ev['created_at']}] {ev['text']}")
        else:
            lines.append("  event snippets mentioning it: (none)")
    payload = "\n".join(lines)
    return PROMPT_TEMPLATE.format(max_chars=SUMMARY_MAX_CHARS, payload=payload)


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

def parse_summaries(raw: str, valid_ids: Iterable[int]) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse the model's JSON reply; tolerate fences and surrounding prose."""
    warnings: list[str] = []
    if not raw or not raw.strip():
        return [], ["empty response"]
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return [], ["no JSON object in response"]
    try:
        payload = json.loads(text[start:end + 1])
    except ValueError as exc:
        return [], [f"invalid JSON: {exc}"]

    items = payload.get("summaries") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return [], ["missing 'summaries' array"]

    allowed = set(valid_ids)
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            warnings.append("non-object entry skipped")
            continue
        try:
            entity_id = int(item.get("id"))
        except (TypeError, ValueError):
            warnings.append(f"non-integer id skipped: {item.get('id')!r}")
            continue
        if entity_id not in allowed:
            warnings.append(f"id {entity_id} not in batch — skipped")
            continue
        summary = re.sub(r"\s+", " ", str(item.get("summary") or "")).strip().strip('"').strip()
        if not summary:
            warnings.append(f"id {entity_id}: empty summary")
            continue
        if len(summary) > SUMMARY_MAX_CHARS * 2:
            summary = summary[:SUMMARY_MAX_CHARS].rsplit(" ", 1)[0] + "…"
            warnings.append(f"id {entity_id}: truncated")
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.6
        out.append({"id": entity_id, "summary": summary,
                    "confidence": max(0.0, min(1.0, confidence))})
    return out, warnings


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------

def apply_rows(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
    *,
    model: str,
    audit_path: Optional[Path],
    tier_by_id: dict[int, dict[str, Any]],
) -> int:
    """Write summaries + provenance. Returns the number of rows written.

    The UPDATE carries its own guard, so a concurrent writer that filled a
    summary in the meantime wins and our row is skipped (never overwritten).
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    written = 0
    audit_lines: list[str] = []
    for row in rows:
        entity_id = row["id"]
        cur = conn.execute(
            "UPDATE entities SET summary = ?, updated_at = ? "
            "WHERE id = ? AND status = 'active' "
            "AND (summary IS NULL OR TRIM(summary) = '')",
            (row["summary"], now, entity_id),
        )
        if cur.rowcount != 1:
            continue
        conn.execute(
            "INSERT INTO extraction_log "
            "(entity_id, method, source_text, source_session_id, confidence, created_at) "
            "VALUES (?, ?, ?, NULL, ?, ?)",
            (entity_id, FIXD_BACKFILL_METHOD,
             row.get("evidence_digest", "")[:200], row["confidence"], now),
        )
        written += 1
        meta = tier_by_id.get(entity_id, {})
        audit_lines.append(json.dumps({
            "ts": now,
            "id": entity_id,
            "name": meta.get("name", ""),
            "old_summary": "",
            "new_summary": row["summary"],
            "confidence": row["confidence"],
            "model": model,
            "evidence_sha256": row.get("evidence_digest", ""),
            "in_t3": bool(meta.get("in_t3")),
            "degree": meta.get("degree", 0),
            "prompt_tokens": row.get("prompt_tokens", 0),
            "completion_tokens": row.get("completion_tokens", 0),
        }, ensure_ascii=False))
    conn.commit()
    if audit_path and audit_lines:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(audit_lines) + "\n")
    return written


def write_checkpoint(conn: sqlite3.Connection, payload: dict[str, Any]) -> bool:
    """Record the checkpoint; returns False when `ichor_settings` is absent.

    A missing settings table must not abort a run whose writes already landed —
    the caller reports the boolean so the gap is visible instead of silent.
    """
    try:
        conn.execute(
            "INSERT OR REPLACE INTO ichor_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (CHECKPOINT_KEY, json.dumps(payload, ensure_ascii=False),
             datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    except sqlite3.OperationalError:
        return False
    return True


def rollback(conn: sqlite3.Connection, audit_path: Path) -> dict[str, int]:
    """Revert rows recorded in an audit file (only if unchanged since)."""
    reverted = skipped = 0
    for line in audit_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not entry.get("new_summary"):
            continue
        cur = conn.execute(
            "UPDATE entities SET summary = '' WHERE id = ? AND summary = ?",
            (entry["id"], entry["new_summary"]),
        )
        if cur.rowcount == 1:
            conn.execute("DELETE FROM extraction_log WHERE entity_id = ? AND method = ?",
                         (entry["id"], FIXD_BACKFILL_METHOD))
            reverted += 1
        else:
            skipped += 1
    conn.commit()
    return {"reverted": reverted, "skipped": skipped}


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def run(
    conn: sqlite3.Connection,
    *,
    model: str,
    batch_size: int,
    limit: int,
    hubs: int,
    depth: int,
    order: str,
    apply: bool,
    audit_path: Optional[Path],
    call_fn: Callable[..., tuple[str, dict[str, int]]],
    provider_cfg: dict[str, Any],
    timeout: float,
    log: Callable[[str], None],
    db_path: Path = ICHOR_DB,
    scope: str = "priority",
) -> dict[str, Any]:
    """Select → ground → generate → (optionally) write. Returns a run report."""
    started = time.monotonic()
    targets, scope_stats = select_targets(conn, depth=depth, hubs=hubs, limit=limit,
                                          db_path=db_path, scope=scope)
    log(f"scope: {json.dumps(scope_stats)}")
    if not targets:
        # Full report shape even when nothing is in scope — callers assert on it.
        return {
            "scope": scope_stats, "targets": 0, "generated": 0, "written": 0,
            "calls": 0, "checkpoint_written": False,
            "tokens": {"prompt_tokens": 0, "completion_tokens": 0},
            "failures": [], "preview": [],
            "elapsed_s": round(time.monotonic() - started, 1),
            "dry_run": not apply,
        }

    entity_types, relation_types = _type_descriptions(conn)
    tier_by_id = {t["id"]: t for t in targets}
    generated: list[dict[str, Any]] = []
    failures: list[str] = []
    tokens = {"prompt_tokens": 0, "completion_tokens": 0}
    calls = 0

    pending = list(targets)
    index = 0
    while index < len(pending):
        batch = pending[index:index + batch_size]
        evidence = [build_evidence(conn, t) for t in batch]
        prompt = build_prompt(evidence, entity_types, relation_types)
        valid_ids = [e["id"] for e in evidence]
        digests = {e["id"]: evidence_digest(e) for e in evidence}
        parsed, warnings = [], []
        attempts_left = 2
        while attempts_left > 0:
            calls += 1
            try:
                raw, usage = call_fn(prompt, provider_cfg, model=model, timeout=timeout)
            except Exception as exc:  # network/HTTP — retry once, then record
                warnings = [f"call failed: {exc}"]
                parsed = []
                attempts_left -= 1
                log(f"batch at {index}: {warnings[0]} (attempts left {attempts_left})")
                continue
            tokens["prompt_tokens"] += usage.get("prompt_tokens", 0)
            tokens["completion_tokens"] += usage.get("completion_tokens", 0)
            parsed, warnings = parse_summaries(raw, valid_ids)
            if parsed:
                break
            attempts_left -= 1
            log(f"batch at {index}: parse issue {warnings[:2]} (attempts left {attempts_left})")

        for row in parsed:
            row["evidence_digest"] = digests.get(row["id"], "")
            row["prompt_tokens"] = tokens["prompt_tokens"]
            row["completion_tokens"] = tokens["completion_tokens"]
        missing = [i for i in valid_ids if i not in {r['id'] for r in parsed}]
        if missing:
            failures.append(f"ids {missing[:6]} got no summary")
        generated.extend(parsed)
        log(f"batch {index // batch_size + 1}/{max(1, (len(pending) + batch_size - 1) // batch_size)}: "
            f"{len(parsed)}/{len(batch)} summaries, warnings={warnings[:2]}")
        index += batch_size

    preview = [
        {"id": row["id"], "name": tier_by_id.get(row["id"], {}).get("name", ""),
         "summary": row["summary"], "confidence": row["confidence"]}
        for row in generated[:PREVIEW_LIMIT]
    ]

    written = 0
    checkpointed = False
    if apply and generated:
        written = apply_rows(conn, generated, model=model, audit_path=audit_path,
                             tier_by_id=tier_by_id)
        checkpointed = write_checkpoint(conn, {
            "applied_ids": [r["id"] for r in generated],
            "written": written,
            "model": model,
            "prompt_tokens": tokens["prompt_tokens"],
            "completion_tokens": tokens["completion_tokens"],
            "scope": scope_stats,
        })

    return {
        "scope": scope_stats,
        "targets": len(targets),
        "generated": len(generated),
        "written": written,
        "calls": calls,
        "checkpoint_written": checkpointed,
        "tokens": tokens,
        "failures": failures,
        "preview": preview,
        "elapsed_s": round(time.monotonic() - started, 1),
        "dry_run": not apply,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Priority-scoped LLM summary backfill for the Ichor ER graph")

    parser.add_argument("--apply", action="store_true",
                        help="write to the live DB (default: plan/dry-run)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"max entities this run (default {DEFAULT_LIMIT})")
    parser.add_argument("--hubs", type=int, default=HUB_COUNT,
                        help=f"top-N hubs by live edge degree (default {HUB_COUNT})")
    parser.add_argument("--scope", choices=("priority", "all"), default="priority",
                        help="priority = Option A (T3-visible ∪ hubs, default); "
                             "all = Option B (every active entity with an empty "
                             "summary, ranked by live degree)")
    parser.add_argument("--depth", type=int, default=T3_DEPTH,
                        help=f"BFS depth from the anchor (default {T3_DEPTH})")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH,
                        help=f"entities per LLM call (default {DEFAULT_BATCH})")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=float, default=150.0)
    parser.add_argument("--event-order", choices=("recent", "rank"), default="recent")
    parser.add_argument("--audit", type=Path,
                        default=Path("/home/konan/athenaeum/Codex-God-hermes/reports/"
                                     f"fixd-priority-summary-audit-{datetime.now():%Y%m%d}.jsonl"))
    parser.add_argument("--report", type=Path, help="write a JSON run report here")
    parser.add_argument("--rollback", type=Path,
                        help="revert the rows in this audit file (requires --apply)")
    parser.add_argument("--db", type=Path, default=ICHOR_DB)
    args = parser.parse_args(argv)

    load_env_file()
    conn = sqlite3.connect(str(args.db), timeout=60)
    conn.row_factory = sqlite3.Row

    if args.rollback:
        if not args.apply:
            print("--rollback needs --apply (dry-run makes no changes)")
            return 2
        result = rollback(conn, args.rollback)
        print(json.dumps(result, indent=2))
        return 0

    provider_cfg = _provider_config(args.provider)
    model = args.model or provider_cfg.get("default_model", DEFAULT_MODEL)

    def log(message: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)

    report = run(
        conn, model=model, batch_size=args.batch_size, limit=args.limit,
        hubs=args.hubs, depth=args.depth, order=args.event_order,
        apply=args.apply, audit_path=args.audit,
        call_fn=call_llm_with_usage, provider_cfg=provider_cfg,
        timeout=args.timeout, log=log, db_path=args.db, scope=args.scope,
    )
    report["model"] = model
    report["provider"] = args.provider
    print(json.dumps(report, indent=2, default=str))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
