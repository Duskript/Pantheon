#!/bin/bash
# Run the Athenaeum re-embed catchup with nomic-embed-text:v1.5
export ATHENAEUM_EMBED_MODEL=nomic-embed-text:v1.5
export ATHENAEUM_EMBED_PROVIDER=ollama
cd /home/konan/pantheon
exec python3 -u scripts/embed-catchup.py --workers 8
