## [tech-debt] dead-code/unreachable

| Field | Value |
|-------|-------|
| **File** | `/home/konan/pantheon/webui/api/routes.py` |
| **Line** | 8206 |
| **Severity** | high |
| **Detected** | 2026-07-06T11:09:00Z |
| **Author** | unknown |

### Context

code after return

This batch covers **1 findings across 1 files**.

### Samples

| File | Line | Description |
|---|---:|---|
| `webui/api/routes.py` | 8206 | code after return |

### Representative Snippet

```
8205:        # REMOVED (ACI.dev dead direction): from api.connectors import handle_post_connect
8206:        return handle_post_connect(handler)
8207:
```

### Recommendation

Remove the unreachable statement or move it into the intended control-flow branch.

### Labels

`tech-debt`, `category:dead-code`, `severity:high`
