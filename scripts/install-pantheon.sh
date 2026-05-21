#!/usr/bin/env bash
# =============================================================================
# Pantheon — One-Line Installer
# =============================================================================
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Duskript/Pantheon/main/scripts/install-pantheon.sh | sh
#
# Or if you prefer to inspect first:
#   curl -fsSL https://raw.githubusercontent.com/Duskript/Pantheon/main/scripts/install-pantheon.sh -o /tmp/install-pantheon.sh
#   bash /tmp/install-pantheon.sh
#
# What it does:
#   1. Installs Hermes Agent (if not already installed)
#   2. Clones Pantheon to ~/pantheon (if not already cloned)
#   3. Creates ~/pantheon/.env from .env.example (if not exists)
#   4. Installs core gods (Hermes + Hephaestus)
#   5. Deploys Pantheon plugins (symlinks to ~/.hermes/plugins/)
#   6. Configures memory provider + enables plugins in config
#   7. Creates Pantheon cron jobs (digests, Ichor, Hades, etc.)
#   8. Installs systemd services (WebUI, MCP server, Demeter watcher)
#   9. Sets up and starts the gateway
#  10. Opens the Welcome Wizard in your browser
# =============================================================================

set -e

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

# ── Detect platform ─────────────────────────────────────────────────────────
detect_platform() {
  case "$(uname -s)" in
    Linux*)  echo "linux" ;;
    Darwin*) echo "macos" ;;
    *)       echo "unknown" ;;
  esac
}

PLATFORM=$(detect_platform)
PANTHEON_DIR="${HOME}/pantheon"
HERMES_DIR="${HOME}/.hermes"

# ── Header ──────────────────────────────────────────────────────────────────
clear 2>/dev/null || true
cat << 'EOF'

 ╔══════════════════════════════════════════════════════════╗
 ║                     PANTHEON                             ║
 ║              Your Personal AI Family                     ║
 ╚══════════════════════════════════════════════════════════╝

EOF
echo ""

# ── Step 1: Check prerequisites ─────────────────────────────────────────────
header "Prerequisites"

for cmd in curl git python3; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$cmd found"
  else
    err "$cmd is required but not installed."
    case "$cmd" in
      curl) warn "Install: apt install curl (Debian) / brew install curl (macOS)" ;;
      git)  warn "Install: apt install git (Debian) / brew install git (macOS)" ;;
      python3) warn "Install: apt install python3 (Debian) / brew install python3 (macOS)" ;;
    esac
    exit 1
  fi
done

# ── Step 2: Install Hermes Agent ────────────────────────────────────────────
header "Hermes Agent"

if command -v hermes >/dev/null 2>&1; then
  ok "Hermes Agent already installed ($(hermes --version 2>/dev/null || echo 'unknown version'))"
else
  info "Installing Hermes Agent..."
  if curl -fsSL https://hermes-agent.nousresearch.com/install.sh | sh; then
    ok "Hermes Agent installed"
    # Refresh PATH
    export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
  else
    err "Hermes Agent installation failed."
    warn "Try: curl -fsSL https://hermes-agent.nousresearch.com/install.sh | sh"
    exit 1
  fi
fi

# Ensure hermes is in PATH
if ! command -v hermes >/dev/null 2>&1; then
  export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
fi

# ── Step 3: Clone Pantheon ──────────────────────────────────────────────────
header "Pantheon Repository"

if [ -d "$PANTHEON_DIR/.git" ]; then
  ok "Pantheon already cloned at $PANTHEON_DIR"
  info "Pulling latest changes..."
  cd "$PANTHEON_DIR" && git pull --ff-only 2>/dev/null && ok "Updated to latest" || warn "Could not pull (you may have local changes)"
else
  info "Cloning Pantheon to $PANTHEON_DIR..."
  git clone https://github.com/Duskript/Pantheon.git "$PANTHEON_DIR"
  ok "Pantheon cloned"
fi

cd "$PANTHEON_DIR"

