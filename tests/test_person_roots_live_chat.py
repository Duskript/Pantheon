"""Tests for Person Roots active-chat wrapper.

The active chat path is deliberately different from the unattended watcher:
unknown/similar names return clarify tool args immediately, safe Konan-authored
facts may apply through the guarded writer, and approval/deny items are never
written to `_pending/PROPOSALS.jsonl` during a live turn.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lib.person_roots.live_chat import handle_live_chat_candidates, load_candidate_stream, render_live_chat_result
from lib.person_roots.pending import pending_path

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


def _write_index(root: Path) -> None:
    (root / 'INDEX.md').write_text(
        '# Person Roots Index\n\n'
        '## Resolver Table\n\n'
        '| Person ID | Display Name | Notes |\n'
        '|---|---|---|\n'
        '| sammy | Sammy | |\n'
        '| jesus | Jesus | |\n',
        encoding='utf-8',
    )


def _write_person(root: Path, person_id: str, display_name: str, aliases: list[str]) -> None:
    folder = root / person_id
    folder.mkdir(parents=True, exist_ok=True)
    aliases_block = ''.join(f'  - {alias}\n' for alias in aliases)
    (folder / 'PROFILE.md').write_text(
        '---\n'
        f'person_id: {person_id}\n'
        'document_type: profile\n'
        'schema_version: 0.1\n'
        'status: draft\n'
        'sensitivity: private\n'
        f'display_name: {display_name}\n'
        f'aliases:\n{aliases_block}'
        'direct_user: false\n'
        'trust_tier: tier_1_recognized\n'
        '---\n'
        f'# {display_name} — Profile\n\n## Known context\n\n- Seed context.\n',
        encoding='utf-8',
    )
    for name, doc_type, sens in (
        ('PERMISSIONS.md', 'permissions', 'private'),
        ('ALIASES.md', 'aliases', 'private'),
        ('MEMORY_POLICY.md', 'memory_policy', 'private'),
        ('RELATIONSHIP_TO_KONAN.md', 'relationship_to_konan', 'sensitive'),
        ('NOTES.md', 'notes', 'private'),
        ('INTERACTION_LOG.md', 'interaction_log', 'private'),
    ):
        (folder / name).write_text(_minimal_fm(person_id, doc_type, sens), encoding='utf-8')


def _fixture() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    _write_index(root)
    _write_person(root, 'sammy', 'Sammy', ['Sam', 'Sammy'])
    _write_person(root, 'jesus', 'Jesus', ['Jesus', 'Jesus Morales'])
    return tmp, root


def _fact(**overrides) -> dict:
    data = {
        'candidate_name': 'Sam',
        'field': 'profile.known_context',
        'value': 'Sam is coming over later.',
        'source_person_id': 'konan',
        'source_type': 'konan_account',
        'sensitivity': 'private',
        'observed_context': 'Sam is coming over later.',
        'provenance': {'message_id': 'm1'},
    }
    data.update(overrides)
    return data


class TestPersonRootsLiveChat(unittest.TestCase):
    def test_unknown_or_similar_name_returns_clarify_tool_call_without_mutation(self) -> None:
        tmp, root = _fixture()
        try:
            result = handle_live_chat_candidates([_fact(candidate_name='Samuel', value='similar')], root=root)
            self.assertEqual(result['action'], 'clarify')
            self.assertEqual(result['tool_call']['name'], 'clarify')
            self.assertIn('choices', result['clarify_args'])
            self.assertFalse(pending_path(root).exists())
            self.assertNotIn('similar', (root / 'sammy' / 'PROFILE.md').read_text(encoding='utf-8'))
            self.assertIn('Person Roots needs clarification', render_live_chat_result(result))
        finally:
            tmp.cleanup()

    def test_safe_known_fact_applies_without_queue(self) -> None:
        tmp, root = _fixture()
        try:
            result = handle_live_chat_candidates([_fact()], root=root, today='2026-08-07')
            self.assertEqual(result['action'], 'applied')
            self.assertEqual(result['summary']['applied'], 1)
            self.assertEqual(result['summary']['queued'], 0)
            self.assertFalse(pending_path(root).exists())
            self.assertIn('Sam is coming over later.', (root / 'sammy' / 'PROFILE.md').read_text(encoding='utf-8'))
        finally:
            tmp.cleanup()

    def test_approval_or_denial_items_are_not_queued_in_live_chat_path(self) -> None:
        tmp, root = _fixture()
        try:
            result = handle_live_chat_candidates(
                [_fact(field='relationship_to_konan.category', source_type='god_subagent', source_person_id='hermes')],
                root=root,
                today='2026-08-07',
            )
            self.assertEqual(result['action'], 'planned_review')
            self.assertEqual(result['summary']['review'], 1)
            self.assertEqual(result['summary']['queued'], 0)
            self.assertFalse(pending_path(root).exists())
        finally:
            tmp.cleanup()

    def test_no_candidates_is_noop(self) -> None:
        result = handle_live_chat_candidates([])
        self.assertEqual(result['action'], 'no_candidates')
        self.assertIsNone(result['tool_call'])

    def test_load_candidate_stream_and_cli_smoke(self) -> None:
        tmp, root = _fixture()
        try:
            source = root / 'candidates.jsonl'
            source.write_text(json.dumps(_fact()) + '\n', encoding='utf-8')
            self.assertEqual(load_candidate_stream(source)[0]['candidate_name'], 'Sam')
            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / 'scripts' / 'person-roots-live-chat.py'),
                    str(source),
                    '--root',
                    str(root),
                    '--today',
                    '2026-08-07',
                    '--json',
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data['action'], 'applied')
        finally:
            tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
