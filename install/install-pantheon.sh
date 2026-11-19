#!/usr/bin/env bash
# install-pantheon.sh — install the Pantheon public release on a fresh CachyOS/Debian/macOS box
#
# Source of truth: ~/athenaeum/Codex-Olympus/INSTALL_PIPELINE.md
# This script is the executable form of that spec. Specs drift; the script
# is what actually runs. When you change this, update the spec in the same
# commit and append a decision to DECISIONS.md.
#
# Idempotent: re-running after partial failure completes the rest.
# Two-mode: --enterprise skips the interactive Composio prompt (assumes
#           ~/.hermes/.env is pre-populated by Pantheon-Enterprise).
#           --skip-composio-prompt keeps all other prompts but skips Composio.
#
# Exit codes:
#   0  success
#   1  preflight failure
#   2  phase failure (see output for which phase)
#   3  validation failure (run validate-pantheon.sh for details)
#
# Flags:
#   --enterprise              skip the interactive Composio/n8n prompts
#   --skip-composio-prompt    skip Composio prompt only (n8n still skipped always)
#   --non-interactive         fail rather than prompt (for CI/automation)
#   --phase N                 run only phase N (1-16, or 8b); for debugging
#   --client                  install the shipped CLIENT roster (6 gods) instead of
#                             the operator's god set, and scrub the result
#   --client-root PATH        the client's $HOME to install into (default: $HOME)
#   --client-answers PATH     interview answers JSON (see client-kit/README.md)
#   --client-dry-run          render + report, write nothing (safe rehearsal)
#   --conductor-platform P    plan the platform onboarding (discord | telegram)
#   --conductor-guild ID      the client's Discord guild id (discord only)
#   --conductor-chat ID       the client's Telegram supergroup id (telegram only)
#   --conductor-token-file F  file holding the conductor's bot token (needed to --apply)
#   --conductor-apply         actually call the platform API (default: plan only)

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────
PANTHEON_REPO="https://github.com/Duskript/Pantheon"
PANTHEON_REPO_BRANCH="${PANTHEON_REPO_BRANCH:-main}"
HERMES_AGENT_REPO="https://github.com/Codex-God-Marvin/hermes-agent"
HERMES_HOME="$HOME/.hermes"
PANTHEON_HOME="$HOME/pantheon"
ATHENAEUM_HOME="$HOME/athenaeum"
GOD_EXPORTS_DIR="$PANTHEON_HOME/god-exports"
HEPHAESTUS_ASSETS="$PANTHEON_HOME/install/assets/hephaestus"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
COMPOSIO_BRIDGE_PORT=8789
PANTHEON_WEBUI_PORT=8787
PANTHEON_MCP_PORT=8010
HEPHAESTUS_SKILL_COUNT=9

ENTERPRISE_MODE=false
SKIP_COMPOSIO_PROMPT=false
NON_INTERACTIVE=false
ONLY_PHASE=""

# Client kit mode (SPEC-CONTRACT Phase 2). Default root is deliberately $HOME so a
# real install needs no flag, and --client-dry-run makes a rehearsal safe.
CLIENT_MODE=false
CLIENT_ROOT="${CLIENT_ROOT:-$HOME}"
CLIENT_ANSWERS=""
CLIENT_DRY_RUN=false
CLIENT_KIT_NAME="pantheon-client-kit"

# Conductor onboarding (SPEC-CONTRACT Phase 3). Plan-first: nothing is called
# until --conductor-apply is passed AND a token file is supplied.
CONDUCTOR_PLATFORM=""
CONDUCTOR_GUILD=""
CONDUCTOR_CHAT=""
CONDUCTOR_TOKEN_FILE=""
CONDUCTOR_APPLY=false

