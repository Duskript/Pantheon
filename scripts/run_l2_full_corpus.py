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

API key resolution order (credential pool first — see _load_api_key):
  1. the Hermes credential pool, ~/.hermes/auth.json (canonical, rotated)
  2. $OPENCODE_GO_API_KEY in the environment
  3. ~/.hermes/.env
  4. ~/.hermes/profiles/{marvin,hephaestus,thoth,iris,apollo}/.env

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

# Floor for adaptive batch shrinking on truncation. Below this the prompt is
# too small to be worth an LLM call.
_MIN_BATCH_SIZE = 5

# Default events per call. 50 was the historical default and is too large:
# `_call_llm` caps responses at max_tokens=8000, so a 50-event call (30,625-char
# prompt) asks for more JSON than the budget allows and the response is
# truncated. 20 keeps the prompt near ~12k chars, under the cap with headroom.
DEFAULT_BATCH_SIZE = 20


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
    # 0. The Hermes credential pool is the canonical source.
    #    config.yaml provider blocks carry an empty `api_key` by design and the
    #    real tokens live in ~/.hermes/auth.json, where Hermes rotates them.
    #    Resolving only from env / .env is what left L2 extraction with no
    #    credential — 456 silently-skipped ticks including 26 unbroken days
    #    (see issues #152 and #154). The pool is consulted first so a missing
    #    env var can no longer disable the drainer.
    try:
        from lib.ichor.llm import resolve_provider_credentials
        _pool_key, _pool_url = resolve_provider_credentials(PROVIDER_NAME)
        if _pool_key:
            return _pool_key
    except Exception:
        pass

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
            # Name the producer. extraction_log is multi-writer (2,182 DB rows
            # vs 183 journal batches), so a row's origin has to be recorded or
            # any metric over this table mixes producers.
            writer="run_l2_full_corpus",
        )
    finally:
        con.close()
    return result


# The shared L2 extraction cursor. The Ichor tick writes this file after every
# batch; the drainer must read and advance the SAME cursor, or the two writers
# fight over corpus progress.
_L2_EXTRACT_STATE = _REAL_HOME / ".hermes" / "ichor_l2_extract_state.json"


def _read_l2_cursor() -> int:
    """Read the shared L2 extraction cursor (the tick's state file).

    Returns 0 when the file is absent or unreadable, which is the correct
    "start of corpus" value.
    """
    try:
        return int(json.loads(_L2_EXTRACT_STATE.read_text()).get("last_event_id", 0))
    except (OSError, json.JSONDecodeError, ValueError, AttributeError):
        return 0


def _write_l2_cursor(cursor: int) -> None:
    """Persist the shared cursor after each successful batch (crash-safe).

    Written in the same shape the tick uses, with an extra `writer` key that is
    additive and ignored by the tick's reader.
    """
    try:
        _L2_EXTRACT_STATE.parent.mkdir(parents=True, exist_ok=True)
        _L2_EXTRACT_STATE.write_text(json.dumps({
            "last_event_id": int(cursor),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "writer": "run_l2_full_corpus",
        }))
    except OSError as exc:
        _say(f"  WARNING: could not persist L2 cursor {cursor}: {exc}")


# Exclusive-run guard. The drainer advances the SHARED L2 cursor, so two
# overlapping runs would read the same cursor, extract the same events twice, and
# interleave cursor writes — duplicating entities and losing progress. Scheduling
# the drainer makes an overrun reachable (a run that outlasts its interval), so
# guard explicitly instead of trusting the scheduler not to overlap.
_LOCK_PATH = _REAL_HOME / ".hermes" / "pantheon" / "l2-drainer.lock"


def _acquire_run_lock():
    """Non-blocking exclusive lock. Returns a file handle, or None if held."""
    import fcntl
    try:
        _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fh = open(_LOCK_PATH, "w")
    except OSError as exc:
        _say(f"WARNING: could not open run lock {_LOCK_PATH}: {exc}")
        return object()  # fail-open on an unusable lockfile, but say so
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fh.write(f"{os.getpid()}\n")
    fh.flush()
    return fh


