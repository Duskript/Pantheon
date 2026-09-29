"""Tests for Person Roots explicit observer and pending resolver.

These tests use temporary Person Roots fixtures only. They verify the next
pipeline slice after the background watcher:

- explicit marker source files produce CandidateFact JSONL in `_incoming`;
- the existing unattended watcher can consume that output;
- pending records can be listed, ignored, dry-run approved, and approved;
- unsupported future actions stay unresolved.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lib.person_roots.observer import extract_candidates_from_text, observe_source_files
from lib.person_roots.pending import append_pending_items, pending_path, read_pending_items
from lib.person_roots.pending_resolver import list_pending, resolve_pending_records
from lib.person_roots.runtime import unattended_ingest_files

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


def _write_index(root: Path, people: list[str]) -> None:
    rows = '\n'.join(f'| {person_id} | {person_id} | |' for person_id in people)
    (root / 'INDEX.md').write_text(
        '# Person Roots Index\n\n'
        '## Resolver Table\n\n'
        '| Person ID | Display Name | Notes |\n'
        '|---|---|---|\n'
        f'{rows}\n',
        encoding='utf-8',
    )


def _write_person(root: Path, person_id: str, display_name: str, aliases: list[str]) -> None:
    folder = root / person_id
    folder.mkdir(parents=True, exist_ok=True)
    aliases_block = ''.join(f'  - {alias}\n' for alias in aliases)
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
        f'aliases:\n{aliases_block}'
        'direct_user: false\n'
        'trust_tier: tier_1_recognized\n'
        '---\n'
        f'# {display_name} — Profile\n\n'
        '## Known context\n\n'
        '- Seed context.\n'
    )
    (folder / 'PROFILE.md').write_text(profile, encoding='utf-8')
    (folder / 'RELATIONSHIP_TO_KONAN.md').write_text(
        _minimal_fm(person_id, 'relationship_to_konan', 'sensitive')
        + '# Relationship to Konan\n\n## What Konan has said\n\n- Seed statement.\n',
        encoding='utf-8',
    )
    (folder / 'NOTES.md').write_text(
        _minimal_fm(person_id, 'notes', 'private') + '# Notes\n\nPrivate notes.\n',
        encoding='utf-8',
    )
    (folder / 'INTERACTION_LOG.md').write_text(
        _minimal_fm(person_id, 'interaction_log', 'private')
        + '# Interaction Log\n\n| Date | Source | Summary | Notes |\n|---|---|---|---|\n',
        encoding='utf-8',
    )
    for name, doc_type, sens in (
        ('PERMISSIONS.md', 'permissions', 'private'),
        ('ALIASES.md', 'aliases', 'private'),
        ('MEMORY_POLICY.md', 'memory_policy', 'private'),
    ):
        (folder / name).write_text(_minimal_fm(person_id, doc_type, sens), encoding='utf-8')


def _make_fixture() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    _write_index(root, ['sammy', 'jesus'])
    _write_person(root, 'sammy', 'Sammy', ['Sam', 'Sammy'])
    _write_person(root, 'jesus', 'Jesus', ['Jesus', 'Jesus Morales'])
    return tmp, root


class TestObserver(unittest.TestCase):
    def test_extracts_only_explicit_markers(self) -> None:
        text = '''
This free prose about Sam should not be extracted.
PERSON_ROOT: Sam | profile.known_context | Sam is coming over later.
PERSON_FACT: Jesus Morales | notes.work | Jesus retires in Dec 2026.
@person-fact Sam | profile.known_context | Duplicate-ish but different marker.
PERSON_ROOT candidate_name="Sam" field="notes.misc" value="Quoted value works" sensitivity=basic
PERSON_ROOT malformed no separators
'''
        candidates = extract_candidates_from_text(text, source_path='session.md')
        self.assertEqual(len(candidates), 4)
        self.assertEqual(candidates[0]['candidate_name'], 'Sam')
        self.assertEqual(candidates[0]['field'], 'profile.known_context')
        self.assertEqual(candidates[0]['source_person_id'], 'konan')
        self.assertEqual(candidates[0]['source_type'], 'konan_account')
        self.assertEqual(candidates[0]['provenance']['source_path'], 'session.md')
        self.assertEqual(candidates[0]['provenance']['line_number'], 3)
        self.assertEqual(candidates[0]['provenance']['extractor'], 'person_roots_observer')
        self.assertEqual(candidates[-1]['sensitivity'], 'basic')

    def test_observe_source_files_writes_jsonl_only_when_candidates_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.md'
            source.write_text('PERSON_ROOT: Sam | profile.known_context | from observer\n', encoding='utf-8')
            incoming = root / 'incoming'
            result = observe_source_files([source], incoming_dir=incoming, today='2026-08-06')
            self.assertEqual(result['files_seen'], 1)
            self.assertEqual(result['files_read'], 1)
            self.assertEqual(result['candidates'], 1)
            output = Path(result['output_path'])
            self.assertTrue(output.exists())
            self.assertEqual(output.parent, incoming)
            rows = [json.loads(line) for line in output.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(rows[0]['value'], 'from observer')

    def test_observer_output_feeds_background_ingest(self) -> None:
        tmp, root = _make_fixture()
        try:
            source = root / 'source.md'
            source.write_text('PERSON_ROOT: Sam | profile.known_context | observer safe fact\n', encoding='utf-8')
            incoming = root / '_incoming'
            observe_result = observe_source_files([source], incoming_dir=incoming, today='2026-08-06')
            self.assertEqual(observe_result['candidates'], 1)
            ingest_result = unattended_ingest_files(incoming, root=root, today='2026-08-06')
            self.assertEqual(ingest_result['applied_count'], 1)
            self.assertIn('observer safe fact', (root / 'sammy' / 'PROFILE.md').read_text(encoding='utf-8'))
        finally:
            tmp.cleanup()


class TestPendingResolver(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp, self.root = _make_fixture()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _approval_item(self, value: str = 'approved fact') -> dict:
        return {
            'person_id': 'sammy',
            'display_name': 'Sammy',
            'field': 'profile.known_context',
            'value': value,
            'source_person_id': 'konan',
            'source_type': 'konan_account',
            'sensitivity': 'private',
            'decision': 'needs_konan_approval',
            'reason': 'operator review required',
            'provenance': {'test': 'pending_resolver'},
        }

    def test_list_pending_adds_indices(self) -> None:
        append_pending_items([self._approval_item(), {'candidate_name': 'Samuel'}], root=self.root, reason='approval')
        records = list_pending(self.root)
        self.assertEqual([record['index'] for record in records], [0, 1])
        self.assertEqual(records[0]['queue_reason'], 'approval')

    def test_ignore_rewrites_queue_and_logs_resolved_with_backup(self) -> None:
        append_pending_items([self._approval_item('ignored'), {'candidate_name': 'Samuel'}], root=self.root, reason='approval', today='2026-08-06')
        result = resolve_pending_records([{'index': 0, 'action': 'ignore', 'note': 'not useful'}], root=self.root, today='2026-08-06')
        self.assertEqual(result['resolved_count'], 1)
        self.assertEqual(result['records_after'], 1)
        self.assertIsNotNone(result['backup_path'])
        self.assertTrue(Path(result['backup_path']).exists())
        self.assertEqual(len(read_pending_items(self.root)), 1)
        resolved_path = self.root / '_pending' / 'RESOLVED.jsonl'
        self.assertTrue(resolved_path.exists())
        resolved = json.loads(resolved_path.read_text(encoding='utf-8').splitlines()[0])
        self.assertEqual(resolved['resolution_action'], 'ignore')
        self.assertEqual(resolved['resolution_note'], 'not useful')

    def test_dry_run_approve_does_not_mutate_or_rewrite(self) -> None:
        append_pending_items([self._approval_item('dry approved')], root=self.root, reason='approval', today='2026-08-06')
        before_queue = pending_path(self.root).read_text(encoding='utf-8')
        before_profile = (self.root / 'sammy' / 'PROFILE.md').read_text(encoding='utf-8')
        result = resolve_pending_records([{'index': 0, 'action': 'approve'}], root=self.root, today='2026-08-06', dry_run=True)
        self.assertTrue(result['dry_run'])
        self.assertEqual(result['resolved_count'], 1)
        self.assertEqual(result['records_after'], 1)
        self.assertIsNone(result['backup_path'])
        self.assertEqual(pending_path(self.root).read_text(encoding='utf-8'), before_queue)
        self.assertEqual((self.root / 'sammy' / 'PROFILE.md').read_text(encoding='utf-8'), before_profile)

    def test_approve_applies_fact_and_removes_record(self) -> None:
        append_pending_items([self._approval_item('approved from pending')], root=self.root, reason='approval', today='2026-08-06')
        result = resolve_pending_records([{'index': 0, 'action': 'approve'}], root=self.root, today='2026-08-06')
        self.assertEqual(result['failed_count'], 0)
        self.assertEqual(result['applied_count'], 1)
        self.assertEqual(result['records_after'], 0)
        self.assertEqual(read_pending_items(self.root), [])
        self.assertIn('approved from pending', (self.root / 'sammy' / 'PROFILE.md').read_text(encoding='utf-8'))
        self.assertTrue((self.root / '_pending' / 'RESOLVED.jsonl').exists())

    def test_unsupported_actions_remain_unresolved(self) -> None:
        append_pending_items([self._approval_item('alias me')], root=self.root, reason='approval')
        result = resolve_pending_records([{'index': 0, 'action': 'alias'}], root=self.root)
        self.assertEqual(result['failed_count'], 1)
        self.assertEqual(result['records_after'], 1)
        self.assertEqual(len(read_pending_items(self.root)), 1)
        self.assertEqual(result['failed'][0]['reason'], 'unsupported action in this slice')


class TestObserverAndPendingCli(unittest.TestCase):
    def test_observer_cli_json_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.md'
            source.write_text('PERSON_ROOT: Sam | profile.known_context | cli fact\n', encoding='utf-8')
            incoming = root / '_incoming'
            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / 'scripts' / 'person-roots-observe.py'),
                    str(source),
                    '--incoming',
                    str(incoming),
                    '--json',
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data['candidates'], 1)
            self.assertTrue(Path(data['output_path']).exists())

    def test_pending_cli_list_and_ignore_smoke(self) -> None:
        tmp, root = _make_fixture()
        try:
            append_pending_items([
                {
                    'person_id': 'sammy',
                    'field': 'profile.known_context',
                    'value': 'cli ignored',
                    'source_person_id': 'konan',
                    'source_type': 'konan_account',
                    'decision': 'needs_konan_approval',
                }
            ], root=root, reason='approval')
            list_proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / 'scripts' / 'person-roots-pending.py'), 'list', '--root', str(root), '--json'],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(list_proc.returncode, 0, list_proc.stderr)
            self.assertEqual(json.loads(list_proc.stdout)[0]['index'], 0)
            resolve_proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / 'scripts' / 'person-roots-pending.py'),
                    'resolve',
                    '--root',
                    str(root),
                    '--actions',
                    '[{"index": 0, "action": "ignore"}]',
                    '--json',
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(resolve_proc.returncode, 0, resolve_proc.stderr)
            result = json.loads(resolve_proc.stdout)
            self.assertEqual(result['resolved_count'], 1)
            self.assertEqual(read_pending_items(root), [])
        finally:
            tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
