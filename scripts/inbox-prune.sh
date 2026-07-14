#!/bin/bash
# inbox-prune.sh — Delete Pantheon god inbox messages older than 7 days
# Runs daily via Hermes cron (no-agent mode).
# Keeps inboxes clean so the poller only sees recent, actionable messages.
#
# Dry-run mode: pass --dry-run to see what would be deleted without deleting.

set -euo pipefail

MESSAGES_ROOT="${HOME}/pantheon/gods/messages"
DRY_RUN=false
DAYS=7

[ "${1:-}" = "--dry-run" ] && DRY_RUN=true

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

total_deleted=0
total_kept=0

for inbox in "$MESSAGES_ROOT"/*/; do
    [ -d "$inbox" ] || continue
    god=$(basename "$inbox")

    # Count old files
    old=$(find "$inbox" -maxdepth 1 -name "*.json" -type f -mtime +${DAYS} 2>/dev/null | wc -l)
    kept=$(find "$inbox" -maxdepth 1 -name "*.json" -type f -mtime -${DAYS} 2>/dev/null | wc -l)

    if [ "$old" -gt 0 ]; then
        if $DRY_RUN; then
            log "DRY-RUN ${god}: would delete ${old} files, keep ${kept}"
        else
            find "$inbox" -maxdepth 1 -name "*.json" -type f -mtime +${DAYS} -delete
            log "PRUNE ${god}: deleted ${old}, kept ${kept}"
        fi
        total_deleted=$((total_deleted + old))
        total_kept=$((total_kept + kept))
    fi
done

if $DRY_RUN; then
    log "DRY-RUN complete — would delete ${total_deleted} files across all gods, keep ${total_kept}"
else
    log "Prune complete — deleted ${total_deleted} files, kept ${total_kept}"
fi
