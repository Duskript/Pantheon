"""Heartbeat check script - run by cron job"""
import sys
sys.path.insert(0, '/home/konan/pantheon')
from scripts.heartbeat import check_stale, get_all
from datetime import datetime, timezone

now = datetime.now(timezone.utc)

# Check stale subsystems
stale = check_stale()
if stale:
    print("⚠️  STALE SUBSYSTEMS:")
    for s in stale:
        print(f'  ❌ {s["label"]} ({s["subsystem_id"]}): {s.get("reason")} | stale {s.get("staleness_min","?")}min | expected {s["expected_interval_min"]}min')
else:
    print("✅ All subsystems healthy")

print()
print("=== Full Heartbeat Status ===")
data = get_all()
for sid, info in sorted(data.items()):
    ok = info.get('last_ok')
    err = info.get('last_error')
    interval = info.get('expected_interval_min','?')
    if ok is None and err is None:
        status = '❌ Never'
    elif ok:
        dt = datetime.fromisoformat(ok)
        ago = (now - dt).total_seconds() / 60
        status = f'✅ OK ({round(ago)} min ago)'
    else:
        status = '⚠️  Error'
    print(f'  {status} | {info.get("label",sid):40s} | interval: {interval} min')
    if ok: print(f'         Last OK: {ok}')
    if err: print(f'         Last Err: {err}')
