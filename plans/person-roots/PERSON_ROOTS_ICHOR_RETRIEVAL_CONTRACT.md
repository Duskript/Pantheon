# Person Roots Ichor Retrieval Integration Contract

## Objective

Expose Person Roots through Ichor as an ACL-gated retrieval backend while keeping legacy Ichor callers unchanged.

## Scope

Allowed implementation surfaces:

- `lib/ichor/person_roots_backend.py`
- `lib/ichor_hybrid.py`
- `lib/ichor_mcp.py`
- `tests/test_ichor_person_roots_backend.py`
- `tests/test_ichor_mcp.py`

## Required behavior

1. `PersonRootsBackend` resolves explicit `target_person` or query aliases using the Person Roots repository.
2. It evaluates ACL via `build_context_decision(...)` before reading any markdown file.
3. Allowed requests return only files selected by the ACL hook.
4. Denied or approval-required requests return redacted decision rows, not private snippets.
5. Legacy `MemoryTrait().retrieve(query, limit)` must not auto-read Person Roots.
6. Supplying person-context intent auto-joins the `person_roots` backend.
7. MCP `ichor_retrieve(...)` passes the person-context parameters through.
8. `WEIGHTS` remains unchanged; `person_roots` uses `_EXTRA_BACKEND_WEIGHTS` only.
9. Audit rows must remain valid JSON even when a tool result exceeds the compact audit payload budget.

## Verification commands

```bash
cd /home/konan/pantheon
python3 -m unittest discover -s tests -p 'test_ichor*.py'
python3 -m unittest discover -s tests -p 'test_person_roots*.py'
python3 scripts/validate-person-roots.py --root /home/konan/athenaeum/Codex-User/relationships
python3 - <<'PY'
from lib.ichor_hybrid import MemoryTrait
legacy = MemoryTrait().retrieve('Xander code roast', limit=5)
ctx = MemoryTrait().retrieve(
    'Xander code roast',
    limit=5,
    requesting_person_id='xander',
    target_person='xander',
    person_context_domain='code_submitted_by_xander',
    person_fact_type='private',
    person_purpose='code_roast_and_learning',
    active_god='marvin',
)
roots = [r for r in ctx.get('results', []) if r.get('backend') == 'person_roots']
assert 'person_roots' not in legacy.get('backends_used', [])
assert roots and roots[0].get('access_decision') == 'allow'
print('ICHOR_PERSON_ROOTS_FINAL_SMOKE OK legacy_default_no_join=True contextual_join=True access=allow')
PY
```

## Delivered verification evidence

```text
Ran 383 tests in 117.762s
OK (skipped=1)
Ran 92 tests in 6.221s
OK
RESULT: PASS (15 person folder(s), 125 file(s) checked, 0 warning(s))
AST OK
ICHOR_PERSON_ROOTS_FINAL_SMOKE OK legacy_default_no_join=True contextual_join=True access=allow
```

## Safety notes

- No live DB data backfill is part of this slice.
- No root creation, account linking, or profile mutation is part of retrieval.
- `person_roots` is optional and can be disabled with `ICHOR_PERSON_ROOTS_ENABLED=false`.
- The full Ichor test run exposed an order/payload bug in MCP audit logging: truncated audit JSON could become unparsable. The fix stores a valid compact JSON summary when audit payloads are too large.
