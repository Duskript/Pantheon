"""Pure Ichor context-pack builder.

Phase 1 intentionally stays small: deterministic source-backed selection,
no LLM/API calls, no DB writes, and graceful degradation when live Ichor data
is unavailable.
"""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


ATHENAEUM = Path("/home/konan/athenaeum")
ICHOR_DB = Path.home() / ".hermes" / "ichor.db"

PRIMARY_SECTIONS = (
    "current_decisions",
    "hard_constraints",
    "relevant_files",
    "risks",
    "related_entities",
    "recent_changes",
)
ROLE_TAGS = {"hephaestus", "thoth", "rheta"}
MEMORY_TRIGGER_TERMS = {
    "athenaeum",
    "canary",
    "compress",
    "conductor",
    "context",
    "decide",
    "decision",
    "god",
    "gods",
    "ichor",
    "infrastructure",
    "lcm",
    "managed",
    "pantheon",
    "pricing",
    "retainer",
    "session",
    "workflow",
}


@dataclass(frozen=True)
class Anchor:
    section: str
    title: str
    text: str
    source_path: str
    source_id: str
    tags: tuple[str, ...]
    priority: int = 50


ANCHORS: tuple[Anchor, ...] = (
    Anchor(
        section="current_decisions",
        title="Conductor v2 canonical reaction engine",
        text=(
            "Conductor v2 shipped as the canonical reaction engine; v1 stays "
            "retired. The implementation is a single-process daemon wired by "
            "engine, gateway, nats, webhook, delivery, and a service entry."
        ),
        source_path="/home/konan/athenaeum/Codex-Pantheon/decisions/2026-06-14-conductor-v2.md",
        source_id="conductor-v2-built-tested-deployed",
        tags=("conductor", "v2", "workflow", "nats", "systemd", "hephaestus", "debug"),
        priority=95,
    ),
    Anchor(
        section="relevant_files",
        title="Conductor v2 runtime files and endpoints",
        text=(
            "Runtime evidence names conductor/v2/engine.py, service.py, "
            "api_server.py, delivery.py, nats.py, webhook.py, cron_scheduler.py, "
            "the /health endpoint, and the Thoth gateway on :8642."
        ),
        source_path="/home/konan/athenaeum/Codex-Pantheon/briefs/2026-06-23-pantheon-vs-hermes-344.md",
        source_id="pantheon-vs-hermes-344-workflow-dag-engine",
        tags=("conductor", "v2", "endpoint", "nats", "mcp", "hephaestus", "debug"),
        priority=92,
    ),
    Anchor(
        section="hard_constraints",
        title="Systemd service is part of the deployed Conductor v2 seam",
        text=(
            "The Conductor v2 deployment record points to the systemd unit "
            "at ~/.config/systemd/user/conductor-v2.service and records a live "
            "smoke test with daemon start, /health 200, gateway connection, and "
            "webhook event quarantine behavior."
        ),
        source_path="/home/konan/athenaeum/Codex-Pantheon/decisions/2026-06-14-conductor-v2.md",
        source_id="conductor-v2-systemd-smoke-test",
        tags=("conductor", "v2", "systemd", "endpoint", "hephaestus", "debug"),
        priority=90,
    ),
    Anchor(
        section="related_entities",
        title="MCP and cross-platform messaging surface",
        text=(
            "Pantheon exposes dynamic registration through MCP tools and uses "
            "NATS/Subspace subjects for cross-Pantheon routing, including "
            "subspace outgoing and incoming patterns."
        ),
        source_path="/home/konan/athenaeum/Codex-Pantheon/briefs/2026-06-23-pantheon-vs-hermes-344.md",
        source_id="pantheon-vs-hermes-344-agent-comms",
        tags=("conductor", "v2", "mcp", "nats", "routing", "hephaestus", "debug"),
        priority=88,
    ),
    Anchor(
        section="current_decisions",
        title="Workflow validator and cross-god dispatch model",
        text=(
            "Conductor workflows are validated at load time; workflow records "
            "and routing decisions cover cross-god handoffs, production YAML, "
            "and the workflow catalog."
        ),
        source_path="/home/konan/athenaeum/Codex-Pantheon/DECISIONS.md",
        source_id="workflow-validator-cross-god-routing",
        tags=("conductor", "v2", "workflow", "cross-god", "routing", "thoth", "research"),
        priority=96,
    ),
    Anchor(
        section="relevant_files",
        title="Pantheon workflow architecture",
        text=(
            "The workflow engine is Pantheon's runtime for executing multi-god "
            "task pipelines. Workflows are directed graphs stored as JSON and "
            "made available from the workflow launcher."
        ),
        source_path="/home/konan/athenaeum/Codex-Pantheon/constitution/WORKFLOWS.md",
        source_id="constitution-workflows-runtime",
        tags=("conductor", "v2", "workflow", "cross-god", "routing", "thoth", "research"),
        priority=93,
    ),
    Anchor(
        section="related_entities",
        title="Zeus routing and cross-god handoff",
        text=(
            "Pantheon architecture assigns routing and handoffs to the harness "
            "layer; Zeus evaluates candidate gods and returns routing options "
            "with reasoning."
        ),
        source_path="/home/konan/athenaeum/Codex-Pantheon/constitution/SANCTUARY.md",
        source_id="sanctuary-zeus-routing",
        tags=("conductor", "v2", "workflow", "cross-god", "routing", "thoth", "research"),
        priority=91,
    ),
    Anchor(
        section="current_decisions",
        title="Pantheon $5k managed offer",
        text=(
            "Pantheon pricing context repeatedly frames the offer as a $5k/mo "
            "managed multi-agent AI system for local professional services."
        ),
        source_path="/home/konan/athenaeum/Codex-God-thoth/research/lead-funnel-2026-05-23/sub_conversion-optimization.md",
        source_id="pantheon-5k-managed-offer",
        tags=("pantheon", "pricing", "$5k", "managed", "rheta", "copywriting"),
        priority=96,
    ),
    Anchor(
        section="hard_constraints",
        title="Managed dedicated infrastructure lane",
        text=(
            "For pricing copy, position the managed offer around dedicated "
            "infrastructure and a concrete $5k monthly commitment, not a "
            "self-hosted or no-subscription lane."
        ),
        source_path="/home/konan/athenaeum/Codex-God-thoth/research/lead-funnel-2026-05-23/sub_funnel-design.md",
        source_id="pantheon-dedicated-infrastructure-pricing-lane",
        tags=("pantheon", "pricing", "$5k", "managed", "dedicated", "infrastructure", "rheta", "copywriting"),
        priority=94,
    ),
)


