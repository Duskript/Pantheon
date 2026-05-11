#!/usr/bin/env python3
"""Standalone Demeter inbox watcher — bypasses pantheon plugin init."""

import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Demeter] %(levelname)s: %(message)s",
)

# Inject demeter dir + its parent so relative imports work
_DEMETER_DIR = Path.home() / "pantheon" / "plugins" / "pantheon" / "demeter"
_PANTHON_DIR = _DEMETER_DIR.parent  # pantheon/
sys.path.insert(0, str(_PANTHON_DIR))
# Also need the parent of pantheon/ so relative cross-module imports resolve
sys.path.insert(0, str(_PANTHON_DIR.parent))

# --- Load demeter modules without triggering pantheon/__init__.py ---
import importlib.machinery
import importlib.util

_MODULES = {}

for _fname, _modname in [
    ("classifier.py", "demeter.classifier"),
    ("ingest.py", "demeter.ingest"),
    ("watcher.py", "demeter.watcher"),
]:
    _path = _DEMETER_DIR / _fname
    _spec = importlib.util.spec_from_file_location(_modname, _path)
    _mod = importlib.util.module_from_spec(_spec)
    # Pre-register before exec so relative imports find each other
    sys.modules[_modname] = _mod
    _spec.loader.exec_module(_mod)
    _MODULES[_modname] = _mod

DelWatcher = _MODULES["demeter.watcher"].DemeterWatcher


def main():
    import json
    from datetime import datetime, timezone

    inbox = str(Path.home() / "Staging" / "inbox")
    Path(inbox).mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("demeter-watch")
    logger.info("Starting Demeter watcher on %s/", inbox)

    watcher = DelWatcher(inbox_path=inbox)
    watcher.start()

    try:
        # Keep alive — DemeterWatcher.start() spawns a thread for watchdog
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        watcher.stop()


if __name__ == "__main__":
    main()
