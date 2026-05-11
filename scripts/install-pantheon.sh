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
#   5. Sets up and starts the gateway as a user service
#   6. Opens the Welcome Wizard in your browser
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
  cp .env.example .env 2>/dev/null || cat > .env << 'ENVEOF'
# Pantheon Environment Configuration
# Copy your API keys below. At minimum, set one LLM provider.

# Recommended starter: OpenCode Go ($10/month, multiple open models)
# Get key at: https://opencode.ai/auth
# OPENCODE_GO_API_KEY=put_your_key_here

# Alternative: OpenRouter (pay-as-you-go, 200+ models)
# Get key at: https://openrouter.ai/keys
# OPENROUTER_API_KEY=sk-or-v1-put_your_key_here

# Or use local models with Ollama:
# OLLAMA_API_KEY=ollama  # Any value works — Ollama runs locally
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

# ── Step 7: Open Welcome Wizard ─────────────────────────────────────────────
header "Welcome"

WELCOME_URL="file://${PANTHEON_DIR}/welcome.html"
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
