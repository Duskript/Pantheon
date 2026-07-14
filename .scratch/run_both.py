"""Run Phase 3 tests + the Phase 2 contract tests to confirm no regression.

Phase 2 (Bounded Graph Traversal) was the parent task t_456660aa, and its
QA chain is still in flight. Re-running those tests here is the cheapest
way to confirm I didn't break them with my Phase 3 changes — they live
in the same ichor retrieval pipeline.

Also runs the baseline observability tests (now restructured into
positive Phase 3 contract tests).
"""
import sys

# Strip /tmp from sys.path so /tmp/inspect.py doesn't shadow stdlib
sys.path = [p for p in sys.path if p != '/tmp']

sys.path.insert(0, '/home/konan/pantheon')
sys.path.insert(0, '/home/konan/pantheon/tests')

import pytest

out_path = '/tmp/pytest_all_full.txt'
with open(out_path, 'w') as f:
    exit_code = pytest.main([
        # Phase 3 newly written — coverage helper + dispatch
        '/home/konan/pantheon/tests/test_retrieval_coverage.py',
        # Phase 3 contract — restructured from xfail placeholders
        '/home/konan/pantheon/tests/test_ichor_retrieval_observability.py',
        # Phase 2 contract (parent task) — confirm no regression
        '/home/konan/pantheon/tests/test_ichor_graph_traversal_bounded.py',
        '/home/konan/pantheon/tests/test_ichor_graph_validated_only.py',
        '-v', '--tb=short', '--no-header', '-p', 'no:cacheprovider',
        '--color=no',
    ], plugins=[])
print(f"exit_code={exit_code}")
print(f"output at {out_path}")
