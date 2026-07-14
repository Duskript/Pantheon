"""Run the observability tests and dump full output to file."""
import sys
import os
import pytest

# Make /tmp NOT shadow stdlib
sys.path = [p for p in sys.path if p != '/tmp']
sys.path = [p for p in sys.path if p != '']

# Add the project paths properly
sys.path.insert(0, '/home/konan/pantheon')
sys.path.insert(0, '/home/konan/pantheon/tests')

# Use pytest.main with explicit args
out_path = '/tmp/pytest_obs_full.txt'
with open(out_path, 'w') as f:
    exit_code = pytest.main([
        '/home/konan/pantheon/tests/test_ichor_retrieval_observability.py',
        '-v', '--tb=long', '--no-header', '-p', 'no:cacheprovider', '--color=no',
    ], plugins=[])
print(f"exit_code={exit_code}")
print(f"output at {out_path}")
