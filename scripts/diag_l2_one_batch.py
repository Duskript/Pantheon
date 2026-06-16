"""Single-batch L2 diagnostic.

Captures the prompt, the raw LLM response, and the parser view for one
batch of 5 real cold_events from the corpus. Run after the L2 loop has
been seen to produce 0 yield, to determine which of the 4 failure
modes is active (empty model output / parser drop / unparseable / silent
network error).

Usage:
    /home/konan/.hermes/hermes-agent/venv/bin/python3 \
        /home/konan/pantheon/scripts/diag_l2_one_batch.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_PANTHEON_ROOT = "/home/konan/pantheon"
if _PANTHEON_ROOT not in sys.path:
    sys.path.insert(0, _PANTHEON_ROOT)

_REAL_HOME = Path("/home/konan")
ICHOR_DB = _REAL_HOME / ".hermes" / "ichor.db"

import sqlite3
from lib.ichor.entities.l2_llm import build_prompt, parse_extraction
from lib.ichor.llm import _call_llm


def _load_opencode_go_key() -> str:
    """Same priority order as run_l2_full_corpus.py: env > ~/.hermes/.env > profile."""
    key = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
    if key:
        return key
    global_env = _REAL_HOME / ".hermes" / ".env"
    if global_env.is_file():
        for line in global_env.read_text().splitlines():
            line = line.strip()
            if line.startswith("OPENCODE_GO_API_KEY="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    raise RuntimeError("OPENCODE_GO_API_KEY not found in env or ~/.hermes/.env")


def main() -> int:
    print("=" * 70)
    print("L2 single-batch diagnostic")
    print("=" * 70)

    # 1. Pull 5 real corpus events with substantial raw_text.
    conn = sqlite3.connect(str(ICHOR_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, name, raw_text, god_name
        FROM cold_events
        WHERE raw_text IS NOT NULL
          AND length(raw_text) > 500
        ORDER BY id
        LIMIT 5
        """
    ).fetchall()
    conn.close()

    if len(rows) < 5:
        print(f"ERROR: only {len(rows)} events found with raw_text > 500 chars")
        return 1

    print(f"\nSampled {len(rows)} events:")
    for r in rows:
        print(f"  id={r['id']:>5} god={r['god_name']:<12} len={len(r['raw_text']):>5} name={r['name'][:60]}")

    # 2. Build the prompt the loop would have sent.
    texts = [r["raw_text"] for r in rows]
    prompt = build_prompt(texts)
    print(f"\n=== PROMPT (length={len(prompt)} chars) ===")
    print(prompt[:1500])
    if len(prompt) > 1500:
        print(f"... [{len(prompt) - 1500} more chars truncated]")

    # 3. Call the LLM directly.
    api_key = _load_opencode_go_key()
    print(f"\nAPI key loaded: length={len(api_key)}")

    provider_cfg = {
        "name": "opencode-go",
        "api": "https://opencode.ai/zen/go/v1",
        "api_key": api_key,
        "default_model": "deepseek-v4-flash",
    }

    print("\n=== LLM CALL ===")
    print("Calling https://opencode.ai/zen/go/v1/chat/completions ...")
    try:
        raw = _call_llm(prompt, provider_cfg, model="deepseek-v4-flash", timeout=60.0)
        print(f"OK — response length: {len(raw)} chars")
    except Exception as e:
        print(f"FAILED — {type(e).__name__}: {e}")
        return 2

    print(f"\n=== RAW RESPONSE (first 2000 chars) ===")
    print(raw[:2000])
    if len(raw) > 2000:
        print(f"... [{len(raw) - 2000} more chars truncated]")

    # 4. Parser view.
    print(f"\n=== PARSER VIEW (parse_extraction) ===")
    try:
        parsed = parse_extraction(raw)
        print(json.dumps(parsed, indent=2, default=str)[:3000])
    except Exception as e:
        print(f"parse_extraction raised: {type(e).__name__}: {e}")
        parsed = None

    # 5. Diagnosis.
    print("\n" + "=" * 70)
    print("DIAGNOSIS")
    print("=" * 70)
    if parsed is None:
        print("  FAILURE MODE 3: parse_extraction raised an exception")
    elif isinstance(parsed, dict):
        ents = parsed.get("entities", [])
        rels = parsed.get("relationships", [])
        if not ents and not rels:
            # Was the model returning empty, or did parse_extraction filter?
            # Quick sanity check: does the raw response look like the model
            # *intended* empty, or is there JSON we missed?
            stripped = raw.strip()
            print(f"  Parser returned: entities={len(ents)} relationships={len(rels)}")
            print(f"  Raw response first 200 chars: {stripped[:200]!r}")
            print(f"  Raw response last 200 chars: {stripped[-200:]!r}")
            if "```json" in raw or '"entities"' in raw or '"relationships"' in raw:
                print("  FAILURE MODE 2: raw response contains JSON-like content but parser returned empty")
            else:
                print("  FAILURE MODE 1: model returned empty entities/relationships by design")
        else:
            print(f"  SUCCESS-shaped: entities={len(ents)} relationships={len(rels)}")
            print("  If a real L2 run produces 0 yield, the bug is downstream of parse_extraction")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
