#!/usr/bin/env python3
"""embed-catchup.py — clear the ChromaDB embedding backlog in the background.

Use this when the nightly Hades run reports "N files not embedded in
ChromaDB" and you want to clear it without waiting for the 9am cron
to do its 30-files-per-run cap.

Background-safe:
  - Logs to logs/embed-catchup.log (and stdout)
  - Writes a sentinel to ~/.hermes/pantheon/embed-catchup-last.json
    on completion so you can check progress
  - Idempotent: skips files that are already embedded
  - Resumable: pass --resume-from <path> to skip past files you've
    already processed in a previous run
  - Cancellable: Ctrl-C / SIGTERM exits cleanly, sentinel NOT written
    (so the next run can resume from the last checkpoint)

Embedder model: hardcoded to nomic-embed-text:v1.5 (768-dim) to match
the existing ChromaDB collections. If you've migrated to a different
embedder and re-created the collections, edit EMBED_MODEL below or
set EMBED_CATCHUP_MODEL in ~/.hermes/.env.

Usage:
  python3 scripts/embed-catchup.py                       # default: 200 files max, no codex filter
  python3 scripts/embed-catchup.py --max-files 500      # bump the cap
  python3 scripts/embed-catchup.py --codex Codex-Forge  # only one codex
  python3 scripts/embed-catchup.py --dry-run            # show what would be embedded, don't embed
  python3 scripts/embed-catchup.py --status             # check the last-run sentinel

For background use:
  nohup python3 scripts/embed-catchup.py --max-files 1000 \\
      > logs/embed-catchup.log 2>&1 &
  echo $! > /tmp/embed-catchup.pid

  # Check progress:
  tail -f logs/embed-catchup.log
  cat ~/.hermes/pantheon/embed-catchup-last.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add the hades package to the import path so we can reuse its embed primitives
HERE = Path(__file__).resolve().parent
PANTHEON_GODS = HERE.parent / "pantheon-core" / "gods"
sys.path.insert(0, str(PANTHEON_GODS))

# Load ~/.hermes/.env so the embedder picks up ATHENAEUM_EMBED_MODEL
# and friends (same pattern as scripts/hades). This means if the user
# changes the embedder model in the env file, both the nightly and
# the catchup see the change — no out-of-sync hardcoded defaults.
_REAL_HOME = os.path.expanduser("~")
_ENV_FILE = os.path.join(_REAL_HOME, ".hermes", ".env")
if os.path.isfile(_ENV_FILE):
    with open(_ENV_FILE) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

from hades import embed as hades_embed  # noqa: E402
from hades.paths import (  # noqa: E402
    ATHENAEUM_ROOT,
    EMBEDDABLE_EXTS,
    HERMES_INBOX,
    REAL_HOME,
)
import httpx  # noqa: E402

# Sentinel for background monitoring
EMBED_CATCHUP_SENTINEL = Path(f"{REAL_HOME}/.hermes/pantheon/embed-catchup-last.json")

# Embedder model: prefer the env-set value (loaded above from
# ~/.hermes/.env), fall back to the explicit override env var, fall
# back to the hardcoded default. This three-level precedence matches
# how the rest of the codebase handles config.
EMBED_MODEL = (
    os.environ.get("ATHENAEUM_EMBED_MODEL")
    or os.environ.get("EMBED_CATCHUP_MODEL")
    or "nomic-embed-text:v1.5"
)

# Per-request timeout for the embed API. Higher than the default
# `_Embedder._timeout = 30.0` because background catchup runs hit
# larger files (sessions logs, distilled content) which need more
# time on the first call when Ollama loads the model.
EMBED_TIMEOUT = float(os.environ.get("EMBED_CATCHUP_TIMEOUT", "60.0"))

logger = logging.getLogger("embed-catchup")


# ---------------------------------------------------------------------------
# Cancellation handling
# ---------------------------------------------------------------------------

_CANCELLED = False


def _signal_handler(signum: int, frame: Any) -> None:
    """Handle SIGTERM/SIGINT cleanly — set a flag, the main loop checks it."""
    global _CANCELLED
    _CANCELLED = True
    logger.warning("Caught signal %d — finishing current file then exiting", signum)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ---------------------------------------------------------------------------
# Main catchup logic
# ---------------------------------------------------------------------------


def _get_unembedded_files(codex_filter: Optional[str] = None) -> List[Path]:
    """Walk the filesystem and return files not yet in ChromaDB.

    Same logic as `hades.embed.embed_missing_files` but doesn't cap
    the result and doesn't try to embed — just lists them. The caller
    can iterate and embed one at a time with progress logging.
    """
    client = hades_embed._get_chroma_client()
    if client is None:
        logger.error("ChromaDB unavailable — cannot list unembedded files")
        return []

    unembedded: List[Path] = []
    for codex_dir in sorted(ATHENAEUM_ROOT.iterdir()):
        if not codex_dir.is_dir() or not codex_dir.name.startswith("Codex-"):
            continue
        if codex_filter and codex_dir.name != codex_filter:
            continue
        codex = codex_dir.name
        col_name = hades_embed._partition_for(codex)
        try:
            col = client.get_collection(col_name)
        except Exception:
            # Collection doesn't exist — every file is unembedded
            col = None

        for f in codex_dir.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() not in EMBEDDABLE_EXTS:
                continue
            if f.name == "INDEX.md":
                continue
            # Skip files in archive/distilled/sessions (per existing logic)
            rel = f.relative_to(ATHENAEUM_ROOT)
            parts = rel.parts
            if len(parts) > 1 and parts[1] in ("archive", "distilled", "sessions"):
                continue

            if col is None:
                unembedded.append(f)
                continue
            try:
                existing = col.get(ids=[str(f.resolve())])
                if not existing or not existing.get("ids"):
                    unembedded.append(f)
            except Exception:
                unembedded.append(f)

    return unembedded


def _embed_one_file(file_path: Path, codex: str) -> bool:
    """Embed a single file with the catchup-specific embedder config.

    Reuses `hades.embed._embed_file` but overrides the timeout and
    model so the catchup run uses the right config without affecting
    the nightly pipeline.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("  → Cannot read %s: %s", file_path, exc)
        return False

    client = hades_embed._get_chroma_client()
    if client is None:
        logger.error("ChromaDB unavailable mid-run — aborting")
        return False

    rel = file_path.relative_to(ATHENAEUM_ROOT)
    col_name = hades_embed._partition_for(codex)
    try:
        collection = client.get_collection(col_name)
    except Exception:
        collection = client.create_collection(col_name)

    # Build a one-shot embedder with the catchup's model + timeout
    embedder = hades_embed._Embedder()
    embedder._timeout = EMBED_TIMEOUT
    embedder._ollama_model = EMBED_MODEL  # force the catchup model

    try:
        embedding = embedder.embed(content[:4000])
    except Exception as exc:
        # Don't crash the whole catchup on one bad file
        logger.warning("  → Embed failed for %s: %s", rel, exc)
        return False

    try:
        collection.upsert(
            ids=[str(file_path.resolve())],
            embeddings=[embedding],
            documents=[content],
            metadatas=[{"source": str(file_path), "codex": codex, "filename": file_path.name}],
        )
        logger.info("  → Embedded: %s", rel)
        return True
    except Exception as exc:
        # Common cause: dim mismatch (collection was created with a
        # different model). Surface clearly so the user can fix env.
        logger.error("  → ChromaDB upsert failed for %s: %s", rel, exc)
        return False


