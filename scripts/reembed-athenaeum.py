#!/usr/bin/env python3
"""Clean re-embed of the entire Athenaeum into ChromaDB.

Destroys and recreates all collections so dimensions are consistent
with the current embedder (OpenRouter, 2048-dim).

Usage:
  OPENROUTER_API_KEY="sk-or-..." python3 scripts/reembed-athenaeum.py
  python3 scripts/reembed-athenaeum.py --clean  # same as default
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("reembed")

_REAL_HOME = os.path.expanduser("~konan")
ATHENAEUM_ROOT = Path(f"{_REAL_HOME}/athenaeum")
CHROMA_DIR = Path(f"{_REAL_HOME}/.hermes/pantheon/chroma")
EMBED_MODEL = os.environ.get(
    "ATHENAEUM_EMBED_MODEL",
    "nvidia/llama-nemotron-embed-vl-1b-v2:free",
)
EMBED_API_URL = os.environ.get(
    "ATHENAEUM_EMBED_URL",
    "https://openrouter.ai/api/v1/embeddings",
)
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
EMBEDDABLE_EXTS = {".md", ".txt", ".json", ".yaml", ".yml"}


def _partition_for(codex: str) -> str:
    return f"pantheon_{codex.lower().replace('-', '_')}"


def _list_codexes(root: Path) -> List[str]:
    return sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and d.name.startswith("Codex-")
    )


def _walk_files(root: Path) -> List[Tuple[str, str, str]]:
    """Mirrors plugin's _walk_athenaeum_files logic."""
    results = []
    for codex_dir in root.iterdir():
        if not codex_dir.is_dir() or not codex_dir.name.startswith("Codex-"):
            continue
        codex = codex_dir.name
        for file_path in codex_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in EMBEDDABLE_EXTS:
                continue
            rel = file_path.relative_to(root)
            parts = rel.parts
            if "archive" in parts or "distilled" in parts:
                continue
            if file_path.name == "INDEX.md":
                continue
            results.append((str(rel), str(file_path), codex))
    return results


def main():
    import chromadb
    import requests

    # ── Test embedder connection ─────────────────────────────────────────
    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY is not set")
        sys.exit(1)

    logger.info("Testing OpenRouter embedding with %s...", EMBED_MODEL)
    try:
        test_resp = requests.post(
            EMBED_API_URL,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": EMBED_MODEL, "input": "test"},
            timeout=30,
        )
        test_resp.raise_for_status()
        test_data = test_resp.json()
        test_dim = len(test_data["data"][0]["embedding"])
        logger.info("  ✓ OpenRouter available, embedding dimension: %d", test_dim)
    except Exception as exc:
        logger.error("OpenRouter embedding failed: %s", exc)
        sys.exit(1)

    # ── Wipe existing collections ────────────────────────────────────────
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    existing = client.list_collections()
    if existing:
        logger.info("Deleting %d existing collections...", len(existing))
        for col in existing:
            try:
                client.delete_collection(col.name)
                logger.info("  ✗ Deleted: %s", col.name)
            except Exception as exc:
                logger.warning("  Failed to delete %s: %s", col.name, exc)

    # ── Create fresh collections ─────────────────────────────────────────
    for codex in _list_codexes(ATHENAEUM_ROOT):
        col_name = _partition_for(codex)
        try:
            client.create_collection(col_name)
            logger.info("  ✓ Created: %s", col_name)
        except Exception as exc:
            logger.warning("  Failed to create %s: %s", col_name, exc)

    # ── Get all files to embed ──────────────────────────────────────────
    all_files = _walk_files(ATHENAEUM_ROOT)
    logger.info("Files to embed: %d", len(all_files))

    def openrouter_embed(text: str) -> List[float]:
        """Embed text via OpenRouter API."""
        chunk_size = 2000  # characters, ~500 tokens
        text_str = text[:64000]  # Truncate to 64K chars max
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }

        if len(text_str) <= chunk_size:
            resp = requests.post(
                EMBED_API_URL,
                headers=headers,
                json={"model": EMBED_MODEL, "input": text_str},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]

        # Chunk and average for long texts
        chunks = [text_str[i:i+chunk_size] for i in range(0, len(text_str), chunk_size)]
        if len(chunks) > 20:
            chunks = chunks[:20]  # Cap at 20 chunks
        embeddings = []
        for chunk in chunks:
            resp = requests.post(
                EMBED_API_URL,
                headers=headers,
                json={"model": EMBED_MODEL, "input": chunk},
                timeout=60,
            )
            resp.raise_for_status()
            embeddings.append(resp.json()["data"][0]["embedding"])
        # Average
        dim = len(embeddings[0])
        avg = [sum(vals[i] for vals in embeddings) / len(embeddings) for i in range(dim)]
        return avg

    # ── Embed all files ──────────────────────────────────────────────────
    success = 0
    fail = 0
    for idx, (rel, full, codex) in enumerate(all_files, 1):
        try:
            path = Path(full)
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                logger.debug("Skipping empty: %s", rel)
                continue

            embedding = openrouter_embed(content)
            doc_id = str(path.resolve())
            col = client.get_collection(_partition_for(codex))
            col.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[{
                    "source": str(path),
                    "codex": codex,
                    "filename": path.name,
                }],
            )
            success += 1
        except Exception as exc:
            logger.warning("Failed: %s — %s", rel, exc)
            fail += 1

        if idx % 25 == 0 or idx == len(all_files):
            logger.info("  → %d/%d (%d ok, %d fail)", idx, len(all_files), success, fail)

    # ── Final summary ────────────────────────────────────────────────────
    total_after = 0
    for col in client.list_collections():
        try:
            total_after += col.count()
        except Exception:
            pass

    logger.info("═══════════════════════════════════════")
    logger.info("  Done! Embedded: %d, Failed: %d", success, fail)
    logger.info("  Total entries in ChromaDB: %d", total_after)
    logger.info("═══════════════════════════════════════")


if __name__ == "__main__":
    main()
