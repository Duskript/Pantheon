## [tech-debt] deprecated/run_until_complete

| Field | Value |
|-------|-------|
| **File** | `/home/konan/pantheon/conductor/v2/engine.py` |
| **Line** | 2569 |
| **Severity** | medium |
| **Detected** | 2026-07-06T11:09:00Z |
| **Author** | unknown |

### Context

3 callsites across 3 files

This batch covers **3 findings across 3 files**.

### Samples

| File | Line | Description |
|---|---:|---|
| `conductor/v2/engine.py` | 2569 | use asyncio.run() |
| `scripts/inbox-notifier.py` | 189 | use asyncio.run() |
| `scripts/inbox-watcher.py` | 338 | use asyncio.run() |

### Representative Snippet

```
2568:            asyncio.set_event_loop(loop)
2569:        return loop.run_until_complete(
2570:            self.approve_quarantined_async(quarantine_filename, approver=approver, action=action)
```

### Recommendation

Replace `loop.run_until_complete(...)` with `asyncio.run(...)` or an explicit async entrypoint.

### Labels

`tech-debt`, `category:deprecated`, `severity:medium`