# ── Step 4: Create .env ─────────────────────────────────────────────────────
header "Environment Configuration"

if [ -f ".env" ]; then
  ok ".env already exists — keeping your configuration"
  warn "Edit ~/pantheon/.env to add or update API keys"
else
  info "Creating .env from .env.example..."
  if [ -f ".env.example" ]; then
    cp .env.example .env
    warn "Edit ~/pantheon/.env to add API keys"
  else
    cat > .env << 'ENVEOF'
# Pantheon Environment Configuration
# =============================================================================
# At minimum, you need ONE primary LLM provider + ONE embedding provider.
# Quick start: set both OPENCODE_GO_API_KEY and OPENROUTER_API_KEY below.
# =============================================================================

# ── Primary LLM Provider (pick one) ──────────────────────────────────────────

# 🟢 OpenCode Go — $10/mo flat, multiple open models
# Get key: https://opencode.ai/auth
# OPENCODE_GO_API_KEY=sk-put_your_key_here

# 🟡 OpenRouter — pay-as-you-go, 200+ models including free ones
# Get key: https://openrouter.ai/keys
# OPENROUTER_API_KEY=sk-or-v1-put_your_key_here

# 🟣 Ollama (local) — free, offline
# OLLAMA_API_KEY=ollama  # Any value works — Ollama ignores it

# ── Embedding Provider ───────────────────────────────────────────────────────
# Required for vector search. OpenCode Go doesn't provide embeddings.
# Set OPENROUTER_API_KEY above and it'll be used automatically for embeddings.

# Alternative (local, offline): Ollama + nomic-embed-text
# ATHENAEUM_EMBED_PROVIDER=ollama
# ATHENAEUM_EMBED_API_KEY=ollama
# ATHENAEUM_EMBED_MODEL=nomic-embed-text
# ATHENAEUM_EMBED_URL=http://localhost:11434/api/embeddings
ENVEOF
  ok ".env created — you'll need to add API keys"
  warn "Edit ~/pantheon/.env and add at least one API key"
fi

# ── Step 5: Install core gods ───────────────────────────────────────────────
header "Core Gods"

# Install base profile (Hermes + core config)
if [ -f "$HERMES_DIR/config.yaml" ]; then
  ok "Hermes config found"
else
  info "Running hermes setup wizard..."
  hermes setup --non-interactive 2>/dev/null || warn "Run 'hermes setup' manually to configure"
fi

# Install Hephaestus
if python3 scripts/pantheon-install . 2>/dev/null; then
  ok "Core gods installed"
else
  warn "Could not auto-install — run 'cd ~/pantheon && python3 scripts/pantheon-install .' manually"
fi

# ── Step 5b: Deploy Pantheon Plugins ─────────────────────────────────────────
header "Pantheon Plugins"

PLUGIN_SOURCE_DIR="$PANTHEON_DIR/plugins"
PLUGIN_TARGET_DIR="$HERMES_DIR/plugins"

mkdir -p "$PLUGIN_TARGET_DIR"

# List of plugins to deploy (exclude pantheon — it's already deployed as the
# Athenaeum memory provider and may be a copy or symlink already)
PLUGINS=("ichor-gates" "pantheon-ichor-nudge" "pantheon-shared-facts" "rtk-rewrite")

for plugin in "${PLUGINS[@]}"; do
  source_path="$PLUGIN_SOURCE_DIR/$plugin"
  target_path="$PLUGIN_TARGET_DIR/$plugin"

  if [ ! -d "$source_path" ]; then
    warn "Plugin source not found: $source_path — skipping"
    continue
  fi

  if [ ! -f "$source_path/plugin.yaml" ]; then
    warn "Plugin $plugin missing plugin.yaml — skipping"
    continue
  fi

  if [ ! -f "$source_path/__init__.py" ]; then
    warn "Plugin $plugin missing __init__.py — skipping"
    continue
  fi

  if [ -L "$target_path" ] || [ -d "$target_path" ]; then
    # Check if it's already a symlink pointing to the right place
    if [ -L "$target_path" ] && [ "$(readlink "$target_path")" = "$source_path" ]; then
      ok "Plugin $plugin already symlinked correctly"
    else
      warn "Plugin $plugin target exists — skipping (remove $target_path manually to re-link)"
    fi
  else
    ln -s "$source_path" "$target_path"
    ok "Symlinked plugin: $plugin"
  fi
