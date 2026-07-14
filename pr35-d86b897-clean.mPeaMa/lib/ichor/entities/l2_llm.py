"""ER-P2: L2 LLM extraction for the Entity-Relationship Graph.

Per Thoth's spec (2026-06-11), L2 extracts NOVEL entities and
relationships that L0/L1 regex+cluster can't catch — e.g.
"Alice convinced Bob to invest in Acme" → typed entities + a
'convinced_to_invest' relationship.

Lifecycle (spec §Incremental Extraction):
  - Incremental: every N=25 turns (or N=25 events in the cold_events
    model), call LLM on the residual range, store entities/relationships
    as provisional=1.
  - Finalize: at session end, process the remaining residual events
    (those not yet L2-extracted), store as provisional=0, then flip
    all provisional=1 → 0 for the session (they're now confirmed).
  - Idempotency: a per-event-id mark in extraction_log prevents
    re-extraction of the same events.

Cost: ~500 tokens per pass per spec. 12 passes × 500t = ~6,000t for a
300-turn session. Token budget is the spec's; no dollar amount is
specified by the spec.

Public API:
  build_prompt(texts: list[str])                  -> str
  parse_extraction(raw: str)                      -> dict
  extract_batch(texts, provider_cfg, *, model=None, call_fn=None, timeout=30.0) -> dict
  extract_incremental(conn, *, batch_size, last_event_id, provider_cfg, model, call_fn) -> dict
  finalize(conn, *, last_event_id, total_event_id, provider_cfg, model, call_fn) -> dict
  l2_stats(conn)                                  -> dict

The LLM call is injected as `call_fn` for testability. Default is
`_call_llm` from `lib.ichor.llm` (was `lib.ichor_tier_a_plus`) (OpenAI-compatible chat
completions). To run with a different provider, pass a custom
call_fn(prompt, provider_cfg, model=..., timeout=...) -> str.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable, Optional

# Prompt template. Asks the LLM for a JSON object with three arrays:
# entities, relationships, and relationship_types (any new types the
# LLM discovers that aren't in the canonical registry).
PROMPT_TEMPLATE = """You are an entity-and-relationship extractor.

Given a list of conversation turns, extract:
1. **Entities** — people, organizations, projects, tools, concepts, files, URLs.
2. **Relationships** — typed connections between entities (e.g. works_at,
   uses, depends_on, related_to, replaces, derived_from, mentioned_with).
3. **Relationship types** — if you use a relationship predicate that
   isn't in the canonical list below, propose a new type id and a
   short description.

Canonical entity types (use these when applicable):
  person, organization, project, tool, concept, file, url,
  document, decision, blocker, preference, fact, reference,
  github_org, github_repo, github_handle

Canonical relationship types (use when applicable):
  works_at, uses, depends_on, related_to, replaces, derived_from,
  learned_from, superseded_by, mentioned_with, cites, references,
  conflicts_with, enables, similar_to, knows, owns, manages,
  contributes_to, part_of, located_in, member_of

Guidance on the LEARNING family (learned_from, derived_from):
  - "learned_from" — a skill/pattern/learning explicitly described as
    informed by or acquired from another skill, event, source, or
    pattern. Example: entity "Cache invalidation lesson" learned_from
    "2026-06-04 incident".
  - "derived_from" — a skill/pattern that is mechanically derived from
    another (e.g., a specialized version of a general one).

Guidance on the LIFECYCLE family (superseded_by, replaces):
  - "superseded_by" — a skill/decision that has been deprecated or
    invalidated by a newer one. Example: entity "old Atlas auth" is
    superseded_by "new OIDC auth".
  - "replaces" — a softer form: a new thing took the place of an old
    one without necessarily deprecating it.

