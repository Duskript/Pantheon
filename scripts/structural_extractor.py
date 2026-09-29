#!/usr/bin/env python3
"""Deterministic Ichor structural extractor.

Scans session transcripts and project directories for new entities
and relationships, deduplicating against already-stored Ichor memory.
Designed to run as a cron job (Thoth's subconscious tick).
"""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── constants ──────────────────────────────────────────────────────────────
# Use hardcoded path — in cron env $HOME is overridden to ~/.hermes/profiles/thoth/home
_REAL_HOME = Path("/home/konan")
ICHOR_DB = _REAL_HOME / ".hermes" / "profiles" / "thoth" / "ichor_memory.db"
MAX_FILE_SIZE = 200_000  # skip source files larger than this
KNOWN_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini", ".sh", ".css", ".html"}
IGNORE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build"}

# ── claim patterns (loose but deterministic) ────────────────────────────────
CLAIM_PATTERNS = [
    (re.compile(r"(?:uses?|use[sd]?|utilize[sd]?|leverag(?:e|ed|ing))\s+(\w+(?:\s+\w+){0,4})", re.IGNORECASE), "uses"),
    (re.compile(r"(?:is|are|was|were)\s+(?:a|an|the)\s+(\w+(?:\s+\w+){0,4})(?:\s+(?:for|of|that|which))", re.IGNORECASE), "is_a"),
    (re.compile(r"(?:depend[s]?\s+on|depend[s]?\s+upon|depends?\s+on|depends?\s+upon)\s+(\w+(?:\s+\w+){0,4})", re.IGNORECASE), "depends_on"),
    (re.compile(r"(?:built\s+(?:with|on|using)|writ(?:ten|e)\s+in|coded\s+in|developed\s+(?:with|in|using))\s+(\w+(?:\s+\w+){0,4})", re.IGNORECASE), "built_with"),
    (re.compile(r"(?:provides?|offers?|support[s]?|enable[s]?|power[s]?)\s+(\w+(?:\s+\w+){0,4})", re.IGNORECASE), "provides"),
    (re.compile(r"(\w+)\s+(?:is|are)\s+(\w+(?:\s+\w+){0,4})\s+(?:of|for|in)\s+the", re.IGNORECASE), "entity_attr"),
    (re.compile(r"(?:configure[sd]?\s+as|set\s+up\s+as|setup\s+as|act[s]?\s+as|serve[s]?\s+as)\s+(\w+(?:\s+\w+){0,4})", re.IGNORECASE), "acts_as"),
]

