#!/usr/bin/env python3
"""One-shot Athenaeum → cold_events ingest.

Walks ~/athenaeum/Codex-*/ recursively, chunks each .md/.txt/.json/.yaml/.yml
file into ~3000-char segments, and inserts each segment as a row in
ichor.db's cold_events table. Idempotent: dedups on (god_name, name)
where name = relative path. Re-running on a partially-ingested tree
just fills the gaps.

Each row:
  event_type='reference'
  category='reference'
  god_name='athenaeum'
  name=<relative_path>          # e.g. "Codex-Olympus/journal/foo.md"
  raw_text=<chunk>              # up to 3000 chars
  confidence=0.7
  importance=30
  trust=70
  session_id='athenaeum:<sha256(path)[:12]>'
  speaker='athenaeum'
  direction='inbound'
  peer_god=''
  created_at=<now>
  brief=NULL, outline=NULL
  goal_id=NULL

Idempotency: before insert, SELECT MAX(id) from cold_events where
god_name='athenaeum' AND name=?. If a row already exists for that
path, skip the file (chunking is deterministic so the same chunks
will be there). To force a re-ingest, pass --force.

Usage:
  /home/konan/.hermes/hermes-agent/venv/bin/python3 \\
      /home/konan/pantheon/scripts/ingest_athenaeum_to_cold_events.py
  /home/konan/.hermes/hermes-agent/venv/bin/python3 \\
      /home/konan/pantheon/scripts/ingest_athenaeum_to_cold_events.py --force
  /home/konan/.hermes/hermes-agent/venv/bin/python3 \\
      /home/konan/pantheon/scripts/ingest_athenaeum_to_cold_events.py --status
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Paths
_REAL_HOME = Path("/home/konan")
ATHENAEUM_ROOT = _REAL_HOME / "athenaeum"
ICHOR_DB = _REAL_HOME / ".hermes" / "ichor.db"
EMBEDDABLE_EXTS = {".md", ".txt", ".json", ".yaml", ".yml"}
CHUNK_SIZE = 3000  # chars; matches L2 prompt builder's per-turn cap
SKIP_DIRS = {".chromadb", "node_modules", ".git", "__pycache__", ".ruff_cache"}


def _say(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} | {msg}", flush=True)


def _path_hash(rel_path: str) -> str:
    return hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:12]


def _chunk(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Split text into ~size-char chunks on line boundaries where possible."""
    if len(text) <= size:
        return [text]
    chunks = []
    i = 0
    while i < len(text):
        end = i + size
        if end >= len(text):
            chunks.append(text[i:])
            break
        # Try to break on a newline within the last 200 chars
        nl = text.rfind("\n", i + size - 200, end)
        if nl > i:
            chunks.append(text[i:nl])
            i = nl + 1
        else:
            chunks.append(text[i:end])
            i = end
    return chunks


def _walk_athenaeum() -> list[Path]:
    """Return all embeddable files under Codex-* directories, sorted."""
    files = []
    for codex_dir in sorted(ATHENAEUM_ROOT.iterdir()):
        if not codex_dir.is_dir() or not codex_dir.name.startswith("Codex-"):
            continue
        for fp in codex_dir.rglob("*"):
            if not fp.is_file():
                continue
            if fp.suffix.lower() not in EMBEDDABLE_EXTS:
                continue
            if any(part in SKIP_DIRS for part in fp.parts):
                continue
            files.append(fp)
    return files


def _existing_paths(conn: sqlite3.Connection) -> set[str]:
    """Return set of relative paths already in cold_events from athenaeum."""
    return {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT name FROM cold_events "
            "WHERE god_name = 'athenaeum' AND name IS NOT NULL"
        ).fetchall()
    }


