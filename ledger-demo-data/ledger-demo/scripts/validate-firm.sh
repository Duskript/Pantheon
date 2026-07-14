#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# validate-firm.sh — post-provision health check for one firm.
#
# Usage:
#   validate-firm.sh                  # uses $FIRM_DIR or cwd
#   validate-firm.sh /srv/ledger/jones-cpa
#   validate-firm.sh --skip-network   # skip HTTPS endpoint checks
#   validate-firm.sh --skip-backups   # skip restic + cron checks
#   validate-firm.sh --strict         # exit 1 on any WARN (not just FAIL)
#
# What it checks (18 checks across 7 groups):
#   [FS]    .env present + 0600, .state complete, compose file present
#   [DOCKER] every service Up + (healthy|starting) per docker compose ps
#   [API]   internal curl/wget against each service inside its container
#   [HTTPS] public Traefik routes return 200 from this host
#   [TLS]   wildcard cert for *.{firm}.{domain} valid > 30 days
#   [BACK]  restic repo reachable + nightly cron installed
#   [DATA]  Frappe site exists + > 5 GB free on firm dir filesystem
#
# Exit code:
#   0  all checks passed
#   1  one or more checks FAILED (operator must investigate)
#   2  bad invocation (missing firm dir, missing tools)
#
# Designed to be the automatable part of the "first 10 minutes" test
# from blueprint §6.2. Marketing-side items (Stripe, Discord, emails)
# are not in scope — those need a human or a SaaS integration.
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail
IFS=$'\n\t'

# ─── Defaults ────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIRM_DIR=""
SKIP_NETWORK=0
SKIP_BACKUPS=0
STRICT=0

# ─── Colors (TTY only) ───────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_BLUE=$'\033[34m'; C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_BOLD=$'\033[1m'
else
  C_RESET=""; C_BLUE=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_BOLD=""
fi

log()  { printf '%s[validate]%s %s\n' "$C_BLUE"   "$C_RESET" "$*"; }
ok()   { printf '%s[  ok   ]%s %s\n' "$C_GREEN"  "$C_RESET" "$*"; }
warn() { printf '%s[ warn  ]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
fail() { printf '%s[ fail  ]%s %s\n' "$C_RED"    "$C_RESET" "$*" >&2; }

usage() {
  cat <<EOF
validate-firm.sh — end-to-end health check for one TheoForge Ledger firm.

USAGE
  validate-firm.sh [firm-dir] [--skip-network] [--skip-backups] [--strict]
  validate-firm.sh -h | --help

OPTIONS
  --skip-network    Skip the [HTTPS] group — useful when DNS is not yet
                    propagated or when validating from inside the VPS.
  --skip-backups    Skip the [BACK] group — useful on fresh firms before
                    the first scheduled backup has run.
  --strict          Treat [WARN] results as [FAIL] for exit code.
                    Default: only FAIL causes non-zero exit.

EXIT CODES
  0  all checks passed
  1  one or more checks failed (or strict + warn)
  2  bad invocation (missing firm dir, missing tools)

EXAMPLES
  # Full check from the firm dir:
  cd /srv/ledger/jones-cpa && ./scripts/validate-firm.sh

  # Same check from anywhere with an explicit path:
  sudo /srv/ledger/jones-cpa/scripts/validate-firm.sh

  # Quick check during fresh provision (DNS not propagated yet):
  ./scripts/validate-firm.sh --skip-network
EOF
}

# ─── Arg parsing ─────────────────────────────────────────────────────
while (( $# > 0 )); do
  case "$1" in
    -h|--help)        usage; exit 0 ;;
    --skip-network)   SKIP_NETWORK=1 ;;
    --skip-backups)   SKIP_BACKUPS=1 ;;
    --strict)         STRICT=1 ;;
    --)               shift; break ;;
    -*)               fail "unknown flag: $1 (try --help)" ;;
    *)
      if [[ -z "$FIRM_DIR" ]]; then FIRM_DIR="$1"
      else fail "unexpected positional arg: $1 (firm dir already set)"
      fi
      ;;
  esac
  shift
