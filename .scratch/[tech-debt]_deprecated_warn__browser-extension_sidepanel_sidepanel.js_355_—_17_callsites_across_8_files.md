## [tech-debt] deprecated/warn

| Field | Value |
|-------|-------|
| **File** | `/home/konan/pantheon/browser-extension/sidepanel/sidepanel.js` |
| **Line** | 355 |
| **Severity** | medium |
| **Detected** | 2026-07-06T11:09:00Z |
| **Author** | unknown |

### Context

17 callsites across 8 files

This batch covers **17 findings across 8 files**.

### Samples

| File | Line | Description |
|---|---:|---|
| `browser-extension/sidepanel/sidepanel.js` | 355 | use .warning() |
| `scripts/clawforge-pass3-smoke-continuation.py` | 159 | use .warning() |
| `scripts/clawforge-pass3-smoke-finalcheck.py` | 48 | use .warning() |
| `scripts/clawforge-pass3-smoke-finalcheck.py` | 60 | use .warning() |
| `scripts/clawforge-pass3-smoke-finalcheck.py` | 62 | use .warning() |
| `scripts/clawforge-pass3-smoke-finalcheck.py` | 64 | use .warning() |
| `webui/static/assets/StreamDashboard-CwQiTRCE.js` | 1 | use .warning() |
| `webui/static/assets/index-CtGWpBml.js` | 10 | use .warning() |
| `webui/static/assets/index-CtGWpBml.js` | 12 | use .warning() |
| `webui/static/assets/index-CtGWpBml.js` | 28 | use .warning() |
| `webui/static/assets/index.lazy-VkiYtsgj.js` | 1 | use .warning() |
| `webui/static/assets/index.lazy-VkiYtsgj.js` | 36 | use .warning() |

### Representative Snippet

```
354:      default:
355:        console.warn('[Pantheon] Unknown pending action type:', pending.type);
356:    }
```

### Recommendation

Replace `logging.warn()` with `logging.warning()` and keep the callsites on the supported API.

### Labels

`tech-debt`, `category:deprecated`, `severity:medium`
