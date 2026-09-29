# Person Roots Package Manifest — 2026-08-07

## Purpose

Scope the completed Person Roots autopopulation/retrieval/admin work so it can be reviewed, bundled, or committed later without dragging the wider dirty Pantheon tree into the change set.

## Git boundary

Do **not** run broad `git add .`, `git commit -a`, `git reset`, or `git clean` from this state. The repository has a large unrelated dirty tree. This manifest is the bounded file list for the Person Roots slice only.

## Included repo files (56)

- `lib/ichor/person_roots_backend.py`
- `lib/ichor_hybrid.py`
- `lib/ichor_mcp.py`
- `lib/person_roots/__init__.py`
- `lib/person_roots/account_verification.py`
- `lib/person_roots/accounts.py`
- `lib/person_roots/acl.py`
- `lib/person_roots/admin_status.py`
- `lib/person_roots/apply.py`
- `lib/person_roots/clarification.py`
- `lib/person_roots/frontmatter.py`
- `lib/person_roots/hooks.py`
- `lib/person_roots/ingest.py`
- `lib/person_roots/live_chat.py`
- `lib/person_roots/observer.py`
- `lib/person_roots/pending.py`
- `lib/person_roots/pending_resolver.py`
- `lib/person_roots/proposals.py`
- `lib/person_roots/resolver.py`
- `lib/person_roots/runtime.py`
- `lib/person_roots/schema.py`
- `plans/person-roots/PERSON_ROOTS_ACCOUNT_VERIFICATION_CONTRACT.md`
- `plans/person-roots/PERSON_ROOTS_ACTIVE_CHAT_CLARIFY_CONTRACT.md`
- `plans/person-roots/PERSON_ROOTS_ADMIN_DASHBOARD_CONTRACT.md`
- `plans/person-roots/PERSON_ROOTS_BUILD_GATES.md`
- `plans/person-roots/PERSON_ROOTS_FUSION_BUILD_PLAN.md`
- `plans/person-roots/PERSON_ROOTS_ICHOR_RETRIEVAL_CONTRACT.md`
- `plans/person-roots/PERSON_ROOTS_INGEST_APPLY_FUSION_CONTRACT.md`
- `plans/person-roots/PERSON_ROOTS_OBSERVER_RESOLVER_CONTRACT.md`
- `plans/person-roots/PERSON_ROOTS_PACKAGE_MANIFEST.md`
- `plans/person-roots/PERSON_ROOTS_PRIVACY_ACL.md`
- `plans/person-roots/PERSON_ROOTS_REST_INTEGRATION_FUSION_CONTRACT.md`
- `plans/person-roots/PERSON_ROOTS_SCHEMA.md`
- `plans/person-roots/PERSON_ROOTS_THESIS.md`
- `plans/person-roots/README.md`
- `scripts/person-roots-background-ingest.py`
- `scripts/person-roots-ingest.py`
- `scripts/person-roots-live-chat.py`
- `scripts/person-roots-observe.py`
- `scripts/person-roots-pending.py`
- `scripts/person-roots-status.py`
- `scripts/person-roots-verify-account.py`
- `scripts/validate-person-roots.py`
- `tests/test_ichor_mcp.py`
- `tests/test_ichor_person_roots_backend.py`
- `tests/test_person_roots_account_verification.py`
- `tests/test_person_roots_acl.py`
- `tests/test_person_roots_admin_status.py`
- `tests/test_person_roots_clarification.py`
- `tests/test_person_roots_hooks.py`
- `tests/test_person_roots_ingest_apply.py`
- `tests/test_person_roots_live_chat.py`
- `tests/test_person_roots_observer_pending_resolver.py`
- `tests/test_person_roots_proposals.py`
- `tests/test_person_roots_resolver.py`
- `tests/test_person_roots_runtime_pending.py`

## Package artifacts

- `artifacts/person-roots/person-roots-package-files-20260807.txt`
- `artifacts/person-roots/person-roots-package-20260807.tar.gz`

The tarball contains the included repo files plus the package file-list artifact. It does not include the live Athenaeum relationship data or Hermes skill directory.

## Live data mutations outside repo

These are intentional live Person Roots data changes and are **not** included in the repo tarball:

- `/home/konan/athenaeum/Codex-User/relationships/INDEX.md`
- `/home/konan/athenaeum/Codex-User/relationships/fia/PERMISSIONS.md`

Backups created before the Fia live account-proof refresh:

- `/home/konan/athenaeum/Codex-User/relationships/INDEX.md.bak-account-verify-20260807014901`
- `/home/konan/athenaeum/Codex-User/relationships/fia/PERMISSIONS.md.bak-account-verify-20260807014901`

## Skill docs outside repo

Updated skill references live under:

- `/home/konan/.hermes/skills/pantheon/person-roots-privacy-acl/`

They document the delivered slices but are not included in this repo tarball.

## Verification commands

```bash
cd /home/konan/pantheon
python3 -m unittest discover -s tests -p 'test_person_roots*.py'
python3 -m unittest discover -s tests -p 'test_ichor*.py'
python3 scripts/validate-person-roots.py --root /home/konan/athenaeum/Codex-User/relationships
python3 scripts/person-roots-status.py --format text --pending-limit 5
```


## Final verification evidence

```text
Ran 106 Person Roots tests in 11.822s — OK
Ran 6 Ichor Person Roots backend tests in 5.150s — OK
Ran 7 Ichor MCP tests in 2.442s — OK
RESULT: PASS (15 person folder(s), 125 file(s) checked, 0 warning(s))
Person Roots Admin Dashboard text smoke — OK
PACKAGE_HYGIENE_OK py_files=41 diff_check_rc=0
TARBALL_INTEGRITY OK members=56
```

Tarball checksum:

```text
76f00f011ed870330654733b462b02bf08f6d3de0bb80187c64e4fa87acf080a  artifacts/person-roots/person-roots-package-20260807.tar.gz
```

## Remaining known blocker

Xander still has a pending Discord account link because no Discord user ID has been supplied or discovered in canon. The verification workflow is ready once the snowflake is available.
