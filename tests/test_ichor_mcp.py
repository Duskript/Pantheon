from __future__ import annotations

import importlib.machinery
import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / 'lib' / 'ichor_mcp.py'


def load_module(home_dir: str):
    os.environ['HOME'] = home_dir
    name = f'ichor_mcp_test_{Path(home_dir).name}'
    loader = importlib.machinery.SourceFileLoader(name, str(MODULE_PATH))
    return loader.load_module()  # type: ignore[deprecated-call]


class TestIchorMCP(unittest.TestCase):
    def test_tool_registry_has_expected_phase_a_tools(self) -> None:
        mod = load_module(tempfile.mkdtemp(prefix='ichor-mcp-tools-', dir='/home/konan'))
        self.assertEqual(len(mod.list_tools()), 10)
        self.assertEqual(mod.list_tools(), mod.REGISTERED_TOOL_NAMES)
        self.assertIn('ichor_store', mod.list_tools())
        self.assertIn('ichor_compare', mod.list_tools())
        self.assertIn('ichor_context_pack', mod.list_tools())

    def test_context_pack_tool_defaults_to_dry_run_and_returns_pack(self) -> None:
        mod = load_module(tempfile.mkdtemp(prefix='ichor-mcp-context-pack-', dir='/home/konan'))
        result = json.loads(mod.ichor_context_pack(
            query='Conductor v2',
            god_name='thoth',
            phase='research',
            max_items=8,
        ))

        self.assertEqual(result['query'], 'Conductor v2')
        self.assertEqual(result['god'], 'thoth')
        self.assertEqual(result['phase'], 'research')
        self.assertEqual(result['metrics']['mode'], 'dry_run')
        self.assertEqual(result['metrics']['llm_calls'], 0)
        self.assertEqual(result['metrics']['api_calls'], 0)
        self.assertEqual(result['metrics']['db_writes'], 0)
        self.assertGreaterEqual(result['coverage']['returned'], 1)
        self.assertIn('injectable_context', result)

    def test_context_pack_tool_does_not_expose_live_mode_knob(self) -> None:
        mod = load_module(tempfile.mkdtemp(prefix='ichor-mcp-context-pack-safe-', dir='/home/konan'))

        signature = inspect.signature(mod.ichor_context_pack)

        self.assertNotIn('dry_run', signature.parameters)

    def test_context_pack_tool_clamps_public_budgets(self) -> None:
        mod = load_module(tempfile.mkdtemp(prefix='ichor-mcp-context-pack-budget-', dir='/home/konan'))
        result = json.loads(mod.ichor_context_pack(
            query='Conductor v2',
            god_name='hephaestus',
            phase='debug',
            max_items=999,
            max_tokens=999999,
            max_ms=999999,
        ))

        self.assertEqual(result['metrics']['mode'], 'dry_run')
        self.assertLessEqual(result['coverage']['returned'], 8)
        self.assertLessEqual(result['metrics']['tokens_estimated'], 900)
        self.assertEqual(result['metrics']['llm_calls'], 0)
        self.assertEqual(result['metrics']['api_calls'], 0)
        self.assertEqual(result['metrics']['db_writes'], 0)

    def test_context_pack_tool_handles_bad_budget_values_as_defaults(self) -> None:
        mod = load_module(tempfile.mkdtemp(prefix='ichor-mcp-context-pack-bad-budget-', dir='/home/konan'))
        result = json.loads(mod.ichor_context_pack(
            query='Conductor v2',
            god_name='thoth',
            phase='research',
            max_items='nope',
            max_tokens='nah',
            max_ms='no-way',
        ))

        self.assertNotIn('error', result)
        self.assertEqual(result['metrics']['mode'], 'dry_run')
        self.assertLessEqual(result['coverage']['returned'], 8)
        self.assertLessEqual(result['metrics']['tokens_estimated'], 900)
        self.assertEqual(result['metrics']['llm_calls'], 0)
        self.assertEqual(result['metrics']['api_calls'], 0)
        self.assertEqual(result['metrics']['db_writes'], 0)

    def test_context_pack_tool_handles_non_finite_budget_values_as_defaults(self) -> None:
        mod = load_module(tempfile.mkdtemp(prefix='ichor-mcp-context-pack-nonfinite-', dir='/home/konan'))
        result = json.loads(mod.ichor_context_pack(
            query='Conductor v2',
            god_name='thoth',
            phase='research',
            max_items=float('inf'),
            max_tokens=float('inf'),
            max_ms=float('inf'),
        ))

        self.assertNotIn('error', result)
        self.assertEqual(result['metrics']['mode'], 'dry_run')
        self.assertLessEqual(result['coverage']['returned'], 8)
        self.assertLessEqual(result['metrics']['tokens_estimated'], 900)
        self.assertEqual(result['metrics']['llm_calls'], 0)
        self.assertEqual(result['metrics']['api_calls'], 0)
        self.assertEqual(result['metrics']['db_writes'], 0)

    def test_context_pack_tool_does_not_create_audit_db(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            mod = load_module(td)

            result = json.loads(mod.ichor_context_pack(
                query='Conductor v2',
                god_name='thoth',
                phase='research',
            ))

            self.assertNotIn('error', result)
            self.assertEqual(result['metrics']['mode'], 'dry_run')
            self.assertFalse((Path(td) / '.hermes' / 'ichor.db').exists())

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
