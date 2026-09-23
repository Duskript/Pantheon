#!/usr/bin/env python3
"""Resume L2 full-corpus from batch 100 onward (last_event_id=5133)."""
import sys, os, time, urllib.error, urllib.request, sqlite3
from pathlib import Path

sys.path.insert(0, '/home/konan/pantheon')

# Set DB path before importing schema-dependent modules
import lib.ichor.entities.schema as schema_mod
schema_mod.DB_PATH = '/home/konan/.hermes/ichor.db'

from scripts.run_l2_full_corpus import (
    _load_api_key,
    _call_extract_incremental,
    _say,
    PROVIDER_NAME,
    PROVIDER_API,
    PROVIDER_DEFAULT_MODEL,
)

api_key = _load_api_key()
if not api_key:
    print("ERROR: API key not found", file=sys.stderr)
    sys.exit(1)

# Config keys MUST match what _call_llm() expects:
#   provider_cfg["api"]           -> URL base
#   provider_cfg["default_model"] -> model name
#   provider_cfg["name"]          -> provider name
#   provider_cfg["api_key"]       -> API key
provider_cfg = {
    "api": PROVIDER_API,
    "default_model": PROVIDER_DEFAULT_MODEL,
    "name": "MiniMax",
    "api_key": api_key,
}

# Resume from where the last run stopped (batch 100, new_id 5133)
last_event_id = 5133
batch_size = 50
max_batches = None
retry_max = 3
batch_num = 0
total_chunks_processed = 5000  # carry forward count
total_entities_created = 0
total_rels_created = 0
errors = []
t0 = time.time()

_say(f"resuming L2 full-corpus from last_event_id={last_event_id}")

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
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError, ConnectionError) as exc:
            attempt += 1
            if attempt > retry_max:
                _say(f"  ERROR: persistent network failure after "
                     f"{retry_max+1} attempts: {exc!r}")
                errors.append({"batch": batch_num, "type": "network",
                               "detail": str(exc)})
                _say(f"  SKIP batch {batch_num} (network)")
                result = {"events_in_batch": 50,
                          "last_event_id_after": last_event_id + batch_size,
                          "stored": {}}
                break
            backoff = 2 ** attempt
            _say(f"  retry {attempt}/{retry_max} after {backoff}s: {exc!r}")
            time.sleep(backoff)
        except Exception as exc:
            attempt += 1
            if attempt > retry_max:
                errors.append({"batch": batch_num, "type": "logic",
                               "detail": str(exc)})
                _say(f"  SKIP batch {batch_num}: {exc!r}")
                result = {"events_in_batch": 50,
                          "last_event_id_after": last_event_id + batch_size,
                          "stored": {}}
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

    _say(
        f"  batch {batch_num + 100:4d} | events {events_in_batch:3d} | "
        f"new_id {last_id_after:6d} | +{ent_created:3d} entities "
        f"+{rel_created:3d} rels | "
        f"total {total_chunks_processed:6d} events processed | "
        f"{rate:5.1f} ev/s | {elapsed:6.1f}s"
    )

    if events_in_batch == 0:
        _say("no more events — corpus exhausted")
        break
    if last_id_after == last_event_id:
        _say("WARNING: last_event_id did not advance, breaking")
        break
    last_event_id = last_id_after

print()
print(f"\n{'=' * 50}")
print(f"   status:                {'complete' if not errors else 'complete_with_errors'}")
print(f"   batches completed:     {batch_num}")
print(f"   last event id:         {last_event_id}")
print(f"   events processed:      {total_chunks_processed}")
print(f"   entities created:      {total_entities_created}")
print(f"   relationships created: {total_rels_created}")
print(f"   wall time:             {time.time() - t0:.1f}s")
if errors:
    print(f"   errors: {len(errors)}")
    for e in errors[:5]:
        print(f"     {e}")
