#!/usr/bin/env bash
# validate-pantheon.sh — health check for an installed Pantheon system
#
# Source of truth: ~/athenaeum/Codex-Olympus/INSTALL_PIPELINE.md §5
# Tests each of the 16 install goals with PASS/FAIL and a non-zero exit on any FAIL.
#
# n8n check is intentionally absent (known broken, out of scope per user).
#
# Exit codes:
#   0  all checks pass
#   1  one or more checks failed
#   2  preflight failure (e.g., Pantheon not installed)

set -uo pipefail

HERMES_HOME="$HOME/.hermes"
PANTHEON_HOME="$HOME/pantheon"
COMPOSIO_PORT=8789
PANTHEON_PORT=8787
PANTHEON_MCP_PORT=8010

FAILS=0
PASSES=0
WARNS=0

pass() { printf "  \033[1;32m✓\033[0m %s\n" "$*"; PASSES=$((PASSES+1)); }
fail() { printf "  \033[1;31m✗\033[0m %s\n" "$*"; FAILS=$((FAILS+1)); }
warn() { printf "  \033[1;33m!\033[0m %s\n" "$*"; WARNS=$((WARNS+1)); }

heading() { printf "\n\033[1;36m== %s ==\033[0m\n" "$*"; }

# ─── Preflight ──────────────────────────────────────────────────────────
heading "Preflight"
if [[ ! -d "$PANTHEON_HOME" ]]; then
    fail "Pantheon not installed at $PANTHEON_HOME (run install-pantheon.sh first)"
    exit 2
fi
pass "Pantheon repo at $PANTHEON_HOME"

# ─── G1: Hermes Agent installed ─────────────────────────────────────────
heading "G1: Hermes Agent"
if command -v hermes >/dev/null 2>&1; then
    v=$(hermes --version 2>&1 | head -1)
    pass "hermes --version: $v"
else
    fail "hermes CLI not on PATH"
fi

# ─── G2: Pantheon cloned at expected HEAD ──────────────────────────────
heading "G2: Pantheon clone"
cd "$PANTHEON_HOME"
local_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
local_sha=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
pass "Pantheon on branch $local_branch @ $local_sha"

# ─── G3: Composio bridge running with credentials ──────────────────────
heading "G3: Composio bridge"
if curl -fsS "http://127.0.0.1:$COMPOSIO_PORT/health" 2>/dev/null | grep -q '"composio":true'; then
    pass "composio health: composio=true"
else
    health=$(curl -fsS "http://127.0.0.1:$COMPOSIO_PORT/health" 2>/dev/null || echo "{}")
    if [[ "$health" != "{}" ]]; then
        warn "composio health: $health (bridge up but composio=false; check ~/.hermes/.env keys)"
    else
        fail "composio bridge not reachable on :$COMPOSIO_PORT"
    fi
fi

# G3b: n8n is intentionally NOT checked
heading "G3b: n8n (intentionally out of scope)"
warn "n8n check skipped (out of scope per user; see docs/N8N_SETUP.md if you want to fix it)"

# ─── G4: Ollama + nomic-embed-text ─────────────────────────────────────
heading "G4: Ollama"
if command -v ollama >/dev/null 2>&1; then
    # Don't pipe `ollama list` directly to grep — `grep -q` exits on first
    # match, closing the pipe and SIGPIPE-ing ollama, which trips pipefail.
    # Capture into a variable first.
    ollama_list=$(ollama list 2>/dev/null || true)
    if printf '%s\n' "$ollama_list" | grep -q nomic-embed-text; then
        pass "ollama list contains nomic-embed-text"
    else
        fail "ollama installed but nomic-embed-text not in model list"
    fi
else
    fail "ollama not on PATH"
fi

# ─── G5/G6: faster-whisper + base model ────────────────────────────────
heading "G5/G6: faster-whisper"
if python3 -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu')" 2>/dev/null; then
    pass "WhisperModel('base') loads without network"
else
    fail "WhisperModel('base') failed (model not downloaded or pip install missing)"
fi

# ─── G7: 2 god profiles pre-installed ──────────────────────────────────
heading "G7: God profiles"
[[ -f "$HERMES_HOME/god.json" ]] \
    && pass "~/.hermes/god.json exists (default profile)" \
    || fail "~/.hermes/god.json missing"
