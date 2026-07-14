#!/usr/bin/env python3
"""Batch embedding catch-up — embeds distilled files in batches.

10-20x faster than single-file embedding because Ollama processes
batches in one forward pass.

Usage:
    python3 scripts/batch-embed-catchup.py               # Embed missing distilled
    python3 scripts/batch-embed-catchup.py --dry-run     # Just report
"""

import logging
import os
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("batch-embed")

R = os.path.expanduser("~konan")
ATH = Path(f"{R}/athenaeum")
CHR = f"{R}/.hermes/pantheon/chroma"
OLLAMA_URL = "http://localhost:11434/api/embed"
MODEL = "nomic-embed-text"
EXTS = {".md", ".txt", ".json", ".yaml", ".yml"}
BATCH_SIZE = 10  # Files per batch


def find_missing(client):
    """Find all distilled files not yet in ChromaDB."""
    codexes = sorted(
        d.name for d in ATH.iterdir()
        if d.is_dir() and d.name.startswith("Codex-") and not d.name.startswith("Codex-God-")
    )

    distilled = []
    for cn in codexes:
        d = ATH / cn / "distilled"
        if not d.exists():
            continue
        for ext in EXTS:
            for p in d.rglob(f"*{ext}"):
                if p.is_file():
                    distilled.append((cn, p))

    missing = []
    for cn, fp in distilled:
        doc_id = str(fp.relative_to(ATH))
        cname = f"pantheon_codex_{cn.lower().replace('codex-', '').replace('-', '_')}"
        try:
            col = client.get_collection(name=cname)
            existing = col.get(ids=[doc_id])
            if existing and existing.get("ids") and existing["ids"][0] == doc_id:
                continue
        except Exception:
            pass
        missing.append((cn, fp))

    return missing


def main():
    import argparse
    import chromadb
    import httpx

    parser = argparse.ArgumentParser(description="Batch embedding catch-up")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
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
    logger.info("Missing: %d files", len(missing))
    for cn, files in sorted(by_codex.items(), key=lambda x: -len(x[1])):
        logger.info("  %s: %d files", cn, len(files))

    if args.dry_run:
        return

    # Batch embed
    ok = fail = 0
    start = time.time()
    batch_num = 0
    total_batches = (len(missing) + args.batch_size - 1) // args.batch_size

    for i in range(0, len(missing), args.batch_size):
        batch = missing[i:i + args.batch_size]
        batch_num += 1
        batch_start = time.time()

        # Prepare batch data
        texts = []
        batch_meta = []
        for cn, fp in batch:
            try:
                content = fp.read_text(encoding="utf-8", errors="replace").strip()
                if not content:
                    ok += 1
                    continue
                if len(content) > 3000:
                    content = content[:3000]
                texts.append(content)
                batch_meta.append((cn, fp))
            except Exception:
                fail += 1

        if not texts:
            continue

        # Batch embed via Ollama
        try:
            resp = httpx.post(
                OLLAMA_URL,
                json={"model": MODEL, "input": texts},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("embeddings", [])
        except Exception as exc:
            logger.warning("Batch %d/%d failed: %s", batch_num, total_batches, exc)
            fail += len(texts)
            ok += len(batch) - len(texts)
            continue

        # Store results
        for j, (cn, fp) in enumerate(batch_meta):
            if j >= len(embeddings):
                fail += 1
                continue
            vec = embeddings[j]
            if not vec:
                fail += 1
                continue
            try:
                cname = f"pantheon_codex_{cn.lower().replace('codex-', '').replace('-', '_')}"
                try:
                    col = client.get_collection(name=cname)
                except Exception:
                    col = client.create_collection(name=cname)
                doc_id = str(fp.relative_to(ATH))
                col.add(
                    embeddings=[vec],
                    documents=[texts[j]],
                    ids=[doc_id],
                    metadatas=[{
                        "codex": cn,
                        "source": str(fp),
                        "filename": fp.name,
                    }],
                )
                ok += 1
            except Exception as exc:
                logger.debug("Store fail: %s", exc)
                fail += 1

        elapsed = time.time() - batch_start
        total_elapsed = time.time() - start
        rate = ok / total_elapsed if total_elapsed > 0 else 0
        remaining = len(missing) - (i + len(batch))
        eta = remaining / rate if rate > 0 else 0
        logger.info("  Batch %d/%d: %d files in %.1fs | %d ok, %d fail | %.1f/s | ETA %.0fs",
                    batch_num, total_batches, len(batch), elapsed,
                    ok, fail, rate, eta)

    elapsed = time.time() - start
    logger.info("Done! %d embedded, %d failed in %.1fs", ok, fail, elapsed)
    logger.info("Average: %.1f files/s", (ok + fail) / elapsed if elapsed > 0 else 0)


if __name__ == "__main__":
    main()
