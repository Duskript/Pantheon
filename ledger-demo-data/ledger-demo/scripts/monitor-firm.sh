#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# monitor-firm.sh — per-founder instance monitoring stub.
#
# Usage:
#   monitor-firm.sh                  # uses $FIRM_DIR or cwd
#   monitor-firm.sh /srv/ledger/jones-cpa
#   monitor-firm.sh --push URL       # POST JSON status to URL (future)
#
# What it does (v0.1 stub):
#   1. Snapshot container states via docker compose ps
#   2. Check disk free > 1 GB
#   3. Check TLS cert expiry on the apex subdomain
#   4. Check most-recent restic snapshot age (if backups enabled)
#   5. Print a human-readable summary
#   6. Write structured JSON to ${FIRM_DIR}/logs/monitor.json for
#      future Uptime Kuma push integration
#
# Designed to run from cron every 5 minutes:
#   */5 * * * * /srv/ledger/{slug}/scripts/monitor-firm.sh \
#     >> /srv/ledger/{slug}/logs/monitor.log 2>&1
#
# Exit code:
#   0  healthy (or degraded but no immediate action required)
#   1  one or more checks in degraded state
#
# Future (not in v0.1):
#   - --push URL: POST the JSON status to a Uptime Kuma push monitor
#     (or any HTTPS endpoint that accepts {status, msg}). Will need
#     a MONITOR_PUSH_TOKEN env var for auth.
#   - Slack/Discord webhook on first-failure to suppress noise.
#
# The blueprint §7 calls for Uptime Kuma on a separate VPS pinging
# every founder's Traefik. This script is the on-founder side: it
# runs locally, can detect issues that Uptime Kuma's external ping
# would miss (disk, container state, cert details, backup freshness).
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIRM_DIR=""
PUSH_URL=""

# ─── Colors (TTY only) ───────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'
  C_BLUE=$'\033[34m'; 
else
  C_RESET=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_BLUE=""; 
fi

log()  { printf '%s[monitor]%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()   { printf '%s[  ok  ]%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s[ warn ]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
fail() { printf '%s[ fail ]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; }

usage() {
  cat <<EOF
monitor-firm.sh — per-founder instance health snapshot.

USAGE
  monitor-firm.sh [firm-dir] [--push URL]
  monitor-firm.sh -h | --help

OPTIONS
  --push URL       POST the JSON snapshot to URL (not implemented in v0.1;
                   prints the curl invocation that WOULD run instead).

ENV VARS
  MONITOR_PUSH_TOKEN   Bearer token to send with --push (future).
  DISK_MIN_GB          Minimum free GB before WARN (default: 1).
  CERT_WARN_DAYS       Cert expiry threshold for WARN (default: 30).
  BACKUP_MAX_HOURS     Max hours since last backup before WARN (default: 26).

OUTPUT
  stdout: human-readable summary
  \${FIRM_DIR}/logs/monitor.json: structured status (for Uptime Kuma)

EXIT CODES
  0  healthy
  1  degraded

EXAMPLES
  # One-shot check (prints summary + writes JSON):
  /srv/ledger/jones-cpa/scripts/monitor-firm.sh

  # From cron, every 5 minutes:
  */5 * * * * /srv/ledger/jones-cpa/scripts/monitor-firm.sh \
    >> /srv/ledger/jones-cpa/logs/monitor.log 2>&1
EOF
}

# ─── Arg parsing ─────────────────────────────────────────────────────
while (( $# > 0 )); do
  case "$1" in
    -h|--help)  usage; exit 0 ;;
    --push)     shift; PUSH_URL="${1:?--push requires URL}" ;;
    --)         shift; break ;;
    -*)         fail "unknown flag: $1 (try --help)" ;;
    *)
      if [[ -z "$FIRM_DIR" ]]; then FIRM_DIR="$1"
      else fail "unexpected positional arg: $1 (firm dir already set)"
      fi
      ;;
  esac
  shift
done

# Default firm dir: parent of script dir.
if [[ -z "$FIRM_DIR" ]]; then
  FIRM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi

if [[ ! -d "$FIRM_DIR" ]]; then
  fail "firm dir does not exist: $FIRM_DIR"
fi

FIRM_SLUG="${FIRM_SLUG:-$(basename "$FIRM_DIR")}"
DOMAIN="${DOMAIN:-theoforge.app}"

# Tunables (overridable via env).
DISK_MIN_GB="${DISK_MIN_GB:-1}"
CERT_WARN_DAYS="${CERT_WARN_DAYS:-30}"
BACKUP_MAX_HOURS="${BACKUP_MAX_HOURS:-26}"

# ─── Load .env if present ────────────────────────────────────────────
ENV_FILE="${FIRM_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1091,SC1090  # env file lives at runtime path, not constant
  source "$ENV_FILE"
  set +a
  export FIRM_SLUG DOMAIN
