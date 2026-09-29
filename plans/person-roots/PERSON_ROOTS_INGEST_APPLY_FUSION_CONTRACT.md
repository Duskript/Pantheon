# Person Roots Ingest/Apply Layer — Fusion Spec Contract

## Objective

Build the first deterministic Person Roots autopopulation layer so profile information can be added as automatically/background as is safe:

- Accept **structured candidate facts** from future Discord/Hermes/Ichor scanners. Do **not** build LLM extraction in this slice.
- Resolve candidate person names through existing Person Roots aliases.
- Use existing clarification rules for unknown/common/similar names.
- Use existing proposal/source-authority rules to decide `allow`, `deny`, or `needs_konan_approval`.
- Auto-apply only `allow` decisions to existing person roots with provenance.
- Never auto-create person roots.
- Never auto-link accounts.
- Never canonize sensitive/ambiguous/non-Konan/public/god-subagent claims without approval.

Hermes is planner/reviewer. Executor implements. No commits/pushes.

## Files: exact paths to create/modify

Allowed implementation files:

- `lib/person_roots/ingest.py` — NEW deterministic candidate classification/planning layer.
- `lib/person_roots/apply.py` — NEW guarded writer for allowed profile updates.
- `scripts/person-roots-ingest.py` — NEW CLI for structured JSON/JSONL candidate input.
- `tests/test_person_roots_ingest_apply.py` — NEW unittest coverage.
- `lib/person_roots/__init__.py` — OPTIONAL only to export new public symbols.
- `lib/person_roots/schema.py` — OPTIONAL only if adding small dataclasses/constants that are truly shared.

Do not modify outside these files unless absolutely necessary for tests. If necessary, report it explicitly.

Existing files to read/anchor behavior:

- `lib/person_roots/resolver.py`
- `lib/person_roots/clarification.py`
- `lib/person_roots/proposals.py`
- `lib/person_roots/frontmatter.py`
- `lib/person_roots/hooks.py`
- `tests/test_person_roots_resolver.py`
- `tests/test_person_roots_clarification.py`
- `tests/test_person_roots_proposals.py`
- `scripts/validate-person-roots.py`

## Interfaces: function names, APIs, types, expected shapes

### `lib/person_roots/ingest.py`

Implement side-effect-free planning helpers.

Required dataclass:

```python
@dataclass(frozen=True)
class CandidateFact:
    candidate_name: str
    field: str
    value: Any
    source_person_id: str | None
    source_type: str
    sensitivity: str = "private"
    observed_context: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
```

Required functions:

```python
def candidate_from_mapping(data: Mapping[str, Any]) -> CandidateFact:
    """Parse/validate a dict into CandidateFact. Raise ValueError for missing required fields."""
```

```python
def build_ingest_plan(
    candidates: Iterable[CandidateFact | Mapping[str, Any]],
    root: str | Path = DEFAULT_ROOT,
) -> dict[str, Any]:
    """Return a serializable plan without mutating files."""
```

Expected `build_ingest_plan` return shape:

```python
{
    "applies": [
        {
            "person_id": "jesus",
            "display_name": "Jesus",
            "field": "profile.known_context",
            "value": "...",
            "source_person_id": "konan",
            "source_type": "konan_account",
            "sensitivity": "private",
            "decision": "allow",
            "reason": "...",
            "provenance": {...},
        }
    ],
    "clarifications": [
        {
            "candidate_name": "Samuel",
            "clarify_args": {"question": "...", "choices": (...), "multi_select": False},
            "reason": "...",
            "provenance": {...},
        }
    ],
    "approvals": [ ... ],
    "denied": [ ... ],
    "summary": {
        "total": 4,
        "apply": 1,
        "clarify": 1,
        "approval": 1,
        "deny": 1,
    }
}
```

Planning rules:

1. Use `build_name_clarification(candidate_name, observed_context, root)` first.
2. If `should_pause=True`, put the item in `clarifications`; do not propose/apply it.
3. If known, use resolved `person_id` and `propose_update(...)`.
4. `ALLOW` -> `applies`.
5. `NEEDS_KONAN_APPROVAL` -> `approvals`.
6. `DENY` -> `denied`.
7. Preserve `provenance` in every emitted item.

### `lib/person_roots/apply.py`

Implement guarded mutation only for `applies` from `build_ingest_plan`.

Required functions:

```python
def apply_ingest_plan(
    plan: Mapping[str, Any],
    root: str | Path = DEFAULT_ROOT,
    dry_run: bool = False,
    today: str | None = None,
) -> dict[str, Any]:
    """Apply only allowed planned updates. Return serializable results."""
```

