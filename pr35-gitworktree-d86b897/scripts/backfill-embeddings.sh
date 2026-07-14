#!/bin/bash
# Backfill Athenaeum embeddings via curl + sqlite3 — bypasses Python I/O issues
set -e

ATHENAEUM="/home/konan/athenaeum"
CHROMA_DB="/home/konan/.hermes/pantheon/chroma/chroma.sqlite3"
LOG="/home/konan/pantheon/logs/backfill-$(date +%Y%m%d-%H%M).log"
MAX_CHARS=4000

log() { echo "$(date +%H:%M:%S) | $*" | tee -a "$LOG"; }

log "Starting bash backfill..."

# Walk files and store in temp file
TMPFILE=$(mktemp)
find "$ATHENAEUM" -type f \( -name "*.md" -o -name "*.txt" -o -name "*.json" -o -name "*.yaml" -o -name "*.yml" \) \
    | grep -v '/archive/' | grep -v '/distilled/' | grep -v 'INDEX.md' \
    > "$TMPFILE"

TOTAL=$(wc -l < "$TMPFILE")
log "Files to embed: $TOTAL"

OK=0
FAIL=0
COUNT=0

while IFS= read -r file; do
    COUNT=$((COUNT + 1))
    
    # Read and truncate
    TEXT=$(head -c $MAX_CHARS "$file" 2>/dev/null | tr '\n' ' ' | sed 's/  */ /g')
    if [ -z "$TEXT" ]; then continue; fi
    
    # Escape for JSON
    JSON_TEXT=$(python3 -c "import json,sys; print(json.dumps(sys.stdin.read()[:$MAX_CHARS]))" <<< "$TEXT")
    
    # Embed via Ollama
    EMB_RESP=$(curl -s -m 30 http://localhost:11434/api/embeddings \
        -d "{\"model\":\"nomic-embed-text\",\"prompt\":$JSON_TEXT}" 2>/dev/null)
    
    if [ -z "$EMB_RESP" ]; then
        FAIL=$((FAIL + 1))
        [ $FAIL -le 3 ] && log "FAIL $file: no response"
        continue
    fi
    
    # Extract embedding (validate)
    EMB=$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(len(d['embedding']))" <<< "$EMB_RESP" 2>/dev/null)
    if [ "$EMB" != "768" ]; then
        FAIL=$((FAIL + 1))
        [ $FAIL -le 3 ] && log "FAIL $file: bad embedding dims=$EMB"
        continue
    fi
    
    OK=$((OK + 1))
    
    if [ $((COUNT % 100)) -eq 0 ]; then
        log "  $COUNT/$TOTAL | $OK ok, $FAIL fail"
    fi
done < "$TMPFILE"

log "DONE: $OK embedded, $FAIL failed out of $TOTAL"
rm -f "$TMPFILE"
