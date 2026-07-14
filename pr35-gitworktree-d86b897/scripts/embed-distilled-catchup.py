#!/usr/bin/env python3
"""Embed distilled files into ChromaDB — fast, targeted, parallel.

Usage:
    python3 scripts/embed-distilled-catchup.py              # Embed distilled files
    python3 scripts/embed-distilled-catchup.py --dry-run     # Just report
"""

import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("embed-catchup")

R = os.path.expanduser("~konan")
ATH = Path(f"{R}/athenaeum")
CHR = f"{R}/.hermes/pantheon/chroma"
EXTS = {".md", ".txt", ".json", ".yaml", ".yml"}

# Shared resources (lazily initialized, thread-safe)
_embedder = None
_embedder_lock = Lock()


def _get_embedder():
    """Get or create the shared embedder (thread-safe)."""
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                sys.path.insert(0, f"{R}/pantheon/lib")
                from ichor_hybrid import _Embedder
                e = _Embedder()
                e.is_available()  # one-time health check
                _embedder = e
    return _embedder


def _get_collection(client, codex_name):
    """Get or create a ChromaDB collection for a codex."""
    cname = f"pantheon_codex_{codex_name.lower().replace('codex-', '').replace('-', '_')}"
    try:
        return client.get_collection(name=cname)
    except Exception:
        return client.create_collection(name=cname)


def embed_one(codex_name, file_path):
    """Embed a single file into ChromaDB. Returns True on success.

    Thread-safe: uses shared embedder + per-call ChromaDB client.
    """
    import chromadb

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace").strip()
        if not content:
            return True

        if len(content) > 3000:
            content = content[:3000]

        embedder = _get_embedder()
        vector = embedder.embed(content)
        if vector is None:
            return False

        client = chromadb.PersistentClient(path=CHR)
        collection = _get_collection(client, codex_name)
        doc_id = str(file_path.relative_to(ATH))
        collection.add(
            embeddings=[vector],
            documents=[content],
            ids=[doc_id],
            metadatas=[{
                "codex": codex_name,
                "source": str(file_path),
                "filename": file_path.name,
            }],
        )
        return True
    except Exception as exc:
        logger.debug("Fail %s: %s", file_path.name, exc)
        return False


def find_missing(client):
    """Find all distilled files not yet in ChromaDB."""
    codexes = sorted(
        d.name for d in ATH.iterdir()
        if d.is_dir() and d.name.startswith("Codex-") and not d.name.startswith("Codex-God-")
    )

    distilled_files = []
    for cn in codexes:
        d = ATH / cn / "distilled"
        if not d.exists():
            continue
        for ext in EXTS:
            for p in d.rglob(f"*{ext}"):
                if p.is_file():
                    distilled_files.append((cn, p))

    # Check each via ID lookup
    missing = []
    for cn, fp in distilled_files:
        doc_id = str(fp.relative_to(ATH))
        cname = f"pantheon_codex_{cn.lower().replace('codex-', '').replace('-', '_')}"
        try:
            collection = client.get_collection(name=cname)
            existing = collection.get(ids=[doc_id])
            if existing and existing.get("ids") and existing["ids"][0] == doc_id:
                continue
        except Exception:
            pass
        missing.append((cn, fp))

    return missing


def main():
    import argparse
    import chromadb

    parser = argparse.ArgumentParser(description="Targeted distilled embedding catch-up")
    parser.add_argument("--dry-run", action="store_true", help="Just report what's missing")
    parser.add_argument("--workers", type=int, default=6, help="Parallel workers")
    args = parser.parse_args()

    logger.info("Scanning for missing distilled files...")
    client = chromadb.PersistentClient(path=CHR)
    missing = find_missing(client)

    if not missing:
        logger.info("No missing distilled files!")
        return

    by_codex = {}
    for cn, fp in missing:
        by_codex.setdefault(cn, []).append(fp)

    logger.info("Distilled files missing from ChromaDB: %d", len(missing))
    for cn, files in sorted(by_codex.items(), key=lambda x: -len(x[1])):
        total_kb = sum(os.path.getsize(f) for f in files) // 1024
        logger.info("  %s: %d files (%dKB)", cn, len(files), total_kb)

    if args.dry_run:
        return

    logger.info("Embedding with %d workers...", args.workers)
    ok = fail = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(embed_one, cn, fp): (cn, fp) for cn, fp in missing}
        done = 0
        for f in as_completed(futures):
            done += 1
            try:
                if f.result():
                    ok += 1
                else:
                    fail += 1
            except Exception:
                fail += 1

            if done % 50 == 0 or done == len(missing):
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(missing) - done) / rate if rate > 0 else 0
                logger.info("  [%d/%d] %d ok, %d fail | %.1f/s | ETA %.0fs",
                            done, len(missing), ok, fail, rate, eta)

    elapsed = time.time() - start
    logger.info("Done! %d embedded, %d failed in %.1fs (%.1f files/s)",
                ok, fail, elapsed, len(missing) / elapsed if elapsed > 0 else 0)


if __name__ == "__main__":
    main()