done

# Also ensure the pantheon plugin is present (existing provider)
pantheon_source="$PLUGIN_SOURCE_DIR/pantheon"
pantheon_target="$PLUGIN_TARGET_DIR/pantheon"
if [ ! -d "$pantheon_target" ] && [ ! -L "$pantheon_target" ]; then
  if [ -d "$pantheon_source" ]; then
    ln -s "$pantheon_source" "$pantheon_target"
    ok "Symlinked plugin: pantheon"
  fi
fi

# ── Step 5c: Update Plugin Configuration ─────────────────────────────────────
header "Plugin Configuration"

CONFIG_FILE="$HERMES_DIR/config.yaml"

if [ -f "$CONFIG_FILE" ]; then
  # Enable plugins in config.yaml using yq if available, or python3
  # Merge the enabled list: ensure all four plugins are present

  python3 -c "
import yaml, sys, os

config_path = os.path.expanduser('$CONFIG_FILE')
with open(config_path) as f:
    config = yaml.safe_load(f)

if config is None:
    config = {}

# Ensure plugins section exists
if 'plugins' not in config:
    config['plugins'] = {}
if 'enabled' not in config['plugins']:
    config['plugins']['enabled'] = []

required = ['ichor-gates', 'pantheon-ichor-nudge', 'pantheon-shared-facts', 'rtk-rewrite']
current = config['plugins']['enabled']
for p in required:
    if p not in current:
        current.append(p)

config['plugins']['enabled'] = current

# Also ensure memory provider is set
if config.get('memory', {}).get('provider', '') != 'pantheon-shared-facts':
    if 'memory' not in config:
        config['memory'] = {}
    config['memory']['provider'] = 'pantheon-shared-facts'

with open(config_path, 'w') as f:
    yaml.dump(config, f, default_flow_style=False)

print('Config updated successfully')
"
  ok "Plugin configuration updated in config.yaml"
else
  warn "Config file not found at $CONFIG_FILE — skipping plugin config update"
  warn "Run 'hermes setup --non-interactive' first, then re-run this script"
fi

# ── Step 5d: Setup Cron Jobs ────────────────────────────────────────────────
header "Cron Jobs"

# Symlink critical cron scripts from repo to ~/.hermes/scripts/ so Hermes can find them
mkdir -p "${HERMES_DIR}/scripts"
CRON_SCRIPTS=("shared-context-digest.py" "ichor_subconscious.py" "morning-briefing.py" "inject-shared-context.py")
for script in "${CRON_SCRIPTS[@]}"; do
  repo_script="$PANTHEON_DIR/scripts/$script"
  target_link="${HERMES_DIR}/scripts/$script"
  if [ -f "$repo_script" ]; then
    if [ ! -L "$target_link" ] && [ ! -f "$target_link" ]; then
      ln -s "$repo_script" "$target_link"
      ok "Symlinked cron script: $script"
    else
      ok "Cron script already linked: $script"
    fi
  else
    warn "Cron script not found in repo: $script"
  fi
done

if [ -f "$PANTHEON_DIR/scripts/setup-pantheon-cron.sh" ]; then
  bash "$PANTHEON_DIR/scripts/setup-pantheon-cron.sh"
  ok "Cron jobs set up"
else
  warn "Cron setup script not found at $PANTHEON_DIR/scripts/setup-pantheon-cron.sh"
  warn "Run manually after install: cd ~/pantheon && bash scripts/setup-pantheon-cron.sh"
fi