# ─── Argument parsing ────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --enterprise)              ENTERPRISE_MODE=true; shift ;;
        --skip-composio-prompt)    SKIP_COMPOSIO_PROMPT=true; shift ;;
        --non-interactive)         NON_INTERACTIVE=true; shift ;;
        --phase)                   ONLY_PHASE="$2"; shift 2 ;;
        --client)                  CLIENT_MODE=true; shift ;;
        --client-root)             CLIENT_ROOT="$2"; shift 2 ;;
        --client-answers)          CLIENT_ANSWERS="$2"; shift 2 ;;
        --client-dry-run)          CLIENT_DRY_RUN=true; shift ;;
        --conductor-platform)      CONDUCTOR_PLATFORM="$2"; shift 2 ;;
        --conductor-guild)         CONDUCTOR_GUILD="$2"; shift 2 ;;
        --conductor-chat)          CONDUCTOR_CHAT="$2"; shift 2 ;;
        --conductor-token-file)    CONDUCTOR_TOKEN_FILE="$2"; shift 2 ;;
        --conductor-apply)         CONDUCTOR_APPLY=true; shift ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)  echo "Unknown flag: $1" >&2; exit 1 ;;
    esac
done

# ─── Logging ─────────────────────────────────────────────────────────────
LOG_DIR="$HOME/.local/share/pantheon-install"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/install-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

log() { printf "\033[1;36m[%s] %s\033[0m\n" "$(date +%H:%M:%S)" "$*"; }
ok()  { printf "\033[1;32m  ✓ %s\033[0m\n" "$*"; }
warn(){ printf "\033[1;33m  ! %s\033[0m\n" "$*"; }
die() { printf "\033[1;31m  ✗ %s\033[0m\n" "$*" >&2; exit "${2:-1}"; }

phase_done() {
    echo "PHASE_DONE: $1" >> "$LOG_FILE"
}

# ─── Phase gate ──────────────────────────────────────────────────────────
should_run_phase() {
    local phase="$1"
    [[ -z "$ONLY_PHASE" || "$ONLY_PHASE" == "$phase" ]]
}

# ─── Phase 0: preflight ──────────────────────────────────────────────────
phase_0_preflight() {
    log "Phase 0: preflight"

    # Not root
    if [[ $EUID -eq 0 ]]; then
        die "Do not run as root. This script uses --user systemd and \$HOME paths."
    fi

    # Distro detection
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        PLATFORM="${ID:-unknown}"
        PLATFORM_FAMILY="${ID_LIKE:-unknown}"
    elif [[ "$(uname)" == "Darwin" ]]; then
        PLATFORM="macos"
        PLATFORM_FAMILY="macos"
    else
        PLATFORM="unknown"
        PLATFORM_FAMILY="unknown"
    fi
    log "  platform=$PLATFORM family=$PLATFORM_FAMILY user=$USER home=$HOME"

    # Home writability
    [[ -w "$HOME" ]] || die "$HOME is not writable"
    ok "preflight passed"
    phase_done 0
}

# ─── Phase 1: install system packages ─────────────────────────────────────
phase_1_packages() {
    log "Phase 1: install system packages"
    case "$PLATFORM" in
        cachyos|arch|manjaro)
            sudo pacman -S --noconfirm --needed git curl python python-pip nodejs npm
            ;;
        ubuntu|debian|pop)
            sudo apt-get update
            sudo apt-get install -y git curl python3 python3-pip python3-venv nodejs npm
            ;;
        macos)
            if ! command -v brew >/dev/null 2>&1; then
                die "Homebrew not installed. Install from https://brew.sh first."
            fi
            brew install git curl python@3.11 node
            ;;
        *)
            warn "unknown platform; assuming git/curl/python3/node/npm are present"
            ;;
    esac

    for cmd in git curl python3 node npm; do
        command -v "$cmd" >/dev/null 2>&1 || die "missing required command: $cmd"
    done
    ok "system packages installed"
    phase_done 1
}

