"""
conftest.py — pytest config for the lib test suite.

Makes the ``lib`` package importable when running ``pytest`` from the
``connectors/`` workspace root.
"""

import sys
from pathlib import Path

# Add the parent of this file (the workspace root) to sys.path so
# ``import lib`` resolves to ``connectors/lib/``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
