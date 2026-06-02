#!/usr/bin/env python3
"""Fast minimal Athenaeum embedder — truncation mode, no chunking.

Bypasses buggy ichor_hybrid._Embedder. Uses single shared ChromaDB client,
no per-file is_available() checks, no re-imports. WARNING-level error logging.
Truncates each file to model's max input length — one API call per file.

Usage:
    ATHENAEUM_EMBED_MODEL=nomic-embed-text:v1.5 EMBED_WORKERS=4 \\
        python3 scripts/embed-fast.py
"""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("embed-fast")

# Config
HOME = os.path.expanduser("~")
ATH = Path(f"{HOME}/athenaeum")
CHROMA_DIR = f"{HOME}/.hermes/pantheon/chroma"
MODEL = os.environ.get("ATHENAEUM_EMBED_MODEL", "nomic-embed-text:v1.5")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/embeddings")
WORKERS = int(os.environ.get("EMBED_WORKERS", "4"))
EXTS = {".md", ".txt", ".json", ".yaml", ".yml"}
GOD_PREFIX = "Codex-God-"

# Model max input lengths (chars, including "search_document: " prefix)
MODEL_MAX_INPUT = {
    "all-minilm:33m": 480,
    "nomic-embed-text:v1.5": 8000,
}
MAX_INPUT = MODEL_MAX_INPUT.get(MODEL, 8000)

import httpx
import chromadb

_http = httpx.Client(timeout=120.0)

# Shared ChromaDB client + lock for thread safety
_chroma_client = None
_chroma_lock = __import__("threading").Lock()


def _get_chroma():
    global _chroma_client
    with _chroma_lock:
        if _chroma_client is None:
            _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
        return _chroma_client


def get_or_create_collection(codex: str):
    """Thread-safe get or create a ChromaDB collection."""
    slug = codex.lower().replace("-", "_")
    c = _get_chroma()
    with _chroma_lock:
        return c.get_or_create_collection(f"pantheon_{slug}")


def get_embedding(text: str):
    """Get embedding from Ollama. Truncates — no chunking, one call per file."""
    truncated = text[:MAX_INPUT]
    try:
        resp = _http.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": "search_document: " + truncated},
        )
        resp.raise_for_status()
        return resp.json()["embedding"]
    except Exception as exc:
        log.warning("Embedding failed (%d chars -> %d truncated): %s",
                     len(text), len(truncated), exc)
        return None


def find_missing():
    """Compare ChromaDB vs filesystem, return missing file list."""
    c = _get_chroma()
    collections = c.list_collections()
    embedded = set()

    for col in collections:
        try:
            records = col.get()
            if records and records.get("ids"):
                embedded.update(records["ids"])
        except Exception:
            log.warning("Could not read collection %s", col.name)

    codex_dirs = {}
    for d in sorted(ATH.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        cn = d.name
        codex_dirs[cn] = d

    total_on_disk = 0
    missing = []

    for cn, d in sorted(codex_dirs.items()):
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in EXTS:
                continue
            total_on_disk += 1
            src = str(p)
            if src not in embedded:
                missing.append((cn, p))

    return missing, total_on_disk, len(embedded)


def embed_one(codex_name: str, file_path: Path):
    """Embed a single file. Returns (filename, success)."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace").strip()
        if not content:
            return (file_path.name, True)

        embedding = get_embedding(content)
        if embedding is None:
            return (file_path.name, False)

        doc_id = str(file_path.resolve())
        col = get_or_create_collection(codex_name)
        col.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[{
                "codex": codex_name,
                "source": str(file_path),
                "filename": file_path.name,
            }],
        )
        return (file_path.name, True)
    except Exception as exc:
        log.warning("Failed %s: %s", file_path.name, exc)
        return (file_path.name, False)


def main():
    log.info("Scanning (model=%s, workers=%d, chroma=%s, max_input=%d)...",
             MODEL, WORKERS, CHROMA_DIR, MAX_INPUT)
    t0 = time.time()
    missing, total_on_disk, total_in_chroma = find_missing()
    scan_time = time.time() - t0

    log.info("ChromaDB: %d | Filesystem: %d | Missing: %d (scan %.1fs)",
             total_in_chroma, total_on_disk, len(missing), scan_time)

    if not missing:
        log.info("Gap closed! Nothing to do.")
        return

    by_codex = {}
    for cn, fp in missing:
        by_codex.setdefault(cn, []).append(fp)
    for cn, files in sorted(by_codex.items(), key=lambda x: -len(x[1])):
        sz = sum(os.path.getsize(f) for f in files)
        log.info("  %s: %d files (%dKB)", cn, len(files), sz // 1024)

    log.info("Embedding %d files (1 call each, truncating to %d chars)...",
             len(missing), MAX_INPUT)
    ok = fail = 0
    embed_start = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(embed_one, cn, fp): (cn, fp) for cn, fp in missing}
        done = 0
        total = len(futs)

        for fut in as_completed(futs):
            done += 1
            fname, success = fut.result()
            if success:
                ok += 1
            else:
                fail += 1
            if done % 25 == 0 or done == total:
                elapsed = time.time() - embed_start
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                log.info("  [%d/%d] %d ok, %d fail | %.1f/s | ETA %ds",
                         done, total, ok, fail, rate, eta)

    elapsed = time.time() - embed_start
    log.info("=" * 40)
    log.info("Done! %d ok, %d fail in %.1fs (%.1f/s)",
             ok, fail, elapsed, total / elapsed if elapsed > 0 else 0)


if __name__ == "__main__":
    main()