# ─── Phase 2: clone Pantheon ─────────────────────────────────────────────
phase_2_clone() {
    log "Phase 2: clone Pantheon"
    if [[ -d "$PANTHEON_HOME/.git" ]]; then
        log "  $PANTHEON_HOME already exists; pulling"
        (cd "$PANTHEON_HOME" && git fetch origin && git reset --hard "origin/$PANTHEON_REPO_BRANCH")
    else
        # Clone with submodule recurse. If the pinned submodule SHA is dead
        # (upstream force-push / ref rewrite / tag deleted), `--recurse-submodules`
        # dies with `upload-pack: not our ref <sha>`. We retry by populating
        # the submodule from the default branch of hermes-agent instead.
        if ! git clone --recurse-submodules --branch "$PANTHEON_REPO_BRANCH" "$PANTHEON_REPO" "$PANTHEON_HOME"; then
            warn "submodule clone failed (likely pinned SHA is gone from upstream)"
            log "  re-cloning with placeholder URL, then we will fix the submodule"
            rm -rf "$PANTHEON_HOME"
            git clone --branch "$PANTHEON_REPO_BRANCH" "$PANTHEON_REPO" "$PANTHEON_HOME"
            (
                cd "$PANTHEON_HOME"
                # Drop the dead pin and re-init submodule against default branch
                git submodule deinit -f hermes-agent 2>/dev/null || true
                git rm -f hermes-agent 2>/dev/null || true
                rm -rf .git/modules/hermes-agent
                git submodule add --force "https://github.com/NousResearch/hermes-agent.git" hermes-agent
                git -c user.name="pantheon-quickstart" -c user.email="quickstart@pantheon.local" \
                    commit -m "fix: re-pin hermes-agent submodule to live default branch" || true
            )
        fi
    fi
    ok "Pantheon cloned at $PANTHEON_HOME"
    phase_done 2
}

# ─── Phase 3: install Hermes Agent ────────────────────────────────────────
phase_3_hermes() {
    log "Phase 3: install Hermes Agent"
    mkdir -p "$HERMES_HOME"

    # Install hermes-agent (editable, so updates via git pull work)
    python3 -m pip install --user -e "$PANTHEON_HOME/hermes-agent"

    # Pin so the auto-updater doesn't undo our install
    touch "$PANTHEON_HOME/hermes-agent/.pantheon-pinned"
    touch "$HERMES_HOME/.update-locked"

    # Verify
    command -v hermes >/dev/null 2>&1 || die "hermes CLI not on PATH after install"
    local v
    v=$(hermes --version 2>&1 | head -1)
    log "  hermes --version: $v"
    ok "Hermes Agent installed"
    phase_done 3
}

# ─── Phase 4: Composio bridge ────────────────────────────────────────────
phase_4_composio() {
    log "Phase 4: install + start Composio bridge"

    # Install node deps
    (cd "$PANTHEON_HOME/composio-bridge" && npm ci)

    # Populate ~/.hermes/.env from the install template (if .env missing)
    if [[ ! -f "$HERMES_HOME/.env" ]]; then
        cp "$PANTHEON_HOME/install/assets/env/.env.example" "$HERMES_HOME/.env"
        chmod 600 "$HERMES_HOME/.env"
        log "  created $HERMES_HOME/.env (you'll need to fill in keys)"
    fi

    # Get the Composio project key (ak_…). See docs/COMPOSIO_SETUP.md.
    # composio-bridge/.env is the authoritative location for COMPOSIO_* (gitignored, 0600).
    local bridge_env="$PANTHEON_HOME/composio-bridge/.env"
    local project_key=""

    if [[ -n "${COMPOSIO_API_KEY:-}" ]]; then
        project_key="$COMPOSIO_API_KEY"
        log "  using COMPOSIO_API_KEY from environment"
    elif [[ -f "$bridge_env" ]] && grep -q '^COMPOSIO_API_KEY=ak_.\+$' "$bridge_env" 2>/dev/null; then
        project_key=$(grep '^COMPOSIO_API_KEY=' "$bridge_env" | cut -d= -f2-)
        log "  using COMPOSIO_API_KEY from composio-bridge/.env"
    elif [[ "$ENTERPRISE_MODE" == true || "$SKIP_COMPOSIO_PROMPT" == true || "$NON_INTERACTIVE" == true ]]; then
        warn "no Composio project key present; bridge will start but report composio:false"
        warn "see docs/COMPOSIO_SETUP.md to add it later"
    else
        echo
        echo "Composio integration setup"
        echo "=========================="
        echo "The wizard's Connect Integrations step needs a Composio PROJECT API key (ak_…)."
        echo "Sign up free at https://composio.dev, then copy the key from your project's"
        echo "  Settings -> API Keys  page."
        echo "The ck_ key on the personal 'Sessions & API Key' page is a different"
        echo "credential and will NOT work."
        echo
        read -r -s -p "COMPOSIO_API_KEY / ak_ project key (or Enter to skip): " project_key
        echo
    fi

    if [[ -n "$project_key" ]]; then
        if [[ "$project_key" != ak_* ]]; then
            warn "that key does not start with ak_; the bridge will reject it (see docs/COMPOSIO_SETUP.md)"
        fi
        umask 077
        printf 'COMPOSIO_API_KEY=%s\n' "$project_key" > "$bridge_env"
        chmod 600 "$bridge_env"
        ok "Composio project key written to composio-bridge/.env"
    elif [[ "$ENTERPRISE_MODE" != true && "$SKIP_COMPOSIO_PROMPT" != true && "$NON_INTERACTIVE" != true ]]; then
        warn "no Composio project key; bridge will start but report composio:false"
    fi

    # Install the systemd service
    mkdir -p "$SYSTEMD_USER_DIR"
    cp "$PANTHEON_HOME/install/assets/systemd/composio-bridge.service" \
       "$SYSTEMD_USER_DIR/composio-bridge.service"

    systemctl --user daemon-reload
    systemctl --user enable --now composio-bridge.service

    # Wait for health (max 30s)
    local i=0
    while (( i < 30 )); do
        if curl -fsS "http://127.0.0.1:$COMPOSIO_BRIDGE_PORT/health" >/dev/null 2>&1; then
            local health
            health=$(curl -fsS "http://127.0.0.1:$COMPOSIO_BRIDGE_PORT/health" 2>/dev/null || echo '{}')
            log "  composio health: $health"
            ok "Composio bridge is up"
            phase_done 4
            return 0
        fi
        sleep 1
        i=$((i+1))
    done
    warn "Composio bridge did not respond within 30s; check 'journalctl --user -u composio-bridge'"
    phase_done 4
}