def _rss_kb() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, IndexError, ValueError):
        return None
    return None


def _estimate_tokens_text(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


def _terms(*parts: str) -> set[str]:
    words: set[str] = set()
    for part in parts:
        for raw in part.lower().replace("/", " ").replace("-", " ").split():
            word = raw.strip(".,:;()[]{}'\"`")
            if len(word) > 1:
                words.add(word)
    return words


def _sanitize_fts(query: str) -> str:
    """Sanitize user text for SQLite FTS5 MATCH syntax."""
    cleaned = re.sub(r'[":*()\^\-]', " ", query or "")
    cleaned = re.sub(r"\b(AND|OR|NOT|NEAR)\b", " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _needs_memory_context(query: str, god_name: str, phase: str, task_type: str) -> bool:
    """Cheap no-read classifier: casual turns avoid DB and prompt growth.

    God and role labels are ranking hints, not memory-need signals. A casual
    chat turn should not become a DB read just because the active profile is
    named ``thoth`` or ``hephaestus``.
    """
    del god_name, phase
    terms = _terms(query, task_type)
    return bool(terms & MEMORY_TRIGGER_TERMS)


@lru_cache(maxsize=64)
def _source_file_info(source_path: str, tags: tuple[str, ...]) -> tuple[bool, str]:
    """Return existence + compact excerpt for a source file.

    Source files are stable during one dry-run/manual build, so caching avoids
    repeated full-file reads and keeps the pack builder compressor-weight.
    """
    path = Path(source_path)
    if not path.exists():
        return False, ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False, ""

    lowered_tags = [tag.lower() for tag in tags[:4] if tag]
    first_nonempty = ""
    for line in lines:
        clean = line.strip()
        if clean and not first_nonempty:
            first_nonempty = clean[:360]
        lower = clean.lower()
        if clean and any(tag in lower for tag in lowered_tags):
            return True, clean[:360]
    return True, first_nonempty[:360]


def _source_exists_for(anchor: Anchor) -> bool:
    return _source_file_info(anchor.source_path, anchor.tags)[0]


def _source_excerpt_for(anchor: Anchor) -> str:
    """Return a compact source excerpt from the backing file when present."""
    return _source_file_info(anchor.source_path, anchor.tags)[1]


def _row_value(row: sqlite3.Row, key: str) -> str:
    try:
        value = row[key]
    except (IndexError, KeyError):
        return ""
    return "" if value is None else str(value)


def _fallback_title(source: str, source_id: str) -> str:
    label = (source or "ichor_source").replace("_", " ").strip()
    label = label[:1].upper() + label[1:] if label else "Ichor source"
    suffix = source_id.rsplit(":", 1)[-1] if source_id else ""
    return f"{label} {suffix}".strip()


def _clean_title(title: str, *, source: str, source_id: str) -> str:
    raw = title or ""
    raw_lower = raw.lower()
    raw_fragment_markers = ("`", "|", "\n", "<", ">", "http", "www", "**", "#", "'", "=", ":", "/")
    if any(marker in raw_lower for marker in raw_fragment_markers):
        return _fallback_title(source, source_id)
    full = " ".join(raw.split())
    if not full:
        return _fallback_title(source, source_id)
    compact = full[:180]
    if compact.endswith((",", ";")) or not compact[:1].isupper():
        return _fallback_title(source, source_id)
    if len(compact.split()) > 9 and not compact.endswith((".", ")")):
        return _fallback_title(source, source_id)
    return compact


def _db_item(
    *,
    source: str,
    source_id: str,
    title: str,
    text: str,
    source_path: str,
    source_excerpt: str = "",
) -> dict[str, Any] | None:
    clean = " ".join((text or "").split())
    if not clean:
        return None
    return {
        "title": _clean_title(title, source=source, source_id=source_id),
        "text": clean[:420],
        "snippet": clean[:320],
        "source": source,
        "source_path": source_path or source_id,
        "source_id": source_id,
        "source_excerpt": source_excerpt[:360] or clean[:320],
        "path": source_path or source_id,
        "id": source_id,
    }


def _append_unique(items: list[dict[str, Any]], candidate: dict[str, Any] | None) -> bool:
    if candidate is None:
        return False
    candidate_key = (candidate.get("source"), candidate.get("source_id"))
    candidate_text = str(candidate.get("text", "")).lower()[:160]
    for item in items:
        existing_key = (item.get("source"), item.get("source_id"))
        existing_text = str(item.get("text", "")).lower()[:160]
        if candidate_key == existing_key or candidate_text == existing_text:
            return False
    items.append(candidate)
    return True


def _item(anchor: Anchor) -> dict[str, Any]:
    return {
        "title": anchor.title,
        "text": anchor.text,
        "snippet": anchor.text[:320],
        "source": "athenaeum",
        "source_path": anchor.source_path,
        "source_id": anchor.source_id,
        "source_excerpt": _source_excerpt_for(anchor),
        "path": anchor.source_path,
        "id": anchor.source_id,
    }


def _score(anchor: Anchor, query_terms: set[str], god_name: str, phase: str, task_type: str) -> int:
    tags = set(anchor.tags)
    if not query_terms & tags:
        return 0
    score = anchor.priority
    score += 18 * len(query_terms & tags)
    if god_name.lower() in tags:
        score += 80
    if phase.lower() in tags:
        score += 35
    if task_type and task_type.lower() in tags:
        score += 20
    return score


def _read_db_candidates(query: str, max_rows: int, deadline: float) -> tuple[list[dict[str, Any]], int, int, list[str]]:
    if max_rows <= 0 or not ICHOR_DB.exists() or time.perf_counter() > deadline:
        return [], 0, 0, []

    cleaned = _sanitize_fts(query)
    if not cleaned:
        return [], 0, 0, ["unsafe_query"]

    rows_examined = 0
    db_reads = 0
    omitted: list[str] = []
    results: list[dict[str, Any]] = []
    uri = f"file:{ICHOR_DB}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=0.05)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return [], 0, 0, [f"db_unavailable:{exc.__class__.__name__}"]

    try:
        try:
            claim_rows = conn.execute(
                """
                SELECT c.id, c.text, c.type, c.source_session_id,
                       e.source_event_id, e.excerpt
                FROM ichor_claims c
                LEFT JOIN ichor_claim_evidence e ON e.claim_id = c.id
                WHERE c.status = 'active' AND c.text LIKE ?
                ORDER BY c.trust_score DESC, c.confidence DESC, c.id DESC
                LIMIT ?
                """,
                (f"%{query}%", max_rows),
            ).fetchall()
            db_reads += 1
            rows_examined += len(claim_rows)
            for row in claim_rows:
                if len(results) >= max_rows or time.perf_counter() > deadline:
                    break
                source_id = f"ichor_claims:{_row_value(row, 'id')}"
                evidence_id = _row_value(row, "source_event_id")
                source_path = _row_value(row, "source_session_id")
                if evidence_id:
                    source_path = source_path or f"ichor_events:{evidence_id}"
                _append_unique(
                    results,
                    _db_item(
                        source="ichor_claims",
                        source_id=source_id,
                        title=_row_value(row, "type") or source_id,
                        text=_row_value(row, "text"),
                        source_path=source_path,
                        source_excerpt=_row_value(row, "excerpt"),
                    ),
                )
        except sqlite3.Error as exc:
            omitted.append(f"claims_query_failed:{exc.__class__.__name__}")

        if len(results) < max_rows and time.perf_counter() <= deadline:
            obs_rows = conn.execute(
                """
                SELECT o.id, o.subject, o.predicate, o.object, o.content,
                       o.category, o.confidence, o.last_seen,
                       s.source_session_id, s.source_god_name, s.event_id, s.quote
                FROM ichor_observations_fts f
                JOIN ichor_observations o ON f.rowid = o.id
                LEFT JOIN (
                    SELECT observation_id,
                           MIN(source_session_id) AS source_session_id,
                           MIN(source_god_name) AS source_god_name,
                           MIN(event_id) AS event_id,
                           MIN(quote) AS quote
                    FROM ichor_observation_sources
                    GROUP BY observation_id
                ) s ON s.observation_id = o.id
                WHERE ichor_observations_fts MATCH ?
                GROUP BY o.id
                LIMIT ?
                """,
                (cleaned, max_rows - len(results)),
            ).fetchall()
            db_reads += 1
            rows_examined += len(obs_rows)
            for row in obs_rows:
                if len(results) >= max_rows or time.perf_counter() > deadline:
                    break
                source_id = f"ichor_observations:{_row_value(row, 'id')}"
                event_id = _row_value(row, "event_id")
                source_path = _row_value(row, "source_session_id")
                if event_id:
                    source_path = source_path or f"ichor_events:{event_id}"
                title = _row_value(row, "subject") or _row_value(row, "category") or source_id
                text = _row_value(row, "content") or " ".join(
                    part for part in (
                        _row_value(row, "subject"),
                        _row_value(row, "predicate"),
                        _row_value(row, "object"),
                    ) if part
                )
                _append_unique(
                    results,
                    _db_item(
                        source="ichor_observations",
                        source_id=source_id,
                        title=title,
                        text=text,
                        source_path=source_path,
                        source_excerpt=_row_value(row, "quote"),
                    ),
                )

        if len(results) < max_rows and time.perf_counter() <= deadline:
            event_rows = conn.execute(
                """
                SELECT e.id, e.event_type, e.subject, e.raw_text,
                       e.session_id, e.god_name, e.created_at
                FROM ichor_events_fts f
                JOIN ichor_events e ON f.rowid = e.id
                WHERE ichor_events_fts MATCH ?
                ORDER BY e.importance DESC, e.id DESC
                LIMIT ?
                """,
                (cleaned, max_rows - len(results)),
            ).fetchall()
            db_reads += 1
            rows_examined += len(event_rows)
            for row in event_rows:
                if len(results) >= max_rows or time.perf_counter() > deadline:
                    break
                raw_text = _row_value(row, "raw_text")
                if not raw_text.strip():
                    omitted.append("unhydrated_event")
                    continue
                source_id = f"ichor_events:{_row_value(row, 'id')}"
                _append_unique(
                    results,
                    _db_item(
                        source="ichor_events",
                        source_id=source_id,
                        title=_row_value(row, "subject") or _row_value(row, "event_type") or source_id,
                        text=raw_text,
                        source_path=_row_value(row, "session_id") or _row_value(row, "god_name") or source_id,
                    ),
                )
    except sqlite3.Error as exc:
        omitted.append(f"db_query_failed:{exc.__class__.__name__}")
    finally:
        conn.close()

    if time.perf_counter() > deadline:
        omitted.append("max_ms")
    return results, db_reads, rows_examined, omitted


def _collect_items(query: str, god_name: str, phase: str, task_type: str, max_items: int, max_ms: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not _needs_memory_context(query, god_name, phase, task_type):
        return [], {
            "db_reads": 0,
            "rows_examined": 0,
            "omitted_reasons": ["classifier_no_memory_need"],
        }

    deadline = time.perf_counter() + max(max_ms, 1) / 1000.0
    query_terms = _terms(query)
    ranked: list[tuple[int, Anchor]] = []
    omitted_reasons: list[str] = []

    for anchor in ANCHORS:
        if time.perf_counter() > deadline:
            omitted_reasons.append("max_ms")
            break
        if not _source_exists_for(anchor):
            omitted_reasons.append("missing_source")
            continue
        role_tags = ROLE_TAGS & set(anchor.tags)
        if role_tags and god_name.lower() not in role_tags and phase.lower() not in anchor.tags:
            omitted_reasons.append("role_mismatch")
            continue
        score = _score(anchor, query_terms, god_name, phase, task_type)
        if score >= 90:
            ranked.append((score, anchor))
        else:
            omitted_reasons.append("low_authority")

    ranked.sort(key=lambda pair: (-pair[0], pair[1].source_id))
    selected: list[dict[str, Any]] = []
    for _, anchor in ranked[:max(max_items, 0)]:
        _append_unique(selected, _item(anchor))
    db_reads = 0
    rows_examined = 0
    if not selected and time.perf_counter() <= deadline:
        # Phase 1 keeps live DB reads as a bounded fallback, not a mandatory
        # addition to already-covered source anchors. This avoids making the
        # golden-query path heavier than the default compressor baseline.
        remaining_slots = max(max_items, 0) - len(selected)
        db_items, db_reads, rows_examined, db_omitted = _read_db_candidates(
            query, min(remaining_slots, 3), deadline
        )
        for item in db_items:
            if len(selected) >= max_items:
                break
            _append_unique(selected, item)
        omitted_reasons.extend(db_omitted)

    return selected, {
        "db_reads": db_reads,
        "rows_examined": rows_examined + len(ranked),
        "omitted_reasons": omitted_reasons,
    }


def _sectioned(items: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    sections = {section: [] for section in PRIMARY_SECTIONS}
    for item in items:
        anchor = next((a for a in ANCHORS if a.source_id == item.get("source_id")), None)
        section = anchor.section if anchor else "recent_changes"
        sections.setdefault(section, []).append(item)
    return sections


def _source_links(items: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    links: list[dict[str, str]] = []
    for item in items:
        key = (str(item.get("source_path", "")), str(item.get("source_id", "")))
        if key in seen:
            continue
        seen.add(key)
        links.append({
            "title": str(item.get("title", "")),
            "source_path": key[0],
            "source_id": key[1],
        })
    return links


def _render_context(pack: dict[str, Any]) -> str:
    lines = [
        f'<ichor-context source="ichor" mode="{pack["metrics"]["mode"]}" god="{pack["god"]}" phase="{pack["phase"]}">',
        (
            f'  <coverage status="{pack["coverage"]["status"]}" '
            f'returned="{pack["coverage"]["returned"]}" omitted="{pack["coverage"]["omitted"]}" />'
        ),
    ]
    for section in PRIMARY_SECTIONS:
        items = pack.get(section) or []
        if not items:
            continue
        xml_name = section.replace("_", "-")
        lines.append(f"  <{xml_name}>")
        for item in items:
            lines.append(
                f"    - {item['text']} Source: {item['source_path']}#{item['source_id']}"
            )
        lines.append(f"  </{xml_name}>")
    lines.append("</ichor-context>")
    return "\n".join(lines)


def _trim_to_budget(pack: dict[str, Any], max_tokens: int) -> int:
    removed = 0
    while _estimate_tokens_text(_render_context(pack)) > max_tokens:
        removed_this_round = False
        for section in reversed(PRIMARY_SECTIONS):
            items = pack.get(section) or []
            if items:
                items.pop()
                removed += 1
                removed_this_round = True
                break
        if not removed_this_round:
            break
    pack["injectable_context"] = _render_context(pack)
    return removed


def _primary_count(pack: dict[str, Any]) -> int:
    return sum(len(pack[section]) for section in PRIMARY_SECTIONS)


def build_context_pack(
    query: str,
    *,
    god_name: str,
    phase: str = "",
    task_type: str = "",
    max_items: int = 8,
    max_tokens: int = 900,
    max_ms: int = 350,
    include_graph: bool = True,
    dry_run: bool = False,
) -> dict:
    """Build a deterministic source-backed Ichor context pack."""
    initial_omissions: list[str] = []
    if include_graph:
        initial_omissions.append("graph_not_attempted_phase1")
    rss_before = _rss_kb()
    started = time.perf_counter()
    items, stats = _collect_items(query, god_name, phase, task_type, max_items, max_ms)
    sections = _sectioned(items)
    returned = sum(len(sections[section]) for section in PRIMARY_SECTIONS)
    omitted_reasons = initial_omissions + stats["omitted_reasons"]
    status = "ok" if returned else "low"
    if time.perf_counter() - started > max(max_ms, 1) / 1000.0:
        status = "low"
        omitted_reasons.append("max_ms")

    pack: dict[str, Any] = {
        "query": query,
        "god": god_name,
        "phase": phase,
        "injectable_context": "",
        "coverage": {
            "status": status,
            "returned": returned,
            "omitted": len(omitted_reasons),
            "warnings": [] if returned else ["no_source_backed_context_found"],
        },
        "current_decisions": sections["current_decisions"],
        "hard_constraints": sections["hard_constraints"],
        "relevant_files": sections["relevant_files"],
        "risks": sections["risks"],
        "related_entities": sections["related_entities"],
        "recent_changes": sections["recent_changes"],
        "source_links": _source_links(items),
        "omitted": {
            "count": len(omitted_reasons),
            "reasons": sorted(set(omitted_reasons)),
        },
        "metrics": {
            "wall_ms": 0,
            "db_reads": stats["db_reads"],
            "db_writes": 0,
            "rows_examined": stats["rows_examined"],
            "tokens_estimated": 0,
            "llm_calls": 0,
            "api_calls": 0,
            "rss_delta_kb": None,
            "mode": "dry_run" if dry_run else "manual",
        },
    }
    if returned:
        removed_for_budget = _trim_to_budget(pack, max(max_tokens, 1))
    else:
        removed_for_budget = 0
        pack["injectable_context"] = ""
    if removed_for_budget:
        pack["omitted"]["reasons"] = sorted(set(pack["omitted"]["reasons"] + ["token_budget"]))
        pack["omitted"]["count"] += removed_for_budget
    rss_after = _rss_kb()
    pack["coverage"]["returned"] = _primary_count(pack)
    pack["coverage"]["omitted"] = pack["omitted"]["count"]
    pack["coverage"]["warnings"] = [] if pack["coverage"]["returned"] else ["no_source_backed_context_found"]
    pack["metrics"]["tokens_estimated"] = _estimate_tokens_text(pack["injectable_context"])
    pack["metrics"]["wall_ms"] = int((time.perf_counter() - started) * 1000)
    pack["metrics"]["rss_delta_kb"] = (
        None if rss_before is None or rss_after is None else rss_after - rss_before
    )
    return pack


def ichor_context_pack(
    query: str,
    god_name: str = "",
    phase: str = "",
    task_type: str = "",
    max_items: int = 8,
    dry_run: bool = True,
) -> str:
    """Return the injectable context pack text for manual/tool callers."""
    pack = build_context_pack(
        query,
        god_name=god_name,
        phase=phase,
        task_type=task_type,
        max_items=max_items,
        dry_run=dry_run,
    )
    return pack["injectable_context"]
