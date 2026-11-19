#!/usr/bin/env python3
"""Hermes Voice LLM — OpenAI-compatible Custom LLM bridge for ElevenLabs Agents.

ElevenLabs' Conversational AI platform can point an agent at any OpenAI-compatible
streaming endpoint ("Custom LLM"). This service is that endpoint, but it is not a
thin proxy: it exists to hide the ~2.4s time-to-first-token of a full Hermes agent
turn behind instant speech.

Why the filler matters
----------------------
Measured on this box: a cold Hermes turn takes ~7.0s to first token, a warm one
~2.4s. Silence that long reads as a broken demo. ElevenLabs' own docs prescribe
"buffer words" for slow LLMs — an immediate chunk ending in an ellipsis, then the
real content, so TTS keeps prosody while the answer is still being generated.

So: emit a rotating acknowledgement chunk within milliseconds, call Hermes in
parallel, then stream Hermes' deltas through. Perceived time-to-first-audio lands
around 300-500ms while the real answer arrives underneath it.

Turn structure
--------------
ElevenLabs sends the full transcript every turn. Forwarding that to Hermes would
double history on both sides, so only the latest user utterance is sent, scoped by
``X-Hermes-Session-Key`` — Hermes keeps the conversation in its own state.db.

Delivery rules are injected per-turn as an ephemeral system prompt, so the words
that come back are already spoken-word shaped (short, no markdown, no lists).

Endpoints
---------
    POST /v1/chat/completions   streaming SSE, OpenAI Chat Completions shape
    GET  /v1/models             advertises the configured model name
    GET  /health                liveness + config summary (no secrets)

Environment
-----------
    HERMES_API_URL      default http://127.0.0.1:8650/v1/chat/completions
    HERMES_API_KEY      gateway API_SERVER_KEY (required)
    HERMES_MODEL        model alias sent upstream (default "hermes")
    VOICE_SHIM_TOKEN    optional bearer this shim requires from ElevenLabs
    VOICE_SHIM_PORT     default 8651
    VOICE_SESSION_KEY   default "voice-demo" (prefix for the Hermes session key)
    FIRST_TOKEN_WAIT    seconds before an extra filler is spoken (default 6.0)
    TOTAL_WAIT          seconds before giving up gracefully (default 25.0)
    VOICE_BRIEF_FILE    optional file whose text is injected as stage context
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

LOG = logging.getLogger("hermes_voice_llm")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)

HERMES_API_URL = os.getenv("HERMES_API_URL", "http://127.0.0.1:8650/v1/chat/completions")
HERMES_API_KEY = os.getenv("HERMES_API_KEY", "")
HERMES_MODEL = os.getenv("HERMES_MODEL", "hermes")
VOICE_SHIM_TOKEN = os.getenv("VOICE_SHIM_TOKEN", "")
VOICE_SHIM_PORT = int(os.getenv("VOICE_SHIM_PORT", "8651"))
VOICE_SESSION_KEY = os.getenv("VOICE_SESSION_KEY", "voice-demo")
FIRST_TOKEN_WAIT = float(os.getenv("FIRST_TOKEN_WAIT", "6.0"))
TOTAL_WAIT = float(os.getenv("TOTAL_WAIT", "25.0"))
VOICE_BRIEF_FILE = os.getenv("VOICE_BRIEF_FILE", "")

# Rotating openers. Each ends mid-thought so ElevenLabs' TTS keeps prosody and the
# real answer drops in seamlessly. Deliberately short — a long filler draws attention
# to itself, which is the opposite of the goal.
FILLERS: tuple[str, ...] = (
    "Right, so... ",
    "Okay, here's the thing... ",
    "So look... ",
    "Hold on, let me pull that up... ",
    "Yeah, good question... ",
    "Alright, so... ",
)

# conversation id -> Hermes session id. The gateway fingerprints a session from the
# system prompt plus the FIRST user message, and this shim only forwards the newest
# utterance -- so without an explicit id every turn would land in a fresh session and
# Hermes would forget the pitch it is co-presenting. Captured from the response
# header on turn one, replayed afterwards.
_SESSION_IDS: dict[str, str] = {}

# Spoken when Hermes fails or times out. Never leave dead air on stage.
FALLBACK_LINES: tuple[str, ...] = (
    "I'm losing that thread for a second — give me the follow-up and I'll get it.",
    "That one's not coming back clean in my head, ask me again in a second.",
)

# Turns anything Hermes emits into something a voice should say out loud.
_MD_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"```.*?```", re.S), " "),                  # fenced code
    (re.compile(r"`([^`]*)`"), r"\1"),                      # inline code
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), " "),             # images
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),          # links -> label
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.M), ""),           # headings
    (re.compile(r"(\*\*|__|\*|_)"), ""),                    # emphasis
    (re.compile(r"^\s*[-*+]\s+", re.M), ""),                # bullets
    (re.compile(r"^\s*>\s?", re.M), ""),                    # quotes
    (re.compile(r"https?://\S+"), " "),                     # bare urls
    (re.compile(r"\|\s*"), " "),                            # table pipes
    # Emoji and pictographs only. Stripping the whole non-ASCII range would
    # mangle names and accented characters during a live pitch.
    (re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]"), ""),
)

VOICE_RULES = (
    "You are speaking out loud in a live product pitch. Your reply is turned into "
    "audio, so: 1 to 3 short sentences, under 40 words total. No markdown, no bullet "
    "lists, no code, no emoji, no URLs, no headings. Speak like a confident person "
    "across the table, not like a document. Never narrate what you are doing. If a "
    "question needs a long answer, give the headline and offer to go deeper."
)


def spoken(text: str) -> str:
    """Strip formatting that TTS would otherwise read literally.

    Whitespace is preserved deliberately. Hermes streams token-level deltas, so a
    delta like ``" retainer"`` carries its leading space; stripping it per-delta
    would weld neighbouring words together and TTS would pronounce "becausean
    agency". Interior runs collapse, edges survive, and the caller strips once at
    the end of the utterance.
    """
    if not text:
        return text
    leading = " " if text[0].isspace() else ""
    trailing = " " if text[-1].isspace() else ""
    for pattern, repl in _MD_PATTERNS:
        text = pattern.sub(repl, text)
    text = re.sub(r"\s+", " ", text).strip(" \t\n\r")
    if not text:
        return ""
    return leading + text + trailing


def brief_text() -> str:
    """Optional stage context from disk, re-read each turn so it can be edited live."""
    if not VOICE_BRIEF_FILE:
        return ""
    try:
        return Path(VOICE_BRIEF_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def last_user_message(messages: Iterable[dict[str, Any]]) -> str:
    """Pull the newest user utterance out of the ElevenLabs transcript."""
    for message in reversed(list(messages or [])):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            if content.strip():
                return content.strip()
        elif isinstance(content, list):
            parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") in (None, "text")
            ]
            joined = " ".join(p for p in parts if p).strip()
            if joined:
                return joined
    return ""


def chunk(completion_id: str, model: str, delta: dict[str, Any],
          finish: str | None = None) -> str:
    """One OpenAI-shaped SSE data frame."""
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def error_frame(completion_id: str, message: str) -> str:
    """Surface an upstream problem without breaking the SSE contract."""
    LOG.warning("upstream error surfaced to client: %s", message)
    return chunk(completion_id, HERMES_MODEL, {"content": spoken(message)})


async def hermes_deltas(client: httpx.AsyncClient, user_text: str,
                        session_key: str, conversation: str) -> AsyncIterator[str]:
    """Stream content deltas from the Hermes gateway."""
    system_parts = [VOICE_RULES]
    brief = brief_text()
    if brief:
        system_parts.append("Live context for this pitch:\n" + brief)

    body = {
        "model": HERMES_MODEL,
        "stream": True,
        "messages": [
            {"role": "system", "content": "\n\n".join(system_parts)},
            {"role": "user", "content": user_text},
        ],
    }
    headers = {
        "Authorization": f"Bearer {HERMES_API_KEY}",
        "Content-Type": "application/json",
        "X-Hermes-Session-Key": session_key,
    }
    known_session = _SESSION_IDS.get(conversation)
    if known_session:
        # Continuation: the gateway loads history from state.db for this id.
        headers["X-Hermes-Session-Id"] = known_session

    async with client.stream("POST", HERMES_API_URL, json=body, headers=headers,
                             timeout=httpx.Timeout(TOTAL_WAIT, connect=5.0)) as response:
        if response.status_code != 200:
            detail = (await response.aread()).decode("utf-8", "replace")[:300]
            raise RuntimeError(f"Hermes returned {response.status_code}: {detail}")

        issued = response.headers.get("x-hermes-session-id", "").strip()
        if issued and _SESSION_IDS.get(conversation) != issued:
            _SESSION_IDS[conversation] = issued
            LOG.info("conversation %s bound to Hermes session %s", conversation, issued)

        async for line in response.aiter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                continue
            for choice in parsed.get("choices") or []:
                text = (choice.get("delta") or {}).get("content")
                if text:
                    yield text


async def sse_stream(body: dict[str, Any], session_key: str,
                     conversation: str = "") -> AsyncIterator[str]:
    """Filler first, real answer behind it, graceful exit either way."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    user_text = last_user_message(body.get("messages") or [])

    yield chunk(completion_id, HERMES_MODEL, {"role": "assistant"})

    if not user_text:
        yield chunk(completion_id, HERMES_MODEL,
                    {"content": "I didn't catch that one — say it again?"}, "stop")
        yield "data: [DONE]\n\n"
        return

    # Instant audio so the room never hears silence.
    yield chunk(completion_id, HERMES_MODEL, {"content": FILLERS[0]})
    started = time.monotonic()
    filler_index = 1
    emitted = False

    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def pump() -> None:
        try:
            async with httpx.AsyncClient() as client:
                async for delta in hermes_deltas(client, user_text, session_key, conversation):
                    await queue.put(delta)
        except Exception as exc:                     # network, timeout, bad status
            await queue.put(exc)
        finally:
            await queue.put(None)

    task = asyncio.create_task(pump())
    try:
        while True:
            if time.monotonic() - started > TOTAL_WAIT:
                LOG.warning("total wait exceeded (%.1fs) for session %s",
                            TOTAL_WAIT, session_key)
                yield chunk(completion_id, HERMES_MODEL,
                            {"content": " " + FALLBACK_LINES[0]})
                break

            try:
                item = await asyncio.wait_for(queue.get(), timeout=FIRST_TOKEN_WAIT)
            except asyncio.TimeoutError:
                # Still thinking. Keep the voice moving instead of going quiet.
                if not emitted:
                    yield chunk(completion_id, HERMES_MODEL,
                                {"content": FILLERS[filler_index % len(FILLERS)]})
                    filler_index += 1
                continue

            if item is None:
                break
            if isinstance(item, Exception):
                yield chunk(completion_id, HERMES_MODEL,
                            {"content": " " + spoken(FALLBACK_LINES[0])})
                LOG.warning("turn aborted: %s", item)
                break

            text = spoken(item)
            if text:
                emitted = True
                yield chunk(completion_id, HERMES_MODEL, {"content": text})
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        yield chunk(completion_id, HERMES_MODEL, {}, "stop")
        yield "data: [DONE]\n\n"


