## [tech-debt] deprecated/utcnow

| Field | Value |
|-------|-------|
| **File** | `/home/konan/pantheon/conductor/credentials/__tests__/test_types.py` |
| **Line** | 24 |
| **Severity** | high |
| **Detected** | 2026-07-06T11:09:00Z |
| **Author** | unknown |

### Context

11 callsites across 5 files

This batch covers **11 findings across 5 files**.

### Samples

| File | Line | Description |
|---|---:|---|
| `conductor/credentials/__tests__/test_types.py` | 24 | use datetime.now(timezone.utc) |
| `conductor/credentials/__tests__/test_types.py` | 166 | use datetime.now(timezone.utc) |
| `conductor/credentials/__tests__/test_types.py` | 168 | use datetime.now(timezone.utc) |
| `conductor/credentials/__tests__/test_types.py` | 169 | use datetime.now(timezone.utc) |
| `conductor/credentials/types.py` | 33 | use datetime.now(timezone.utc) |
| `conductor/credentials/types.py` | 36 | use datetime.now(timezone.utc) |
| `lib/ichor/retrieve_fusion.py` | 123 | use datetime.now(timezone.utc) |
| `scripts/clawforge-issue-client-token.py` | 105 | use datetime.now(timezone.utc) |
| `scripts/clawforge-issue-client-token.py` | 166 | use datetime.now(timezone.utc) |
| `scripts/clawforge-issue-client-token.py` | 171 | use datetime.now(timezone.utc) |
| `webui/api/routes.py` | 6558 | use datetime.now(timezone.utc) |

### Representative Snippet

```
23:    RotationPolicy,
24:    _utcnow_iso,
25:    _parse_iso,
```

### Recommendation

Replace `datetime.utcnow()` with `datetime.now(timezone.utc)` and update any dependent formatting/tests.

### Labels

`tech-debt`, `category:deprecated`, `severity:high`
