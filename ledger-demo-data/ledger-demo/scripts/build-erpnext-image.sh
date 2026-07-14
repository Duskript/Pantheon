#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# build-erpnext-image.sh — build and push the custom ERPNext image.
#
# Wraps `docker buildx build` so the operator doesn't have to remember
# the right flags. Output: theoforge/erpnext:<tag> ready for
# docker compose to pull.
#
# Usage:
#   build-erpnext-image.sh                       # builds v16.22.0-ledger-1
#   build-erpnext-image.sh v16.22.0-ledger-2     # custom tag
#   build-erpnext-image.sh --push v16.22.0-ledger-2   # also push to Docker Hub
#   build-erpnext-image.sh --load                 # load into local docker (default)
#   build-erpnext-image.sh --platform linux/amd64  # override target arch
#
# Requires:
#   - docker with buildx enabled
#   - DOCKERHUB_USERNAME + DOCKERHUB_TOKEN (or
#     DOCKER_REGISTRY_URL + DOCKER_REGISTRY_USER + DOCKER_REGISTRY_PASS)
#     for --push
#
# Where it fits in the deploy flow:
#   1. Operator edits ledger_brand/ (or any change to the build context)
#   2. Operator runs: build-erpnext-image.sh --push v16.22.0-ledger-2
#   3. Operator updates FRAPPE_IMAGE_TAG in /srv/ledger/{firm}/.env
#   4. Operator runs: cd /srv/ledger/{firm} && docker compose pull frappe-erpnext
#   5. Operator runs: cd /srv/ledger/{firm} && docker compose up -d frappe-erpnext
#
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail
IFS=$'\n\t'

# ─── Resolve paths ──────────────────────────────────────────
# SCRIPT_DIR       = infra/_templates/scripts/
# DOCKERFILE_DIR   = infra/_templates/frappe-bench/   (where the Dockerfile lives)
# PROJECT_ROOT     = theoforge-ledger/                 (build context root)
#
# Why PROJECT_ROOT is the build context: the Dockerfile COPYs the
# app from `./frappe-bench/apps/ledger_brand/` (project-relative).
# Docker COPY refuses to follow symlinks that point OUTSIDE the
# build context, so the context must be the project root (which
# contains both this Dockerfile dir and the app dir).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE_DIR="$(cd "${SCRIPT_DIR}/../frappe-bench" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
DEFAULT_TAG="v16.22.0-ledger-1"
IMAGE_NAME="theoforge/erpnext"

# ─── Logging helpers ───────────────────────────────────────────
if [[ -t 1 ]]; then
  C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_BLUE=$'\033[34m'; C_GREEN=$'\033[32m'; C_RED=$'\033[31m'; C_YELLOW=$'\033[33m'
else
  C_RESET=""; C_BOLD=""; C_BLUE=""; C_GREEN=""; C_RED=""; C_YELLOW=""
fi
log()  { printf '%s[build]%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()   { printf '%s[  ok ]%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s[ warn ]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
fail() { printf '%s[ fail ]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }

# ─── Dependency checks ────────────────────────────────────────
command -v docker >/dev/null 2>&1 || fail "docker not installed"
docker buildx version >/dev/null 2>&1 || fail "docker buildx not available — upgrade to Docker 19.03+"

# ─── Argument parsing ─────────────────────────────────────────
push=0
load=1    # default: load into local docker
platform=""
tag="${DEFAULT_TAG}"

usage() {
  cat <<EOF
build-erpnext-image.sh — build (and optionally push) the custom ERPNext image.

USAGE
  build-erpnext-image.sh [--push] [--no-load] [--platform <arch>] [<tag>]

OPTIONS
  --push              Push the image to the registry after build.
  --no-load           Don't load into local docker (useful with --push for CI).
  --platform <arch>   Target platform (default: native, e.g. linux/amd64).
  --help              Show this help.

DEFAULTS
  IMAGE_NAME = ${IMAGE_NAME}
  TAG        = ${DEFAULT_TAG}

EXAMPLES
  build-erpnext-image.sh                          # build + load v16.22.0-ledger-1
  build-erpnext-image.sh v16.22.0-ledger-2        # build + load a new tag
  build-erpnext-image.sh --push v16.22.0-ledger-2 # build + push to registry
  build-erpnext-image.sh --push --no-load v16.22.0-ledger-2
                                                  # build only, push, no local load

ENV (consumed when --push is set)
  DOCKERHUB_USERNAME        Docker Hub user (default: theoforge)
  DOCKERHUB_TOKEN           Docker Hub access token
  DOCKER_REGISTRY_URL       Override the registry (default: docker.io)
  DOCKER_REGISTRY_USER      Override the user (default: \$DOCKERHUB_USERNAME)
  DOCKER_REGISTRY_PASS      Override the password (default: \$DOCKERHUB_TOKEN)
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --push)      push=1; load=0 ;;
    --no-load)   load=0 ;;
    --load)      load=1 ;;
    --platform)  shift; platform="${1:?--platform requires an arch}" ;;
    --help|-h)   usage; exit 0 ;;
    -*)          fail "unknown flag: $1" ;;
    *)           tag="$1" ;;
  esac
  shift
