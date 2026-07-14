#!/usr/bin/env python3
"""
Doc Discipline Verify — Nightly drift detector for Pantheon canonical docs.

Runs the verification checks from the doc-discipline skill against the
canonical docs (currently: OLYMPUS_UI_STATE.md, OLYMPUS_UI_ROADMAP.md).
Output: ~/pantheon/shared/DOC_DRIFT.md (only if drift found; silent if clean).

Schedule: 0 3 * * * (lowest-activity time, per Cyber's request 2026-06-02).
Executor: system cron (no god profile binding).
This script does not use an LLM — pure bash/python, fast, deterministic.

Companion to: ~/pantheon/god-packages/shared-skills/doc-discipline/SKILL.md
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────
PANTHEON_DIR = Path.home() / "pantheon"
OLYMPUS_UI_DIR = Path.home() / "Olympus-UI"
ATHENAEUM_DIR = Path.home() / "athenaeum"
SHARED_DIR = PANTHEON_DIR / "shared"
DRIFT_REPORT = SHARED_DIR / "DOC_DRIFT.md"

# Canonical docs (extend this list as the project adds more)
CANONICAL_DOCS = [
    {
        "path": ATHENAEUM_DIR / "Codex-Olympus" / "OLYMPUS_UI_STATE.md",
        "name": "OLYMPUS_UI_STATE.md",
        "purpose": "Olympus UI source-of-truth: layout, live state, type health, what's in flight",
    },
    {
        "path": ATHENAEUM_DIR / "Codex-Olympus" / "OLYMPUS_UI_ROADMAP.md",
        "name": "OLYMPUS_UI_ROADMAP.md",
        "purpose": "Olympus UI prioritized roadmap (Now/Next/Later/Maybe + Project Ideas)",
    },
]

# Verifications: each yields (claim_id, expected, actual, severity) on drift
# Severity: "info" (noted but no action), "warn" (someone should look), "drift" (action required)

# ── Helpers ─────────────────────────────────────────────────────────────

def _sh(cmd: str, cwd: Path | None = None, timeout: int = 30) -> tuple[str, int]:
    """Run a shell command, return (stdout, returncode)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=str(cwd) if cwd else None, timeout=timeout
        )
        return r.stdout.strip(), r.returncode
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return f"[{e.__class__.__name__}: {e}]", 1


def _tsc_error_count() -> int | None:
    """Run tsc -b in Olympus-UI, return error count, or None on failure."""
    if not (OLYMPUS_UI_DIR / "package.json").exists():
        return None
    out, rc = _sh("npx tsc -b --noEmit 2>&1 | grep -c 'error TS'", cwd=OLYMPUS_UI_DIR, timeout=60)
    try:
        return int(out.splitlines()[-1]) if out else 0
    except (ValueError, IndexError):
        return None


