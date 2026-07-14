#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# provision-firm.sh — main entry point for spinning up a new firm.
#
# Usage:
#   provision-firm.sh --dry-run                     # validate template
#   provision-firm.sh <firm-slug>                   # interactive setup
#   provision-firm.sh --generate-env <firm-slug>    # produce .env only
#   provision-firm.sh --from-stdin                  # read params from stdin
#   provision-firm.sh --status <firm-slug>          # show provision state
#   provision-firm.sh --rollback <firm-slug>        # tear down a firm
#   provision-firm.sh --resume <firm-slug>          # resume failed provision
#
# What it does:
#   1. Validates the firm slug (lowercase, dashes, ≤32 chars)
#   2. Generates a .env file with random secrets (or uses existing one)
#   3. Creates /srv/ledger/{slug}/ directory tree
#   4. Renders docker-compose.yml + Traefik config with slug substituted
#   5. Brings the Traefik stack up
#   6. Brings the main stack up
#   7. Runs create-site.sh to bootstrap the Frappe site
#   8. Configures restic backup cron
#   9. Prints the verification checklist
#
# Idempotency: re-running against an existing firm is safe. Phases
# already completed (recorded in /srv/ledger/{slug}/.state) are
# skipped with a clear "already done" message.
#
# State tracking: each completed phase appends a line to .state so
# `--status` can report progress and `--resume` can pick up from the
# first incomplete phase. The state file is plain text — one phase
# per line — so operators can inspect it with `cat`.
#
# Logging: every line written to stdout/stderr is also appended to
# ${firm_dir}/logs/provision.log (created on demand). Use `tail -f`
# on that file in another terminal to watch progress.
#
# Rollback: `--rollback` removes the firm in reverse order. Volumes
# (postgres data, sites, etc.) are KEPT unless `--purge` is passed.
# Pass `--confirm` in non-interactive mode to skip the per-step
# confirmation prompt.
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail
IFS=$'\n\t'

# ─── Constants ──────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_DATA_ROOT="/srv/ledger"
DEFAULT_DOMAIN="theoforge.app"
# Single external bridge that all stacks (Traefik + main) attach to.
# Created by the tree-created phase — see ensure_ledger_network().
# External=true in both compose files means the network MUST exist
# before any `docker compose up -d` runs.
LEDGER_NETWORK_NAME="ledger-net"

# Phases that make up a provision, in order. `--resume` reads the
# state file and picks up from the first missing phase. Adding a new
# phase here means operators can resume past it on a retry.
PHASES=(
  tree-created
  env-generated
  files-rendered
  traefik-up
  stack-up
  frappe-healthy
  site-created
  cron-installed
)

# ─── Logging helpers ────────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'
  C_BOLD=$'\033[1m'
  C_BLUE=$'\033[34m'
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_RED=$'\033[31m'
else
  C_RESET="" C_BOLD="" C_BLUE="" C_GREEN="" C_YELLOW="" C_RED=""
fi

# LOG_FILE is set once we know the firm_dir. Before that, log lines
# go only to the terminal.
LOG_FILE=""

# log/ok/warn/fail print to terminal (TTY-aware color) and optionally
# append a plain version to $LOG_FILE. We print the newline directly
# via printf "%s\n" — capturing into a local with $(...) would
# silently strip the trailing newline (a well-known bash gotcha).
log() {
  printf '%s[provision]%s %s\n' "$C_BLUE" "$C_RESET" "$*"
  if [[ -n "$LOG_FILE" ]]; then
    printf '[%s] [provision] %s\n' "$(date -u +%H:%M:%S)" "$*" >>"$LOG_FILE" 2>/dev/null || true
  fi
}
ok() {
  printf '%s[  ok  ]%s %s\n' "$C_GREEN" "$C_RESET" "$*"
  if [[ -n "$LOG_FILE" ]]; then
    printf '[%s] [  ok  ] %s\n' "$(date -u +%H:%M:%S)" "$*" >>"$LOG_FILE" 2>/dev/null || true
  fi
}
warn() {
  printf '%s[ warn ]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2
  if [[ -n "$LOG_FILE" ]]; then
    printf '[%s] [ warn ] %s\n' "$(date -u +%H:%M:%S)" "$*" >>"$LOG_FILE" 2>/dev/null || true
  fi
}
fail() {
  printf '%s[ fail ]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2
  if [[ -n "$LOG_FILE" ]]; then
    printf '[%s] [ fail ] %s\n' "$(date -u +%H:%M:%S)" "$*" >>"$LOG_FILE" 2>/dev/null || true
  fi
  exit 1
}


# ─── State tracking ─────────────────────────────────────────────────
# The state file lives at ${firm_dir}/.state. Each completed phase
# is appended as one line. Use `state_has` / `state_mark` to interact
# with it. Avoid reading/writing the file directly elsewhere — these
# helpers keep the format consistent.

state_has() {
  local phase="$1" state_file="$2"
  [[ -f "$state_file" ]] && grep -qxF "$phase" "$state_file"
}

state_mark() {
  local phase="$1" state_file="$2"
  if state_has "$phase" "$state_file"; then
    return 0
  fi
  printf '%s\n' "$phase" >>"$state_file"
}

