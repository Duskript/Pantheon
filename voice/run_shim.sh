#!/usr/bin/env bash
# Launch the Hermes voice bridge with local config.
# Reuses the main Hermes env for the gateway key; nothing is hardcoded.
set -a
source /home/konan/.hermes/.env
set +a
export HERMES_API_URL="${HERMES_API_URL:-http://127.0.0.1:8650/v1/chat/completions}"
export HERMES_API_KEY="${API_SERVER_KEY}"
export HERMES_MODEL="${HERMES_MODEL:-hermes}"
export VOICE_SESSION_KEY="${VOICE_SESSION_KEY:-voice-demo}"
# Bearer the shim demands from ElevenLabs. Generated once into .shim_token so the
# public funnel URL is never an unauthenticated door into the agent.
export VOICE_SHIM_TOKEN="${VOICE_SHIM_TOKEN:-$(cat /home/konan/pantheon/voice/.shim_token 2>/dev/null)}"
# Watermark so the launcher can prove which build is running.
export VOICE_SHIM_BUILD="continuity+v2"
export FIRST_TOKEN_WAIT="${FIRST_TOKEN_WAIT:-6.0}"
export TOTAL_WAIT="${TOTAL_WAIT:-25.0}"
exec /home/konan/pantheon/voice/.venv/bin/python /home/konan/pantheon/voice/hermes_voice_llm.py
