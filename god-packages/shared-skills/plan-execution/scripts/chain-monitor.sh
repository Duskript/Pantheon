#!/bin/bash
# Chain monitor — watches kanban for state changes, notifies operator via god-notify.
# Run: bash chain-monitor.sh &
# Polls every 120s. Compares kanban snapshot against previous, diffs on change.
# Logs to ~/.hermes/profiles/hephaestus/cron/output/chain-monitor.log
# Customize PROJECT_PREFIXES below for the chains you want to watch.

LOG="$HOME/.hermes/profiles/hephaestus/cron/output/chain-monitor.log"
NOTIFY="$HOME/.local/bin/god-notify"
SNAPSHOT="/tmp/kanban-snapshot.txt"
PROJECT_PREFIXES="uce-v0.3|conductor-ui"

mkdir -p "$(dirname "$LOG")"

echo "[$(date)] Chain monitor started. Watching: $PROJECT_PREFIXES" >> "$LOG"

while true; do
    CURRENT=$(hermes kanban list 2>/dev/null | grep -E "\[($PROJECT_PREFIXES)\]" | awk '{print $1, $2, $3}' | sort)
    
    if [ -f "$SNAPSHOT" ]; then
        PREV=$(cat "$SNAPSHOT")
        
        diff <(echo "$PREV") <(echo "$CURRENT") 2>/dev/null | while IFS= read -r line; do
            case "$line" in
                "<"*)
                    TID=$(echo "$line" | cut -c3- | awk '{print $1}')
                    OLD_STATE=$(echo "$line" | cut -c3- | awk '{print $2}')
                    NEW_LINE=$(echo "$CURRENT" | grep "^$TID ")
                    NEW_STATE=$(echo "$NEW_LINE" | awk '{print $2}')
                    if [ -n "$NEW_STATE" ] && [ "$OLD_STATE" != "$NEW_STATE" ]; then
                        TITLE=$(hermes kanban show "$TID" 2>/dev/null | head -1 | cut -d: -f2- | xargs)
                        echo "[$(date)] CHANGE: $TID $OLD_STATE→$NEW_STATE | $TITLE" >> "$LOG"
                        $NOTIFY Hephaestus info "Chain: $OLD_STATE → $NEW_STATE" "$TITLE ($TID)" 2>/dev/null
                    fi
                    ;;
                ">"*)
                    TID=$(echo "$line" | cut -c3- | awk '{print $1}')
                    if ! echo "$PREV" | grep -q "^$TID "; then
                        NEW_STATE=$(echo "$line" | cut -c3- | awk '{print $2}')
                        TITLE=$(hermes kanban show "$TID" 2>/dev/null | head -1 | cut -d: -f2- | xargs)
                        echo "[$(date)] NEW: $TID $NEW_STATE | $TITLE" >> "$LOG"
                    fi
                    ;;
            esac
        done
    fi
    
    echo "$CURRENT" > "$SNAPSHOT"
    sleep 120
done
