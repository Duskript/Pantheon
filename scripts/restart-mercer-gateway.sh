#!/bin/bash
# 2026-09-18 — one-shot restart of the Mercer god gateway.
#
# Why this exists: the terminal-tool gateway guard blocks any
# `systemctl --user restart hermes-gateway@<god>` issued from inside a gateway
# process (see skills/pantheon/pantheon-operations/references/
# gateway-restart-via-cron.md). A one-shot no_agent cron job runs OUTSIDE the
# gateway, so this script can do the restart legitimately.
#
# Purpose of this particular restart: load Mercer's new explicit
# `gateway.platforms.discord.enabled: false` lock (Mercer has no Discord bot by
# design; the lock stops it inheriting the shared Hermes bot token and stealing
# the main gateway's Discord session).

set -u
LOG="/home/konan/pantheon/logs/mercer-gateway-restart.log"
mkdir -p "$(dirname "$LOG")"

{
  echo "=== $(date -Is) restarting hermes-gateway@mercer.service ==="
  systemctl --user restart hermes-gateway@mercer.service
  rc=$?
  echo "restart rc=$rc"
  sleep 15
  systemctl --user show hermes-gateway@mercer.service \
      -p ActiveState -p SubState -p MainPID -p NRestarts --value | tr '\n' ' '
  echo
  echo "--- mercer gateway log: platform connect lines ---"
  tail -80 /home/konan/.hermes/profiles/mercer/logs/gateway.log \
    | grep -aiE 'Connecting to|✓ .* connected|Gateway running|discord|disabled' | tail -20
  echo "--- discord references in last 300 log lines (expect 0) ---"
  tail -300 /home/konan/.hermes/profiles/mercer/logs/gateway.log | grep -aic discord
  echo "=== done ==="
} >> "$LOG" 2>&1
