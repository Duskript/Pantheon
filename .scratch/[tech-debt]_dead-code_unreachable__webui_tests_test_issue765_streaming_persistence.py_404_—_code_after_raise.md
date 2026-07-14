## [tech-debt] dead-code/unreachable

| Field | Value |
|-------|-------|
| **File** | `/home/konan/pantheon/webui/tests/test_issue765_streaming_persistence.py` |
| **Line** | 404 |
| **Severity** | high |
| **Detected** | 2026-07-06T11:09:00Z |
| **Author** | unknown |

### Context

code after raise

This batch covers **1 findings across 1 files**.

### Samples

| File | Line | Description |
|---|---:|---|
| `webui/tests/test_issue765_streaming_persistence.py` | 404 | code after raise |

### Representative Snippet

```
403:                raise ValueError("early failure, e.g. get_session KeyError")
404:                _checkpoint_stop = threading.Event()  # never reached
405:            finally:
```

### Recommendation

Remove the unreachable statement or move it into the intended control-flow branch.

### Labels

`tech-debt`, `category:dead-code`, `severity:high`
