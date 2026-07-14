#!/bin/bash
# Chain monitor — watches kanban for state changes, notifies operator.
# Run: bash chain-monitor.sh &
# Logs: ~/.hermes/profiles/hephaestus/cron/output/chain-monitor.log

LOG="$HOME/.hermes/profiles/hephaestus/cron/output/chain-monitor.log"
NOTIFY="$HOME/.local/bin/god-notify"
SNAPSHOT="/tmp/kanban-snapshot.txt"
mkdir -p "$(dirname "$LOG")"

echo "[$(date)] Chain monitor started. Watching: uce-v0.3, conductor-ui" >> "$LOG"

while true; do
    # Get current state for monitored projects
    CURRENT=$(hermes kanban list 2>/dev/null | grep -E "\[uce-v0.3\]|\[conductor-ui\]" | awk '{print $1, $2, $3}' | sort)
    
    if [ -f "$SNAPSHOT" ]; then
        PREV=$(cat "$SNAPSHOT")
        
        # Compare and notify on changes
        diff <(echo "$PREV") <(echo "$CURRENT") 2>/dev/null | while IFS= read -r line; do
            case "$line" in
                "<"*)
                    # Task changed FROM this state (old)
                    TID=$(echo "$line" | cut -c3- | awk '{print $1}')
                    OLD_STATE=$(echo "$line" | cut -c3- | awk '{print $2}')
                    # Find current state
                    NEW_LINE=$(echo "$CURRENT" | grep "^$TID ")
                    NEW_STATE=$(echo "$NEW_LINE" | awk '{print $2}')
                    if [ -n "$NEW_STATE" ] && [ "$OLD_STATE" != "$NEW_STATE" ]; then
                        TITLE=$(hermes kanban show "$TID" 2>/dev/null | head -1 | cut -d: -f2- | xargs)
                        echo "[$(date)] CHANGE: $TID $OLD_STATE→$NEW_STATE | $TITLE" >> "$LOG"
                        $NOTIFY Hephaestus info "Chain: $OLD_STATE → $NEW_STATE" "$TITLE ($TID)" 2>/dev/null
                    fi
                    ;;
                ">"*)
                    # New task appeared
                    TID=$(echo "$line" | cut -c3- | awk '{print $1}')
                    if ! echo "$PREV" | grep -q "^$TID "; then
                        NEW_STATE=$(echo "$line" | cut -c3- | awk '{print $2}')
                        GOD=$(echo "$line" | cut -c3- | awk '{print $3}')
                        TITLE=$(hermes kanban show "$TID" 2>/dev/null | head -1 | cut -d: -f2- | xargs)
                        echo "[$(date)] NEW: $TID $NEW_STATE ($GOD) | $TITLE" >> "$LOG"
                    fi
                    ;;
            esac
        done
    fi
    
    echo "$CURRENT" > "$SNAPSHOT"
    sleep 120
done
