#!/usr/bin/env python3
"""Final PII-only assertion check (assertion 4 properly).

This bypasses the smoke.py scan_for_pii() helper which still uses
Python's default User-Agent and 403s on Cloudflare. Fetches each
registry with a real browser UA and scans for forbidden PII fields.
"""
import json
import sys
import urllib.request

REGISTRIES = [
    "https://forge-adjustments.theoforgesolutions.com/INDEX.json",
    "https://memory-patterns.theoforgesolutions.com/INDEX.json",
    "https://dojo-learnings.theoforgesolutions.com/INDEX.json",
    "https://pattern-effectiveness.theoforgesolutions.com/INDEX.json",
]
PII = ["session_id", "user_id", "raw_text", "user_intent"]
# 'query' is too short to grep safely; use as a JSON key check

hits = []
for url in REGISTRIES:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; clawforge-smoke-finalcheck/1.0)"},
        )
        body = urllib.request.urlopen(req, timeout=10).read().decode("utf-8")
    except Exception as e:
        print(f"[FAIL] could not fetch {url}: {e}", file=sys.stderr)
        sys.exit(1)
    for field in PII:
        if field in body:
            hits.append((url, field))
    if '"query"' in body or "'query'" in body:
        hits.append((url, "query"))

if hits:
    print(f"[FAIL] PII hits: {hits}", file=sys.stderr)
    sys.exit(1)
print(f"[PASS] [4/4] no PII fields in any of {len(REGISTRIES)} registries")
