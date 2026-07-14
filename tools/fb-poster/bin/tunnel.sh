#!/usr/bin/env bash
# tunnel.sh — start an SSH SOCKS5 tunnel from laptop -> CachyOS.
# Idempotent: reuses an existing tunnel if the port is already bound.

set -euo pipefail

REMOTE=${FB_PROXY_REMOTE:-konan@100.114.60.103}
LOCAL_PORT=${FB_PROXY_PORT:-1080}
PIDFILE="/tmp/fb-poster-tunnel.${LOCAL_PORT}.pid"
LOGFILE="$(dirname "$0")/../logs/tunnel.log"

is_up() {
    # Liveness check: can we actually reach a host through the SOCKS5?
    # curl --socks5 fails fast with non-zero exit if the port is bound
    # but the tunnel is dead.
    curl -sS --max-time 3 --socks5-hostname "127.0.0.1:${LOCAL_PORT}" \
        https://api.ipify.org >/dev/null 2>&1
}

if is_up; then
    echo "tunnel already up on 127.0.0.1:${LOCAL_PORT}"
    exit 0
fi

# Stale pidfile cleanup
[[ -f "$PIDFILE" ]] && kill "$(cat "$PIDFILE")" 2>/dev/null || true
rm -f "$PIDFILE"

# Disable strict host key prompts on first run noise
mkdir -p ~/.ssh
touch ~/.ssh/known_hosts
ssh-keygen -F "$REMOTE" >/dev/null 2>&1 || ssh-keyscan "${REMOTE##*@}" >> ~/.ssh/known_hosts 2>/dev/null || true

# -N no remote command, -D SOCKS, -f background, -T no tty, -n /dev/null stdin
nohup ssh -N -D "${LOCAL_PORT}" \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -o StrictHostKeyChecking=accept-new \
    "$REMOTE" >>"$LOGFILE" 2>&1 &

echo $! > "$PIDFILE"
disown || true

# Wait for tunnel to come up (max ~10s)
for i in {1..20}; do
    if is_up; then
        echo "tunnel up — PID $(cat "$PIDFILE"), port ${LOCAL_PORT}"
        exit 0
    fi
    sleep 0.5
done

echo "tunnel failed to come up — see $LOGFILE" >&2
exit 1
