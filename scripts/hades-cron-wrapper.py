#!/usr/bin/env python3
"""Hades cron wrapper — sets up sys.path/env then runs full pipeline."""
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Use the REAL home (not profile-isolated) for Athenaeum paths
REAL_HOME = "/home/konan"
os.environ["HOME"] = REAL_HOME

# Load profile .env for API keys
env_file = Path(REAL_HOME) / ".hermes" / ".env"
if env_file.is_file():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# Add the gods dir so `from hades.orchestrator import run_hades` works
sys.path.insert(0, f"{REAL_HOME}/pantheon/pantheon-core/gods")
# Also make sure hermes_state / hermes_cli are importable. The canonical
# checkout lives under /home/konan/pantheon/hermes-agent; keep the profile
# path as a fallback for older installs.
for candidate in (
    f"{REAL_HOME}/pantheon/hermes-agent",
    f"{REAL_HOME}/.hermes/hermes-agent",
):
    if Path(candidate).exists():
        sys.path.insert(0, candidate)
        break

from hades.orchestrator import run_hades

start = time.time()
signal.alarm(1500)
try:
    report = run_hades(skip_resume=True, timeout=1500)
    elapsed = time.time() - start
    md = report.to_markdown()
    report_data = report.to_dict()
    timestamp = report_data.get("timestamp")
    try:
        report_date = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")).date().isoformat()
    except Exception:
        report_date = datetime.now(timezone.utc).date().isoformat()
    report_dir = Path(REAL_HOME) / "athenaeum" / "Codex-Pantheon" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"hades-{report_date}.md"
    report_path.write_text(md.rstrip() + "\n")
    print(f"=== SAVED REPORT: {report_path} ===")
    print("=== HADES REPORT (MARKDOWN) ===")
    print(md)
    print("=== HADES REPORT (JSON) ===")
    print(json.dumps(report_data, indent=2, default=str))
    print(f"=== DONE ({elapsed:.1f}s) ===")
except Exception as exc:
    print(f"FATAL: {exc}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    signal.alarm(0)
