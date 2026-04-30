#!/usr/bin/env bash
# =============================================================================
# Pantheon Migration Restore — run this on the NEW Ubuntu machine
# =============================================================================
# After extracting the tarball (tar ... -xpf -C /), run this to:
#   1. Install Ollama (if not present) and sign in to cloud
#   2. Set up Hermes Agent (if not present)
#   3. Clone Pantheon-Core from GitHub
#   4. Verify all profile configs, plugins, state
#   5. Test that things work
#
# Prerequisites:
#   - Ubuntu system
#   - Tarball extracted to / (so ~/athenaeum and ~/.hermes exist)
#   - sudo access
#   - GitHub SSH key set up (https://github.com/settings/keys)
#   - Telegram bot tokens from @BotFather ready (you already have these)
#
# Usage:
#   bash ~/pantheon/scripts/migrate-restore.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}══════════════════════════════════════════${NC}"
echo -e "${CYAN}   Pantheon Migration Restore${NC}"
echo -e "${CYAN}══════════════════════════════════════════${NC}"
echo ""

USERNAME=$(whoami)
echo -e "User: ${GREEN}$USERNAME${NC}"
echo ""

# ── Step 1: System dependencies ─────────────────────────────────────────────
echo -e "${YELLOW}[1/6] Checking system dependencies...${NC}"

# Update package list silently
sudo apt-get update -qq 2>/dev/null || true

# Install essentials
MISSING_PKGS=""
for pkg in curl git python3 python3-pip python3-venv; do
    if ! dpkg -l "$pkg" &>/dev/null 2>&1; then
        MISSING_PKGS="$MISSING_PKGS $pkg"
    fi
done

if [ -n "$MISSING_PKGS" ]; then
    echo "  → Installing:$MISSING_PKGS"
    sudo apt-get install -y $MISSING_PKGS
fi
echo -e "  ${GREEN}✓${NC} System packages ready"

# zstd for fast decompression
if ! command -v zstd &>/dev/null; then
    echo "  → Installing zstd"
    sudo apt-get install -y zstd 2>/dev/null || true
fi

# ── Step 2: Verify extracted data ───────────────────────────────────────────
echo ""
echo -e "${YELLOW}[2/6] Verifying extracted data...${NC}"

declare -A CHECK
CHECK["Athenaeum"]="$HOME/athenaeum"
CHECK["Pantheon store"]="$HOME/.hermes/pantheon"
CHECK["Hermes config"]="$HOME/.hermes/config.yaml"
CHECK["Hephaestus config"]="$HOME/.hermes/profiles/hephaestus/config.yaml"
CHECK["Apollo config"]="$HOME/.hermes/profiles/apollo/config.yaml"

ALL_OK=true
for label in "${!CHECK[@]}"; do
    path="${CHECK[$label]}"
    if [ -e "$path" ]; then
        echo -e "  ${GREEN}✓${NC} $label"
    else
        echo -e "  ${RED}✗${NC} MISSING: $label ($path)"
        ALL_OK=false
    fi
done

if [ "$ALL_OK" = false ]; then
    echo ""
    echo -e "${RED}Missing files — did you extract the tarball?${NC}"
    echo "  tar -I zstd -xpf pantheon-migration-*.tar.zst -C /"
    echo "  (or use gzip instead of zstd)"
    exit 1
fi

# ── Step 3: Install Ollama + sign in ────────────────────────────────────────
echo ""
echo -e "${YELLOW}[3/6] Setting up Ollama...${NC}"

if ! command -v ollama &>/dev/null; then
    echo "  → Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    echo ""
    echo -e "${CYAN}  ┌──────────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}  │ Ollama installed! Run this now:             │${NC}"
    echo -e "${CYAN}  │                                              │${NC}"
    echo -e "${CYAN}  │   ollama signin                              │${NC}"
    echo -e "${CYAN}  │                                              │${NC}"
    echo -e "${CYAN}  │ Then verify with:                            │${NC}"
    echo -e "${CYAN}  │   ollama pull deepseek-v4-flash:cloud        │${NC}"
    echo -e "${CYAN}  │   ollama pull gemma4:31b-cloud              │${NC}"
    echo -e "${CYAN}  └──────────────────────────────────────────────┘${NC}"
    echo ""
    read -p "  Press Enter after signing in to Ollama... "
else
    echo -e "  ${GREEN}✓${NC} Ollama already installed"
    echo ""
    # Check if signed in to cloud
    if ollama list 2>&1 | grep -q "cloud"; then
        echo -e "  ${GREEN}✓${NC} Cloud models available"
    else
        echo -e "  ${YELLOW}⚠ Run 'ollama signin' if you haven't yet${NC}"
    fi