# ── database helpers ────────────────────────────────────────────────────────
def get_db():
    ICHOR_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ICHOR_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS structural_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_hash TEXT UNIQUE NOT NULL,
            source_type TEXT NOT NULL,
            source_path TEXT NOT NULL,
            claim_type TEXT NOT NULL,
            claim_text TEXT NOT NULL,
            confidence TEXT DEFAULT 'medium',
            extracted_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_claim_hash ON structural_claims(claim_hash)
    """)
    return conn

def claim_hash(source_path, claim_type, claim_text):
    raw = f"{source_path}|{claim_type}|{claim_text}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]

def dedup_existing(conn, candidates):
    """Filter out already-stored claims."""
    existing = set()
    for row in conn.execute("SELECT claim_hash FROM structural_claims").fetchall():
        existing.add(row[0])
    return [c for c in candidates if c["hash"] not in existing]

def store_batch(conn, claims):
    now = datetime.now(timezone.utc).isoformat()
    for c in claims:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO structural_claims (claim_hash, source_type, source_path, claim_type, claim_text, confidence, extracted_at) VALUES (?,?,?,?,?,?,?)",
                (c["hash"], c["source_type"], c["source_path"], c["claim_type"], c["claim_text"], c["confidence"], now)
            )
        except sqlite3.IntegrityError:
            pass
    conn.commit()


# ── session scanning ────────────────────────────────────────────────────────
def read_with_limit(fpath):
    try:
        text = fpath.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_FILE_SIZE:
            return text[:MAX_FILE_SIZE] + f"\n... [truncated at {MAX_FILE_SIZE} chars]"
        return text
    except Exception as e:
        print(f"[WARN] Failed to read {fpath}: {e}", file=sys.stderr)
        return ""

def extract_session_text(session_path):
    """Extract conversational text from a session file.
    Supports .md transcripts and .json request dumps (Hermes format).
    """
    spath = Path(session_path)
    if spath.suffix == ".json":
        try:
            data = json.loads(spath.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            print(f"[WARN] Failed to parse JSON session {spath}: {e}", file=sys.stderr)
            return None

        # Hermes request dump format: request.body.messages
        messages = None
        try:
            messages = data.get("request", {}).get("body", {}).get("messages", [])
        except AttributeError:
            pass

        if not messages:
            return None

        parts = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Multi-modal content arrays
                texts = []
                for c in content:
                    if isinstance(c, dict):
                        texts.append(c.get("text", ""))
                    elif isinstance(c, str):
                        texts.append(c)
                content = "\n".join(texts)
            if not isinstance(content, str):
                content = str(content)
            if len(content) > 5000:
                content = content[:5000] + "\n... [truncated]"
            parts.append(f"[{role}]: {content}")
        return "\n\n".join(parts)

    # .md or other - read raw text
    return read_with_limit(spath)

def scan_session_files(session_dir):
    """Yield (source_path, content_text) for all session files."""
    sd = Path(session_dir).resolve()
    if not sd.is_dir():
        print(f"[WARN] Session dir not found: {sd}", file=sys.stderr)
        return
    for fpath in sorted(sd.rglob("*")):
        if fpath.is_dir():
            continue
        if fpath.suffix not in {".json", ".md"}:
            continue
        if any(ign in fpath.parts for ign in IGNORE_DIRS):
            continue
        text = extract_session_text(str(fpath))
        if text:
            yield str(fpath), text


# ── project scanning ────────────────────────────────────────────────────────
def scan_project_files(project_dirs):
    for pd in project_dirs:
        pdir = Path(pd).resolve()
        if not pdir.is_dir():
            print(f"[WARN] Project dir not found: {pdir}", file=sys.stderr)
            continue
        for fpath in sorted(pdir.rglob("*")):
            if fpath.is_dir():
                continue
            if fpath.suffix not in KNOWN_EXTENSIONS:
                continue
            if any(ign in fpath.parts for ign in IGNORE_DIRS):
                continue
            try:
                if fpath.stat().st_size > MAX_FILE_SIZE:
                    continue
                yield str(fpath), fpath.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                print(f"[WARN] Failed to read {fpath}: {e}", file=sys.stderr)


# ── extraction ──────────────────────────────────────────────────────────────
def extract_claims(text, source_path, source_type):
    """Run regex patterns over text, yield claim dicts."""
    for pattern, claim_type in CLAIM_PATTERNS:
        for m in pattern.finditer(text):
            matched = m.group(0).strip()
            if len(matched) < 10 or len(matched) > 300:
                continue
            if not any(c.isalpha() for c in matched):
                continue
            ch = claim_hash(source_path, claim_type, matched)
            yield {
                "hash": ch,
                "source_type": source_type,
                "source_path": source_path,
                "claim_type": claim_type,
                "claim_text": matched,
                "confidence": "low" if len(matched) < 20 else "medium",
            }


# ── main ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Ichor structural extractor")
    parser.add_argument("--session-dir", default="/home/konan/.hermes/sessions", help="Session transcript directory")
    parser.add_argument("--project-dir", action="append", default=[], help="Project source directory (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="Print would-add claims without storing")
    args = parser.parse_args()

    conn = get_db() if not args.dry_run else None
    all_candidates = []
    proj_files = []
    project_candidate_count = 0

    # ── sessions ──
    print("Scanning sessions...")
    session_paths = list(scan_session_files(args.session_dir))
    print(f"  Found {len(session_paths)} session files")
    session_candidate_count = 0
    for spath, content in session_paths:
        if not content.strip():
            continue
        extracted = list(extract_claims(content, spath, "session"))
        all_candidates.extend(extracted)
        session_candidate_count += len(extracted)

    print(f"  Extracted {session_candidate_count} raw candidates from sessions")

    # ── projects ──
    if args.project_dir:
        print("Scanning project directories...")
        proj_files = list(scan_project_files(args.project_dir))
        print(f"  Found {len(proj_files)} project source files")
        project_candidate_count = 0
        for ppath, content in proj_files:
            if not content.strip():
                continue
            extracted = list(extract_claims(content, ppath, "project"))
            all_candidates.extend(extracted)
            project_candidate_count += len(extracted)
        print(f"  Extracted {project_candidate_count} raw candidates from projects")

    total_candidates = len(all_candidates)

    # ── dedup ──
    if conn:
        new_claims = dedup_existing(conn, all_candidates)
        total_new = len(new_claims)
        if new_claims:
            store_batch(conn, new_claims)
    else:
        new_claims = all_candidates
        total_new = len(new_claims)

    project_files_scanned = len(proj_files) if args.project_dir else 0
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sessions_scanned": len(session_paths),
        "session_candidates": session_candidate_count,
        "project_files_scanned": project_files_scanned,
        "project_candidates": project_candidate_count if args.project_dir else 0,
        "total_candidates": total_candidates,
        "new_claims_added": total_new,
        "dup_skipped": total_candidates - total_new,
        "db_path": str(ICHOR_DB),
        "project_dirs": args.project_dir,
    }

    print()
    print("=" * 60)
    print(json.dumps(summary, indent=2))
    print("=" * 60)

    if conn:
        conn.close()

    return summary


if __name__ == "__main__":
    main()
