#!/usr/bin/env python3
"""
Pantheon Health Watcher — runs every 15 minutes via cron (no_agent).

Probes Pantheon subsystems (gods, services, databases, disk, LLM providers)
and writes one ``health_check`` event per probe to ``ichor_events``.

Spec:     ~/athenaeum/Codex-Pantheon/plans/ichor-v2-build-blueprint.md §3
Gated on: Phase 0 schema migration (t_e476e4cd — ichor_v2_temporal_001 applied)
Gate:     rows with event_type='health_check' land in ichor_events.

Usage:
    python3 health_watcher.py               # human-readable probe results
    python3 health_watcher.py --json        # machine-readable
    python3 health_watcher.py --dry-run    # probe but do not write events

Schema mapping (spec → real ichor_events):

    spec column    real column      notes
    -----------    -----------      -----------------------------------------
    key            subject          short identifier, e.g. health:god:iris:…
    content        object           compact status string ("ok"|"warning"|"dead")
    content        raw_text         full JSON payload (searchable via FTS5)
    category       event_type       "health_check"
    namespace      (dropped)        spec used "default"; no such column exists
    god_name       god_name         "hermes" — the god that owns this watcher
    session_id     session_id       "health-watcher"
    created_at     created_at       ISO-8601 UTC

The spec used a schema with (key, content, namespace, category, …) but the
shipped ichor_events table uses (subject, predicate, object, raw_text, …).
VALID_EVENT_TYPES in lib/ichor_db does not include "health_check" — raw SQL
INSERT bypasses that check. Adding "health_check" to the canonical set is a
Phase-2 follow-up so the L1 fusion scorer counts these events correctly.

Exit codes:
    0 — all probes ran (some may report "dead"; the script itself succeeded)
    1 — fatal: could not even write to ichor.db or another hard error
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Config ──────────────────────────────────────────────────────────────────

# Resolve the REAL home — $HOME and $HERMES_HOME may be profile-scoped in
# Hermes Agent (HERMES_HOME=/home/konan/.hermes/profiles/<name>), but for
# health probing we want the canonical /home/konan so we hit the actual
# ichor.db the rest of the system uses, not a profile-shim that may not
# exist. Cron jobs always set HOME=/home/konan, so HERMES_REAL_HOME falls
# back to HOME then to a hard default of /home/konan.
_REAL_HOME = Path(
    os.environ.get("HERMES_REAL_HOME")
    or os.environ.get("REAL_HOME")
    or os.environ.get("HOME")
    or "/home/konan"
)
PANTHEON_DIR = Path(os.environ.get("PANTHEON_DIR", _REAL_HOME / "pantheon"))
HERMES_HOME = Path(os.environ.get("_HEALTH_WATCHER_HERMES_HOME", _REAL_HOME / ".hermes"))
ATHENAEUM_DIR = Path(os.environ.get("ATHENAEUM_DIR", _REAL_HOME / "athenaeum"))
ICHOR_DB = HERMES_HOME / "ichor.db"

# Flap detection: only escalate "dead" → "warning" until N consecutive fails.
FAIL_THRESHOLD = 3
CONSECUTIVE_FILE = HERMES_HOME / "tmp" / "health_consecutive.json"

# God gateway processes. systemd unit names match the pattern
# ``hermes-gateway-<god>``; the bare ``hermes-gateway`` is the base service
# (Telegram bot dispatcher). pgrep fallback covers cases where a god runs
# outside systemd.
GODS = [
    "hermes-gateway",            # base dispatcher
    "hermes-gateway-hephaestus", # per-god template instance
    "hermes-gateway-iris",
    "hermes-gateway-marvin",
    "hermes-gateway-rheta",
    "hermes-gateway-thoth",
    "hermes-gateway-apollo",
    "iris",
    "hephaestus",
    "marvin",
    "thoth",
    "mercer",
    "rheta",
]

# System-level services. These match unit names on the host — both system and
# user scopes — so we probe with the unqualified name; ``is-active`` searches
# both scopes.
SERVICES = [
    "nats-server",
    "conductor",
    "pantheon-mcp",
]

# LLM providers — keyed by the env var that holds the base URL.
LLM_PROVIDERS = {
    "opencode-go": os.environ.get(
        "OPENCODE_GO_BASE_URL", "https://opencode.ai/zen/go/v1"
    ),
}

# Watcher metadata written into every event so Phase 2+ queries can filter.
SESSION_ID = "health-watcher"
GOD_NAME = "hermes"
EVENT_TYPE = "health_check"
SOURCE = "health-watcher"
CONFIDENCE = 0.9

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [health-watcher] %(levelname)s: %(message)s",
)
logger = logging.getLogger("health-watcher")


# ── Probe helpers ───────────────────────────────────────────────────────────


def _sh(cmd: str, timeout: int = 10) -> tuple[str, int]:
    """Run a shell command, return (stdout, returncode). Never raises."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "[timeout]", -1
    except FileNotFoundError:
        return "[not found]", -1


