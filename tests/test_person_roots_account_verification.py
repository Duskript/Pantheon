"""Tests for Person Roots account verification workflow.

The live Discord API proof is collected outside this module. These tests verify
that a supplied proof can safely update the resolver source of truth and the
person's permissions file, while mismatches/bots/conflicts are refused.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lib.person_roots.account_verification import verify_account_link
from lib.person_roots.accounts import resolve_account

REPO_ROOT = Path(__file__).resolve().parent.parent


def _minimal_fm(person_id: str, document_type: str, sensitivity: str) -> str:
    return (
        '---\n'
        f'person_id: {person_id}\n'
        f'document_type: {document_type}\n'
        'schema_version: 0.1\n'
        'status: draft\n'
        f'sensitivity: {sensitivity}\n'
        '---\n\n'
    )


def _write_person(root: Path, person_id: str, display_name: str) -> None:
    folder = root / person_id
    folder.mkdir(parents=True, exist_ok=True)
    profile = (
        '---\n'
        f'person_id: {person_id}\n'
        'document_type: profile\n'
        'schema_version: 0.1\n'
        'status: draft\n'
        'created: 2026-08-06\n'
        'updated: 2026-08-06\n'
        'source_authority: konan\n'
        'sensitivity: private\n'
        f'display_name: {display_name}\n'
        f'aliases:\n  - {display_name}\n'
        'direct_user: true\n'
        'trust_tier: tier_2_collaborator\n'
        '---\n'
        f'# {display_name} — Profile\n\n## Known context\n\n- Seed context.\n'
    )
    (folder / 'PROFILE.md').write_text(profile, encoding='utf-8')
    (folder / 'PERMISSIONS.md').write_text(
        _minimal_fm(person_id, 'permissions', 'private')
        + '# Permissions\n\n'
        + '## Account links\n\n'
        + '```yaml\n'
        + 'account_links:\n'
        + '  discord:\n'
        + '    user_ids: []\n'
        + '  telegram:\n'
        + '    user_ids: []\n'
        + '```\n\n'
        + 'Status: pending — no account linked yet.\n',
        encoding='utf-8',
    )
    for name, doc_type, sens in (
        ('RELATIONSHIP_TO_KONAN.md', 'relationship_to_konan', 'sensitive'),
        ('NOTES.md', 'notes', 'private'),
        ('ALIASES.md', 'aliases', 'private'),
        ('MEMORY_POLICY.md', 'memory_policy', 'private'),
        ('INTERACTION_LOG.md', 'interaction_log', 'private'),
    ):
        (folder / name).write_text(_minimal_fm(person_id, doc_type, sens), encoding='utf-8')


def _fixture() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / 'INDEX.md').write_text(
        '# Person Roots Index\n\n'
        '## Resolver Table\n\n'
        '| Person ID | Display Name | Notes |\n'
        '|---|---|---|\n'
        '| xander | Xander | |\n'
        '| fia | Fia | |\n\n'
        '## Account Links\n\n'
        '| Platform | Account ID | Person ID | Status | Verified By | Notes |\n'
        '|---|---|---|---|---|---|\n'
        '| discord | (pending — no ID) | xander | pending | konan | Planned direct user. |\n'
        '| discord | 111111111111111111 | fia | verified | konan | Existing verified link. |\n',
        encoding='utf-8',
    )
    _write_person(root, 'xander', 'Xander')
    _write_person(root, 'fia', 'Fia')
    return tmp, root


class TestAccountVerification(unittest.TestCase):
    def test_verify_discord_account_updates_index_and_permissions(self) -> None:
        tmp, root = _fixture()
        try:
            proof = {'user_id': '222222222222222222', 'username': 'xander', 'display_name': 'Xander', 'bot': False}
            result = verify_account_link(
                person_id='xander',
                platform='discord',
                account_id='222222222222222222',
                root=root,
                proof=proof,
                today='2026-08-07',
            )
            self.assertTrue(result['would_change'])
            self.assertEqual(resolve_account('discord', '222222222222222222', root), 'xander')
            index = (root / 'INDEX.md').read_text(encoding='utf-8')
            self.assertIn('| discord | 222222222222222222 | xander | verified | konan | Live Discord guild member verified as Xander (xander) on 2026-08-07. |', index)
            perms = (root / 'xander' / 'PERMISSIONS.md').read_text(encoding='utf-8')
            self.assertIn('- "222222222222222222"', perms)
            self.assertIn('Status: verified — Live Discord guild member verified as Xander (xander) on 2026-08-07.', perms)
        finally:
            tmp.cleanup()

    def test_dry_run_does_not_mutate(self) -> None:
        tmp, root = _fixture()
        try:
            before = (root / 'INDEX.md').read_text(encoding='utf-8')
            proof = {'user_id': '222222222222222222', 'username': 'xander', 'display_name': 'Xander', 'bot': False}
            result = verify_account_link(
                person_id='xander', platform='discord', account_id='222222222222222222',
                root=root, proof=proof, dry_run=True, today='2026-08-07'
            )
            self.assertTrue(result['dry_run'])
            self.assertTrue(result['would_change'])
            self.assertEqual((root / 'INDEX.md').read_text(encoding='utf-8'), before)
            self.assertIsNone(resolve_account('discord', '222222222222222222', root))
        finally:
            tmp.cleanup()

    def test_refuses_mismatched_discord_proof(self) -> None:
        tmp, root = _fixture()
        try:
            with self.assertRaises(ValueError):
                verify_account_link(
                    person_id='xander', platform='discord', account_id='222222222222222222',
                    root=root, proof={'user_id': '999999999999999999', 'bot': False}
                )
        finally:
            tmp.cleanup()

    def test_refuses_bot_accounts(self) -> None:
        tmp, root = _fixture()
        try:
            with self.assertRaises(ValueError):
                verify_account_link(
                    person_id='xander', platform='discord', account_id='222222222222222222',
                    root=root, proof={'user_id': '222222222222222222', 'bot': True}
                )
        finally:
            tmp.cleanup()

    def test_refuses_account_conflicts(self) -> None:
        tmp, root = _fixture()
        try:
            with self.assertRaises(ValueError):
                verify_account_link(
                    person_id='xander', platform='discord', account_id='111111111111111111',
                    root=root, proof={'user_id': '111111111111111111', 'bot': False}
                )
        finally:
            tmp.cleanup()

    def test_cli_dry_run_smoke(self) -> None:
        tmp, root = _fixture()
        try:
            proof = json.dumps({'user_id': '222222222222222222', 'username': 'xander', 'display_name': 'Xander', 'bot': False})
            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / 'scripts' / 'person-roots-verify-account.py'),
                    '--root', str(root),
                    '--person-id', 'xander',
                    '--platform', 'discord',
                    '--account-id', '222222222222222222',
                    '--proof-json', proof,
                    '--dry-run',
                    '--json',
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data['dry_run'])
            self.assertTrue(data['would_change'])
        finally:
            tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
