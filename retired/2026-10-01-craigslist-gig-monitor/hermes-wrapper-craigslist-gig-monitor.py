#!/usr/bin/env python3
"""Run Craigslist gig monitoring directly; keep output script-owned."""
from __future__ import annotations

import subprocess
import sys

CMD = [sys.executable, "/home/konan/pantheon/scripts/craigslist-monitor.py"]


if __name__ == "__main__":
    raise SystemExit(subprocess.call(CMD, cwd="/home/konan/pantheon"))
