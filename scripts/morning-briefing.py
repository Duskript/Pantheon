#!/usr/bin/env python3
"""Collect morning briefing data for Hermes cron job.
Now outputs condensed Hades summary instead of the full report."""
import subprocess, sys
import re
from datetime import datetime, timezone, timedelta, date

today = date.today().isoformat()
now_utc = datetime.now(timezone.utc)
now_mdt = now_utc + timedelta(hours=-6)

print(f"=== TIMESTAMP ===")
print(f"UTC:  {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}")
print(f"MDT:  {now_mdt.strftime('%Y-%m-%d %H:%M:%S MDT')}")
print(f"Unix: {int(now_utc.timestamp())}")

print("=== HADES_REPORT ===")
report_path = f"/home/konan/athenaeum/Codex-Pantheon/reports/hades-{today}.md"
try:
    with open(report_path) as f:
        content = f.read()

    # Extract key sections for a condensed summary
    errors = []

    # Compilation errors
    comp_errors = re.findall(r'❌ (.+?)(?:\n|$)', content)
    errors.extend(comp_errors)

    # General errors section
    in_errors = False
    error_lines = []
    for line in content.split('\n'):
        if line.startswith('## ❌ Errors'):
            in_errors = True
            continue
        if in_errors:
            if line.startswith('## ') or line.startswith('---'):
                break
            if line.strip().startswith('- ❌') or line.strip().startswith('-'):
                error_lines.append(line.strip().lstrip('- '))

    # Consistency issues
    consistency = re.findall(r'⚠️ (.+?)(?:\n|$)', content)

    # Extraction errors
    extract_errors = re.findall(r'❌ Error: (.+?)(?:\n|$)', content)

    # Build condensed output
    output_parts = []
    output_parts.append(f"Report date: {today}")

    if errors:
        output_parts.append(f"COMPILATION_ERRORS: {' | '.join(errors)}")
    if error_lines:
        output_parts.append(f"RUN_ERRORS: {' | '.join(error_lines)}")
    if consistency:
        output_parts.append(f"CONSISTENCY: {' | '.join(consistency)}")
    if extract_errors:
        output_parts.append(f"EXTRACT_ERRORS: {' | '.join(extract_errors)}")

    # Check for new codices
    new_cx = re.findall(r'\*\*(Codex-[^*]+)\*\*', content)
    if new_cx:
        output_parts.append(f"NEW_CODICES: {', '.join(new_cx)}")

    # Quick stats
    compiled = re.search(r'Sessions compiled: (\d+)', content)
    articles = re.search(r'Articles created: (\d+)', content)
    distilled = re.search(r'Distilled files written: (\d+)', content)
    stats = []
    if compiled: stats.append(f"compiled={compiled.group(1)}")
    if articles: stats.append(f"articles={articles.group(1)}")
    if distilled: stats.append(f"distilled={distilled.group(1)}")
    if stats:
        output_parts.append(f"STATS: {', '.join(stats)}")

    if not errors and not error_lines and not consistency and not extract_errors:
        output_parts.append("STATUS: GREEN")

    sys.stdout.write('\n'.join(output_parts))

except FileNotFoundError:
    print("[No Hades report for today yet — consolidation may not have run]")
except Exception as e:
    print(f"[Hades report error: {e}]")

print("\n=== ATHENAEUM_TRIAGE ===", flush=True)
triage = subprocess.run(
    [sys.executable, "/home/konan/athenaeum/scripts/athenaeum-triage.py"],
    check=False,
    text=True,
    capture_output=True,
)
if triage.stdout:
    sys.stdout.write(triage.stdout)
if triage.stderr:
    sys.stdout.write(triage.stderr)

print("\n=== PROJECT_IDEAS ===", flush=True)
with open("/home/konan/pantheon/project-ideas.md") as f:
    sys.stdout.write(f.read())
sys.stdout.flush()

print("\n=== OVERNIGHT_INBOX ===", flush=True)
subprocess.run([sys.executable, "/home/konan/.hermes/scripts/overnight-inbox.py"], check=False)

print("\n=== HERMES_UPDATE_CHECK ===")
subprocess.run(["bash", "/home/konan/.hermes/scripts/check-hermes-update.sh"], check=False)

print("\n=== HERMES_NEWS ===")
subprocess.run([sys.executable, "/home/konan/.hermes/scripts/hermes-news.py"], check=False)

print("\n=== PANTHEON_RESEARCH ===")
subprocess.run([sys.executable, "/home/konan/.hermes/scripts/pantheon-research.py"], check=False)

print("\n=== JOB_MARKET ===")
subprocess.run([sys.executable, "/home/konan/.hermes/scripts/job-market.py"], check=False)

print("\n=== REDDIT_MONITOR ===")
subprocess.run([sys.executable, "/home/konan/.hermes/scripts/reddit-monitor.py"], check=False)

print("\n=== GITHUB_STARS ===")
subprocess.run([sys.executable, "/home/konan/.hermes/scripts/github-stars.py"], check=False)

print("\n=== PROSPECT_REMINDER ===")
import os
prospect_file = "/home/konan/workspace/pantheon-prospect-pipeline.md"
if os.path.exists(prospect_file):
    print(f"📋 PROSPECT PIPELINE READY: pantheon-prospect-pipeline.md")
    print(f"   Generated 2026-05-20 — Pocatello + Blackfoot prospects for Pantheon")
    print(f"   Includes: 10 biz prospects + 22 mental health practices + 30+ email drafts")
    print(f"   ACTION: Review pipeline doc before daily work begins")