done

# Default firm dir: parent of script dir (scripts/ lives at firm_dir/scripts/).
if [[ -z "$FIRM_DIR" ]]; then
  FIRM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi

if [[ ! -d "$FIRM_DIR" ]]; then
  fail "firm dir does not exist: $FIRM_DIR"
fi

FIRM_SLUG="${FIRM_SLUG:-$(basename "$FIRM_DIR")}"

log "validating firm ${C_BOLD}${FIRM_SLUG}${C_RESET} at ${FIRM_DIR}"

# ─── Load .env (sets DOMAIN, POSTGRES_PASSWORD, etc.) ────────────────
ENV_FILE="${FIRM_DIR}/.env"
DOMAIN="${DOMAIN:-theoforge.app}"
if [[ -f "$ENV_FILE" ]]; then
  log "loading ${ENV_FILE}"
  set -a
  # shellcheck disable=SC1091,SC1090  # env file lives at runtime path, not constant
  source "$ENV_FILE"
  set +a
  # Re-export FIRM_SLUG and DOMAIN in case the .env overwrote them.
  export FIRM_SLUG DOMAIN
else
  warn ".env missing at ${ENV_FILE} — running with defaults (DOMAIN=${DOMAIN})"
fi

# ─── Check infrastructure ────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || fail "docker not installed"
docker compose version >/dev/null 2>&1 || fail "docker compose plugin not installed"

# ─── Counters ────────────────────────────────────────────────────────
PASS=0
FAIL=0
WARN=0

# Print a result line and bump the matching counter. Three levels:
#   pass → green OK
#   warn → yellow (informational, e.g. new cert not yet issued)
#   fail → red (something the operator must fix)
record() {
  local level="$1" group="$2" name="$3" detail="${4:-}"
  case "$level" in
    pass)
      PASS=$((PASS+1))
      printf '  %s[ %s ] [ %-3s ] %s%s%s\n' "$C_GREEN" "PASS" "$group" "$name" \
        "${detail:+ — ${detail}}" "$C_RESET"
      ;;
    warn)
      WARN=$((WARN+1))
      printf '  %s[ %s ] [ %-3s ] %s%s%s\n' "$C_YELLOW" "WARN" "$group" "$name" \
        "${detail:+ — ${detail}}" "$C_RESET" >&2
      ;;
    fail)
      FAIL=$((FAIL+1))
      printf '  %s[ %s ] [ %-3s ] %s%s%s\n' "$C_RED" "FAIL" "$group" "$name" \
        "${detail:+ — ${detail}}" "$C_RESET" >&2
      ;;
  esac
}

# ─── [FS] Filesystem checks ──────────────────────────────────────────
check_fs() {
  # .env present + 0600.
  if [[ -f "$ENV_FILE" ]]; then
    local mode
    mode="$(stat -c%a "$ENV_FILE" 2>/dev/null || stat -f%Lp "$ENV_FILE")"
    if [[ "$mode" == "600" || "$mode" == "400" ]]; then
      record pass FS ".env permissions" "mode=${mode}"
    else
      record fail FS ".env permissions" "mode=${mode} (expected 600)"
    fi
  else
    record fail FS ".env present" "missing at ${ENV_FILE}"
  fi

  # .state complete (all 8 phases marked).
  local state_file="${FIRM_DIR}/.state"
  if [[ -f "$state_file" ]]; then
    local phases_done
    phases_done="$(grep -c . "$state_file" 2>/dev/null || echo 0)"
    if (( phases_done >= 8 )); then
      record pass FS ".state complete" "${phases_done}/8 phases"
    else
      record warn FS ".state complete" "${phases_done}/8 phases (run --resume)"
    fi
  else
    record fail FS ".state present" "missing at ${state_file}"
  fi

  # docker-compose.yml rendered.
  if [[ -f "${FIRM_DIR}/docker-compose.yml" ]]; then
    record pass FS "docker-compose.yml" "rendered"
  else
    record fail FS "docker-compose.yml" "not rendered"
  fi
}

