#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# restore.sh — restore a firm's data from a restic snapshot in B2.
#
# Usage:
#   restore.sh --list                       # list all snapshots
#   restore.sh --list <snapshot-id>         # files inside a snapshot
#   restore.sh --latest --target=db         # restore latest db dump
#   restore.sh <snapshot-id> --target=<path>
#
# DESTRUCTIVE: this script will overwrite the firm's live data.
# Refuses to run without --confirm unless --dry-run is set.
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIRM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ─── Colors ─────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_BLUE=$'\033[34m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'
else
  C_RESET=""; C_BLUE=""; C_GREEN=""; C_YELLOW=""; C_RED=""
fi
# C_BOLD is reserved for future emphasis; declared when first used.
log()  { printf '%s[restore]%s %s\n' "$C_BLUE"  "$C_RESET" "$*"; }
ok()   { printf '%s[  ok  ]%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s[ warn ]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
fail() { printf '%s[ fail ]%s %s\n' "$C_RED"   "$C_RESET" "$*" >&2; exit 1; }

# ─── Tools ──────────────────────────────────────────────────────────
# Only required when actually doing work. --help must work on a
# barebones host without restic / docker installed.
require_tools() {
  command -v restic >/dev/null 2>&1 || fail "restic not installed"
  command -v docker >/dev/null 2>&1 || fail "docker not installed"
}

# ─── Load .env ──────────────────────────────────────────────────────
if [[ -f "${FIRM_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091  # sourced file lives in /srv/ledger
  source "${FIRM_DIR}/.env"
  set +a
fi

# ─── Args (parse before requiring tools, so --help works without them)
snapshot_id=""
list_only=0
list_files=0
target_path=""
dry_run=0
confirm=0

usage() {
  cat <<EOF
restore.sh — restore a firm's data from restic/B2.

USAGE
  restore.sh --list                           List all snapshots for ${FIRM_SLUG:-firm}.
  restore.sh --list <snapshot-id>             List files in a snapshot.
  restore.sh --latest [--target=<path>]       Restore latest snapshot to <path>
                                              (default: ${FIRM_DIR}/restore).
  restore.sh <snapshot-id> --target=<path>    Restore specific snapshot.
  restore.sh --dry-run --latest               Show what would happen.

DESTRUCTIVE: this script overwrites live data unless --target points
outside the firm's data paths. You MUST pass --confirm to proceed.

EXAMPLES
  restore.sh --list
  restore.sh --list latest
  restore.sh --latest --target=/tmp/restore-test --confirm
  restore.sh abc1234 --target=/srv/ledger/${FIRM_SLUG:-firm} --confirm

ENV VARS (set from .env)
  RESTIC_REPO, RESTIC_PASSWORD, B2_ACCOUNT_ID, B2_ACCOUNT_KEY, FIRM_SLUG
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --list)        list_only=1 ;;
    --list-files)  list_files=1 ;;
    --latest)      snapshot_id="latest" ;;
    --target=*)    target_path="${1#--target=}" ;;
    --dry-run)     dry_run=1 ;;
    --confirm)     confirm=1 ;;
    -h|--help)     usage; exit 0 ;;
    -*)            fail "unknown flag: $1" ;;
    *)             snapshot_id="$1" ;;
  esac
  shift
done

# Past here we actually need restic + docker.
require_tools
: "${RESTIC_REPO:?RESTIC_REPO is required}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD is required}"
: "${B2_ACCOUNT_ID:?B2_ACCOUNT_ID is required}"
: "${B2_ACCOUNT_KEY:?B2_ACCOUNT_KEY is required}"
: "${FIRM_SLUG:?FIRM_SLUG is required}"

export RESTIC_REPOSITORY="$RESTIC_REPO"
export RESTIC_PASSWORD
export AWS_ACCESS_KEY_ID="$B2_ACCOUNT_ID"
export AWS_SECRET_ACCESS_KEY="$B2_ACCOUNT_KEY"

# ─── Commands ───────────────────────────────────────────────────────
do_list() {
  log "snapshots in ${RESTIC_REPOSITORY}"
  restic snapshots --no-lock
}

do_list_files() {
  local sid="$1"
  restic ls "$sid" --no-lock
}

do_restore() {
  local sid="$1" tgt="$2"
  [[ -z "$tgt" ]] && tgt="${FIRM_DIR}/restore"

  if [[ ! "$tgt" =~ ^/ ]] && [[ "$tgt" != "." ]]; then
    fail "--target must be an absolute path or '.'"
  fi

  if [[ "$tgt" == "${FIRM_DIR}" || "$tgt" == "${FIRM_DIR}/"* ]] && (( ! confirm )); then
    fail "restoring into the live firm directory requires --confirm"
  fi

  if [[ -e "$tgt" && "$tgt" != "." ]]; then
    warn "target ${tgt} already exists — contents will be overwritten"
  fi

  log "restoring snapshot ${sid} → ${tgt}"
  if (( dry_run )); then
    printf '  [dry-run] restic restore %s --target %s\n' "$sid" "$tgt"
    return 0
  fi

  # Stop the running stack so we don't fight with live writes.
  log "stopping ${FIRM_SLUG} docker stack"
  (cd "${FIRM_DIR}" && docker compose down)

  mkdir -p "$tgt"
  restic restore "$sid" --target "$tgt" --no-lock

  ok "snapshot ${sid} restored to ${tgt}"
  printf '\nNext steps:\n'
  printf '  1. Inspect %s\n' "$tgt"
  printf '  2. Copy back into live paths: rsync -av %s/ %s/\n' "$tgt" "$FIRM_DIR"
  printf '  3. Bring the stack back up: cd %s && docker compose up -d\n' "$FIRM_DIR"
}

# ─── Main ───────────────────────────────────────────────────────────
if (( list_only )); then
  do_list
  exit 0
fi
if (( list_files )); then
  [[ -z "$snapshot_id" ]] && fail "--list-files requires a snapshot id"
  do_list_files "$snapshot_id"
  exit 0
fi

[[ -z "$snapshot_id" ]] && fail "snapshot id or --latest required (use --list to see available)"

if (( ! confirm && ! dry_run )); then
  fail "refusing to restore without --confirm (or pass --dry-run to preview)"
fi

do_restore "$snapshot_id" "$target_path"