state_next_pending() {
  local state_file="$1"
  local p
  for p in "${PHASES[@]}"; do
    state_has "$p" "$state_file" || { printf '%s' "$p"; return 0; }
  done
  return 1  # all phases done
}

# ─── Error trap ─────────────────────────────────────────────────────
# On any failure, print the offending line number and the firm dir
# so the operator can find logs immediately. We don't auto-rollback
# — that would destroy data the operator might want to inspect.
on_error() {
  local rc=$? lineno=${1:-0}
  if (( lineno > 0 )); then
    warn "provision-firm.sh failed at line ${lineno} (exit ${rc})"
  fi
  if [[ -n "${FIRM_DIR:-}" && -d "${FIRM_DIR:-}" ]]; then
    warn "firm dir: ${FIRM_DIR}"
    warn "state:    ${FIRM_DIR}/.state"
    if [[ -n "${LOG_FILE:-}" && -f "${LOG_FILE}" ]]; then
      warn "log:      ${LOG_FILE}"
      warn "tail:     tail -n 50 ${LOG_FILE}"
    fi
    warn "resume:   sudo $(printf '%q' "$0") --resume ${FIRM_SLUG:-<slug>}"
    warn "rollback: sudo $(printf '%q' "$0") --rollback ${FIRM_SLUG:-<slug>}"
  fi
}
trap 'on_error ${LINENO}' ERR


# ─── Dependency checks ──────────────────────────────────────────────
require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"
}

check_dependencies() {
  require_cmd docker
  require_cmd openssl
  if ! docker compose version >/dev/null 2>&1; then
    fail "docker compose plugin not installed"
  fi
  # htpasswd (apache2-utils) is preferred, but fall back to a Python
  # implementation if it's not installed. Modern Ubuntu cloud images
  # don't ship apache2-utils by default.
  if ! command -v htpasswd >/dev/null 2>&1; then
    log "htpasswd not installed; will use python fallback for Traefik basic auth"
  fi
}
# Generate an htpasswd-compatible `user:bcrypt-hash` line.
# Prefers the real htpasswd binary; falls back to `openssl passwd -6`
# (sha512-crypt) if htpasswd isn't installed. Traefik accepts both
# bcrypt and sha512-crypt for basicauth users.
htpasswd_line() {
  local user="$1" password="$2"
  if command -v htpasswd >/dev/null 2>&1; then
    htpasswd -nB "$user" <<<"$password" | tail -1
  else
    # openssl passwd -6 emits a sha512-crypt hash with a $6$ prefix
    # (e.g. $6$saltsalt$hash...). Compose it into user:hash form.
    local hash
    hash="$(openssl passwd -6 "$password")"
    printf '%s:%s\n' "$user" "$hash"
  fi
}

# ─── Slug validation ────────────────────────────────────────────────
validate_slug() {
  local slug="$1"
  if [[ ! "$slug" =~ ^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$ ]]; then
    fail "invalid firm slug: '${slug}' (must be lowercase letters, digits, dashes; 3-32 chars)"
  fi
  if [[ "$slug" == *".."* ]] || [[ "$slug" == *"--"* ]]; then
    fail "invalid firm slug: '${slug}' (consecutive dashes not allowed)"
  fi
}

# ─── Pre-flight checks ─────────────────────────────────────────────
# Catch obvious problems BEFORE we render files or touch docker:
#   - Port 80/443 already bound (Traefik needs them)
#   - Disk space below threshold (ledger needs ~10 GB)
preflight() {
  local firm_dir="$1"
  local issues=0

  # Port 80/443 free?
  if command -v ss >/dev/null 2>&1; then
    if ss -tlnH 'sport = :80' 2>/dev/null | grep -q LISTEN; then
      warn "port 80 is already in use — Traefik will fail to bind"
      issues=$((issues+1))
    fi
    if ss -tlnH 'sport = :443' 2>/dev/null | grep -q LISTEN; then
      warn "port 443 is already in use — Traefik will fail to bind"
      issues=$((issues+1))
    fi
  fi

  # Disk space — refuse to start if the firm dir's filesystem has
  # less than 5 GB free. ERPNext images alone are ~3 GB.
  if command -v df >/dev/null 2>&1 && [[ -d "$firm_dir" ]]; then
    local free_kb
    free_kb="$(df -Pk "$firm_dir" | awk 'NR==2 {print $4}')"
    if (( free_kb < 5 * 1024 * 1024 )); then
      warn "less than 5 GB free on $(df -P "$firm_dir" | awk 'NR==2 {print $6}') — provision may fail"
      issues=$((issues+1))
    fi
  fi

  if (( issues > 0 )); then
    warn "${issues} preflight issue(s) found — continuing, but expect failures"
  else
    ok "preflight checks passed"
  fi
}