def _run_loop(
    batch_size: int,
    max_batches: int | None,
    retry_max: int,
    api_key: str,
    restart_from_zero: bool = False,
) -> dict:
    """The main loop.

    Starts from the **shared** L2 cursor so it continues where the Ichor tick
    left off. Pass ``restart_from_zero=True`` (CLI: ``--restart``) to re-run the
    whole corpus from the beginning — that is a full re-extraction of ~76.5k
    events and is therefore opt-in, not the default.
    """
    provider_cfg = {
        "api": PROVIDER_API,
        "default_model": PROVIDER_DEFAULT_MODEL,
        "name": PROVIDER_NAME,
        "api_key": api_key,
    }

    # Resume from the SHARED cursor so the drainer continues where the tick
    # left off.
    #
    # This previously hardcoded 0 with a comment claiming idempotence. It was
    # not harmless: every invocation re-extracted the entire cold_events corpus
    # (~76.5k events, of which ~30k were already done) at ~50 events per batch,
    # and it shared no progress with the tick's cursor. A full pass is now
    # explicit via restart_from_zero.
    last_event_id = 0 if restart_from_zero else _read_l2_cursor()
    _say(
        f"starting from last_event_id={last_event_id}"
        + (" (--restart: full corpus from 0)" if restart_from_zero else " (shared cursor)")
    )
    batch_num = 0
    total_chunks_processed = 0
    total_entities_created = 0
    total_rels_created = 0
    errors = []
    # Set when a batch exhausted its retries. The run stops WITHOUT advancing
    # the cursor, so the failed events are retried by the next invocation.
    fatal_stop = False
    t0 = time.time()

    while True:
        if max_batches is not None and batch_num >= max_batches:
            _say(f"reached max_batches={max_batches}, stopping")
            break

        attempt = 0
        result = None
        # Retry with a SMALLER batch on truncation instead of retrying
        # identically. `_call_llm` caps the response at max_tokens=8000
        # (lib/ichor/llm.py:334), so a large batch asks the model for more JSON
        # than the response budget can hold and the answer is cut off
        # mid-object — which surfaces as "could not parse JSON". Measured:
        # batch 50 -> 30,625-char prompt -> truncation; batch 15 -> 6,090 chars
        # -> clean. Retrying the same size just repeats the failure.
        eff_batch = batch_size
        while attempt <= retry_max:
            try:
                result = _call_extract_incremental(
                    last_event_id, eff_batch, provider_cfg, api_key,
                )
                break
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError) as exc:
                attempt += 1
                if attempt > retry_max:
                    errors.append({"batch": batch_num, "type": "network", "detail": str(exc)})
                    _say(
                        f"  STOP after {retry_max+1} attempts (network): {exc!r}"
                    )
                    _say(
                        f"  cursor left at {last_event_id} — batch {batch_num} was NOT "
                        f"skipped, so the next run retries it"
                    )
                    fatal_stop = True
                    result = None
                    break
                backoff = 2 ** attempt
                _say(f"  retry {attempt}/{retry_max} after {backoff}s: {exc!r}")
                time.sleep(backoff)
            except Exception as exc:
                if "could not parse JSON" in str(exc) and eff_batch > _MIN_BATCH_SIZE:
                    eff_batch = max(_MIN_BATCH_SIZE, eff_batch // 2)
                    _say(
                        f"  response truncated at batch_size={eff_batch * 2} — "
                        f"retrying with batch_size={eff_batch}"
                    )
                attempt += 1
                if attempt > retry_max:
                    errors.append({"batch": batch_num, "type": "logic", "detail": str(exc)})
                    _say(
                        f"  STOP after {retry_max+1} attempts: {exc!r}"
                    )
                    _say(
                        f"  cursor left at {last_event_id} — batch {batch_num} was NOT "
                        f"skipped, so the next run retries it"
                    )
                    fatal_stop = True
                    result = None
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
            f"  batch {batch_num:4d} | batch_size {eff_batch:3d} | events {events_in_batch:3d} | "
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
        # Crash-safe: the cursor on disk always reflects the last batch that
        # actually completed, so an interrupted run resumes cleanly.
        _write_l2_cursor(last_event_id)

    return {
        "status": (
            "stopped_on_error" if fatal_stop
            else ("complete" if not errors else "complete_with_errors")
        ),
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
        print("   ⚠️  No credential: add one to the pool (~/.hermes/auth.json) or set OPENCODE_GO_API_KEY")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Run L2 extraction over the full cold_events corpus",
    )
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"events per LLM call (default {DEFAULT_BATCH_SIZE}; max 200). "
             "Large batches overflow the response token budget and truncate "
             "the JSON — the retry loop halves the batch automatically.",
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
        "--restart", action="store_true",
        help="Re-extract the WHOLE corpus from id 0 instead of resuming from "
             "the shared L2 cursor (~30k events are already extracted; this "
             "is a full re-run and normally not what you want)",
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
        print("ERROR: no opencode-go credential resolvable. Run with --status.", file=sys.stderr)
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
    # Hold the exclusive run lock for the whole run (the handle must stay
    # referenced; it is released when this process exits).
    run_lock = _acquire_run_lock()
    if run_lock is None:
        print("another L2 drainer run holds the lock — exiting without work",
              file=sys.stderr)
        return 0

    summary = _run_loop(batch_size, args.max_batches, args.retry_max, api_key,
                         restart_from_zero=args.restart)
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

    # Exit non-zero when the run stopped because a batch failed, so systemd and
    # any watchdog can see it. Returning 0 unconditionally made a failed run
    # indistinguishable from a clean one — the same dead-success pattern fixed in
    # ichor_tick's summary gate. The cursor is safe either way: a stopped run
    # leaves it at the last successful batch, so the next run retries.
    if summary["status"] == "stopped_on_error":
        print(
            f"\n   ❌ stopped_on_error — exiting non-zero. "
            f"Cursor is at {summary['last_event_id']}; the next run retries the "
            f"failed batch."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