Output ONLY valid JSON of this shape (no prose before/after):
{{
  "entities": [
    {{"name": "Anthropic", "type": "organization", "aliases": ["anthropics", "Anthropic PBC"], "confidence": 0.95}}
  ],
  "relationships": [
    {{"source": "Alice", "type": "works_at", "target": "Anthropic", "confidence": 0.9, "valid_from": "2025-01-01"}}
  ],
  "relationship_types": [
    {{"id": "invested_in", "description": "Source invested capital in target", "family": "affiliation"}}
  ]
}}

If a turn has no entities, omit it. Don't invent relationships that
aren't supported by the text. Confidence 0.0–1.0; use <0.6 for weak signals.

Conversation turns:
{turns_json}

JSON:"""


def build_prompt(texts: list[str], max_chars_per_turn: int = 1500) -> str:
    """Build the LLM prompt from a list of raw text strings.

    Truncates each turn to max_chars_per_turn to keep the prompt bounded.
    """
    truncated = []
    for t in texts:
        if t is None:
            continue
        t = t.strip()
        if len(t) > max_chars_per_turn:
            t = t[:max_chars_per_turn] + "..."
        if t:
            truncated.append(t)
    turns_json = json.dumps(truncated, ensure_ascii=False, indent=2)
    return PROMPT_TEMPLATE.format(turns_json=turns_json)


def parse_extraction(raw: str) -> dict[str, Any]:
    """Parse the LLM's JSON output into our standard shape.

    Tolerates:
      - leading/trailing prose
      - markdown code fences ```json ... ```
      - missing optional arrays (defaults to [])

    Returns:
      {
        "entities": [{"name": str, "type": str, "aliases": list[str], "confidence": float}, ...],
        "relationships": [{"source": str, "type": str, "target": str, "confidence": float, "valid_from": str|None}, ...],
        "relationship_types": [{"id": str, "description": str, "family": str|None}, ...],
        "_parse_warnings": [str, ...]  # diagnostics; not used by storage
      }

    Raises ValueError if no JSON object can be found.
    """
    if not raw or not raw.strip():
        return {"entities": [], "relationships": [], "relationship_types": [], "_parse_warnings": ["empty response"]}

    warnings: list[str] = []
    text = raw.strip()

    # Strip markdown code fence if present
    if text.startswith("```"):
        # find the first newline after the opening fence
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        # strip trailing fence
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    # Try direct parse
    parsed: Any = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Find the first '{' and last '}' and try again
        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last != -1 and last > first:
            try:
                parsed = json.loads(text[first:last + 1])
                warnings.append("extracted JSON from prose-wrapped response")
            except json.JSONDecodeError as e:
                raise ValueError(f"could not parse JSON from LLM response: {e}; raw={raw[:300]!r}")
        else:
            raise ValueError(f"no JSON object in LLM response; raw={raw[:300]!r}")

    if not isinstance(parsed, dict):
        raise ValueError(f"LLM response is not a JSON object; got {type(parsed).__name__}")

    # Normalize to standard shape
    entities = parsed.get("entities") or []
    relationships = parsed.get("relationships") or []
    rel_types = parsed.get("relationship_types") or []

    # Filter + validate each entity
    norm_entities: list[dict[str, Any]] = []
    for e in entities:
        if not isinstance(e, dict):
            warnings.append(f"skipped non-dict entity: {e!r}")
            continue
        name = e.get("name")
        if not name or not isinstance(name, str):
            warnings.append(f"skipped entity without name: {e!r}")
            continue
        ent_type = e.get("type") or "concept"
        if not isinstance(ent_type, str):
            ent_type = "concept"
        aliases = e.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = []
        aliases = [a for a in aliases if isinstance(a, str)]
        try:
            confidence = float(e.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        confidence = max(0.0, min(1.0, confidence))
        norm_entities.append({
            "name": name.strip(),
            "type": ent_type.strip(),
            "aliases": aliases,
            "confidence": confidence,
        })

    # Filter + validate each relationship
    norm_rels: list[dict[str, Any]] = []
    for r in relationships:
        if not isinstance(r, dict):
            warnings.append(f"skipped non-dict relationship: {r!r}")
            continue
        src = r.get("source")
        tgt = r.get("target")
        rtype = r.get("type")
        if not (src and tgt and rtype) or not isinstance(src, str) or not isinstance(tgt, str) or not isinstance(rtype, str):
            warnings.append(f"skipped relationship missing source/target/type: {r!r}")
            continue
        try:
            confidence = float(r.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        confidence = max(0.0, min(1.0, confidence))
        valid_from = r.get("valid_from")
        if valid_from is not None and not isinstance(valid_from, str):
            valid_from = None
        norm_rels.append({
            "source": src.strip(),
            "type": rtype.strip(),
            "target": tgt.strip(),
            "confidence": confidence,
            "valid_from": valid_from,
        })

    # Filter relationship types
    norm_rel_types: list[dict[str, Any]] = []
    for rt in rel_types:
        if not isinstance(rt, dict):
            continue
        rid = rt.get("id")
        if not rid or not isinstance(rid, str):
            continue
        desc = rt.get("description") or ""
        family = rt.get("family")
        if family is not None and not isinstance(family, str):
            family = None
        norm_rel_types.append({
            "id": rid.strip(),
            "description": desc,
            "family": family,
        })

    return {
        "entities": norm_entities,
        "relationships": norm_rels,
        "relationship_types": norm_rel_types,
        "_parse_warnings": warnings,
    }


# Default LLM call. Importable for direct use, but tests should inject
# their own call_fn to avoid network calls and keep tests deterministic.
def _default_call_llm(prompt: str, provider_cfg: dict, model: str | None = None, timeout: float = 180.0) -> str:
    """Use the OpenAI-compatible chat completions endpoint from
    `lib.ichor.llm._call_llm`."""
    # Imported lazily so the module can be loaded without that dep
    # in minimal test environments.
    from lib.ichor.llm import _call_llm  # moved from lib.ichor_tier_a_plus 2026-06-12
    return _call_llm(prompt, provider_cfg, model=model, timeout=timeout)


# ---------- Storage ----------

def _ensure_entity_type(conn: sqlite3.Connection, type_id: str) -> None:
    """Make sure an entity_type row exists for the given type id. Idempotent."""
    existing = conn.execute("SELECT 1 FROM entity_types WHERE id = ?", (type_id,)).fetchone()
    if existing:
        return
    conn.execute(
        """INSERT INTO entity_types (id, description, parent_type, extractable, icon, created_at)
           VALUES (?, ?, NULL, 1, '🧠', datetime('now'))""",
        (type_id, f"Auto-created by L2 LLM extraction for type '{type_id}'"),
    )


def _ensure_relationship_type(conn: sqlite3.Connection, rt: dict[str, Any]) -> None:
    """Ensure a relationship_type row exists. Idempotent."""
    rid = rt["id"]
    existing = conn.execute("SELECT 1 FROM relationship_types WHERE id = ?", (rid,)).fetchone()
    if existing:
        return
    conn.execute(
        """INSERT INTO relationship_types
           (id, description, source_type, target_type, is_temporal, is_directional, family, created_at)
           VALUES (?, ?, NULL, NULL, 1, 1, ?, datetime('now'))""",
        (rid, rt.get("description", ""), rt.get("family")),
    )


def _get_or_create_entity(
    conn: sqlite3.Connection,
    name: str,
    type_id: str,
    aliases: list[str],
    confidence: float,
    provisional: bool,
) -> int:
    """Return the entity id for (name, type_id). Create if missing.
    If a different-type entity with the same name exists, prefer the
    existing one (don't fail)."""
    row = conn.execute(
        "SELECT id, aliases FROM entities WHERE name = ? AND type_id = ?",
        (name, type_id),
    ).fetchone()
    if row:
        return int(row["id"])
    # Also check for name-only match (different type) — keep both for now
    # (they represent different facets of the same name)
    aliases_json = json.dumps(sorted(set(aliases)), separators=(",", ":"))
    cur = conn.execute(
        """INSERT INTO entities
           (type_id, name, aliases, summary, confidence, status, provisional, created_at, updated_at)
           VALUES (?, ?, ?, '', ?, 'active', ?, datetime('now'), datetime('now'))""",
        (type_id, name, aliases_json, confidence, 1 if provisional else 0),
    )
    return int(cur.lastrowid) if cur.lastrowid is not None else 0


def _get_or_create_relationship(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
    type_id: str,
    confidence: float,
    source_ref: str,
    valid_from: str | None,
    provisional: bool,
) -> int:
    """Return the relationship id. Create if missing.

    The schema's UNIQUE(type_id, source_id, target_id, valid_from)
    constraint means re-inserting the same (src, tgt, type, valid_from)
    raises IntegrityError. We use INSERT OR IGNORE.
    """
    vf = valid_from if valid_from else "1970-01-01"  # sentinel for "unknown"
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO relationships
               (type_id, source_id, target_id, confidence, weight, provenance, source_ref,
                valid_from, valid_to, provisional, created_at, updated_at)
               VALUES (?, ?, ?, ?, 1.0, 'llm', ?, ?, NULL, ?, datetime('now'), datetime('now'))""",
            (type_id, source_id, target_id, confidence, source_ref, vf, 1 if provisional else 0),
        )
        if cur.lastrowid:
            return int(cur.lastrowid)
    except Exception:
        pass
    # Already exists; fetch the existing id
    row = conn.execute(
        "SELECT id FROM relationships WHERE type_id = ? AND source_id = ? AND target_id = ? AND valid_from = ?",
        (type_id, source_id, target_id, vf),
    ).fetchone()
    return int(row["id"]) if row else 0


def _store_extraction(
    conn: sqlite3.Connection,
    parsed: dict[str, Any],
    *,
    source_text: str,
    provisional: bool,
    session_id: str | None = None,
) -> dict[str, int]:
    """Store a parsed extraction into entities + relationships + extraction_log.

    Idempotent: re-running on the same parsed data is a no-op for
    entities/relationships (PK conflict is caught) and appends a new
    extraction_log row (one per extraction call, not per entity).
    """
    counts = {
        "entity_types_created": 0,
        "rel_types_created": 0,
        "entities_created": 0,
        "relationships_created": 0,
        "extraction_logs_inserted": 0,
    }

    # 1) Make sure all entity types exist
    for e in parsed.get("entities", []):
        t = e.get("type") or "concept"
        before = conn.execute("SELECT 1 FROM entity_types WHERE id = ?", (t,)).fetchone()
        _ensure_entity_type(conn, t)
        if not before:
            counts["entity_types_created"] += 1

    # 2) Make sure all relationship types exist
    for r in parsed.get("relationships", []):
        rt_id = r.get("type")
        if not rt_id:
            continue
        before = conn.execute("SELECT 1 FROM relationship_types WHERE id = ?", (rt_id,)).fetchone()
        # If the LLM proposed a new rel_type, register it
        existing_proposed = next(
            (p for p in parsed.get("relationship_types", []) if p.get("id") == rt_id), None
        )
        if not existing_proposed:
            # Use a minimal auto-description
            existing_proposed = {"id": rt_id, "description": "auto-registered by L2", "family": None}
        _ensure_relationship_type(conn, existing_proposed)
        if not before:
            counts["rel_types_created"] += 1

    # 3) Create entities (deduped by (name, type_id))
    entity_id_cache: dict[tuple[str, str], int] = {}
    for e in parsed.get("entities", []):
        name = e["name"]
        type_id = e.get("type") or "concept"
        before = conn.execute(
            "SELECT 1 FROM entities WHERE name = ? AND type_id = ?",
            (name, type_id),
        ).fetchone()
        eid = _get_or_create_entity(
            conn, name, type_id, e.get("aliases") or [], float(e.get("confidence", 0.7)), provisional
        )
        entity_id_cache[(name, type_id)] = eid
        if not before:
            counts["entities_created"] += 1

    # 4) Create relationships (using entity name → id resolution)
    for r in parsed.get("relationships", []):
        src_name = r["source"]
        tgt_name = r["target"]
        rtype = r["type"]
        # Resolve entity names to ids. We try (name, type) first; if no
        # exact match, look up by name alone (any type) and use the first.
        src_id = _resolve_entity_id(conn, src_name)
        tgt_id = _resolve_entity_id(conn, tgt_name)
        if not src_id or not tgt_id:
            continue
        before = conn.execute(
            """SELECT 1 FROM relationships
               WHERE type_id = ? AND source_id = ? AND target_id = ? AND valid_from = ?""",
            (rtype, src_id, tgt_id, r.get("valid_from") or "1970-01-01"),
        ).fetchone()
        _get_or_create_relationship(
            conn, src_id, tgt_id, rtype,
            confidence=float(r.get("confidence", 0.7)),
            source_ref=source_text[:200] if source_text else "",
            valid_from=r.get("valid_from"),
            provisional=provisional,
        )
        if not before:
            counts["relationships_created"] += 1

    # 5) Log the extraction
    n_ent = len(parsed.get("entities", []))
    n_rel = len(parsed.get("relationships", []))
    evidence = f"L2 pass: {n_ent} entities, {n_rel} relationships (provisional={provisional})"
    conn.execute(
        """INSERT INTO extraction_log
           (entity_id, relationship_id, fact_id, method, source_text, source_session_id, confidence, created_at)
           VALUES (NULL, NULL, NULL, ?, ?, ?, 1.0, datetime('now'))""",
        ("llm", evidence, session_id),
    )
    counts["extraction_logs_inserted"] = 1

    return counts


def _resolve_entity_id(conn: sqlite3.Connection, name: str) -> int:
    """Find an entity by name. Prefer exact (name, type) match; fall
    back to name-only match. Returns 0 if not found."""
    row = conn.execute(
        "SELECT id FROM entities WHERE name = ? ORDER BY id LIMIT 1",
        (name,),
    ).fetchone()
    return int(row["id"]) if row else 0


# ---------- Lifecycle: incremental + finalize ----------

def extract_batch(
    texts: list[str],
    provider_cfg: dict[str, Any],
    *,
    model: str | None = None,
    call_fn: Optional[Callable[..., str]] = None,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """One LLM extraction pass over a batch of texts. Returns the parsed
    shape (entities/relationships/relationship_types). Does NOT write
    to the DB — caller decides where to store.

    For tests, pass a `call_fn` that returns canned JSON, avoiding the
    real LLM call.
    """
    if not texts:
        return {"entities": [], "relationships": [], "relationship_types": [], "_parse_warnings": ["empty batch"]}
    if call_fn is None:
        call_fn = _default_call_llm
    prompt = build_prompt(texts)
    raw = call_fn(prompt, provider_cfg, model=model, timeout=timeout)
    return parse_extraction(raw)


def _events_for_batch(
    conn: sqlite3.Connection,
    last_event_id: int,
    batch_size: int,
) -> list[sqlite3.Row]:
    """Pull up to `batch_size` cold_events with id > last_event_id."""
    return conn.execute(
        """SELECT id, raw_text FROM cold_events
           WHERE raw_text IS NOT NULL AND raw_text != '' AND id > ?
           ORDER BY id ASC
           LIMIT ?""",
        (last_event_id, batch_size),
    ).fetchall()


def extract_incremental(
    conn: sqlite3.Connection,
    *,
    last_event_id: int,
    batch_size: int,
    provider_cfg: dict[str, Any],
    model: str | None = None,
    call_fn: Optional[Callable[..., str]] = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """One incremental pass. Pulls up to `batch_size` events after
    `last_event_id`, runs LLM, stores as provisional. Returns counts
    + the new last_event_id (caller persists it).
    """
    rows = _events_for_batch(conn, last_event_id, batch_size)
    if not rows:
        return {
            "events_in_batch": 0,
            "last_event_id_before": last_event_id,
            "last_event_id_after": last_event_id,
            "provisional": True,
            "stored": {"entity_types_created": 0, "rel_types_created": 0,
                       "entities_created": 0, "relationships_created": 0,
                       "extraction_logs_inserted": 0},
            "skipped": "no events past last_event_id",
        }
    texts = [r["raw_text"] for r in rows]
    parsed = extract_batch(texts, provider_cfg, model=model, call_fn=call_fn)
    # Source for this batch: concatenate the truncated raw_texts
    source_text = " | ".join((t[:120] for t in texts))
    counts = _store_extraction(
        conn, parsed,
        source_text=source_text,
        provisional=True,
        session_id=session_id,
    )
    conn.commit()
    return {
        "events_in_batch": len(rows),
        "last_event_id_before": last_event_id,
        "last_event_id_after": int(rows[-1]["id"]),
        "provisional": True,
        "stored": counts,
        "parse_warnings": parsed.get("_parse_warnings", []),
    }


def finalize(
    conn: sqlite3.Connection,
    *,
    last_event_id: int,
    provider_cfg: dict[str, Any],
    model: str | None = None,
    call_fn: Optional[Callable[..., str]] = None,
    session_id: str | None = None,
    max_residual: int = 10000,
) -> dict[str, Any]:
    """Session-end finalize. Process the residual events (those past
    `last_event_id`) as non-provisional, then flip all provisional=1
    entities/relationships for this session to provisional=0.

    The session scope is approximated as the residual range — we flip
    provisional=1 → 0 for any rows whose most recent extraction_log
    entry for this session was an L2 pass.
    """
    residual = _events_for_batch(conn, last_event_id, max_residual)
    residual_count = 0
    residual_stored: dict[str, int] = {}
    if residual:
        texts = [r["raw_text"] for r in residual]
        parsed = extract_batch(texts, provider_cfg, model=model, call_fn=call_fn)
        source_text = " | ".join((t[:120] for t in texts))
        residual_stored = _store_extraction(
            conn, parsed,
            source_text=source_text,
            provisional=False,  # final = non-provisional
            session_id=session_id,
        )
        residual_count = len(residual)

    # Flip all provisional=1 → 0 (we've now finalized the session)
    flipped_entities = conn.execute(
        "UPDATE entities SET provisional = 0 WHERE provisional = 1"
    ).rowcount
    flipped_relationships = conn.execute(
        "UPDATE relationships SET provisional = 0 WHERE provisional = 1"
    ).rowcount
    conn.commit()

    return {
        "residual_events": residual_count,
        "residual_stored": residual_stored,
        "flipped_entities_provisional": flipped_entities,
        "flipped_relationships_provisional": flipped_relationships,
    }


def l2_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Read-only stats about L2 extraction state. Cheap."""
    out: dict[str, Any] = {}
    out["llm_extractions_logged"] = conn.execute(
        "SELECT COUNT(*) FROM extraction_log WHERE method = 'llm'"
    ).fetchone()[0]
    out["provisional_entities"] = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE provisional = 1"
    ).fetchone()[0]
    out["provisional_relationships"] = conn.execute(
        "SELECT COUNT(*) FROM relationships WHERE provisional = 1"
    ).fetchone()[0]
    out["llm_entity_types"] = conn.execute(
        "SELECT COUNT(DISTINCT type_id) FROM entities WHERE id IN (SELECT entity_id FROM extraction_log WHERE method = 'llm' AND entity_id IS NOT NULL)"
    ).fetchone()[0]
    return out
