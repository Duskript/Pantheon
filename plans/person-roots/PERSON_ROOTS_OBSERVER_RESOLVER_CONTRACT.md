# Person Roots Observer + Pending Resolver Contract

## Objective

Turn the live background Person Roots ingest watcher from "safe engine waiting for structured candidate files" into a practical, still-conservative pipeline:

1. A deterministic source-file observer/extractor that reads session/handoff/digest text or JSON-ish source files and writes structured `CandidateFact` JSONL to the live `_incoming/` directory.
2. A pending decision resolver that lets an operator list/resolve `_pending/PROPOSALS.jsonl` records without hand-editing the JSONL queue.

This slice must **not** add LLM extraction, live Discord scanning, Ichor writes, account linking, person-root creation, cron creation, service restarts, commits, staging, resets, or unrelated file edits.

## Allowed files

Create/modify only:

- `lib/person_roots/observer.py` — new deterministic extractor/writer.
- `lib/person_roots/pending_resolver.py` — new queue resolution helpers.
- `scripts/person-roots-observe.py` — CLI for source files/dirs → candidate JSONL in `_incoming/`.
- `scripts/person-roots-pending.py` — CLI for list/resolve pending proposals.
- `tests/test_person_roots_observer_pending_resolver.py` — tests.
- `lib/person_roots/__init__.py` — exports only.
- `plans/person-roots/PERSON_ROOTS_OBSERVER_RESOLVER_CONTRACT.md` — this contract.

Do not edit the live relationship tree during implementation or tests except in temp fixtures.

## Interfaces

### `lib.person_roots.observer`

Expose:

```python
extract_candidates_from_text(
    text: str,
    *,
    source_path: str | None = None,
    source_person_id: str = "konan",
    source_type: str = "konan_account",
    sensitivity: str = "private",
) -> list[dict]

observe_source_files(
    sources: Iterable[str | Path],
    *,
    incoming_dir: str | Path,
    source_person_id: str = "konan",
    source_type: str = "konan_account",
    sensitivity: str = "private",
    recursive: bool = False,
    today: str | None = None,
) -> dict
```

Extraction must be deterministic and conservative. It may extract only explicit operator-style lines, not arbitrary prose guessing.

Supported line patterns:

```text
PERSON_ROOT: <name> | <field> | <value>
PERSON_FACT: <name> | <field> | <value>
@person-root <name> | <field> | <value>
@person-fact <name> | <field> | <value>
```

Optional key/value line format:

```text
PERSON_ROOT candidate_name=<name> field=<field> value=<value> sensitivity=<sensitivity>
```

Requirements:

- Emit dicts accepted by `candidate_from_mapping`.
- Include provenance: `source_path`, `line_number`, `extractor: person_roots_observer`.
- Default source is Konan-authored only: `source_person_id='konan'`, `source_type='konan_account'`.
- Never resolve names, classify, apply, queue, or mutate person roots. This is extraction only.
- Ignore malformed/ambiguous lines rather than guessing.
- Deduplicate identical candidates within one extraction run.

`observe_source_files` behavior:

- Accept files or directories.
- If directory and recursive false, read direct `*.md`, `*.txt`, `*.json`, `*.jsonl` files only.
- If recursive true, recurse those suffixes.
- Write one JSONL output to `incoming_dir` only if at least one candidate was extracted.
- Filename should be unique and deterministic-ish: `person-roots-candidates-YYYY-MM-DD-<hash>.jsonl`.
- Return summary: files_seen, files_read, candidates, output_path, errors.

### `lib.person_roots.pending_resolver`

Expose:

```python
list_pending(root=DEFAULT_ROOT, limit=None) -> list[dict]
resolve_pending_records(
    actions: Iterable[dict],
    *,
    root=DEFAULT_ROOT,
    today=None,
    dry_run=False,
) -> dict
```

Action shape:

```json
{"index": 0, "action": "approve"}
{"index": 1, "action": "ignore", "note": "not useful"}
```

Allowed actions in this slice:

- `approve`: only for pending records whose wrapped `item.decision == "allow"` OR queue_reason is `approval` with a complete known-person item. It must call `apply_ingest_plan` with a single explicit-allow apply item after forcing `decision='allow'` only because the human/operator action is the explicit approval. It must never create roots or account links.
- `ignore`: mark resolved without mutation.

Unsupported actions (`alias`, `create_root`, `link_account`) must be returned as unsupported, not executed.

Queue storage:

- Preserve unresolved records in `PROPOSALS.jsonl`.
- Append resolved records to `<root>/_pending/RESOLVED.jsonl` with `resolved`, `resolution_action`, and optional note.
- Make a timestamped `.bak-YYYYMMDDHHMMSS` backup of `PROPOSALS.jsonl` before rewriting it, unless `dry_run=True`.
- Blank lines tolerated. Malformed JSON raises ValueError.
- Never drop unselected records.

### CLIs

`scripts/person-roots-observe.py`:

- Args: one or more sources; `--incoming`, `--root`, `--recursive`, `--source-person-id`, `--source-type`, `--sensitivity`, `--json`.
- Default incoming: `/home/konan/athenaeum/Codex-User/relationships/_incoming`.
- Print compact summary by default; JSON summary with `--json`.

`scripts/person-roots-pending.py`:

- Subcommands:
  - `list [--root] [--limit N] [--json]`
  - `resolve --actions ACTIONS_JSON [--root] [--dry-run] [--json]`
- Default root: `/home/konan/athenaeum/Codex-User/relationships`.
- Default text output should be compact.

## Verification

Run fresh:

```bash
python3 - <<'PY'
import ast
from pathlib import Path
for path in [
    'lib/person_roots/observer.py',
    'lib/person_roots/pending_resolver.py',
    'scripts/person-roots-observe.py',
    'scripts/person-roots-pending.py',
    'tests/test_person_roots_observer_pending_resolver.py',
    'lib/person_roots/__init__.py',
]:
    ast.parse(Path(path).read_text(encoding='utf-8'))
print('AST OK')
PY
python3 -m unittest discover -s tests -p 'test_person_roots*.py'
python3 scripts/validate-person-roots.py --root /home/konan/athenaeum/Codex-User/relationships
```

Also run temp-fixture CLI smokes proving:

- observer extracts explicit marker lines to an incoming JSONL file;
- background ingest consumes that JSONL and archives it;
- pending resolver list/ignore works on a temp queue;
- pending resolver approve applies a temp fixture fact and rewrites the queue.

## Success criteria

- No top-level `print()` in files with function definitions except under `if __name__ == "__main__"`.
- No bare `except:`.
- Existing tests remain green.
- Live relationship tree validator remains green.
- No live relationship-tree mutation during tests/smokes.
