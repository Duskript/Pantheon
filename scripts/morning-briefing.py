#!/usr/bin/env python3
"""
Pantheon Morning Briefing — portable data collector (v2.0.0).

Collects system state for the Hermes cron agent to compose into a
daily briefing. The synthesis layer (Thoth at 05:00) produces a
structured intelligence file at
``~/athenaeum/reports/dawn-patrol/YYYY-MM-DD.md``; this script gathers
the additional context the Hermes delivery summary needs:

  - Hades nightly consolidation summary
  - Dawn Patrol Thoth synthesis (the canonical brief)
  - Athenaeum triage results
  - Project ideas snapshot
  - Overnight inbox from other gods
  - Hermes Dojo (overnight self-improvement) report
  - Ichor Forge (nightly harness analysis) report
  - Prospect / TheoForge distribution reminders
  - GitHub stars across Pantheon repos
  - Hermes Agent subreddit top threads
  - Hermes version
  - Git status for pantheon + athenaeum

The Hermes cron agent (06:00) uses the sections here as context, then
produces a punchy, fast-talking Telegram delivery summary. Thoth does
the heavy synthesis; this script is the delivery-side fuel.

Environment variables (all optional):
  PANTHEON_DIR       — root of Pantheon checkout       (default: $HOME/pantheon)
  ATHENAEUM_DIR      — root of Athenaeum               (default: $HOME/athenaeum)
  HERMES_HOME        — Hermes config root               (default: $HOME/.hermes)
  PROJECT_IDEAS_FILE — path to project-ideas.md         (default: PANTHEON_DIR/project-ideas.md)
  TZ / system zone   — local time comes from OS timezone (expected: America/Boise)

See examples/morning-briefing/ for setup docs.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────
PANTHEON_DIR = os.environ.get("PANTHEON_DIR", os.path.expanduser("~/pantheon"))
ATHENAEUM_DIR = os.environ.get("ATHENAEUM_DIR", os.path.expanduser("~/athenaeum"))
HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
PROJECT_IDEAS = os.environ.get(
    "PROJECT_IDEAS_FILE",
    os.path.join(PANTHEON_DIR, "project-ideas.md"),
)

# Optional: token for GitHub API (raises rate limit from 60/hr to 5000/hr)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


# ── Helpers ──────────────────────────────────────────────────────────

def _sh(cmd: str, timeout: int = 15) -> str:
    """Run a shell command and return stdout, or an error marker."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        out = r.stdout.strip()
        if out:
            return out
        if r.returncode:
            return f"[exit {r.returncode}]"
        return ""
    except FileNotFoundError:
        return "[command not found]"
    except subprocess.TimeoutExpired:
        return "[timed out]"


def _read(path: str | os.PathLike) -> str:
    """Read a file if it exists, else return empty string."""
    try:
        with open(path) as f:
            return f.read().strip()
    except (FileNotFoundError, PermissionError, IsADirectoryError, OSError):
        return ""


