#!/usr/bin/env python3
"""Dead-simple backfill: embed Athenaeum → ChromaDB via Ollama."""
import time
from pathlib import Path

def say(msg):
    print(f"{time.strftime('%H:%M:%S')} | {msg}", flush=True)

say("Starting backfill...")

import httpx
import chromadb

HOME = Path.home()
ATHENAEUM = HOME / "athenaeum"
CHROMA_DIR = HOME / ".hermes" / "pantheon" / "chroma"
MAX_CHARS = 4000

CHROMA_DIR.mkdir(parents=True, exist_ok=True)
client = chromadb.PersistentClient(path=str(CHROMA_DIR))

# Walk files
say("Walking filesystem...")
files = []
for codex_dir in sorted(ATHENAEUM.iterdir()):
    if not codex_dir.is_dir() or not codex_dir.name.startswith("Codex-"):
        continue
    for fp in codex_dir.rglob("*"):
        if not fp.is_file(): continue
        if fp.suffix.lower() not in {".md", ".txt", ".json", ".yaml", ".yml"}: continue
        parts = fp.relative_to(ATHENAEUM).parts
        if "archive" in parts or "distilled" in parts: continue
        if fp.name == "INDEX.md": continue
        files.append((str(fp.relative_to(ATHENAEUM)), str(fp), codex_dir.name))

say(f"Files to embed: {len(files)}")

success = fail = 0
t0 = time.time()

for idx, (rel, full, codex) in enumerate(files, 1):
    try:
        content = Path(full).read_text(encoding="utf-8")
        if not content.strip(): continue
        text = content[:MAX_CHARS]

        r = httpx.post(
            "http://localhost:11434/api/embeddings",
            json={"model": "nomic-embed-text", "prompt": text},
            timeout=30,
        )
        if r.status_code != 200:
            fail += 1
            if fail <= 3: say(f"FAIL {rel}: HTTP {r.status_code}")
            continue

        emb = r.json()["embedding"]
        col_name = "pantheon_" + codex.lower().replace("-", "_")
        try:
            col = client.get_collection(col_name)
        except Exception:
            col = client.create_collection(col_name)

        col.upsert(
            ids=[full],
            embeddings=[emb],
            metadatas=[{"source": full, "codex": codex, "filename": Path(full).name}],
        )
        success += 1

        if idx % 100 == 0:
            elapsed = time.time() - t0
            say(f"  {idx}/{len(files)} | {success} ok, {fail} fail | {idx/elapsed:.1f}/s")

    except Exception as e:
        fail += 1
        if fail <= 5: say(f"FAIL {rel}: {str(e)[:120]}")

elapsed = time.time() - t0
say(f"DONE: {success} embedded, {fail} failed in {elapsed:.1f}s")
