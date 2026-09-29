#!/usr/bin/env bash
# Recurring Fix D Option A pass — summarise the empty-summary entities that
# relational recall can actually surface (T3-visible from Konan's person graph
# plus the top live-degree hubs). Silent by default: it prints a single line only
# when it wrote something or hit a failure, so the cron can run as a watchdog.
#
# Driven by: scripts/ichor_fix_d_priority_backfill.py (dry-run default, --apply here)
# Audit:     shared/handoffs/ichor-relational-recall-fix/fixd-audit-cron.jsonl
set -uo pipefail

# Resolve an interpreter that actually exists. The old per-user venv path
# (~/.hermes/hermes-agent/.venv) was removed when Hermes moved to
# /usr/local/lib/hermes-agent/venv — hardcoding it made this cron exit 127.
PY=""
for c in /usr/local/lib/hermes-agent/venv/bin/python3 \
         /home/konan/.hermes/runtimes/fleet/hermes-agent/.venv/bin/python3; do
  [ -x "$c" ] && { PY="$c"; break; }
done
[ -z "$PY" ] && PY="$(command -v python3 2>/dev/null || true)"
[ -z "$PY" ] && { echo "fixd backfill FATAL: no python3 interpreter found" >&2; exit 127; }
FIX_DIR=/home/konan/pantheon/shared/handoffs/ichor-relational-recall-fix
REPORT="$FIX_DIR/fixd-cron-run.json"

out=$("$PY" /home/konan/pantheon/scripts/ichor_fix_d_priority_backfill.py \
        --apply --limit 100 --batch-size 8 \
        --audit "$FIX_DIR/fixd-audit-cron.jsonl" \
        --report "$REPORT" 2>&1)
status=$?
if [ "$status" -ne 0 ]; then
  echo "fixd priority backfill FAILED (exit $status):"
  echo "$out" | tail -5
  exit 1
fi

"$PY" - "$REPORT" <<'PYEOF'
import json
import sys

report = json.load(open(sys.argv[1]))
tokens = report["tokens"]["prompt_tokens"] + report["tokens"]["completion_tokens"]
if report["written"] or report["failures"]:
    print(
        f"fixd priority backfill: targets={report['targets']} written={report['written']} "
        f"calls={report['calls']} tokens={tokens} failures={len(report['failures'])} "
        f"in-scope={report['scope']['empty_in_scope']}"
    )
PYEOF
