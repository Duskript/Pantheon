"""QA-only import shim for PR #35 isolated test run.

The v2 tests' fixtures.py inserts /home/konan/pantheon/conductor at sys.path[0],
which makes bare `from v2 ...` imports resolve to the live working tree instead
of this exported PR head. Pre-importing v2 here pins the package __path__ to the
clean archive before fixtures.py mutates sys.path.
"""
from __future__ import annotations

import importlib
import os
import sys

ARCHIVE_ROOT = os.environ.get("PR35_QA_ARCHIVE_ROOT")
if ARCHIVE_ROOT:
    conductor_root = f"{ARCHIVE_ROOT}/conductor"
    if conductor_root not in sys.path:
        sys.path.insert(0, conductor_root)
    if ARCHIVE_ROOT not in sys.path:
        sys.path.insert(0, ARCHIVE_ROOT)
    importlib.import_module("v2")
