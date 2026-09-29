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
        self.assertEqual(len(mod.list_tools()), 11)
        self.assertEqual(mod.list_tools(), mod.REGISTERED_TOOL_NAMES)
        self.assertIn('ichor_store', mod.list_tools())
        self.assertIn('ichor_compare', mod.list_tools())
        # Phase 2D / 3D additions
        self.assertIn('ichor_entity_resolve', mod.list_tools())
        self.assertIn('ichor_recall_stats', mod.list_tools())

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
            # Drain the async recall_log writer before the temp DB dir is
            # removed — a still-running thread re-creates -wal/-shm files
            # inside the dir mid-rmtree and fails cleanup (order-dependent
            # flake seen when this test runs after the gap-closure suite).
            mod._drain_recall_log_writes()

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

    def test_audit_reader_survives_large_tool_outputs(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            mod = load_module(td)

            class FatTrait:
                def retrieve(self, **kwargs):
                    return {
                        'results': [
                            {'id': 'fat', 'backend': 'fts5', 'score': 1.0, 'snippet': 'x' * 12000}
                        ],
                        'backends_used': ['fts5'],
                        'total': 1,
                        'returned': 1,
                        'warnings': [],
                    }

            with patch.object(mod, '_memory_trait', return_value=FatTrait()):
                retrieve = json.loads(mod.ichor_retrieve('fat payload', limit=1))
            self.assertEqual(retrieve['total'], 1)
            audit = json.loads(mod.ichor_audit(10))
            self.assertGreaterEqual(audit['count'], 1)
            retrieve_rows = [row for row in audit['entries'] if row['tool_name'] == 'ichor_retrieve']
            self.assertTrue(retrieve_rows)
            self.assertTrue(retrieve_rows[0]['output']['_truncated'])
            mod._drain_recall_log_writes()

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


class TestIchorMCPWire(unittest.TestCase):
    """End-to-end proof that the module is a working MCP server, not just importable.

    Import-level green is not evidence: the module imported fine for months
    while ``mcp.server.fastmcp`` had been removed from the SDK, and every test
    in this file failed with ModuleNotFoundError. These tests speak real MCP
    over stdio to a real subprocess.
    """

    def _run_handshake(self, temp_home: str) -> list[str]:
        """Spawn the server on stdio, initialize, and list its tools."""
        try:
            from mcp import ClientSession, StdioServerParameters, stdio_client
        except Exception as exc:  # pragma: no cover - SDK absent
            self.skipTest(f'mcp client unavailable: {exc}')

        import asyncio
        import sys

        env = dict(os.environ)
        env['HOME'] = temp_home

        async def handshake() -> list[str]:
            params = StdioServerParameters(
                command=sys.executable,
                args=[str(MODULE_PATH), '--stdio'],
                env=env,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    return [tool.name for tool in listed.tools]

        return asyncio.run(asyncio.wait_for(handshake(), timeout=90))

    def test_stdio_server_lists_every_registered_tool(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            names = self._run_handshake(td)

        # The wire surface must match the manifest the module advertises -- a
        # tool in TOOL_NAMES that the server never registers is a dead promise.
        self.assertEqual(sorted(names), sorted(load_module(td).REGISTERED_TOOL_NAMES))
        self.assertEqual(len(names), 11)

    def test_stdio_server_calls_a_tool_end_to_end(self) -> None:
        """A tool call must return real data over the wire, not just be listed.

        Listing tools proves the server booted and registered its decorators;
        it does not prove the handlers are reachable or that their arguments
        survive the JSON-RPC round trip. This test stores a memory and reads it
        back through the real stdio transport, against a temp ``HOME`` so it
        cannot touch the live Ichor DB.
        """
        try:
            from mcp import ClientSession, StdioServerParameters, stdio_client
        except Exception as exc:  # pragma: no cover - SDK absent
            self.skipTest(f'mcp client unavailable: {exc}')

        import asyncio
        import sys

        def _text(result: object) -> str:
            """Return the text payload of a CallToolResult (these tools return JSON text)."""
            for block in getattr(result, 'content', []) or []:
                text = getattr(block, 'text', None)
                if text is not None:
                    return text
            raise AssertionError(f'tool result carried no text content: {result!r}')

        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            env = dict(os.environ)
            env['HOME'] = td

            async def call() -> dict:
                params = StdioServerParameters(
                    command=sys.executable,
                    args=[str(MODULE_PATH), '--stdio'],
                    env=env,
                )
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        stored = await session.call_tool('ichor_store', {
                            'key': 'wire.probe',
                            'content': 'stdio round trip proof for the wire test',
                            'category': 'fact',
                        })
                        retrieved = await session.call_tool('ichor_retrieve', {
                            'query': 'stdio round trip',
                            'limit': 5,
                        })
                        return {
                            'stored': json.loads(_text(stored)),
                            'retrieved': json.loads(_text(retrieved)),
                        }

            payload = asyncio.run(asyncio.wait_for(call(), timeout=90))

        self.assertTrue(payload['stored']['stored'])
        self.assertTrue(payload['retrieved']['results'])


if __name__ == '__main__':
    unittest.main()
