## [tech-debt] dead-code/unreachable

| Field | Value |
|-------|-------|
| **File** | `/home/konan/pantheon/scripts/clawforge-registry-server.py` |
| **Line** | 76 |
| **Severity** | high |
| **Detected** | 2026-07-06T11:09:00Z |
| **Author** | unknown |

### Context

code after return

This batch covers **1 findings across 1 files**.

### Samples

| File | Line | Description |
|---|---:|---|
| `scripts/clawforge-registry-server.py` | 76 | code after return |

### Representative Snippet

```
75:    return ""
76:    for line in Path(path).read_text().splitlines():
77:        line = line.strip()
```

### Recommendation

Remove the unreachable statement or move it into the intended control-flow branch.

### Labels

`tech-debt`, `category:dead-code`, `severity:high`
