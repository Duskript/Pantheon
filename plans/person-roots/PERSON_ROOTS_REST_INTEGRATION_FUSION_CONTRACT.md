# Person Roots Rest Integration — Fusion Spec Contract

## Objective

Build the remaining safe runtime surfaces around the deterministic Person Roots ingest/apply core.

The prior slice delivered:

- `lib/person_roots/ingest.py` — structured candidate planning into `applies`, `clarifications`, `approvals`, `denied`.
- `lib/person_roots/apply.py` — guarded writer that only writes explicit `decision == "allow"` items.
- `scripts/person-roots-ingest.py` — JSON/JSONL plan/dry-run/apply CLI.

This slice must make that core usable by active Hermes turns and unattended/background jobs, without adding LLM extraction or live Discord/Ichor scanning.

## Product behavior

### Active chat mode

For structured candidates observed in a live Hermes turn:

1. Build an ingest plan.
2. If there are any clarifications, return the first `clarify_args` payload plus a compact summary. The caller/Hermes can call the real `clarify` tool.
3. If there are no clarifications, apply only safe `allow` facts when requested.
4. Return approvals/denials for reporting; do not auto-write them.
5. Never create person roots or account links.

### Unattended/background mode

For structured candidate files dropped by future scanners:

1. Read JSON list or JSONL files from an incoming directory.
2. Build an ingest plan.
3. Auto-apply safe `allow` facts.
4. Append clarifications/approvals/denied/errors to a durable pending JSONL queue.
5. Archive processed input files after successful processing.
6. Emit no stdout when there is no work.
7. Emit a compact digest only when there are pending decisions or errors. Safe-only applies should be quiet by default unless explicitly requested.

This is cron-safe: cron cannot use interactive `clarify`, so it must hold questionable items instead of interrupting.

## Files: exact paths to create/modify

Allowed files:

- `lib/person_roots/runtime.py` — NEW active/background orchestration helpers.
- `lib/person_roots/pending.py` — NEW pending queue append/read helpers for `relationships/_pending/PROPOSALS.jsonl`.
- `scripts/person-roots-background-ingest.py` — NEW cron-safe unattended processor.
- `tests/test_person_roots_runtime_pending.py` — NEW unittest coverage.
- `lib/person_roots/__init__.py` — OPTIONAL public exports only.
- `plans/person-roots/PERSON_ROOTS_REST_INTEGRATION_FUSION_CONTRACT.md` — already written by Hermes planner; do not edit unless fixing typo.

Do not modify existing core files unless absolutely required by tests, and if so explain why.

Do not modify any unrelated dirty/untracked files.

## Required interfaces

### `lib/person_roots/pending.py`

Implement:

```python
def pending_path(root: str | Path = DEFAULT_ROOT) -> Path:
    """Return `<root>/_pending/PROPOSALS.jsonl`."""


def append_pending_items(
    items: Iterable[Mapping[str, Any]],
    root: str | Path = DEFAULT_ROOT,
    reason: str | None = None,
    source_file: str | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Append serialized pending entries. Create `_pending/` if needed. Return path/count."""


def read_pending_items(root: str | Path = DEFAULT_ROOT, limit: int | None = None) -> list[dict[str, Any]]:
    """Read pending JSONL entries; tolerate blank lines; raise ValueError on malformed JSON."""
```

Pending record shape must be JSON-serializable and include at least:

```json
{
  "created": "YYYY-MM-DD",
  "queue_reason": "clarification|approval|denied|error|...",
  "source_file": "optional path",
  "item": { ... original plan/apply item ... }
}
```

No top-level prints. No bare except.

### `lib/person_roots/runtime.py`

Implement:

```python
def active_ingest_step(
    candidates: Iterable[CandidateFact | Mapping[str, Any]],
    root: str | Path = DEFAULT_ROOT,
    apply_safe: bool = False,
    today: str | None = None,
) -> dict[str, Any]:
    """Plan active-chat ingestion. If clarification needed, return action='clarify' and do not apply. Otherwise optionally apply safe facts."""
```

Return shape:

- `action`: one of `clarify`, `applied`, `planned`
- `plan`: full ingest plan
- `clarify_args`: first clarification payload or `None`
- `apply_result`: result from guarded writer or `None`
- `summary`: compact counts including pending approvals/denials

Rules:

- If `plan['clarifications']` non-empty: return `action='clarify'`, first `clarify_args`, no apply.
- Else if `apply_safe=True`: call `apply_ingest_plan(plan, ...)`; return `action='applied'`.
- Else: no mutation, return `action='planned'`.

Implement:

