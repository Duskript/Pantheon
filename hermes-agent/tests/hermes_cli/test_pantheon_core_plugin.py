from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import yaml

REPO_ROOT = Path('/home/konan/pantheon/hermes-agent')
PLUGIN_PATH = REPO_ROOT / 'plugins' / 'pantheon-core' / '__init__.py'
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _write_config(home: Path, *, enabled: list[str], hooks: dict[str, object] | None = None) -> None:
    cfg = {
        'plugins': {
            'enabled': enabled,
            'disabled': [],
        },
        'hooks': hooks or {},
    }
    home.mkdir(parents=True, exist_ok=True)
    (home / 'config.yaml').write_text(yaml.safe_dump(cfg), encoding='utf-8')


def _load_plugin_module(tag: str):
    spec = importlib.util.spec_from_file_location(f'pantheon_core_{tag}', PLUGIN_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestPantheonCorePlugin(unittest.TestCase):
    def test_plugin_loads_and_registers_hooks(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            home = Path(td)
            _write_config(home, enabled=['pantheon-core'])
            os.environ['HERMES_HOME'] = str(home)
            os.environ['HERMES_BUNDLED_PLUGINS'] = str(REPO_ROOT / 'plugins')

            from hermes_cli.plugins import PluginManager

            mgr = PluginManager()
            mgr.discover_and_load()

            self.assertIn('pantheon-core', mgr._plugins)
            loaded = mgr._plugins['pantheon-core']
            self.assertTrue(loaded.enabled)
            self.assertEqual(set(loaded.hooks_registered), {
                'pre_llm_call',
                'pre_tool_call',
                'post_tool_call',
                'on_session_start',
                'on_session_finalize',
            })

    def test_hooks_return_none_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            home = Path(td)
            _write_config(home, enabled=['pantheon-core'])
            os.environ['HERMES_HOME'] = str(home)
            mod = _load_plugin_module('disabled')

            self.assertIsNone(mod._on_pre_llm_call(user_message='hello'))
            self.assertIsNone(mod._on_pre_tool_call(tool_name='write_file', args={'path': '/tmp/x'}))
            self.assertIsNone(mod._on_post_tool_call(tool_name='write_file', args={'path': '/tmp/x'}, result='ok'))
            self.assertIsNone(mod._on_session_start(session_id='sess-1', platform='cli'))
            self.assertIsNone(mod._on_session_finalize(session_id='sess-1', platform='cli', completed=True, interrupted=False))

            self.assertFalse((home / 'hooks' / 'pantheon-core' / 'comparison').exists())
            self.assertFalse((home / 'hooks' / 'pantheon-core' / 'episodes').exists())
            self.assertFalse((home / 'hooks' / 'pantheon-core' / 'digests').exists())

    def test_comparison_mode_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            home = Path(td)
            _write_config(home, enabled=['pantheon-core'], hooks={'comparison_mode': True})
            os.environ['HERMES_HOME'] = str(home)
            mod = _load_plugin_module('comparison')

            result = mod._on_session_start(session_id='sess-2', platform='cli')
            self.assertIsInstance(result, dict)
            self.assertIn('inbox item(s) pending', result['context'])

            log = home / 'hooks' / 'pantheon-core' / 'comparison' / 'on_session_start.jsonl'
            self.assertTrue(log.exists())
            text = log.read_text(encoding='utf-8')
            self.assertIn('inbox_count', text)

    def test_memory_injection_returns_context(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            home = Path(td)
            _write_config(home, enabled=['pantheon-core'], hooks={'memory_injection': True})
            os.environ['HERMES_HOME'] = str(home)
            mod = _load_plugin_module('memory')

            with patch.object(mod, '_build_memory_context', return_value={'context': 'memory hit', 'result_count': 1}):
                result = mod._on_pre_llm_call(user_message='teapot')

            self.assertIsInstance(result, dict)
            self.assertIn('context', result)
            self.assertIsInstance(result['context'], str)
            self.assertEqual(result.get('source'), 'pantheon-core')
            self.assertIn('memory hit', result['context'])

    def test_pre_llm_call_injects_accordion_expansion_when_engine_selected(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            home = Path(td)
            _write_config(home, enabled=['pantheon-core'], hooks={},)
            config_path = home / 'config.yaml'
            config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
            config.setdefault('context', {})['engine'] = 'accordion'
            config_path.write_text(yaml.safe_dump(config), encoding='utf-8')
            os.environ['HERMES_HOME'] = str(home)
            mod = _load_plugin_module('accordion-hook')

            class FakeAccordionEngine:
                name = 'accordion'

                def on_session_start(self, session_id: str, **kwargs):
                    self.session_id = session_id
                    self.kwargs = kwargs

                def expand_for_message(self, message: str):
                    if 'database schema' in message:
                        return {
                            'context': 'accordion expansion: database schema decisions',
                            'fold_id': 77,
                            'source': 'accordion',
                        }
                    return None

            with patch('plugins.context_engine.load_context_engine', return_value=FakeAccordionEngine()):
                result = mod._on_pre_llm_call(session_id='sess-5', platform='cli', model='gpt-5.4-mini', user_message='remember the database schema')

            self.assertIsInstance(result, dict)
            self.assertIn('accordion expansion', result['context'])
            self.assertEqual(result.get('source'), 'accordion')

    def test_gate_blocking_returns_block_message(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            home = Path(td)
            _write_config(home, enabled=['pantheon-core'], hooks={'gates': True})
            os.environ['HERMES_HOME'] = str(home)
            mod = _load_plugin_module('gate')

            target = home / 'blocked.txt'
            target.write_text('hello', encoding='utf-8')
            result = mod._on_pre_tool_call(
                tool_name='write_file',
                args={'path': str(target)},
                user_message='please edit the file',
            )
            self.assertIsInstance(result, dict)
            self.assertEqual(result['action'], 'block')
            self.assertIn('read_file', result['message'])

    def test_session_finalize_writes_digest_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            home = Path(td)
            _write_config(home, enabled=['pantheon-core'], hooks={'session_finalize': True})
            os.environ['HERMES_HOME'] = str(home)
            mod = _load_plugin_module('finalize')

            self.assertIsNone(
                mod._on_session_finalize(
                    session_id='sess-4',
                    platform='cli',
                    model='gpt-5.4-mini',
                    completed=True,
                    interrupted=False,
                    summary='finished clean',
                )
            )
            digest = home / 'hooks' / 'pantheon-core' / 'digests' / 'sess-4.json'
            self.assertTrue(digest.exists())
            self.assertIn('finished clean', digest.read_text(encoding='utf-8'))

    def test_post_tool_call_reconciles_contradiction_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            home = Path(td)
            _write_config(home, enabled=['pantheon-core'], hooks={'reconcile_memory': True})
            os.environ['HERMES_HOME'] = str(home)
            mod = _load_plugin_module('reconcile')

            stored = {}

            class FakeTrait:
                def retrieve(self, **kwargs):
                    return {
                        'results': [
                            {
                                'title': 'db fact',
                                'snippet': 'The database is MySQL',
                                'content': 'The database is MySQL',
                                'raw_text': 'The database is MySQL',
                            }
                        ]
                    }

                def store(self, **kwargs):
                    stored.update(kwargs)
                    return {'stored': True, 'backend': 'events', 'id': 'evt:1'}

            with patch.object(mod, '_memory_trait', return_value=FakeTrait()):
                self.assertIsNone(
                    mod._on_post_tool_call(
                        tool_name='sql_query',
                        args={'query': 'what db do we use?'},
                        result='The database is not MySQL',
                        session_id='sess-9',
                        god_name='konan',
                    )
                )

            self.assertEqual(stored['category'], 'correction')
            self.assertEqual(stored['session_id'], 'sess-9')
            self.assertEqual(stored['god_name'], 'konan')
            self.assertIn('not MySQL', stored['content'])
            self.assertIn('MySQL', stored['content'])
            self.assertTrue(stored['key'].startswith('sess-9:sql_query'))


if __name__ == '__main__':
    unittest.main()