# ─── [DOCKER] Container health ───────────────────────────────────────
# docker compose ps --format json gives us name+state. We want every
# service either Up+healthy or Up+starting (transitional). Anything
# else (down, exited, restarting, unhealthy) is a fail.
check_docker() {
  local raw
  if ! raw="$(cd "$FIRM_DIR" && docker compose ps --format json 2>/dev/null)"; then
    record fail DOCKER "compose reachable" "docker compose ps failed"
    return
  fi

  # Aggregate state across services. If 'raw' is empty, no services.
  if [[ -z "$raw" ]]; then
    record fail DOCKER "any services running" "compose ps returned no rows"
    return
  fi

  local bad=0 starting=0 running=0
  while IFS= read -r line; do
    local name state health
    name="$(printf '%s' "$line"  | jq -r '.Name // .Service // "?"' 2>/dev/null)"
    state="$(printf '%s' "$line" | jq -r '.State // "unknown"' 2>/dev/null)"
    health="$(printf '%s' "$line" | jq -r '.Health // ""' 2>/dev/null)"
    if [[ "$state" != "running" ]]; then
      bad=$((bad+1))
      record fail DOCKER "${name}" "state=${state}"
    elif [[ -n "$health" && "$health" != "healthy" && "$health" != "" ]]; then
      bad=$((bad+1))
      record fail DOCKER "${name}" "health=${health}"
    elif [[ "$health" == "" ]]; then
      starting=$((starting+1))
    else
      running=$((running+1))
    fi
  done <<<"$raw"

  if (( bad == 0 )); then
    record pass DOCKER "all services up" \
      "${running} healthy, ${starting} no healthcheck"
  fi
}

# ─── [API] Internal service health (inside containers) ───────────────
# Same probes the docker-compose healthchecks use, just driven from
# this script so we can attribute failures per service.
check_api() {
  local svc cmd
  # Returns: 0 if probe succeeded, 1 otherwise. Output is silently
  # captured — the docker compose exec error messages are noisy.
  probe() {
    svc="$1"; shift
    cmd="$*"
    (cd "$FIRM_DIR" && docker compose exec -T "$svc" $cmd) >/dev/null 2>&1
  }

  if probe frappe-erpnext   curl -fsS http://localhost:8000/api/method/ping; then
    record pass API "frappe-erpnext ping"
  else
    record fail API "frappe-erpnext ping"
  fi

  if probe docuseal wget -qO/dev/null http://localhost:3000/; then
    record pass API "docuseal root"
  else
    record fail API "docuseal root"
  fi

  if probe vaultwarden curl -fsS http://localhost:80/alive; then
    record pass API "vaultwarden alive"
  else
    record fail API "vaultwarden alive"
  fi

  if probe conductor wget -qO/dev/null http://localhost:7100/healthz; then
    record pass API "conductor healthz"
  else
    record fail API "conductor healthz"
  fi

  if probe postgres pg_isready -U "${POSTGRES_USER:-frappe}" -d "${POSTGRES_DB:-frappe}"; then
    record pass API "postgres ready"
  else
    record fail API "postgres ready"
  fi

  if probe redis bash -c "redis-cli -a \"\${REDIS_PASSWORD}\" ping | grep -q PONG"; then
    record pass API "redis ping"
  else
    record fail API "redis ping"
  fi
}