# ── Step 5e: Deploy Systemd Services ─────────────────────────────────────────
header "Systemd Services"

SERVICE_DIR="${HOME}/.config/systemd/user"
mkdir -p "$SERVICE_DIR"

# Service files in the repo: webui/pantheon-webui.service, pantheon-core/pantheon-mcp.service, webui/demeter-watcher.service
SERVICES=(
  "webui/pantheon-webui.service"
  "pantheon-core/pantheon-mcp.service"
  "webui/demeter-watcher.service"
)

for relpath in "${SERVICES[@]}"; do
  src="$PANTHEON_DIR/$relpath"
  name=$(basename "$relpath")
  tgt="$SERVICE_DIR/$name"

  if [ ! -f "$src" ]; then
    warn "Service file not found: $src — skipping"
    continue
  fi

  cp "$src" "$tgt"
  ok "Installed $name"
done

systemctl --user daemon-reload 2>/dev/null && ok "Systemd reloaded"

# Enable and start services
for relpath in "${SERVICES[@]}"; do
  name=$(basename "$relpath")
  if systemctl --user enable "$name" 2>/dev/null; then
    systemctl --user start "$name" 2>/dev/null || warn "Could not start $name (may need manual config)"
    ok "Enabled + started $name"
  else
    warn "Could not enable $name — systemd user services may not be available"
  fi
done

# ── Step 6: Start Gateway ───────────────────────────────────────────────────
header "Gateway"

if pgrep -f "hermes.*gateway" >/dev/null 2>&1; then
  ok "Gateway already running"
else
  info "Starting Pantheon gateway..."
  nohup hermes gateway > /tmp/pantheon-gateway.log 2>&1 &
  GATEWAY_PID=$!
  sleep 2
  if kill -0 "$GATEWAY_PID" 2>/dev/null; then
    ok "Gateway started (PID: $GATEWAY_PID)"
  else
    warn "Gateway may not have started — check: cat /tmp/pantheon-gateway.log"
  fi
fi

# ── Step 7: Start Setup Server ──────────────────────────────────────────────
header "Setup Server"

# Kill any previous setup server
pkill -f "setup-server.py" 2>/dev/null || true
sleep 0.5

# Start the setup server (serves welcome page + API for .env writes)
python3 scripts/setup-server.py &
SETUP_PID=$!
sleep 1

if kill -0 "$SETUP_PID" 2>/dev/null; then
  ok "Setup server running (PID: $SETUP_PID) on http://localhost:9876"
else
  warn "Setup server may not have started — check scripts/setup-server.py"
fi

# ── Step 8: Open Welcome Wizard ─────────────────────────────────────────────
header "Welcome"

WELCOME_URL="http://localhost:9876/welcome.html"
WEBUI_URL="http://localhost:8787"

info "Opening Welcome Wizard..."
case "$PLATFORM" in
  linux)  xdg-open "$WELCOME_URL" 2>/dev/null || true ;;
  macos)  open "$WELCOME_URL" 2>/dev/null || true ;;
  *)      warn "Open $WELCOME_URL in your browser" ;;
esac

# ── Summary ─────────────────────────────────────────────────────────────────
cat << EOF

${BOLD}${CYAN}══════════════════════════════════════════════${NC}
${BOLD}${GREEN}  Pantheon is ready! 🎉${NC}
${BOLD}${CYAN}══════════════════════════════════════════════${NC}

  ${BOLD}Web UI:${NC}      ${CYAN}http://localhost:8787${NC}
  ${BOLD}Pantheon dir:${NC} ${CYAN}$PANTHEON_DIR${NC}
  ${BOLD}Config:${NC}      ${CYAN}$PANTHEON_DIR/.env${NC}

${YELLOW}  Next steps:${NC}
    1. Add API keys to ${CYAN}~/pantheon/.env${NC} (at least one LLM provider)
    2. Browse the Welcome Wizard that just opened
    3. Open the Web UI and forge your first God

EOF
