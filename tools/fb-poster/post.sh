#!/usr/bin/env bash
# post.sh — thin CLI wrapper. Auto-starts tunnel, runs the python.
# Pass --headless for TUI / CI use; omit it for the interactive login
# flow (you need to see the Firefox window to complete 2FA).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/.venv/bin/activate"
bash "$HERE/bin/tunnel.sh"
exec python3 "$HERE/post.py" "$@"
