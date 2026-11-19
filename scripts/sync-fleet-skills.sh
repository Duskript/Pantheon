#!/usr/bin/env bash
# sync-fleet-skills.sh — mirror the FULL Hermes skills library to attached Pantheon nodes.
#
# Builds one canonical export on this laptop:
#     ~/pantheon/god-packages/fleet-skills
#   = ~/.hermes/skills/            (the whole local library, admin junk excluded)
#   + ~/pantheon/god-packages/shared-skills/   overlaid, without clobbering local copies
# then rsyncs it (mirror, --delete) to the node's ~/pantheon/god-packages/fleet-skills.
#
# Usage: sync-fleet-skills.sh [remote-host]      (default: omarchy, where Mercury lives)
# Requires: ssh to the node via Tailscale SSH, rsync on both ends.
set -euo pipefail

REMOTE_HOST="${1:-omarchy}"
SRC="$HOME/.hermes/skills/"
SHARED="$HOME/pantheon/god-packages/shared-skills/"
STAGE="$HOME/pantheon/god-packages/fleet-skills/"
REMOTE_DEST="pantheon/god-packages/fleet-skills/"

# --- identity guard: never mutate a box that is not the one we named -----------------
actual="$(ssh -o ConnectTimeout=10 "$REMOTE_HOST" 'hostname' 2>/dev/null || true)"
if [ "$actual" != "$REMOTE_HOST" ]; then
  echo "REFUSE_WRONG_HOST: expected '$REMOTE_HOST', got '$actual'" >&2
  exit 1
fi

mkdir -p "$STAGE"

# 1. full local library, minus archives / backups / transient state.
#    -L (--copy-links): dereference symlinks so the export is self-contained —
#    a few skills are links (last30days, hermes-lcm, pantheon/auto-compact-topic-shift)
#    and relative links would dangle once mirrored to another host.
rsync -aL --delete \
  --exclude='.archive/' \
  --exclude='.audit/' \
  --exclude='.curator_backups/' \
  --exclude='.curator_ledger.jsonl' \
  --exclude='.curator_state' \
  --exclude='.curator_suppressed' \
  --exclude='.dojo-archive-*/' \
  --exclude='.hermes-tmp.*' \
  --exclude='.hub/' \
  --exclude='.locks/' \
  --exclude='.usage.json*' \
  --exclude='.bundled_manifest' \
  --exclude='__pycache__/' \
  --exclude='*.lock' \
  --exclude='.git/' \
  "$SRC" "$STAGE"

# 2. overlay the Pantheon shared library without overwriting newer local copies
rsync -a --ignore-existing "$SHARED" "$STAGE"

# 3. push to the node
rsync -a --delete "$STAGE" "$REMOTE_HOST:$REMOTE_DEST"

count="$(ssh -o ConnectTimeout=10 "$REMOTE_HOST" \
  'find ~/pantheon/god-packages/fleet-skills -name SKILL.md | wc -l')"
size="$(ssh -o ConnectTimeout=10 "$REMOTE_HOST" \
  'du -sh ~/pantheon/god-packages/fleet-skills | cut -f1')"
echo "synced -> $REMOTE_HOST:~/$REMOTE_DEST  skills=$count  size=$size"
