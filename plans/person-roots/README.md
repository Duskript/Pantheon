# Person Roots Framework (Sanitized)

Generic Person Roots framework: resolver, ACL evaluator, guarded ingest/apply, explicit-marker observer, pending resolver, account verification helpers, and a standalone Ichor-compatible retrieval backend.

This package intentionally excludes operator-specific profiles, private relationship folders, account IDs, private names, live Athenaeum paths, and built profile data. Tests create synthetic roots in temporary directories.

Runtime roots must be supplied by `PERSON_ROOTS_ROOT` or explicit CLI `--root` arguments.

## Verification

```bash
python3 -m py_compile lib/person_roots/*.py lib/ichor/person_roots_backend.py scripts/person-roots-*.py scripts/validate-person-roots.py
python3 -m unittest tests/test_person_roots_framework.py
```
