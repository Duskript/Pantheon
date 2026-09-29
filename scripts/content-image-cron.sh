#!/usr/bin/env bash
# 6am content-pipeline image run, plus the reaction collect that follows it.
#
# ORDER IS THE POINT
# ------------------
# `collect` runs FIRST. Reactions accumulate overnight, and collecting before drafting
# means a variant chosen at 11pm is applied to its job before the new day's work starts.
# Collecting after would leave that job imageless for another full day.
#
# The draft phase needs post copy. Until the upstream topic/draft steps exist, that copy
# comes from a plan file the operator writes. No plan file means the draft phase is
# skipped and reported - it never invents copy, and it never drafts an image for an
# empty post.
#
# MODES
# -----
#   content-image-cron.sh                 collect, then draft (the 06:00 run)
#   content-image-cron.sh --collect-only  collect only (the */15 run)
#
# `--collect-only` exists because the every-15-minutes entry must NOT draft. Without
# this flag the frequent entry would generate image variants 96 times a day - real
# spend and a flooded channel. The mode is explicit, not inferred from argv, and an
# unrecognised argument exits 2 rather than silently defaulting to the expensive path.
#
# Every run appends to the log. A silent cron is indistinguishable from a broken one.
set -uo pipefail

PY=/home/konan/.hermes/installs/0e9a9a07be293592/environments/eb330f29c6584cc995caafbf6ca89d49/venv/bin/python3
RUNNER=/home/konan/pantheon/scripts/content_image_runner.py
PLAN=/home/konan/pantheon/shared/content-plan.json
LOG=/home/konan/pantheon/logs/content-image-runner.log

MODE="full"
case "${1:-}" in
  --collect-only) MODE="collect" ;;
  "" )            MODE="full" ;;
  * )             echo "unknown argument: $1" >&2; exit 2 ;;
esac

mkdir -p "$(dirname "$LOG")"
{
  echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) content-image-runner mode=$MODE ====="

  echo "--- collect (reactions from the last 24h) ---"
  "$PY" "$RUNNER" collect 2>&1 || echo "collect exited $?"

  if [ "$MODE" = "collect" ]; then
    echo "--- draft skipped: --collect-only ---"
  elif [ -f "$PLAN" ]; then
    echo "--- draft from $PLAN ---"
    "$PY" "$RUNNER" draft --all --text-file "$PLAN" --tier draft 2>&1 \
      || echo "draft exited $?"
  else
    echo "--- draft skipped: no plan file at $PLAN ---"
  fi

  echo "--- status ---"
  "$PY" "$RUNNER" status 2>&1 | head -40
  echo
} >> "$LOG" 2>&1
