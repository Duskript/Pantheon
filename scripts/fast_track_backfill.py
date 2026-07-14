#!/usr/bin/env python3
"""Fast-track L2 backfill from cursor -> end, then finalize, then dream cycle."""
import json, sys, time, sqlite3, urllib.error, faulthandler
from pathlib import Path

print(f"{time.strftime('%H:%M:%S')} | bootstrap: fast_track_backfill starting", flush=True)
faulthandler.dump_traceback_later(90, repeat=True)

sys.path.insert(0, "/home/konan/pantheon")
_ICHOR_DB = Path.home() / ".hermes" / "ichor.db"
_STATE_FILE = Path.home() / ".hermes" / "ichor_subconscious" / "l2_last_event_id.txt"
# Keep batches small enough that DeepSeek emits complete JSON reliably.
# Do not advance cursor on parse failure; complete backfill beats speed.
_BATCH_SIZE = 10
_RETRY_MAX = 5

def say(msg):
    print(f"{time.strftime('%H:%M:%S')} | {msg}", flush=True)

# ── Phase 1: Fast-track L2 backfill ──

from lib.ichor.llm import _load_provider_config
from lib.ichor.entities import extract_incremental
from lib.ichor.entities.schema import get_conn

provider_cfg = _load_provider_config("opencode-go")
if not isinstance(provider_cfg, dict):
    sys.exit("FATAL: no opencode-go provider in Hermes config")

provider_cfg["name"] = "opencode-go"

# Load API key from auth.json credential pool
_auth_path = Path.home() / ".hermes" / "auth.json"
if _auth_path.exists():
    try:
        _auth = json.loads(_auth_path.read_text())
        for _creds in _auth.get("credential_pool", {}).get("opencode-go", []):
            _token = _creds.get("access_token", "")
            if _token:
                provider_cfg["api_key"] = _token
                say(f"Loaded API key from auth.json (len={len(_token)})")
                break
    except Exception as e:
        say(f"Warning: could not load auth.json: {e}")

if not provider_cfg.get("api_key"):
    sys.exit("FATAL: no API key found in auth.json credential_pool.opencode-go")

# Read cursor
cursor = 0
if _STATE_FILE.exists():
    cursor = int(_STATE_FILE.read_text().strip())
say(f"Starting L2 from cursor={cursor} (batch_size={_BATCH_SIZE})")

t0 = time.perf_counter()
total_events = 0
total_entities = 0
total_relationships = 0
batches = 0
errors = 0

while True:
    elapsed = time.perf_counter() - t0
    if elapsed > 10800:  # 3 hour safety budget for full catch-up
        say(f"Time budget reached ({elapsed:.0f}s), stopping")
        break

    # Retry loop
    result = None
    for attempt in range(_RETRY_MAX + 1):
        try:
            conn = get_conn()
            try:
                result = extract_incremental(
                    conn,
                    last_event_id=cursor,
                    batch_size=_BATCH_SIZE,
                    provider_cfg=provider_cfg,
                    session_id="fast-track-backfill",
                )
            finally:
                conn.close()
            break
        except (ValueError, json.JSONDecodeError) as e:
            msg = str(e)[:200]
            if attempt < _RETRY_MAX:
                backoff = 2 ** attempt
                say(f"  retry {attempt+1}/{_RETRY_MAX} after {backoff}s: {msg}")
                time.sleep(backoff)
            else:
                # Parse failures usually mean the model truncated/malformed JSON.
                # Do not synthesize progress or advance the cursor; retry the same
                # event window so the backfill remains complete.
                errors += 1
                say(f"  persistent parse failure at cursor={cursor}; sleeping 30s and retrying same cursor with batch_size={_BATCH_SIZE}: {msg}")
                time.sleep(30)
                result = None
        except urllib.error.HTTPError as e:
            # 429 means the key/provider is rate-limiting. Do NOT advance the cursor;
            # sleep and retry this same batch so backfill remains complete.
            if e.code == 429:
                wait = 60 * (attempt + 1)
                say(f"  rate limited (429); sleeping {wait}s before retrying same cursor={cursor}")
                time.sleep(wait)
                continue
            if attempt < _RETRY_MAX:
                backoff = 2 ** attempt
                say(f"  network retry {attempt+1}/{_RETRY_MAX} after {backoff}s: {e!r}")
                time.sleep(backoff)
            else:
                errors += 1
                say(f"  SKIP batch (network non-429): {e!r}")
                result = {"events_in_batch": _BATCH_SIZE,
                          "last_event_id_after": cursor + _BATCH_SIZE,
                          "stored": {}}
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < _RETRY_MAX:
                backoff = 2 ** attempt
                say(f"  network retry {attempt+1}/{_RETRY_MAX} after {backoff}s: {e!r}")
                time.sleep(backoff)
            else:
                errors += 1
                say(f"  SKIP batch (network non-429): {e!r}")
                result = {"events_in_batch": _BATCH_SIZE,
                          "last_event_id_after": cursor + _BATCH_SIZE,
                          "stored": {}}
        except Exception as e:
            if attempt < _RETRY_MAX:
                backoff = 2 ** attempt
                say(f"  retry {attempt+1}/{_RETRY_MAX} after {backoff}s: {e!r}")
                time.sleep(backoff)
            else:
                errors += 1
                say(f"  SKIP batch (unexpected): {e!r}")
                result = {"events_in_batch": _BATCH_SIZE,
                          "last_event_id_after": cursor + _BATCH_SIZE,
                          "stored": {}}

    if result is None:
        # A retryable failure happened without a valid extraction result.
        # Loop back without touching the cursor.
        continue

    events_in_batch = int(result.get("events_in_batch", 0))
    if events_in_batch == 0:
        say(f"No more events -- caught up at cursor={cursor}")
        break

    cursor = int(result.get("last_event_id_after", cursor))
    _STATE_FILE.write_text(str(cursor))
    batches += 1
    total_events += events_in_batch
    stored = result.get("stored", {})
    total_entities += int(stored.get("entities_created", 0))
    total_relationships += int(stored.get("relationships_created", 0))

    rate = total_events / max(1, time.perf_counter() - t0)
    say(f"batch {batches:4d} | +{events_in_batch:3d} ev | cursor={cursor:6d} | "
        f"+{total_entities:4d} ent +{total_relationships:4d} rel | "
        f"{rate:.1f} ev/s | {time.perf_counter() - t0:.0f}s")

    if events_in_batch < _BATCH_SIZE:
        say("Batch smaller than requested -- caught up to end")
        break