# ─── Phase 5: Ollama ──────────────────────────────────────────────────────
phase_5_ollama() {
    log "Phase 5: install Ollama + pull nomic-embed-text"
    case "$PLATFORM" in
        cachyos|arch|manjaro)
            sudo pacman -S --noconfirm --needed ollama
            ;;
        ubuntu|debian|pop)
            curl -fsSL https://ollama.com/install.sh | sh
            ;;
        macos)
            brew install ollama
            ;;
        *)
            warn "unknown platform; assuming ollama is installed"
            ;;
    esac

    systemctl --user enable --now ollama.service

    # Pull nomic-embed-text only (wizard pulls chat models on demand)
    log "  pulling nomic-embed-text (this may take a minute)..."
    ollama pull nomic-embed-text

    # Verify
    ollama list | grep -q nomic-embed-text || die "nomic-embed-text not in ollama list after pull"
    ok "Ollama installed with nomic-embed-text"
    phase_done 5
}

# ─── Phase 6: faster-whisper + base model ─────────────────────────────────
phase_6_whisper() {
    log "Phase 6: install faster-whisper + base model"
    python3 -m pip install --user faster-whisper

    # Trigger the model download by instantiating
    log "  downloading base model (75MB, may take a minute)..."
    python3 -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu')" \
        || die "WhisperModel('base') failed to instantiate"

    ok "faster-whisper + base model ready"
    phase_done 6
}

# ─── Phase 7: Pantheon .env from example ─────────────────────────────────
phase_7_pantheon_env() {
    log "Phase 7: create Pantheon .env from example"
    if [[ -f "$PANTHEON_HOME/.env" ]]; then
        warn "  $PANTHEON_HOME/.env already exists; keeping (review it for completeness)"
    else
        cp "$PANTHEON_HOME/install/assets/env/.env.example" "$PANTHEON_HOME/.env"
        chmod 600 "$PANTHEON_HOME/.env"
    fi
    ok "Pantheon .env in place"
    phase_done 7
}

