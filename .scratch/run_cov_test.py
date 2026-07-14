"""Run the retrieval coverage helper tests against the live DB and dump output.

Mirrors .scratch/run_obs_test.py but for the helper module
(lib.ichor.retrieval_coverage). Bypasses the /tmp/inspect.py shadow
that breaks pytest in this environment.
"""
import sys

# Strip /tmp from sys.path — /tmp/inspect.py shadows stdlib inspect
# in some test environments (e.g. when the script lives in /tmp).
sys.path = [p for p in sys.path if p != '/tmp']

sys.path.insert(0, '/home/konan/pantheon')
sys.path.insert(0, '/home/konan/pantheon/tests')

import pytest

out_path = '/tmp/pytest_cov_full.txt'
with open(out_path, 'w') as f:
    exit_code = pytest.main([
        '/home/konan/pantheon/tests/test_retrieval_coverage.py',
        '-v', '--tb=long', '--no-header', '-p', 'no:cacheprovider',
        '--color=no',
    ], plugins=[])
print(f"exit_code={exit_code}")
print(f"output at {out_path}")
