#!/usr/bin/env bash
# =============================================================================
# setup-ollama-models.sh — Install Ollama + Pull Models for Pantheon Onboarding
# =============================================================================
#
# Usage:
#   setup-ollama-models.sh [model1] [model2] ...
#   setup-ollama-models.sh qwen2.5:7b llama3.1:8b
#   setup-ollama-models.sh --check    # just check installed models
#
# Called by the Pantheon onboarding wizard (Step 2 — Local path).
# Each line written to stdout is a JSON object parseable line-by-line:
#   {"model":"qwen2.5:7b","status":"pending","message":""}
#   {"model":"qwen2.5:7b","status":"downloading","message":"45%"}
#   {"model":"qwen2.5:7b","status":"done","message":"success"}
#   {"model":"qwen2.5:7b","status":"error","message":"connection refused"}
#
# nomic-embed-text is ALWAYS pulled (required for Pantheon embeddings).
# Idempotent: already-pulled models report "done" immediately.
# =============================================================================

set -euo pipefail

# ── Constants ────────────────────────────────────────────────────────────────
OLLAMA_INSTALL_URL="https://ollama.com/install.sh"
EMBEDDING_MODEL="nomic-embed-text:latest"

# ── JSON helpers (no external deps) ──────────────────────────────────────────
_emit() {
    local model="$1" status="$2" message="${3:-}"
    # Escape JSON-special chars in message
    message="${message//\\/\\\\}"
    message="${message//\"/\\\"}"
    message="${message//$'\n'/\\n}"
    message="${message//$'\r'/}"
    message="${message//$'\t'/\\t}"
    printf '{"model":"%s","status":"%s","message":"%s"}\n' "$model" "$status" "$message"
}

_emit_pending()   { _emit "$1" "pending"   "$2"; }
_emit_downloading(){ _emit "$1" "downloading" "$2"; }
_emit_done()      { _emit "$1" "done"      "$2"; }
_emit_error()     { _emit "$1" "error"     "$2"; }

# ── Detect / install Ollama ──────────────────────────────────────────────────
_ensure_ollama() {
    if command -v ollama &>/dev/null; then
        _emit "ollama" "done" "$(ollama --version 2>/dev/null || echo 'installed')"
    else
        _emit "ollama" "pending" "installing..."
        if curl -fsSL "$OLLAMA_INSTALL_URL" | sh 2>&1; then
            _emit "ollama" "done" "installed"
        else
            _emit "ollama" "error" "failed to install Ollama"
            exit 1
        fi
    fi
}

# ── Check if model is already pulled ─────────────────────────────────────────
_is_pulled() {
    local model="$1"
    # Normalize: strip :latest if present for comparison
    local base="${model%:latest}"
    # ollama list shows model names; grep for the model
    # Output format: "modelname:tag    id    size    modified"
    if ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' | grep -qFx "$model" 2>/dev/null; then
        return 0
    fi
    # If exact match fails, try without :latest
    if [ "$model" != "$base" ]; then
        if ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' | grep -qFx "$base" 2>/dev/null; then
            return 0
        fi
    fi
    # Also try matching base name with any tag
    if ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' | grep -q "^${base}:" 2>/dev/null; then
        return 0
    fi
    return 1
}

# ── Pull a single model with progress ────────────────────────────────────────
_pull_model() {
    local model="$1"

    _emit_pending "$model" "starting pull"

    # Check if already pulled
    if _is_pulled "$model"; then
        _emit_done "$model" "already installed"
        return 0
    fi

    # Pull the model and parse progress from stderr/stdout
    # ollama pull writes progress to stderr
    local tmpfile
    tmpfile="$(mktemp)"
    local exit_code=0

    # Run ollama pull, capturing stderr to a file for progress parsing
    # while letting stdout pass through
    ollama pull "$model" 2>"$tmpfile" 1>&2 || exit_code=$?

    if [ $exit_code -ne 0 ]; then
        local err
        err="$(tail -5 "$tmpfile" | tr '\n' ' ' | sed 's/  */ /g' | xargs)"
        _emit_error "$model" "${err:-pull failed}"
        rm -f "$tmpfile"
        return 1
    fi

    # Parse progress: look for percentage patterns like "45%" or "100%"
    # ollama pull stderr lines look like:
    #   pulling manifest
    #   pulling <hash>... 100% ▕██████████████████▏ 4.7 GB
    #   verifying sha256 digest
    #   writing manifest
    #   success
    local last_pct=0
    while IFS= read -r line; do
        # Extract percentage from lines like "pulling ... 45% ..."
        if [[ "$line" =~ pulling ]]; then
            local pct
            pct="$(echo "$line" | grep -oP '\d+(?=%)' 2>/dev/null || true)"
            if [ -n "$pct" ] && [ "$pct" != "$last_pct" ]; then
                last_pct="$pct"
                _emit_downloading "$model" "${pct}%"
            fi
        fi
    done < "$tmpfile"

    rm -f "$tmpfile"

    # Verify the model is now in the list
    if _is_pulled "$model"; then
        _emit_done "$model" "pulled (100%)"
    else
        _emit_error "$model" "pull completed but model not found in list"
        return 1
    fi

    return 0
}

# ── Summary report ───────────────────────────────────────────────────────────
_summary() {
    local total="$1" ok="$2" fail="$3" pending="${4:-0}"
    if [ "${pending:-0}" -gt 0 ]; then
        printf '{"summary":{"total":%d,"done":%d,"pending":%d,"error":%d}}\n' "$total" "$ok" "$pending" "$fail"
    else
        printf '{"summary":{"total":%d,"done":%d,"error":%d}}\n' "$total" "$ok" "$fail"
    fi
}

# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

main() {
    local models=()
    local check_only=false

    # Parse flags
    for arg in "$@"; do
        case "$arg" in
            --check)
                check_only=true
                ;;
            *)
                models+=("$arg")
                ;;
        esac
    done

    # ── Install Ollama if needed ──────────────────────────────────────────
    _ensure_ollama

    # ── Collect model list: user args + nomic-embed-text ───────────────────
    local all_models=()

    # Always include nomic-embed-text
    all_models+=("$EMBEDDING_MODEL")

    for m in "${models[@]}"; do
        # Deduplicate: skip if nomic-embed-text was already added
        if [ "$m" = "nomic-embed-text" ] || [ "$m" = "nomic-embed-text:latest" ]; then
            continue
        fi
        all_models+=("$m")
    done

    if [ ${#all_models[@]} -eq 1 ] && [ "${all_models[0]}" = "$EMBEDDING_MODEL" ]; then
        # Only nomic-embed-text was requested (no user models)
        # This is fine — we'll still pull it if needed
        :
    fi

    # ── Pull each model ────────────────────────────────────────────────────
    local total=${#all_models[@]}
    local ok=0
    local fail=0
    local pending=0

    if $check_only; then
        # --check mode: just report installed status, don't pull
        for model in "${all_models[@]}"; do
            if _is_pulled "$model"; then
                _emit_done "$model" "installed"
                ok=$((ok + 1))
            else
                _emit_pending "$model" "not installed"
                pending=$((pending + 1))
            fi
        done
        _summary "$total" "$ok" "$fail" "$pending"
        return $(( pending > 0 ? 1 : 0 ))
    else
        for model in "${all_models[@]}"; do
            if _pull_model "$model"; then
                ok=$((ok + 1))
            else
                fail=$((fail + 1))
            fi
        done
    fi

    _summary "$total" "$ok" "$fail"

    return $(( fail > 0 ? 1 : 0 ))
}

main "$@"