```python
def ingest_and_apply(
    candidates: Iterable[CandidateFact | Mapping[str, Any]],
    root: str | Path = DEFAULT_ROOT,
    dry_run: bool = False,
    today: str | None = None,
) -> dict[str, Any]:
    """Convenience wrapper: build plan then apply allowed updates."""
```

Expected `apply_ingest_plan` return shape:

```python
{
    "applied": [
        {
            "person_id": "jesus",
            "field": "profile.known_context",
            "target_file": "/.../jesus/PROFILE.md",
            "value": "...",
            "dry_run": False,
        }
    ],
    "skipped": [
        {"reason": "not in applies", ...}
    ],
    "errors": [],
    "summary": {"applied": 1, "skipped": 0, "errors": 0, "dry_run": False},
}
```

Writer behavior:

- Only apply items already in `plan["applies"]`.
- Re-check that the target person folder exists through `PersonRootsRepository`/`path_for`.
- Never create a new person folder.
- Never write account links.
- Append facts as markdown bullets with provenance, preserving frontmatter.
- Append an interaction log row for each applied fact.
- Support at least these field routes:
  - `profile.*` -> append under `## Known context` in `PROFILE.md`.
  - `relationship_to_konan.*` -> append under `## What Konan has said` in `RELATIONSHIP_TO_KONAN.md`.
  - `notes.*` or `notes` -> append under an `## Auto-applied facts` section in `NOTES.md`.
- If a field route is unknown, do not write; return an error entry.
- Avoid duplicate exact bullets if the same value already exists in the target section.
- For `dry_run=True`, do not mutate files; still report target files and would-apply rows.

### `scripts/person-roots-ingest.py`

Implement deterministic CLI. No LLM extraction.

Required behavior:

```bash
python3 scripts/person-roots-ingest.py --input candidates.jsonl --root /path/to/relationships --dry-run
python3 scripts/person-roots-ingest.py --input candidates.jsonl --root /path/to/relationships --apply
```

Input may be:

- JSON list of candidate objects, or
- JSONL, one candidate object per line.

Output JSON to stdout:

```json
{
  "plan": {...},
  "apply_result": {... or null}
}
```

`--dry-run` should produce a plan and dry-run apply result.
`--apply` should apply allowed updates.
If neither is passed, produce plan only.

## Constraints: what not to touch, scope boundaries, no commits/pushes

- Do **not** edit unrelated dirty files. The repo has many existing modified/untracked files unrelated to this task.
- Do **not** commit, push, stage, reset, checkout, clean, delete, or run destructive git commands.
- Do **not** alter live Hermes config, profiles, credentials, gateways, cron jobs, Discord settings, or Ichor DB files.
- Do **not** scan live Discord or Ichor in this slice. Structured input only.
- Do **not** auto-create roots.
- Do **not** auto-link accounts.
- Do **not** write sensitive or approval-required facts.
- Do **not** use top-level `print()` in importable `.py` modules. `print()` is allowed in CLI `main()` guarded by `if __name__ == "__main__":`.
- No bare `except:`.
- Keep tests stdlib `unittest` style to match existing Person Roots tests.

## Verification: exact commands to run and expected success signal

Executor should run, from `/home/konan/pantheon`:

```bash
python3 - <<'PY'
import ast
from pathlib import Path
for path in [
    Path('lib/person_roots/ingest.py'),
    Path('lib/person_roots/apply.py'),
    Path('scripts/person-roots-ingest.py'),
    Path('tests/test_person_roots_ingest_apply.py'),
]:
    ast.parse(path.read_text(encoding='utf-8'))
print('AST OK')
PY
```

```bash
python3 -m unittest discover -s tests -p 'test_person_roots*.py'
```

Expected signal:

```text
OK
```

```bash
python3 scripts/validate-person-roots.py --root /home/konan/athenaeum/Codex-User/relationships
```

Expected signal:

```text
RESULT: PASS (15 person folder(s), 125 file(s) checked, 0 warning(s))
```

Also run a CLI smoke using a temporary fixture root, not the live root, proving `--dry-run` does not mutate and `--apply` appends a safe fact.

## Required executor return shape

Return exactly:

```text
STATUS: complete | partial | blocked | escalate
CHANGES:
- <files changed>
VERIFIED:
- <commands run + final signal>
GAPS:
- <none or explicit blockers>
NOTES:
- <1-3 lines max>
```
