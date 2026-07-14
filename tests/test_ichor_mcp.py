from __future__ import annotations

import importlib.machinery
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path('/home/konan/pantheon/lib/ichor_mcp.py')


def load_module(home_dir: str):
    os.environ['HOME'] = home_dir
    name = f'ichor_mcp_test_{Path(home_dir).name}'
    loader = importlib.machinery.SourceFileLoader(name, str(MODULE_PATH))
    return loader.load_module()  # type: ignore[deprecated-call]


class TestIchorMCP(unittest.TestCase):
    def test_tool_registry_has_expected_phase_a_tools(self) -> None:
        mod = load_module(tempfile.mkdtemp(prefix='ichor-mcp-tools-', dir='/home/konan'))
        self.assertEqual(len(mod.list_tools()), 9)
        self.assertEqual(mod.list_tools(), mod.REGISTERED_TOOL_NAMES)
        self.assertIn('ichor_store', mod.list_tools())
        self.assertIn('ichor_compare', mod.list_tools())

    def test_store_reconcile_supersedes_old_memory(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            mod = load_module(td)
            first = json.loads(mod.ichor_store(
                namespace='test',
                key='user.job',
                content='I work at Acme',
                category='fact',
                session_id='sess-1',
                god_name='hermes',
            ))
            self.assertTrue(first['stored'])

            second = json.loads(mod.ichor_store(
                namespace='test',
                key='user.job',
                content='I do not work at Acme anymore; I work at Relay 7',
                category='fact',
                session_id='sess-2',
                god_name='hermes',
                reconcile=True,
            ))
            self.assertTrue(second['stored'])
            self.assertIn('reconciliation', second)
            self.assertTrue(second['reconciliation']['applied'])
            self.assertEqual(second['reconciliation']['operation'], 'UPDATE')

            retrieve = json.loads(mod.ichor_retrieve('Acme', limit=10))
            rows = retrieve['results']
            self.assertTrue(any(item.get('title') == 'user.job' and 'Relay 7' in item.get('snippet', '') for item in rows))
            self.assertFalse(any(item.get('title') == 'user.job' and 'I work at Acme' in item.get('snippet', '') for item in rows))

    def test_store_retrieve_and_audit(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            mod = load_module(td)
            store = json.loads(mod.ichor_store(
                namespace='test',
                key='phase-a-key',
                content='phase a memory server smoke test',
                category='fact',
                session_id='sess-1',
                god_name='hermes',
            ))
            self.assertTrue(store['stored'])
            self.assertTrue(str(store['id']).startswith('fts5:'))

            retrieve = json.loads(mod.ichor_retrieve('phase a memory server', limit=5))
            self.assertIn('results', retrieve)
            self.assertGreaterEqual(len(retrieve['results']), 1)

            audit = json.loads(mod.ichor_audit(10))
            self.assertGreaterEqual(audit['count'], 2)
            self.assertTrue(all('tool_name' in row for row in audit['entries']))

            stats = json.loads(mod.ichor_stats())
            self.assertIn('tables', stats)
            self.assertIn('audit', stats)
            self.assertGreaterEqual(stats['tables']['audit_entries'], 2)

    def test_fold_expand_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            mod = load_module(td)
            fold = json.loads(mod.ichor_fold(
                session_id='sess-2',
                content='{"turn": 1, "message": "remember this"}',
                summary='remember this',
                token_count=42,
                fold_type='turn',
            ))
            self.assertTrue(fold['stored'])
            fold_id = fold['fold']['id']
            self.assertEqual(fold['fold']['expand_count'], 0)

            expanded = json.loads(mod.ichor_expand(fold_id))
            self.assertTrue(expanded['expanded'])
            self.assertEqual(expanded['fold']['full_content'], '{"turn": 1, "message": "remember this"}')
            self.assertEqual(expanded['fold']['expand_count'], 1)

    def test_gate_check_blocks_unread_write(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            mod = load_module(td)
            target = Path(td) / 'blocked.txt'
            target.write_text('hello')
            result = json.loads(mod.ichor_gate_check(
                tool_name='write_file',
                params={'path': str(target)},
                context={},
            ))
            self.assertTrue(result['blocked'])
            self.assertEqual(result['gate'], 'state_gate')
            self.assertIn('read_file', result['recovery_hint'])

    def test_compare_reports_legacy_and_tiered(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            mod = load_module(td)

            class FakeTrait:
                def retrieve(self, query, limit=10, backends=None, min_score=0.0, mode=None, active_god=None):
                    return {
                        'query': query,
                        'limit': limit,
                        'mode': mode,
                        'results': [
                            {'id': 'a', 'title': 'alpha', 'score': 0.9},
                            {'id': 'shared', 'title': 'shared', 'score': 0.8},
                        ] if mode == 'legacy' else [
                            {'id': 'shared', 'title': 'shared', 'score': 0.95},
                            {'id': 'b', 'title': 'beta', 'score': 0.7},
                        ]
                    }

            with patch.object(mod, '_memory_trait', return_value=FakeTrait()):
                result = json.loads(mod.ichor_compare('hello', limit=3))

            self.assertIn('legacy', result)
            self.assertIn('tiered', result)
            self.assertEqual(result['diff']['legacy_only'], ['a'])
            self.assertEqual(result['diff']['tiered_only'], ['b'])
            self.assertEqual(result['diff']['shared'], ['shared'])


if __name__ == '__main__':
    unittest.main()
