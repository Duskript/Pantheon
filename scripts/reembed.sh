#!/bin/bash
# Wrapper for reembed-athenaeum.py with unbuffered output to log file
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-OPENROUTER_API_KEY_PLACEHOLDER}"
cd /home/konan/pantheon
exec stdbuf -oL -eL python3 -u scripts/reembed-athenaeum.py > /tmp/reembed.log 2>&1
