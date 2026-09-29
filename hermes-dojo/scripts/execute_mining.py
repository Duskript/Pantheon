#!/usr/bin/env python3
"""Run failed trajectory mining script."""

import subprocess
import json

# Run the script and capture output
result = subprocess.run(
    ['python3', '~/.pantheon/hermes-dojo/scripts/failed_trajectory_mining.py', '--json'],
    capture_output=True,
    text=True,
    timeout=60
)

print(f"Exit code: {result.returncode}")
print(f"Stdout: {result.stdout}")
print(f"Stderr: {result.stderr}")