# ─── Phase 8: install core god profiles ─────────────────────────────────
phase_8_god_profiles() {
    log "Phase 8: install core god profiles (Hermes + Hephaestus)"

    # Hermes (default profile)
    if [[ ! -f "$HERMES_HOME/god.json" ]]; then
        cp "$PANTHEON_HOME/install/assets/env/hermes-god.json" "$HERMES_HOME/god.json"
        ok "wrote $HERMES_HOME/god.json (default profile)"
    else
        log "  $HERMES_HOME/god.json exists; keeping"
    fi

    # Hermes (named profile — the one the wizard actually checks at
    # webui/api/onboarding.py:1127). This is the gap the wizard
    # register_core_gods() doesn't close.
    local hermes_named="$HERMES_HOME/profiles/hermes"
    mkdir -p "$hermes_named"
    if [[ ! -f "$hermes_named/god.json" ]]; then
        cp "$PANTHEON_HOME/install/assets/env/hermes-god.json" "$hermes_named/god.json"
        ok "wrote $hermes_named/god.json (named profile, fixes wizard gap)"
    else
        log "  $hermes_named/god.json exists; keeping"
    fi

    # Hephaestus is NOT in the shipped client roster: he builds code, and the cut
    # removed both builders (see client-kit/manifest.yaml -> known_limits).
    if [[ "$CLIENT_MODE" == true ]]; then
        log "  client mode: skipping the Hephaestus profile (not in the shipped roster)"
        phase_done 8
        return 0
    fi

    # Hephaestus profile
    local heph_home="$HERMES_HOME/profiles/hephaestus"
    mkdir -p "$heph_home"
    if [[ ! -f "$heph_home/SOUL.md" ]]; then
        cp "$HEPHAESTUS_ASSETS/SOUL.md" "$heph_home/SOUL.md"
        ok "wrote $heph_home/SOUL.md"
    else
        log "  $heph_home/SOUL.md exists; keeping"
    fi
    if [[ ! -f "$heph_home/persona.md" ]]; then
        cp "$HEPHAESTUS_ASSETS/persona.md" "$heph_home/persona.md"
        ok "wrote $heph_home/persona.md"
    else
        log "  $heph_home/persona.md exists; keeping"
    fi
    if [[ ! -f "$heph_home/god.json" ]]; then
        cp "$HEPHAESTUS_ASSETS/god.json" "$heph_home/god.json"
        ok "wrote $heph_home/god.json"
    else
        log "  $heph_home/god.json exists; keeping"
    fi

    phase_done 8
}

