# Person Roots Admin Dashboard Contract

## Objective

Extend the local Person Roots admin/status surface into a compact operator dashboard without building a web server or creating any new background process.

## Delivered surfaces

- `lib/person_roots/admin_status.py`
  - `build_status(root, pending_limit=20)` returns a serializable dashboard dict.
  - `render_status_text(status)` renders a compact operator summary.
- `scripts/person-roots-status.py`
  - `--format json` for machine/dashboard callers.
  - `--format text` for operator CLI use.
  - `--pending-limit N` for pending proposal previews.
- `tests/test_person_roots_admin_status.py`
  - Verifies live person counts, direct users, account-link counts, validator health, queues, blockers, text render, and CLI smoke.

## Dashboard fields

The status payload includes:

- root path;
- person count and IDs;
- direct users;
- trust tiers;
- account links;
- verified/pending account-link counts;
- queue status for `_incoming`, `_processed`, `_pending/PROPOSALS.jsonl`, `_pending/RESOLVED.jsonl`;
- pending proposal preview rows;
- validator pass/errors/warnings;
- blockers;
- next actions.

## Safety boundaries

This slice intentionally does **not**:

- open a socket;
- run a web UI;
- write relationship files;
- resolve pending account IDs;
- call Discord or any messaging platform;
- approve/ignore pending proposals.

It is a read-only local/admin surface that future Olympus/Pantheon UI code can render.

## Live text output

```text
Person Roots Admin Dashboard
============================
Root: /home/konan/athenaeum/Codex-User/relationships
People: 15 (fia, xander direct users)
Account links: 1 verified / 1 pending
Queues: 0 pending proposal(s), 0 incoming file(s), 0 processed file(s)
Validator: PASS

Blockers:
- xander has pending discord account link

Next actions:
- Provide and verify xander discord account ID.
```

## Verification evidence

```text
Ran 6 admin/status tests in 1.775s — OK
ADMIN_STATUS_CLI_SMOKE OK
Ran 101 Person Roots tests in 7.923s — OK
RESULT: PASS (15 person folder(s), 125 file(s) checked, 0 warning(s))
AST OK
git diff --check passed for touched admin files
No top-level debug print / bare except / pdb / TODO / FIXME matches in touched admin files.
```
