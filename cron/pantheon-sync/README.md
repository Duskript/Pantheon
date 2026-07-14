# Pantheon Sync Scheduler (T11)

20-minute cron sync loop that walks active connections, checks sync state, and calls adapters.

## Files

| File | Purpose |
|------|---------|
| `sync_scheduler.py` | Main entry point — the cron loop |
| `sync_state.py` | `SyncState` class: tracks `last_sync`, `cursor`, `records_today`, daily budget + reset logic |
| `connections.json` | Active connections configuration |
| `scan.log` | Every tick is logged here (auto-created) |
| `sync_state.json` | Persisted state between ticks (auto-created) |

## Quick Start

```bash
# Single tick (cron mode)
cd ~/.hermes/cron/pantheon-sync
python3 sync_scheduler.py

# Continuous loop (useful for testing / daemon mode)
python3 sync_scheduler.py --loop

# Custom interval (e.g. 10 minutes)
python3 sync_scheduler.py --loop --interval 600
```

## Cron Setup

The recommended cron line (NOT installed by this script — add manually):

```cron
*/20 * * * * cd ~/.hermes/cron/pantheon-sync && python3 sync_scheduler.py
```

To install it, run `crontab -e` and paste the line above.

## How It Works

1. **Load** — reads `connections.json`, filtering to `enabled: true` connections
2. **Check state** — for each connection:
   - Resets `records_today` if the date has changed
   - Skips connections that aren't due yet (based on `sync_interval_minutes`)
   - Skips connections that have exceeded their `daily_budget`
3. **Call adapter** — invokes the adapter registered for the connection
4. **Record** — updates `last_sync`, `cursor`, and `records_today` in `sync_state.json`
5. **Log** — writes a summary line to `scan.log` and stderr

### Error Handling

- The scheduler **never crashes** — every connection is wrapped in try/except
- Errors are logged with full tracebacks to `scan.log`
- A failed connection does not block other connections

## Adapter Stubs

Real adapters are built in T12. Currently all adapters are stubs that log `would sync <provider>` and return `{"synced": 0, "cursor": None, "status": "ok"}`.

To register a real adapter, add it to `ADAPTER_REGISTRY` in `sync_scheduler.py`.

## SyncState API

```python
from sync_state import SyncState

state = SyncState("~/.hermes/cron/pantheon-sync/sync_state.json")

# Check / reset daily budget
state.reset_daily_if_needed("wiki-dedup")
state.set_daily_budget("wiki-dedup", 500)
assert not state.is_over_budget("wiki-dedup")

# Scheduling
state.is_due("wiki-dedup", min_interval_minutes=20)   # → True/False

# Record sync
state.record_sync("wiki-dedup", records_synced=42, cursor="abc123")
```

## Design Decisions

- **Standalone** — no dependency on Hermes Agent or Olympus UI
- **Atomic writes** — state is saved via temp-file + rename to avoid corruption
- **Idempotent** — safe to run overlapping ticks (each checks `is_due` before acting)
- **Minimal** — only stdlib dependencies (`json`, `logging`, `argparse`, `pathlib`)
