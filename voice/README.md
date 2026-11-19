# Hermes Voice — real-time co-presenter for Pantheon demos

Give Hermes a voice and let him sit in the pitch meeting next to Konan, talking live.

This directory holds the one piece that is not off-the-shelf: a shim that makes a
full Hermes agent turn usable inside a real-time voice conversation.

---

## The design in one paragraph

ElevenLabs Agents handles everything audio — speech-to-text, voice activity
detection, turn-taking, barge-in, and text-to-speech. Its "Custom LLM" feature lets
an agent point at any OpenAI-compatible streaming endpoint, and the Hermes gateway
already exposes exactly that on `:8650`. So the chain is: microphone → ElevenLabs
agent (STT + turn detection) → this shim → Hermes agent (tools, Ichor memory,
Pantheon MCP) → back through ElevenLabs TTS in a custom Hermes voice. Hermes is not
simulated or re-prompted: the actual agent, with its actual memory, answers.

---

## Why the shim exists

Measured on this machine with the real gateway:

| Path | Time to first token |
|---|---|
| Hermes agent turn, cold | ~7,050 ms |
| Hermes agent turn, warm | ~2,450 ms |
| Raw model, tiny prompt | ~250 ms |

The gap is the system prompt: ~27,400 tokens of persona, tools, and routing are
processed every turn. That is fine for chat and fatal for conversation — a 2.5 second
silence mid-pitch reads as a broken demo.

ElevenLabs documents the fix ("buffer words"): emit a short filler ending in an
ellipsis so TTS keeps prosody, then stream the real answer behind it. This shim
does that automatically.

### Verified result

```
first audio    :  12–60 ms      <- what the room hears
real answer    :  2.9–5.0 s     <- hidden behind the filler
```

Proven with three consecutive turns on one conversation id: seeded a fact
("prospect is Kirstin, 12-person CPA firm in Boise"), asked for it back, then asked
for an opening line. Hermes recalled the fact, cross-referenced a pre-existing Ichor
note about the same person, and produced a usable pitch line — all as speech-shaped
sentences under 40 words.

---

## Files

| Path | Purpose |
|---|---|
| `hermes_voice_llm.py` | The bridge. OpenAI-compatible `/v1/chat/completions`, filler-first streaming, session continuity, TTS text sanitizing. |
| `run_shim.sh` | Launcher. Pulls `API_SERVER_KEY` from the main Hermes env, nothing hardcoded. |
| `requirements.txt` | fastapi, uvicorn, httpx. |
| `.venv/` | Python 3.11 virtualenv. |

### Endpoints

- `POST /v1/chat/completions` — streaming SSE, OpenAI Chat Completions shape. This is what ElevenLabs calls.
- `GET /v1/models` — advertises the model name.
- `GET /voice/sessions` — which conversation is bound to which Hermes session (debugging).
- `GET /health` — liveness plus config summary, no secrets.

### Environment

| Variable | Default | Meaning |
|---|---|---|
| `HERMES_API_URL` | `http://127.0.0.1:8650/v1/chat/completions` | Gateway endpoint |
| `HERMES_API_KEY` | — | Gateway `API_SERVER_KEY` (required) |
| `HERMES_MODEL` | `hermes` | Model alias sent upstream |
| `VOICE_SHIM_TOKEN` | empty | Bearer this shim requires from ElevenLabs |
| `VOICE_SHIM_PORT` | `8651` | Listen port |
| `VOICE_SESSION_KEY` | `voice-demo` | Prefix for the Hermes session key |
| `FIRST_TOKEN_WAIT` | `6.0` | Seconds before a second filler is spoken |
| `TOTAL_WAIT` | `25.0` | Seconds before a graceful fallback line |
| `VOICE_BRIEF_FILE` | empty | File whose contents are injected as live stage context |

---

## Run it

```bash
cd /home/konan/pantheon/voice
./run_shim.sh            # foreground
curl -s localhost:8651/health
```

Smoke test against the real gateway:

```bash
curl -N localhost:8651/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-Eleven-Conversation-Id: smoke-1' \
  -d '{"model":"hermes","stream":true,
       "messages":[{"role":"user","content":"One line on why Pantheon beats an agency?"}]}'
```

---

## Current status (verified 2026-10-23)

