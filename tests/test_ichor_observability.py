from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PANTHEON_ROOT = Path('/home/konan/pantheon')
COMPARISON_REPORT = PANTHEON_ROOT / 'scripts' / 'comparison_report.py'
GUARDIAN = PANTHEON_ROOT / 'scripts' / 'ichor_health_guardian.py'


def _load_module(path: Path, tag: str):
    spec = importlib.util.spec_from_file_location(f'{tag}_{path.stem}', path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestComparisonReport(unittest.TestCase):
    def test_summarize_comparison_counts_hooks_and_divergences(self) -> None:
        mod = _load_module(COMPARISON_REPORT, 'comparison')
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            root = Path(td)
            comp = root / 'hooks' / 'pantheon-core' / 'comparison'
            comp.mkdir(parents=True, exist_ok=True)
            (comp / 'pre_llm_call.jsonl').write_text(
                '\n'.join([
                    json.dumps({'hook': 'pre_llm_call', 'source': 'accordion', 'comparison_mode': True}),
                    json.dumps({'hook': 'pre_llm_call', 'source': 'pantheon-core', 'comparison_mode': True}),
                ]) + '\n',
                encoding='utf-8',
            )
            (comp / 'pre_tool_call.jsonl').write_text(
                json.dumps({'hook': 'pre_tool_call', 'result': {'passed': False, 'message': 'block'}}) + '\n',
                encoding='utf-8',
            )
            (comp / 'broken.jsonl').write_text(
                json.dumps({'hook': 'pre_llm_call', 'error': 'boom'}) + '\n',
                encoding='utf-8',
            )

            summary = mod.summarize_comparison_logs(comp)

            self.assertEqual(summary['total_entries'], 4)
            self.assertEqual(summary['hook_counts']['pre_llm_call'], 2)
            self.assertEqual(summary['hook_counts']['pre_tool_call'], 1)
            self.assertEqual(summary['divergence_count'], 2)
            self.assertEqual(summary['blocked_count'], 1)

            out = mod.write_comparison_report(comp, output_root=root / 'reports')
            self.assertTrue(out.exists())
            text = out.read_text(encoding='utf-8')
            self.assertIn('pre_llm_call', text)
            self.assertIn('divergence_count', text)


# ---------------------------------------------------------------------------
# Health guardian — component verdicts
#
# These assert the *contracts* the guardian promises, not snapshots of the
# current fleet: an absent component is informational rather than a permanent
# alarm, the context-engine probe follows config.yaml instead of a hardcoded
# engine name, the hook probe checks declared-vs-registered hooks on whatever
# plugins are deployed, and an empty comparison lane is reported as unmeasured
# rather than as health.
# ---------------------------------------------------------------------------
class TestHealthGuardian(unittest.TestCase):
    def test_collect_observability_state_reports_healthy_components(self) -> None:
        mod = _load_module(GUARDIAN, 'guardian')
        with patch.object(mod, 'probe_ichor_mcp', return_value={'component': 'Ichor MCP', 'status': 'ok', 'detail': 'healthy'}), patch.object(mod, 'probe_context_engine', return_value={'component': 'Context Engine', 'status': 'ok', 'detail': 'loaded'}), patch.object(mod, 'probe_pantheon_hooks', return_value={'component': 'Pantheon Hooks', 'status': 'ok', 'detail': '2/2 hooks'}), patch.object(mod, 'probe_comparison_report', return_value={'component': 'Comparison Report', 'status': 'ok', 'detail': 'clean', 'summary': {'total_entries': 4, 'divergence_count': 0}}):
            state = mod.collect_observability_state()

        self.assertEqual(state['warning_count'], 0)
        self.assertEqual(state['dead_count'], 0)
        self.assertEqual(
            [item['component'] for item in state['components']],
            ['Ichor MCP', 'Context Engine', 'Pantheon Hooks', 'Comparison Report'],
        )
        self.assertEqual(state['equivalence']['status'], 'ok')
        self.assertEqual(mod.render_guardian_text(state), '')

    def test_render_guardian_text_includes_broken_component(self) -> None:
        mod = _load_module(GUARDIAN, 'guardian_broken')
        state = {
            'components': [
                {'component': 'Ichor MCP', 'status': 'dead', 'detail': 'unreachable'},
                {'component': 'Context Engine', 'status': 'ok', 'detail': 'loaded'},
            ],
            'warning_count': 0,
            'dead_count': 1,
            'equivalence': {'status': 'warning', 'detail': '2 divergences'},
        }
        text = mod.render_guardian_text(state)
        self.assertIn('Ichor MCP', text)
        self.assertIn('UNHEALTHY', text)
        self.assertIn('2 divergences', text)

    def test_not_deployed_components_are_reported_but_not_faults(self) -> None:
        """An absent component must not be a permanent alarm.

        The two probes this replaces were pinned to components that only exist
        in Pantheon's vendored 0.17.0 checkout, so they reported 'dead' forever
        for lanes this deployment does not run. An absent component is
        informational: it stays in the ledger, it never makes the guardian
        unhealthy, and it never fires a notification.
        """
        mod = _load_module(GUARDIAN, 'guardian_absent')
        absent = {
            'component': 'Comparison Report',
            'status': 'n/a',
            'detail': 'unmeasured — 0 comparison entries',
        }
        with patch.object(mod, 'probe_ichor_mcp', return_value={'component': 'Ichor MCP', 'status': 'ok', 'detail': 'healthy'}), patch.object(mod, 'probe_context_engine', return_value={'component': 'Context Engine', 'status': 'ok', 'detail': 'loaded'}), patch.object(mod, 'probe_pantheon_hooks', return_value={'component': 'Pantheon Hooks', 'status': 'ok', 'detail': 'ok'}), patch.object(mod, 'probe_comparison_report', return_value=dict(absent)):
            state = mod.collect_observability_state()

        self.assertEqual(state['dead_count'], 0)
        self.assertEqual(state['warning_count'], 0)
        self.assertEqual(state['not_deployed_count'], 1)
        self.assertEqual(state['not_deployed'][0]['component'], 'Comparison Report')
        # Still healthy: the guardian stays silent instead of alerting forever.
        self.assertEqual(mod.render_guardian_text(state), '')

    def test_probe_context_engine_resolves_the_engine_the_config_selects(self) -> None:
        """The probe must follow config.yaml, not a hardcoded engine name."""
        mod = _load_module(GUARDIAN, 'guardian_engine')

        with patch.object(mod, '_live_config', return_value={'context': {'engine': 'compressor'}}):
            builtin = mod.probe_context_engine()
        self.assertEqual(builtin['status'], 'ok')
        self.assertEqual(builtin['source'], 'builtin')

        # A config naming an engine that is not installed is a real fault, and
        # the probe must say which engine and what was available.
        with patch.object(mod, '_live_config', return_value={'context': {'engine': 'no-such-engine'}}):
            broken = mod.probe_context_engine()
        self.assertEqual(broken['status'], 'dead')
        self.assertIn('no-such-engine', broken['detail'])
        self.assertIn('plugin engines available', broken['detail'])

    def test_probe_pantheon_hooks_catches_a_declared_hook_that_never_registered(self) -> None:
        """A deployed plugin must register every hook its manifest promises."""
        mod = _load_module(GUARDIAN, 'guardian_hooks')

        class FakeManifest:
            provides_hooks = ['pre_tool_call', 'post_tool_call']

        class FakePlugin:
            manifest = FakeManifest()
            hooks_registered = ['pre_tool_call']

        class FakeManager:
            _plugins = {'half-broken': FakePlugin()}

        with patch.object(mod, '_plugin_manager', return_value=(FakeManager(), {})):
            result = mod.probe_pantheon_hooks()

        self.assertEqual(result['status'], 'dead')
        self.assertIn('half-broken', result['detail'])
        self.assertIn('post_tool_call', result['detail'])

    def test_probe_pantheon_hooks_warns_when_a_deployed_plugin_cannot_load(self) -> None:
        """A plugin that fails to load is invisible otherwise — the fleet just
        runs without it, so the guardian has to be the one that says so."""
        mod = _load_module(GUARDIAN, 'guardian_load_failure')

        class FakeManifest:
            provides_hooks = ['pre_tool_call']

        class FakePlugin:
            manifest = FakeManifest()
            hooks_registered = ['pre_tool_call']

        class FakeManager:
            _plugins = {'good-plugin': FakePlugin()}

        failures = {'broken-plugin': 'register() takes 0 positional arguments but 1 was given'}
        with patch.object(mod, '_plugin_manager', return_value=(FakeManager(), failures)):
            result = mod.probe_pantheon_hooks()

        self.assertEqual(result['status'], 'warning')
        self.assertIn('broken-plugin', result['detail'])

    def test_probe_pantheon_hooks_reports_not_applicable_when_no_hooks_are_deployed(self) -> None:
        mod = _load_module(GUARDIAN, 'guardian_no_hooks')

        class FakeManager:
            _plugins = {}

        with patch.object(mod, '_plugin_manager', return_value=(FakeManager(), {})):
            result = mod.probe_pantheon_hooks()

        self.assertEqual(result['status'], 'n/a')

    def test_probe_comparison_report_refuses_to_call_an_empty_lane_healthy(self) -> None:
        """'0 divergences' with 0 entries is not health, it is an unmeasured lane.

        The comparison lane is fed by the pantheon-core hook plugin, which is not
        deployed in this fleet, so every daily report said '0 divergences' over
        an empty directory -- a green light from a lane that was not running.
        """
        mod = _load_module(GUARDIAN, 'guardian_comparison')
        with tempfile.TemporaryDirectory(dir='/home/konan') as td:
            empty = Path(td) / 'comparison'
            empty.mkdir(parents=True, exist_ok=True)
            with patch.object(mod, 'DEFAULT_COMPARISON_DIR', empty):
                unmeasured = mod.probe_comparison_report()

            self.assertEqual(unmeasured['status'], 'n/a')
            self.assertIn('not evidence of health', unmeasured['detail'])

            (empty / 'pre_llm_call.jsonl').write_text(
                json.dumps({'hook': 'pre_llm_call', 'source': 'pantheon-core'}) + '\n',
                encoding='utf-8',
            )
            with patch.object(mod, 'DEFAULT_COMPARISON_DIR', empty):
                measured = mod.probe_comparison_report()

            self.assertEqual(measured['status'], 'ok')
            self.assertIn('1 comparison entries', measured['detail'])


if __name__ == '__main__':
    unittest.main()