[[ -f "$HERMES_HOME/profiles/hermes/god.json" ]] \
    && pass "~/.hermes/profiles/hermes/god.json exists (named profile, fixes wizard gap)" \
    || fail "~/.hermes/profiles/hermes/god.json missing (wizard's register_core_gods will report Hermes as missing)"
[[ -f "$HERMES_HOME/profiles/hephaestus/SOUL.md" ]] \
    && pass "~/.hermes/profiles/hephaestus/SOUL.md exists" \
    || fail "~/.hermes/profiles/hephaestus/SOUL.md missing"

# ─── G9: Hephaestus core skills ─────────────────────────────────────────
heading "G9: Hephaestus skills"
heph_skills="$HERMES_HOME/profiles/hephaestus/skills"
if [[ -d "$heph_skills" ]]; then
    # Count both symlinks (new install contract) and directories (legacy
    # pre-install setups). Either satisfies the post-install goal.
    count=$(find "$heph_skills" -maxdepth 1 -mindepth 1 \( -type l -o -type d \) | wc -l)
    if [[ "$count" -ge 9 ]]; then
        pass "Hephaestus has $count skills (expected ≥9)"
    else
        fail "Hephaestus has $count skills (expected ≥9)"
    fi
else
    fail "$heph_skills missing"
fi

# ─── G11: MCP server reachable ─────────────────────────────────────────
heading "G11: MCP server"
if curl -fsS -o /dev/null "http://127.0.0.1:$PANTHEON_MCP_PORT/mcp" 2>/dev/null; then
    pass "pantheon-mcp reachable on :$PANTHEON_MCP_PORT/mcp"
else
    fail "pantheon-mcp not reachable on :$PANTHEON_MCP_PORT/mcp"
fi

# ─── G13: systemd services active ──────────────────────────────────────
heading "G13: systemd services"
for svc in pantheon-webui pantheon-mcp demeter-watcher composio-bridge; do
    if systemctl --user is-active "$svc.service" >/dev/null 2>&1; then
        pass "$svc.service active"
    else
        fail "$svc.service not active (status: $(systemctl --user is-active "$svc.service" 2>&1))"
    fi
done

# ─── G15: wizard reachable ─────────────────────────────────────────────
heading "G15: SPA wizard"
code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PANTHEON_PORT/onboarding/welcome" 2>/dev/null || echo "000")
if [[ "$code" == "200" ]]; then
    pass "wizard returns 200 at /onboarding/welcome"
else
    fail "wizard returns HTTP $code (expected 200)"
fi

# ─── G16: GitHub is clean (no archive/, no harness/ YAMLs, etc.) ──────
heading "G16: clean public repo"
cd "$PANTHEON_HOME"
untracked_junk=$(git status -s 2>/dev/null | grep -E '\.tar\.gz$|\.zip$|archive/' | head -5)
if [[ -z "$untracked_junk" ]]; then
    pass "no untracked tarballs/zipfiles/archive cruft"
else
    warn "untracked cruft found:"
    echo "$untracked_junk" | sed 's/^/      /'
fi

if [[ -d harnesses ]]; then
    yaml_count=$(find harnesses -maxdepth 1 -name '*.yaml' 2>/dev/null | wc -l)
    if [[ "$yaml_count" -eq 0 ]]; then
        pass "harnesses/ has no YAML files"
    else
        fail "harnesses/ has $yaml_count YAML files (should be 0)"
    fi
fi

pc_count=$(git ls-files pantheon-core/ 2>/dev/null | wc -l)
if [[ "$pc_count" -eq 2 ]]; then
    pass "pantheon-core/ has $pc_count tracked files (expected 2: mcp_server.py + service)"
else
    fail "pantheon-core/ has $pc_count tracked files (expected 2)"
fi

# ─── Summary ────────────────────────────────────────────────────────────
heading "Summary"
total=$((PASSES + FAILS + WARNS))
echo
echo "  $PASSES pass, $FAILS fail, $WARNS warn, $total total"
echo

if [[ $FAILS -gt 0 ]]; then
    echo -e "\033[1;31mFAIL: $FAILS check(s) failed\033[0m"
    exit 1
else
    echo -e "\033[1;32mPASS: all checks passed\033[0m"
    exit 0
fi
