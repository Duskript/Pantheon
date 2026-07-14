#!/usr/bin/env python3
"""Athenaeum scanner — extract entities and relationships from markdown knowledge files.

Walks the Athenaeum directory tree, reads markdown files, and passes them through
the L2 LLM extraction engine to produce structured entities and relationships in
the ER-P entity tables (ichor.db).

Design:
  - Uses lib.ichor.entities.l2_llm.extract_batch() for the LLM extraction
    (shared prompt + parse with the session-based L2 pipeline)
  - Checkpoint tracking by file mtime (JSON checkpoint file)
  - Batches files into groups for efficient LLM calls
  - Walks Codex directories via Athenaeum's INDEX.md tree

Modes:
  --index-only (default)  Scan only INDEX.md files per codex (cheap, ~60 files)
  --all                   Scan all markdown files (full 2,900+ pass)
  --codex NAME            Scan only a specific codex
  --force                 Re-process regardless of checkpoint
  --dry-run               Preview what would be processed

Usage:
    python3 -m lib.ichor.entities.athenaeum_scan
    python3 -m lib.ichor.entities.athenaeum_scan --codex Codex-Pantheon
    python3 -m lib.ichor.entities.athenaeum_scan --all --force
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.ichor.entities.schema import DB_PATH, get_conn
from lib.ichor.entities.l2_llm import extract_batch, build_prompt
from lib.ichor.entities.entity_type_seeds import seed_entity_types
from lib.ichor.entities.relationship_type_seeds import seed_relationship_types

logger = logging.getLogger("ichor.entities.athenaeum_scan")

# ── Config ────────────────────────────────────────────────────────────────

_REAL_HOME = os.path.expanduser("~konan")
ATHENAEUM_ROOT = Path(f"{_REAL_HOME}/athenaeum")
CHECKPOINT_PATH = Path(f"{_REAL_HOME}/.hermes/pantheon/athenaeum-scan-checkpoint.json")

# File extensions to process
EMBEDDABLE_EXTS = {".md", ".txt", ".json", ".yaml", ".yml"}

# Index files — the entrypoint for each codex
INDEX_FILENAME = "INDEX.md"

# Files to always skip (noise)
SKIP_FILENAMES = {
    "TEMPLATE.md",
    "SCHEMA.md",
    "compilation-log.md",
}

# Batch size for LLM calls — how many files per prompt
BATCH_SIZE = 10

# ── Checkpoint helpers ────────────────────────────────────────────────────


def _load_checkpoint() -> dict[str, float]:
    """Load checkpoint dict: {relative_path: last_modified_timestamp}."""
    if CHECKPOINT_PATH.exists():
        try:
            return json.loads(CHECKPOINT_PATH.read_text())
        except (json.JSONDecodeError, ValueError):
            logger.warning("corrupt checkpoint, starting fresh")
    return {}


def _save_checkpoint(checkpoint: dict[str, float]) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(checkpoint, indent=2))
    logger.info("checkpoint saved: %d entries", len(checkpoint))


def _file_mtime(path: Path) -> float:
    """Get file modification timestamp as float."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


# ── File discovery ────────────────────────────────────────────────────────


