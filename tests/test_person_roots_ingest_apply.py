"""Person Roots ingest/apply layer tests using stdlib unittest.

Spec source:
- /home/konan/pantheon/plans/person-roots/PERSON_ROOTS_INGEST_APPLY_FUSION_CONTRACT.md

The ingest layer plans structured candidate facts without mutating files; the
apply layer is a guarded writer that only appends allow-classified facts to
existing person roots — never creating roots, never linking accounts, never
writing clarification- or approval-required facts.

Tests use a temporary fixture tree (not the live relationships root) except for
one read-only live-root planning test. The CLI is exercised via subprocess on
the fixture root.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lib.person_roots.apply import apply_ingest_plan, ingest_and_apply
from lib.person_roots.ingest import CandidateFact, build_ingest_plan, candidate_from_mapping
from lib.person_roots.schema import ALLOW, DENY, NEEDS_KONAN_APPROVAL

LIVE_ROOT = Path('/home/konan/athenaeum/Codex-User/relationships')
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


def _write_person(
    root: Path,
    person_id: str,
    display_name: str,
    aliases: list[str],
    profile_section: bool = True,
    relationship_section: bool = True,
    log_rows: str = '',
) -> None:
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
    )
    if profile_section:
        profile += '## Known context\n\n- Seed context.\n'
    (folder / 'PROFILE.md').write_text(profile, encoding='utf-8')

    for name, doc_type, sens in (
        ('PERMISSIONS.md', 'permissions', 'private'),
        ('ALIASES.md', 'aliases', 'private'),
        ('MEMORY_POLICY.md', 'memory_policy', 'private'),
    ):
        (folder / name).write_text(_minimal_fm(person_id, doc_type, sens), encoding='utf-8')

    relationship = _minimal_fm(person_id, 'relationship_to_konan', 'sensitive')
    relationship += '# Relationship to Konan\n\n'
    if relationship_section:
        relationship += '## What Konan has said\n\n- Seed statement.\n'
    (folder / 'RELATIONSHIP_TO_KONAN.md').write_text(relationship, encoding='utf-8')

    (folder / 'NOTES.md').write_text(
        _minimal_fm(person_id, 'notes', 'private') + '# Notes\n\nPrivate notes.\n',
        encoding='utf-8',
    )

    (folder / 'INTERACTION_LOG.md').write_text(
        _minimal_fm(person_id, 'interaction_log', 'private')
        + '# Interaction Log\n\n'
        + '| Date | Source | Summary | Notes |\n'
        + '|---|---|---|---|\n'
        + log_rows,
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


# ---------------------------------------------------------------------------
# candidate_from_mapping
# ---------------------------------------------------------------------------

class TestCandidateFromMapping(unittest.TestCase):
    def test_valid_mapping(self) -> None:
        fact = candidate_from_mapping({
            'candidate_name': 'Sam',
            'field': 'profile.known_context',
            'value': 'Sam is coming over.',
            'source_person_id': 'konan',
            'source_type': 'konan_account',
            'sensitivity': 'basic',
            'observed_context': 'in a DM',
            'provenance': {'session_id': 's1'},
        })
        self.assertIsInstance(fact, CandidateFact)
        self.assertEqual(fact.candidate_name, 'Sam')
        self.assertEqual(fact.field, 'profile.known_context')
        self.assertEqual(fact.value, 'Sam is coming over.')
        self.assertEqual(fact.source_person_id, 'konan')
        self.assertEqual(fact.source_type, 'konan_account')
        self.assertEqual(fact.sensitivity, 'basic')
        self.assertEqual(fact.observed_context, 'in a DM')
        self.assertEqual(fact.provenance, {'session_id': 's1'})

    def test_defaults_applied(self) -> None:
        fact = candidate_from_mapping(_konan_profile_fact())
        self.assertEqual(fact.sensitivity, 'private')
        self.assertEqual(fact.observed_context, '')
        self.assertEqual(fact.provenance, {})

    def test_missing_required_fields_raise(self) -> None:
        base = _konan_profile_fact()
        for key in ('candidate_name', 'field', 'value', 'source_person_id', 'source_type'):
            data = dict(base)
            del data[key]
            with self.subTest(missing=key):
                with self.assertRaises(ValueError):
                    candidate_from_mapping(data)

    def test_blank_name_and_field_raise(self) -> None:
        with self.assertRaises(ValueError):
            candidate_from_mapping(_konan_profile_fact(name='   '))
        with self.assertRaises(ValueError):
            candidate_from_mapping(_konan_profile_fact(field='  '))

    def test_null_source_person_id_accepted(self) -> None:
        fact = candidate_from_mapping(_konan_profile_fact(source_person_id=None))
        self.assertIsNone(fact.source_person_id)


# ---------------------------------------------------------------------------
# build_ingest_plan (fixture + live root, read-only)
# ---------------------------------------------------------------------------

class TestBuildIngestPlan(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _write_index(self.root, ['jesus', 'sammy'])
        _write_person(self.root, 'jesus', 'Jesus', ['Jesus', 'Jesus Morales'])
        _write_person(self.root, 'sammy', 'Sammy', ['Sam', 'Sammy'])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_known_alias_konan_fact_goes_to_applies(self) -> None:
        plan = build_ingest_plan([
            _konan_profile_fact(value='Sam is coming over later.', provenance={'session_id': 's1'}),
        ], root=self.root)
        self.assertEqual(plan['summary']['apply'], 1)
        item = plan['applies'][0]
        self.assertEqual(item['person_id'], 'sammy')
        self.assertEqual(item['display_name'], 'Sammy')
        self.assertEqual(item['decision'], ALLOW)
        self.assertEqual(item['provenance'], {'session_id': 's1'})

    def test_unknown_or_similar_names_go_to_clarifications(self) -> None:
        plan = build_ingest_plan([
            _konan_profile_fact(name='Samuel', value='similar'),
            _konan_profile_fact(name='Zephyr Nox', value='new'),
        ], root=self.root)
        self.assertEqual(plan['summary']['clarify'], 2)
        for entry in plan['clarifications']:
            self.assertIn('candidate_name', entry)
            self.assertIn('clarify_args', entry)
            self.assertIn('reason', entry)
        self.assertIsNotNone(plan['clarifications'][0]['clarify_args'])

    def test_god_subagent_fact_goes_to_approvals(self) -> None:
        plan = build_ingest_plan([
            {
                'candidate_name': 'Sam',
                'field': 'relationship_to_konan.category',
                'value': 'collaborator',
                'source_person_id': 'hermes',
                'source_type': 'god_subagent',
            },
        ], root=self.root)
        self.assertEqual(plan['summary']['approval'], 1)
        self.assertEqual(plan['approvals'][0]['decision'], NEEDS_KONAN_APPROVAL)
        self.assertEqual(plan['applies'], [])

    def test_public_web_private_fact_is_denied(self) -> None:
        plan = build_ingest_plan([
            {
                'candidate_name': 'Sam',
                'field': 'profile.private_context',
                'value': 'untrusted public claim',
                'source_person_id': None,
                'source_type': 'public_web_social',
            },
        ], root=self.root)
        self.assertEqual(plan['summary']['deny'], 1)
        self.assertEqual(plan['denied'][0]['decision'], DENY)
        self.assertEqual(plan['applies'], [])

    def test_summary_shape_and_serializability(self) -> None:
        candidates = [
            _konan_profile_fact(value='v1'),
            _konan_profile_fact(name='Samuel', value='v2'),
            {
                'candidate_name': 'Sam',
                'field': 'relationship_to_konan.category',
                'value': 'v3',
                'source_person_id': 'hermes',
                'source_type': 'god_subagent',
            },
            {
                'candidate_name': 'Sam',
                'field': 'profile.private_context',
                'value': 'v4',
                'source_person_id': None,
                'source_type': 'public_web_social',
            },
        ]
        plan = build_ingest_plan(candidates, root=self.root)
        self.assertEqual(
            plan['summary'],
            {'total': 4, 'apply': 1, 'clarify': 1, 'approval': 1, 'deny': 1},
        )
        json.dumps(plan, default=str)  # must be JSON-serializable

    def test_accepts_candidatefact_instances_directly(self) -> None:
        fact = CandidateFact(
            candidate_name='Sam',
            field='profile.known_context',
            value='direct',
            source_person_id='konan',
            source_type='konan_account',
        )
        plan = build_ingest_plan([fact], root=self.root)
        self.assertEqual(plan['summary']['apply'], 1)
        self.assertEqual(plan['applies'][0]['value'], 'direct')

    def test_plan_is_read_only(self) -> None:
        before = _snapshot(self.root)
        build_ingest_plan([_konan_profile_fact()], root=self.root)
        self.assertEqual(_snapshot(self.root), before)

    def test_live_root_alias_resolution_read_only(self) -> None:
        plan = build_ingest_plan([
            _konan_profile_fact(value='live root fact'),
        ], root=LIVE_ROOT)
        self.assertEqual(plan['summary']['apply'], 1)
        self.assertEqual(plan['applies'][0]['person_id'], 'sammy')
        self.assertEqual(plan['applies'][0]['display_name'], 'Sammy')


# ---------------------------------------------------------------------------
# apply_ingest_plan / ingest_and_apply
# ---------------------------------------------------------------------------

class TestApplyIngestPlan(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _write_index(self.root, ['jesus', 'sammy'])
        _write_person(self.root, 'jesus', 'Jesus', ['Jesus', 'Jesus Morales'])
        _write_person(self.root, 'sammy', 'Sammy', ['Sam', 'Sammy'])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_apply_appends_profile_bullet_and_log_row(self) -> None:
        plan = build_ingest_plan([
            _konan_profile_fact(value='Sam is coming over later.', provenance={'session_id': 's1'}),
        ], root=self.root)
        result = apply_ingest_plan(plan, root=self.root, today='2026-08-06')
        self.assertEqual(result['summary'], {'applied': 1, 'skipped': 0, 'errors': 0, 'dry_run': False})
        profile = (self.root / 'sammy' / 'PROFILE.md').read_text(encoding='utf-8')
        self.assertIn('Sam is coming over later.', profile)
        self.assertIn('source=konan_account', profile)
        self.assertIn('session_id=s1', profile)
        log = (self.root / 'sammy' / 'INTERACTION_LOG.md').read_text(encoding='utf-8')
        self.assertIn('| 2026-08-06 | konan_account | Ingested profile.known_context. | Sam is coming over later. |', log)

    def test_apply_appends_relationship_bullet(self) -> None:
        plan = build_ingest_plan([
            {
                'candidate_name': 'Sam',
                'field': 'relationship_to_konan.summary',
                'value': 'Konan considers Sammy a close collaborator.',
                'source_person_id': 'konan',
                'source_type': 'konan_account',
            },
        ], root=self.root)
        result = apply_ingest_plan(plan, root=self.root, today='2026-08-06')
        self.assertEqual(result['summary']['applied'], 1)
        text = (self.root / 'sammy' / 'RELATIONSHIP_TO_KONAN.md').read_text(encoding='utf-8')
        self.assertIn('Konan considers Sammy a close collaborator.', text)
        self.assertIn('## What Konan has said', text)

    def test_apply_appends_notes_bullet_creating_section(self) -> None:
        plan = build_ingest_plan([
            {
                'candidate_name': 'Sam',
                'field': 'notes.preferred_days',
                'value': 'Weekends',
                'source_person_id': 'konan',
                'source_type': 'konan_account',
            },
            {
                'candidate_name': 'Sam',
                'field': 'notes',
                'value': 'Bare notes route',
                'source_person_id': 'konan',
                'source_type': 'konan_account',
            },
        ], root=self.root)
        result = apply_ingest_plan(plan, root=self.root, today='2026-08-06')
        self.assertEqual(result['summary']['applied'], 2)
        text = (self.root / 'sammy' / 'NOTES.md').read_text(encoding='utf-8')
        self.assertIn('## Auto-applied facts', text)
        self.assertIn('- Weekends', text)
        self.assertIn('- Bare notes route', text)

    def test_apply_skips_exact_duplicate_bullet(self) -> None:
        candidates = [_konan_profile_fact(value='Sam likes hiking.')]
        first = ingest_and_apply(candidates, root=self.root, today='2026-08-06')
        self.assertEqual(first['apply_result']['summary']['applied'], 1)
        second = ingest_and_apply(candidates, root=self.root, today='2026-08-06')
        self.assertEqual(second['apply_result']['summary']['applied'], 0)
        self.assertEqual(second['apply_result']['summary']['skipped'], 1)
        self.assertEqual(second['apply_result']['skipped'][0]['reason'], 'duplicate bullet')

    def test_apply_unknown_route_errors_without_writing(self) -> None:
        plan = build_ingest_plan([
            {
                'candidate_name': 'Sam',
                'field': 'accounts.discord',
                'value': '123456789',
                'source_person_id': 'konan',
                'source_type': 'konan_account',
            },
        ], root=self.root)
        result = apply_ingest_plan(plan, root=self.root, today='2026-08-06')
        self.assertEqual(result['errors'][0]['reason'], 'unknown field route')
        self.assertEqual(result['summary']['applied'], 0)
        self.assertFalse((self.root / 'sammy' / 'ACCOUNTS.md').exists())

    def test_apply_skips_non_applies_buckets(self) -> None:
        plan = build_ingest_plan([
            {
                'candidate_name': 'Sam',
                'field': 'relationship_to_konan.category',
                'value': 'x',
                'source_person_id': 'hermes',
                'source_type': 'god_subagent',
            },
            _konan_profile_fact(name='Samuel', value='y'),
        ], root=self.root)
        result = apply_ingest_plan(plan, root=self.root, today='2026-08-06')
        self.assertEqual(result['summary']['applied'], 0)
        self.assertEqual(result['summary']['skipped'], 2)
        self.assertTrue(all(entry['reason'] == 'not in applies' for entry in result['skipped']))

    def test_apply_errors_when_person_folder_disappears(self) -> None:
        plan = build_ingest_plan([_konan_profile_fact()], root=self.root)
        shutil.rmtree(self.root / 'sammy')
        result = apply_ingest_plan(plan, root=self.root, today='2026-08-06')
        self.assertEqual(result['summary']['errors'], 1)
        self.assertEqual(result['errors'][0]['reason'], 'person folder no longer exists')

    def test_apply_rejects_non_allow_decision_in_applies_bucket(self) -> None:
        plan = build_ingest_plan([_konan_profile_fact()], root=self.root)
        plan['applies'][0]['decision'] = DENY  # tampered plan
        result = apply_ingest_plan(plan, root=self.root, today='2026-08-06')
        self.assertEqual(result['summary']['applied'], 0)
        self.assertEqual(result['skipped'][0]['reason'], 'decision is not allow')

    def test_apply_rejects_applies_item_with_missing_decision(self) -> None:
        plan = build_ingest_plan([_konan_profile_fact(value='no decision fact')], root=self.root)
        del plan['applies'][0]['decision']  # hand-crafted plan without explicit decision
        before = _snapshot(self.root)
        result = apply_ingest_plan(plan, root=self.root, today='2026-08-06')
        self.assertEqual(_snapshot(self.root), before)
        self.assertEqual(result['summary'], {'applied': 0, 'skipped': 1, 'errors': 0, 'dry_run': False})
        self.assertEqual(result['skipped'][0]['reason'], 'decision is not allow')
        self.assertFalse('no decision fact' in (self.root / 'sammy' / 'PROFILE.md').read_text(encoding='utf-8'))

    def test_dry_run_mutates_nothing(self) -> None:
        plan = build_ingest_plan([_konan_profile_fact(value='dry run fact')], root=self.root)
        before = _snapshot(self.root)
        result = apply_ingest_plan(plan, root=self.root, dry_run=True, today='2026-08-06')
        self.assertEqual(_snapshot(self.root), before)
        self.assertTrue(result['summary']['dry_run'])
        self.assertEqual(result['summary']['applied'], 1)
        self.assertEqual(result['applied'][0]['target_file'], str(self.root / 'sammy' / 'PROFILE.md'))
        self.assertTrue(result['applied'][0]['dry_run'])

    def test_apply_preserves_frontmatter(self) -> None:
        profile_path = self.root / 'sammy' / 'PROFILE.md'
        frontmatter_before = profile_path.read_text(encoding='utf-8').split('---', 2)[1]
        plan = build_ingest_plan([_konan_profile_fact(value='frontmatter check')], root=self.root)
        apply_ingest_plan(plan, root=self.root, today='2026-08-06')
        frontmatter_after = profile_path.read_text(encoding='utf-8').split('---', 2)[1]
        self.assertEqual(frontmatter_before, frontmatter_after)

    def test_ingest_and_apply_wrapper_shape(self) -> None:
        result = ingest_and_apply(
            [_konan_profile_fact(value='wrapper fact')],
            root=self.root,
            today='2026-08-06',
        )
        self.assertIn('plan', result)
        self.assertIn('apply_result', result)
        self.assertEqual(result['plan']['summary']['apply'], 1)
        self.assertEqual(result['apply_result']['summary']['applied'], 1)


# ---------------------------------------------------------------------------
# CLI smoke via subprocess (fixture root only)
# ---------------------------------------------------------------------------

class TestPersonRootsIngestCli(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _write_index(self.root, ['sammy'])
        _write_person(self.root, 'sammy', 'Sammy', ['Sam', 'Sammy'])
        self.input_path = self.root / 'candidates.jsonl'
        self.input_path.write_text(
            json.dumps(_konan_profile_fact(value='CLI fact', provenance={'session': 'cli-smoke'})) + '\n',
            encoding='utf-8',
        )
        self.script = REPO_ROOT / 'scripts' / 'person-roots-ingest.py'

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run_cli(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(self.script),
                '--input',
                str(self.input_path),
                '--root',
                str(self.root),
                *extra,
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )

    def test_cli_plan_only_mode(self) -> None:
        result = self._run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIsNone(payload['apply_result'])
        self.assertEqual(payload['plan']['summary']['apply'], 1)

    def test_cli_dry_run_does_not_mutate(self) -> None:
        before = _snapshot(self.root)
        result = self._run_cli('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['apply_result']['summary']['dry_run'], True)
        self.assertEqual(payload['apply_result']['summary']['applied'], 1)
        self.assertEqual(_snapshot(self.root), before)

    def test_cli_apply_appends_safe_fact(self) -> None:
        result = self._run_cli('--apply')
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['apply_result']['summary']['applied'], 1)
        profile = (self.root / 'sammy' / 'PROFILE.md').read_text(encoding='utf-8')
        self.assertIn('CLI fact', profile)
        self.assertIn('session=cli-smoke', profile)

    def test_cli_rejects_bad_json(self) -> None:
        self.input_path.write_text('{not json}\n', encoding='utf-8')
        result = self._run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertIn('error:', result.stderr)


if __name__ == '__main__':
    unittest.main()
