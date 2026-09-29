#!/bin/bash
# Cycle every Pantheon god gateway unit — the step that loads changed core code
# (e.g. agent/account_usage.py) into the long-running god gateway processes.
#
# MUST be launched OUTSIDE the Hermes gateway process tree, e.g.
#   systemd-run --user --collect /home/konan/pantheon/scripts/god-gateway-cycle.sh
# Launching it from inside a gateway-spawned shell means a SIGTERM to that gateway
# propagates to this script and can abort the sweep halfway through.
#
# One unit at a time, waiting for a *new* MainPID before moving on, so the fleet is
# never fully down at once. Writes a per-god line plus DONE to $LOG.
set -u

LOG=/home/konan/.hermes/logs/god-gateway-cycle.log
mkdir -p "$(dirname "$LOG")"
: > "$LOG"
echo "started $(date -Is)" >> "$LOG"

for god in apollo caduceus hephaestus iris kairos marvin mercer rheta thoth; do
  unit="hermes-gateway@${god}.service"
  before=$(systemctl --user show -p MainPID --value "$unit")
  systemctl --user restart "$unit" >>"$LOG" 2>&1
  state=starting
  pid=""
  for _ in $(seq 1 30); do
    state=$(systemctl --user is-active "$unit")
    pid=$(systemctl --user show -p MainPID --value "$unit")
    if [ "$state" = "active" ] && [ -n "$pid" ] && [ "$pid" != "0" ] && [ "$pid" != "$before" ]; then
      break
    fi
    sleep 2
  done
  printf '%-11s %-8s pid %s -> %s  since %s\n' "$god" "$state" "$before" "$pid" \
    "$(systemctl --user show -p ActiveEnterTimestamp --value "$unit")" >> "$LOG"
done

echo "DONE $(date -Is)" >> "$LOG"
