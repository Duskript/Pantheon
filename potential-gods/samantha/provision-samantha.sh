#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────
# Samantha — Travel Advisory Operations God
# Provisioning script v0.2
#
# Runs ON the client VPS (Hostinger), after the Pantheon/Hermes base
# install, as the deploy user. Creates the `samantha` profile, renders
# the templates, scaffolds the Codex, installs cron jobs and the
# systemd gateway unit.
#
# One client, one box, one god: Samantha is made the sticky active
# profile so gateway + cron run in her context without per-command
# profile flags.
#
# Usage:
#   ./provision-samantha.sh \
#     --name "Erica" \
#     --business "Travel Gems" \
#     --email "erica@example.com" \
#     --tz "America/Chicago" \
#     --channel "discord" \
#     --model "deepseek-v4-flash" \
#     --provider "opencode-go"
#
# Flags:
#   --dry-run   Print what would happen; write nothing.
#   --force     Overwrite an existing samantha profile (backup taken first).
# ────────────────────────────────────────────────────────────────────
set -euo pipefail

PROFILE="samantha"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_USER="${USER}"

CLIENT_NAME=""
CLIENT_BUSINESS=""
CLIENT_EMAIL=""
CLIENT_TZ="America/Chicago"
BRIEF_CHANNEL="discord"
MODEL_DEFAULT="deepseek-v4-flash"
PROVIDER_NAME="opencode-go"
PROVIDER_LABEL="OpenCode Go"
BRIEF_TIME="07:00"
WEEKLY_TIME="16:00"
WEEKLY_CRON="0 16 * * 5"
WORK_HOURS="08:00-18:00"
QUIET_START="19:00"
QUIET_END="07:00"
DRY_RUN=0
FORCE=0

GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

log()  { printf '%b\n' "${BLUE}▸${NC} $*"; }
ok()   { printf '%b\n' "  ${GREEN}✓${NC} $*"; }
warn() { printf '%b\n' "  ${YELLOW}!${NC} $*"; }
die()  { printf '%b\n' "${RED}✗ $*${NC}" >&2; exit 1; }

usage() { sed -n '2,29p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --name)       CLIENT_NAME="$2"; shift 2 ;;
    --business)   CLIENT_BUSINESS="$2"; shift 2 ;;
    --email)      CLIENT_EMAIL="$2"; shift 2 ;;
    --tz)         CLIENT_TZ="$2"; shift 2 ;;
    --channel)    BRIEF_CHANNEL="$2"; shift 2 ;;
    --model)      MODEL_DEFAULT="$2"; shift 2 ;;
    --provider)   PROVIDER_NAME="$2"; shift 2 ;;
    --brief-time) BRIEF_TIME="$2"; shift 2 ;;
    --dry-run)    DRY_RUN=1; shift ;;
    --force)      FORCE=1; shift ;;
    -h|--help)    usage ;;
    *) die "Unknown argument: $1 (try --help)" ;;
  esac
done

[ -n "$CLIENT_NAME" ]     || die "--name is required"
[ -n "$CLIENT_BUSINESS" ] || die "--business is required"
[ -n "$CLIENT_EMAIL" ]    || die "--email is required"

HERMES_BIN="$(command -v hermes || true)"
[ -n "$HERMES_BIN" ] || die "hermes CLI not found. Install the Pantheon base first."

HERMES_HOME="${HOME}/.hermes"
PROFILE_DIR="${HERMES_HOME}/profiles/${PROFILE}"
CODEX_DIR="${HOME}/athenaeum/Codex-Samantha"
STATE_DIR="${HOME}/pantheon/state"
BACKUP_DIR="${HOME}/pantheon/backups/samantha-$(date +%Y%m%d-%H%M%S)"
ENVFILE="${PROFILE_DIR}/.env"
GOOGLE_MCP_BIN="${HOME}/.local/bin/google-workspace-mcp"

