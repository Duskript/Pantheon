#!/usr/bin/env python3
"""Shared-ledger recurrence writer — 2026-09-17T13:02:49Z sweep (recurrence 18).

Exact frozen-pool replay of the post-20260916T190200Z cohort. A replay writes NO
Dojo sink: the only durable write is ONE recurrence line appended to
~/pantheon/shared/active/marvin-skill-crystallization.md (406 -> 407 lines).

Implements the append-only-sink-writes protocol:
  - payload composed to a sweep-unique file FIRST, asserted on disk
  - --target lets the caller point at a COPY for the copy-first test
  - idempotency guard: refuses if the signature is already present (no second write)
  - prints delta_bytes / line-delta / sha256 so the caller can hash-compare

Usage:
  python3 record_recurrence_20260917T1302Z.py --assert-only
  python3 record_recurrence_20260917T1302Z.py --target /tmp/copy.md      # copy-first
  python3 record_recurrence_20260917T1302Z.py --target /tmp/copy.md      # -> refusal
  python3 record_recurrence_20260917T1302Z.py                            # ONE real write
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

PAYLOAD = Path("/tmp/recurrence-payload-20260917T1302Z.txt")
REAL_SINK = Path("/home/konan/pantheon/shared/active/marvin-skill-crystallization.md")

# The idempotency signature: must be unique in the sink and absent before the write.
SIGNATURE = "recurrence 18 of the post-20260916T190200Z cohort"
START_MARKER = "- **2026-09-17T13:00Z \u2014 recurrence 18"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_payload() -> str:
    text = PAYLOAD.read_text(encoding="utf-8")
    assert text.endswith("\n"), "payload must end with exactly one trailing newline"
    assert text.count("\n") == 1, f"payload must be ONE physical line, got {text.count(chr(10))}"
    assert SIGNATURE in text, "payload is missing the idempotency signature"
    assert text.startswith(START_MARKER), f"payload must start with {START_MARKER!r}"
    assert "\\\"" not in text, "payload contains a backslash-quote escaping artifact"
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=str(REAL_SINK))
    ap.add_argument("--assert-only", action="store_true")
    args = ap.parse_args()

    target = Path(args.target)
    payload = load_payload()
    print(f"payload: {len(payload)} chars / {len(payload.encode('utf-8'))} bytes / 1 line")

    if args.assert_only:
        print("ASSERT_OK")
        return 0

    existing = target.read_text(encoding="utf-8")
    if SIGNATURE in existing:
        print(f"REFUSED: signature already present in {target} — nothing appended (guard held)")
        return 3

    before_lines = existing.count("\n")
    before_bytes = target.stat().st_size
    before_sha = sha(target)

    with open(target, "a", encoding="utf-8") as fh:
        fh.write(payload)

    after_lines = target.read_text(encoding="utf-8").count("\n")
    after_bytes = target.stat().st_size
    after_sha = sha(target)

    delta_bytes = after_bytes - before_bytes
    payload_bytes = len(payload.encode("utf-8"))
    print(f"target:       {target}")
    print(f"before_sha:   {before_sha[:16]}")
    print(f"after_sha:    {after_sha[:16]}")
    print(f"delta_bytes:  {delta_bytes}  (payload_bytes {payload_bytes})")
    print(f"line_delta:   {after_lines - before_lines}")
    ok = delta_bytes == payload_bytes and (after_lines - before_lines) == 1
    print("DELTA_OK" if ok else "DELTA_MISMATCH")
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