# ─── Phase 9: install Hephaestus core skills ─────────────────────────────
phase_9_hephaestus_skills() {
    if [[ "$CLIENT_MODE" == true ]]; then
        log "Phase 9: skipped (client mode) — the skill manifest belongs to Hephaestus,"
        log "          who is not in the shipped roster"
        phase_done 9
        return 0
    fi
    log "Phase 9: install Hephaestus core skills (9 curated)"

    local heph_skills="$HERMES_HOME/profiles/hephaestus/skills"
    mkdir -p "$heph_skills"

    local manifest="$HEPHAESTUS_ASSETS/skills-manifest.txt"
    [[ -f "$manifest" ]] || die "skills manifest missing: $manifest"

    local installed=0
    while IFS= read -r skill; do
        # Skip comments and blank lines
        [[ -z "$skill" || "$skill" =~ ^# ]] && continue

        local src=""
        # shared-skills are the canonical home
        if [[ -d "$PANTHEON_HOME/god-packages/shared-skills/$skill" ]]; then
            src="$PANTHEON_HOME/god-packages/shared-skills/$skill"
        elif [[ -d "$PANTHEON_HOME/skills/$skill" ]]; then
            src="$PANTHEON_HOME/skills/$skill"
        else
            warn "  skill not found in repo: $skill (skipping)"
            continue
        fi

        # Symlink (idempotent)
        if [[ ! -e "$heph_skills/$skill" ]]; then
            ln -s "$src" "$heph_skills/$skill"
            installed=$((installed + 1))
        fi
    done < "$manifest"

    # Verify count
    local count
    count=$(find "$heph_skills" -maxdepth 1 -type l | wc -l)
    log "  Hephaestus skills: $count symlinks ($installed installed this run, expected $HEPHAESTUS_SKILL_COUNT)"
    [[ "$count" -ge "$HEPHAESTUS_SKILL_COUNT" ]] || warn "fewer skills than expected; check manifest"

    phase_done 9
}

# ─── Phase 8b: client roster (--client only) ──────────────────────────────
phase_8b_client_roster() {
    if [[ "$CLIENT_MODE" != true ]]; then
        return 0
    fi
    log "Phase 8b: install the shipped client roster"

    local installer="$PANTHEON_HOME/client-kit/roster_install.py"
    [[ -f "$installer" ]] || die "client roster installer missing: $installer"

    # The pack gates itself before it touches anything.
    if ! python3 "$installer" --check; then
        die "client kit failed its own artifact-hygiene check; nothing was installed"
    fi

    local -a args=(--root "$CLIENT_ROOT")
    [[ -n "$CLIENT_ANSWERS" ]] && args+=(--answers "$CLIENT_ANSWERS")
    [[ "$CLIENT_DRY_RUN" == true ]] && args+=(--dry-run)

    python3 "$installer" "${args[@]}" || die "client roster install failed"

    # Cross-check the result rather than trusting the exit code.
    local kit_json="$CLIENT_ROOT/.hermes/client-kit/MANIFEST.json"
    if [[ "$CLIENT_DRY_RUN" != true ]]; then
        [[ -f "$kit_json" ]] || die "client kit wrote no MANIFEST.json at $kit_json"
        local shipped
        shipped=$(python3 -c "import json,sys;print(len(json.load(open(sys.argv[1]))['gods']))" "$kit_json")
        [[ "$shipped" == "6" ]] || die "expected 6 shipped gods, MANIFEST.json says $shipped"
        ok "client roster installed: $shipped gods under $CLIENT_ROOT"
    fi
    phase_done 8b
}

# ─── Phase 8c: conductor onboarding (plan-first) ──────────────────────────
phase_8c_conductor() {
    local tool="$PANTHEON_HOME/client-kit/conductor_onboard.py"
    [[ -f "$tool" ]] || { warn "conductor tool missing: $tool"; return 0; }

    log "Phase 8c: conductor onboarding"

    # The pack's own gates first: the manifest, and the permission split that
    # otherwise fails live at "create the category".
    if ! python3 "$tool" --check; then
        if [[ "$CLIENT_MODE" == true ]]; then
            die "conductor check failed; fix the pack before onboarding a client"
        fi
        warn "conductor check failed (operator run; continuing)"
    fi

    if [[ -z "$CONDUCTOR_PLATFORM" ]]; then
        log "  no --conductor-platform given: skipping the platform plan"
        log "  next step is the wizard's interview, then:"
        log "    python3 $tool --platform discord --guild-id <id>"
        phase_done 8c
        return 0
    fi

    local -a args=(--platform "$CONDUCTOR_PLATFORM")
    case "$CONDUCTOR_PLATFORM" in
        discord)  [[ -n "$CONDUCTOR_GUILD" ]] && args+=(--guild-id "$CONDUCTOR_GUILD") ;;
        telegram) [[ -n "$CONDUCTOR_CHAT" ]]  && args+=(--chat-id "$CONDUCTOR_CHAT") ;;
        *) die "unknown --conductor-platform '$CONDUCTOR_PLATFORM' (discord | telegram)" ;;
    esac

    # Live verification signals come first: what MUST be observed before this is done.
    python3 "$tool" --platform "$CONDUCTOR_PLATFORM" --verify

    if [[ "$CONDUCTOR_APPLY" != true ]]; then
        python3 "$tool" "${args[@]}"
        warn "  plan only — nothing was called. Pass --conductor-apply with"
        warn "  --conductor-token-file to execute it."
        phase_done 8c
        return 0
    fi

    [[ -n "$CONDUCTOR_TOKEN_FILE" ]] || die "--conductor-apply needs --conductor-token-file"
    [[ -f "$CONDUCTOR_TOKEN_FILE" ]] || die "token file not found: $CONDUCTOR_TOKEN_FILE"
    python3 "$tool" "${args[@]}" --conductor-token-file "$CONDUCTOR_TOKEN_FILE" --apply \
        || die "conductor apply failed (see the call log above)"
    ok "conductor onboarding applied for $CONDUCTOR_PLATFORM"
    phase_done 8c
}

