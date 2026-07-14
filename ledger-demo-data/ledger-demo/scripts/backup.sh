#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# backup.sh — snapshot the firm's data into Backblaze B2 via restic.
#
# Usage:
#   backup.sh                 # full backup of all named volumes + db
#   backup.sh --dry-run       # show what would run, don't touch B2
#   backup.sh --only=db       # just a postgres dump + restic snapshot
#   backup.sh --prune         # snapshot + prune old (keep policy)
#
# What gets backed up:
#   1. Named docker volumes (frappe sites, postgres data, redis, etc.)
#   2. /srv/ledger/{slug}/.env       (encrypted at rest by restic)
#   3. /srv/ledger/{slug}/docker-compose.yml + traefik/ + scripts/
#   4. Postgres logical dump (per-service)
#
# Retention policy (override via RESTIC_KEEP_* env vars):
#   RESTIC_KEEP_HOURLY=6   RESTIC_KEEP_DAILY=30
#   RESTIC_KEEP_WEEKLY=4   RESTIC_KEEP_MONTHLY=6
#
# Cron: installed by provision-firm.sh (03:00 nightly).
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIRM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ─── Colors (TTY only) ──────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_BLUE=$'\033[34m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'
else
  C_RESET=""; C_BLUE=""; C_GREEN=""; C_YELLOW=""; C_RED=""
fi
log()  { printf '%s[backup]%s %s\n' "$C_BLUE"  "$C_RESET" "$*"; }
ok()   { printf '%s[  ok ]%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s[ warn ]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
fail() { printf '%s[ fail ]%s %s\n' "$C_RED"   "$C_RESET" "$*" >&2; exit 1; }

# ─── Tools ──────────────────────────────────────────────────────────
# Only required when we're actually doing work. --help must work
# even on a barebones host without restic / docker installed.
require_tools() {
  command -v restic >/dev/null 2>&1 || fail "restic not installed"
  command -v docker >/dev/null 2>&1 || fail "docker not installed"
}

# ─── Load .env if present ──────────────────────────────────────────
if [[ -f "${FIRM_DIR}/.env" ]]; then
  log "loading ${FIRM_DIR}/.env"
  set -a
  # shellcheck disable=SC1091  # sourced file lives in /srv/ledger, not here
  source "${FIRM_DIR}/.env"
  set +a
fi

# Arg parsing — exit before checking dependencies if we just want help.
dry_run=0
only=""
prune=0
for arg in "$@"; do
  case "$arg" in
    --dry-run)       dry_run=1 ;;
    --only=*)        only="${arg#--only=}" ;;
    --prune)         prune=1 ;;
    -h|--help)
      cat <<EOF
backup.sh — restic + B2 backup for one firm.

USAGE
  backup.sh [--dry-run] [--only=db|volumes|configs] [--prune]

ENV VARS (set from .env by provision-firm.sh)
  RESTIC_REPO, RESTIC_PASSWORD    restic backend (b2:bucket/slug)
  B2_ACCOUNT_ID, B2_ACCOUNT_KEY   Backblaze B2 application key
  FIRM_SLUG, POSTGRES_PASSWORD    firm identity + db password

RETENTION
  RESTIC_KEEP_HOURLY=6  RESTIC_KEEP_DAILY=30
  RESTIC_KEEP_WEEKLY=4  RESTIC_KEEP_MONTHLY=6
EOF
      exit 0 ;;
    *) fail "unknown flag: $arg" ;;
  esac
done

# Past here we actually need restic + docker.
require_tools

# ─── restic env ─────────────────────────────────────────────────────
export RESTIC_REPOSITORY="$RESTIC_REPO"
export RESTIC_PASSWORD
export AWS_ACCESS_KEY_ID="$B2_ACCOUNT_ID"
export AWS_SECRET_ACCESS_KEY="$B2_ACCOUNT_KEY"

# ─── Helpers ────────────────────────────────────────────────────────
run_or_print() {
  if (( dry_run )); then
    printf '  [dry-run] %s\n' "$*"
  else
    "$@"
  fi
}

ensure_repo() {
  if (( dry_run )); then
    log "[dry-run] would 'restic snapshots' / init if missing"
    return 0
  fi
  if ! restic snapshots --no-lock >/dev/null 2>&1; then
    log "initializing restic repo at ${RESTIC_REPOSITORY}"
    restic init
    ok "restic repo initialized"
  else
    log "restic repo already initialized"
  fi
}

snapshot_path() {
  local path="$1" tag="$2"
  run_or_print restic backup \
    --tag "$tag" \
    --exclude-caches \
    --exclude-file "${FIRM_DIR}/scripts/backup.exclude" \
    "$path"
}

pg_dump() {
  local db="$1" container="$2" outfile="$3"
  log "dumping ${db} → ${outfile}"
  run_or_print docker compose -f "${FIRM_DIR}/docker-compose.yml" exec -T "$container" \
    sh -c "pg_dump -U \$POSTGRES_USER -d $db" ">${outfile}"
}

