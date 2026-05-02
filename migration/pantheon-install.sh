#!/usr/bin/env bash
# =============================================================================
# Pantheon Migration Install Script
# Run this on the NEW (Beelink) machine after extracting the migration tarball.
#
# WHAT IT DOES:
#   1. Installs system packages (git, curl, python3, nodejs, npm, bun, build tools)
#   2. Installs Ollama (local LLM endpoint)
#   3. Installs Hermes Agent
#   4. Restores Hermes profiles (hephaestus + apollo)
#   5. Clones and builds AionUi
#   6. Restores Pantheon repo + Athenaeum + shared state
#   7. Installs systemd services and starts everything
#
# USAGE:
#   ./pantheon-install.sh [--gpg-passphrase PASSPHRASE]
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Config — adjust these if your local user is NOT 'konan'
# ---------------------------------------------------------------------------
USER_NAME="${USER:-konan}"
HOME_DIR="$HOME"
PANTHEON_REPO="$HOME/pantheon"
ATHENAEUM_DIR="$HOME/athenaeum"
HERMES_PROFILES_DIR="$HOME/.hermes/profiles"
PANTHEON_STATE_DIR="$HOME/.hermes/pantheon"
AIONUI_DIR="$HOME/aionui"

# Extract arguments
# (GPG passphrase is consumed before this script runs via README instructions)

# Find the migration data directory
MIGRATION_DIR=""
if [ -d "$HOME/pantheon-migration" ]; then
    MIGRATION_DIR="$HOME/pantheon-migration"
elif [ -d "$(pwd)/pantheon-migration" ]; then
    MIGRATION_DIR="$(pwd)/pantheon-migration"
fi

if [ -z "$MIGRATION_DIR" ]; then
    echo "[ERROR] Could not find pantheon-migration directory."
    echo "        Run: tar xzf pantheon-migration.tar.gz.gpg first"
    exit 1
fi

LOG_FILE="$HOME/pantheon-install.log"
exec >> "$LOG_FILE" 2>&1
echo "=== Pantheon Install Started at $(date) ==="

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
log_step()  { echo "&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&"; echo "STEP: $1"; echo "&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&"; }
log_info()  { echo "[INFO]  $1"; }
log_warn()  { echo "[WARN]  $1"; }
log_error() { echo "[ERROR] $1"; }

die() { log_error "$1"; exit 1; }

# ---------------------------------------------------------------------------
# STEP 0: Sanity checks
# ---------------------------------------------------------------------------
if [ "$EUID" -eq 0 ]; then
    die "Do not run as root. This script installs under the current user ($USER_NAME)."
fi

log_step "0/11: Sanity checks"
log_info "User: $USER_NAME, Home: $HOME_DIR"
log_info "Migration dir: $MIGRATION_DIR"

# ---------------------------------------------------------------------------
# STEP 1: System packages
# ---------------------------------------------------------------------------
log_step "1/11: Installing system packages"

sudo apt-get update -qq
sudo apt-get install -y \
    curl git wget unzip build-essential \
    python3 python3-pip python3-venv \
    nodejs npm pkg-config \
    gnupg2 ca-certificates lsof jq \
    sqlite3 libsqlite3-dev \
    ffmpeg imagemagick \
    >> "$LOG_FILE" 2>&1

# Install bun (JavaScript bundler used by AionUi)
if ! command -v bun &>/dev/null; then
    log_info "Installing bun..."
    curl -fsSL https://bun.sh/install | bash
    export PATH="$HOME/.bun/bin:$PATH"
fi

# Install fnm (Fast Node Manager) for managing Node.js versions
if ! command -v fnm &>/dev/null; then
    log_info "Installing fnm..."
    curl -fsSL https://fnm.vercel.app/install | bash
    export PATH="$HOME/.local/share/fnm:$PATH"
    eval "$(fnm env)"
fi

# Fix ~/.local/bin on PATH
if ! grep -q '\.local/bin' ~/.bashrc 2>/dev/null; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
fi
export PATH="$HOME/.local/bin:$PATH"

# ---------------------------------------------------------------------------
# STEP 2: Ollama (local LLM endpoint)
# ---------------------------------------------------------------------------
log_step "2/11: Installing Ollama"

if ! command -v ollama &>/dev/null; then
    log_info "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh >> "$LOG_FILE" 2>&1