```python
def unattended_ingest_files(
    incoming_dir: str | Path,
    root: str | Path = DEFAULT_ROOT,
    archive_dir: str | Path | None = None,
    pending_file_reason: str = "unattended_ingest",
    report_applies: bool = False,
    today: str | None = None,
) -> dict[str, Any]:
    """Cron-safe processor for JSON/JSONL candidate files."""
```

Behavior:

- If `incoming_dir` does not exist or has no `.json`/`.jsonl` files, return summary with `files_seen=0`, no errors.
- For each input file:
  - Load JSON list or JSONL candidate mappings.
  - Build ingest plan.
  - Apply safe facts via `apply_ingest_plan`.
  - Append all `clarifications`, `approvals`, `denied`, and apply `errors` to pending queue with source file provenance.
  - Archive file to `<root>/_processed/` by default or `archive_dir`, preserving a unique filename and never overwriting.
- Do not delete input unless archive copy/write succeeds; moving with `Path.replace` is okay if target unique.
- Return serializable result with files, applied counts, pending counts, errors, pending_path, archived_paths.
- Do not print from library.

Helper functions are okay if private.

### `scripts/person-roots-background-ingest.py`

Cron-safe CLI:

```bash
python3 scripts/person-roots-background-ingest.py \
  --incoming /home/konan/athenaeum/Codex-User/relationships/_incoming \
  --root /home/konan/athenaeum/Codex-User/relationships
```

Options:

- `--incoming PATH` required.
- `--root PATH` defaults to `DEFAULT_ROOT`.
- `--archive-dir PATH` optional.
- `--report-applies` optional; if absent, safe-only applies are silent.
- `--json` optional; print full JSON result even if no pending/errors.

Output rules:

- If no work and not `--json`: print nothing, exit 0.
- If safe-only applies and not `--report-applies` and not `--json`: print nothing, exit 0.
- If pending decisions/errors exist: print compact human-readable digest suitable for no-agent cron delivery.
- If `--json`: print full JSON.

Make the script importable/executable from repo root like existing `scripts/person-roots-ingest.py`.

## Tests

Create `tests/test_person_roots_runtime_pending.py` using stdlib `unittest`.

Use temporary fixture roots only. Do not mutate live relationships except read-only if absolutely needed; prefer no live root in this slice.

Required coverage:

1. `pending_path()` returns `_pending/PROPOSALS.jsonl`.
2. `append_pending_items()` creates `_pending`, appends JSONL, preserves queue reason/source_file/date.
3. `read_pending_items()` reads appended records.
4. `active_ingest_step()` returns `action='clarify'` and no apply when candidate name is ambiguous/similar (`Samuel` vs `Sammy`).
5. `active_ingest_step(apply_safe=True)` applies safe Konan-authored fact when no clarification needed.
6. `active_ingest_step(apply_safe=False)` plans without mutation.
7. `unattended_ingest_files()` with no incoming dir returns no-work summary and no error.
8. `unattended_ingest_files()` applies safe facts, archives source file, and does not create pending entries for safe-only apply.
9. `unattended_ingest_files()` sends ambiguous/sensitive/god/public items to pending and archives source file.
10. CLI no-work mode prints nothing and exits 0.
11. CLI pending digest prints a compact "Person Roots needs decisions" message.
12. CLI `--json` prints parseable JSON.

## Constraints

- No LLM extraction.
- No live Discord/Hermes session scan.
- No live Ichor retrieval/write.
- No cron job creation in code. Hermes reviewer may schedule later after verifying.
- No person-root creation.
- No account linking.
- No commits/staging/pushes/resets/clean/checkouts.
- No edits to unrelated dirty files.
- No top-level `print()` in importable modules.
- No bare `except:`.
- Use explicit exception types.

## Verification commands

Run from `/home/konan/pantheon`:

```bash
python3 -c "import ast; from pathlib import Path; paths=[Path('lib/person_roots/runtime.py'),Path('lib/person_roots/pending.py'),Path('scripts/person-roots-background-ingest.py'),Path('tests/test_person_roots_runtime_pending.py'),Path('lib/person_roots/__init__.py')]; [ast.parse(p.read_text(encoding='utf-8')) for p in paths]; print('AST OK')"
python3 -m unittest discover -s tests -p 'test_person_roots*.py'
python3 scripts/validate-person-roots.py --root /home/konan/athenaeum/Codex-User/relationships
python3 scripts/person-roots-background-ingest.py --incoming /tmp/nonexistent-person-roots-incoming --root /home/konan/athenaeum/Codex-User/relationships --json
```

Also run a temp-fixture CLI smoke proving:

- no-work prints nothing without `--json`;
- pending digest prints only when decision items exist;
- safe-only apply is quiet by default and mutates only the temp fixture root.

## Required return shape

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
