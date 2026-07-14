"""pytest configuration for Ichor Memory Engine tests."""
import os
import sys

# Ensure the pantheon root is on sys.path so that `from lib.ichor_db` etc. work
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)