# Morning brief cron from --brief-time (07:00 → "0 7 * * 1-5")
BRIEF_HOUR="${BRIEF_TIME%%:*}"
BRIEF_HOUR="${BRIEF_HOUR#0}"
BRIEF_CRON="0 ${BRIEF_HOUR} * * 1-5"

printf '%b\n' "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
printf '%b\n' "${BLUE}  Samantha — provisioning for ${CLIENT_BUSINESS}${NC}"
printf '%b\n' "${BLUE}  user=${DEPLOY_USER}  tz=${CLIENT_TZ}  model=${MODEL_DEFAULT}${NC}"
if [ "$DRY_RUN" -eq 1 ]; then
  printf '%b\n' "${YELLOW}  DRY RUN — no files will be written${NC}"
fi
printf '%b\n' "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Runs a command, or prints it under --dry-run. No eval.
run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '    [dry-run] %s\n' "$*"
  else
    "$@"
  fi
}

# ── Step 0: Safety ──────────────────────────────────────────────────
if [ -d "$PROFILE_DIR" ] && [ "$FORCE" -ne 1 ]; then
  die "Profile ${PROFILE_DIR} already exists. Re-run with --force to overwrite (backup is taken)."
fi
if [ -d "$PROFILE_DIR" ] && [ "$FORCE" -eq 1 ]; then
  log "Backing up existing profile → ${BACKUP_DIR}"
  if [ "$DRY_RUN" -ne 1 ]; then
    mkdir -p "$(dirname "$BACKUP_DIR")"
    cp -a "$PROFILE_DIR" "$BACKUP_DIR"
  fi
  ok "backup taken"
fi

# ── Step 1: Profile ─────────────────────────────────────────────────
log "[1/7] Creating Hermes profile '${PROFILE}'"
if [ ! -d "$PROFILE_DIR" ]; then
  run "$HERMES_BIN" profile create "$PROFILE"
fi
run mkdir -p "${PROFILE_DIR}/home"
ok "profile ready"

# ── Step 2: Templated files ─────────────────────────────────────────
log "[2/7] Rendering SOUL.md, persona.md, god.json, config.yaml"

render() {
  # render <src> <dst>
  local src="$1" dst="$2"
  [ -f "$src" ] || die "template missing: $src"
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '    [dry-run] render %s → %s\n' "$src" "$dst"
    return 0
  fi
  sed -e "s|\[CLIENT_NAME\]|${CLIENT_NAME}|g" \
      -e "s|\[CLIENT_BUSINESS\]|${CLIENT_BUSINESS}|g" \
      -e "s|\[CLIENT_EMAIL\]|${CLIENT_EMAIL}|g" \
      -e "s|\[CLIENT_TZ\]|${CLIENT_TZ}|g" \
      -e "s|\[DEPLOY_USER\]|${DEPLOY_USER}|g" \
      -e "s|\[BRIEF_CHANNEL\]|${BRIEF_CHANNEL}|g" \
      -e "s|\[BRIEF_TIME\]|${BRIEF_TIME}|g" \
      -e "s|\[BRIEF_CRON\]|${BRIEF_CRON}|g" \
      -e "s|\[WEEKLY_TIME\]|${WEEKLY_TIME}|g" \
      -e "s|\[WEEKLY_CRON\]|${WEEKLY_CRON}|g" \
      -e "s|\[WORK_HOURS\]|${WORK_HOURS}|g" \
      -e "s|\[QUIET_START\]|${QUIET_START}|g" \
      -e "s|\[QUIET_END\]|${QUIET_END}|g" \
      -e "s|\[MODEL_DEFAULT\]|${MODEL_DEFAULT}|g" \
      -e "s|\[PROVIDER_NAME\]|${PROVIDER_NAME}|g" \
      -e "s|\[PROVIDER_LABEL\]|${PROVIDER_LABEL}|g" \
      -e "s|\[GOOGLE_MCP_BIN\]|${GOOGLE_MCP_BIN}|g" \
      "$src" > "$dst"
}

