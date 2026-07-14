## [tech-debt] duplication/function

| Field | Value |
|-------|-------|
| **File** | `/home/konan/pantheon/conductor-package/server/conductor_server.py` |
| **Line** | 101 |
| **Severity** | medium |
| **Detected** | 2026-07-06T11:09:00Z |
| **Author** | unknown |

### Context

69 duplicate function fingerprints across 29 files

This batch covers **69 findings across 29 files**.

### Samples

| File | Line | Description |
|---|---:|---|
| `conductor-package/server/conductor_server.py` | 101 | _read_nats_token() duplicated across 2 files |
| `conductor-package/server/conductor_server.py` | 163 | validate() duplicated across 2 files |
| `conductor-package/server/conductor_server.py` | 190 | _load_workflow_definition() duplicated across 2 files |
| `conductor-package/server/conductor_server.py` | 199 | _next_step_from_definition() duplicated across 2 files |
| `conductor-package/server/conductor_server.py` | 282 | check_inbox() duplicated across 2 files |
| `conductor-package/server/conductor_server.py` | 289 | list_pending() duplicated across 2 files |
| `conductor-package/server/conductor_server.py` | 374 | abort_workflow() duplicated across 2 files |
| `conductor-package/server/conductor_server.py` | 406 | cleanup() duplicated across 2 files |
| `conductor-package/server/conductor_server.py` | 444 | _nats_connect() duplicated across 2 files |
| `conductor-package/server/conductor_server.py` | 494 | start_nats_listener() duplicated across 2 files |
| `conductor-package/server/conductor_server.py` | 522 | stop_nats_listener() duplicated across 2 files |
| `conductor-package/server/conductor_server.py` | 531 | _nats_subscriber() duplicated across 2 files |

### Recommendation

Consolidate the repeated function bodies into a shared helper or generated template; if the duplication is intentional, add a comment explaining the divergence.

### Labels

`tech-debt`, `category:duplication`, `severity:medium`
