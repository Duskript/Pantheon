#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────
# Clara — Pantheon Medical Practice Operations God
# Provisioning Script v1.0
#
# Usage:
#   ./provision-clara.sh <client-name> <gmail-address>
#
# Example:
#   ./provision-clara.sh dr-smith dr.smith@practice.com
#
# Prerequisites:
#   - Pantheon base installed on target machine
#   - SSH root access (password or key)
#   - Google OAuth credentials for Google Workspace MCP
# ────────────────────────────────────────────────────────────────────
set -euo pipefail

CLIENT="$1"
CLIENT_GMAIL="$2"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Clara — Provisioning for: $CLIENT${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# ── Step 1: Create Hermes profile ──────────────────────────────────
echo -e "\n${GREEN}[1/6]${NC} Creating Hermes profile..."
hermes profile create clara
echo "  ✓ Profile 'clara' created"

# ── Step 2: Write SOUL.md and persona.md ───────────────────────────
echo -e "\n${GREEN}[2/6]${NC} Writing SOUL.md and persona.md..."
CLARA_HOME="$HOME/.hermes/profiles/clara"

# Copy from packaged template (these live in ~/pantheon/clara-templates/)
cp "$HOME/pantheon/clara-templates/SOUL.md" "$CLARA_HOME/SOUL.md"
cp "$HOME/pantheon/clara-templates/persona.md" "$CLARA_HOME/persona.md"

# Replace client-specific placeholders
# (Templating: $CLIENT_NAME and $CLIENT_GMAIL get set in SOUL.md)
sed -i "s/\[CLIENT_NAME\]/$CLIENT/g" "$CLARA_HOME/SOUL.md"
sed -i "s/\[CLIENT_GMAIL\]/$CLIENT_GMAIL/g" "$CLARA_HOME/SOUL.md"

echo "  ✓ SOUL.md written"
echo "  ✓ persona.md written"

# ── Step 3: Configure model and provider ────────────────────────────
echo -e "\n${GREEN}[3/6]${NC} Setting up model config..."
cat > "$CLARA_HOME/config.yaml" << 'YAMLEOF'
model:
  default: deepseek-v4-flash
  provider: opencode-go
providers:
  opencode-go:
    default_model: deepseek-v4-flash
    models:
      - deepseek-v4-flash
      - deepseek-v4-pro
      - kimi-k2.6
    name: OpenCode Go
toolsets:
  - hermes-cli
  - web
agent:
  max_turns: 120
  gateway_timeout: 1800
  restart_drain_timeout: 60
YAMLEOF

echo "  ✓ Config written"

# ── Step 4: Write god.json metadata ─────────────────────────────────
echo -e "\n${GREEN}[4/6]${NC} Writing god.json..."
cat > "$CLARA_HOME/god.json" << 'JSONEOF'
{
  "display_name": "Clara",
  "icon": "🏥",
  "color": "#4C6EF5",
  "domain": "Medical Practice Operations"
}
JSONEOF
echo "  ✓ god.json written"

# ── Step 5: Create Athenaeum Codex structures ──────────────────────
echo -e "\n${GREEN}[5/6]${NC} Creating Athenaeum Codices..."

# Codex-PriorAuth
mkdir -p "$HOME/athenaeum/Codex-PriorAuth"/{guides,payers/medicaid,payers/medicare,payers/cigna,medications,templates/state-specific-forms}
cp "$HOME/pantheon/clara-templates/Codex-PriorAuth-INDEX.md" "$HOME/athenaeum/Codex-PriorAuth/INDEX.md"
echo "  ✓ Codex-PriorAuth created"

# Codex-Practice (practice-specific knowledge)
mkdir -p "$HOME/athenaeum/Codex-Practice"
cat > "$HOME/athenaeum/Codex-Practice/INDEX.md" << 'CPEOF'
# Codex-Practice — $CLIENT_NAME

> Practice-specific knowledge: provider preferences, typical workflows,
> commonly prescribed medications, office hours, staff roles.

## Contents

- providers.md              ← Provider names, NPI, specialties, signatures
- common-medications.md      ← Most frequently prescribed, renewal cadences
- office-hours.md            ← Scheduling windows, closed days
- workflows.md               ← Practice-specific SOPs
CPEOF
echo "  ✓ Codex-Practice created"

# Codex-God-clara (Clara's shared brain, Hades-excluded)
mkdir -p "$HOME/athenaeum/Codex-God-clara"
cat > "$HOME/athenaeum/Codex-God-clara/INDEX.md" << 'CGEOF'
# Codex-God-clara — Memory & Shared Brain

> Hades-excluded. Clara's living memory.

## Files

- memory.md — Current active memory, updated after each session
- form-mappings.md — Learned form field mappings (payer → form field)
- patient-cadences.md — Per-patient renewal windows and contact patterns
- preferences.md — Med manager's preferences (learned, never re-asked)
CGEOF
echo "  ✓ Codex-God-clara created"

# ── Step 6: Set up Google Workspace MCP credentials ────────────────
echo -e "\n${GREEN}[6/6]${NC} Setting up Google Workspace integration..."

# Check if Google Workspace MCP credentials exist for this address
MCP_CRED_DIR="$HOME/.local/share/google-workspace-mcp/credentials"
MCP_EMAIL_SLUG=$(echo "$CLIENT_GMAIL" | tr '@.' '-')
MCP_CRED_FILE="$MCP_CRED_DIR/${MCP_EMAIL_SLUG}.json"

if [ -f "$MCP_CRED_FILE" ]; then
  echo "  ✓ Existing Google credentials found"
else
  echo -e "  ${YELLOW}⚠ No Google credentials found for $CLIENT_GMAIL${NC}"
  echo "  └ Run Google OAuth setup manually after provisioning:"
  echo "    → https://console.cloud.google.com/apis/credentials"
  echo "    → Download credentials to: $MCP_CRED_FILE"
  echo "    → Then configure ~/.config/google-workspace-mcp/accounts.json"
fi

# ── Done ────────────────────────────────────────────────────────────
echo -e "\n${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Clara provisioned for: $CLIENT${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Next steps:"
echo "  1. Switch to Clara:  hermes profile use clara"
echo "  2. Ingest criteria doc to: ~/athenaeum/Codex-PriorAuth/guides/approval-criteria.md"
echo "  3. Test connection:  hermes session start"
echo "  4. Set up cron jobs:"
echo "     - Morning inbox scan (8:00 AM weekdays)"
echo "     - Renewal check (10:00 AM weekdays)"
echo "     - Weekly briefing (4:00 PM Friday)"
echo ""
echo "Deployment complete. 🏥"