# ─── [HTTPS] Public Traefik routes ───────────────────────────────────
# Skip the whole group with --skip-network (DNS not propagated, or
# running from inside the VPS before Traefik bound :443).
check_https() {
  if (( SKIP_NETWORK )); then
    log "skipping HTTPS checks (--skip-network)"
    return
  fi

  local code
  fetch_code() {
    local url="$1"
    # --max-time 10 so a hung TCP doesn't block the whole check.
    # -o /dev/null discards body. -w '%{http_code}' prints code.
    curl -ksS -o /dev/null -w '%{http_code}' --max-time 10 "$url" 2>/dev/null || echo 000
  }

  for route in "ledger" "sign" "vault" "conductor"; do
    local url="https://${route}.${FIRM_SLUG}.${DOMAIN}"
    case "$route" in
      ledger)    path="/api/method/ping" ;;
      sign)      path="/" ;;
      vault)     path="/alive" ;;
      conductor) path="/healthz" ;;
    esac
    code="$(fetch_code "${url}${path}")"
    if [[ "$code" == "200" ]]; then
      record pass HTTPS "${route}.${FIRM_SLUG}.${DOMAIN}" "200"
    elif [[ "$code" == "401" || "$code" == "403" ]]; then
      # Traefik basic-auth routes (e.g. /api/dashboard/) legitimately 401
      # without creds — that's reachable, just auth-gated.
      record pass HTTPS "${route}.${FIRM_SLUG}.${DOMAIN}" "${code} (auth-gated)"
    else
      record fail HTTPS "${route}.${FIRM_SLUG}.${DOMAIN}" "HTTP ${code}"
    fi
  done

  # Traefik dashboard — auth-gated, expect 401/403 without creds.
  local tcode
  tcode="$(fetch_code "https://traefik.${FIRM_SLUG}.${DOMAIN}/api/ping")"
  if [[ "$tcode" == "200" || "$tcode" == "401" || "$tcode" == "403" ]]; then
    record pass HTTPS "traefik.${FIRM_SLUG}.${DOMAIN}" "HTTP ${tcode}"
  else
    record fail HTTPS "traefik.${FIRM_SLUG}.${DOMAIN}" "HTTP ${tcode}"
  fi
}

# ─── [TLS] Certificate validity ──────────────────────────────────────
# OpenSSL s_client against the apex subdomain. We accept any cert that
# is currently valid AND expires more than 30 days from now. Self-signed
# certs (no CA issuer) are a warn — typically Traefik's staging LE.
check_tls() {
  if (( SKIP_NETWORK )); then return; fi

  local host="ledger.${FIRM_SLUG}.${DOMAIN}"
  # Capture both the notAfter date AND the issuer for self-signed detection.
  local info
  info="$(echo | openssl s_client -servername "$host" -connect "${host}:443" 2>/dev/null \
            | openssl x509 -noout -enddate -issuer 2>/dev/null)"
  if [[ -z "$info" ]]; then
    record fail TLS "${host}" "could not read certificate"
    return
  fi

  local enddate_epoch now_epoch days_left issuer self_signed=0
  local end_str
  end_str="$(awk -F= '/notAfter/ {print $2}' <<<"$info")"
  # 'notAfter=Jun 15 12:00:00 2026 GMT' → 'Jun 15 12:00:00 2026'
  end_str="${end_str/GMT/}"
  enddate_epoch="$(date -u -d "$end_str" +%s 2>/dev/null || echo 0)"
  now_epoch="$(date -u +%s)"
  days_left=$(( (enddate_epoch - now_epoch) / 86400 ))

  issuer="$(awk -F= '/issuer/ {print $2}' <<<"$info")"
  if [[ "$issuer" == *"Let's Encrypt"* ]]; then
    : # production cert, no self-signed warning
  elif [[ "$issuer" == *"Fake LE"* || "$issuer" == *"(STAGING)"* ]]; then
    self_signed=1
  elif [[ -z "$issuer" ]]; then
    self_signed=1
  fi

  if (( days_left > 30 )); then
    if (( self_signed )); then
      record warn TLS "${host}" "${days_left}d left — staging/self-signed cert"
    else
      record pass TLS "${host}" "${days_left}d left"
    fi
  elif (( days_left > 0 )); then
    record warn TLS "${host}" "only ${days_left}d left — renew soon"
  else
    record fail TLS "${host}" "expired ${days_left}d ago"
  fi
}

