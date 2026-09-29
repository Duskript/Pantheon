# Person Roots Account Verification Workflow Contract

## Objective

Create a repeatable, bounded workflow for promoting platform account links from pending/manual notes to verified resolver rows, using live platform proof.

## Scope

Delivered surfaces:

- `lib/person_roots/account_verification.py`
- `scripts/person-roots-verify-account.py`
- `tests/test_person_roots_account_verification.py`
- `lib/person_roots/__init__.py` exports
- Live Fia account proof refresh in:
  - `/home/konan/athenaeum/Codex-User/relationships/INDEX.md`
  - `/home/konan/athenaeum/Codex-User/relationships/fia/PERMISSIONS.md`

## Safety rules

1. Account linking proves account identity only; it does not broaden ACL access.
2. Discord verification requires a `discord_admin member_info` proof object.
3. Proof `user_id` must match supplied `account_id`.
4. Bot accounts are refused.
5. Existing verified links to another person are refused as conflicts.
6. Dry-run mode reports exact files that would change.
7. Live applies should be backed up before mutation.

## Usage

```bash
cd /home/konan/pantheon
python3 scripts/person-roots-verify-account.py \
  --person-id fia \
  --platform discord \
  --account-id 1276700977705123872 \
  --proof-json '{"user_id":"1276700977705123872","username":"sephrenia369","display_name":"Fia","bot":false}' \
  --dry-run \
  --json
```

Apply by removing `--dry-run` after backing up `INDEX.md` and the target person's `PERMISSIONS.md`.

## Live Fia proof applied

`discord_admin member_info` returned:

```json
{
  "user_id": "1276700977705123872",
  "username": "sephrenia369",
  "display_name": "Fia",
  "bot": false,
  "joined_at": "2026-07-12T04:38:24.946000+00:00"
}
```

Applied note:

```text
Live Discord guild member verified as Fia (sephrenia369) on 2026-08-07.
```

Backups:

```text
/home/konan/athenaeum/Codex-User/relationships/INDEX.md.bak-account-verify-20260807014901
/home/konan/athenaeum/Codex-User/relationships/fia/PERMISSIONS.md.bak-account-verify-20260807014901
```

## Verification evidence

```text
Ran 6 account-verification tests in 0.396s — OK
Ran resolver tests in 0.639s — OK
Ran 98 Person Roots tests in 6.501s — OK
RESULT: PASS (15 person folder(s), 125 file(s) checked, 0 warning(s))
AST OK
No top-level debug print / bare except / pdb / TODO / FIXME matches in touched files.
```

## Remaining account-link blocker

Xander still has no Discord account ID in canon. The workflow is ready, but actual Xander verification requires Konan to provide or identify his Discord snowflake first.
