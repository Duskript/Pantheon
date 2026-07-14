#!/usr/bin/env python3
"""
inject-shared-context.py — Shared Context → Ichor Injection Script (v2)

Injects shared context files into Ichor's ichor_events table as digest_entry
events, making them queryable via ichor_retrieve by all Pantheon gods.

Companion to the agent-driven shared-context-injection cron job (f6ec8a7b7ca4).
Runs as a script fallback when the agent-driven job is unavailable.

Sources: DIGEST.md, CONTEXT_*.md, athenaeum-writes.md, decisions/, active/
Destination: ichor_events table with event_type='digest_entry'

Schema:
  event_type='digest_entry'
  subject='shared:{category}:{content_hash}'
  raw_text=file_content (truncated to 10K for large files)
  source='inject-shared-context.py'
  importance=50.0, trust=50.0, maturity='validated'
  god_name='thoth'

Cron schedule: every 15 minutes
Dedup: by subject key (SHA-256 content hash first 16 chars)
"""

import os, sqlite3, hashlib
from pathlib import Path
from datetime import datetime, timezone

SHARED_DIR = Path("/home/konan/pantheon/shared")
ICHOR_DB = Path("/home/konan/.hermes/ichor.db")
LOG_FILE = Path("/home/konan/pantheon/logs/inject-shared-context.log")


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except OSError:
        pass


def content_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def get_dedup_subjects(cursor):
    try:
        cursor.execute(
            "SELECT subject FROM ichor_events WHERE event_type = 'digest_entry'"
        )
        return {row[0] for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        return set()


def inject_file_content(cursor, category, content, existing_subjects,
                        god_name="thoth", session_id="cron-inject"):
    ch = content_hash(content)
    subject = f"shared:{category}:{ch}"
    if subject in existing_subjects:
        return False
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """INSERT INTO ichor_events 
               (session_id, event_type, subject, predicate, object,
                raw_text, created_at, god_name,
                importance, trust, maturity, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, "digest_entry", subject, category,
             f"Shared context {category}", content[:10000],
             now, god_name, 50.0, 50.0, "validated",
             "inject-shared-context.py"),
        )
        return True
    except sqlite3.OperationalError as e:
        log(f"  ERROR: {e}")
        return False


def main():
    log("=" * 60)
    log("Injecting shared context...")
    log(f"  SHARED: {SHARED_DIR}")
    log(f"  DB:     {ICHOR_DB}")

    if not ICHOR_DB.exists():
        log(f"  ERROR: Ichor DB not found at {ICHOR_DB}")
        return

    conn = sqlite3.connect(str(ICHOR_DB))
    cursor = conn.cursor()
    existing = get_dedup_subjects(cursor)
    injected = 0
    skipped = 0

    # 1. DIGEST.md
    f = SHARED_DIR / "DIGEST.md"
    if f.is_file():
        sz = f.stat().st_size
        log(f"  -> digest: DIGEST.md ({sz}b)")
        if inject_file_content(cursor, "digest", f.read_text(encoding="utf-8", errors="replace"), existing):
            log("  + shared:digest")
            injected += 1
        else:
            skipped += 1
    else:
        log("  -> digest: NOT FOUND")

    # 2. CONTEXT_*.md
    for ctx_file in sorted(SHARED_DIR.glob("CONTEXT_*.md")):
        sz = ctx_file.stat().st_size
        uid = ctx_file.stem.replace("CONTEXT_", "")
        log(f"  -> context: {ctx_file.name} ({sz}b)")
        if inject_file_content(cursor, f"context:{uid}", ctx_file.read_text(encoding="utf-8", errors="replace"), existing):
            log(f"  + shared:context:{uid}")
            injected += 1
        else:
            skipped += 1

    # 3. athenaeum-writes.md
    f = SHARED_DIR / "athenaeum-writes.md"
    if f.is_file():
        sz = f.stat().st_size
        log(f"  -> athenaeum: {f.name} ({sz}b)")
        if inject_file_content(cursor, "athenaeum", f.read_text(encoding="utf-8", errors="replace"), existing):
            log("  + shared:athenaeum")
            injected += 1
        else:
            skipped += 1
    else:
        log("  -> athenaeum-writes: NOT FOUND")

    # 4. decisions/
    dec_dir = SHARED_DIR / "decisions"
    total_dec = 0
    if dec_dir.is_dir():
        for entry in sorted(dec_dir.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                for md in sorted(entry.iterdir()):
                    if md.suffix == ".md" and md.name != "INDEX.md":
                        total_dec += 1
                        cat = f"decisions:{entry.name}:{md.stem}"
                        c = md.read_text(encoding="utf-8", errors="replace")
                        if inject_file_content(cursor, cat, c[:2000], existing):
                            log(f"  + shared:{cat}")
                            injected += 1
                        else:
                            skipped += 1
            elif entry.suffix == ".md" and entry.name != "INDEX.md":
                total_dec += 1
                cat = f"decisions:{entry.stem}"
                c = entry.read_text(encoding="utf-8", errors="replace")
                if inject_file_content(cursor, cat, c[:2000], existing):
                    log(f"  + shared:{cat}")
                    injected += 1
                else:
                    skipped += 1
        log(f"  -> decisions: {total_dec} file(s)")
    else:
        log("  -> decisions: NOT FOUND")

    # 5. active/
    act_dir = SHARED_DIR / "active"
    total_act = 0
    if act_dir.is_dir():
        for md in sorted(act_dir.iterdir()):
            if md.suffix == ".md":
                total_act += 1
                cat = f"active:{md.stem}"
                c = md.read_text(encoding="utf-8", errors="replace")
                if inject_file_content(cursor, cat, c[:2000], existing):
                    log(f"  + shared:{cat}")
                    injected += 1
                else:
                    skipped += 1
        log(f"  -> active: {total_act} file(s)")
    else:
        log("  -> active: NOT FOUND")

    conn.commit()
    conn.close()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    log(f"\nDone. {injected} injected, {skipped} skipped (already current). ({ts})")
    log("")


if __name__ == "__main__":
    main()
