#!/usr/bin/env bash
# =============================================================================
# Pantheon Migration Export Script
# Run this on the CURRENT (source) machine.
# Creates an encrypted tarball with everything needed to reconstruct Pantheon
# on the Beelink.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
USER_NAME="konan"
EXPORT_DIR="$(mktemp -d /tmp/pantheon-export-XXXXXX)"
OUTPUT_FILE="$HOME/pantheon-migration.tar.gz"
ENCRYPTED_FILE="$HOME/pantheon-migration.tar.gz.gpg"

# If you want a passphrase prompt instead of env var, comment out the next line
# and uncomment the GPG encrypt line that uses --symmetric --cipher-algo AES256
GPG_PASSPHRASE="${PANTHEON_MIGRATION_PASSPHRASE:-PantheonMigration2026}"

# ---------------------------------------------------------------------------
# Validate prerequisites
# ---------------------------------------------------------------------------
if ! command -v gpg &>/dev/null; then
    echo "[ERROR] gpg not found. Install with: sudo apt install gnupg"
    exit 1
fi

if ! command -v tar &>/dev/null; then
    echo "[ERROR] tar not found."
    exit 1
fi

# ---------------------------------------------------------------------------
# Gather sources
# ---------------------------------------------------------------------------
echo "
╔═══════════════════════════════════════════════════════════════════════╗
║  Pantheon Migration Export                                            ║
╚═══════════════════════════════════════════════════════════════════════╝
"

PANTHEON_REPO="$HOME/pantheon"
ATHENAEUM_DIR="$HOME/athenaeum"
HERMES_PROFILES_DIR="$HOME/.hermes/profiles"
PANTHEON_STATE_DIR="$HOME/.hermes/pantheon"
AIONUI_DIR="$HOME/aionui"
SSH_DIR="$HOME/.ssh"

# Verify paths
for dir in "$PANTHEON_REPO" "$ATHENAEUM_DIR" "$HERMES_PROFILES_DIR"; do
    if [ ! -d "$dir" ]; then
        echo "[ERROR] Required directory missing: $dir"
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# Build export tree
# ---------------------------------------------------------------------------
echo "[1/6] Building export tree in $EXPORT_DIR ..."

mkdir -p "$EXPORT_DIR"/{pantheon,athenaeum,profiles,shared-state,ssh,cron-jobs,systemd}

# --- Pantheon repo (full clone via git archive to keep history) ------
echo "  → Exporting Pantheon repo ..."
cd "$PANTHEON_REPO"
git archive --format=tar HEAD | tar xf - -C "$EXPORT_DIR/pantheon/"
# Include the migration scripts themselves (they may be uncommitted)
cp -r "$PANTHEON_REPO/migration" "$EXPORT_DIR/pantheon/" 2>/dev/null || true
# Include the .git directory so the Beelink gets full history
cp -r "$PANTHEON_REPO/.git" "$EXPORT_DIR/pantheon/.git/"

# --- Athenaeum ---------------------------------------------------------
echo "  → Exporting Athenaeum ..."
cp -a "$ATHENAEUM_DIR/"* "$EXPORT_DIR/athenaeum/"

# --- Hermes profiles (hephaestus + apollo) ----------------------------
echo "  → Exporting Hermes profiles ..."
for profile in hephaestus apollo; do
    src="$HERMES_PROFILES_DIR/$profile"
    dst="$EXPORT_DIR/profiles/$profile"
    if [ ! -d "$src" ]; then
        echo "    [WARN] Profile $profile not found, skipping."
        continue
    fi
    echo "    → $profile ..."
    mkdir -p "$dst"
    # Copy everything EXCEPT rebuildable caches in the sandbox home/
    # We use tar with --exclude to skip the big stuff
    tar -cf - \
        --exclude='home/.cache' \
        --exclude='home/.npm' \
        --exclude='home/.bun' \
        --exclude='home/.ollama/models' \
        --exclude='home/.local/share/pnpm' \
        --exclude='home/.local/share/fnm' \
        --exclude='home/.config/Code' \
        --exclude='home/.config/google-chrome' \
        --exclude='home/.config/chromium' \
        --exclude='home/.pki' \
        --exclude='home/.thunderbird' \
        --exclude='home/.mozilla' \
        --exclude='*.log' \
        --exclude='__pycache__' \
        -C "$src" . \
        | tar -xf - -C "$dst"
done

# --- Shared Pantheon state (ChromaDB, graph, heartbeats, etc.) -------
echo "  → Exporting Pantheon shared state ..."
if [ -d "$PANTHEON_STATE_DIR" ]; then
    cp -a "$PANTHEON_STATE_DIR/"* "$EXPORT_DIR/shared-state/"
fi

# --- SSH keys (GitHub deploy key + config) ---------------------------
echo "  → Exporting SSH keys ..."
if [ -d "$SSH_DIR" ]; then
    # Only copy the Pantheon-specific key + config, not all personal keys
    cp -a "$SSH_DIR/config" "$EXPORT_DIR/ssh/" 2>/dev/null || true
    cp -a "$SSH_DIR/github_pantheon" "$EXPORT_DIR/ssh/" 2>/dev/null || true
    cp -a "$SSH_DIR/github_pantheon.pub" "$EXPORT_DIR/ssh/" 2>/dev/null || true
    cp -a "$SSH_DIR/known_hosts" "$EXPORT_DIR/ssh/" 2>/dev/null || true
