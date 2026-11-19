#!/usr/bin/env python3
"""ichor-health.py — single-pane health monitor for the Ichor memory stack.

WHY THIS EXISTS
    The 2026-09-20 Ichor audit found that every serious defect was a machine
    reporting success while doing nothing: jobs exited 0, logs said
    "completed", and the work did not happen. None of it raised an error.
    Nothing in the fleet would ever have alerted on it.

    This script asserts the *effects* those jobs are supposed to have, so a
    silent no-op shows up as a red line instead of a green one.

DESIGN CONTRACT — "runs the same way every time"
    * HOME is pinned, not inherited. The shell in some contexts expands `~`
      to a sandbox home, which silently points every probe at the wrong tree.
    * Absolute paths only. No dependence on cwd.
    * Fixed queries, fixed thresholds, fixed output order.
    * Read-only. It never writes to ichor.db, state.db, or any config.
    * No sampling. Every count is exact.

USAGE
    python3 ichor-health.py              # human report
    python3 ichor-health.py --json       # machine report
    python3 ichor-health.py --deep       # + live tier probe (imports the provider)
    python3 ichor-health.py --quiet      # print only when something is wrong

EXIT CODES
    0  all checks pass
    1  warnings (degraded, not broken)
    2  critical (data loss or total feature failure in progress)

Recommended cron:  0 */6 * * *   (exit code drives the alert; no LLM needed)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
# `time` backs the delivery check's freshness test: messages.timestamp is an
# epoch float, and SQLite will not compare a REAL against a datetime string, so
# the age calculation has to happen in Python.
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── pinned environment (do NOT inherit HOME) ────────────────────────────
HOME = Path("/home/konan")
os.environ["HOME"] = str(HOME)

HERMES = HOME / ".hermes"
ICHOR_DB = HERMES / "ichor.db"
STATE_DB = HERMES / "state.db"
PROFILES = HERMES / "profiles"
LIVE_TREE = HERMES / "runtimes" / "fleet" / "hermes-agent"
PLUGIN = HERMES / "plugins" / "ichor" / "provider.py"
PANTHEON_ROOT = Path(__file__).resolve().parent.parent
PANTHEON = HOME / "pantheon"

OK, WARN, CRIT = "ok", "warn", "crit"
_ICON = {OK: "  ok ", WARN: " WARN", CRIT: " CRIT"}

# Thresholds — fixed constants, not tuned per run.
FENCE = "<memory-context>"
HOLLOW_BODY_CHARS = 20          # a body shorter than this carries no content

# delivery check scope.
#
# The store is append-only history: once a block was written hollow, no fix can
# repair it, and every historical row stays hollow forever. Judging the
# accumulated rows keeps the check red long after a repair, which is exactly the
# alert-fatigue failure mode this script exists to prevent.
#
# So the VERDICT comes from the NEWEST block, and everything else is context:
#   * the newest row is the only one that reflects the code the RUNNING process
#     is executing -- and it is also the row that tracks the activation
#     boundary, because editing provider.py changes nothing until the gateway
#     holding the old module in memory restarts;
#   * RECENT_WINDOW recent rows and the all-time count are reported in `data`
#     and in the detail string, but never set the level. A ratio over a rolling
#     window cannot distinguish "current behaviour" from "history draining out
#     of the window": with 183 legacy hollow rows on disk, a 50% threshold would
#     stay CRIT for hundreds of turns after the mechanism was repaired.
#   * DELIVERY_STALE_MINUTES separates "no evidence -- the fleet has been quiet"
#     (WARN) from "a fresh block just arrived hollow" (CRIT).
DELIVERY_STALE_MINUTES = 24 * 60
RECENT_WINDOW = 200             # fenced rows fetched as CONTEXT for the verdict
# The eviction cutoff is READ FROM THE SHIPPED MODULE, never re-typed here.
# A duplicated threshold is exactly how the original defect survived review:
# the job ran `importance < 0.1` while every reader assumed a sane number, and
# this monitor's own "correct" value was a third opinion nobody was using.
# `_configured_eviction_cutoff()` resolves what the job will actually execute;
# the literal below is only the fallback for a tree where the import fails.
EVICTION_THRESHOLD_FALLBACK = 40.0
EVICTION_AGE_DAYS_FALLBACK = 90
FROZEN_DAYS = 30                # a producer silent this long is suspect
CRON_LOOKBACK = 40              # executions examined per job
EXPECTED_TIER_TABLES = {
    "memory_fts": "T1 FTS5 index",
    "warm_entities": "T2 warm entity store",
    "warm_entities_fts": "T2 warm FTS index",
    "relationships": "T3 graph edges",
    "ichor_observations": "observations lane",
}

# Tables designed but never written (verified 2026-09-20: no INSERT caller in lib/ or scripts/)
KNOWN_EMPTY_TABLES = [
    "ichor_knowledge_pages",
    "ichor_knowledge_page_versions",
    "ichor_cold_storage",
    "ichor_claim_entities",
    "hot_state",
    "episodic_folds",
    "archive_retired",
]

# (table, timestamp column) pairs for the frozen-producer check.
FROZEN_WATCH = [
    ("entity_facts", "created_at"),
    ("ichor_claims", "created_at"),
    ("ichor_claim_evidence", "created_at"),
    # recall_log's timestamp column is `retrieved_at`, not `created_at`. With the
    # wrong column name the frozen check degraded to age_days=None, and the stale
    # filter below requires age_days is not None -- so recall_log was structurally
    # incapable of ever raising the alarm while still sitting in this watch list,
    # which is how it stayed silent for 46 days (9 rows, newest 2026-08-07)
    # without a single WARN. Keep this name in step with the table's schema.
    ("recall_log", "retrieved_at"),
    ("strategic_goals", "created_at"),
    ("reference_knowledge", "created_at"),
    ("relationships", "created_at"),
    ("ichor_events", "created_at"),
    ("ichor_observations", "created_at"),
]


class Result:
    """One check outcome."""

    __slots__ = ("name", "level", "detail", "data")

    def __init__(self, name: str, level: str, detail: str, data=None):
        self.name = name
        self.level = level
        self.detail = detail
        self.data = data if data is not None else {}

    def as_dict(self) -> dict:
        return {"check": self.name, "level": self.level, "detail": self.detail, "data": self.data}


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def scalar(conn: sqlite3.Connection, sql: str, params=()):
    try:
        row = conn.execute(sql, params).fetchone()
        return None if row is None else row[0]
    except sqlite3.Error:
        return None


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    except sqlite3.Error:
        return False
    return column in cols


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return scalar(
        conn, "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", (table,)
    ) is not None


# ── 1. which Hermes tree is actually running ────────────────────────────
def check_trees() -> Result:
    """The fleet runs from ONE tree; several others exist and look plausible."""
    trees = [
        ("live (fleet runtime)", LIVE_TREE),
        ("staged upgrade (.new)", HERMES / "runtimes" / "fleet" / "hermes-agent.new"),
        ("entrypoint tree", HERMES / "hermes-agent"),
        ("ichor canary", HERMES / "runtimes" / "ichor-canary" / "hermes-agent"),
        ("pantheon checkout", PANTHEON / "hermes-agent"),
    ]
    found, live_version = [], None
    for label, path in trees:
        init = path / "hermes_cli" / "__init__.py"
        if not init.is_file():
            continue
        version = None
        for line in init.read_text(errors="replace").splitlines():
            if line.startswith("__version__"):
                # Guard: a bare `__version__` line (annotation or re-export with
                # no `=`) would otherwise raise IndexError on split("=", 1)[1].
                # Seen live 2026-10-08 after a `hermes_cli/__init__.py` shape
                # change — this crashed `check_trees` on every run since 10-05.
                if "=" in line:
                    version = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
        found.append({"label": label, "path": str(path), "version": version})
        if path == LIVE_TREE:
            live_version = version

    ### Which tree does the fleet actually resolve? Ask it the fleet's way.
    #
    # Two probes, because the naive one lies:
    #
    #   * "installed" — bare interpreter, PYTHONPATH cleared, cwd=/. On this host
    #     that resolves hermes_cli to `~/.hermes/hermes-agent` (0.21.1), the
    #     STAGED upgrade, because hermes-agent is pip-installed from there.
    #     Reproduce:
    #         env -u PYTHONPATH /usr/local/lib/hermes-agent/venv/bin/python3 \
    #             -c "import hermes_cli, os; print(os.path.dirname(os.path.dirname(hermes_cli.__file__)))"
    #     That answer says nothing about what the fleet executes, and treating it
    #     as CRIT pinned this check red on every run while the fleet was in fact
    #     correctly pinned. A monitor that always cries wolf gets ignored — that
    #     is the failure mode this whole script exists to avoid.
    #
    #   * "fleet" — the same interpreter with PYTHONPATH=<live tree> and cwd at
    #     the live tree, which is exactly how the running gateway processes are
    #     configured. Verified against `/proc/<pid>/environ` and
    #     `/proc/<pid>/cwd` on 2026-09-20: every god gateway carries
    #     PYTHONPATH=/home/konan/.hermes/runtimes/fleet/hermes-agent.
    #
    # VERDICT = the "fleet" probe. The "installed" resolution is context only:
    # it is the staged-upgrade skew already surfaced by the version list above.
    def _resolve_hermes_cli(extra_env=None, cwd=None):
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        if extra_env:
            env.update(extra_env)
        try:
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import hermes_cli,os;print(os.path.dirname(os.path.dirname(hermes_cli.__file__)))"],
                capture_output=True, text=True, timeout=30, env=env, cwd=cwd,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        return proc.stdout.strip() if proc.returncode == 0 else None

    # cwd="/" on the installed probe: without it, running this script from
    # ~/pantheon puts pantheon's stub `hermes_cli` first on the interpreter's
    # path (cwd is sys.path[0]) and the report claims the installed resolution
    # is pantheon. The module contract is "absolute paths only, no dependence on
    # cwd" -- and a monitor whose verdict moves with the operator's cwd is worse
    # than no monitor.
    resolved = _resolve_hermes_cli(cwd="/")
    fleet_resolved = _resolve_hermes_cli({"PYTHONPATH": str(LIVE_TREE)}, cwd=str(LIVE_TREE))

    if live_version is None:
        return Result("trees", CRIT, "live fleet tree not found", {"trees": found})

    detail = f"live={live_version} at {LIVE_TREE.name}; {len(found)} trees on disk"
    level = OK
    notes = []
    for t in found:
        if t["path"] == str(LIVE_TREE):
            continue
        if t["version"] and t["version"] != live_version:
            notes.append(f"{t['label']}={t['version']}")
    if notes:
        level = WARN
        detail += f"; skew: {', '.join(notes)}"

    # ── verdict: the fleet-configured resolution, not the installed one ────
    #
    # This is the line that decides red/green. Only a failure of the "fleet"
    # probe means the fleet is executing something other than the live tree;
    # a differing "installed" resolution is the staged 0.21.1 upgrade already
    # reported by `skew:` above, so it is appended as context and never sets the
    # level. (Getting this backwards is what made the original check report CRIT
    # on every run: the installed copy resolves elsewhere BY DESIGN here.)
    if fleet_resolved and fleet_resolved != str(LIVE_TREE):
        level = CRIT
        detail += (f"; FLEET RUNTIME RESOLVES ELSEWHERE: {fleet_resolved} — "
                   f"the fleet's own PYTHONPATH/cwd no longer pins the live tree")
    if resolved and resolved != str(LIVE_TREE):
        detail += (f"; installed resolution={resolved} "
                   f"(staged/installed copy — skew, not a misconfiguration)")

    return Result("trees", level, detail,
                  {"trees": found,
                   "resolved_by_interpreter": resolved,
                   "resolved_by_fleet_path": fleet_resolved,
                   "live_version": live_version})


# ── 2. is a top-level Hermes package shadowed by pantheon? ──────────────
def check_shadow() -> Result:
    """`~/pantheon` is prepended to sys.path by the ichor plugin. If pantheon also
    defines a top-level package name that Hermes owns, pantheon wins -- and any
    module the real package has but the pantheon copy lacks becomes unimportable.

    The dangerous case is a *smaller* pantheon copy (a partial stub). A *larger*
    one is the intended provider for that namespace (e.g. `lib`, which is
    Pantheon's own and has no Hermes equivalent) and is not a collision.

    Confirmed 2026-09-20: pantheon/hermes_cli holds 4 modules against the real
    189. With pantheon at sys.path[0], `hermes_cli.config`, `hermes_cli.auth` and
    `hermes_cli._subprocess_compat` all raise ModuleNotFoundError.
    """
    collisions = []
    for name in ("hermes_cli", "plugins", "agent", "lib", "tools", "config"):
        fleet_dir = LIVE_TREE / name
        pant_dir = PANTHEON / name
        if not (fleet_dir.is_dir() and pant_dir.is_dir()):
            continue
        fleet_entries = len(list(fleet_dir.iterdir()))
        pant_entries = len(list(pant_dir.iterdir()))
        collisions.append({
            "package": name,
            "fleet_entries": fleet_entries,
            "pantheon_entries": pant_entries,
            "pantheon_is_stub": pant_entries < fleet_entries,
        })
    if not collisions:
        return Result("shadow", OK, "no top-level package collisions", {"collisions": []})

    # Entry counts are EVIDENCE, not a verdict. A smaller pantheon package is
    # only a defect if it actually hides the real one, so probe the EFFECT: with
    # pantheon first on sys.path, does a real submodule still import?
    #
    # Before 2026-09-21 this check reported "STUB SHADOWS REAL" for hermes_cli
    # purely on 5-vs-189, while the stub had been rewritten to extend the real
    # package's __path__. The effect probe is the same correction the delivery
    # check needed: grade behaviour, not the shape that usually implies it.
    for collision in collisions:
        collision["effect"] = _probe_collision_effect(
            collision["package"], _REPRESENTATIVE_SUBMODULE.get(collision["package"])
        )

    shadowed = [
        c for c in collisions
        if c["effect"].get("submodule_error") and c["pantheon_is_stub"]
    ]
    extended = [
        c for c in collisions
        if c["pantheon_is_stub"] and not c["effect"].get("submodule_error")
        and c["effect"].get("submodule")
    ]
    level = WARN if shadowed else OK
    parts = []
    for c in collisions:
        if not c["pantheon_is_stub"]:
            parts.append(f"{c['package']} ({c['pantheon_entries']} vs "
                         f"{c['fleet_entries']} entries, pantheon owns it)")
        elif c["effect"].get("submodule_error"):
            parts.append(f"{c['package']} ({c['pantheon_entries']} vs "
                         f"{c['fleet_entries']} entries, SHADOWS REAL: "
                         f"{c['effect']['submodule_error']})")
        else:
            parts.append(f"{c['package']} ({c['pantheon_entries']} vs "
                         f"{c['fleet_entries']} entries, extends the real package: "
                         f"real={c['effect'].get('version') or '?'} via __path__)")
    return Result("shadow", level, "; ".join(parts), {"collisions": collisions})


# Representative real submodule per colliding package: something the pantheon
# copy does NOT define, so a successful import proves the real package is still
# reachable. `None` means "no probe" (nothing safe to name).
_REPRESENTATIVE_SUBMODULE = {
    "hermes_cli": "hermes_cli.config",
    "tools": "tools.registry",
    "plugins": "plugins.kanban",
}

_COLLISION_PROBE = """
import json, sys
sys.path.insert(0, {pantheon!r})
out = {{"package": {package!r}, "submodule": {submodule!r}}}
try:
    module = __import__({package!r})
    out["file"] = getattr(module, "__file__", None)
    out["version"] = getattr(module, "__version__", None)
    out["path"] = list(getattr(module, "__path__", []) or [])
except Exception as exc:
    out["import_error"] = f"{{type(exc).__name__}}: {{exc}}"
if {submodule!r}:
    try:
        __import__({submodule!r})
        out["submodule_ok"] = True
    except Exception as exc:
        out["submodule_error"] = f"{{type(exc).__name__}}: {{exc}}"
print(json.dumps(out))
"""


def _probe_collision_effect(package: str, submodule: str | None) -> dict:
    """Import `package` with pantheon first, in a subprocess, and report reality."""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _COLLISION_PROBE.format(
                pantheon=str(PANTHEON), package=package, submodule=submodule or "",
            )],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    if proc.returncode != 0:
        return {"error": f"probe exited {proc.returncode}: {proc.stderr.strip()[:200]}"}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": f"unparseable probe output: {proc.stdout[:200]}"}


# ── 3. storage inventory ────────────────────────────────────────────────
def check_storage() -> Result:
    if not ICHOR_DB.is_file():
        return Result("storage", CRIT, f"ichor.db missing at {ICHOR_DB}")
    size_gb = ICHOR_DB.stat().st_size / (1024 ** 3)
    conn = connect(ICHOR_DB)
    try:
        counts = {}
        for table, why in EXPECTED_TIER_TABLES.items():
            n = scalar(conn, f"SELECT COUNT(*) FROM {table}") if table_exists(conn, table) else None
            counts[table] = {"rows": n, "why": why}
    finally:
        conn.close()

    missing = [t for t, v in counts.items() if v["rows"] is None]
    empty = [t for t, v in counts.items() if v["rows"] == 0]
    level = OK
    if missing:
        level = CRIT
    elif empty:
        level = WARN
    detail = f"{size_gb:.2f} GB; " + ", ".join(
        f"{t}={v['rows']}" for t, v in counts.items()
    )
    if missing:
        detail += f"; MISSING TABLES: {', '.join(missing)}"
    return Result("storage", level, detail, {"size_gb": round(size_gb, 3), "tables": counts})


# ── 4. THE CRITICAL ONE: does recalled memory actually reach the model? ─
def check_delivery() -> Result:
    """Ichor self-wraps its output in <memory-context>. Hermes' sanitize_context()
    strips that fence INCLUDING its interior, so a self-wrapped payload arrives
    empty. This is the check that would have caught it on day one.

    Measured 2026-09-20 before the fix: 174/174 fenced blocks hollow, 0 payload.

    WHY THE VERDICT IS THE NEWEST BLOCK, NOT A RATIO
        The store is append-only. Once the provider is fixed, every historical
        row stays hollow forever -- nothing rewrites them -- so a ratio over a
        rolling window measures "history draining out of the window", not current
        behaviour. With 183 legacy hollow rows on disk, a 50% threshold stays CRIT
        for hundreds of turns after the mechanism is repaired.
        The newest row is the only one that reflects the code the RUNNING process
        is executing, so it decides the level; the recent window and the all-time
        count ride along in `data` as context.
        It is also the row that tracks the ACTIVATION boundary: editing
        provider.py on disk changes nothing until the gateway holding the old
        module in memory restarts, and a hollow newest block proves exactly that.
    """
    if not STATE_DB.is_file():
        return Result("delivery", CRIT, f"state.db missing at {STATE_DB}")
    conn = connect(STATE_DB)
    try:
        if not table_exists(conn, "messages") or not has_column(conn, "messages", "api_content"):
            return Result("delivery", WARN, "messages.api_content not present")
        recent_rows = conn.execute(
            "SELECT api_content, timestamp FROM messages "
            "WHERE api_content IS NOT NULL AND api_content LIKE ? "
            "ORDER BY id DESC LIMIT ?",
            (f"%{FENCE}%", RECENT_WINDOW),
        ).fetchall()
        all_time_total = scalar(
            conn, "SELECT COUNT(*) FROM messages WHERE api_content IS NOT NULL AND api_content LIKE ?",
            (f"%{FENCE}%",),
        ) or 0
    finally:
        conn.close()

    def classify(rows) -> tuple:
        """Return (hollow, with_payload) for a set of api_content rows."""
        hollow = with_payload = 0
        for r in rows:
            text = r["api_content"] or ""
            # Strip the fence, then strip the WHOLE `[System note: ...]` line.
            #
            # The system note is Hermes' own wrapper text, not recalled payload.
            # Counting it as payload is precisely how a hollow block reports as
            # healthy -- the first revision of this check did that and announced
            # "175/175 fenced blocks carry payload" against a store where the
            # audit had proven 174/174 hollow. A monitor that lies about its most
            # important check is worse than no monitor.
            body = text
            start = body.find(FENCE)
            end = body.find("</memory-context>")
            if start != -1 and end > start:
                body = body[start + len(FENCE):end]
            body = body.strip()
            if body.startswith("[System note:"):
                close = body.find("]")
                body = body[close + 1:] if close != -1 else ""
            body = body.strip()
            if len(body) < HOLLOW_BODY_CHARS:
                hollow += 1
            else:
                with_payload += 1
        return hollow, with_payload

    hollow, with_payload = classify(recent_rows)
    total = len(recent_rows)
    newest_hollow, newest_with_payload = classify(recent_rows[:1])

    # Age of the newest block, in minutes.
    #
    # messages.timestamp is an EPOCH FLOAT, not a datetime string: comparing it
    # with `datetime('now', '-2 hours')` compares a real to a text and silently
    # matches nothing (measured: 0 rows for every window tried, while the newest
    # fenced row was four minutes old). Do the comparison in Python.
    age_minutes = None
    if recent_rows and recent_rows[0]["timestamp"]:
        try:
            age_minutes = int((time.time() - float(recent_rows[0]["timestamp"])) // 60)
        except (TypeError, ValueError):
            age_minutes = None

    data = {
        "recent_window": RECENT_WINDOW,
        "recent_fenced": total,
        "recent_hollow": hollow,
        "recent_with_payload": with_payload,
        "newest_block_hollow": bool(newest_hollow),
        "newest_block_age_minutes": age_minutes,
        "all_time_fenced": all_time_total,
    }

    if total == 0:
        return Result("delivery", WARN,
                      f"no fenced memory blocks in the last {RECENT_WINDOW} rows "
                      f"({all_time_total} all-time)",
                      data)

    # ── verdict: the newest block only ─────────────────────────────────────
    if newest_with_payload:
        return Result("delivery", OK,
                      f"newest block carries payload — delivery is working "
                      f"(context: {with_payload}/{total} of the last {RECENT_WINDOW} rows, "
                      f"all-time {all_time_total} fenced; pre-fix rows stay hollow forever)",
                      data)

    if age_minutes is not None and age_minutes > DELIVERY_STALE_MINUTES:
        return Result("delivery", WARN,
                      f"nothing fresh to judge: newest fenced block is "
                      f"{age_minutes // 60}h old and hollow "
                      f"(recent {hollow}/{total} hollow, all-time {all_time_total} fenced)",
                      data)

    return Result("delivery", CRIT,
                  f"NEWEST fenced block is HOLLOW — recalled memory is STILL being "
                  f"stripped by the running process (recent {hollow}/{total} hollow, "
                  f"all-time {all_time_total} fenced). Fixing provider.py is not enough "
                  f"on its own: restart the gateway, which holds the old module in memory",
                  data)


# ── 5. does auto-eviction's predicate match anything? ───────────────────
def _configured_eviction_cutoff() -> tuple[float, int, str]:
    """Resolve the eviction predicate the job will ACTUALLY execute.

    Returns (importance_cutoff, age_days, source). The source string is surfaced
    in the report so a reader can tell "the job changed" from "the monitor
    changed" -- drift between those two is the failure this whole check is for.
    """
    try:
        root = str(PANTHEON_ROOT)
        saved_path = list(sys.path)
        try:
            if root not in sys.path:
                sys.path.insert(0, root)
            from lib.ichor_eviction import CUTOFF_DAYS, CUTOFF_IMPORTANCE  # type: ignore
        finally:
            # Restore the path exactly: this module is a read-only reporter, and
            # leaving pantheon at sys.path[0] would change how every LATER check
            # resolves top-level packages (`hermes_cli` above all).
            sys.path[:] = saved_path

        return float(CUTOFF_IMPORTANCE), int(CUTOFF_DAYS), "lib/ichor_eviction.py"
    except Exception as exc:  # pragma: no cover - defensive
        return (
            float(EVICTION_THRESHOLD_FALLBACK),
            int(EVICTION_AGE_DAYS_FALLBACK),
            f"fallback constant ({type(exc).__name__})",
        )


def _eviction_predicate_sql(age_bound: str = "datetime('now', ?)") -> str:
    """The eligibility predicate, imported from the job that executes it.

    A monitor that keeps its own copy of a predicate can silently grade a job it
    no longer describes -- that drift is how `importance < 0.1` against a 0-100
    column stayed green for months. So the SQL comes from the shipped builder in
    `lib/ichor_eviction.py`; the literal fallback is the IDENTICAL expression and
    exists only for the case where the import itself fails.

    `age_bound` is the normalised right-hand side: the monitor uses a relative
    `datetime('now', ?)` modifier while the job uses an absolute `datetime(?)`.
    Either way `created_at` is normalised before comparison -- see
    `lib.ichor_temporal.CREATED_AT_SHAPES` for why the raw column cannot be
    compared to a differently-shaped literal.
    """
    try:
        root = str(PANTHEON_ROOT)
        saved_path = list(sys.path)
        try:
            if root not in sys.path:
                sys.path.insert(0, root)
            from lib.ichor_eviction import eligibility_sql  # type: ignore
        finally:
            sys.path[:] = saved_path
        return eligibility_sql(age_bound)
    except Exception:  # pragma: no cover - defensive
        return f"importance < ? AND datetime(created_at) < {age_bound}"


def check_eviction() -> Result:
    """Does the auto-eviction predicate match anything, ever?

    A predicate that matches zero rows is indistinguishable from a healthy idle
    job -- it exits 0 either way and no alert can fire.

    Measured 2026-09-20: `importance < 0.1` matched 0 of 1,813,406 rows, because
    `ichor_events.importance` is on a 0-100 scale (schema DEFAULT 50.0,
    observed values 27.6 / 45.2). `ichor_cold_storage` was empty by defect, not
    by design, and the job had reported success on 8 of 8 runs. A second layer
    sat underneath it: 88% of rows shared one seeded value, so no threshold
    could discriminate at all.

    Fixed 2026-09-21: the cutoff is 40.0 in `lib/ichor_eviction.py` (this check
    imports it rather than restating it), the 1.81M duplicated rows were
    deduped, and the modal share fell to 40.2% -- below the degeneracy line, so
    the signal can be thresholded again.

    Two distinct failures are graded here:
      * FLAT signal (modal share > 50%) -- no constant can work; CRIT.
      * DEAD predicate (matches 0 rows) -- the silent no-op; CRIT.
    An eligible-but-unarchived backlog is WARN: the predicate matches, but
    nothing has been moved, which means the caller is not running.
    """
    if not ICHOR_DB.is_file():
        return Result("eviction", CRIT, "ichor.db missing")
    configured, age_days, cutoff_source = _configured_eviction_cutoff()
    conn = connect(ICHOR_DB)
    try:
        if not table_exists(conn, "ichor_events"):
            return Result("eviction", WARN, "ichor_events missing")
        total = scalar(conn, "SELECT COUNT(*) FROM ichor_events") or 0
        lo = scalar(conn, "SELECT MIN(importance) FROM ichor_events")
        hi = scalar(conn, "SELECT MAX(importance) FROM ichor_events")
        avg = scalar(conn, "SELECT AVG(importance) FROM ichor_events")
        cold = scalar(conn, "SELECT COUNT(*) FROM ichor_cold_storage") \
            if table_exists(conn, "ichor_cold_storage") else None
        n_configured = scalar(
            conn, "SELECT COUNT(*) FROM ichor_events WHERE importance < ?",
            (configured,),
        )
        n_eligible = scalar(
            conn, "SELECT COUNT(*) FROM ichor_events WHERE "
                  + _eviction_predicate_sql("datetime('now', ?)"),
            (configured, f"-{age_days} days"),
        )
        n_eligible_at_fallback = scalar(
            conn, "SELECT COUNT(*) FROM ichor_events WHERE "
                  + _eviction_predicate_sql("datetime('now', ?)"),
            (EVICTION_THRESHOLD_FALLBACK, f"-{EVICTION_AGE_DAYS_FALLBACK} days"),
        )
    finally:
        conn.close()

    data = {
        "events": total, "importance_min": lo, "importance_max": hi,
        "importance_avg": None if avg is None else round(avg, 3),
        "cold_storage_rows": cold,
        "configured_cutoff": configured,
        "configured_age_days": age_days,
        "cutoff_source": cutoff_source,
        "rows_below_configured_cutoff": n_configured,
        "rows_eligible_now": n_eligible,
    }
    if total == 0:
        return Result("eviction", WARN, "ichor_events is empty", data)

    # Degeneracy check.
    #
    # If most rows share one value, NO threshold can discriminate between them,
    # and "fix the constant" just produces a second silent no-op. That is exactly
    # what happened on 2026-09-20: the first recommendation was 0.1 -> 10.0, and
    # 10.0 also matched zero rows on a column where p5..p90 were all the single
    # seeded value 49.50125.
    conn = connect(ICHOR_DB)
    try:
        modal = conn.execute(
            "SELECT importance, COUNT(*) c FROM ichor_events "
            "GROUP BY importance ORDER BY c DESC LIMIT 1"
        ).fetchone()
        n_modal = modal["c"] if modal else 0
        modal_value = modal["importance"] if modal else None
    finally:
        conn.close()
    modal_share = (n_modal / total) if total else 0.0
    data.update({
        "modal_importance": modal_value,
        "modal_share": round(modal_share, 4),
        "rows_eligible_at_40_and_90d": n_eligible_at_fallback,
    })
    if modal_share > 0.5:
        return Result(
            "eviction", CRIT,
            f"importance SIGNAL IS DEGENERATE: {modal_share:.0%} of rows share the single "
            f"value {modal_value} - no threshold can discriminate, so changing the "
            f"constant alone yields a second silent no-op "
            f"(configured {configured:g} gives {n_configured} rows, "
            f"<40 AND older than 90d gives {n_eligible_at_fallback:,})",
            data,
        )
    if not n_configured:
        return Result(
            "eviction", CRIT,
            f"EVICTION PREDICATE MATCHES NOTHING: configured cutoff {configured:g} "
            f"(from {cutoff_source}) matches 0 of {total:,} rows on a "
            f"{lo:.1f}-{hi:.1f} scale - the job exits 0 and archives nothing, forever",
            data,
        )
    if not cold and n_eligible:
        return Result(
            "eviction", WARN,
            f"predicate matches {n_configured:,} rows but nothing was archived: "
            f"{n_eligible:,} rows are eligible (<{configured:g} and older than "
            f"{age_days}d) and cold_storage is empty - the caller is not running",
            data,
        )
    return Result(
        "eviction", OK,
        f"cutoff {configured:g} from {cutoff_source} matches {n_configured:,} rows "
        f"({n_eligible:,} eligible now); cold_storage={cold}",
        data,
    )


def check_empty_tables() -> Result:
    if not ICHOR_DB.is_file():
        return Result("empty_tables", CRIT, "ichor.db missing")
    conn = connect(ICHOR_DB)
    try:
        rows = {}
        for t in KNOWN_EMPTY_TABLES:
            rows[t] = scalar(conn, f"SELECT COUNT(*) FROM {t}") if table_exists(conn, t) else None
    finally:
        conn.close()
    still_empty = [t for t, n in rows.items() if n == 0]
    filled = [t for t, n in rows.items() if n and n > 0]
    if filled:
        level = OK
        detail = f"{len(filled)} of {len(rows)} previously-empty tables now populated: {', '.join(filled)}"
    else:
        level = WARN
        detail = (f"all {len(still_empty)} designed-but-unwritten tables still empty "
                  f"(incl. ichor_knowledge_pages = highest-priority retrieval lane)")
    return Result("empty_tables", level, detail, {"rows": rows, "still_empty": still_empty})


# ── 7. frozen producers ─────────────────────────────────────────────────
def check_frozen() -> Result:
    if not ICHOR_DB.is_file():
        return Result("frozen", CRIT, "ichor.db missing")
    conn = connect(ICHOR_DB)
    now = datetime.now(timezone.utc)
    findings, worst = {}, 0
    try:
        for table, column in FROZEN_WATCH:
            if not table_exists(conn, table):
                findings[table] = {"rows": None, "age_days": None, "note": "table missing"}
                continue
            if not has_column(conn, table, column):
                findings[table] = {"rows": scalar(conn, f"SELECT COUNT(*) FROM {table}"),
                                   "age_days": None, "note": f"no {column} column"}
                continue
            rows = scalar(conn, f"SELECT COUNT(*) FROM {table}")
            latest = scalar(conn, f"SELECT MAX({column}) FROM {table}")
            age = None
            if latest:
                norm = str(latest).replace("T", " ")[:19]
                try:
                    dt = datetime.strptime(norm, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    age = (now - dt).days
                except ValueError:
                    age = None
            findings[table] = {"rows": rows, "latest": latest, "age_days": age}
            if rows and age is not None:
                worst = max(worst, age)
    finally:
        conn.close()

    stale = {t: v for t, v in findings.items() if v.get("age_days") is not None
             and v["age_days"] >= FROZEN_DAYS and (v.get("rows") or 0) > 0}
    if stale:
        level = WARN
        detail = "; ".join(f"{t} silent {v['age_days']}d ({v['rows']} rows)" for t, v in stale.items())
    else:
        level = OK
        detail = f"all watched producers active within {FROZEN_DAYS}d (oldest {worst}d)"
    return Result("frozen", level, detail, {"tables": findings})


# ── 8. cron health across every profile ─────────────────────────────────
def check_cron() -> Result:
    if not PROFILES.is_dir():
        return Result("cron", WARN, f"no profiles dir at {PROFILES}")
    problems, summary, total_jobs = [], {}, 0
    for prof in sorted(PROFILES.iterdir()):
        jobs_file = prof / "cron" / "jobs.json"
        exec_db = prof / "cron" / "executions.db"
        if not jobs_file.is_file():
            continue
        try:
            payload = json.loads(jobs_file.read_text())
        except (OSError, json.JSONDecodeError):
            problems.append(f"{prof.name}: jobs.json unreadable")
            continue
        jobs = payload.get("jobs") or []
        total_jobs += len(jobs)
        last_status = {}
        if exec_db.is_file():
            conn = connect(exec_db)
            try:
                for j in jobs:
                    row = conn.execute(
                        "SELECT status, finished_at FROM executions WHERE job_id = ? "
                        "ORDER BY claimed_at DESC LIMIT 1", (j.get("id"),),
                    ).fetchone()
                    if row:
                        last_status[j.get("id")] = {"status": row["status"],
                                                    "finished_at": row["finished_at"]}
                    n_fail = scalar(
                        conn, "SELECT COUNT(*) FROM executions WHERE job_id = ? AND status = 'failed'",
                        (j.get("id"),),
                    )
                    if n_fail:
                        last_status.setdefault(j.get("id"), {})["total_failures"] = n_fail
            finally:
                conn.close()
        summary[prof.name] = {"jobs": len(jobs), "last": last_status}
        for j in jobs:
            if not j.get("enabled"):
                continue
            st = last_status.get(j.get("id"), {})
            if st.get("status") == "failed":
                problems.append(f"{prof.name}/{j.get('name')}: last run FAILED")
    if problems:
        return Result("cron", WARN, "; ".join(problems[:6]),
                      {"summary": summary, "problems": problems, "total_jobs": total_jobs})
    return Result("cron", OK, f"{total_jobs} jobs across {len(summary)} profiles, no failed last-runs",
                  {"summary": summary, "total_jobs": total_jobs})


# ── 9. deep: live tier reachability ─────────────────────────────────────
def check_tiers() -> Result:
    """Imports the live provider and exercises each retrieval tier for real.

    Replicates production import order: hermes_cli resolves from the installed
    fleet tree BEFORE the plugin prepends ~/pantheon to sys.path. Without that
    ordering pantheon's stub hermes_cli shadows the real one and this check
    cannot run at all.
    """
    # Order matters, and getting it wrong is the very bug this check exists to
    # detect.
    #
    # Two traps, both hit while building this:
    #   1. Each insert(0, ...) pushes the previous entry right, so inserting in
    #      FORWARD order leaves ~/pantheon at sys.path[0].
    #   2. PYTHONPATH on this host already contains the live fleet tree, so an
    #      `if p not in sys.path` guard silently SKIPS the reorder entirely and
    #      pantheon stays at index 0 anyway.
    #
    # With pantheon first, its 4-module hermes_cli stub shadows the real
    # 189-module package and this probe dies with
    # "No module named 'hermes_cli.config'". So: remove-then-insert
    # unconditionally, giving a deterministic order regardless of PYTHONPATH.
    for p in (str(PANTHEON), str(HERMES / "plugins"), str(LIVE_TREE)):
        while p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    try:
        import hermes_cli  # noqa: F401
        from hermes_cli.config import get_env_value_prefer_dotenv  # noqa: F401
        from ichor import provider as P
        from lib.ichor_hybrid import MemoryTrait
    except Exception as exc:
        return Result("tiers", WARN, f"provider not importable: {type(exc).__name__}: {exc}")

    try:
        prov = P.IchorMemoryProvider()
    except Exception as exc:
        return Result("tiers", WARN, f"provider init failed: {type(exc).__name__}: {exc}")
    # Neutralise write-side effects: a monitor must not mutate importance/edges.
    prov._apply_score = lambda *a, **k: None
    prov._reinforce_edges = lambda *a, **k: None

    # Two query shapes, because T1 behaves completely differently on each and a
    # single probe would misreport it either way.
    #   keyword  -> "ichor memory"                          (what T1 is built for)
    #   natural  -> "How does Ichor handle memory for Konan?" (what users type)
    # _query_fts5 ANDs every token including stopwords, so the natural-language
    # form returns 0 while the keyword form returns hits. Reporting only the
    # natural-language form would label T1 "DEAD" when it is merely narrow.
    keyword = "ichor memory"
    query = "How does Ichor handle memory for Konan?"
    lower = "how does ichor handle memory for konan?"
    data = {}
    try:
        data["T1_fts5_keyword"] = len(prov._query_fts5(keyword, limit=5))
        data["T1_fts5_natural"] = len(prov._query_fts5(query, limit=5))
        data["T2_warm"] = len(prov._query_warm(query, limit=5))
        ents = prov._extract_named_entities(query)
        data["T3_graph_caps"] = len(prov._query_graph(ents, depth=2)) if ents else 0
        # Measure the EFFECT (graph rows), not the intermediate (entity count).
        # The old probe counted entities, which is why it said "T3=12" for weeks
        # while the lowercase path returned nothing at all: it only ever asked
        # the capitalised question.
        lower_ents = prov._extract_named_entities(lower)
        data["T3_graph_lowercase_entities"] = len(lower_ents)
        data["T3_graph_lowercase"] = len(prov._query_graph(lower_ents, depth=2)) if lower_ents else 0
    except Exception as exc:
        return Result("tiers", WARN, f"tier probe failed: {type(exc).__name__}: {exc}")

    # Ladder strictness: does the graph half survive?
    try:
        trait = MemoryTrait()
        raw = trait.retrieve(query=query, limit=10, backends=["fts5", "events", "graph"],
                             tags=[], tags_match="any_strict", budget="mid",
                             max_tokens=4096, include_sources=True)
        excluded = raw.get("strict_scope_excluded_counts") or {}
        data["ladder_strict_graph_excluded"] = excluded.get("graph_untagged", 0)
        data["ladder_strict_results"] = len(list(raw.get("results") or []))
    except Exception as exc:
        data["ladder_error"] = f"{type(exc).__name__}: {exc}"

    # T4 reachability without spending an API call. The error is RECORDED, not
    # swallowed -- a monitor that hides its own failures reproduces the exact
    # defect it is supposed to catch.
    try:
        from agent.credential_pool import load_pool
        pool = load_pool("opencode-go")
        data["T4_pool_creds"] = len(pool.entries()) if pool and pool.has_credentials() else 0
    except Exception as exc:
        data["T4_pool_creds"] = None
        data["T4_error"] = f"{type(exc).__name__}: {exc}"

    # T1 counts as dead only if the KEYWORD form returns nothing.
    dead = [k for k in ("T1_fts5_keyword", "T2_warm", "T3_graph_caps") if not data.get(k)]
    level = OK
    detail = (f"T1(keyword)={data.get('T1_fts5_keyword')} "
              f"T1(natural)={data.get('T1_fts5_natural')} "
              f"T2={data.get('T2_warm')} T3={data.get('T3_graph_caps')} "
              f"T3(lowercase)={data.get('T3_graph_lowercase')} "
              f"T4_creds={data.get('T4_pool_creds')}")
    if dead:
        level = WARN
        detail += f"; DEAD TIERS: {', '.join(dead)}"
    if not data.get("T1_fts5_natural"):
        level = WARN
        detail += ("; T1 returns 0 for full-sentence queries "
                   "(all tokens ANDed, no stopword filter)")
    if data.get("ladder_strict_graph_excluded"):
        level = WARN
        detail += (f"; ladder discards {data['ladder_strict_graph_excluded']} graph "
                   f"candidates under default strictness")
    if not data.get("T3_graph_lowercase"):
        level = WARN
        detail += ("; T3 returns 0 rows for all-lowercase input — the graph tier "
                   "is dead for the way people actually type")
    if data.get("T4_error"):
        level = WARN
        detail += f"; T4 probe error: {data['T4_error']}"
    return Result("tiers", level, detail, data)


CHECKS_FAST = [check_trees, check_shadow, check_storage, check_delivery,
               check_eviction, check_empty_tables, check_frozen, check_cron]
CHECKS_DEEP = CHECKS_FAST + [check_tiers]


def run(deep: bool) -> list:
    return [fn() for fn in (CHECKS_DEEP if deep else CHECKS_FAST)]


def render(results: list) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [f"Ichor Health — {stamp}", "=" * 72]
    for r in results:
        lines.append(f"[{_ICON[r.level]}] {r.name:<14} {r.detail}")
    crit = sum(1 for r in results if r.level == CRIT)
    warn = sum(1 for r in results if r.level == WARN)
    lines.append("-" * 72)
    lines.append(f"{len(results)} checks — {crit} critical, {warn} warning")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ichor memory stack health monitor")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--deep", action="store_true", help="include live tier probe")
    parser.add_argument("--quiet", action="store_true", help="print only when unhealthy")
    args = parser.parse_args(argv)

    results = run(args.deep)
    crit = sum(1 for r in results if r.level == CRIT)
    warn = sum(1 for r in results if r.level == WARN)

    if args.json:
        print(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "critical": crit, "warnings": warn,
            "checks": [r.as_dict() for r in results],
        }, indent=2, ensure_ascii=False))
    elif not args.quiet or crit or warn:
        print(render(results))

    return 2 if crit else (1 if warn else 0)


if __name__ == "__main__":
    raise SystemExit(main())