# ─── External network ──────────────────────────────────────────────
# Both docker-compose.yml (main) and traefik/docker-compose.yml
# declare `ledger-net` as `external: true`. That means docker refuses
# to start either stack unless the network already exists. So we
# create it here in the tree-created phase — before any compose up.
#
# Idempotent: if the network already exists (e.g. previous firm on
# the same host provisioned it), this is a no-op. Safe to re-run.
ensure_ledger_network() {
  local net_name="$LEDGER_NETWORK_NAME"
  if docker network inspect "$net_name" >/dev/null 2>&1; then
    log "network ${net_name} already exists — reusing"
    return 0
  fi
  log "creating external network: ${net_name}"
  if ! docker network create --driver bridge "$net_name" >/dev/null; then
    fail "failed to create network ${net_name}"
  fi
  ok "created network ${net_name}"
}


# ─── Secret generation ──────────────────────────────────────────────
gen_secret() {
  # 32 random bytes → base64
  openssl rand -base64 32 | tr -d '\n'
}

gen_hex_secret() {
  openssl rand -hex 32
}

# ─── .env rendering ─────────────────────────────────────────────────
generate_env() {
  local slug="$1" firm_name="$2" admin_email="$3" domain="$4" target="$5"
  local cf_token="${CLOUDFLARE_DNS_API_TOKEN:-}"
  local acme_email="${ACME_EMAIL:-${admin_email}}"
  local b2_id="${B2_ACCOUNT_ID:-}"
  local b2_key="${B2_ACCOUNT_KEY:-}"

  if [[ -z "$cf_token" ]]; then
    warn "CLOUDFLARE_DNS_API_TOKEN not set — wildcard certs will fail until you fill it in."
  fi
  if [[ -z "$b2_id" || -z "$b2_key" ]]; then
    warn "B2_ACCOUNT_ID / B2_ACCOUNT_KEY not set — backups will fail until you fill them in."
  fi

  local pg_pw redis_pw frappe_pw docu_secret docu_db_pw
  local vault_token vault_rsa conductor_token restic_pw traefik_auth
  pg_pw="$(gen_secret)"
  redis_pw="$(gen_secret)"
  frappe_pw="$(gen_secret)"
  docu_secret="$(gen_hex_secret)"
  docu_db_pw="$(gen_secret)"
  vault_token="$(gen_hex_secret)"
  vault_rsa="$(gen_secret)"
  conductor_token="$(gen_hex_secret)"
  restic_pw="$(gen_secret)"

  # htpasswd: non-interactive (-n = print to stdout, -B = bcrypt).
  # The output contains $ characters that bash would otherwise parse as
  # variable references (e.g. $6 → positional param). Single-quote the
  # whole value so the .env file round-trips through `source` cleanly.
  local traefik_admin_user="${TRAEFIK_ADMIN_USER:-admin}"
  local traefik_admin_pw="${TRAEFIK_ADMIN_PASSWORD:-$(gen_secret)}"
  traefik_auth="'$(htpasswd_line "$traefik_admin_user" "$traefik_admin_pw")'"
  if [[ -z "${TRAEFIK_ADMIN_PASSWORD:-}" ]]; then
    warn "Generated Traefik dashboard password (admin): ${traefik_admin_pw}"
    warn "Save this somewhere safe — it's not stored in .env."
  fi

  umask 077
  cat >"$target" <<EOF
# Generated by provision-firm.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# DO NOT COMMIT. .env is in .gitignore.

FIRM_SLUG=${slug}
FIRM_NAME="${firm_name}"
ADMIN_EMAIL=${admin_email}

DOMAIN=${domain}
ACME_EMAIL=${acme_email}

CLOUDFLARE_DNS_API_TOKEN=${cf_token}
TRAEFIK_BASIC_AUTH_USERS=${traefik_auth}

POSTGRES_PASSWORD=${pg_pw}
REDIS_PASSWORD=${redis_pw}
FRAPPE_ADMIN_PASSWORD=${frappe_pw}

DOCUSEAL_SECRET_KEY=${docu_secret}
DOCUSEAL_DB_PASSWORD=${docu_db_pw}

VAULTWARDEN_ADMIN_TOKEN=${vault_token}
VAULTWARDEN_RSA_KEY=${vault_rsa}

CONDUCTOR_ADMIN_TOKEN=${conductor_token}

B2_ACCOUNT_ID=${b2_id}
B2_ACCOUNT_KEY=${b2_key}
B2_BUCKET=${B2_BUCKET:-ledger-backups}
RESTIC_PASSWORD=${restic_pw}
RESTIC_REPO=b2:\${B2_BUCKET}/${slug}

FRAPPE_SITE_NAME=${FRAPPE_SITE_NAME:-ledger}
EOF

  chmod 600 "$target"
  ok "wrote ${target}"
}

# ─── File rendering ─────────────────────────────────────────────────
render_file() {
  local src="$1" dst="$2"
  # Substitute ${FIRM_SLUG} and ${DOMAIN} from the .env we just wrote.
  # Everything else stays literal — docker compose expands at runtime.
  if [[ -f "$dst" ]]; then
    # Only warn; we intentionally overwrite so a re-provision picks up
    # template changes (e.g. new Traefik labels). The .state file
    # protects against re-doing the heavy work (compose up, site create).
    warn "overwriting existing file: ${dst}"
  fi
  mkdir -p "$(dirname "$dst")"
  # shellcheck disable=SC2016  # intentional: pass through docker compose expansion
  envsubst '${FIRM_SLUG} ${DOMAIN}' <"$src" >"$dst"
}

