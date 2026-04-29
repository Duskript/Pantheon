#!/usr/bin/env bash
# migrate-oracle-vault.sh
# Migrates existing ORACLE vault content into the correct Athenaeum Codex folders.
# Idempotent — never overwrites existing files, skips already-migrated content.
# Usage: ./scripts/migrate-oracle-vault.sh /path/to/oracle/vault [optional: /custom/athenaeum/path]

set -euo pipefail

# ─── Arguments ────────────────────────────────────────────────────────────────

if [ $# -lt 1 ]; then
    echo "Usage: $0 /path/to/oracle/vault [/path/to/athenaeum]"
    echo ""
    echo "  vault_path    Path to your existing ORACLE vault root"
    echo "  athenaeum     Optional. Defaults to ~/Pantheon/Athenaeum"
    exit 1
fi

VAULT_SRC="$(realpath "$1")"
ATHENAEUM_ROOT="${2:-$HOME/Pantheon/Athenaeum}"

# ─── Validate ─────────────────────────────────────────────────────────────────

if [ ! -d "$VAULT_SRC" ]; then
    echo "ERROR: Vault source not found: $VAULT_SRC"
    exit 1
fi

if [ ! -d "$ATHENAEUM_ROOT" ]; then
    echo "ERROR: Athenaeum not found at $ATHENAEUM_ROOT"
    echo "       Run init-athenaeum.sh first."
    exit 1
fi

# ─── Counters ─────────────────────────────────────────────────────────────────

migrated=0
skipped=0
missing_src=0

# ─── Migration log ────────────────────────────────────────────────────────────

LOG_FILE="$ATHENAEUM_ROOT/Codex-Pantheon/sessions/archive/migration-$(date -u +"%Y-%m-%dT%H%M%SZ").md"

log() {
    echo "$1"
    echo "$1" >> "$LOG_FILE"
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

migrate_dir() {
    local src="$1"
    local dest="$2"
    local label="$3"

    if [ ! -d "$src" ]; then
        echo "  [missing]  $label ($src — not found, skipping)"
        ((missing_src++)) || true
        log "MISSING  | $label | $src → $dest"
        return
    fi

    echo "  ▸ $label"
    echo "    src  : $src"
    echo "    dest : $dest"

    mkdir -p "$dest"

    local file_count=0
    local skip_count=0

    while IFS= read -r -d '' file; do
        rel="${file#$src/}"
        target="$dest/$rel"

        if [ -f "$target" ]; then
            ((skip_count++)) || true
            ((skipped++)) || true
            log "SKIPPED  | $label | $rel (already exists at destination)"
        else
            mkdir -p "$(dirname "$target")"
            cp "$file" "$target"
            ((file_count++)) || true
            ((migrated++)) || true
            log "MIGRATED | $label | $rel"
        fi
    done < <(find "$src" -type f -print0 2>/dev/null)

    echo "    moved: $file_count  skipped: $skip_count"
    echo ""
}

migrate_file() {
    local src="$1"
    local dest_dir="$2"
    local label="$3"

    if [ ! -f "$src" ]; then
        echo "  [missing]  $label ($src — not found, skipping)"
        ((missing_src++)) || true
        log "MISSING  | $label | $src"
        return
    fi

    mkdir -p "$dest_dir"
    local filename
    filename="$(basename "$src")"
    local target="$dest_dir/$filename"

    if [ -f "$target" ]; then
        echo "  [exists]   $label/$filename"
        ((skipped++)) || true
        log "SKIPPED  | $label | $filename (already exists)"
    else
        cp "$src" "$target"
        echo "  [migrated] $label/$filename"
        ((migrated++)) || true
        log "MIGRATED | $label | $filename"
    fi
}

# ─── Initialize log ───────────────────────────────────────────────────────────

mkdir -p "$(dirname "$LOG_FILE")"
cat > "$LOG_FILE" <<EOF
---
type: migration-log
source_vault: $VAULT_SRC
athenaeum: $ATHENAEUM_ROOT
timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
---

# ORACLE Migration Log

EOF

# ─── Run migration ────────────────────────────────────────────────────────────

echo ""
echo "━━━ ORACLE Vault Migration ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Source vault  : $VAULT_SRC"
echo "  Athenaeum     : $ATHENAEUM_ROOT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# vault/Lyrics/ → Athenaeum/Codex-SKC/lyrics/
migrate_dir \
    "$VAULT_SRC/Lyrics" \
    "$ATHENAEUM_ROOT/Codex-SKC/lyrics" \
    "vault/Lyrics → Codex-SKC/lyrics"

# vault/IT-Notes/ → Athenaeum/Codex-Infrastructure/
migrate_dir \
    "$VAULT_SRC/IT-Notes" \
    "$ATHENAEUM_ROOT/Codex-Infrastructure" \
    "vault/IT-Notes → Codex-Infrastructure"

# vault/Projects/ORACLE/ → Athenaeum/Codex-Pantheon/
migrate_dir \
    "$VAULT_SRC/Projects/ORACLE" \
    "$ATHENAEUM_ROOT/Codex-Pantheon" \
    "vault/Projects/ORACLE → Codex-Pantheon"

# vault/Projects/SKC/ → Athenaeum/Codex-SKC/style/
migrate_dir \
    "$VAULT_SRC/Projects/SKC" \
    "$ATHENAEUM_ROOT/Codex-SKC/style" \
    "vault/Projects/SKC → Codex-SKC/style"

# vault/Projects/CantorsTale/ → Athenaeum/Codex-Fiction/
migrate_dir \
    "$VAULT_SRC/Projects/CantorsTale" \
    "$ATHENAEUM_ROOT/Codex-Fiction/cantors-tale" \
    "vault/Projects/CantorsTale → Codex-Fiction/cantors-tale"

# vault/Sessions/ → Athenaeum/Codex-Pantheon/sessions/archive/
migrate_dir \
    "$VAULT_SRC/Sessions" \
    "$ATHENAEUM_ROOT/Codex-Pantheon/sessions/archive" \
    "vault/Sessions → Codex-Pantheon/sessions/archive"

# vault/Knowledge/ → Athenaeum/Codex-General/distilled/
# Note: Files with clear domain affinity should be manually moved to the appropriate
# Codex distilled folder after migration. Codex-General/distilled is the safe default.
migrate_dir \
    "$VAULT_SRC/Knowledge" \
    "$ATHENAEUM_ROOT/Codex-General/distilled" \
    "vault/Knowledge → Codex-General/distilled (review and redistribute manually)"

# vault/STL-Library/ → Athenaeum/Codex-General/
migrate_dir \
    "$VAULT_SRC/STL-Library" \
    "$ATHENAEUM_ROOT/Codex-General" \
    "vault/STL-Library → Codex-General"

# vault/Interests/ → Staging/inbox/
# Interests go to Staging — Mnemosyne will classify them
STAGING_INBOX="$(dirname "$ATHENAEUM_ROOT")/Staging/inbox"
migrate_dir \
    "$VAULT_SRC/Interests" \
    "$STAGING_INBOX" \
    "vault/Interests → Staging/inbox (Mnemosyne will classify)"

# ─── Summary ──────────────────────────────────────────────────────────────────

echo "━━━ Migration Summary ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Files migrated      : $migrated"
echo "  Files skipped       : $skipped (already existed at destination)"
echo "  Source dirs missing : $missing_src (vault folders not found)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Migration log written to:"
echo "  $LOG_FILE"
echo ""
echo "Post-migration notes:"
echo "  • vault/Knowledge files landed in Codex-General/distilled/"
echo "    Review and redistribute to appropriate Codex distilled folders."
echo "  • vault/Interests files landed in Staging/inbox/"
echo "    Mnemosyne will classify and route these automatically."
echo "  • Demeter will detect new Athenaeum files and trigger Mnemosyne"
echo "    re-embedding once Phase 1 background gods are running."
echo ""

# Append summary to log
log ""
log "## Summary"
log "Files migrated      : $migrated"
log "Files skipped       : $skipped"
log "Source dirs missing : $missing_src"
log ""
log "## Post-Migration Actions Required"
log "- Review Codex-General/distilled/ and redistribute Knowledge files"
log "- Staging/inbox/ contents will be classified by Mnemosyne once Phase 1 is running"