def _doc_last_verified(path: Path) -> str | None:
    """Extract the 'Last verified' or 'Last updated' date from a doc header.

    Accepts formats like:
      - "Last updated: 2026-06-02"
      - "Last updated: 2026-06-02 (post-audit, +L10 Pantheon Desktop)"
      - "Last verified: 2026-06-02"
    Returns the YYYY-MM-DD portion, or None if not found.
    """
    if not path.exists():
        return None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    # Try several patterns, in order of preference
    # Handle markdown bold (**...**), optional parenthetical after the date
    patterns = [
        r"\*\*Last verified:\*\*\s*(\d{4}-\d{2}-\d{2})",
        r"\*\*Last updated:\*\*\s*(\d{4}-\d{2}-\d{2})",
        r"Last verified:\s*(\d{4}-\d{2}-\d{2})",
        r"Last updated:\s*(\d{4}-\d{2}-\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    # Also check the first 20 lines (header area) specifically
    header = "\n".join(text.splitlines()[:20])
    for pat in patterns:
        m = re.search(pat, header)
        if m:
            return m.group(1)
    return None


def _git_ahead_count(cwd: Path) -> int | None:
    """Count unpushed commits in a git repo, or None if not a repo."""
    if not (cwd / ".git").exists():
        return None
    out, rc = _sh("git log --oneline @{u}..HEAD 2>/dev/null | wc -l", cwd=cwd, timeout=10)
    if rc != 0:
        # No upstream configured; count commits not in main
        out, _ = _sh("git log --oneline main..HEAD 2>/dev/null | wc -l", cwd=cwd, timeout=10)
    try:
        return int(out)
    except ValueError:
        return None


def _git_uncommitted_count(cwd: Path) -> int | None:
    """Count uncommitted changes (modified + untracked) in a git repo."""
    if not (cwd / ".git").exists():
        return None
    out, _ = _sh("git status --short 2>/dev/null | wc -l", cwd=cwd, timeout=10)
    try:
        return int(out)
    except ValueError:
        return None


def _bundle_max_age_hours() -> float | None:
    """Age of the most recent compiled bundle in webui/static/assets."""
    assets = PANTHEON_DIR / "webui" / "static" / "assets"
    if not assets.exists():
        return None
    bundles = list(assets.glob("*.js"))
    if not bundles:
        return None
    newest = max(bundles, key=lambda p: p.stat().st_mtime)
    mtime = datetime.fromtimestamp(newest.stat().st_mtime, tz=timezone.utc)
    age = datetime.now(tz=timezone.utc) - mtime
    return age.total_seconds() / 3600


def _service_active(unit: str) -> bool | None:
    """Check if a systemd user unit is active."""
    out, rc = _sh(f"systemctl --user is-active {unit} 2>/dev/null")
    if rc == 0:
        return out == "active"
    if "inactive" in out or "failed" in out:
        return False
    return None


# ── Verifications ───────────────────────────────────────────────────────

def run_verifications() -> list[dict]:
    """Run all checks. Return list of drift findings."""
    findings = []

    # Check 1: doc last-verified dates are within grace period (7 days)
    for doc in CANONICAL_DOCS:
        path = doc["path"]
        if not path.exists():
            findings.append({
                "id": f"doc-missing::{doc['name']}",
                "severity": "drift",
                "claim": f"{doc['name']} exists at {path}",
                "actual": "file not found",
                "where": str(path),
                "fix": "Re-create the canonical doc or update the script's path list",
            })
            continue
        last_verified = _doc_last_verified(path)
        if not last_verified:
            findings.append({
                "id": f"doc-no-date::{doc['name']}",
                "severity": "warn",
                "claim": f"{doc['name']} has a 'Last updated' or 'Last verified' date in its header",
                "actual": "no date found",
                "where": str(path),
                "fix": "Add a 'Last updated: YYYY-MM-DD' line to the doc header",
            })
            continue
        try:
            last_date = datetime.strptime(last_verified, "%Y-%m-%d").date()
        except ValueError:
            continue
        days_old = (date.today() - last_date).days
        if days_old > 7:
            findings.append({
                "id": f"doc-stale::{doc['name']}",
                "severity": "warn",
                "claim": f"{doc['name']} last verified within 7 days",
                "actual": f"last verified {last_verified} ({days_old} days ago)",
                "where": str(path),
                "fix": "Re-verify claims in the doc against current state, update the date",
            })

    # Check 2: tsc -b in Olympus-UI matches what's in state doc (if claimed)
    # NOTE: We treat ANY non-zero tsc count as "warn" rather than "drift", because
    # the state doc may legitimately document a known-1-error case (e.g., a stale
    # import in a test file that the next commit will fix). Drift is when the
    # claimed count and actual count differ; this script doesn't parse the doc
    # claim, so it just surfaces the actual count for human review.
    tsc_count = _tsc_error_count()
    if tsc_count is not None and tsc_count > 0:
        findings.append({
            "id": "tsc-errors",
            "severity": "warn",
            "claim": "Olympus-UI tsc -b should be 0 errors for green build",
            "actual": f"tsc -b reports {tsc_count} error(s)",
            "where": str(OLYMPUS_UI_DIR),
            "fix": "Run `cd ~/Olympus-UI && npx tsc -b --noEmit` to see errors; "
                   "fix or update state doc if intentional and documented",
        })

    # Check 3: Pantheon has unpushed commits (informational)
    pantheon_ahead = _git_ahead_count(PANTHEON_DIR)
    if pantheon_ahead is not None and pantheon_ahead > 0:
        findings.append({
            "id": "pantheon-unpushed",
            "severity": "info",
            "claim": "Pantheon is in sync with origin/main (or uncommitted work is acceptable)",
            "actual": f"{pantheon_ahead} unpushed commit(s) in ~/pantheon/",
            "where": str(PANTHEON_DIR),
            "fix": "Run `cd ~/pantheon && git log --oneline origin/main..HEAD` to review; push if ready",
        })

    # Check 4: Olympus-UI has uncommitted changes (informational)
    oly_uncommitted = _git_uncommitted_count(OLYMPUS_UI_DIR)
    if oly_uncommitted is not None and oly_uncommitted > 0:
        findings.append({
            "id": "olympus-uncommitted",
            "severity": "info",
            "claim": "Olympus-UI working tree clean",
            "actual": f"{oly_uncommitted} uncommitted change(s) in ~/Olympus-UI/",
            "where": str(OLYMPUS_UI_DIR),
            "fix": "Commit or stash before next session; consider applying doc-discipline skill first",
        })

    # Check 5: compiled bundles are not stale (informational)
    bundle_age = _bundle_max_age_hours()
    if bundle_age is not None and bundle_age > 48:  # more than 2 days
        findings.append({
            "id": "bundles-stale",
            "severity": "info",
            "claim": "Compiled bundles in webui/static/assets/ are recent (within 48h)",
            "actual": f"newest bundle is {bundle_age:.1f}h old",
            "where": str(PANTHEON_DIR / "webui" / "static" / "assets"),
            "fix": "If Olympus-UI source has uncommitted changes, build and deploy via deploy-olympus.sh",
        })

    # Check 6: pantheon-webui service is active
    webui_active = _service_active("pantheon-webui.service")
    if webui_active is False:
        findings.append({
            "id": "service-down::pantheon-webui",
            "severity": "drift",
            "claim": "pantheon-webui.service is active",
            "actual": "service is not active",
            "where": "systemd --user",
            "fix": "Run `systemctl --user status pantheon-webui.service` to diagnose",
        })

    return findings


# ── Output ──────────────────────────────────────────────────────────────

def write_report(findings: list[dict]) -> bool:
    """Write the drift report. Returns True if report was written (drift found)."""
    if not findings:
        # Silent: no drift
        # If a previous report exists, leave it (it documents the last drift event)
        return False

    SHARED_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(tz=timezone.utc).astimezone()
    today = now.strftime("%Y-%m-%d")
    now_str = now.strftime("%Y-%m-%d %H:%M:%S %Z")

    drift_count = sum(1 for f in findings if f["severity"] == "drift")
    warn_count = sum(1 for f in findings if f["severity"] == "warn")
    info_count = sum(1 for f in findings if f["severity"] == "info")

    lines = [
        f"# Doc Discipline — Drift Report",
        f"",
        f"**Generated:** {now_str}",
        f"**Severity counts:** {drift_count} drift, {warn_count} warn, {info_count} info",
        f"",
        f"**Skill:** `doc-discipline` (`~/pantheon/god-packages/shared-skills/doc-discipline/`)",
        f"**Script:** `~/pantheon/scripts/doc-discipline-verify.py`",
        f"**Schedule:** 0 3 * * * (system cron, no god binding)",
        f"",
        f"---",
        f"",
    ]

    for severity in ["drift", "warn", "info"]:
        sev_findings = [f for f in findings if f["severity"] == severity]
        if not sev_findings:
            continue
        emoji = {"drift": "🔴", "warn": "🟡", "info": "🔵"}[severity]
        lines.append(f"## {emoji} {severity.upper()}")
        lines.append("")
        for f in sev_findings:
            lines.append(f"### {f['id']}")
            lines.append(f"- **Claim:** {f['claim']}")
            lines.append(f"- **Actual:** {f['actual']}")
            lines.append(f"- **Where:** `{f['where']}`")
            lines.append(f"- **Fix:** {f['fix']}")
            lines.append("")

    lines.extend([
        "---",
        "",
        "## What to do",
        "",
        "1. **drift findings (🔴):** These are real problems. Fix before the next commit. If the doc-discipline skill is being followed, these should be 0.",
        "2. **warn findings (🟡):** Soft signals. Doc is stale, or a build claim is drifting. Decide if it's worth a session or if the next natural change will address it.",
        "3. **info findings (🔵):** Informational. Unpushed commits, uncommitted WIP, stale bundles. Decide if these are intentional.",
        "",
        "If you disagree with a finding, edit this report or update the canonical doc — do not silence the script.",
        "",
    ])

    DRIFT_REPORT.write_text("\n".join(lines))
    return True


def main() -> int:
    findings = run_verifications()
    wrote = write_report(findings)

    if wrote:
        # Print a one-line summary to stdout for cron output / morning briefing
        drift_count = sum(1 for f in findings if f["severity"] == "drift")
        warn_count = sum(1 for f in findings if f["severity"] == "warn")
        info_count = sum(1 for f in findings if f["severity"] == "info")
        print(
            f"Doc discipline drift: {drift_count} drift, {warn_count} warn, {info_count} info. "
            f"See {DRIFT_REPORT}"
        )
        # Non-zero exit so the cron shows this as a "soft failure" worth surfacing
        return 0 if drift_count == 0 else 1
    else:
        # Silent success — nothing to print (cron will show 0 output, normal)
        return 0


if __name__ == "__main__":
    sys.exit(main())