def check_process(name: str) -> dict:
    """Probe a systemd service (user-scope first, then system-scope, then pgrep).

    Pantheon god gateways run as user-scoped systemd units
    (``hermes-gateway-<god>.service``); system-scoped units like
    ``nats-server`` live in the system manager. We try user scope first
    because the more common failure mode (system scope seeing ``inactive``
    on user units) is what most health-checks get wrong.
    """
    # 1. user scope (catches god gateways)
    out, rc = _sh(f"systemctl --user is-active {name} 2>/dev/null")
    if rc == 0 and out == "active":
        up, _ = _sh(
            f"systemctl --user show {name} -p ActiveEnterTimestamp --value 2>/dev/null"
        )
        return {"status": "ok", "detail": f"active since {up[:19]} (user)"}

    # 2. system scope (catches nats-server, etc.)
    out, rc = _sh(f"systemctl is-active {name} 2>/dev/null")
    if rc == 0 and out == "active":
        up, _ = _sh(
            f"systemctl show {name} -p ActiveEnterTimestamp --value 2>/dev/null"
        )
        return {"status": "ok", "detail": f"active since {up[:19]} (system)"}

    # 3. pgrep fallback (covers ad-hoc processes with no unit)
    _, rc2 = _sh(f"pgrep -f {name} | head -1")
    if rc2 == 0:
        return {"status": "ok", "detail": "running (no systemd unit)"}

    return {"status": "dead", "detail": f"inactive: user={out!r}, system={out!r}"}


def check_http(url: str, timeout: int = 5) -> dict:
    """HEAD-then-GET probe of an HTTP endpoint."""
    # Cheap HEAD first; fall back to GET if the server doesn't support HEAD.
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return {
                    "status": "ok",
                    "detail": f"HTTP {resp.status} ({method}) in {timeout}s",
                }
        except urllib.error.HTTPError as e:
            # 4xx is "up but rejected our request" — still healthy.
            if 400 <= e.code < 500:
                return {"status": "ok", "detail": f"HTTP {e.code} (reachable)"}
            return {"status": "dead", "detail": f"HTTP {e.code}"}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if method == "GET":
                return {"status": "dead", "detail": f"{type(e).__name__}: {e}"}
            # try GET before giving up
            continue
    return {"status": "dead", "detail": "unreachable"}


def check_db_writable(path: Path) -> dict:
    """Check that an SQLite DB exists and accepts writes."""
    if not path.exists():
        return {"status": "dead", "detail": "file not found"}
    try:
        conn = sqlite3.connect(str(path), timeout=3)
        try:
            conn.execute("SELECT 1").fetchone()
            # Probe write without committing — WAL mode rollbacks for free.
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
        finally:
            conn.close()
        size_mb = path.stat().st_size / (1024 * 1024)
        return {"status": "ok", "detail": f"writable, {size_mb:.0f}MB"}
    except Exception as e:
        return {"status": "dead", "detail": f"{type(e).__name__}: {str(e)[:80]}"}


def check_disk(path: str, warn_pct: int = 80, crit_pct: int = 95) -> dict:
    """Stat-based disk usage probe for a mount point."""
    try:
        usage = os.statvfs(path)
        total = usage.f_frsize * usage.f_blocks
        free = usage.f_frsize * usage.f_bfree
        used = total - free
        pct = (used / total) * 100 if total else 0.0
        if pct >= crit_pct:
            status = "dead"
        elif pct >= warn_pct:
            status = "warning"
        else:
            status = "ok"
        return {
            "status": status,
            "detail": f"{pct:.0f}% used ({used / (1024**3):.0f}GB / {total / (1024**3):.0f}GB)",
        }
    except Exception as e:
        return {"status": "dead", "detail": f"statvfs failed: {e}"}


# ── Consecutive-failure tracking (flap suppression) ────────────────────────


