"""Top-level ``hermes_cli`` package — kanban contract module.

This package exists so the HephaestusBuildCard contract and its 12
contract tests are runnable from the repository root:

    cd /home/konan/pantheon && python3 -m pytest hermes_cli/kanban_contract_test.py

The canonical ``hermes_cli`` package (full CLI, ~hundreds of files) lives
at ``hermes-agent/hermes_cli/``. Both packages define ``kanban_contract``
with identical content so consumers can import from whichever package is
on their sys.path first. See ``hermes-agent/hermes_cli/kanban_contract.py``
for the canonical implementation.
"""

__version__ = "0.17.0"
__release_date__ = "2026.6.19"
