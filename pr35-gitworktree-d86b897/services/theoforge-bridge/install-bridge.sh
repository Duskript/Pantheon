#!/bin/bash
# install-bridge.sh — install + enable the TheoForge Bridge systemd unit.
# Run once on Pantheon (sudo required).
#
# Usage:
#   chmod +x install-bridge.sh && ./install-bridge.sh

set -euo pipefail

SERVICE_SRC="/home/konan/pantheon/services/theoforge-bridge/theoforge-bridge.service"
SERVICE_DST="/etc/systemd/system/theoforge-bridge.service"

if [ ! -f "$SERVICE_SRC" ]; then
  echo "ERROR: unit file not found at $SERVICE_SRC"
  exit 1
fi

echo "→ Installing unit file to $SERVICE_DST"
sudo install -m 0644 "$SERVICE_SRC" "$SERVICE_DST"

echo "→ Reloading systemd daemon"
sudo systemctl daemon-reload

echo "→ Enabling + starting theoforge-bridge.service"
sudo systemctl enable --now theoforge-bridge.service

echo "→ Waiting 2s for startup"
sleep 2

echo "→ Status"
sudo systemctl status theoforge-bridge.service --no-pager

echo ""
echo "→ Health check"
curl -sS --max-time 5 http://127.0.0.1:4323/healthz | python3 -m json.tool || echo "WARN: healthz not reachable"

echo ""
echo "Done. To watch logs: journalctl -u theoforge-bridge -f"
