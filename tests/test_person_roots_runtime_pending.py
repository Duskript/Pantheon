"""Person Roots runtime/pending integration tests using stdlib unittest.

Spec source:
- /home/konan/pantheon/plans/person-roots/PERSON_ROOTS_REST_INTEGRATION_FUSION_CONTRACT.md

Covers the active-chat surface (``active_ingest_step``), the cron-safe
unattended surface (``unattended_ingest_files``), the durable pending queue
(``lib.person_roots.pending``), and the background CLI. Tests use temporary
fixture roots only — no live relationships root is mutated.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lib.person_roots.pending import append_pending_items, pending_path, read_pending_items
from lib.person_roots.runtime import active_ingest_step, unattended_ingest_files

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixture helpers (temporary Person Roots tree)
# ---------------------------------------------------------------------------

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

    for name, doc_type, sens in (
        ('PERMISSIONS.md', 'permissions', 'private'),
        ('ALIASES.md', 'aliases', 'private'),
        ('MEMORY_POLICY.md', 'memory_policy', 'private'),
    ):
        (folder / name).write_text(_minimal_fm(person_id, doc_type, sens), encoding='utf-8')

    relationship = _minimal_fm(person_id, 'relationship_to_konan', 'sensitive')
    relationship += '# Relationship to Konan\n\n## What Konan has said\n\n- Seed statement.\n'
    (folder / 'RELATIONSHIP_TO_KONAN.md').write_text(relationship, encoding='utf-8')

    (folder / 'NOTES.md').write_text(
        _minimal_fm(person_id, 'notes', 'private') + '# Notes\n\nPrivate notes.\n',
        encoding='utf-8',
    )

    (folder / 'INTERACTION_LOG.md').write_text(
        _minimal_fm(person_id, 'interaction_log', 'private')
        + '# Interaction Log\n\n'
        + '| Date | Source | Summary | Notes |\n'
        + '|---|---|---|---|\n',
        encoding='utf-8',
    )


def _konan_profile_fact(name: str = 'Sam', field: str = 'profile.known_context', value: str = 'x', **extra) -> dict:
    fact: dict = {
        'candidate_name': name,
        'field': field,
        'value': value,
        'source_person_id': 'konan',
        'source_type': 'konan_account',
    }
    fact.update(extra)
    return fact


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(path): path.read_text(encoding='utf-8')
        for path in sorted(root.rglob('*.md'))
    }


def _make_fixture() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    _write_index(root, ['jesus', 'sammy'])
    _write_person(root, 'jesus', 'Jesus', ['Jesus', 'Jesus Morales'])
    _write_person(root, 'sammy', 'Sammy', ['Sam', 'Sammy'])
    return tmp, root


# ---------------------------------------------------------------------------
# pending_path / append / read
# ---------------------------------------------------------------------------

class TestPendingQueue(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp, self.root = _make_fixture()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_pending_path_shape(self) -> None:
        path = pending_path(self.root)
        self.assertEqual(path.name, 'PROPOSALS.jsonl')
        self.assertEqual(path.parent.name, '_pending')
        self.assertEqual(path.parent.parent, self.root)

    def test_append_creates_queue_and_preserves_fields(self) -> None:
        items = [
            {'person_id': 'sammy', 'field': 'profile.x', 'decision': 'allow'},
            {'candidate_name': 'Samuel', 'reason': 'ambiguous'},
        ]
        result = append_pending_items(
            items, root=self.root, reason='approval', source_file='candidates.jsonl', today='2026-08-06'
        )
        path = pending_path(self.root)
        self.assertEqual(result['path'], str(path))
        self.assertEqual(result['count'], 2)
        self.assertTrue(path.exists())
        lines = path.read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(first['created'], '2026-08-06')
        self.assertEqual(first['queue_reason'], 'approval')
        self.assertEqual(first['source_file'], 'candidates.jsonl')
        self.assertEqual(first['item'], items[0])

    def test_append_empty_items_creates_nothing(self) -> None:
        result = append_pending_items([], root=self.root, reason='approval')
        self.assertEqual(result['count'], 0)
        self.assertFalse(pending_path(self.root).exists())

    def test_append_default_reason(self) -> None:
        append_pending_items([{'person_id': 'sammy'}], root=self.root, today='2026-08-06')
        record = read_pending_items(self.root)[0]
        self.assertEqual(record['queue_reason'], 'pending')
        self.assertIsNone(record['source_file'])

    def test_read_tolerates_blank_lines_and_honors_limit(self) -> None:
        append_pending_items(
            [{'person_id': 'a'}, {'person_id': 'b'}, {'person_id': 'c'}],
            root=self.root,
            reason='denied',
            today='2026-08-06',
        )
        with open(pending_path(self.root), 'a', encoding='utf-8') as handle:
            handle.write('\n\n')
        self.assertEqual(len(read_pending_items(self.root)), 3)
        limited = read_pending_items(self.root, limit=2)
        self.assertEqual([record['item']['person_id'] for record in limited], ['a', 'b'])
        self.assertEqual(read_pending_items(self.root / 'missing'), [])

    def test_read_raises_value_error_on_malformed_json(self) -> None:
        append_pending_items([{'person_id': 'a'}], root=self.root, reason='error')
        with open(pending_path(self.root), 'a', encoding='utf-8') as handle:
            handle.write('{not json}\n')
        with self.assertRaises(ValueError):
            read_pending_items(self.root)


# ---------------------------------------------------------------------------
# active_ingest_step
# ---------------------------------------------------------------------------

class TestActiveIngestStep(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp, self.root = _make_fixture()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_ambiguous_name_returns_clarify_without_apply(self) -> None:
        result = active_ingest_step(
            [_konan_profile_fact(name='Samuel', value='similar')], root=self.root
        )
        self.assertEqual(result['action'], 'clarify')
        self.assertIsNotNone(result['clarify_args'])
        self.assertIsNone(result['apply_result'])
        self.assertEqual(result['summary']['clarify'], 1)
        self.assertNotIn('similar', (self.root / 'sammy' / 'PROFILE.md').read_text(encoding='utf-8'))

    def test_apply_safe_applies_konan_fact(self) -> None:
        result = active_ingest_step(
            [_konan_profile_fact(value='Sam is coming over later.')],
            root=self.root,
            apply_safe=True,
            today='2026-08-06',
        )
        self.assertEqual(result['action'], 'applied')
        self.assertIsNone(result['clarify_args'])
        self.assertIsNotNone(result['apply_result'])
        self.assertEqual(result['apply_result']['summary']['applied'], 1)
        self.assertEqual(result['summary']['applied'], 1)
        self.assertIn('Sam is coming over later.', (self.root / 'sammy' / 'PROFILE.md').read_text(encoding='utf-8'))

    def test_planned_without_mutation(self) -> None:
        before = _snapshot(self.root)
        result = active_ingest_step(
            [_konan_profile_fact(value='no mutation fact')], root=self.root, apply_safe=False
        )
        self.assertEqual(result['action'], 'planned')
        self.assertIsNone(result['clarify_args'])
        self.assertIsNone(result['apply_result'])
        self.assertEqual(result['summary']['applied'], 0)
        self.assertEqual(_snapshot(self.root), before)


# ---------------------------------------------------------------------------
# unattended_ingest_files
# ---------------------------------------------------------------------------

class TestUnattendedIngestFiles(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp, self.root = _make_fixture()
        self.incoming = self.root / '_incoming'
        self.incoming.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_incoming_dir_is_no_work(self) -> None:
        result = unattended_ingest_files(self.root / 'does-not-exist', root=self.root)
        self.assertEqual(result['files_seen'], 0)
        self.assertEqual(result['files_processed'], 0)
        self.assertEqual(result['pending_count'], 0)
        self.assertEqual(result['applied_count'], 0)
        self.assertEqual(result['errors'], [])
        self.assertIsNone(result['pending_path'])

    def test_empty_incoming_dir_is_no_work(self) -> None:
        result = unattended_ingest_files(self.incoming, root=self.root)
        self.assertEqual(result['files_seen'], 0)
        self.assertEqual(result['errors'], [])

    def test_safe_only_apply_is_quiet_and_archives(self) -> None:
        source = self.incoming / 'candidates.jsonl'
        source.write_text(
            json.dumps(_konan_profile_fact(value='Unattended safe fact', provenance={'job': 't8'})) + '\n',
            encoding='utf-8',
        )
        result = unattended_ingest_files(self.incoming, root=self.root, today='2026-08-06')
        self.assertEqual(result['files_seen'], 1)
        self.assertEqual(result['files_processed'], 1)
        self.assertEqual(result['files_failed'], 0)
        self.assertEqual(result['applied_count'], 1)
        self.assertEqual(result['pending_count'], 0)
        self.assertEqual(result['errors'], [])
        self.assertFalse(pending_path(self.root).exists())
        self.assertFalse(source.exists())
        archived = self.root / '_processed' / 'candidates.jsonl'
        self.assertTrue(archived.exists())
        self.assertEqual(result['archived_paths'], [str(archived)])
        self.assertIn('Unattended safe fact', (self.root / 'sammy' / 'PROFILE.md').read_text(encoding='utf-8'))

    def test_decision_items_go_to_pending_and_archive(self) -> None:
        source = self.incoming / 'candidates.jsonl'
        facts = [
            _konan_profile_fact(name='Samuel', value='ambiguous'),
            {
                'candidate_name': 'Sam',
                'field': 'relationship_to_konan.category',
                'value': 'collaborator',
                'source_person_id': 'hermes',
                'source_type': 'god_subagent',
            },
            {
                'candidate_name': 'Sam',
                'field': 'profile.private_context',
                'value': 'untrusted public claim',
                'source_person_id': None,
                'source_type': 'public_web_social',
            },
        ]
        source.write_text(
            '\n'.join(json.dumps(fact) for fact in facts) + '\n',
            encoding='utf-8',
        )
        result = unattended_ingest_files(self.incoming, root=self.root, today='2026-08-06')
        self.assertEqual(result['files_seen'], 1)
        self.assertEqual(result['files_processed'], 1)
        self.assertEqual(result['applied_count'], 0)
        self.assertEqual(result['pending_count'], 3)
        self.assertEqual(
            result['pending_breakdown'],
            {'clarification': 1, 'approval': 1, 'denied': 1, 'error': 0},
        )
        self.assertEqual(result['pending_path'], str(pending_path(self.root)))
        records = read_pending_items(self.root)
        self.assertEqual(len(records), 3)
        self.assertEqual({record['queue_reason'] for record in records}, {'clarification', 'approval', 'denied'})
        for record in records:
            self.assertEqual(record['created'], '2026-08-06')
            self.assertEqual(record['source_file'], str(source))
            self.assertIn('item', record)
        self.assertFalse(source.exists())
        self.assertTrue((self.root / '_processed' / 'candidates.jsonl').exists())

    def test_archive_never_overwrites(self) -> None:
        (self.root / '_processed').mkdir()
        first = self.root / '_processed' / 'candidates.jsonl'
        first.write_text('stale', encoding='utf-8')
        source = self.incoming / 'candidates.jsonl'
        source.write_text(json.dumps(_konan_profile_fact(value='archive unique')) + '\n', encoding='utf-8')
        result = unattended_ingest_files(self.incoming, root=self.root, today='2026-08-06')
        self.assertEqual(first.read_text(encoding='utf-8'), 'stale')
        self.assertTrue((self.root / '_processed' / 'candidates-1.jsonl').exists())
        self.assertEqual(len(result['archived_paths']), 1)

    def test_bad_file_is_recorded_and_kept_in_incoming(self) -> None:
        source = self.incoming / 'broken.jsonl'
        source.write_text('{not json}\n', encoding='utf-8')
        result = unattended_ingest_files(self.incoming, root=self.root, today='2026-08-06')
        self.assertEqual(result['files_seen'], 1)
        self.assertEqual(result['files_failed'], 1)
        self.assertEqual(result['files_processed'], 0)
        self.assertEqual(len(result['errors']), 1)
        self.assertIn('broken.jsonl', result['errors'][0])
        self.assertTrue(source.exists())  # never deleted on failure


# ---------------------------------------------------------------------------
# Background CLI via subprocess (fixture root only)
# ---------------------------------------------------------------------------

class TestBackgroundIngestCli(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp, self.root = _make_fixture()
        self.incoming = self.root / '_incoming'
        self.incoming.mkdir()
        self.script = REPO_ROOT / 'scripts' / 'person-roots-background-ingest.py'

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_cli(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(self.script),
                '--incoming',
                str(self.incoming),
                '--root',
                str(self.root),
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_no_work_prints_nothing_and_exits_zero(self) -> None:
        proc = self._run_cli()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, '')
        self.assertEqual(proc.stderr, '')

    def test_pending_digest_prints_decisions_message(self) -> None:
        (self.incoming / 'c.jsonl').write_text(
            json.dumps(_konan_profile_fact(name='Samuel', value='ambiguous')) + '\n',
            encoding='utf-8',
        )
        proc = self._run_cli()
        self.assertEqual(proc.returncode, 0)
        self.assertIn('Person Roots needs decisions', proc.stdout)
        self.assertIn('Pending queue', proc.stdout)
        self.assertNotIn('Traceback', proc.stderr)

    def test_json_mode_prints_parseable_json(self) -> None:
        proc = self._run_cli('--json')
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertEqual(data['files_seen'], 0)
        self.assertEqual(data['errors'], [])

    def test_safe_only_apply_is_quiet_without_report(self) -> None:
        (self.incoming / 'c.jsonl').write_text(
            json.dumps(_konan_profile_fact(value='CLI quiet safe fact')) + '\n',
            encoding='utf-8',
        )
        proc = self._run_cli()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, '')
        self.assertIn('CLI quiet safe fact', (self.root / 'sammy' / 'PROFILE.md').read_text(encoding='utf-8'))

    def test_report_applies_prints_applied_digest(self) -> None:
        (self.incoming / 'c.jsonl').write_text(
            json.dumps(_konan_profile_fact(value='CLI reported fact')) + '\n',
            encoding='utf-8',
        )
        proc = self._run_cli('--report-applies')
        self.assertEqual(proc.returncode, 0)
        self.assertIn('applied 1 safe fact', proc.stdout)


if __name__ == '__main__':
    unittest.main()
