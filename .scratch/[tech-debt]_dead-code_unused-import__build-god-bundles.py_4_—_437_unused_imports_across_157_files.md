## [tech-debt] dead-code/unused-import

| Field | Value |
|-------|-------|
| **File** | `/home/konan/pantheon/build-god-bundles.py` |
| **Line** | 4 |
| **Severity** | medium |
| **Detected** | 2026-07-06T11:09:00Z |
| **Author** | unknown |

### Context

437 unused imports across 157 files

This batch covers **437 findings across 157 files**.

### Samples

| File | Line | Description |
|---|---:|---|
| `build-god-bundles.py` | 4 | import json |
| `conductor-package/service/conductor-session-start.py` | 12 | import json |
| `conductor/conductor-poll-all.py` | 12 | from conductor_server import DEFAULT_GODS |
| `conductor/credentials/__init__.py` | 47 | from .types import Credential |
| `conductor/credentials/__init__.py` | 47 | from .types import CredentialAlreadyExistsError |
| `conductor/credentials/__init__.py` | 47 | from .types import CredentialError |
| `conductor/credentials/__init__.py` | 47 | from .types import CredentialNotFoundError |
| `conductor/credentials/__init__.py` | 47 | from .types import CredentialStoreLockedError |
| `conductor/credentials/__init__.py` | 47 | from .types import CredentialType |
| `conductor/credentials/__init__.py` | 47 | from .types import CredentialValidationError |
| `conductor/credentials/__init__.py` | 47 | from .types import RotationPolicy |
| `conductor/credentials/__tests__/conftest.py` | 22 | import json |

### Representative Snippet

```
3:
4:import json
5:import os
```

### Recommendation

Delete the unused imports or convert them to local imports only where they are intentionally side-effectful.

### Labels

`tech-debt`, `category:dead-code`, `severity:medium`
