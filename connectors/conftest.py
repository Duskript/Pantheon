"""
Top-level conftest for the Pantheon connector library.

Ensures ``import lib`` resolves to ``connectors/lib/`` when pytest is
invoked from the ``connectors/`` workspace root.
"""

import sys
from pathlib import Path

# Insert the workspace root (the parent of this conftest's directory) at
# the front of sys.path so the ``lib`` package is importable.
_WORKSPACE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_WORKSPACE_ROOT))