def _insert_chunk(
    conn: sqlite3.Connection,
    rel_path: str,
    chunk_idx: int,
    total_chunks: int,
    text: str,
) -> None:
    """Insert one chunk as a cold_events row."""
    session_id = f"athenaeum:{_path_hash(rel_path)}"
    # Distinguish chunks by appending :N to the name so uniqueness is preserved
    # but the original name is recoverable by stripping the suffix.
    chunked_name = f"{rel_path}#{chunk_idx:03d}/{total_chunks:03d}" if total_chunks > 1 else rel_path
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO cold_events (
            event_type, category, name, confidence, importance, trust,
            raw_text, speaker, session_id, god_name, direction, peer_god,
            created_at, brief, outline, goal_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
        """,
        (
            "reference",
            "reference",
            chunked_name,
            0.7,
            30.0,
            70.0,
            text,
            "athenaeum",
            session_id,
            "athenaeum",
            "inbound",
            "",
            now,
        ),
    )


def cmd_status() -> int:
    """Show ingest state without making changes."""
    if not ICHOR_DB.exists():
        _say(f"ichor.db not found at {ICHOR_DB}")
        return 1
    con = sqlite3.connect(ICHOR_DB)
    try:
        # Total athenaeum files on disk
        all_files = _walk_athenaeum()
        total = len(all_files)

        # Already-ingested
        existing = _existing_paths(con)
        chunked = con.execute(
            "SELECT COUNT(*) FROM cold_events WHERE god_name = 'athenaeum'"
        ).fetchone()[0]

        # Distinct codexes
        codexes = sorted({f.parts[len(ATHENAEUM_ROOT.parts)] for f in all_files if len(f.parts) > len(ATHENAEUM_ROOT.parts)})

        print(f"\n📚 Athenaeum ingest status")
        print(f"{'=' * 50}")
        print(f"   Files on disk:       {total}")
        print(f"   Files ingested:      {len(existing)} (paths)")
        print(f"   Total chunks in DB:  {chunked}")
        print(f"   Codexes:             {len(codexes)}")
        for c in codexes:
            n_codex = sum(1 for f in all_files if len(f.parts) > len(ATHENAEUM_ROOT.parts) and f.parts[len(ATHENAEUM_ROOT.parts)] == c)
            n_ingested = sum(1 for p in existing if p.startswith(c + "/"))
            print(f"      {c}: {n_ingested}/{n_codex}")
    finally:
        con.close()
    return 0


def cmd_ingest(force: bool = False, batch_commit: int = 200) -> int:
    """Walk the Athenaeum, chunk, insert."""
    if not ATHENAEUM_ROOT.is_dir():
        _say(f"Athenaeum root not found at {ATHENAEUM_ROOT}")
        return 1
    if not ICHOR_DB.exists():
        _say(f"ichor.db not found at {ICHOR_DB}")
        return 1

    _say(f"walking {ATHENAEUM_ROOT} ...")
    all_files = _walk_athenaeum()
    _say(f"found {len(all_files)} embeddable files")

    con = sqlite3.connect(ICHOR_DB)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    try:
        existing = set() if force else _existing_paths(con)
        _say(f"{len(existing)} paths already in cold_events (use --force to re-ingest)")

        to_process = [f for f in all_files if str(f.relative_to(ATHENAEUM_ROOT)) not in existing]
        _say(f"will process {len(to_process)} new files")

        if not to_process:
            _say("nothing to do")
            return 0

        t0 = time.time()
        total_chunks = 0
        bytes_read = 0
        errors = []

        for i, fp in enumerate(to_process, 1):
            rel = str(fp.relative_to(ATHENAEUM_ROOT))
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
                bytes_read += len(text)
                chunks = _chunk(text)
                for ci, chunk in enumerate(chunks, 1):
                    _insert_chunk(con, rel, ci, len(chunks), chunk)
                    total_chunks += 1

                if i % batch_commit == 0:
                    con.commit()
                    elapsed = time.time() - t0
                    rate = i / elapsed if elapsed > 0 else 0
                    _say(f"  progress: {i}/{len(to_process)} files, {total_chunks} chunks, {bytes_read/1024/1024:.1f} MB, {rate:.1f} files/s")

            except Exception as exc:
                errors.append((rel, str(exc)))
                _say(f"  ERROR reading {rel}: {exc}")

        con.commit()
        elapsed = time.time() - t0
        _say(f"")
        _say(f"✅ ingest complete in {elapsed:.1f}s")
        _say(f"   files processed: {len(to_process)}")
        _say(f"   chunks inserted: {total_chunks}")
        _say(f"   bytes read: {bytes_read/1024/1024:.1f} MB")
        _say(f"   errors: {len(errors)}")
        for rel, err in errors[:10]:
            _say(f"     {rel}: {err[:100]}")

        # Updated totals
        new_total = con.execute(
            "SELECT COUNT(*) FROM cold_events WHERE god_name = 'athenaeum'"
        ).fetchone()[0]
        _say(f"   cold_events where god_name='athenaeum': {new_total}")

    finally:
        con.close()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Athenaeum → cold_events ingest (one-shot, idempotent)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="re-ingest all files even if name already in cold_events",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="show ingest state without making changes",
    )
    args = parser.parse_args()
    if args.status:
        return cmd_status()
    return cmd_ingest(force=args.force)


if __name__ == "__main__":
    sys.exit(main())
