## [tech-debt] dead-code/unreachable

| Field | Value |
|-------|-------|
| **File** | `/home/konan/pantheon/webui/api/routes.py` |
| **Line** | 8210 |
| **Severity** | high |
| **Detected** | 2026-07-06T11:09:00Z |
| **Author** | unknown |

### Context

code after return

This batch covers **1 findings across 1 files**.

### Samples

| File | Line | Description |
|---|---:|---|
| `webui/api/routes.py` | 8210 | code after return |

### Representative Snippet

```
8209:        # REMOVED (ACI.dev dead direction): from api.connectors import handle_post_disconnect
8210:        return handle_post_disconnect(handler)
8211:
```

### Recommendation

Remove the unreachable statement or move it into the intended control-flow branch.

### Labels

`tech-debt`, `category:dead-code`, `severity:high`