elapsed = time.perf_counter() - t0
say(f"\n== Phase 1 done: {batches} batches, {total_events} events, "
    f"{total_entities} entities, {total_relationships} rels, "
    f"{errors} errors in {elapsed:.0f}s ==")

# ── Phase 2/3: Finalize + dream only if caught up ──

conn = get_conn()
try:
    max_event_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM cold_events").fetchone()[0]
finally:
    conn.close()

fin_result = {"skipped": "not_caught_up", "cursor": cursor, "max_event_id": max_event_id}
dream_result = {"skipped": "not_caught_up", "cursor": cursor, "max_event_id": max_event_id}

if cursor >= max_event_id:
    say("\n--- Phase 2: Finalizing provisional entities/relationships ---")
    # Avoid finalize() residual mega-batch; we are already caught up.
    conn = get_conn()
    try:
        flipped_entities = conn.execute("UPDATE entities SET provisional = 0 WHERE provisional = 1").rowcount
        flipped_relationships = conn.execute("UPDATE relationships SET provisional = 0 WHERE provisional = 1").rowcount
        conn.commit()
        fin_result = {
            "flipped_entities_provisional": flipped_entities,
            "flipped_relationships_provisional": flipped_relationships,
        }
    finally:
        conn.close()
    say(f"Finalize result: {json.dumps(fin_result, default=str)}")

    say("\n--- Phase 3: Dream cycle ---")
    from lib.ichor.entities.dream import run_dream_cycle
    from lib.ichor.entities.schema import DB_PATH
    dream_result = run_dream_cycle(db_path=str(DB_PATH))
    say(f"Dream cycle result: {json.dumps(dream_result, default=str)}")
else:
    say(f"Not caught up yet (cursor={cursor}, max_event_id={max_event_id}); skipping finalize/dream for this sweep")

# ── Final summary ──

conn = get_conn()
try:
    e_cnt = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    r_cnt = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    prov_e = conn.execute("SELECT COUNT(*) FROM entities WHERE provisional=1").fetchone()[0]
    prov_r = conn.execute("SELECT COUNT(*) FROM relationships WHERE provisional=1").fetchone()[0]
    llm_log = conn.execute("SELECT COUNT(*) FROM extraction_log WHERE method='llm'").fetchone()[0]
finally:
    conn.close()

say(f"\n{'='*50}")
say(f"FINAL STATE:")
say(f"  entities:          {e_cnt}")
say(f"  relationships:     {r_cnt}")
say(f"  provisional ents:  {prov_e}")
say(f"  provisional rels:  {prov_r}")
say(f"  LLM extractions:   {llm_log}")
print(json.dumps({
    "batches": batches,
    "events_processed": total_events,
    "entities_created": total_entities,
    "relationships_created": total_relationships,
    "errors": errors,
    "finalized": fin_result,
    "dream_cycle": dream_result,
    "cursor": cursor,
    "wall_seconds": round(elapsed, 1),
    "final_entities": e_cnt,
    "final_relationships": r_cnt,
    "provisional_entities": prov_e,
    "provisional_relationships": prov_r,
    "llm_extractions": llm_log,
}, indent=2))
