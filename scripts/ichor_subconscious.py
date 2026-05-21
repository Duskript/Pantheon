#!/usr/bin/env python3
"""Wrapper: delegates to the canonical Ichor Subconscious Engine."""
import sys
import subprocess

CANONICAL = "/home/konan/pantheon/lib/ichor_subconscious.py"

if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, CANONICAL] + sys.argv[1:]))
