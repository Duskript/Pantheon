#!/bin/bash
# install-touch.sh — install the TheoForge touch sequence systemd
# service + timer. Run once on Pantheon (sudo required).
#
# Usage:
#   chmod +x install-touch.sh && ./install-touch.sh

set -euo pipefail

SRC="/home/konan/pantheon/services/theoforge-bridge"
DST="/etc/systemd/system"

for f in theoforge-touch.service theoforge-touch.timer; do
  echo "→ Installing $f"
  sudo install -m 0644 "$SRC/$f" "$DST/$f"
done

echo "→ Reloading systemd daemon"
sudo systemctl daemon-reload

echo "→ Enabling + starting theoforge-touch.timer"
sudo systemctl enable --now theoforge-touch.timer

echo
echo "→ Timer status"
sudo systemctl list-timers theoforge-touch.timer --no-pager

echo
echo "→ Next 3 scheduled runs"
sudo systemctl list-timers theoforge-touch.timer --all --no-pager 2>&1 | head -10

echo
echo "Done. To watch logs: journalctl -u theoforge-touch -f"
echo "To trigger a manual run: sudo systemctl start theoforge-touch.service"