def _discover_files(
    root: Path = ATHENAEUM_ROOT,
    *,
    index_only: bool = False,
    codex_filter: str | None = None,
    force: bool = False,
) -> list[Path]:
    """Discover markdown files in the Athenaeum, respecting filters.

    Args:
        root: Athenaeum root directory.
        index_only: Only return INDEX.md files.
        codex_filter: If set, only scan this codex (e.g. 'Codex-Pantheon').
        force: Ignore checkpoint (return all files regardless).
    """
    files: list[Path] = []
    checkpoint = {} if force else _load_checkpoint()

    # Walk the Athenaeum directory tree
    for dirpath_str, _dirnames, filenames in os.walk(root):
        dirpath = Path(dirpath_str)

        # Apply codex filter
        if codex_filter:
            # Check if this path is within the requested codex
            try:
                rel = dirpath.relative_to(root)
            except ValueError:
                continue
            parts = rel.parts
            if not parts or parts[0] != codex_filter:
                # Allow the codex itself and its subdirs
                if not any(codex_filter in p for p in parts):
                    continue

        for fname in filenames:
            if fname in SKIP_FILENAMES:
                continue
            ext = Path(fname).suffix.lower()
            if ext not in EMBEDDABLE_EXTS:
                continue

            # Index-only mode: skip non-INDEX files
            if index_only and fname != INDEX_FILENAME:
                continue

            fpath = dirpath / fname
            try:
                rel_path = str(fpath.relative_to(root))
            except ValueError:
                rel_path = str(fpath)

            # Checkpoint: skip if mtime unchanged
            if not force:
                last_mtime = checkpoint.get(rel_path)
                current_mtime = _file_mtime(fpath)
                if last_mtime is not None and current_mtime <= last_mtime:
                    continue

            files.append(fpath)

    # Sort for deterministic ordering
    files.sort(key=lambda p: str(p))
    logger.info(
        "discovered %d files (index_only=%s, codex_filter=%s, force=%s)",
        len(files), index_only, codex_filter, force,
    )
    return files


# ── File content helpers ──────────────────────────────────────────────────