def _read_latest(pattern: str, base: str | os.PathLike) -> str:
    """Read the most recent file matching a glob pattern, or empty string."""
    try:
        files = sorted(Path(base).glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return ""
        return files[0].read_text().strip()
    except Exception:
        return ""


def _http_get(url: str, timeout: int = 15) -> str | None:
    """Fetch a URL with optional GitHub auth, return text or None."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Pantheon-Morning-Briefing/2.0",
                **({"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}),
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        return None


# ── Collectors ───────────────────────────────────────────────────────

def collect_timestamp() -> str:
    now_utc = datetime.now(timezone.utc)
    local = datetime.now().astimezone()
    tz_name = local.tzname() or "local"
    return (
        f"UTC:   {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        f"Local: {local.strftime('%Y-%m-%d %H:%M:%S %Z%z')} ({tz_name})\n"
        f"Unix:  {int(now_utc.timestamp())}"
    )


def collect_hades() -> str:
    """Read the most recent Hades report and surface the current state."""
    report_dir = Path(ATHENAEUM_DIR) / "Codex-Pantheon" / "reports"
    files = sorted(
        report_dir.glob("hades-*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return "[No Hades report found — nightly consolidation may not have run]"
    latest = files[0]
    content = latest.read_text().strip()
    if not content:
        return f"[Hades report {latest.name} is empty]"
    mtime = datetime.fromtimestamp(
        latest.stat().st_mtime, tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")
    lines = content.splitlines()
    excerpt = [
        line for line in lines[:120]
        if line.startswith(("# ", "## ", "| ", "- ", "✅", "❌", "⚠️", "🔴", "🟡"))
    ]
    if not excerpt:
        excerpt = lines[:25]
    preview = "\n".join(excerpt[:40])
    return f"[Most recent Hades report: {latest.name} · modified {mtime}]\n{preview}"

def collect_dawn_patrol() -> str:
    """Read the most recent Thoth dawn patrol briefing."""
    patrol_dir = Path(ATHENAEUM_DIR) / "reports" / "dawn-patrol"
    if not patrol_dir.exists():
        return "[No dawn patrol directory — intelligence scan not yet set up]"
    files = sorted(
        patrol_dir.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return "[No dawn patrol briefings found yet — first scan runs at midnight]"
    latest = files[0]
    content = latest.read_text().strip()
    if not content:
        return f"[Dawn patrol report {latest.name} is empty]"
    mtime = datetime.fromtimestamp(
        latest.stat().st_mtime, tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")
    lines = content.splitlines()

    def section(title: str) -> list[str]:
        marker = f"## {title}"
        start = next((i for i, line in enumerate(lines) if line.strip().startswith(marker)), None)
        if start is None:
            return []
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        chunk = [line for line in lines[start:end] if line.strip()]
        if len(chunk) > 12:
            chunk = chunk[:12]
        return chunk

    sections = []
    for title in ("📦 System Health", "🔍 Ichor Brief", "📰 Intel", "📨 Quarantine"):
        chunk = section(title)
        if chunk:
            sections.extend(chunk)
            sections.append("")
    if not sections:
        sections = [
            line for line in lines
            if line.startswith(("# ", "## ", "### ", "- "))
            or any(t in line for t in ("HIGH", "MEDIUM", "LOW", "⚠️", "❌", "✅", "🔴"))
        ][:60]
    preview = "\n".join(sections).strip()
    return f"[Dawn Patrol: {latest.name} · modified {mtime}]\n{preview or content[:3000]}"

def collect_triage() -> str:
    """Run athenaeum-triage.py if present."""
    script = os.path.join(ATHENAEUM_DIR, "scripts", "athenaeum-triage.py")
    if not os.path.exists(script):
        # Try the pantheon location
        script = os.path.join(PANTHEON_DIR, "pantheon-core", "athenaeum-triage.py")
    if not os.path.exists(script):
        return "[athenaeum-triage.py not found — skipping]"
    out = _sh(f"python3 {script}", timeout=60)
    return out if out else "[athenaeum-triage: no output]"


def collect_project_ideas() -> str:
    """Snapshot of project-ideas.md (truncated for brevity)."""
    c = _read(PROJECT_IDEAS)
    if not c:
        return "[No project ideas file — skipping]"
    # Keep only the first 2000 chars — the agent can read more if needed
    return c[:2000] + ("\n\n[... truncated — full file available]" if len(c) > 2000 else "")


def collect_memory_pipeline_health() -> str:
    """Live Ichor + graph DB health.

    This section exists to prevent the briefing agent from inferring DB health
    from stale placeholder files or old Dawn Patrol prose. The canonical Ichor
    DB is ``~/.hermes/ichor.db``. The canonical graph DB is
    ``~/.hermes/pantheon/graph.db``.
    """
    try:
        import sqlite3

        checks = [
            ("Ichor events DB", Path(HERMES_HOME) / "ichor.db"),
            ("Entity graph DB", Path(HERMES_HOME) / "pantheon" / "graph.db"),
        ]
        lines: list[str] = []
        for label, db_path in checks:
            if not db_path.exists():
                lines.append(f"- ❌ {label}: missing at `{db_path}`")
                continue
            size_mb = db_path.stat().st_size / (1024 * 1024)
            with sqlite3.connect(str(db_path)) as conn:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                table_rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
                tables = [row[0] for row in table_rows]

                counts: list[str] = []
                for table in (
                    "ichor_events",
                    "cold_events",
                    "entities",
                    "warm_entities",
                    "relationships",
                    "nodes",
                    "edges",
                ):
                    if table not in tables:
                        continue
                    count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                    counts.append(f"{table}={count:,}")

                recency = ""
                for table in ("ichor_events", "cold_events"):
                    if table in tables:
                        latest = conn.execute(
                            f'SELECT COALESCE(MAX(created_at), "") FROM "{table}"'
                        ).fetchone()[0]
                        if latest:
                            recency = f"; latest {table}={latest}"
                            break

            status = "✅" if integrity == "ok" and tables else "⚠️"
            detail = ", ".join(counts) if counts else f"{len(tables)} tables"
            lines.append(
                f"- {status} {label}: `{db_path}` — {size_mb:.1f}MB, "
                f"integrity={integrity}, {detail}{recency}"
            )

        return "\n".join(lines)
    except Exception as e:
        return f"[Memory pipeline health error: {type(e).__name__}: {e}]"


def collect_overnight_inbox() -> str:
    """Read overnight inbox messages for the user (from all gods).

    Queries the Ichor events DB directly via sqlite (cron runs hermes-venv,
    not pantheon venv, so we can't import from pantheon-core). Filters to
    the 14h lookback window and the event types that actually represent
    messages worth surfacing in a brief — blockers, commitments, decisions,
    digest entries. Other event types (fact, preference, insight, follow_up)
    would drown the inbox in noise.

    Schema note: the Ichor events table is ``ichor_events`` with columns
    ``event_type`` (not ``category``) and ``subject`` (not ``title``).
    ``created_at`` is a TEXT ISO8601 timestamp, not a unix integer — so
    we filter on a string comparison, not on a numeric cutoff.
    """
    try:
        import sqlite3

        events_db = Path(HERMES_HOME) / "ichor.db"
        if not events_db.exists():
            events_db = Path(ATHENAEUM_DIR) / "ichor.db"
        if not events_db.exists():
            return "[Ichor events DB not found — skipping overnight inbox]"
        # 14h lookback as an ISO8601 string
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=14)
        ).strftime("%Y-%m-%dT%H:%M:%S")
        with sqlite3.connect(str(events_db)) as conn:
            rows = conn.execute(
                """
                SELECT god_name, event_type, subject, created_at
                FROM ichor_events
                WHERE created_at >= ?
                  AND event_type IN (
                      'blocker', 'commitment', 'decision',
                      'digest_entry'
                  )
                ORDER BY created_at DESC
                LIMIT 25
                """,
                (cutoff,),
            ).fetchall()
        if not rows:
            return "[No overnight inbox messages — quiet night]"
        lines = []
        for god, etype, subject, ts in rows:
            t = ts[:16].replace("T", " ") + " UTC"
            lines.append(
                f"- [{t}] **{god}** ({etype}): {subject[:120]}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"[Overnight inbox error: {type(e).__name__}: {e}]"


def collect_hermes_dojo() -> str:
    """Pull the latest Hermes Dojo overnight improvement report.

    Tries multiple known report locations in priority order. The Dojo
    cron writes its output to ``$HERMES_HOME/cron/output/<job_id>/`` —
    we use the most recent ``*.md`` there. Falls back to a ``dojo/reports/``
    subdir under HERMES_HOME if the cron output dir doesn't exist.
    """
    candidates = [
        Path(HERMES_HOME) / "cron" / "output" / "094c10e20512",  # Hermes Dojo cron
        Path(HERMES_HOME) / "dojo" / "reports",
        Path(HERMES_HOME) / "logs" / "dojo",
    ]
    for out_dir in candidates:
        if out_dir.exists():
            latest = _read_latest("*.md", out_dir)
            if latest:
                lines = latest.splitlines()
                key = [l for l in lines if any(
                    t in l for t in (
                        "## ", "✅", "❌", "⚠️", "Skills", "Issues",
                        "Patches", "Result", "Score",
                    )
                )]
                return "\n".join(key[:30]) if key else latest[:1500]
    return "[No Hermes Dojo report found — first run may not have happened yet]"


def collect_ichor_forge() -> str:
    """Pull the latest Ichor Forge nightly harness analysis.

    Prefer the current script-only Forge cron output. Older archive paths are
    retained only as fallback and are explicitly labeled when stale, so the
    morning briefing never presents June/July Forge ghosts as today's state.
    """
    candidates = [
        Path(HERMES_HOME) / "cron" / "output" / "1cef23871068",  # current Forge cron
        Path(PANTHEON_DIR) / "logs" / "ichor-forge",
        Path(HERMES_HOME) / "ichor-forge",
        Path(HERMES_HOME) / "cron" / "output" / "9a8a0bae3225",  # legacy paused Forge cron
        Path(ATHENAEUM_DIR) / "Codex-God-thoth" / "reports" / "ichor-forge",
        Path(ATHENAEUM_DIR) / "reports" / "ichor-forge-nightly",
    ]
    report_files = []
    for out_dir in candidates:
        if out_dir.exists():
            report_files.extend(p for p in out_dir.glob("*.md") if p.is_file())
    if not report_files:
        return "[No Ichor Forge report found — last run may have skipped or not started yet]"

    latest_path = max(report_files, key=lambda p: p.stat().st_mtime)
    latest = latest_path.read_text().strip()
    if not latest:
        return f"[Ichor Forge report {latest_path.name} is empty]"

    mtime = datetime.fromtimestamp(latest_path.stat().st_mtime, tz=timezone.utc)
    age = datetime.now(timezone.utc) - mtime
    if age > timedelta(hours=36):
        prefix = (
            f"⚠️ Stale Ichor Forge report: {latest_path.name} "
            f"modified {mtime.strftime('%Y-%m-%d %H:%M UTC')} "
            f"({age.days}d old). Treat as historical unless the next Forge cycle refreshes it.\n"
        )
    else:
        prefix = (
            f"[Ichor Forge report: {latest_path.name} · "
            f"modified {mtime.strftime('%Y-%m-%d %H:%M UTC')}]\n"
        )

    lines = latest.splitlines()
    key = [l for l in lines if any(
        t in l for t in (
            "Analyzed:", "Timespan:", "Interventions:", "Overall block rate:",
            "Models:", "Gates active:", "Per-Gate Metrics", "Detected Patterns",
            "Suggested Adjustments", "## ", "✅", "❌", "⚠️", "🚨",
            "Block rate", "Intervention", "Gate", "Forge",
        )
    )]
    return prefix + ("\n".join(key[:40]) if key else latest[:1500])


def collect_prospect_reminder() -> str:
    """TheoForge prospect pipeline status + distribution reminders."""
    candidates = [
        Path(PANTHEON_DIR) / "theoforge" / "prospects.md",
        Path(ATHENAEUM_DIR) / "Codex-TheoForge" / "prospects.md",
        Path(PANTHEON_DIR) / "project-ideas.md",
    ]
    for path in candidates:
        if path.exists():
            content = _read(path)
            if content:
                # Pull only the first 1500 chars — the agent can read more
                return content[:1500] + ("\n\n[... truncated]" if len(content) > 1500 else "")
    return "[No TheoForge prospect file found]"


def collect_github_stars() -> str:
    """Total stars across known Pantheon repos."""
    repos = [
        ("Pantheon", "MiniMax-AI/Pantheon"),
        ("Hermes Agent", "NousResearch/hermes-agent"),
        ("TheoForge", "theoforgehq/theoforge"),
        ("Ichor", "pantheon-ai/ichor"),
    ]
    lines = []
    total = 0
    for label, slug in repos:
        url = f"https://api.github.com/repos/{slug}"
        data = _http_get(url, timeout=10)
        if not data:
            lines.append(f"- **{label}** (`{slug}`): [API unreachable]")
            continue
        try:
            body = json.loads(data)
            stars = body.get("stargazers_count", 0)
            forks = body.get("forks_count", 0)
            total += stars
            lines.append(f"- **{label}** (`{slug}`): ★{stars:,}  ·  ⑂{forks:,}")
        except (json.JSONDecodeError, KeyError):
            lines.append(f"- **{label}** (`{slug}`): [parse error]")
    lines.append(f"\n**Total across Pantheon-owned repos: ★{total:,}**")
    return "\n".join(lines)


def collect_hermes_subreddit() -> str:
    """Top threads from the Hermes Agent subreddit (r/HermesAgent or r/NousResearch)."""
    # Try a few known subreddit names
    for sub in ("HermesAgent", "NousResearch", "LocalLLaMA"):
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit=5"
        data = _http_get(url, timeout=10)
        if data:
            try:
                body = json.loads(data)
                posts = body.get("data", {}).get("children", [])
                if posts:
                    lines = [f"**Top of r/{sub} (past 24h):**"]
                    for p in posts:
                        d = p.get("data", {})
                        title = d.get("title", "?")
                        score = d.get("score", 0)
                        comments = d.get("num_comments", 0)
                        permalink = d.get("permalink", "")
                        lines.append(
                            f"- [{score}▲ {comments}💬] {title}\n  https://reddit.com{permalink}"
                        )
                    return "\n".join(lines)
            except (json.JSONDecodeError, KeyError):
                continue
    return "[Reddit API blocked or no results — fallback to web search not implemented in script]"


def collect_update_check() -> str:
    """Hermes version + any available update."""
    ver = _sh("hermes --version 2>/dev/null || echo unknown")
    update = _sh("hermes update check 2>/dev/null || true")
    if update and "[exit" not in update and update:
        return f"Hermes version: {ver}\n{update[:500]}"
    return f"Hermes version: {ver}"


def collect_git_status() -> str:
    """Git status for the two main repos."""
    results = []
    for repo in [PANTHEON_DIR, ATHENAEUM_DIR]:
        git_dir = os.path.join(repo, ".git")
        if os.path.isdir(git_dir):
            status = _sh(f"cd {repo} && git status --short 2>/dev/null")
            branch = _sh(f"cd {repo} && git branch --show-current 2>/dev/null")
            ahead = _sh(f"cd {repo} && git rev-list --count --left-only '@{{u}}'..HEAD 2>/dev/null")
            behind = _sh(f"cd {repo} && git rev-list --count --right-only '@{{u}}'..HEAD 2>/dev/null")
            label = os.path.basename(repo) or repo
            # rev-list fails (exit 128) when the branch has no upstream set;
            # report it cleanly instead of leaking "[exit 128]" into the brief.
            if ahead.startswith("[exit") or behind.startswith("[exit"):
                sync = "no upstream"
            else:
                sync = f"+{ahead or 0} ahead / -{behind or 0} behind"
            if status:
                results.append(f"**[{label}]** ({branch or '?'}, {sync}):\n```\n{status[:1000]}\n```")
            else:
                results.append(f"**[{label}]** ({branch or '?'}) ✓ clean ({sync})")
        else:
            results.append(f"[{repo}]: not a git repo")
    return "\n\n".join(results) or "[No git repos found]"


# ── Main ─────────────────────────────────────────────────────────────

# Collector registry — order = output order. Hermes prompt lists these
# in the same order, so the LLM can locate sections predictably.
COLLECTORS: list[tuple[str, str]] = [
    ("TIMESTAMP", "collect_timestamp"),
    ("HADES_REPORT", "collect_hades"),
    ("DAWN_PATROL", "collect_dawn_patrol"),
    ("MEMORY_PIPELINE_HEALTH", "collect_memory_pipeline_health"),
    ("ATHENAEUM_TRIAGE", "collect_triage"),
    ("OVERNIGHT_INBOX", "collect_overnight_inbox"),
    ("HERMES_DOJO_REPORT", "collect_hermes_dojo"),
    ("ICHOR_FORGE_REPORT", "collect_ichor_forge"),
    ("PROSPECT_REMINDER", "collect_prospect_reminder"),
    ("GITHUB_STARS", "collect_github_stars"),
    ("HERMES_AGENT_SUBREDDIT", "collect_hermes_subreddit"),
    ("PROJECT_IDEAS", "collect_project_ideas"),
    ("HERMES_UPDATE", "collect_update_check"),
    ("GIT_STATUS", "collect_git_status"),
]


def main() -> None:
    for header, func_name in COLLECTORS:
        func = globals().get(func_name)
        print(f"=== {header} ===")
        if func is None:
            print(f"[collector '{func_name}' not found]")
            print()
            continue
        try:
            result = func()
        except Exception as e:
            result = f"[collector error: {type(e).__name__}: {e}]"
        if result:
            print(result)
        print()


if __name__ == "__main__":
    main()
