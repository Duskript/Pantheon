#!/usr/bin/env bash
# =============================================================================
# Pantheon Migration Export — run this on the OLD machine
# =============================================================================
# Creates a tarball of everything outside git that Pantheon needs:
#   - ~/athenaeum/ (your knowledge store, 11 Codices, ~7.5MB)
#   - ~/.hermes/pantheon/ (ChromaDB vector store ~40MB, graph DB, ingest rules)
#   - ~/.hermes/config.yaml, .env, SOUL.md (root Hermes config)
#   - Both profiles (hephaestus, apollo) — configs, state, memories, plugins
#
# Creates a tarball with paths relative to / so tar -xpf extracts to the
# correct locations on the new machine.
#
# Usage:
#   bash scripts/migrate-export.sh
#
# Output: pantheon-migration-YYYY-MM-DD.tar.zst (or .gz if zstd unavailable)
# =============================================================================

set -euo pipefail

TIMESTAMP=$(date +%Y-%m-%d)
TARBALL="$HOME/pantheon-migration-$TIMESTAMP.tar"
USERNAME=$(whoami)

echo "═══ Pantheon Migration Export ═══"
echo "Source: $USERNAME@$(hostname)"
echo "Date:   $TIMESTAMP"
echo ""

# ── Verify key paths exist ──────────────────────────────────────────────────
echo "→ Checking paths..."

declare -A PATHS
PATHS["Athenaeum"]="$HOME/athenaeum"
PATHS["Hermes root"]="$HOME/.hermes"
PATHS["Pantheon store"]="$HOME/.hermes/pantheon"
PATHS["Profile: hephaestus"]="$HOME/.hermes/profiles/hephaestus"
PATHS["Profile: apollo"]="$HOME/.hermes/profiles/apollo"

MISSING=""
for label in "${!PATHS[@]}"; do
    path="${PATHS[$label]}"
    if [ -d "$path" ] || [ -f "$path" ]; then
        echo "  ✓ $label"
    else
        echo "  ⚠ MISSING: $label ($path)"
        MISSING="$MISSING $label "
    fi
done

if [ -n "$MISSING" ]; then
    echo ""
    echo "ERROR: Some paths are missing. Aborting."
    exit 1
fi

# ── Check for compression tools ─────────────────────────────────────────────
COMPRESSOR="gzip"
EXT=".gz"
if command -v zstd &>/dev/null; then
    COMPRESSOR="zstd -T0 -10"
    EXT=".zst"
    echo "→ Using zstd compression (fast + high ratio)"
else
    echo "→ zstd not found, using gzip"
fi

# ── Build the tarball ───────────────────────────────────────────────────────
echo ""
echo "→ Building tarball..."
echo "  Target: $(basename "$TARBALL$EXT")"
echo ""

rm -f "$TARBALL" "$TARBALL$EXT"

# Tar from / using relative paths so extracts cleanly anywhere
# Strip the leading / from absolute paths by using -C /
tar --create \
    --file "$TARBALL" \
    --exclude="cache" \
    --exclude="logs" \
    --exclude="__pycache__" \
    --exclude="*.pyc" \
    --exclude=".tick.lock" \
    --exclude="gateway.lock" \
    --exclude="gateway.pid" \
    --exclude="gateway_state.json" \
    --exclude="gateway-run.log" \
    --exclude="auth.lock" \
    --exclude="sessions/sessions.json" \
    --exclude="*.jsonl" \
    --exclude=".skills_prompt_snapshot.json" \
    --exclude=".curator_state" \
    --exclude=".usage.json" \
    --exclude="context_length_cache.yaml" \
    --exclude="channel_directory.json" \
    --exclude="processes.json" \
    --exclude="cron/.tick.lock" \
    --exclude="cron/jobs.json" \
    --exclude="cron/output" \
    --exclude="audio_cache" \
    --exclude="image_cache" \
    --exclude="images" \
    --exclude="pastes" \
    --exclude="sandboxes" \
    --exclude="pairing" \
    --exclude="node" \
    --exclude="hooks" \
    --exclude="bin" \
    --exclude="plugins/pantheon/__pycache__" \
    -C / \
    "home/$USERNAME/athenaeum" \
    "home/$USERNAME/.hermes/pantheon" \
    "home/$USERNAME/.hermes/config.yaml" \
    "home/$USERNAME/.hermes/SOUL.md" \
    "home/$USERNAME/.hermes/.env" \
    "home/$USERNAME/.hermes/profiles/hephaestus/config.yaml" \
    "home/$USERNAME/.hermes/profiles/hephaestus/.env" \
    "home/$USERNAME/.hermes/profiles/hephaestus/SOUL.md" \
    "home/$USERNAME/.hermes/profiles/hephaestus/state.db" \
    "home/$USERNAME/.hermes/profiles/hephaestus/memories" \
    "home/$USERNAME/.hermes/profiles/hephaestus/plugins" \
    "home/$USERNAME/.hermes/profiles/hephaestus/sessions" \
    "home/$USERNAME/.hermes/profiles/hephaestus/cron" \
    "home/$USERNAME/.hermes/profiles/apollo/config.yaml" \
    "home/$USERNAME/.hermes/profiles/apollo/.env" \
    "home/$USERNAME/.hermes/profiles/apollo/SOUL.md" \
    "home/$USERNAME/.hermes/profiles/apollo/state.db" \
    "home/$USERNAME/.hermes/profiles/apollo/memories" \
    "home/$USERNAME/.hermes/profiles/apollo/plugins" \
    "home/$USERNAME/.hermes/profiles/apollo/sessions" \
    "home/$USERNAME/.hermes/profiles/apollo/cron" \
    2>&1

# ── Compress ────────────────────────────────────────────────────────────────
echo ""
echo "→ Compressing..."
$COMPRESSOR "$TARBALL"

FINAL="$TARBALL$EXT"
FINAL_SIZE=$(du -h "$FINAL" | awk '{print $1}')

cat >> "$FINAL.manifest" <<EOF
Pantheon Migration Export
Exported: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Source:   $USERNAME@$(hostname)
Hermes:   $(hermes --version 2>/dev/null || echo "unknown")
Ollama:   $(ollama --version 2>/dev/null || echo "unknown")
Size:     $FINAL_SIZE

Contents:
  home/$USERNAME/athenaeum/        — Knowledge store (11 Codices)
  home/$USERNAME/.hermes/pantheon/ — ChromaDB + graph + ingest rules
  home/$USERNAME/.hermes/config.yaml, .env, SOUL.md
  home/$USERNAME/.hermes/profiles/hephaestus/  — Your profile
  home/$USERNAME/.hermes/profiles/apollo/      — Apollo profile

Restore instructions: https://github.com/Duskript/Pantheon-Core#migration
EOF

echo ""
echo "═══ Export complete ═══"
echo "File:      $FINAL"
echo "Size:      $FINAL_SIZE"
echo "Manifest:  $FINAL.manifest"
echo ""
echo "Next steps:"
echo ""
echo "  1. Copy $(basename "$FINAL$EXT") to the NEW Ubuntu machine"
echo "     (USB drive, scp, rsync, whatever works)"
echo ""
echo "  2. On the NEW machine, extract:"
echo "     tar -I $COMPRESSOR -xpf $(basename "$FINAL$EXT") -C /"
echo ""
echo "  3. Run the restore script:"
echo "     cd ~/pantheon && bash scripts/migrate-restore.sh"
echo ""
echo "  4. Add SSH key, sign in to Ollama, start gateways"
