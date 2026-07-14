#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# create-site.sh — bootstrap a Frappe site inside the running stack.
#
# Usage:
#   create-site.sh                    # uses $FRAPPE_SITE_NAME + $DOMAIN
#   create-site.sh <site-name>        # explicit site name (no domain)
#   create-site.sh --dry-run          # print bench commands without running
#
# Reads the following env vars (set by provision-firm.sh or exported
# by hand):
#   FRAPPE_SITE_NAME   site name (default: ledger)
#   DOMAIN             apex domain (default: theoforge.app)
#   ADMIN_EMAIL        admin email (default: administrator@${FRAPPE_SITE_NAME}.${DOMAIN})
#   FRAPPE_ADMIN_PASSWORD  required (set by docker compose from .env)
#
# Idempotent: re-running on a configured site is a no-op (prints a
# message and exits 0).
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail
IFS=$'\n\t'

# ─── Defaults from env ──────────────────────────────────────────────
FRAPPE_SITE_NAME="${FRAPPE_SITE_NAME:-ledger}"
DOMAIN="${DOMAIN:-theoforge.app}"
SITE_FQDN="${FRAPPE_SITE_NAME}.${DOMAIN}"
ADMIN_EMAIL="${ADMIN_EMAIL:-administrator@${SITE_FQDN}}"

# Color helpers (only on TTY).
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_BLUE=$'\033[34m'; C_GREEN=$'\033[32m'; C_RED=$'\033[31m'
else
  C_RESET=""; C_BLUE=""; C_GREEN=""; C_RED=""
fi
log()  { printf '%s[site]%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()   { printf '%s[ ok ]%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
fail() { printf '%s[fail]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }

# ─── Dependency checks ──────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || fail "docker not installed"

usage() {
  cat <<EOF
create-site.sh — bootstrap the Frappe site for this firm.

USAGE
  create-site.sh [site-name] [--dry-run]

Reads FRAPPE_SITE_NAME, DOMAIN, ADMIN_EMAIL, FRAPPE_ADMIN_PASSWORD from the
environment (set automatically by docker compose from .env).

EXAMPLES
  create-site.sh                       # uses .env values
  create-site.sh ledger-staging       # override site name
  FRAPPE_SITE_NAME=ledger create-site.sh
EOF
}

dry_run=0
target_site=""
for arg in "$@"; do
  case "$arg" in
    -h|--help)     usage; exit 0 ;;
    --dry-run)     dry_run=1 ;;
    -*)            fail "unknown flag: $arg" ;;
    *)             target_site="$arg" ;;
  esac
done

[[ -n "$target_site" ]] && FRAPPE_SITE_NAME="$target_site"
SITE_FQDN="${FRAPPE_SITE_NAME}.${DOMAIN}"

: "${FRAPPE_ADMIN_PASSWORD:?FRAPPE_ADMIN_PASSWORD must be set (via .env or env)}"

# ─── Detect existing site ───────────────────────────────────────────
log "checking if site ${SITE_FQDN} already exists"
bench_exec() {
  docker compose exec -T frappe-erpnext \
    bash -c "cd /home/frappe/frappe-bench && $*"
}

if bench_exec "test -f sites/${SITE_FQDN}/site_config.json" 2>/dev/null; then
  ok "site ${SITE_FQDN} already exists — skipping"
  exit 0
fi

# ─── Build the bench command ────────────────────────────────────────
# Full multi-line bench command as a single string for `bench exec`.
new_site_cmd="bench new-site ${SITE_FQDN} \\
  --db-type=postgres \\
  --db-host=postgres \\
  --db-port=5432 \\
  --db-name=\${POSTGRES_DB:-frappe} \\
  --db-user=\${POSTGRES_USER:-frappe} \\
  --db-password=\${POSTGRES_PASSWORD} \\
  --admin-password=\${FRAPPE_ADMIN_PASSWORD} \\
  --db-root-username=frappe \\
  --db-root-password=\${POSTGRES_PASSWORD} \\
  --force \\
  --install-app erpnext \\
  --install-app ledger_brand"

if (( dry_run )); then
  log "dry-run: would execute the following inside the frappe container:"
  printf '  %s\n' "$new_site_cmd"
  exit 0
fi

# ─── Execute ────────────────────────────────────────────────────────
log "creating site ${SITE_FQDN}"
if ! bench_exec "$new_site_cmd"; then
  fail "bench new-site failed — see frappe container logs"
fi

# Set the site name in Frappe's site_config.
log "writing site_config.json (HTTPS, host_name)"
bench_exec "bench set-config -g \
  host_name https://${SITE_FQDN} \
  db_name \${POSTGRES_DB:-frappe} \
  db_type postgres \
  encryption_key \$(openssl rand -hex 32)"

# Install the custom Ledger brand app on the new site.
log "installing ledger_brand app"
bench_exec "bench --site ${SITE_FQDN} install-app ledger_brand || true" \
  || warn "ledger_brand app install failed — install manually with 'bench install-app ledger_brand'"

# Enable scheduler + daily backups.
log "enabling scheduler + daily backup"
bench_exec "bench --site ${SITE_FQDN} enable-scheduler"
bench_exec "bench --site ${SITE_FQDN} set-config -g backup_path /home/frappe/frappe-bench/sites/${SITE_FQDN}/private/backups"
# Kick the scheduler to start running queued tasks immediately. Wrapped in
# || true so a missing frappe.utils.scheduler.enqueue_scheduler (e.g.
# stripped Frappe build) doesn't fail the whole bootstrap.
bench_exec "bench --site ${SITE_FQDN} execute frappe.utils.scheduler.enqueue_scheduler" \
  || warn "scheduler enqueue failed — run 'bench execute frappe.utils.scheduler.enqueue_scheduler' manually"

# Configure Nginx inside the Frappe container to listen on :8000 only
# (Traefik handles TLS termination — Frappe's built-in nginx would
# otherwise claim :80).
log "disabling Frappe's built-in nginx (Traefik handles TLS)"
bench_exec "bench setup nginx --yes || true"

ok "site ${SITE_FQDN} ready"
printf '\nNext steps:\n'
printf '  1. Visit https://%s and login as Administrator.\n' "$SITE_FQDN"
printf '  2. Verify the Ledger branding is active (logo, sidebar color).\n'
# shellcheck disable=SC2016  # ${FIRM_SLUG} is intentionally literal here
printf '  3. Run /srv/ledger/${FIRM_SLUG}/scripts/backup.sh to seed the restic repo.\n'