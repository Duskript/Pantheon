#!/usr/bin/env python3
"""Wrapper: run the L2 full-corpus loop against the main ichor.db.

Patches the DB path before calling the corpus loop, since the Thoth
profile's get_conn() resolves to the wrong location.
"""
import sys
import os
from pathlib import Path

REAL_DB = "/home/konan/.hermes/ichor.db"

# Patch the package's DB_PATH before anything imports it
import lib.ichor.entities.schema as schema_mod
schema_mod.DB_PATH = Path(REAL_DB)

# Also patch get_conn's default
original_get_conn = schema_mod.get_conn
def patched_get_conn(db_path=None):
    if db_path is None:
        return original_get_conn(REAL_DB)
    return original_get_conn(db_path)
schema_mod.get_conn = patched_get_conn

# Now run the corpus loop
from scripts.run_l2_full_corpus import _run_loop, _load_api_key, PROVIDER_NAME, PROVIDER_API, PROVIDER_DEFAULT_MODEL

api_key = _load_api_key()
if not api_key:
    print("ERROR: no API key found")
    sys.exit(1)

result = _run_loop(
    api_key=api_key,
    batch_size=50,
    max_batches=None,
    retry_max=3,
)

print(f"\nResult: {result['status']}")
print(f"Batches: {result['batches_completed']}")
print(f"Last event ID: {result['last_event_id']}")
print(f"Errors: {len(result.get('errors', []))}")