def _read_file_content(path: Path, max_chars: int = 3000) -> str | None:
    """Read file content, truncated to max_chars.

    Returns None if the file can't be read.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("can't read %s: %s", path, exc)
        return None

    if not text.strip():
        return None

    # Truncate very long files
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... [truncated from {len(text)} chars]"

    return text


# ── LLM extraction ────────────────────────────────────────────────────────


def _run_extraction(
    file_texts: list[tuple[Path, str]],
    provider_cfg: dict[str, Any] | None = None,
    call_fn=None,
) -> list[tuple[Path, dict[str, Any] | None]]:
    """Run L2 extraction on a batch of files.

    Returns list of (path, parsed_result_or_None) pairs.
    """
    if not file_texts:
        return []

    texts = [t for _, t in file_texts]
    if provider_cfg is None:
        provider_cfg = {"name": "stub", "default_model": "stub"}

    try:
        parsed = extract_batch(
            texts,
            provider_cfg,
            call_fn=call_fn,
            timeout=180.0,
        )
    except Exception as exc:
        logger.error("extraction batch failed: %s", exc)
        return [(path, None) for path, _ in file_texts]

    # extract_batch returns a dict with entities, relationships, relationship_types
    # It's a single result for the batch, not per-file
    return [(file_texts[0][0], parsed)]  # Attach to first file


# ── Storage ───────────────────────────────────────────────────────────────


def _store_extraction(
    conn,
    parsed: dict[str, Any],
    source_file: str,
    source_ref: str = "athenaeum_scan",
) -> dict[str, int]:
    """Store extracted entities/relationships into ER-P tables.

    Returns count of items stored.
    """
    entities = parsed.get("entities", []) or []
    relationships = parsed.get("relationships", []) or []
    rel_types = parsed.get("relationship_types", []) or []

    # Register any novel relationship types
    for rt in rel_types:
        existing = conn.execute(
            "SELECT 1 FROM relationship_types WHERE id = ?", (rt["id"],)
        ).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO relationship_types
                   (id, description, source_type, target_type,
                    is_temporal, is_directional, family, created_at)
                   VALUES (?, ?, NULL, NULL, 1, 1, ?, datetime('now'))""",
                (rt["id"], rt.get("description", ""), rt.get("family", "reference")),
            )

    # Extract entity type IDs used
    entity_type_ids = {e.get("type", "concept") for e in entities if e.get("type")}
    for etid in entity_type_ids:
        existing = conn.execute(
            "SELECT 1 FROM entity_types WHERE id = ?", (etid,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO entity_types (id, description, icon) VALUES (?, ?, ?)",
                (etid, f"Auto-created by Athenaeum scan for type '{etid}'", "📄"),
            )

    # Store entities
    entity_id_map: dict[str, int] = {}  # name -> id
    entities_created = 0
    for ent in entities:
        name = ent.get("name", "").strip()
        if not name:
            continue

        # Check for existing entity with same name + type
        etype = ent.get("type", "concept")
        existing = conn.execute(
            "SELECT id FROM entities WHERE name = ? AND type_id = ?",
            (name, etype),
        ).fetchone()
        if existing:
            entity_id_map[name] = existing["id"]
            # Update summary if new info
            summary = ent.get("summary", "")
            if summary:
                conn.execute(
                    "UPDATE entities SET summary = ?, updated_at = datetime('now') WHERE id = ?",
                    (summary[:500], existing["id"]),
                )
            continue

        # Insert new entity
        cursor = conn.execute(
            """INSERT INTO entities (type_id, name, aliases, summary, confidence)
               VALUES (?, ?, ?, ?, ?)""",
            (
                etype,
                name,
                json.dumps(ent.get("aliases", [])),
                (ent.get("summary", "") or "")[:500],
                min(ent.get("confidence", 0.8), 1.0),
            ),
        )
        entity_id_map[name] = cursor.lastrowid
        entities_created += 1

        # Log extraction
        conn.execute(
            """INSERT INTO extraction_log (entity_id, method, source_text, source_session_id, confidence)
               VALUES (?, 'llm', ?, ?, ?)""",
            (cursor.lastrowid, source_file, source_ref, ent.get("confidence", 0.8)),
        )

    # Store relationships
    rels_created = 0
    for rel in relationships:
        source_name = rel.get("source", "").strip()
        target_name = rel.get("target", "").strip()
        rel_type = rel.get("type", "related_to")
        if not source_name or not target_name:
            continue
        src_id = entity_id_map.get(source_name)
        tgt_id = entity_id_map.get(target_name)
        if src_id is None or tgt_id is None:
            # One of the entities wasn't created (shouldn't happen with good data)
            continue

        # Check for duplicate
        existing = conn.execute(
            "SELECT 1 FROM relationships WHERE type_id = ? AND source_id = ? AND target_id = ?",
            (rel_type, src_id, tgt_id),
        ).fetchone()
        if existing:
            continue

        conn.execute(
            """INSERT INTO relationships
               (type_id, source_id, target_id, confidence, weight, provenance, source_ref)
               VALUES (?, ?, ?, ?, 1.0, 'llm', ?)""",
            (rel_type, src_id, tgt_id, min(rel.get("confidence", 0.8), 1.0), source_file),
        )
        rels_created += 1

    conn.commit()
    return {
        "entities_created": entities_created,
        "relationships_created": rels_created,
        "relationship_types_registered": len(rel_types),
        "total_in_batch": len(entities) + len(relationships),
    }


# ── Orchestrator ──────────────────────────────────────────────────────────


def run_scan(
    *,
    index_only: bool = True,
    codex_filter: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    batch_size: int = BATCH_SIZE,
    provider_cfg: dict[str, Any] | None = None,
    call_fn=None,
) -> dict[str, Any]:
    """Run the Athenaeum scan.

    Returns aggregate stats.
    """
    files = _discover_files(
        index_only=index_only,
        codex_filter=codex_filter,
        force=force,
    )

    if not files:
        logger.info("no files to process (all up to date)")
        return {"files_discovered": 0, "files_processed": 0, "entities_created": 0}

    if dry_run:
        logger.info("DRY RUN: would process %d files:", len(files))
        for f in files:
            logger.info("  %s", f.relative_to(ATHENAEUM_ROOT))
        return {
            "files_discovered": len(files),
            "files_dry_run": True,
            "files_processed": 0,
        }

    conn = get_conn()
    checkpoint = {} if force else _load_checkpoint()
    started = time.time()

    total_processed = 0
    total_entities = 0
    total_relationships = 0
    files_skipped = 0

    # Process in batches
    for i in range(0, len(files), batch_size):
        batch = files[i : i + batch_size]
        batch_texts: list[tuple[Path, str]] = []

        for fpath in batch:
            content = _read_file_content(fpath)
            if content is None:
                continue

            # Add a header with the file path so the LLM has context
            try:
                rel = str(fpath.relative_to(ATHENAEUM_ROOT))
            except ValueError:
                rel = str(fpath)
            headed_content = f"[File: {rel}]\n{content}"
            batch_texts.append((fpath, headed_content))

        if not batch_texts:
            continue

        # Run extraction on this batch
        if provider_cfg and provider_cfg.get("name") != "stub":
            # Real LLM call
            results = _run_extraction(batch_texts, provider_cfg=provider_cfg, call_fn=call_fn)
        else:
            # Stub/dry mode — use a mock result
            logger.info("stub mode — would extract %d files (pass --provider-config for real LLM)", len(batch_texts))
            results = [(path, None) for path, _ in batch_texts]

        for fpath, parsed in results:
            if parsed is None:
                files_skipped += 1
                continue

            try:
                rel = str(fpath.relative_to(ATHENAEUM_ROOT))
            except ValueError:
                rel = str(fpath)

            stored = _store_extraction(conn, parsed, source_file=rel)
            total_entities += stored["entities_created"]
            total_relationships += stored["relationships_created"]
            total_processed += 1

            # Update checkpoint
            checkpoint[rel] = _file_mtime(fpath)

        # Save checkpoint after each batch
        if total_processed % (batch_size * 2) == 0 and total_processed > 0:
            _save_checkpoint(checkpoint)

        if (i // batch_size) % 10 == 0 and i > 0:
            logger.info(
                "progress: %d/%d files processed, +%d entities, +%d relationships",
                total_processed, len(files), total_entities, total_relationships,
            )

    # Final checkpoint save
    _save_checkpoint(checkpoint)

    elapsed = time.time() - started
    logger.info(
        "scan complete: %d files processed, %d skipped, %d entities, %d relationships in %.1fs",
        total_processed, files_skipped, total_entities, total_relationships, elapsed,
    )

    conn.close()
    return {
        "files_discovered": len(files),
        "files_processed": total_processed,
        "files_skipped": files_skipped,
        "entities_created": total_entities,
        "relationships_created": total_relationships,
        "elapsed_seconds": round(elapsed, 1),
    }


# ── CLI ───────────────────────────────────────────────────────────────────


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Athenaeum entity scanner")
    parser.add_argument("--index-only", action="store_true", default=True,
                        help="Scan only INDEX.md files (default: True)")
    parser.add_argument("--all", action="store_false", dest="index_only",
                        help="Scan all markdown files (not just INDEX.md)")
    parser.add_argument("--codex", default=None,
                        help="Scan only this codex (e.g. 'Codex-Pantheon')")
    parser.add_argument("--force", action="store_true",
                        help="Re-process regardless of checkpoint")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be processed without doing it")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help=f"Files per LLM call (default: {BATCH_SIZE})")
    parser.add_argument("--provider-config", default=None,
                        help="Path to provider config JSON (for real LLM calls)")
    args = parser.parse_args()

    # Ensure entity and relationship types are seeded
    conn = get_conn()
    try:
        seed_entity_types(conn)
        seed_relationship_types(conn)
        conn.commit()
    finally:
        conn.close()

    provider_cfg = None
    if args.provider_config:
        p = Path(args.provider_config)
        if p.exists():
            provider_cfg = json.loads(p.read_text())
        else:
            logger.warning("provider config not found: %s; running in stub mode", args.provider_config)

    result = run_scan(
        index_only=args.index_only,
        codex_filter=args.codex,
        force=args.force,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        provider_cfg=provider_cfg,
    )

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