done

# ─── Resolve full image reference ────────────────────────────
REGISTRY="${DOCKER_REGISTRY_URL:-docker.io}"
USER="${DOCKER_REGISTRY_USER:-${DOCKERHUB_USERNAME:-theoforge}}"
if [[ "${REGISTRY}" == "docker.io" ]]; then
  full_image="${USER}/${IMAGE_NAME#*/}:${tag}"   # docker.io/theoforge/erpnext:TAG
else
  full_image="${REGISTRY}/${USER}/${IMAGE_NAME}:${tag}"
fi

log "building ${C_BOLD}${full_image}${C_RESET}"

# ─── Pre-flight: check the build context ────────────────────
[[ -f "${DOCKERFILE_DIR}/Dockerfile" ]] || fail "Dockerfile not found at ${DOCKERFILE_DIR}/Dockerfile"
[[ -d "${PROJECT_ROOT}/frappe-bench/apps/ledger_brand" ]] || fail "ledger_brand app not found at ${PROJECT_ROOT}/frappe-bench/apps/ledger_brand (build context)"

# ─── Build ───────────────────────────────────────────────────
# Build context = PROJECT_ROOT (so COPY ./frappe-bench/apps/ledger_brand/
# in the Dockerfile resolves). The Dockerfile itself is at
# DOCKERFILE_DIR/Dockerfile, passed via --file.
build_args=(
  buildx build
  --tag "${full_image}"
  --file "${DOCKERFILE_DIR}/Dockerfile"
)

if (( load )); then
  build_args+=(--load)
fi
if (( push )); then
  build_args+=(--push)
fi
# Final positional arg = build context. Must be PROJECT_ROOT (not
# DOCKERFILE_DIR), because the Dockerfile COPYs from
# `./frappe-bench/apps/ledger_brand/` — a path that only resolves
# when the build context is the project root.
if [[ -n "$platform" ]]; then
  build_args+=(--platform "$platform")
fi
build_args+=("${PROJECT_ROOT}")

log "buildx: docker ${build_args[*]}"
if ! docker "${build_args[@]}"; then
  fail "docker buildx failed — see output above"
fi

ok "built ${full_image}"

# ─── Push (separate path for cases where --load + --push both apply)
if (( push && load )); then
  log "loading + pushing both requested; pushing after load"
  if ! docker push "${full_image}"; then
    fail "docker push failed — check DOCKERHUB_USERNAME / DOCKERHUB_TOKEN"
  fi
  ok "pushed ${full_image}"
fi

# ─── Post-flight summary ────────────────────────────────────
cat <<EOF

${C_BOLD}Done.${C_RESET}
  Image: ${full_image}

${C_BOLD}Next steps:${C_RESET}
EOF
if (( push )); then
  cat <<EOF
  1. Update /srv/ledger/{firm}/.env: set FRAPPE_IMAGE_TAG=${tag}
  2. Pull on the VPS:    cd /srv/ledger/{firm} && docker compose pull frappe-erpnext
  3. Restart the stack:  cd /srv/ledger/{firm} && docker compose up -d frappe-erpnext
  4. Verify the brand:   open https://ledger.{firm}.theoforge.app (check logo)
EOF
else
  cat <<EOF
  Image is loaded into local docker. To use it in a stack:
  1. Set FRAPPE_IMAGE_TAG=${tag} in the firm's .env
  2. cd /srv/ledger/{firm} && docker compose up -d frappe-erpnext
  3. To publish for other firms to pull, re-run with --push.
EOF
fi