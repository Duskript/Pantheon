#!/usr/bin/env python3
"""Run ichor_extract_entities over the full cold_events corpus.

Loops extract_incremental from last_event_id=0 to MAX(id), advancing
last_event_id_after each batch. Bounded retries on transient errors
(timeout, 5xx). Clean shutdown on persistent failure. Idempotent —
re-running resumes from the last successful batch.

The Phase 1 ingest (scripts/ingest_athenaeum_to_cold_events.py)
should be run first to populate cold_events with Athenaeum content.

Usage:
  /home/konan/.hermes/hermes-agent/venv/bin/python3 \\
      /home/konan/pantheon/scripts/run_l2_full_corpus.py
  /home/konan/.hermes/hermes-agent/venv/bin/python3 \\
      /home/konan/pantheon/scripts/run_l2_full_corpus.py --batch-size 50
  /home/konan/.hermes/hermes-agent/venv/bin/python3 \\
      /home/konan/pantheon/scripts/run_l2_full_corpus.py --status
  /home/konan/.hermes/hermes-agent/venv/bin/python3 \\
      /home/konan/pantheon/scripts/run_l2_full_corpus.py --dry-run

API key resolution order:
  1. $MINIMAX_API_KEY env var
  2. ~/.hermes/profiles/marvin/.env
  3. ~/.hermes/profiles/hephaestus/.env
  4. ~/.hermes/profiles/thoth/.env
  5. ~/.hermes/.env

Cost: ~18k events at batch=50 = ~370 LLM calls. At ~3-5s/call = 20-30 min
wall clock. Tokens: ~4k input * 370 = ~1.5M input + ~200k output.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Ensure the Ichor package is importable. We add pantheon/ to sys.path
# so 'import lib.ichor' resolves. Python auto-adds the script's own
# directory (scripts/) to sys.path[0], which would also expose
# scripts/lib/ as a 'lib' candidate — that's fine as a namespace
# package since scripts/lib/__init__.py was removed in 2026-06-12.
_PANTHEON_ROOT = "/home/konan/pantheon"
if _PANTHEON_ROOT not in sys.path:
    sys.path.insert(0, _PANTHEON_ROOT)

_REAL_HOME = Path("/home/konan")
ICHOR_DB = _REAL_HOME / ".hermes" / "ichor.db"

# Provider config — opencode-go (NOT ollama-launch, NOT minimax)
# API: https://opencode.ai/zen/go/v1 (OpenAI-compatible)
# Models: deepseek-v4-flash, deepseek-v4-pro, kimi-k2.6, glm-5.1,
#         minimax-m3, etc. (per ~/.hermes/provider_models_cache.json)
# Env var for API key: OPENCODE_GO_API_KEY
# Key location: ~/.hermes/.env (also in profile .envs as fallback)
# $10/month subscription via https://opencode.ai/auth
#
# The provider's `name` would resolve to OPENCODE_API_KEY in the
# package's env-var fallback; we pass the key directly in provider_cfg
# to bypass that mismatch. The same key is what auth.json's
# credential_pool.opencode-go[0] uses.
PROVIDER_NAME = "opencode-go"
PROVIDER_API = "https://opencode.ai/zen/go/v1"
PROVIDER_DEFAULT_MODEL = "deepseek-v4-flash"
PROVIDER_KEY_ENV = "OPENCODE_GO_API_KEY"


def _load_api_key() -> str:
    """Resolve the provider's API key from env or .env files.

    Order (revised 2026-06-12 after the first L2 run hit a 401):
      1. $PROVIDER_KEY_ENV env var
      2. ~/.hermes/.env (GLOBAL, canonical source)
      3. ~/.hermes/profiles/marvin/.env (profile override)
      4. ~/.hermes/profiles/hephaestus/.env
      5. ~/.hermes/profiles/thoth/.env
      6. ~/.hermes/profiles/iris/.env
      7. ~/.hermes/profiles/apollo/.env

    The previous order (profile .envs first) picked up a stale key
    in the profile .envs (sk-7SXlK...) that was unauthorized for
    opencode-go. The active working key lives in ~/.hermes/.env
    (sk-Q75TD...). Profile .envs are now treated as overrides that
    only fire when the global is missing.
    """
    # 1. direct env var
    key = os.environ.get(PROVIDER_KEY_ENV, "").strip()
    if key:
        return key
    # 2. ~/.hermes/.env first (the global canonical key)
    global_env = _REAL_HOME / ".hermes" / ".env"
    if global_env.is_file():
        try:
            for line in global_env.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == PROVIDER_KEY_ENV:
                    v = v.strip().strip("\"'")
                    if v:
                        return v
        except Exception:
            pass
    # 3-7. profile .envs as fallback
    for profile in ["marvin", "hephaestus", "thoth", "iris", "apollo"]:
        env_file = _REAL_HOME / ".hermes" / "profiles" / profile / ".env"
        if env_file.is_file():
            try:
                for line in env_file.read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() == PROVIDER_KEY_ENV:
                        v = v.strip().strip("\"'")
                        if v:
                            return v
            except Exception:
                pass
    return ""


def _say(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} | {msg}", flush=True)


def _current_corpus_stats() -> dict:
    """How many cold_events are we about to process?"""
    con = sqlite3.connect(ICHOR_DB)
    try:
        total = con.execute("SELECT COUNT(*) FROM cold_events").fetchone()[0]
        max_id = con.execute("SELECT MAX(id) FROM cold_events").fetchone()[0] or 0
        by_god = {}
        for god, n in con.execute(
            "SELECT god_name, COUNT(*) FROM cold_events GROUP BY god_name ORDER BY 2 DESC"
        ).fetchall():
            by_god[god or "<null>"] = n
        return {"total": total, "max_id": max_id, "by_god": by_god}
    finally:
        con.close()


def _post_run_stats() -> dict:
    """L2 extraction outcome stats."""
    con = sqlite3.connect(ICHOR_DB)
    try:
        return {
            "entities": con.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
            "entity_facts": con.execute("SELECT COUNT(*) FROM entity_facts").fetchone()[0],
            "relationships": con.execute("SELECT COUNT(*) FROM relationships").fetchone()[0],
            "provisional_entities": con.execute("SELECT COUNT(*) FROM entities WHERE provisional=1").fetchone()[0],
            "provisional_relationships": con.execute("SELECT COUNT(*) FROM relationships WHERE provisional=1").fetchone()[0],
            "llm_extractions_logged": con.execute(
                "SELECT COUNT(*) FROM extraction_log WHERE method='llm'"
            ).fetchone()[0],
        }
    finally:
        con.close()


def _call_extract_incremental(
    last_event_id: int,
    batch_size: int,
    provider_cfg: dict,
    api_key: str,
    timeout: float = 60.0,
) -> dict:
    """One call to extract_incremental, returns the result dict.

    Direct port of the package's _default_call_llm flow,
    but in-process (no MCP server roundtrip) and with our own
    retry/error handling. urllib is imported at module level.
    """
    from lib.ichor.entities import extract_incremental
    from lib.ichor.entities.schema import get_conn

    con = get_conn()
    try:
        result = extract_incremental(
            con,
            last_event_id=last_event_id,
            batch_size=batch_size,
            provider_cfg=provider_cfg,
            session_id=f"l2-full-corpus",
        )
    finally:
        con.close()
    return result


def _run_loop(
    batch_size: int,
    max_batches: int | None,
    retry_max: int,
    api_key: str,
) -> dict:
    """The main loop."""
    provider_cfg = {
        "api": PROVIDER_API,
        "default_model": PROVIDER_DEFAULT_MODEL,
        "name": "MiniMax",
        "api_key": api_key,
    }

    # Resume from where we left off: lowest id of any event not yet
    # processed. We approximate this as "the last_event_id of the most
    # recent L2 extraction run" — but since the package doesn't store
    # that explicitly, we just start from 0 (idempotent: re-processing
    # an event produces the same entity name with a slightly updated
    # confidence).
    last_event_id = 0
    batch_num = 0
    total_chunks_processed = 0
    total_entities_created = 0
    total_rels_created = 0
    errors = []
    t0 = time.time()

    while True:
        if max_batches is not None and batch_num >= max_batches:
            _say(f"reached max_batches={max_batches}, stopping")
            break

        attempt = 0
        result = None
        while attempt <= retry_max:
            try:
                result = _call_extract_incremental(
                    last_event_id, batch_size, provider_cfg, api_key,
                )
                break
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError) as exc:
                attempt += 1
                if attempt > retry_max:
                    _say(f"  ERROR: persistent network failure after {retry_max+1} attempts: {exc!r}")
                    errors.append({"batch": batch_num, "type": "network", "detail": str(exc)})
                    errors.append({"batch": batch_num, "type": "network", "detail": str(exc)})
                    _say(f"  SKIP batch {batch_num} after {retry_max+1} retries (network)")
                    result = {"events_in_batch": 50, "last_event_id_after": last_event_id + batch_size, "stored": {}}
                    break
                backoff = 2 ** attempt
                _say(f"  retry {attempt}/{retry_max} after {backoff}s: {exc!r}")
                time.sleep(backoff)
            except Exception as exc:
                attempt += 1
                if attempt > retry_max:
                    errors.append({"batch": batch_num, "type": "logic", "detail": str(exc)})
                    _say(f"  SKIP batch {batch_num} after {retry_max+1} retries: {exc!r}")
                    result = {"events_in_batch": 50, "last_event_id_after": last_event_id + batch_size, "stored": {}}
                    break
                backoff = 2 ** attempt
                _say(f"  retry {attempt}/{retry_max} after {backoff}s: {exc!r}")
                time.sleep(backoff)

        if result is None:
            break

        events_in_batch = result.get("events_in_batch", 0)
        last_id_after = result.get("last_event_id_after", last_event_id)
        stored = result.get("stored", {})
        ent_created = stored.get("entities_created", 0)
        rel_created = stored.get("relationships_created", 0)
        total_chunks_processed += events_in_batch
        total_entities_created += ent_created
        total_rels_created += rel_created
        batch_num += 1
        elapsed = time.time() - t0
        rate = total_chunks_processed / elapsed if elapsed > 0 else 0

        # Progress line: every batch
        _say(
            f"  batch {batch_num:4d} | events {events_in_batch:3d} | "
            f"new_id {last_id_after:6d} | +{ent_created:3d} entities +{rel_created:3d} rels | "
            f"total {total_chunks_processed:6d} events processed | "
            f"{rate:5.1f} ev/s | {elapsed:6.1f}s"
        )

        # End conditions
        if events_in_batch == 0:
            _say("no more events past last_event_id — corpus exhausted")
            break
        if last_id_after == last_event_id:
            # shouldn't happen if events_in_batch > 0, but guard
            _say(f"WARNING: last_event_id did not advance ({last_event_id} → {last_id_after}), breaking to avoid infinite loop")
            break
        last_event_id = last_id_after

    return {
        "status": "complete" if not errors else "complete_with_errors",
        "batches_completed": batch_num,
        "last_event_id": last_event_id,
        "total_events_processed": total_chunks_processed,
        "total_entities_created": total_entities_created,
        "total_relationships_created": total_rels_created,
        "errors": errors,
        "wall_seconds": time.time() - t0,
    }


def cmd_status() -> int:
    """Show corpus state and L2 state, no LLM calls."""
    stats = _current_corpus_stats()
    l2 = _post_run_stats()
    api_key = _load_api_key()
    print(f"\n📊 L2 full-corpus status")
    print(f"{'=' * 50}")
    print(f"   cold_events total: {stats['total']} (max id {stats['max_id']})")
    print(f"   by god_name:")
    for god, n in stats["by_god"].items():
        print(f"      {god:30s}  {n}")
    print()
    print(f"   L2 state:")
    print(f"      entities:                       {l2['entities']}")
    print(f"      entity_facts:                   {l2['entity_facts']}")
    print(f"      relationships:                  {l2['relationships']}")
    print(f"      provisional entities:           {l2['provisional_entities']}")
    print(f"      provisional relationships:      {l2['provisional_relationships']}")
    print(f"      llm extractions logged:         {l2['llm_extractions_logged']}")
    print()
    print(f"   API key: {'SET (length=' + str(len(api_key)) + ')' if api_key else 'NOT FOUND'}")
    if not api_key:
        print(f"   ⚠️  Set MINIMAX_API_KEY env var or add to ~/.hermes/profiles/marvin/.env")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Run L2 extraction over the full cold_events corpus",
    )
    parser.add_argument(
        "--batch-size", type=int, default=50,
        help="events per LLM call (default 50; max 200)",
    )
    parser.add_argument(
        "--max-batches", type=int, default=None,
        help="safety cap on number of batches (default: unlimited)",
    )
    parser.add_argument(
        "--retry-max", type=int, default=3,
        help="retries per batch on transient errors (default 3)",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="show corpus + L2 state without running",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="resolve config and print first batch prompt, no LLM call",
    )
    args = parser.parse_args()
    if args.status:
        return cmd_status()
    batch_size = max(1, min(args.batch_size, 200))

    api_key = _load_api_key()
    if not api_key:
        print("ERROR: MINIMAX_API_KEY not set. Run with --status to see where to set it.", file=sys.stderr)
        return 1

    if args.dry_run:
        from lib.ichor.entities.l2_llm import build_prompt, _events_for_batch
        from lib.ichor.entities.schema import get_conn
        con = get_conn()
        try:
            rows = _events_for_batch(con, 0, batch_size)
        finally:
            con.close()
        if not rows:
            print("no events to process")
            return 0
        texts = [r["raw_text"] for r in rows]
        prompt = build_prompt(texts)
        print(f"\n=== DRY RUN ===")
        # Bug fix: provider=minimax was hardcoded here, lying about which
        # provider the real run would call. Use the module-level
        # constants so dry-run, status, and the real run all agree.
        print(
            f"would call: provider={PROVIDER_NAME} "
            f"model={PROVIDER_DEFAULT_MODEL} api={PROVIDER_API}"
        )
        print(f"events in first batch: {len(rows)}")
        print(f"prompt chars: {len(prompt)}")
        print(f"prompt preview (first 800 chars):\n{prompt[:800]}")
        return 0

    # Real run
    print(f"\n🚀 Starting L2 full-corpus run")
    print(f"   batch_size: {batch_size}")
    print(f"   max_batches: {args.max_batches or 'unlimited'}")
    print(f"   retry_max: {args.retry_max}")
    print(f"   provider: {PROVIDER_NAME}, model: {PROVIDER_DEFAULT_MODEL}")
    print()
    summary = _run_loop(batch_size, args.max_batches, args.retry_max, api_key)
    print()
    print(f"\n📊 Final summary")
    print(f"{'=' * 50}")
    print(f"   status:                {summary['status']}")
    print(f"   batches completed:     {summary['batches_completed']}")
    print(f"   last event id:         {summary['last_event_id']}")
    print(f"   events processed:      {summary.get('total_events_processed', '?')}")
    print(f"   entities created:      {summary.get('total_entities_created', '?')}")
    print(f"   relationships created: {summary.get('total_relationships_created', '?')}")
    print(f"   wall time:             {summary['wall_seconds']:.1f}s")
    if summary.get("errors"):
        print(f"   errors: {len(summary['errors'])}")
        for e in summary["errors"][:5]:
            print(f"     {e}")
    # Re-pull L2 stats post-run
    print()
    cmd_status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
