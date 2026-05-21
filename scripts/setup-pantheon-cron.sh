#!/usr/bin/env bash
# =============================================================================
# Pantheon Cron Setup Script
# =============================================================================
# Reads pantheon-cron-manifest.json and creates/updates all cron jobs.
# - Hermes cron jobs via `hermes cron create` (idempotent — skips if exists)
# - System crontab entries via `crontab` (idempotent — checks before adding)
#
# Usage:
#   ./scripts/setup-pantheon-cron.sh
#
# Can be run multiple times safely — will not create duplicate jobs.
# =============================================================================

set -euo pipefail

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PANTHEON_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MANIFEST="$SCRIPT_DIR/pantheon-cron-manifest.json"
HERMES_SCRIPTS_DIR="${HOME}/.hermes/scripts"

# ── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { printf "${CYAN}  →${NC} %s\n" "$*"; }
ok()    { printf "${GREEN}  ✓${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}  ⚠${NC} %s\n" "$*"; }
err()   { printf "${RED}  ✗${NC} %s\n" "$*"; }
header(){ printf "\n${BOLD}${CYAN}══ %s ══${NC}\n" "$*"; }

# ── Ensure manifest exists ─────────────────────────────────────────────────
if [ ! -f "$MANIFEST" ]; then
  err "Cron manifest not found at $MANIFEST"
  exit 1
fi

# ── Ensure hermes is available ─────────────────────────────────────────────
if ! command -v hermes >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
fi

if ! command -v hermes >/dev/null 2>&1; then
  err "hermes command not found in PATH"
  exit 1
fi

# ── Helper: check if a hermes cron job already exists ──────────────────────
hermes_cron_exists() {
  local job_name="$1"
  hermes cron list 2>/dev/null | grep -qF "$job_name"
}

# ── Helper: check if system crontab line already exists ────────────────────
system_crontab_has() {
  local pattern="$1"
  crontab -l 2>/dev/null | grep -qF "$pattern"
}

# ============================================================================
# STEP 1: Hermes Cron Jobs
# ============================================================================
header "Hermes Cron Jobs"

job_count=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(len(m['hermes_cron_jobs']))")

for i in $(seq 0 $((job_count - 1))); do
  # Extract job config from JSON manifest
  name=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m['hermes_cron_jobs'][$i]['name'])")
  schedule=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m['hermes_cron_jobs'][$i]['schedule'])")
  deliver=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m['hermes_cron_jobs'][$i]['deliver'])")
  prompt=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m['hermes_cron_jobs'][$i].get('prompt', ''))")
  script=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m['hermes_cron_jobs'][$i].get('script', ''))")
  skills_json=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(json.dumps(m['hermes_cron_jobs'][$i].get('skills', [])))")
  workdir=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m['hermes_cron_jobs'][$i].get('workdir', ''))")

  info "Processing cron job: ${name}"

  # Skip if already exists
  if hermes_cron_exists "$name"; then
    ok "Already exists — skipping: ${name}"
    continue
  fi

  # Build the command
  CMD=(hermes cron create)

  # Name (--name)
  CMD+=(--name "$name")

  # Schedule (positional)
  CMD+=("$schedule")

  # Deliver (--deliver)
  CMD+=(--deliver "$deliver")

  # Script (--script) — if specified
  if [ -n "$script" ]; then
    # Check that the script exists at ~/.hermes/scripts/
    script_path="${HERMES_SCRIPTS_DIR}/${script}"
    if [ ! -f "$script_path" ]; then
      warn "Script not found at ${script_path} — will reference it but it may fail until created"
    fi
    CMD+=(--script "$script")
  fi

  # Workdir (--workdir)
  if [ -n "$workdir" ]; then
    CMD+=(--workdir "$workdir")
  fi

  # Skills (--skill) — repeatable
  if [ "$skills_json" != "[]" ]; then
    skills=$(python3 -c "import json; print(' '.join(json.loads('$skills_json')))")
    for skill in $skills; do
      CMD+=(--skill "$skill")
    done
  fi

  # Prompt (positional — last)
  if [ -n "$prompt" ]; then
    CMD+=("$prompt")
  fi

  info "Running: ${CMD[*]}"
  if "${CMD[@]}" 2>&1; then
    ok "Created cron job: ${name}"
  else
    warn "Failed to create cron job: ${name} (may already exist or hermes needs configuration)"
  fi
done

# ============================================================================
# STEP 2: System Crontab Entries
# ============================================================================
header "System Crontab Entries"

# Ensure log directory exists
mkdir -p "$PANTHEON_DIR/logs"

entry_count=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(len(m['system_crontab_entries']))")

for i in $(seq 0 $((entry_count - 1))); do
  schedule=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m['system_crontab_entries'][$i]['schedule'])")
  command=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m['system_crontab_entries'][$i]['command'])")
  description=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m['system_crontab_entries'][$i]['description'])")

  info "Processing system crontab: ${description}"

  # Use a unique comment as a marker for idempotency
  marker="# pantheon-cron: ${description}"

  if system_crontab_has "$marker"; then
    ok "Already exists — skipping: ${description}"
    continue
  fi

  # Add the entry to crontab
  (crontab -l 2>/dev/null || true; echo "$marker"; echo "$schedule $command") | crontab -
  ok "Added system crontab: ${description}"
done

# ============================================================================
# Summary
# ============================================================================
header "Cron Setup Complete"
ok "Hermes cron jobs and system crontab entries configured."
info "To verify: hermes cron list"
info "To verify: crontab -l"
