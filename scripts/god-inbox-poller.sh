#!/bin/bash
# god-inbox-poller.sh — Poll ACTIVE Pantheon god inboxes and auto-launch idle gods
# Runs every 60s via Hermes cron (no-agent mode). Only polls active gods from gods.yaml.
#
# Design:
#   - Reads active gods from ~/pantheon/gods/gods.yaml
#   - Skips infrastructure gods (hermes, hephaestus — never auto-launched)
#   - Skips gods already running (pgrep for python hermes_cli process)
#   - Launches idle gods with unread messages via direct hermes invocation
#   - Logs to ~/pantheon/scripts/logs/inbox-poller.log (rotated at 100KB)

set -euo pipefail

MESSAGES_ROOT="${HOME}/pantheon/gods/messages"
HERMES_BIN="${HOME}/.hermes/hermes-agent/venv/bin/hermes"
LOG_FILE="${HOME}/pantheon/scripts/logs/inbox-poller.log"
MAX_LOG_SIZE=102400
NEVER_LAUNCH="hermes hephaestus"

mkdir -p "$(dirname "$LOG_FILE")"

if [ -f "$LOG_FILE" ] && [ "$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)" -gt "$MAX_LOG_SIZE" ]; then
    mv "$LOG_FILE" "${LOG_FILE}.old"
fi

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }

get_active_gods() {
    python3 -c "
import yaml, sys
try:
    with open('${HOME}/pantheon/gods/gods.yaml') as f:
        data = yaml.safe_load(f)
    for name, info in data.get('gods', {}).items():
        if isinstance(info, dict) and info.get('status') == 'active':
            print(name)
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null
}

is_god_busy() {
    local god="$1"
    pgrep -f "python.*hermes_cli.*-p[[:space:]]*${god}" >/dev/null 2>&1
}

should_skip() {
    local god="$1"
    for skip in $NEVER_LAUNCH; do
        [ "$god" = "$skip" ] && return 0
    done
    return 1
}

launch_god() {
    local god="$1"
    local msg_count="$2"
    log "LAUNCH: ${god} (${msg_count} messages)"
    "$HERMES_BIN" chat -p "$god" --yolo --accept-hooks -Q -q \
        "You have ${msg_count} unread messages in your Pantheon inbox. Check them with the messaging_check_inbox tool (god_name=${god}). Process all tasks in priority order." \
        > "/tmp/inbox-poller-${god}.log" 2>&1 &
}

# --- Main ---
log "--- Poll start ---"
launched=0; skipped_busy=0; skipped_empty=0; skipped_infra=0

ACTIVE_GODS=$(get_active_gods)
if [ -z "$ACTIVE_GODS" ]; then
    log "ERROR: could not read active gods from gods.yaml"
    exit 1
fi

for god in $ACTIVE_GODS; do
    if should_skip "$god"; then
        skipped_infra=$((skipped_infra + 1))
        continue
    fi

    inbox="${MESSAGES_ROOT}/${god}"
    [ -d "$inbox" ] || { skipped_empty=$((skipped_empty + 1)); continue; }

    # Count only recent messages (last 24h) to avoid launching gods for ancient backlog
    msg_count=$(find "$inbox" -maxdepth 1 -name "*.json" -type f -mtime -1 2>/dev/null | wc -l)
    [ "$msg_count" -gt 0 ] || { skipped_empty=$((skipped_empty + 1)); continue; }

    if is_god_busy "$god"; then
        skipped_busy=$((skipped_busy + 1))
        continue
    fi

    launch_god "$god" "$msg_count"
    launched=$((launched + 1))
    sleep 2
done

log "Done — launched:${launched} busy:${skipped_busy} empty:${skipped_empty} infra:${skipped_infra}"
