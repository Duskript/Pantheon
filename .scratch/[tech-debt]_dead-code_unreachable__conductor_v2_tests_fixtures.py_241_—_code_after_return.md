## [tech-debt] dead-code/unreachable

| Field | Value |
|-------|-------|
| **File** | `/home/konan/pantheon/conductor/v2/tests/fixtures.py` |
| **Line** | 241 |
| **Severity** | high |
| **Detected** | 2026-07-06T11:09:00Z |
| **Author** | unknown |

### Context

code after return

This batch covers **1 findings across 1 files**.

### Samples

| File | Line | Description |
|---|---:|---|
| `conductor/v2/tests/fixtures.py` | 241 | code after return |

### Representative Snippet

```
240:        return
241:        yield  # make this an async generator
242:
```

### Recommendation

Remove the unreachable statement or move it into the intended control-flow branch.

### Labels

`tech-debt`, `category:dead-code`, `severity:high`