else
    log_info "Ollama already installed."
fi

# Pull the default model used by Hephaestus
if [ -f "$MIGRATION_DIR/ollama-models.txt" ]; then
    log_info "Ollama models from source machine:"
    cat "$MIGRATION_DIR/ollama-models.txt" >> "$LOG_FILE"
    # Optionally pull them on the Beelink:
    # while read -r model _; do
    #   [ -n "$model" ] && ollama pull "$model" &>/dev/null
    # done < "$MIGRATION_DIR/ollama-models.txt"
fi

# Start ollama as a user service
systemctl --user enable ollama 2>/dev/null || true
systemctl --user start ollama 2>/dev/null || true

# ---------------------------------------------------------------------------
# STEP 3: Hermes Agent
# ---------------------------------------------------------------------------
log_step "3/11: Installing Hermes Agent"

if ! command -v hermes &>/dev/null; then
    log_info "Running Hermes install script..."
    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash >> "$LOG_FILE" 2>&1
else
    log_info "Hermes already installed at: $(which hermes)"
fi

# Verify
if ! command -v hermes &>/dev/null; then
    die "Hermes installation failed. Check $LOG_FILE"
fi

# ---------------------------------------------------------------------------
# STEP 4: Restore Hermes profiles
# ---------------------------------------------------------------------------
log_step "4/11: Restoring Hermes profiles"

# NOTE: Hermes creates a 'default' profile on first run. We replace it
# conditionally, or just create our own named profiles.

# Ensure the global .env exists
if [ ! -f "$HOME/.hermes/.env" ] && [ -f "$MIGRATION_DIR/profiles/hephaestus/.env" ]; then
    # We don't blindly copy the global .env — it's not in the export.
    # Instead, instruct the user to manually set it after install.
    log_warn "Global Hermes .env not found. You'll need to set OPENROUTER_API_KEY etc."
fi

for profile in hephaestus apollo; do
    src="$MIGRATION_DIR/profiles/$profile"
    dst="$HERMES_PROFILES_DIR/$profile"

    if [ ! -d "$src" ]; then
        log_warn "Source profile $profile not found in migration data, skipping."
        continue
    fi

    if [ -d "$dst" ]; then
        log_warn "Profile $profile already exists. Backing up: ${dst}.backup"
        mv "$dst" "${dst}.backup"
    fi

    log_info "Restoring profile: $profile"
    mkdir -p "$dst"
    cp -a "$src/"* "$dst/" 2>/dev/null || true

    # Rebuild the sandbox home with proper symlinks (Hermes normally does this)
    # We don't need to do anything special — Hermes handles sandbox creation

done

# ---------------------------------------------------------------------------
# STEP 5: Restore Pantheon repo + Athenaeum + shared state
# ---------------------------------------------------------------------------
log_step "5/11: Restoring Pantheon ecosystem data"

# --- Pantheon repo ---
log_info "Restoring Pantheon repository ..."
if [ -d "$MIGRATION_DIR/pantheon/.git" ]; then
    rm -rf "$PANTHEON_REPO" 2>/dev/null || true
    cp -a "$MIGRATION_DIR/pantheon" "$PANTHEON_REPO"
    log_info "Pantheon repo restored."
else
    log_warn "Pantheon .git export missing. Will re-clone from GitHub."
    git clone git@github.com:Duskript/Pantheon-Core.git "$PANTHEON_REPO"
fi

# --- Athenaeum ---
log_info "Restoring Athenaeum ..."
rm -rf "$ATHENAEUM_DIR" 2>/dev/null || true
cp -a "$MIGRATION_DIR/athenaeum" "$ATHENAEUM_DIR"
log_info "Athenaeum restored ($(du -sh $ATHENAEUM_DIR | cut -f1))."

# --- Shared Pantheon state (graph, heartbeat, ChromaDB) ---
log_info "Restoring Pantheon shared state ..."
mkdir -p "$PANTHEON_STATE_DIR"
if [ -d "$MIGRATION_DIR/shared-state" ] && [ "$(ls -A $MIGRATION_DIR/shared-state)" ]; then
    cp -a "$MIGRATION_DIR/shared-state/"* "$PANTHEON_STATE_DIR/"
    log_info "Shared state restored."
else
    log_warn "No shared state found in migration data. Will regenerate on first use."
fi