app = FastAPI(title="Hermes Voice LLM", version="1.0.0")


def authorized(request: Request) -> bool:
    """Bearer check matching what ElevenLabs sends for a Custom LLM secret."""
    if not VOICE_SHIM_TOKEN:
        return True
    header = request.headers.get("authorization", "")
    return header.removeprefix("Bearer ").strip() == VOICE_SHIM_TOKEN


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "upstream": HERMES_API_URL,
        "model": HERMES_MODEL,
        "auth_required": bool(VOICE_SHIM_TOKEN),
        "brief_loaded": bool(brief_text()),
        "first_token_wait_s": FIRST_TOKEN_WAIT,
        "total_wait_s": TOTAL_WAIT,
    }


@app.get("/voice/sessions")
async def voice_sessions() -> dict[str, Any]:
    """Which ElevenLabs conversation is bound to which Hermes session."""
    return {"sessions": dict(_SESSION_IDS)}


@app.get("/v1/models")
async def models() -> dict[str, Any]:
    return {"object": "list", "data": [
        {"id": HERMES_MODEL, "object": "model", "owned_by": "pantheon"},
    ]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    if not authorized(request):
        return JSONResponse({"error": {"message": "invalid shim token",
                                       "type": "auth_error"}}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": {"message": "body must be JSON",
                                       "type": "invalid_request_error"}}, status_code=400)

    # One Hermes session per ElevenLabs conversation keeps cross-turn memory intact.
    conversation = (
        request.headers.get("x-eleven-conversation-id")
        or str(body.get("user") or "")
        or request.headers.get("x-conversation-id", "")
    )
    session_key = f"{VOICE_SESSION_KEY}-{conversation}" if conversation else VOICE_SESSION_KEY

    if not body.get("stream"):
        # Non-streaming callers get the same turn, collected.
        parts: list[str] = []
        async for frame in sse_stream(body, session_key, conversation):
            if not frame.startswith("data: {"):
                continue
            try:
                payload = json.loads(frame[6:])
            except json.JSONDecodeError:
                continue
            for choice in payload.get("choices") or []:
                piece = (choice.get("delta") or {}).get("content")
                if piece:
                    parts.append(piece)
        return JSONResponse({
            "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": HERMES_MODEL,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant",
                          "content": re.sub(r"\s+", " ", "".join(parts)).strip()}}],
        })

    return StreamingResponse(
        sse_stream(body, session_key, conversation),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=VOICE_SHIM_PORT, log_level="info")