fi

# --- System-wide cron jobs for Pantheon ------------------------------
echo "  → Exporting cron jobs ..."
export PANTHEON_CRON="$EXPORT_DIR/cron-jobs/pantheon-crontab.txt"
(crontab -l 2>/dev/null || true) | grep -i pantheon > "$PANTHEON_CRON" || true
if [ ! -s "$PANTHEON_CRON" ]; then
    # If no crontab entries matched, copy the scripts anyway as reference
    cp -a "$HOME/.hermes/profiles/hephaestus/cron"/* "$EXPORT_DIR/cron-jobs/" 2>/dev/null || true
fi

# --- AionUi build artifact -------------------------------------------
echo "  → Exporting AionUi build artifacts ..."
mkdir -p "$EXPORT_DIR/aionui"
# We DON'T export the full AionUi repo (it's large). Instead, export:
# 1. The .git ref so we know which commit to checkout
# 2. The built dist-server/ and out/renderer/ bundles
if [ -d "$AIONUI_DIR/.git" ]; then
    git -C "$AIONUI_DIR" rev-parse HEAD > "$EXPORT_DIR/aionui/AIONUI_COMMIT"
fi
if [ -d "$AIONUI_DIR/dist-server" ]; then
    cp -a "$AIONUI_DIR/dist-server" "$EXPORT_DIR/aionui/"
fi
if [ -d "$AIONUI_DIR/out/renderer" ]; then
    cp -a "$AIONUI_DIR/out/renderer" "$EXPORT_DIR/aionui/"
fi
# Also export package.json and lockfile for reproducibility
cp "$AIONUI_DIR/package.json" "$EXPORT_DIR/aionui/" 2>/dev/null || true
cp "$AIONUI_DIR/package-lock.json" "$EXPORT_DIR/aionui/" 2>/dev/null || true

# --- Ollama model list (reference, no models exported yet) -------------
if command -v ollama &>/dev/null; then
    ollama list > "$EXPORT_DIR/ollama-models.txt" 2>/dev/null || true
fi

# --- Environment reference (redacted) ----------------------------------
echo "  → Exporting environment reference ..."
cat > "$EXPORT_DIR/ENV_REFERENCE.md" << 'EOF'
# Environment Reference
Files with secrets that need manual setup on the new machine:

1. ~/.hermes/.env                 (Hermes global secrets: OpenRouter key, etc.)
2. ~/.hermes/profiles/hephaestus/.env  (Hephaestus bot tokens, Discord token)
3. ~/.hermes/profiles/apollo/.env    (Apollo bot tokens, Discord token)
4. ~/.ssh/github_pantheon         (GitHub deploy key — copied automatically)

The actual .env files ARE included in the encrypted tarball, but this doc
lists them for awareness.
EOF

# --- Metadata ----------------------------------------------------------
cat > "$EXPORT_DIR/META.json" << EOF
{
  "exported_at": "$(date -Iseconds)",
  "source_hostname": "$(hostname -f 2>/dev/null || hostname)",
  "source_user": "$USER_NAME",
  "pantheon_repo_sha": "$(cd $PANTHEON_REPO && git rev-parse HEAD)",
  "profiles_included": ["hephaestus", "apollo"],
  "services": {
    "pantheon_mcp": "$(systemctl --user is-active pantheon-mcp 2>/dev/null || echo 'unknown')",
    "hermes_gateway": "$(systemctl --user is-active hermes-gateway 2>/dev/null || echo 'unknown')",
    "hermes_gateway_hephaestus": "$(systemctl --user is-active hermes-gateway-hephaestus 2>/dev/null || echo 'unknown')"
  }
}
EOF

# ---------------------------------------------------------------------------
# Tar + Encrypt
# ---------------------------------------------------------------------------
echo "[2/6] Creating tarball ..."
tar -czf "$OUTPUT_FILE" -C "$EXPORT_DIR" .

echo "[3/6] Encrypting tarball ..."
# Use a GPG symmetric encryption with the passphrase
echo "$GPG_PASSPHRASE" | gpg \
    --batch --yes \
    --passphrase-fd 0 \
    --symmetric --cipher-algo AES256 \
    --output "$ENCRYPTED_FILE" \
    "$OUTPUT_FILE"

# Wipe the unencrypted tarball
shred -u "$OUTPUT_FILE" 2>/dev/null || rm -f "$OUTPUT_FILE"

# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------
FILE_SIZE=$(du -h "$ENCRYPTED_FILE" | cut -f1)

echo "
╔═══════════════════════════════════════════════════════════════════════╗
║  Export Complete                                                      ║
╚═══════════════════════════════════════════════════════════════════════╝

  Encrypted file: $ENCRYPTED_FILE
  Size:           $FILE_SIZE
  Passphrase:     (set via PANTHEON_MIGRATION_PASSPHRASE env var)
                    Default if unset: 'PantheonMigration2026'

Next steps:
  1. Transfer this file to the Beelink via USB or SCP.
  2. On the Beelink: tar xzf pantheon-migration.tar.gz.gpg
  3. Install with: ./pantheon-migration/pantheon-install.sh
  4. After confirmed working: shred -u pantheon-migration.tar.gz.gpg

  REMINDER: The old machine remains untouched until you confirm success.
"

# Cleanup temp
rm -rf "$EXPORT_DIR"