# --- SSH keys ---
log_info "Restoring SSH keys ..."
if [ -f "$MIGRATION_DIR/ssh/github_pantheon" ]; then
    mkdir -p "$HOME/.ssh"
    chmod 700 "$HOME/.ssh"
    cp -a "$MIGRATION_DIR/ssh/github_pantheon" "$HOME/.ssh/"
    cp -a "$MIGRATION_DIR/ssh/github_pantheon.pub" "$HOME/.ssh/"
    cp -a "$MIGRATION_DIR/ssh/config" "$HOME/.ssh/" 2>/dev/null || true
    cp -a "$MIGRATION_DIR/ssh/known_hosts" "$HOME/.ssh/" 2>/dev/null || true
    chmod 600 "$HOME/.ssh/github_pantheon"
    log_info "SSH keys restored."
fi

# ---------------------------------------------------------------------------
# STEP 6: Verify Python dependencies for Pantheon
# ---------------------------------------------------------------------------
log_step "6/11: Installing Pantheon Python dependencies"

python3 -m pip install --user \
    mcp chromadb pyyaml httpx \
    >> "$LOG_FILE" 2>&1

log_info "Python deps installed."

# ---------------------------------------------------------------------------
# STEP 7: Ollama model pull (optional — auto-pull configured models)
# ---------------------------------------------------------------------------
log_step "7/11: Checking Ollama models"

# Wait a moment for ollama service to warm up
sleep 3
if [ -f "$MIGRATION_DIR/ollama-models.txt" ]; then
    log_info "Pulling models from source machine list..."
    while IFS= read -r line; do
        model_name="$(echo "$line" | awk '{print $1}')"
        [ -n "$model_name" ] && [ "$model_name" != "NAME" ] && ollama pull "$model_name" &>/dev/null
    done < "$MIGRATION_DIR/ollama-models.txt"
else
    log_info "No ollama-models.txt found — skipping auto-pull."
fi

# ---------------------------------------------------------------------------
# STEP 8: AionUi
# ---------------------------------------------------------------------------
log_step "8/11: Installing AionUi"

# Clone your AionUi fork
if [ ! -d "$AIONUI_DIR/.git" ]; then
    log_info "Cloning AionUi (Duskript/AionUi fork)..."
    mkdir -p "$AIONUI_DIR"
    git clone git@github.com:Duskript/AionUi.git "$AIONUI_DIR" &>/dev/null || git clone https://github.com/Duskript/AionUi.git "$AIONUI_DIR"
else
    log_info "AionUi already cloned."
fi

cd "$AIONUI_DIR"

# Install dependencies
log_info "Running npm install ..."
npm install >> "$LOG_FILE" 2>&1

# Build the standalone server backend
log_info "Building AionUi server backend ..."
npm run build:server >> "$LOG_FILE" 2>&1

# Build the web renderer (the React UI bundle — REQUIRED or 502)
log_info "Building AionUi web renderer ..."
npm run build:renderer:web >> "$LOG_FILE" 2>&1

# Install bun globally (needed by AionUi internals)
if ! command -v bun &>/dev/null; then
    log_warn "bun not found after install. Some AionUi tasks may fail."
fi

log_info "AionUi build complete."

# ---------------------------------------------------------------------------
# STEP 9: Systemd services
# ---------------------------------------------------------------------------
log_step "9/11: Installing systemd user services"

SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"

# --- AionUi service ---
cat > "$SYSTEMD_USER_DIR/aionui.service" << 'EOF'
[Unit]
Description=AionUi Web Server
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/aionui
Environment=PATH=%h/.bun/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=%h
ExecStart=/usr/bin/node %h/aionui/dist-server/server.mjs
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

# --- Pantheon MCP server service ---
cat > "$SYSTEMD_USER_DIR/pantheon-mcp.service" << 'EOF'
[Unit]
Description=Pantheon MCP Server
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/pantheon/pantheon-core
Environment=PATH=/usr/local/bin:/usr/bin:/bin
Environment=HOME=%h
ExecStart=/usr/bin/python3 %h/pantheon/pantheon-core/mcp_server.py --port 8010
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

# Enable user systemd persistence across SSH logout
log_info "Enabling systemd linger for user-level services ..."
sudo loginctl enable-linger "$USER_NAME" &>/dev/null || log_warn "Could not enable linger — services will die on SSH logout."