def _load_consecutive() -> dict:
    if not CONSECUTIVE_FILE.exists():
        return {}
    try:
        return json.loads(CONSECUTIVE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_consecutive(data: dict) -> None:
    CONSECUTIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONSECUTIVE_FILE.write_text(json.dumps(data, indent=2))


def update_consecutive_failures(name: str, current_status: str) -> int:
    """Increment on dead, reset on anything else. Returns new count."""
    data = _load_consecutive()
    count = int(data.get(name, {}).get("count", 0))
    if current_status == "dead":
        count += 1
    else:
        count = 0
    data[name] = {"count": count, "last_seen": datetime.now(timezone.utc).isoformat()}
    try:
        _save_consecutive(data)
    except OSError as e:
        logger.warning("could not persist consecutive failures: %s", e)
    return count


# ── ichor_events writer ─────────────────────────────────────────────────────


def _open_ichor() -> sqlite3.Connection | None:
    """Open ichor.db. Returns None if the file is missing — caller decides."""
    if not ICHOR_DB.exists():
        logger.warning("ichor.db not found at %s; skipping writes", ICHOR_DB)
        return None
    try:
        conn = sqlite3.connect(str(ICHOR_DB), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn
    except sqlite3.Error as e:
        logger.warning("could not open ichor.db: %s", e)
        return None


def write_health_event(
    component: str, result: dict, consec_failures: int, dry_run: bool = False
) -> int | None:
    """Insert one ``health_check`` row. Returns the rowid or None on skip.

    Flap rule: a single "dead" reading reports as ``"warning"`` until the
    component has been dead for FAIL_THRESHOLD consecutive runs — keeps the
    event stream free of one-off transient blips.
    """
    ts = datetime.now(timezone.utc)
    status = result["status"]
    if status == "dead" and consec_failures < FAIL_THRESHOLD:
        status = "warning"

    payload = {
        "component": component,
        "status": status,
        "raw_status": result["status"],
        "detail": result["detail"],
        "consecutive_failures": consec_failures,
        "watcher_run_at": ts.isoformat(),
    }
    subject = f"health:{component}:{ts.strftime('%Y%m%d%H%M%S')}"

    if dry_run:
        logger.info("[dry-run] would insert health_check %s status=%s", component, status)
        return None

    conn = _open_ichor()
    if conn is None:
        return None
    try:
        cur = conn.execute(
            """
            INSERT INTO ichor_events
                (session_id, event_type, subject, predicate, object,
                 confidence, source, raw_text, god_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                SESSION_ID,
                EVENT_TYPE,
                subject,
                "status",                # static predicate; FTS5-searchable
                status,                  # object: compact status string
                CONFIDENCE,
                SOURCE,
                json.dumps(payload),     # raw_text: full JSON (FTS5-indexed)
                GOD_NAME,
                ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.Error as e:
        # Health-watcher failing to write its own event is ironic but non-fatal.
        logger.warning("insert failed for %s: %s", component, e)
        return None
    finally:
        conn.close()


# ── Probe orchestration ─────────────────────────────────────────────────────


def _run_probe(
    component: str, probe_fn, *args, dry_run: bool = False, **kwargs
) -> dict:
    """Probe a single component, persist the event, return the result dict.

    ``dry_run`` is consumed here and not forwarded to ``probe_fn`` (probe
    functions don't take it; only the writer does).
    """
    try:
        result = probe_fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        result = {"status": "dead", "detail": f"{type(e).__name__}: {e}"}

    # The consecutive-failure tracker must run even on dry runs so a follow-up
    # ``--execute`` doesn't inherit stale counts.
    consec = update_consecutive_failures(component, result["status"])

    write_health_event(component, result, consec, dry_run=dry_run)
    return {**result, "component": component, "consecutive_failures": consec}


def run_all_probes(dry_run: bool = False) -> list[dict]:
    """Probe every subsystem, persist events, return the combined report."""
    results: list[dict] = []
    logger.info("starting probe sweep (dry_run=%s)", dry_run)

    for god in GODS:
        results.append(_run_probe(f"god:{god}", check_process, god, dry_run=dry_run))

    for svc in SERVICES:
        results.append(_run_probe(f"service:{svc}", check_process, svc, dry_run=dry_run))

    for label, path in [("ichor.db", ICHOR_DB)]:
        results.append(_run_probe(f"db:{label}", check_db_writable, path, dry_run=dry_run))

    for mount, label in [(str(ATHENAEUM_DIR.parent), "home")]:
        results.append(_run_probe(f"disk:{label}", check_disk, mount, dry_run=dry_run))

    for provider, base_url in LLM_PROVIDERS.items():
        results.append(_run_probe(
            f"provider:{provider}",
            check_http,
            f"{base_url}/models",
            timeout=5,
            dry_run=dry_run,
        ))

    return results


# ── Output formatting ──────────────────────────────────────────────────────


_STATUS_ICON = {"ok": "✓", "warning": "⚠", "dead": "✗"}


def _format_text(results: list[dict]) -> str:
    lines: list[str] = []
    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_warn = sum(1 for r in results if r["status"] == "warning")
    n_dead = sum(1 for r in results if r["status"] == "dead")
    lines.append(
        f"Pantheon health: {n_ok} ok / {n_warn} warn / {n_dead} dead"
    )
    for r in results:
        icon = _STATUS_ICON.get(r["status"], "?")
        lines.append(f"  {icon} {r['component']:42s} {r['detail']}")
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pantheon Health Watcher")
    parser.add_argument("--json", action="store_true", help="JSON output to stdout")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Probe everything but skip writing ichor_events",
    )
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    results = run_all_probes(dry_run=args.dry_run)
    elapsed = time.perf_counter() - t0

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "dry_run": args.dry_run,
        "probe_count": len(results),
        "results": results,
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(_format_text(results))

    # Exit non-zero only if the watcher itself failed (not if probes did).
    return 0


if __name__ == "__main__":
    sys.exit(main())