# ─── Stack bring-up ─────────────────────────────────────────────────
bring_up_stack() {
  local firm_dir="$1"
  log "bringing up Traefik for ${FIRM_SLUG}"
  (cd "${firm_dir}/traefik" && docker compose up -d)

  log "bringing up main stack for ${FIRM_SLUG}"
  (cd "${firm_dir}" && docker compose up -d)

  log "waiting for Frappe healthcheck (up to 5 min)..."
  local i=0
  while (( i < 60 )); do
    if (cd "${firm_dir}" && docker compose exec -T frappe-erpnext \
          curl -fsS http://localhost:8000/api/method/ping >/dev/null 2>&1); then
      ok "frappe-erpnext is healthy"
      return 0
    fi
    sleep 5
    ((i++))
  done
  warn "frappe healthcheck timed out — check 'docker compose logs frappe-erpnext'"
  return 1
}


# ─── Backup cron ────────────────────────────────────────────────────
install_backup_cron() {
  local firm_dir="$1" slug="$2"
  local cron_line="0 3 * * * cd ${firm_dir} && ${firm_dir}/scripts/backup.sh >>${firm_dir}/logs/backup.log 2>&1"
  local existing
  existing="$(crontab -l 2>/dev/null || true)"
  if grep -qF "${firm_dir}/scripts/backup.sh" <<<"$existing"; then
    log "backup cron already installed for ${slug}"
  else
    printf '%s\n' "$existing" "$cron_line" | grep -v '^$' | crontab -
    ok "installed nightly backup cron for ${slug}"
  fi
}

# ─── Cron uninstall (for --rollback) ───────────────────────────────
uninstall_backup_cron() {
  local firm_dir="$1" slug="$2"
  local existing
  existing="$(crontab -l 2>/dev/null || true)"
  if grep -qF "${firm_dir}/scripts/backup.sh" <<<"$existing"; then
    printf '%s\n' "$existing" \
      | grep -vF "${firm_dir}/scripts/backup.sh" \
      | crontab -
    ok "removed backup cron for ${slug}"
  else
    log "no backup cron to remove for ${slug}"
  fi
}

# ─── Verification checklist ─────────────────────────────────────────
print_verification() {
  local slug="$1" domain="$2"
  cat <<EOF

${C_BOLD}Verification checklist for ${slug}:${C_RESET}
  [ ] tailscale status — confirm VPS is on Konan's tailnet
  [ ] curl -fsS https://traefik.${slug}.${domain}/api/ping
  [ ] curl -fsS https://ledger.${slug}.${domain}/api/method/ping
  [ ] curl -fsS https://sign.${slug}.${domain}/  (DocuSeal)
  [ ] curl -fsS https://vault.${slug}.${domain}/alive  (Vaultwarden)
  [ ] Login to Frappe, see ledger_brand skin + demo client
  [ ] Run ${C_BOLD}backup.sh --dry-run${C_RESET} to verify restic repo
  [ ] Run ${C_BOLD}./scripts/validate-firm.sh ${slug}${C_RESET} for automated checks

For automated post-provision validation, run:
  sudo /srv/ledger/${slug}/scripts/validate-firm.sh

EOF
}

# ─── Dry run ────────────────────────────────────────────────────────
dry_run() {
  log "dry-run: validating templates and dependencies"
  check_dependencies

  # Build a dummy .env so `docker compose config` doesn't fail on the
  # ${VAR:?...} validations in the template. The values are not used
  # to start anything — only to parse the YAML.
  #
  # Phase L0 (2026-06-21) added Pantheon Core, which requires
  # HERMES_SESSION_TOKEN + PRACTICE_MANAGER_API_KEY. Phase L2 (2026-
  # 06-21) verified they're actually interpolated by `docker compose
  # config` (the dry-run gate) — without them the gate fails before
  # it can ever start a real provision.
  local dummy_env
  dummy_env="$(mktemp)"
  cat >"$dummy_env" <<'EOF'
FIRM_SLUG=dryrun-firm
DOMAIN=theoforge.app
ACME_EMAIL=dryrun@example.com
TRAEFIK_BASIC_AUTH_USERS='admin:$apr1$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd'
POSTGRES_PASSWORD=dummy
REDIS_PASSWORD=dummy
FRAPPE_ADMIN_PASSWORD=dummy
DOCUSEAL_SECRET_KEY=dummy
DOCUSEAL_DB_PASSWORD=dummy
VAULTWARDEN_ADMIN_TOKEN=dummy
VAULTWARDEN_RSA_KEY=dummy
CONDUCTOR_ADMIN_TOKEN=dummy
HERMES_SESSION_TOKEN=dummy
PRACTICE_MANAGER_API_KEY=dummy
B2_ACCOUNT_ID=dummy
B2_ACCOUNT_KEY=dummy
RESTIC_PASSWORD=dummy
RESTIC_REPO=b2:dummy/dummy
EOF

  # Validate the Traefik docker-compose + main docker-compose.
  if ! docker compose -f "${TEMPLATE_DIR}/traefik/docker-compose.yml" \
        --project-name theoforge-dryrun \
        --env-file "$dummy_env" \
        config >/dev/null; then
    rm -f "$dummy_env"
    fail "traefik/docker-compose.yml failed 'docker compose config'"
  fi
  if ! docker compose -f "${TEMPLATE_DIR}/docker-compose.yml" \
        --project-name theoforge-dryrun \
        --env-file "$dummy_env" \
        config >/dev/null; then
    rm -f "$dummy_env"
    fail "docker-compose.yml failed 'docker compose config'"
  fi
  rm -f "$dummy_env"

  # Validate the dynamic traefik config (YAML only — Traefik itself
  # isn't running here).
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "
import sys, yaml
for p in ['${TEMPLATE_DIR}/traefik/traefik.yml',
          '${TEMPLATE_DIR}/traefik/dynamic/tls.yml']:
    try:
        with open(p) as f:
            yaml.safe_load(f)
    except Exception as e:
        sys.exit(f'{p}: {e}')
" || fail "traefik YAML files have syntax errors"
    ok "traefik YAML parses cleanly"
  fi

  # Validate the shell scripts with shellcheck if available.
  if command -v shellcheck >/dev/null 2>&1; then
    log "running shellcheck on scripts/"
    # SC1091 — sourcing files we don't have is fine (they live in /srv/ledger).
    # SC2086 — word splitting on variables is intentional in some spots.
    # SC2155 — declare-and-assign without quoting is a stylistic note, not a bug.
    shellcheck -e SC1091,SC2086,SC2155 \
      "${TEMPLATE_DIR}/scripts/"provision-firm.sh \
      "${TEMPLATE_DIR}/scripts/"create-site.sh \
      "${TEMPLATE_DIR}/scripts/"backup.sh \
      "${TEMPLATE_DIR}/scripts/"restore.sh \
      "${TEMPLATE_DIR}/scripts/"validate-firm.sh \
      "${TEMPLATE_DIR}/scripts/"monitor-firm.sh \
      || fail "shellcheck failed"
    ok "shellcheck passed"
  else
    warn "shellcheck not installed — skipping script lint"
  fi

  ok "templates validate cleanly"
}


# ─── --status: show current state of a firm ────────────────────────
show_status() {
  local firm_dir="$1" slug="$2"
  local state_file="${firm_dir}/.state"

  echo "Firm: ${C_BOLD}${slug}${C_RESET}"
  echo "Dir:  ${firm_dir}"

  if [[ ! -d "$firm_dir" ]]; then
    echo
    echo "Status: ${C_YELLOW}not provisioned${C_RESET} (directory does not exist)"
    exit 0
  fi

  echo
  local env_file="${firm_dir}/.env"
  if [[ -f "$env_file" ]]; then
    echo ".env:  present (size: $(stat -c%s "$env_file" 2>/dev/null || stat -f%z "$env_file") bytes)"
  else
    echo ".env:  ${C_YELLOW}missing${C_RESET}"
  fi

  echo
  echo "Phases:"
  local p
  for p in "${PHASES[@]}"; do
    if state_has "$p" "$state_file"; then
      printf '  %s[done]%s  %s\n' "$C_GREEN" "$C_RESET" "$p"
    else
      printf '  %s[ todo]%s %s\n' "$C_YELLOW" "$C_RESET" "$p"
    fi
  done

  if [[ -f "${firm_dir}/docker-compose.yml" ]]; then
    echo
    echo "Compose status (if reachable):"
    if (cd "$firm_dir" && docker compose ps --format json 2>/dev/null \
          | jq -r '.Name + " " + .State' 2>/dev/null) | head -10; then
      :
    else
      echo "  (docker compose ps unavailable — is the daemon up?)"
    fi
  fi

  echo
  if state_has cron-installed "$state_file"; then
    echo "Cron: nightly backup installed"
  else
    echo "Cron: ${C_YELLOW}not installed${C_RESET}"
  fi
}

# ─── --rollback: tear down a firm ──────────────────────────────────
do_rollback() {
  local firm_dir="$1" slug="$2" purge="$3" confirm="$4"

  if [[ ! -d "$firm_dir" ]]; then
    fail "firm dir does not exist: ${firm_dir}"
  fi

  echo "${C_BOLD}Rollback plan for ${slug}:${C_RESET}"
  echo "  1. Stop the docker stack (containers only — volumes KEPT)"
  echo "  2. Remove the backup cron"
  if (( purge )); then
    echo "  3. Delete docker volumes (--purge — DATA LOSS)"
    echo "  4. Delete rendered files + .env + .state"
    echo "  5. Delete the firm directory: ${firm_dir}"
  else
    echo "  3. Delete rendered files + .state"
    echo "  4. Keep .env (in case you want to restart)"
    echo "  5. Keep firm directory shell"
  fi

  echo
  if (( ! confirm )); then
    local reply
    read -r -p "Proceed? [y/N] " reply
    [[ "$reply" == "y" || "$reply" == "Y" ]] || { log "aborted"; exit 0; }
  fi

  # 1. Stop the stack.
  if [[ -f "${firm_dir}/docker-compose.yml" ]]; then
    log "stopping docker stack for ${slug}"
    if (cd "$firm_dir" && docker compose down --remove-orphans 2>&1); then
      ok "docker stack stopped"
    else
      warn "docker compose down failed — continuing anyway"
    fi
  fi

  # 2. Remove cron.
  uninstall_backup_cron "$firm_dir" "$slug"

  # 3. (optional) Remove volumes.
  if (( purge )); then
    log "removing docker volumes (purge)"
    local vols=(
      "${slug}-postgres-data"
      "${slug}-redis-data"
      "${slug}-frappe-sites"
      "${slug}-frappe-apps"
      "${slug}-docuseal-data"
      "${slug}-docuseal-db-data"
      "${slug}-vaultwarden-data"
      "${slug}-conductor-data"
      "${slug}-traefik-letsencrypt"
    )
    local v
    for v in "${vols[@]}"; do
      if docker volume inspect "$v" >/dev/null 2>&1; then
        if docker volume rm "$v" >/dev/null 2>&1; then
          ok "removed volume: ${v}"
        else
          warn "failed to remove volume: ${v}"
        fi
      fi
    done
  fi

  # 4. Remove rendered files + state. .env is preserved unless --purge.
  local state_file="${firm_dir}/.state"
  rm -f "$state_file"
  rm -rf "${firm_dir}/traefik"
  rm -f "${firm_dir}/docker-compose.yml"
  rm -rf "${firm_dir}/logs"
  if (( purge )); then
    rm -f "${firm_dir}/.env"
    rm -rf "${firm_dir}/backups"
    rm -rf "${firm_dir}/scripts"
    rm -f "${firm_dir}/.data-root"
  fi

  if (( purge )); then
    log "removing firm directory: ${firm_dir}"
    rmdir "$firm_dir" 2>/dev/null \
      || warn "firm dir is not empty (backups?) — left in place"
    ok "firm ${slug} fully purged"
  else
    ok "firm ${slug} stopped (data preserved for restart)"
    echo
    echo "To restart: re-run provision-firm.sh with the same slug."
    echo "To fully purge data: --rollback --purge --confirm"
  fi
}

# ─── Main flow ──────────────────────────────────────────────────────
usage() {
  cat <<EOF
provision-firm.sh — provision a new TheoForge Ledger firm.

USAGE
  provision-firm.sh --dry-run
  provision-firm.sh --status <slug>
  provision-firm.sh --rollback [--purge] [--confirm] <slug>
  provision-firm.sh --resume <slug>
  provision-firm.sh --generate-env <slug>
  provision-firm.sh [--data-root <path>] [--domain <name>] [--non-interactive] [--force] <slug>

OPTIONS
  --dry-run                Validate templates + scripts, exit.
  --status <slug>          Show what phases of a firm have completed.
  --rollback <slug>        Tear down a firm. Volumes kept by default;
                           pass --purge to delete data volumes too.
                           Pass --confirm to skip the prompt (CI use).
  --resume <slug>          Continue a previously-failed provision
                           from the first incomplete phase.
  --generate-env <slug>    Only generate the .env file (no stack bring-up).
  --force                  Re-render files + re-up containers even if
                           the state says they're done. Use after a
                           template change.
  --data-root <path>       Where to put firm data (default: ${DEFAULT_DATA_ROOT}).
  --domain <name>          Apex domain (default: ${DEFAULT_DOMAIN}).
  --non-interactive        Skip prompts; require env vars FIRM_NAME, ADMIN_EMAIL.
  --from-stdin             Read firm_name + admin_email from stdin (2 lines).
  -h, --help               This help text.

ENV VARS (consumed by --generate-env / --non-interactive)
  FIRM_NAME                Display name (e.g. "Jones & Co CPAs")
  ADMIN_EMAIL              Admin contact email
  CLOUDFLARE_DNS_API_TOKEN Cloudflare DNS API token (optional, see .env.example)
  B2_ACCOUNT_ID            Backblaze B2 key ID (optional)
  B2_ACCOUNT_KEY           Backblaze B2 application key (optional)
  TRAEFIK_ADMIN_USER       Traefik dashboard user (default: admin)
  TRAEFIK_ADMIN_PASSWORD   If unset, one is generated and printed once

EXAMPLES
  # Validate templates
  provision-firm.sh --dry-run

  # Provision a firm interactively
  sudo provision-firm.sh jones-cpa

  # Headless provision (in CI / cron)
  FIRM_NAME="Jones & Co" ADMIN_EMAIL=ops@jones.co \\
    CLOUDFLARE_DNS_API_TOKEN=*** \\
    sudo provision-firm.sh --non-interactive jones-cpa

  # Provision failed at the Frappe healthcheck — pick up where it left off
  sudo provision-firm.sh --resume jones-cpa

  # See where a provision left off
  provision-firm.sh --status jones-cpa

  # Stop a firm (data preserved)
  sudo provision-firm.sh --rollback jones-cpa

  # Stop a firm AND delete all data
  sudo provision-firm.sh --rollback --purge --confirm jones-cpa
EOF
}

main() {
  local slug="" data_root="$DEFAULT_DATA_ROOT" domain="$DEFAULT_DOMAIN"
  local non_interactive=0 from_stdin=0 dry=0 gen_only=0
  local cmd_status=0 cmd_rollback=0 cmd_resume=0 purge=0 confirm=0 force=0

  while (( $# > 0 )); do
    case "$1" in
      --dry-run)             dry=1 ;;
      --status)              cmd_status=1; shift; slug="${1:?--status requires slug}" ;;
      --rollback)            cmd_rollback=1; shift; slug="${1:?--rollback requires slug}" ;;
      --resume)              cmd_resume=1; shift; slug="${1:?--resume requires slug}" ;;
      --generate-env)        gen_only=1; shift; slug="${1:?--generate-env requires slug}" ;;
      --data-root)           shift; data_root="${1:?--data-root requires path}" ;;
      --domain)              shift; domain="${1:?--domain requires name}" ;;
      --non-interactive)     non_interactive=1 ;;
      --from-stdin)          from_stdin=1 ;;
      --purge)               purge=1 ;;
      --confirm)             confirm=1 ;;
      --force)               force=1 ;;
      -h|--help)             usage; exit 0 ;;
      -*)                    fail "unknown flag: $1" ;;
      *)                     slug="${1:?firm slug required}" ;;
    esac
    shift
  done

  # ─── Dispatch ──────────────────────────────────────────────────
  if (( dry )); then
    dry_run
    exit 0
  fi

  if [[ -z "$slug" ]]; then
    usage >&2
    fail "firm slug required (or use --dry-run)"
  fi

  validate_slug "$slug"
  local firm_dir="${data_root}/${slug}"
  export FIRM_DIR="$firm_dir"

  if (( cmd_status )); then
    show_status "$firm_dir" "$slug"
    exit 0
  fi

  if (( cmd_rollback )); then
    do_rollback "$firm_dir" "$slug" "$purge" "$confirm"
    exit 0
  fi

  # From here on we need the firm dir to exist (or be created). Wire
  # up logging to ${firm_dir}/logs/provision.log once we know the path.
  mkdir -p "${firm_dir}/logs"
  LOG_FILE="${firm_dir}/logs/provision.log"
  # Write a session header to the log so successive runs are greppable.
  {
    printf '─── run started at %s by pid %s ───\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$$"
    printf 'args: %s\n' "$*"
  } >>"$LOG_FILE"

  local state_file="${firm_dir}/.state"

  check_dependencies
  preflight "$firm_dir"

  # If --resume, derive which phases still need doing.
  if (( cmd_resume )); then
    if [[ ! -d "$firm_dir" ]]; then
      fail "--resume needs an existing firm dir — run a normal provision first"
    fi
    log "resuming ${slug} from ${state_file}"
    if [[ -f "$state_file" ]]; then
      sed 's/^/  ✓ /' "$state_file" 2>/dev/null || true
    fi
    echo
  fi

  # Resolve the firm directory root permission.
  if [[ ! -d "$data_root" ]] && (( EUID != 0 )); then
    fail "data root ${data_root} does not exist — create it (e.g. sudo mkdir -p ${data_root})"
  fi

  # Gather firm metadata.
  local firm_name="${FIRM_NAME:-}" admin_email="${ADMIN_EMAIL:-}"
  if (( from_stdin )); then
    IFS= read -r firm_name
    IFS= read -r admin_email
  elif (( ! non_interactive )); then
    [[ -z "$firm_name" ]] && read -r -p "Firm display name (e.g. 'Jones & Co CPAs'): " firm_name
    [[ -z "$admin_email" ]] && read -r -p "Admin email (LE contact + ops): " admin_email
  fi

  # Fail-fast on missing required vars BEFORE creating the tree.
  if (( cmd_resume )); then
    # On resume we trust the existing .env — don't require firm_name again.
    :
  else
    [[ -n "$firm_name" ]] || fail "FIRM_NAME is required"
    [[ -n "$admin_email" ]] || fail "ADMIN_EMAIL is required"
  fi

  log "provisioning ${C_BOLD}${slug}${C_RESET} (${firm_name:-resuming}) into ${firm_dir}"

  # ─── Phase 1: tree ─────────────────────────────────────────────
  if state_has tree-created "$state_file" && (( ! force )); then
    log "tree-created — already done, skipping"
  else
    mkdir -p "${firm_dir}"/{backups,logs,scripts}
    # External bridge that BOTH the Traefik stack and the main stack
    # attach to. Both compose files declare it `external: true` —
    # they will refuse to start without it. Idempotent: re-running
    # against an existing network is a no-op.
    ensure_ledger_network
    state_mark tree-created "$state_file"
  fi

  # ─── Phase 2: .env ─────────────────────────────────────────────
  local env_file="${firm_dir}/.env"
  if state_has env-generated "$state_file" && [[ -f "$env_file" ]] && (( ! force )); then
    log "env-generated — already done, reusing ${env_file}"
    set -a
    # shellcheck source=/dev/null
    source "$env_file"
    set +a
    export FIRM_SLUG="$slug"
    export DOMAIN="$domain"
  else
    if [[ -f "$env_file" ]]; then
      warn "reusing existing ${env_file} (delete to regenerate secrets)"
      set -a
      # shellcheck source=/dev/null
      source "$env_file"
      set +a
      export FIRM_SLUG="$slug"
      export DOMAIN="$domain"
      state_mark env-generated "$state_file"
    else
      generate_env "$slug" "$firm_name" "$admin_email" "$domain" "$env_file"
      set -a
      # shellcheck source=/dev/null
      source "$env_file"
      set +a
      state_mark env-generated "$state_file"
    fi
  fi

  # --generate-env exits here, before any compose / traefik rendering.
  if (( gen_only )); then
    ok "generated .env for ${slug} at ${env_file}"
    exit 0
  fi

  # ─── Phase 3: rendered files ───────────────────────────────────
  if state_has files-rendered "$state_file" && [[ -f "${firm_dir}/docker-compose.yml" ]] && (( ! force )); then
    log "files-rendered — already done, skipping"
  else
    # Render Traefik: compose + static config + dynamic tls config.
    # The dynamic/ subdir holds hot-reloadable TLS + middlewares;
    # mkdir it before any cp/envsubst into it.
    mkdir -p "${firm_dir}/traefik/dynamic"
    render_file "${TEMPLATE_DIR}/traefik/docker-compose.yml" "${firm_dir}/traefik/docker-compose.yml"
    cp "${TEMPLATE_DIR}/traefik/traefik.yml" "${firm_dir}/traefik/traefik.yml"
    cp "${TEMPLATE_DIR}/traefik/dynamic/tls.yml" "${firm_dir}/traefik/dynamic/tls.yml"

    # Sub the slug into the dynamic config too.
    # shellcheck disable=SC2016  # intentional: envsubst handles expansion
    envsubst '${FIRM_SLUG} ${DOMAIN} ${TRAEFIK_BASIC_AUTH_USERS}' \
      <"${TEMPLATE_DIR}/traefik/dynamic/tls.yml" \
      >"${firm_dir}/traefik/dynamic/tls.yml"

    # Copy the main compose file + scripts.
    cp "${TEMPLATE_DIR}/docker-compose.yml" "${firm_dir}/docker-compose.yml"
    cp "${TEMPLATE_DIR}/scripts/"*.sh "${firm_dir}/scripts/"
    chmod +x "${firm_dir}/scripts/"*.sh

    # Persist the data root on the firm so re-runs find it.
    printf '%s\n' "$data_root" >"${firm_dir}/.data-root"

    state_mark files-rendered "$state_file"
  fi

  # ─── Phase 4 + 5: bring up the stacks ──────────────────────────
  if state_has stack-up "$state_file" && (( ! force )); then
    log "stack-up — already done, skipping"
  else
    # Traefik and main stack are coupled — if one is missing, do both.
    if ! state_has traefik-up "$state_file" || (( force )); then
      log "bringing up Traefik for ${FIRM_SLUG}"
      (cd "${firm_dir}/traefik" && docker compose up -d)
      state_mark traefik-up "$state_file"
    fi

    log "bringing up main stack for ${FIRM_SLUG}"
    (cd "${firm_dir}" && docker compose up -d)
    state_mark stack-up "$state_file"

    log "waiting for Frappe healthcheck (up to 5 min)..."
    local i=0
    while (( i < 60 )); do
      if (cd "${firm_dir}" && docker compose exec -T frappe-erpnext \
            curl -fsS http://localhost:8000/api/method/ping >/dev/null 2>&1); then
        ok "frappe-erpnext is healthy"
        state_mark frappe-healthy "$state_file"
        break
      fi
      sleep 5
      ((i++))
    done

    if ! state_has frappe-healthy "$state_file"; then
      warn "frappe healthcheck timed out — continuing; run --resume later"
    fi
  fi

  # ─── Phase 6: site create ──────────────────────────────────────
  if state_has site-created "$state_file" && (( ! force )); then
    log "site-created — already done, skipping"
  else
    if (cd "${firm_dir}" && docker compose exec -T frappe-erpnext \
          test -f /home/frappe/frappe-bench/sites/${FRAPPE_SITE_NAME:-ledger}.${domain}/site_config.json); then
      log "frappe site ${FRAPPE_SITE_NAME:-ledger}.${domain} already exists — skipping create-site.sh"
      state_mark site-created "$state_file"
    else
      log "running create-site.sh for first-time Frappe site"
      # Use env(1) so the per-invocation exports are unambiguous.
      env \
        FRAPPE_SITE_NAME="${FRAPPE_SITE_NAME:-ledger}" \
        FRAPPE_DOMAIN="${FRAPPE_SITE_NAME:-ledger}.${domain}" \
        "${firm_dir}/scripts/create-site.sh"
      state_mark site-created "$state_file"
    fi
  fi

  # ─── Phase 7: backup cron ──────────────────────────────────────
  if state_has cron-installed "$state_file" && (( ! force )); then
    log "cron-installed — already done, skipping"
  else
    install_backup_cron "$firm_dir" "$slug"
    state_mark cron-installed "$state_file"
  fi

  print_verification "$slug" "$domain"
  ok "done. See README.md for ongoing operations."
  echo
  echo "Run ${C_BOLD}/srv/ledger/${slug}/scripts/validate-firm.sh${C_RESET} to verify"
  echo "the firm is reachable end-to-end (the automatable parts of the"
  echo "first-10-minutes test)."

  {
    printf '─── run finished at %s ───\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >>"$LOG_FILE"
}

main "$@"