# Reload systemd
systemctl --user daemon-reload

# Start MCP server
log_info "Starting Pantheon MCP server ..."
if systemctl --user start pantheon-mcp.service; then
    log_info "MCP server started."
else
    log_warn "MCP server failed to start. Will retry after profile setup."
fi

# Start AionUi
log_info "Starting AionUi ..."
if systemctl --user start aionui.service; then
    log_info "AionUi started."
else
    log_warn "AionUi failed to start. Will retry after profile setup."
fi

# Enable autostart
systemctl --user enable pantheon-mcp.service &>/dev/null || true
systemctl --user enable aionui.service &>/dev/null || true

# ---------------------------------------------------------------------------
# STEP 10: Enable Pantheon plugin in Hermes profiles
# ---------------------------------------------------------------------------
log_step "10/11: Enabling Pantheon plugin in Hermes profiles"

for profile in hephaestus apollo; do
    if [ -d "$HERMES_PROFILES_DIR/$profile" ]; then
        log_info "Enabling pantheon plugin for profile: $profile"
        # The plugin files are already copied, but may need enabling
        hermes -p "$profile" plugins enable pantheon 2>> "$LOG_FILE" || log_warn "Plugin enable for $profile had issues."
    fi
done

# ---------------------------------------------------------------------------
# STEP 11: Verify and report
# ---------------------------------------------------------------------------
log_step "11/11: Final verification"

# Restart services once more now that everything is in place
systemctl --user restart pantheon-mcp.service &>/dev/null || true
systemctl --user restart aionui.service &>/dev/null || true

sleep 2

# Quick health checks
MCP_OK=false
AIONUI_OK=false
OLLAMA_OK=false
HERMES_OK=false

if curl -fsS http://127.0.0.1:8010/mcp \
    -X POST -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}},"id":1}' \
    -o /dev/null -w "%{http_code}" 2>/dev/null | grep -q "200"; then
    MCP_OK=true
fi

if curl -fsS http://127.0.0.1:3000 -o /dev/null -w "%{http_code}" 2>/dev/null | grep -q "200"; then
    AIONUI_OK=true
fi

if systemctl --user is-active ollama &>/dev/null; then
    OLLAMA_OK=true
fi

if command -v hermes &>/dev/null; then
    HERMES_OK=true
fi

# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------
echo ""
echo "  ╔═══════════════════════════════════════════════════════════════════════╗"
echo "  ║  Pantheon Migration — Install Complete                                ║"
echo "  ╚═══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Services status:"
echo "    ✓ Pantheon MCP Server    : http://127.0.0.1:8010/mcp      $($MCP_OK     && echo "UP" || echo "CHECK LOGS")"
echo "    ✓ AionUi Web UI          : http://pantheon.local:3000    $($AIONUI_OK && echo "UP" || echo "CHECK LOGS")"
echo "    ✓ Ollama                 : http://127.0.0.1:11434         $($OLLAMA_OK && echo "UP" || echo "CHECK LOGS")"
echo "    ✓ Hermes Agent CLI        : $($HERMES_OK && echo "OK" || echo "MISSING")"
echo ""
echo "  Next Steps:"
echo "    1. Open AionUi in browser: http://$(hostname -I | awk '{print $1}' | head -1):3000"
echo "    2. In AionUi Settings → MCP Servers → Add:"
echo "         Name: pantheon"
echo "         URL:  http://127.0.0.1:8010/mcp"
echo "    3. If profiles need secrets (OpenRouter key, bot tokens):"
echo "         ~/.hermes/profiles/hephaestus/.env"
echo "         ~/.hermes/profiles/apollo/.env"
echo "         ~/.hermes/.env"
echo "    4. Start Hermes gateways (per profile):"
echo "         hermes -p hephaestus gateway run"
echo "         hermes -p apollo gateway run"
echo "    5. To start gateways as systemd services:"
echo "         systemctl --user start hermes-gateway"
echo "         systemctl --user start hermes-gateway-hephaestus"
echo ""
echo "  Logs are in: $LOG_FILE"
echo ""
echo "  systemd control:"
echo "    systemctl --user status pantheon-mcp aionui"
echo "    systemctl --user restart pantheon-mcp aionui"
echo "    journalctl --user -u pantheon-mcp -u aionui --no-pager -f"
echo ""

exit 0