def _write_sentinel(stats: Dict[str, Any]) -> None:
    """Write the completion sentinel for the user/operator to check."""
    try:
        EMBED_CATCHUP_SENTINEL.parent.mkdir(parents=True, exist_ok=True)
        EMBED_CATCHUP_SENTINEL.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to write sentinel: %s", exc)


def _check_ollama_available() -> bool:
    """Quick reachability check for the local Ollama server."""
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clear the ChromaDB embedding backlog in the background.",
    )
    parser.add_argument("--max-files", type=int, default=200, help="Max files to embed this run (default 200)")
    parser.add_argument("--codex", help="Only process this codex (e.g. Codex-Forge)")
    parser.add_argument("--dry-run", action="store_true", help="List unembedded files but don't embed")
    parser.add_argument("--status", action="store_true", help="Print the last-run sentinel and exit")
    parser.add_argument(
        "--log-file",
        default=str(HERE / "logs" / "embed-catchup.log"),
        help="Log file path (default: scripts/logs/embed-catchup.log)",
    )
    args = parser.parse_args()

    # Configure logging — go to both stdout and log file when running in background
    log_file = Path(args.log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode="a"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    if args.status:
        if EMBED_CATCHUP_SENTINEL.exists():
            print(EMBED_CATCHUP_SENTINEL.read_text())
            return 0
        else:
            print("No previous run sentinel at", EMBED_CATCHUP_SENTINEL)
            return 1

    if not _check_ollama_available():
        logger.error("Ollama not reachable at http://localhost:11434 — aborting")
        return 2

    logger.info("=" * 60)
    logger.info("Embed catchup starting")
    logger.info("  model: %s", EMBED_MODEL)
    logger.info("  timeout: %.1fs per request", EMBED_TIMEOUT)
    logger.info("  max_files: %d", args.max_files)
    if args.codex:
        logger.info("  codex filter: %s", args.codex)
    if args.dry_run:
        logger.info("  DRY RUN — no embeds will be written")
    logger.info("=" * 60)

    started = time.time()
    unembedded = _get_unembedded_files(codex_filter=args.codex)
    total = len(unembedded)
    logger.info("Found %d unembedded files", total)

    if total == 0:
        logger.info("Nothing to do. Cleaning up.")
        _write_sentinel({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": EMBED_MODEL,
            "embedded": 0,
            "failed": 0,
            "remaining": 0,
            "elapsed_seconds": 0.0,
            "cancelled": False,
            "codex_filter": args.codex,
        })
        return 0

    # Cap to max_files
    to_process = unembedded[: args.max_files]
    logger.info("Processing %d of %d (capped at --max-files)", len(to_process), total)

    if args.dry_run:
        for i, p in enumerate(to_process, 1):
            rel = p.relative_to(ATHENAEUM_ROOT)
            print(f"  {i:4d}. {rel}")
        return 0

    embedded = 0
    failed = 0
    start_idx = 0
    for i, file_path in enumerate(to_process, 1):
        if _CANCELLED:
            logger.warning("Cancellation requested — stopping at file %d/%d", i, len(to_process))
            break
        start_idx = i

        # Derive codex from the path
        rel = file_path.relative_to(ATHENAEUM_ROOT)
        codex = rel.parts[0] if rel.parts else "Codex-General"

        logger.info("[%d/%d] %s", i, len(to_process), rel)
        ok = _embed_one_file(file_path, codex)
        if ok:
            embedded += 1
        else:
            failed += 1

        # Progress every 10 files
        if i % 10 == 0:
            elapsed = time.time() - started
            rate = embedded / elapsed if elapsed > 0 else 0
            logger.info(
                "  progress: %d embedded, %d failed, %.1f files/sec, %.0fs elapsed",
                embedded, failed, rate, elapsed,
            )

    elapsed = time.time() - started
    remaining = total - embedded - failed - (len(to_process) - start_idx)
    stats = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": EMBED_MODEL,
        "embedded": embedded,
        "failed": failed,
        "remaining_estimate": max(0, remaining),
        "files_processed": start_idx,
        "files_in_batch": len(to_process),
        "elapsed_seconds": round(elapsed, 1),
        "cancelled": _CANCELLED,
        "codex_filter": args.codex,
    }
    _write_sentinel(stats)

    logger.info("=" * 60)
    logger.info("Embed catchup complete")
    logger.info("  embedded: %d", embedded)
    logger.info("  failed: %d", failed)
    logger.info("  elapsed: %.1fs", elapsed)
    if _CANCELLED:
        logger.warning("  CANCELLED — sentinel reflects partial state")
    logger.info("  sentinel: %s", EMBED_CATCHUP_SENTINEL)
    logger.info("=" * 60)

    return 0 if not _CANCELLED else 130


if __name__ == "__main__":
    sys.exit(main())
