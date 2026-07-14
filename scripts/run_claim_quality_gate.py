#!/usr/bin/env python3
"""Phase 0C Quality Gate: Run claim extractor against 10 representative sessions.

SPEC requirement: 8 of 10 representative sessions must produce claims.

Usage:
    python3 scripts/run_claim_quality_gate.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

# Ensure pantheon is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.ichor.contracts import ClaimStore
from lib.ichor.llm import _resolve_llm_provider
from lib.extractors.llm_extractor import LLMClaimExtractor

ICHOR_DB = Path.home() / ".hermes" / "ichor.db"
CLAIM_DB = Path.home() / ".hermes" / "ichor_claims.db"
MAX_EVENTS_PER_SESSION = 25  # sample size per session
RETRY_DELAY = 30  # seconds to wait between retries on 429
MAX_RETRIES = 3  # max retry attempts per session


def get_representative_sessions(limit: int = 10) -> list[tuple[str, int]]:
    """Get the top N sessions by event count."""
    conn = sqlite3.connect(str(ICHOR_DB))
    cur = conn.execute(
        """
        SELECT session_id, COUNT(*) as cnt
        FROM cold_events
        WHERE session_id IS NOT NULL AND session_id != ''
        GROUP BY session_id
        ORDER BY cnt DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()
    conn.close()
    return [(r[0], r[1]) for r in rows]


def sample_events_from_session(session_id: str, limit: int = MAX_EVENTS_PER_SESSION) -> list[tuple[int, str]]:
    """Sample events from a session, preferring content-bearing rows.

    The cold_events table has columns: id, event_type, category, name,
    confidence, importance, trust, raw_text, speaker, session_id, god_name,
    direction, peer_god, created_at, brief, outline, goal_id.

    We use `raw_text` as the primary text content column, falling back to
    `brief` or `outline` if raw_text is empty.
    """
    conn = sqlite3.connect(str(ICHOR_DB))
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT id, COALESCE(NULLIF(raw_text, ''), NULLIF(brief, ''), NULLIF(outline, '')) as text
        FROM cold_events
        WHERE session_id = ?
          AND COALESCE(NULLIF(raw_text, ''), NULLIF(brief, ''), NULLIF(outline, '')) IS NOT NULL
          AND length(COALESCE(NULLIF(raw_text, ''), NULLIF(brief, ''), NULLIF(outline, ''))) > 10
        ORDER BY id DESC
        LIMIT ?
        """,
        (session_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return [(int(r["id"]), str(r["text"])[:1500]) for r in rows if r["text"]]


def extract_with_retry(extractor, events, session_id, provider_cfg):
    """Run extraction with retry-on-429 and exponential backoff."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = extractor.extract(
                events,
                session_id=session_id,
                provider_cfg=provider_cfg,
                model=None,
                timeout=180.0,
            )
            return result, None
        except Exception as e:
            err_str = str(e)
            if "429" in err_str and attempt < MAX_RETRIES:
                wait = RETRY_DELAY * attempt
                print(f"  429 rate-limited, waiting {wait}s before retry {attempt + 1}/{MAX_RETRIES}...", flush=True)
                time.sleep(wait)
                continue
            return None, e
    return None, Exception("max retries exceeded")


def main() -> None:
    print("=" * 60, flush=True)
    print("  Ichor Phase 0C — Claim Extraction Quality Gate", flush=True)
    print("=" * 60, flush=True)

    # 1. Resolve provider
    provider_cfg = _resolve_llm_provider("marvin") or _resolve_llm_provider("opencode-go")
    if not isinstance(provider_cfg, dict):
        print("ERROR: No LLM provider configured for marvin or opencode-go", flush=True)
        sys.exit(1)
    print(f"\nProvider: {provider_cfg.get('name', 'unknown')}", flush=True)
    print(f"Model: {provider_cfg.get('default_model', 'unknown')}", flush=True)
    print(f"API base: {provider_cfg.get('api', 'unknown')}", flush=True)

    # 2. Get 10 representative sessions
    sessions = get_representative_sessions(limit=10)
    print(f"\nSampling {len(sessions)} sessions:", flush=True)
    for sid, cnt in sessions:
        print(f"  {sid}: {cnt} events", flush=True)

    # 3. Initialize claim store + extractor
    store = ClaimStore(CLAIM_DB)
    extractor = LLMClaimExtractor(store)

    # 4. Run extraction with retry
    results = []
    sessions_with_claims = 0
    total_claims = 0

    for i, (session_id, event_count) in enumerate(sessions, 1):
        print(f"\n--- Session {i}/{len(sessions)}: {session_id} ({event_count} events) ---", flush=True)
        events = sample_events_from_session(session_id)
        if not events:
            print("  No content-bearing events found — skipping", flush=True)
            results.append({"session": session_id, "claims_created": 0, "skipped": True})
            continue

        print(f"  Sampled {len(events)} events", flush=True)
        started = time.perf_counter()
        result, error = extract_with_retry(extractor, events, session_id, provider_cfg)
        elapsed = (time.perf_counter() - started)

        if error:
            print(f"  ERROR: {error}", flush=True)
            print(f"  Latency: {elapsed:.1f}s", flush=True)
            results.append({
                "session": session_id,
                "events_sampled": len(events),
                "claims_created": 0,
                "error": str(error),
                "latency_s": round(elapsed, 1),
            })
            # Wait before next session to avoid cascading 429s
            if "429" in str(error):
                print(f"  Cooling down 30s...", flush=True)
                time.sleep(30)
            continue

        claims_created = result.get("claims_created", 0)
        fallback = result.get("fallback_used", False)
        warnings = result.get("parse_warnings", [])

        print(f"  Claims: {claims_created}", flush=True)
        print(f"  Fallback: {fallback}", flush=True)
        if warnings:
            print(f"  Warnings: {warnings}", flush=True)
        print(f"  Latency: {elapsed:.1f}s", flush=True)

        if claims_created > 0:
            sessions_with_claims += 1
        total_claims += claims_created
        results.append({
            "session": session_id,
            "events_sampled": len(events),
            "claims_created": claims_created,
            "fallback_used": fallback,
            "warnings": warnings,
            "latency_s": round(elapsed, 1),
        })

        # Small pause between sessions to avoid rate limiting
        if i < len(sessions):
            print(f"  Pausing 10s before next session...", flush=True)
            time.sleep(10)

    # 5. Final report
    print("\n" + "=" * 60, flush=True)
    print("  QUALITY GATE RESULTS", flush=True)
    print("=" * 60, flush=True)
    print(f"  Sessions tested:     {len(sessions)}", flush=True)
    print(f"  Sessions with claims: {sessions_with_claims}", flush=True)
    print(f"  Total claims created: {total_claims}", flush=True)
    print(f"  Gate requirement:     8 of 10 sessions produce claims", flush=True)
    gate_result = "PASS ✅" if sessions_with_claims >= 8 else "FAIL ⏳"
    print(f"  Result:               {gate_result} ({sessions_with_claims}/10)", flush=True)
    print("=" * 60, flush=True)

    # Write full results
    results_path = Path.home() / "pantheon" / "claim_quality_gate_results.json"
    with open(results_path, "w") as f:
        json.dump({
            "sessions_tested": len(sessions),
            "sessions_with_claims": sessions_with_claims,
            "total_claims": total_claims,
            "gate_passed": sessions_with_claims >= 8,
            "details": results,
        }, f, indent=2)
    print(f"\nFull results: {results_path}", flush=True)


if __name__ == "__main__":
    main()