# ─── Phase 10: install systemd services ───────────────────────────────────
phase_10_services() {
    log "Phase 10: install + start Pantheon systemd services"

    mkdir -p "$SYSTEMD_USER_DIR"

    # pantheon-webui
    cp "$PANTHEON_HOME/webui/pantheon-webui.service" \
       "$SYSTEMD_USER_DIR/pantheon-webui.service"
    # pantheon-mcp
    cp "$PANTHEON_HOME/pantheon-core/pantheon-mcp.service" \
       "$SYSTEMD_USER_DIR/pantheon-mcp.service"
    # demeter-watcher
    cp "$PANTHEON_HOME/webui/demeter-watcher.service" \
       "$SYSTEMD_USER_DIR/demeter-watcher.service"

    systemctl --user daemon-reload
    systemctl --user enable --now pantheon-webui.service
    systemctl --user enable --now pantheon-mcp.service
    systemctl --user enable --now demeter-watcher.service

    # Wait for webui on :8787 (max 30s)
    local i=0
    while (( i < 30 )); do
        if curl -fsS -o /dev/null "http://127.0.0.1:$PANTHEON_WEBUI_PORT/onboarding/welcome" 2>/dev/null; then
            ok "pantheon-webui responding on :$PANTHEON_WEBUI_PORT"
            phase_done 10
            return 0
        fi
        sleep 1
        i=$((i+1))
    done
    warn "pantheon-webui did not respond within 30s; check 'journalctl --user -u pantheon-webui'"
    phase_done 10
}

# ─── Phase 11: install cron jobs ─────────────────────────────────────────
phase_11_cron() {
    if [[ "$CLIENT_MODE" == true ]]; then
        log "Phase 11: skipped (client mode) — these are the operator's fleet jobs"
        warn "  (dawn patrol, digests, tech-debt scans). A client's own schedule comes"
        warn "  from the interview: T4 sets the timezone, G9 sets recurring work."
        phase_done 11
        return 0
    fi
    log "Phase 11: install cron jobs"
    if [[ -x "$PANTHEON_HOME/scripts/setup-pantheon-cron.sh" ]]; then
        bash "$PANTHEON_HOME/scripts/setup-pantheon-cron.sh"
    else
        warn "setup-pantheon-cron.sh not found; skipping (manual cron setup needed)"
    fi
    phase_done 11
}

# ─── Phase 12: build Olympus-UI bundles ──────────────────────────────────
phase_12_olympus_ui() {
    log "Phase 12: build Olympus-UI bundles"

    local olympus_src="$HOME/Olympus-UI"
    if [[ ! -d "$olympus_src" ]]; then
        warn "Olympus-UI source not found at $olympus_src; cloning..."
        git clone --branch "feature/pwa-icons" \
            "https://github.com/Codex-God-Marvin/Olympus-UI" "$olympus_src" \
            || warn "Olympus-UI clone failed; wizard will serve a stub UI"
    fi

    if [[ -d "$olympus_src" ]]; then
        (cd "$olympus_src" && npm ci && npm run build) || warn "Olympus-UI build failed"
        if [[ -x "$PANTHEON_HOME/scripts/deploy-olympus.sh" ]]; then
            bash "$PANTHEON_HOME/scripts/deploy-olympus.sh" || warn "deploy-olympus.sh failed"
        fi
    fi

    phase_done 12
}

# ─── Phase 13: create god-exports runtime staging dir ───────────────────
phase_13_god_exports() {
    log "Phase 13: create god-exports runtime staging dir"
    mkdir -p "$GOD_EXPORTS_DIR"
    # The dir is gitignored; the install script creates it fresh
    ok "god-exports/ ready at $GOD_EXPORTS_DIR"
    phase_done 13
}

# ─── Phase 14: smoke test wizard endpoint ────────────────────────────────
phase_14_wizard_smoke() {
    log "Phase 14: smoke test wizard endpoint"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PANTHEON_WEBUI_PORT/onboarding/welcome" 2>/dev/null || echo "000")
    if [[ "$code" == "200" ]]; then
        ok "wizard reachable at http://localhost:$PANTHEON_WEBUI_PORT/onboarding/welcome"
    else
        warn "wizard returned HTTP $code; check pantheon-webui logs"
    fi
    phase_done 14
}

# ─── Phase 15: smoke test intake endpoint ────────────────────────────────
phase_15_intake() {
    log "Phase 15: smoke test intake endpoint"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        "http://127.0.0.1:$PANTHEON_WEBUI_PORT/api/onboarding/context-gathering" 2>/dev/null || echo "000")
    if [[ "$code" == "200" || "$code" == "405" ]]; then
        # 405 = method not allowed, which is fine — endpoint exists, just GET-only or whatever
        ok "intake endpoint reachable (HTTP $code)"
    else
        warn "intake endpoint returned HTTP $code; will be triggered by wizard Step 6"
    fi
    phase_done 15
}