fi

# ─── Tool checks (warn, don't fail — monitor should be tolerant) ─────
have_docker=0
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  have_docker=1
else
  warn "docker not available — container check will report unknown"
fi

# ─── Snapshot state ──────────────────────────────────────────────────
# All checks write to per-key vars; we assemble the JSON at the end.
STATUS="ok"          # overall: ok | warn | fail
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DETAIL_LINES=()

# Containers: count by state.
CONTAINERS_UP=0
CONTAINERS_DOWN=0
CONTAINERS_UNKNOWN=0
if (( have_docker )); then
  # Parse `docker compose ps` table output. Format (one per service):
  # NAME   SERVICE   STATUS   PORTS
  # We only need the STATUS column (3rd). Fall back to "unknown" on
  # any parse failure.
  while IFS= read -r line; do
    # Skip header.
    [[ "$line" =~ ^(NAME|--|$) ]] && continue
    state="$(awk '{print tolower($3)}' <<<"$line")"
    if [[ "$state" == *"running"* && "$state" != *"restarting"* ]]; then
      CONTAINERS_UP=$((CONTAINERS_UP+1))
    else
      CONTAINERS_DOWN=$((CONTAINERS_DOWN+1))
      DETAIL_LINES+=("container not running: ${line%% *}")
    fi
  done < <(cd "$FIRM_DIR" && (docker compose ps 2>/dev/null || true))

  if (( CONTAINERS_DOWN > 0 )); then
    STATUS="fail"
    warn "${CONTAINERS_DOWN} container(s) not running"
  else
    ok "${CONTAINERS_UP} container(s) running"
  fi
else
  CONTAINERS_UNKNOWN=1
  warn "docker not reachable — container state unknown"
  STATUS="warn"
fi

# Disk space.
DISK_FREE_GB=0
if command -v df >/dev/null 2>&1; then
  free_kb="$(df -Pk "$FIRM_DIR" | awk 'NR==2 {print $4}')"
  DISK_FREE_GB=$(( free_kb / 1024 / 1024 ))
  if (( DISK_FREE_GB < DISK_MIN_GB )); then
    STATUS="fail"
    fail "disk free: ${DISK_FREE_GB} GB (< ${DISK_MIN_GB} GB minimum)"
  elif (( DISK_FREE_GB < DISK_MIN_GB * 2 )); then
    [[ "$STATUS" == "ok" ]] && STATUS="warn"
    warn "disk free: ${DISK_FREE_GB} GB (within 2x of ${DISK_MIN_GB} GB minimum)"
  else
    ok "disk free: ${DISK_FREE_GB} GB"
  fi
fi

# TLS cert on the apex subdomain. Use openssl s_client non-interactively.
# Pipe Q into openssl so it doesn't block waiting for stdin, and add
# -servername (SNI) so the right cert is served from Traefik's SNI
# multiplexer. We use `|| true` aggressively — cert checks are
# informational; a hung TCP should not freeze the monitor.
CERT_DAYS_LEFT=""
CERT_ISSUER=""
if command -v openssl >/dev/null 2>&1; then
  tls_host="ledger.${FIRM_SLUG}.${DOMAIN}"
  # 5-second timeout so a black-holed port doesn't block the cron job.
  tls_info="$(printf "Q" | timeout 5 openssl s_client -servername "$tls_host" \
            -connect "${tls_host}:443" 2>/dev/null \
            | openssl x509 -noout -enddate -issuer 2>/dev/null || true)"
  if [[ -n "$tls_info" ]] && [[ "$tls_info" == *"notAfter"* ]]; then
    tls_end_str="$(awk -F= '/notAfter/ {print $2}' <<<"$tls_info")"
    tls_end_str="${tls_end_str/GMT/}"
    tls_end_epoch="$(date -u -d "$tls_end_str" +%s 2>/dev/null || echo 0)"
    tls_now_epoch="$(date -u +%s)"
    tls_days_left=$(( (tls_end_epoch - tls_now_epoch) / 86400 ))
    CERT_DAYS_LEFT="$tls_days_left"
    CERT_ISSUER="$(awk -F= '/issuer/ {print $2}' <<<"$tls_info")"
    if (( tls_days_left <= 0 )); then
      STATUS="fail"
      fail "TLS cert ${tls_host}: EXPIRED (${tls_days_left}d ago)"
    elif (( tls_days_left < CERT_WARN_DAYS )); then
      [[ "$STATUS" == "ok" ]] && STATUS="warn"
      warn "TLS cert ${tls_host}: ${tls_days_left}d left (< ${CERT_WARN_DAYS}d threshold)"
    else
      ok "TLS cert ${tls_host}: ${tls_days_left}d left"
    fi
  else
    [[ "$STATUS" == "ok" ]] && STATUS="warn"
    warn "TLS cert ${tls_host}: could not read (DNS not propagated?)"
    CERT_DAYS_LEFT="null"
  fi