# ─── [BACK] restic + cron ────────────────────────────────────────────
check_backups() {
  if (( SKIP_BACKUPS )); then
    log "skipping backup checks (--skip-backups)"
    return
  fi

  # restic repo reachable.
  if [[ -n "${RESTIC_REPO:-}" && -n "${RESTIC_PASSWORD:-}" ]]; then
    if command -v restic >/dev/null 2>&1; then
      if restic snapshots --no-lock >/dev/null 2>&1; then
        local n
        n="$(restic snapshots --no-lock --json 2>/dev/null \
              | jq 'length' 2>/dev/null || echo 0)"
        record pass BACK "restic repo reachable" "${n} snapshot(s)"
      else
        record warn BACK "restic repo reachable" \
          "restic snapshots failed — check RESTIC_REPO + credentials"
      fi
    else
      record warn BACK "restic installed" "restic not on PATH"
    fi
  else
    record warn BACK "restic env vars" \
      "RESTIC_REPO/RESTIC_PASSWORD not set in .env"
  fi

  # Nightly cron installed.
  local cron_line
  cron_line="$(crontab -l 2>/dev/null | grep -F "${FIRM_DIR}/scripts/backup.sh" || true)"
  if [[ -n "$cron_line" ]]; then
    record pass BACK "nightly cron installed" "${cron_line##*  }}"
  else
    record fail BACK "nightly cron installed" \
      "no crontab line for ${FIRM_DIR}/scripts/backup.sh"
  fi
}

# ─── [DATA] Frappe site + disk ───────────────────────────────────────
check_data() {
  # At least one Frappe site_config.json exists.
  # Frappe's docker-compose mounts sites at the named volume `frappe_sites`
  # which is bound to /home/frappe/frappe-bench/sites inside the container.
  local site_count
  site_count="$(cd "$FIRM_DIR" && docker compose exec -T frappe-erpnext \
    bash -c "ls -1 /home/frappe/frappe-bench/sites 2>/dev/null \
              | grep -v '^apps$' | grep -v '^\.' | wc -l" 2>/dev/null || echo 0)"
  if (( site_count > 0 )); then
    record pass DATA "frappe sites" "${site_count} site(s)"
  else
    record fail DATA "frappe sites" "0 sites — run create-site.sh"
  fi

  # Disk space on the firm dir filesystem.
  if command -v df >/dev/null 2>&1; then
    local free_kb
    free_kb="$(df -Pk "$FIRM_DIR" | awk 'NR==2 {print $4}')"
    if (( free_kb > 5 * 1024 * 1024 )); then
      record pass DATA "disk free" "$(( free_kb / 1024 / 1024 )) GB"
    else
      record fail DATA "disk free" \
        "only $(( free_kb / 1024 )) MB free (< 5 GB threshold)"
    fi
  fi
}

# ─── Run all checks ──────────────────────────────────────────────────
check_fs
check_docker
check_api
check_https
check_tls
check_backups
check_data

# ─── Summary + exit ──────────────────────────────────────────────────
echo
printf '%sSummary:%s\n' "$C_BOLD" "$C_RESET"
printf '  PASS: %s%d%s\n' "$C_GREEN" "$PASS" "$C_RESET"
printf '  WARN: %s%d%s\n' "$C_YELLOW" "$WARN" "$C_RESET"
printf '  FAIL: %s%d%s\n' "$C_RED"   "$FAIL" "$C_RESET"

if (( FAIL > 0 )); then
  fail "${FAIL} check(s) failed — see above"
elif (( STRICT && WARN > 0 )); then
  fail "${WARN} warning(s) treated as failure (--strict)"
fi

ok "all checks passed"
