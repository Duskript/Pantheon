#!/usr/bin/env python3
"""
Clawforge Audit — v0.4.0

Append-only JSONL audit log for cross-instance god requests.

Files written:
    ~/.hermes/clawforge/audit/<role>-<YYYY-MM-DD>.jsonl

Where <role> is "messenger" (receiver) or "ask" (sender). The active
file is always today's; we never append to a closed file (rotation
happens on first write after midnight UTC).

Each record is one line of JSON. Schema:
    {
      "ts": "2026-06-11T05:30:00Z",        # UTC timestamp
      "request_id": "abc123-...",           # matches NATS request
      "from_instance": "konan",             # sender instance
      "from_god": "messenger-cli",          # sender god (or "messenger-cli")
      "target_god": "iris",                 # god being called
      "target_instance": "konan",           # receiver instance
      "prompt_len": 42,                     # chars in prompt
      "response_len": 280,                  # chars in response
      "duration_seconds": 27.3,             # wall clock for the call
      "status": "ok" | "rate_limited" | "error" | "timeout"
      "error": "...",                       # only when status != ok
      "retry_after_seconds": 1.0,           # only when rate_limited
    }

Retention: FOREVER (user picked `retention_forever`). The module will
emit a WARNING log line if the audit directory exceeds 1 GB total,
but never deletes anything.

CLI:
    clawforge-audit.py summary [--role messenger|ask] [--days 7]
    clawforge-audit.py list [--role messenger|ask] [--last 24h|7d|100]
                            [--status ok|rate_limited|error|timeout]
                            [--god <name>] [--json]
    clawforge-audit.py size  # total bytes in audit dir
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

log = logging.getLogger("clawforge-audit")

DEFAULT_AUDIT_DIR = os.path.expanduser("~/.hermes/clawforge/audit")
SIZE_WARN_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB
_DURATION_RE = re.compile(r"^(\d+)([mhd])$")  # 5m, 24h, 7d


# ----- Writer ---------------------------------------------------------------

class AuditWriter:
    """One writer per role. Append-only, with daily rotation."""

    def __init__(self, role: str, audit_dir: str = DEFAULT_AUDIT_DIR):
        if role not in ("messenger", "ask"):
            raise ValueError(f"role must be 'messenger' or 'ask', got {role!r}")
        self.role = role
        self.dir = Path(audit_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._current_date: Optional[str] = None
        self._fh = None
        self._lock_path = self.dir / f".{role}.lock"

    def _active_path(self, date: str) -> Path:
        return self.dir / f"{self.role}-{date}.jsonl"

    def _open(self, date: str) -> None:
        path = self._active_path(date)
        # Open in append mode, line-buffered
        self._fh = open(path, "a", buffering=1, encoding="utf-8")
        self._current_date = date
        log.debug(f"audit: opened {path}")

    def _maybe_rotate(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._current_date != today:
            if self._fh:
                self._fh.close()
            self._open(today)

    def write(self, record: dict) -> None:
        """Append a record. Auto-rotates to today's file. NOT thread-safe
        but Clawforge messenger/ask are single-process, single-coroutine
        paths so this is fine. (If we add threading later, wrap with a
        threading.Lock or move to a single asyncio.create_task writer.)"""
        self._maybe_rotate()
        # Always include ts if not set
        record.setdefault("ts", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
        try:
            self._fh.write(line)
        except Exception as e:
            log.error(f"audit write failed: {e}")
        self._check_size_warning()

    def _check_size_warning(self) -> None:
        # Total size of the audit dir; warn if > 1GB. Cheap enough to do
        # on every write (modern filesystems handle this in O(dirents)).
        try:
            total = sum(p.stat().st_size for p in self.dir.glob("*.jsonl"))
        except OSError:
            return
        if total > SIZE_WARN_BYTES:
            log.warning(
                f"audit dir size {total/1024/1024:.1f} MB exceeds 1GB threshold; "
                f"consider pruning. (User opted into forever retention.)"
            )

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None
            self._current_date = None


# ----- Record builder helper -----------------------------------------------

def make_record(
    *,
    request_id: str,
    from_instance: str,
    from_god: str,
    target_god: str,
    target_instance: str,
    prompt_len: int,
    response_len: int,
    duration_seconds: float,
    status: str,
    error: Optional[str] = None,
    retry_after_seconds: Optional[float] = None,
) -> dict:
    rec = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "request_id": request_id,
        "from_instance": from_instance,
        "from_god": from_god,
        "target_god": target_god,
        "target_instance": target_instance,
        "prompt_len": prompt_len,
        "response_len": response_len,
        "duration_seconds": round(duration_seconds, 3),
        "status": status,
    }
    if error:
        rec["error"] = error
    if retry_after_seconds is not None:
        rec["retry_after_seconds"] = round(retry_after_seconds, 2)
    return rec


# ----- Reader / filters -----------------------------------------------------

def _iter_files(role: str, audit_dir: str = DEFAULT_AUDIT_DIR) -> Iterable[Path]:
    d = Path(audit_dir)
    if not d.exists():
        return
    # Newest first
    yield from sorted(d.glob(f"{role}-*.jsonl"), reverse=True)


def _parse_duration_to_seconds(s: str) -> float:
    """Parse '5m', '24h', or '7d' to seconds."""
    m = _DURATION_RE.match(s)
    if not m:
        raise ValueError(f"bad duration: {s!r} (use 5m, 24h, 7d, etc.)")
    n, unit = m.group(1), m.group(2)
    n = int(n)
    if unit == "m":
        return n * 60
    if unit == "h":
        return n * 3600
    if unit == "d":
        return n * 86400
    raise ValueError(f"bad unit: {unit}")


def list_records(
    *,
    role: str = "messenger",
    last: Optional[str] = None,
    status: Optional[str] = None,
    god: Optional[str] = None,
    limit: Optional[int] = None,
    audit_dir: str = DEFAULT_AUDIT_DIR,
) -> list[dict]:
    """Read records, filter, return list. Most recent first."""
    out: list[dict] = []
    cutoff_ts: Optional[float] = None
    if last:
        cutoff_ts = time.time() - _parse_duration_to_seconds(last)
    for path in _iter_files(role, audit_dir):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if status and rec.get("status") != status:
                        continue
                    if god and rec.get("target_god") != god:
                        continue
                    if cutoff_ts is not None:
                        # ts is "2026-06-11T05:30:00Z" — parse to epoch
                        try:
                            rec_ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00")).timestamp()
                        except (ValueError, KeyError):
                            continue
                        if rec_ts < cutoff_ts:
                            continue
                    out.append(rec)
                    if limit and len(out) >= limit:
                        return out
        except OSError as e:
            log.warning(f"could not read {path}: {e}")
    return out


def summary(
    *,
    role: str = "messenger",
    days: int = 7,
    audit_dir: str = DEFAULT_AUDIT_DIR,
) -> dict:
    """Return counts by status, top gods, total calls, avg duration."""
    cutoff_ts = time.time() - days * 86400
    by_status: dict[str, int] = {}
    by_god: dict[str, int] = {}
    by_from_instance: dict[str, int] = {}
    total_calls = 0
    total_duration = 0.0
    rate_limited = 0
    errors = 0
    for path in _iter_files(role, audit_dir):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    try:
                        rec_ts = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00")).timestamp()
                    except (ValueError, KeyError):
                        continue
                    if rec_ts < cutoff_ts:
                        continue
                    total_calls += 1
                    total_duration += rec.get("duration_seconds", 0.0)
                    s = rec.get("status", "unknown")
                    by_status[s] = by_status.get(s, 0) + 1
                    if s == "rate_limited":
                        rate_limited += 1
                    elif s == "error":
                        errors += 1
                    g = rec.get("target_god", "unknown")
                    by_god[g] = by_god.get(g, 0) + 1
                    inst = rec.get("from_instance", "unknown")
                    by_from_instance[inst] = by_from_instance.get(inst, 0) + 1
        except OSError:
            continue
    return {
        "role": role,
        "days": days,
        "total_calls": total_calls,
        "rate_limited": rate_limited,
        "errors": errors,
        "avg_duration_seconds": round(total_duration / total_calls, 2) if total_calls else 0.0,
        "by_status": by_status,
        "top_gods": sorted(by_god.items(), key=lambda kv: -kv[1])[:10],
        "top_caller_instances": sorted(by_from_instance.items(), key=lambda kv: -kv[1])[:10],
    }


def total_size(audit_dir: str = DEFAULT_AUDIT_DIR) -> int:
    d = Path(audit_dir)
    if not d.exists():
        return 0
    return sum(p.stat().st_size for p in d.glob("*.jsonl"))


# ----- CLI ------------------------------------------------------------------

def _format_record_human(rec: dict) -> str:
    ts = rec.get("ts", "?")
    rid = rec.get("request_id", "?")[:8]
    fi = rec.get("from_instance", "?")
    fg = rec.get("from_god", "?")
    tg = rec.get("target_god", "?")
    ti = rec.get("target_instance", "?")
    pl = rec.get("prompt_len", 0)
    rl = rec.get("response_len", 0)
    dur = rec.get("duration_seconds", 0.0)
    st = rec.get("status", "?")
    extra = ""
    if rec.get("error"):
        extra = f" err={rec['error'][:60]!r}"
    if rec.get("retry_after_seconds") is not None:
        extra += f" retry={rec['retry_after_seconds']}s"
    return (f"{ts}  {rid}  {fi}:{fg} -> {tg}@{ti}  "
            f"in={pl}/out={rl}  {dur:.1f}s  {st}{extra}")


def cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Clawforge Audit (v0.4.0)")
    p.add_argument("--audit-dir", default=DEFAULT_AUDIT_DIR)
    sub = p.add_subparsers(dest="cmd", required=True)

    p_sum = sub.add_parser("summary", help="aggregate stats for a window")
    p_sum.add_argument("--role", choices=["messenger", "ask"], default="messenger")
    p_sum.add_argument("--days", type=int, default=7)

    p_list = sub.add_parser("list", help="list recent records")
    p_list.add_argument("--role", choices=["messenger", "ask"], default="messenger")
    p_list.add_argument("--last", default=None, help="time window, e.g. 24h, 7d")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.add_argument("--status", choices=["ok", "rate_limited", "error", "timeout"])
    p_list.add_argument("--god", help="filter by target_god")
    p_list.add_argument("--json", action="store_true", help="output raw JSON")

    p_size = sub.add_parser("size", help="total size of audit dir in bytes")

    args = p.parse_args(argv)

    if args.cmd == "summary":
        s = summary(role=args.role, days=args.days, audit_dir=args.audit_dir)
        print(json.dumps(s, indent=2))
        return 0
    if args.cmd == "list":
        recs = list_records(
            role=args.role, last=args.last, status=args.status,
            god=args.god, limit=args.limit, audit_dir=args.audit_dir,
        )
        if args.json:
            print(json.dumps(recs, indent=2))
        else:
            for r in recs:
                print(_format_record_human(r))
        return 0
    if args.cmd == "size":
        print(total_size(args.audit_dir))
        return 0
    return 1


# ----- Self-test ------------------------------------------------------------

def _selftest():
    import tempfile, shutil
    tmp = tempfile.mkdtemp(prefix="clawforge-audit-test-")
    try:
        w = AuditWriter("messenger", audit_dir=tmp)
        w.write(make_record(
            request_id="abc-1", from_instance="konan", from_god="cli",
            target_god="iris", target_instance="konan",
            prompt_len=10, response_len=200, duration_seconds=2.5,
            status="ok",
        ))
        w.write(make_record(
            request_id="abc-2", from_instance="konan", from_god="cli",
            target_god="iris", target_instance="konan",
            prompt_len=5, response_len=0, duration_seconds=0.0,
            status="rate_limited", retry_after_seconds=1.0,
        ))
        w.write(make_record(
            request_id="abc-3", from_instance="konan", from_god="cli",
            target_god="marvin", target_instance="konan",
            prompt_len=20, response_len=0, duration_seconds=30.0,
            status="timeout",
        ))
        w.close()
        # Read back
        recs = list_records(role="messenger", audit_dir=tmp)
        assert len(recs) == 3, f"expected 3, got {len(recs)}"
        recs_iris = list_records(role="messenger", god="iris", audit_dir=tmp)
        assert len(recs_iris) == 2, f"expected 2 iris, got {len(recs_iris)}"
        recs_rl = list_records(role="messenger", status="rate_limited", audit_dir=tmp)
        assert len(recs_rl) == 1, f"expected 1 rate_limited, got {len(recs_rl)}"
        s = summary(role="messenger", days=1, audit_dir=tmp)
        assert s["total_calls"] == 3
        assert s["rate_limited"] == 1
        assert s["errors"] == 0  # timeout is not "error"
        sz = total_size(audit_dir=tmp)
        assert sz > 0
        # Rotation: write a record with a far-future date and confirm a new file
        w2 = AuditWriter("messenger", audit_dir=tmp)
        # Force rotation by directly opening a past-dated file
        w2._open("1999-01-01")
        w2.write(make_record(
            request_id="old", from_instance="konan", from_god="cli",
            target_god="iris", target_instance="konan",
            prompt_len=1, response_len=1, duration_seconds=0.0,
            status="ok",
        ))
        w2.close()
        # Should now have at least 2 files
        files = list(Path(tmp).glob("messenger-*.jsonl"))
        assert len(files) >= 2, f"expected rotation, got {len(files)} files"
        print(f"OK (audit dir: {tmp}, files: {len(files)}, size: {sz}B)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "_selftest":
        _selftest()
    else:
        logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
        sys.exit(cli(sys.argv[1:]))
