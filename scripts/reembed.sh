#!/bin/bash
# Wrapper for reembed-athenaeum.py with unbuffered output to log file
# OPENROUTER_API_KEY — set via .env or environment. No hardcoded fallback.
: "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY is required. Set it in .env or export it.}"
cd /home/konan/pantheon
exec stdbuf -oL -eL python3 -u scripts/reembed-athenaeum.py > /tmp/reembed.log 2>&1