# ─── Phase 16: final summary ─────────────────────────────────────────────
phase_16_summary() {
    log "Phase 16: final summary"

    if [[ "$CLIENT_MODE" == true ]]; then
        cat <<EOF

╔══════════════════════════════════════════════════════════════╗
║  Pantheon CLIENT install complete                             ║
╚══════════════════════════════════════════════════════════════╝

  Wizard:      http://localhost:$PANTHEON_WEBUI_PORT/onboarding/welcome
  Client kit:  $CLIENT_ROOT/.hermes/client-kit/
  Profiles:    $CLIENT_ROOT/.hermes/profiles/<god>/

  Shipped:     hermes (conductor), rheta, iris, thoth, kairos, caduceus
  Not shipped: hephaestus, marvin (no builder), mercer (no sales god)

Next steps:
  1. Open the wizard and answer the interview — tenant layer once, then per god
  2. Fill each profiles/<god>/.env (tokens are blank on purpose)
  3. Plan the platform onboarding (invites, channel mesh, lanes, phonebook):
       python3 $PANTHEON_HOME/client-kit/conductor_onboard.py --platform discord \
         --guild-id <guild id>
  4. Verify the pack any time:
       python3 $PANTHEON_HOME/client-kit/roster_install.py --check
       python3 $PANTHEON_HOME/client-kit/conductor_onboard.py --check

EOF
        phase_done 16
        return 0
    fi

    cat <<EOF

╔══════════════════════════════════════════════════════════════╗
║  Pantheon install complete                                    ║
╚══════════════════════════════════════════════════════════════╝

  Wizard:    http://localhost:$PANTHEON_WEBUI_PORT/onboarding/welcome
  Composio:  http://localhost:$COMPOSIO_BRIDGE_PORT/health
  MCP:       http://localhost:$PANTHEON_MCP_PORT/mcp

  Logs:      $LOG_FILE

Next steps:
  1. Open the wizard URL above
  2. Walk through the 6 steps
  3. If Composio health is "composio:false", fill in
     $HERMES_HOME/.env with your keys (see docs/COMPOSIO_SETUP.md)
  4. Run validate-pantheon.sh any time to check system health

EOF
    phase_done 16
}

# ─── Main ───────────────────────────────────────────────────────────────
main() {
    log "Pantheon install starting (log: $LOG_FILE)"
    [[ "$ENTERPRISE_MODE" == true ]] && log "  mode: enterprise"
    if [[ "$CLIENT_MODE" == true ]]; then
        log "  mode: client kit (roster: $PANTHEON_HOME/client-kit/manifest.yaml)"
        log "  target root: $CLIENT_ROOT"
        [[ "$CLIENT_DRY_RUN" == true ]] && log "  rehearsal: --client-dry-run (writes nothing)"
        [[ -n "$CONDUCTOR_PLATFORM" ]] && log "  conductor: $CONDUCTOR_PLATFORM \
(apply=$CONDUCTOR_APPLY) — see Phase 8c"
    fi
    [[ -n "$ONLY_PHASE" ]] && log "  running only phase $ONLY_PHASE"

    phase_0_preflight
    [[ "$ONLY_PHASE" == "0" ]] && exit 0

    should_run_phase 1 && phase_1_packages
    should_run_phase 2 && phase_2_clone
    should_run_phase 3 && phase_3_hermes
    should_run_phase 4 && phase_4_composio
    should_run_phase 5 && phase_5_ollama
    should_run_phase 6 && phase_6_whisper
    should_run_phase 7 && phase_7_pantheon_env
    should_run_phase 8 && phase_8_god_profiles
    should_run_phase 8b && phase_8b_client_roster
    should_run_phase 8c && phase_8c_conductor
    should_run_phase 9 && phase_9_hephaestus_skills
    should_run_phase 10 && phase_10_services
    should_run_phase 11 && phase_11_cron
    should_run_phase 12 && phase_12_olympus_ui
    should_run_phase 13 && phase_13_god_exports
    should_run_phase 14 && phase_14_wizard_smoke
    should_run_phase 15 && phase_15_intake
    should_run_phase 16 && phase_16_summary

    log "Done."
}

main "$@"