render "${SCRIPT_DIR}/SOUL.md"              "${PROFILE_DIR}/SOUL.md"
render "${SCRIPT_DIR}/persona.md"            "${PROFILE_DIR}/persona.md"
render "${SCRIPT_DIR}/god.json"              "${PROFILE_DIR}/god.json"
render "${SCRIPT_DIR}/config.yaml.template"  "${PROFILE_DIR}/config.yaml"
ok "SOUL.md, persona.md, god.json, config.yaml rendered"

if [ "$DRY_RUN" -ne 1 ]; then
  if grep -q "\[CLIENT_" "${PROFILE_DIR}/SOUL.md"; then
    die "Unfilled placeholder left in SOUL.md — check the render map."
  fi
fi

# ── Step 3: Codex scaffold ──────────────────────────────────────────
log "[3/7] Scaffolding ${CODEX_DIR}"
run mkdir -p "${CODEX_DIR}/travelers" "${CODEX_DIR}/suppliers" \
             "${CODEX_DIR}/destinations" "${CODEX_DIR}/templates" "${CODEX_DIR}/reports"

if [ "$DRY_RUN" -ne 1 ]; then
  cp "${SCRIPT_DIR}/Codex-Samantha-INDEX.md" "${CODEX_DIR}/INDEX.md"

  if [ ! -f "${CODEX_DIR}/memory.md" ]; then
    cat > "${CODEX_DIR}/memory.md" <<MEMEOF
# Active Memory — $(date +%F)

## Current focus

## Open loops

## Decisions

## Corrections
MEMEOF
  fi

  if [ ! -f "${CODEX_DIR}/preferences.md" ]; then
    cat > "${CODEX_DIR}/preferences.md" <<PREFEOF
# Preferences — ${CLIENT_NAME}

> Ask once, remember forever.

- Airline:
- Seat:
- Hotel style:
- Meeting length:
- Signature block:
- Working hours:
- Never:
PREFEOF
  fi

  if [ ! -f "${CODEX_DIR}/voice-guide.md" ]; then
    cat > "${CODEX_DIR}/voice-guide.md" <<VOICEEOF
# Voice Guide — ${CLIENT_NAME}

> Seed with 20-30 real sent emails. Highest-leverage file in this Codex.

## Tone

## Signoff

## Phrases she uses

## Phrases she never uses
VOICEEOF
  fi

  if [ ! -f "${CODEX_DIR}/workflows.md" ]; then
    cat > "${CODEX_DIR}/workflows.md" <<WFEOF
# Workflows — ${CLIENT_BUSINESS}

> Walk one real trip end to end, out loud, and record the actual sequence.

## Inquiry → booked

## Booked → pre-trip

## In-trip

## Returned → review
WFEOF
  fi
fi
ok "Codex scaffolded"

# ── Step 4: Secrets file ────────────────────────────────────────────
log "[4/7] Preparing environment file (secrets stay out of config.yaml)"
if [ -f "$ENVFILE" ]; then
  warn "env file already exists, leaving untouched: ${ENVFILE}"
elif [ "$DRY_RUN" -eq 1 ]; then
  printf '    [dry-run] would write %s (chmod 600)\n' "$ENVFILE"
else
  umask 077
  {
    printf '# Samantha — %s. chmod 600. Never commit.\n' "$CLIENT_BUSINESS"
    printf 'HERMES_PROVIDER_API_KEY=REPLACE_ME\n'
    printf 'FORA_MCP_TOKEN=REPLACE_ME\n'
    printf 'BRIEF_WEBHOOK_URL=REPLACE_ME\n'
  } > "$ENVFILE"
  chmod 600 "$ENVFILE"
  ok "wrote ${ENVFILE} (chmod 600)"
fi

# ── Step 5: Google Workspace check ──────────────────────────────────
log "[5/7] Checking Google Workspace MCP availability"
if command -v google-workspace-mcp >/dev/null 2>&1 || [ -x "$GOOGLE_MCP_BIN" ]; then
  ok "google-workspace-mcp found"
else
  warn "google-workspace-mcp not installed — Gmail/Calendar unavailable until it is"