fi

# ── Step 4: Install Hermes Agent ────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[4/6] Setting up Hermes Agent...${NC}"

if ! command -v hermes &>/dev/null; then
    echo "  → Installing Hermes Agent..."
    curl -fsSL https://hermes-agent.nousresearch.com/install.sh | sh
    
    echo ""
    echo -e "${YELLOW}  ┌──────────────────────────────────────────────┐${NC}"
    echo -e "${YELLOW}  │ IMPORTANT: Add to PATH                       │${NC}"
    echo -e "${YELLOW}  │                                              │${NC}"
    echo -e "${YELLOW}  │ After install, you may need to:              │${NC}"
    echo -e "${YELLOW}  │   source ~/.bashrc                           │${NC}"
    echo -e "${YELLOW}  │   (or add ~/.local/bin to your PATH)          │${NC}"
    echo -e "${YELLOW}  └──────────────────────────────────────────────┘${NC}"
    echo ""
    
    # Re-source path so we can continue
    export PATH="$HOME/.local/bin:$PATH"
else
    echo -e "  ${GREEN}✓${NC} Hermes already installed"
fi

# ── Step 5: Clone Pantheon-Core + verify ────────────────────────────────────
echo ""
echo -e "${YELLOW}[5/6] Setting up Pantheon-Core...${NC}"

if [ -d "$HOME/pantheon/.git" ]; then
    echo -e "  ${GREEN}✓${NC} ~/pantheon/ already exists"
else
    echo "  → Cloning Pantheon-Core from GitHub..."
    
    if [ ! -f "$HOME/.ssh/id_ed25519.pub" ]; then
        echo ""
        echo -e "${CYAN}  ┌──────────────────────────────────────────────┐${NC}"
        echo -e "${CYAN}  │ No SSH key found. Generate one:             │${NC}"
        echo -e "${CYAN}  │                                              │${NC}"
        echo -e "${CYAN}  │   ssh-keygen -t ed25519 -C 'pantheon-core'   │${NC}"
        echo -e "${CYAN}  │   cat ~/.ssh/id_ed25519.pub                 │${NC}"
        echo -e "${CYAN}  │                                              │${NC}"
        echo -e "${CYAN}  │ Then add to: https://github.com/settings/keys│${NC}"
        echo -e "${CYAN}  └──────────────────────────────────────────────┘${NC}"
        echo ""
        read -p "  Press Enter after setting up GitHub SSH access... "
    fi
    
    git clone git@github.com:Duskript/Pantheon-Core.git "$HOME/pantheon"
    echo -e "  ${GREEN}✓${NC} Pantheon-Core cloned"
fi

# ── Step 6: Verify profiles and gateways ────────────────────────────────────
echo ""
echo -e "${YELLOW}[6/6] Verification...${NC}"

echo -e "  → Hermes version: $(hermes --version 2>/dev/null || echo 'check PATH')"
echo -e "  → Profiles found:"
for p in hephaestus apollo; do
    if [ -d "$HOME/.hermes/profiles/$p" ]; then
        echo -e "    ${GREEN}✓${NC} $p"
    fi
done

echo ""
echo "  → Secrets check:"
if [ -f "$HOME/.hermes/.env" ]; then
    echo -e "    ${GREEN}✓${NC} Root .env present"
fi
for p in hephaestus apollo; do
    if [ -f "$HOME/.hermes/profiles/$p/.env" ]; then
        echo -e "    ${GREEN}✓${NC} $p/.env present"
    fi
done

echo ""
echo "  → Available models (will pull if needed):"
ollama pull deepseek-v4-flash:cloud 2>/dev/null || echo "    Run 'ollama signin' first for cloud"
ollama pull gemma4:31b-cloud 2>/dev/null || true

echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}   Restore complete!${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo ""
echo "Two gateways are ready to start. Each needs its own terminal or systemd service:"
echo ""
echo "  # 1. You (Hephaestus forge god) — Telegram bot"
echo "  cd ~/pantheon && hermes -p hephaestus gateway run"
echo ""
echo "  # 2. Apollo (creative god) — Telegram bot"
echo "  cd ~/pantheon && hermes -p apollo gateway run"
echo ""
echo "To install as systemd services (auto-start on boot):"
echo "  hermes -p hephaestus gateway install"
echo "  hermes -p apollo gateway install"
echo ""
echo "CLI usage (no gateway needed):"
echo "  hermes -p hephaestus  # Talk to Hephaestus (forge / build)"
echo "  hermes -p apollo      # Talk to Apollo (songcraft / creative)"
