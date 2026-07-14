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


class TestHealthGuardian(unittest.TestCase):
    def test_collect_observability_state_reports_healthy_components(self) -> None:
        mod = _load_module(GUARDIAN, 'guardian')
        with patch.object(mod, 'probe_ichor_mcp', return_value={'component': 'Ichor MCP', 'status': 'ok', 'detail': 'healthy'}), patch.object(mod, 'probe_accordion_engine', return_value={'component': 'Accordion', 'status': 'ok', 'detail': 'loaded'}), patch.object(mod, 'probe_pantheon_core', return_value={'component': 'Hook Plugin', 'status': 'ok', 'detail': '5/5 hooks'}), patch.object(mod, 'probe_comparison_report', return_value={'component': 'Comparison Report', 'status': 'ok', 'detail': 'clean'}):
            state = mod.collect_observability_state()

        self.assertEqual(state['warning_count'], 0)
        self.assertEqual(state['dead_count'], 0)
        self.assertEqual([item['component'] for item in state['components']], ['Ichor MCP', 'Accordion', 'Hook Plugin', 'Comparison Report'])
        self.assertEqual(mod.render_guardian_text(state), '')

    def test_render_guardian_text_includes_broken_component(self) -> None:
        mod = _load_module(GUARDIAN, 'guardian_broken')
        state = {
            'components': [
                {'component': 'Ichor MCP', 'status': 'dead', 'detail': 'unreachable'},
                {'component': 'Accordion', 'status': 'ok', 'detail': 'loaded'},
            ],
            'warning_count': 0,
            'dead_count': 1,
            'equivalence': {'status': 'warning', 'detail': '2 divergences'},
        }
        text = mod.render_guardian_text(state)
        self.assertIn('Ichor MCP', text)
        self.assertIn('UNHEALTHY', text)
        self.assertIn('2 divergences', text)


if __name__ == '__main__':
    unittest.main()