fi
if [ ! -f "${HOME}/.config/google-workspace-mcp/accounts.json" ]; then
  warn "no accounts.json — run the OAuth flow for ${CLIENT_EMAIL} post-provision"
fi

# ── Step 6: Sticky profile + cron jobs ──────────────────────────────
log "[6/7] Making ${PROFILE} the active profile and installing cron jobs"
if [ "$DRY_RUN" -eq 1 ]; then
  printf '    [dry-run] hermes profile use %s\n' "$PROFILE"
else
  "$HERMES_BIN" profile use "$PROFILE"
  ok "active profile → ${PROFILE}"
fi

if "$HERMES_BIN" cron create --help >/dev/null 2>&1; then
  run "$HERMES_BIN" cron create "$BRIEF_CRON" \
      "Build and deliver the morning brief exactly as specified in SOUL.md. Include calendar, Tier-1 email, deadlines due within 7 days, and follow-up debt. Silent if nothing is worth reporting." \
      --name morning-brief --deliver "$BRIEF_CHANNEL"

  run "$HERMES_BIN" cron create "0 9 * * *" \
      "Check supplier payment, cancellation, and document deadlines. Escalate anything due within 7 days. Flag Fora-derived data as stale until the integration is live." \
      --name deadline-watch --deliver "$BRIEF_CHANNEL"

  run "$HERMES_BIN" cron create "$WEEKLY_CRON" \
      "Produce the weekly review per SOUL.md: pipeline movement, revenue and commissions, follow-up debt, content performance, wins." \
      --name weekly-review --deliver "$BRIEF_CHANNEL"

  ok "cron jobs installed — verify: hermes cron list"
else
  warn "hermes cron create unavailable — install the three jobs manually"
fi

# ── Step 7: systemd gateway unit ────────────────────────────────────
log "[7/7] Writing systemd gateway unit"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_FILE="${UNIT_DIR}/hermes-${PROFILE}.service"

if [ "$DRY_RUN" -eq 1 ]; then
  printf '    [dry-run] would write %s and enable hermes-%s.service\n' "$UNIT_FILE" "$PROFILE"
else
  mkdir -p "$UNIT_DIR" "$STATE_DIR"
  cat > "$UNIT_FILE" <<UNITEOF
[Unit]
Description=Hermes gateway — ${PROFILE} (${CLIENT_BUSINESS})
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory=${HERMES_HOME}
EnvironmentFile=%h/.hermes/profiles/${PROFILE}/.env
Environment="HERMES_HOME=${HERMES_HOME}"
Environment="HERMES_PROFILE=${PROFILE}"
Environment="TZ=${CLIENT_TZ}"
ExecStart=${HERMES_BIN} gateway run
Restart=always
RestartSec=10
TimeoutStopSec=210

[Install]
WantedBy=default.target
UNITEOF
  systemctl --user daemon-reload
  systemctl --user enable --now "hermes-${PROFILE}.service"
  ok "unit enabled: hermes-${PROFILE}.service"
fi

warn "ensure the service survives logout: sudo loginctl enable-linger ${DEPLOY_USER}"

# ── Report ──────────────────────────────────────────────────────────
printf '\n%b\n' "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
printf '%b\n' "${GREEN}  Samantha staged for ${CLIENT_BUSINESS}${NC}"
printf '%b\n' "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
cat <<'NEXT'

Next steps, in order:
  1. Fill secrets:        ~/.hermes/profiles/samantha/.env
  2. Google OAuth:        run the workspace MCP auth flow for the client address
  3. Enable lingering:    sudo loginctl enable-linger <deploy_user>
  4. Verify gateway:      systemctl --user status hermes-samantha
  5. Seed the Codex:      voice-guide.md (20-30 sent emails), workflows.md, preferences.md
  6. Smoke test in chat:  "what's on my calendar this week?"
  7. First live brief:    let it fire once, then correct what it got wrong
  8. Fora MCP:            add the endpoint to config.yaml only after a verified handshake

Do not enable autonomous sending. Draft-only until the client has trusted it for a month.
NEXT