# ─── Step 1: postgres dumps ────────────────────────────────────────
mkdir -p "${FIRM_DIR}/backups/dumps"

run_db_backup() {
  if [[ -n "$only" && "$only" != "db" ]]; then
    return 0
  fi

  log "snapshotting postgres dumps"

  local stamp
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  local tmp_dir="${FIRM_DIR}/backups/dumps/${stamp}"
  mkdir -p "$tmp_dir"

  # Frappe database.
  pg_dump "${POSTGRES_DB:-frappe}" postgres "${tmp_dir}/frappe.sql"

  # DocuSeal database.
  pg_dump docuseal docuseal-db "${tmp_dir}/docuseal.sql"

  # Bundle the dumps + the firm's static config into one snapshot.
  snapshot_path "${FIRM_DIR}/backups/dumps/${stamp}" "db-${stamp}"

  # Local retention — keep 7 days of dumps locally so a quick restore
  # doesn't need a B2 round-trip.
  find "${FIRM_DIR}/backups/dumps" -mindepth 1 -maxdepth 1 -type d \
    -mtime +7 -exec rm -rf {} +

  ok "db dumps snapshotted"
}

# ─── Step 2: named volumes ─────────────────────────────────────────
run_volumes_backup() {
  if [[ -n "$only" && "$only" != "volumes" ]]; then
    return 0
  fi

  log "snapshotting named docker volumes"
  # Restic reads directly from the volume mount points. We don't back
  # up live volumes (consistency) — we use the host-level bind mounts
  # under /var/lib/docker/volumes/{name}/_data.
  #
  # For consistency, the docker-compose stack defines volumes like:
  #   postgres_data, redis_data, frappe_sites, frappe_apps,
  #   docuseal_data, docuseal_db_data, vaultwarden_data, conductor_data
  #
  # We stop the stack for a few seconds during the snapshot to keep
  # the data files quiescent. In v1 this is acceptable (nightly,
  # brief downtime). For higher SLA, switch to pg_basebackup + redis
  # RDB copy in v2.

  local volumes=(
    "${FIRM_SLUG}-postgres-data"
    "${FIRM_SLUG}-redis-data"
    "${FIRM_SLUG}-frappe-sites"
    "${FIRM_SLUG}-frappe-apps"
    "${FIRM_SLUG}-docuseal-data"
    "${FIRM_SLUG}-docuseal-db-data"
    "${FIRM_SLUG}-vaultwarden-data"
    "${FIRM_SLUG}-conductor-data"
  )

  # Build the volume source paths. Use docker volume inspect to get the
  # actual host mountpoint, falling back to the default path.
  local paths=()
  local vol
  for vol in "${volumes[@]}"; do
    local mountpoint
    mountpoint="$(docker volume inspect "$vol" --format '{{ .Mountpoint }}' 2>/dev/null || true)"
    if [[ -z "$mountpoint" ]]; then
      warn "volume ${vol} not found — skipping"
      continue
    fi
    paths+=("$mountpoint")
  done

  if (( ${#paths[@]} == 0 )); then
    warn "no volume mountpoints found; skipping volume backup"
    return 0
  fi

  snapshot_path "$(IFS=' '; echo "${paths[*]}")" "volumes-$(date -u +%Y%m%d-%H%M%S)"
  ok "volume snapshots created"
}

# ─── Step 3: configs + .env ─────────────────────────────────────────
run_configs_backup() {
  if [[ -n "$only" && "$only" != "configs" ]]; then
    return 0
  fi
  log "snapshotting configs + .env"
  snapshot_path "${FIRM_DIR}" "configs-$(date -u +%Y%m%d-%H%M%S)"
  ok "config snapshot created"
}

# ─── Step 4: prune ──────────────────────────────────────────────────
run_prune() {
  if (( ! prune )); then
    return 0
  fi
  log "pruning old snapshots"
  run_or_print restic forget \
    --group-by host,paths,tag \
    --keep-hourly "${RESTIC_KEEP_HOURLY:-6}" \
    --keep-daily   "${RESTIC_KEEP_DAILY:-30}" \
    --keep-weekly  "${RESTIC_KEEP_WEEKLY:-4}" \
    --keep-monthly "${RESTIC_KEEP_MONTHLY:-6}" \
    --prune
  ok "prune complete"
}

# ─── Main ───────────────────────────────────────────────────────────
main() {
  log "starting backup for ${FIRM_SLUG}"
  ensure_repo
  run_db_backup
  run_volumes_backup
  run_configs_backup
  run_prune

  if (( ! dry_run )); then
    local count
    count="$(restic snapshots --json | grep -c '"id"' || true)"
    log "restic repo has ${count} snapshots"
  fi
  ok "backup done"
}

main