| Piece | State |
|---|---|
| Shim code, filler logic, TTS sanitizer | done |
| Session continuity across turns | done — conversation bound to a real Hermes session id |
| Bearer auth on `/v1/*` | done — 401 without token, 200 with |
| systemd user service `hermes-voice-shim` | done — enabled, `Linger=yes`, restarts on failure |
| ElevenLabs account key | **BLOCKED — no key exists on this machine** |
| Public HTTPS for the Custom LLM | **BLOCKED — Funnel must be enabled in the Tailscale admin console** |

Live measurements through the systemd-managed service:

```
first audio : 53 ms
real answer : 4,433 ms
```

```
Right, so... Fair — most AI is a fad. But the firms automating their grunt
work are the ones still standing in five years, and it starts with ten
minutes saved per return. Want to see it?
```

That is the whole trick: the 4.4 second Hermes turn is real, and it is hidden
behind 53 milliseconds of convincing speech.

### Service management

```bash
systemctl --user status  hermes-voice-shim
systemctl --user restart hermes-voice-shim
journalctl --user -u hermes-voice-shim -f
```

---

## Remaining phases

### Phase A — ElevenLabs account and key (BLOCKED: needs Konan)

No `ELEVENLABS_API_KEY` exists in `~/.hermes/.env` or `~/pantheon/.env`; the only
ElevenLabs config present is a TTS `voice_id` in `config.yaml`. An Agents plan with
conversational AI credits is required.

### Phase B — public HTTPS for the Custom LLM

ElevenLabs must reach the shim over public HTTPS. This box already runs Tailscale,
so no third-party tunnel account is needed:

```bash
tailscale funnel --bg 8651          # gives https://<host>.<tailnet>.ts.net
```

Set `VOICE_SHIM_TOKEN` first and hand that bearer to ElevenLabs as the Custom LLM
secret — a public URL with no auth is an open door to the agent.

### Phase C — create the agent

Via API once the key exists (or by hand in the dashboard, same fields):

- **LLM**: Custom LLM → `https://<funnel-host>/v1/chat/completions`, model id `hermes`, secret = `VOICE_SHIM_TOKEN`.
- **Voice**: custom ElevenLabs voice (see Phase D).
- **STT**: Scribe v2, language `en`.
- **Turn detection**: ElevenLabs VAD defaults, barge-in enabled.
- **System prompt**: identity only — the delivery rules and stage brief are injected by the shim, so they can be edited mid-pitch without touching the agent.
- **Tools**: optional. Pantheon MCP on `:8010` can be attached if a second funnel is opened, enabling on-stage actions ("pull up the pipeline numbers").

### Phase D — the voice

Three routes: design one from a description (fast, no sample needed), instant-clone
from 30 seconds of clean audio, or pick a preset. Voice design via API keeps the
whole setup reproducible in code.

### Phase E — demo surface

- **In person**: browser widget or share link on the laptop, mic and speakers. Simplest, best audio.
- **Virtual call**: needs a virtual audio device on the demo laptop (BlackHole on macOS, VB-Cable on Windows, PipeWire null sink on Linux) to present Hermes' voice to Zoom/Meet as a microphone.

### Phase F — stage brief

Put the live pitch context in a file and point `VOICE_BRIEF_FILE` at it. It is
re-read every turn, so notes can be edited during the meeting and Hermes picks them
up on his next reply.

---

## Interaction notes for the demo

- Hermes answers in 1–3 spoken sentences by design. "Go deeper" is a deliberate turn, not the default.
- Barge-in works: interrupting stops the current response.
- Filler phrases are rotated so repeated turns do not sound robotic.
- If the gateway fails or exceeds `TOTAL_WAIT`, the shim speaks a graceful line rather than going silent.
- Openers to use on stage: "Hermes, what do you remember about this firm?" and "Hermes, what would you do differently than an agency here?" — both exercise memory and reasoning live.

---

## Tuning the 3–5 second answer latency

The filler hides it, but the real number can come down:

1. **Lighter profile.** A dedicated Hermes profile with a tight persona and tools disabled should cut the prompt dramatically. Cost: loses Pantheon tools.
2. **Prompt caching.** The upstream provider caches repeated prefixes; keep the injected system prompt byte-stable so it caches.
3. **Model route alias.** `model_routes` in the gateway config can map an alias to a faster model for voice while leaving the full agent for deep work.

Measure first, then change one thing at a time.