fi

# Latest restic snapshot age. If restic is missing or .env lacks the
# vars, just skip — don't fail the monitor over backups.
BACKUP_AGE_HOURS=""
BACKUP_LATEST=""
if command -v restic >/dev/null 2>&1 \
   && [[ -n "${RESTIC_REPO:-}" && -n "${RESTIC_PASSWORD:-}" ]]; then
  snap_json="$(restic snapshots --no-lock --json --latest 1 2>/dev/null || true)"
  if [[ -n "$snap_json" ]] && command -v jq >/dev/null 2>&1; then
    snap_ts="$(jq -r '.[0].time // empty' <<<"$snap_json" 2>/dev/null)"
    if [[ -n "$snap_ts" ]]; then
      BACKUP_LATEST="$snap_ts"
      snap_epoch="$(date -u -d "$snap_ts" +%s 2>/dev/null || echo 0)"
      now_epoch="$(date -u +%s)"
      age_h=$(( (now_epoch - snap_epoch) / 3600 ))
      BACKUP_AGE_HOURS="$age_h"
      if (( age_h > BACKUP_MAX_HOURS )); then
        [[ "$STATUS" == "ok" ]] && STATUS="warn"
        warn "latest backup: ${age_h}h old (> ${BACKUP_MAX_HOURS}h threshold)"
      else
        ok "latest backup: ${age_h}h old"
      fi
    else
      [[ "$STATUS" == "ok" ]] && STATUS="warn"
      warn "restic reachable but no snapshots yet"
    fi
  fi
fi

# ─── Emit JSON snapshot ──────────────────────────────────────────────
# Hand-rolled JSON (no jq dep at the caller side). Fields are stable;
# adding new ones is fine, removing or renaming breaks Uptime Kuma
# integrations — bump the version field if you do.
LOG_DIR="${FIRM_DIR}/logs"
JSON_PATH="${LOG_DIR}/monitor.json"
mkdir -p "$LOG_DIR"

# Escape strings for JSON (handles ", \, control chars).
json_escape() {
  s="${1-}"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//	/\\t}"
  printf '%s' "$s"
}

DETAIL_JSON=""
if (( ${#DETAIL_LINES[@]} > 0 )); then
  joined="$(printf '\\n%s' "${DETAIL_LINES[@]}")"
  joined="${joined#\\n}"
  DETAIL_JSON="\"$(json_escape "$joined")\""
else
  DETAIL_JSON="\"\""
fi

CERT_ISSUER_ESCAPED="$(json_escape "${CERT_ISSUER:-}")"

cat >"$JSON_PATH" <<EOF
{
  "version": "0.1",
  "ts": "${TS}",
  "firm_slug": "${FIRM_SLUG}",
  "domain": "${DOMAIN}",
  "status": "${STATUS}",
  "checks": {
    "containers": {
      "up": ${CONTAINERS_UP},
      "down": ${CONTAINERS_DOWN},
      "unknown": ${CONTAINERS_UNKNOWN}
    },
    "disk": {
      "free_gb": ${DISK_FREE_GB},
      "min_gb": ${DISK_MIN_GB}
    },
    "tls": {
      "host": "ledger.${FIRM_SLUG}.${DOMAIN}",
      "days_left": ${CERT_DAYS_LEFT:-null},
      "issuer": "${CERT_ISSUER_ESCAPED}"
    },
    "backup": {
      "latest": ${BACKUP_LATEST:+\"${BACKUP_LATEST}\"}${BACKUP_LATEST:-null},
      "age_hours": ${BACKUP_AGE_HOURS:-null},
      "max_hours": ${BACKUP_MAX_HOURS}
    }
  },
  "detail": ${DETAIL_JSON}
}
EOF

log "wrote ${JSON_PATH} (status=${STATUS})"

# ─── Optional push (not implemented in v0.1 stub) ────────────────────
if [[ -n "$PUSH_URL" ]]; then
  warn "--push not yet implemented (v0.1 stub)"
  log "would POST ${JSON_PATH} → ${PUSH_URL}"
  log "  curl -fsS -X POST -H 'Content-Type: application/json' \\"
  log "    -H \"Authorization: Bearer \${MONITOR_PUSH_TOKEN}\" \\"
  log "    --data-binary @${JSON_PATH} ${PUSH_URL}"
fi

# ─── Summary + exit ──────────────────────────────────────────────────
echo
case "$STATUS" in
  ok)   ok "status: healthy" ;;
  warn) warn "status: degraded" ;;
  fail) fail "status: failing" ;;
esac

# Exit 0 for ok+warn, 1 for fail. Cron mail handlers usually key off
# non-zero exit so they only page on hard failures.
if [[ "$STATUS" == "fail" ]]; then
  exit 1
fi
exit 0
